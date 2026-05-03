# Pod / ReplicaSet / Deployment — 자동 복구와 롤링 업데이트

> **Phase**: 1 — Kubernetes 기본기
> **소요 시간**: 3–4시간 (Phase 0 이미지를 minikube에 로드하는 시간 포함)
> **선수 학습**:
> - [Phase 1 / 01-cluster-setup — minikube 설치와 첫 Pod](../01-cluster-setup/lesson.md)
> - [Phase 0 / 01-docker-fastapi-model — Docker로 분류 모델 컨테이너화](../../phase-0-docker-review/01-docker-fastapi-model/lesson.md)

## 학습 목표

이 챕터를 마치면 다음을 할 수 있습니다.

- Pod, ReplicaSet, Deployment의 **포함 관계**를 그림으로 그리고, 각자가 보장하는 것(과 보장하지 못하는 것)을 ML 모델 서빙 관점에서 설명합니다.
- Pod 단독은 노드 장애·삭제 시 자동 복구되지 않는 반면, ReplicaSet은 desired replicas로 끊임없이 수렴함을 `kubectl delete pod`로 직접 관찰합니다.
- `kubectl scale`과 매니페스트의 `replicas` 수정, 두 가지 스케일 방법의 차이(즉시성 vs GitOps 선언성)를 설명하고 상황에 맞게 선택합니다.
- Deployment의 `RollingUpdate` 전략(`maxSurge`/`maxUnavailable`)을 이해하고, sentiment-api 이미지를 v1 → v2로 무중단 교체한 뒤 `kubectl rollout undo`로 롤백합니다.
- `kubectl get rs` / `kubectl get pods -l app=...` / `kubectl rollout status`/`history` 셋으로 새/구 ReplicaSet의 분포와 롤아웃 진행 상태를 진단합니다.

## 왜 ML 엔지니어에게 필요한가

이전 토픽에서 띄운 첫 Pod은 `kubectl delete pod first-pod` 한 줄이면 그대로 사라집니다. ML 모델 서빙은 **긴 입력 토큰으로 인한 OOM, 노드 디스크 압박, 모델 v1.0.3 → v1.0.4 같은 잦은 교체**가 일상이므로 Pod 단독으로는 단 하루도 운영에 못 올라갑니다. K8s는 이 문제를 풀기 위해 Pod 위에 **ReplicaSet(원하는 복제본 수를 유지하는 컨트롤 루프)** 을 두고, 그 위에 다시 **Deployment(템플릿이 바뀌면 새 ReplicaSet을 만들어 점진적으로 교체)** 라는 2단 구조를 사용합니다. 이 토픽에서 Phase 0의 sentiment-api 이미지를 바로 이 Deployment에 올려, 죽이면 살아나고·`scale`로 늘어나고·`set image`로 무중단 교체되는 모습을 직접 손으로 확인합니다. 여기서 익힌 매니페스트는 03 토픽의 Service, 04 토픽의 본격 분류 모델 배포, 그리고 Phase 2의 ConfigMap·PVC, Phase 3의 HPA로 그대로 진화합니다.

## 1. 핵심 개념

### 1-1. Pod 단독의 한계 — 왜 Pod을 직접 띄우면 안 되는가

Pod의 `restartPolicy: Always`는 **같은 노드 위에서 컨테이너가 죽었을 때만** 재시작해 줍니다. Pod 자체가 누군가에게 삭제되거나, 노드 자체가 죽으면 그 Pod은 영원히 사라집니다.

```
Pod 단독                                ReplicaSet
─────────                                ─────────
[Pod] ── kubectl delete pod ──→  ✗     [Pod] ── kubectl delete pod ──→  ✗
                                                                       │
                                                                       ▼
                                                              "desired=N인데
                                                               현재 N-1이네?"
                                                                       │
                                                                       ▼
                                                                    [새 Pod] ✓
```

매니페스트 한 줄로 비교해 보면 차이가 명확합니다.

```yaml
# pod-direct.yaml — 단독 Pod
apiVersion: v1
kind: Pod
spec:
  containers: [...]   # 죽으면 끝
```

```yaml
# replicaset.yaml — ReplicaSet
apiVersion: apps/v1
kind: ReplicaSet
spec:
  replicas: 2         # 이 수만큼은 항상 떠 있어야 함
  selector: {...}
  template: {...}     # 부족하면 이 템플릿으로 새로 찍어냅니다
```

본 토픽 실습 2단계에서 단독 Pod을 직접 만들고 `kubectl delete pod`로 지워, "사라지고 끝"임을 눈으로 확인합니다.

### 1-2. ReplicaSet — 원하는 Pod 개수를 보장하는 컨트롤 루프

ReplicaSet은 컨트롤러입니다. 사용자가 적은 desired replicas와 selector를 보고, **매 순간 selector에 맞는 Pod을 세어 desired보다 적으면 만들고, 많으면 지웁니다**. 이걸 control loop라고 부릅니다.

> 📌 **실무 메모**: ReplicaSet을 직접 매니페스트로 만드는 일은 거의 없습니다. Deployment가 자기 안에 ReplicaSet을 자동으로 만들어 관리하기 때문입니다. 본 토픽에서 ReplicaSet을 직접 만드는 이유는 **self-healing이라는 메커니즘 자체**를 한 번 눈으로 보기 위함입니다.

핵심은 **selector와 template label이 정확히 일치**해야 한다는 점입니다. 한 글자라도 어긋나면 ReplicaSet은 자기가 만든 Pod을 자기 selector로 못 잡아, 영원히 새 Pod을 무한히 만들어 냅니다.

```yaml
# replicaset.yaml — selector ↔ template label 짝
spec:
  selector:
    matchLabels:
      app: sentiment-api
      controller: replicaset      # ← 이 두 줄과
  template:
    metadata:
      labels:
        app: sentiment-api
        controller: replicaset    # ← 이 두 줄이 정확히 같아야 합니다
```

진단 명령은 `kubectl get rs`로 한 줄 상태를 봅니다.

```
NAME                DESIRED   CURRENT   READY   AGE
sentiment-api-rs    2         2         2       45s
```

`DESIRED`(원하는 수) = `CURRENT`(실제 만든 수) = `READY`(준비 완료된 수)가 같으면 정상 수렴 상태입니다.

### 1-3. Deployment — ReplicaSet 위의 "버전 매니저"

Deployment는 자기 안에 항상 **Pod 템플릿**을 갖고 있고, 이 템플릿이 바뀔 때마다 **새 ReplicaSet을 하나 더 만들어** 점진적으로 교체합니다. 이전 ReplicaSet은 `replicas=0`으로 줄어든 채 남아 있어, `kubectl rollout undo`로 즉시 롤백할 수 있습니다.

```
시간 →

t0  Deployment(v1)
    └─ ReplicaSet-A (v1)  [Pod, Pod, Pod]   replicas=3

t1  kubectl set image ... =sentiment-api:v2
    Deployment(v2)
    ├─ ReplicaSet-A (v1)  [Pod, Pod]        replicas=2  ← 줄어드는 중
    └─ ReplicaSet-B (v2)  [Pod]             replicas=1  ← 늘어나는 중

t2  Deployment(v2)
    ├─ ReplicaSet-A (v1)  [        ]        replicas=0  ← 0으로 줄었지만 history에 남음
    └─ ReplicaSet-B (v2)  [Pod, Pod, Pod]   replicas=3
```

핵심 매니페스트 4영역만 보면 다음과 같습니다.

```yaml
# deployment-v1.yaml — 메인 Deployment
spec:
  replicas: 3                       # 원하는 Pod 수
  revisionHistoryLimit: 5           # 과거 RS 5개까지 보관 (= 5단계 전까지 롤백 가능)
  selector:
    matchLabels: {app: sentiment-api}
  template:
    metadata:
      labels: {app: sentiment-api}  # selector와 정확히 일치
    spec:
      containers:
        - name: app
          image: sentiment-api:v1   # 이 줄이 바뀌면 → 새 ReplicaSet 생성 → 롤아웃 시작
          env:
            - name: APP_VERSION
              value: "v1"
```

진단 명령은 한 줄 더 추가해서 사용합니다.

```bash
kubectl rollout status deployment/sentiment-api    # 롤아웃이 끝났는지 ('successfully rolled out' 메시지)
kubectl rollout history deployment/sentiment-api   # 지금까지의 REVISION 목록
kubectl get rs -l app=sentiment-api                # 현재 떠 있는 ReplicaSet들
```

### 1-4. 스케일 — 매니페스트 vs 명령형, 두 갈래

레플리카 수를 바꾸는 방법은 두 가지이며, 둘은 **운영 철학이 다릅니다**.

| 방식 | 명령 예시 | 장점 | 단점·주의 |
|------|-----------|------|-----------|
| 명령형 | `kubectl scale deployment/sentiment-api --replicas=5` | 즉시 반영, 한 줄 | 매니페스트의 `replicas`는 그대로라 다음 `kubectl apply` 때 원래 값으로 회귀 |
| 선언형 | 매니페스트 `replicas: 5`로 수정 후 `kubectl apply -f ...` | GitOps 친화 (git 이력에 남음) | 한 글자 고치고 commit + apply 두 단계 |

ML 운영에서는 **트래픽 spike에 대한 즉시 대응은 `kubectl scale`(혹은 Phase 3의 HPA)**, **정상 운영의 baseline은 매니페스트 + GitOps**로 관리하는 것이 일반적입니다. 본 토픽 실습 5단계에서 두 방식을 모두 해 보고 회귀 현상을 직접 확인합니다.

### 1-5. 롤링 업데이트 전략 — `maxSurge` / `maxUnavailable`

Deployment의 기본 전략은 `RollingUpdate`이며, 두 값으로 교체 속도를 제어합니다.

- **maxSurge**: 교체 중 동시에 띄울 수 있는 **추가 Pod 수**. (replicas 기준 정수 또는 %)
- **maxUnavailable**: 교체 중 잠시 사라져도 되는 **Pod 수**. (replicas 기준 정수 또는 %)

`replicas=3` 기준 4가지 조합과 ML 메모리 관점 코멘트:

| maxSurge | maxUnavailable | 동시에 떠 있는 Pod 수 | 가용 Pod 수 (최소) | ML 메모리 관점 코멘트 |
|---------:|---------------:|---------------------:|-------------------:|---------------------|
| 1 | 0 | 최대 4 | 3 | **무중단 우선**. 모델 메모리 600Mi × 4 = 2.4Gi 필요. SLA가 중요한 모델 서빙의 추천값. |
| 0 | 1 | 최대 3 | 2 | **메모리 우선**. capacity가 -33% 깎이는 동안 교체. 노드 RAM이 빠듯할 때. |
| 25% | 25% | 최대 4 | 2 | K8s 기본값. 일반 웹앱에 안전하나 ML 서빙엔 약간 보수적. |
| 3 | 0 | 최대 6 | 3 | **즉시 두 배**. 메모리 +100% 위험. 노드가 충분할 때만. |

매니페스트 표현은 다음 6줄입니다.

```yaml
# deployment-rolling.yaml — 발췌
spec:
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
  minReadySeconds: 10                # Ready 후 10초 안정화 확인 후에야 다음 교체
  progressDeadlineSeconds: 300       # 5분 안에 못 끝내면 progress=False (실패로 간주)
```

본 토픽 실습 7단계에서 기본값과 명시판을 비교해, 동시에 떠 있는 Pod 수가 어떻게 달라지는지 `kubectl get pods -w`로 관찰합니다.

## 2. 실습 — 핵심 흐름 5단계

상세 단계와 예상 출력은 [labs/README.md](labs/README.md)를 따라갑니다. 여기서는 흐름만 짚습니다.

### 2-1. 사전 준비 — Phase 0 이미지를 minikube에 로드

```bash
# Phase 0에서 빌드한 이미지를 v1/v2 두 태그로 재태그 (같은 이미지의 다른 이름)
docker tag sentiment-api:multi sentiment-api:v1
docker tag sentiment-api:multi sentiment-api:v2

# minikube 내부 docker 데몬으로 이미지 전송 (첫 회 2–4분, 이후 변경분만)
minikube image load sentiment-api:v1
minikube image load sentiment-api:v2
```

> 💡 **팁**: 본 토픽에서는 `APP_VERSION` 환경변수만 v1/v2로 다르게 줘서 `/ready` 응답으로 구별합니다. 이미지 SHA까지 진짜 다른 두 빌드를 만들고 싶다면 Phase 0 Dockerfile에 `ARG APP_VERSION`을 추가해 두 번 빌드하는 방법도 있습니다 (lesson 더 알아보기 항목 참조).

### 2-2. Pod 단독의 한계 시연

```bash
kubectl apply -f manifests/pod-direct.yaml
kubectl delete pod pod-direct
kubectl get pod pod-direct          # → "not found" — 사라지고 끝
```

### 2-3. ReplicaSet self-healing 관찰

```bash
kubectl apply -f manifests/replicaset.yaml
kubectl get pods -l controller=replicaset -w   # 다른 터미널에서 관찰
# 별도 터미널에서 Pod 1개 삭제
POD=$(kubectl get pod -l controller=replicaset -o jsonpath='{.items[0].metadata.name}')
kubectl delete pod $POD
# → 30초 안에 새 Pod 이름이 생기고 READY=1/1로 도달
```

### 2-4. Deployment 배포 + scale

```bash
kubectl apply -f manifests/deployment-v1.yaml
kubectl rollout status deployment/sentiment-api   # 'successfully rolled out'
kubectl get rs -l app=sentiment-api               # ReplicaSet 1개 (3/3)
kubectl scale deployment/sentiment-api --replicas=5
kubectl get pods -l app=sentiment-api             # Pod 5개 (또는 일부 Pending)
```

### 2-5. 롤링 업데이트 + 롤백

```bash
# 백그라운드 셸에서 port-forward + curl 루프 (자세한 명령은 labs 6단계)
kubectl set image deployment/sentiment-api app=sentiment-api:v2
kubectl rollout status deployment/sentiment-api   # 무중단 교체 진행
kubectl get rs -l app=sentiment-api               # 구 RS 0/0, 신 RS 3/3
# /ready 응답의 version이 v1 → 혼재 → v2로 변경되는 모습 확인 후
kubectl rollout undo deployment/sentiment-api     # v1로 롤백
```

## 3. 검증 체크리스트

다음 항목을 모두 확인했다면 이 챕터를 마쳤다고 볼 수 있습니다.

- [ ] `kubectl get deploy sentiment-api`가 `READY 3/3`을 보입니다.
- [ ] `kubectl get rs -l app=sentiment-api`가 두 개의 ReplicaSet을 보여줍니다 (구 0/0, 신 3/3).
- [ ] `kubectl rollout history deployment/sentiment-api`가 `REVISION 2` 이상을 표시합니다.
- [ ] ReplicaSet 실습에서 Pod 1개를 강제 삭제한 뒤 30초 안에 새 Pod이 `READY=1/1`에 도달합니다.
- [ ] `curl /ready` 응답의 `version` 필드가 롤아웃 중 v1 → 혼재 → v2로 변하고, `rollout undo` 후 다시 v1로 돌아옵니다.
- [ ] `kubectl scale --replicas=5` 후 5개 Pod이 모두 떠 있거나, 일부 Pending이라면 `describe`에 `Insufficient memory` 메시지가 명확히 보입니다.

## 4. 정리

```bash
# 본 토픽에서 만든 리소스 모두 삭제
kubectl delete -f manifests/deployment-rolling.yaml --ignore-not-found
kubectl delete -f manifests/deployment-v1.yaml --ignore-not-found
kubectl delete -f manifests/replicaset.yaml --ignore-not-found
kubectl delete -f manifests/pod-direct.yaml --ignore-not-found

# minikube는 다음 토픽(03-service-networking)에서 그대로 사용하므로 stop만 합니다.
minikube stop
```

이미지(`sentiment-api:v1`, `:v2`)는 다음 토픽에서도 그대로 쓰므로 `minikube image rm`을 하지 않습니다.

## 🚨 자주 하는 실수

1. **`selector`와 `template.metadata.labels` 불일치로 Pod이 무한 생성됨** — `selector.matchLabels.app: sentiment-api`인데 `template.metadata.labels.app: sentiment`처럼 한 글자만 빠지면, Deployment/ReplicaSet은 자기가 만든 Pod을 자기 selector로 못 잡아 영원히 새 Pod을 만들어 냅니다. 게다가 **selector 필드는 immutable**이라 한번 잘못 만든 Deployment는 수정으로 못 고치고 `kubectl delete deploy ...` 후 다시 만들어야 합니다. 매니페스트에서 selector와 template label 짝을 항상 같이 보는 습관이 중요합니다.
2. **`kubectl scale`로 늘렸는데 다음 `kubectl apply`에서 다시 줄어듦** — 명령형 `scale`은 클러스터의 현재 replicas만 바꿀 뿐 매니페스트 파일은 그대로 둡니다. 며칠 뒤 같은 매니페스트로 `apply`하면 원래 값으로 덮어씌워집니다. 베이스라인이 정말 바뀐 거면 매니페스트의 `replicas`도 같이 수정해 commit해야 합니다 (GitOps 관점). 임시 spike 대응은 `scale`, 정상 운영 baseline은 매니페스트가 정석입니다.
3. **`imagePullPolicy: Always`인 채 `minikube image load`만 한 이미지로 `ImagePullBackOff`** — 로컬에 `minikube image load`로 넣은 이미지는 외부 레지스트리에 없으므로, kubelet이 매번 풀하려고 하면 실패합니다. 학습 환경에서는 매니페스트에 `imagePullPolicy: IfNotPresent`를 명시해, "노드에 이미지가 있으면 그대로 쓰고 없을 때만 풀"하도록 해야 합니다. 본 토픽의 모든 매니페스트는 이 옵션을 명시하고 있습니다.

## 더 알아보기

- [Kubernetes — Deployments](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/) — strategy, revisionHistoryLimit, paused 등 추가 옵션
- [Kubernetes — ReplicaSet](https://kubernetes.io/docs/concepts/workloads/controllers/replicaset/) — selector 동작, isolating Pod 등
- [Kubernetes — Performing a Rolling Update (Tutorial)](https://kubernetes.io/docs/tutorials/kubernetes-basics/update/update-intro/)
- [minikube — Pushing images](https://minikube.sigs.k8s.io/docs/handbook/pushing/) — image load 외에 docker-env, registry 등 4가지 방법

## 다음 챕터

➡️ [Phase 1 / 03-service-networking — Service 3종과 네트워킹](../03-service-networking/lesson.md) (작성 예정)
