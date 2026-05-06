# 캡스톤 시스템 아키텍처

> **버전**: Day 1~4 작성분 (2026-05-07)
> **상위 문서**: [`docs/capstone-plan.md`](../../../docs/capstone-plan.md), [`lesson.md`](../lesson.md) §1·§2.1·§3.2·§3.3·§4.3·§4.6·§4.7
> **다음 갱신**: Day 5(RAG API 시퀀스 정정) → Day 7(메트릭 라벨 실측) → Day 8(HPA 커스텀 메트릭)

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

**Day 4 시점 cold start 메모** — 시퀀스 (4) 의 vLLM 호출 경로는 *정상 운영 시* p95 1~3 초가 일상이지만, vLLM Pod 의 *최초 1 회 기동* 에는 모델 다운로드 5GB+ + GPU 메모리 로드 + KV cache 할당이 합쳐 5~10 분이 걸립니다. 이 cold start latency 는 사용자 요청 경로의 일부가 아니라 *Pod 라이프사이클 한 번에 한 번* 만 발생합니다. Day 4 의 PVC `vllm-model-cache` 는 두 번째 기동부터 30 초 안에 ready 를 보장해 rolling update 가용성을 끌어올립니다 — 자세한 결정 노트는 §3.8 cold start 의 운영적 의미.

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

## 3.6 왜 Job 이 아닌 Argo Workflow 인가 (Day 3 핵심)

§3.5 의 4 단계 인덱싱 흐름을 클러스터 위에서 자동화할 때, K8s 네이티브 옵션은 다음 3 가지입니다.

| 옵션 | 의존성 표현 | 재시도 단위 | 시각화 | 캡스톤 적합성 |
|---|---|---|---|---|
| **단일 Job** (4 subcommand 를 한 번에 `python pipeline.py all`) | (단계 안 보임) | Job 단위 → 처음부터 재실행 | 텍스트 로그 | ❌ 한 단계 실패 = 전체 재실행. embed 가 가장 비싼데 chunk 까지만 됐다면 모델 재다운로드 |
| **4 개 Job + cron** (각 단계마다 Job + `kubectl wait` 폴링) | 사람 또는 별도 스크립트가 의존성 관리 | Job 단위 | 텍스트 로그 × 4 | ❌ 의존성·재시도·파라미터화 모두 사람 손 |
| **Argo Workflow + CronWorkflow** ✅ | DAG `dependencies:` 선언적 | step 단위 (앞단 PVC 결과 보존) | argo-server UI 그래프 + 색상 | ✅ 의존성·재시도·시각화·파라미터화 4 축 모두 매니페스트 1 개로 해결 |

**핵심 트레이드오프 — 학습 부담 vs 운영 가치**

Argo Workflow 의 학습 부담은 namespace 분리 + RBAC 매니페스트 + WorkflowTemplate / DAG / Steps / artifacts 같은 추가 개념 5~6 개입니다. Phase 4-4 에서 한 번 익힌 것을 캡스톤이 그대로 재사용하므로 **추가 학습 비용은 0** 에 가깝고, 얻는 가치(의존성·재시도·시각화·파라미터화) 는 운영 시점에 결정적입니다.

**왜 KubeFlow Pipelines / Tekton 이 아닌가** — KFP 는 ML 메타데이터(실험 추적, lineage) 가 필요할 때, Tekton 은 CI/CD 패턴이 강할 때 더 적합합니다. 캡스톤은 두 가치 모두 부차적이므로 가장 가벼운 Argo 가 자연스럽습니다.

---

## 3.7 단계 간 데이터 공유 — volumeClaimTemplate 통합 마운트

DAG 의 각 step 은 서로 다른 Pod 입니다. 단계 사이 데이터(`docs.jsonl`, `chunks.jsonl`, `embeddings.jsonl`) 를 어떻게 다음 step 에 넘길지 3 가지 옵션이 있습니다.

| 방식 | 데이터 종류 | 인프라 요구 | RWO 노드 제약 | 캡스톤 채택 |
|---|---|---|---|---|
| `parameters` | 작은 string (수 KB) | 없음 (etcd) | 없음 | git-repo URL 등 매니페스트 파라미터로만 사용 |
| `artifacts` (MinIO/S3) | 파일 (KB ~ GB) | ArtifactRepository ConfigMap + 객체 스토리지 | 없음 (RWX 효과) | ❌ MinIO 설치 학습 부담 |
| **`volumeClaimTemplates`** ✅ | 파일 (GB+) | 클러스터 default storageClass | step 들이 같은 노드여야 함 | **단일 PVC `pipeline-data` 의 mountPath 2 개(`/docs`+`/data`) 로 통합** |

### 3.7.1 왜 단일 PVC 통합 마운트인가

`/docs` 와 `/data` 를 별도 PVC 2 개로 나누면 다음 문제가 발생합니다.

- 둘 다 RWO 라 step 마다 노드 제약이 두 번 걸림
- volumeClaimGC 가 PVC 2 개를 따로 정리해야 함
- volumeMounts 선언이 step 마다 2 개씩

**단일 PVC 의 mountPath 2 개로 통합** 하면:

- step 들이 동일 노드에 스케줄되어 RWO 제약이 자연스럽게 충족 (DAG 의 직선 의존성 + Argo controller 의 affinity 추론)
- volumeClaimGC `OnWorkflowCompletion` 이 PVC 1 개만 정리
- 디버깅 시 `kubectl exec ... -- ls /docs /data` 한 번으로 양쪽 확인

### 3.7.2 운영 환경으로 갈 때의 한계

단일 노드 RWO 패턴은 다음 시나리오에서 한계가 명확합니다.

- **step 의 *진짜* 병렬화** (예: embed 를 문서 100 개씩 fan-out): RWO 가 동시 쓰기를 막음 → ReadWriteMany NFS 또는 MinIO artifacts 로 전환
- **다른 워크플로우 간 산출물 공유** (예: 인덱싱 결과 jsonl 을 학습 파이프라인이 입력으로 사용): `OnWorkflowCompletion` 정책으로 PVC 가 자동 삭제되므로 객체 스토리지로 export 하는 step 이 추가로 필요
- **수십 GB 의 중간 산출물**: PVC 2Gi 로는 부족 — `volumeClaimTemplates.spec.resources.requests.storage` 를 늘리거나 객체 스토리지로 전환

캡스톤 학습 단계에서는 단일 PVC 통합 마운트가 가장 단순합니다. Day 9 부하 테스트나 Phase 5 심화 시점에 RWX/객체 스토리지 패턴을 도입할 수 있습니다.

---

## 3.8 vLLM Deployment 결정 노트 (Day 4 핵심)

§1 의 시퀀스 (4) `vLLM 호출 ── /v1/chat/completions ──►` 단계가 본 절의 운영 결정에 의존합니다. vLLM 자체의 본질(PagedAttention / continuous batching / KV cache / `/dev/shm`) 은 [Phase 4-3 lesson.md §1-1~§1-6](../../phase-4-ml-on-k8s/03-vllm-llm-serving/lesson.md#1-핵심-개념) 에서 다뤘으므로, 본 절은 *그 결과물을 RAG 시스템 안의 한 컴포넌트로 배치하는* 운영 결정 4 가지를 트레이드오프 표로 정리합니다.

### 3.8.1 왜 vLLM 인가 — Ollama / TGI / Triton 와 비교

캡스톤이 LLM 서빙을 vLLM 으로 단일화한 근거는 4 가지 도구의 *RAG 시스템 적합성* 입니다. Phase 4-3 의 비교 표를 캡스톤 컨텍스트로 재해석합니다.

| 도구 | 캡스톤 적합성 | 운영적 약점 | 본 캡스톤 채택 |
|---|---|---|---|
| **vLLM** ✅ | OpenAI 호환 API → RAG API 코드 한 줄(`from openai import OpenAI`), continuous batching → 챗봇 가변 prompt 길이 흡수 | LLM 전용 (분류 모델엔 오버킬, 캡스톤 무관) | **메인** — `manifests/20-vllm-deployment.yaml` |
| TGI (HuggingFace Text Generation Inference) | HF 생태계 통합 강함, 양자화 옵션 풍부 | OpenAI 호환 API 가 vLLM 대비 부분 호환 — RAG API 코드에 어댑터 한 층 필요 | ❌ |
| Triton + TensorRT-LLM | NVIDIA 공식, 멀티 모델 동시 운영 | 설정 복잡(model repository + config.pbtxt), TensorRT 모델 변환 부담 | ❌ |
| Ollama | 단일 노트북에서 한 줄(`ollama run llama3`) | K8s 통합 미성숙 (StatefulSet/HPA 패턴 부재) | ❌ — 본 코스 학습 목표(K8s 운영 패턴) 와 불일치 |

핵심 트레이드오프는 ① OpenAI 호환 API 의 *완전성* 과 ② K8s 운영 패턴의 *성숙도* 입니다. 두 축에서 모두 vLLM 이 우세 — 캡스톤 학습 목표 4(retrieval → augmentation → generation) 의 generation 단계가 RAG API 코드를 단순하게 만들어 캡스톤 전체 분량을 한 단계 줄여줍니다.

### 3.8.2 cold start 의 운영적 의미

vLLM 의 *첫 기동* 은 다음 4 단계로 합쳐 5~10 분입니다.

```
Pod 생성 → 컨테이너 시작 → 모델 다운로드 (5~10 분) → GPU 메모리 로딩 (30~60 초) → KV cache 할당 (수 초) → /health 200 OK
```

이 cold start 가 운영의 어디에서 비용으로 나타나는지 4 가지 시나리오로 정리합니다.

| 시나리오 | cold start 영향 | 캡스톤 대응 |
|---|---|---|
| **첫 배포 (Day 4 Step 5~6)** | 학습자가 5~10 분 대기 | startupProbe `failureThreshold: 60` (= 10 분) 으로 livenessProbe 보호 |
| **Pod 재시작 (OOM, eviction 등)** | replica=1 캡스톤은 5~10 분 응답 불가 | PVC `vllm-model-cache` 가 두 번째 기동부터 30 초 안에 ready (Step 9 검증) |
| **Rolling update (Day 6 Helm `replicas≥2`)** | replica 단위 순차 재시작 — 각 30 초 | PVC RWO 가 step 별 노드 제약을 만들지만 single-region GKE 에서는 무시 가능 |
| **노드 풀 size=0 → size=1 복원 (Day 4 정리 후 재개)** | 노드 부팅 + image pull + 모델 다운로드 = 10~15 분 | Day 4 §🧹 정리에 *Day 5 로 이어가지 않을 때만 size=0* 강조 |

**Day 6 Helm 차트 매핑** — Day 10 의 `helm/values-prod.yaml` 은 본 cold start 를 다음 values 로 흡수합니다.

```yaml
vllm:
  replicas: 2                              # rolling update 시 한 replica 가 cold start 동안 다른 replica 가 트래픽 흡수
  startupProbe:
    failureThreshold: 60                   # 학습자 네트워크 5~10 분 다운로드 허용
  modelCache:
    enabled: true                          # PVC 사용 — 두 번째 기동부터 30 초 ready
    size: 20Gi
```

`replicas: 2` + PVC 캐시 + startupProbe 길이 3 가지가 함께 있어야 *사용자 체감 다운타임 0* 으로 모델 교체가 가능합니다.

### 3.8.3 GPU 노드 풀 분리 결정

Day 1~3 의 `capstone` 클러스터는 CPU 워크로드(Qdrant 256MiB / Argo controller 200MiB) 만으로 충분했습니다. Day 4 에서 GPU 가 필요해지는 시점에 두 옵션을 비교했습니다.

| 옵션 | 시간당 비용 (us-central1-a 기준) | 매니페스트 부담 | 비용 효율 |
|---|---|---|---|
| 단일 GPU 노드 풀 — 모든 워크로드를 T4 노드에 | T4 ≈$0.35/노드 (Qdrant/Argo 도 T4 점유) | taint 없음 → 매니페스트 단순 | ❌ 인덱싱 안 도는 시간 동안 GPU 자원 이론상 낭비 |
| **별도 GPU 노드 풀 + taint** ✅ | T4 ≈$0.35/GPU 노드 + e2-medium ≈$0.07/CPU 노드 | tolerations + nodeSelector 매니페스트 라인 2 개 추가 | **CPU 워크로드는 e2-medium, vLLM 만 T4. Day 4 종료 시 GPU 노드 풀만 size=0 으로 축소 가능** |
| 별도 GPU 클러스터 신규 생성 | T4 ≈$0.35/노드 + 클러스터 control plane fee | 클러스터 간 통신(LB/ServiceEndpoint) 추가 | ❌ Day 5/6 RAG API → vLLM 호출이 클러스터 내부 DNS 한 줄로 안 끝남 |

**선택: 별도 GPU 노드 풀 + taint**. taint `nvidia.com/gpu=present:NoSchedule` 은 GKE 가 노드 풀 생성 시 `--node-taints` 옵션으로 자동 부여하고, 매니페스트의 `tolerations` + `nodeSelector` + GPU resource 셋이 통과합니다. Day 4 종료 시점에 노드 풀만 `size=0` 으로 축소하면 시간당 비용 0 — 5 분 내 복원 가능하므로 Day 5~10 진행에 유연합니다.

### 3.8.4 served-model-name 결정

vLLM 의 OpenAI 호환 API 호출 시 `model` 파라미터에 들어가는 문자열의 결정. Phase 4-3 은 `--served-model-name` 을 *명시하지 않아* `--model=microsoft/phi-2` 가 자동으로 served name 이 됐습니다(우연한 동작). 캡스톤은 이를 *명시적 결정* 으로 끌어올려, 모델 교체(Day 9) 시 RAG API 코드 변경 영향을 매니페스트 1 곳으로 줄입니다.

| served name 형식 | 호출 시 model 파라미터 | 모델 교체 시 영향 범위 | 캡스톤 채택 |
|---|---|---|---|
| **`microsoft/phi-2`** (HF ID 그대로) ✅ | `model="microsoft/phi-2"` | 매니페스트 `--served-model-name` + `--model` + RAG API `OPENAI_MODEL` env 3 곳 | **메인** — 학습자가 익숙한 HF ID 호출 그대로 |
| `phi-2` (단축) | `model="phi-2"` | 매니페스트 + RAG API env 2 곳. `--model` 은 별개 (HF ID 유지) | ❌ — 다른 phi 계열(Phi-3.5-mini) 로 교체 시 충돌 |
| `capstone-llm` (논리명) | `model="capstone-llm"` | 매니페스트 1 곳만 (RAG API env 는 그대로) | △ — 운영적으로 가장 깔끔하지만 학습자가 *왜 capstone-llm 인지* 를 한 번 더 추론해야 함 |

**선택: HF ID 그대로**. 캡스톤의 학습 목표는 K8s 운영 패턴 + RAG 시스템 통합이지 *vLLM 추상화의 모범 사례 학습* 이 아니므로, 학습자가 OpenAI SDK 호출(`model="microsoft/phi-2"`) 을 그대로 재현할 수 있는 형식이 우선합니다. 향후 Phase 5(GitOps + 멀티 클러스터) 에서 같은 인터페이스로 여러 모델을 운영할 일이 생기면 논리명(`capstone-llm`) 으로 마이그레이션 — 그때는 `--served-model-name` 한 줄 변경 + RAG API env 한 줄 변경 = 2 곳만 수정.

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
| Day 3 ✅ | §3.6·§3.7 신규 | Job vs Workflow 4 축 비교, 단계 간 데이터 공유(volumeClaimTemplate 통합 마운트) 결정 노트, 운영 한계 |
| Day 4 ✅ | §3.8 vLLM Deployment 결정 노트 신규 + §1 시퀀스 본문 cold start 단락 추가 | §3.8.1 왜 vLLM(Ollama/TGI/Triton 비교), §3.8.2 cold start 의 운영적 의미(rolling update + Helm values 매핑), §3.8.3 GPU 노드 풀 분리(taint), §3.8.4 served-model-name 결정 |
| Day 5 | §1 시퀀스 다이어그램 정정 | RAG API 내부 단계(임베딩 → 검색 → 합성 → 호출) 실제 구현과 일치시킴 |
| Day 7 | §5 메트릭 표 → 실측값으로 갱신 | ServiceMonitor 가 실제 수집 중인 메트릭 라벨 명시 |
| Day 8 | §5 + HPA 결정 노트 | 왜 CPU 가 아닌 `vllm:num_requests_running` 인가 |
| Day 10 | §6 트레이드오프 보강 | 부하 테스트 결과 + Helm 차트 구조 결정 노트 |

---

## 부록 A. 참조 매니페스트 위치

Day 1~3 에 이 문서가 다루는 매니페스트는 다음과 같습니다.

**Day 1**

- [`../manifests/00-namespace.yaml`](../manifests/00-namespace.yaml) — Namespace
- [`../manifests/10-qdrant-statefulset.yaml`](../manifests/10-qdrant-statefulset.yaml) — Qdrant StatefulSet + volumeClaimTemplates
- [`../manifests/11-qdrant-service.yaml`](../manifests/11-qdrant-service.yaml) — Qdrant Headless Service

**Day 3**

- [`../manifests/49-argo-rbac.yaml`](../manifests/49-argo-rbac.yaml) — Argo workflow ServiceAccount + Role + RoleBinding (`rag-llm` namespace)
- [`../manifests/50-indexing-workflow.yaml`](../manifests/50-indexing-workflow.yaml) — 5-step DAG Workflow (git-clone → load-docs → chunk → embed → upsert)
- [`../manifests/51-indexing-cronworkflow.yaml`](../manifests/51-indexing-cronworkflow.yaml) — CronWorkflow (매일 03:00 KST, concurrencyPolicy: Replace)

**Day 4**

- [`../manifests/20-vllm-deployment.yaml`](../manifests/20-vllm-deployment.yaml) — vLLM Deployment (microsoft/phi-2, GPU 노드 격리 3 종, args 6 종 + `--served-model-name`, startupProbe failureThreshold 60, /dev/shm tmpfs 4Gi, 모델 캐시 PVC 마운트)
- [`../manifests/21-vllm-pvc.yaml`](../manifests/21-vllm-pvc.yaml) — 모델 가중치 캐시 PVC (RWO 20Gi, Pod 재시작 시 30 초 ready)
- [`../manifests/22-vllm-service.yaml`](../manifests/22-vllm-service.yaml) — ClusterIP Service (vllm.rag-llm.svc.cluster.local:8000, 모델 교체 무관 안정 endpoint)
- [`../manifests/23-vllm-hf-secret.yaml`](../manifests/23-vllm-hf-secret.yaml) — HF 토큰 Secret (옵션 — phi-2 는 public 이라 미적용 가능)

이식 원본:

- `course/phase-4-ml-on-k8s/04-argo-workflows/manifests/02-qdrant.yaml` (Deployment + emptyDir → 본 캡스톤에서 StatefulSet + PVC 로 변환)
- `course/phase-4-ml-on-k8s/04-argo-workflows/manifests/01-argo-rbac.yaml` (namespace `ml-pipelines` → `rag-llm` 변경)
- `course/phase-4-ml-on-k8s/04-argo-workflows/manifests/20-rag-indexing-workflow.yaml` (5 가지 변경 — namespace, git-clone step 신규 추가, 이미지 레지스트리, env 6 종 주입, volumeClaimTemplate 통합 마운트)
- `course/phase-4-ml-on-k8s/04-argo-workflows/manifests/30-rag-indexing-cron.yaml` (workflowSpec 본문을 50 과 동기화)
- `course/phase-4-ml-on-k8s/03-vllm-llm-serving/manifests/{vllm-phi2-deployment, vllm-pvc, vllm-service, vllm-hf-secret}.yaml` (Day 4 — 6 가지 변경: namespace `rag-llm`, labels 캡스톤 컨벤션, 이름 `vllm-phi2` → `vllm`, PVC `vllm-phi2-cache` → `vllm-model-cache`, args 에 `--served-model-name=microsoft/phi-2` 추가, ServiceMonitor/HPA 라벨 제거)
