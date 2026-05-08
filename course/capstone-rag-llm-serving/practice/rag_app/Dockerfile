# 캡스톤 RAG API 이미지 — Day 6 클러스터 배포용으로 빌드합니다.
# 이식 출처: .claude/skills/k8s-ml-course-author/assets/templates/practice/Dockerfile.tmpl
# 변경:
#   - port 8000 → 8001 (vLLM 이 8000 을 점유하므로 RAG API 는 8001 로 분리, port-forward 시 충돌 회피)
#   - CMD entrypoint 를 fastapi_app:app → main:app 으로 (캡스톤 모듈명 컨벤션)
#   - HF_HOME 캐시 경로는 그대로 — 임베딩 모델(e5-small ≈ 130MB) 첫 실행 시 다운로드되며
#     Day 6 Deployment 에서 emptyDir 또는 PVC 로 마운트해 Pod 재기동 가속

# ===== Builder stage =====
FROM python:3.12-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

# ===== Runtime stage =====
FROM python:3.12-slim

WORKDIR /app

RUN useradd -m -u 1000 app

COPY --from=builder /root/.local /home/app/.local
ENV PATH=/home/app/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/home/app/.cache/huggingface

# 애플리케이션 코드 (main.py / retriever.py / llm_client.py / prompts.py)
COPY --chown=app:app . .

USER app

RUN mkdir -p /home/app/.cache/huggingface

EXPOSE 8001

# uvicorn 으로 FastAPI 실행. --workers 1 (lifespan 의 임베딩 모델 로딩이 worker 별로 발생하지 않도록)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "1"]
