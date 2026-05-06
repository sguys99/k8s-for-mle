# Day 2 — 인덱싱 스크립트 로컬 실행

> **상위 lesson**: [`../lesson.md`](../lesson.md) §3.2 인덱싱 데이터 흐름, §4.6 인덱싱 파이프라인
> **상위 plan**: [`docs/capstone-plan.md`](../../../docs/capstone-plan.md) §7 Day 2
> **이전 단계**: [`day-01-namespace-qdrant.md`](day-01-namespace-qdrant.md)
> **소요 시간**: 1.5 ~ 2 시간 (첫 임베딩 모델 다운로드 5~10 분 포함)

---

## 🎯 Goal

Day 2 를 마치면 다음 5 가지가 충족됩니다.

- 본 코스 자료(`course/phase-*/**/lesson.md` 약 20 파일 + `docs/study-roadmap.md`) 를 청크/임베딩하는 로컬 파이썬 스크립트 동작 확인
- Day 1 에 띄운 Qdrant 의 컬렉션 `rag-docs` 에 **수백 개 청크 upsert 완료** (`points_count > 0`)
- `multilingual-e5-small` 임베딩 모델로 한국어/영어 혼재 자료를 384 차원 벡터로 변환
- 자연어 쿼리("쿠버네티스에서 GPU 노드는 어떻게 분리하나요?") → 본 코스 파일 경로가 top1 으로 검색됨 (자기참조형 retrieval 동작)
- Day 3 Argo Workflow 로 컨테이너화될 코드의 **로컬 동등 동작** 확보

---

## 🔧 사전 조건

- **Day 1 완료**: `qdrant-0` Pod 가 Running, Headless Service `qdrant` 살아있음.
  ```bash
  kubectl get pod qdrant-0 -n rag-llm
  # → qdrant-0   1/1   Running   0   ...
  ```
- **Python 3.11+**: `python3.11 --version` 으로 확인. 가상환경 권장.
- **kubectl 컨텍스트**: 캡스톤 클러스터에 연결.
  ```bash
  kubectl config current-context
  ```
- **디스크 여유 1GB**: 첫 실행 시 임베딩 모델 다운로드(~130MB) + torch 휠(~200MB) + 캐시.
- **인터넷**: 첫 모델 다운로드용. 두 번째 실행부터는 HuggingFace 캐시 재사용.
- **작업 디렉토리**: 본 lab 의 모든 명령은 **프로젝트 루트**(`k8s-for-mle/`) 에서 실행하는 것을 기준으로 합니다.

> 💡 **GKE 비용 관리**: Day 2 도 CPU only 클러스터로 충분합니다(임베딩은 로컬 CPU). T4 노드풀은 Day 4 vLLM 까지 미루세요.

---

## 🚀 Steps

### Step 1. 가상환경 + 의존성 설치

```bash
# 프로젝트 루트에서
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r course/capstone-rag-llm-serving/practice/pipelines/indexing/requirements.txt
```

**예상 출력 (마지막 줄):**

```
Successfully installed certifi-... charset-normalizer-... ... sentence-transformers-3.1.1 qdrant-client-1.12.0 langchain-text-splitters-0.3.0
```

> 💡 첫 설치 시 torch CPU 휠을 의존성으로 함께 가져오므로 1~2 분 걸립니다. 이미 다른 프로젝트에서 torch 가 설치되어 있다면 거의 즉시.

### Step 2. Qdrant 에 port-forward (백그라운드)

```bash
kubectl port-forward -n rag-llm svc/qdrant 6333:6333 &
sleep 2
curl -s http://localhost:6333/healthz
```

**예상 출력:**

```
healthz check passed
```

✅ **확인 포인트**: `healthz check passed` 가 보이면 Day 1 의 Qdrant 가 로컬에서 호출 가능합니다. 만약 `connection refused` 가 나오면 트러블슈팅 §1 참고.

### Step 3. 환경변수 export

```bash
export DOCS_ROOT=course
export ROADMAP_PATH=docs/study-roadmap.md
export QDRANT_URL=http://localhost:6333
export QDRANT_COLLECTION=rag-docs
export EMBED_MODEL=intfloat/multilingual-e5-small
```

> 💡 본 lab 의 모든 후속 명령은 위 5 개 환경변수가 설정되어 있다고 가정합니다. 새 셸에서 다시 실행할 때마다 export 를 반복하거나 `direnv` 같은 도구로 자동화하세요.

### Step 4. `load-docs` — 코스 자료 적재

```bash
cd course/capstone-rag-llm-serving/practice/pipelines/indexing
# DOCS_ROOT 가 상대 경로이므로, pipeline.py 도 프로젝트 루트 기준으로 호출하는 게 안전합니다.
cd -
python course/capstone-rag-llm-serving/practice/pipelines/indexing/pipeline.py load-docs
```

**예상 출력:**

```
[load-docs] wrote 21 docs -> .pipeline-data/docs.jsonl
```

✅ **확인 포인트**: `wrote N docs` 의 N 은 본 코스 자료의 lesson.md 수 + 1(study-roadmap) 입니다. 작성 시점에 따라 19~22 사이가 정상.

```bash
wc -l .pipeline-data/docs.jsonl
# → 21 .pipeline-data/docs.jsonl
head -1 .pipeline-data/docs.jsonl | python -c "import json,sys; d=json.loads(sys.stdin.read()); print(d['source'], '|', d['phase'], '|', d['topic'])"
# → course/phase-0-docker-review/...lesson.md | phase-0-docker-review | <topic-slug>
```

### Step 5. `chunk` — 마크다운 청크 분할

```bash
python course/capstone-rag-llm-serving/practice/pipelines/indexing/pipeline.py chunk \
  --chunk-size 512 --chunk-overlap 64
```

**예상 출력:**

```
[chunk] split into 612 chunks (md-header → char chunk_size=512, overlap=64) -> .pipeline-data/chunks.jsonl
```

✅ **확인 포인트**: 청크 수는 자료 분량에 따라 약 **500~800** 사이가 정상. `heading` 메타가 부여됐는지 확인:

```bash
head -1 .pipeline-data/chunks.jsonl | python -c "import json,sys; d=json.loads(sys.stdin.read()); print('heading:', repr(d['heading']))"
# → heading: '도입 — 왜 ML 엔지니어에게...' 같은 헤딩 경로
```

### Step 6. `embed` — 임베딩 생성 (시간이 가장 오래 걸리는 단계)

```bash
python course/capstone-rag-llm-serving/practice/pipelines/indexing/pipeline.py embed \
  --model intfloat/multilingual-e5-small
```

**예상 출력 (첫 실행 — 모델 다운로드 포함, 5~10 분):**

```
[embed] loading model intfloat/multilingual-e5-small (HF_HOME=default)
... (모델 다운로드 progress bar)
[embed] embedding dimension=384
[embed] e5 model detected → prefixing inputs with 'passage:'
[embed] wrote 612 embeddings (dim=384) -> .pipeline-data/embeddings.jsonl
```

✅ **확인 포인트**:
- `embedding dimension=384` — 차원이 맞으면 캡스톤 plan §4.6 / architecture §4 의 PVC 산정값과 호환.
- `e5 model detected → prefixing` — e5 규약 prefix 가 자동 적용됨.

> 💡 **2 회차부터는 30 초~1 분**: HuggingFace 캐시(`~/.cache/huggingface/`) 가 모델을 보존합니다.

### Step 7. `upsert` — Qdrant 컬렉션에 적재

```bash
python course/capstone-rag-llm-serving/practice/pipelines/indexing/pipeline.py upsert \
  --collection rag-docs
```

**예상 출력 (최초 실행):**

```
[upsert] connecting to http://localhost:6333, collection=rag-docs
[upsert] created collection 'rag-docs' (size=384, distance=Cosine)
[upsert] uploaded 612 points. collection points_count=612
```

**예상 출력 (두 번째 실행 — idempotent):**

```
[upsert] connecting to http://localhost:6333, collection=rag-docs
[upsert] reusing existing collection 'rag-docs' (size=384)
[upsert] uploaded 612 points. collection points_count=612
```

✅ **확인 포인트**: 두 번 실행해도 `points_count` 가 그대로 유지되면 idempotent upsert 가 동작 중.

### Step 8. Qdrant REST API 로 컬렉션 검증

```bash
curl -s http://localhost:6333/collections/rag-docs | jq '.result | {points_count, vectors_config: .config.params.vectors}'
```

**예상 출력:**

```json
{
  "points_count": 612,
  "vectors_config": {
    "size": 384,
    "distance": "Cosine"
  }
}
```

✅ **확인 포인트** 3 가지:
- `points_count > 0` (대략 500~800)
- `size: 384` (multilingual-e5-small 차원)
- `distance: "Cosine"` (코사인 유사도)

### Step 9. 자기참조형 retrieval 검증

본 코스 자료를 인덱싱했으므로, 본 코스에 대한 질문이 본 코스 파일을 top1 으로 가져와야 합니다.

```bash
python course/capstone-rag-llm-serving/practice/pipelines/indexing/pipeline.py search \
  --query "쿠버네티스에서 GPU 노드는 어떻게 분리하나요?" \
  --top-k 3
```

**예상 출력 (요약 — 실제 score 와 heading 은 자료 분량에 따라 다를 수 있음):**

```json
[
  {
    "score": 0.83,
    "payload": {
      "source": "course/phase-4-ml-on-k8s/01-gpu-scheduling/lesson.md",
      "phase": "phase-4-ml-on-k8s",
      "topic": "01-gpu-scheduling",
      "heading": "## 3. GPU 노드 풀 분리 > 3.1 nodeSelector 와 taints",
      "preview": "GPU 노드 풀은 별도 nodeSelector 와 taints 로 분리하여 일반 워크로드가 GPU 자원을 ..."
    }
  },
  {
    "score": 0.78,
    "payload": {
      "source": "course/phase-4-ml-on-k8s/01-gpu-scheduling/lesson.md",
      ...
    }
  },
  ...
]
```

✅ **확인 포인트** 3 가지:
- top1 의 `payload.source` 가 본 코스의 GPU 관련 lesson.md (대개 `phase-4-ml-on-k8s/01-gpu-scheduling/lesson.md` 또는 캡스톤 자체 lesson)
- `score > 0.7` 정도 (e5-small 코사인 유사도 기준 의미 있는 매칭)
- `heading` 메타가 헤딩 경로 형식 (`> ` 으로 연결)

다른 쿼리도 시험해 보세요:

```bash
python course/capstone-rag-llm-serving/practice/pipelines/indexing/pipeline.py search \
  --query "vLLM startupProbe failureThreshold 을 왜 늘려야 하나요?" --top-k 3
# → phase-4-ml-on-k8s/03-vllm-llm-serving/lesson.md 가 top1 일 가능성 높음
```

### Step 10. port-forward 종료 + 정리

```bash
# 백그라운드 port-forward 종료
kill %1
# 또는: pkill -f "port-forward.*qdrant"
```

**확인:**

```bash
jobs
# → (출력 없음 — 백그라운드 프로세스 없음)
```

> 💡 **중간 산출물 보존 여부**: `.pipeline-data/` 의 docs/chunks/embeddings JSONL 은 Day 3 에서 Argo Workflow 의 동작과 비교할 때 유용합니다. 디스크 여유가 있다면 보존, 정리하려면 `rm -rf .pipeline-data` 한 줄.

---

## ✅ 검증 체크리스트

다음 항목을 모두 확인했다면 Day 2 가 완료된 것입니다.

- [ ] `pip install -r requirements.txt` 가 에러 없이 끝남
- [ ] `curl http://localhost:6333/healthz` → `healthz check passed`
- [ ] `python pipeline.py load-docs` → `wrote N docs` (N ≥ 19)
- [ ] `python pipeline.py chunk ...` → `split into M chunks` (M = 500~800)
- [ ] `python pipeline.py embed ...` → `embedding dimension=384`, `e5 model detected → prefixing`
- [ ] `python pipeline.py upsert ...` → `uploaded ... points. collection points_count=...`
- [ ] `curl /collections/rag-docs` → `points_count > 0`, `size: 384`, `distance: "Cosine"`
- [ ] `python pipeline.py search --query "..."` → top1 의 `payload.source` 가 본 코스 파일
- [ ] (idempotent 검증) Step 7 을 한 번 더 실행해도 `points_count` 가 동일

---

## 🧹 정리

**Day 3 으로 바로 이어서 진행**하는 경우는 **컬렉션과 클러스터를 그대로 둡니다**(Day 3 Argo Workflow 가 동일 컬렉션을 덮어씁니다 — idempotent 패턴).

**Day 2 만 단독으로 끝낼 때**:

```bash
# 1. (선택) Qdrant 컬렉션 비우기 — 다음 실행을 깨끗하게
kubectl port-forward -n rag-llm svc/qdrant 6333:6333 &
sleep 2
curl -X DELETE http://localhost:6333/collections/rag-docs
kill %1

# 2. (선택) 로컬 중간 산출물 정리
rm -rf .pipeline-data

# 3. (선택) 가상환경 비활성화
deactivate
```

**Day 1 의 Qdrant 까지 정리**하려면 [`day-01-namespace-qdrant.md`](day-01-namespace-qdrant.md) §🧹 정리 참고.

**GKE 클러스터 자체를 종료**하려면:

```bash
gcloud container clusters delete capstone --zone us-central1-a --quiet
```

---

## 🚨 막힐 때 (트러블슈팅)

| 증상 | 원인 | 해결 |
|---|---|---|
| `[upsert] connection refused` 또는 `curl localhost:6333/healthz` 실패 | port-forward 프로세스 미기동 또는 종료됨 | `jobs` 로 확인 → 없으면 Step 2 재실행. `lsof -i :6333` 로 포트 점유 충돌 확인 |
| `[load-docs] WARNING: 0 docs found` | `DOCS_ROOT` 가 잘못된 경로를 가리킴 | 프로젝트 루트에서 명령 실행 + `echo $DOCS_ROOT` 가 `course` 인지 확인. `ls course/phase-*/lesson.md` 로 입력 존재 확인 |
| `[embed] OSError: ... model not found` | HuggingFace 모델 다운로드 실패(인터넷/방화벽) | 로컬에 모델 미리 다운로드 후 `HF_HOME=/path/to/cache` 지정. 사내 프록시 환경이면 `HTTPS_PROXY` 설정 |
| `[embed]` 가 매우 느림 (10 분 이상) | CPU 만 사용 + 청크 수 과다 | `--chunk-size 256` 으로 청크 줄이기, 또는 일시적으로 GPU 환경에서 재실행. 1 회만 인덱싱하면 되므로 시간만 들이면 OK |
| `[upsert] ERROR: vector size 불일치` | 이전에 다른 차원 모델로 컬렉션을 만든 적 있음 | `curl -X DELETE http://localhost:6333/collections/rag-docs` 로 컬렉션 비운 뒤 Step 7 재실행 |
| `search` 결과가 모두 영어 lesson 만 매칭 | e5 prefix 가 빠진 다른 모델로 임베딩됨 | `EMBED_MODEL` 이 `intfloat/multilingual-e5-small` 인지 확인. `embed` 단계 로그에 `e5 model detected → prefixing` 라인이 있어야 함 |
| `pip install` 이 `torch` 빌드에서 멈춤 | macOS arm64 + 오래된 pip | `pip install --upgrade pip` 후 재시도. 그래도 실패하면 `pip install torch==2.4.1` 을 별도로 먼저 설치 |

---

## 다음 단계

➡️ Day 3 — 인덱싱 Argo Workflow 클러스터 실행 (작성 예정)

본 lab 에서 만든 동일 코드(`pipeline.py`) 와 컨테이너 이미지(`Dockerfile`) 를 Argo Workflow 의 4 단계 step 으로 감싸 클러스터 안에서 실행합니다. 변경되는 것은 환경변수(`DOCS_ROOT=/docs`, `QDRANT_URL=http://qdrant.rag-llm.svc:6333`) 와 입력 자료의 마운트 방식뿐입니다.

> 참고: Day 3 lab 은 후속 작업입니다. 본 캡스톤 진행 순서는 [`docs/capstone-plan.md`](../../../docs/capstone-plan.md) §7 을 따릅니다.
