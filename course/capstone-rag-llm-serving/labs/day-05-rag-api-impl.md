# Day 5 — RAG API 구현 (로컬 개발 + 단위 테스트)

> **상위 lesson**: [`../lesson.md`](../lesson.md) §2.3 RAG API 분리 4 축, §3.1 챗봇 호출 흐름, §5 RAG API 구현 노트
> **상위 plan**: [`docs/capstone-plan.md`](../../../docs/capstone-plan.md) §7 Day 5
> **상위 architecture**: [`../docs/architecture.md`](../docs/architecture.md) §1 시퀀스 정밀화, §3.9 동기 호출 흐름, §3.10 임베딩 모델 로딩 전략
> **이전 단계**: [`day-04-vllm-deploy.md`](day-04-vllm-deploy.md)
> **소요 시간**: 90 ~ 120 분 (venv + 의존성 설치 10 분, 임베딩 모델 첫 다운로드 1~2 분, 코드 단독 검증 + uvicorn + curl 30 분, pytest 5 분, 정리 5 분)

---

## 🎯 Goal

Day 5 를 마치면 다음 4 가지가 충족됩니다.

- `practice/rag_app/` 아래에 RAG API 의 6 개 모듈(`Dockerfile` / `requirements.txt` / `main.py` / `retriever.py` / `llm_client.py` / `prompts.py`) + `tests/test_retriever.py` + `.env.example` 이 작성되어, 학습자 환경에서 그대로 실행/테스트 가능
- **Terminal A** 에서 Qdrant port-forward(6333), **Terminal B** 에서 vLLM port-forward(8000), **Terminal C** 에서 `uvicorn main:app --reload --port 8001` 의 3 터미널 패턴을 익히고, 각 로그를 독립 추적
- `curl http://localhost:8001/chat -d '{"messages":[{"role":"user","content":"K8s에서 GPU 어떻게 잡지?"}],"top_k":3}'` 호출 → 200 OK + 한국어 답변 + `sources` 3 개(각 `source/phase/topic/heading/score/chunk_id`) 응답 확인
- `pytest tests/ -v` 로 retriever 단위 테스트 5+1 케이스 모두 통과 — Qdrant/vLLM 인프라 의존 없이 mock 만으로 PASS (캡스톤 §2 결정 #4)

---

## 🔧 사전 조건

- **Day 1~4 완료**: Qdrant `qdrant-0` Pod Running + Day 2/3 의 인덱싱이 적재한 `rag-docs` 컬렉션 존재 + Day 4 의 vLLM Pod Running.
  ```bash
  kubectl get pods -n rag-llm
  # → qdrant-0       1/1  Running
  # → vllm-xxxxxx    1/1  Running
  ```
  ```bash
  curl http://localhost:6333/collections/rag-docs 2>/dev/null | jq '.result.points_count'
  # → 500 ~ 800 (Day 2/3 인덱싱 결과; port-forward 가 살아있지 않으면 본 줄은 Step 3 후에 검증)
  ```
- **GKE GPU 노드 풀이 size>=1**: Day 4 종료 시 `size=0` 으로 줄였다면 본 lab 시작 전 복원합니다.
  ```bash
  gcloud container node-pools resize gpu-pool --cluster=capstone --zone=us-central1-a --num-nodes=1 --quiet
  # → 5 분 안에 vLLM Pod Running
  ```
- **로컬 도구**: `python3` (3.11+), `pip`, `kubectl`, `jq`, `curl`. 디스크 ~500MB 여유(임베딩 모델 e5-small ≈ 130MB + 파이썬 의존성).
- **HuggingFace 접근**: `intfloat/multilingual-e5-small` 은 public 이라 토큰 없이 다운로드. 사내망에서 차단되면 `HF_HOME=~/.cache/huggingface` 가 미리 채워져 있어야 합니다 (트러블슈팅 #6 참조).
- **포트 충돌 사전 확인**: 6333 / 8000 / 8001 이 다른 프로세스에 점유되지 않았는지.
  ```bash
  lsof -i :6333 -i :8000 -i :8001
  # → 비어있어야 함
  ```
- **작업 디렉토리**: 본 lab 의 모든 명령은 **`course/capstone-rag-llm-serving/practice/rag_app/`** 에서 실행합니다 (별도 안내 없으면).

> 💰 **GKE 비용 박스**
>
> Day 5 는 *로컬 개발* 이지만 vLLM Pod 가 떠 있어야 `/chat` 검증이 가능합니다 (T4 1 노드 ≈$0.35/h × 1.5h = ~$0.5).
> Day 6 으로 바로 넘어갈 예정이면 GPU 노드 풀을 그대로 두고, 휴식이 길면 Day 4 §🧹 정리 (c) 의 `--num-nodes=0` 으로 일시 축소 — 5 분 내 복원 가능.

---

## 🚀 Steps

### Step 1. venv 생성 + 디렉터리 확인

```bash
cd course/capstone-rag-llm-serving/practice/rag_app
ls
# → Dockerfile  llm_client.py  main.py  prompts.py  requirements.txt  retriever.py  tests/  .env.example

python3 -m venv .venv
source .venv/bin/activate
python --version
# → Python 3.11.x 또는 3.12.x
```

> 💡 **`source .venv/bin/activate` 가 필수인 이유** — 시스템 Python 에 `sentence-transformers` 를 설치하면 다른 프로젝트와 의존성이 충돌할 수 있습니다. venv 안에서만 격리.

### Step 2. requirements 설치

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

**예상 출력 (마지막 줄):**

```
Successfully installed openai-1.51.0 qdrant-client-1.12.0 sentence-transformers-3.1.0 fastapi-0.115.0 ...
```

설치 시간은 약 2~5 분 (sentence-transformers 가 PyTorch 의존성을 가져오기 때문 — CPU 빌드라도 ~200MB).

```bash
pip list | grep -E "(fastapi|qdrant|sentence|openai|prometheus)"
```

**예상 출력:**

```
fastapi              0.115.0
openai               1.51.0
prometheus-client    0.21.0
qdrant-client        1.12.0
sentence-transformers 3.1.0
```

### Step 3. port-forward 2 개 (분리 터미널 — vLLM 8000 + Qdrant 6333)

본 Step 만 **3 개의 터미널** 을 사용합니다. 각 터미널은 *독립 프로세스* 라 한쪽이 끊겨도 다른 쪽이 영향을 받지 않으며, 로그를 따로 볼 수 있어 디버깅이 쉽습니다.

**Terminal A — Qdrant 6333**

```bash
kubectl port-forward -n rag-llm svc/qdrant 6333:6333
# → Forwarding from 127.0.0.1:6333 -> 6333
#    Forwarding from [::1]:6333 -> 6333
```

**Terminal B — vLLM 8000**

```bash
kubectl port-forward -n rag-llm svc/vllm 8000:8000
# → Forwarding from 127.0.0.1:8000 -> 8000
#    Forwarding from [::1]:8000 -> 8000
```

**Terminal C — 본 작업** (이후 Step 모두 본 터미널에서 진행)

```bash
cd course/capstone-rag-llm-serving/practice/rag_app
source .venv/bin/activate

# 두 endpoint 가 응답하는지 한 번에 검증
curl -s http://localhost:6333/collections/rag-docs | jq '.result.points_count'
# → 500 ~ 800

curl -s http://localhost:8000/v1/models | jq '.data[0].id'
# → "microsoft/phi-2"
```

> 💡 **`&` 백그라운드 변형 (단일 터미널이 필요할 때)**
> ```bash
> kubectl port-forward -n rag-llm svc/qdrant 6333:6333 &
> kubectl port-forward -n rag-llm svc/vllm   8000:8000 &
> # 종료: pkill -f "kubectl port-forward"
> ```
> 단점은 두 로그가 같은 터미널에 섞이는 점입니다. 본 lab 은 분리 터미널 패턴을 권장하지만, 단일 터미널 운영을 선호하면 트러블슈팅 #1 의 백그라운드 변형을 참고하세요.

### Step 4. 환경변수 + retriever.py 단독 검증

```bash
cp .env.example .env
cat .env
```

**예상 출력:**

```
QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION=rag-docs
EMBED_MODEL=intfloat/multilingual-e5-small
LLM_BASE_URL=http://localhost:8000/v1
LLM_MODEL=microsoft/phi-2
TOP_K=3
```

retriever 만 단독으로 호출해 검색이 동작하는지 확인합니다 (vLLM 호출 없이).

```bash
python -c "
from retriever import QdrantRetriever
r = QdrantRetriever(
    url='http://localhost:6333',
    collection='rag-docs',
    embed_model_name='intfloat/multilingual-e5-small',
)
hits = r.search('K8s에서 GPU 어떻게 잡지', top_k=3)
for i, h in enumerate(hits, 1):
    print(f'[{i}] score={h.score:.3f}  heading={h.heading[:60]}')
    print(f'    source={h.source}')
"
```

**예상 출력 (첫 실행은 e5-small 다운로드로 1~2 분 소요):**

```
[1] score=0.834  heading=Phase 4 > vLLM > GPU 노드 격리
    source=course/phase-4-ml-on-k8s/03-vllm-llm-serving/lesson.md
[2] score=0.817  heading=Day 4 > vLLM Deployment > GPU 노드 풀 분리
    source=course/capstone-rag-llm-serving/lesson.md
[3] score=0.792  heading=Phase 4 > GPU 스케줄링
    source=course/phase-4-ml-on-k8s/01-gpu-scheduling/lesson.md
```

retrieve 가 *본 코스 자료* 를 찾아낸 것을 확인했다면, Day 2/3 의 인덱싱이 정상이고 Day 5 의 retriever 가 e5 query prefix 까지 일관되게 처리한 것입니다 (자기참조형 검증).

### Step 5. llm_client.py 단독 검증

vLLM 만 단독 호출해 OpenAI 호환 응답이 오는지 확인합니다 (retriever 없이).

```bash
python -c "
from llm_client import VLLMClient
c = VLLMClient(base_url='http://localhost:8000/v1', model='microsoft/phi-2')
ans = c.chat([
    {'role': 'system', 'content': '한국어로 답변하세요.'},
    {'role': 'user', 'content': 'Kubernetes 가 무엇입니까? 한 문장으로.'},
])
print(ans)
"
```

**예상 출력 (첫 호출은 cold cache 로 30~60 초, 이후 2~5 초):**

```
Kubernetes 는 컨테이너화된 애플리케이션을 자동으로 배포·확장·관리하는 오픈소스 오케스트레이션 플랫폼입니다.
```

### Step 6. uvicorn 으로 RAG API 기동

```bash
uvicorn main:app --reload --port 8001
```

**예상 출력 (lifespan 에서 임베딩 모델 로딩 — 두 번째 실행부터는 5~10 초):**

```
INFO:     Will watch for changes in these directories: ['.../rag_app']
INFO:     Uvicorn running on http://127.0.0.1:8001 (Press CTRL+C to quit)
INFO:     Started reloader process [12345]
INFO:     Started server process [12346]
2026-05-08 10:23:11,234 INFO rag: Loading embedding model intfloat/multilingual-e5-small and connecting to Qdrant=http://localhost:6333, vLLM=http://localhost:8000/v1
2026-05-08 10:23:13,456 INFO rag: RAG API ready
INFO:     Application startup complete.
```

> 💡 본 Step 은 백그라운드로 띄워도 무방하지만, 학습 단계에선 *포어그라운드* 로 두고 다른 터미널(Terminal D 또는 새 탭)에서 curl 을 호출하는 것이 로그를 따라가기 쉽습니다.

### Step 7. `/healthz` + `/ready` 검증

새 터미널 또는 Terminal C 의 새 탭에서:

```bash
curl http://localhost:8001/healthz
# → {"status":"ok"}

curl http://localhost:8001/ready
# → {"status":"ready"}
```

`/ready` 가 503 이면 lifespan 이 아직 초기화 중 — uvicorn 로그의 `RAG API ready` 줄을 확인 후 재시도.

### Step 8. `/chat` end-to-end 호출

```bash
curl -s http://localhost:8001/chat \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"K8s에서 GPU 어떻게 잡지?"}],"top_k":3}' \
  | jq
```

**예상 출력 (cold cache 30~60 초, 이후 호출은 2~5 초):**

```json
{
  "answer": "K8s 에서 GPU 를 사용하려면 노드 풀에 NVIDIA 드라이버를 설치하고, Pod spec 의 resources.limits 에 nvidia.com/gpu 를 명시해야 합니다 [1]. 추가로 별도 노드 풀에 nvidia.com/gpu=present:NoSchedule taint 를 부여하여 CPU 워크로드와 분리하는 것이 권장됩니다 [2].",
  "sources": [
    {
      "source": "course/phase-4-ml-on-k8s/03-vllm-llm-serving/lesson.md",
      "phase": "phase-4-ml-on-k8s",
      "topic": "03-vllm-llm-serving",
      "heading": "vLLM > GPU 격리",
      "score": 0.834,
      "chunk_id": "..."
    },
    { "...": "(2 개 더)" }
  ]
}
```

답변에 `[1]` `[2]` 인용 마커가 등장하면 prompts.py 의 SYSTEM_PROMPT 가 동작 중입니다. sources 가 *본 코스 파일* 을 가리키면 자기참조형 RAG 가 정상 동작.

### Step 9. `/metrics` 노출 + pytest

```bash
curl -s http://localhost:8001/metrics | grep -E "^rag_(chat|retrieve|llm)" | head -20
```

**예상 출력:**

```
rag_chat_total_total{status="ok"} 1.0
rag_chat_latency_seconds_count 1.0
rag_chat_latency_seconds_sum 4.231
rag_retrieve_latency_seconds_count 1.0
rag_retrieve_latency_seconds_sum 0.072
rag_llm_latency_seconds_count 1.0
rag_llm_latency_seconds_sum 4.150
```

4 개 메트릭이 모두 노출되면 Day 7 의 ServiceMonitor 가 그대로 수집할 라벨이 준비된 것입니다.

마지막으로 단위 테스트:

```bash
pytest tests/ -v
```

**예상 출력:**

```
tests/test_retriever.py::test_search_returns_chunks PASSED
tests/test_retriever.py::test_payload_metadata_preserved PASSED
tests/test_retriever.py::test_top_k_boundary PASSED
tests/test_retriever.py::test_empty_results PASSED
tests/test_retriever.py::test_e5_query_prefix_applied PASSED
tests/test_retriever.py::test_non_e5_model_no_prefix PASSED
====== 6 passed in 0.45s ======
```

테스트는 Qdrant/vLLM 호출 없이 mock 만 사용하므로 port-forward 가 끊겨도 통과합니다 — 이는 의도된 분리입니다.

---

## ✅ 검증 체크리스트

- [ ] `practice/rag_app/` 에 6 개 모듈 + `tests/` + `.env.example` + `Dockerfile` 모두 존재
- [ ] `pip install -r requirements.txt` 가 에러 0 으로 완료
- [ ] Terminal A 의 Qdrant port-forward 와 Terminal B 의 vLLM port-forward 가 동시 LISTEN
- [ ] retriever 단독 호출 시 *본 코스 자료* 의 `source` 가 top1 으로 검색 (자기참조형 검증)
- [ ] llm_client 단독 호출 시 한국어 답변 1 문장 정상
- [ ] `/healthz` + `/ready` 모두 200 OK
- [ ] `/chat` 호출 시 200 OK + `answer` 비어있지 않음 + `sources` 3 개 + 각 source 의 `phase` 가 `capstone` 또는 `phase-*` 형식
- [ ] `/metrics` 에 `rag_chat_total`, `rag_chat_latency_seconds`, `rag_retrieve_latency_seconds`, `rag_llm_latency_seconds` 4 종 모두 노출
- [ ] `pytest tests/ -v` 6 케이스 모두 PASS

---

## 🧹 정리

Day 5 종료 후 두 분기가 있습니다.

**(a) Day 6 으로 바로 이어서 진행 — 권장**
- uvicorn 만 Ctrl+C 로 종료 (Terminal C)
- port-forward 2 개는 그대로 유지 가능 (Day 6 이미지 빌드 + 클러스터 배포 검증에 활용)
- `.venv` 와 `.env` 는 보존 — Day 6 에서 Dockerfile 빌드 시 동일 파일 참고

**(b) 단독으로 끝낼 때 (또는 GKE 비용 절감)**
```bash
# 1. uvicorn 종료 (Terminal C)
# Ctrl+C

# 2. port-forward 종료 (Terminal A, B)
# 각 터미널에서 Ctrl+C

# 3. venv 비활성화
deactivate

# 4. (선택) GPU 노드 풀 size=0 — 5 분 내 복원 가능
gcloud container node-pools resize gpu-pool --cluster=capstone --zone=us-central1-a --num-nodes=0 --quiet

# 5. (장기 휴식) Day 1~3 리소스 정리는 day-01 §🧹 정리, vLLM Deployment 는 day-04 §🧹 정리 참조
```

> ⚠️ **`.env` 파일에 민감 정보가 들어가면 `.gitignore`** — 본 캡스톤은 더미 `EMPTY` api_key 만 사용하지만, 실 운영 시 HF 토큰을 추가하면 반드시 commit 제외 필요.

---

## 🚨 트러블슈팅

| # | 증상 | 원인 | 해결 |
|---|---|---|---|
| 1 | `Connection refused` on `localhost:6333` 또는 `localhost:8000` | port-forward 가 끊겼거나 시작되지 않음 | 해당 Terminal A/B 에서 Ctrl+C 후 명령 재실행. 또는 `lsof -i :6333 -i :8000` 으로 LISTEN 확인. 백그라운드 변형 사용 시 `pkill -f "kubectl port-forward"` 후 재시작. |
| 2 | `pip install` 에서 `Could not find a version that satisfies the requirement` | Python 3.10 미만 — sentence-transformers 3.1.0 은 3.10+ 요구 | `python --version` 확인 후 3.11 또는 3.12 로 venv 재생성. macOS 에선 `brew install python@3.12`. |
| 3 | `/chat` 응답이 `{"detail":"The model 'microsoft/phi-2' does not exist"}` | vLLM 의 `--served-model-name` 과 `LLM_MODEL` 환경변수 불일치 | `curl http://localhost:8000/v1/models \| jq '.data[0].id'` 결과를 그대로 `.env` 의 `LLM_MODEL` 에 복사. 대소문자/슬래시 정확히. (lesson.md §10 #14) |
| 4 | `/chat` 응답이 *본 코스와 무관한* 답변 | Qdrant 컬렉션이 비어있거나 차원 불일치 | `curl http://localhost:6333/collections/rag-docs \| jq '.result.points_count'` 가 0 이면 Day 2 또는 Day 3 인덱싱 미완. `points_count > 0` 인데도 무관한 답이면 `EMBED_MODEL` 이 인덱싱 시점과 다른지 확인 (Day 2 = `intfloat/multilingual-e5-small` 고정). |
| 5 | retriever 가 빈 리스트 반환 (top_k=3 인데 0 건) | e5 query prefix 누락 — 인덱싱은 `passage:` prefix 로 들어갔는데 검색이 raw text 면 recall 폭락 | `retriever.py` 의 `_E5_QUERY_PREFIX` 와 `_is_e5_model()` 가 살아있는지 확인. `EMBED_MODEL` 에 'e5' 가 포함되어야 prefix 적용. (lesson.md §10 #13) |
| 6 | 첫 실행 시 SentenceTransformer 다운로드 무한 대기 또는 SSL 에러 | 사내 방화벽이 huggingface.co 차단 | (a) 다른 네트워크에서 모델 1 회 다운로드 후 `~/.cache/huggingface/hub/models--intfloat--multilingual-e5-small/` 디렉터리를 옮긴 뒤 `HF_HOME=~/.cache/huggingface` 설정. (b) 또는 `HF_ENDPOINT=https://hf-mirror.com` 미러 환경변수. |
| 7 | `/chat` 첫 호출이 60 초 이상 응답 없음 후 timeout | vLLM 의 첫 토큰 생성 cold cache + OpenAI SDK timeout 부족 | 정상 동작입니다 (phi-2 첫 KV cache 적재). `llm_client.py` 의 `timeout=120` 으로 충분. 그래도 부족하면 두 번째 호출은 2~5 초로 떨어지므로 한 번 더 시도. 영구 부족 시 `VLLMClient(timeout=180)` 로 조정. |
| 8 | `pytest` 가 `ModuleNotFoundError: retriever` | `tests/` 에서 `retriever` import 실패 — 작업 디렉터리 문제 | `pytest tests/` 는 반드시 `practice/rag_app/` 에서 실행. 또는 `python -m pytest tests/`. `tests/test_retriever.py` 의 `sys.path.insert(...)` 줄이 살아있어야 함. |
| 9 | `/metrics` 에 4 종 메트릭이 0 으로만 보임 | `/chat` 호출 1 회도 안 됐거나 모두 에러 | Step 8 의 curl 한 번 성공 후 `/metrics` 재호출. `rag_chat_total{status="ok"}` 가 1 이상이면 정상. |

---

## 다음 단계

Day 5 가 완료되었다면 다음으로 진행합니다.

- 📘 **[Day 6 — RAG API 클러스터 배포 + Ingress](day-06-rag-api-deploy.md)** *(예정)* — 본 lab 의 6 개 모듈을 Docker 이미지로 빌드 → Deployment + Service + Ingress 매니페스트(`30~33`, `40`) 적용 → 클러스터 안에서 `/chat` end-to-end 검증.
- 📖 본 코드의 *왜 이렇게 모듈을 나눴는가* 의 결정 노트는 [`../lesson.md`](../lesson.md) §5 RAG API 구현 노트, [`../docs/architecture.md`](../docs/architecture.md) §3.9 동기 호출 흐름 / §3.10 임베딩 모델 로딩 전략을 참고하세요.
