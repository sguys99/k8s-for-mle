# Lab — Pod 단독 한계 → ReplicaSet self-healing → Deployment 롤링 업데이트

이 실습은 [lesson.md](../lesson.md)의 흐름을 그대로 따라, **Phase 0의 sentiment-api 이미지를 minikube 클러스터에 올려** 다음 세 가지를 손으로 확인합니다.

1. Pod을 컨트롤러 없이 직접 띄우면 `kubectl delete`로 그대로 사라진다.
2. ReplicaSet은 Pod 1개를 죽여도 즉시 새 Pod을 만들어 desired replicas를 유지한다.
3. Deployment는 이미지 태그를 v1 → v2로 바꾸면 새 ReplicaSet을 만들어 점진 교체하고, `rollout undo`로 즉시 롤백할 수 있다.

> 모든 명령은 본 디렉토리의 부모(`02-pod-deployment/`)를 기준으로 합니다. 1단계의 `minikube image load`는 첫 회 2–4분 소요됩니다.

## 0단계 — 사전 준비

### 0-1. kubectl context가 minikube를 가리키는지 확인

이전 토픽에서 회사 클러스터로 전환했다면 다시 minikube로 돌려놓습니다.

```bash
kubectl config current-context
```

**예상 출력**

```
minikube
```

`minikube`가 아니라면 다음을 실행합니다.

```bash
kubectl config use-context minikube
```

### 0-2. minikube 클러스터가 떠 있는지 확인

```bash
minikube status
```

**예상 출력 (Running 상태)**

```
minikube
type: Control Plane
host: Running
kubelet: Running
apiserver: Running
kubeconfig: Configured
```

`Stopped`로 보이면 시작합니다.

```bash
minikube start --driver=docker --memory=4g --cpus=2
```

### 0-3. Phase 0에서 빌드한 sentiment-api 이미지가 호스트 docker에 있는지 확인

```bash
docker images sentiment-api
```

**예상 출력 (둘 중 하나만 있어도 OK, 1단계에서 v1/v2로 재태그합니다)**

```
REPOSITORY      TAG       IMAGE ID       CREATED          SIZE
sentiment-api   multi     1a2b3c4d5e6f   2 hours ago      1.42GB
sentiment-api   single    7g8h9i0j1k2l   2 hours ago      3.1GB
```

> Phase 0를 건너뛴 경우엔 다음 한 줄로 빌드합니다 (첫 회 5–10분 소요).
>
> ```bash
> ( cd ../../phase-0-docker-review/01-docker-fastapi-model/practice \
>   && docker build -t sentiment-api:multi . )
> ```

## 1단계 — 이미지 v1/v2 minikube 로드

같은 이미지를 두 태그(`v1`, `v2`)로 재태그한 뒤 minikube로 전송합니다. 본 토픽에서는 v1/v2 차이를 매니페스트의 `APP_VERSION` 환경변수로만 줍니다.

### 1-1. 호스트에서 v1/v2 태그 만들기

```bash
docker tag sentiment-api:multi sentiment-api:v1
docker tag sentiment-api:multi sentiment-api:v2
docker images sentiment-api
```

**예상 출력**

```
REPOSITORY      TAG       IMAGE ID       CREATED          SIZE
sentiment-api   multi     1a2b3c4d5e6f   2 hours ago      1.42GB
sentiment-api   v1        1a2b3c4d5e6f   2 hours ago      1.42GB
sentiment-api   v2        1a2b3c4d5e6f   2 hours ago      1.42GB
```

세 태그가 같은 `IMAGE ID`를 가리키면 정상입니다 (재태그는 SHA를 안 바꿉니다).

### 1-2. minikube로 이미지 전송

> ⏱ **시간 안내**: 첫 회 한 태그당 1–2분 소요(이미지 1.4GB 전송). **도중에 Ctrl+C 금지** — 이미지 절단으로 다시 받아야 합니다.

```bash
minikube image load sentiment-api:v1
minikube image load sentiment-api:v2
```

각 명령은 진행 메시지 없이 끝나면 성공입니다 (출력이 없는 게 정상).

### 1-3. minikube 안에 이미지가 들어갔는지 확인

```bash
minikube image ls | grep sentiment-api
```

**예상 출력**

```
docker.io/library/sentiment-api:v1
docker.io/library/sentiment-api:v2
```

> 💡 **대안**: `eval $(minikube docker-env)` 후 `docker build`로 minikube 내부 docker 데몬에서 직접 빌드하면 `image load`가 필요 없습니다. 다만 Phase 0 이미지를 다시 빌드해야 합니다.

## 2단계 — Pod 단독의 한계 시연

```bash
kubectl apply --dry-run=client -f manifests/pod-direct.yaml
```

**예상 출력**

```
pod/pod-direct created (dry run)
```

실제로 띄웁니다.

```bash
kubectl apply -f manifests/pod-direct.yaml
kubectl get pod pod-direct -w
```

**예상 출력 (Ctrl+C로 종료)**

```
NAME         READY   STATUS              RESTARTS   AGE
pod-direct   0/1     ContainerCreating   0          3s
pod-direct   0/1     Running             0          8s
pod-direct   1/1     Running             0          28s    ← 모델 로드 후 Ready=1/1
```

이제 Pod을 강제로 지우고 무슨 일이 일어나는지 봅니다.

```bash
kubectl delete pod pod-direct
kubectl get pod pod-direct
```

**예상 출력**

```
pod "pod-direct" deleted
Error from server (NotFound): pods "pod-direct" not found
```

**해석**: 단독 Pod은 컨트롤러가 없어 자동 복구되지 않습니다. 사라지고 끝입니다.

## 3단계 — ReplicaSet self-healing 관찰

### 3-1. ReplicaSet 배포

```bash
kubectl apply -f manifests/replicaset.yaml
kubectl get rs sentiment-api-rs
```

**예상 출력 (모델 로드 완료 후)**

```
NAME                DESIRED   CURRENT   READY   AGE
sentiment-api-rs    2         2         2       45s
```

### 3-2. Pod 강제 삭제 → 자동 복구 관찰

**터미널 A** (관찰용, 이 명령은 Ctrl+C 전까지 계속 떠 있습니다):

```bash
kubectl get pods -l controller=replicaset -w
```

**터미널 B** (Pod 1개 삭제):

```bash
POD=$(kubectl get pod -l controller=replicaset -o jsonpath='{.items[0].metadata.name}')
echo "삭제할 Pod: $POD"
kubectl delete pod $POD
```

터미널 A의 **예상 출력 (시간 순)**

```
sentiment-api-rs-abcde   1/1   Running             0     1m
sentiment-api-rs-fghij   1/1   Running             0     1m
sentiment-api-rs-abcde   1/1   Terminating         0     1m
sentiment-api-rs-klmno   0/1   Pending             0     0s    ← desired=2 맞추려 즉시 새 Pod
sentiment-api-rs-klmno   0/1   ContainerCreating   0     1s
sentiment-api-rs-klmno   0/1   Running             0     8s
sentiment-api-rs-klmno   1/1   Running             0     28s   ← 30초 안에 Ready
```

**해석**: 지웠는데도 desired=2를 맞추려 새 Pod이 즉시 만들어집니다. 새 Pod의 이름이 다른 hash(`klmno`)인 것이 "정말 새 Pod"임의 증거입니다. 이게 ReplicaSet의 self-healing입니다.

### 3-3. ReplicaSet 정리 (다음 단계로 넘어가기 전)

```bash
kubectl delete -f manifests/replicaset.yaml
```

## 4단계 — Deployment 배포 + 진단 셋

```bash
kubectl apply -f manifests/deployment-v1.yaml
kubectl rollout status deployment/sentiment-api
```

**예상 출력 (모델 로드 완료까지 30~60초)**

```
deployment.apps/sentiment-api created
Waiting for deployment "sentiment-api" rollout to finish: 0 of 3 updated replicas are available...
Waiting for deployment "sentiment-api" rollout to finish: 1 of 3 updated replicas are available...
Waiting for deployment "sentiment-api" rollout to finish: 2 of 3 updated replicas are available...
deployment "sentiment-api" successfully rolled out
```

이제 Deployment가 자동으로 만든 ReplicaSet과 Pod을 확인합니다.

```bash
kubectl get deploy sentiment-api
kubectl get rs -l app=sentiment-api
kubectl get pods -l app=sentiment-api -o wide
```

**예상 출력**

```
# kubectl get deploy
NAME            READY   UP-TO-DATE   AVAILABLE   AGE
sentiment-api   3/3     3            3           2m

# kubectl get rs (Deployment가 자동 생성한 RS, 이름 끝의 hash는 template hash)
NAME                       DESIRED   CURRENT   READY   AGE
sentiment-api-7c9d8b5f74   3         3         3       2m

# kubectl get pods
NAME                             READY   STATUS    RESTARTS   AGE   IP            NODE
sentiment-api-7c9d8b5f74-aa11    1/1     Running   0          2m    10.244.0.10   minikube
sentiment-api-7c9d8b5f74-bb22    1/1     Running   0          2m    10.244.0.11   minikube
sentiment-api-7c9d8b5f74-cc33    1/1     Running   0          2m    10.244.0.12   minikube
```

> 💡 Pod 이름은 `<deployment>-<rs-hash>-<pod-hash>` 형식입니다. 같은 ReplicaSet에서 만들어진 Pod은 가운데 hash(`7c9d8b5f74`)가 같습니다.

## 5단계 — `kubectl scale`로 레플리카 변경

### 5-1. replicas=5로 늘리기

```bash
kubectl scale deployment/sentiment-api --replicas=5
kubectl get pods -l app=sentiment-api
```

**예상 출력 (충분한 메모리가 있을 때)**

```
NAME                             READY   STATUS              RESTARTS   AGE
sentiment-api-7c9d8b5f74-aa11    1/1     Running             0          3m
sentiment-api-7c9d8b5f74-bb22    1/1     Running             0          3m
sentiment-api-7c9d8b5f74-cc33    1/1     Running             0          3m
sentiment-api-7c9d8b5f74-dd44    0/1     ContainerCreating   0          5s
sentiment-api-7c9d8b5f74-ee55    0/1     ContainerCreating   0          5s
```

minikube에 4Gi만 줬다면 일부가 `Pending`에 머무를 수 있습니다.

### 5-2. (Pending이 보이는 경우) 원인 확인

```bash
kubectl get pods -l app=sentiment-api
```

**예상 출력 (메모리 부족 시)**

```
sentiment-api-7c9d8b5f74-dd44    0/1     Pending             0          30s
```

```bash
PENDING=$(kubectl get pod -l app=sentiment-api --field-selector=status.phase=Pending -o jsonpath='{.items[0].metadata.name}')
kubectl describe pod $PENDING | tail -20
```

**예상 출력 (Events 섹션)**

```
Events:
  Type     Reason            Age   From               Message
  ----     ------            ----  ----               -------
  Warning  FailedScheduling  20s   default-scheduler  0/1 nodes are available: 1 Insufficient memory.
```

해결: minikube에 메모리를 더 줍니다 (트러블슈팅 표 3 참고).

### 5-3. (선택) 매니페스트 회귀 현상 확인

```bash
# 매니페스트는 replicas=3 그대로
kubectl apply -f manifests/deployment-v1.yaml
kubectl get deploy sentiment-api
```

**예상 출력**

```
deployment.apps/sentiment-api configured
NAME            READY   UP-TO-DATE   AVAILABLE   AGE
sentiment-api   3/3     3            3           5m
```

방금 `scale`로 5개로 늘려놨는데 `apply` 한 번에 다시 3개로 줄었습니다. 이게 **자주 하는 실수 2번**의 정체입니다. 베이스라인을 정말 5로 바꿀 거면 매니페스트의 `replicas`도 같이 5로 수정해야 합니다.

## 6단계 — 롤링 업데이트 (v1 → v2)

세 개의 셸을 띄워 진행합니다.

### 6-1. 셸 1 — port-forward (백그라운드 유지)

```bash
kubectl port-forward deploy/sentiment-api 8000:8000
```

**예상 출력**

```
Forwarding from 127.0.0.1:8000 -> 8000
Forwarding from [::1]:8000 -> 8000
```

이 셸은 그대로 둡니다.

### 6-2. 셸 2 — `/ready` 응답을 2초마다 호출 (v1/v2 전환 관찰)

```bash
while true; do curl -s localhost:8000/ready; echo; sleep 2; done
```

**예상 출력 (롤아웃 전)**

```
{"status":"ready","model":"cardiffnlp/twitter-roberta-base-sentiment","version":"v1"}
{"status":"ready","model":"cardiffnlp/twitter-roberta-base-sentiment","version":"v1"}
{"status":"ready","model":"cardiffnlp/twitter-roberta-base-sentiment","version":"v1"}
```

이 셸도 그대로 둡니다.

### 6-3. 셸 3 — 롤아웃 트리거 + 관찰

```bash
kubectl set image deployment/sentiment-api app=sentiment-api:v2
kubectl rollout status deployment/sentiment-api
```

**예상 출력**

```
deployment.apps/sentiment-api image updated
Waiting for deployment "sentiment-api" rollout to finish: 1 out of 3 new replicas have been updated...
Waiting for deployment "sentiment-api" rollout to finish: 2 out of 3 new replicas have been updated...
Waiting for deployment "sentiment-api" rollout to finish: 1 old replicas are pending termination...
deployment "sentiment-api" successfully rolled out
```

이 사이 **셸 2**의 `/ready` 응답에서 `"version":"v2"`가 섞여 들어오기 시작하다가, 끝나면 모두 v2가 됩니다.

> 💡 port-forward는 가장 먼저 Ready인 Pod 하나에 묶이는 경향이 있어 v1/v2가 잘 안 섞여 보일 수 있습니다. 이 경우 셸 1을 한 번 끊었다 다시 띄우면 다른 Pod로 바뀝니다.

### 6-4. 새/구 ReplicaSet 분포 확인

```bash
kubectl get rs -l app=sentiment-api
```

**예상 출력**

```
NAME                       DESIRED   CURRENT   READY   AGE
sentiment-api-7c9d8b5f74   0         0         0       10m   ← 구 RS, replicas=0으로 줄어듦
sentiment-api-86fbb56b8d   3         3         3       2m    ← 신 RS
```

### 6-5. 진짜 점진 교체였는지 한 번 더 검증

다음 명령은 롤아웃 중에 실행하면 `:v1`과 `:v2`가 동시에 보입니다 (이미 끝났다면 v2만 보입니다).

```bash
kubectl get pods -l app=sentiment-api \
  -o jsonpath='{.items[*].spec.containers[0].image}'; echo
```

**예상 출력 (롤아웃 종료 후)**

```
sentiment-api:v2 sentiment-api:v2 sentiment-api:v2
```

## 7단계 — RollingUpdate 전략 비교 (`maxSurge=1, maxUnavailable=0`)

기본값(25%/25%)과 명시판(`maxSurge:1, maxUnavailable:0`)을 비교합니다.

### 7-1. 명시판 적용

```bash
kubectl apply -f manifests/deployment-rolling.yaml
kubectl rollout status deployment/sentiment-api
```

이 시점에서 Deployment는 v1 이미지로 다시 돌아갑니다 (`deployment-rolling.yaml`의 image가 `:v1`이므로).

### 7-2. 다시 v2로 토글하면서 동시 Pod 수 관찰

**셸 A** (관찰용):

```bash
kubectl get pods -l app=sentiment-api -w
```

**셸 B** (트리거):

```bash
kubectl set image deployment/sentiment-api app=sentiment-api:v2
```

**예상 출력 (셸 A)**

```
NAME                             READY   STATUS    RESTARTS   AGE
sentiment-api-aaaaaaaaa-pod1     1/1     Running   0          2m
sentiment-api-aaaaaaaaa-pod2     1/1     Running   0          2m
sentiment-api-aaaaaaaaa-pod3     1/1     Running   0          2m
sentiment-api-bbbbbbbbb-pod4     0/1     Pending   0          0s     ← +1 (maxSurge=1)
sentiment-api-bbbbbbbbb-pod4     0/1     Running   0          5s
sentiment-api-bbbbbbbbb-pod4     1/1     Running   0          28s    ← Ready 후 minReadySeconds 10초 대기
sentiment-api-aaaaaaaaa-pod1     1/1     Terminating  0       2m     ← 그제서야 구 Pod 1개 삭제
sentiment-api-bbbbbbbbb-pod5     0/1     Pending   0          0s
...
```

**해석**: 동시에 떠 있는 Pod 수가 **항상 4 이하**(`replicas=3 + maxSurge=1`)로 유지됩니다. `maxUnavailable=0`이라 새 Pod이 Ready 전에는 구 Pod이 절대 사라지지 않습니다 → 가용 capacity 무중단.

## 8단계 — 롤백 + 정리

### 8-1. 롤아웃 history 확인

```bash
kubectl rollout history deployment/sentiment-api
```

**예상 출력**

```
deployment.apps/sentiment-api
REVISION  CHANGE-CAUSE
1         <none>
2         <none>
3         <none>
```

REVISION 번호가 3개 보이면 그동안 (`apply` v1, `set image` v2, `apply` rolling, `set image` v2) 변경이 잘 기록된 것입니다.

### 8-2. 직전 버전으로 롤백

```bash
kubectl rollout undo deployment/sentiment-api
kubectl rollout status deployment/sentiment-api
```

**예상 출력**

```
deployment.apps/sentiment-api rolled back
deployment "sentiment-api" successfully rolled out
```

`/ready` 응답이 다시 v1으로 돌아왔는지 확인합니다 (셸 2의 루프가 살아 있다면 자동으로 보임).

```bash
curl -s localhost:8000/ready; echo
```

**예상 출력**

```
{"status":"ready","model":"cardiffnlp/twitter-roberta-base-sentiment","version":"v1"}
```

### 8-3. 정리

```bash
# 셸 1, 셸 2의 port-forward와 curl 루프는 Ctrl+C로 종료
# 그다음 본 디렉토리에서:
kubectl delete -f manifests/deployment-rolling.yaml --ignore-not-found
kubectl delete -f manifests/deployment-v1.yaml --ignore-not-found
kubectl delete -f manifests/replicaset.yaml --ignore-not-found
kubectl delete -f manifests/pod-direct.yaml --ignore-not-found

# minikube는 다음 토픽에서도 그대로 사용
minikube stop
```

## 트러블슈팅

| 증상 | 원인 | 해결 |
|------|------|------|
| Pod이 `ImagePullBackOff` 또는 `ErrImagePull` | minikube에 이미지가 안 올라갔거나 `imagePullPolicy: Always`로 매번 외부 레지스트리 조회 | `minikube image ls \| grep sentiment-api`로 확인 후 1단계 재실행. 매니페스트의 `imagePullPolicy: IfNotPresent` 필드 확인. |
| `kubectl set image` 성공 메시지가 떴는데 Pod이 영영 안 바뀜 | `selector`가 새 template label과 불일치하거나, 같은 image 태그라 controller가 변경을 인지하지 못함 | `kubectl describe deploy sentiment-api`의 Events에서 selector 관련 경고 확인. selector는 immutable이므로 잘못 만들었으면 `kubectl delete deploy sentiment-api` 후 재생성. |
| `kubectl scale --replicas=5` 후 일부 Pod이 `Pending`에 머무름 | 노드 RAM 부족 (모델 600Mi × 5 + 시스템 ≈ 4Gi 한도 근접) | `kubectl describe pod <pending>` Events에서 `Insufficient memory` 확인. `minikube stop && minikube start --memory=6g --cpus=2`로 메모리 확장 후 1단계부터 다시 실행. |
| `kubectl rollout status`가 5분 이상 진행 없이 멈춤 | readinessProbe가 `/ready` 503을 받아 새 Pod이 Ready로 안 됨 (모델 로드 실패 또는 v2 이미지 깨짐) | `kubectl logs <new-pod>`에서 모델 로드 에러 확인. 정상 복구가 어렵다면 `kubectl rollout undo deployment/sentiment-api`로 롤백. |
| `kubectl rollout undo` 후에도 `/ready`가 v2 응답 | port-forward가 이미 종료된 옛 Pod에 묶여 stale | 셸 1의 `kubectl port-forward`를 Ctrl+C 후 다시 실행. 또는 `pkill -f "port-forward"`. |

## 다음 단계

이 토픽을 끝냈으면 [03-service-networking](../../03-service-networking/lesson.md)으로 이동해, sentiment-api Pod 집합 앞에 안정적인 네트워크 엔드포인트(Service)를 붙여 외부에서 호출하는 방법을 학습합니다.
