# Argo Workflow 의 4단계(load-docs / chunk / embed / upsert)를 단일 이미지로 처리합니다.
# subcommand 가 다르고 args 만 바뀌므로 이미지를 4개로 나눌 필요가 없습니다.
FROM python:3.11-slim

# pip 캐시 비활성화 — 이미지 크기 절감
ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# torch CPU 빌드는 무거우므로 미리 별도 인덱스로 설치 (GPU 빌드를 끌어오면 1GB+ 증가)
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch==2.4.1

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY pipeline.py /app/pipeline.py
COPY sample_docs/ /docs/

# 기본 진입점은 도움말. 실제 실행은 Workflow 의 args 가 subcommand 를 넘겨줍니다.
ENTRYPOINT ["python", "/app/pipeline.py"]
CMD ["--help"]
