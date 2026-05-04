# Phase 3/03 — manifests

본 디렉토리는 03-autoscaling-hpa 토픽이 추가하는 **standalone 매니페스트** 만 담습니다.
CPU 기반 HPA (`templates/hpa.yaml`) 는 Phase 3/01 의 sentiment-api 차트 안에 이미 들어 있고, lab 2 단계의 `helm upgrade --set autoscaling.enabled=true` 로 활성화됩니다.

## 파일 목록

| 경로 | 종류 | 용도 |
|------|------|------|
| `prometheus-adapter/values.yaml` | Helm values | `prometheus-community/prometheus-adapter` 설치값. Prometheus Counter `predict_requests_total` 을 custom.metrics.k8s.io API 의 `predict_requests_per_second` Pods 메트릭으로 변환하는 룰 1개 포함 |
| `hpa-custom-metric.yaml` | K8s manifest | 두 번째 HPA. 동일한 sentiment-api Deployment 를 RPS 기준으로 스케일. 01 차트의 CPU HPA 와 공존 |
| `load-test/hey-job.yaml` | K8s manifest | rakyll/hey 이미지로 60초 POST 부하를 주는 Job. 클러스터 안에서 실행되어 학습자 PC 의 hey 설치 불필요 |

## 적용 순서 (labs/README.md 와 1:1)

```
[lab 6] helm install prom-adapter -f prometheus-adapter/values.yaml   ← custom.metrics.k8s.io API 활성화
[lab 7] kubectl get --raw .../predict_requests_per_second              ← 메트릭 노출 확인
[lab 8] kubectl apply -f hpa-custom-metric.yaml                        ← 두 번째 HPA
[lab 3,9] kubectl apply -f load-test/hey-job.yaml                      ← 부하 부여
```

> 💡 CPU 기반 HPA 는 본 디렉토리에 없습니다 — Phase 3/01 의 차트에 `templates/hpa.yaml` 형태로 포함되어 있고, lab 2 단계의 `helm upgrade --set autoscaling.enabled=true` 로 활성화됩니다.
