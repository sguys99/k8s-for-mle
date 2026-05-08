"""캡스톤 RAG API — FastAPI 진입점.

이식 출처: .claude/skills/k8s-ml-course-author/assets/templates/practice/rag_app.py.tmpl
변경:
  - 단일 파일 _retrieve / _build_prompt 패턴 → 모듈 분리(retriever / llm_client / prompts)
    main.py 는 *조립* 만 담당. 실제 로직은 3 모듈에 위임 → 각 모듈이 독립적으로 단위 테스트 가능.
  - 임베딩 모델 캐싱: 모듈 전역 dict _state → FastAPI lifespan + app.state 패턴으로 전환
    (캡스톤 §2 결정 #5 — 테스트 가능성 + module singleton 의 import 부작용 회피)
  - sources 필드: doc_id/score/snippet 3 종 → Day 2 인덱싱 메타 4 종(source/phase/topic/heading) + score
    Day 5/6 학습자가 "이 답이 어디서 왔나" 를 헤딩 경로(`Phase 4 > vLLM > startupProbe`) 로 즉시 파악
  - 영어 system prompt → 한국어 (prompts.py 의 SYSTEM_PROMPT 로 위임)

본 모듈은 환경변수 6 개를 읽습니다 (.env.example 참조).
로컬 실행:
    uvicorn main:app --reload --port 8001
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from pydantic import BaseModel
from starlette.responses import Response

from llm_client import VLLMClient
from prompts import build_messages
from retriever import QdrantRetriever, RetrievedChunk

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("rag")

# ── 환경변수 (.env.example 와 동기화) ─────────────────────────────────────────
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "rag-docs")
EMBED_MODEL = os.getenv("EMBED_MODEL", "intfloat/multilingual-e5-small")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:8000/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "microsoft/phi-2")
TOP_K_DEFAULT = int(os.getenv("TOP_K", "3"))

# ── Prometheus 메트릭 4 종 (Day 7 ServiceMonitor 가 수집할 라벨) ───────────────
CHAT_COUNT = Counter("rag_chat_total", "Total /chat requests", ["status"])
CHAT_LATENCY = Histogram("rag_chat_latency_seconds", "End-to-end /chat latency seconds")
RETRIEVE_LATENCY = Histogram("rag_retrieve_latency_seconds", "Qdrant retrieval latency seconds")
LLM_LATENCY = Histogram("rag_llm_latency_seconds", "vLLM generation latency seconds")


# ── lifespan: 임베딩 모델 + Qdrant + vLLM 클라이언트 1 회 초기화 ───────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """RAG API 기동 시 1 회 호출. retriever 와 llm 인스턴스를 app.state 에 보관.

    임베딩 모델 로딩은 약 1~2 분(첫 다운로드) 또는 5~10 초(HF_HOME 캐시 hit) 걸립니다.
    이 비용을 요청마다 치르지 않도록 lifespan 으로 캐싱합니다 — lesson.md §10 자주 하는 실수 #15.
    """
    logger.info("Loading embedding model %s and connecting to Qdrant=%s, vLLM=%s",
                EMBED_MODEL, QDRANT_URL, LLM_BASE_URL)
    app.state.retriever = QdrantRetriever(
        url=QDRANT_URL,
        collection=QDRANT_COLLECTION,
        embed_model_name=EMBED_MODEL,
    )
    app.state.llm = VLLMClient(base_url=LLM_BASE_URL, model=LLM_MODEL)
    app.state.ready = True
    logger.info("RAG API ready")
    yield
    logger.info("RAG API shutting down")


app = FastAPI(title="Capstone RAG API", lifespan=lifespan)


# ── Pydantic 스키마 ──────────────────────────────────────────────────────────
class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[Message]
    top_k: int | None = None


class Source(BaseModel):
    """RAG 응답의 출처 1 개. Day 2 인덱싱 메타 4 종 + score + chunk_id 노출."""
    source: str
    phase: str
    topic: str
    heading: str
    score: float
    chunk_id: str


class ChatResponse(BaseModel):
    answer: str
    sources: list[Source]


def _to_source(chunk: RetrievedChunk) -> Source:
    return Source(
        source=chunk.source,
        phase=chunk.phase,
        topic=chunk.topic,
        heading=chunk.heading,
        score=chunk.score,
        chunk_id=chunk.chunk_id,
    )


# ── 라우트 ────────────────────────────────────────────────────────────────────
@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """retrieval → augmentation → generation 흐름 — lesson.md §3.1 시퀀스 7 단계 그대로."""
    if not getattr(app.state, "ready", False):
        CHAT_COUNT.labels(status="not_ready").inc()
        raise HTTPException(status_code=503, detail="RAG API not ready")
    if not req.messages:
        CHAT_COUNT.labels(status="bad_request").inc()
        raise HTTPException(status_code=400, detail="messages cannot be empty")

    # 캡스톤 §2 결정 #8 — last user message 만 사용, multi-turn 합성은 §11 확장 아이디어로
    user_query = req.messages[-1].content
    top_k = req.top_k if req.top_k is not None else TOP_K_DEFAULT

    with CHAT_LATENCY.time():
        try:
            with RETRIEVE_LATENCY.time():
                chunks = app.state.retriever.search(user_query, top_k)

            messages = build_messages(user_query, chunks)

            with LLM_LATENCY.time():
                answer = app.state.llm.chat(messages)
        except Exception as exc:
            logger.exception("Chat failed: %s", exc)
            CHAT_COUNT.labels(status="error").inc()
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    CHAT_COUNT.labels(status="ok").inc()
    return ChatResponse(answer=answer, sources=[_to_source(c) for c in chunks])


@app.get("/healthz")
async def healthz():
    """liveness — 프로세스 응답 가능한지만 확인. Day 6 Deployment 의 livenessProbe 가 호출."""
    return {"status": "ok"}


@app.get("/ready")
async def ready():
    """readiness — lifespan 초기화 완료 여부. Day 6 Deployment 의 readinessProbe 가 호출."""
    if not getattr(app.state, "ready", False):
        raise HTTPException(status_code=503, detail="not ready")
    return {"status": "ready"}


@app.get("/metrics")
async def metrics():
    """Prometheus scrape 대상. Day 7 ServiceMonitor 가 30s 간격으로 호출."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
