# 멀티스테이지 PyTorch 슬림 빌드 — Phase 0 / 01-docker-fastapi-model
# CPU 추론용. GPU 추론은 베이스 이미지를 nvidia/cuda 계열로 교체합니다.

# ===== Builder stage =====
FROM python:3.12-slim AS builder

WORKDIR /build

# 휠 빌드에 필요한 도구만 설치합니다. 빌드가 끝나면 runtime 이미지에는 남지 않습니다.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# requirements를 먼저 COPY해 코드 변경 시 pip install 캐시를 재사용합니다.
COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

# ===== Runtime stage =====
FROM python:3.12-slim

WORKDIR /app

# 비루트 실행. K8s SecurityContext 정책(runAsNonRoot)과 호환됩니다.
RUN useradd -m -u 1000 app

# Builder에서 설치한 패키지만 복사합니다. build-essential 같은 빌드 도구는 가져오지 않습니다.
COPY --from=builder /root/.local /home/app/.local

ENV PATH=/home/app/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/home/app/.cache/huggingface

# 애플리케이션 코드만 복사합니다.
COPY --chown=app:app fastapi_app.py .

USER app

# HuggingFace 캐시 경로. Phase 2에서 PVC로 마운트하게 됩니다.
RUN mkdir -p /home/app/.cache/huggingface

EXPOSE 8000

# uvicorn으로 FastAPI 실행. K8s에서는 Pod의 containers[].command/args로 오버라이드할 수 있습니다.
CMD ["uvicorn", "fastapi_app:app", "--host", "0.0.0.0", "--port", "8000"]
