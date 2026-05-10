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

★ **Day 1 에서 실제로 만드는 것은 Namespace + Qdrant StatefulSet + Headless Service 3 개**입니다. 나머지 박스는 후속 Day 에 채워집니다. **Day 3 에서는 별도 namespace `argo` 에 Argo controller 를 quick-start-minimal 로 설치**하고, `rag-llm` 안에 Workflow + CronWorkflow + RBAC 3 개를 추가합니다. **Day 4 에서는 GKE T4 노드 풀을 캡스톤 클러스터에 추가**해 GPU 워크로드와 CPU 워크로드를 같은 클러스터에서 분리 운영하고, `rag-llm` 안에 vLLM Deployment + Service + 모델 캐시 PVC + (옵션)HF Secret 4 개를 배치합니다. **★ Day 5 에서는 위 그림의 RAG API 박스를 *로컬 개발* 단계로 먼저 작성**합니다 — 클러스터 매니페스트(Deployment / Service / Ingress) 는 Day 6 에서 추가하고, Day 5 는 `practice/rag_app/` 의 6 개 모듈 + 단위 테스트를 만들어 Terminal A(Qdrant 6333) + Terminal B(vLLM 8000) port-forward 위에서 `uvicorn main:app` → `/chat` 200 OK 까지를 검증합니다.

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

### 2.3 왜 RAG API 를 별도 Deployment 로 분리하는가 (Day 5 핵심)

§2.1 이 *vLLM 분리* 의 4 축이었다면, 본 절은 그 거울 짝 — **RAG API 가 stateless 한 글루(glue) 컴포넌트로 별도 분리되어야 하는 이유** 4 축입니다. 같은 시스템을 다른 각도에서 다시 보는 셈이므로 §2.1 과 대구를 이루는 4 축으로 정리합니다.

| 축 | RAG API | vLLM·Qdrant |
|---|---|---|
| **① 배포 사이클** | retrieval 알고리즘·프롬프트 템플릿·top_k — *일 단위* 변경 | 모델 가중치 5GB+ — *주~월 단위* 교체 / 인덱스 — 인덱싱 트리거 시 |
| **② 상태성** | **stateless** — Pod 재시작이 사용자 요청에 영향 0 | stateful (vLLM = GPU 메모리·KV cache, Qdrant = PVC 인덱스) |
| **③ 메트릭 축** | RPS · `rag_chat_latency_seconds` · `rag_retrieve_latency_seconds` | vLLM = `vllm:num_requests_running` / Qdrant = 검색 latency / GPU = util |
| **④ 의존성 방향** | **단방향 호출자** (RAG API → vLLM, RAG API → Qdrant) | 응답 제공자 (역방향 호출 없음) |

#### ① 배포 사이클이 다르다 — 일 단위 코드 vs 월 단위 모델

`prompts.py` 의 SYSTEM_PROMPT 한 줄 수정, `retriever.py` 의 top_k 기본값 조정, `main.py` 의 응답 sources 필드 추가 — 캡스톤 운영 시 **주에 수회** 발생하는 변경입니다. 반면 vLLM 의 `--served-model-name` 변경(phi-2 → Qwen2.5)이나 인덱싱 모델 교체(e5-small → e5-base) 는 **월에 한 번** 수준. 같은 Pod 에 묶으면 *프롬프트 한 줄 수정* 마다 vLLM 의 5~10 분 cold start (Day 4 §4.3.5 결정 박스 ②) 가 동반됩니다. 분리하면 RAG API 만 30 초 rolling update 로 끝납니다 — 이는 §2.1 ②번의 *반대 방향* 같은 결정입니다.

#### ② RAG API 는 stateless — 가장 단순한 워크로드

RAG API 의 메모리에는 **임베딩 모델 인스턴스 1 개** 외에 어떤 사용자 상태도 없습니다(캡스톤 §2 결정 #8 — last user message 만 사용, conversation history 미보관). `app.state.retriever` 와 `app.state.llm` 도 *읽기 전용 핸들* 일 뿐 mutate 되지 않습니다. 따라서:

- Pod 재시작 시 *유실되는 정보 0*
- replica N 개로 늘려도 *동기화 부담 0*
- 어떤 Pod 에 트래픽이 가도 *결과 동일* (Qdrant·vLLM 응답이 같으면)

이 단순함이 Day 8 의 표준 HPA(CPU%/RPS) 를 *그대로* 적용 가능하게 만듭니다 — vLLM 처럼 prometheus-adapter + 커스텀 메트릭이 필요 없습니다. stateless 가 *분리 결정의 결과* 가 아니라 *분리를 가능하게 만든 전제* 입니다.

#### ③ 메트릭 축이 RPS·latency 로 표준화 — 커스텀 메트릭 불필요

§2.1 ③번에서 vLLM 의 *진짜 부하* 는 `vllm:num_requests_running` 같은 *vLLM 특유의 메트릭* 이라 정리했습니다. RAG API 는 그 반대 — *진짜 부하* 가 **RPS + 95p latency 의 표준 두 축**입니다. `main.py` 의 4 종 Prometheus 메트릭(`rag_chat_total{status}`, `rag_chat_latency_seconds`, `rag_retrieve_latency_seconds`, `rag_llm_latency_seconds`) 도 *Counter + Histogram* 의 표준 패턴으로 노출됩니다.

같은 Pod 에 묶이면 vLLM 의 GPU 부하가 RAG API 의 latency 메트릭을 **혼동** 시킵니다 — `/chat` 의 4 초 응답이 retriever 가 느렸는지 vLLM 이 느렸는지 분리 불가능. RAG API 가 *자기 latency 만 측정* 하고 vLLM 호출 시간을 별도 Histogram 으로 떼어내려면 워크로드 자체가 분리되어야 합니다. Day 7 ServiceMonitor 가 두 endpoint 를 *각자 scrape* 하는 것이 이 결정의 최종 결과입니다.

#### ④ 의존성 방향이 단방향 — 명확한 레이어링

`main.py → retriever.py → Qdrant` 와 `main.py → llm_client.py → vLLM` 두 흐름은 **모두 RAG API 가 호출자, vLLM/Qdrant 가 응답자** 입니다. 역방향(Qdrant 또는 vLLM 이 RAG API 를 호출) 은 본 캡스톤에 존재하지 않습니다. 따라서 RAG API 를 *상층 레이어*, vLLM/Qdrant 를 *하층 레이어* 로 둘 수 있고, 이는 다음 운영 패턴들을 가능하게 합니다.

- RAG API 를 일시 중지(replica 0)해도 vLLM·Qdrant 는 다른 클라이언트(예: Day 9 의 부하 테스트 hey 가 vLLM 직접 호출) 에 그대로 응답
- vLLM 또는 Qdrant 가 일시 중단되면 RAG API 는 503 으로 *우아하게* 실패 — 사용자에게 명확한 에러
- Day 6 의 Ingress 는 RAG API 만 외부 노출 — vLLM/Qdrant 는 클러스터 내부 endpoint 로 격리(`internal API`)

> 💡 **본 캡스톤의 §2 트레이드오프 4 축 채택 결과**
>
> §2.1 (vLLM 분리 4 축) + §2.3 (RAG API 분리 4 축) 두 절의 *같은 4 축 (스케일·라이프사이클·메트릭·역할)* 을 두 컴포넌트 시점에서 한 번씩 다뤘습니다. §2.2 (인덱싱 분리) 와 §2.4 (단일 Namespace) 는 한 줄 인용으로 처리했으니, §2 전체가 **각 컴포넌트가 *왜* 분리되어야 하는지** 의 4 + 1 + 1 + 1 결정 노트로 완성됩니다. 매니페스트 해설(§4) 과 데이터 흐름(§3) 은 본 §2 의 *결과* 이지 *근거* 가 아닙니다.

### 2.4 왜 단일 Namespace `rag-llm` 인가

§1.3 에서 다룬 4 가지 근거(RBAC 단위 일치 / ResourceQuota·NetworkPolicy 적용 단위 / DNS 가독성 / 삭제 단위 일치) 와 동일합니다. Day 1 시점에 결정.

---

## 3. 데이터 흐름

캡스톤 시스템에는 두 개의 데이터 흐름이 존재합니다. 사용자 요청을 처리하는 **챗봇 호출 흐름**(synchronous, online) 과 본 코스 자료를 청크/임베딩하여 Qdrant 에 적재하는 **인덱싱 데이터 흐름**(batch, offline) 입니다. 둘을 분리하는 것이 캡스톤 아키텍처의 핵심 결정입니다.

### 3.1 챗봇 호출 흐름 (`/chat` → 응답)

학습자가 `curl localhost:8001/chat` 으로 질문을 보내면 RAG API 안에서 다음 7 단계가 *동기적으로* 실행됩니다. Day 5 의 `practice/rag_app/` 4 모듈(`main.py` / `retriever.py` / `llm_client.py` / `prompts.py`) 이 각각 어떤 단계를 담당하는지 1:1 로 매핑됩니다.

```
[Client]
   │  POST /chat  {messages:[{role:"user", content:"K8s 에서 GPU 어떻게 잡지?"}], top_k:3}
   ▼
┌────────────────────────────────────────────────────────────────────┐
│ RAG API (uvicorn :8001 — Day 5 로컬 / Day 6 Deployment)           │
│                                                                    │
│ (1) main.py @app.post("/chat")                                     │
│      ├─ ChatRequest.messages 검증, last user message 추출          │
│      ├─ top_k = req.top_k or TOP_K_DEFAULT                         │
│      └─ CHAT_LATENCY.time() 시작                                   │
│                                                                    │
│ (2) retriever.search(query, top_k=3)                               │
│      ├─ _encode_query() — 'query: ' prefix + e5-small encode      │
│      │     (RETRIEVE_LATENCY.time() 시작/끝)                      │
│      └─ qdrant.search(collection='rag-docs', limit=3)              │
│                                                                    │
│      ─── HTTP ───────────────────► [Qdrant StatefulSet :6333]      │
│                                          │                          │
│      ◄── ScoredPoint × 3 ────────────────┘ (payload: source/phase/  │
│              (id, score, payload)                topic/heading/text)│
│                                                                    │
│      → list[RetrievedChunk] (5 종 메타 + score + chunk_id)         │
│                                                                    │
│ (3) prompts.build_messages(user_query, chunks)                     │
│      ├─ build_context(chunks) — [n] 번호 + 메타 4 종 + text 합성   │
│      └─ messages = [system(SYSTEM_PROMPT), system(context), user]  │
│         (3 메시지, 한국어 system prompt + 인용 지시)                │
│                                                                    │
│ (4) llm_client.chat(messages)                                      │
│      ├─ openai.ChatCompletions.create(model='microsoft/phi-2',    │
│      │     messages=..., temperature=0.2, max_tokens=512)         │
│      │     (LLM_LATENCY.time() 시작/끝)                           │
│      │                                                            │
│      ─── HTTP /v1/chat/completions ──► [vLLM Deployment :8000]    │
│                                              │                     │
│      ◄── ChatCompletion JSON ────────────────┘                    │
│                                                                    │
│      └─ choices[0].message.content → str (한국어 답변 + [n] 인용)  │
│                                                                    │
│ (5) [chunk → Source] 변환                                          │
│      └─ source/phase/topic/heading/score/chunk_id 6 종 노출        │
│                                                                    │
│ (6) ChatResponse(answer=..., sources=[Source × 3])                 │
│      └─ CHAT_LATENCY.time() 끝, CHAT_COUNT{status="ok"}.inc()     │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
   │
   ▼
[Client]  200 OK { answer, sources: [{source,phase,topic,heading,score,chunk_id}] × 3 }
```

#### 단계별 책임·예상 latency 표

| # | 모듈 | 호출 함수 | 평균 latency (정상 운영) | Prometheus 메트릭 |
|---|------|-----------|--------------------------|-------------------|
| (1)(6) | `main.py` | `chat()` 핸들러 + `_to_source()` | < 10 ms | `rag_chat_total{status}`, `rag_chat_latency_seconds` |
| (2) | `retriever.py` | `QdrantRetriever.search()` | 30~100 ms (e5 encode 20ms + Qdrant 50ms) | `rag_retrieve_latency_seconds` |
| (3) | `prompts.py` | `build_messages()` | < 1 ms (순수 함수) | (별도 메트릭 없음 — 단계 (1) latency 에 포함) |
| (4) | `llm_client.py` | `VLLMClient.chat()` | 1~3 초 (warm) / 30~60 초 (cold cache) | `rag_llm_latency_seconds` |

**총 정상 응답** 은 약 **1~3 초** 입니다. 단계 (4) vLLM 호출이 latency 의 95% 이상을 차지하므로, Day 8 의 HPA 는 *vLLM 측* 메트릭(`vllm:num_requests_running`) 으로 스케일링하는 것이 자연스럽습니다 (RAG API 자체는 CPU 부담이 작아 RPS 기반 표준 HPA 로 충분).

#### 왜 동기 호출인가 (asyncio·streaming 미도입 결정)

`main.py` 의 `/chat` 핸들러는 `async def` 이지만 내부의 retriever / llm_client 호출은 **동기** 입니다. 임베딩 모델의 `model.encode()` 는 CPU 바운드라 asyncio 의 이벤트 루프가 await 할 대상이 없고, vLLM 호출도 OpenAI SDK 의 동기 `create()` 를 그대로 사용합니다. streaming(`stream=True`) 은 학습자가 첫 토큰부터 답변이 나오는 UX 를 제공하지만, Day 5 의 학습 목표(*모듈 분리 + 단위 테스트*) 와 거리가 있어 §11 확장 아이디어로 미룹니다.

상세 설계 노트(*왜 동기 / 임베딩 모델 캐싱 전략*) 는 [`docs/architecture.md`](docs/architecture.md) §3.9·§3.10 을 참조하세요.

#### Day 5 (port-forward) ↔ Day 6 (Ingress) 호출 경로 차이

위 7 단계 시퀀스의 *(1) 진입* 만 Day 5 와 Day 6 에서 다릅니다. 단계 (2)~(6) 의 RAG API 내부 흐름은 동일.

```
[Day 5 — 로컬 개발 (port-forward 2 개)]              [Day 6 — 클러스터 배포 (Ingress)]
                                                     [외부 client (브라우저/curl)]
[학습자 호스트 PC]                                          │ POST /chat (HTTP)
   uvicorn :8001 ◄──────── (직접 호출)                       ▼
   │                                                  ┌─────────────────────┐
   │ port-forward                                     │ GCE LoadBalancer    │ ← Ingress 가 자동 생성
   ├──── localhost:6333 → svc/qdrant ──── (내부 DNS)    │  (외부 IP, ephemeral)│   (`<IP>.nip.io` 해석)
   └──── localhost:8000 → svc/vllm  ──── (내부 DNS)    └─────────┬───────────┘
                                                                │ host: <IP>.nip.io, path: /chat
                                                                ▼
                                                       ┌─────────────────────┐
                                                       │ GCE Ingress         │ ← 40-ingress.yaml
                                                       │ controller          │   rules → backend rag-api:http
                                                       └─────────┬───────────┘
                                                                 ▼
                                                       ┌─────────────────────┐
                                                       │ Service `rag-api`   │ ← 31-rag-api-service.yaml
                                                       │ (ClusterIP :8001)   │   selector: app=rag-api
                                                       └─────────┬───────────┘
                                                                 ▼
                                                       ┌─────────────────────┐
                                                       │ Pod `rag-api-*`     │ ← 30-rag-api-deployment.yaml
                                                       │ (replicas=2, :8001) │   uvicorn main:app
                                                       └─────────────────────┘
                                                                 │ (이후 단계 (2)~(6) 동일 — Qdrant + vLLM 호출)
```

**3 가지 운영적 차이**:

| 항목 | Day 5 (port-forward) | Day 6 (Ingress) |
|---|---|---|
| 호출자 | 학습자 호스트 PC 의 curl/uvicorn | 임의의 외부 client (브라우저/모바일/타 서비스) |
| 인증 | 없음 — 학습자 한 명만 접근 | 없음 — 외부 노출 (학습용 단계, 운영은 cert-manager + auth proxy 별도) |
| latency 추가 | 0 ms (port-forward 가 직접 터널) | +5~30 ms (LoadBalancer + Ingress 라우팅 1 hop) |

Ingress 라우팅의 라인별 결정(GCE vs nginx, nip.io host, timeout) 은 [§4.5](#45-ingress) 에서 다룹니다.

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

Day 6 에서 추가하는 매니페스트 2 개입니다. **§4.3 vLLM Deployment 와 *형제 패턴*** 으로 작성하되 4 가지가 다릅니다 — 변경 목록은 매니페스트 상단 출처 주석에 명시되어 있습니다. Day 7 에서 ConfigMap/Secret 으로 *분리 리팩토링* 될 매니페스트 2 개도 함께 예고합니다.

| 파일 | kind | Day | 역할 |
|---|---|---|---|
| `30-rag-api-deployment.yaml` | Deployment | 6 | RAG API Pod (replicas=2). env 6 종 직접 박기 + `/healthz`(liveness) + `/ready`(readiness, startup) |
| `31-rag-api-service.yaml` | Service | 6 | ClusterIP — Day 6 Ingress 와 Day 7 ServiceMonitor 가 공통 endpoint 로 사용 |
| `32-rag-api-configmap.yaml` | ConfigMap | 7 (예고) | env 6 종 중 비밀이 아닌 5 종(QDRANT_URL/COLLECTION/EMBED_MODEL/LLM_BASE_URL/LLM_MODEL/TOP_K) 외재화 |
| `33-rag-api-secret.yaml` | Secret | 7 (예고) | HF 토큰 (옵션 — 23-vllm-hf-secret.yaml 과 동일 Secret 재사용 가능) |

Day 6 의 학습 목표는 **"일단 동작"** — env 를 Deployment 에 직접 박아서 *최소한의 매니페스트로 클러스터 위 동작 확인* 까지. Day 7 은 **"왜 분리해야 하는가"** — 코드 변경 없이 환경 값 갱신, Secret 의 별도 RBAC, 환경별 values 차이 등을 ConfigMap/Secret 의 학습 가치로 삼습니다 (Phase 2-01 ConfigMap/Secret 토픽과 연결).

#### 4.4.1 핵심 구조 발췌 — env 6 종 (Day 7 분리 예고)

`practice/rag_app/.env.example` 의 6 개 로컬 변수를 *클러스터 내부 DNS* 로 치환해 Deployment 에 직접 박습니다. 핵심 변환은 `localhost` → `<service>.rag-llm.svc.cluster.local` 두 줄.

```yaml
env:
  - name: QDRANT_URL                                       # → Day 7 ConfigMap 32 로 이동 예정
    value: http://qdrant.rag-llm.svc.cluster.local:6333    #   localhost:6333 → Day 1 Headless Service
  - name: QDRANT_COLLECTION
    value: rag-docs                                        # Day 2 인덱싱이 적재한 컬렉션명 (.env.example 와 일치)
  - name: EMBED_MODEL
    value: intfloat/multilingual-e5-small                  # Day 2 결정 — 384 dim, 한국어 자료 대응
  - name: LLM_BASE_URL
    value: http://vllm.rag-llm.svc.cluster.local:8000/v1   # localhost:8000 → Day 4 vLLM Service
  - name: LLM_MODEL
    value: microsoft/phi-2                                 # Day 4 vLLM 의 --served-model-name 과 *완전 일치* 필수
  - name: TOP_K
    value: "3"
  - name: HF_TOKEN                                         # → Day 7 Secret 33
    valueFrom:
      secretKeyRef: { name: hf-secret, key: HF_TOKEN, optional: true }
```

`localhost` → 클러스터 내부 DNS 치환은 Day 5 .env.example 주석에서 이미 예고된 변경입니다. **Service 이름 / namespace / port** 가 모두 일치해야 하며, 한 글자라도 틀리면 Pod 기동 시 `getaddrinfo: Name or service not known` 또는 `ConnectionError: [Errno 111] Connection refused` 로 readiness 통과 실패. lab 트러블슈팅 #2 에서 진단 명령을 안내합니다.

#### 4.4.2 핵심 구조 발췌 — 3 종 Probe (vLLM 보다 짧은 timeout)

```yaml
startupProbe:
  httpGet: { path: /ready, port: http }
  failureThreshold: 30          # 30 × 10s = 최대 5 분 (vLLM 의 절반 — 모델이 130MB 로 작아서)
  periodSeconds: 10
readinessProbe:
  httpGet: { path: /ready, port: http }   # main.py 의 @app.get("/ready") — app.state.ready 가 True 일 때 200
  periodSeconds: 10
livenessProbe:
  httpGet: { path: /healthz, port: http } # main.py 의 @app.get("/healthz") — 프로세스 응답 가능 여부만
  periodSeconds: 30
```

§4.3.3 의 startupProbe·livenessProbe 보호 패턴을 그대로 따르되 *느린 startup 의 길이* 만 다릅니다 — vLLM 은 모델 5GB+ 다운로드라 10 분 허용, RAG API 는 e5-small 130MB + lifespan 초기화라 5 분 허용. **두 probe 를 분리한 이유** 는 Day 5 의 `main.py` 가 의도한 분리(`/ready` 는 lifespan 완료, `/healthz` 는 프로세스 응답) 를 K8s 측에서 그대로 활용하는 데 있습니다 — `lifespan` 안에서 임베딩 모델 로딩이 길어져도 livenessProbe 가 Pod 를 죽이지 않습니다.

#### 4.4.3 핵심 구조 발췌 — resources (CPU bound, GPU/PVC 없음)

```yaml
resources:
  requests: { cpu: "200m", memory: "1Gi" }
  limits:   { cpu: "1",    memory: "2Gi" }
volumes:
  - name: hf-cache
    emptyDir: { sizeLimit: 1Gi }            # 임베딩 모델 캐시. PVC 가 아닌 emptyDir 채택 — 결정 박스 ④
```

vLLM 의 8Gi/16Gi 와 비교하면 1/8 수준입니다. RAG API 는 *임베딩 모델 inference + HTTP I/O* 만 담당하고 무거운 텐서 연산은 vLLM 으로 위임하므로 CPU bound. Day 9 부하 테스트에서 1 Pod = 1 코어가 단일 처리 한계임을 확인하고, Day 8 에서 RPS 기반 HPA 로 확장합니다.

`nodeSelector` / `tolerations` 가 없어서 GKE T4 노드 풀의 taint(`nvidia.com/gpu=present:NoSchedule`) 를 통과하지 못합니다 — *자동으로* 일반 CPU 노드 풀(`default-pool` 또는 e2-medium pool) 에만 schedule 됩니다. 비싼 GPU 노드를 RAG API 가 점유하지 않도록 하는 안전 장치입니다.

#### 4.4.4 핵심 구조 발췌 — RollingUpdate strategy (replicas=2 가용성)

```yaml
strategy:
  type: RollingUpdate
  rollingUpdate:
    maxSurge: 1                # replicas=2 에서 update 시 일시적으로 3 Pod
    maxUnavailable: 0          # 다운타임 0 — 검증의 1 줄 완료 기준이 항상 통과되도록
```

`maxUnavailable: 0` 으로 두면 *새 Pod 이 ready 가 된 뒤에야* 기존 Pod 이 종료됩니다. RAG API 의 startupProbe 가 5 분까지 허용하므로 update 시 일시적으로 3 Pod 가 노드를 점유할 수 있습니다 — 학습용 클러스터(2~3 노드) 에서 노드 자원이 빠듯하면 maxSurge 를 0 으로, maxUnavailable 을 1 로 바꿔 가용성과 자원 사용을 트레이드오프 합니다 (운영 권장은 본 문서값 — 가용성 우선).

#### 4.4.5 결정 박스 4 개

> **결정 ① — 왜 replicas=2 인가 (vLLM 의 1 과 비대칭)**
>
> Day 5 §2.3 ② "RAG API 는 stateless" 결정의 매니페스트 표면입니다. RAG API 의 모든 상태(임베딩 모델 / Qdrant 클라이언트 / vLLM 클라이언트) 는 lifespan 에서 *각 Pod 별 독립적으로* 초기화되며 Pod 간 공유 상태가 없습니다. 따라서 1 Pod 죽어도 다른 Pod 가 그대로 처리 — Day 9 부하 테스트의 *1 Pod = 1 코어 한계* 를 자연스럽게 우회.
>
> | 컴포넌트 | replicas | 근거 |
> |---|---|---|
> | vLLM | 1 | GPU 1 장 = 1 Pod 가 표준. KV cache / continuous batching 이 Pod 내부 상태라 단순 복제 불가 |
> | RAG API | 2 | stateless. Day 8 HPA 로 RPS 따라 1~10 까지 확장 가능 |
> | Qdrant | 1 | StatefulSet (Day 1). 데이터 일관성을 위해 단일 instance, 클러스터링은 §11 확장 |
>
> **운영 시 replicas=2 의 의미** — rolling update 중에도 항상 1 Pod 이 살아 있어 `kubectl rollout restart deploy/rag-api` 가 무중단. Day 6 lab 검증에서 update 중에도 `/chat` 이 200 OK 를 유지하는지 확인합니다.

> **결정 ② — 왜 env 를 Deployment 에 직접 박는가 (Day 7 ConfigMap 분리 예고)**
>
> Day 6 시점에서는 매니페스트 한 장으로 동작 확인을 끝내는 것이 학습 목표입니다. ConfigMap/Secret 분리는 *왜 분리해야 하는가* 라는 학습 가치를 *문제 발생 시점에 가르쳐야* 효과적이라, Day 6 에서 직접 박기로 시작 → Day 7 에서 두 가지 학습자 경험을 만듭니다.
>
> | Day 6 (현재) | Day 7 (분리 후) |
> |---|---|
> | env 변경 → Deployment 매니페스트 수정 → `kubectl apply` → **Pod 재시작 (5 분 cold start)** | env 변경 → ConfigMap 만 수정 → `kubectl rollout restart` → 1 분 안에 반영 |
> | env 6 종이 한 매니페스트 안에 섞임 — 비밀과 평문 구분 어려움 | ConfigMap(평문 5종) + Secret(HF 토큰) 분리 — RBAC 으로 Secret 만 별도 권한 부여 가능 |
> | 환경별 차이를 매니페스트 사본으로 관리 (`30-rag-api-deployment-prod.yaml`) | Helm `values-dev.yaml` / `values-prod.yaml` 한 줄 차이 (Day 10) |
>
> Day 6 lab 트러블슈팅 #2 에서 *env 한 글자 오타로 readiness 실패* 를 학습자가 직접 겪으면 Day 7 에서 ConfigMap 분리의 *체감 가치* 가 살아납니다.

> **결정 ③ — 왜 livenessProbe 와 readinessProbe 의 path 가 다른가 (`/healthz` vs `/ready`)**
>
> 본 캡스톤은 `main.py` 단계에서 두 엔드포인트를 *의도적으로 분리* 했습니다. K8s 의 두 probe 가 *목적이 다르기* 때문입니다.
>
> | Probe | path | 실패 시 동작 | 본 캡스톤의 책임 |
> |---|---|---|---|
> | livenessProbe | `/healthz` | Pod 재시작 | 프로세스 응답 가능 여부만 — `lifespan` 진행 중에도 200 OK |
> | readinessProbe | `/ready` | Service endpoint 에서 제거 (트래픽 차단) | `app.state.ready=True` 일 때만 200 — lifespan 완료 전엔 503 |
> | startupProbe | `/ready` | Pod 재시작 (재시작 횟수 무시) | readinessProbe 와 동일 핸들러 — 첫 5 분 보호 |
>
> 두 probe 를 같은 path 로 두면 lifespan 진행 중(임베딩 모델 다운로드 1~2 분) 에 livenessProbe 가 503 을 받아 Pod 를 죽이는 *무한 재시작 루프* 가 발생합니다. **두 path 분리는 Day 5 코드의 명시적 결정** 이며, Day 6 매니페스트는 그 분리를 활용하는 형태입니다.

> **결정 ④ — 왜 임베딩 모델 캐시는 PVC 가 아닌 emptyDir 인가**
>
> vLLM 의 5GB+ 모델 캐시는 PVC(20Gi RWO) 로 영속화하지만, RAG API 의 e5-small 130MB 는 emptyDir 로 충분합니다.
>
> | 옵션 | 첫 기동 | 재기동 (rolling update) | 운영 부담 | 본 캡스톤 |
> |---|---|---|---|---|
> | **emptyDir** ✅ | 30 초 (130MB 다운로드) | 30 초 (캐시 사라져 재다운로드) | 0 — 매니페스트 1 줄 | replicas=2 의 가용성으로 cold start 영향 최소 |
> | PVC RWO | 30 초 | 5 초 (캐시 hit) | PVC 매니페스트 + storageClass 의존 | Day 9 부하 테스트 후 cold start 가 거슬리면 전환 |
> | PVC RWX | 30 초 | 5 초 (모든 replica 가 같은 캐시 공유) | RWX storageClass 필요 (NFS/Filestore) | 캡스톤 학습 단계엔 과함 |
>
> emptyDir 채택의 **숨은 이점** — Pod 마다 모델 파일이 *복사본* 으로 존재해 디스크 격리. PVC RWO 는 단일 Pod 점유라 replicas=2 와 호환 불가하므로 PVC 로 갈 거면 RWX 만 의미 있음 (운영 권장 패턴은 RWX, 캡스톤 단순성 위해 emptyDir).

#### 4.4.6 Day 6 에서 늘어나는 컴포넌트 표

| 추가 컴포넌트 | 위치 | 라이프사이클 |
|---|---|---|
| Deployment `rag-api` (replicas=2) | namespace `rag-llm` | Day 6~10 유지 |
| Service `rag-api` (ClusterIP, port 8001) | namespace `rag-llm` | Day 6~10 유지 |
| Pod `rag-api-*` × 2 (CPU 노드 풀) | 일반 노드 풀 | Day 6~10 유지. 노드 풀 size=0 시 함께 삭제 |
| Docker Hub 이미지 `<user>/rag-api:0.1.0` | 외부 레지스트리 | 재사용 — Day 9 코드 변경 시에만 새 tag(`0.1.1`) push |

상세 실행 절차는 [`labs/day-06-rag-api-deploy.md`](labs/day-06-rag-api-deploy.md), Ingress 통합은 다음 §4.5.

### 4.5 Ingress

Day 6 에서 추가하는 매니페스트 1 개로 RAG API 가 *외부에 노출* 됩니다. 캡스톤 §3 검증 시나리오의 1 줄 완료 기준(`curl http://<ingress-host>/chat ...`) 이 처음으로 통과하는 시점입니다.

| 파일 | kind | 역할 |
|---|---|---|
| `40-ingress.yaml` | Ingress | GCE Ingress controller 가 LoadBalancer + forwarding rule 자동 생성 → 외부 IP 부여 |

**Phase 2-03 학습 자료와의 의도적 차이** — Phase 2-03 은 minikube + nginx-ingress 기반인데, 본 캡스톤은 GKE 환경 전제이므로 GCE(Google Cloud) Ingress 를 사용합니다. nginx 와 GCE 의 annotation 키가 다르므로 Phase 2-03 매니페스트의 `nginx.ingress.kubernetes.io/*` annotations 를 그대로 복사하면 GCE 가 *조용히 무시* 합니다 (자주 하는 실수 ⑯ 의 변형).

#### 4.5.1 핵심 구조 발췌 — annotations + ingress class

```yaml
metadata:
  name: rag-api
  namespace: rag-llm
  annotations:
    kubernetes.io/ingress.class: "gce"     # GCE 환경 명시. 생략해도 GKE 는 자동으로 GCE 로 처리.
spec:
  # ingressClassName: gce                  # 동등 표현. 명시하려면 본 라인 사용.
  rules:
    - host: <EXTERNAL_IP>.nip.io           # lab Step 6 에서 sed 치환
```

GCE Ingress 는 controller 설치 단계가 *없습니다* — GKE 기본 install 에 포함됩니다. 매니페스트 apply 즉시 GCE Project 의 forwarding rule + health check + backend service 가 자동 생성되며, 약 3~5 분 후 `status.loadBalancer.ingress[0].ip` 에 외부 IP 가 채워집니다.

#### 4.5.2 핵심 구조 발췌 — rules (host + pathType + backend)

```yaml
spec:
  rules:
    - host: <EXTERNAL_IP>.nip.io
      http:
        paths:
          - path: /chat
            pathType: Prefix                             # /chat, /chat/, /chat/anything 모두 매칭
            backend:
              service:
                name: rag-api
                port:
                  name: http                             # Service 31 의 port.name 참조 (자주 하는 실수 ⑯)
          - path: /healthz                               # 외부에서 RAG API 헬스 확인용 (선택)
            pathType: Prefix
            backend:
              service: { name: rag-api, port: { name: http } }
```

`backend.service.port.name` 에 number(`8001`) 대신 `http` (문자열) 를 사용하는 이유 — Service 31 에서 `name: http` named port 를 선언했기 때문에 *동일 키워드로 참조* 하면 Service port 변경 시 Ingress 매니페스트는 그대로 둘 수 있습니다. Day 7 ServiceMonitor 도 동일 named port 를 참조하므로 일관성이 살아납니다.

#### 4.5.3 결정 박스 3 개

> **결정 ① — 왜 GCE Ingress 인가 (vs nginx-ingress)**
>
> Phase 2-03 학습 자료와 *의도적으로 다르게* 갑니다. 캡스톤이 GKE 전제이므로 GCE 를 채택하는 것이 자연스럽지만, *학습 연속성* 측면에서는 nginx 도 후보입니다.
>
> | 옵션 | controller 설치 | annotations | 외부 IP 획득 | Day 8 HPA 호환 |
> |---|---|---|---|---|
> | **GCE Ingress** ✅ | 없음 (GKE 기본) | 단순 (몇 가지만 존재) | 자동 (LoadBalancer + forwarding rule) | BackendConfig CRD 로 timeout/CDN 통합 |
> | nginx-ingress | Helm chart 설치 1 회 | 풍부 (`proxy-read-timeout` 등 수십 종) | LoadBalancer Service 별도 생성 | annotation 으로 timeout 세팅 |
>
> **trade-off**: GCE 는 Phase 2-03 매니페스트 패턴(nginx annotations) 이 *그대로 동작하지 않음* — 학습자가 무심코 `nginx.ingress.kubernetes.io/proxy-read-timeout` 을 추가하면 GCE 는 무시하고 기본 30 초 timeout 으로 동작 → vLLM cold start 시 504 Gateway Timeout. lab 트러블슈팅 #6 에 이 경로의 진단 명령을 둡니다. 본 캡스톤은 timeout 조정을 Day 8 의 BackendConfig CRD 로 별도 학습 (결정 ③ 참조).

> **결정 ② — 왜 nip.io host 인가 (vs Host 헤더 시뮬레이션)**
>
> 학습자가 외부 도메인 없이 *실제 DNS 해석* 으로 검증할 수 있도록 nip.io 를 사용합니다.
>
> | 옵션 | 도메인 비용 | 검증 방식 | 브라우저 호환 |
> |---|---|---|---|
> | **nip.io** ✅ | 0 원 | `curl http://34.123.45.67.nip.io/chat` 직접 동작 | ✅ — 그대로 클릭 가능 |
> | `chat.example.com` placeholder | 0 원 | `curl -H "Host: chat.example.com" http://<IP>/chat` Host 헤더 수동 | ❌ — `/etc/hosts` 수정 필요 |
> | host 생략 (path 라우팅만) | 0 원 | `curl http://<IP>/chat` | ✅ | Phase 2-03 의 host 라우팅 학습 포인트 무시 |
>
> nip.io 의 동작 원리 — 모든 `<IP>.nip.io` 형태 도메인의 A 레코드를 자동으로 *그 IP* 로 응답하는 와일드카드 DNS. 외부 의존성이지만 ML 엔지니어 학습 환경에서는 사실상 표준입니다. lab Step 6 에서 `nslookup 34.123.45.67.nip.io` 로 해석 동작을 직접 확인합니다.

> **결정 ③ — 왜 timeout 조정을 Day 6 에서 안 하는가**
>
> GCE Ingress 의 default timeout 은 30 초 — vLLM cold start 시점(첫 호출이 5~10 초) 이 넘어가면 504 가 발생할 수 있습니다. 그럼에도 본 Day 6 매니페스트는 timeout 을 *건드리지 않습니다*.
>
> 이유: GCE Ingress 의 timeout 조정은 별도 CRD `BackendConfig` 가 필요한데, 이는 Day 8 의 HPA + BackendConfig 학습과 *함께 다루는 것이 자연스럽기* 때문입니다.
>
> | Day | 매니페스트 | timeout 동작 |
> |---|---|---|
> | Day 6 | Ingress 40 만 | 기본 30 초 — cold start 시 504 가능 (vLLM 워밍업 후엔 1~3 초라 정상) |
> | Day 7 | + ServiceMonitor 34 | 동일 (메트릭만 추가) |
> | Day 8 | + BackendConfig + HPA 35 | `timeoutSec: 120` 으로 명시적 상향. cold start 보호 |
>
> Day 6 lab 트러블슈팅 #6 에서 504 진단 + Day 8 까지의 우회(첫 호출은 무시하고 두 번째 호출 검증) 를 안내합니다.

#### 4.5.4 Day 6 에서 늘어나는 컴포넌트 표

| 추가 컴포넌트 | 위치 | 라이프사이클 |
|---|---|---|
| Ingress `rag-api` | namespace `rag-llm` | Day 6~10 유지. Day 종료 시 비용 회수 위해 `kubectl delete ingress` (자주 하는 실수 ⑱) |
| GCE LoadBalancer + forwarding rule (자동 생성) | GCP Project 자원 | Ingress 와 동기 — Ingress 삭제 시 자동 회수 (5 분 이내) |
| 외부 IP (ephemeral) | GCP Project 자원 | Ingress apply 후 3~5 분 부여, 삭제 시 자동 반납 |
| nip.io DNS A 레코드 | 외부 (nip.io 서비스) | 0 원, 학습자 액션 없음 — IP 만 알면 자동 해석 |

상세 실행 절차는 [`labs/day-06-rag-api-deploy.md`](labs/day-06-rag-api-deploy.md), GCE Ingress 의 trade-off 노트(BackendConfig / Cloud Armor / GitOps 와의 호환) 는 [`docs/architecture.md`](docs/architecture.md) §3.11 참조.

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

### 4.8 ConfigMap / Secret 분리 (Day 7)

Day 6 매니페스트 30 의 env 6 종 + HF_TOKEN secretKeyRef 7 줄을 *통째 참조* 2 줄로 단축합니다. 본 절은 **§4.4 결정 박스 ② 의 "Day 7 분리 후" 컬럼이 실제로 어떻게 구현되는가** 를 다룹니다.

#### 4.8.1 매니페스트 2 종 + Deployment 30 변경 표

| 산출물 | 종류 | 키/필드 | Day 6 → Day 7 변화 |
|---|---|---|---|
| `manifests/32-rag-api-configmap.yaml` | ConfigMap | data 6 키 (QDRANT_URL/COLLECTION/EMBED_MODEL/LLM_BASE_URL/LLM_MODEL/TOP_K) | 신규 (Day 6 의 env 6 종을 그대로 이전) |
| `manifests/33-rag-api-secret.yaml` | Secret (Opaque) | stringData 1 키 (HF_TOKEN, placeholder) | 신규 (23-vllm-hf-secret 와 *별도* 생성 — 결정 박스 ②) |
| `manifests/30-rag-api-deployment.yaml` | Deployment | env 6 + HF_TOKEN block (총 7 줄) → envFrom 1 블록 | env 7 줄 → envFrom 2 줄 (configMapRef + secretRef.optional) |

#### 4.8.2 핵심 구조 발췌 — envFrom 일괄 주입

```yaml
# manifests/30-rag-api-deployment.yaml (Day 7 리팩토링)
containers:
  - name: rag-api
    image: docker.io/<user>/rag-api:0.1.0
    ports:
      - { name: http, containerPort: 8001 }
    envFrom:
      - configMapRef:
          name: rag-api-config        # 32-rag-api-configmap.yaml 의 6 키 일괄 주입
      - secretRef:
          name: rag-api-secrets       # 33-rag-api-secret.yaml 의 HF_TOKEN
          optional: true              # Secret 부재해도 Pod 기동 정상 — e5-small public 이라 디폴트
```

ConfigMap 의 키명을 `QDRANT_URL` 처럼 *환경변수명과 완전 일치* 시켰기에 매핑 변환 없이 바로 env 가 됩니다. Phase 2-01 §1-2 envFrom 패턴.

#### 4.8.3 결정 박스 4 개

> **결정 ① — 왜 ConfigMap 1 개로 통합하는가 (Qdrant/vLLM/일반 분리 거부)**
>
> 옵션 3 가지 — A) ConfigMap 1 개 통합 / B) Qdrant·vLLM·일반 3 개 분리 / C) 키별 분리 6 개. 본 캡스톤은 **A 채택**.
>
> | 옵션 | 매니페스트 수 | RBAC 분리 | envFrom 줄 수 | 캡스톤 적합성 |
> |---|---|---|---|---|
> | **A: 단일 통합** ✅ | 1 | 컴포넌트 단위(rag-api) — 충분 | 1 블록 | 6 키 모두 *RAG API 한 컴포넌트 전용* |
> | B: 3 개 분리 | 3 | 컴포넌트 단위 — A 와 동일 | 3 블록 | 매니페스트 비대 + RBAC 이득 없음 |
> | C: 키별 6 개 | 6 | 키 단위 — 과도 | 6 블록 | 학습 부담만 증가 |
>
> 본 캡스톤은 RAG API 한 컴포넌트의 설정만 6 키로 모았기 때문에, 분리해도 *서로 다른 권한 주체* 가 없습니다. Helm Day 10 차트에서도 `templates/rag-api.yaml` 한 파일에 ConfigMap + Deployment 가 함께 정의되는 자연스러운 결합.

> **결정 ② — 왜 Secret 33 을 23-vllm-hf-secret 과 *별도* 로 두는가**
>
> 옵션 3 가지 — A) RAG API 전용 Secret 33 신규 / B) 23-vllm-hf-secret 재사용 / C) 두 컴포넌트 통합 Secret. 본 캡스톤은 **A 채택**.
>
> | 옵션 | 컴포넌트 RBAC 분리 | Helm 차트 분리 | 의미 명확성 | 단점 |
> |---|---|---|---|---|
> | **A: 별도 Secret** ✅ | 컴포넌트별 가능 | `templates/vllm.yaml`+`templates/rag-api.yaml` 깔끔 | 이름이 자기 컴포넌트를 가리킴 | HF_TOKEN 값 *2 곳에 중복* — 학습 단계 placeholder 라 무영향 |
> | B: 23 재사용 | vLLM Secret 에 RAG API 가 의존 | `rag-api.yaml` 이 vllm 의 Secret 참조 | 이름(`hf-secret`) 이 *vLLM 전용* 으로 보여 오용 | RBAC 으로 vLLM/RAG API 권한 분리 어려움 |
> | C: 통합 Secret | 컴포넌트 분리 불가 | 한 차트로 합쳐야 함 | 책임 경계 모호 | Phase 5 GitOps 시 가장 큰 부담 |
>
> 단점 (값 중복) 은 학습 단계에서 둘 다 placeholder 라 무영향. 운영 배포 시 SealedSecrets/External Secrets Operator 로 *원본은 한 곳* 에 두고 *parametrize* 하는 패턴으로 해결 — Phase 5 주제.

> **결정 ③ — 왜 envFrom 일괄 주입인가 (env.valueFrom 명시 거부)**
>
> 옵션 2 가지 — A) `envFrom` 일괄 / B) `env: [{name, valueFrom: {configMapKeyRef: {name, key}}}]` 6 번 명시. 본 캡스톤은 **A 채택**.
>
> | 옵션 | 매니페스트 줄 수 | 키명 변경 가능 | 매니페스트만 보고 키 파악 | 캡스톤 적합성 |
> |---|---|---|---|---|
> | **A: envFrom 일괄** ✅ | 2 줄 (configMapRef + secretRef) | 환경변수명=키명 강제 | ConfigMap 매니페스트 함께 봐야 함 | 6 키 모두 환경변수명=ConfigMap 키명 일치 — 매핑 불필요 |
> | B: env.valueFrom | 6 키 × 6 줄 = 36 줄 | 자유 (env name ≠ key 가능) | Deployment 한 곳에서 키 모두 보임 | 매니페스트 비대 + DRY 위반 |
>
> 단점 (매니페스트만 보고 키 모름) 은 ConfigMap 32 가 같은 디렉토리에 있어 상쇄. ⚠ 키 충돌 시 *후순위* (envFrom 리스트의 뒤쪽) 가 우선이라, 본 캡스톤처럼 ConfigMap 후 Secret 순서면 Secret 의 동명 키가 ConfigMap 값을 덮어씁니다 — Phase 2-01 자주 하는 실수 인용.

> **결정 ④ — 왜 ConfigMap 변경 시 Pod 재시작이 자동이 아닌가 (Day 7 = 수동, Day 10 = 자동)**
>
> ConfigMap 의 데이터를 *envFrom* 으로 주입하면 **Pod 의 환경변수는 컨테이너 기동 시점에 한 번만 평가** 됩니다. ConfigMap 을 나중에 수정해도 *이미 동작 중인 컨테이너의 env 는 옛값* — Pod 재시작이 명시적으로 필요합니다.
>
> | 옵션 | 동작 | 외부 의존성 | 캡스톤 적합성 |
> |---|---|---|---|
> | **Day 7: `kubectl rollout restart` 수동** ✅ | 학습자가 직접 명령 실행 | 없음 | *왜 자동이 아닌가* 를 직접 체험 (자주 하는 실수 #20) |
> | **Day 10: `checksum/config` annotation** | Helm 차트가 ConfigMap 의 sha256 을 podTemplate annotation 에 박음 → ConfigMap 변경 → annotation 변경 → rollout 자동 | Helm | Day 10 의 한 줄 배포 패턴과 자연스러운 결합 |
> | Reloader 컨트롤러 | `reloader.stakater.com/auto: true` annotation 만으로 자동 rollout | stakater/Reloader 설치 (1 컨트롤러 + 1 RBAC) | 외부 의존성 추가 — 캡스톤 학습 부담 |
> | volumeMount 주입 (envFrom 대신) | ConfigMap 을 파일로 마운트하면 *kubelet 이 60 초 단위 폴링* 으로 파일 갱신 (재시작 없이 반영) | 없음 | 코드 변경 필요 — `os.environ` 대신 파일 읽기 + watcher 로직 |
>
> 본 캡스톤은 *학습자 체험* 을 위해 Day 7 에서 수동 → Day 10 Helm 자동화로 점진적 추상화. Reloader 는 Phase 5 의 *컨트롤러 패턴 학습* 에서 다시 등장.

#### 4.8.4 Day 7 에서 늘어나는 컴포넌트 표 (1)

| 추가 컴포넌트 | 위치 | 라이프사이클 |
|---|---|---|
| ConfigMap `rag-api-config` | namespace `rag-llm` | Day 7~10 유지. ConfigMap 변경 시 `kubectl rollout restart` 필수 |
| Secret `rag-api-secrets` | namespace `rag-llm` | Day 7~10 유지. 토큰 부재 시 `optional: true` 가 동작 |
| Deployment 30 (envFrom 리팩토링) | 동일 (Day 6 의 30 을 *덮어쓰기*) | 동일 |

상세 실행 절차는 [`labs/day-07-config-secret-monitoring.md`](labs/day-07-config-secret-monitoring.md) Step 2~4.

### 4.9 ServiceMonitor — Prometheus 메트릭 자동 수집 (Day 7)

본 절은 [`practice/rag_app/main.py`](practice/rag_app/main.py) 에 등록한 prometheus_client 메트릭 4 종(Day 5 §5.5) + vLLM 의 표준 메트릭 6 종(Phase 4-3 §1-6) 을 Prometheus 가 자동 scrape 하도록 연결합니다.

#### 4.9.1 매니페스트 2 종 표

| 산출물 | 대상 Service | 핵심 라벨/필드 | 결정 박스 |
|---|---|---|---|
| `manifests/24-vllm-servicemonitor.yaml` | `vllm` (Service 22, port 8000) | release: prom + selector app=vllm + endpoints[0].port=http | 결정 ① (Phase 4-3 이식 5 변경점) |
| `manifests/34-rag-api-servicemonitor.yaml` | `rag-api` (Service 31, port 8001) | release: prom + selector app=rag-api + endpoints[0].port=http + interval=30s | 결정 ① ② |

#### 4.9.2 핵심 구조 발췌 — RAG API ServiceMonitor 라벨 매칭 2 단계

```yaml
# manifests/34-rag-api-servicemonitor.yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: rag-api
  namespace: rag-llm
  labels:
    app: rag-api
    component: rag-api
    release: prom            # ← 단계 1: Prometheus CR 의 serviceMonitorSelector 와 매칭
spec:
  selector:
    matchLabels:
      app: rag-api           # ← 단계 2: Service 31 의 metadata.labels 와 매칭 (replicas=2 → endpoints 2 개)
  endpoints:
    - port: http             # Service 31 의 ports[0].name 과 일치 (number 8001 직접 사용 대신)
      path: /metrics         # main.py 의 prometheus_client 엔드포인트
      interval: 30s          # vLLM(15s) 보다 길게 — RAG API 는 RPS 변동이 분 단위
      scrapeTimeout: 10s
```

**라벨 매칭 2 단계** (자주 하는 실수 #19):

```
[Prometheus CR]                       [ServiceMonitor]                  [Service]
serviceMonitorSelector:    ─ 단계1 ─→  metadata.labels:      ─ 단계2 ─→  metadata.labels:
  matchLabels:                          app: rag-api                       app: rag-api
    release: prom                       release: prom        ← 매칭 핵심
                                      spec.selector.matchLabels:
                                        app: rag-api
```

둘 중 하나만 어긋나도 Targets 페이지에 안 잡힙니다. Phase 3-02 §1-2 와 동일 패턴.

#### 4.9.3 결정 박스 3 개

> **결정 ① — 왜 kube-prometheus-stack(Helm) 인가 (Prometheus 직접 설치 거부)**
>
> 옵션 3 가지 — A) kube-prometheus-stack / B) Prometheus + Grafana 매니페스트 직접 작성 / C) 매니지드(GMP, Cloud Monitoring). 본 캡스톤은 **A 채택**.
>
> | 옵션 | 설치 명령 | CRD 자동 등록 | Day 8 Grafana 통합 | 캡스톤 적합성 |
> |---|---|---|---|---|
> | **A: kube-prometheus-stack** ✅ | `helm install prom ... --set ...` | ServiceMonitor/PrometheusRule/AlertmanagerConfig 등 자동 | 차트에 Grafana 포함 | Phase 3-02 와 *동일 패턴 재사용* |
> | B: 직접 작성 | YAML 수십 장 | 수동 등록 필요 | Grafana 별도 설치 | 학습 부담 — 캡스톤 학습 가치는 ServiceMonitor 자체 |
> | C: GMP / Cloud Monitoring | gcloud CLI | 매니지드 | Cloud Console 사용 | K8s 학습 패턴(CRD) 누락 |
>
> Phase 3-02 의 `values.yaml` (retention 2 일 + Alertmanager 비활성) 그대로 재사용 — 학습 누적성.

> **결정 ② — 왜 release name 을 `prom` 으로 두는가**
>
> kube-prometheus-stack 의 Prometheus CR 은 기본적으로 `serviceMonitorSelector: { matchLabels: { release: <release-name> } }` 로 설정됩니다. Helm install 시 release name 을 `prom` 으로 두면 ServiceMonitor 의 `release: prom` 라벨 한 줄로 자동 매칭. Phase 3-02 와 일관.
>
> 만약 학습자가 release name 을 다르게 두면(예: `helm install monitoring prometheus-community/...`) ServiceMonitor 의 라벨도 `release: monitoring` 으로 일치시켜야 합니다. 잊으면 Targets 페이지 빈 상태 (자주 하는 실수 #19).

> **결정 ③ — 왜 Qdrant ServiceMonitor 는 본 Day 에서 빠지는가**
>
> 4 옵션 중 본 캡스톤은 **부록 한 단락 + Day 10 Helm 으로 미룸** (architecture.md §3.12.3 결정 노트 표 참고).
>
> | 옵션 | 본 Day 매니페스트 | 학습 가치 | 운영 가치 |
> |---|---|---|---|
> | **부록 + Day 10 Helm** ✅ | vllm + rag-api 2 개만 | RAG/LLM 핵심 메트릭에 집중 | Day 10 Helm 차트로 3 종 통합 도입 |
> | Day 7 에 정식 포함 | 3 개 (35 신규) | Qdrant Service 에 named port 추가 선결 — 학습 흐름 분산 | 동일 |
> | Day 8 Grafana 시점 도입 | 2 개 → 3 개 | Day 8 의 HPA 학습 흐름 방해 | 동일 |
> | 영구 미적용 | 2 개 | (단순) | Qdrant 모니터링 부재 — 운영 곤란 |
>
> Qdrant 는 6333 포트의 `/metrics` 가 기본 노출이지만, 캡스톤 매니페스트 11-qdrant-service.yaml 에 named port 가 없어 ServiceMonitor 작성 시 추가 작업 필요. Day 10 Helm 차트에서 vllm/rag-api/qdrant 3 종 통합으로 정식 도입.

#### 4.9.4 Day 7 에서 늘어나는 컴포넌트 표 (2)

| 추가 컴포넌트 | 위치 | 라이프사이클 |
|---|---|---|
| Helm release `prom` (kube-prometheus-stack) | namespace `monitoring` | Day 7~10 유지. Day 8 Grafana 작업의 입력 |
| ServiceMonitor `vllm` | namespace `rag-llm` | Day 7~10 유지 |
| ServiceMonitor `rag-api` | namespace `rag-llm` | Day 7~10 유지 |

상세 실행 절차는 [`labs/day-07-config-secret-monitoring.md`](labs/day-07-config-secret-monitoring.md) Step 5~7.

---

## 5. RAG API 구현 노트

§3.1 의 7 단계 흐름을 실제 Python 코드로 분리한 결과가 [`practice/rag_app/`](practice/rag_app/) 의 6 개 모듈입니다. 본 절은 **모듈을 왜 그렇게 나눴는가** 와 **각 모듈이 어떤 책임만 갖는가** 의 결정 노트입니다.

### 5.1 모듈 분리 원칙 — main.py 는 *조립* 만

캡스톤 §2 결정 #5 에 따라 `main.py` 는 **80 줄 이내** 로 유지하고 실제 로직은 3 개 하위 모듈에 위임합니다. 이는 Phase 4-3 의 `fastapi_app.py` 단일 파일 패턴과 의도적으로 다릅니다 — RAG API 는 *서로 독립적인 두 외부 의존성(Qdrant + vLLM)* 을 호출하므로, 각 의존성의 단위 테스트를 분리하려면 모듈도 분리되어야 합니다.

| 파일 | 역할 | LOC | 외부 의존성 |
|------|------|-----|-------------|
| [`main.py`](practice/rag_app/main.py) | FastAPI 진입점, lifespan, Pydantic 스키마, 메트릭 정의, 3 모듈 조립 | ~140 | fastapi, prometheus-client |
| [`retriever.py`](practice/rag_app/retriever.py) | Qdrant 검색 + e5 query prefix + RetrievedChunk dataclass | ~120 | qdrant-client, sentence-transformers |
| [`llm_client.py`](practice/rag_app/llm_client.py) | vLLM OpenAI 호환 호출 + timeout 명시 | ~75 | openai |
| [`prompts.py`](practice/rag_app/prompts.py) | 한국어 SYSTEM_PROMPT + build_context + build_messages | ~70 | (없음 — 순수 함수) |
| [`tests/test_retriever.py`](practice/rag_app/tests/test_retriever.py) | retriever 단위 테스트 5+1 케이스 (Qdrant·임베딩 모두 mock) | ~165 | pytest, unittest.mock |
| [`Dockerfile`](practice/rag_app/Dockerfile) | Day 6 빌드용 멀티스테이지 (port 8001) | ~40 | — |

> 💡 **prompts.py 가 외부 의존성 0 인 이유**
>
> SYSTEM_PROMPT 변경, context 구분자 변경, 인용 마커 [n] 형식 변경 — 이 3 가지는 **재배포 없이도 잦은 실험** 이 필요한 부분입니다. prompts.py 를 순수 함수로 두면 Day 9 부하 테스트 후 *프롬프트만 4~5 변형으로 비교* 하는 실험이 코드 변경 한 줄로 가능합니다. retriever / llm_client 가 여러 외부 객체를 가져야 하는 것과 대비됩니다.

### 5.2 retriever.py — 임베딩 모델 캐싱 + e5 prefix

```python
# practice/rag_app/retriever.py
class QdrantRetriever:
    def __init__(self, url, collection, embed_model_name, embed_model=None, qdrant_client=None):
        self._use_e5_prefix = _is_e5_model(embed_model_name)
        self.embed_model = embed_model or SentenceTransformer(embed_model_name)  # 1 회 로드
        self.client = qdrant_client or QdrantClient(url=url)

    def search(self, query: str, top_k: int) -> list[RetrievedChunk]:
        if top_k <= 0:
            return []                                                # 명시적 경계 처리
        prefixed = (_E5_QUERY_PREFIX + query) if self._use_e5_prefix else query
        qvec = self.embed_model.encode(prefixed, normalize_embeddings=True).tolist()
        hits = self.client.search(collection_name=self.collection, query_vector=qvec, limit=top_k, ...)
        return [RetrievedChunk(text=..., score=..., source=..., heading=..., chunk_id=...) for hit in hits]
```

**핵심 결정:**
- 임베딩 모델은 **`__init__` 에서 1 회 로드**, `search()` 호출마다 재로드하지 않음 — §10 자주 하는 실수 #15 의 사전 차단
- `embed_model` / `qdrant_client` 인자를 **테스트 주입 가능** 하게 열어둠 — pytest 가 mock 으로 호출하므로 인프라 의존성 0
- e5 query prefix 는 Day 2 인덱싱(`passage:`) 와 짝을 이루는 `query:` — 두 prefix 가 일관되어야 recall 정상 (§10 #13)
- `RetrievedChunk` 는 `@dataclass` — 불변 데이터 컨테이너로 prompts.build_context / main._to_source 에 그대로 전달

### 5.3 llm_client.py — OpenAI SDK + timeout 명시

```python
# practice/rag_app/llm_client.py
class VLLMClient:
    def __init__(self, base_url, model, timeout=120.0, client=None):
        self.model = model      # ← Day 4 의 --served-model-name 과 *완전 동일* 해야 함
        self.client = client or OpenAI(base_url=base_url, api_key="EMPTY", timeout=timeout)

    def chat(self, messages, temperature=0.2, max_tokens=512) -> str:
        completion = self.client.chat.completions.create(
            model=self.model, messages=messages, temperature=temperature, max_tokens=max_tokens,
        )
        return completion.choices[0].message.content or "" if completion.choices else ""
```

**핵심 결정:**
- `api_key="EMPTY"` 는 더미 — vLLM 은 인증을 강제하지 않음 (Phase 4-3 와 동일)
- `timeout=120` 은 phi-2 cold cache 첫 토큰(30~60 초) 을 견디면서 학습 흐름이 끊기지 않을 정도 — OpenAI SDK 기본값(약 600 초) 보다 짧게 두어 *명백한 실패* 가 빨리 보이게
- `temperature=0.2` 는 RAG 답변 일관성을 위한 보수적 값 — 학습자가 두 번 호출했을 때 컨텍스트 같으면 답변도 거의 같아야
- streaming 미도입 (캡스톤 §2 결정 #6) — 단순 응답 1 회로 학습 흐름 단순화, 확장은 §11 로

### 5.4 prompts.py — 한국어 SYSTEM_PROMPT + 인용 마커

```python
# practice/rag_app/prompts.py
SYSTEM_PROMPT = (
    "당신은 Kubernetes 와 ML 엔지니어링을 가르치는 한국어 전문가입니다. "
    "아래 [Context] 의 내용만 근거로 사용자의 질문에 한국어로 답변하세요. "
    "Context 에 답이 없으면 '제공된 자료에서 답을 찾을 수 없습니다.' 라고 정직하게 답하고, "
    "추측하거나 일반 지식으로 보충하지 마세요. 답변에 근거가 된 청크의 [번호] 를 본문에 인용하세요."
)

def build_context(chunks: list[RetrievedChunk]) -> str:
    if not chunks:
        return "(검색된 자료가 없습니다.)"
    blocks = [f"[{i}] (source: {c.source} / phase: {c.phase} / topic: {c.topic} / heading: {c.heading})\n{c.text}"
              for i, c in enumerate(chunks, start=1)]
    return "\n---\n".join(blocks)

def build_messages(user_query: str, chunks: list[RetrievedChunk]) -> list[dict]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": f"[Context]\n{build_context(chunks)}"},
        {"role": "user",   "content": user_query},
    ]
```

**핵심 결정 (캡스톤 §2 결정 #2·#7·#8):**
- **한국어 system prompt** — 본 코스 자료가 한국어이므로 답변 언어 일관성 우선. phi-2 가 영어 강한 SLM 이지만 *한국어로 답변* 강제 + *한국어 context* 두 조건이면 답변 품질 충분
- **컨텍스트 한정 + 환각 억제** — "Context 에 답이 없으면 모른다고" 명시 강제. 운영 시 RAG 의 가장 큰 함정인 *모델이 자기 사전지식으로 답변* 을 차단
- **인용 마커 `[번호]` 강제** — 답변 본문에 `[1] [2]` 가 등장하면 사용자가 sources 항목과 1:1 매칭으로 검증 가능
- **메타 4 종 컨텍스트 노출** — `(source: ... / phase: ... / topic: ... / heading: ...)` 가 LLM 입력에도 들어가 모델이 "어느 자료를 참고했는지" 인지하고 답변

### 5.5 main.py — lifespan + 4 메트릭 + 단순 조립

```python
# practice/rag_app/main.py
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.retriever = QdrantRetriever(url=QDRANT_URL, collection=QDRANT_COLLECTION,
                                          embed_model_name=EMBED_MODEL)        # ← 1 회 로드
    app.state.llm = VLLMClient(base_url=LLM_BASE_URL, model=LLM_MODEL)
    app.state.ready = True
    yield                                                                       # ← 요청 처리 구간
    # shutdown 정리는 별도 없음 (외부 의존성이 connection pool 알아서 정리)

app = FastAPI(title="Capstone RAG API", lifespan=lifespan)

CHAT_COUNT = Counter("rag_chat_total", "Total /chat requests", ["status"])
CHAT_LATENCY = Histogram("rag_chat_latency_seconds", ...)
RETRIEVE_LATENCY = Histogram("rag_retrieve_latency_seconds", ...)
LLM_LATENCY = Histogram("rag_llm_latency_seconds", ...)

@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    user_query = req.messages[-1].content                       # last user message 만 사용
    top_k = req.top_k if req.top_k is not None else TOP_K_DEFAULT
    with CHAT_LATENCY.time():
        with RETRIEVE_LATENCY.time():
            chunks = app.state.retriever.search(user_query, top_k)
        messages = build_messages(user_query, chunks)
        with LLM_LATENCY.time():
            answer = app.state.llm.chat(messages)
    CHAT_COUNT.labels(status="ok").inc()
    return ChatResponse(answer=answer, sources=[_to_source(c) for c in chunks])
```

> 💡 **결정 박스 — 임베딩 모델 캐싱 전략 (캡스톤 §2 결정 #5)**
>
> 캡스톤은 임베딩 모델 인스턴스를 **FastAPI lifespan + `app.state.retriever`** 에 보관합니다. 다음 두 대안을 검토 후 본 패턴을 선택했습니다.
>
> | 옵션 | 장점 | 단점 |
> |---|---|---|
> | **lifespan + app.state** ✅ | 테스트에서 `TestClient` 로 lifespan 우회 가능 / Pod 라이프사이클과 정확히 일치 | 코드가 한 단계 추가 |
> | module-level singleton (`_state` dict) | 가장 단순 | import 시점에 즉시 모델 로드 → pytest collection 단계에서 5GB 파일 다운로드 시도 (테스트 환경 오염) |
> | class instance 의존성 주입 (FastAPI Depends) | 호출별 mock 가능 | retriever 호출 시마다 의존성 그래프 평가 — *불필요한* 동적 생성 |
>
> 본 캡스톤의 학습 단계에서는 lifespan 패턴이 *명시적 + 테스트 친화* 의 균형이 가장 좋습니다. 상세 비교는 [`docs/architecture.md`](docs/architecture.md) §3.10 임베딩 모델 로딩 전략 참조.

### 5.6 tests/test_retriever.py — 인프라 의존성 0 의 단위 테스트

캡스톤 §2 결정 #4 에 따라 retriever 의 단위 테스트는 **Qdrant client 와 임베딩 모델 모두 mock 으로 주입** 합니다. CI 환경에서 port-forward 없이 통과해야 하므로 라이브 호출은 lab Step 4·8 의 curl 검증으로 분리합니다.

```python
def _make_retriever(points, embed_model_name="intfloat/multilingual-e5-small"):
    embed_mock = MagicMock()
    embed_mock.encode.return_value = SimpleNamespace(tolist=lambda: [0.1, 0.2, 0.3])
    qdrant_mock = MagicMock()
    qdrant_mock.search.return_value = points
    return QdrantRetriever(
        url="http://mock:6333", collection="rag-docs",
        embed_model_name=embed_model_name,
        embed_model=embed_mock, qdrant_client=qdrant_mock,                    # ← 주입
    )
```

5+1 케이스가 다루는 영역:

| 케이스 | 검증 대상 |
|--------|-----------|
| `test_search_returns_chunks` | mock 4 개 → top_k=3 호출 시 3 개 RetrievedChunk 매핑 + Qdrant 호출 인자 |
| `test_payload_metadata_preserved` | payload 4 종(source/phase/topic/heading) 이 RetrievedChunk 에 보존 |
| `test_top_k_boundary` | `top_k=0` → 빈 리스트 (Qdrant 호출 X) / `top_k=10` → 결과 4 개 |
| `test_empty_results` | Qdrant 가 빈 리스트 반환 시 `[]` 반환, 예외 없음 |
| `test_e5_query_prefix_applied` | e5 모델일 때 encode 인자가 `'query: '` 로 시작 |
| `test_non_e5_model_no_prefix` | e5 가 아닌 모델은 prefix 미적용 |

> ⚠️ **단위 테스트 범위의 의도된 한계**
>
> 본 테스트는 *retriever 의 책임 영역만* 검증합니다 — 실제 Qdrant 컬렉션이 비어있거나 차원이 다르면 테스트는 통과하지만 라이브 호출은 실패합니다. 그런 통합 검증은 lab Step 4 (`python -c "from retriever import ..."` 단독 호출) 와 Step 8 (`/chat` curl) 로 분리됩니다.

상세 실행 절차는 [`labs/day-05-rag-api-impl.md`](labs/day-05-rag-api-impl.md) 를 참고하세요.

---

## 6. 모니터링 핵심 메트릭

§4.9 의 ServiceMonitor 가 *수집하는* 메트릭들이 어떤 의미를 가지는지 — 그리고 Day 8 (HPA + Grafana) 와 Day 9 (부하 테스트) 에서 어떻게 활용되는지 4 축으로 정리합니다.

> 💡 본 절은 *이론* 입니다. 실제 PromQL 쿼리 실습은 [`labs/day-07-config-secret-monitoring.md`](labs/day-07-config-secret-monitoring.md) Step 8 참고. Grafana 대시보드 화면 구성은 Day 8 lab 에서 다룹니다.

### 6.1 RAG API 메트릭 4 종

[`practice/rag_app/main.py`](practice/rag_app/main.py) 가 등록한 prometheus_client 메트릭. ServiceMonitor 34 가 30 초 간격으로 `/metrics` 를 scrape.

| 메트릭명 | 타입 | 라벨 | 의미 | Day 8 활용 |
|---|---|---|---|---|
| `rag_chat_total` | Counter | `status` (ok/not_ready/bad_request/error) | `/chat` 누적 호출 수 | `rate(...[1m])` → HPA 의 RPS 입력 |
| `rag_chat_latency_seconds` | Histogram | (없음) | `/chat` 전체 응답 latency (sources 직렬화 포함) | p95/p99 → Grafana 대시보드 SLO |
| `rag_retrieve_latency_seconds` | Histogram | (없음) | retriever 만의 latency (Qdrant 검색 + e5 인코딩) | 병목 분리 — vLLM 이 느린지 retriever 가 느린지 |
| `rag_llm_latency_seconds` | Histogram | (없음) | vLLM `/v1/chat/completions` 호출 latency | 병목 분리. timeout=120 의 95% 도달 여부 |

**왜 이 4 종인가** — `/chat` 한 건이 `retriever → llm` 두 단계로 분해되므로 *전체 latency = retrieve + llm + 직렬화* 로 병목을 쪼갤 수 있어야 합니다. 단일 `chat_latency` 만 있으면 *어디가 느린가* 를 추적 불가. Histogram 의 bucket 은 prometheus_client 기본값 (0.005 ~ 10 초) 사용.

**Counter status 라벨의 활용**: `rag_chat_total{status="ok"}` 와 `rag_chat_total{status="error"}` 의 비율로 **error rate** 알람 가능 — Day 8 에서 Alertmanager 활성화 시 5% 초과 시 슬랙 알림.

### 6.2 vLLM 메트릭 6 종

[`course/phase-4-ml-on-k8s/03-vllm-llm-serving/lesson.md`](../phase-4-ml-on-k8s/03-vllm-llm-serving/lesson.md) §1-6 의 메트릭들이 ServiceMonitor 24 를 통해 그대로 수집됩니다. 별도 코드 변경 없음.

| 메트릭명 | 타입 | 의미 | Day 8 활용 |
|---|---|---|---|
| `vllm:num_requests_running` | Gauge | 현재 GPU 에서 동시 처리 중인 요청 수 (continuous batching 효과) | **HPA 기준 1 순위** — prometheus-adapter 로 `pods/vllm_running_requests` 노출 |
| `vllm:num_requests_waiting` | Gauge | KV cache 부족으로 대기 중인 요청 수 | 0 이 아니면 *GPU 메모리 한계* — `--gpu-memory-utilization` 또는 `--max-model-len` 튜닝 신호 |
| `vllm:gpu_cache_usage_perc` | Gauge | KV cache 사용률 (0.0 ~ 1.0) | 0.9 넘으면 max-model-len 축소 검토 |
| `vllm:time_to_first_token_seconds` | Histogram | TTFT — *사용자 체감 latency* 의 핵심 | 스트리밍 도입(§11) 시 가장 중요해지는 지표 |
| `vllm:e2e_request_latency_seconds` | Histogram | 요청 전체 latency 분포 | RAG API 의 `rag_llm_latency_seconds` 와 비교해 *네트워크 오버헤드* 추적 |
| `vllm:generation_tokens_total` | Counter | 누적 생성 토큰 수 | RPS 와 함께 보면 *토큰/sec* — 비용 추적 (\$/1M tokens) |

**왜 `vllm:num_requests_running` 이 HPA 의 1 순위인가** — vLLM 의 continuous batching 은 *Pod 내부에서 동시 요청을 함께 처리* 합니다. CPU 사용률은 GPU 가 떠받쳐 거의 변하지 않고, Memory 도 KV cache 가 *모델 가중치 + 전체* 라 단순 임계값으로 의미 없음. Day 8 §7 에서 *왜 CPU 가 부적절한가* 를 정식 다룹니다.

### 6.3 Qdrant 메트릭 (본 Day 미적용)

캡스톤 매니페스트 11-qdrant-service.yaml 에 named port 가 없어 본 Day 의 ServiceMonitor 35 작성을 *생략* 했습니다 (§4.9 결정 박스 ③). Qdrant 가 노출하는 메트릭 ([Qdrant 공식 문서](https://qdrant.tech/documentation/guides/monitoring/)):

| 메트릭명 | 타입 | 의미 |
|---|---|---|
| `qdrant_collections_total` | Gauge | 컬렉션 수 — 본 캡스톤은 1 (`rag-docs`) |
| `qdrant_search_total` | Counter | 누적 검색 호출 수 |
| `app_info` | Gauge | 버전 / 빌드 정보 |

Day 10 Helm 차트의 `templates/monitoring.yaml` 에서 vllm/rag-api/qdrant 3 종 ServiceMonitor 가 *통합 차트의 한 part* 로 정식 도입됩니다.

### 6.4 GPU 메트릭 (DCGM exporter)

NVIDIA DCGM exporter 를 별도 DaemonSet 으로 설치하면 GPU 노드의 다음 메트릭이 자동 수집됩니다 ([Phase 4-1 GPU 토픽](../phase-4-ml-on-k8s/01-gpu-scheduling/lesson.md) 인용):

| 메트릭명 | 의미 | 본 캡스톤 활용 |
|---|---|---|
| `DCGM_FI_DEV_GPU_UTIL` | GPU 사용률 (%) | vLLM Pod 가 GPU 를 *얼마나 채우는가* — 부하 부족 시 30% 미만 |
| `DCGM_FI_DEV_FB_USED` | Frame Buffer (VRAM) 사용량 (MiB) | T4 16GB 중 *얼마나 사용 중인가* — `--gpu-memory-utilization=0.9` 결정의 검증 |
| `DCGM_FI_DEV_POWER_USAGE` | 전력 사용량 (W) | 비용 / 효율 추적 |

본 캡스톤은 GKE 의 GPU 모니터링 자동 통합(Cloud Monitoring) 을 그대로 사용하고, 별도 DCGM exporter 매니페스트는 작성하지 않습니다. 학습자가 셀프 호스팅 클러스터로 옮길 때는 [NVIDIA DCGM Exporter Helm chart](https://github.com/NVIDIA/dcgm-exporter) 한 줄 설치.

> 📊 **요약 — 본 캡스톤의 모니터링 깊이**
>
> 4 축 메트릭 중 **본 lab 에서 검증** 하는 것은 RAG API 4 종 + vLLM 6 종 = 10 메트릭. Qdrant 는 부록, GPU 는 GKE 자동 통합으로 위임. Day 8 에서 이 10 메트릭 중 4 개를 Grafana 대시보드 4 패널 + HPA 2 개(vllm, rag-api) 로 구성합니다.
>
> **Day 8 실제 패널 4 종 (capstone-plan §7 의 초안 변경)**:
> ① `/chat` 요청량 (req/s, status별) — `rag_chat_total` Counter rate
> ② `/chat` 응답 latency p95 단계별 분해 (chat / retrieve / llm 3 종 Histogram)
> ③ vLLM 동시 요청 수 (running vs waiting) — Gauge 2 종
> ④ vLLM GPU KV cache 사용률 — `gpu_cache_usage_perc` Gauge
>
> > 💡 capstone-plan §7 Day 8 초안의 *retriever hit-ratio* 패널은 main.py 에 메트릭 부재라 §6.1 의 4 메트릭 단계별 분해(②번 패널) 로 교체 — 코드 변경 0, 이미 노출 중인 메트릭만 시각화. *GPU 메모리* 는 KV cache 사용률(④번)로 동등 시각화. 추가 패널 후보(스트리밍 TTFT, 토큰/sec 비용 추적, retrieval 점수 분포) 는 §11 확장 아이디어로.

---

## 7. HPA 커스텀 메트릭

Day 7 의 ServiceMonitor 가 *수집* 한 메트릭이 Day 8 의 자동 스케일링 *입력* 으로 흘러들어가는 구간을 정리합니다. 본 절은 ML 워크로드의 핵심 학습 포인트인 **"왜 CPU 기반 HPA 가 vLLM 에 부적절한가"** 를 prometheus-adapter + 커스텀 메트릭 흐름으로 설명합니다.

### 7.1 왜 CPU 가 아니라 `vllm:num_requests_running` 인가

쿠버네티스 기본 HPA 는 `metrics.k8s.io` (metrics-server) 가 노출하는 CPU/Memory 기반입니다. ML 서빙 워크로드 — 특히 vLLM 같은 LLM 서버 — 는 이 기본 메트릭이 *부적절* 합니다.

| 신호 | vLLM Pod 의 실제 동작 | 결론 |
|---|---|---|
| CPU 사용률 | 추론은 GPU 가 떠받쳐 CPU 는 거의 *항상 5~15%* — 1 RPS 든 100 RPS 든 큰 변동 없음 | CPU 기준 HPA 는 *부하 증가를 감지하지 못함* |
| Memory 사용률 | 모델 가중치 + KV cache 가 *기동 직후 90% 채움* — 이후 변동 없음 | Memory 기준 HPA 는 *항상 임계 초과 또는 항상 미달* |
| `vllm:num_requests_running` | 0 (idle) ~ 8~16 (정상) ~ 16+ (KV cache 한계) — continuous batching 의 *직접 신호* | HPA 의 1 순위 신호 |

vLLM 의 [continuous batching](../phase-4-ml-on-k8s/03-vllm-llm-serving/lesson.md) 은 *Pod 내부에서 동시 요청을 함께 처리* 합니다 (PagedAttention). GPU 1 장이 8~16 개 요청을 동시에 처리하므로 *Pod 단위 CPU* 는 의미가 없고, *동시 처리 요청 수* 가 부하의 본질입니다.

> 💡 **Phase 3-03 와의 연결** — Phase 3 에서 다룬 [Resource HPA (CPU 기반)](../phase-3-production/03-autoscaling-hpa/lesson.md) 는 일반 웹 서버 / sentiment-api 같은 *CPU bound* 워크로드에 적합합니다. ML 서빙은 대부분 GPU bound 라 *외부 메트릭* 이 필요 — `custom.metrics.k8s.io` 에 prometheus-adapter 가 자리 잡는 이유.

### 7.2 prometheus-adapter 의 4 단계 흐름

Prometheus 시계열을 K8s HPA 가 직접 소비할 수 있도록 변환하는 어댑터의 동작:

```
[1] Prometheus  →  [2] adapter rules  →  [3] custom.metrics.k8s.io API  →  [4] HPA
   (시계열 저장)        (PromQL 변환)            (K8s API 노출)             (Pod 수 조정)

[1] vllm:num_requests_running{namespace="rag-llm",pod="vllm-xxx"} = 8
        ↓
[2] rules.custom (60-prometheus-adapter-values.yaml):
      seriesQuery   : 'vllm:num_requests_running{namespace!="",pod!=""}'
      name.matches  : "^vllm:(.*)$"     ← 콜론 → 언더스코어 별칭
      name.as       : "vllm_${1}"        ← vllm_num_requests_running
      metricsQuery  : avg(<<.Series>>{<<.LabelMatchers>>}) by (<<.GroupBy>>)
        ↓
[3] kubectl get --raw "/apis/custom.metrics.k8s.io/v1beta1/namespaces/rag-llm/pods/*/vllm_num_requests_running"
      → { "value": "8", "timestamp": "..." }
        ↓
[4] HPA 25 (25-vllm-hpa.yaml):
      spec.metrics: [{ type: Pods, pods: { metric: { name: vllm_num_requests_running },
                                            target: { type: AverageValue, averageValue: "8" } }}]
      → desiredReplicas = ceil(currentReplicas × currentValue / targetValue)
                        = ceil(1 × 8 / 8) = 1   (idle 상태 유지)
                        = ceil(1 × 16 / 8) = 2  (부하 증가 → scale-out)
```

**각 단계의 책임 분리** — 학습자가 트러블슈팅 시 어느 계층이 문제인지 빠르게 격리할 수 있습니다.

| 단계 | 검증 명령 | 실패 시 진단 |
|---|---|---|
| [1] Prometheus 수집 | Prometheus UI Targets 페이지 UP 상태 | Day 7 ServiceMonitor 회귀 — `release: prom` 라벨 누락 (자주 하는 실수 #19) |
| [2] adapter 변환 | `kubectl logs deploy/prometheus-adapter -n monitoring` | Prometheus URL 오타 / rules.custom 의 PromQL syntax 오류 |
| [3] API 노출 | `kubectl get --raw "/apis/custom.metrics.k8s.io/v1beta1" \| jq '.resources[].name'` | 메트릭 리스트에 부재 → resources.overrides 매핑 실패 |
| [4] HPA 적용 | `kubectl get hpa -n rag-llm` | TARGETS 가 `<unknown>` → API path 매칭 실패 또는 selector 라벨 매칭 실패 |

### 7.3 매니페스트 해설 — 25-vllm-hpa.yaml + 35-rag-api-hpa.yaml

본 Day 의 매니페스트 4 종 위치:

| 매니페스트 | 역할 |
|---|---|
| [`manifests/25-vllm-hpa.yaml`](manifests/25-vllm-hpa.yaml) | vLLM HPA — Pods 메트릭 `vllm_num_requests_running` (averageValue=8) |
| [`manifests/35-rag-api-hpa.yaml`](manifests/35-rag-api-hpa.yaml) | RAG API HPA — Pods 메트릭 `rag_chat_requests_per_second` (averageValue=10) |
| [`manifests/60-prometheus-adapter-values.yaml`](manifests/60-prometheus-adapter-values.yaml) | adapter Helm values — rules.custom 2 규칙 (RAG Counter rate, vLLM Gauge 별칭) |
| [`manifests/61-grafana-rag-dashboard.yaml`](manifests/61-grafana-rag-dashboard.yaml) | Grafana 대시보드 ConfigMap — sidecar 자동 import (4 패널) |

#### 핵심 발췌 1 — vLLM HPA 의 Pods 메트릭

```yaml
# 25-vllm-hpa.yaml 발췌
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment                         # ⚠ ReplicaSet 이 아닌 Deployment 지정 (자주 하는 실수 #23)
    name: vllm
  minReplicas: 1
  maxReplicas: 2                             # 학습 포인트 — T4 노드 풀 1 대 환경에서 두 번째는 Pending
  metrics:
    - type: Pods
      pods:
        metric:
          name: vllm_num_requests_running    # adapter 의 name.as 변환 결과 (콜론 제거)
        target:
          type: AverageValue                 # Pods 타입은 AverageValue 만 가능
          averageValue: "8"                  # Pod 당 평균 8 도달 시 scale-out
```

#### 핵심 발췌 2 — RAG API HPA 의 Counter rate 변환

```yaml
# 35-rag-api-hpa.yaml 발췌
metrics:
  - type: Pods
    pods:
      metric:
        # Counter rag_chat_total → adapter 가 rate(2m) 으로 변환 → rag_chat_requests_per_second
        name: rag_chat_requests_per_second
      target:
        type: AverageValue
        averageValue: "10"                   # Pod 당 평균 10 RPS 도달 시 scale-out
```

#### 핵심 발췌 3 — adapter rules.custom 2 규칙

```yaml
# 60-prometheus-adapter-values.yaml 발췌 (전체는 매니페스트 파일 참조)
rules:
  default: false                             # 기본 rule 비활성 — 명시 규칙만 사용
  custom:
    # 규칙 1: Counter → req/s (rate 변환 필요)
    - seriesQuery: 'rag_chat_total{namespace!="",pod!=""}'
      name: { matches: "^(.*)_total$", as: "${1}_requests_per_second" }
      metricsQuery: 'sum(rate(<<.Series>>{<<.LabelMatchers>>}[2m])) by (<<.GroupBy>>)'

    # 규칙 2: Gauge → 별칭만 (rate 불필요, 콜론 제거)
    - seriesQuery: 'vllm:num_requests_running{namespace!="",pod!=""}'
      name: { matches: "^vllm:(.*)$", as: "vllm_${1}" }
      metricsQuery: 'avg(<<.Series>>{<<.LabelMatchers>>}) by (<<.GroupBy>>)'
```

#### 핵심 발췌 4 — behavior 의 비대칭

```yaml
# 25/35 공통
behavior:
  scaleUp:
    stabilizationWindowSeconds: 0            # 즉시 — cold start 보호 (vLLM 30~60s, RAG API 20~30s)
    policies: [{ type: Percent, value: 100, periodSeconds: 60 }]
  scaleDown:
    stabilizationWindowSeconds: 300          # 5 분 — 부하 패턴 짧을 때 Pod 유지 (떨림 방지)
    policies: [{ type: Pods, value: 1, periodSeconds: 60 }]
```

#### 결정 박스 ① — vLLM HPA 메트릭으로 `num_requests_running` 단일 채택

3 옵션 비교 (`docs/architecture.md` §3.13.1 상세):

| 옵션 | 정상값 | 임계 설정 난이도 | 채택 |
|---|---|---|---|
| **(A) num_requests_running** ✅ | 0~16 | 쉬움 (averageValue=8) | Day 8 |
| (B) running + waiting | running 0~8 + waiting 0 | 중 (waiting 임계 0 → noise) | (미채택) |
| (C) gpu_cache_usage_perc | 0.0~0.95 | 어려움 (정상도 0.95 부근) | (미채택) |

continuous batching 의 본질이 *동시 처리 요청 수* — ML 엔지니어가 vLLM 운영을 이해하는 핵심 학습 가치.

#### 결정 박스 ② — RAG API Counter → rate 변환

`rag_chat_total` 은 Counter (단조 증가) 라 그대로 HPA 입력으로 쓸 수 없습니다. adapter 의 `name.matches: "^(.*)_total$"` + `metricsQuery: rate(...)` 로 RPS 환산. averageValue=10 산정은 Day 7 측정 1 Pod 처리량 약 12 RPS 의 80% 안전선 (`docs/architecture.md` §3.13.2).

> 왜 vLLM 만 HPA 두면 안 되는가 — 부하 시 RAG API 가 *큐잉* 으로 vLLM 까지 트래픽이 도달하지 못해 `vllm:num_requests_running` 이 변동하지 않습니다 → vLLM HPA 발동 안 함. RAG API HPA 가 *프론트* 에서 트래픽을 받아내야 vLLM HPA 가 *백엔드* 의 부하를 본다는 인과 관계.

#### 결정 박스 ③ — behavior 의 비대칭 (scaleUp 0s, scaleDown 300s)

Cold start 보호 vs 떨림 방지 (`docs/architecture.md` §3.13.3):
- scaleUp 0s — RAG API 20~30s + vLLM 30~60s cold start 가 길어 *지연 없이* 트리거
- scaleDown 300s — hey 60s 부하 종료 직후 Pod 회수 시 다음 부하에서 또 cold start, 5 분 stabilization 으로 재사용

운영 환경: 트래픽이 burst 패턴 (15 분 간격 5 분 부하) 일 때 scaleDown 5 분이면 Pod 유지율 100%.

#### 결정 박스 ④ — vLLM maxReplicas=2 의 노드 풀 제약 학습

T4 노드 풀 1 대 → vLLM Pod 1 개만 schedule 가능. maxReplicas=2 두면 두 번째는 *Pending* — 이것이 학습 포인트. `kubectl describe pod vllm-2 -n rag-llm` 의 Events 에 `0/2 nodes are available: ...` 가 표시되며 운영 환경의 *노드 부족 시나리오* 를 안전하게 재현. 자주 하는 실수 #24 와 직접 연결 (`docs/architecture.md` §3.13.4).

### 7.4 검증 명령 (lab Step 4~7 과 동일 게재)

```bash
# (1) custom.metrics.k8s.io API 에 두 메트릭이 노출되는지
kubectl get --raw "/apis/custom.metrics.k8s.io/v1beta1" \
  | jq '.resources[] | select(.name | test("rag_chat|vllm_num"))'
# → "pods/rag_chat_requests_per_second", "pods/vllm_num_requests_running"

# (2) HPA TARGETS 칼럼이 <unknown> 이 아닌 실수치
kubectl get hpa -n rag-llm
# NAME      REFERENCE             TARGETS    MINPODS   MAXPODS   REPLICAS
# rag-api   Deployment/rag-api    0/10       2         6         2
# vllm      Deployment/vllm       0/8        1         2         1

# (3) hey 60s 부하 후 REPLICAS 변동
hey -z 60s -c 8 -m POST -H 'Content-Type: application/json' \
    -d '{"messages":[{"role":"user","content":"K8s에서 GPU 어떻게 잡지?"}]}' \
    http://$INGRESS/chat &
watch -n 5 kubectl get hpa,pods -n rag-llm
# → rag-api 2→4, vllm 1→2 (두 번째 Pending 정상)
```

---

## 8. Helm 으로 한 줄 배포

Day 1~9 의 21 매니페스트 + 인덱싱 코드 + RAG API 코드 + 부하 테스트 자산을 *한 줄 명령*으로 배포·롤백·정리할 수 있게 만드는 마지막 단계입니다. 본 절은 *왜 Helm 인가* 보다 *우리 캡스톤에 맞춘 차트 구조와 결정* 에 집중합니다 — Helm 자체의 학습 누적은 [Phase 3-01 Helm 차트](../phase-3-production/01-helm-chart/lesson.md) 에서 끝났습니다.

### 8.1 차트 구조 (`helm/`)

| 파일 | 역할 | raw 매니페스트 매핑 | 줄 수 |
|------|------|---------------------|------|
| `Chart.yaml` | 메타데이터 (name=capstone-rag-llm, version 0.1.0, appVersion 1.0.0) | — | 46 |
| `values.yaml` | 기본값 (7 컴포넌트 키 — namespace/qdrant/vllm/ragApi/ingress/monitoring/indexing) | — | 216 |
| `values-dev.yaml` | dev override (vllm.enabled=false + HPA off + Ingress off) | — | 53 |
| `values-prod.yaml` | prod override (GPU on + HPA on + Ingress on + Day 9 튜닝 0.90) | — | 69 |
| `templates/_helpers.tpl` | 5 named templates — name / fullname / chart / commonLabels / componentLabels | — | 105 |
| `templates/namespace.yaml` | Namespace 1 종 | 00 | 24 |
| `templates/qdrant.yaml` | StatefulSet + Headless Service | 10 + 11 | 87 |
| `templates/vllm.yaml` | Deployment + PVC + Service + Secret + ServiceMonitor + HPA | 20 + 21 + 22 + 23 + 24 + 25 | 245 |
| `templates/rag-api.yaml` | Deployment(+checksum/config) + Service + ConfigMap + Secret + ServiceMonitor + HPA | 30 + 31 + 32 + 33 + 34 + 35 | 226 |
| `templates/ingress.yaml` | GCE Ingress (host required 검증) | 40 | 46 |
| `templates/monitoring.yaml` | adapter values ConfigMap + Grafana dashboard ConfigMap | 60 + 61 | 69 |
| `templates/indexing.yaml` | Argo RBAC + CronWorkflow (Workflow 는 학습자 수동 submit) | 49 + 51 | 224 |
| `templates/NOTES.txt` | install 후 안내 (Pod Ready / Ingress IP / 비용 경고) | — | 142 |
| `dashboards/rag-llm.json` | Grafana 4 패널 JSON (`{{ .Files.Get }}` 로 monitoring.yaml 가 로드) | 61 발췌 | 193 |
| `files/prometheus-adapter-values.yaml` | adapter values 본문 (별도 helm install 입력) | 60 발췌 | 73 |

총 **15 파일 약 1818 줄** — Phase 3-01 sentiment-api 차트(약 800 줄) 의 2 배 분량은 *6 컴포넌트 통합* 의 자연스러운 결과입니다.

### 8.2 values 우선순위 4 단계 (Phase 3-01 §1-3 인용)

```
values.yaml (가장 낮음)  <  -f values-<env>.yaml  <  --set  <  --set-file
```

캡스톤 환경 분리 (Phase 3-01 패턴 계승):

| 컴포넌트 | values.yaml (기본) | values-dev.yaml | values-prod.yaml |
|----------|---------------------|-----------------|------------------|
| `vllm.enabled` | true | **false** | true |
| `vllm.gpuMemoryUtilization` | 0.85 | (무관) | **0.90** (Day 9 튜닝 결과) |
| `vllm.hpa.enabled` | false | false | **true** (min=1, max=2) |
| `vllm.serviceMonitor.enabled` | false | false | **true** |
| `ragApi.replicas` | 2 | **1** | 2 |
| `ragApi.hpa.enabled` | false | false | **true** (min=2, max=6) |
| `ragApi.serviceMonitor.enabled` | false | false | **true** |
| `ingress.enabled` | false | false | **true** |
| `monitoring.*.enabled` | false | false | **true** (2 종) |
| `indexing.cron.enabled` | true | true | true |

### 8.3 한 줄 install 명령 + 예상 출력

```bash
helm install rag-llm helm/ -n rag-llm --create-namespace \
  -f helm/values-prod.yaml \
  --set ragApi.image.repository=docker.io/<user>/rag-api \
  --set indexing.imageRepository=docker.io/<user>/rag-indexer \
  --set indexing.gitRepo=https://github.com/<user>/k8s-for-mle.git \
  --set ingress.host="placeholder.nip.io"            # Step 5 에서 진짜 IP 로 helm upgrade
```

```
NAME: rag-llm
LAST DEPLOYED: Sat May 10 16:45:00 2026
NAMESPACE: rag-llm
STATUS: deployed
REVISION: 1
TEST SUITE: None
NOTES:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎉 Capstone RAG-LLM 차트 설치가 시작되었습니다.
   release: rag-llm / namespace: rag-llm
   chart: capstone-rag-llm-0.1.0 / appVersion: 1.0.0
...
```

이후 `kubectl get pods -n rag-llm -w` 로 약 6~8 분 기다리면 6 종 Pod (qdrant-0 / vllm / rag-api×2 / + 모니터링 sidecar) 모두 Ready.

### 8.4 결정 박스 — 캡스톤 Helm 차트의 4 핵심 결정

| # | 결정 | 대안 | 채택 근거 |
|---|------|------|----------|
| ① | **컴포넌트별 7 templates** (vllm 6 매니페스트를 한 파일에) | 리소스별 14 templates (deployment.yaml / service.yaml ...) | vLLM·RAG API 가 *1 컴포넌트 = 6 매니페스트* 라 컴포넌트 응집도 우선. `{{- if .Values.vllm.enabled }}` 한 줄로 vLLM 전체 끄기 가능. capstone-plan §4.3 명세와 일치. |
| ② | **values-dev = vllm.enabled=false** (CPU fallback 본 구현 X) | dev 도 vLLM CPU 모드 / HuggingFace TGI 변경 / 미니 모델(distilbert) 대체 | CPU 모드 vLLM 는 inference 가 분 단위라 학습 가치 0. dev 의 의도는 *Helm 흐름만* (install/upgrade/rollback 사이클) 학습. RAG API /chat 503 not_ready 가 *의도된 dev 결과* — Day 7 envFrom 학습 가치 dev 에서 살림. |
| ③ | **`checksum/config` annotation 으로 ConfigMap 자동 rollout** (Day 7 결정 박스 ④ 이행) | 수동 `kubectl rollout restart` (Day 7 패턴 유지) / Reloader 외부 컨트롤러 / 코드 watcher | Day 7 = 수동 → Day 10 = 자동 *점진적 추상화*. Reloader 는 외부 의존성 추가라 캡스톤 미적용 (Phase 5 컨트롤러 패턴 학습 시 다시 등장). 자주 하는 실수 #28 → 해결 패턴이 자동화됨. |
| ④ | **kube-prometheus-stack / argo-workflows / prometheus-adapter 의존 차트 미포함** | `Chart.yaml dependencies:` 에 3 개 의존 추가 | ① 세 의존이 모두 *클러스터 단일 인스턴스* 라 캡스톤 release 마다 새로 설치되면 충돌 ② install/upgrade 사이클 30 초 → 5 분+ 로 학습 가치 감소 ③ Phase 3-01 의 *Phase 2 매니페스트 패키징* 패턴 계승 — 본 차트는 *RAG-LLM 시스템 자체* 만 패키징. NOTES.txt 가 별도 설치 명령 안내. |

### 8.5 라이프사이클 4 명령 (Phase 3-01 lab Step 6~8 인용)

```bash
# install / upgrade / rollback / uninstall
helm install rag-llm helm/ -n rag-llm --create-namespace -f helm/values-prod.yaml ...

# values 변경 — `--set ragApi.config.topK=5` → ConfigMap 변경 → checksum/config 갱신 → Pod rollout 자동
helm upgrade rag-llm helm/ -n rag-llm -f helm/values-prod.yaml --set ragApi.config.topK=5

# revision 비교 (helm template --revision 또는 `helm get manifest --revision`)
helm history rag-llm -n rag-llm
helm rollback rag-llm 1 -n rag-llm                  # 직전 revision 으로 복원

# 정리 (PVC 는 데이터 보호 목적으로 남음 — 명시적 삭제 별도)
helm uninstall rag-llm -n rag-llm
kubectl get pvc -n rag-llm                          # qdrant-storage-qdrant-0, vllm-model-cache 잔존
kubectl delete pvc -n rag-llm --all                 # 학습 종료 시
```

---

## 9. 검증 시나리오

캡스톤 완료 = `helm install` 한 줄 → §1~§6 6 단계가 모두 통과. 각 단계는 [labs/day-10-helm-integration-cleanup.md](labs/day-10-helm-integration-cleanup.md) 의 검증 체크리스트와 1:1 매핑.

```bash
# §0. 사전: 모든 Pod Running (~6~8 분 기다림)
kubectl get all -n rag-llm

# §1. 인덱싱 Workflow Succeeded
argo submit -n rag-llm --serviceaccount workflow --from cronwf/rag-indexing-daily
kubectl get wf -n rag-llm
# → STATUS=Succeeded (5 step 완료, ~3~5 분), points_count > 0

# §2. vLLM /v1/models 응답
kubectl port-forward -n rag-llm svc/vllm 8000:8000 &
curl http://localhost:8000/v1/models | jq '.data[0].id'
# → "microsoft/phi-2"

# §3. RAG end-to-end (1 줄 완료 기준)
INGRESS=$(kubectl get ing -n rag-llm rag-api -o jsonpath='{.spec.rules[0].host}')
curl http://$INGRESS/chat \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"K8s에서 GPU 어떻게 잡지?"}],"top_k":3}' | jq
# → 200 OK, answer 텍스트, sources 3 개 (인용 마커 [1]/[2]/[3])

# §4. HPA REPLICAS 변동 (Day 9 부하 스크립트 재사용)
LABEL=integration-check INGRESS_HOST=$INGRESS bash practice/llm_serving/load_test.sh
watch kubectl get hpa,pods -n rag-llm
# → rag-api HPA: 2→4 REPLICAS, vllm HPA: TARGETS 변동 (maxReplicas=2 학습 설계상 1 유지 가능)

# §5. Helm 한 줄 재배포
helm uninstall rag-llm -n rag-llm
helm install rag-llm helm/ -n rag-llm --create-namespace \
  -f helm/values-prod.yaml \
  --set ragApi.image.repository=docker.io/<user>/rag-api \
  --set indexing.imageRepository=docker.io/<user>/rag-indexer \
  --set indexing.gitRepo=https://github.com/<user>/k8s-for-mle.git \
  --set ingress.host=$INGRESS
# → 6~8 분 후 §1~§4 동일 검증 통과

# §6. GKE 클러스터 삭제 (필수)
kubectl delete namespace rag-llm
gcloud container clusters delete capstone --zone us-central1-a --quiet
gcloud compute addresses list   # 잔여 0 확인
gcloud compute disks list        # 잔여 0 확인
```

> 🚨 **GKE 비용 경고** — T4 GPU 노드 시간당 약 $0.35 + GCE Ingress 시간당 약 $0.025 + LoadBalancer External IP 시간당 약 $0.005 = 일 약 $9 누적. 캡스톤 종료 시 §6 의 `gcloud container clusters delete` 가 *필수*. 잔여 자원(External IP / Disks / LoadBalancer) 도 GCP Console 에서 직접 확인. 자세한 비용 산정은 [README.md](README.md) §GKE 비용 경고 표.

---

## 10. 🚨 자주 하는 실수

<!-- 캡스톤 진행 중 발견 시 누적 추가합니다. 현재 Day 1(Qdrant/StatefulSet 3건) + Day 2(인덱싱 3건) + Day 3(Argo 3건) + Day 4(vLLM/GPU 3건) + Day 5(RAG API 3건) + Day 6(Ingress/배포 3건) + Day 7(ConfigMap/Secret/ServiceMonitor 3건) + Day 8(HPA/Grafana/adapter 3건) + Day 9(부하 테스트/튜닝 3건) + Day 10(Helm 통합/비용 관리 3건) = 30건. -->

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

**Day 5 — RAG API / 로컬 개발**

13. **e5 임베딩 모델에 `query:` prefix 누락** — Day 2 인덱싱은 `passage: ` prefix 로 들어갔는데 Day 5 검색이 raw text 면 *벡터 공간 불일치* 로 recall 이 폭락합니다 (top_k=3 인데 무관한 청크 또는 빈 리스트). 증상: `python -c "from retriever import ...; print(r.search(...))"` 가 본 코스 자료와 무관한 source 를 반환하거나, `/chat` 응답이 `(검색된 자료가 없습니다.)` 로 일관됨. **해결**: `retriever.py` 의 `_E5_QUERY_PREFIX = "query: "` 와 `_is_e5_model()` 가 살아있는지 확인. `EMBED_MODEL` 에 'e5' 가 포함되어야 prefix 가 자동 부여 (Day 2 의 `_E5_PASSAGE_PREFIX` 와 짝). 두 prefix 가 일관되어야 — Day 2/5 의 모델명을 같이 변경할 때 *둘 다* 갱신 필수. (lab 트러블슈팅 #5 와 동일.)

14. **vLLM `/v1/chat/completions` 의 `model` 필드 누락 또는 served-model-name 불일치로 422/404** — `llm_client.py` 의 `VLLMClient.chat()` 에서 `model=self.model` 인자를 빠뜨리면 OpenAI SDK 가 422, vLLM 의 `--served-model-name=microsoft/phi-2` 와 `LLM_MODEL` env 가 다르면 404 (`The model 'phi-2' does not exist`). Day 4 §4.3 결정 박스 ① + Day 4 §10 #11 와 연결되는 *후속 표면* 입니다. **해결**: `curl http://localhost:8000/v1/models | jq '.data[0].id'` 출력값을 그대로 `.env` 의 `LLM_MODEL` 에 복사. 대소문자/슬래시 정확히. 모델 교체(Day 9) 시 매니페스트 `--served-model-name` + ConfigMap `LLM_MODEL` 두 곳을 *체크리스트로* 동기화.

15. **임베딩 모델을 요청마다 재로딩 → p99 latency 폭발** — `def search(query): model = SentenceTransformer(EMBED_MODEL); return model.encode(...)` 처럼 함수 안에서 모델을 다시 만들면 첫 호출 5~10 초가 *모든 요청* 에 발생합니다. 캡스톤 운영 시 `/chat` p99 latency 가 30 초 이상 튀고 메모리도 청크 수만큼 누적. **해결**: `retriever.py` 의 `QdrantRetriever.__init__` 에서 1 회 로드 + `main.py` 의 lifespan 에서 `app.state.retriever` 보관 1 회 (Day 5 의 본 캡스톤 코드 패턴). Day 2 §10 #5 (인덱싱 시 동일 실수) 와 *같은 원인 다른 표면* — 인덱싱은 batch 시간 폭증, RAG API 는 사용자 응답 latency 폭증.

**Day 6 — Ingress / 클러스터 배포**

16. **Ingress backend 의 named port 미선언으로 502 Bad Gateway** — Day 6 의 `40-ingress.yaml` 은 `backend.service.port.name: http` 로 Service 를 참조합니다. Service 31 에서 `ports[0].name: http` 를 명시해야 GCE Ingress 가 backend 를 찾습니다. **증상**: `curl http://<IP>.nip.io/chat` 응답 502, `kubectl describe ingress rag-api -n rag-llm` 의 Events 에 `no healthy upstream` 또는 `Translation failed: Service ... has no port with name "http"`. **해결**: `kubectl get svc rag-api -n rag-llm -o jsonpath='{.spec.ports[*].name}'` 출력이 `http` 인지 확인. number(`8001`) 로 참조하려면 Ingress 의 `port.name: http` 를 `port.number: 8001` 로 변경. 본 캡스톤은 named port 를 일관 사용 (Day 7 ServiceMonitor 도 동일 키워드 참조) — Service 작성 시 `name` 빠뜨리지 않기.

17. **Docker Hub anonymous pull rate limit 으로 ImagePullBackOff** — Docker Hub 의 미인증 pull 은 IP 당 6 시간 100 회 제한입니다. 학습자가 Day 9 부하 테스트로 노드 풀 size 를 0↔2 토글하거나, replicas=2 로 두 Pod 가 다른 노드에 schedule 되면 *각 노드가* pull 을 시도해 학습 도중 갑자기 `ImagePullBackOff: 429 Too Many Requests` 가 발생합니다. **증상**: `kubectl describe pod rag-api-* -n rag-llm` 의 Events 에 `Failed to pull image ...: 429 Too Many Requests - You have reached your pull rate limit`. **해결**: ① 매니페스트의 `imagePullPolicy: IfNotPresent` 와 tag 핀(`:0.1.0`) 유지로 pull 빈도 최소화. ② 그래도 발생하면 Docker Hub 로그인 후 Secret 으로 imagePullSecret 추가 — `kubectl create secret docker-registry dockerhub --docker-username=<user> --docker-password=<token> -n rag-llm` 후 Deployment `spec.template.spec.imagePullSecrets: [{name: dockerhub}]`. ③ 장기적으로 GAR(Google Artifact Registry) 로 전환하면 GKE 가 IAM 으로 자동 인증 — Day 10 Helm 차트의 values 옵션으로 안내.

18. **GKE LoadBalancer 비용 누수 — Day 끝에 `kubectl delete ingress` 잊기** — GCE Ingress 가 자동 생성하는 forwarding rule + 외부 IP 는 시간당 약 $0.025. Day 6 → Day 10 5 일 동안 켜두면 약 $3, 학습자가 캡스톤 후 잊으면 한 달 $20+. **증상**: GCP Console > VPC network > External IP addresses 에 학습자 의도와 무관한 외부 IP 가 *In use* 상태로 남아 청구 발생. **해결**: ① 매 Day 작업 끝에 lab 정리 절차의 `kubectl delete ingress rag-api -n rag-llm` 을 *체크박스로* 운영. forwarding rule + health check + 외부 IP 가 5 분 내 자동 회수. ② Ingress 만 지우고 Deployment/Service 는 유지하면 다음 Day 작업 시 `kubectl apply -f 40-ingress.yaml` 한 줄로 재시작 (단, 새 외부 IP 가 부여되므로 nip.io host 도 다시 sed 필요). ③ Day 10 캡스톤 종료 시 `gcloud container clusters delete capstone --zone <zone>` 으로 클러스터 통째 삭제 — 모든 GCE 자원 자동 회수.

**Day 7 — ConfigMap / Secret / ServiceMonitor**

19. **ServiceMonitor 의 `release` 라벨 누락 → Targets 페이지 빈 상태** — kube-prometheus-stack 의 Prometheus CR 은 기본적으로 `serviceMonitorSelector: { matchLabels: { release: prom } }` 로 동작합니다. 매니페스트 24/34 의 `metadata.labels.release: prom` 한 줄이 빠지면 Operator 가 본 ServiceMonitor 를 *무시* — Prometheus UI Targets 페이지에 vllm/rag-api 가 등장하지 않습니다. **증상**: `curl http://localhost:9090/api/v1/targets | jq '.data.activeTargets[] | select(.labels.namespace=="rag-llm")'` 결과 빈 배열. **해결**: ① `kubectl get prometheus -n monitoring -o jsonpath='{.items[0].spec.serviceMonitorSelector}'` 로 Prometheus 가 요구하는 라벨 확인 → ② `kubectl get servicemonitor -n rag-llm -o jsonpath='{.items[*].metadata.labels}'` 출력에 동일 라벨(`release: prom`) 있는지 확인 → ③ 누락 시 매니페스트 수정 후 재apply. Helm release name 을 `prom` 이 아닌 다른 이름(`monitoring` 등) 으로 두면 라벨도 그에 맞춰 변경 필요. Phase 3-02 §1-2 인용.

20. **ConfigMap 변경 후 Pod 재시작 누락 → 옛값 그대로** — ConfigMap 의 `data` 를 수정해도 *envFrom 으로 주입된 컨테이너의 환경변수는 옛값으로 고정* 됩니다 (kubelet 은 ConfigMap 변경을 감지하지만 *컨테이너 env 갱신은 하지 않음*). **증상**: ConfigMap 의 `QDRANT_COLLECTION` 을 `rag-docs` → `rag-docs-v2` 로 바꿨는데 RAG API 가 여전히 옛 컬렉션 검색 → 응답 sources 가 옛 데이터. **해결**: ① 즉시 — `kubectl rollout restart deployment/rag-api -n rag-llm` (Day 7 lab Step 4 패턴) → ② 자동화 — Day 10 Helm 차트의 `checksum/config` annotation 이 ConfigMap sha256 을 podTemplate annotation 으로 박아 ConfigMap 변경 시 rollout 자동 트리거. ③ 외부 의존성 가능 — stakater/Reloader 컨트롤러 설치(`reloader.stakater.com/auto: true` annotation) 로 자동화 (Phase 5 컨트롤러 패턴 학습 시 다시 등장). 본 캡스톤은 학습 효과를 위해 Day 7 = 수동 / Day 10 = Helm 자동화 두 단계로 점진적 추상화.

21. **Secret 의 `data` vs `stringData` 혼동 → 깨진 토큰 주입** — Kubernetes Secret 의 두 필드 차이를 헷갈려 평문을 `data` 에 넣으면 *base64 디코딩 실패* 로 컨테이너가 깨진 토큰을 받습니다. **증상**: HF_TOKEN 을 `hf_xxxxx` 로 적었는데 Pod 가 401 Unauthorized 또는 `Invalid base64-encoded string`. **해결**: ① 평문은 항상 `stringData` — `stringData: { HF_TOKEN: hf_xxxxx }` (본 캡스톤 Secret 33 의 패턴). ② base64 인코딩된 값은 `data` — `echo -n hf_xxxxx | base64` 로 인코딩 후 `data: { HF_TOKEN: aGZfeHh4eHg= }`. ③ CLI 사용 — `kubectl create secret generic rag-api-secrets --from-literal=HF_TOKEN=hf_xxxxx -n rag-llm --dry-run=client -o yaml | kubectl apply -f -` (인코딩 자동). ④ 검증 — `kubectl get secret rag-api-secrets -n rag-llm -o jsonpath='{.data.HF_TOKEN}' | base64 -d` 로 평문 복원되는지 확인. Phase 2-01 §1-1 인용.

**Day 8 — HPA / Grafana 대시보드 / prometheus-adapter**

22. **prometheus-adapter rules.custom 의 `<<.LabelMatchers>>` template syntax 누락 → adapter Pod Ready 인데 메트릭 미노출** — Helm values 작성 시 `metricsQuery: 'rate(<<.Series>>[2m])'` 처럼 LabelMatchers 를 빠뜨리면 adapter 가 *모든 namespace 의 Pod* 메트릭을 한 번에 합산해 K8s API 가 인식하지 못합니다. **증상**: Pod 는 Running 인데 `kubectl get --raw "/apis/custom.metrics.k8s.io/v1beta1"` 결과에 메트릭이 없음. `kubectl logs deploy/prometheus-adapter -n monitoring` 에 `discovered metrics: 0` 또는 `failed to query: missing label matchers`. **해결**: 60-prometheus-adapter-values.yaml 의 `metricsQuery: 'sum(rate(<<.Series>>{<<.LabelMatchers>>}[2m])) by (<<.GroupBy>>)'` 형식을 *세 placeholder 모두* 포함하는지 확인. `<<.Series>>` (메트릭명), `<<.LabelMatchers>>` (namespace/pod 라벨 셀렉터), `<<.GroupBy>>` (자원 라벨 그룹화) 가 모두 필수. `helm upgrade prometheus-adapter ...` 로 재적용. Phase 3-03 §1-3 의 자주 하는 실수 2번 인용.

23. **HPA `scaleTargetRef.kind: ReplicaSet` 또는 잘못된 name → HPA 가 아무 일도 안 함** — 실수로 `kind: ReplicaSet` 또는 Deployment 이름을 *현재 ReplicaSet 이름* (`rag-api-7d8f9b6c5`) 으로 적으면 HPA 가 만들어지긴 하나 *제어 대상이 없어* REPLICAS 가 변동하지 않습니다. **증상**: `kubectl get hpa` 의 TARGETS 는 정상 표시되는데 부하 발사 후에도 REPLICAS 그대로. `kubectl describe hpa rag-api -n rag-llm` 의 Conditions 에 `AbleToScale=False, FailedGetScale: deployments.apps "rag-api-7d8f9b6c5" not found` 또는 ReplicaSet 의 경우 `the HPA controller was unable to get the target's current scale`. **해결**: ① `kind: Deployment` 명시 (ReplicaSet 은 Deployment 가 자동 생성/관리하는 하위 자원이라 직접 제어 금지). ② `name` 은 *Deployment 이름* (`rag-api`), 해시 suffix 없는 형태. ③ 검증 — `kubectl get deploy rag-api -n rag-llm` 결과의 NAME 이 HPA scaleTargetRef.name 과 *완전 동일* 한지 비교. StatefulSet/DaemonSet 도 동일 패턴.

24. **hey 부하 후 RAG API 는 scale 했는데 vLLM 은 그대로 → 잘못된 결론 "HPA 가 안 동작한다"** — 캡스톤의 GPU 노드 풀 size=1 환경에서 vLLM HPA maxReplicas=2 로 두면 *두 번째 Pod 가 Pending* 되고, *그 동안 첫 번째 Pod 의 num_requests_running 이 8 이하라면 scale-out 자체가 발동하지 않습니다*. 학습자가 "HPA 가 깨졌다" 로 오인할 수 있으나 *정상 동작* 입니다. **증상**: `kubectl get hpa vllm` 의 TARGETS=`5/8` (8 미만) 인데 부하는 분명 도달 중. RAG API replicas 만 2→4 로 증가, vLLM 은 1 유지. **원인 진단**: 부하가 RAG API 4 Pod 에 분산되어 *각 Pod 가 vLLM 으로 던지는 RPS* 가 절반으로 떨어짐 → vLLM 1 Pod 가 충분히 소화. 이 자체가 *시스템이 잘 설계된 결과* (vLLM 의 continuous batching). **해결**: ① 의도된 동작이라면 그대로 두고 RAG API 의 latency 증가만 관측. ② vLLM scale-out 을 강제 검증하려면 hey 의 동시 접속 수(`-c`) 를 8→32 로 증가하거나 RAG API replicas 를 minReplicas=4 로 고정해 vLLM 으로 가는 RPS 집중. ③ T4 노드 풀 size 를 2 로 확장 — `gcloud container node-pools resize gpu-pool --num-nodes=2 --cluster capstone --zone <zone>` 후 재테스트. lesson.md §7 결정 박스 ④ 와 architecture.md §3.13.4 인용.

**Day 9 — 부하 테스트 / vLLM 튜닝**

25. **`--gpu-memory-utilization` 0.95+ 설정 → KV cache OOM CrashLoop** — Phase 4-3 자주 하는 실수 3번의 캡스톤 표면. Day 9 부하 테스트 도중 학습자가 *호기심으로* 또는 *0.95 면 더 많은 동시 처리* 라고 짐작해 0.95 이상으로 patch 하면, vLLM 이 *시작 시* GPU 메모리의 95%를 사전 예약하다 모니터링 agent / NVIDIA driver / 컨테이너 런타임과 충돌해 *시작도 못 합니다*. **증상**: `kubectl get pods -n rag-llm -l app=vllm` 의 STATUS 가 `CrashLoopBackOff`, `kubectl describe pod vllm-xxxx -n rag-llm` 의 *Last State: Terminated, Reason: OOMKilled* 또는 `Init: Error`. `kubectl logs deployment/vllm -n rag-llm --previous` 에 `torch.cuda.OutOfMemoryError: CUDA out of memory` 또는 vLLM 측 `Failed to initialize the cache engine`. **해결**: ① 즉시 — `kubectl patch deployment vllm -n rag-llm --type='json' -p='[{"op":"replace","path":"/spec/template/spec/containers/0/args/2","value":"--gpu-memory-utilization=0.85"}]'` 로 0.85 로 복원. ② 가용 상향 시 0.90 까지만 (캡스톤 T4 16GB 검증 한계) — practice/llm_serving/README.md §3.1 권장값 매트릭스. ③ 그 이상 동시 처리가 필요하면 더 큰 GPU(L4 24GB / A10G 24GB) 또는 maxReplicas 와 GPU 노드 풀 size 동반 확장 (자주 하는 실수 #24 해소). Day 9 가 0.85 → 0.90 *안전 상향만* 시연하는 이유가 본 위험 — 이론은 표면화하되 lab 에서는 재현하지 않음.

26. **부하 테스트 시 chat_latency 만 보고 retrieve_latency / llm_latency 단계별 분해 누락 → 병목 컴포넌트 오진단** — Day 5 의 RAG API 가 4 메트릭(`rag_chat_latency_seconds` / `rag_retrieve_latency_seconds` / `rag_llm_latency_seconds` + `rag_chat_total`) 을 *단계별로 분해해 노출* 한 이유는 부하 테스트 시 *어느 컴포넌트가 병목인가* 를 즉시 분리하기 위함입니다. 학습자가 chat_latency p95 만 보고 "RAG API 가 느리다" 또는 "vLLM 이 느리다" 고 단정하면 잘못된 튜닝 방향을 잡습니다. **증상**: chat p95=4.5s 를 보고 RAG API replicas 를 6→10 으로 늘렸으나 변화 없음 (실제 병목은 vLLM). 또는 vLLM args 를 0.85 → 0.90 으로 올렸으나 chat p95 는 그대로 (실제 병목은 Qdrant). **해결**: ① Step 5 의 PromQL 2 종을 *항상 동시 캡처* — `histogram_quantile(0.95, sum(rate(rag_retrieve_latency_seconds_bucket[1m])) by (le))` 와 `histogram_quantile(0.95, sum(rate(rag_llm_latency_seconds_bucket[1m])) by (le))`. ② 합산 검산 — `chat_p95 ≈ retrieve_p95 + llm_p95 + 약 0.1~0.3s overhead` 가 일치하는지. ③ 외부 메트릭 교차 — `llm_p95` 가 vLLM 자체의 `vllm:e2e_request_latency_seconds` p95 와 거의 같은지. ④ 의사결정 트리 — practice/llm_serving/README.md §4.3 의 ASCII 트리를 부하 테스트 직후 *체크리스트* 로 사용. Day 8 의 4 패널 Grafana 대시보드 ② 패널이 본 분해를 시각화.

27. **hey 의 `Successful responses` (200 OK) 만 보고 timeout / 5xx 무시 → 실제 사용자 체감보다 낙관적 평가** — hey 출력의 `Summary` 섹션은 `Total: 60.01 secs` 와 `Requests/sec: 22.34` 만 보면 시스템이 잘 동작한 것처럼 보이지만, `Status code distribution` 섹션의 `[200] 1320 responses` 와 `Error distribution` 섹션의 `[40] Connection timeout` 또는 `[15] EOF` 같은 항목을 *동시* 보지 않으면 *진짜 RPS* 와 *진짜 latency* 를 잘못 산출합니다. **증상**: hey 출력의 RPS 는 22 인데 학습자가 "초당 22 명을 처리한다" 로 결론 → 운영 배포 후 사용자의 5%가 *영원히 응답을 못 받는* (timeout) 상태. p95 latency 도 *200 OK 응답들 사이의 p95* 라서 timeout 은 latency 분포에 *포함되지 않음* — 실제 사용자 체감 p95 는 timeout 시간(보통 `--timeout` 기본 20s) 까지 포함해야 정확. **해결**: ① 결과 보고 시 *항상* `Status code distribution` + `Error distribution` 섹션을 함께 인용 — practice/llm_serving/load_test.sh 의 한 줄 요약에 `200_ok=N` 으로 카운트 노출. ② SLO 정의를 *200 OK 의 p95 + 99% availability* 두 축으로 — 캡스톤 RAG SLO 예시: chat p95 < 3s 이면서 200 OK 비율 > 99%. ③ hey 의 `-t` 옵션으로 timeout 명시 (`-t 30` = 30s 타임아웃) 후 `Error distribution` 행 수 확인. ④ Grafana 패널 ① (chat req/s status별) 의 *200 vs 5xx 색상 분리* 를 부하 도중 실시간 관찰. Day 9 c=32 단계가 본 위험을 직접 시연 — 일부 timeout 이 *의도된 결과* 임을 학습자가 인지해야 자주 하는 실수 #3 트러블슈팅과 일관.

**Day 10 — Helm 통합 / 비용 관리**

28. **Helm 차트로 ConfigMap 변경했는데 Pod rollout 안 됨 → 옛 env 그대로** — `helm upgrade --set ragApi.config.topK=5` 했는데 RAG API 가 여전히 topK=3 으로 동작합니다. 원인은 Day 7 자주 하는 실수 #20 의 *재발* — Helm 이 ConfigMap 의 `data` 만 갱신하고 *Deployment 의 podTemplate 은 변경하지 않아* 기존 Pod 가 재시작되지 않기 때문입니다. **증상**: `helm upgrade` 출력은 `STATUS: deployed REVISION: 2` 정상인데 `kubectl get pods -n rag-llm` 의 RESTARTS=0, AGE 도 그대로. `kubectl exec deploy/rag-api -- env | grep TOP_K` 출력 = 3 (옛값). **해결**: ① 본 캡스톤 차트는 `templates/rag-api.yaml` Deployment 의 podTemplate annotation 에 `checksum/config: {{ include "..." . | sha256sum }}` 한 줄로 자동화 — ConfigMap 매니페스트 sha256 변경 시 annotation 변경 → podTemplate hash 변경 → 자동 rollout. ② annotation 누락된 학습자 차트라면 — `kubectl describe deployment rag-api -n rag-llm | grep checksum` 으로 부재 확인 → `templates/rag-api.yaml` 에 한 줄 추가. ③ Helm 외 — `kubectl rollout restart deployment/rag-api -n rag-llm` 즉시 트리거. ④ Reloader 외부 의존성 — `reloader.stakater.com/auto: true` annotation 만으로 자동화 (Phase 5 컨트롤러 패턴). 본 캡스톤 결정은 ① 자동화 (lesson.md §8.4 결정 박스 ③).
29. **`--set ingress.host=` 누락 또는 LoadBalancer IP 미갱신 → install 실패 또는 Ingress 응답 없음** — `templates/ingress.yaml` 의 `{{- if not .Values.ingress.host }}{{- fail "..." }}{{- end }}` 가 빈 host 의 install 을 차단합니다. **증상 A** (install 차단): `helm install ... -f helm/values-prod.yaml` 명령이 `Error: ingress.host required` 로 즉시 실패. **증상 B** (host 갱신 누락): install 직후에는 `--set ingress.host="placeholder.nip.io"` 로 통과하지만, LoadBalancer IP 받은 후 host 를 갱신하지 않아 `curl http://placeholder.nip.io/chat` → DNS resolution failure. **해결**: ① 첫 install 은 placeholder host 로 — `--set ingress.host="placeholder.nip.io"`. ② Ingress IP 받은 후 (`kubectl get ing rag-api -n rag-llm -w` 의 ADDRESS 컬럼이 IP 로 채워질 때까지 ~3~5 분) 갱신 — `helm upgrade rag-llm helm/ -n rag-llm -f helm/values-prod.yaml --set ingress.host=$EXTERNAL_IP.nip.io --reuse-values`. ③ `--reuse-values` 누락 시 다른 `--set` 변수(image.repository 등) 가 모두 values.yaml 기본값으로 reset 되므로 *반드시* 함께 사용 — 이는 Helm 이 *upgrade 마다 values 를 새로 계산* 하는 동작에서 비롯되는 자주 하는 실수의 자주 하는 실수.
30. **GKE 클러스터/노드 풀 미삭제로 비용 누수** — Day 6 자주 하는 실수 #18 (Ingress 비용) 의 *클러스터 단위 확장*. 캡스톤 종료 시 `helm uninstall` 만 실행하고 GKE 클러스터를 살려두면, *T4 GPU 노드 풀의 시간당 $0.35 + cluster management $0.10 + LoadBalancer/External IP $0.025+/시간* 이 *학습자가 잊고 있는 동안* 누적됩니다. 한 달이면 $250+ 비용. **증상**: 캡스톤 종료 후 1 주 후 GCP 결제 알림 → "예상치 못한 \$60 청구". `gcloud container clusters list` 출력에 `capstone us-central1-a RUNNING` 표시. **해결**: ① 매 Day 작업 끝에 *최소* `gcloud container node-pools resize gpu-pool --num-nodes=0 --cluster capstone --zone <zone>` 으로 GPU 노드 0 으로 축소 (T4 비용만 정지, cluster management $0.10/h 는 유지). ② 캡스톤 종료 시 *반드시* `gcloud container clusters delete capstone --zone us-central1-a --quiet`. ③ 잔여 자원 점검 4 종 — `gcloud compute addresses list` (Reserved External IP) / `gcloud compute disks list` (PVC 의 영속 디스크) / `gcloud compute forwarding-rules list` (LoadBalancer) / `gcloud compute target-pools list` 모두 빈 결과여야 함. ④ GCP 결제 알림 budget 설정 — 캡스톤 시작 전 `Cloud Billing > Budgets` 에서 \$50 budget + 50% 알림 설정으로 비용 누수 조기 발견. ⑤ 학습 환경에선 *클러스터 자동 삭제 cron* 도 가능 — `cloud-functions-cron` 으로 24h 후 자동 삭제. 본 캡스톤 [labs/day-10-helm-integration-cleanup.md](labs/day-10-helm-integration-cleanup.md) Step 10 이 ②~③ 을 체크박스로 강제.

---

## 11. 확장 아이디어

본 캡스톤을 *5 가지 방향* 으로 확장할 수 있습니다. 각 항목은 *어떤 메트릭이 개선되는가* + *어떤 기존 결정과 충돌하는가* 로 트레이드오프를 명시합니다.

### ① reranker 도입 (cross-encoder)

- **무엇**: retriever top_k=10 으로 후보 확장 → cross-encoder (`BAAI/bge-reranker-v2-m3` 등) 로 rerank → top 3 만 LLM context 로 전달.
- **개선**: source precision 향상 (특히 한국어 자료 특수성). 답변의 인용 마커 정확도 ↑.
- **충돌**: latency +500~1000ms (cross-encoder 1 회 forward). Day 9 부하 테스트의 chat p95 = 3s 가 4s 로 증가 가능 → HPA 임계값 재조정 필요.
- **구현 위치**: `practice/rag_app/retriever.py` 의 `QdrantRetriever.search()` 출력에 `_rerank()` 메서드 추가. Day 7 ConfigMap 32 에 `RERANKER_MODEL` env 추가.

### ② 스트리밍 응답 (vLLM `stream=true` + FastAPI SSE)

- **무엇**: vLLM `/v1/chat/completions` 의 `stream=true` 활성 → FastAPI 가 Server-Sent Events 로 토큰을 *생성 즉시* 클라이언트에게 전송.
- **개선**: 사용자 체감 latency 단축 (전체 응답 5s → 첫 토큰 0.5s + 마지막 토큰 5s). UX 만족도 ↑.
- **충돌**: Day 5 의 `rag_chat_latency_seconds` 메트릭 의미 변화 — *전체 응답 완료* 시간이 아닌 *연결 종료* 시간이 됨. SLO 정의 재고. 인용 마커 [n] 의 *부분 출력* 처리 (앞 토큰만 보고 마커 분석 어려움).
- **구현 위치**: `main.py` 의 `chat()` → `StreamingResponse` 변경. `llm_client.py` 의 `chat()` → AsyncGenerator 반환. 메트릭 분리 — `rag_chat_first_token_seconds` + `rag_chat_total_duration_seconds` 두 종.

### ③ 멀티턴 대화 (대화 이력 압축)

- **무엇**: 클라이언트 → `/chat` 호출 시 `messages: [user_1, assistant_1, user_2, ...]` 전체 이력 전달 → 서버는 직전 N 턴만 유지하고 그 이전은 *요약 압축*.
- **개선**: 사용자 follow-up 질문이 자연스럽게 동작 ("그럼 위에서 말한 GPU 잡는 방법 더 자세히").
- **충돌**: phi-2 max_model_len=2048 한계 → 5~6 턴 후 context 포화 → 압축 LLM 호출 추가 latency. Phase 5 *컨트롤러 패턴 학습* 후 (메타 LLM 호출은 캡스톤 범위 초과).
- **구현 위치**: `prompts.py` 의 `build_messages()` → 히스토리 입력 받는 시그니처 변경. `main.py` 의 ChatRequest Pydantic → `messages: list[Message]` 자유 길이. 압축 메서드는 별도 `summarizer.py` 신규 모듈.

### ④ RAGAS 평가 자동화 (faithfulness / answer_relevancy / context_precision)

- **무엇**: RAGAS 라이브러리로 *질문 100 개 + 정답 + 검색 청크* 셋을 자동 채점. CronJob 으로 매일 03:30 (인덱싱 직후) 평가 → Prometheus pushgateway → Grafana 대시보드.
- **개선**: 인덱싱 품질 *수치화* — 새 lesson.md 추가 / chunk_size 변경 시 RAGAS 점수 변동을 *자동 감지*.
- **충돌**: 평가 자체에 LLM 호출 100 회 + GPT-4 같은 평가용 LLM 필요 (또는 phi-2 자체 평가의 한계). 비용 일 \$1~2 추가.
- **구현 위치**: `practice/evaluation/` 신규 디렉토리. CronJob 매니페스트 + RAGAS evaluator Python 스크립트 + 평가 데이터셋 (`questions.jsonl`).

### ⑤ vLLM scale-to-zero (KEDA + cold start 최적화)

- **무엇**: KEDA(Kubernetes Event-Driven Autoscaling) 로 vLLM Deployment 가 *첫 요청 도달까지* replicas=0 유지. 첫 요청 시 Pod 기동 → cold start 5~10 분 → 응답.
- **개선**: 야간/주말 사용 없을 때 GPU 비용 0. 본 캡스톤 prod 환경 일 비용 $9 → $0.5 (GCE Ingress + Qdrant + 클러스터 management 만).
- **충돌**: 첫 요청 사용자 *5~10 분 대기*. PVC hit 시 ~2 분으로 단축 가능하지만 여전히 사용자 체감 큼. SLA *최초 요청 응답* 보장 X.
- **구현 위치**: KEDA Helm install + ScaledObject CRD (`triggers: [{type: prometheus, query: rag_chat_total[5m]>0}]`). vLLM HPA 25 와 충돌하므로 둘 중 하나 선택. Phase 5 *비용 최적화 패턴* 학습 시 다시.

---

## 12. 다음 단계

본 캡스톤을 마쳤다면 두 갈래 중 하나로 이어갑니다.

- **Phase 5 (선택)** — Operator, Service Mesh, GitOps, 멀티 클러스터로 심화. [`docs/study-roadmap.md`](../../docs/study-roadmap.md) Phase 5 섹션 참고. 본 캡스톤 차트가 ArgoCD 의 *Application* 으로 자동 sync 되는 흐름이 다음 학습 지점.
- **자기 업무 적용** — 본인이 다루는 모델·데이터로 같은 아키텍처를 재구성합니다. 가장 큰 학습은 본 코스 자료가 아닌 **본인 문제**에 적용할 때 일어납니다. 본 차트의 *2 줄 변경* 으로 시작 — `vllm.modelName` 을 회사 모델 ID 로, `ragApi.config.embedModel` 을 회사 도메인에 맞는 임베딩 모델로.

### 캡스톤 완료 회고 체크리스트 (8 항목)

- [ ] 학습 목표 6 개 모두 *직접* 검증 — `kubectl get` 으로 매니페스트 / `curl` 로 응답 / `helm history` 로 라이프사이클
- [ ] §9 검증 시나리오 6 단계 모두 통과 (Helm 한 줄 재배포 후에도 동일)
- [ ] 자주 하는 실수 30 건 중 *직접 마주친* 항목 표시 — 학습자별 메모로 보관 (다음 K8s 작업 시 재발 방지)
- [ ] GKE 클러스터 삭제 + 잔여 자원 0 확인 (External IP / Disks / LoadBalancer / forwarding-rules)
- [ ] GCP 결제 *최종 청구액* 확인 — 캡스톤 시작 ~ 종료 사이 비용이 예산($50?) 안에 들어왔는지
- [ ] 본 차트의 *내 fork* 또는 *내 회사 repo* 에 옮긴 후 모델/데이터만 교체해 1 회 install 시도
- [ ] capstone-plan.md §10 작성 품질 체크리스트 12 항목 모두 점검 (학습자 본인 학습 자료 작성 시점에)
- [ ] Phase 5 진입 vs 자기 업무 적용 *둘 중 하나* 선택 — 다음 학습 방향을 1 줄로 적어두기

---

## Day 1~10 실습 가이드

본 lesson.md 의 내용을 직접 클러스터/로컬에서 적용해 보려면 다음 lab 들을 순서대로 진행하세요. 각 lab 은 Goal / 사전 조건 / Step / 검증 / 정리 5 단계 + 트러블슈팅 표 구조입니다.

- [`labs/day-01-namespace-qdrant.md`](labs/day-01-namespace-qdrant.md) — Namespace + Qdrant StatefulSet + Headless Service (lesson §1·§4.1·§4.2)
- [`labs/day-02-indexing-script-local.md`](labs/day-02-indexing-script-local.md) — 본 코스 자료를 로컬 Python 으로 청크/임베딩하여 Qdrant `rag-docs` 에 적재 (lesson §3.2·§4.6)
- [`labs/day-03-indexing-argo.md`](labs/day-03-indexing-argo.md) — 동일 코드를 Argo Workflow 5-step DAG (`git-clone → load-docs → chunk → embed → upsert`) 으로 패키징해 클러스터에서 실행 + CronWorkflow 로 일별 자동화 (lesson §3.3·§4.7)
- [`labs/day-04-vllm-deploy.md`](labs/day-04-vllm-deploy.md) — GKE T4 노드 풀 추가 → vLLM Deployment + Service + 모델 캐시 PVC 적용 → `curl /v1/models` + OpenAI Python SDK 로 OpenAI 호환 API 검증 (lesson §2.1·§4.3)
- [`labs/day-05-rag-api-impl.md`](labs/day-05-rag-api-impl.md) — `practice/rag_app/` 6 모듈 + 단위 테스트 작성, port-forward 2 개(Qdrant 6333 + vLLM 8000) + `uvicorn main:app --port 8001` → `curl /chat` 200 OK + sources 3 개 + `pytest tests/` 통과 (lesson §2.3·§3.1·§5)
- [`labs/day-06-rag-api-deploy.md`](labs/day-06-rag-api-deploy.md) — Docker Hub 본인 계정으로 `rag-api:0.1.0` 이미지 빌드/푸시 + Deployment(replicas=2) + Service + GCE Ingress 적용 → 외부 IP 부여 + nip.io host → `/chat` end-to-end 200 OK (lesson §3.1 Day 6 보강·§4.4·§4.5)
- [`labs/day-07-config-secret-monitoring.md`](labs/day-07-config-secret-monitoring.md) — env 6 종을 ConfigMap 32 + Secret 33 으로 분리 + `envFrom` 일괄 주입 리팩토링 → kube-prometheus-stack 설치 + ServiceMonitor 24/34 적용 → Prometheus Targets UP 검증 + PromQL `rate(rag_chat_total[1m])` 그래프 (lesson §4.4 결정 박스 ②·§4.8·§4.9·§6)
- [`labs/day-08-grafana-hpa.md`](labs/day-08-grafana-hpa.md) — Grafana sidecar 자동 import + prometheus-adapter Helm install + custom.metrics.k8s.io API 노출 → HPA 25/35 적용 → hey 60s 부하로 REPLICAS 변동 + 4 패널 대시보드 동시 변동 관측 (lesson §6 보강·§7)
- [`labs/day-09-load-test-tuning.md`](labs/day-09-load-test-tuning.md) — `practice/llm_serving/load_test.sh` 로 c=8/16/32 3 단계 부하 → Prometheus 5 메트릭 캡처 + RAG 단계별 분해 PromQL → vLLM args 0.85→0.90 안전 상향 1 회전 튜닝 → before/after 비교 표 5 지표 (lesson §10 #25~#27 + architecture.md §3.14)
- [`labs/day-10-helm-integration-cleanup.md`](labs/day-10-helm-integration-cleanup.md) — `helm/` 차트 한 줄 install (dev → prod) + ConfigMap 변경 → checksum/config 자동 rollout 검증 + `helm rollback` 라이프사이클 + §9 6 단계 통합 검증 + GKE 클러스터 삭제 + 잔여 자원 점검 (lesson §8·§9·§10 #28~#30)
