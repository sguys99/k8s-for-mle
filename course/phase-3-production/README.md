# Phase 3 — 프로덕션 운영 도구 (2주)

> Phase 2까지 만든 dev / prod 두 묶음 매니페스트를 단일 Helm 차트로 패키징하고, Prometheus / Grafana 로 메트릭을 수집하며, HPA 로 자동 스케일링하고, RBAC 로 최소 권한을 적용합니다. ML 운영 도구 대부분이 Helm 으로 배포되므로 본 Phase 가 Phase 4 (KServe / vLLM / Argo) 의 직접 발판입니다.
>
> **권장 기간**: 2주
> **선수 학습**: [Phase 2 — 운영에 필요한 K8s 개념](../phase-2-operations/)

## 이 Phase에서 배우는 것

Phase 2/05 까지 dev / prod 두 namespace 에 거의 같은 5개 자원(ConfigMap + Secret + PVC + Deployment + Service)을 손으로 두 벌 만들었습니다. 환경이 늘어날 때마다 매니페스트를 손으로 동기화하는 운영 부담을 Phase 3 가 차례로 풀어냅니다.

| 운영 문제 | Phase 3 해결책 |
|----------|----------------|
| 환경별 매니페스트 두 벌 → 손 동기화 부담 | Helm 차트 + values-`<env>`.yaml |
| 추론 latency / throughput / 에러율을 어떻게 보지? | Prometheus + Grafana + ServiceMonitor |
| 트래픽이 폭증하면? 폭감하면? | HPA (CPU / 커스텀 메트릭) |
| 모든 Pod 가 cluster-admin 권한? | ServiceAccount + Role + RoleBinding |

## 학습 목표

- Phase 2 매니페스트를 Helm 차트로 변환하고 `helm install / upgrade / rollback / uninstall` 라이프사이클을 운용할 수 있습니다.
- kube-prometheus-stack 을 Helm 으로 설치하고 FastAPI 의 `/metrics` 를 ServiceMonitor 로 수집해 Grafana 대시보드로 시각화합니다.
- HPA 로 CPU 또는 커스텀 메트릭 기반 오토스케일링을 설정하고 부하 테스트(`hey`/`wrk`)로 동작을 검증합니다.
- ServiceAccount + Role + RoleBinding 으로 최소 권한 원칙을 적용합니다.

## 챕터 구성

| 챕터 | 제목 | 핵심 내용 |
|------|------|----------|
| [01](./01-helm-chart/) | Helm Chart | Phase 2/05 의 dev/prod 매니페스트 두 벌을 단일 차트로 패키징, `values-dev.yaml` / `values-prod.yaml` 환경 분리, 4가지 라이프사이클 명령(install/upgrade/rollback/uninstall), `helm template` / `--dry-run` / `helm history` 디버깅 |
| 02 | Prometheus + Grafana | (작성 예정) kube-prometheus-stack 설치, FastAPI `/metrics`, ServiceMonitor, Grafana 대시보드 |
| 03 | Autoscaling (HPA) | (작성 예정) HPA + 부하 테스트(`hey`/`wrk`), VPA·Cluster Autoscaler 개념 |
| 04 | RBAC & ServiceAccount | (작성 예정) ServiceAccount / Role / RoleBinding, 최소 권한, kubeconfig 분리 |

## 권장 진행 순서

1. 위 표 순서대로 진행합니다. 01에서 만든 sentiment-api 차트가 02·03·04에서 templates 추가 형태로 점진적으로 evolve 합니다.
2. Phase 2/05 의 dev / prod namespace 와 ResourceQuota / LimitRange 가 살아 있어야 합니다 (각 토픽 lab 0단계에서 점검).
3. 모든 차트 변경은 `helm lint` → `helm template` → `helm install --dry-run --debug` → 실제 install 4단계로 검증합니다.

## 환경 요구사항

- Phase 2 와 동일 (minikube v1.32+, kubectl v1.28+, 메모리 4GB+, 디스크 10GB+)
- **Helm v3.x** 추가 (01 토픽 lab 0-1 단계)
- GPU 는 필요하지 않습니다 (Phase 4 부터 GPU 사용)

## 마치면 할 수 있는 것

이 Phase 를 완료하면 다음 운영 시스템을 구축할 수 있습니다.

> 분류 모델 서빙을 단일 Helm 차트로 패키징해 `helm upgrade --install` 한 줄로 dev / staging / prod 어느 환경에든 배포하고, Grafana 에서 latency p95 / throughput / 에러율 대시보드를 보며, 트래픽이 늘면 HPA 가 자동으로 Pod 를 늘리고, 모든 권한이 namespace 단위 RBAC 으로 최소화된 상태가 됩니다.

## 다음 Phase

➡️ [Phase 4 — ML on Kubernetes](../phase-4-ml-on-k8s/) (작성 예정) — Phase 3 의 Helm / Prometheus / HPA 가 그대로 쓰이고, GPU / KServe / vLLM / Argo 같은 ML 전용 도구로 확장합니다.
