"""FastAPI 모델 서빙 — Phase 0 / 01-docker-fastapi-model.

엔드포인트:
- POST /predict   : 추론
- GET  /healthz   : liveness (모델 로딩 여부 무관)
- GET  /ready     : readiness (모델 로딩 완료 시 200)
- GET  /metrics   : Prometheus 메트릭

환경 변수:
- MODEL_NAME : HuggingFace 모델 ID (기본: cardiffnlp/twitter-roberta-base-sentiment)
- APP_VERSION: 앱 버전 식별자 (기본: "unknown"). Phase 1/02의 롤링 업데이트 실습에서
               같은 이미지를 v1/v2 두 태그로 띄우면서 /ready 응답으로 구별할 때 사용합니다.
"""
from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from pydantic import BaseModel
from starlette.responses import Response
from transformers import pipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("serving")

MODEL_NAME = os.getenv("MODEL_NAME", "cardiffnlp/twitter-roberta-base-sentiment")
APP_VERSION = os.getenv("APP_VERSION", "unknown")

# Prometheus 메트릭 — Phase 3의 Grafana 대시보드에서 그대로 사용합니다.
REQUEST_COUNT = Counter(
    "predict_requests_total", "Total /predict requests", ["status"]
)
REQUEST_LATENCY = Histogram(
    "predict_latency_seconds", "Latency of /predict in seconds"
)

# 전역 상태 — 모델은 무겁기 때문에 lifespan에서 한 번만 로드합니다.
_state: dict[str, Any] = {"model": None, "ready": False}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱 시작 시 모델을 로드하고, 종료 시 정리합니다."""
    logger.info("Loading model: %s", MODEL_NAME)
    t0 = time.time()
    _state["model"] = pipeline("text-classification", model=MODEL_NAME)
    _state["ready"] = True
    logger.info("Model loaded in %.2fs", time.time() - t0)
    yield
    logger.info("Shutting down")


app = FastAPI(title="Phase 0 Sentiment API", lifespan=lifespan)


class PredictRequest(BaseModel):
    text: str


class PredictResponse(BaseModel):
    label: str
    score: float


@app.post("/predict", response_model=PredictResponse)
async def predict(req: PredictRequest):
    if not _state["ready"]:
        REQUEST_COUNT.labels(status="not_ready").inc()
        raise HTTPException(status_code=503, detail="Model is loading")

    with REQUEST_LATENCY.time():
        try:
            result = _state["model"](req.text)[0]
        except Exception as exc:
            logger.exception("Prediction failed")
            REQUEST_COUNT.labels(status="error").inc()
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    REQUEST_COUNT.labels(status="ok").inc()
    return PredictResponse(label=result["label"], score=float(result["score"]))


@app.get("/healthz")
async def healthz():
    """K8s livenessProbe용 — 프로세스가 떠 있으면 항상 200을 반환합니다."""
    return {"status": "ok"}


@app.get("/ready")
async def ready():
    """K8s readinessProbe용 — 모델 로딩이 끝나야 200을 반환합니다."""
    if not _state["ready"]:
        raise HTTPException(status_code=503, detail="Model not ready")
    return {"status": "ready", "model": MODEL_NAME, "version": APP_VERSION}


@app.get("/metrics")
async def metrics():
    """Prometheus가 스크래핑할 엔드포인트입니다."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
