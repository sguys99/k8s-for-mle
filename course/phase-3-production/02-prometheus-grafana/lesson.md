# Phase 3 / 02 — Prometheus + Grafana 로 추론 SLO 모니터링

> 직전 토픽 [Phase 3/01 Helm 차트](../01-helm-chart/lesson.md) 의 `sentiment-api` 차트가 이미 `monitoring.serviceMonitor.*` placeholder 를 갖고 있고, [Phase 0 의 FastAPI 앱](../../phase-0-docker-review/01-docker-fastapi-model/practice/fastapi_app.py) 은 이미 `prometheus-client` 로 `/metrics` 를 노출하고 있습니다. 본 토픽의 모든 작업은 **이 두 개를 연결** 하는 것 — 코드 수정은 없습니다.

## 학습 목표

1. `kube-prometheus-stack` 을 Helm 으로 설치하고 Prometheus / Grafana / Alertmanager / kube-state-metrics 의 역할을 구분합니다.
2. 01 차트의 `templates/servicemonitor.yaml` 을 활성화해 FastAPI `/metrics` 를 자동 스크래핑되게 합니다.
3. PromQL 핵심 5개 (`rate`, `sum by`, `histogram_quantile`, `increase`, `up`) 로 throughput, p95 latency, error rate 를 계산합니다.
4. Grafana 대시보드 [JSON 파일](manifests/grafana-dashboards/sentiment-api-dashboard.json) 을 import 해 ML 추론 SLO 4 패널 (요청량 · p95/p99 latency · 에러율 · Pod 가용) 을 시각화합니다.
5. ServiceMonitor 가 발견되지 않을 때 Operator 의 라벨 셀렉터 / Service 의 named port / Histogram bucket 측면에서 트러블슈팅합니다.

**완료 기준 (1줄)**: `kubectl get servicemonitor -n prod sentiment-api` 로 1건 확인 + Grafana 대시보드의 *Latency p95* 패널에 라인이 그려지면 완료.

## 왜 ML 엔지니어에게 모니터링이 필요한가

ML 모델 서빙은 일반 웹 서비스와 시그널이 다릅니다. 200 OK 가 돌아온다고 *답이 맞다* 는 보장이 없고, latency 가 정상이라도 *모델이 제대로 추론* 하고 있는지는 별개입니다. ML 운영자가 매일 봐야 하는 시그널은 보통 다음 4종입니다.

| 시그널 | 의미 | 본 토픽 패널 |
|--------|------|------|
| **Throughput** (req/s) | 트래픽 부하. HPA (Phase 3/03) 입력으로 직접 사용 | 패널 1 |
| **Latency p95 / p99** | 사용자가 체감하는 응답 시간 — SLO 의 표준 지표 | 패널 2 |
| **Error rate** | 모델 로딩 실패 / 추론 예외 / not_ready 503 비율 | 패널 3 |
| **Pod 가용성** | 롤링 업데이트 / readinessProbe / OOMKill 의 결과 가시화 | 패널 4 |

GPU / LLM 서빙 (Phase 4) 으로 넘어가면 토큰 처리량, GPU 메모리, KV cache 사용률 같은 지표가 더 추가되지만, 그 기반은 모두 **Prometheus 스크래핑 + PromQL + Grafana 시각화** 라는 동일한 파이프라인 위에 얹힙니다. 본 토픽이 그 파이프라인 자체를 다룹니다.

## 1. 핵심 개념

### 1-1. kube-prometheus-stack 이 깔아주는 것

`prometheus-community/kube-prometheus-stack` 은 *우산 차트* 입니다. 한 번 install 하면 7개 컴포넌트가 함께 들어옵니다.

| 컴포넌트 | 역할 | 본 토픽에서 보는 곳 |
|---------|------|------|
| **Prometheus Operator** | ServiceMonitor / PodMonitor / PrometheusRule CRD 를 watch 해 Prometheus 설정으로 변환 | `kubectl get crd | grep monitoring.coreos.com` |
| **Prometheus 서버** | 메트릭 스크래핑 + TSDB 저장 + PromQL 쿼리 엔진 | port-forward 9090 |
| **Alertmanager** | 알림 라우팅 (본 토픽은 비활성, lab 1 단계 values 참고) | `--`|
| **Grafana** | 대시보드 / 시각화 | port-forward 3000 |
| **node-exporter** | 노드 CPU / 메모리 / 디스크 / 네트워크 메트릭 | `node_cpu_seconds_total` 등 |
| **kube-state-metrics** | K8s 자원 상태 (`kube_pod_status_phase`, `kube_deployment_status_replicas_available` …) | 패널 4 가 사용 |
| **CRDs** | `ServiceMonitor` / `PodMonitor` / `Probe` / `PrometheusRule` / `Alertmanager` | `kubectl explain servicemonitor` |

학습용 [values.yaml](manifests/kube-prometheus-stack/values.yaml) 은 minikube 부담을 낮추기 위해 retention 2일, Alertmanager 비활성, 디폴트 룰 일부 비활성으로 시작합니다. 운영 차트로 이전할 때 바꿀 항목은 같은 파일 하단의 *운영 시 검토 항목* 8개로 정리해 두었습니다.

### 1-2. ServiceMonitor — Operator 의 발견 메커니즘

ServiceMonitor 는 "Service 라벨이 X 인 것을 찾아 그 Service 의 포트 Y 의 path Z 를 N 초마다 스크래핑하라" 는 선언입니다. Operator 가 이걸 watch 해서 Prometheus 의 스크래핑 잡을 자동 생성합니다.

라벨 매칭이 두 단계로 일어납니다.

```
[Operator]                              [ServiceMonitor]                     [Service]
serviceMonitorSelector:        ────►    metadata.labels:           ────►    metadata.labels:
  matchLabels:                            release: prom                       app.kubernetes.io/name: sentiment-api
    release: prom                       spec.selector.matchLabels:            app.kubernetes.io/instance: prod-prom
                                          app.kubernetes.io/name: ...         app: sentiment-api
                                          app: sentiment-api
       (1) Operator 가                    (2) ServiceMonitor 가
           ServiceMonitor 발견                Service / Pod 매칭
```

본 차트의 [servicemonitor.yaml](../01-helm-chart/manifests/chart/sentiment-api/templates/servicemonitor.yaml) 은 이 두 단계 라벨을 모두 만족하도록 설계되어 있습니다 — `metadata.labels.release: prom` 으로 (1) 을 통과, `spec.selector.matchLabels` 가 `_helpers.tpl` 의 `selectorLabels` 를 참조해 (2) 를 통과.

```bash
kubectl explain servicemonitor.spec --recursive | head -30
# spec 의 endpoints[].port (named port), interval, path, scrapeTimeout 가 본 토픽이 다루는 핵심 필드
```

### 1-3. ML 메트릭 4종 패턴

prometheus-client 가 노출하는 메트릭 타입은 4가지입니다. ML 추론 API 가 뭘 어디에 쓰는지 알면 PromQL 쿼리가 쉬워집니다.

| 타입 | 의미 | 추론 API 사용 예 | PromQL 패턴 |
|-----|------|-----------------|-------------|
| **Counter** | 단조 증가 (요청 수 / 에러 수) | `predict_requests_total{status}` | `rate()`, `increase()` |
| **Histogram** | 분포 (latency / response size) | `predict_latency_seconds` (`_bucket`/`_count`/`_sum`) | `histogram_quantile()` |
| **Gauge** | 즉시값 (큐 길이 / GPU 메모리) | (Phase 4 vLLM `vllm:num_requests_running`) | 그대로 / `avg_over_time()` |
| **Summary** | 클라이언트가 quantile 직접 계산 | (LLM 토큰 분포 등 — 본 코스에선 거의 안 씀) | quantile 라벨 직접 |

[fastapi_app.py](../../phase-0-docker-review/01-docker-fastapi-model/practice/fastapi_app.py) 는 두 메트릭을 정의합니다.

```python
# fastapi_app.py:38-43 (이미 정의되어 있음 — 본 토픽에서 코드 수정 없음)
REQUEST_COUNT = Counter(
    "predict_requests_total", "Total /predict requests", ["status"]
)
REQUEST_LATENCY = Histogram(
    "predict_latency_seconds", "Latency of /predict in seconds"
)
```

`Histogram` 의 bucket 은 prometheus-client 디폴트 (5ms ~ 10s) 를 사용합니다. ML 추론은 모델/입력 크기에 따라 분포가 다르니 운영 단계에서 본인의 latency 분포에 맞게 bucket 을 조정하는 것이 자주 하는 실수 2번에서 다룹니다.

### 1-4. PromQL 핵심 5개

본 토픽이 다루는 모든 패널은 다음 5개로 표현됩니다.

| 함수 | 사용 예 | 의미 |
|-----|--------|------|
| `rate(metric[2m])` | `rate(predict_requests_total[2m])` | 2분 윈도우의 초당 평균 증가율. **Counter 에만** 사용 |
| `sum by (label) (...)` | `sum by (status) (rate(...[2m]))` | 라벨로 그룹핑 후 합 |
| `histogram_quantile(0.95, ...)` | `histogram_quantile(0.95, sum by (le) (rate(predict_latency_seconds_bucket[5m])))` | Histogram 의 p95 추정. `le` (less-than-or-equal) bucket 라벨 보존 필수 |
| `increase(metric[1h])` | `increase(predict_requests_total[1h])` | 1시간 누적 증가량. 점검 / 캡스톤 보고서용 |
| `up{job="..."}` | `up{job="prod/sentiment-api"}` | 스크래핑 성공 여부 (1=UP, 0=DOWN). lab 5 단계가 가장 먼저 보는 쿼리 |

> 💡 `rate()` 는 반드시 **window 가 scrape interval × 4 이상** 이어야 정확. ServiceMonitor `interval: 30s` 면 `rate(...[2m])` 가 안전한 최소.

### 1-5. Grafana 대시보드 구조

대시보드는 3개 레벨로 구성됩니다.

```
Dashboard
├── Variable (templating)        ← lab 7 단계: $namespace 변수로 dev / prod 토글
└── Panel
    ├── Datasource              ← kube-prometheus-stack 이 Prom 을 자동 등록
    ├── Query (PromQL)          ← 1-4 절의 5개 함수
    └── Visualization (timeseries / stat / table / ...)
```

본 토픽의 [sentiment-api-dashboard.json](manifests/grafana-dashboards/sentiment-api-dashboard.json) 은 4 패널 + 1 변수 (`$namespace`) 구조입니다. 학습자가 직접 복제 / 수정하기 좋은 단순한 형태로 의도했습니다.

## 2. 실습 개요

전체 절차는 [labs/README.md](labs/README.md) 에 0 ~ 9 단계로 작성되어 있습니다. 본 lesson.md 에서는 흐름만 요약합니다.

| 단계 | 내용 | 검증 |
|-----|------|------|
| 0 | minikube 기동 + 01-helm-chart 의 prod release 가 살아 있는지 확인 | `helm list -n prod` |
| 1 | kube-prometheus-stack 설치 (`monitoring` namespace, 본 토픽 [values.yaml](manifests/kube-prometheus-stack/values.yaml)) | `kubectl get pods -n monitoring` |
| 2 | Prometheus / Grafana UI port-forward + 첫 접속 (admin / prom-operator) | 브라우저 9090 / 3000 |
| 3 | sentiment-api `/metrics` 직접 호출해 raw 출력 확인 | `predict_latency_seconds_bucket` 라인 |
| 4 | 01 차트에 servicemonitor 활성화 (`helm upgrade --set monitoring.serviceMonitor.enabled=true`) | `kubectl get servicemonitor` |
| 5 | Prometheus UI > Status > Targets 에서 `prod/sentiment-api` UP 확인 | `up{...}` = 1 |
| 6 | PromQL 4개 작성 (req rate / p95 latency / error rate / replicas available) | Prom UI Graph 탭 |
| 7 | Grafana 대시보드 import → 4 패널 시각화 | 패널 데이터 표시 |
| 8 | 부하 부여 (`hey -z 30s -c 10 .../predict`) → 패널 변화 관찰 | 모든 패널 라인 변화 |
| 9 | 정리 (`helm uninstall prom`, namespace 삭제 — sentiment-api 는 보존) | Phase 3/03 입력 보존 |

## 3. 검증 체크리스트

본 토픽 완료 후 다음이 모두 ✅ 여야 합니다.

- [ ] `kubectl get crd | grep monitoring.coreos.com` 으로 `servicemonitors.monitoring.coreos.com` 등 CRD 5개 존재
- [ ] `kubectl get pods -n monitoring` 가 모두 `Running` (Prom Operator / Prom 서버 / Grafana / kube-state-metrics / node-exporter)
- [ ] `kubectl get servicemonitor -n prod sentiment-api` 가 1건 반환
- [ ] Prometheus UI ▶ Status ▶ Targets 에서 `serviceMonitor/prod/sentiment-api/0` 가 **UP** 상태
- [ ] Prometheus UI ▶ Graph 탭에서 `predict_requests_total` 시계열이 보임
- [ ] Grafana ▶ import 한 *Sentiment API — ML 추론 SLO* 대시보드에서 4 패널 모두 데이터 표시
- [ ] `hey -z 30s` 부하 부여 후 30 ~ 60초 안에 패널 1 (요청량) 의 라인이 0 → N 으로 상승

> ⚠️ **prod release 보존** — lab 9 (정리) 는 `helm uninstall prom` 만 수행하고 `sentiment-api` (prod) 는 그대로 둡니다. Phase 3/03 (HPA) 이 본 토픽의 메트릭을 그대로 입력으로 사용하기 때문입니다.

## 🚨 자주 하는 실수

1. **ServiceMonitor 라벨 미스매치 — Targets 에 안 나타남**
   가장 흔한 실수입니다. ServiceMonitor 를 만들었는데 Prometheus UI ▶ Status ▶ Targets 에 보이지 않으면 99% 라벨 문제입니다. 두 단계 중 어디서 끊어졌는지 진단하세요. ① **Operator → ServiceMonitor 단계**: `kubectl get servicemonitor -A --show-labels` 로 `release: prom` 라벨이 붙어 있는지 확인. 본 차트는 [values.yaml](../01-helm-chart/manifests/chart/sentiment-api/values.yaml) 의 `monitoring.serviceMonitor.labels.release: prom` 로 자동 주입하지만, kube-prometheus-stack 을 다른 release 이름으로 (예: `helm install kps ...`) 설치했다면 라벨도 같이 바꿔야 합니다 (`--set monitoring.serviceMonitor.labels.release=kps`). ② **ServiceMonitor → Service 단계**: `kubectl describe servicemonitor sentiment-api -n prod` 의 `Selector` 와 `kubectl get svc sentiment-api -n prod --show-labels` 의 라벨이 일치하는지 비교. 차트의 `_helpers.tpl` `selectorLabels` 가 둘 다 만들기 때문에 일반적으론 일치하지만, `fullnameOverride` 를 잘못 주면 어긋날 수 있습니다. 디버깅 명령: `kubectl get prometheus -n monitoring -o yaml | grep -A 5 serviceMonitorSelector` 로 Operator 가 정확히 어떤 라벨을 찾고 있는지 확인.

2. **Histogram bucket 부족으로 `histogram_quantile` 이 NaN — 분포 끝단의 추정 실패**
   prometheus-client `Histogram` 디폴트 bucket 은 `[0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1.0, 2.5, 5.0, 7.5, 10.0]` 초입니다. 본 코스의 분류 모델은 CPU 추론 시 0.1 ~ 0.5초가 흔해 디폴트가 잘 맞지만, **vLLM / LLM 서빙 (Phase 4-3)** 은 응답이 5 ~ 30초까지 가서 디폴트 마지막 bucket 이 `+Inf` 로 몰려 p95 추정이 부정확해집니다. 그리고 요청이 *전혀 없으면* 모든 bucket 이 0 → `histogram_quantile` 의 결과는 NaN → Grafana 가 'No data' 로 표시 — 정상입니다 (lab 6 단계가 부하를 주기 전엔 이 상태). bucket 조정은 코드에서 `Histogram(..., buckets=(0.1, 0.5, 1.0, 5.0, 10.0, 30.0))` 로. 단, **buckets 는 한 번 정하면 바꾸지 마세요** — 기존 메트릭과 호환 안 되어 PromQL 쿼리가 끊깁니다. ML 표준 패턴: `prometheus-client` 의 `Histogram` 대신 `Summary` 를 쓰면 quantile 을 클라이언트가 직접 계산해 bucket 문제는 사라지지만, 여러 Pod 의 Summary 는 *합칠 수 없습니다* (Histogram 만 가능) — 멀티 레플리카 서빙엔 Histogram 이 정답.

3. **Prometheus / Grafana 가 minikube 자원을 잡아먹어 sentiment-api 가 OOM**
   kube-prometheus-stack 디폴트 리소스는 만만치 않습니다 — Prometheus 서버 1Gi+, Grafana 200Mi, node-exporter 노드당 50Mi, kube-state-metrics 200Mi. minikube 기본 (CPU 2 / RAM 2Gi) 에서 디폴트로 install 하면 sentiment-api Pod 가 `Pending` 으로 멈추거나, 기존 prod release 가 evict 됩니다. 본 토픽의 [values.yaml](manifests/kube-prometheus-stack/values.yaml) 은 모든 컴포넌트의 `resources.requests/limits` 를 명시적으로 낮춰 두었지만, **minikube 가 너무 작으면 (RAM 2Gi 이하) 그래도 부족** 할 수 있습니다. 권장: `minikube start --memory=4096 --cpus=4` 로 시작. 검증: lab 1 단계에서 `kubectl top pod -n monitoring` 로 실제 사용량 확인 (metrics-server 가 켜져 있어야 함 — `minikube addons enable metrics-server`). 그래도 부족하면 retention 을 1일로 더 줄이거나 (`--set prometheus.prometheusSpec.retention=1d`) Grafana 의 sidecar dashboards / datasources 를 비활성 (`--set grafana.sidecar.dashboards.enabled=false`).

## 더 알아보기

- [Prometheus 공식 — Histograms and Summaries](https://prometheus.io/docs/practices/histograms/) — 자주 하는 실수 2번의 깊이 있는 배경.
- [kube-prometheus-stack ArtifactHub](https://artifacthub.io/packages/helm/prometheus-community/kube-prometheus-stack) — 본 토픽이 사용한 차트의 전체 values 레퍼런스.
- [Prometheus Operator — ServiceMonitor 디자인](https://prometheus-operator.dev/docs/operator/design/) — Operator 가 ServiceMonitor → Prometheus 설정으로 변환하는 정확한 메커니즘.
- [Grafana 공식 — Prometheus 데이터소스](https://grafana.com/docs/grafana/latest/datasources/prometheus/) — `$__interval`, `$__rate_interval` 같은 Grafana 전용 변수.
- [PromQL Cheat Sheet (PromLabs)](https://promlabs.com/promql-cheat-sheet/) — 본 토픽 1-4 절의 확장판. 캡스톤 보고서 패널 만들 때 다시 참조.

## 다음 챕터

➡️ [Phase 3 / 03-autoscaling-hpa — HPA 와 부하 테스트](../03-autoscaling-hpa/lesson.md) (작성 예정)

본 토픽이 노출한 메트릭 (`predict_requests_total`, `predict_latency_seconds`) 과 ServiceMonitor 인프라가 다음 토픽의 입력으로 그대로 사용됩니다. 03-autoscaling-hpa 는 두 가지로 evolve 합니다. ① **CPU 기반 HPA** — 본 토픽의 [values.yaml](../01-helm-chart/manifests/chart/sentiment-api/values.yaml) `autoscaling.enabled: false` placeholder 를 활성화해 `templates/hpa.yaml` 추가. ② **커스텀 메트릭 HPA** — `prometheus-adapter` 를 추가 install 해 본 토픽의 `predict_requests_total` 을 HPA 가 직접 읽고 스케일링. ML 추론 API 의 표준 스케일링 시그널은 CPU 보다 *요청 큐 길이 / 토큰 처리량* 이라, 커스텀 메트릭 패턴이 Phase 4 의 KServe / vLLM 까지 그대로 이어집니다.
