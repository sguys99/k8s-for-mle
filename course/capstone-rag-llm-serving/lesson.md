# 캡스톤: RAG 챗봇 + LLM 서빙 종합 프로젝트

> **Phase**: Capstone — Phase 1~4 누적 통합
> **소요 기간**: 1~2주 (10일 일정)
> **선수 학습**: Phase 0 ~ Phase 4 전체 (특히 Phase 4-3 vLLM, Phase 4-4 Argo Workflows)
> **본 문서 진행 상태**: Day 1~2 작성분 (학습 목표 + §1 시스템 아키텍처 + §3.2 인덱싱 데이터 흐름 + §4.1·§4.2·§4.6 매니페스트 해설 + §10 자주 하는 실수 6건). 나머지 섹션은 Day 별로 누적 보강됩니다.

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
                                             │   │ ★ Day 1 ★   │  │ (Day 4) │  │
                                             │   │ + PVC 5Gi   │  │ + GPU   │  │
                                             │   └──────▲──────┘  └─────────┘  │
                                             │          │                      │
                                             │          │ upsert(임베딩)       │
                                             │   ┌──────┴──────────────┐       │
                                             │   │ 인덱싱 Workflow      │      │
                                             │   │ Argo Workflow(Day 3)│      │
                                             │   │ + CronWorkflow      │      │
                                             │   └─────────────────────┘      │
                                             │                                 │
                                             │   [ServiceMonitor × 3] (Day 7)  │
                                             │   [HPA × 2] (Day 8)             │
                                             └─────────────────────────────────┘
```

★ **Day 1 에서 실제로 만드는 것은 Namespace + Qdrant StatefulSet + Headless Service 3 개**입니다. 나머지 박스는 후속 Day 에 채워집니다.

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

<!-- TBD: Day 2~6 에서 누적 보강. vLLM(Day 4), RAG API(Day 5), Argo(Day 3) 결정 노트가 들어갑니다.
     현재는 docs/architecture.md §3 (Qdrant StatefulSet 결정) 만 채워져 있습니다. -->

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

<!-- TBD: Day 4 에서 작성합니다. (image, GPU resource request, startupProbe failureThreshold, served-model-name 등) -->

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

<!-- 캡스톤 진행 중 발견 시 누적 추가합니다. 현재 Day 1(Qdrant/StatefulSet 3건) + Day 2(인덱싱 3건) = 6건. -->

**Day 1 — Qdrant / StatefulSet**

1. **`serviceName` 과 Service 이름 불일치** — StatefulSet 의 `spec.serviceName` 과 Headless Service 의 `metadata.name` 이 다르면 `qdrant-0.qdrant` 안정 DNS 가 발급되지 않습니다. 두 값을 정확히 같게 두세요.
2. **PVC 자동 삭제 기대** — StatefulSet 을 `kubectl delete -f` 해도 `volumeClaimTemplates` 가 만든 PVC 는 데이터 보호 목적으로 남습니다. 정리하려면 `kubectl delete pvc qdrant-storage-qdrant-0 -n rag-llm` 을 별도로 실행해야 합니다.
3. **storageClass 누락으로 PVC Pending** — `storageClassName: standard` 가 클러스터에 없으면 PVC 가 영원히 Pending 입니다. `kubectl get sc` 로 사용 가능한 storageClass 를 확인하고 매니페스트를 교체하세요.

**Day 2 — 인덱싱 파이프라인**

4. **port-forward 미기동 상태로 스크립트 실행** — `python pipeline.py upsert` 가 `connection refused` 로 죽습니다. 인덱싱 단계는 시간이 걸리므로 `embed` 까지 다 돌고 마지막에 실패하면 매우 아깝습니다. **Step 2 직후 `curl http://localhost:6333/healthz` 로 미리 검증**하세요. 백그라운드 port-forward 가 살아 있는지는 `jobs` 또는 `lsof -i :6333` 으로 수시 확인합니다.
5. **임베딩 모델을 청크마다 재로딩** — `def embed_one(text): return SentenceTransformer(model).encode(...)` 처럼 함수 안에서 모델을 매번 만들면 청크 수만큼 모델을 다시 로드해 메모리/시간이 폭증합니다. **모델은 명령 진입 시 1 회만 로드**하고 `model.encode(texts, batch_size=32)` 로 일괄 처리하세요. `pipeline.py` 의 `cmd_embed` 가 이 패턴입니다.
6. **`recreate_collection` 으로 운영 환경에서 컬렉션 비우기** — Phase 4-4 학습용 코드는 매 실행마다 컬렉션을 비웠지만, 캡스톤 운영에서는 **인덱싱 도중 RAG API 가 빈 컬렉션을 만나 502 가 나는 짧은 구간** 이 생깁니다. 캡스톤은 `create_collection_if_not_exists + 결정론적 point ID(`uuid5`) + upsert` 패턴으로 부분 갱신을 허용합니다. 차원이 바뀌었을 때만 명시적 에러로 학습자에게 컬렉션 삭제를 요구합니다.

<!-- TBD: Day 4(vLLM cold start), Day 8(HPA 메트릭 미수집) 관련 추가 예정. -->

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

## Day 1~2 실습 가이드

본 lesson.md 의 내용을 직접 클러스터/로컬에서 적용해 보려면 다음 lab 들을 순서대로 진행하세요. 각 lab 은 Goal / 사전 조건 / Step / 검증 / 정리 5 단계 + 트러블슈팅 표 구조입니다.

- [`labs/day-01-namespace-qdrant.md`](labs/day-01-namespace-qdrant.md) — Namespace + Qdrant StatefulSet + Headless Service (lesson §1·§4.1·§4.2)
- [`labs/day-02-indexing-script-local.md`](labs/day-02-indexing-script-local.md) — 본 코스 자료를 로컬 Python 으로 청크/임베딩하여 Qdrant `rag-docs` 에 적재 (lesson §3.2·§4.6)
