# 캡스톤 인덱싱 파이프라인 (`practice/pipelines/indexing`)

> **상위 lesson**: [`../../../lesson.md`](../../../lesson.md) §3.2 인덱싱 데이터 흐름, §4.6 인덱싱 파이프라인
> **상위 plan**: [`docs/capstone-plan.md`](../../../../../docs/capstone-plan.md) §4.6, §7 Day 2
> **labs**: [`../../../labs/day-02-indexing-script-local.md`](../../../labs/day-02-indexing-script-local.md)
> **이식 출처**: [`course/phase-4-ml-on-k8s/04-argo-workflows/practice/rag_pipeline/`](../../../../phase-4-ml-on-k8s/04-argo-workflows/practice/rag_pipeline/)

---

## 목적

본 코스 자료(`course/phase-*/**/lesson.md` 약 20 파일 + `docs/study-roadmap.md`) 를 청크/임베딩하여 캡스톤 Qdrant 컬렉션 `rag-docs` 에 upsert 하는 인덱싱 스크립트입니다. **자기참조형 RAG 검증**(본 코스가 본 코스를 답한다) 의 데이터 공급원이며, 아래 두 컨텍스트에서 동일 코드가 재사용됩니다.

| 컨텍스트 | 실행 방식 | 입력 위치 | Qdrant 접속 |
|---|---|---|---|
| **Day 2 (로컬)** | `python pipeline.py all` | 호스트 `course/`, `docs/` | `kubectl port-forward` → `http://localhost:6333` |
| **Day 3 (Argo)** | Workflow 4 단계 | PVC 또는 git-clone init container 로 `/docs` 마운트 | 클러스터 내부 `http://qdrant.rag-llm.svc:6333` |

코드 변경 없이 **환경변수만 바꿔** 두 컨텍스트를 모두 지원하도록 설계했습니다.

---

## 파일 구성

| 파일 | 역할 |
|---|---|
| `pipeline.py` | 4 subcommand (`load-docs / chunk / embed / upsert`) + `all` + 보조 `search` |
| `requirements.txt` | `sentence-transformers`, `qdrant-client`, `langchain-text-splitters` |
| `Dockerfile` | Day 3 Argo Workflow 용 컨테이너 이미지 |

---

## 환경변수

| 이름 | 기본값 | 설명 |
|---|---|---|
| `DOCS_ROOT` | `course` | 코스 자료 루트. `phase-*/**/lesson.md` 와 `capstone-*/lesson.md` 글로브. |
| `ROADMAP_PATH` | `docs/study-roadmap.md` | 별도 추가 인덱싱할 로드맵 파일. |
| `PIPELINE_DATA_DIR` | `./.pipeline-data` (로컬), `/data` (컨테이너) | 4 단계 사이의 JSONL 중간 산출물 디렉토리. |
| `QDRANT_URL` | `http://localhost:6333` (로컬), `http://qdrant.rag-llm.svc:6333` (컨테이너) | Qdrant HTTP 엔드포인트. |
| `QDRANT_COLLECTION` | `rag-docs` | upsert 대상 컬렉션명. |
| `EMBED_MODEL` | `intfloat/multilingual-e5-small` | sentence-transformers 모델 ID. |

---

## 실행 예 (로컬, Day 2)

> 사전: Day 1 의 Qdrant StatefulSet 이 클러스터에 떠 있어야 합니다 (`kubectl get pod qdrant-0 -n rag-llm` Running).

```bash
# 0. 가상환경 + 의존성
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r course/capstone-rag-llm-serving/practice/pipelines/indexing/requirements.txt

# 1. Qdrant 에 port-forward (백그라운드)
kubectl port-forward -n rag-llm svc/qdrant 6333:6333 &
sleep 2 && curl -s http://localhost:6333/healthz

# 2. 환경변수 (프로젝트 루트에서 실행 가정)
export DOCS_ROOT=course
export ROADMAP_PATH=docs/study-roadmap.md
export QDRANT_URL=http://localhost:6333

# 3. 4 단계 한 번에 (또는 단계별 호출)
cd course/capstone-rag-llm-serving/practice/pipelines/indexing
python pipeline.py all

# 4. 검증 (자연어 검색)
python pipeline.py search --query "쿠버네티스에서 GPU 노드는 어떻게 분리하나요?"
```

각 단계를 따로 실행하려면:

```bash
python pipeline.py load-docs                      # → .pipeline-data/docs.jsonl
python pipeline.py chunk --chunk-size 512 --chunk-overlap 64
                                                  # → .pipeline-data/chunks.jsonl
python pipeline.py embed --model intfloat/multilingual-e5-small
                                                  # → .pipeline-data/embeddings.jsonl
python pipeline.py upsert --collection rag-docs   # → Qdrant
```

---

## 결정 노트

### 왜 임베딩 모델이 `intfloat/multilingual-e5-small` 인가

본 코스 자료는 **한국어가 다수**(lesson.md 본문 + 한국어 주석 포함된 매니페스트 발췌) 입니다. 영어 전용 모델(`BAAI/bge-small-en` 등) 은 한국어 토큰을 OOV 처리에 가깝게 다뤄 retrieval recall 이 떨어집니다.

- `multilingual-e5-small` 은 **차원 384** 로 캡스톤 plan §4.6 / architecture.md §4 의 PVC 5Gi 산정값과 무수정으로 호환됩니다.
- e5 계열은 인덱싱 본문에 `passage:`, 검색 쿼리에 `query:` 접두사를 붙여야 의도된 retrieval 품질이 나옵니다. `pipeline.py` 의 `_E5_PASSAGE_PREFIX`, `_E5_QUERY_PREFIX` 상수가 자동 처리합니다.
- 다국어 품질이 더 필요해지면 `BAAI/bge-m3`(1024 dim) 로 교체할 수 있으나, 차원이 바뀌면 컬렉션을 **반드시 한 번 비워야 합니다** (`curl -X DELETE http://localhost:6333/collections/rag-docs`).

### 왜 `MarkdownHeaderTextSplitter` 를 1 차로 쓰는가

마크다운의 `#` `##` `###` 구조는 의미 단위 경계와 거의 일치합니다. 이를 무시하고 처음부터 문자 길이 기반으로 자르면 청크가 헤딩 중간에서 끊겨 retrieval 결과 페이지를 사람이 읽기 어렵습니다.

- 1 차: `MarkdownHeaderTextSplitter` 가 헤딩 단위 섹션으로 분리 + `h1/h2/h3` 메타 부여
- 2 차: 헤딩 섹션이 `chunk_size` 보다 길면 `RecursiveCharacterTextSplitter` 로 추가 분할
- 결과: 모든 청크가 `heading` 메타데이터(`Phase 4 > vLLM > startupProbe`) 를 가지며, Day 5/6 의 RAG API 가 응답에 인용 출처를 표시할 때 사람이 읽기 좋은 경로로 노출됩니다.

### 왜 `recreate_collection` 이 아니라 `create_collection_if_not_exists + upsert` 인가

Phase 4-4 원본은 `recreate_collection` 으로 **매 실행마다 컬렉션을 비우고 재생성** 했습니다. 학습 흐름상 매번 깨끗한 상태에서 시작한다는 장점은 있으나, 캡스톤 운영 시점(Day 7~10) 에는 다음 문제가 발생합니다.

- 인덱싱 도중 RAG API 가 검색하면 **빈 컬렉션을 만나** 502 가 나는 짧은 구간이 생깁니다.
- 부분 갱신(예: `phase-4` lesson 만 수정) 이 불가능합니다.
- Day 3 Argo Workflow + CronWorkflow 가 야간 재인덱싱하면 그 사이 모든 검색이 잠시 비어 보입니다.

캡스톤은 idempotent 패턴 — 컬렉션이 없으면 만들고, point ID 를 결정론적(`uuid5(NAMESPACE_URL, chunk_id)`) 으로 부여해 같은 청크는 덮어쓰기 — 을 채택합니다. 차원이 바뀌었을 때만 명시적 에러로 학습자에게 컬렉션 삭제 명령을 안내합니다.

### 청크 메타데이터 4 종을 보존하는 이유

Day 5/6 의 RAG API 가 응답에 사용할 `sources` 항목은 다음 4 가지를 그대로 노출합니다.

| 메타 | 예시 | 용도 |
|---|---|---|
| `source` | `course/phase-4-ml-on-k8s/03-vllm-llm-serving/lesson.md` | 정확한 파일 경로 (학습자가 직접 클릭) |
| `phase` | `phase-4-ml-on-k8s` | UI 에서 Phase 단위 필터링 |
| `topic` | `03-vllm-llm-serving` | 같은 Phase 내 토픽 묶음 표시 |
| `heading` | `4. 핵심 매니페스트 해설 > 4.1 vllm-deployment.yaml > startupProbe` | 청크가 속한 헤딩 경로 — 응답 출처 라벨에 사용 |

---

## Day 3 컨테이너화로 가는 변경점 (예고)

- 본 README 의 "실행 예" 의 환경변수만 바뀌고 코드는 그대로입니다.
  - `DOCS_ROOT=/docs` (PVC/init container 마운트)
  - `PIPELINE_DATA_DIR=/data` (Workflow 의 4 단계가 공유하는 PVC)
  - `QDRANT_URL=http://qdrant.rag-llm.svc:6333` (클러스터 내부 DNS)
- Argo Workflow 의 4 step 이 같은 이미지를 띄워 `args: ["load-docs"]`, `args: ["chunk"]`, ... 로 호출합니다.
- Workflow 매니페스트는 [`../../../manifests/50-indexing-workflow.yaml`](../../../manifests/50-indexing-workflow.yaml) (Day 3 작성 예정).

---

## 트러블슈팅

| 증상 | 원인 | 해결 |
|---|---|---|
| `[upsert] connection refused` | port-forward 미기동 | `kubectl port-forward -n rag-llm svc/qdrant 6333:6333 &` 후 `curl localhost:6333/healthz` |
| `[upsert] ERROR: vector size 불일치` | 모델을 다른 차원의 것으로 바꿔 재실행 | `curl -X DELETE http://localhost:6333/collections/rag-docs` 로 컬렉션 비운 뒤 재실행 |
| `[load-docs] WARNING: 0 docs found` | `DOCS_ROOT` 가 `course/` 를 가리키지 않음 | 프로젝트 루트에서 실행하거나 `export DOCS_ROOT=$(pwd)/course` |
| `[embed] OOM` (메모리 초과) | CPU 메모리 부족 | `--chunk-size 256` 로 청크를 줄이거나 `batch_size` 를 코드에서 16 으로 낮춤 |
| 한국어 검색이 영어 자료만 매칭 | e5 prefix 가 빠진 다른 모델로 변경 | 모델명에 `e5` 가 포함되면 자동 prefix. 다른 모델 사용 시 `pipeline.py` 의 `_is_e5_model` 분기 조정 필요 |
