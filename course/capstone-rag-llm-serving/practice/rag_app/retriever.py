"""Qdrant 벡터 검색 — Day 1 의 StatefulSet + Day 2 의 인덱싱 결과를 호출.

이식 출처: .claude/skills/k8s-ml-course-author/assets/templates/practice/rag_app.py.tmpl 의 _retrieve()
변경:
  - 함수 _retrieve() → 클래스 QdrantRetriever 로 캡슐화
    (단위 테스트에서 임베딩 모델·Qdrant 클라이언트를 mock 으로 주입 가능)
  - 임베딩 모델은 생성자에서 1 회만 로드 (lesson.md §10 자주 하는 실수 #15 — 요청마다 재로딩 폭증)
  - e5 query prefix 'query: ' 자동 부여
    Day 2 인덱싱 시 'passage: ' prefix 가 붙었으므로 검색 시 쌍을 맞춰야 recall 정상
    (Day 2 pipeline.py 의 _is_e5_model + _E5_QUERY_PREFIX 패턴과 동일)
  - 응답에 메타데이터 4 종(source / phase / topic / heading) + chunk_id 노출
    Day 5/6 RAG API 의 sources 필드 + prompts.py 의 build_context 가 그대로 사용
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# qdrant-client 와 sentence-transformers 는 main.py / 테스트 fixture 에서만 import.
# 본 모듈은 라이브러리 의존성을 함수 시그니처에 노출하지 않고 클래스 책임만 정의.


_E5_QUERY_PREFIX = "query: "


def _is_e5_model(name: str) -> bool:
    """e5 계열 모델이면 query prefix 적용.

    Day 2 pipeline.py 의 동명 함수와 정확히 같은 규칙 — 인덱싱과 검색이 같은 prefix 정책을 공유해야
    recall 이 정상이 됩니다.
    """
    return "e5" in name.lower()


@dataclass
class RetrievedChunk:
    """검색 결과 1 개 — Qdrant point 를 RAG API 응답 친화 형태로 변환.

    필드는 Day 2 의 인덱싱 payload 6 종(source / phase / topic / heading / chunk_index / text) 중
    chunk_index 를 제외한 5 종 + score + chunk_id 로 구성합니다. chunk_index 는 RAG 응답에
    노출할 가치가 작아 (학습자가 보는 라벨은 heading 으로 충분) 생략합니다.
    """
    text: str
    score: float
    source: str
    phase: str
    topic: str
    heading: str
    chunk_id: str


class QdrantRetriever:
    """Qdrant 컬렉션 검색기.

    생성자에서 임베딩 모델 + Qdrant 클라이언트를 1 회 로드.
    search() 호출마다 모델을 다시 만들지 않습니다 — main.py 의 lifespan 에서 본 클래스를
    1 회만 인스턴스화하면 충분합니다.
    """

    def __init__(
        self,
        url: str,
        collection: str,
        embed_model_name: str,
        embed_model: Any | None = None,
        qdrant_client: Any | None = None,
    ) -> None:
        """
        Args:
            url: Qdrant base URL. 로컬 개발 시 'http://localhost:6333' (port-forward),
                 클러스터 내부에서는 'http://qdrant.rag-llm.svc:6333'.
            collection: Day 2 인덱싱이 적재한 컬렉션 이름. 기본 'rag-docs'.
            embed_model_name: sentence-transformers 모델 ID. 기본 'intfloat/multilingual-e5-small'
                              (Day 2 결정 — 384 dim, 한국어 다수 자료 대응).
            embed_model: (테스트 전용) 사전 생성된 SentenceTransformer 인스턴스를 주입.
                         None 이면 본 생성자가 직접 로드.
            qdrant_client: (테스트 전용) 사전 생성된 QdrantClient 를 주입. None 이면 직접 생성.
        """
        self.collection = collection
        self.embed_model_name = embed_model_name
        self._use_e5_prefix = _is_e5_model(embed_model_name)

        if embed_model is None:
            from sentence_transformers import SentenceTransformer

            self.embed_model = SentenceTransformer(embed_model_name)
        else:
            self.embed_model = embed_model

        if qdrant_client is None:
            from qdrant_client import QdrantClient

            self.client = QdrantClient(url=url)
        else:
            self.client = qdrant_client

    def _encode_query(self, query: str) -> list[float]:
        """검색 쿼리 1 개를 e5 prefix 적용 후 임베딩 → list[float] 반환.

        normalize_embeddings=True 는 Day 2 인덱싱과 동일 — Cosine 거리 호환을 위함.
        """
        prefixed = (_E5_QUERY_PREFIX + query) if self._use_e5_prefix else query
        vec = self.embed_model.encode(prefixed, normalize_embeddings=True)
        # numpy.ndarray → list 변환 (Qdrant client 호환)
        return vec.tolist() if hasattr(vec, "tolist") else list(vec)

    def search(self, query: str, top_k: int) -> list[RetrievedChunk]:
        """자연어 쿼리 1 건을 Qdrant 에 검색하여 top_k 청크를 반환.

        top_k <= 0 이면 빈 리스트를 즉시 반환 (Qdrant 호출 없이).
        Qdrant 응답이 빈 리스트면 빈 리스트를 그대로 반환 — 호출자가 sources=[] 응답을 만듭니다.
        """
        if top_k <= 0:
            return []

        qvec = self._encode_query(query)
        hits = self.client.search(
            collection_name=self.collection,
            query_vector=qvec,
            limit=top_k,
            with_payload=True,
        )

        chunks: list[RetrievedChunk] = []
        for hit in hits:
            payload = hit.payload or {}
            chunks.append(
                RetrievedChunk(
                    text=str(payload.get("text", "")),
                    score=float(hit.score),
                    source=str(payload.get("source", "")),
                    phase=str(payload.get("phase", "")),
                    topic=str(payload.get("topic", "")),
                    heading=str(payload.get("heading", "")),
                    chunk_id=str(hit.id),
                )
            )
        return chunks
