# Phase 3 — 프로덕션 운영 도구 (2주)

Helm으로 매니페스트를 패키징하고, Prometheus/Grafana로 모니터링하며, HPA로 자동 스케일링하는 단계.

## 권장 토픽 분할

```
course/phase-3-production/
├── README.md
├── 01-helm/                    # 차트 구조, install/upgrade/rollback
├── 02-monitoring/              # Prometheus + Grafana 스택
├── 03-logging/                 # Loki/Promtail (선택)
├── 04-autoscaling/             # HPA, VPA, Cluster Autoscaler
└── 05-rbac/                    # ServiceAccount, Role, RoleBinding
```

## 학습 목표 후보

- Helm 차트 구조(`Chart.yaml`, `values.yaml`, `templates/`)를 이해하고 Phase 2 매니페스트를 차트로 변환할 수 있다
- kube-prometheus-stack을 Helm으로 설치하고 Grafana로 메트릭을 시각화할 수 있다
- FastAPI에 `/metrics` 엔드포인트를 추가하고 ServiceMonitor로 자동 스크래핑되게 할 수 있다
- HPA로 CPU/커스텀 메트릭 기반 오토스케일링을 설정할 수 있다
- ServiceAccount + Role + RoleBinding으로 최소 권한 원칙을 적용할 수 있다

## ML 관점 도입

- **Helm**: ML 스택(KServe, Kubeflow, vLLM, Triton)은 거의 다 Helm 차트로 배포됩니다. 차트를 못 읽으면 도입 자체가 어려워집니다
- **모니터링**: 추론 latency p95, throughput, GPU 사용률은 ML 서비스 SLO의 기본
- **HPA**: 트래픽 변동이 큰 추론 API는 오토스케일링이 비용/안정성 양쪽에 결정적

## 핵심 토픽 상세

### 3-1. Helm

차트 구조:
```
my-chart/
├── Chart.yaml          # 메타데이터 (이름, 버전, appVersion)
├── values.yaml         # 기본값
├── templates/          # Go template + K8s 매니페스트
│   ├── deployment.yaml
│   ├── service.yaml
│   └── _helpers.tpl
└── charts/             # 의존 차트
```

기본 명령:
```bash
helm create my-chart           # 보일러플레이트 생성
helm install sentiment ./my-chart -f values-prod.yaml
helm upgrade sentiment ./my-chart --set replicas=5
helm rollback sentiment 1
helm list
helm template ./my-chart       # 렌더링만 (디버깅)
helm uninstall sentiment
```

ML 패턴:
- `values.yaml`에 `model.name`, `model.version`, `replicas`, `resources`, `gpu.enabled` 등 노출
- 환경별 `values-dev.yaml`, `values-prod.yaml` 분리

### 3-2. Prometheus + Grafana (kube-prometheus-stack)

설치:
```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm install prom prometheus-community/kube-prometheus-stack -n monitoring --create-namespace
```

이게 뭘 깔아주냐:
- Prometheus Operator
- Prometheus 서버
- Alertmanager
- Grafana (기본 대시보드 다수)
- node-exporter, kube-state-metrics

ML 메트릭 노출:
- FastAPI에 `prometheus-client`로 `/metrics`
- ServiceMonitor 매니페스트로 자동 스크래핑
- Grafana 대시보드 임포트 (NVIDIA DCGM, vLLM 대시보드 등)

### 3-3. 로깅 (선택)

- **Loki + Promtail + Grafana**: 가벼움, 한 화면에서 메트릭/로그
- **EFK** (Elasticsearch + Fluentd + Kibana): 강력하지만 무거움
- ML에서 추론 요청/응답 로그를 수집하면 디버깅에 유용 (PII 주의)

### 3-4. 오토스케일링

세 가지 레벨:
- **HPA** (Horizontal Pod Autoscaler): Pod 개수 조절. CPU, 메모리, 커스텀 메트릭(req/s)
- **VPA** (Vertical Pod Autoscaler): Pod의 requests/limits 조절. 학습 워크로드에 유용
- **Cluster Autoscaler**: 노드 자체 추가/제거 (클라우드)

ML 패턴:
- 추론 API: HPA로 CPU 70% 또는 req/s 기준
- 학습 Job: HPA보다는 Job 자체 스펙 + GPU 노드 풀 오토스케일
- LLM 서빙: 토큰 처리량(`vllm:num_requests_running`) 기반 커스텀 HPA

### 3-5. RBAC

- **ServiceAccount**: Pod이 누구로 인증되는지
- **Role / ClusterRole**: 권한 묶음
- **RoleBinding / ClusterRoleBinding**: SA에 Role 부여
- ML 패턴:
  - 학습 Job이 결과를 PVC에 쓰고 메트릭을 push하려면 SA 필요
  - 외부 시스템 (S3, GCS) 접근은 IRSA(EKS) 또는 Workload Identity(GKE) 권장

## 권장 실습

**모델 서빙 시스템에 운영 기능 추가**

1. Phase 2 매니페스트를 Helm 차트로 변환 → `helm install` 한 줄로 배포
2. kube-prometheus-stack 설치
3. FastAPI에 `/metrics` 엔드포인트 추가, ServiceMonitor 등록
4. Grafana에 추론 latency / throughput 대시보드 만들기
5. HPA 설정 (CPU 70% 또는 커스텀 메트릭)
6. `hey` 또는 `wrk`로 부하 테스트해 Pod이 자동 증가하는지 확인

## 자주 하는 실수

- Helm `values.yaml`에 너무 많은 옵션을 넣어 사용자가 혼란 → 핵심 5–10개만 노출
- ServiceMonitor를 Prometheus가 발견 못 함 → label selector 확인 (`release: prom`)
- HPA min/max를 너무 좁게 설정 → 트래픽 폭증/폭감 시 대응 못 함
- HPA 메트릭 수집 지연 (보통 30s+) 무시 → 부하 테스트할 때 충분히 기다리기
- RBAC 너무 느슨하게 (`cluster-admin` 부여) → 최소 권한 원칙

## 검증 명령어

```bash
helm list -A
kubectl get servicemonitor
kubectl port-forward svc/prom-grafana -n monitoring 3000:80
# 브라우저로 http://localhost:3000 (admin/prom-operator)

kubectl get hpa
kubectl describe hpa sentiment

# 부하 테스트
hey -z 60s -c 50 http://<svc>/predict
# HPA 변화 관찰
watch kubectl get hpa,pods -l app=sentiment
```

## 다음 단계

Phase 4에서 GPU, KServe/vLLM/Triton 같은 ML 전용 서빙 도구로 확장합니다. Helm/모니터링/HPA가 그대로 활용됩니다.
