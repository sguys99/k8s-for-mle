# 캡스톤 인덱싱 파이프라인 컨테이너 이미지
# - 출처: course/phase-4-ml-on-k8s/04-argo-workflows/practice/rag_pipeline/Dockerfile
# - 변경: COPY sample_docs/ 제거 — 입력 코스 자료는 외부 마운트(PVC 또는 git-clone init container)로 받음
#         Day 3 Argo Workflow 의 4 단계(load-docs/chunk/embed/upsert)가 같은 이미지를 띄워 subcommand 만 바꿔 호출

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

# 입력 코스 자료는 컨테이너 외부에서 마운트합니다.
# 권장 마운트 경로: /docs (DOCS_ROOT 환경변수의 기본값과 일치).
#   Day 2 (로컬): 컨테이너를 띄우지 않고 호스트에서 직접 python pipeline.py 실행
#   Day 3 (Argo): PVC 또는 git-clone init container 로 /docs 에 코스 자료 트리 마운트
ENV DOCS_ROOT=/docs \
    PIPELINE_DATA_DIR=/data \
    QDRANT_URL=http://qdrant.rag-llm.svc:6333 \
    QDRANT_COLLECTION=rag-docs \
    EMBED_MODEL=intfloat/multilingual-e5-small

# 기본 진입점은 도움말. 실제 실행은 Workflow 의 args 가 subcommand 를 넘겨줍니다.
ENTRYPOINT ["python", "/app/pipeline.py"]
CMD ["--help"]
