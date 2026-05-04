# Phase 3 / 03 — HPA 와 부하 테스트로 ML 추론 API 오토스케일링

> 직전 토픽 [Phase 3/02 prometheus-grafana](../02-prometheus-grafana/lesson.md) 가 sentiment-api 의 `/metrics` 를 ServiceMonitor 로 스크래핑하는 인프라를 만들었고, [Phase 3/01 의 차트](../01-helm-chart/manifests/chart/sentiment-api/) `values.yaml` 에는 이미 `autoscaling.*` placeholder 와 `templates/hpa.yaml` 이 *비활성 상태로* 들어 있습니다. 본 토픽의 작업은 이 두 자산을 **연결** 하고, 추가로 prometheus-adapter 를 install 해 커스텀 메트릭 기반 HPA 까지 확장하는 것 — sentiment-api 의 코드 수정은 **없습니다**.

## 학습 목표

1. HPA control loop 와 Deployment 의 `/scale` subresource 기반 스케일링 메커니즘을 설명합니다.
2. Resource / Custom / External 세 가지 메트릭 API 의 차이를 구분하고 각 케이스의 manifest 작성 패턴을 안다.
3. `autoscaling/v2` HPA 의 `metrics` + `behavior` (scaleDown stabilization, scaleUp policies) 를 비대칭으로 작성합니다.
4. `prometheus-adapter` 를 install 해 Prometheus Counter 를 `custom.metrics.k8s.io` API 로 노출하고 두 번째 HPA 가 이를 직접 소비하게 만듭니다.
5. HPA / VPA / Cluster Autoscaler / KEDA 의 스코프 차이와 ML 워크로드별 권장 조합을 설명합니다.

**완료 기준 (1줄)**: `kubectl get hpa -n prod -w` 가 `hey` 부하 시작 후 60–90초 안에 `REPLICAS` 컬럼을 2 → 4 이상으로 증가시키고, `kubectl get --raw "/apis/custom.metrics.k8s.io/v1beta1/namespaces/prod/pods/*/predict_requests_per_second"` 가 JSON 을 반환하면 완료.

## 왜 ML 엔지니어에게 오토스케일링이 필요한가

ML 추론 워크로드의 트래픽은 일반 웹 서비스와 패턴이 다릅니다. 캠페인 / 알림 / 배치 트리거 같은 외부 이벤트로 *spike-prone* 하고, 모델 로딩 (transformers `from_pretrained` 30초+) 같은 cold start 비용이 커서 **고정 replica 운영은 두 방향 모두 비효율** 입니다 — 평소엔 idle Pod 가 GPU/CPU 를 점유하고, spike 시엔 큐가 쌓여 p95 latency 가 무너집니다.

| ML 워크로드 | 트래픽 패턴 | HPA 신호 | 본 토픽이 다루는 단계 |
|------------|------------|---------|--------------------|
| 온라인 추론 API (분류) | spike-prone | CPU% / req/s | 두 HPA 모두 (lab 2, lab 8) |
| 배치 추론 | bursty | 큐 길이 (External) | 개념만 (1-2, 1-5), Phase 4 |
| LLM 서빙 (vLLM) | concurrency-bound | `vllm:num_requests_running` | 패턴만 언급, Phase 4-3 |
| GPU 학습 Job | long-running | (HPA 부적합 — Job/Operator) | 비교 (1-5) |

CPU 기반 HPA 는 입문 단계에선 잘 동작하지만, 실제 ML 추론에서 *충분치 않은 경우* 가 많습니다. 모델 추론은 한 번 시작되면 CPU spike 가 짧고 평균이 낮아 백분율로 평균을 내면 신호가 약해지고, 진짜 SLO 인 *p95 latency* 는 CPU 가 70% 에 닿기 전에 이미 무너집니다. 그래서 본 토픽은 CPU HPA 를 먼저 동작시킨 뒤, 곧장 *application-level metric (req/s)* 로 확장합니다 — 같은 패턴이 Phase 4 의 KServe / vLLM 까지 그대로 이어집니다.

## 1. 핵심 개념

### 1-1. HPA control loop & scale subresource

HPA 는 별도의 데몬이 아니라 `kube-controller-manager` 안의 컨트롤러입니다. 다음 4단계가 `--horizontal-pod-autoscaler-sync-period` (기본 15초) 마다 반복됩니다.

```
[1] List Pods (label selector)              [3] Compute desiredReplicas
        │                                            │
        ▼                                            ▼
[2] Fetch metrics                          [4] Patch Deployment /scale
   metrics.k8s.io                                    │
   custom.metrics.k8s.io                             ▼
   external.metrics.k8s.io                  ReplicaSet → Pod ±N
```

3번 단계의 공식은 단순합니다.

```
desiredReplicas = ceil( currentReplicas × currentMetricValue / desiredMetricValue )
```

예: `currentReplicas=2`, `currentCPU=140m` (Pod 평균), `targetCPU=100m` (requests 500m × 70% × 0.286? — 실제 컨트롤러는 *백분율 직접* 계산) → desired=3. 실수를 줄이는 두 안전장치도 함께 알면 좋습니다.

| 컨트롤러 플래그 | 기본값 | 의미 |
|----------------|--------|------|
| `--horizontal-pod-autoscaler-sync-period` | 15s | loop 주기. minikube 에선 그대로 |
| `--horizontal-pod-autoscaler-tolerance` | 0.1 | desired/current 비율이 ±10% 이내면 무시 (jitter 방지) |
| `--horizontal-pod-autoscaler-cpu-initialization-period` | 5m | Pod 가 막 떴을 때 초기 CPU spike 무시 |
| `--horizontal-pod-autoscaler-downscale-stabilization` | 5m | scaleDown 의 cluster-wide 디폴트 stabilization (HPA per-resource `behavior` 가 우선) |

4번 단계의 `/scale` subresource 는 Deployment / StatefulSet / ReplicaSet 등 *scale 가능한 모든 리소스* 가 노출하는 표준 엔드포인트입니다. 직접 호출도 가능합니다.

```bash
kubectl get deploy sentiment-api -n prod -o jsonpath='{.spec.replicas}'  # 현재 desired
kubectl scale deploy sentiment-api -n prod --replicas=3                  # 수동 patch — HPA 가 다음 sync 에서 다시 덮어씀
```

### 1-2. 세 가지 메트릭 API

HPA `spec.metrics[].type` 은 4가지지만 (`Resource`, `Pods`, `Object`, `External`), API 백엔드는 3개입니다.

| API | 서빙 주체 | 데이터 | HPA `type` |
|-----|----------|-------|-----------|
| `metrics.k8s.io` | metrics-server | CPU / 메모리 only (Pod, Node) | `Resource` |
| `custom.metrics.k8s.io` | prometheus-adapter (또는 다른 adapter) | Pod 단위 임의 메트릭 | `Pods`, `Object` |
| `external.metrics.k8s.io` | KEDA, 클라우드별 adapter | 클러스터 외부 (SQS depth, Pub/Sub backlog) | `External` |

각각의 manifest 1줄 스니펫:

```yaml
# Resource (CPU 백분율)
- type: Resource
  resource: { name: cpu, target: { type: Utilization, averageUtilization: 70 } }

# Pods (Pod 당 평균 — req/s)
- type: Pods
  pods: { metric: { name: predict_requests_per_second }, target: { type: AverageValue, averageValue: "10" } }

# Object (특정 Service 의 누적값 — 예: Ingress 의 reqs)
- type: Object
  object: { describedObject: { kind: Service, name: sentiment-api }, metric: { name: requests_per_second }, target: { type: Value, value: "100" } }

# External (큐 길이 — Phase 4 배치)
- type: External
  external: { metric: { name: queue_length, selector: { matchLabels: { queue: "infer-batch" } } }, target: { type: AverageValue, averageValue: "30" } }
```

본 토픽은 `Resource` (lab 2) 와 `Pods` (lab 8) 를 다룹니다. `External` 은 Phase 4 의 배치 추론에서 KEDA 와 함께 다시 등장합니다.

### 1-3. autoscaling/v2 manifest 구조

`autoscaling/v1` 은 CPU 만 지원하고 `behavior` 가 없어 prod 운영에 부족합니다. `autoscaling/v2beta2` 는 K8s v1.26 부터 deprecated. **항상 `autoscaling/v2`** 를 사용합니다.

01 차트의 [templates/hpa.yaml](../01-helm-chart/manifests/chart/sentiment-api/templates/hpa.yaml) 이 렌더하는 minimal 형태:

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata: { name: sentiment-api }
spec:
  scaleTargetRef: { apiVersion: apps/v1, kind: Deployment, name: sentiment-api }
  minReplicas: 2
  maxReplicas: 8
  metrics:
    - type: Resource
      resource: { name: cpu, target: { type: Utilization, averageUtilization: 70 } }
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 300            # 부하 종료 후 5분간 desired 의 max 유지
    scaleUp:
      stabilizationWindowSeconds: 0              # spike 즉시 반응
      policies:
        - type: Percent
          value: 100                             # 한 번 평가에 최대 100% 증가
          periodSeconds: 60
      selectPolicy: Max                          # 여러 정책 중 가장 공격적인 desired 채택
```

`behavior` 의 비대칭이 ML 추론의 핵심입니다. **scaleUp 은 즉시, scaleDown 은 보수적** — 모델 로딩에 30초+ 가 걸리는 워크로드에서 5분 stabilization 없이 축소하면 트래픽 잔파동마다 Pod 가 죽었다 살아나며 응답 latency 가 출렁입니다 (자주 하는 실수 3번).

> ⚠️ **production 에서는 한 Deployment 에 HPA 하나** — `metrics: []` 에 여러 신호를 묶는 것이 표준입니다. 본 토픽은 학습용으로 두 HPA 를 같은 Deployment 에 붙여 *동작은 가능하지만 권장 패턴은 아님* 임을 lab 8 단계에서 직접 보여줍니다.

### 1-4. prometheus-adapter — Prometheus 메트릭이 HPA 까지 도달하는 길

ServiceMonitor 까지 만들어둔 메트릭은 *Prometheus 안* 에 있을 뿐, HPA 컨트롤러는 직접 Prometheus 를 보지 않습니다. 둘 사이를 연결하는 어댑터가 `prometheus-adapter` 입니다.

```
FastAPI /metrics
     │  scrape (ServiceMonitor 30s)
     ▼
Prometheus  ──PromQL (rules.custom)──►  prometheus-adapter
                                              │
                                              ▼  serves API
                                  custom.metrics.k8s.io
                                              │
                                              ▼
                                            HPA
```

본 토픽의 [manifests/prometheus-adapter/values.yaml](manifests/prometheus-adapter/values.yaml) 의 핵심은 `rules.custom[0]` 한 항목입니다.

```yaml
- seriesQuery: 'predict_requests_total{namespace!="",pod!=""}'   # ① 어떤 시계열을 후보로?
  resources:
    overrides:                                                    # ② Prometheus 라벨 → K8s 자원 매핑
      namespace: { resource: namespace }
      pod:       { resource: pod }
  name:
    matches: "^(.*)_total$"                                       # ③ 노출 시 이름 변환
    as: "${1}_per_second"
  metricsQuery: |                                                 # ④ 실제 던져지는 PromQL
    sum(rate(<<.Series>>{<<.LabelMatchers>>}[2m])) by (<<.GroupBy>>)
```

- ① `seriesQuery` 의 `namespace!="",pod!=""` 필터가 K8s 자원 라벨을 가진 시리즈만 통과시킴.
- ② `resources.overrides` 가 *Prometheus 라벨* 을 *K8s 자원 종류* 로 매핑. kube-prometheus-stack 의 ServiceMonitor 는 자동으로 `namespace`, `pod` 라벨을 붙여줍니다 (라벨 이름이 다르면 **자주 하는 실수 2번** 시나리오).
- ③ `name.matches`/`as` 로 Counter `predict_requests_total` 을 의미가 명확한 `predict_requests_per_second` 로 리네임.
- ④ `metricsQuery` 의 rate window 는 ServiceMonitor `interval: 30s` 의 4배인 2m 로 안전하게 둡니다.

### 1-5. HPA / VPA / Cluster Autoscaler / KEDA — 무엇이 무엇을 바꾸는가

오토스케일링 도구는 *바꾸는 대상* 으로 구분하면 헷갈리지 않습니다.

| 도구 | 변경 대상 | ML 사용처 | HPA 와의 관계 |
|------|---------|----------|--------------|
| **HPA** | Pod 개수 (Deployment.replicas) | 추론 API | 본 토픽 |
| **VPA** | 컨테이너 spec (resources.requests/limits) | 학습 Job, GPU 컨테이너 | CPU 기반 HPA 와 충돌 — *CPU 신호가 양쪽에 동시 사용*. 권장: req/s HPA + 메모리만 VPA |
| **Cluster Autoscaler** | 노드 개수 | GPU 노드 풀 | HPA 가 Pending Pod 를 만들면 CA 가 노드 추가. HPA 의 *상위 layer* |
| **KEDA** | Pod 개수 (HPA 를 wrap) | 큐 기반 배치 추론 | External 메트릭 다양화. 내부적으로 HPA 를 만들어 사용 |

본 토픽은 HPA 만 직접 다루고, 나머지는 *언제 도입하는지* 만 짧게 짚습니다. ML 진영에서 자주 보는 조합은 다음 두 가지입니다.

```
[온라인 추론 API]    HPA(req/s) + VPA(memory only) + CA(노드)
[배치 추론]          KEDA(큐 길이) + CA(GPU 노드)
```

### 1-6. ML 워크로드 관점 — 왜 CPU 만으론 부족한가

본 코스의 분류 모델 (`cardiffnlp/twitter-roberta-base-sentiment`) 은 한 추론에 100–300ms, 모델 로딩에 30초+, Pod 메모리 1Gi 가 정상입니다. 이 워크로드에서 CPU 기반 HPA 가 가지는 세 가지 한계:

1. **CPU spike 가 짧아 평균이 신호로 약함** — Histogram window 가 길수록 평균이 묽어져 70% 임계치를 못 넘기는데도 큐는 쌓이는 상황 발생.
2. **cold start 비용이 커서 scaleDown 이 위험** — 5분 stabilization 없이 축소하면 트래픽 잔파동마다 30초 latency spike.
3. **SLO 의 본질이 p95 latency 인데 CPU 평균은 그 신호를 못 잡음** — req/s 또는 latency-derived 메트릭이 더 직접적.

결론: **CPU HPA 는 출발점, 운영의 표준은 application-level metric (req/s, queue depth, p95 latency)** 입니다. 본 토픽의 두 번째 HPA (`predict_requests_per_second`) 가 그 첫 단계이고, Phase 4 의 KServe / vLLM 으로 가면 토큰 처리량 / GPU 메모리 / KV cache 사용률까지 확장됩니다.

## 2. 실습 개요

전체 절차는 [labs/README.md](labs/README.md) 에 0–10 단계로 작성되어 있습니다. lesson.md 에선 흐름만 요약합니다.

| 단계 | 내용 | 검증 |
|-----|------|------|
| 0 | 사전 점검 (Phase 3/01 prod release + Phase 3/02 monitoring stack 살아있나, `metrics-server` addon 활성) | `helm list -n prod`, `kubectl top pod -n prod` |
| 1 | metrics-server 가 HPA 의 절반인 이유 — APIService 등록 확인 | `kubectl get apiservice v1beta1.metrics.k8s.io` |
| 2 | 01 차트 helm upgrade `--set autoscaling.enabled=true` → `templates/hpa.yaml` 첫 렌더 | `kubectl get hpa -n prod` (`cpu: 2%/70%`) |
| 3 | hey-job 으로 부하 부여 → resource HPA 가 replicas 2 → 4 이상 | `kubectl get hpa -w -n prod`, `kubectl get events ...` |
| 4 | 부하 종료 후 5분 stabilization 관찰 — replicas 가 곧장 줄지 *않는* 게 정상 | `watch kubectl get hpa,deploy -n prod` |
| 5 | Grafana 패널 1 (req rate) 과 HPA replicas 비교 — CPU 가 신호로 lag 가 큰 이유 시각 확인 | grafana port-forward |
| 6 | prometheus-adapter 설치 | `kubectl get apiservice v1beta1.custom.metrics.k8s.io` |
| 7 | custom 메트릭 raw API 호출로 노출 확인 | `kubectl get --raw .../predict_requests_per_second \| jq` |
| 8 | 두 번째 HPA (`hpa-custom-metric.yaml`) 적용 — 한 Deployment 에 HPA 둘 | `kubectl get hpa -n prod` (2건) |
| 9 | 다시 hey-job → RPS HPA 가 보통 더 빨리 트리거. controller 가 두 HPA desired 의 max 채택 | `kubectl describe hpa sentiment-api-rps` |
| 10 | 정리 — prom-adapter, 두 번째 HPA, hey-job 만 제거. 차트 / monitoring 보존 | Phase 3/04 가 이어 사용 |

## 3. 검증 체크리스트

본 토픽 완료 후 다음이 모두 ✅ 여야 합니다.

- [ ] `kubectl get apiservice v1beta1.metrics.k8s.io` 가 `Available=True`
- [ ] lab 2 직후 `kubectl get hpa sentiment-api -n prod` 의 TARGETS 컬럼이 약 30초 안에 `<unknown>/70%` → `2%/70%` 로 변환
- [ ] `hey-job` 시작 60–90초 안에 `REPLICAS` 컬럼이 2 → 4 이상으로 증가
- [ ] hey-job 종료 후 *최소 5분* 동안 replicas 유지 (scaleDown stabilization)
- [ ] `kubectl get pod -n monitoring -l app.kubernetes.io/name=prometheus-adapter` 가 모두 Running
- [ ] `kubectl get --raw "/apis/custom.metrics.k8s.io/v1beta1/namespaces/prod/pods/*/predict_requests_per_second" \| jq '.items \| length'` ≥ 2
- [ ] `kubectl get hpa -n prod` 에 두 HPA (`sentiment-api`, `sentiment-api-rps`) 가 동시에 표시되고 두 번째 HPA 의 TARGETS 가 `<unknown>` 이 아님

## 4. 정리

```bash
# 본 토픽이 추가한 것만 정리. Phase 3/01 차트와 Phase 3/02 monitoring 은 보존 (Phase 3/04 가 사용).
kubectl delete -f manifests/hpa-custom-metric.yaml
kubectl delete -f manifests/load-test/hey-job.yaml --ignore-not-found
helm uninstall prom-adapter -n monitoring

# 01 차트의 CPU HPA 는 helm upgrade --set autoscaling.enabled=false 로 끄거나, 그대로 두어도 됨 (Phase 3/04 영향 없음).
```

## 🚨 자주 하는 실수

1. **`resources.requests.cpu` 누락 → resource HPA 가 영원히 `<unknown>/70%`**
   HPA 의 백분율은 *requests* 기준이라 requests 가 없으면 컨트롤러가 desired 를 계산할 수 없습니다. 본 차트의 [values.yaml](../01-helm-chart/manifests/chart/sentiment-api/values.yaml) 디폴트 `resources: {}` 가 정확히 이 함정입니다 — dev 환경에선 Phase 2/05 의 LimitRange default 가 채워주지만, LimitRange 없이 `helm install` 하면 HPA 가 영원히 unknown. 진단 명령 1줄: `kubectl describe hpa sentiment-api -n prod` 의 Events 에 `failedGetResourceMetric: did not receive metrics` 또는 `missing request for cpu`. 해결: ① values-prod.yaml 처럼 명시 requests, ② 네임스페이스에 LimitRange (Phase 2/05 패턴) 적용, ③ helm upgrade 시 `--set resources.requests.cpu=200m,resources.requests.memory=256Mi` 직접 주입. 본 토픽 lab 2 단계는 ①(values-prod.yaml) 로 진행합니다.

2. **prometheus-adapter `resources.overrides` 라벨 미스매치 → custom 메트릭이 API 에 안 나타남**
   adapter 가 Prometheus 시리즈의 라벨을 K8s 자원 (`namespace`, `pod`) 으로 매핑해야 합니다. kube-prometheus-stack 의 ServiceMonitor 는 보통 `namespace` / `pod` 라벨을 자동 부여하지만, 자체 PodMonitor / 직접 만든 scrape config 가 `kubernetes_namespace` / `kubernetes_pod_name` 으로 라벨을 만들었다면 본 토픽의 [values.yaml](manifests/prometheus-adapter/values.yaml) 의 `overrides` 가 매칭에 실패합니다. 진단: ① Prometheus UI ▶ Status ▶ Targets 에서 sentiment-api 시리즈의 라벨 직접 확인, ② `kubectl logs -n monitoring deploy/prom-adapter` 의 `unable to fetch metrics from custom metrics API` 라인. 해결: 실제 라벨 이름에 맞춰 `overrides` 의 키 (`namespace:` / `pod:`) 를 변경하거나, ServiceMonitor 의 `relabelings` 로 표준 라벨을 만들어 주는 것 — 후자가 권장 (다른 adapter / dashboards 도 같은 라벨을 기대).

3. **scaleDown stabilization 미설정 → 부하 종료 직후 즉시 축소 → flapping**
   K8s 의 클러스터 디폴트는 5분 (`--horizontal-pod-autoscaler-downscale-stabilization=5m`) 이지만, HPA 의 `behavior.scaleDown.stabilizationWindowSeconds` 를 *명시적으로 0* 으로 두면 cluster 디폴트보다 우선합니다. ML inference 는 cold start 비용 (모델 로딩 30초+) 이 커서 hey 종료 직후 15초마다 desired 가 흔들리며 Pod 생성/삭제가 반복되면 응답 latency 가 spike → SLO 무너짐. 권장 패턴: scaleDown 300s 이상, scaleUp 0s — `behavior` 의 비대칭이 핵심입니다. 본 토픽의 [values-prod.yaml](../01-helm-chart/manifests/chart/sentiment-api/values-prod.yaml) `autoscaling.behavior` 와 [hpa-custom-metric.yaml](manifests/hpa-custom-metric.yaml) 의 behavior 가 같은 정책을 사용합니다 — 두 HPA 의 정책이 다르면 트러블슈팅이 매우 어려워집니다.

## 더 알아보기

- [Kubernetes 공식 — HPA Walkthrough](https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale-walkthrough/) — autoscaling/v2 의 metrics / behavior 풀 reference.
- [prometheus-adapter — Configuration Walkthroughs](https://github.com/kubernetes-sigs/prometheus-adapter/blob/master/docs/walkthrough.md) — 본 토픽 1-4 절의 `rules.custom` 작성 패턴 확장판.
- [KEDA 공식 사이트](https://keda.sh/) — External 메트릭 (큐, 스트리밍) 기반 스케일러. Phase 4 배치 추론에서 다시 등장.
- [`hey` README](https://github.com/rakyll/hey) — 부하 옵션 전체. 본 토픽은 `-z`, `-c`, `-m`, `-T`, `-d` 5개만 사용.
- [KEP-117 (HPA behavior block)](https://github.com/kubernetes/enhancements/tree/master/keps/sig-autoscaling/853-configurable-hpa-scale-velocity) — `behavior` 가 어떤 문제를 풀려고 도입됐는지의 배경.

## 다음 챕터

➡️ [Phase 3 / 04-rbac-serviceaccount — 최소 권한 원칙으로 ML 서비스 보안](../04-rbac-serviceaccount/lesson.md) (작성 예정)

본 토픽이 만든 자산이 다음 토픽에서 어떻게 RBAC 와 만나는지: ① **HPA 컨트롤러** 는 사실상 cluster-scope 로 동작 (kube-controller-manager 가 system:serviceaccount:kube-system:horizontal-pod-autoscaler 라는 내장 ServiceAccount 사용). ② **prometheus-adapter** 는 별도 ClusterRole 이 필요 — `external.metrics.k8s.io` / `custom.metrics.k8s.io` API 에 self-register 하기 위해 APIService 등록 권한과 metrics.k8s.io 의 metrics 조회 권한이 둘 다 필요합니다. 04 토픽이 이를 직접 작성해 *왜 ML 데이터 플레인은 RBAC 가 그렇게 까다로운지* 를 보여줍니다.
