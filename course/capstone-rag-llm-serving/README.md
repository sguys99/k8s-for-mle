# Capstone — RAG 챗봇 + LLM 서빙 종합 프로젝트

본 코스 자료(`course/phase-*/**/lesson.md` + `docs/study-roadmap.md`) 를 인덱싱한 Qdrant 벡터 DB +
vLLM(microsoft/phi-2) + RAG API(FastAPI) 통합 시스템을 K8s 위에 배포하고, Prometheus/Grafana
모니터링과 HPA 커스텀 메트릭 오토스케일링까지 마무리하는 10 일 캡스톤입니다. 학습 완료 시
**`curl http://<ingress-host>/chat ...`** 한 줄로 RAG 응답 + 인용 문서 3 개를 받습니다.

## 시스템 아키텍처

```
                    ┌─────────────────────── rag-llm namespace ───────────────────────┐
External client     │                                                                 │
    │               │   ┌──── Ingress (GCE) ─── rag-api Service ─── RAG API ─────┐    │
    │  HTTP /chat   │   │   <IP>.nip.io          ClusterIP 8001    Deployment   │    │
    └──────────────►│───┘                                          replicas=2    │    │
                    │                                                  │  │      │    │
                    │   ┌── Argo CronWorkflow (KST 03:00) ──┐         │  │ FastAPI    │
                    │   │  git-clone → load → chunk →       │         │  │  /chat /metrics  │
                    │   │  embed → upsert (5-step DAG)      │         │  │            │
                    │   └────────────┬──────────────────────┘         │  │            │
                    │                ▼                                 ▼  ▼            │
                    │   ┌── Qdrant ──────┐         ┌── vLLM ───────────────┐          │
                    │   │  StatefulSet 1 │         │  Deployment, GPU=T4   │          │
                    │   │  PVC 5Gi       │         │  PVC 20Gi (모델 캐시) │          │
                    │   │  6333 (REST)   │         │  8000 (OpenAI 호환)   │          │
                    │   └────────────────┘         └───────────────────────┘          │
                    │                                                                 │
                    │   ┌── Prometheus / Grafana / prometheus-adapter (monitoring ns) │
                    │   │  ServiceMonitor 2 종 → HPA 2 (vllm + rag-api 커스텀 메트릭) │
                    └─────────────────────────────────────────────────────────────────┘
```

자세한 결정 노트는 [docs/architecture.md](docs/architecture.md) (§1~§3.15, §4 PVC 산정, §5 메트릭 표) 참조.

## Day 1~10 일정표

| Day | 주제 | 산출물 | lab |
|-----|------|--------|-----|
| 1   | Namespace + Qdrant StatefulSet + Headless Service | manifests/00·10·11 + docs/architecture.md | [day-01](labs/day-01-namespace-qdrant.md) |
| 2   | 인덱싱 스크립트 로컬 (5 단계 + idempotent upsert) | practice/pipelines/indexing/ | [day-02](labs/day-02-indexing-script-local.md) |
| 3   | 인덱싱 Argo Workflow + CronWorkflow | manifests/49·50·51 | [day-03](labs/day-03-indexing-argo.md) |
| 4   | vLLM Deployment + OpenAI 호환 API 검증 | manifests/20·21·22·23 | [day-04](labs/day-04-vllm-deploy.md) |
| 5   | RAG API 구현 (retriever + LLM 결합) | practice/rag_app/ (9 파일) | [day-05](labs/day-05-rag-api-impl.md) |
| 6   | RAG API Deployment + Service + GCE Ingress | manifests/30·31·40 | [day-06](labs/day-06-rag-api-deploy.md) |
| 7   | ConfigMap/Secret 분리 + ServiceMonitor 2 종 | manifests/24·32·33·34 | [day-07](labs/day-07-config-secret-monitoring.md) |
| 8   | Grafana 대시보드 + HPA 커스텀 메트릭 (adapter) | manifests/25·35·60·61 | [day-08](labs/day-08-grafana-hpa.md) |
| 9   | 부하 테스트(`hey`) + vLLM args 튜닝 (0.85→0.90) | practice/llm_serving/ | [day-09](labs/day-09-load-test-tuning.md) |
| 10  | Helm 차트 통합 + 6 단계 검증 + GKE 정리 | helm/ (15 파일) | [day-10](labs/day-10-helm-integration-cleanup.md) |

## 사전 준비

- **GKE 클러스터** + T4 노드 풀 1 노드 (`nvidia.com/gpu=present:NoSchedule` taint) — Day 4 부터 필수
- **Docker Hub 본인 계정** — Day 3 (rag-indexer) + Day 6 (rag-api) 이미지 푸시
- **Argo Workflows controller** — Day 3 에 `kubectl apply -n argo -f https://github.com/argoproj/argo-workflows/releases/download/v3.5.7/quick-start-minimal.yaml`
- **kube-prometheus-stack** — Day 7 에 `helm install prom prometheus-community/kube-prometheus-stack -n monitoring --create-namespace`
- **prometheus-adapter** — Day 8 에 `helm install prometheus-adapter ... -f manifests/60-prometheus-adapter-values.yaml -n monitoring`
- HuggingFace 토큰 (선택) — phi-2 / e5-small 은 public, gated 모델 사용 시 필수

## 빠른 시작 (Day 10 한 줄 배포)

```bash
# 1) prod 환경 install (학습자별 변수 3 개 주입)
helm install rag-llm helm/ -n rag-llm --create-namespace \
  -f helm/values-prod.yaml \
  --set ragApi.image.repository=docker.io/<user>/rag-api \
  --set indexing.imageRepository=docker.io/<user>/rag-indexer \
  --set indexing.gitRepo=https://github.com/<user>/k8s-for-mle.git

# 2) Pod Ready 대기 (~6~8 분, vLLM 첫 다운로드 5GB 포함)
kubectl get pods -n rag-llm -w

# 3) Ingress IP 받은 후 host 갱신
EXTERNAL_IP=$(kubectl get ing rag-api -n rag-llm -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
helm upgrade rag-llm helm/ -n rag-llm -f helm/values-prod.yaml --set ingress.host=$EXTERNAL_IP.nip.io

# 4) 1 줄 완료 기준 (200 OK + sources 3)
curl http://$EXTERNAL_IP.nip.io/chat \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"K8s에서 GPU 어떻게 잡지?"}],"top_k":3}' | jq
```

## 🚨 GKE 비용 경고

| 자원 | 시간당 | 일 (24h) |
|------|--------|---------|
| T4 GPU 노드 (n1-standard-4) | ~$0.35 | ~$8.4 |
| GCE Ingress + LoadBalancer  | ~$0.025 | ~$0.6 |
| External IP / Disks 등      | ~$0.01 | ~$0.24 |
| **합산** | **~$0.4** | **~$9.2** |

작업 종료 후 반드시 클러스터 삭제 + 잔여 자원 점검:

```bash
helm uninstall rag-llm -n rag-llm
kubectl delete namespace rag-llm
gcloud container clusters delete capstone --zone us-central1-a --quiet
gcloud compute addresses list && gcloud compute disks list   # 잔여 0 확인
```

## 문서 링크

- [lesson.md](lesson.md) — 이론 (1900+ 줄, §0~§12)
- [docs/architecture.md](docs/architecture.md) — 결정 노트 (§3.1~§3.15)
- [labs/README.md](labs/README.md) — Day 1~10 lab 인덱스
- 진행 상태: [docs/capstone-plan.md](../../docs/capstone-plan.md) §7~§9 (체크박스)
- 커리큘럼 SSOT: [docs/study-roadmap.md](../../docs/study-roadmap.md) §Capstone

## 라이선스 / 출처

- 모델 출처: `microsoft/phi-2` (MIT), `intfloat/multilingual-e5-small` (MIT)
- 본 코스 자료: 본 repo 의 LICENSE 파일 적용
