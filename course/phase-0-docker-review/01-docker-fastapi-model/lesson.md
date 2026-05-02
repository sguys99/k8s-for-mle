# Docker 점검 — FastAPI로 분류 모델 컨테이너화

> **Phase**: 0 — 사전 점검 (Docker)
> **소요 시간**: 3–4시간 (모델·이미지 다운로드 시간 포함)
> **선수 학습**: Python 기초, HuggingFace `transformers`로 추론을 한 번이라도 해본 경험

## 학습 목표

이 챕터를 마치면 다음을 할 수 있습니다.

- Dockerfile 핵심 명령어(`FROM`/`COPY`/`RUN`/`CMD`/`ENTRYPOINT`)의 차이를 설명하고, 캐시 효율적인 순서로 작성할 수 있습니다.
- 멀티스테이지 빌드로 PyTorch + transformers 이미지 크기를 절반 이하로 줄일 수 있습니다.
- `docker run`의 `-p`, `-v`, `--env`, `--gpus` 옵션을 ML 워크로드 맥락에서 사용할 수 있습니다.
- HuggingFace 분류 모델을 FastAPI로 감싼 컨테이너를 빌드하고 `/predict`로 추론을 검증할 수 있습니다.

## 왜 ML 엔지니어에게 필요한가

K8s는 컨테이너 위에서 동작하기 때문에, Docker 기본기가 흔들리면 K8s에서 만나는 문제(이미지 풀링 지연, OOMKilled, 권한 오류) 대부분이 함께 흔들립니다. 특히 ML 워크로드는 베이스 이미지를 잘못 고르면 이미지가 5GB를 넘어 노드 디스크와 풀링 시간을 갉아먹고, CUDA·PyTorch 버전이 맞지 않으면 Pod가 무한히 CrashLoopBackOff에 빠집니다. 이 챕터에서 만든 `sentiment-api:multi` 이미지는 Phase 1의 첫 Pod, Phase 2의 ConfigMap·PVC 실습, Phase 3의 HPA 부하 테스트까지 그대로 사용하므로, 처음부터 잘 만들어 두면 이후 모든 챕터가 매끄럽게 이어집니다.

## 1. 핵심 개념

### 1-1. Dockerfile 명령어 정리

자주 헷갈리는 명령어를 한 표로 정리합니다.

| 명령어 | 역할 | 캐시 영향 |
|--------|------|----------|
| `FROM` | 베이스 이미지 선택 | 베이스가 바뀌면 이후 전부 재실행 |
| `COPY` | 빌드 컨텍스트의 파일을 이미지로 복사 | 복사 대상이 바뀌면 이후 단계 재실행 |
| `RUN` | 빌드 시점에 명령 실행 (레이어 생성) | 명령/입력이 바뀌면 재실행 |
| `CMD` | 컨테이너 시작 시 기본 명령 (오버라이드 가능) | 캐시 영향 적음 |
| `ENTRYPOINT` | 컨테이너 시작 시 고정 명령 (인자만 오버라이드) | 캐시 영향 적음 |

`CMD`와 `ENTRYPOINT`의 차이가 K8s에서 자주 사고를 부릅니다. K8s 매니페스트의 `containers[].command`는 **ENTRYPOINT를 덮어쓰고**, `containers[].args`는 **CMD를 덮어씁니다**. 이번 실습에서는 익숙한 `CMD` 형식만 사용합니다.

```dockerfile
# 좋은 패턴: exec 형식 (쉘을 거치지 않으므로 신호가 PID 1로 직접 전달됩니다)
CMD ["uvicorn", "fastapi_app:app", "--host", "0.0.0.0", "--port", "8000"]

# 피해야 할 패턴: shell 형식
CMD uvicorn fastapi_app:app --host 0.0.0.0 --port 8000
```

> 💡 **팁**: K8s의 `kubectl rollout`이 Pod에 `SIGTERM`을 보내 정상 종료를 유도하는데, shell 형식 `CMD`는 신호를 잡지 못해 30초를 기다리다 강제 종료됩니다.

### 1-2. 이미지 레이어와 빌드 캐시

Docker는 Dockerfile의 각 명령마다 레이어를 만들고, 입력이 같으면 그 레이어를 캐시합니다. ML 프로젝트에서 핵심은 **무거운 의존성 설치 단계의 캐시를 살리는 것**입니다.

```dockerfile
# ❌ 안티패턴: 코드 한 줄 바꾸면 pip install이 다시 돌아감
COPY . .
RUN pip install -r requirements.txt

# ✅ 권장 패턴: 의존성 설치 레이어를 코드 변경과 분리
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
```

PyTorch 휠 다운로드는 첫 실행에 5–10분이 걸립니다. 캐시 레이어 하나를 잘 두면 두 번째 빌드부터 이 시간을 0초로 줄일 수 있습니다.

### 1-3. 멀티스테이지 빌드

이미지에는 **빌드 도구**(`build-essential`, 컴파일러 등)와 **런타임**(파이썬 인터프리터, 모델 로딩 코드)이 모두 들어갈 수 있습니다. 운영에는 런타임만 있으면 충분하므로, builder stage에서 휠을 빌드한 뒤 runtime stage로 결과만 옮기는 패턴이 표준입니다.

```dockerfile
# ===== Builder =====
FROM python:3.12-slim AS builder
RUN apt-get update && apt-get install -y --no-install-recommends build-essential
COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

# ===== Runtime =====
FROM python:3.12-slim
COPY --from=builder /root/.local /home/app/.local
COPY fastapi_app.py /app/
CMD ["uvicorn", "fastapi_app:app", "--host", "0.0.0.0", "--port", "8000"]
```

이번 실습에서 단일 stage 이미지(약 2.5GB)와 멀티 stage 이미지(약 1.4GB)의 크기 차이를 직접 확인합니다. CUDA 베이스를 쓰면 격차가 5GB → 1.5GB까지도 벌어집니다.

### 1-4. `docker run` 런타임 옵션

K8s 매니페스트로 넘어가기 전에, 핵심 옵션이 무엇과 매핑되는지 미리 익혀둡니다.

| `docker run` | K8s에서의 대응 | ML 시나리오 예시 |
|--------------|---------------|----------------|
| `-p 8000:8000` | Service의 `port`/`targetPort` | FastAPI 추론 엔드포인트 노출 |
| `-v $(pwd)/cache:/home/app/.cache/huggingface` | PersistentVolumeClaim 마운트 | 모델 가중치 캐시 보존 (Pod 재시작 시 재다운로드 방지) |
| `--env MODEL_NAME=...` | ConfigMap 또는 env | 추론 모델 ID, 임계치 같은 하이퍼파라미터 |
| `--gpus all` | `resources.limits."nvidia.com/gpu": 1` | vLLM, Triton, KServe GPU 추론 |
| `--env-file .env` | Secret + envFrom | HuggingFace 토큰, S3 키 |

> 💡 **팁**: 볼륨 마운트는 Phase 2의 PVC 학습으로, GPU 옵션은 Phase 4의 Device Plugin 학습으로 그대로 이어집니다.

## 2. 실습

상세 절차와 예상 출력은 [labs/README.md](labs/)에 있습니다. 여기서는 핵심 단계만 짚습니다.

### 2-1. 사전 준비

```bash
docker version       # 24.0+ 권장
cd course/phase-0-docker-review/01-docker-fastapi-model/practice
ls
# Dockerfile  Dockerfile.singlestage  fastapi_app.py  requirements.txt
```

### 2-2. FastAPI 앱 살펴보기

[practice/fastapi_app.py](practice/fastapi_app.py)는 4개 엔드포인트를 가집니다.

```python
@app.post("/predict")    # 추론
@app.get("/healthz")     # liveness — 항상 200
@app.get("/ready")       # readiness — 모델 로드 완료 시 200
@app.get("/metrics")     # Prometheus 스크래핑용
```

`/healthz`와 `/ready`를 분리한 이유는 K8s에서 그대로 차이가 의미를 갖기 때문입니다. 모델 로딩 중에는 트래픽을 받으면 안 되지만(readiness=503) 프로세스 자체는 살아 있어야(liveness=200) 재시작 루프에 빠지지 않습니다. Phase 2~3에서 이 구조를 그대로 사용합니다.

### 2-3. 단일 stage 빌드 → 크기 확인

```bash
docker build -f Dockerfile.singlestage -t sentiment-api:single .
docker images sentiment-api:single
```

**예상 출력 (요약)**

```
REPOSITORY      TAG     IMAGE ID    CREATED         SIZE
sentiment-api   single  efgh5678    1 minute ago    2.6GB
```

### 2-4. 멀티 stage 빌드 → 크기 비교

```bash
docker build -t sentiment-api:multi .
docker images sentiment-api
```

**예상 출력**

```
REPOSITORY      TAG     IMAGE ID    CREATED         SIZE
sentiment-api   multi   abcd1234    30 seconds ago  1.4GB
sentiment-api   single  efgh5678    3 minutes ago   2.6GB
```

### 2-5. 컨테이너 실행과 추론 검증

```bash
docker run -d --name sentiment-api -p 8000:8000 sentiment-api:multi
docker logs -f sentiment-api    # "Model loaded" 메시지 확인 후 Ctrl+C

curl -s http://localhost:8000/ready
# {"status":"ready","model":"cardiffnlp/twitter-roberta-base-sentiment"}

curl -s -X POST http://localhost:8000/predict \
  -H 'Content-Type: application/json' \
  -d '{"text":"I love this product!"}'
# {"label":"LABEL_2","score":0.9821}
```

`LABEL_2`가 positive입니다 (`LABEL_0`=negative, `LABEL_1`=neutral, `LABEL_2`=positive).

## 3. 검증 체크리스트

다음 항목을 모두 확인했다면 이 챕터를 마쳤다고 볼 수 있습니다.

- [ ] `docker images sentiment-api`로 두 태그(`single`, `multi`)가 보이고, `multi`가 더 작다.
- [ ] `curl http://localhost:8000/healthz`가 즉시 200을 반환한다.
- [ ] 모델 로드 중에는 `/ready`가 503, 로드 후에는 200을 반환한다.
- [ ] `/predict`에 긍정/부정 텍스트를 보내 라벨이 다르게 나온다.
- [ ] `/metrics`에서 `predict_requests_total`이 호출 횟수만큼 증가한다.

## 4. 정리

```bash
docker rm -f sentiment-api
docker rmi sentiment-api:single sentiment-api:multi
```

`sentiment-api:multi` 이미지는 Phase 1에서 다시 만들어 사용하니, 학습을 곧바로 이어간다면 `multi` 태그만 남겨 두어도 됩니다.

## 🚨 자주 하는 실수

1. **`COPY .`로 의존성과 코드를 한 번에 복사** — 코드 한 줄을 바꿔도 `pip install`이 다시 실행됩니다. 항상 `requirements.txt`를 코드보다 먼저 `COPY`하고 의존성 설치 → 코드 복사 순서로 작성합니다.
2. **`python:latest` 베이스 사용** — 어제 동작하던 빌드가 오늘 깨질 수 있습니다. 항상 `python:3.12-slim`처럼 메이저·마이너 버전을 고정합니다. 이미지 크기도 절반 가까이 줄어듭니다.
3. **`ENTRYPOINT`와 `CMD`를 혼동** — K8s `command`는 ENTRYPOINT를, `args`는 CMD를 덮어씁니다. `CMD`만 쓰고 K8s에서 `args`로 인자만 바꾸는 패턴이 가장 단순합니다.

## 더 알아보기

- [Docker — Best practices for writing Dockerfiles](https://docs.docker.com/develop/develop-images/dockerfile_best-practices/)
- [Docker — Multi-stage builds](https://docs.docker.com/build/building/multi-stage/)
- [HuggingFace — `cardiffnlp/twitter-roberta-base-sentiment`](https://huggingface.co/cardiffnlp/twitter-roberta-base-sentiment)
- [FastAPI — Lifespan events](https://fastapi.tiangolo.com/advanced/events/)

## 다음 챕터

➡️ [Phase 1 / 01-cluster-setup — minikube 설치와 첫 Pod](../../phase-1-k8s-basics/01-cluster-setup/lesson.md)
