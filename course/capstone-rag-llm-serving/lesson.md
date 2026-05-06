# 캡스톤: RAG 챗봇 + LLM 서빙 종합 프로젝트

> **Phase**: Capstone — Phase 1~4 누적 통합
> **소요 기간**: 1~2주 (10일 일정)
> **선수 학습**: Phase 0 ~ Phase 4 전체 (특히 Phase 4-3 vLLM, Phase 4-4 Argo Workflows)
> **본 문서 진행 상태**: Day 1~4 작성분 (학습 목표 + §1 시스템 아키텍처 + §2 vLLM 분리 트레이드오프 + §3.2 인덱싱 데이터 흐름 + §3.3 인덱싱 Workflow DAG + §4.1·§4.2·§4.3·§4.6·§4.7 매니페스트 해설 + §10 자주 하는 실수 12건). 나머지 섹션(§5·§6·§7·§8·§9·§11) 은 Day 별로 누적 보강됩니다.

---

## 학습 목표

이 캡스톤을 마치면 다음 6 가지를 할 수 있습니다.

1. 여러 K8s 워크로드(Deployment, StatefulSet, Job/Workflow)를 통합한 **다중 컴포넌트 ML 시스템**을 설계할 수 있습니다.
2. vLLM 으로 SLM 을 K8s 에 서빙하고 OpenAI 호환 API 로 RAG API 에서 호출할 수 있습니다.
3. Qdrant 벡터 DB 를 StatefulSet 으로 운영하고 PVC 로 인덱스를 영속화할 수 있습니다.
4. retrieval → augmentation → generation 으로 이어지는 RAG 파이프라인을 K8s 환경에서 구현할 수 있습니다.
5. Prometheus/Grafana 로 멀티 컴포넌트 시스템을 모니터링하고 HPA(커스텀 메트릭)로 LLM 서빙을 오토스케일링할 수 있습니다.
6. 캡스톤 시스템 전체를 Helm 차트 한 줄로 배포·롤백할 수 있습니다.

**완료 기준 (1 줄)**

```bash
curl http://<ingress-host>/chat \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"K8s에서 GPU 어떻게 잡지?"}],"top_k":3}'
# → 200 OK + 답변 텍스트 + 인용 문서 3 개
```

---

## 도입 — 왜 ML 엔지니어에게 필요한가

ML 엔지니어가 RAG 시스템을 모델 코드 한 덩어리로 다루면, 검색 품질·LLM 비용·인덱스 신선도·동시성 처리 중 어느 하나가 흔들릴 때 어디부터 손볼지 결정할 수 없습니다. 캡스톤은 이 시스템을 **K8s 워크로드 종류에 따라 정확히 분리**하는 훈련입니다. 인덱스는 상태이므로 StatefulSet, LLM 서빙은 GPU 점유 stateless 이므로 Deployment, RAG API 는 HPA 친화적인 stateless Deployment, 인덱싱은 배치이므로 Argo Workflow — 이 매핑을 직접 구축해 보면 운영 중 마주칠 문제(인덱스 손실, 비용 과다, 콜드 스타트, 수평 확장 한계) 의 해결 위치가 자연스럽게 보입니다. 본 코스 자료를 인덱싱하여 자기 자신을 답할 수 있는 챗봇으로 만드는 것이 10 일 일정의 목표입니다.

---

## 1. 시스템 아키텍처

### 1.1 전체 구성도

```
                                             ┌─────────────────────────────────┐
                                             │       rag-llm Namespace         │
                                             │                                 │
   [User]                                    │   ┌──────────────────────┐      │
     │                                       │   │ Ingress (Day 6)      │      │
     │  POST /chat                           │   │  /chat → rag-api     │      │
     ▼                                       │   └──────┬───────────────┘      │
   ┌──────────────────────────┐              │          │                      │
   │ <ingress-host>           │ ─────────────┼──────────▶                      │
   └──────────────────────────┘              │   ┌──────▼───────────────┐      │
                                             │   │ RAG API (Day 5~6)    │      │
                                             │   │ Deployment + HPA     │      │
                                             │   │ /chat /healthz /metrics│    │
                                             │   └──┬─────────────────┬─┘      │
                                             │      │                 │        │
                                             │      │ HTTP            │ /v1/chat/completions
                                             │      ▼                 ▼        │
                                             │   ┌─────────────┐  ┌─────────┐  │
                                             │   │ Qdrant      │  │ vLLM    │  │
                                             │   │ StatefulSet │  │ Deploy  │  │
                                             │   │ ★ Day 1 ★   │  │ ★ Day 4 ★│  │
                                             │   │ + PVC 5Gi   │  │ + GPU   │  │
                                             │   └──────▲──────┘  └─────────┘  │
                                             │          │                      │
                                             │          │ upsert(임베딩)       │
                                             │   ┌──────┴──────────────┐       │
                                             │   │ 인덱싱 Workflow      │      │
                                             │   │ ★ Day 3 ★            │      │
                                             │   │ Argo Workflow        │      │
                                             │   │ + CronWorkflow       │      │
                                             │   └──────▲──────────────┘      │
                                             │          │ submit              │
                                             │          │                      │
                                             └──────────┼─────────────────────┘
                                                        │
                                             ┌──────────┴───────────────────┐
                                             │ argo Namespace               │
                                             │  workflow-controller         │
                                             │  argo-server (UI :2746)      │
                                             │  ★ Day 3 (quick-start-min) ★ │
                                             └──────────────────────────────┘

                                             rag-llm 내 추가:
                                             [ServiceMonitor × 3] (Day 7)
                                             [HPA × 2] (Day 8)
```

★ **Day 1 에서 실제로 만드는 것은 Namespace + Qdrant StatefulSet + Headless Service 3 개**입니다. 나머지 박스는 후속 Day 에 채워집니다. **Day 3 에서는 별도 namespace `argo` 에 Argo controller 를 quick-start-minimal 로 설치**하고, `rag-llm` 안에 Workflow + CronWorkflow + RBAC 3 개를 추가합니다. **Day 4 에서는 GKE T4 노드 풀을 캡스톤 클러스터에 추가**해 GPU 워크로드와 CPU 워크로드를 같은 클러스터에서 분리 운영하고, `rag-llm` 안에 vLLM Deployment + Service + 모델 캐시 PVC + (옵션)HF Secret 4 개를 배치합니다.

### 1.2 컴포넌트 역할

| 컴포넌트 | 워크로드 종류 | 역할 | 영속성 | 첫 등장 Day |
|---|---|---|---|---|
| `rag-llm` Namespace | (cluster-scoped) | 캡스톤 전 컴포넌트 격리 | — | Day 1 |
| Qdrant | StatefulSet | 벡터 인덱스 저장·검색 | PVC 5Gi | **Day 1** |
| 인덱싱 Workflow | Argo Workflow | 본 코스 자료를 청크/임베드/upsert | (입력 PVC) | Day 3 |
| vLLM | Deployment | SLM 서빙(OpenAI 호환 API) | PVC(가중치 캐시) | Day 4 |
| RAG API | Deployment + HPA | retrieval + 프롬프트 합성 + LLM 호출 | 없음 | Day 5~6 |
| Ingress | Ingress | `/chat` 외부 노출 | — | Day 6 |
| ServiceMonitor × 3 | CRD | Prometheus 가 3 컴포넌트 메트릭 수집 | — | Day 7 |
| HPA × 2 | HPA | RAG API(RPS), vLLM(`vllm:num_requests_running`) | — | Day 8 |

### 1.3 왜 단일 Namespace `rag-llm` 인가

- **RBAC 단위 일치**: 캡스톤 운영자에게 `rag-llm` Namespace 단위 Role 만 부여하면 모든 컴포넌트 접근 권한이 한 번에 정해집니다.
- **ResourceQuota·NetworkPolicy 적용 단위**: 후속 Phase 에서 캡스톤 전체에 GPU 쿼터, 송수신 정책을 일괄 적용 가능합니다.
- **DNS 가독성**: `qdrant.rag-llm.svc`, `vllm.rag-llm.svc`, `rag-api.rag-llm.svc` 처럼 의도가 명확한 호출 경로가 생깁니다.
- **삭제 단위 일치**: `kubectl delete namespace rag-llm` 한 줄로 깔끔히 정리됩니다(Day 10 정리 명령).

상세 트레이드오프와 컴포넌트 분리 근거는 [`docs/architecture.md`](docs/architecture.md) §2~§3 에서 다룹니다.

---

## 2. 왜 이렇게 분리했는가 (트레이드오프)

§1 의 컴포넌트 매핑이 *형식*이라면, 본 섹션은 그 매핑을 *왜 그렇게 갈라야 하는지* 의 근거입니다. 학습용으로는 한두 컴포넌트만 묶어도 동작하지만, 운영 시점에 한 축이 흔들리면 다른 축까지 함께 무너지는 *결합* 이 잠복합니다. 본 캡스톤은 그 결합을 K8s 워크로드 종류로 정확히 끊어내는 훈련입니다.

상세 트레이드오프 노트는 [`docs/architecture.md`](docs/architecture.md) §3 시리즈에 누적되며, 본 섹션은 *각 분리 결정의 한 줄 근거*만 모읍니다.

### 2.1 왜 vLLM 을 RAG API 와 분리하는가 (Day 4 핵심)

가장 단순한 RAG 시스템은 *retrieval + 프롬프트 합성 + LLM 추론* 을 한 프로세스(예: FastAPI 안에서 `transformers.pipeline()` 직접 호출) 에 넣는 것입니다. 학습용으로는 동작하지만, 운영 시점에 4 가지 독립적인 축이 같은 코드 안에서 결합돼 어디부터 손볼지 결정할 수 없게 됩니다. 캡스톤은 vLLM 을 **별도 Deployment** 로 분리해 이 4 축을 각각의 결정 단위로 풀어냅니다.

#### ① 스케일 단위가 다르다 — GPU 점유 vs stateless 다중 replica

| 워크로드 | 스케일 단위 | 자원 종류 | HPA 메트릭 |
|---|---|---|---|
| **vLLM** | GPU 1 장 = 1 Pod (GPU 단위 정수) | 비싼 GPU 점유 | `vllm:num_requests_running` (커스텀 메트릭) |
| **RAG API** | replica N (CPU 단위 가변) | 싼 CPU/메모리 | `rps` 또는 CPU% (Day 8 의 표준 HPA) |

같은 Pod 에 묶으면 *RAG API 가 5 replica 로 스케일 아웃* 하면 vLLM 도 함께 5 GPU 를 점유하려 시도해 GPU 자원이 즉시 고갈됩니다. 분리해야 RAG API 만 5 로 늘리고 vLLM 은 1~2 GPU 에서 continuous batching 으로 처리하는 *비대칭 스케일* 이 가능합니다. (Day 8 HPA 작성 시 두 메트릭 축이 별개임을 다시 다룹니다.)

#### ② 라이프사이클이 다르다 — 모델 가중치 5GB+ vs 빠른 코드 배포

vLLM 의 첫 기동은 **모델 다운로드 5~10 분** + GPU 메모리 로딩 + KV cache 할당이 합쳐 5~10 분(Day 4 §4.3 결정 박스 ②). RAG API 의 코드 변경은 *retriever 가중치 튜닝, 프롬프트 템플릿 수정, top_k 변경* 같이 **빈번 + 가벼움** 이라 30 초 이내 rolling update 가 자연스럽습니다.

같은 Pod 에 묶으면 RAG API 코드 한 줄 수정마다 vLLM 도 함께 5~10 분 cold start. 분리하면 RAG API 의 빠른 배포 사이클을 vLLM 이 막지 않고, vLLM 의 모델 캐시 PVC(`vllm-model-cache`, Day 4 `manifests/21`) 가 두 번째 기동부터 30 초 이내 ready 를 보장합니다.

#### ③ 메트릭 축이 다르다 — `vllm:num_requests_running` vs RPS

vLLM 의 *진짜 부하* 는 GPU KV cache 사용률(`vllm:gpu_cache_usage_perc`) 과 동시 처리 요청 수(`vllm:num_requests_running`) 입니다. RAG API 의 *진짜 부하* 는 들어오는 RPS(`rag_requests_total{status} rate`) 와 retriever latency(`rag_retriever_duration_seconds`) 입니다. 두 메트릭은 **서로 독립적으로 움직입니다** — vLLM 이 KV cache 를 다 채워도 RAG API 는 retriever 캐시로 추가 요청을 받을 수 있고, 그 반대도 가능합니다.

같은 Pod 의 같은 HPA 정책으로 두 워크로드를 다스리면 항상 한쪽 메트릭이 무시됩니다. 분리하면 Day 8 에서 HPA × 2 를 작성해 *각자의 메트릭으로 각자 스케일* 합니다 — 이것이 캡스톤 §7 (HPA 커스텀 메트릭) 의 핵심 결정입니다.

#### ④ 모델 교체 빈도가 코드 수정 빈도보다 훨씬 낮다

캡스톤의 LLM 모델 교체(예: phi-2 → Qwen2.5-1.5B-Instruct) 는 **분기에 1 회 이하**, RAG API 코드 수정(retriever 알고리즘, 프롬프트 템플릿) 은 **주에 수회**. 같은 Pod 에 묶으면 *낮은 빈도의 모델 교체* 도 RAG API rolling update 와 동일한 사이클을 강요받아 *불필요한 5~10 분 cold start* 가 매번 발생합니다.

분리하면 모델 교체는 vLLM Deployment 의 `args` + `OPENAI_MODEL` env 두 곳만 수정 → vLLM 만 재배포. RAG API 는 그대로 돌아가 사용자 체감 다운타임 0. (Day 4 §4.3 결정 박스 ②의 `--served-model-name` 명시가 이 분리를 매니페스트 1 곳으로 줄입니다.)

> 💡 **Phase 4-3 자료의 깊이를 캡스톤이 그대로 이어받습니다.** vLLM 의 PagedAttention / continuous batching / KV cache / `/dev/shm` 같은 *vLLM 자체 운영 깊이* 는 [Phase 4-3 lesson.md §1-1 ~ §1-6](../phase-4-ml-on-k8s/03-vllm-llm-serving/lesson.md#1-핵심-개념) 에서 충분히 다뤘습니다. 본 캡스톤 §4.3 은 그 결과물을 *RAG 시스템 안에서 어떻게 배치할 것인가* 의 결정에 집중합니다 — 같은 매니페스트지만 보는 각도가 다릅니다.

### 2.2 왜 인덱싱을 Argo Workflow 로 분리하는가 (Day 3)

인덱싱은 GPU/CPU 를 길게 점유하는 배치이고 챗봇 호출은 짧은 동기 응답입니다. 두 작업의 라이프사이클·재시도 단위·시각화 요구가 모두 달라 단일 Job 으로 묶을 수 없습니다. 결정 근거 4 축(의존성·재시도·시각화·파라미터화) 비교는 [`docs/architecture.md`](docs/architecture.md) §3.6, 단계 간 데이터 공유(`volumeClaimTemplates` 통합 마운트) 는 §3.7 참조.

### 2.3 왜 RAG API 를 별도 Deployment 로 분리하는가 (Day 5~6)

<!-- TBD: Day 5~6 에서 작성합니다. retrieval + 프롬프트 합성 로직이 자주 바뀌므로 빠른 배포 사이클이 필요한 점, vLLM/Qdrant 호출이 모두 상류 의존성이라 RAG API 만 stateless 한 점을 다룹니다. -->

### 2.4 왜 단일 Namespace `rag-llm` 인가

§1.3 에서 다룬 4 가지 근거(RBAC 단위 일치 / ResourceQuota·NetworkPolicy 적용 단위 / DNS 가독성 / 삭제 단위 일치) 와 동일합니다. Day 1 시점에 결정.

---

## 3. 데이터 흐름

캡스톤 시스템에는 두 개의 데이터 흐름이 존재합니다. 사용자 요청을 처리하는 **챗봇 호출 흐름**(synchronous, online) 과 본 코스 자료를 청크/임베딩하여 Qdrant 에 적재하는 **인덱싱 데이터 흐름**(batch, offline) 입니다. 둘을 분리하는 것이 캡스톤 아키텍처의 핵심 결정입니다.

### 3.1 챗봇 호출 흐름 (`/chat` → 응답)

<!-- TBD: Day 5 에서 RAG API 구현과 함께 작성합니다.
     단계: 임베딩 생성 → Qdrant 검색 → 프롬프트 합성 → vLLM 호출 → sources 첨부 응답. -->

### 3.2 인덱싱 데이터 흐름 (오프라인)

본 코스 자료를 청크/임베딩하여 Qdrant 컬렉션 `rag-docs` 로 적재하는 **오프라인 배치 흐름**입니다. Day 2 에서는 로컬 Python 으로, Day 3 에서는 Argo Workflow 의 4 단계 step 으로 동일 코드를 실행합니다.

```
[코스 자료 트리 (입력)]
   │   course/phase-*/**/lesson.md  (약 20 파일)
   │   docs/study-roadmap.md
   ▼
┌──────────────────────────────────────────────────────────────────┐
│ load-docs                                                        │
│  - 화이트리스트 글로브 (phase-*/**/lesson.md + capstone-*/lesson.md) │
│  - 메타데이터 추출: phase / topic (디렉토리명에서 파싱)            │
│  - 출력: docs.jsonl  {id, source, phase, topic, text}            │
└──────────────────────────────────────────────────────────────────┘
   │
   ▼
┌──────────────────────────────────────────────────────────────────┐
│ chunk                                                            │
│  - 1차 MarkdownHeaderTextSplitter (h1/h2/h3 보존)                 │
│  - 2차 RecursiveCharacterTextSplitter (chunk_size=512, overlap=64) │
│  - heading 메타데이터 부여 (`Phase 4 > vLLM > startupProbe` 형식)  │
│  - 출력: chunks.jsonl  {…, heading, chunk_index}                 │
└──────────────────────────────────────────────────────────────────┘
   │
   ▼
┌──────────────────────────────────────────────────────────────────┐
│ embed                                                            │
│  - 모델: intfloat/multilingual-e5-small (384 dim, 한국어 대응)    │
│  - 모델 1 회 로드 후 model.encode(batch_size=32) 일괄 처리         │
│  - e5 규약: 본문 앞에 'passage: ' 접두사 자동 부여                 │
│  - 출력: embeddings.jsonl  {…, vector: float[384]}               │
└──────────────────────────────────────────────────────────────────┘
   │
   ▼
┌──────────────────────────────────────────────────────────────────┐
│ upsert                                                           │
│  - 컬렉션이 없으면 생성, 있으면 재사용 (idempotent)                │
│  - point ID = uuid5(NAMESPACE_URL, chunk_id) — 결정론적 → 덮어쓰기 │
│  - 출력: Qdrant collection `rag-docs` (size=384, distance=Cosine) │
└──────────────────────────────────────────────────────────────────┘
   │
   ▼
[Qdrant rag-docs 컬렉션 (Day 1 의 StatefulSet PVC 에 영속화)]
```

**왜 챗봇 흐름과 분리하는가**

인덱싱은 GPU/CPU 를 길게 점유하는 배치 작업이고 챗봇 호출은 짧은 응답이 필요한 동기 작업입니다. 두 작업을 같은 워크로드에 묶으면 인덱싱이 도는 동안 응답 latency 가 튀고, 인덱싱 실패 시 RAG API 까지 함께 죽습니다. 캡스톤은 인덱싱을 **별도 Argo Workflow / CronWorkflow** 로 분리해 다음 이점을 얻습니다.

- 인덱싱이 실패해도 **기존 컬렉션 데이터로 RAG API 가 계속 응답**함 (idempotent upsert 패턴이 핵심)
- 인덱싱 주기를 자율적으로 결정 (예: 야간 1 회 / 자료 업데이트 시 수동 트리거)
- 인덱싱 리소스 한도(`resources.limits`) 와 추론 리소스 한도를 **각자 조정** 가능

**왜 청크 메타데이터 4 종(`source / phase / topic / heading`) 을 보존하는가**

Day 5/6 의 RAG API 가 응답에 함께 반환할 `sources` 항목이 이 메타데이터를 그대로 노출하기 위함입니다. 인덱싱 단계에서 보존하지 않으면 검색 후 다시 파일을 읽어 헤딩을 역추적해야 하므로 latency 가 늘어납니다. 상세는 [`practice/pipelines/indexing/README.md`](practice/pipelines/indexing/README.md) §결정 노트.

### 3.3 인덱싱 Workflow DAG (Day 3 — 클러스터 위 자동화)

Day 2 의 4 단계 subcommand(`load-docs / chunk / embed / upsert`) 를 클러스터 위 Argo Workflow 의 5 step DAG 으로 패키징합니다. **첫 step `git-clone`** 이 본 코스 자료를 받아오고, 이후 4 step 은 Day 2 와 **완전히 동일한 코드** 가 환경변수만 바뀐 채 컨테이너로 실행됩니다.

```
┌──────────────────────────────────────────────────────────────────────────┐
│ Workflow: rag-indexing  (namespace: rag-llm, serviceAccountName: workflow)│
│ volumeClaimTemplates: pipeline-data (RWO 2Gi) → /docs + /data 통합 마운트  │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌────────────┐  ┌──────────┐  ┌───────┐  ┌───────┐  ┌────────┐         │
│  │ git-clone  │→ │load-docs │→ │ chunk │→ │ embed │→ │ upsert │         │
│  │alpine/git  │  │rag-indexer│ │  ...  │  │  ...  │  │  ...   │         │
│  │→ /docs/    │  │/docs/...  │ │/data/ │  │/data/ │  │→ Qdrant│         │
│  │  k8s-for-  │  │ → /data/  │ │chunks │  │embed  │  │collec- │         │
│  │  mle/      │  │ docs.jsonl│ │.jsonl │  │.jsonl │  │tion    │         │
│  └────────────┘  └──────────┘  └───────┘  └───────┘  └────────┘         │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
                                                            │
                                                            ▼
                                          ┌───────────────────────────────┐
                                          │ Qdrant StatefulSet (Day 1)    │
                                          │ qdrant.rag-llm.svc:6333       │
                                          │ collection=rag-docs           │
                                          │ size=384, distance=Cosine     │
                                          └───────────────────────────────┘
```

#### Day 2 (로컬) ↔ Day 3 (Argo) 1:1 매핑

| Day 2 로컬 명령 | Day 3 Workflow step | 변경점 |
|---|---|---|
| `git checkout` (학습자가 미리 수행) | `git-clone` step (alpine/git) | Workflow 가 직접 clone — CronWorkflow 가 매 실행마다 자동으로 최신 자료 반영 |
| `python pipeline.py load-docs` | `load-docs` step | env `DOCS_ROOT=/docs/k8s-for-mle/course` 로 경로만 변경 |
| `python pipeline.py chunk --chunk-size 512 ...` | `chunk` step | Workflow `arguments.parameters.chunk-size` → `extra-args` 로 전달 |
| `python pipeline.py embed --model intfloat/...` | `embed` step | env `EMBED_MODEL` + `--model` 두 곳에서 모두 명시 가능 |
| `python pipeline.py upsert --collection rag-docs` | `upsert` step | env `QDRANT_URL=http://qdrant.rag-llm.svc:6333` 로 port-forward 불필요 |

#### 왜 git-clone 을 첫 step 으로 두는가

ConfigMap 마운트(자료 1MB 초과) 와 PVC 사전 적재(`kubectl cp`) 두 대안과 비교했을 때, **CronWorkflow 가 매번 최신 자료를 자동으로 반영** 하는 것이 git-clone step 의 가장 큰 가치입니다. 새 lesson.md 가 main 브랜치에 push 되면 다음 03:00 KST 의 자동 인덱싱이 그것을 포함합니다 — 운영 시점에 학습자가 별도 작업할 필요가 없습니다.

#### port-forward 패턴(Day 2) 과의 차이

Day 2 에서는 로컬 Python 이 Qdrant 에 닿기 위해 `kubectl port-forward -n rag-llm svc/qdrant 6333:6333` 가 필요했습니다. Day 3 에서는 Workflow Pod 가 클러스터 안에 있으므로 **클러스터 내부 DNS** `qdrant.rag-llm.svc.cluster.local:6333` 을 직접 호출합니다. 환경변수 `QDRANT_URL` 만 다르고 `pipeline.py` 코드는 동일합니다.

상세 매니페스트 해설은 §4.7, 실행 절차는 [`labs/day-03-indexing-argo.md`](labs/day-03-indexing-argo.md), 트레이드오프 노트(Workflow vs Job, 단계 간 데이터 공유) 는 [`docs/architecture.md`](docs/architecture.md) §3.6·§3.7 참조.

---

## 4. 핵심 매니페스트 해설

### 4.1 Namespace (`manifests/00-namespace.yaml`)

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: rag-llm
  labels:
    purpose: capstone-rag-llm-serving
    course: k8s-for-mle
```

**해설:**
- `name: rag-llm` — 캡스톤 모든 컴포넌트가 들어가는 단일 Namespace 입니다. Phase 4-4 의 `ml-pipelines` 와 분리합니다.
- `labels.purpose=capstone-rag-llm-serving` — 후속 Day 에서 `kubectl get all -l purpose=capstone-rag-llm-serving --all-namespaces` 같은 일괄 조회의 기준이 됩니다.
- `labels.course=k8s-for-mle` — 본 코스 전체에서 캡스톤을 식별하는 라벨입니다. ResourceQuota / NetworkPolicy 적용 시 selector 로 활용 가능합니다.

### 4.2 Qdrant StatefulSet + Headless Service

#### 4.2.1 StatefulSet (`manifests/10-qdrant-statefulset.yaml`)

핵심 라인 발췌:

```yaml
spec:
  serviceName: qdrant            # ← Headless Service 이름과 정확히 일치해야 함
  replicas: 1
  template:
    spec:
      containers:
        - name: qdrant
          image: qdrant/qdrant:v1.11.3
          ports:
            - { name: http, containerPort: 6333 }
            - { name: grpc, containerPort: 6334 }
          readinessProbe:
            httpGet: { path: /readyz, port: http }    # 컬렉션 메타 로드 후부터 트래픽 수신
          livenessProbe:
            httpGet: { path: /healthz, port: http }   # 프로세스 살아있는지 확인
          volumeMounts:
            - { name: qdrant-storage, mountPath: /qdrant/storage }
  volumeClaimTemplates:
    - metadata: { name: qdrant-storage }
      spec:
        accessModes: [ "ReadWriteOnce" ]
        storageClassName: standard
        resources: { requests: { storage: 5Gi } }
```

**왜 Deployment 가 아니라 StatefulSet 인가**

Phase 4-4 의 `02-qdrant.yaml` 은 학습 단순화를 위해 Deployment + emptyDir 였습니다. 캡스톤은 **인덱스 영속성, 안정 DNS, 결정론적 PVC 이름** 세 가지 이유로 StatefulSet 으로 전환합니다(상세: [`docs/architecture.md`](docs/architecture.md) §3).

**`serviceName: qdrant` 가 결정하는 것**

이 필드는 이름이 같은 Headless Service 와 매칭되어 다음 DNS 를 발급합니다.

```
qdrant-0.qdrant.rag-llm.svc.cluster.local   ← Pod 단위 안정 DNS (ordinal)
qdrant.rag-llm.svc.cluster.local            ← 전체 selector 매칭 endpoint 목록
```

`serviceName` 의 값과 Service 의 `metadata.name` 이 다르면 ordinal DNS 가 발급되지 않습니다. 자주 하는 실수입니다(§10).

**`volumeClaimTemplates` 의 PVC 이름 규칙**

`volumeClaimTemplates` 는 Pod 마다 PVC 를 자동 생성합니다. 이름 규칙은 다음과 같습니다.

```
<volumeClaimTemplate.metadata.name>-<statefulset.metadata.name>-<ordinal>
        qdrant-storage              -    qdrant                  -    0
                                    →  qdrant-storage-qdrant-0
```

따라서 `kubectl get pvc -n rag-llm` 하면 `qdrant-storage-qdrant-0` 이 보일 것이며, **이 PVC 는 StatefulSet 을 삭제해도 자동 삭제되지 않습니다**(데이터 보호). 정리하려면 별도로 `kubectl delete pvc qdrant-storage-qdrant-0 -n rag-llm` 을 실행해야 합니다(§10, Day 1 labs §🧹 정리).

**readiness vs liveness probe 가 path 가 다른 이유**

Qdrant 는 프로세스 시작 직후에는 `/healthz` 가 200 이지만 컬렉션 메타데이터 로드가 끝나야 검색 요청을 처리할 수 있습니다. 이 둘을 구분하기 위해 `/readyz`(레디니스, 트래픽 수신 가능 여부) 와 `/healthz`(라이브니스, 프로세스 생존) 를 분리해 둔 것입니다. `livenessProbe` 가 너무 일찍 실패하지 않도록 `initialDelaySeconds: 15` 를 줬습니다.

#### 4.2.2 Headless Service (`manifests/11-qdrant-service.yaml`)

```yaml
apiVersion: v1
kind: Service
metadata:
  name: qdrant
  namespace: rag-llm
spec:
  clusterIP: None              # ← Headless: ordinal DNS 발급의 핵심
  selector: { app: qdrant }
  ports:
    - { name: http, port: 6333, targetPort: http }
    - { name: grpc, port: 6334, targetPort: grpc }
```

**`clusterIP: None` 의 의미**

일반 Service 는 ClusterIP 한 개를 발급받아 그 뒤에 selector 매칭 Pod 들을 로드밸런싱합니다. Headless Service 는 ClusterIP 를 만들지 않고 **DNS 응답에 selector 매칭 Pod 들의 IP 를 직접 반환**합니다. 또한 StatefulSet 의 `serviceName` 과 매칭되면 추가로 `<pod-name>.<service-name>` 형식의 안정 DNS 를 각 Pod 마다 발급합니다.

후속 Day 에서 RAG API 가 Qdrant 를 호출할 때는 단일 endpoint 로 충분하므로 `qdrant.rag-llm.svc:6333` 을 사용하면 됩니다. 향후 Qdrant 클러스터링(replicas > 1) 시에는 `qdrant-0.qdrant.rag-llm.svc:6333`, `qdrant-1...` 처럼 ordinal DNS 로 노드별 접근이 가능해집니다.

> 💡 **팁**: Headless 외에 별도의 ClusterIP Service 를 두는 패턴도 있습니다. 캡스톤은 단일 replica 라서 Headless 하나로 두 역할(ordinal DNS + 클라이언트 endpoint) 을 모두 처리합니다.

### 4.3 vLLM Deployment

Day 4 에서 추가하는 매니페스트 4 개입니다. **Phase 4-3 의 vLLM 단일 매니페스트 학습**(`vllm-phi2-deployment.yaml` 한 장으로 LLM 서빙을 마침) 을 *RAG 시스템 안의 한 컴포넌트* 로 다시 배치하면서 6 가지를 변경한 결과물입니다 — 변경 목록은 매니페스트 상단 출처 주석에 명시되어 있습니다.

| 파일 | kind | 역할 |
|---|---|---|
| `20-vllm-deployment.yaml` | Deployment | vLLM OpenAI 호환 서빙. `microsoft/phi-2` 를 GPU 1 장으로 추론 |
| `21-vllm-pvc.yaml` | PVC | 모델 가중치 캐시 20Gi (RWO) — 두 번째 기동 30 초 안에 ready |
| `22-vllm-service.yaml` | Service | ClusterIP — Day 5/6 RAG API 가 `vllm.rag-llm.svc.cluster.local:8000` 로 호출 |
| `23-vllm-hf-secret.yaml` | Secret | HF 토큰 (옵션 — phi-2 는 public 이라 미적용 가능) |

#### 4.3.1 핵심 구조 발췌 — `args` 6 종

Phase 4-3 의 5 종(`--model`, `--gpu-memory-utilization`, `--max-model-len`, `--port`, `--dtype`) 에 **`--served-model-name=microsoft/phi-2` 한 줄을 추가**해 6 종으로 만듭니다.

```yaml
args:
  - --model=microsoft/phi-2                  # ① HF Hub 모델 ID. 첫 로드 시 자동 다운로드 (5~10 분)
  - --served-model-name=microsoft/phi-2      # ② OpenAI SDK 의 model 파라미터 값. Day 5/6 RAG API 의 OPENAI_MODEL env 와 일치 필요
  - --gpu-memory-utilization=0.85            # ③ GPU VRAM 의 85% 까지 (모델 + KV cache). 0.95+ OOM 위험
  - --max-model-len=2048                     # ④ phi-2 의 학습 시 max context. 늘릴 수 없음
  - --port=8000                              # ⑤ HTTP 서버 포트. Service targetPort 와 일치
  - --dtype=auto                             # ⑥ T4 자동으로 FP16. T4 는 BF16 미지원
```

각 옵션이 *무엇을 결정* 하고 *어떤 트레이드오프* 를 가지는지의 깊이는 [Phase 4-3 lesson.md §1-4](../phase-4-ml-on-k8s/03-vllm-llm-serving/lesson.md#1-4-vllm-컨테이너-spec--args-핵심-5종) 에서 다뤘습니다. 본 캡스톤 §4.3 은 ②번 `--served-model-name` 의 추가 결정에만 집중합니다 — 결정 박스 ②.

#### 4.3.2 핵심 구조 발췌 — GPU 노드 격리 3 종

```yaml
spec:
  nodeSelector:
    cloud.google.com/gke-accelerator: nvidia-tesla-t4   # GKE T4 노드 풀의 자동 라벨
  tolerations:
    - key: nvidia.com/gpu                               # 노드 풀 생성 시 부여한 taint 통과
      operator: Exists
      effect: NoSchedule
  containers:
    - name: vllm
      resources:
        requests:
          nvidia.com/gpu: 1                             # extended resource — 정수, requests=limits 필수
        limits:
          nvidia.com/gpu: 1
```

Day 4 Step 1 에서 `gcloud container node-pools create gpu-pool ... --node-taints=nvidia.com/gpu=present:NoSchedule` 명령으로 T4 노드 풀에 taint 를 부여하고, 본 매니페스트의 `tolerations` + `nodeSelector` 가 그 taint 를 통과합니다. **셋 중 하나라도 누락**하면 vLLM Pod 가 일반 CPU 노드에 schedule 되어 `RuntimeError: No CUDA GPUs are available` 로 CrashLoopBackOff (자주 하는 실수 ⑩).

#### 4.3.3 핵심 구조 발췌 — startupProbe 가 livenessProbe 를 보호

```yaml
startupProbe:
  httpGet: { path: /health, port: http }
  failureThreshold: 60         # 60 × 10s = 최대 10 분 모델 로딩 허용
  periodSeconds: 10
livenessProbe:
  httpGet: { path: /health, port: http }
  periodSeconds: 30
  failureThreshold: 3
```

K8s 의 startupProbe 는 *통과 후 자동으로 비활성화* 되고, 그 시점부터 livenessProbe 가 동작합니다. 그래서 *느린 startup + 빠른 liveness 체크* 를 함께 둘 수 있습니다. phi-2 다운로드 5GB+ 가 학습자 네트워크에서 10 분을 초과할 수 있어, 트러블슈팅에서는 `failureThreshold: 90` 으로 임시 상향하는 옵션을 안내합니다.

#### 4.3.4 핵심 구조 발췌 — 모델 캐시 PVC + `/dev/shm` 두 볼륨

```yaml
volumeMounts:
  - name: model-cache
    mountPath: /root/.cache/huggingface     # vLLM (HF transformers) 캐시 기본 경로
  - name: shm
    mountPath: /dev/shm                     # CUDA IPC 공유 메모리 (Phase 4-3 자주 하는 실수 2번 방지)
volumes:
  - name: model-cache
    persistentVolumeClaim:
      claimName: vllm-model-cache           # 21-vllm-pvc.yaml 의 PVC name 과 일치
  - name: shm
    emptyDir:
      medium: Memory
      sizeLimit: 4Gi
```

첫 기동에서 HF Hub → PVC 로 5GB+ 다운로드가 일어나지만, 두 번째부터는 캐시 hit 으로 30 초 이내에 GPU 로딩만 끝납니다. **운영에서 이 차이는 Deployment rolling update 의 가용성에 직접 영향**합니다 — replica 1 인 캡스톤 vLLM 도 Day 6 Helm 차트(`values-prod.yaml` 의 `replicas: 2~3`) 에서는 PVC 캐시가 없으면 rolling update 중 모든 replica 가 동시에 5~10 분 cold start 를 겪습니다.

#### 4.3.5 결정 박스 4 개

> **결정 ① — 왜 `vllm-phi2` 가 아닌 `vllm` 이름인가**
>
> Phase 4-3 의 매니페스트는 Deployment / Service / PVC 모두 `vllm-phi2` 였습니다. *모델명 종속 이름* 이라 Day 9 모델 교체(예: phi-2 → Qwen2.5-1.5B-Instruct) 시 다음 4 곳을 함께 바꿔야 합니다.
>
> 1. Deployment `metadata.name`
> 2. Service `metadata.name` + `selector` + `spec.selector`
> 3. PVC `metadata.name`
> 4. RAG API 의 `OPENAI_BASE_URL` env (Day 5/6 코드)
>
> 캡스톤은 Service / Deployment / PVC 이름을 **`vllm` / `vllm-model-cache`** 로 단순화합니다 — Service DNS `vllm.rag-llm.svc.cluster.local:8000` 가 모델 교체와 무관한 안정 endpoint. 모델 종속성은 `--served-model-name` 한 곳으로만 격리.

> **결정 ② — 왜 `--served-model-name=microsoft/phi-2` 를 명시하는가**
>
> Phase 4-3 의 `args` 5 종에는 `--served-model-name` 이 *없습니다*. vLLM 의 기본 동작은 `--model` 값을 그대로 served name 으로 사용 — 따라서 OpenAI SDK 호출 시 `model="microsoft/phi-2"` 가 *우연히* 동작합니다. 캡스톤은 이 명시성을 한 단계 올려 `--served-model-name` 을 추가합니다.
>
> | 호출 시점 | model 파라미터 | 결정 ② 효과 |
> |---|---|---|
> | Day 4 검증 (`curl /v1/chat/completions`) | `microsoft/phi-2` | 명시적이라 학습자가 served name ↔ HF ID 의 분리 인지 |
> | Day 5/6 (RAG API 의 `OPENAI_MODEL` env) | `microsoft/phi-2` | RAG API 코드는 model name 만 알고 HF ID 는 모름 — 매니페스트 1 곳 변경으로 모델 교체 가능 |
> | Day 9 (모델 교체) | (변경) | served name 을 *바꾸지 않으면* RAG API env 그대로. 변경 영향이 매니페스트 1 곳으로 줄어듦 |
>
> 본 캡스톤은 served name 을 `microsoft/phi-2` (HF ID 그대로) 로 시작합니다. 운영에서는 논리명(`capstone-llm`) 으로 두는 패턴도 흔하지만, 학습자가 `model="microsoft/phi-2"` 라는 익숙한 호출을 그대로 재현할 수 있도록 HF ID 를 우선합니다.

> **결정 ③ — 왜 별도 GPU 노드 풀(taint 분리) 인가**
>
> Day 1~3 의 캡스톤 클러스터는 CPU 만으로 충분했습니다(Qdrant 256MiB / Argo controller 200MiB). Day 4 에서 GPU 가 처음 필요해질 때 두 옵션을 비교했습니다.
>
> | 옵션 | 시간당 비용 | 매니페스트 부담 | 캡스톤 적합성 |
> |---|---|---|---|
> | 단일 GPU 노드 풀 (모든 워크로드를 GPU 노드에) | T4 ≈$0.35/노드 (Qdrant/Argo 도 T4 점유) | taint 없음 → 매니페스트 단순 | ❌ T4 노드에 CPU 워크로드가 올라가 GPU 자원 낭비, 비용 ↑ |
> | **별도 GPU 노드 풀 + taint** ✅ | T4 ≈$0.35/GPU 노드 + e2-medium ≈$0.07/CPU 노드 | `tolerations` + `nodeSelector` 매니페스트 라인 2 개 추가 | **CPU 워크로드 비용 절감 + GPU 자원 격리, Day 4 종료 시 GPU 노드 풀만 size=0 으로 축소 가능** |
>
> taint `nvidia.com/gpu=present:NoSchedule` 은 GKE T4 노드 풀이 `--node-taints` 옵션으로 자동 부여 — 매니페스트의 `tolerations` + `nodeSelector` + `requests/limits.nvidia.com/gpu=1` 셋만 챙기면 됩니다. 누락 시 자주 하는 실수 ⑩.

> **결정 ④ — 왜 HF Secret 은 옵션 처리인가**
>
> phi-2 는 HuggingFace public 모델이라 토큰 없이 다운로드됩니다. Deployment 의 `valueFrom.secretKeyRef.optional: true` 가 Secret 부재를 정상 처리 — 본 캡스톤 디폴트는 **Secret 미적용**.
>
> Secret apply 가 *필수* 가 되는 두 시나리오:
> - HuggingFace anonymous rate limit 도달 (시간당 수십 회 다운로드 시 401 Unauthorized)
> - gated 모델 (`meta-llama/Llama-3.x-Instruct`, `mistralai/Mistral-7B-Instruct-v0.3` 등) 로 교체
>
> 두 경우 학습자는 `manifests/23-vllm-hf-secret.yaml` 의 placeholder 를 본인 토큰으로 바꿔 apply 하면 됩니다. 학습용 매니페스트라 평문 placeholder 를 그대로 두지만, 운영 시 SealedSecrets / External Secrets Operator / GKE Workload Identity 로 평문 토큰이 매니페스트에 안 남게 전환을 권장합니다.

#### 4.3.6 Day 4 에서 늘어나는 컴포넌트 표

| 추가 컴포넌트 | 위치 | 라이프사이클 |
|---|---|---|
| GKE T4 노드 풀 `gpu-pool` (1 노드) | 캡스톤 클러스터 노드 풀 | Day 4~10 유지. Day 4 단독 종료 시 `size=0` 또는 삭제 |
| Deployment `vllm` (replicas=1) | namespace `rag-llm` | Day 4~10 유지 |
| Service `vllm` (ClusterIP) | namespace `rag-llm` | Day 4~10 유지 |
| PVC `vllm-model-cache` (RWO 20Gi) | namespace `rag-llm` | Day 4~10 유지. Deployment 삭제 시 자동 삭제 안 됨 — 명시적 삭제 필요 |
| Secret `hf-secret` (옵션) | namespace `rag-llm` | gated 모델 교체 시점에만 |

상세 실행 절차는 [`labs/day-04-vllm-deploy.md`](labs/day-04-vllm-deploy.md), 트레이드오프 노트(cold start 의 운영적 의미, GPU 노드 풀 분리, served-model-name) 는 [`docs/architecture.md`](docs/architecture.md) §3.8 참조.

### 4.4 RAG API Deployment

<!-- TBD: Day 6 에서 작성합니다. -->

### 4.5 Ingress

<!-- TBD: Day 6 에서 작성합니다. -->

### 4.6 인덱싱 파이프라인 (`practice/pipelines/indexing/pipeline.py`)

Day 2 에서 작성하는 인덱싱 스크립트는 **Phase 4-4 의 `rag_pipeline/pipeline.py` 4 subcommand 골격을 그대로 이어받되**, 캡스톤 맥락(코스 자료 인덱싱, 한국어 다수, idempotent 운영) 에 맞춰 6 가지를 변경한 결과물입니다.

#### 4.6.1 subcommand 구성

| subcommand | 입력 | 출력 | 핵심 책임 |
|---|---|---|---|
| `load-docs` | `DOCS_ROOT/phase-*/**/lesson.md` + `study-roadmap.md` | `docs.jsonl` | 화이트리스트 글로브 + `phase`/`topic` 메타 추출 |
| `chunk` | `docs.jsonl` | `chunks.jsonl` | MD header → char splitter 2 단계, `heading` 메타 부여 |
| `embed` | `chunks.jsonl` | `embeddings.jsonl` | `multilingual-e5-small` 1 회 로드 + 일괄 encode |
| `upsert` | `embeddings.jsonl` | Qdrant `rag-docs` | idempotent 컬렉션 + 결정론적 point ID |
| `all` | (위 4 개 자동 호출) | (동일) | 로컬 학습용 한 줄 실행 |
| `search` | 자연어 쿼리 1 건 | top_k JSON | Day 2 검증용 보조 (RAG API 미니 시뮬레이터) |

`all` 을 제외한 5 개는 Day 3 의 Argo Workflow 의 4 개 step 에 1:1 매핑되며, 같은 컨테이너 이미지를 띄워 `args` 만 바꿔 호출합니다. 이는 **로컬 디버깅과 클러스터 실행이 같은 코드 경로를 공유**하게 만드는 설계입니다.

#### 4.6.2 핵심 코드 발췌 — load-docs 의 화이트리스트

```python
# practice/pipelines/indexing/pipeline.py
lesson_paths = sorted(DOCS_ROOT.glob("phase-*/**/lesson.md"))   # 모든 Phase 토픽
lesson_paths += sorted(DOCS_ROOT.glob("capstone-*/lesson.md"))  # 캡스톤 자체
```

Phase 4-4 원본의 단순 `*.md` 글로브 대신 **재귀 + 화이트리스트** 로 변경했습니다. `labs/` 의 README, 템플릿 파일, 작업 노트 등은 검색 품질을 떨어뜨리므로 인덱싱 대상에서 제외합니다.

#### 4.6.3 핵심 코드 발췌 — chunk 의 메타데이터 부여

```python
md_splitter = MarkdownHeaderTextSplitter(
    headers_to_split_on=[("#","h1"), ("##","h2"), ("###","h3")],
    strip_headers=False,                                  # 헤딩 라인 자체를 청크 본문에 보존
)
char_splitter = RecursiveCharacterTextSplitter(chunk_size=512, chunk_overlap=64, ...)

for doc in _iter_jsonl(src):
    for section in md_splitter.split_text(doc["text"]):   # 1차: 헤딩 단위
        heading = " > ".join(section.metadata.get(k, "") for k in ("h1","h2","h3"))
        for idx, piece in enumerate(char_splitter.split_text(section.page_content)):
            rows.append({
                "source": doc["source"], "phase": doc["phase"], "topic": doc["topic"],
                "heading": heading,                       # ← Day 5/6 sources 출처 라벨
                "chunk_index": idx, "text": piece,
            })
```

#### 4.6.4 핵심 코드 발췌 — embed 의 1 회 로드 패턴

```python
print(f"[embed] loading model {args.model}")
model = SentenceTransformer(args.model)                   # ← 모듈/명령 레벨에서 1 회만
texts = [(_E5_PASSAGE_PREFIX + c["text"]) if use_e5_prefix else c["text"] for c in chunks]
vectors = model.encode(texts, batch_size=32, normalize_embeddings=True)  # 일괄 처리
```

함수 안에서 청크마다 `SentenceTransformer(...)` 를 새로 호출하면 청크 수만큼 모델을 다시 로드해 메모리/시간이 폭증합니다. 이는 §10 자주 하는 실수 ⑤번에 정리되어 있습니다.

#### 4.6.5 핵심 코드 발췌 — upsert 의 idempotent 패턴

```python
# 컬렉션이 없으면 만들고, 있으면 차원 일치만 확인 → 데이터 보존
try:
    info = client.get_collection(name)
    if info.config.params.vectors.size != vector_size:
        sys.exit(2)                                       # 명시적 에러 → 학습자가 인지
except UnexpectedResponse:
    client.create_collection(name, vectors_config=...)

# point ID 는 chunk_id 의 결정론적 UUID — 같은 청크는 덮어쓰기 (중복 X)
points = [PointStruct(id=str(uuid.uuid5(NAMESPACE_URL, r["chunk_id"])), ...) for r in rows]
client.upsert(collection_name=name, points=points)
```

> 💡 **왜 `recreate_collection` 이 아닌가**
>
> Phase 4-4 원본은 매 실행마다 컬렉션을 비웠습니다. 이는 학습 흐름상 매번 깨끗한 상태를 보장하지만, 캡스톤 운영(Day 7~10) 에서는 **인덱싱 도중 RAG API 가 빈 컬렉션을 만나는 짧은 502 구간** 이 생깁니다. 캡스톤은 idempotent 패턴으로 전환해 부분 갱신과 무중단 재인덱싱을 가능하게 합니다.

#### 4.6.6 환경변수만 바꿔 두 컨텍스트를 모두 지원

| 환경변수 | Day 2 (로컬) | Day 3 (Argo) |
|---|---|---|
| `DOCS_ROOT` | `course` | `/docs` (PVC 또는 init container 마운트) |
| `PIPELINE_DATA_DIR` | `./.pipeline-data` | `/data` (Workflow 의 4 step 공유 PVC) |
| `QDRANT_URL` | `http://localhost:6333` (port-forward) | `http://qdrant.rag-llm.svc:6333` (클러스터 내부 DNS) |
| `EMBED_MODEL` | `intfloat/multilingual-e5-small` | (동일) |

**코드 변경 없이** 환경변수만 다르면 같은 스크립트가 양쪽에서 동작합니다. 이는 Day 3 의 Argo Workflow 작성 부담을 줄이고, 로컬에서 빠르게 디버깅한 동작이 클러스터에서 그대로 재현됨을 보장합니다.

상세 실행 절차는 [`labs/day-02-indexing-script-local.md`](labs/day-02-indexing-script-local.md) 를, 결정 근거 전문은 [`practice/pipelines/indexing/README.md`](practice/pipelines/indexing/README.md) 를 참고하세요.

### 4.7 Argo Workflow / CronWorkflow (`manifests/49`, `50`, `51`)

Day 3 에서 추가하는 매니페스트 3 개입니다.

| 파일 | kind | 역할 |
|---|---|---|
| `49-argo-rbac.yaml` | ServiceAccount + Role + RoleBinding | `rag-llm` 안에서 Workflow Pod 가 자식 Pod 을 생성할 권한 |
| `50-indexing-workflow.yaml` | Workflow | 1 회 실행용 5-step DAG (수동 트리거 / 첫 인덱싱) |
| `51-indexing-cronworkflow.yaml` | CronWorkflow | 매일 03:00 KST 자동 재인덱싱 (Workflow 와 본문 동일) |

#### 4.7.1 핵심 구조 발췌 — `50-indexing-workflow.yaml`

```yaml
spec:
  entrypoint: rag-indexing
  serviceAccountName: workflow                    # ← 49-argo-rbac.yaml 의 SA. 누락 시 즉시 RBAC 실패.

  arguments:
    parameters:
    - { name: git-repo,        value: "https://github.com/<user>/k8s-for-mle.git" }
    - { name: embedding-model, value: "intfloat/multilingual-e5-small" }   # Day 2 결정 인용
    - { name: chunk-size,      value: "512" }
    - { name: chunk-overlap,   value: "64" }

  volumeClaimTemplates:                           # ← 5 step 이 공유할 PVC 1 개 (자동 생성/삭제)
  - metadata: { name: pipeline-data }
    spec:
      accessModes: ["ReadWriteOnce"]
      resources: { requests: { storage: 2Gi } }
  volumeClaimGC:
    strategy: OnWorkflowCompletion                # workflow 종료 시 PVC 자동 정리

  templates:
  - name: rag-indexing
    dag:
      tasks:
      - { name: git-clone, template: git-clone-step }
      - { name: load-docs, template: pipeline-step, dependencies: [git-clone], ... }
      - { name: chunk,     template: pipeline-step, dependencies: [load-docs], ... }
      - { name: embed,     template: pipeline-step, dependencies: [chunk], ... }
      - { name: upsert,    template: pipeline-step, dependencies: [embed], ... }
```

#### 4.7.2 결정 박스 4 개

> **결정 ① — 왜 Job 이 아니라 Workflow 인가**
>
> Phase 4-4 에서 익혔듯, Job 한 개로는 4 단계 의존성을 표현할 수 없습니다. Argo Workflow 가 해결하는 4 가지를 캡스톤 컨텍스트로 다시 정리합니다.
>
> | 축 | Job 한계 | Workflow 해결 |
> |---|---|---|
> | 의존성 | `kubectl wait` 폴링 또는 cron 시차 | DAG `dependencies:` 로 선언적 |
> | 재시도 단위 | 4 단계 묶음 → 처음부터 다시 | step 단위 `retryStrategy` (앞단 결과는 PVC 보존) |
> | 시각화 | `kubectl logs` × 4 | argo-server UI 가 그래프 색상으로 실시간 표시 |
> | 파라미터화 | 매니페스트 복사·수정 | `arguments.parameters` + `argo submit -p ...` |
>
> 캡스톤은 5 개 (chunk-size, chunk-overlap, embedding-model, collection-name, git-repo) 를 글로벌 파라미터로 노출해, 청킹 전략 변경 / 모델 교체 / 다른 브랜치 인덱싱이 매니페스트 수정 없이 가능합니다.

> **결정 ② — 단계 간 데이터 공유: volumeClaimTemplate 통합 마운트**
>
> Workflow 의 step 들은 서로 다른 Pod 입니다. 단계 사이 데이터(`docs.jsonl`, `chunks.jsonl`, `embeddings.jsonl`) 를 공유하는 3 가지 방법이 있고, 캡스톤은 그중 가장 단순한 **PVC 단일 통합 마운트** 를 택합니다.
>
> | 방식 | 적합성 | 캡스톤 채택 |
> |---|---|---|
> | parameters | 작은 string ({{kb}} 단위) | git-repo URL 전달용으로만 사용 |
> | artifacts (MinIO/S3) | 파일·대용량 | ❌ ArtifactRepository 설정 부담으로 학습 단순성 저해 |
> | **volumeClaimTemplates** ✅ | 파일·중간 산출물 | **단일 PVC `pipeline-data` 의 `/docs` + `/data` mountPath 2 개로 통합** |
>
> `/docs` 와 `/data` 를 별도 PVC 로 나누면 RWO accessMode 의 노드 제약이 step 마다 발생합니다. 단일 PVC 로 통합하면 5 step 이 같은 노드에서 순차 실행되어 RWO 제약이 자연스럽게 충족됩니다. 트레이드오프 전문은 [`docs/architecture.md`](docs/architecture.md) §3.7 참조.

> **결정 ③ — `serviceAccountName: workflow` + namespace 분리**
>
> Argo controller 는 `argo` namespace 에 quick-start-minimal 로 설치하고, Workflow 자체는 `rag-llm` namespace 에서 실행합니다. 두 가지를 같은 namespace 에 두면 RBAC 가 단순해지지만, 분리해 두면 캡스톤(`rag-llm`) 만 통째로 삭제할 때 controller 가 영향을 받지 않습니다.
>
> 분리의 비용은 RBAC 매니페스트 1 개(`49-argo-rbac.yaml`) 입니다. Workflow Pod 가 자식 Pod (5 step 의 컨테이너) 을 생성할 권한을 얻기 위해 `pods`/`pods/log`/`workflowtaskresults` 권한을 가진 ServiceAccount `workflow` 를 만들고, Workflow spec 에 `serviceAccountName: workflow` 를 명시합니다. 이 라인을 누락하면 `pods is forbidden ... default ... cannot create resource pods` 메시지로 즉시 실패합니다 (§10 자주 하는 실수 ⑦번).

> **결정 ④ — CronWorkflow `concurrencyPolicy: Replace` + WorkflowTemplate 미도입**
>
> CronWorkflow 의 두 가지 결정:
>
> 1. **`concurrencyPolicy: Replace`** — 이전 실행이 안 끝났을 때 어떻게 할지의 선택지는 `Allow / Forbid / Replace` 3 가지입니다. 캡스톤은 §4.6.5 의 idempotent upsert 패턴 덕분에 동일 자료 재실행이 안전하므로 `Replace` (이전 취소 후 새로 시작) 가 가장 자연스럽습니다. `Allow` 는 동일 PVC 경합 위험, `Forbid` 는 자료 갱신이 며칠 늦어질 위험.
> 2. **WorkflowTemplate 미도입** — `50` 과 `51` 의 workflowSpec 본문이 거의 동일해 DRY 가 깨집니다. 운영에서는 공통 4-step DAG 을 WorkflowTemplate 으로 추출하고 두 매니페스트가 `templateRef` 로 참조하는 것이 정석입니다(상세는 [Phase 4-4 lesson.md §1-1 의 WorkflowTemplate CRD 설명](../phase-4-ml-on-k8s/04-argo-workflows/lesson.md#1-1-argo-workflows-아키텍처--두-개의-컨트롤러)). 캡스톤은 학습 단순성을 위해 두 매니페스트가 본문을 공유하지 않는 형태로 둡니다 — Day 4 부터 작성될 매니페스트가 늘어나면서 WorkflowTemplate 의 가치가 부각될 때 도입을 재고할 수 있습니다.

#### 4.7.3 Day 3 에서 늘어나는 컴포넌트 표

| 추가 컴포넌트 | 위치 | 라이프사이클 |
|---|---|---|
| Argo controller (`workflow-controller`, `argo-server`) | namespace `argo` | 캡스톤 전 기간 유지 |
| ServiceAccount/Role/RoleBinding `workflow` | namespace `rag-llm` | 캡스톤 전 기간 유지 |
| Workflow `rag-indexing-*` (1 회) | namespace `rag-llm` | 실행 후 GC 정책에 따라 정리 |
| CronWorkflow `rag-indexing-daily` | namespace `rag-llm` | 캡스톤 전 기간 유지 (suspend 가능) |

상세 실행 절차는 [`labs/day-03-indexing-argo.md`](labs/day-03-indexing-argo.md), 컴포넌트 분리 트레이드오프는 [`docs/architecture.md`](docs/architecture.md) §3.6·§3.7 참조.

---

## 5. RAG API 구현 노트

<!-- TBD: Day 5 에서 작성합니다. retriever 청크 추출, 컨텍스트 합성 규칙, 스트리밍 옵션. -->

---

## 6. 모니터링 핵심 메트릭

<!-- TBD: Day 7 에서 작성합니다. RAG / vLLM / Qdrant / GPU 4 축. -->

---

## 7. HPA 커스텀 메트릭

<!-- TBD: Day 8 에서 작성합니다. 왜 CPU 가 아닌 vllm:num_requests_running 인가, prometheus-adapter 흐름. -->

---

## 8. Helm 으로 한 줄 배포

<!-- TBD: Day 10 에서 작성합니다. values 분리(dev/prod), helm install --create-namespace. -->

---

## 9. 검증 시나리오

<!-- TBD: Day 10 에서 작성합니다. 6 단계 통합 검증 + GKE 클러스터 삭제. -->

---

## 10. 🚨 자주 하는 실수

<!-- 캡스톤 진행 중 발견 시 누적 추가합니다. 현재 Day 1(Qdrant/StatefulSet 3건) + Day 2(인덱싱 3건) + Day 3(Argo 3건) + Day 4(vLLM/GPU 3건) = 12건. -->

**Day 1 — Qdrant / StatefulSet**

1. **`serviceName` 과 Service 이름 불일치** — StatefulSet 의 `spec.serviceName` 과 Headless Service 의 `metadata.name` 이 다르면 `qdrant-0.qdrant` 안정 DNS 가 발급되지 않습니다. 두 값을 정확히 같게 두세요.
2. **PVC 자동 삭제 기대** — StatefulSet 을 `kubectl delete -f` 해도 `volumeClaimTemplates` 가 만든 PVC 는 데이터 보호 목적으로 남습니다. 정리하려면 `kubectl delete pvc qdrant-storage-qdrant-0 -n rag-llm` 을 별도로 실행해야 합니다.
3. **storageClass 누락으로 PVC Pending** — `storageClassName: standard` 가 클러스터에 없으면 PVC 가 영원히 Pending 입니다. `kubectl get sc` 로 사용 가능한 storageClass 를 확인하고 매니페스트를 교체하세요.

**Day 2 — 인덱싱 파이프라인**

4. **port-forward 미기동 상태로 스크립트 실행** — `python pipeline.py upsert` 가 `connection refused` 로 죽습니다. 인덱싱 단계는 시간이 걸리므로 `embed` 까지 다 돌고 마지막에 실패하면 매우 아깝습니다. **Step 2 직후 `curl http://localhost:6333/healthz` 로 미리 검증**하세요. 백그라운드 port-forward 가 살아 있는지는 `jobs` 또는 `lsof -i :6333` 으로 수시 확인합니다.
5. **임베딩 모델을 청크마다 재로딩** — `def embed_one(text): return SentenceTransformer(model).encode(...)` 처럼 함수 안에서 모델을 매번 만들면 청크 수만큼 모델을 다시 로드해 메모리/시간이 폭증합니다. **모델은 명령 진입 시 1 회만 로드**하고 `model.encode(texts, batch_size=32)` 로 일괄 처리하세요. `pipeline.py` 의 `cmd_embed` 가 이 패턴입니다.
6. **`recreate_collection` 으로 운영 환경에서 컬렉션 비우기** — Phase 4-4 학습용 코드는 매 실행마다 컬렉션을 비웠지만, 캡스톤 운영에서는 **인덱싱 도중 RAG API 가 빈 컬렉션을 만나 502 가 나는 짧은 구간** 이 생깁니다. 캡스톤은 `create_collection_if_not_exists + 결정론적 point ID(`uuid5`) + upsert` 패턴으로 부분 갱신을 허용합니다. 차원이 바뀌었을 때만 명시적 에러로 학습자에게 컬렉션 삭제를 요구합니다.

**Day 3 — Argo Workflow / RBAC**

7. **Workflow spec 의 `serviceAccountName: workflow` 누락** — workflow controller 가 workflow Pod 을 만들 때 `default` ServiceAccount 를 사용하다 `pods is forbidden: User "system:serviceaccount:rag-llm:default" cannot create resource "pods"` 메시지로 즉시 실패합니다. **`49-argo-rbac.yaml` 적용 + Workflow spec 한 줄 추가** 두 가지를 함께 검증해야 합니다. 같은 namespace 에서 새 Workflow 를 만들 때마다 잊기 쉬운 부분이라 §4.7 결정 박스 ③에서 분리 패턴을 강조했습니다.
8. **`alpine` 이미지로 git-clone 시도** — `alpine:3.20` 에는 git 이 포함되어 있지 않아 `sh: git: not found` 로 실패합니다. **반드시 `alpine/git:2.45.x`** 를 사용하세요. 비슷한 실수로 `python:3.11-slim` 이미지에서 `git clone` 하려는 경우도 같은 에러가 발생합니다 (slim 이미지는 git 미포함).
9. **단계 간 데이터 공유에 `emptyDir` 사용** — Phase 4-4 자주 하는 실수 ③번과 동일. DAG 의 각 step 은 서로 다른 Pod 이므로 emptyDir 는 다음 step 에서 비어 있습니다. 캡스톤은 단일 PVC `pipeline-data` 의 mountPath 2 개(`/docs`, `/data`) 로 통합 마운트 + `volumeClaimGC.strategy: OnWorkflowCompletion` 으로 자동 정리하는 패턴을 사용합니다(§4.7 결정 박스 ②). 운영 시 RWX 가 필요하면 NFS 또는 객체 스토리지로 전환합니다.

**Day 4 — vLLM / GPU 노드 풀**

10. **T4 노드 풀 taint 누락으로 vLLM Pod 가 CPU 노드에 schedule** — Phase 4-3 자주 하는 실수 1번의 캡스톤 변형. `gcloud container node-pools create gpu-pool ...` 명령에서 `--node-taints=nvidia.com/gpu=present:NoSchedule` 를 빠뜨리면 GPU 노드 풀이 *taint 없이* 만들어집니다. vLLM Pod 의 `tolerations` 가 동작할 taint 자체가 없어지면서, K8s 의 스케줄러가 *어느 노드든 자원이 충분하면 OK* 로 판단해 일반 CPU 노드(Qdrant 가 도는 e2-medium) 에 vLLM Pod 를 배치합니다. 결과: Pod 시작 → vLLM 의 CUDA 초기화 시도 → `RuntimeError: No CUDA GPUs are available` → CrashLoopBackOff. **해결**: `gcloud container node-pools describe gpu-pool --cluster capstone --format='value(config.taints)'` 로 taint 확인. 누락 시 `gcloud container node-pools update gpu-pool --node-taints=nvidia.com/gpu=present:NoSchedule` 또는 노드 풀 재생성. 매니페스트의 `tolerations.key` 도 동일 키 인지 확인(자주 `nvidia.com/gpu` ↔ `gpu` 오타).

11. **served-model-name 불일치로 RAG API `/chat` 응답이 404** — Day 6 시점 발견되는 후속 문제이지만 **Day 4 시점에 미리 인지** 해야 합니다. `args` 에 `--served-model-name=microsoft/phi-2` 를 명시했는데 RAG API 의 `OPENAI_MODEL` env 가 `phi-2` 또는 `microsoft/Phi-2` (대문자) 로 다르면, vLLM 이 응답으로 `{"error": "The model 'phi-2' does not exist"}` 를 돌려줍니다. **해결**: 두 곳을 *완전 동일 문자열*로. Day 4 검증 시점에 `curl /v1/models | jq '.data[0].id'` 로 정확한 served name 을 확인하고, Day 5/6 의 RAG API ConfigMap(`32-rag-api-configmap.yaml`) 작성 시 그 값을 그대로 복사. 모델 교체(Day 9) 시 매니페스트 `--served-model-name` 변경 → ConfigMap 동시 변경을 잊지 않게 *체크리스트화*.

12. **vLLM Deployment 삭제 후 PVC `vllm-model-cache` 재사용 시 디스크 누적** — Day 9 모델 교체로 phi-2 → Qwen2.5-1.5B 로 바꾸고 Deployment 를 재생성하면, 기존 PVC 의 `/root/.cache/huggingface/hub/` 아래에 *두 모델이 모두 남습니다*. 의도된 동작(다른 모델 캐시는 보존) 이지만 학습자가 *디스크 사용량 누적* 을 인지하지 않으면 PVC 20Gi 를 30 일 안에 채울 수 있습니다. **해결**: 모델 교체 후 사용하지 않을 모델 캐시를 명시적으로 삭제 — `kubectl exec deploy/vllm -n rag-llm -- rm -rf /root/.cache/huggingface/hub/models--microsoft--phi-2`. 또는 Day 10 Helm 차트 작성 시 `values.yaml` 의 `oldModelCleanup: true` flag 로 init container 에서 자동 정리. PVC 사용량은 `kubectl exec deploy/vllm -n rag-llm -- du -sh /root/.cache/huggingface` 로 모니터링.

> 💡 **Phase 4-3 의 자주 하는 실수 3 종 (`nvidia.com/gpu` 누락 / `/dev/shm` 누락 / `--gpu-memory-utilization` 0.95+)** 은 본 캡스톤에서도 그대로 유효합니다. 본 매니페스트는 셋 모두 *해결된 상태* 로 작성되어 있으므로, 학습자가 `vllm/vllm-openai` 이미지로 자신의 매니페스트를 처음부터 작성할 때를 대비한 보호장치는 [Phase 4-3 lesson.md §자주 하는 실수](../phase-4-ml-on-k8s/03-vllm-llm-serving/lesson.md#-자주-하는-실수) 에서 한 번 더 확인하세요.

<!-- TBD: Day 7(ServiceMonitor 라벨 selector), Day 8(HPA 메트릭 미수집), Day 9(부하 테스트 OOM) 관련 추가 예정. -->

---

## 11. 확장 아이디어

<!-- TBD: Day 10 에서 작성합니다. reranker, 스트리밍, 멀티턴, RAGAS 평가. -->

---

## 12. 다음 단계

본 캡스톤을 마쳤다면 두 갈래 중 하나로 이어갑니다.

- **Phase 5 (선택)** — Operator, Service Mesh, GitOps, 멀티 클러스터로 심화. [`docs/study-roadmap.md`](../../docs/study-roadmap.md) Phase 5 섹션 참고.
- **자기 업무 적용** — 본인이 다루는 모델·데이터로 같은 아키텍처를 재구성합니다. 가장 큰 학습은 본 코스 자료가 아닌 **본인 문제**에 적용할 때 일어납니다.

<!-- TBD: Day 10 에서 보강. 캡스톤 완료 후 회고 체크리스트, GKE 비용 정산 안내 등. -->

---

## Day 1~4 실습 가이드

본 lesson.md 의 내용을 직접 클러스터/로컬에서 적용해 보려면 다음 lab 들을 순서대로 진행하세요. 각 lab 은 Goal / 사전 조건 / Step / 검증 / 정리 5 단계 + 트러블슈팅 표 구조입니다.

- [`labs/day-01-namespace-qdrant.md`](labs/day-01-namespace-qdrant.md) — Namespace + Qdrant StatefulSet + Headless Service (lesson §1·§4.1·§4.2)
- [`labs/day-02-indexing-script-local.md`](labs/day-02-indexing-script-local.md) — 본 코스 자료를 로컬 Python 으로 청크/임베딩하여 Qdrant `rag-docs` 에 적재 (lesson §3.2·§4.6)
- [`labs/day-03-indexing-argo.md`](labs/day-03-indexing-argo.md) — 동일 코드를 Argo Workflow 5-step DAG (`git-clone → load-docs → chunk → embed → upsert`) 으로 패키징해 클러스터에서 실행 + CronWorkflow 로 일별 자동화 (lesson §3.3·§4.7)
- [`labs/day-04-vllm-deploy.md`](labs/day-04-vllm-deploy.md) — GKE T4 노드 풀 추가 → vLLM Deployment + Service + 모델 캐시 PVC 적용 → `curl /v1/models` + OpenAI Python SDK 로 OpenAI 호환 API 검증 (lesson §2.1·§4.3)
