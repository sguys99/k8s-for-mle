# Phase 2 / 01-configmap-secret — 실습 가이드

> Phase 1/04 의 매니페스트에 하드코딩되어 있던 `MODEL_NAME`·`APP_VERSION` 을 ConfigMap 으로 분리하고, HuggingFace 토큰을 Secret 으로 주입한 뒤, 두 가지 주입 방식(env vs file) 과 변경 시 동작을 직접 실험합니다.
>
> **예상 소요 시간**: 45–60분
>
> **선행 조건**
> - [Phase 1 / 04-serve-classification-model](../../../phase-1-k8s-basics/04-serve-classification-model/lesson.md) 완료
> - minikube 에 `sentiment-api:v1` 이미지가 적재되어 있어야 합니다 (Phase 1/04 lab 1단계에서 적재됨)
>
> **작업 디렉토리**
> ```bash
> cd course/phase-2-operations/01-configmap-secret
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

`Stopped`가 보이면 `minikube start` 로 기동합니다.

### 0-2. kubectl 컨텍스트 확인

```bash
kubectl config current-context
```

```
# 예상 출력
minikube
```

### 0-3. sentiment-api:v1 이미지가 minikube 에 있는지 확인

```bash
minikube image ls | grep sentiment-api
```

```
# 예상 출력 (있는 경우)
docker.io/library/sentiment-api:v1
```

비어 있다면 → [Phase 1/04 lab 1단계](../../../phase-1-k8s-basics/04-serve-classification-model/labs/README.md#1단계--필요-시-phase-0-이미지를-minikube에-적재) 로 가서 다시 적재한 뒤 돌아옵니다.

### 0-4. 04 의 잔여 Deployment 정리

04 정리 단계를 잘 수행했다면 비어 있어야 합니다.

```bash
kubectl get deploy,svc,pod -l app=sentiment-api
```

남아 있다면 본 토픽이 같은 이름(`sentiment-api`) Deployment 를 만들기 때문에 **Deployment 만** 삭제하고 시작합니다. (Service / debug-client 는 본 토픽에서 그대로 재사용해도 무방합니다 — `kubectl apply` 는 멱등하므로 manifests/ 의 같은 매니페스트를 덮어써도 변화가 없습니다.)

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

## 1단계 — ConfigMap 과 Secret 적용

이번 단계의 학습 포인트는 **두 오브젝트가 어떻게 클러스터에 등록되는지** 와 **`stringData` 가 자동으로 base64 로 인코딩됨** 을 확인하는 것입니다.

### 1-1. ConfigMap 과 Secret 을 함께 적용

```bash
kubectl apply -f manifests/configmap.yaml -f manifests/secret.yaml
```

```
# 예상 출력
configmap/sentiment-api-config created
secret/sentiment-api-secrets created
```

### 1-2. 등록된 두 오브젝트 확인

```bash
kubectl get configmap,secret -l app=sentiment-api
```

```
# 예상 출력 (이름, 타입, AGE 만 보임)
NAME                              DATA   AGE
configmap/sentiment-api-config    4      10s

NAME                              TYPE     DATA   AGE
secret/sentiment-api-secrets      Opaque   1      10s
```

`DATA: 4` 는 ConfigMap 의 키 4개(`MODEL_NAME`, `APP_VERSION`, `LOG_LEVEL`, `inference.yaml`) 를 의미합니다.

### 1-3. ConfigMap 내용을 yaml 로 확인

```bash
kubectl get configmap sentiment-api-config -o yaml
```

```
# 예상 출력 (발췌)
apiVersion: v1
kind: ConfigMap
metadata:
  name: sentiment-api-config
data:
  APP_VERSION: v1-cm
  LOG_LEVEL: INFO
  MODEL_NAME: cardiffnlp/twitter-roberta-base-sentiment
  inference.yaml: |
    model:
      name: cardiffnlp/twitter-roberta-base-sentiment
      max_length: 128
    ...
```

값이 평문으로 그대로 보입니다. ConfigMap 은 **공개 정보**라는 사고를 가져야 합니다.

---

## 2단계 — Secret 의 base64 가 암호화가 아님을 직접 확인

K8s 입문자가 가장 흔히 오해하는 지점입니다. Secret 은 base64 "인코딩" 일 뿐이며, etcd 에 별도 암호화 옵션을 켜지 않는 한 평문에 가깝습니다.

### 2-1. Secret 의 data 필드를 yaml 로 확인

```bash
kubectl get secret sentiment-api-secrets -o yaml
```

```
# 예상 출력 (발췌)
apiVersion: v1
kind: Secret
metadata:
  name: sentiment-api-secrets
type: Opaque
data:
  HF_TOKEN: aGZfUkVQTEFDRV9NRV9XSVRIX1JFQUxfVE9LRU4=
```

`stringData` 로 작성한 평문이 `data.HF_TOKEN` 의 base64 값으로 변환되어 저장된 것을 확인할 수 있습니다.

### 2-2. base64 디코딩으로 평문 복원

```bash
kubectl get secret sentiment-api-secrets -o jsonpath='{.data.HF_TOKEN}' | base64 -d
echo
```

```
# 예상 출력
hf_REPLACE_ME_WITH_REAL_TOKEN
```

> 💡 **핵심**: Secret 에 접근 권한만 있으면 **누구나 평문을 복원**할 수 있습니다. 운영에서는 SealedSecret 또는 External Secrets Operator 로 암호화하고, RBAC 으로 접근을 제한합니다 (Phase 3/04 에서 다룹니다).

---

## 3단계 — Deployment 적용 + Pod Ready 대기

### 3-1. 모든 매니페스트 한 번에 적용

```bash
kubectl apply -f manifests/
```

```
# 예상 출력
configmap/sentiment-api-config unchanged
deployment.apps/sentiment-api created
pod/debug-client created
secret/sentiment-api-secrets unchanged
service/sentiment-api created   # (또는 04 의 Service 가 살아있다면 unchanged)
```

`unchanged` 는 `apply` 가 멱등이라는 증거입니다 — 1단계에서 이미 적용한 ConfigMap/Secret 은 변경 사항이 없으므로 그대로 둡니다.

### 3-2. Pod 가 모두 Ready(1/1) 가 될 때까지 대기

```bash
kubectl rollout status deployment/sentiment-api --timeout=180s
```

```
# 예상 출력 (모델 로딩 30–90초 후)
Waiting for deployment "sentiment-api" rollout to finish: 0 of 3 updated replicas are available...
Waiting for deployment "sentiment-api" rollout to finish: 1 of 3 updated replicas are available...
Waiting for deployment "sentiment-api" rollout to finish: 2 of 3 updated replicas are available...
deployment "sentiment-api" successfully rolled out
```

### 3-3. Pod 상태 확인

```bash
kubectl get pods -l app=sentiment-api
```

```
# 예상 출력
NAME                             READY   STATUS    RESTARTS   AGE
sentiment-api-7c4d8f5c9b-abcd1   1/1     Running   0          90s
sentiment-api-7c4d8f5c9b-efgh2   1/1     Running   0          90s
sentiment-api-7c4d8f5c9b-ijkl3   1/1     Running   0          90s
```

세 Pod 모두 `READY 1/1` 이면 모델 로딩이 끝나고 Service 가 트래픽을 보내기 시작한 상태입니다.

---

## 4단계 — env 주입 검증

이번 단계의 학습 포인트는 **envFrom 한 줄로 ConfigMap·Secret 의 모든 키가 환경 변수로 등록됨** 을 직접 확인하는 것입니다.

### 4-1. Pod 안에서 환경 변수 확인

```bash
POD=$(kubectl get pod -l app=sentiment-api -o jsonpath='{.items[0].metadata.name}')
kubectl exec -it $POD -- env | grep -E 'MODEL_NAME|APP_VERSION|HF_TOKEN|LOG_LEVEL' | sort
```

```
# 예상 출력
APP_VERSION=v1-cm
HF_TOKEN=hf_REPLACE_ME_WITH_REAL_TOKEN
LOG_LEVEL=INFO
MODEL_NAME=cardiffnlp/twitter-roberta-base-sentiment
```

ConfigMap 의 3개 키 + Secret 의 1개 키, 총 4개가 모두 환경 변수로 들어왔습니다.

### 4-2. /ready 응답으로 APP_VERSION 검증

```bash
kubectl exec -it debug-client -- curl -s http://sentiment-api/ready
echo
```

```
# 예상 출력
{"status":"ready","model":"cardiffnlp/twitter-roberta-base-sentiment","version":"v1-cm"}
```

`version` 이 `"v1-cm"` 으로 보이면 ConfigMap 의 `APP_VERSION` 이 FastAPI 앱에 정상 주입된 것입니다 (04 에서는 `"v1"` 이었습니다).

### 4-3. /predict 호출로 모델 동작 확인

```bash
kubectl exec -it debug-client -- curl -s -X POST http://sentiment-api/predict \
  -H 'Content-Type: application/json' \
  -d '{"text":"I love how easy ConfigMaps make config management"}'
echo
```

```
# 예상 출력 (라벨은 모델에 따라 LABEL_0/1/2 중 하나)
{"label":"LABEL_2","score":0.96...}
```

---

## 5단계 — volume 주입 검증

ConfigMap 의 같은 키(`inference.yaml`) 가 envFrom 만이 아니라 volumeMount 로도 컨테이너 안에 **파일** 로 들어왔는지 확인합니다.

### 5-1. 마운트된 파일 내용 확인

```bash
kubectl exec -it $POD -- cat /etc/inference/inference.yaml
```

```
# 예상 출력
model:
  name: cardiffnlp/twitter-roberta-base-sentiment
  max_length: 128
  top_k: 1
serving:
  batch_size: 32
  timeout_seconds: 30
```

ConfigMap 에 정의한 yaml 텍스트가 그대로 파일로 보입니다.

### 5-2. 파일 메타정보 확인 (subPath 의 동작 이해)

```bash
kubectl exec -it $POD -- ls -la /etc/inference/
```

```
# 예상 출력
-rw-r--r--    1 root     root           143 May  3 12:00 inference.yaml
```

> 💡 **subPath 를 안 썼다면** `/etc/inference/` 디렉토리에 ConfigMap 의 모든 키가 파일로 늘어섰을 것입니다 (`MODEL_NAME` 같은 env 용 키도 포함). subPath 로 한 키만 골라 마운트하는 것이 흔한 패턴입니다.

> ⚠️ **subPath 의 트레이드오프**: subPath 로 마운트한 파일은 ConfigMap 변경 시에도 **자동 갱신되지 않습니다**. 갱신을 받으려면 디렉토리 단위로 마운트해야 하지만, 그러면 다른 키가 파일로 함께 노출되는 문제가 생깁니다. 해결책은 6단계의 `rollout restart` 또는 별도 ConfigMap 으로 분리.

---

## 6단계 — ConfigMap 변경 → Pod 가 자동 재시작되지 않는 함정

이번 단계가 본 토픽의 가장 중요한 학습 포인트입니다. 학습자가 운영에서 가장 많이 부딪히는 함정입니다.

### 6-1. ConfigMap 의 APP_VERSION 변경

```bash
# v1-cm → v1-cm-2 로 변경
kubectl patch configmap sentiment-api-config \
  --type merge -p '{"data":{"APP_VERSION":"v1-cm-2"}}'
```

```
# 예상 출력
configmap/sentiment-api-config patched
```

### 6-2. 변경 직후 /ready 응답 확인 (옛 값이 그대로 반환됨)

```bash
sleep 5
kubectl exec -it debug-client -- curl -s http://sentiment-api/ready
echo
```

```
# 예상 출력
{"status":"ready","model":"cardiffnlp/twitter-roberta-base-sentiment","version":"v1-cm"}
```

**`version` 이 여전히 `"v1-cm"` 입니다.** envFrom 으로 주입된 환경 변수는 컨테이너 시작 시점에 한 번만 결정되며, ConfigMap 이 바뀌어도 컨테이너는 모릅니다.

### 6-3. Pod 안의 환경 변수도 옛 값 그대로

```bash
kubectl exec -it $POD -- env | grep APP_VERSION
```

```
# 예상 출력
APP_VERSION=v1-cm
```

### 6-4. rollout restart 로 새 Pod 띄우기

```bash
kubectl rollout restart deployment/sentiment-api
kubectl rollout status deployment/sentiment-api --timeout=180s
```

```
# 예상 출력
deployment.apps/sentiment-api restarted
Waiting for deployment "sentiment-api" rollout to finish: 1 old replicas are pending termination...
deployment "sentiment-api" successfully rolled out
```

### 6-5. 새 Pod 의 /ready 응답에서 변경된 값 확인

```bash
kubectl exec -it debug-client -- curl -s http://sentiment-api/ready
echo
```

```
# 예상 출력
{"status":"ready","model":"cardiffnlp/twitter-roberta-base-sentiment","version":"v1-cm-2"}
```

`version` 이 `"v1-cm-2"` 로 갱신되었습니다.

> 💡 **운영 패턴**: Helm/Kustomize 는 ConfigMap 의 sha256 해시를 Deployment 의 `template.metadata.annotations.checksum/config` 에 자동으로 박아두어, ConfigMap 이 바뀌면 Deployment 의 Pod template 이 변경되고 자연스럽게 롤링 업데이트가 트리거됩니다. 본 토픽의 `deployment.yaml` 에는 그 자리가 `manual-v1` 로 비어 있으니, ConfigMap 을 손으로 바꿀 때는 같이 손으로 `manual-v2`, `manual-v3` 으로 올리거나 위처럼 `rollout restart` 로 대체합니다.

---

## 7단계 — envFrom 키 충돌 미니 실험 (선택)

ConfigMap 과 Secret 을 envFrom 으로 동시에 주입하면 **같은 이름의 키가 있을 경우 어느 쪽이 이기는지** 확인합니다.

### 7-1. Secret 에 `LOG_LEVEL` 키 추가

```bash
kubectl patch secret sentiment-api-secrets \
  --type merge -p '{"stringData":{"LOG_LEVEL":"DEBUG"}}'
```

```
# 예상 출력
secret/sentiment-api-secrets patched
```

이제 ConfigMap 에는 `LOG_LEVEL=INFO`, Secret 에는 `LOG_LEVEL=DEBUG` 가 됩니다.

### 7-2. Pod 재시작 후 어느 값이 이기는지 확인

```bash
kubectl rollout restart deployment/sentiment-api
kubectl rollout status deployment/sentiment-api --timeout=180s

NEW_POD=$(kubectl get pod -l app=sentiment-api -o jsonpath='{.items[0].metadata.name}')
kubectl exec -it $NEW_POD -- env | grep LOG_LEVEL
```

```
# 예상 출력
LOG_LEVEL=DEBUG
```

**Secret 이 ConfigMap 을 덮어썼습니다.** 이유는 [deployment.yaml](../manifests/deployment.yaml) 의 envFrom 배열에서 `secretRef` 가 `configMapRef` **뒤에** 선언되어 있기 때문입니다. 배열 순서가 마지막인 소스가 우선합니다.

> 💡 같은 키 이름을 두 소스에 두는 것은 운영에서 **권장되지 않습니다**. 이름 prefix 를 다르게 두거나(`CFG_LOG_LEVEL` / `SEC_HF_TOKEN`), envFrom 대신 `env.valueFrom` 으로 키를 명시적으로 매핑합니다.

---

## 8단계 — 정리

본 토픽에서 만든 리소스를 모두 삭제합니다. 다만 `sentiment-api:v1` 이미지는 다음 토픽(02-volumes-pvc) 에서 그대로 재사용하므로 `minikube image rm` 은 하지 않습니다.

```bash
kubectl delete -f manifests/ --ignore-not-found
```

```
# 예상 출력
configmap "sentiment-api-config" deleted
deployment.apps "sentiment-api" deleted
pod "debug-client" deleted
secret "sentiment-api-secrets" deleted
service "sentiment-api" deleted
```

minikube 는 다음 토픽에서 그대로 사용하므로 `stop` 만 합니다.

```bash
minikube stop
```

---

## 검증 체크리스트

다음 항목을 모두 확인했다면 본 lab 을 마쳤다고 볼 수 있습니다.

- [ ] **1-2단계**: `kubectl get cm,secret -l app=sentiment-api` 가 두 오브젝트를 모두 표시.
- [ ] **2-2단계**: `base64 -d` 로 Secret 의 평문(`hf_REPLACE_ME_WITH_REAL_TOKEN`)을 복원.
- [ ] **3-3단계**: Pod 3개 모두 `READY 1/1`.
- [ ] **4-1단계**: Pod 안의 `env` 출력에 `MODEL_NAME`/`APP_VERSION`/`HF_TOKEN`/`LOG_LEVEL` 4개가 모두 보임.
- [ ] **4-2단계**: `/ready` 응답의 `version` 필드가 `"v1-cm"`.
- [ ] **5-1단계**: `/etc/inference/inference.yaml` 에 ConfigMap 의 yaml 텍스트가 그대로 들어 있음.
- [ ] **6-2 → 6-5단계**: ConfigMap 변경 직후엔 옛 값이 반환되고, `rollout restart` 후엔 새 값이 반환됨을 직접 관찰.
- [ ] **7-2단계** (선택): 같은 키가 ConfigMap·Secret 에 모두 있을 때 envFrom 배열 마지막 소스가 우선함을 직접 관찰.

체크리스트가 모두 채워졌다면 [docs/course-plan.md](../../../../docs/course-plan.md) 의 Phase 2/01 항목 `minikube 검증` 박스를 `[x]` 로 업데이트합니다.
