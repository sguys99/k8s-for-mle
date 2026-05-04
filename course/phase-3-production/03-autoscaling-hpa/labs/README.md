# Phase 3 / 03 — 실습 가이드 (HPA + 부하 테스트)

> [lesson.md](../lesson.md) 의 1–6 절 개념을 실제 minikube 클러스터에 적용해 두 HPA (CPU 기반 / RPS 커스텀 메트릭 기반) 가 동작하는 것을 직접 확인합니다.
>
> **사전 환경**: Phase 3/01 (Helm 차트로 sentiment-api 배포 완료) + Phase 3/02 (kube-prometheus-stack + ServiceMonitor 활성화) 가 모두 끝나 있어야 합니다.
>
> **소요 시간**: 약 60분 (대부분 부하 테스트 + stabilization 대기)

## 작업 디렉토리

본 lab 의 명령은 모두 다음 디렉토리에서 실행한다고 가정합니다.

```bash
cd course/phase-3-production/03-autoscaling-hpa
```

상대경로 `manifests/...` 와 `../01-helm-chart/manifests/chart/sentiment-api` 가 그대로 동작합니다.

---

## Step 0. 사전 점검

본 토픽의 모든 단계는 Phase 3/01 의 prod release 와 Phase 3/02 의 monitoring stack 위에서 동작합니다. 두 자산이 살아 있는지 먼저 확인합니다.

```bash
helm list -n prod
helm list -n monitoring
kubectl get pods -n prod
kubectl get pods -n monitoring
```

**예상 출력**:

```
NAME            NAMESPACE   REVISION   STATUS     CHART                  APP VERSION
sentiment-api   prod        1          deployed   sentiment-api-0.1.0    v1
```

```
NAME    NAMESPACE    REVISION   STATUS     CHART                          APP VERSION
prom    monitoring   1          deployed   kube-prometheus-stack-...      ...
```

```
NAME                              READY   STATUS    RESTARTS   AGE
sentiment-api-7c96f7c84d-abcde    1/1     Running   0          ...
```

```
NAME                                                READY   STATUS    RESTARTS   AGE
alertmanager-prom-...                               2/2     Running   0          ...
prom-grafana-...                                    3/3     Running   0          ...
prom-kube-prometheus-stack-operator-...             1/1     Running   0          ...
prom-kube-state-metrics-...                         1/1     Running   0          ...
prom-prometheus-node-exporter-...                   1/1     Running   0          ...
prometheus-prom-kube-prometheus-stack-prometheus-0  2/2     Running   0          ...
```

✅ **확인 포인트**: prod ns 에 sentiment-api Pod 1개 Running, monitoring ns 에 prometheus / grafana / operator 모두 Running. 둘 중 하나라도 없으면 직전 토픽으로 돌아가서 복구합니다.

> 💡 minikube 메모리가 4Gi 미만이면 monitoring stack 이 OOM 으로 죽을 수 있습니다. `minikube stop && minikube start --memory=4096 --cpus=4` 로 재기동을 권장합니다 (Phase 3/02 lesson.md 자주 하는 실수 3번 참고).

---

## Step 1. metrics-server 활성화 — HPA 의 절반

HPA 의 Resource 타입 메트릭 (CPU/메모리) 은 `metrics.k8s.io` API 에서 옵니다. 이 API 를 서빙하는 컴포넌트가 metrics-server 입니다. minikube 는 addon 으로 한 줄에 켤 수 있습니다.

```bash
minikube addons enable metrics-server
kubectl get apiservice v1beta1.metrics.k8s.io
```

**예상 출력**:

```
metrics-server was successfully enabled
```

```
NAME                     SERVICE                      AVAILABLE   AGE
v1beta1.metrics.k8s.io   kube-system/metrics-server   True        30s
```

활성화 후 30–60초 기다린 뒤 실제 메트릭이 채워졌는지 확인합니다.

```bash
kubectl top pod -n prod
```

**예상 출력**:

```
NAME                              CPU(cores)   MEMORY(bytes)
sentiment-api-7c96f7c84d-abcde    3m           412Mi
```

✅ **설명**: `kubectl top` 이 숫자를 표시하면 metrics-server 가 정상 동작 중. CPU 가 3m (idle) 이고 메모리는 모델 로딩 후 약 400Mi 수준이 정상입니다. 만약 `error: Metrics API not available` 이 나오면 1–2분 더 대기하거나 `kubectl logs -n kube-system deploy/metrics-server` 로 진단합니다.

> ⚠️ minikube 가 아닌 kind 사용자: kind 는 metrics-server 를 기본 제공하지 않으므로 `kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml` 후 `--kubelet-insecure-tls` 플래그를 추가해야 합니다.

---

## Step 2. CPU HPA 활성화 — 01 차트의 placeholder 켜기

[Phase 3/01 차트의 templates/hpa.yaml](../../01-helm-chart/manifests/chart/sentiment-api/templates/hpa.yaml) 은 `{{- if .Values.autoscaling.enabled }}` 게이트로 비활성 상태입니다. helm upgrade 로 켭니다.

```bash
helm upgrade sentiment-api ../01-helm-chart/manifests/chart/sentiment-api \
  -n prod \
  -f ../01-helm-chart/manifests/chart/sentiment-api/values-prod.yaml \
  --set secrets.hfToken=$HF_TOKEN
```

> 💡 [values-prod.yaml](../../01-helm-chart/manifests/chart/sentiment-api/values-prod.yaml) 에 `autoscaling.enabled: true` 가 이미 명시되어 있어 별도 `--set` 없이도 켜집니다 — 차트의 *의도된 prod 상태* 가 곧 HPA 활성. `--set` 으로 toggle 하고 싶으면 `--set autoscaling.enabled=true` 추가.

**예상 출력**:

```
Release "sentiment-api" has been upgraded. Happy Helming!
NAME: sentiment-api
LAST DEPLOYED: ...
NAMESPACE: prod
STATUS: deployed
REVISION: 2
```

HPA 가 만들어졌는지 확인합니다.

```bash
kubectl get hpa -n prod
```

**예상 출력 (helm upgrade 직후 ~30초)**:

```
NAME            REFERENCE                  TARGETS         MINPODS   MAXPODS   REPLICAS   AGE
sentiment-api   Deployment/sentiment-api   <unknown>/70%   2         8         2          15s
```

30–60초 더 기다리면 메트릭이 채워집니다.

```bash
kubectl get hpa -n prod
```

**예상 출력**:

```
NAME            REFERENCE                  TARGETS    MINPODS   MAXPODS   REPLICAS   AGE
sentiment-api   Deployment/sentiment-api   2%/70%     2         8         2          1m
```

✅ **설명**: TARGETS 컬럼이 `<unknown>/70%` 에서 `2%/70%` 로 변하는 것이 정상. `<unknown>` 단계는 metrics-server 가 아직 첫 메트릭을 수집/노출하기 전, 또는 Pod 의 CPU 초기화 기간 5분 (`--horizontal-pod-autoscaler-cpu-initialization-period`) 안에 들어왔을 때 발생합니다. `2%` 는 `requests.cpu: 500m` 의 2% = 10m — idle 상태의 transformer 추론 모델이 흔히 보이는 값입니다.

```bash
kubectl describe hpa sentiment-api -n prod
```

**기대 항목** (출력의 일부):

```
Metrics:
  resource cpu on pods  (as a percentage of request):  2% (10m) / 70%
Min replicas:           2
Max replicas:           8
Behavior:
  Scale Up:
    Stabilization Window: 0 seconds
    Select Policy:        Max
    Policies:
      - Type: Percent  Value: 100  Period: 60 seconds
  Scale Down:
    Stabilization Window: 300 seconds
```

✅ behavior 블록이 [values-prod.yaml](../../01-helm-chart/manifests/chart/sentiment-api/values-prod.yaml) 의 비대칭 정책 (scaleUp 0s, scaleDown 300s) 그대로 렌더된 것을 확인합니다.

---

## Step 3. hey-job 부하 부여 → resource HPA 동작 관찰

이제 부하를 주고 HPA 의 desired 가 올라가는지 봅니다. **두 개의 터미널** 을 사용합니다.

**터미널 A — 부하 부여**:

```bash
kubectl apply -f manifests/load-test/hey-job.yaml
kubectl get pod -n prod -l purpose=load-test
```

**예상 출력**:

```
job.batch/hey-load created
NAME             READY   STATUS    RESTARTS   AGE
hey-load-xxxxx   1/1     Running   0          5s
```

**터미널 B — HPA 와 Pod 변화 추적**:

```bash
kubectl get hpa,deploy,pod -n prod -w
```

**예상 변화 (60–90초 사이)**:

```
NAME                                                REFERENCE                  TARGETS    REPLICAS
horizontalpodautoscaler.autoscaling/sentiment-api   Deployment/sentiment-api   2%/70%     2
horizontalpodautoscaler.autoscaling/sentiment-api   Deployment/sentiment-api   85%/70%    2     ← 부하 인식
horizontalpodautoscaler.autoscaling/sentiment-api   Deployment/sentiment-api   85%/70%    3     ← scale-out 시작
horizontalpodautoscaler.autoscaling/sentiment-api   Deployment/sentiment-api   72%/70%    4
horizontalpodautoscaler.autoscaling/sentiment-api   Deployment/sentiment-api   60%/70%    5
```

scale-out 이벤트도 함께 확인합니다.

```bash
kubectl get events -n prod --field-selector reason=SuccessfulRescale --sort-by=.lastTimestamp
```

**예상 출력**:

```
LAST SEEN   TYPE     REASON              OBJECT                              MESSAGE
60s         Normal   SuccessfulRescale   horizontalpodautoscaler/sentiment-api   New size: 3; reason: cpu resource utilization (percentage of request) above target
30s         Normal   SuccessfulRescale   horizontalpodautoscaler/sentiment-api   New size: 4; reason: cpu resource utilization (percentage of request) above target
```

✅ **설명**: hey 가 50 동시 접속 × 60초로 Pod 의 CPU 를 70% 이상으로 올림 → HPA 컨트롤러가 desired 계산 → Deployment.replicas patch → ReplicaSet 이 새 Pod 생성. 새 Pod 는 readinessProbe (Phase 1/04 부터의 24×5s 모델 로딩 여유) 통과 후에야 Service 로 트래픽이 라우팅됩니다 — 그래서 첫 scale-out 후 효과가 즉시 보이지 않을 수 있습니다.

> 💡 `kubectl top pod -n prod` 로 각 Pod 의 실 CPU 도 함께 보면 *어떤 Pod 가 평균을 올렸는지* 직관적으로 보입니다. 50 동시 접속 정도면 보통 Pod 당 250–400m 가 측정됩니다 (requests 500m 의 50–80%).

---

## Step 4. 부하 종료 후 scaleDown stabilization 관찰

hey-job 이 끝날 때까지 기다린 뒤, **즉시 축소되지 않는 것** 이 정상임을 확인합니다.

```bash
kubectl wait --for=condition=complete job/hey-load -n prod --timeout=120s
echo "===== hey-load completed at $(date) ====="
```

**예상 출력**:

```
job.batch/hey-load condition met
===== hey-load completed at 화 5  4 12:34:56 KST 2026 =====
```

이제 5분간 HPA / Deployment 변화를 관찰합니다.

```bash
watch -n 10 'kubectl get hpa,deploy -n prod && echo --- && date'
```

**예상 변화 (시간순)**:

| 시간 | HPA TARGETS | REPLICAS | 의미 |
|-----|------------|---------|------|
| 0분 | 5%/70% | 5 | 부하 종료, 평균 CPU 급락 |
| 1분 | 3%/70% | 5 | desired 가 줄지만 stabilization 윈도우가 *아직* desired 의 max 유지 중 |
| 3분 | 2%/70% | 5 | 동일 |
| 5분+ | 2%/70% | 4 | stabilization 윈도우 (300s) 만료 → 점진 축소 시작 |
| 8분 | 2%/70% | 2 | minReplicas 도달 → 더 이상 축소 안 함 |

✅ **설명**: 부하가 끝나자마자 Pod 가 줄지 *않는* 것이 *정상* 입니다. `behavior.scaleDown.stabilizationWindowSeconds: 300` 이 정확히 이 효과를 만듭니다 — ML 추론은 cold start 비용이 커서 트래픽 잔파동마다 죽었다 살리면 latency 가 spike 합니다 (lesson.md 자주 하는 실수 3번). minReplicas 2 까지 도달하는 데 보통 8–10분 정도 걸립니다.

> 💡 학습 시간을 절약하고 싶으면 `--set autoscaling.behavior.scaleDown.stabilizationWindowSeconds=60` 으로 helm upgrade 해서 1분으로 단축 가능. 단 prod 에서는 절대 그렇게 하지 않습니다.

---

## Step 5. 왜 CPU 만으론 부족한가 — Grafana 와 함께 보기

Phase 3/02 의 Grafana 대시보드와 본 토픽의 HPA replicas 를 *함께* 보면 CPU 신호의 한계가 시각적으로 드러납니다.

```bash
# 별도 터미널 (또는 백그라운드)
kubectl port-forward -n monitoring svc/prom-grafana 3000:80
```

브라우저로 `http://localhost:3000` 접속 → 로그인 (`admin` / `prom-operator`) → Phase 3/02 에서 import 한 *Sentiment API — ML 추론 SLO* 대시보드 열기.

또 하나의 터미널에서 다시 hey-job 을 부여하고 (`kubectl delete job hey-load -n prod && kubectl apply -f manifests/load-test/hey-job.yaml`) 다음 두 신호를 비교합니다.

| 시점 | 패널 1 (req rate) | HPA replicas |
|-----|------------------|-------------|
| t = 0s | 0 | 2 |
| t = 5s | 50 req/s 즉시 도달 | 2 (CPU 가 아직 70% 못 미침) |
| t = 30s | 50 req/s 유지 | 2 (CPU 평균이 60% 부근에서 진동) |
| t = 60s | 50 req/s 유지 | 3 (드디어 평균 CPU 70% 돌파) |
| t = 90s | 50 req/s 유지 | 4 |

✅ **설명**: 패널 1 의 req rate 은 즉시 50 req/s 로 점프하지만, HPA 의 replicas 는 60–90초 *지연* 후에야 반응합니다. 그 사이의 60초가 **사용자가 latency spike 를 겪는 구간** 입니다. 이 lag 가 lesson.md 1-6 절의 결론 (req/s HPA 가 CPU HPA 보다 직접적) 의 시각적 근거입니다.

---

## Step 6. prometheus-adapter 설치

이제 lab 5 에서 본 lag 를 줄여 봅니다 — Prometheus 가 이미 가지고 있는 `predict_requests_total` 시계열을 HPA 가 *직접* 소비하게 만드는 것이 prometheus-adapter 의 역할입니다.

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

helm install prom-adapter prometheus-community/prometheus-adapter \
  -n monitoring \
  -f manifests/prometheus-adapter/values.yaml
```

**예상 출력**:

```
"prometheus-community" has been added to your repositories
...Successfully got an update from the "prometheus-community" chart repository
NAME: prom-adapter
LAST DEPLOYED: ...
NAMESPACE: monitoring
STATUS: deployed
REVISION: 1
```

설치 직후 Pod 가 Running 으로 가는지, APIService 가 등록되는지 확인합니다.

```bash
kubectl get pods -n monitoring -l app.kubernetes.io/name=prometheus-adapter
kubectl get apiservice v1beta1.custom.metrics.k8s.io
```

**예상 출력**:

```
NAME                            READY   STATUS    RESTARTS   AGE
prom-adapter-xxxxxxxxx-yyyyy    1/1     Running   0          45s
```

```
NAME                            SERVICE                          AVAILABLE   AGE
v1beta1.custom.metrics.k8s.io   monitoring/prom-adapter          True        45s
```

✅ **설명**: APIService 가 Available=True 면 K8s API 서버가 `/apis/custom.metrics.k8s.io/v1beta1` 요청을 prom-adapter 에 위임할 준비를 마친 것입니다. 만약 `Available=False` 가 30초 이상 지속되면 `kubectl logs -n monitoring deploy/prom-adapter` 의 에러 라인 확인 (가장 흔한 원인은 prometheus.url 의 서비스명 오타).

---

## Step 7. custom 메트릭이 API 로 노출되는지 raw 호출로 검증

```bash
kubectl get --raw "/apis/custom.metrics.k8s.io/v1beta1/namespaces/prod/pods/*/predict_requests_per_second" | jq
```

**예상 출력 (idle 상태)**:

```json
{
  "kind": "MetricValueList",
  "apiVersion": "custom.metrics.k8s.io/v1beta1",
  "metadata": {},
  "items": [
    {
      "describedObject": {
        "kind": "Pod",
        "namespace": "prod",
        "name": "sentiment-api-7c96f7c84d-abcde",
        "apiVersion": "/v1"
      },
      "metricName": "predict_requests_per_second",
      "timestamp": "2026-05-04T03:30:00Z",
      "value": "0",
      "selector": null
    },
    {
      "describedObject": {
        "kind": "Pod",
        ...
      },
      "metricName": "predict_requests_per_second",
      "value": "0"
    }
  ]
}
```

✅ **설명**: `items` 배열에 prod 네임스페이스의 sentiment-api Pod 개수만큼 (보통 2개) 항목이 있어야 합니다. 부하가 없으면 `value: "0"`. 부하 중에는 `"5"`, `"2500m"` 같이 K8s `Quantity` 형식으로 옵니다 (`m` = milli = 1/1000, 즉 `2500m` = 2.5 req/s/Pod).

> ⚠️ `items: []` 빈 배열이 반환되면 `seriesQuery` 또는 `resources.overrides` 가 라벨 매칭에 실패한 것입니다 — lesson.md **자주 하는 실수 2번** 시나리오. 디버깅:
>
> ```bash
> # ① Prometheus 가 시리즈를 갖고 있는가
> kubectl port-forward -n monitoring svc/prom-kube-prometheus-stack-prometheus 9090:9090
> # 브라우저 localhost:9090 ▶ Graph ▶ predict_requests_total → 라벨 namespace, pod 가 보이는지
>
> # ② adapter 의 결정 로그 확인
> kubectl logs -n monitoring deploy/prom-adapter --tail=50
> ```

---

## Step 8. 두 번째 HPA 적용 — 같은 Deployment 에 HPA 둘

```bash
kubectl apply -f manifests/hpa-custom-metric.yaml
kubectl get hpa -n prod
```

**예상 출력**:

```
horizontalpodautoscaler.autoscaling/sentiment-api-rps created
```

```
NAME                 REFERENCE                  TARGETS                MINPODS   MAXPODS   REPLICAS
sentiment-api        Deployment/sentiment-api   2%/70%                 2         8         2
sentiment-api-rps    Deployment/sentiment-api   0/10                   2         8         2
```

✅ **설명**: 같은 Deployment 에 HPA 가 두 개 붙어 있습니다. K8s 공식 가이드는 *지원하지 않음* 으로 표기하지만 실제 동작은 — 매 sync 주기마다 두 컨트롤러가 각자 desired 를 계산해 Deployment.replicas 를 patch 하고, *마지막에 patch 한 값이 이김*. 결과적으로 두 HPA 의 desired 중 *주기상 더 큰 값* 이 보통 채택됩니다 (정확히 "Max" 가 아니라 "최근 patch 우선" 임을 명심).

> ⚠️ **production 에서는 한 Deployment 에 HPA 하나** — `metrics: []` 에 여러 신호 (Resource CPU + Pods RPS) 를 *함께* 묶는 것이 표준입니다. 본 lab 의 두-HPA 구성은 *학습용 시각화* 목적입니다.

---

## Step 9. 다시 부하 → 어느 HPA 가 먼저 트리거하나

```bash
kubectl delete job hey-load -n prod --ignore-not-found
kubectl apply -f manifests/load-test/hey-job.yaml
kubectl get hpa -n prod -w
```

**예상 변화 (15–30초 사이)**:

```
NAME                 TARGETS                REPLICAS
sentiment-api        2%/70%                 2
sentiment-api-rps    0/10                   2
sentiment-api-rps    25/10                  2     ← RPS HPA 가 먼저 임계 돌파
sentiment-api-rps    25/10                  4     ← RPS HPA 가 desired=4 patch
sentiment-api        20%/70%                4     ← CPU HPA 는 그제서야 메트릭 수집 (여전히 70% 미만)
sentiment-api-rps    12/10                  4
sentiment-api        70%/70%                4     ← CPU HPA 도 따라옴
sentiment-api-rps    12/10                  5
```

```bash
kubectl describe hpa sentiment-api-rps -n prod
```

**기대 항목**:

```
Metrics:
  "predict_requests_per_second" on pods:  12 / 10
Min replicas:           2
Max replicas:           8
Conditions:
  Type            Status   Reason            Message
  AbleToScale     True     ReadyForNewScale  recommended size matches current size
  ScalingActive   True     ValidMetricFound  the HPA was able to successfully calculate a replica count from pods metric predict_requests_per_second
Events:
  Type    Reason             Age   From                       Message
  Normal  SuccessfulRescale  20s   horizontal-pod-autoscaler  New size: 4; reason: pods metric predict_requests_per_second above target
```

✅ **설명**: RPS HPA 의 `ScalingActive=True` 와 `Events: SuccessfulRescale ... pods metric ... above target` 라인이 보이면 success. RPS HPA 가 CPU HPA 보다 *빨리* 트리거되는 이유: ① req/s 는 즉시 측정 가능 (rate window 2분이지만 첫 30초만 지나도 신호가 잡힘), ② CPU 는 평균이 임계치 70% 까지 올라오는 데 60–90초 걸리는 워크로드가 많음. 이것이 lesson.md 1-6 절 결론의 *직접적인 증거* 입니다.

---

## Step 10. 정리

본 토픽이 추가한 자원만 정리합니다 — Phase 3/01 차트와 Phase 3/02 monitoring stack 은 다음 토픽 (Phase 3/04 RBAC) 이 사용하므로 *보존* 합니다.

```bash
# 두 번째 HPA + 부하 Job 제거
kubectl delete -f manifests/hpa-custom-metric.yaml
kubectl delete job hey-load -n prod --ignore-not-found

# prometheus-adapter 제거 — custom.metrics.k8s.io API 도 함께 사라짐
helm uninstall prom-adapter -n monitoring

# 01 차트의 CPU HPA 는 그대로 두어도 무방. 끄려면:
# helm upgrade sentiment-api ../01-helm-chart/manifests/chart/sentiment-api \
#   -n prod \
#   -f ../01-helm-chart/manifests/chart/sentiment-api/values-prod.yaml \
#   --set autoscaling.enabled=false \
#   --set secrets.hfToken=$HF_TOKEN

# 정리 검증
kubectl get hpa -n prod
kubectl get apiservice v1beta1.custom.metrics.k8s.io 2>&1 | tail -1
kubectl get jobs -n prod
```

**예상 출력**:

```
NAME            REFERENCE                  TARGETS    MINPODS   MAXPODS   REPLICAS
sentiment-api   Deployment/sentiment-api   2%/70%     2         8         2
```

```
Error from server (NotFound): apiservices.apiregistration.k8s.io "v1beta1.custom.metrics.k8s.io" not found
```

```
No resources found in prod namespace.
```

✅ **확인 포인트**: HPA 는 (CPU 기반 1개) 만 남고, custom.metrics.k8s.io APIService 는 사라지고, 부하 Job 은 정리되었습니다. Phase 3/02 monitoring stack 과 sentiment-api Deployment 는 그대로 살아 있어야 합니다.

---

## 트러블슈팅

| 증상 | 진단 명령 | 가능 원인 |
|-----|----------|---------|
| HPA TARGETS 가 영원히 `<unknown>/70%` | `kubectl describe hpa sentiment-api -n prod` Events | metrics-server 미설치 / Pod 의 resources.requests.cpu 누락 (lesson.md 자주 하는 실수 1번) |
| `kubectl top pod` 가 `Metrics API not available` | `kubectl get apiservice v1beta1.metrics.k8s.io` | metrics-server 가 아직 첫 메트릭 수집 전 (1–2분 대기) 또는 addon 비활성 |
| custom.metrics.k8s.io 의 items 가 빈 배열 | `kubectl logs -n monitoring deploy/prom-adapter --tail=50` / Prometheus UI 에서 시리즈 라벨 확인 | seriesQuery 라벨 미스매치 (lesson.md 자주 하는 실수 2번) |
| hey-job 이 즉시 실패 | `kubectl logs job/hey-load -n prod` | sentiment-api Service DNS 미해석 / Service 가 prod ns 에 없음 / payload JSON 문법 |
| 부하 종료 직후 replicas 가 곧장 줄어듦 | `kubectl describe hpa sentiment-api -n prod` Behavior | scaleDown.stabilizationWindowSeconds 가 0 으로 잘못 설정됨 (lesson.md 자주 하는 실수 3번) |

## 다음 단계

본 토픽 완료 후 [docs/course-plan.md](../../../docs/course-plan.md) 의 03-autoscaling-hpa minikube 검증 체크박스를 `[x]` 로 갱신합니다. 그리고 다음 토픽으로 이동:

➡️ [Phase 3 / 04-rbac-serviceaccount](../../04-rbac-serviceaccount/lesson.md) (작성 예정)
