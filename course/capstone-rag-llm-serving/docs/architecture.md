# 캡스톤 시스템 아키텍처

> **버전**: Day 1 초안 (2026-05-06)
> **상위 문서**: [`docs/capstone-plan.md`](../../../docs/capstone-plan.md), [`lesson.md`](../lesson.md) §1
> **다음 갱신**: Day 2(인덱싱 데이터 흐름) → Day 4(vLLM cold start) → Day 8(HPA 커스텀 메트릭)

본 문서는 캡스톤 RAG 챗봇 시스템의 컴포넌트 분리 이유와 트레이드오프를 정리합니다. `lesson.md` §1 이 학습용 요약이라면, 본 문서는 그 결정의 근거를 깊이 있게 다루는 **트레이드오프 노트**입니다.

---

## 1. 시스템 개요 — `/chat` 한 건이 흐르는 길

사용자가 Ingress 의 `/chat` 으로 질문을 보내면 다음 6 단계로 처리됩니다.

```
[Client]
   │  POST /chat  {messages, top_k}
   ▼
[Ingress (40-ingress.yaml, Day 6)]
   │  Host 기반 라우팅
   ▼
[RAG API (30-rag-api-deployment.yaml, Day 5~6)]
   │
   ├─(1) 질문 임베딩 생성 (BAAI/bge-small-en, 384 dim)
   │
   ├─(2) Qdrant 검색 ── HTTP ───► [Qdrant StatefulSet (10-..., Day 1) ★]
   │     top_k=3                       │
   │     ◄── 청크 3개 + 메타 ──────────┘
   │
   ├─(3) 프롬프트 합성 (system + context + user)
   │
   ├─(4) vLLM 호출 ── /v1/chat/completions ──► [vLLM Deployment (20-..., Day 4)]
   │                                                    │
   │     ◄────────── 답변 텍스트 + 토큰 사용량 ─────────┘
   │
   ├─(5) sources 3 개와 답변을 합쳐 응답 구성
   │
   ▼
[Client]  200 OK { answer, sources: [doc_id, score] × 3 }
```

이와 별개로, **인덱싱 파이프라인**이 Day 3 의 Argo Workflow 를 통해 본 코스 자료를 청크/임베드하여 Qdrant 에 저장합니다. 챗봇 호출 경로(synchronous) 와 인덱싱 경로(batch, scheduled) 가 분리되어 있는 것이 이 시스템의 핵심 구조입니다.

> ★ Day 1 에서 실제로 만드는 컴포넌트는 **Qdrant StatefulSet + Headless Service + rag-llm Namespace** 까지입니다. 나머지 박스는 후속 Day 에 채워집니다.

---

## 2. 컴포넌트 분리 이유 표

| 컴포넌트 | 워크로드 종류 | 분리 이유 | 영속성 | Day 1 범위 |
|---|---|---|---|---|
| **Qdrant** | StatefulSet | 인덱스 = 상태, ordinal DNS 필요, 재시작 시 인덱스 보존 필수 | PVC 5Gi 필수 | ✅ 본 Day |
| **vLLM** | Deployment | 모델 가중치는 PVC 캐시지만 워크로드 자체는 stateless, GPU 1 개 점유 | PVC(가중치 캐시) | Day 4 |
| **RAG API** | Deployment | 완전 stateless, replica 다수 + HPA 친화 | 없음 | Day 5~6 |
| **인덱싱 Workflow** | Argo Workflow + CronWorkflow | 배치 작업, 주기적 재인덱싱, 챗봇 경로와 라이프사이클 분리 | 입력 PVC 공유 | Day 3 |
| **모니터링** | ServiceMonitor + Grafana | 3 컴포넌트 메트릭을 한 곳에서, prometheus-adapter 가 HPA 에 메트릭 공급 | (없음) | Day 7~8 |

**핵심 원칙 — 상태/무상태/배치를 K8s 워크로드 종류로 정확히 매칭한다.** 이를 어기면(예: Qdrant 를 Deployment 로) 학습용으로는 동작하지만 운영에서는 인덱스 손실, DNS 불안정, 재인덱싱 부담이 발생합니다.

---

## 3. 왜 Qdrant 를 StatefulSet 으로 두는가 (Day 1 핵심)

Phase 4-4 의 학습용 매니페스트(`02-qdrant.yaml`) 는 Argo Workflow 학습에 집중하기 위해 **Deployment + emptyDir** 로 띄웠습니다. Pod 가 재시작되면 인덱스가 사라지지만, 워크플로우 학습 자체에는 지장이 없으므로 의도적인 단순화였습니다.

캡스톤은 이 결정을 뒤집어야 합니다. 이유는 세 가지입니다.

### 3.1 인덱스는 비싼 자산이다

본 코스 자료를 청크/임베드하면 1~2GB 의 인덱스가 생성됩니다. 임베딩 1 회 생성 비용은 작지 않으며(GPU 시간 또는 외부 API 비용), 매번 Pod 재시작 시 재인덱싱하면 캡스톤 검증 시나리오 §1(`인덱싱 Workflow Succeeded`) 가 매번 실패합니다. PVC 로 영속화하는 것이 자연스럽습니다.

### 3.2 ordinal DNS 가 향후 클러스터 확장을 무수정으로 만든다

StatefulSet 은 각 Pod 에 `<sts-name>-<ordinal>.<service-name>` 형식의 안정 DNS 를 발급합니다. 캡스톤 Day 1 에서는 replica 가 1 이라 `qdrant-0.qdrant.rag-llm.svc.cluster.local` 하나뿐이지만, 향후 Qdrant 를 클러스터 모드(replicas=3) 로 확장할 때 이 DNS 패턴이 그대로 동작합니다. Deployment 로 두면 클러스터링 시점에 매니페스트 자체를 갈아엎어야 합니다.

### 3.3 PVC 이름이 결정론적이다

`volumeClaimTemplates` 가 만드는 PVC 이름은 `<vct-name>-<sts-name>-<ordinal>` 규칙을 따릅니다. 캡스톤의 경우 `qdrant-storage-qdrant-0` 입니다. 이름이 결정론적이라는 것은 **백업/복구 자동화 스크립트, 모니터링 라벨링, 디버깅 시 grep** 모두에서 이점이 됩니다. Deployment + 별도 PVC 라면 이름을 직접 관리해야 합니다.

### 3.4 Deployment vs StatefulSet 빠른 비교

| 항목 | Deployment | StatefulSet |
|---|---|---|
| Pod 이름 | `qdrant-7f8c-xz9` (랜덤) | `qdrant-0`, `qdrant-1`, ... (ordinal) |
| DNS | Service IP 만 | Service IP + Pod 단위 안정 DNS |
| PVC | 직접 PVC + selector 매칭 | volumeClaimTemplates 가 자동 생성 |
| 롤링 업데이트 | 임의 순서 | ordinal 역순 (qdrant-2 → 1 → 0) |
| 적합한 워크로드 | stateless API | DB, 메시지 큐, 벡터 인덱스 |

---

## 4. PVC 5Gi 산정 근거

| 항목 | 값 | 비고 |
|---|---|---|
| 본 코스 자료 분량 | 약 50 개 lesson.md (예상) | Phase 0~4 + 캡스톤 + study-roadmap |
| 청크 크기 | 500 토큰 / 청크 | 일반적인 RAG 권장값 |
| 예상 청크 수 | 약 1,500~3,000 청크 | 자료당 30~60 청크 가정 |
| 임베딩 차원 | 384 (BAAI/bge-small-en) | 캡스톤 plan §5 결정 |
| 임베딩 1 개 크기 | 384 × 4 bytes (float32) ≈ 1.5KB | |
| 메타데이터(텍스트, 출처) | 청크당 약 1~2KB | |
| **총 인덱스 크기 추정** | **약 5~12MB** + Qdrant 세그먼트/HNSW 인덱스 | |
| Qdrant 세그먼트 오버헤드 | × 50~200 (HNSW 그래프, payload 인덱스) | |
| **실효 PVC 사용량** | **약 1~2GB** | |
| 여유분 (재인덱싱·세그먼트 머지) | × 2~3 | |
| **할당 PVC** | **5Gi** | |

5Gi 는 학습용 적정선입니다. 운영에서는 자료가 늘어남에 따라 `kubectl edit pvc` 로 확장하거나, 최초 설계 시 storageClass 의 `allowVolumeExpansion: true` 를 확인합니다.

---

## 5. 모니터링 핵심 메트릭 표 (예고)

Day 7~8 에서 Grafana 대시보드를 구축할 때 다음 4 축으로 추적합니다. **Day 1 시점에는 표만 두고 실제 ServiceMonitor/대시보드는 후속 Day 에 추가합니다.**

| 축 | 핵심 메트릭 | 출처 | HPA 연동 |
|---|---|---|---|
| RAG API | `rag_request_duration_seconds_bucket` (p95 latency), `rag_requests_total{status}` | RAG API `/metrics` | RPS 기반 HPA (Day 8) |
| vLLM | `vllm:num_requests_running`, `vllm:num_requests_waiting`, `vllm:gpu_cache_usage_perc` | vLLM `/metrics` | prometheus-adapter 커스텀 메트릭 → HPA |
| Qdrant | `qdrant_collections_total`, `qdrant_search_total`, search latency | Qdrant `/metrics` | (HPA 없음, replica 고정) |
| GPU | `DCGM_FI_DEV_GPU_UTIL`, `DCGM_FI_DEV_FB_USED` | NVIDIA DCGM exporter | (관측용) |

이 메트릭들은 캡스톤 검증 시나리오 §4(부하 테스트 + HPA 스케일) 의 근거가 됩니다.

---

## 6. Qdrant 대안과 선택 이유

| 옵션 | K8s 친화성 | 자가 호스팅 | 비용 | 캡스톤 적합성 |
|---|---|---|---|---|
| **Qdrant** ✅ | StatefulSet 정석, Helm 차트 제공 | ○ | 인프라만 | 학습 + 운영 패턴 모두 자연스러움 |
| Pinecone | API only | × (SaaS) | API 호출당 과금 | K8s 학습 목표와 거리 있음 |
| Milvus | StatefulSet, 의존성(etcd, MinIO) 다수 | ○ | 인프라 | 학습 부담 큼 |
| Chroma | 로컬 개발 친화, K8s 패키징 미성숙 | ○ | 인프라 | 운영 패턴 학습 어려움 |
| pgvector | StatefulSet, Postgres 위에 동작 | ○ | 인프라 | 별도 분리된 벡터 DB 학습 어려움 |

**Qdrant 선택**: K8s 운영 패턴(StatefulSet + PVC + Helm) 학습에 가장 자연스럽고, OpenAI 호환 임베딩과 무관한 자체 SDK 가 명확하며, Phase 4-4 에서 이미 학습용으로 도입한 도구이므로 **학습 누적성**이 가장 높습니다.

---

## 7. Day 별 본 문서 갱신 예정 표

본 문서는 Day 1 초안이며, 캡스톤 진행 중 다음 시점에 보강됩니다.

| Day | 추가/수정 섹션 | 주된 내용 |
|---|---|---|
| Day 2 | §1 시스템 개요 보강 | 인덱싱 파이프라인의 데이터 흐름(load_docs → chunk → embed → upsert) 상세 |
| Day 3 | §2 컴포넌트 표 보강 | Argo Workflow 의 RBAC 권한, CronWorkflow 스케줄 |
| Day 4 | §3 형식의 vLLM 결정 노트 추가 | 왜 vLLM 인가(Ollama, TGI 와 비교), cold start 와 startupProbe |
| Day 5 | §1 시퀀스 다이어그램 정정 | RAG API 내부 단계(임베딩 → 검색 → 합성 → 호출) 실제 구현과 일치시킴 |
| Day 7 | §5 메트릭 표 → 실측값으로 갱신 | ServiceMonitor 가 실제 수집 중인 메트릭 라벨 명시 |
| Day 8 | §5 + HPA 결정 노트 | 왜 CPU 가 아닌 `vllm:num_requests_running` 인가 |
| Day 10 | §6 트레이드오프 보강 | 부하 테스트 결과 + Helm 차트 구조 결정 노트 |

---

## 부록 A. 참조 매니페스트 위치

Day 1 에 이 문서가 다루는 매니페스트는 다음과 같습니다.

- [`../manifests/00-namespace.yaml`](../manifests/00-namespace.yaml) — Namespace
- [`../manifests/10-qdrant-statefulset.yaml`](../manifests/10-qdrant-statefulset.yaml) — Qdrant StatefulSet + volumeClaimTemplates
- [`../manifests/11-qdrant-service.yaml`](../manifests/11-qdrant-service.yaml) — Qdrant Headless Service

이식 원본:

- `course/phase-4-ml-on-k8s/04-argo-workflows/manifests/02-qdrant.yaml` (Deployment + emptyDir → 본 캡스톤에서 StatefulSet + PVC 로 변환)
