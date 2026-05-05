# Phase 4 / 02 — 실습 가이드 (KServe InferenceService)

> **선행 토픽**: [Phase 4 / 01 — GPU on Kubernetes](../../01-gpu-on-k8s/lesson.md)
> **본 토픽**: [Phase 4 / 02 — KServe InferenceService](../lesson.md)
> **소요 시간**: 60~80분 (Step 1 KServe 미설치 시 +20분, Step 6 옵션 +15분)
> **환경**: minikube 단일 트랙 (CPU 분류 모델, GPU 불필요)

---

## 작업 디렉토리

본 lab 의 모든 명령은 다음 디렉토리에서 실행한다고 가정합니다.

```bash
cd course/phase-4-ml-on-k8s/02-kserve-inference
ls
# 예상 출력:
# labs/  lesson.md  manifests/
```

---

## 실습 단계 한눈에 보기

| Step | 목적 | 핵심 명령 | 소요 |
|-----|------|----------|------|
| 0 | 사전 점검 | `minikube status`, `kubectl get nodes` | 5분 |
| 1 | KServe 설치 검증 | `kubectl get pods -n kserve` | 5~20분 |
| 2 | sentiment ISVC 적용 | `kubectl apply -f manifests/sentiment-isvc.yaml` | 10~15분 |
| 3 | 추론 호출 | `curl -H "Host: ..." .../v1/models/sentiment:predict` | 5분 |
| 4 | scale-to-zero 관찰 | `kubectl get pods -w` + `time curl` | 10분 |
| 5 | Canary 30% | `kubectl apply -f sentiment-isvc-v2-canary.yaml` | 15분 |
| 6 | (옵션) 커스텀 predictor | `kubectl apply -f sentiment-isvc-custom.yaml` | 15분 |
| 7 | 정리 | `kubectl delete -f manifests/` | 5분 |

---

## Step 0 — 사전 점검

minikube 가 8GB+ 메모리, 4 CPU+ 로 떠 있는지 확인합니다. 부족하면 KServe 설치 도중 OOM 으로 컴포넌트가 죽거나, ISVC 가 영원히 `READY=False` 에 머무릅니다.

```bash
minikube status
```

**예상 출력**:
```
minikube
type: Control Plane
host: Running
kubelet: Running
apiserver: Running
kubeconfig: Configured
```

minikube 가 stop 상태이거나 처음 띄우는 경우:
```bash
# 권장 자원으로 재시작
minikube start --memory=8192 --cpus=4 --kubernetes-version=v1.28.3
```

```bash
kubectl get nodes
kubectl version --client
```

**예상 출력**:
```
NAME       STATUS   ROLES           AGE   VERSION
minikube   Ready    control-plane   ...   v1.28.x

Client Version: v1.28.x
```

✅ **확인 포인트**: Node 가 `Ready` 이고 kubectl 1.28+ 입니다. 이 조건 미충족 시 다음 Step 으로 넘어가지 마세요.

---

## Step 1 — KServe 설치 검증

KServe + Knative + Istio 가 이미 설치되어 있다면 본 Step 은 검증만으로 끝납니다. 없다면 quick_install 을 실행합니다.

### 1-1. 설치 여부 확인

```bash
kubectl get pods -n kserve
kubectl get pods -n knative-serving
kubectl get pods -n istio-system
```

**이미 설치된 경우의 예상 출력**:
```
# -n kserve
NAME                                READY   STATUS    RESTARTS   AGE
kserve-controller-manager-xxx       2/2     Running   0          ...

# -n knative-serving
NAME                          READY   STATUS    RESTARTS   AGE
activator-xxx                 1/1     Running   0          ...
autoscaler-xxx                1/1     Running   0          ...
controller-xxx                1/1     Running   0          ...
net-istio-controller-xxx      1/1     Running   0          ...
net-istio-webhook-xxx         1/1     Running   0          ...
webhook-xxx                   1/1     Running   0          ...

# -n istio-system
NAME                                    READY   STATUS    RESTARTS   AGE
istio-ingressgateway-xxx                1/1     Running   0          ...
istiod-xxx                              1/1     Running   0          ...
```

✅ **확인 포인트**: 세 네임스페이스 모두 Pod 가 모두 `Running` 입니다. 일부가 `Pending` 이면 minikube 자원이 부족할 가능성이 높습니다 (`minikube stop && minikube start --memory=10240 --cpus=4`).

### 1-2. 미설치 시 quick_install 실행

```bash
# KServe 0.14 + Knative + Istio + cert-manager 한 번에 설치 (15~20분)
curl -s "https://raw.githubusercontent.com/kserve/kserve/release-0.14/hack/quick_install.sh" | bash
```

설치 완료 후 다시 1-1 의 명령으로 모든 Pod 가 `Running` 인지 확인합니다.

> 💡 **트러블슈팅**: 설치 도중 cert-manager Webhook 타임아웃이 나면 `kubectl wait --for=condition=available deployment/cert-manager-webhook -n cert-manager --timeout=300s` 로 명시적 대기 후 다시 시도하세요.

**다음**: Step 2 — sentiment ISVC 적용

---

## Step 2 — sentiment ISVC 적용 (메인 경로)

본 토픽의 핵심 매니페스트인 빌트인 HuggingFace 런타임 ISVC 를 적용합니다.

### 2-1. 매니페스트 적용

```bash
kubectl apply -f manifests/sentiment-isvc.yaml
```

**예상 출력**:
```
inferenceservice.serving.kserve.io/sentiment created
```

### 2-2. ISVC READY 상태까지 대기

```bash
kubectl get isvc sentiment -w
```

**예상 출력 (시간 흐름)**:
```
NAME        URL                                          READY   PREV   LATEST   PREVROLLEDOUTREVISION   LATESTREADYREVISION                  AGE
sentiment                                                False                                                                                10s
sentiment   http://sentiment-default.example.com         False                                                                                30s
sentiment   http://sentiment-default.example.com         False                                                                                90s
sentiment   http://sentiment-default.example.com         True            100                              sentiment-predictor-default-00001    180s
```

✅ **확인 포인트**:
- `URL` 컬럼이 `http://sentiment-default.example.com` 형태로 채워졌습니다
- `READY=True` 까지 약 1~3분 소요됩니다 (HF runtime 이미지 풀 ~5GB + 모델 다운로드 ~500MB)
- `LATESTREADYREVISION` 이 `sentiment-predictor-default-00001` 로 표기됩니다

`Ctrl+C` 로 watch 종료.

### 2-3. ISVC 상세 확인

```bash
kubectl describe isvc sentiment
```

**예상 출력 발췌**:
```
Status:
  Components:
    Predictor:
      Latest Created Revision:    sentiment-predictor-default-00001
      Latest Ready Revision:      sentiment-predictor-default-00001
      Latest Rolled Out Revision: sentiment-predictor-default-00001
      Traffic:
        Latest Revision: true
        Percent:         100
        Revision Name:   sentiment-predictor-default-00001
      URL:                        http://sentiment-default.example.com
  Conditions:
    Type                          Status
    ----                          ------
    IngressReady                  True
    PredictorReady                True
    Ready                         True
```

```bash
kubectl get pods -l serving.kserve.io/inferenceservice=sentiment
```

**예상 출력**:
```
NAME                                                              READY   STATUS    RESTARTS   AGE
sentiment-predictor-default-00001-deployment-xxx                  2/2     Running   0          3m
```

> 💡 `READY 2/2` 의 의미: 첫 번째는 우리 모델 컨테이너(`kserve-container`), 두 번째는 Knative `queue-proxy` 사이드카(자동 주입). 직접 만든 적 없는데 보이는 이유입니다.

### 2-4. (트러블슈팅) READY=False 가 5분 넘게 지속될 때

```bash
# 어떤 Pod 가 막혔는지
kubectl get pods -l serving.kserve.io/inferenceservice=sentiment
kubectl describe pod <pod-name> | tail -40
```

자주 보이는 원인:
- `ImagePullBackOff` — KServe HF runtime 이미지(~5GB) 풀이 느림. 인내심을 갖거나 `kubectl describe pod` 의 Events 에서 진행 상황 확인.
- `OOMKilled` — minikube 메모리 부족. `minikube stop` 후 `--memory=10240` 으로 재시작.
- `Init:0/1` 5분+ — Storage Initializer 가 HF Hub 다운로드 중. 정상.

**다음**: Step 3 — 추론 호출

---

## Step 3 — 추론 호출

ISVC 가 READY 가 되었으니 외부에서 호출해 봅니다. minikube 환경에서는 `port-forward` 로 Istio 인그레스 게이트웨이를 노출합니다.

### 3-1. ISVC URL 확인

```bash
INGRESS_URL=$(kubectl get isvc sentiment -o jsonpath='{.status.url}')
echo "ISVC URL: $INGRESS_URL"
```

**예상 출력**:
```
ISVC URL: http://sentiment-default.example.com
```

이 호스트는 클러스터 외부에서 직접 해석되지 않으므로(가짜 도메인), `Host` 헤더로 명시해 호출합니다.

### 3-2. Istio 인그레스 port-forward (별도 터미널)

```bash
kubectl port-forward svc/istio-ingressgateway -n istio-system 8080:80
```

**예상 출력**:
```
Forwarding from 127.0.0.1:8080 -> 8080
Forwarding from [::1]:8080 -> 8080
```

이 터미널은 그대로 두고, **새 터미널**에서 다음 명령들을 실행합니다.

### 3-3. 추론 호출

```bash
curl -v -H "Host: sentiment-default.example.com" \
  -H "Content-Type: application/json" \
  http://localhost:8080/v1/models/sentiment:predict \
  -d '{"instances":["I love this!"]}'
```

**예상 출력 (성공)**:
```
> POST /v1/models/sentiment:predict HTTP/1.1
> Host: sentiment-default.example.com
> Content-Type: application/json
...
< HTTP/1.1 200 OK
< content-type: application/json
< K-Knative-Revision: sentiment-predictor-default-00001
...

{"predictions":[{"label":"positive","score":0.9837}]}
```

✅ **확인 포인트**:
- HTTP 200 응답
- `K-Knative-Revision` 헤더에 v1 Revision 이름
- `predictions[0].label` 이 `positive`/`neutral`/`negative` 중 하나

### 3-4. 다른 입력 테스트

```bash
curl -s -H "Host: sentiment-default.example.com" \
  -H "Content-Type: application/json" \
  http://localhost:8080/v1/models/sentiment:predict \
  -d '{"instances":["This is the worst day ever."]}' | jq
```

**예상 출력**:
```json
{
  "predictions": [
    { "label": "negative", "score": 0.9123 }
  ]
}
```

> 💡 **여러 텍스트 동시 추론(batch)**: `{"instances": ["text1", "text2", "text3"]}` 처럼 배열로 보내면 응답도 배열입니다. HF 빌트인 runtime 은 자동 batching 으로 처리량을 높여줍니다.

### 3-5. (트러블슈팅) 404 NR 또는 503

- **Host 헤더 빠뜨림** → 404. `-H "Host: $INGRESS_URL"` 의 `http://` 접두사를 빼야 합니다(`sentiment-default.example.com` 만).
- **port-forward 종료됨** → 연결 거부. 별도 터미널의 port-forward 가 살아 있는지 확인.
- **ISVC 가 READY 가 아님** → 503. Step 2 로 돌아가 `kubectl get isvc sentiment` 확인.

**다음**: Step 4 — scale-to-zero 관찰

---

## Step 4 — scale-to-zero 관찰 + cold start 측정

본 토픽의 메인 매니페스트는 `minReplicas: 0` 이므로 트래픽이 없으면 Pod 가 0 개로 줄어듭니다. 직접 관찰하고 첫 응답 시간을 측정합니다.

### 4-1. Pod 수 watch (별도 터미널)

```bash
kubectl get pods -l serving.kserve.io/inferenceservice=sentiment -w
```

### 4-2. 60~120초 idle 대기

요청을 보내지 않고 기다립니다. Knative 기본 `scaleToZeroPodRetentionPeriod` 가 60초이므로, 마지막 요청 후 약 60~90초 후에 Pod 가 종료됩니다.

**예상 변화 (watch 출력)**:
```
NAME                                                              READY   STATUS        AGE
sentiment-predictor-default-00001-deployment-xxx                  2/2     Running       5m
sentiment-predictor-default-00001-deployment-xxx                  2/2     Terminating   6m
sentiment-predictor-default-00001-deployment-xxx                  0/2     Terminating   6m
sentiment-predictor-default-00001-deployment-xxx                  0/2     Terminated    6m
# 이후 list 가 비어 있음 → Pod 0개 = 비용 0
```

✅ **확인 포인트**: `kubectl get pods` 결과에서 sentiment 관련 Pod 가 사라졌습니다.

### 4-3. cold start 측정

scale-to-zero 상태에서 첫 요청을 보내고 시간을 측정합니다.

```bash
time curl -s -H "Host: sentiment-default.example.com" \
  -H "Content-Type: application/json" \
  http://localhost:8080/v1/models/sentiment:predict \
  -d '{"instances":["Cold start test."]}'
```

**예상 출력**:
```
{"predictions":[{"label":"neutral","score":0.6234}]}

real    0m32.451s    ← 첫 응답에 약 30초 (cold start)
user    0m0.012s
sys     0m0.008s
```

✅ **확인 포인트**: 첫 응답이 30초 이상 걸렸습니다. 이는 Knative Activator 가 요청을 잡아두고 Pod 부팅을 기다린 시간입니다.

### 4-4. 두 번째 요청은 즉시 응답

```bash
time curl -s -H "Host: sentiment-default.example.com" \
  -H "Content-Type: application/json" \
  http://localhost:8080/v1/models/sentiment:predict \
  -d '{"instances":["Second call."]}'
```

**예상 출력**:
```
{"predictions":[{"label":"neutral","score":0.7100}]}

real    0m0.142s     ← Pod 가 살아 있어 즉시 응답
```

> 💡 **운영 관점 결정**: 첫 응답 30초 지연이 받아들여지지 않는 워크로드(외부 API, 실시간 사용자)는 `minReplicas: 1` 로 바꿔야 합니다. 본 토픽 메인 매니페스트는 학습 목적이라 0 으로 두었습니다.

**다음**: Step 5 — Canary 배포

---

## Step 5 — v2 적용 + Canary 30% 트래픽 분할

같은 ISVC 이름(`sentiment`)으로 PodSpec 이 다른 v2 매니페스트를 적용합니다. KServe 가 새 Knative Revision 을 만들고 `canaryTrafficPercent: 30` 에 따라 트래픽을 분할합니다.

### 5-1. v2 매니페스트 검토

```bash
diff manifests/sentiment-isvc.yaml manifests/sentiment-isvc-v2-canary.yaml
```

핵심 변경점:
- `maxReplicas: 3` → `5`
- `requests.memory: 1Gi` → `1500Mi`
- `limits.memory: 2Gi` → `3Gi`
- 새 필드 `canaryTrafficPercent: 30`

이 차이가 PodSpec 해시를 바꿔 Knative 가 새 Revision 을 만들게 합니다.

### 5-2. v2 적용

```bash
kubectl apply -f manifests/sentiment-isvc-v2-canary.yaml
```

**예상 출력**:
```
inferenceservice.serving.kserve.io/sentiment configured
```

### 5-3. 두 Revision 이 모두 살아 있는지 확인

```bash
kubectl get revision -l serving.kserve.io/inferenceservice=sentiment
```

**예상 출력**:
```
NAME                                  CONFIG NAME                    K8S SERVICE NAME                       GENERATION   READY   REASON
sentiment-predictor-default-00001     sentiment-predictor-default                                             1            True
sentiment-predictor-default-00002     sentiment-predictor-default                                             2            True
```

```bash
kubectl get isvc sentiment
```

**예상 출력**:
```
NAME        URL                                          READY   PREV   LATEST   PREVROLLEDOUTREVISION                LATESTREADYREVISION
sentiment   http://sentiment-default.example.com         True    70     30       sentiment-predictor-default-00001    sentiment-predictor-default-00002
```

✅ **확인 포인트**:
- `PREV=70`, `LATEST=30` — v1 70%, v2 30%
- 두 Revision 이 모두 `READY=True`

### 5-4. 트래픽 분할 검증 (20회 호출)

먼저 cold start 가 끝나도록 한 번 호출해 두 Pod 를 모두 깨웁니다.

```bash
for i in {1..3}; do
  curl -s -H "Host: sentiment-default.example.com" \
    -H "Content-Type: application/json" \
    http://localhost:8080/v1/models/sentiment:predict \
    -d '{"instances":["warm up '$i'"]}' > /dev/null
  sleep 2
done
```

이제 응답 헤더의 Revision 을 추적합니다.

```bash
for i in {1..20}; do
  curl -s -D - -H "Host: sentiment-default.example.com" \
    -H "Content-Type: application/json" \
    http://localhost:8080/v1/models/sentiment:predict \
    -d '{"instances":["request '$i'"]}' \
    -o /dev/null \
    | grep -i 'k-knative-revision'
done | sort | uniq -c
```

**예상 출력**:
```
     14 K-Knative-Revision: sentiment-predictor-default-00001
      6 K-Knative-Revision: sentiment-predictor-default-00002
```

✅ **확인 포인트**: v1(00001) 과 v2(00002) 가 대략 7:3 비율로 섞여 나옵니다. 표본이 작아 정확히 14:6 이 안 나올 수 있지만, 두 Revision 이 모두 응답했다는 점이 핵심입니다.

### 5-5. (선택) Canary 완료 — v2 100% 로 승격

검증이 끝났으면 `canaryTrafficPercent` 를 제거하고 다시 apply 해 v2 를 100% 로 만들 수 있습니다 (본 lab 에서는 생략).

```bash
# 예시 (실행하지 않음): canaryTrafficPercent 라인을 빼고 다시 apply
# kubectl apply -f manifests/sentiment-isvc.yaml   # v1 같은 spec 으로 되돌리는 게 아니라
                                                    # v2 spec 에서 canaryTrafficPercent 만 제거한 매니페스트를 따로 만들어 적용
```

**다음**: Step 6 (옵션) 또는 Step 7 (정리)

---

## Step 6 — (옵션) 커스텀 predictor

Phase 0~3 의 `sentiment-api:v1` 이미지를 KServe 로 감싸는 보조 경로를 시연합니다. 빌트인 V1 프로토콜이 아닌 **FastAPI 의 `/predict` 가 그대로 외부 API 가 되는 점**을 확인합니다.

### 6-0. 사전 조건 — Phase 0 이미지 적재

minikube 노드에 `sentiment-api:v1` 이미지가 있어야 합니다. Phase 1/02 lab 을 이미 마쳤다면 적재되어 있을 것입니다.

```bash
minikube image ls | grep sentiment-api
```

**예상 출력**:
```
docker.io/library/sentiment-api:v1
```

없으면 Phase 1/02 lab 의 `minikube image load` 단계를 다시 수행합니다.

### 6-1. 커스텀 ISVC 적용

```bash
kubectl apply -f manifests/sentiment-isvc-custom.yaml
```

**예상 출력**:
```
inferenceservice.serving.kserve.io/sentiment-custom created
```

### 6-2. READY 까지 대기

```bash
kubectl get isvc sentiment-custom -w
```

`READY=True` 까지 약 30~120초 (Phase 0 이미지의 모델 로딩 시간).

```
NAME               URL                                                 READY   ...
sentiment-custom   http://sentiment-custom-default.example.com         True    ...
```

`Ctrl+C` 로 종료.

### 6-3. 호출 — V1 프로토콜이 **아닌** FastAPI `/predict` 사용

빌트인 runtime 과 달리 path 가 `/predict`, body 스키마가 `{"text": "..."}` 입니다.

```bash
curl -s -H "Host: sentiment-custom-default.example.com" \
  -H "Content-Type: application/json" \
  http://localhost:8080/predict \
  -d '{"text":"I love this!"}'
```

**예상 출력**:
```json
{"label":"POSITIVE","score":0.9837}
```

✅ **확인 포인트**:
- 경로가 `/v1/models/sentiment-custom:predict` 가 **아니라** `/predict`
- 요청 body 가 `{"text": ...}`, 응답이 `{"label": ..., "score": ...}` (Phase 0 fastapi_app.py 와 동일)

### 6-4. 두 ISVC 동시 운영 확인

```bash
kubectl get isvc
```

**예상 출력**:
```
NAME               URL                                                 READY
sentiment          http://sentiment-default.example.com                True
sentiment-custom   http://sentiment-custom-default.example.com         True
```

> 💡 **GPU 사용 시 변경점**: 본 lab 은 CPU 분류 모델이라 GPU 가 불필요합니다. 만약 GPU 환경에서 본 매니페스트를 GPU 로 올리려면 Phase 4-1 의 패턴을 그대로 가져옵니다.
> ```yaml
> # sentiment-isvc-custom.yaml 의 containers[0].resources 아래에 추가
>     limits:
>       nvidia.com/gpu: 1
> # 그리고 predictor 아래에 추가
>     nodeSelector:
>       cloud.google.com/gke-accelerator: nvidia-tesla-t4
>     tolerations:
>       - { key: nvidia.com/gpu, operator: Exists, effect: NoSchedule }
> ```

**다음**: Step 7 — 정리

---

## Step 7 — 정리

```bash
# 본 토픽 매니페스트 모두 제거
kubectl delete -f manifests/
```

**예상 출력**:
```
inferenceservice.serving.kserve.io "sentiment" deleted
inferenceservice.serving.kserve.io "sentiment-custom" deleted
```

(`sentiment-isvc-v2-canary.yaml` 은 `sentiment-isvc.yaml` 과 같은 이름이라 ISVC 1개만 남아 있어 한 번에 정리됩니다.)

```bash
# 잔존 ISVC 확인
kubectl get isvc
# No resources found in default namespace.

# 잔존 Revision 확인 (모두 삭제되어야 함)
kubectl get revision
# No resources found in default namespace.
```

**port-forward 종료**: Step 3 에서 띄운 별도 터미널에서 `Ctrl+C`.

**minikube 클러스터 보존**: 다음 토픽(`03-vllm-llm-serving`) 은 GPU 가 필요해 별도 클러스터로 전환합니다. 본 minikube 는 그대로 두어도 됩니다 (`minikube pause` 로 일시 정지하면 자원 절약).

> 💡 KServe 자체를 제거하고 싶다면 [KServe 공식 cleanup 문서](https://kserve.github.io/website/) 를 따르되, 다음 토픽에서 다시 쓸 가능성이 높으므로 권장하지 않습니다.

---

## 완료 체크리스트

다음을 모두 직접 확인했다면 본 토픽을 마쳤다고 볼 수 있습니다.

- [ ] Step 2: `kubectl get isvc sentiment` 가 `READY=True`
- [ ] Step 3: `curl ... /v1/models/sentiment:predict` 200 OK + 라벨 응답
- [ ] Step 4: 60~120초 idle 후 sentiment Pod 가 0 개로 감소
- [ ] Step 4: cold start 시간 측정값 (예: 32초) 노트에 기록
- [ ] Step 5: 20회 호출의 `K-Knative-Revision` 헤더가 v1/v2 두 종류로 섞임
- [ ] Step 6 (옵션): 커스텀 ISVC 가 `/predict` 경로로 응답
- [ ] Step 7: `kubectl get isvc` 결과가 비어 있음 (모두 정리)

체크박스를 모두 만족하면 [`docs/course-plan.md`](../../../../docs/course-plan.md) 의 Phase 4 / 02-kserve-inference minikube 검증 항목을 `[x]` 로 갱신해 주세요.

---

## 다음 챕터

➡ [Phase 4 / 03 — vLLM LLM Serving](../../03-vllm-llm-serving/lesson.md) (작성 예정)

본 lab 에서 익힌 패턴(InferenceService, scale-to-zero, Canary, port-forward + Host 헤더 호출) 이 vLLM LLM 서빙에 그대로 적용됩니다. 차이는 predictor 컨테이너가 vLLM OpenAI 호환 이미지로 바뀌고, GPU 자원 요청이 추가되는 정도입니다.
