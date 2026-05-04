# Phase 3 / 02 — Prometheus + Grafana 실습

본 실습은 [lesson.md](../lesson.md) 의 5개 학습 목표를 9단계로 검증합니다. 각 단계는 **명령 → 예상 출력 → ✅ 설명** 순서로 정렬되어 있어, 본인 환경의 출력과 비교하면서 진행하세요.

> 🧱 **전제**: [Phase 3/01 Helm 차트](../../01-helm-chart/lesson.md) 의 lab 까지 완료되어 minikube 에 `dev` / `prod` namespace 가 살아 있고, prod release `sentiment-api` 가 Running 상태여야 합니다. 안 그러면 0단계에서 막힙니다.

| 단계 | 내용 | 소요 |
|-----|------|------|
| 0 | 사전 점검 (minikube / 01 prod release / 도구 버전) | 5분 |
| 1 | kube-prometheus-stack 설치 | 5분 (이미지 pull 포함) |
| 2 | Prometheus / Grafana UI 첫 접속 | 2분 |
| 3 | sentiment-api `/metrics` raw 출력 확인 | 3분 |
| 4 | servicemonitor.yaml 활성화 (`helm upgrade`) | 3분 |
| 5 | Targets UP 확인 + `up` PromQL | 5분 |
| 6 | PromQL 4쿼리 직접 작성 | 10분 |
| 7 | Grafana 대시보드 import | 5분 |
| 8 | 부하 부여 + 패널 변화 관찰 | 7분 |
| 9 | 정리 (kube-prometheus-stack 만 제거) | 2분 |

---

## 0. 사전 점검

### 0-1. minikube 와 도구 버전

```bash
minikube status
kubectl version --client --short
helm version --short
```

```
# 예상 출력
minikube
type: Control Plane
host: Running
kubelet: Running
apiserver: Running
kubeconfig: Configured

Client Version: v1.30.0
Server Version: v1.30.0

v3.14.0+g...
```

✅ minikube 가 Running, kubectl / helm 이 둘 다 호출 가능.

> 💡 minikube 가 Stopped 면 `minikube start --memory=4096 --cpus=4` 로 시작 (RAM 권장 4Gi 이상 — lesson.md 자주 하는 실수 3번 참고).

### 0-2. 01-helm-chart 의 prod release 가 살아 있는지

```bash
helm list -n prod
kubectl get pods -n prod -l app.kubernetes.io/name=sentiment-api
```

```
# 예상 출력
NAME            NAMESPACE  REVISION  UPDATED                STATUS    CHART
sentiment-api   prod       1         2026-...               deployed  sentiment-api-0.1.0

NAME                              READY   STATUS    RESTARTS   AGE
sentiment-api-7c8f6b9d8-abcde     1/1     Running   0          15m
```

✅ release `sentiment-api` 가 prod 에 1건 존재, Pod 1개 Running.

> ⚠️ **prod release 가 없으면**: [Phase 3/01 lab 6단계](../../01-helm-chart/labs/README.md) 를 먼저 실행해 prod 배포를 만들고 오세요. 본 토픽의 ServiceMonitor 가 prod 의 sentiment-api Service 를 스크래핑 대상으로 삼습니다.

### 0-3. metrics-server addon (선택, 권장)

```bash
minikube addons enable metrics-server
kubectl top pod -n prod
```

```
# 예상 출력
metrics-server was successfully enabled

NAME                              CPU(cores)   MEMORY(bytes)
sentiment-api-7c8f6b9d8-abcde     5m           520Mi
```

✅ Pod 의 실제 자원 사용량이 보임. lab 1 단계에서 kube-prometheus-stack 설치 후 monitoring namespace Pod 들의 CPU / 메모리 확인에 사용합니다.

---

## 1. kube-prometheus-stack 설치

### 1-1. Helm 저장소 추가

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update prometheus-community
```

```
# 예상 출력
"prometheus-community" has been added to your repositories
Hang tight while we grab the latest from your chart repositories...
...Successfully got an update from the "prometheus-community" chart repository
Update Complete. ⎈Happy Helming!⎈
```

✅ 저장소가 추가되고 인덱스 캐시가 최신.

### 1-2. 차트 install (학습용 values.yaml 사용)

> ⚠️ **이미지 pull 에 1 ~ 3분 소요** — Prometheus / Grafana / Operator / kube-state-metrics 이미지가 처음 pull 됩니다. 다음 명령을 실행하고 1단계 끝까지 진행한 뒤 1-4 절에서 다시 상태를 확인하세요.

```bash
helm install prom prometheus-community/kube-prometheus-stack \
  -n monitoring --create-namespace \
  -f course/phase-3-production/02-prometheus-grafana/manifests/kube-prometheus-stack/values.yaml \
  --version 60.0.0
```

```
# 예상 출력
NAME: prom
LAST DEPLOYED: ...
NAMESPACE: monitoring
STATUS: deployed
REVISION: 1
NOTES:
kube-prometheus-stack has been installed. Check its status by running:
  kubectl --namespace monitoring get pods -l "release=prom"
...
```

✅ release 이름 `prom`, namespace `monitoring`, status `deployed`.

> 💡 `--version 60.0.0` 을 명시하는 이유: 차트 메이저 버전이 올라가면 일부 values 키가 바뀝니다. 본 실습은 60.x 기준으로 검증되었습니다. 지정 안 하면 최신이 들어와 `unknown field` 오류 가능.

### 1-3. 설치된 자원 확인

```bash
kubectl get pods -n monitoring
```

```
# 예상 출력 (1 ~ 3분 후)
NAME                                                     READY   STATUS    RESTARTS   AGE
prom-grafana-6d4b6d5f7-xyz12                             3/3     Running   0          2m
prom-kube-prometheus-stack-operator-7c9b8f6d5-abcde      1/1     Running   0          2m
prom-kube-state-metrics-5f8d9c4b7-defgh                  1/1     Running   0          2m
prom-prometheus-node-exporter-tlmnq                      1/1     Running   0          2m
prometheus-prom-kube-prometheus-stack-prometheus-0       2/2     Running   0          90s
```

✅ Operator / Prometheus 서버 / Grafana / kube-state-metrics / node-exporter 5종이 모두 Running.

> 💡 `prometheus-prom-...-0` 의 `-0` 접미사는 Prometheus 서버가 **StatefulSet** 으로 떠 있다는 신호입니다 (Operator 가 자동 생성). `prom-grafana` 의 `3/3` 은 sidecar (대시보드 / 데이터소스 자동 등록용) 가 함께 들어 있다는 의미.

### 1-4. CRD 가 들어왔는지 확인

```bash
kubectl get crd | grep monitoring.coreos.com
```

```
# 예상 출력
alertmanagerconfigs.monitoring.coreos.com         ...
alertmanagers.monitoring.coreos.com               ...
podmonitors.monitoring.coreos.com                 ...
probes.monitoring.coreos.com                      ...
prometheusagents.monitoring.coreos.com            ...
prometheuses.monitoring.coreos.com                ...
prometheusrules.monitoring.coreos.com             ...
scrapeconfigs.monitoring.coreos.com               ...
servicemonitors.monitoring.coreos.com             ...
thanosrulers.monitoring.coreos.com                ...
```

✅ ServiceMonitor 등 핵심 CRD 가 들어옴. lab 4 단계에서 sentiment-api 에 ServiceMonitor 자원을 만들면 Operator 가 watch 합니다.

---

## 2. Prometheus / Grafana UI 첫 접속

### 2-1. Prometheus 포트포워딩 (별도 터미널)

```bash
kubectl port-forward -n monitoring svc/prom-kube-prometheus-stack-prometheus 9090:9090
```

```
# 예상 출력
Forwarding from 127.0.0.1:9090 -> 9090
Forwarding from [::1]:9090 -> 9090
```

✅ 브라우저에서 http://localhost:9090 → Prometheus UI 가 뜸.

> 💡 이 터미널은 lab 6 까지 계속 열어두세요. 닫으면 Prometheus UI 가 끊깁니다.

### 2-2. Grafana 포트포워딩 (또 다른 터미널)

```bash
kubectl port-forward -n monitoring svc/prom-grafana 3000:80
```

```
# 예상 출력
Forwarding from 127.0.0.1:3000 -> 3000
Forwarding from [::1]:3000 -> 3000
```

✅ 브라우저에서 http://localhost:3000 → Grafana 로그인 화면.

### 2-3. Grafana 첫 로그인

브라우저에서 http://localhost:3000 접속 후:
- **Email or username**: `admin`
- **Password**: `prom-operator` (본 토픽 [values.yaml](../manifests/kube-prometheus-stack/values.yaml) `grafana.adminPassword`)

✅ 첫 로그인 후 비밀번호 변경 화면이 뜨면 *Skip* 또는 임의 값 입력. 학습 환경이라 무관.

> ⚠️ **운영 환경에선 절대 이 비밀번호를 쓰지 마세요** — 본 values 는 학습용입니다. 운영은 `existingSecret` 으로 주입.

### 2-4. Grafana 의 자동 등록된 Datasource 확인

Grafana UI ▶ 좌측 햄버거 메뉴 ▶ **Connections ▶ Data sources**

```
# 화면 표시
Prometheus  default  http://prom-kube-prometheus-stack-prometheus.monitoring:9090
```

✅ kube-prometheus-stack 의 sidecar 가 Prometheus 데이터소스를 자동 등록. lab 7 단계의 대시보드 import 가 이 데이터소스를 사용합니다.

---

## 3. sentiment-api `/metrics` raw 출력 확인

ServiceMonitor 를 활성화하기 전에, **메트릭이 실제로 노출되는지** 직접 확인합니다. ServiceMonitor 는 단지 "스크래핑해라" 는 *선언* 일 뿐, 메트릭 자체가 없으면 의미가 없습니다.

### 3-1. sentiment-api Pod 에 직접 port-forward

```bash
# 또 다른 터미널
kubectl port-forward -n prod svc/sentiment-api 8000:80
```

```
# 예상 출력
Forwarding from 127.0.0.1:8000 -> 8000
```

### 3-2. 메트릭 raw 출력

```bash
curl -s http://localhost:8000/metrics | grep -E "^predict_"
```

```
# 예상 출력 (요청을 한 번도 안 했다면 일부 메트릭이 0)
# HELP predict_requests_total Total /predict requests
# TYPE predict_requests_total counter
predict_requests_total{status="ok"} 0.0
# HELP predict_latency_seconds Latency of /predict in seconds
# TYPE predict_latency_seconds histogram
predict_latency_seconds_bucket{le="0.005"} 0.0
predict_latency_seconds_bucket{le="0.01"} 0.0
...
predict_latency_seconds_bucket{le="+Inf"} 0.0
predict_latency_seconds_count 0.0
predict_latency_seconds_sum 0.0
```

✅ Counter (`predict_requests_total`) 와 Histogram (`predict_latency_seconds_bucket` / `_count` / `_sum`) 이 모두 노출됨.

> 💡 `_bucket{le="..."}` 라인이 lesson.md 1-3 절의 *Histogram* 그 자체입니다. `histogram_quantile` 이 이 bucket 들을 보고 p95 를 추정합니다. 요청을 한 번도 안 했으면 모두 0 → p95 는 NaN → Grafana 'No data' (자주 하는 실수 2번).

### 3-3. 한 번 호출해서 메트릭이 증가하는지 확인

```bash
curl -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{"text": "I love Kubernetes!"}'
```

```
# 예상 출력
{"label":"positive","score":0.978...}
```

```bash
curl -s http://localhost:8000/metrics | grep predict_requests_total
```

```
# 예상 출력
# HELP predict_requests_total Total /predict requests
# TYPE predict_requests_total counter
predict_requests_total{status="ok"} 1.0
```

✅ Counter 가 1 로 증가. 본 토픽의 모든 PromQL 쿼리는 이 카운터의 변화량(`rate`) 위에 얹힙니다.

> 💡 3-1 의 port-forward 터미널은 이제 닫아도 됩니다 (lab 4 부터는 Prometheus 가 클러스터 내부에서 직접 스크래핑).

---

## 4. ServiceMonitor 활성화

### 4-1. 01 차트의 새 파일 (servicemonitor.yaml) 확인

```bash
ls -la course/phase-3-production/01-helm-chart/manifests/chart/sentiment-api/templates/
```

```
# 예상 출력
total ...
-rw-r--r-- 1 ... NOTES.txt
-rw-r--r-- 1 ... _helpers.tpl
-rw-r--r-- 1 ... configmap.yaml
-rw-r--r-- 1 ... deployment.yaml
-rw-r--r-- 1 ... pvc.yaml
-rw-r--r-- 1 ... secret.yaml
-rw-r--r-- 1 ... service.yaml
-rw-r--r-- 1 ... servicemonitor.yaml          ← 본 토픽이 추가한 파일
```

✅ `servicemonitor.yaml` 이 templates 에 들어와 있음. 단, [values.yaml](../../01-helm-chart/manifests/chart/sentiment-api/values.yaml) 의 `monitoring.serviceMonitor.enabled: false` 라 아직 렌더되지 않습니다.

### 4-2. helm template 으로 렌더 결과 미리 보기 (디버깅)

```bash
helm template sentiment-api course/phase-3-production/01-helm-chart/manifests/chart/sentiment-api \
  --set monitoring.serviceMonitor.enabled=true \
  --show-only templates/servicemonitor.yaml
```

```
# 예상 출력
---
# Source: sentiment-api/templates/servicemonitor.yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: sentiment-api
  labels:
    helm.sh/chart: sentiment-api-0.1.0
    app.kubernetes.io/name: sentiment-api
    app.kubernetes.io/instance: sentiment-api
    app: sentiment-api
    app.kubernetes.io/version: "v1"
    app.kubernetes.io/managed-by: Helm
    release: prom
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: sentiment-api
      app.kubernetes.io/instance: sentiment-api
      app: sentiment-api
  endpoints:
    - port: http
      path: /metrics
      interval: 30s
      scrapeTimeout: 10s
```

✅ `release: prom` 라벨이 metadata 에 박혀 있고 (Operator 가 발견), `selector.matchLabels` 가 Service 의 라벨과 일치 (Service / Pod 매칭).

> 💡 `helm template` 은 클러스터에 적용하지 않고 렌더 결과만 stdout 으로 보여줍니다. 디버깅 표준 도구.

### 4-3. helm upgrade 로 prod release 에 활성화

```bash
helm upgrade sentiment-api course/phase-3-production/01-helm-chart/manifests/chart/sentiment-api \
  -n prod \
  -f course/phase-3-production/01-helm-chart/manifests/chart/sentiment-api/values-prod.yaml \
  --set monitoring.serviceMonitor.enabled=true \
  --set secrets.hfToken=$HF_TOKEN
```

```
# 예상 출력
Release "sentiment-api" has been upgraded. Happy Helming!
NAME: sentiment-api
LAST DEPLOYED: ...
NAMESPACE: prod
STATUS: deployed
REVISION: 2
```

✅ REVISION 이 2 로 올라감 (1 → 2). ServiceMonitor 자원이 추가됨.

> ⚠️ **`--set secrets.hfToken=$HF_TOKEN` 을 빼지 마세요** — 01 의 values-prod.yaml 가 `secrets.hfToken: ""` 로 비워져 있어, 환경 변수에서 주입하지 않으면 Secret 이 placeholder 로 채워져 다음 Pod 재시작 시 인증 실패할 수 있습니다.

### 4-4. ServiceMonitor 자원 확인

```bash
kubectl get servicemonitor -n prod
kubectl describe servicemonitor sentiment-api -n prod | head -20
```

```
# 예상 출력
NAME            AGE
sentiment-api   30s

Name:         sentiment-api
Namespace:    prod
Labels:       app=sentiment-api
              app.kubernetes.io/instance=sentiment-api
              app.kubernetes.io/managed-by=Helm
              app.kubernetes.io/name=sentiment-api
              app.kubernetes.io/version=v1
              helm.sh/chart=sentiment-api-0.1.0
              release=prom
...
Spec:
  Endpoints:
    Interval:        30s
    Path:            /metrics
    Port:            http
    Scrape Timeout:  10s
  Selector:
    Match Labels:
      app:                       sentiment-api
      app.kubernetes.io/instance: sentiment-api
      app.kubernetes.io/name:     sentiment-api
```

✅ ServiceMonitor 의 `release: prom` 라벨, `endpoints.port: http`, `selector.matchLabels` 모두 정상.

---

## 5. Targets UP 확인 + `up` PromQL

### 5-1. Prometheus UI 의 Targets 페이지

브라우저에서 http://localhost:9090/targets 접속 → 검색창에 `sentiment-api` 입력.

```
# 화면 표시
Endpoint                                                         State    Last Scrape
http://10.244.x.y:8000/metrics  serviceMonitor/prod/sentiment-api/0  UP    15s ago
```

✅ State 가 **UP**. 30초마다 스크래핑 중.

> ⚠️ **State 가 DOWN 또는 안 나타나면**: lesson.md 자주 하는 실수 1번 (라벨 미스매치) 진단 절차를 따르세요. 가장 흔한 원인은 ① ServiceMonitor 의 `release: prom` 라벨 부재, ② Service 의 named port `http` 와 endpoints[0].port 불일치.

### 5-2. PromQL 첫 쿼리 — `up`

Prometheus UI ▶ Graph 탭 ▶ Expression 입력란에 다음을 입력 후 Execute.

```promql
up{job=~".*sentiment-api.*"}
```

```
# 예상 출력 (Table 뷰)
up{container="api", endpoint="http", instance="10.244.x.y:8000",
   job="sentiment-api", namespace="prod", pod="sentiment-api-...",
   service="sentiment-api"}                                       1
```

✅ 값이 1 (UP). 0 이면 스크래핑 실패 → 5-1 의 Targets 페이지에서 *Last Error* 확인.

> 💡 `job` 라벨이 자동으로 `sentiment-api` (Service 이름) 로 잡힙니다. ServiceMonitor 가 명시적으로 `jobLabel` 을 안 줘서 Prometheus 가 디폴트로 Service 이름을 사용.

---

## 6. PromQL 4쿼리 직접 작성

이제 lesson.md 1-4 절의 PromQL 5함수를 실제로 써봅니다. Prometheus UI ▶ Graph 탭에서 차례대로 실행하세요.

### 6-1. Throughput (요청량) — Counter + rate

```promql
sum by (status) (rate(predict_requests_total{namespace="prod"}[2m]))
```

```
# 예상 출력 (요청을 한 번도 안 했다면)
no data
```

✅ 데이터가 없는 게 정상 (lab 8 에서 부하 부여 후 다시 보면 라인이 그려짐).

> 💡 한 번이라도 호출했다면 (`{status="ok"}` 라인이 매우 작은 값으로 표시). `[2m]` 윈도우는 lesson.md 1-4 절 — `interval × 4 = 30s × 4 = 120s` 의 안전 최소.

### 6-2. p95 Latency — Histogram + histogram_quantile

```promql
histogram_quantile(0.95,
  sum by (le) (rate(predict_latency_seconds_bucket{namespace="prod"}[5m]))
)
```

```
# 예상 출력
no data
```

✅ 요청이 거의 없으면 NaN → "no data" (자주 하는 실수 2번).

> 💡 `sum by (le) (...)` 가 핵심. `le` (less-than-or-equal) bucket 라벨을 보존해야 `histogram_quantile` 이 동작합니다. `sum by (status) (...)` 식으로 다른 라벨로 그룹핑하면 NaN.

### 6-3. Error rate (%)

```promql
100 * sum(rate(predict_requests_total{namespace="prod",status=~"error|not_ready"}[5m]))
    / sum(rate(predict_requests_total{namespace="prod"}[5m]))
```

```
# 예상 출력 (요청 0)
no data
```

✅ 분모가 0 이면 결과는 NaN.

> 💡 `=~` 는 정규식 매치. `=` 와 `=~` 의 차이를 구별 못 하면 PromQL 이 점점 어려워집니다 — `=~` 가 멀티 라벨 값 매칭의 표준.

### 6-4. Pod 가용 / 목표 — kube-state-metrics

```promql
kube_deployment_status_replicas_available{namespace="prod",deployment="sentiment-api"}
```

```
# 예상 출력
kube_deployment_status_replicas_available{deployment="sentiment-api",
   namespace="prod"}                                              2
```

✅ 값 2 (prod 의 [values-prod.yaml](../../01-helm-chart/manifests/chart/sentiment-api/values-prod.yaml) `replicaCount: 2`).

> 💡 `kube_deployment_*` 은 모두 kube-state-metrics 가 노출합니다 (Operator 가 자동으로 스크래핑). lab 9 의 `helm uninstall prom` 후엔 사라집니다.

---

## 7. Grafana 대시보드 import

### 7-1. JSON 파일 위치 확인

```bash
ls -la course/phase-3-production/02-prometheus-grafana/manifests/grafana-dashboards/
```

```
# 예상 출력
-rw-r--r-- 1 ... sentiment-api-dashboard.json
```

✅ 본 토픽이 만든 [4 패널 대시보드 JSON](../manifests/grafana-dashboards/sentiment-api-dashboard.json) 이 보임.

### 7-2. Grafana UI 에서 Import

1. Grafana UI (http://localhost:3000) ▶ 좌측 햄버거 메뉴 ▶ **Dashboards**
2. 우측 상단 **New ▼** ▶ **Import**
3. **Upload dashboard JSON file** 클릭 → `sentiment-api-dashboard.json` 선택
4. *DS_PROMETHEUS* 입력란에서 **Prometheus** (lab 2-4 에서 자동 등록된 데이터소스) 선택
5. **Import** 클릭

```
# 화면 표시 — 4 패널 모두 표시
┌─────────────────────────┬─────────────────────────────────┐
│ 요청량 (req/s) — status별 │ Latency p95 / p99 (초)           │
│ [no data]               │ [no data]                        │
├─────────────┬───────────┴─────────────────────────────────┤
│ 에러율 (%)   │ Pod 가용 / 목표 레플리카                       │
│ [no data]   │ available 2 ─────                           │
│             │ desired   2 ─────                           │
└─────────────┴─────────────────────────────────────────────┘
```

✅ 패널 4 (Pod 가용 / 목표) 만 데이터가 있고, 나머지 3개는 *no data* (요청이 없어서). lab 8 에서 부하 부여하면 모두 라인이 그려집니다.

> 💡 좌측 상단의 **Namespace** 드롭다운이 보입니다 — 이것이 lesson.md 1-5 절의 *Variable* 입니다. `prod` ↔ `dev` 토글 가능.

---

## 8. 부하 부여 + 패널 변화 관찰

### 8-1. `hey` 설치 (없다면)

```bash
# macOS
brew install hey
# Linux
go install github.com/rakyll/hey@latest
```

```bash
hey -h | head -3
```

```
# 예상 출력
Usage: hey [options...] <url>

Options:
```

✅ `hey` 가 PATH 에 있음.

### 8-2. sentiment-api 에 30초 부하

prod 의 sentiment-api Service 는 ClusterIP 라 클러스터 외부에서 못 부릅니다. lab 3-1 처럼 port-forward 를 하나 더 띄우거나, `kubectl run` 으로 클러스터 내부에서 부르세요. 아래는 port-forward 방법.

```bash
# 터미널 A — port-forward (계속 열어둠)
kubectl port-forward -n prod svc/sentiment-api 8001:80
```

```bash
# 터미널 B — 부하 부여
hey -z 30s -c 10 -m POST \
  -H "Content-Type: application/json" \
  -d '{"text":"hello kubernetes!"}' \
  http://localhost:8001/predict
```

```
# 예상 출력 (30초 후)
Summary:
  Total:        30.0021 secs
  Slowest:      0.7234 secs
  Fastest:      0.0521 secs
  Average:      0.1832 secs
  Requests/sec: 54.6112

  Total data:   ...
  Size/request: ...

Response time histogram:
  0.052 [1]     |
  0.119 [185]   |■■■■■
  0.186 [820]   |■■■■■■■■■■■■■■■■■■■■■■
  0.253 [421]   |■■■■■■■■■■■
  ...

Status code distribution:
  [200] 1639 responses
```

✅ 1500 ~ 1700 건의 요청이 전부 200 (status=ok). p95 latency 가 0.2 ~ 0.3 초 사이.

### 8-3. Grafana 패널 변화 확인

부하 부여 직후 Grafana 대시보드로 돌아가서 **우측 상단 시간 범위 ▶ Last 5 minutes**, **Refresh ▶ 10s** 로 설정.

```
# 화면 표시 — 부하 후 30 ~ 60초 안에
┌────────────────────────────────────┬───────────────────────────────────┐
│ 요청량 (req/s) — status별            │ Latency p95 / p99 (초)              │
│ ok ──────────────── ~50            │ p95 ──── ~0.25                     │
│                                    │ p99 ──── ~0.40                     │
├────────────────┬───────────────────┴───────────────────────────────────┤
│ 에러율 (%)      │ Pod 가용 / 목표 레플리카                                  │
│ 0.00           │ available 2  desired 2                                │
└────────────────┴───────────────────────────────────────────────────────┘
```

✅ 패널 1 (요청량) 의 *ok* 라인이 ~50 req/s 로 솟음, 패널 2 (latency) p95 / p99 가 라인을 그림.

> 💡 패널이 *no data* 그대로면: ① ServiceMonitor 의 30s interval 때문에 첫 데이터 도달까지 30 ~ 60초 대기 필요. ② Prometheus UI Targets 에서 *Last Scrape* 가 최근인지 확인. ③ Grafana 의 시간 범위가 "Last 15 minutes" 보다 짧으면 데이터가 안 보일 수 있음.

### 8-4. PromQL 로 직접 한 번 더 검증 (옵션)

Prometheus UI ▶ Graph 탭:

```promql
sum by (status) (rate(predict_requests_total{namespace="prod"}[2m]))
```

```
# 예상 출력 (Table 뷰)
{status="ok"}  53.2666...
```

✅ 부하 직후 Grafana 패널과 동일한 값. 단, Grafana 가 Prom 보다 약간 늦게 갱신될 수 있어 패널 = PromQL 정확히 같지 않을 수 있습니다.

---

## 9. 정리

> ⚠️ **prod 의 sentiment-api 는 보존합니다** — Phase 3/03 (HPA) 이 본 토픽의 메트릭을 입력으로 사용. ServiceMonitor 도 그대로 둡니다 (`monitoring.serviceMonitor.enabled=true` 유지).

### 9-1. port-forward 터미널 종료

lab 2-1, 2-2, 8-2 에서 띄운 port-forward 터미널 3개를 모두 `Ctrl-C` 로 종료.

### 9-2. kube-prometheus-stack 만 uninstall

```bash
helm uninstall prom -n monitoring
```

```
# 예상 출력
release "prom" uninstalled
```

```bash
kubectl delete namespace monitoring
```

```
# 예상 출력
namespace "monitoring" deleted
```

✅ Prometheus / Grafana / Operator / kube-state-metrics / node-exporter 모두 제거. CRD 는 자동으로 삭제되지 않습니다 (ServiceMonitor 자원이 사라지지 않게 의도적). 다음 토픽에서 다시 install 해도 CRD 는 재사용됩니다.

### 9-3. 정리 후 상태 확인

```bash
helm list -A
kubectl get crd | grep monitoring.coreos.com
kubectl get servicemonitor -n prod
```

```
# 예상 출력
NAME            NAMESPACE  REVISION  STATUS    CHART
sentiment-api   prod       2         deployed  sentiment-api-0.1.0

alertmanagerconfigs.monitoring.coreos.com         ...
servicemonitors.monitoring.coreos.com             ...
... (그대로 남아있음)

NAME            AGE
sentiment-api   ...
```

✅ kube-prometheus-stack 만 사라지고, sentiment-api 와 그 ServiceMonitor 는 그대로. CRD 도 그대로.

---

## 검증 체크리스트 (lesson.md 와 동일)

- [ ] 0단계: `helm list -n prod` 에 sentiment-api 가 있고 Pod 이 Running
- [ ] 1단계: `kubectl get pods -n monitoring` 5개 컴포넌트 모두 Running
- [ ] 1단계: `kubectl get crd | grep monitoring.coreos.com` 10여 개 CRD 출력
- [ ] 2단계: Grafana http://localhost:3000 admin/prom-operator 로 로그인 성공
- [ ] 3단계: `curl /metrics` 가 `predict_requests_total`, `predict_latency_seconds_bucket` 모두 표시
- [ ] 4단계: `kubectl get servicemonitor -n prod sentiment-api` 1건 출력
- [ ] 5단계: Prometheus UI Targets 에서 sentiment-api **UP**
- [ ] 6단계: PromQL 4개 모두 입력 가능 (요청 0이면 no data 정상)
- [ ] 7단계: Grafana 대시보드 4 패널 표시 (Pod 가용 패널만 데이터 있음)
- [ ] 8단계: hey 부하 후 30 ~ 60초 안에 패널 1, 2 라인 표시
- [ ] 9단계: kube-prometheus-stack 만 정리, sentiment-api 보존

---

## 트러블슈팅

| 증상 | 원인 후보 | 진단 / 해결 |
|------|---------|-----------|
| lab 1 의 Pod 가 Pending 만 반복 | minikube 자원 부족 | `kubectl describe pod -n monitoring <pod>` ▶ Events ▶ `0/1 nodes are available` ▶ `minikube stop && minikube start --memory=4096 --cpus=4` |
| lab 1 helm install 이 `unknown field` 에러 | values 키가 차트 버전과 안 맞음 | `--version 60.0.0` 으로 명시. ArtifactHub 의 차트 페이지에서 본인 버전의 values 스키마 확인 |
| lab 2 Grafana 가 502 / 503 | 첫 기동 1분 대기 부족 | `kubectl logs -n monitoring -l app.kubernetes.io/name=grafana -c grafana` 에 `HTTP Server Listen` 가 보일 때까지 대기 |
| lab 4 helm upgrade 후 ServiceMonitor 가 없음 | `--set monitoring.serviceMonitor.enabled=true` 누락 | `helm get values sentiment-api -n prod` 로 실제 적용된 값 확인 |
| lab 5 Targets 에서 sentiment-api DOWN | Service 의 named port 와 ServiceMonitor.endpoints[].port 불일치 | `kubectl describe svc sentiment-api -n prod` ▶ Ports 의 *Name* 이 `http` 인지 확인 |
| lab 5 Targets 에 sentiment-api 가 아예 없음 | 라벨 미스매치 (Operator → ServiceMonitor) | lesson.md 자주 하는 실수 1번 진단 절차 |
| lab 7 import 후 패널이 *Datasource not found* | 데이터소스 이름이 `Prometheus` 가 아님 | import 단계에서 *DS_PROMETHEUS* 입력란에 본인 환경의 Prometheus 데이터소스 선택 (이름이 다를 수 있음) |
| lab 8 부하 후에도 패널 1 *no data* | scrape interval (30s) × 4 = 2분 대기 필요 | 부하 종료 후 1 ~ 2 분 더 기다리거나, ServiceMonitor 의 `interval` 을 10s 로 줄여 재 upgrade |

---

## 다음 단계

본 lab 후의 클러스터 상태:
- `monitoring` namespace: 제거됨
- `prod/sentiment-api`: REVISION 2, ServiceMonitor 활성 상태 (그대로 보존)
- 01 차트의 `templates/servicemonitor.yaml`: 영구 추가됨

다음 토픽 [Phase 3/03 — HPA 와 부하 테스트](../../03-autoscaling-hpa/lesson.md) 에서:
- 본 토픽의 `predict_requests_total` 메트릭을 HPA 의 입력으로 사용 (커스텀 메트릭 어댑터)
- 본 토픽의 `hey` 명령을 더 강한 부하로 변형해 Pod 자동 증가 / 감소 관찰
- kube-prometheus-stack 을 다시 install 해 본 토픽의 인프라를 재사용 (lab 9 가 CRD 를 남겨둔 이유)
