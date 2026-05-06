# 캡스톤 시스템 아키텍처

> **버전**: Day 1~2 작성분 (2026-05-06)
> **상위 문서**: [`docs/capstone-plan.md`](../../../docs/capstone-plan.md), [`lesson.md`](../lesson.md) §1·§3.2·§4.6
> **다음 갱신**: Day 4(vLLM cold start) → Day 8(HPA 커스텀 메트릭)

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

이와 별개로, **인덱싱 파이프라인**이 본 코스 자료를 청크/임베딩하여 Qdrant 에 저장합니다. 챗봇 호출 경로(synchronous) 와 인덱싱 경로(batch, scheduled) 가 분리되어 있는 것이 이 시스템의 핵심 구조입니다.

```
[course/phase-*/**/lesson.md + docs/study-roadmap.md]
   │
   ▼
[ load-docs ]   화이트리스트 글로브 + phase/topic 메타 추출
   │  docs.jsonl
   ▼
[ chunk     ]   MarkdownHeaderTextSplitter → RecursiveCharacterTextSplitter
   │  chunks.jsonl  (heading 메타 4종 부여)
   ▼
[ embed     ]   intfloat/multilingual-e5-small (384 dim)
   │  embeddings.jsonl
   ▼
[ upsert    ]   idempotent: create_collection_if_not_exists + uuid5(point_id) + upsert
   │
   ▼
[ Qdrant rag-docs collection (Day 1 PVC 에 영속화) ]
```

Day 2 에서는 동일 코드를 **로컬 Python** 으로 호출(`python pipeline.py all`), Day 3 에서는 **Argo Workflow 의 4 step** 으로 감싸 클러스터 내부에서 실행합니다. 환경변수(`DOCS_ROOT`, `QDRANT_URL`, `PIPELINE_DATA_DIR`) 만 다르고 코드는 동일합니다.

> ★ Day 1 에서 실제로 만드는 컴포넌트는 **Qdrant StatefulSet + Headless Service + rag-llm Namespace** 까지입니다. Day 2 에서는 클러스터 매니페스트는 추가하지 않고 로컬 인덱싱 스크립트만 작성하며, 인덱싱 결과(컬렉션 데이터) 가 Qdrant PVC 에 적재됩니다.

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

## 3.5 인덱싱 데이터 흐름과 모델 선택 (Day 2 핵심)

§1 의 ASCII 시퀀스가 4 단계 흐름의 윤곽이라면, 본 절은 각 단계의 **결정 근거**를 정리합니다. 코드 전문은 [`../practice/pipelines/indexing/pipeline.py`](../practice/pipelines/indexing/pipeline.py), 실행 절차는 [`../labs/day-02-indexing-script-local.md`](../labs/day-02-indexing-script-local.md) 를 참고하세요.

### 3.5.1 입력 화이트리스트 — 왜 `lesson.md` 만인가

`labs/`, `manifests/`, README, 작업 노트 등을 모두 인덱싱하면 RAG 검색 결과가 반복적인 메타 텍스트(예: "Phase 진행 체크리스트", "다음 단계 링크") 로 오염됩니다. 본 코스의 **이론 본문은 `lesson.md` 에 집중**되어 있으므로 화이트리스트로 한정합니다.

```python
DOCS_ROOT.glob("phase-*/**/lesson.md") + DOCS_ROOT.glob("capstone-*/lesson.md")
```

추가로 `docs/study-roadmap.md` 1 건을 별도 추가합니다(커리큘럼 SSOT 라 자기참조 검색에서 자주 호출됨).

### 3.5.2 청킹 2 단계 — 왜 헤딩을 먼저 보존하는가

마크다운의 `#` `##` `###` 는 의미 단위 경계와 거의 일치합니다. 처음부터 문자 길이로 자르면 청크가 헤딩 중간에서 끊겨 RAG 응답에서 사람이 읽기 어렵습니다.

| 단계 | splitter | 효과 |
|---|---|---|
| 1차 | `MarkdownHeaderTextSplitter` (h1/h2/h3 보존) | 의미 경계 보존 + `heading` 메타 부여 |
| 2차 | `RecursiveCharacterTextSplitter(512/64)` | 헤딩 섹션이 너무 길면 토큰 한도 안에서 추가 분할 |

결과로 모든 청크가 `Phase 4 > vLLM > startupProbe` 같은 **헤딩 경로** 메타데이터를 갖게 되며, Day 5/6 의 RAG API 가 응답 `sources` 의 출처 라벨로 그대로 노출합니다.

### 3.5.3 임베딩 모델 — 왜 `intfloat/multilingual-e5-small` 인가

캡스톤 plan §4.6 의 초안 표기는 `BAAI/bge-small-en` 이었으나, **본 코스 자료가 한국어 다수**(lesson.md 본문 + 한국어 주석) 라 영어 전용 모델은 한국어 토큰을 OOV 처리에 가깝게 다뤄 retrieval recall 이 떨어집니다.

| 모델 후보 | 언어 | 차원 | 캡스톤 적합성 |
|---|---|---|---|
| `BAAI/bge-small-en` | 영어 전용 | 384 | ❌ 한국어 자료 검색 품질 부족 |
| **`intfloat/multilingual-e5-small`** ✅ | 다국어(한국어 포함) | **384** | ✅ 차원 동일 → §4 PVC 산정 무수정 |
| `BAAI/bge-m3` | 다국어 | 1024 | △ 품질 ↑ 이지만 PVC/Qdrant 차원 변경 필요 |

`multilingual-e5-small` 의 차원이 **384 로 plan 초안과 같으므로 PVC 5Gi 산정값을 바꾸지 않아도** 됩니다. 향후 검색 품질이 부족하면 `bge-m3` 로 교체할 수 있으며, 그 경우 컬렉션을 한 번 비워야 합니다(`pipeline.py` 의 `_ensure_collection` 이 차원 불일치를 명시적 에러로 알려줍니다).

> 💡 **e5 규약 — 접두사 prefix**
>
> e5 계열은 인덱싱 본문에 `passage:`, 검색 쿼리에 `query:` 접두사를 붙여야 의도된 retrieval 품질이 나옵니다. `pipeline.py` 의 `_E5_PASSAGE_PREFIX`/`_E5_QUERY_PREFIX` 상수가 모델명에 `e5` 가 포함되면 자동으로 prefix 를 적용합니다.

### 3.5.4 idempotent upsert — 왜 `recreate_collection` 을 버렸는가

Phase 4-4 의 `recreate_collection` 은 매 실행마다 컬렉션을 비우고 재생성합니다. 학습 흐름상 매번 깨끗한 상태를 보장하지만 캡스톤 운영(Day 7~10) 에서는 다음 문제가 생깁니다.

- **단절 구간**: 인덱싱 도중 RAG API 가 빈 컬렉션을 만나 502 응답 발생
- **부분 갱신 불가**: 1 개 lesson 만 수정해도 전체 재인덱싱 필요
- **CronWorkflow 주기 인덱싱과 충돌**: 야간 배치 동안 모든 검색 일시 비어 보임

캡스톤은 **"컬렉션이 없으면 만들고, 있으면 재사용 + 결정론적 point ID 로 덮어쓰기"** 패턴을 채택해 무중단 재인덱싱과 부분 갱신을 가능하게 합니다.

```python
# point ID = uuid5(NAMESPACE_URL, chunk_id)
# 같은 chunk_id 는 같은 UUID → upsert 가 자연스러운 덮어쓰기로 동작
```

---

## 4. PVC 5Gi 산정 근거

| 항목 | 값 | 비고 |
|---|---|---|
| 본 코스 자료 분량 | 약 50 개 lesson.md (예상) | Phase 0~4 + 캡스톤 + study-roadmap |
| 청크 크기 | 500 토큰 / 청크 | 일반적인 RAG 권장값 |
| 예상 청크 수 | 약 1,500~3,000 청크 | 자료당 30~60 청크 가정 |
| 임베딩 차원 | 384 (intfloat/multilingual-e5-small) | Day 2 결정 — bge-small-en 에서 한국어 대응 다국어 모델로 교체. 차원 동일 → 본 표 무수정 |
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
| Day 2 ✅ | §1 시퀀스 보강 + §3.5 신규 + §4 모델명 갱신 | 인덱싱 4 단계 시퀀스, 화이트리스트/2 단계 청킹/multilingual-e5-small 선택 근거/idempotent upsert 트레이드오프 |
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
