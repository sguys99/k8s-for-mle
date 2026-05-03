# Phase 2 / 02-volumes-pvc — 실습 가이드

> Phase 2/01 까지 매번 다시 다운로드되던 모델 가중치를 PVC 에 한 번만 받아 캐시하고, 재기동·복수 Pod 가 그 캐시를 공유함을 직접 검증합니다.
>
> **예상 소요 시간**: 50–70분 (첫 다운로드 30–60초 포함)
>
> **선행 조건**
> - [Phase 2 / 01-configmap-secret](../../01-configmap-secret/lesson.md) 완료
> - minikube 에 `sentiment-api:v1` 이미지가 적재되어 있어야 합니다 (Phase 1/04 lab 1단계에서 적재됨)
>
> **작업 디렉토리**
> ```bash
> cd course/phase-2-operations/02-volumes-pvc
> ```

---

## 0단계 — 사전 준비 점검

### 0-1. minikube 상태 확인

```bash
minikube status
```

```
# 예상 출력
minikube
type: Control Plane
host: Running
kubelet: Running
apiserver: Running
kubeconfig: Configured
```

`Stopped` 가 보이면 `minikube start` 로 기동합니다.

### 0-2. kubectl 컨텍스트 확인

```bash
kubectl config current-context
```

```
# 예상 출력
minikube
```

### 0-3. sentiment-api:v1 이미지 확인

```bash
minikube image ls | grep sentiment-api
```

```
# 예상 출력 (있는 경우)
docker.io/library/sentiment-api:v1
```

비어 있다면 → [Phase 1/04 lab 1단계](../../../phase-1-k8s-basics/04-serve-classification-model/labs/README.md#1단계--필요-시-phase-0-이미지를-minikube에-적재) 로 가서 다시 적재한 뒤 돌아옵니다.

### 0-4. 기본 StorageClass 확인

본 토픽에서 새로 사용하는 사전 점검입니다. PVC 가 동적으로 PV 를 생성하려면 기본 StorageClass 가 있어야 합니다.

```bash
kubectl get storageclass
```

```
# 예상 출력
NAME                 PROVISIONER                RECLAIMPOLICY   VOLUMEBINDINGMODE   ALLOWVOLUMEEXPANSION   AGE
standard (default)   k8s.io/minikube-hostpath   Delete          Immediate           false                  1d
```

`standard (default)` 가 보여야 합니다. `(default)` 표시가 없으면:
```bash
kubectl patch storageclass standard \
  -p '{"metadata":{"annotations":{"storageclass.kubernetes.io/is-default-class":"true"}}}'
```

### 0-5. 01 의 잔여 리소스 정리

01 의 정리 단계를 잘 수행했다면 비어 있습니다.

```bash
kubectl get deploy,svc,pod,cm,secret -l app=sentiment-api
```

남아 있다면 **Deployment 만** 삭제하고 시작합니다 (Service / debug-client / ConfigMap / Secret 은 본 토픽이 같은 이름으로 덮어쓰므로 멱등합니다).

```bash
kubectl delete deployment sentiment-api --ignore-not-found
```

```
# 예상 출력
deployment.apps "sentiment-api" deleted
# 또는 없었다면
# (출력 없음)
```

---

## 1단계 — PVC 생성 + Bound 천이 관찰

이번 단계의 학습 포인트는 **PVC 한 개를 만들면 StorageClass 가 자동으로 PV 를 만들어 묶어 준다(동적 프로비저닝)** 는 동작을 직접 보는 것입니다.

### 1-1. PVC 적용 직후 상태

```bash
kubectl apply -f manifests/pvc.yaml
kubectl get pv,pvc
```

```
# 예상 출력 (수 초 안에 Bound 로 천이됩니다)
NAME                                                        CAPACITY   ACCESS MODES   RECLAIM POLICY   STATUS   CLAIM                 STORAGECLASS   AGE
persistentvolume/pvc-3d0a6e8f-xxxx-xxxx-xxxx-aaaaaaaaaaaa   2Gi        RWO            Delete           Bound    default/model-cache   standard       3s

NAME                                STATUS   VOLUME                                     CAPACITY   ACCESS MODES   STORAGECLASS   AGE
persistentvolumeclaim/model-cache   Bound    pvc-3d0a6e8f-xxxx-xxxx-xxxx-aaaaaaaaaaaa   2Gi        RWO            standard       3s
```

> 💡 **무엇이 일어났나**: `pvc.yaml` 만 적용했는데 `pv` 가 함께 생겼습니다. minikube 의 `standard` StorageClass 가 PVC 의 요청(2Gi, RWO) 을 보고 노드 호스트 디렉토리(`/tmp/hostpath-provisioner/...`) 를 PV 로 만들어 PVC 와 묶은 결과입니다.

### 1-2. PVC 상세 확인

```bash
kubectl describe pvc model-cache
```

```
# 예상 출력 (발췌)
Name:          model-cache
Status:        Bound
Volume:        pvc-3d0a6e8f-xxxx-xxxx-xxxx-aaaaaaaaaaaa
Access Modes:  RWO
StorageClass:  standard
Events:
  Type    Reason                 From                                                                       Message
  ----    ------                 ----                                                                       -------
  Normal  ExternalProvisioning   persistentvolume-controller                                                Waiting for a volume to be created...
  Normal  Provisioning           k8s.io/minikube-hostpath                                                   External provisioner is provisioning volume...
  Normal  ProvisioningSucceeded  k8s.io/minikube-hostpath                                                   Successfully provisioned volume pvc-3d0a6e8f-...
```

Events 섹션에서 **Provisioning → ProvisioningSucceeded** 흐름이 보이면 동적 프로비저닝이 정상 동작한 것입니다.

> 🚨 **Pending 에서 멈춘다면**:
> - StorageClass 이름 오타 (`standerd`, `default` 등)
> - accessModes 가 hostPath 가 지원하지 않는 RWX
> - 디스크 공간 부족
> 위 셋 중 하나입니다 (lesson.md 자주 하는 실수 1번 참고).

---

## 2단계 — ConfigMap 과 Secret 적용

01 과 같은 패턴으로, 본 토픽에서는 ConfigMap 에 `HF_HOME` 키 1개가 추가되었고 `APP_VERSION` 이 `"v1-pvc"` 로 바뀌었습니다.

### 2-1. ConfigMap / Secret 적용

```bash
kubectl apply -f manifests/configmap.yaml -f manifests/secret.yaml
```

```
# 예상 출력
configmap/sentiment-api-config created
secret/sentiment-api-secrets created
```

### 2-2. HF_HOME 키가 들어있는지 확인

```bash
kubectl get cm sentiment-api-config -o jsonpath='{.data.HF_HOME}'
echo
```

```
# 예상 출력
/cache
```

`/cache` 한 곳에서 정의되어 init 와 main 컨테이너가 같은 경로를 공유합니다.

---

## 3단계 — Deployment 적용 + initContainer 단계 천이 관찰

이번 단계가 본 토픽의 가장 중요한 학습 포인트입니다. **initContainer 단계 → main 컨테이너 단계** 의 천이를 직접 보고, 첫 다운로드에 30–60초가 걸림을 측정합니다.

### 3-1. Deployment / Service / debug-client 적용

```bash
kubectl apply -f manifests/deployment.yaml -f manifests/service.yaml -f manifests/debug-client.yaml
```

```
# 예상 출력
deployment.apps/sentiment-api created
service/sentiment-api created
pod/debug-client created
```

### 3-2. Pod 상태를 watch (`-w`) 로 관찰

```bash
kubectl get pods -l app=sentiment-api -w
```

다음과 같이 단계가 천이합니다 (Ctrl+C 로 중단).

```
# 예상 출력 (시간 순서대로 같은 Pod 한 줄이 갱신됩니다)
NAME                             READY   STATUS            RESTARTS   AGE
sentiment-api-7c4d8f5c9b-abcd1   0/1     Pending           0          0s
sentiment-api-7c4d8f5c9b-abcd1   0/1     ContainerCreating 0          2s
sentiment-api-7c4d8f5c9b-abcd1   0/1     Init:0/1          0          5s    ← initContainer 실행 중 (모델 다운로드)
sentiment-api-7c4d8f5c9b-abcd1   0/1     PodInitializing   0          45s   ← init 종료, main 컨테이너 기동
sentiment-api-7c4d8f5c9b-abcd1   0/1     Running           0          50s   ← main 시작, 모델 메모리 로딩 중
sentiment-api-7c4d8f5c9b-abcd1   1/1     Running           0          70s   ← Ready (readinessProbe 통과)
```

> 💡 **`Init:0/1`** 가 본 토픽에서 처음 나타나는 STATUS 입니다. 1개 init container 중 0번째가 실행 중이라는 뜻이며, 메인 컨테이너는 init 이 완전히 끝날 때까지 시작도 하지 않습니다.

### 3-3. Rollout 완료까지 대기

```bash
kubectl rollout status deployment/sentiment-api --timeout=180s
```

```
# 예상 출력
Waiting for deployment "sentiment-api" rollout to finish: 0 of 2 updated replicas are available...
Waiting for deployment "sentiment-api" rollout to finish: 1 of 2 updated replicas are available...
deployment "sentiment-api" successfully rolled out
```

---

## 4단계 — initContainer 로그로 다운로드 검증

### 4-1. init 로그 확인 (첫 기동: 모델 다운로드)

```bash
POD=$(kubectl get pod -l app=sentiment-api -o jsonpath='{.items[0].metadata.name}')
kubectl logs $POD -c model-downloader
```

```
# 예상 출력 (모델 가중치 ~500MB 다운로드)
[init] caching cardiffnlp/twitter-roberta-base-sentiment -> /cache/hub
Fetching 7 files: 100%|██████████| 7/7 [00:35<00:00,  5.0s/file]
[init] done
```

`Fetching N files` 진행률 바가 보이면 init container 가 HuggingFace 에서 정상 다운로드한 것입니다.

### 4-2. main 컨테이너 로그도 함께 확인 (선택)

```bash
kubectl logs $POD -c app | tail -20
```

```
# 예상 출력 (모델 메모리 로딩 + uvicorn 기동)
INFO     serving: Loading model: cardiffnlp/twitter-roberta-base-sentiment
INFO     serving: Model loaded in 6.21s          ← 디스크 캐시에서 읽기 — 첫 다운로드 없음
INFO     uvicorn.access: Started server process
```

`Model loaded in N.NNs` 시간이 한 자릿수 초 단위로 짧아진 것이 PVC 캐시의 효과입니다.

---

## 5단계 — 컨테이너 내부에서 PVC 마운트 확인 + /ready 검증

### 5-1. /cache 디렉토리 내용 확인

```bash
kubectl exec $POD -c app -- ls /cache/hub
```

```
# 예상 출력
models--cardiffnlp--twitter-roberta-base-sentiment
version.txt
```

```bash
kubectl exec $POD -c app -- ls /cache/hub/models--cardiffnlp--twitter-roberta-base-sentiment/snapshots/
```

```
# 예상 출력
<commit-hash>
```

```bash
kubectl exec $POD -c app -- ls /cache/hub/models--cardiffnlp--twitter-roberta-base-sentiment/blobs/ | wc -l
```

```
# 예상 출력
7        # tokenizer, config, weights 등 7개 파일
```

PVC 안에 HuggingFace 표준 캐시 구조(`models--<org>--<repo>/blobs|snapshots/...`) 가 그대로 저장되어 있습니다.

### 5-2. /ready 응답으로 토픽 식별

```bash
kubectl exec -it debug-client -- curl -s http://sentiment-api/ready
echo
```

```
# 예상 출력
{"status":"ready","model":"cardiffnlp/twitter-roberta-base-sentiment","version":"v1-pvc"}
```

`version` 이 `"v1-pvc"` 면 본 토픽의 ConfigMap 이 정상 주입된 것입니다.

### 5-3. /predict 호출

```bash
kubectl exec -it debug-client -- curl -s -X POST http://sentiment-api/predict \
  -H 'Content-Type: application/json' \
  -d '{"text":"PVC caching saves so much download time"}'
echo
```

```
# 예상 출력
{"label":"LABEL_2","score":0.95...}
```

---

## 6단계 — Pod 삭제 → 재기동 시 캐시 재사용 확인

이번 단계가 PVC 가 주는 **실질적 가치** 를 직접 보여주는 부분입니다. Pod 가 죽어도 PVC 는 살아 있어 두 번째 init 은 **다운로드 없이 수 초만에** 끝납니다.

### 6-1. 모든 Pod 강제 삭제

```bash
kubectl delete pod -l app=sentiment-api --all
```

```
# 예상 출력
pod "sentiment-api-7c4d8f5c9b-abcd1" deleted
pod "sentiment-api-7c4d8f5c9b-efgh2" deleted
```

Deployment 의 ReplicaSet 이 새 Pod 2개를 즉시 다시 띄웁니다.

### 6-2. 새 Pod 의 init 로그 — 다운로드 없이 즉시 종료

```bash
# 새 Pod 가 Ready 가 될 때까지 짧게 기다림
sleep 15
NEW_POD=$(kubectl get pod -l app=sentiment-api -o jsonpath='{.items[0].metadata.name}')
kubectl logs $NEW_POD -c model-downloader
```

```
# 예상 출력 (Fetching 진행률 바 없음, 즉시 done)
[init] caching cardiffnlp/twitter-roberta-base-sentiment -> /cache/hub
[init] done
```

> 💡 **무엇이 달라졌나**: snapshot_download 가 캐시의 `version.txt` 와 commit hash 를 보고 "이미 다 받은 상태" 라고 판단해 1초 내에 종료합니다. 첫 기동의 30–60초 다운로드가 사라진 것입니다.

### 6-3. 전체 Ready 시간 비교 (선택)

```bash
kubectl rollout status deployment/sentiment-api --timeout=120s
kubectl get pod -l app=sentiment-api -o custom-columns=NAME:.metadata.name,READY:.status.containerStatuses[0].ready,AGE:.metadata.creationTimestamp
```

첫 기동 (3단계) 대비 새 기동의 AGE 가 절반 이하면 PVC 캐시 효과가 검증된 것입니다.

---

## 7단계 — replicas=2 의 두 Pod 이 같은 PVC 를 공유함을 확인

### 7-1. 두 Pod 이름 가져오기

```bash
PODS=($(kubectl get pod -l app=sentiment-api -o jsonpath='{.items[*].metadata.name}'))
echo "Pod 1: ${PODS[0]}"
echo "Pod 2: ${PODS[1]}"
```

```
# 예상 출력
Pod 1: sentiment-api-7c4d8f5c9b-mnop3
Pod 2: sentiment-api-7c4d8f5c9b-qrst4
```

### 7-2. 두 Pod 의 /cache/hub 내용이 같은지 확인

```bash
kubectl exec ${PODS[0]} -c app -- ls /cache/hub
kubectl exec ${PODS[1]} -c app -- ls /cache/hub
```

```
# 예상 출력 (양쪽 모두 동일)
models--cardiffnlp--twitter-roberta-base-sentiment
version.txt
```

### 7-3. 한 Pod 에서 파일을 만들고 다른 Pod 에서 보이는지 확인 (RWO 공유 시연)

```bash
kubectl exec ${PODS[0]} -c app -- sh -c 'echo "from pod 1" > /cache/shared-marker.txt'
kubectl exec ${PODS[1]} -c app -- cat /cache/shared-marker.txt
```

```
# 예상 출력
from pod 1
```

같은 PVC 를 두 Pod 가 함께 마운트하고 있어 한쪽의 쓰기가 다른쪽에서 즉시 보입니다.

> ⚠️ **운영 관점**: minikube 는 단일 노드라서 RWO PVC 도 두 Pod 가 공유할 수 있지만, **여러 노드의 Pod 가 같은 PVC 를 공유하려면 RWX 가 필요합니다** (NFS, EFS, CephFS, Azure Files 등). lesson.md 1-3 표를 참고하세요.

```bash
# 시연용 파일 정리 (선택)
kubectl exec ${PODS[0]} -c app -- rm /cache/shared-marker.txt
```

---

## 8단계 — 정리

본 토픽에서 만든 리소스를 삭제합니다. **PVC 의 라이프사이클을 인식하기 위해 두 단계로 나눕니다.**

### 8-1. 1차 정리: Deployment / Service / debug-client / ConfigMap / Secret

```bash
kubectl delete -f manifests/deployment.yaml \
                -f manifests/service.yaml \
                -f manifests/debug-client.yaml \
                -f manifests/configmap.yaml \
                -f manifests/secret.yaml \
                --ignore-not-found
```

```
# 예상 출력
deployment.apps "sentiment-api" deleted
service "sentiment-api" deleted
pod "debug-client" deleted
configmap "sentiment-api-config" deleted
secret "sentiment-api-secrets" deleted
```

### 8-2. PVC 가 여전히 살아있음을 확인

```bash
kubectl get pvc,pv
```

```
# 예상 출력
NAME                                STATUS   VOLUME                                     CAPACITY   ACCESS MODES   STORAGECLASS   AGE
persistentvolumeclaim/model-cache   Bound    pvc-3d0a6e8f-xxxx-xxxx-xxxx-aaaaaaaaaaaa   2Gi        RWO            standard       30m

NAME                                                        CAPACITY   ACCESS MODES   RECLAIM POLICY   STATUS   CLAIM                 STORAGECLASS   AGE
persistentvolume/pvc-3d0a6e8f-xxxx-xxxx-xxxx-aaaaaaaaaaaa   2Gi        RWO            Delete           Bound    default/model-cache   standard       30m
```

**PVC 는 Deployment / Pod 와 무관하게 살아 있습니다.** 이 영속성이 PVC 가 emptyDir / hostPath 와 다른 핵심 특징입니다.

### 8-3. 2차 정리: PVC 도 삭제

PVC 의 reclaimPolicy 가 `Delete` 이므로 PVC 를 삭제하면 PV 와 실제 디스크 데이터까지 함께 사라집니다.

```bash
kubectl delete pvc model-cache
kubectl get pv
```

```
# 예상 출력
persistentvolumeclaim "model-cache" deleted
No resources found
```

> 💡 **운영 패턴**: 학습 데이터·모델 가중치 같은 **재생성 비싼** 데이터는 reclaimPolicy 를 `Retain` 으로 두고 PVC 만 삭제해도 PV 와 디스크는 남도록 합니다 (lesson.md 1-6 참고).

### 8-4. minikube 종료

minikube 와 `sentiment-api:v1` 이미지는 다음 토픽(03-ingress) 에서 그대로 재사용하므로 `stop` 만 합니다.

```bash
minikube stop
```

---

## 검증 체크리스트

다음 항목을 모두 확인했다면 본 lab 을 마쳤다고 볼 수 있습니다.

- [ ] **1-1단계**: `kubectl get pv,pvc` 가 PVC `model-cache` 와 동적 생성된 PV 를 모두 `Bound` 로 표시.
- [ ] **3-2단계**: Pod 의 STATUS 가 `Init:0/1` → `PodInitializing` → `Running` (1/1) 순서로 천이함을 직접 관찰.
- [ ] **4-1단계**: 첫 init 로그에 `Fetching 7 files` 진행률 바가 보임 (실제 다운로드 발생).
- [ ] **5-1단계**: `/cache/hub/` 아래에 `models--cardiffnlp--twitter-roberta-base-sentiment` 디렉토리가 보임.
- [ ] **5-2단계**: `/ready` 응답의 `version` 필드가 `"v1-pvc"`.
- [ ] **6-2단계**: Pod 삭제 후 두 번째 init 로그에 `Fetching` 줄이 사라지고 `[init] done` 만 출력됨 (캐시 재사용).
- [ ] **7-3단계**: 한 Pod 에서 `/cache/shared-marker.txt` 를 만들면 다른 Pod 에서 즉시 보임 (RWO 공유 시연).
- [ ] **8-2단계**: Deployment 삭제 후에도 PVC 가 `Bound` 로 살아있음을 직접 관찰.

체크리스트가 모두 채워졌다면 [docs/course-plan.md](../../../../docs/course-plan.md) 의 Phase 2/02 항목 `minikube 검증` 박스를 `[x]` 로 업데이트합니다.
