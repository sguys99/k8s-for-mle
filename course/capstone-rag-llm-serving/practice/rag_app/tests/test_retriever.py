"""QdrantRetriever 단위 테스트 — Qdrant client + 임베딩 모델을 모두 mock 으로 주입.

캡스톤 §2 결정 #4 — pytest 는 인프라 의존성과 분리 (port-forward 불필요).
라이브 검증은 labs/day-05-rag-api-impl.md §Step 7~8 의 curl + uvicorn 으로.

실행:
    cd practice/rag_app
    pytest tests/ -v

5 케이스:
  ① mock 4 개 ScoredPoint 반환 → top_k=3 호출 시 3 개 RetrievedChunk 매핑
  ② payload 4 종 메타데이터(source/phase/topic/heading) 보존 검증
  ③ top_k=0 빈 리스트 / top_k=10 이지만 결과 4 개만 → 4 개 반환
  ④ Qdrant 가 빈 리스트 반환 시 [] 반환 (예외 없음)
  ⑤ e5 모델일 때 embed 호출 인자가 'query: ' 로 시작하는지 spy
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

# tests/ 에서 retriever 모듈을 import 할 수 있도록 부모 디렉터리(rag_app/) 를 sys.path 에 추가.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from retriever import QdrantRetriever, RetrievedChunk  # noqa: E402


def _scored_point(point_id: str, score: float, payload: dict) -> SimpleNamespace:
    """Qdrant client.search() 가 반환하는 ScoredPoint 의 mock 형태.

    실제 라이브러리 객체 대신 SimpleNamespace 로 .id / .score / .payload 만 갖춘 더미.
    QdrantRetriever.search() 는 이 세 속성만 사용합니다.
    """
    return SimpleNamespace(id=point_id, score=score, payload=payload)


def _make_retriever(
    points: list[SimpleNamespace],
    embed_model_name: str = "intfloat/multilingual-e5-small",
) -> tuple[QdrantRetriever, MagicMock, MagicMock]:
    """embed_model + qdrant_client 두 mock 을 주입해 QdrantRetriever 를 생성.

    실제 sentence-transformers 와 qdrant-client 를 import 하지 않으므로 CI 친화적.
    """
    embed_mock = MagicMock()
    # encode() 는 numpy.ndarray 를 반환해야 하지만, list 도 .tolist() 가 없을 뿐 list(vec) 으로 호환.
    embed_mock.encode.return_value = SimpleNamespace(tolist=lambda: [0.1, 0.2, 0.3])

    qdrant_mock = MagicMock()
    qdrant_mock.search.return_value = points

    retriever = QdrantRetriever(
        url="http://mock:6333",
        collection="rag-docs",
        embed_model_name=embed_model_name,
        embed_model=embed_mock,
        qdrant_client=qdrant_mock,
    )
    return retriever, embed_mock, qdrant_mock


# ① mock 4 개 ScoredPoint 반환 → top_k=3 호출 시 3 개 RetrievedChunk 매핑
def test_search_returns_chunks() -> None:
    points = [
        _scored_point(f"id-{i}", 0.9 - i * 0.1, {
            "text": f"chunk text {i}",
            "source": "course/lesson.md",
            "phase": "phase-4",
            "topic": "vllm",
            "heading": "GPU > startupProbe",
        })
        for i in range(4)
    ]
    # Qdrant 는 limit 만큼만 반환하므로 top_k=3 이면 mock 도 3 개로 자른다.
    retriever, _, qdrant_mock = _make_retriever(points[:3])

    result = retriever.search("GPU 어떻게 잡지", top_k=3)

    assert len(result) == 3
    assert all(isinstance(r, RetrievedChunk) for r in result)
    assert result[0].score == pytest.approx(0.9)
    qdrant_mock.search.assert_called_once()
    call_kwargs = qdrant_mock.search.call_args.kwargs
    assert call_kwargs["collection_name"] == "rag-docs"
    assert call_kwargs["limit"] == 3
    assert call_kwargs["with_payload"] is True


# ② payload 4 종 메타데이터(source/phase/topic/heading) 보존 검증
def test_payload_metadata_preserved() -> None:
    points = [_scored_point("id-0", 0.95, {
        "text": "Day 2 인덱싱 시 passage prefix 를 붙입니다.",
        "source": "course/capstone-rag-llm-serving/lesson.md",
        "phase": "capstone",
        "topic": "",
        "heading": "데이터 흐름 > 인덱싱 > e5 prefix",
        "chunk_index": 5,  # ← RetrievedChunk 에 노출되지 않는 필드도 mock 에 포함해 무시 검증
    })]
    retriever, _, _ = _make_retriever(points)

    result = retriever.search("e5 prefix 가 뭐야", top_k=1)

    assert len(result) == 1
    chunk = result[0]
    assert chunk.text == "Day 2 인덱싱 시 passage prefix 를 붙입니다."
    assert chunk.source == "course/capstone-rag-llm-serving/lesson.md"
    assert chunk.phase == "capstone"
    assert chunk.topic == ""
    assert chunk.heading == "데이터 흐름 > 인덱싱 > e5 prefix"
    assert chunk.chunk_id == "id-0"


# ③ top_k=0 빈 리스트 / top_k=10 이지만 결과 4 개만 → 4 개 반환
def test_top_k_boundary() -> None:
    points = [_scored_point(f"id-{i}", 0.9, {"text": f"t{i}"}) for i in range(4)]
    retriever, _, qdrant_mock = _make_retriever(points)

    # top_k=0 — Qdrant 호출 없이 빈 리스트
    result_zero = retriever.search("질문", top_k=0)
    assert result_zero == []
    qdrant_mock.search.assert_not_called()

    # top_k=10 — Qdrant 가 4 개만 반환 → 4 개 그대로 노출 (Qdrant 가 limit 처리)
    result_ten = retriever.search("질문", top_k=10)
    assert len(result_ten) == 4
    qdrant_mock.search.assert_called_once()
    assert qdrant_mock.search.call_args.kwargs["limit"] == 10


# ④ Qdrant 가 빈 리스트 반환 시 [] 반환 (예외 없음)
def test_empty_results() -> None:
    retriever, _, _ = _make_retriever([])

    result = retriever.search("매우 동떨어진 질문", top_k=3)

    assert result == []


# ⑤ e5 모델일 때 embed 호출 인자가 'query: ' 로 시작하는지 spy
def test_e5_query_prefix_applied() -> None:
    retriever, embed_mock, _ = _make_retriever([], embed_model_name="intfloat/multilingual-e5-small")

    retriever.search("K8s GPU 잡는 법", top_k=1)

    # encode() 호출 인자 검증
    embed_mock.encode.assert_called_once()
    args, kwargs = embed_mock.encode.call_args
    encoded_text = args[0] if args else kwargs.get("sentences", "")
    assert encoded_text.startswith("query: "), (
        f"e5 model 인데 query prefix 누락: {encoded_text!r}"
    )
    assert kwargs.get("normalize_embeddings") is True, (
        "Day 2 인덱싱과 동일하게 normalize_embeddings=True 가 들어가야 Cosine 거리 호환"
    )


# 보너스: e5 가 아닌 모델은 prefix 미적용
def test_non_e5_model_no_prefix() -> None:
    retriever, embed_mock, _ = _make_retriever([], embed_model_name="BAAI/bge-small-en")

    retriever.search("질문", top_k=1)

    args, _ = embed_mock.encode.call_args
    encoded_text = args[0]
    assert not encoded_text.startswith("query: "), (
        f"e5 모델이 아닌데 prefix 가 잘못 붙음: {encoded_text!r}"
    )
