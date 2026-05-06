"""캡스톤 RAG 인덱싱 파이프라인 — 4 단계 + all/search 보조 명령.

이식 출처: course/phase-4-ml-on-k8s/04-argo-workflows/practice/rag_pipeline/pipeline.py
주요 변경:
  - load-docs : 단순 glob → 재귀 + 화이트리스트(`phase-*/**/lesson.md` + `study-roadmap.md`)
  - chunk     : MarkdownHeaderTextSplitter(헤딩 보존) → RecursiveCharacterTextSplitter 2 단계
                메타데이터 4 종 부여(source / phase / topic / heading)
  - embed     : 기본 모델을 `intfloat/multilingual-e5-small` 로 교체 (한국어 다수 자료 대응)
                e5 계열 규약에 따라 입력 텍스트에 `passage:` 접두사 부여
  - upsert    : recreate_collection → create_collection_if_not_exists + upsert (idempotent)
                point ID 는 chunk_id 의 결정론적 UUID(uuid5) — 동일 자료 재실행 시 덮어쓰기
  - all       : 4 단계를 로컬에서 한 줄로 실행
  - search    : Day 2 검증용 보조 — 자연어 쿼리 1 건 → top_k 결과를 JSON 출력

각 subcommand 가 입출력하는 파일(공유 디렉토리 `PIPELINE_DATA_DIR`, 기본 `./.pipeline-data` 또는 `/data`):

  load-docs : DOCS_ROOT/phase-*/**/lesson.md  -> docs.jsonl       (id, source, phase, topic, text)
  chunk     : docs.jsonl                       -> chunks.jsonl     (+ chunk_index, heading)
  embed     : chunks.jsonl                     -> embeddings.jsonl (+ vector[float])
  upsert    : embeddings.jsonl                 -> Qdrant collection (rag-docs)

Day 3 의 Argo Workflow 는 동일 이미지에 subcommand 만 바꿔 4 단계 step 으로 호출합니다.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from pathlib import Path
from typing import Iterable

# ── 경로 / 환경변수 기본값 ────────────────────────────────────────────────────
# 로컬 실행 시: 프로젝트 루트(course/) 에서 호출하면 상대경로 그대로 동작
# 컨테이너 실행 시(Day 3): Dockerfile 의 ENV 가 /docs, /data 로 덮어씀
DATA_DIR = Path(os.environ.get("PIPELINE_DATA_DIR", "./.pipeline-data"))
DOCS_ROOT = Path(os.environ.get("DOCS_ROOT", "course"))
# 로드맵 파일은 DOCS_ROOT 와 별도 위치(`docs/study-roadmap.md`)
ROADMAP_PATH = Path(os.environ.get("ROADMAP_PATH", "docs/study-roadmap.md"))


# ── 공통 유틸 ─────────────────────────────────────────────────────────────────

def _iter_jsonl(path: Path) -> Iterable[dict]:
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def _write_jsonl(path: Path, rows: Iterable[dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            count += 1
    return count


def _extract_phase_topic(rel_path: Path) -> tuple[str, str]:
    """`phase-4-ml-on-k8s/04-argo-workflows/lesson.md` → ("phase-4-ml-on-k8s", "04-argo-workflows").

    캡스톤 자체 파일(`capstone-rag-llm-serving/lesson.md`)은 ("capstone", "") 로 표기.
    로드맵(`docs/study-roadmap.md`)은 ("docs", "study-roadmap") 으로 표기.
    """
    parts = rel_path.parts
    if parts and parts[0].startswith("phase-"):
        # phase-X-*/NN-topic-slug/lesson.md 또는 phase-X-*/lesson.md
        return (parts[0], parts[1] if len(parts) >= 3 else "")
    if parts and parts[0].startswith("capstone-"):
        return ("capstone", "")
    if parts and parts[0] == "study-roadmap.md":
        return ("docs", "study-roadmap")
    return ("unknown", "")


# ── 1단계: 문서 로드 ──────────────────────────────────────────────────────────

def cmd_load_docs(_args: argparse.Namespace) -> None:
    """DOCS_ROOT 에서 화이트리스트 패턴에 해당하는 마크다운만 적재."""
    out = DATA_DIR / "docs.jsonl"
    rows: list[dict] = []

    if not DOCS_ROOT.exists():
        print(f"[load-docs] ERROR: DOCS_ROOT={DOCS_ROOT} 가 존재하지 않습니다.", file=sys.stderr)
        sys.exit(2)

    # phase-*/**/lesson.md — 모든 Phase 의 토픽별 lesson 본문
    lesson_paths = sorted(DOCS_ROOT.glob("phase-*/**/lesson.md"))
    # 캡스톤 lesson 도 자기참조형 검색 대상으로 포함
    lesson_paths += sorted(DOCS_ROOT.glob("capstone-*/lesson.md"))

    for md_path in lesson_paths:
        rel = md_path.relative_to(DOCS_ROOT)
        phase, topic = _extract_phase_topic(rel)
        text = md_path.read_text(encoding="utf-8")
        rows.append({
            "id": str(rel).replace("/", "::"),
            "source": str(md_path),
            "phase": phase,
            "topic": topic,
            "text": text,
        })

    # study-roadmap 별도 추가
    if ROADMAP_PATH.exists():
        text = ROADMAP_PATH.read_text(encoding="utf-8")
        rows.append({
            "id": "docs::study-roadmap.md",
            "source": str(ROADMAP_PATH),
            "phase": "docs",
            "topic": "study-roadmap",
            "text": text,
        })
    else:
        print(f"[load-docs] NOTE: ROADMAP_PATH={ROADMAP_PATH} 미존재 — 건너뜀", file=sys.stderr)

    n = _write_jsonl(out, rows)
    print(f"[load-docs] wrote {n} docs -> {out}")
    if n == 0:
        print("[load-docs] WARNING: 0 docs found. DOCS_ROOT 경로를 확인하세요.", file=sys.stderr)
        sys.exit(2)


# ── 2단계: 청크 분할 ─────────────────────────────────────────────────────────

# (h1, h2, h3) 를 메타로 보존하기 위한 헤더 매핑
_HEADERS_TO_SPLIT_ON = [
    ("#", "h1"),
    ("##", "h2"),
    ("###", "h3"),
]


def _build_heading_path(meta: dict) -> str:
    """split 메타에서 가장 깊은 헤딩까지의 경로를 ` > ` 로 연결."""
    parts = [meta.get(k, "") for k in ("h1", "h2", "h3") if meta.get(k)]
    return " > ".join(parts)


def cmd_chunk(args: argparse.Namespace) -> None:
    """1차: MarkdownHeaderTextSplitter (헤딩 보존) → 2차: RecursiveCharacterTextSplitter."""
    from langchain_text_splitters import (
        MarkdownHeaderTextSplitter,
        RecursiveCharacterTextSplitter,
    )

    src = DATA_DIR / "docs.jsonl"
    out = DATA_DIR / "chunks.jsonl"

    md_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=_HEADERS_TO_SPLIT_ON,
        # 헤딩 라인 자체를 청크 본문에 남겨야 의미가 보존됨 (e5 모델은 짧은 문맥에서 헤딩이 도움됨)
        strip_headers=False,
    )
    char_splitter = RecursiveCharacterTextSplitter(
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
        separators=["\n\n", "\n", " ", ""],
    )

    rows: list[dict] = []
    for doc in _iter_jsonl(src):
        # 1차: 헤딩 단위 분할 → 각 섹션마다 메타데이터(h1/h2/h3) 포함
        sections = md_splitter.split_text(doc["text"])
        for section in sections:
            heading = _build_heading_path(section.metadata)
            # 2차: 문자 길이 기반 추가 분할 (헤딩 섹션이 chunk_size 보다 길면)
            for idx, piece in enumerate(char_splitter.split_text(section.page_content)):
                # 청크 ID 는 doc_id + heading 해시 + 인덱스 — 결정론적
                heading_key = re.sub(r"\s+", "_", heading) or "_root"
                rows.append({
                    "id": f"{doc['id']}::{heading_key}::{idx}",
                    "source": doc["source"],
                    "phase": doc["phase"],
                    "topic": doc["topic"],
                    "heading": heading,
                    "chunk_index": idx,
                    "text": piece,
                })

    n = _write_jsonl(out, rows)
    print(
        f"[chunk] split into {n} chunks "
        f"(md-header → char chunk_size={args.chunk_size}, overlap={args.chunk_overlap}) -> {out}"
    )
    if n == 0:
        print("[chunk] WARNING: 0 chunks produced. docs.jsonl 입력을 확인하세요.", file=sys.stderr)
        sys.exit(2)


# ── 3단계: 임베딩 ────────────────────────────────────────────────────────────

# e5 계열 규약: 인덱싱 시 본문에 `passage:` 접두사, 검색 시 쿼리에 `query:` 접두사를 붙임.
# 접두사가 없으면 e5 의 retrieval 품질이 크게 떨어지므로 상수로 명시.
_E5_PASSAGE_PREFIX = "passage: "
_E5_QUERY_PREFIX = "query: "


def _is_e5_model(name: str) -> bool:
    """모델명에 `e5` 가 포함되면 e5 규약 접두사를 적용."""
    return "e5" in name.lower()


def cmd_embed(args: argparse.Namespace) -> None:
    """sentence-transformers 로 임베딩 생성. 모델은 모듈 레벨에서 1 회만 로드."""
    from sentence_transformers import SentenceTransformer

    src = DATA_DIR / "chunks.jsonl"
    out = DATA_DIR / "embeddings.jsonl"

    print(f"[embed] loading model {args.model} (HF_HOME={os.environ.get('HF_HOME', 'default')})")
    # 1 회 로드 → encode 일괄 처리. 청크 단위로 다시 SentenceTransformer(...) 호출하면
    # 메모리/시간이 청크 수 만큼 곱절로 늘어나는 흔한 실수 (lesson.md §10 참고).
    model = SentenceTransformer(args.model)
    dim = model.get_sentence_embedding_dimension()
    print(f"[embed] embedding dimension={dim}")

    chunks = list(_iter_jsonl(src))
    if not chunks:
        print("[embed] no chunks to embed; exiting.")
        _write_jsonl(out, [])
        return

    use_e5_prefix = _is_e5_model(args.model)
    if use_e5_prefix:
        print(f"[embed] e5 model detected → prefixing inputs with '{_E5_PASSAGE_PREFIX.strip()}'")
    texts = [
        (_E5_PASSAGE_PREFIX + c["text"]) if use_e5_prefix else c["text"]
        for c in chunks
    ]

    # batch_size 32 는 CPU 환경에서도 OOM 없이 안전.
    vectors = model.encode(
        texts,
        batch_size=32,
        show_progress_bar=False,
        normalize_embeddings=True,  # 코사인 거리에 적합하도록 L2 정규화
    )

    rows = (
        {
            "chunk_id": c["id"],
            "source": c["source"],
            "phase": c["phase"],
            "topic": c["topic"],
            "heading": c["heading"],
            "chunk_index": c["chunk_index"],
            "text": c["text"],  # 임베딩에는 prefix 를 줬지만 payload 텍스트는 원문 유지
            "vector": vec.tolist(),
        }
        for c, vec in zip(chunks, vectors)
    )
    n = _write_jsonl(out, rows)
    print(f"[embed] wrote {n} embeddings (dim={dim}) -> {out}")


# ── 4단계: Qdrant Upsert ─────────────────────────────────────────────────────

def _ensure_collection(client, name: str, vector_size: int) -> None:
    """컬렉션이 없으면 생성, 있으면 그대로 둔다 (idempotent).

    Phase 4-4 원본은 `recreate_collection` 으로 매번 컬렉션을 비웠지만, 캡스톤은
    동일 자료 재인덱싱 시 부분 갱신을 허용하기 위해 이 패턴을 채택한다.
    """
    from qdrant_client.http import models as qmodels
    from qdrant_client.http.exceptions import UnexpectedResponse

    try:
        client.get_collection(name)
        # 이미 존재 — 차원 일치 확인만 수행 (불일치 시 학습자에게 명시적 에러)
        info = client.get_collection(name)
        existing_size = info.config.params.vectors.size
        if existing_size != vector_size:
            print(
                f"[upsert] ERROR: collection '{name}' 의 vector size={existing_size} 와 "
                f"입력 차원={vector_size} 가 다릅니다. 모델을 변경했다면 "
                f"`curl -X DELETE http://localhost:6333/collections/{name}` 후 재실행하세요.",
                file=sys.stderr,
            )
            sys.exit(2)
        print(f"[upsert] reusing existing collection '{name}' (size={existing_size})")
    except (UnexpectedResponse, ValueError):
        client.create_collection(
            collection_name=name,
            vectors_config=qmodels.VectorParams(size=vector_size, distance=qmodels.Distance.COSINE),
        )
        print(f"[upsert] created collection '{name}' (size={vector_size}, distance=Cosine)")


def cmd_upsert(args: argparse.Namespace) -> None:
    """embeddings.jsonl 을 Qdrant 컬렉션에 idempotent upsert."""
    from qdrant_client import QdrantClient
    from qdrant_client.http import models as qmodels

    src = DATA_DIR / "embeddings.jsonl"
    qdrant_url = os.environ.get("QDRANT_URL", "http://localhost:6333")
    print(f"[upsert] connecting to {qdrant_url}, collection={args.collection}")
    client = QdrantClient(url=qdrant_url)

    rows = list(_iter_jsonl(src))
    if not rows:
        print("[upsert] no embeddings to upsert; exiting.")
        return

    vector_size = len(rows[0]["vector"])
    _ensure_collection(client, args.collection, vector_size)

    # point ID 는 chunk_id 기반 결정론적 UUID — 동일 자료 재실행 시 덮어쓰기(중복 X)
    points = [
        qmodels.PointStruct(
            id=str(uuid.uuid5(uuid.NAMESPACE_URL, r["chunk_id"])),
            vector=r["vector"],
            payload={
                "source": r["source"],
                "phase": r["phase"],
                "topic": r["topic"],
                "heading": r["heading"],
                "chunk_index": r["chunk_index"],
                "text": r["text"],
            },
        )
        for r in rows
    ]
    client.upsert(collection_name=args.collection, points=points)
    info = client.get_collection(args.collection)
    print(f"[upsert] uploaded {len(points)} points. collection points_count={info.points_count}")


# ── 보조: all (4 단계 일괄 실행) ──────────────────────────────────────────────

def cmd_all(args: argparse.Namespace) -> None:
    """로컬 학습용 — load-docs → chunk → embed → upsert 를 한 번에 실행."""
    print("=" * 60)
    print("[all] step 1/4 — load-docs")
    print("=" * 60)
    cmd_load_docs(args)
    print("=" * 60)
    print("[all] step 2/4 — chunk")
    print("=" * 60)
    cmd_chunk(args)
    print("=" * 60)
    print("[all] step 3/4 — embed")
    print("=" * 60)
    cmd_embed(args)
    print("=" * 60)
    print("[all] step 4/4 — upsert")
    print("=" * 60)
    cmd_upsert(args)
    print("=" * 60)
    print("[all] done — RAG retriever 검증은 `python pipeline.py search --query ...`")
    print("=" * 60)


# ── 보조: search (Day 2 검증용) ──────────────────────────────────────────────

def cmd_search(args: argparse.Namespace) -> None:
    """자연어 쿼리 1 건을 임베딩하여 Qdrant 에 검색, top_k 결과를 JSON 으로 출력."""
    from sentence_transformers import SentenceTransformer
    from qdrant_client import QdrantClient

    qdrant_url = os.environ.get("QDRANT_URL", "http://localhost:6333")
    print(f"[search] model={args.model}, qdrant={qdrant_url}, top_k={args.top_k}", file=sys.stderr)

    model = SentenceTransformer(args.model)
    use_e5_prefix = _is_e5_model(args.model)
    query_text = (_E5_QUERY_PREFIX + args.query) if use_e5_prefix else args.query
    qvec = model.encode([query_text], normalize_embeddings=True)[0].tolist()

    client = QdrantClient(url=qdrant_url)
    hits = client.search(
        collection_name=args.collection,
        query_vector=qvec,
        limit=args.top_k,
        with_payload=True,
    )

    # 사람이 읽기 쉽게 source/heading/score 만 추리고, 본문은 100 자만
    output = [
        {
            "score": float(hit.score),
            "payload": {
                "source": hit.payload.get("source"),
                "phase": hit.payload.get("phase"),
                "topic": hit.payload.get("topic"),
                "heading": hit.payload.get("heading"),
                "preview": (hit.payload.get("text") or "")[:120].replace("\n", " "),
            },
        }
        for hit in hits
    ]
    print(json.dumps(output, ensure_ascii=False, indent=2))


# ── argparse ─────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="캡스톤 RAG 인덱싱 파이프라인 (load-docs / chunk / embed / upsert / all / search)",
    )
    sub = p.add_subparsers(dest="command", required=True)

    # 4 단계 + all 이 공유하는 청크/임베딩 옵션을 한 곳에서 정의 (DRY)
    def _add_chunk_args(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--chunk-size", type=int, default=512)
        sp.add_argument("--chunk-overlap", type=int, default=64)

    def _add_embed_args(sp: argparse.ArgumentParser) -> None:
        sp.add_argument(
            "--model",
            default=os.environ.get("EMBED_MODEL", "intfloat/multilingual-e5-small"),
        )

    def _add_upsert_args(sp: argparse.ArgumentParser) -> None:
        sp.add_argument(
            "--collection",
            default=os.environ.get("QDRANT_COLLECTION", "rag-docs"),
        )

    sub.add_parser("load-docs", help="DOCS_ROOT/phase-*/**/lesson.md → docs.jsonl").set_defaults(
        func=cmd_load_docs,
    )

    p_chunk = sub.add_parser("chunk", help="docs.jsonl → chunks.jsonl (md-header + char splitter)")
    _add_chunk_args(p_chunk)
    p_chunk.set_defaults(func=cmd_chunk)

    p_embed = sub.add_parser("embed", help="chunks.jsonl → embeddings.jsonl")
    _add_embed_args(p_embed)
    p_embed.set_defaults(func=cmd_embed)

    p_upsert = sub.add_parser("upsert", help="embeddings.jsonl → Qdrant collection")
    _add_upsert_args(p_upsert)
    p_upsert.set_defaults(func=cmd_upsert)

    p_all = sub.add_parser("all", help="4 단계 일괄 실행 (로컬 학습용)")
    _add_chunk_args(p_all)
    _add_embed_args(p_all)
    _add_upsert_args(p_all)
    p_all.set_defaults(func=cmd_all)

    p_search = sub.add_parser("search", help="자연어 쿼리 1 건을 검색하여 top_k 결과 JSON 출력")
    p_search.add_argument("--query", required=True, help="검색할 자연어 질문")
    p_search.add_argument("--top-k", type=int, default=3)
    _add_embed_args(p_search)
    _add_upsert_args(p_search)
    p_search.set_defaults(func=cmd_search)

    return p


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
