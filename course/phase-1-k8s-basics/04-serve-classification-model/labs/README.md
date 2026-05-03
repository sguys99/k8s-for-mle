# Phase 1 / 04-serve-classification-model — 실습 가이드

> Phase 0에서 만든 분류 모델 컨테이너를 Kubernetes에 정식 배포하고, Pod이 죽었다 살아나는 동안에도 Service가 트래픽을 잃지 않는 것을 직접 검증합니다.
>
> **예상 소요 시간**: 60–90분 (모델 로딩 시간 약 30–90초 × 여러 번 포함)
>
> **선행 조건**
> - [Phase 1 / 03-service-networking](../../03-service-networking/lesson.md) 완료
> - minikube에 `sentiment-api:v1` 이미지가 적재되어 있어야 합니다 (Phase 1/02 lab 1단계에서 적재됨). 정리 단계에서 지웠다면 본 README 1단계 절차로 다시 적재합니다.
>
> **작업 디렉토리**
> ```bash
> cd course/phase-1-k8s-basics/04-serve-classification-model
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

`Stopped`가 보이면 `minikube start`로 기동합니다 (자세한 옵션은 [Phase 1/01](../../01-cluster-setup/lesson.md) 참고).

### 0-2. kubectl 컨텍스트가 minikube를 가리키는지 확인

```bash
kubectl config current-context
```

```
# 예상 출력
minikube
```

다른 컨텍스트가 보이면 `kubectl config use-context minikube`로 전환합니다. 04 토픽의 모든 명령은 `default` 네임스페이스에서 실행한다고 가정합니다.

### 0-3. 기존 sentiment-api 리소스가 남아 있는지 확인

03 정리 단계를 잘 수행했다면 비어 있어야 합니다.

```bash
kubectl get deploy,svc,pod -l app=sentiment-api
```

```
# 예상 출력 (정상)
No resources found in default namespace.
```

남아 있다면 04와 충돌하므로 먼저 삭제합니다.

```bash
kubectl delete deploy,svc -l app=sentiment-api --ignore-not-found
kubectl delete pod -l app=sentiment-api --ignore-not-found
```

### 0-4. sentiment-api:v1 이미지가 minikube에 있는지 확인

```bash
minikube image ls | grep sentiment
```

```
# 예상 출력 (있는 경우)
docker.io/library/sentiment-api:v1
docker.io/library/sentiment-api:v2
```

비어 있다면 → **1단계**로 가서 다시 적재합니다. 한 줄이라도 `sentiment-api:v1`이 보이면 1단계는 건너뛰고 **2단계**로 넘어갑니다.

---

## 1단계 — (필요 시) Phase 0 이미지를 minikube에 적재

03 정리 단계에서 이미지를 지웠거나 새 환경이라면 다시 적재합니다. Phase 0의 멀티스테이지 이미지를 빌드한 뒤 02·03이 사용하던 `:v1` 태그로 별칭을 답니다.

### 1-1. Phase 0 이미지 빌드

```bash
# k8s-for-mle 저장소 루트로 이동했다고 가정
docker build -t sentiment-api:multi -f course/phase-0-docker-review/01-docker-fastapi-model/practice/Dockerfile \
  course/phase-0-docker-review/01-docker-fastapi-model/practice
```

```
# 예상 출력 (마지막 줄)
=> => writing image sha256:....
=> => naming to docker.io/library/sentiment-api:multi
```

### 1-2. v1 태그로 별칭 + minikube에 적재

```bash
docker tag sentiment-api:multi sentiment-api:v1
minikube image load sentiment-api:v1
```

`minikube image load`는 호스트 docker의 이미지를 minikube 노드의 컨테이너 런타임으로 직접 복사합니다. 약 1.4GB이므로 30–90초 정도 걸립니다.

### 1-3. 적재 결과 확인

```bash
minikube image ls | grep sentiment-api
```

```
# 예상 출력
docker.io/library/sentiment-api:v1
```

> 💡 **왜 `sentiment-api:multi`를 그대로 쓰지 않고 `:v1` 태그로 별칭을 다는가?**
> 02·03 매니페스트가 모두 `image: sentiment-api:v1`을 참조하기 때문입니다. 04도 동일 태그를 써서 토픽 사이의 일관성을 유지합니다.

---

## 2단계 — Deployment 적용과 모델 로딩 관찰

이번 단계의 학습 포인트는 **READY 컬럼의 `0/1` → `1/1` 변화 시점**입니다. 컨테이너가 부팅되어 STATUS가 `Running`이 되어도, 모델이 로드되기 전까지 Readiness Probe가 실패하므로 READY는 `0/1`로 남습니다. 이 갭이 ML 워크로드의 특수성입니다.

### 2-1. Deployment 적용

```bash
kubectl apply -f manifests/deployment.yaml
```

```
# 예상 출력
deployment.apps/sentiment-api created
```

### 2-2. Pod 상태 실시간 관찰 (셸 A)

```bash
kubectl get pods -l app=sentiment-api -w
```

```
# 예상 출력 (시간순으로 줄이 추가됨)
NAME                             READY   STATUS              RESTARTS   AGE
sentiment-api-6f8d7c5bfb-abc12   0/1     ContainerCreating   0          5s
sentiment-api-6f8d7c5bfb-def34   0/1     ContainerCreating   0          5s
sentiment-api-6f8d7c5bfb-ghi56   0/1     ContainerCreating   0          5s
sentiment-api-6f8d7c5bfb-abc12   0/1     Running             0          18s
sentiment-api-6f8d7c5bfb-def34   0/1     Running             0          20s
sentiment-api-6f8d7c5bfb-ghi56   0/1     Running             0          22s
# ↑ 여기까지 약 20초 — 컨테이너는 떴지만 모델은 아직 로딩 중 (READY 0/1)
sentiment-api-6f8d7c5bfb-abc12   1/1     Running             0          75s
sentiment-api-6f8d7c5bfb-def34   1/1     Running             0          82s
sentiment-api-6f8d7c5bfb-ghi56   1/1     Running             0          90s
# ↑ 약 60–90초 후 — 모델 로딩 완료 → /ready가 200 → READY 1/1
```

3개 모두 `1/1 Running`이 되면 Ctrl+C로 watch를 종료합니다.

### 2-3. 한 Pod의 로그로 로딩 시점 확인

```bash
POD=$(kubectl get pod -l app=sentiment-api -o jsonpath='{.items[0].metadata.name}')
kubectl logs $POD | head -20
```

```
# 예상 출력 (핵심 줄만)
2026-... INFO serving: Loading model: cardiffnlp/twitter-roberta-base-sentiment
2026-... INFO serving: Model loaded in 47.83s
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000
```

`Model loaded in NN.NNs` 줄의 시간이 곧 READY가 `0/1` → `1/1`로 바뀐 지연 시간입니다. 이 값이 Probe `failureThreshold` 설계의 근거입니다(현재 readinessProbe는 5초 × 24 = 최대 120초까지 허용).

---

## 3단계 — Service 적용과 추론 호출

### 3-1. Service와 디버깅 Pod 적용

```bash
kubectl apply -f manifests/service.yaml
kubectl apply -f manifests/debug-client.yaml
```

```
# 예상 출력
service/sentiment-api created
pod/debug-client created
```

### 3-2. Endpoints가 3개 Pod IP로 채워졌는지 확인

```bash
kubectl get endpoints sentiment-api
```

```
# 예상 출력
NAME            ENDPOINTS                                          AGE
sentiment-api   10.244.0.12:8000,10.244.0.13:8000,10.244.0.14:8000   30s
```

`ENDPOINTS`가 `<none>`이라면 selector 라벨이 어긋난 것입니다. 매니페스트에서 Service의 `selector.app`과 Deployment의 `template.metadata.labels.app`이 정확히 같은지 확인합니다.

### 3-3. debug-client에서 /ready 호출

debug-client Pod이 Running일 때까지 대기 후 exec로 들어갑니다.

```bash
kubectl wait --for=condition=Ready pod/debug-client --timeout=60s
kubectl exec -it debug-client -- sh
```

```
# 예상 출력
pod/debug-client condition met
~ $ 
```

이제 debug-client 안에서 Service DNS로 호출합니다.

```sh
# debug-client 내부
curl -s http://sentiment-api/ready
```

```
# 예상 출력
{"status":"ready","model":"cardiffnlp/twitter-roberta-base-sentiment","version":"v1"}
```

### 3-4. /predict로 실제 추론 호출

```sh
# debug-client 내부
curl -s -X POST http://sentiment-api/predict \
  -H 'Content-Type: application/json' \
  -d '{"text":"Kubernetes makes ML deployment surprisingly enjoyable!"}'
```

```
# 예상 출력
{"label":"LABEL_2","score":0.9785...}
```

`LABEL_0` (negative) / `LABEL_1` (neutral) / `LABEL_2` (positive) 중 하나가 나옵니다. 위 문장은 긍정이라 `LABEL_2`가 나오는 것이 정상입니다.

### 3-5. 부하 분산이 동작하는지 확인 (선택)

3개 Pod에 골고루 트래픽이 가는지 보려면 10번 호출해 응답이 모두 200인지만 확인하면 충분합니다(현재 Service는 라운드 로빈에 가깝게 분산).

```sh
# debug-client 내부
for i in $(seq 1 10); do
  curl -s -o /dev/null -w "%{http_code}\n" \
    -X POST http://sentiment-api/predict \
    -H 'Content-Type: application/json' \
    -d '{"text":"sample"}'
done
```

```
# 예상 출력
200
200
200
200
200
200
200
200
200
200
```

debug-client에서 빠져나옵니다.

```sh
# debug-client 내부
exit
```

---

## 4단계 — Pod 강제 종료와 자동 복구 검증 (04 토픽의 핵심)

study-roadmap이 04에서 가장 강조하는 검증입니다. **Pod 1개를 강제로 죽여도 ReplicaSet이 즉시 새 Pod을 띄우고, Service ClusterIP는 변하지 않으며, debug-client에서 /predict 호출이 끊기지 않습니다.**

### 4-1. Pod 한 개의 이름과 IP 기록

```bash
POD=$(kubectl get pod -l app=sentiment-api -o jsonpath='{.items[0].metadata.name}')
echo "삭제할 Pod: $POD"
kubectl get pod $POD -o jsonpath='{.status.podIP}'; echo
kubectl get svc sentiment-api -o jsonpath='{.spec.clusterIP}'; echo
```

```
# 예상 출력 (IP는 환경마다 다름)
삭제할 Pod: sentiment-api-6f8d7c5bfb-abc12
10.244.0.12
10.96.123.45
```

### 4-2. 셸을 두 개로 나눠 동시에 관찰

**셸 A — Endpoints 변화 관찰** (별도 터미널을 열어 실행):

```bash
kubectl get endpoints sentiment-api -w
```

**셸 B — 1초 간격으로 추론 호출** (또 다른 터미널):

```bash
kubectl exec -it debug-client -- sh -c '
  while true; do
    curl -s -o /dev/null -w "%{http_code} " \
      -X POST http://sentiment-api/predict \
      -H "Content-Type: application/json" \
      -d "{\"text\":\"loop test\"}"
    sleep 1
  done
'
```

```
# 셸 B 예상 출력 (한 줄에 계속 추가됨)
200 200 200 200 200 200 200 200 200 200 ...
```

### 4-3. 원래 셸에서 Pod 삭제

```bash
kubectl delete pod $POD
```

```
# 예상 출력
pod "sentiment-api-6f8d7c5bfb-abc12" deleted
```

### 4-4. 두 셸의 변화 관찰

**셸 A** — Endpoints 컬럼이 일시적으로 2개로 줄었다가 새 Pod IP가 추가되는 모습:

```
# 예상 출력
NAME            ENDPOINTS                                          AGE
sentiment-api   10.244.0.12:8000,10.244.0.13:8000,10.244.0.14:8000   3m
sentiment-api   10.244.0.13:8000,10.244.0.14:8000                    3m   ← 삭제 직후
sentiment-api   10.244.0.13:8000,10.244.0.14:8000,10.244.0.15:8000   3m   ← 새 Pod 등록 (10.244.0.15)
```

**셸 B** — 200이 끊기지 않고 계속 출력됩니다.

```
# 예상 출력
200 200 200 200 200 200 200 200 ...
```

연속 호출이 모두 200이라는 것은 **Service가 죽어 가는 Pod을 즉시 Endpoints에서 빼고 살아 있는 Pod 2개로만 라우팅했다**는 증거입니다. Service ClusterIP는 변하지 않았고, 클라이언트(debug-client)는 어떤 Pod이 죽었는지 알 필요가 없습니다.

확인이 끝났으면 두 셸 모두 Ctrl+C로 종료합니다.

### 4-5. 복구 흔적을 ReplicaSet Events로 확인

```bash
kubectl describe rs -l app=sentiment-api | tail -20
```

```
# 예상 출력 (Events 섹션 발췌)
Events:
  Type    Reason            Age    From                   Message
  ----    ------            ----   ----                   -------
  Normal  SuccessfulCreate  3m     replicaset-controller  Created pod: sentiment-api-6f8d7c5bfb-abc12
  Normal  SuccessfulCreate  3m     replicaset-controller  Created pod: sentiment-api-6f8d7c5bfb-def34
  Normal  SuccessfulCreate  3m     replicaset-controller  Created pod: sentiment-api-6f8d7c5bfb-ghi56
  Normal  SuccessfulCreate  30s    replicaset-controller  Created pod: sentiment-api-6f8d7c5bfb-jkl78
```

마지막 `SuccessfulCreate`가 "사용자가 1개를 지웠으니 ReplicaSet 컨트롤러가 desired=3을 맞추기 위해 새 Pod을 만들었다"는 자가 치유의 흔적입니다.

### 4-6. ClusterIP는 변하지 않았는지 확인

```bash
kubectl get svc sentiment-api -o jsonpath='{.spec.clusterIP}'; echo
```

```
# 예상 출력 (4-1에서 본 값과 동일)
10.96.123.45
```

---

## 5단계 — Probe 비교 실험 (왜 Probe가 필요한가)

이번 단계는 **Readiness Probe를 빼면 Service가 모델 로딩이 끝나기 전부터 트래픽을 보내기 시작해 503이 발생**하는 것을 직접 봅니다. 의도적인 안티패턴 시연입니다.

### 5-1. Probe 없는 버전으로 교체 적용

```bash
kubectl apply -f manifests/deployment-no-probe.yaml
```

```
# 예상 출력
deployment.apps/sentiment-api configured
```

`configured` 키워드가 보이면 같은 이름의 Deployment가 in-place로 업데이트되었다는 뜻입니다.

### 5-2. 새 Pod이 곧바로 READY=true가 되는 모습 관찰

```bash
kubectl get pods -l app=sentiment-api -w
```

```
# 예상 출력 (시간순)
NAME                             READY   STATUS              RESTARTS   AGE
sentiment-api-7c9f6d4c8a-xyz01   0/1     ContainerCreating   0          5s
sentiment-api-7c9f6d4c8a-xyz01   1/1     Running             0          15s
# ↑ 컨테이너 부팅 직후(15초)에 바로 READY=1/1 — 모델은 아직 로딩 중인데도 Service가 트래픽을 보내기 시작
```

기본형(2-2단계)에서는 READY가 `1/1`로 바뀌는 데 60–90초가 걸렸지만, Probe가 없으면 약 15초 만에 READY=true가 됩니다. Ctrl+C로 종료합니다.

### 5-3. 모델 로딩 중에 /predict 호출 → 503 관찰

새 Pod이 `1/1 Running`으로 보이자마자 곧바로 호출합니다.

```bash
kubectl exec -it debug-client -- sh -c '
  for i in $(seq 1 30); do
    curl -s -o /dev/null -w "%{http_code} " \
      -X POST http://sentiment-api/predict \
      -H "Content-Type: application/json" \
      -d "{\"text\":\"early test\"}"
    sleep 2
  done
  echo
'
```

```
# 예상 출력 (모델 로딩이 끝나기 전에는 503, 끝난 후에는 200)
503 503 503 503 503 503 503 200 200 200 200 200 200 200 200 200 200 200 200 200 200 200 200 200 200 200 200 200 200 200
```

> 💡 **무엇이 일어났는가?**
> Probe가 없는 Deployment에서는 Service의 Endpoints에 새 Pod이 즉시 등록됩니다. 하지만 FastAPI 앱 내부에서는 모델이 아직 로딩 중이므로, `/predict` 호출 시 핸들러가 `_state["ready"] == False`를 보고 503을 반환합니다. **Readiness Probe가 있었다면, Probe가 200을 받기 전까지 Service는 이 Pod을 Endpoints에 추가조차 하지 않습니다.**

### 5-4. 다시 Probe가 있는 기본형으로 복구

```bash
kubectl apply -f manifests/deployment.yaml
```

```
# 예상 출력
deployment.apps/sentiment-api configured
```

### 5-5. 복구 후 동일한 호출이 모두 200이 되는지 확인

```bash
kubectl rollout status deployment/sentiment-api --timeout=180s
```

```
# 예상 출력
Waiting for deployment "sentiment-api" rollout to finish: 1 of 3 updated replicas are available...
Waiting for deployment "sentiment-api" rollout to finish: 2 of 3 updated replicas are available...
deployment "sentiment-api" successfully rolled out
```

```bash
kubectl exec -it debug-client -- sh -c '
  for i in $(seq 1 10); do
    curl -s -o /dev/null -w "%{http_code} " \
      -X POST http://sentiment-api/predict \
      -H "Content-Type: application/json" \
      -d "{\"text\":\"after fix\"}"
    sleep 1
  done
  echo
'
```

```
# 예상 출력
200 200 200 200 200 200 200 200 200 200
```

5단계 학습 포인트가 끝났습니다.

---

## 6단계 — 정리

```bash
# 본 토픽에서 만든 리소스 모두 삭제
kubectl delete -f manifests/debug-client.yaml --ignore-not-found
kubectl delete -f manifests/service.yaml --ignore-not-found
kubectl delete -f manifests/deployment.yaml --ignore-not-found

# 정리 결과 확인
kubectl get deploy,svc,pod -l app=sentiment-api
kubectl get pod debug-client
```

```
# 예상 출력
No resources found in default namespace.
Error from server (NotFound): pods "debug-client" not found
```

```bash
# minikube는 다음 토픽(Phase 2/01-configmap-secret)에서 그대로 사용하므로 stop만 합니다.
minikube stop
```

```
# 예상 출력
✋  "minikube" 노드를 정지하는 중...
🛑  "minikube" 의 SSH 데몬을 종료하고 있습니다 ...
🛑  1개의 노드가 정지되었습니다.
```

이미지(`sentiment-api:v1`)는 Phase 2에서 그대로 재사용하므로 `minikube image rm`을 하지 않습니다.

---

## 🔧 트러블슈팅 (자주 막히는 지점)

### Pod이 계속 `0/1 Running`에서 멈춰 있고 시간이 지나도 1/1이 안 되는 경우

```bash
kubectl describe pod -l app=sentiment-api | grep -A 5 "Readiness probe"
kubectl logs -l app=sentiment-api --tail=20
```

`Readiness probe failed: HTTP probe failed with statuscode: 503`이 반복되면 모델 로딩이 아직 안 끝난 것입니다. `Model loaded in ...` 줄이 로그에 보일 때까지 기다리면 됩니다. 만약 `failureThreshold` 시간(120초)을 넘기면 Pod이 Restart됩니다 — 그때는 `failureThreshold`를 더 늘리거나 startupProbe를 도입해야 합니다 (Phase 4 GPU 토픽에서 다룹니다).

### `ImagePullBackOff` 또는 `ErrImagePull`이 보이는 경우

```bash
kubectl describe pod -l app=sentiment-api | grep -A 3 Events
```

`Failed to pull image "sentiment-api:v1"`가 보이면 minikube에 이미지가 없거나 `imagePullPolicy`가 `Always`로 잘못 설정된 경우입니다. **1단계**로 돌아가 이미지를 다시 적재하고, 매니페스트의 `imagePullPolicy: IfNotPresent`를 확인합니다.

### `OOMKilled`로 Pod이 계속 재시작되는 경우

```bash
kubectl get pods -l app=sentiment-api
# RESTARTS 컬럼이 1, 2, 3 ... 으로 늘어납니다
kubectl describe pod <pod> | grep -A 2 "Last State"
```

`Reason: OOMKilled`가 보이면 `resources.limits.memory`가 너무 작은 경우입니다. 매니페스트의 `limits.memory`를 1500Mi → 2Gi로 올린 뒤 다시 적용합니다. `requests`만 있고 `limits`가 없으면 노드 메모리가 부족할 때 다른 Pod까지 영향을 받으므로 항상 둘 다 둡니다.

---

## 정리 체크리스트

이 실습을 마쳤다면 다음을 모두 체크할 수 있어야 합니다.

- [ ] 0–6단계를 한 번씩 끝까지 실행했고, 각 단계의 "예상 출력"과 본인 출력이 일치했습니다.
- [ ] 2-2단계에서 READY가 `0/1` → `1/1`로 바뀌는 시점차(약 60–90초)를 직접 보았습니다.
- [ ] 4단계에서 Pod 강제 삭제 후 새 Pod의 IP가 Endpoints에 자동으로 들어오는 모습을 보았고, 같은 시간 동안 debug-client의 호출이 200을 유지했습니다.
- [ ] 5단계에서 Probe가 없는 Deployment에서는 503이 잠시 발생했고, Probe를 도입한 기본형으로 복구하면 200이 회복되는 차이를 직접 보았습니다.
- [ ] `kubectl get svc sentiment-api`의 ClusterIP가 4-6단계 전후로 동일했습니다.

체크가 끝나면 [docs/course-plan.md](../../../../docs/course-plan.md)의 Phase 1/04 minikube 검증 체크박스를 `[x]`로 갱신합니다.
