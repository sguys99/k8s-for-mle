# Volumes & PVC — PV/PVC/StorageClass 로 모델 가중치를 한 번만 받아 영구 캐시

> **Phase**: 2 — 운영에 필요한 K8s 개념 (두 번째 토픽)
> **소요 시간**: 50–70분 (첫 모델 다운로드 30–60초 포함)
> **선수 학습**:
> - [Phase 2 / 01-configmap-secret — ConfigMap & Secret](../01-configmap-secret/lesson.md)

## 학습 목표

이 챕터를 마치면 다음을 할 수 있습니다.

- PVC 한 개([`pvc.yaml`](manifests/pvc.yaml)) 를 적용해서 minikube 의 기본 StorageClass `standard` 가 PV 를 동적으로 생성·바인딩하는 흐름을 `kubectl get pv,pvc` 와 `kubectl describe pvc` 의 Events 섹션으로 직접 관찰할 수 있습니다.
- init container([deployment.yaml](manifests/deployment.yaml) 의 `model-downloader`) 에서 HuggingFace 모델을 PVC 의 `/cache/hub` 아래에 받고, 메인 컨테이너가 같은 PVC 를 마운트한 채 환경 변수 `HF_HOME=/cache` 만 설정해 transformers 라이브러리가 자동으로 그 캐시를 재사용하게 만들 수 있습니다 — 앱 코드 수정 없이.
- `replicas: 2` 의 두 Pod 이 같은 PVC 를 공유함을 한쪽에서 만든 파일이 다른쪽에서 즉시 보이는 것으로 확인하고, `accessModes` (RWO / ROX / RWX) 의 의미를 환경별(minikube hostPath / NFS / 클라우드 CSI) 트레이드오프로 설명할 수 있습니다.
- PVC 의 라이프사이클이 Pod·Deployment 와 분리됨을 검증하고, `persistentVolumeReclaimPolicy` (`Delete` vs `Retain`) 가 PVC 삭제 시 디스크 데이터 운명을 어떻게 가르는지 운영 관점에서 설명할 수 있습니다.

## 왜 ML 엔지니어에게 필요한가

Phase 2/01 까지의 [`fastapi_app.py`](../../phase-0-docker-review/01-docker-fastapi-model/practice/fastapi_app.py) 는 Pod 가 시작될 때마다 `pipeline("text-classification", model=MODEL_NAME)` 으로 HuggingFace 에서 가중치를 다시 받습니다. roberta-base 처럼 ~500MB 짜리 모델도 `kubectl rollout restart`, HPA 의 스케일 아웃, 노드 장애 복구 등 Pod 가 재생성되는 모든 순간마다 같은 다운로드를 반복합니다. LLM 으로 넘어가면 모델 크기가 7GB · 30GB · 70GB 단위로 커지면서 다운로드 비용은 단순 "느림" 을 넘어 **HuggingFace rate limit, 사내 네트워크 대역폭, 폐쇄망(에어갭) 환경, 클러스터 비용** 의 직접 원인이 됩니다. PVC 캐시 패턴은 이 다운로드를 init container 에서 한 번만 치르고 메인 컨테이너가 디스크에서 즉시 로드하도록 만드는 K8s 표준 답이며, Phase 4 의 KServe·vLLM·Triton 매니페스트와 캡스톤의 Qdrant·LLM 서빙에서 거의 동일한 형태로 다시 등장합니다.

## 1. 핵심 개념

### 1-1. PV / PVC / StorageClass 3계층 관계

K8s 의 영구 저장소 모델은 **세 오브젝트의 분리** 로 설계되어 있습니다. 한 줄로 외우면: "사용자는 PVC 만 작성하고, 클러스터 관리자는 StorageClass 를 한 번 셋업하고, PV 는 그 사이에서 자동 생성된다."

| 오브젝트 | 누가 작성 | 역할 | 예시 |
|---------|----------|------|------|
| **StorageClass** | 클러스터 관리자 (또는 minikube/EKS/GKE 가 기본 제공) | "어떤 종류의 디스크를 어떻게 만들지" 를 정의하는 템플릿. provisioner 와 파라미터를 가짐 | minikube 의 `standard` (provisioner: `k8s.io/minikube-hostpath`), AWS EKS 의 `gp3` (provisioner: `ebs.csi.aws.com`) |
| **PVC** (PersistentVolumeClaim) | ML 엔지니어 / 앱 개발자 | "이만큼의 디스크를 이 access mode 로 달라" 는 요청. Pod 가 마운트하는 대상 | [`pvc.yaml`](manifests/pvc.yaml) 의 `model-cache` (2Gi / RWO / standard) |
| **PV** (PersistentVolume) | StorageClass 가 자동 생성 (동적) 또는 관리자가 수동 작성 (정적) | 실제 디스크 자원의 K8s 표현. 노드의 호스트 디렉토리, EBS 볼륨, NFS export 등을 가리킴 | minikube 가 `pvc-3d0a6e8f-...` 이름으로 자동 생성 |

PVC 만 작성하면 StorageClass 가 PV 를 자동으로 만들어 묶는 이 흐름이 **동적 프로비저닝** 입니다. 그래서 본 토픽의 [`pvc.yaml`](manifests/pvc.yaml) 은 단 18 줄이며, PV 매니페스트는 작성하지 않습니다.

### 1-2. 동적 프로비저닝 vs 정적 프로비저닝

| 구분 | 누가 PV 를 만드나 | 언제 쓰나 |
|------|------------------|----------|
| **동적** (본 토픽) | StorageClass 가 PVC 를 보고 자동 생성 | 일반적인 모든 경우. minikube 의 `standard`, 클라우드의 기본 CSI 가 자동 처리 |
| **정적** | 관리자가 PV 매니페스트를 미리 작성 | 외부에 이미 있는 NFS export, 미리 만든 EBS 볼륨, 특수한 lustre / weka 같은 HPC 스토리지 연결 |

운영에서 정적 프로비저닝을 만나는 가장 흔한 경우는 **이미 있는 학습 데이터 (수 TB 의 ImageNet, 사내 데이터레이크) 를 NFS export 로 PV 에 직접 매핑** 하는 시나리오입니다. 본 토픽은 모델 캐시 (~수백 MB) 만 다루므로 동적만 사용합니다.

### 1-3. accessModes — RWO / ROX / RWX 와 환경별 한계

PVC 의 `accessModes` 는 **여러 노드의 여러 Pod 이 같은 PV 를 어떻게 마운트할 수 있는가** 를 정의합니다. 이름이 헷갈리니 표로 정리합니다.

| accessMode | 약어 | 의미 | minikube hostPath | NFS / EFS / CephFS | AWS EBS / 클라우드 블록 스토리지 |
|------------|------|------|-------------------|---------------------|------------------------------|
| ReadWriteOnce | **RWO** | 한 노드의 여러 Pod 가 함께 읽기/쓰기 | ✅ (본 토픽이 사용) | ✅ | ✅ |
| ReadOnlyMany | **ROX** | 여러 노드의 여러 Pod 가 함께 읽기만 | ❌ | ✅ | ❌ |
| ReadWriteMany | **RWX** | 여러 노드의 여러 Pod 가 함께 읽기/쓰기 | ❌ | ✅ | ❌ |
| ReadWriteOncePod (1.22+) | RWOP | 단 하나의 Pod 만 마운트 | ✅ | ✅ | ✅ |

**가장 흔한 오해**: "RWO 는 Pod 한 개만 마운트할 수 있다." 사실은 **노드 한 개 안의 Pod 들** 은 RWO 도 같이 마운트할 수 있습니다. 본 토픽의 `replicas: 2` 가 같은 PVC 를 공유하는 시연 (lab 7) 이 정확히 그 동작입니다.

ML 워크로드에서의 일반적 선택 기준은:

- **모델 가중치 캐시** (한 번 쓰고 여러 Pod 이 읽음) → 단일 노드면 RWO 충분, 멀티 노드면 ROX 또는 RWX 필요
- **학습 체크포인트** (여러 노드의 분산 학습 워커가 동시 쓰기) → RWX 필수 → NFS / EFS / Lustre / WekaFS
- **벡터 DB / 데이터베이스** → RWO + StatefulSet (Pod 마다 자기 PVC, lab 7 의 RWO 공유와는 다른 패턴)

### 1-4. emptyDir vs PVC — Pod 종료 시 데이터 운명

학습자가 처음 헷갈리는 지점입니다. K8s 의 "볼륨" 에는 PVC 외에도 `emptyDir`, `hostPath`, `configMap`, `secret`, `downwardAPI` 등 여러 종류가 있는데, 데이터 영속성 관점에서 가장 중요한 비교는 emptyDir 과 PVC 입니다.

| 볼륨 종류 | 데이터 유지 범위 | 용도 |
|----------|-----------------|------|
| `emptyDir` | **Pod 의 수명** — Pod 가 죽으면 데이터도 사라짐. 다만 컨테이너 재시작 (Pod 는 살아있음) 에는 살아남음 | 임시 캐시, 컨테이너 간 파일 공유, Pod 내부의 sidecar 통신 |
| `hostPath` | 노드 디스크 — Pod 가 죽어도 디스크에 남으나, **노드가 바뀌면 데이터 안 보임**. 보안 위험 (호스트 파일시스템 노출) | 거의 쓰지 않음. minikube 같은 단일 노드 학습 환경에서만 |
| `persistentVolumeClaim` | **PVC 자체가 삭제될 때까지** — Pod 가 죽고 다시 떠도 데이터 유지, 다른 노드에 옮겨가도 (CSI 가 지원하면) 디스크가 따라옴 | 모델 가중치, 학습 데이터, 체크포인트, 데이터베이스 |

본 토픽의 lab 6 단계가 정확히 이 차이를 시연합니다 — Pod 를 강제 삭제해도 PVC 안의 모델 가중치는 살아있어 두 번째 init container 가 다운로드를 스킵합니다.

### 1-5. init container 패턴 — 모델 다운로드 → PVC 영속화

[`deployment.yaml`](manifests/deployment.yaml) 의 핵심 패턴입니다.

```yaml
spec:
  template:
    spec:
      initContainers:           # 메인 컨테이너 시작 "전" 에 순차 실행되고, 모두 성공해야 진행
        - name: model-downloader
          image: sentiment-api:v1                  # 같은 이미지 재사용 (transformers 가 이미 들어 있음)
          command: ["python", "-c"]
          args:
            - |
              import os
              from huggingface_hub import snapshot_download
              snapshot_download(repo_id=os.environ["MODEL_NAME"],
                                cache_dir=os.environ["HF_HOME"] + "/hub")
          volumeMounts:
            - { name: model-cache, mountPath: /cache }
      containers:
        - name: app
          # ... 메인 컨테이너도 같은 /cache 를 마운트 ...
          volumeMounts:
            - { name: model-cache, mountPath: /cache }
      volumes:
        - name: model-cache
          persistentVolumeClaim:
            claimName: model-cache                 # pvc.yaml 의 metadata.name
```

운영의 흐름은 거의 항상 같습니다.

1. **init container 가 무거운 다운로드를 한 번만 수행** — HuggingFace, S3, GCS, 사내 모델 레지스트리 어디든 같은 패턴
2. **메인 컨테이너는 같은 PVC 를 마운트하고 디스크에서 로드** — 앱 코드는 환경 변수(`HF_HOME`, `TRANSFORMERS_CACHE`, `MODEL_DIR`) 만 봄
3. **두 번째 기동부터 init 은 "이미 다 받았네" 를 빠르게 확인하고 종료** — `snapshot_download` / `aws s3 sync` 같은 도구는 모두 이런 idempotent 한 동작을 기본으로 함

> 💡 **운영에서 S3 로 교체할 때**: init container 의 image 와 command 만 바뀝니다.
> ```yaml
> initContainers:
>   - name: model-downloader
>     image: amazon/aws-cli:2.17.0
>     command: ["aws","s3","sync","s3://my-bucket/models/roberta/","/cache/hub/"]
>     env:
>       - { name: AWS_REGION, value: ap-northeast-2 }
>     envFrom:
>       - secretRef: { name: sentiment-api-secrets }   # AWS_ACCESS_KEY_ID, SECRET_ACCESS_KEY 자동 주입
>     volumeMounts:
>       - { name: model-cache, mountPath: /cache }
> ```
> PVC, 메인 컨테이너, accessModes 패턴은 그대로입니다.

### 1-6. reclaimPolicy — PVC 삭제 시 PV 와 디스크의 운명

`kubectl get pv` 출력의 `RECLAIM POLICY` 컬럼이 이 값입니다. PVC 가 삭제될 때 PV 와 그 디스크 데이터를 어떻게 처리할지 결정합니다.

| reclaimPolicy | PVC 삭제 시 동작 | 추천 사용처 |
|---------------|-----------------|------------|
| **Delete** (minikube 기본) | PV 삭제 + 실제 디스크 데이터까지 함께 사라짐 | 캐시처럼 재생성이 쉬운 데이터 (본 토픽의 모델 캐시) |
| **Retain** | PV 가 `Released` 상태로 남고 디스크 데이터도 보존. 다시 쓰려면 관리자가 PV 를 정리하거나 새 PVC 와 매핑 | 학습 데이터·실험 결과·DB 데이터 등 **재생성 비싼** 데이터 |
| Recycle | (Deprecated) | 사용하지 않음 |

본 토픽 [`pvc.yaml`](manifests/pvc.yaml) 의 PV 는 minikube 기본인 `Delete` 로 생성되므로, lab 8-3 단계에서 PVC 를 지우면 PV 와 디스크 데이터까지 함께 사라집니다. 운영에서 학습 데이터처럼 **다시 받기 어려운** 데이터에 PVC 를 쓸 때는, 별도로 만든 StorageClass 의 `reclaimPolicy: Retain` 으로 두거나 동적 생성된 PV 를 `kubectl patch pv ... persistentVolumeReclaimPolicy: Retain` 으로 한 번 손봐서 사고를 막습니다.

## 2. 실습 — 핵심 흐름 (8단계 요약)

자세한 명령과 예상 출력은 [labs/README.md](labs/README.md) 를 따릅니다. 여기서는 흐름과 학습 포인트만 짚습니다.

| 단계 | 핵심 동작 | 학습 포인트 |
|------|----------|-------------|
| 0 | 사전 점검 (minikube, 이미지, **`get sc` 로 기본 StorageClass 확인**, 01 잔여 정리) | StorageClass 의 `(default)` 표시가 동적 프로비저닝의 전제 |
| 1 | `kubectl apply -f manifests/pvc.yaml` → `get pv,pvc` | PVC 만 적용했는데 PV 가 자동 생성되어 `Bound` 로 천이 (동적 프로비저닝) |
| 2 | ConfigMap (HF_HOME 키 추가) + Secret 적용 | 01 패턴 그대로, 한 곳에서 정의한 `HF_HOME=/cache` 를 init/main 이 공유 |
| 3 | Deployment 적용 → `get pod -w` | STATUS 가 `Init:0/1` → `PodInitializing` → `Running` 으로 천이, 첫 다운로드 30–60초 |
| 4 | `kubectl logs <pod> -c model-downloader` | `Fetching N files` 진행률 바로 다운로드 발생 검증 |
| 5 | `kubectl exec ... -- ls /cache/hub/...` + `/ready` 응답 확인 | PVC 안에 HF 표준 캐시 구조가 저장됨, `version: v1-pvc` |
| 6 | `kubectl delete pod --all` → 새 init 로그에 `Fetching` 사라짐 | PVC 영속성 — 캐시 재사용으로 두 번째 init 은 수 초 안에 종료 |
| 7 | 두 Pod 사이 파일 공유 시연 (`echo > /cache/x` → 다른 Pod 에서 `cat /cache/x`) | RWO 도 같은 노드 안 여러 Pod 공유 가능, 멀티 노드면 RWX 필요 |
| 8 | 정리: Deployment 등 1차 삭제 → PVC 가 살아있음 확인 → PVC 별도 삭제 | PVC 라이프사이클이 Pod 와 분리됨, reclaimPolicy=Delete 의 동작 |

## 3. 검증 체크리스트

다음 항목을 모두 확인했다면 이 챕터를 마쳤다고 볼 수 있습니다.

- [ ] `kubectl get pv,pvc` 가 PVC `model-cache` 와 동적 생성된 PV 를 모두 `Bound` 로 표시함을 확인했습니다.
- [ ] Pod 의 STATUS 가 `Init:0/1` → `PodInitializing` → `Running` (1/1) 순서로 천이함을 직접 관찰했습니다.
- [ ] `kubectl logs <pod> -c model-downloader` 로 첫 다운로드 시 `Fetching N files` 진행률 바를 보았습니다.
- [ ] `kubectl exec <pod> -c app -- ls /cache/hub/` 로 `models--cardiffnlp--twitter-roberta-base-sentiment` 디렉토리가 존재함을 확인했습니다.
- [ ] `/ready` 응답의 `version` 필드가 `"v1-pvc"` 입니다 (01 의 `"v1-cm"` 와 다름).
- [ ] `kubectl delete pod --all` 후 새 Pod 의 init 로그에 `Fetching` 줄이 사라지고 즉시 `[init] done` 만 출력됨을 확인했습니다 (캐시 재사용).
- [ ] `replicas: 2` 의 두 Pod 중 한쪽에서 만든 `/cache/shared-marker.txt` 가 다른쪽에서 즉시 보임을 확인했습니다 (RWO 공유 시연).
- [ ] Deployment 삭제 후에도 `kubectl get pvc` 가 `model-cache` 를 `Bound` 로 표시함을 확인하고, 그 후 PVC 를 별도로 삭제해 PV·디스크가 함께 사라짐을 관찰했습니다.

## 4. 정리

본 토픽에서 만든 리소스를 두 단계로 삭제합니다. PVC 의 라이프사이클이 Pod / Deployment 와 분리됨을 인식하기 위함입니다.

```bash
# 1차: Deployment / Service / debug-client / ConfigMap / Secret 정리
kubectl delete -f manifests/deployment.yaml \
                -f manifests/service.yaml \
                -f manifests/debug-client.yaml \
                -f manifests/configmap.yaml \
                -f manifests/secret.yaml \
                --ignore-not-found

# 2차: PVC 가 여전히 살아있음을 확인하고 별도로 삭제
kubectl get pvc                       # → model-cache 가 Bound 로 보임
kubectl delete pvc model-cache        # PV 와 디스크 데이터까지 함께 사라짐 (reclaimPolicy=Delete)

# minikube 와 sentiment-api:v1 이미지는 다음 토픽(03-ingress) 에서 그대로 재사용하므로 stop 만 합니다.
minikube stop
```

## 🚨 자주 하는 실수

1. **PVC 가 `Pending` 인데 무한 대기** — `kubectl get pvc` 가 `Pending` 으로 멈춰 있고 `kubectl describe pvc` 의 Events 에 `no persistent volumes available` 이나 `failed to provision volume` 이 보입니다. 원인은 거의 항상 셋 중 하나입니다. ① `storageClassName` 오타 (`standerd`, `default`, 또는 클러스터에 없는 이름) — `kubectl get sc` 로 실제 클래스 이름 확인. ② `accessModes` 가 클러스터의 StorageClass 가 지원하지 않는 모드 (예: minikube hostPath 에 RWX 요청) — 1-3 표 참고. ③ 노드 디스크 공간 부족 — `kubectl describe node | grep -A5 Allocated` 로 ephemeral-storage 사용량 확인. minikube 라면 `minikube ssh -- df -h /` 로 호스트 디스크도 봅니다.

2. **init container 가 받은 파일이 메인 컨테이너에서 안 보임** — init 로그는 `[init] done` 으로 정상인데, 메인 컨테이너에서 transformers 가 다시 다운로드를 시작하거나 `kubectl exec ... -- ls /cache` 가 비어 있는 케이스입니다. 원인은 거의 항상 ① init 의 `volumeMounts.mountPath` 와 메인의 `mountPath` 가 다름 (한쪽은 `/cache`, 다른쪽은 `/data`) ② `HF_HOME` 환경 변수가 한쪽에만 설정됨 ③ `cache_dir` 인자에 `/hub` 를 빼먹어서 init 가 `/cache` 에 받았는데 라이브러리는 `/cache/hub` 를 봄. 진단은 `kubectl exec <pod> -c app -- ls -R /cache | head -30` 으로 init 가 어디에 받았는지 직접 확인하면 즉시 보입니다. 본 토픽이 단일 진실 소스(ConfigMap 의 `HF_HOME=/cache`) 패턴을 쓰는 이유가 이 실수 예방입니다.

3. **`kubectl delete pvc` 가 끝나지 않거나 PV 가 `Released` 로 남아 재사용 불가** — PVC 를 마운트한 Pod 가 살아있으면 `delete pvc` 는 finalizer 때문에 무한 대기합니다 (`kubectl get pvc -o yaml | grep finalizers`). Pod 를 먼저 모두 삭제하면 자연스럽게 진행됩니다. 또 다른 케이스: reclaimPolicy=`Retain` 으로 PV 를 만들었다면 PVC 삭제 후에도 PV 가 `Released` 상태로 남아 디스크 데이터를 보존하는데, 이 PV 를 새 PVC 와 다시 묶으려면 `kubectl edit pv <name>` 으로 `spec.claimRef` 섹션을 지워야 합니다. 운영에서 이 PV 의 디스크가 더 이상 필요 없다면 `kubectl delete pv <name>` 로 명시적 삭제 — 동적 생성된 PV 도 reclaimPolicy=`Retain` 이면 자동 삭제되지 않으므로 디스크 비용이 누적됩니다.

## 더 알아보기

- [Kubernetes — Persistent Volumes](https://kubernetes.io/docs/concepts/storage/persistent-volumes/) — PV/PVC 라이프사이클, accessModes, reclaimPolicy 의 모든 상세.
- [Kubernetes — Storage Classes](https://kubernetes.io/docs/concepts/storage/storage-classes/) — provisioner 별 파라미터 (AWS EBS gp3 / GCP PD / Azure Disk / Ceph / NFS).
- [Kubernetes — CSI Volume Cloning / Snapshots](https://kubernetes.io/docs/concepts/storage/volume-snapshots/) — 본 토픽 범위 밖이지만, 학습 체크포인트의 백업·복구를 K8s 표준으로 다루는 방법.
- [HuggingFace — Manage your cache](https://huggingface.co/docs/huggingface_hub/guides/manage-cache) — `HF_HOME`, `HF_HUB_CACHE`, `TRANSFORMERS_CACHE` 환경 변수의 우선순위와 캐시 디렉토리 구조 (`models--<org>--<repo>/blobs|snapshots/refs`) 상세.
- [minikube — CSI Hostpath Driver Add-on](https://minikube.sigs.k8s.io/docs/tutorials/volume_snapshots_and_csi/) — minikube 에서 RWX / 스냅샷을 실험해 보고 싶을 때 활성화하는 애드온.

## 다음 챕터

➡️ [Phase 2 / 03-ingress — nginx-ingress 로 외부 라우팅](../03-ingress/lesson.md) (작성 예정)

다음 토픽에서는 본 토픽까지 `kubectl exec ... -- curl http://sentiment-api/...` 로만 호출하던 모델 엔드포인트를 클러스터 외부에서 `curl http://<host>/v1/sentiment` 로 부르도록 nginx-ingress 컨트롤러를 설치하고 경로 기반 라우팅을 구성합니다. ConfigMap·Secret·PVC 매니페스트는 그대로 두고 Ingress 한 개만 추가하는 흐름이 됩니다.
