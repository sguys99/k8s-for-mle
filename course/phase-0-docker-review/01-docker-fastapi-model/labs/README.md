# Lab — FastAPI 분류 모델 컨테이너 빌드와 실행

이 실습은 [lesson.md](../lesson.md)의 내용을 따라 **단일 stage / 멀티 stage** 두 가지 Dockerfile로 같은 앱을 빌드하고, 이미지 크기 차이를 직접 체감한 뒤 컨테이너를 띄워 추론을 검증합니다.

> 실습은 모두 `practice/` 디렉토리에서 수행합니다. 첫 빌드는 PyTorch CPU 휠을 받느라 5–10분 정도 걸릴 수 있습니다.

## 사전 준비

Docker가 동작하는지 확인합니다.

```bash
docker version
```

**예상 출력 (요약)**

```
Client: Docker Engine - Community
 Version:           24.0.x 이상
Server: Docker Engine - Community
 Version:           24.0.x 이상
```

작업 디렉토리로 이동합니다.

```bash
cd course/phase-0-docker-review/01-docker-fastapi-model/practice
ls
```

**예상 출력**

```
Dockerfile  Dockerfile.singlestage  fastapi_app.py  requirements.txt
```

## 1단계 — 단일 stage 빌드 (안티패턴 비교용)

```bash
docker build -f Dockerfile.singlestage -t sentiment-api:single .
```

**예상 출력 (요약)**

```
[+] Building 280.4s (10/10) FINISHED
 => => naming to docker.io/library/sentiment-api:single
```

## 2단계 — 멀티 stage 빌드 (권장 패턴)

```bash
docker build -t sentiment-api:multi .
```

`requirements.txt`를 코드보다 먼저 COPY했기 때문에, 두 번째 빌드부터는 의존성 단계가 캐시에 적중합니다. 이를 확인하려면 `fastapi_app.py`를 한 줄만 바꾸고 다시 빌드해 보세요.

**예상 출력 (요약)**

```
[+] Building 220.1s (13/13) FINISHED
 => CACHED [builder 4/5] COPY requirements.txt .
 => CACHED [builder 5/5] RUN pip install --user --no-cache-dir -r requirements.txt
 => => naming to docker.io/library/sentiment-api:multi
```

## 3단계 — 이미지 크기 비교

```bash
docker images sentiment-api
```

**예상 출력 (환경에 따라 수치는 다를 수 있습니다)**

```
REPOSITORY      TAG      IMAGE ID       CREATED          SIZE
sentiment-api   multi    abcd1234       2 minutes ago    1.4GB
sentiment-api   single   efgh5678       6 minutes ago    2.6GB
```

> 💡 GPU용 PyTorch(`torch==2.4.1`, CUDA 포함)를 사용했다면 단일 stage 이미지는 5–6GB까지 늘어납니다. 이 실습은 CPU 휠을 사용하므로 격차가 그보다 작습니다.

## 4단계 — 컨테이너 실행

```bash
docker run -d \
  --name sentiment-api \
  -p 8000:8000 \
  sentiment-api:multi
```

**예상 출력**

```
<64자리 컨테이너 ID>
```

모델 로딩이 끝날 때까지 30–90초 정도 기다립니다. 로그로 확인하세요.

```bash
docker logs -f sentiment-api
```

**예상 출력 (요약, Ctrl+C로 빠져나오기)**

```
serving: Loading model: cardiffnlp/twitter-roberta-base-sentiment
serving: Model loaded in 42.13s
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

## 5단계 — 동작 검증

### 5-1. 헬스체크

```bash
curl -s http://localhost:8000/healthz
curl -s http://localhost:8000/ready
```

**예상 출력**

```json
{"status":"ok"}
{"status":"ready","model":"cardiffnlp/twitter-roberta-base-sentiment"}
```

`/healthz`는 모델 로드 여부와 무관하게 200을 반환합니다. `/ready`는 모델이 준비되어야만 200입니다. K8s에서는 이 차이를 livenessProbe / readinessProbe로 그대로 사용합니다.

### 5-2. 추론 호출

```bash
curl -s -X POST http://localhost:8000/predict \
  -H 'Content-Type: application/json' \
  -d '{"text":"I love this product!"}'
```

**예상 출력 (label은 LABEL_0=negative, LABEL_1=neutral, LABEL_2=positive)**

```json
{"label":"LABEL_2","score":0.9821}
```

부정 문장도 시도해봅니다.

```bash
curl -s -X POST http://localhost:8000/predict \
  -H 'Content-Type: application/json' \
  -d '{"text":"This is the worst experience ever."}'
```

**예상 출력**

```json
{"label":"LABEL_0","score":0.9743}
```

### 5-3. Prometheus 메트릭 확인

```bash
curl -s http://localhost:8000/metrics | grep predict_
```

**예상 출력 (요약)**

```
# HELP predict_requests_total Total /predict requests
# TYPE predict_requests_total counter
predict_requests_total{status="ok"} 2.0
# HELP predict_latency_seconds Latency of /predict in seconds
# TYPE predict_latency_seconds histogram
predict_latency_seconds_bucket{le="0.005"} 0.0
predict_latency_seconds_count 2.0
predict_latency_seconds_sum 0.184
```

## 6단계 — `docker run` 옵션 실습 (선택)

K8s로 넘어가기 전에 다음 옵션이 무엇과 매핑되는지 짧게 체험합니다.

| 옵션 | K8s 대응 |
|------|---------|
| `-p 8000:8000` | Service의 `port`/`targetPort` |
| `-v $(pwd)/cache:/home/app/.cache/huggingface` | PVC 마운트 |
| `--env MODEL_NAME=...` | ConfigMap 또는 env |
| `--gpus all` | `resources.limits.nvidia.com/gpu: 1` |

볼륨 마운트로 모델 캐시를 호스트에 보존해보세요.

```bash
docker rm -f sentiment-api
mkdir -p ./hf-cache
docker run -d \
  --name sentiment-api \
  -p 8000:8000 \
  -v "$(pwd)/hf-cache:/home/app/.cache/huggingface" \
  sentiment-api:multi
```

두 번째 실행부터 모델 로드가 빨라지면 캐시가 잘 마운트된 것입니다.

## 7단계 — 정리

```bash
docker rm -f sentiment-api
docker rmi sentiment-api:single sentiment-api:multi
```

**예상 출력 (요약)**

```
sentiment-api
Untagged: sentiment-api:single
Untagged: sentiment-api:multi
Deleted: sha256:...
```

호스트에 남은 캐시를 지우려면 `rm -rf ./hf-cache`를 추가로 실행합니다.

## 트러블슈팅

| 증상 | 원인 / 해결 |
|------|-----------|
| `pip install`이 너무 느림 | PyTorch CPU 휠은 약 200MB입니다. 첫 빌드는 10분이 걸릴 수 있습니다. 두 번째부터는 캐시가 적중합니다. |
| `/predict` 호출이 503 반환 | 모델 로딩이 아직 끝나지 않았습니다. `docker logs sentiment-api`로 "Model loaded" 메시지를 기다리세요. |
| 빌드 중 `error: externally-managed-environment` | 베이스 이미지가 `python:3.12` (full)이 아닌 다른 배포판을 쓰는 경우 발생할 수 있습니다. 본 실습 Dockerfile을 그대로 사용하세요. |
| 컨테이너가 즉시 종료 | `docker logs sentiment-api`로 에러를 확인합니다. 메모리 부족이면 Docker Desktop의 메모리 할당을 4GB 이상으로 늘리세요. |

---

이제 [lesson.md](../lesson.md)의 검증 체크리스트로 돌아가 모든 항목을 확인하세요.
