"""RAG 인덱싱 파이프라인 — 4단계를 단일 진입점으로 묶은 구현.

각 subcommand 는 다음 파일을 입력/출력합니다(공유 PVC `/data` 기준):

  load-docs : /docs/*.md            -> /data/docs.jsonl       (id, source, text)
  chunk     : /data/docs.jsonl      -> /data/chunks.jsonl     (id, source, text, chunk_index)
  embed     : /data/chunks.jsonl    -> /data/embeddings.jsonl (chunk_id, source, text, vector[float])
  upsert    : /data/embeddings.jsonl -> Qdrant collection(rag-docs)

Argo Workflow 의 각 단계가 같은 이미지를 띄워 subcommand 만 바꿔 호출합니다.
한 단계가 실패하면 그 이후 단계는 자동으로 Skipped 상태가 되어 재시도가 단계 단위로 깔끔합니다.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Iterable

DATA_DIR = Path(os.environ.get("PIPELINE_DATA_DIR", "/data"))
DOCS_DIR = Path(os.environ.get("PIPELINE_DOCS_DIR", "/docs"))


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


# --- 1단계: 문서 로드 ---------------------------------------------------------

def cmd_load_docs(_args: argparse.Namespace) -> None:
    """`/docs` 의 .md 파일을 모두 읽어 docs.jsonl 로 적재."""
    out = DATA_DIR / "docs.jsonl"
    rows = []
    for md_path in sorted(DOCS_DIR.glob("*.md")):
        text = md_path.read_text(encoding="utf-8")
        rows.append({
            "id": md_path.stem,
            "source": str(md_path.name),
            "text": text,
        })
    n = _write_jsonl(out, rows)
    print(f"[load-docs] wrote {n} docs -> {out}")
    if n == 0:
        print("[load-docs] WARNING: 0 docs found. Did you copy sample_docs/ into the image?")
        sys.exit(2)


# --- 2단계: 청크 분할 ---------------------------------------------------------

def cmd_chunk(args: argparse.Namespace) -> None:
    """RecursiveCharacterTextSplitter 로 청크 분할."""
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    src = DATA_DIR / "docs.jsonl"
    out = DATA_DIR / "chunks.jsonl"
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
        separators=["\n\n", "\n", " ", ""],
    )

    rows = []
    for doc in _iter_jsonl(src):
        for idx, chunk in enumerate(splitter.split_text(doc["text"])):
            rows.append({
                "id": f"{doc['id']}::{idx}",
                "source": doc["source"],
                "chunk_index": idx,
                "text": chunk,
            })
    n = _write_jsonl(out, rows)
    print(f"[chunk] split into {n} chunks (size={args.chunk_size}, overlap={args.chunk_overlap}) -> {out}")


# --- 3단계: 임베딩 ------------------------------------------------------------

def cmd_embed(args: argparse.Namespace) -> None:
    """sentence-transformers 로 임베딩 생성."""
    from sentence_transformers import SentenceTransformer

    src = DATA_DIR / "chunks.jsonl"
    out = DATA_DIR / "embeddings.jsonl"

    print(f"[embed] loading model {args.model} (HF_HOME={os.environ.get('HF_HOME', 'default')})")
    model = SentenceTransformer(args.model)
    dim = model.get_sentence_embedding_dimension()
    print(f"[embed] embedding dimension={dim}")

    chunks = list(_iter_jsonl(src))
    texts = [c["text"] for c in chunks]
    if not texts:
        print("[embed] no chunks to embed; exiting.")
        _write_jsonl(out, [])
        return

    # batch_size 32 는 CPU 환경에서도 OOM 없이 안전. 임베딩은 64 차원 단위로 처리해도 충분.
    vectors = model.encode(texts, batch_size=32, show_progress_bar=False, normalize_embeddings=True)

    rows = (
        {
            "chunk_id": c["id"],
            "source": c["source"],
            "chunk_index": c["chunk_index"],
            "text": c["text"],
            "vector": vec.tolist(),
        }
        for c, vec in zip(chunks, vectors)
    )
    n = _write_jsonl(out, rows)
    print(f"[embed] wrote {n} embeddings (dim={dim}) -> {out}")


# --- 4단계: Qdrant Upsert -----------------------------------------------------

def cmd_upsert(args: argparse.Namespace) -> None:
    """Qdrant 에 컬렉션 생성(없으면) 후 임베딩 upsert."""
    from qdrant_client import QdrantClient
    from qdrant_client.http import models as qmodels

    src = DATA_DIR / "embeddings.jsonl"
    qdrant_url = os.environ.get("QDRANT_URL", "http://qdrant:6333")
    print(f"[upsert] connecting to {qdrant_url}, collection={args.collection}")
    client = QdrantClient(url=qdrant_url)

    rows = list(_iter_jsonl(src))
    if not rows:
        print("[upsert] no embeddings to upsert; exiting.")
        return

    vector_size = len(rows[0]["vector"])

    # recreate_collection: 학습용으로 매번 깨끗하게 다시 만든다.
    # 운영에서는 add 모드(create_collection_if_not_exists + upsert) 가 안전합니다.
    client.recreate_collection(
        collection_name=args.collection,
        vectors_config=qmodels.VectorParams(size=vector_size, distance=qmodels.Distance.COSINE),
    )

    points = [
        qmodels.PointStruct(
            id=str(uuid.uuid5(uuid.NAMESPACE_URL, r["chunk_id"])),
            vector=r["vector"],
            payload={"source": r["source"], "chunk_index": r["chunk_index"], "text": r["text"]},
        )
        for r in rows
    ]
    client.upsert(collection_name=args.collection, points=points)
    info = client.get_collection(args.collection)
    print(f"[upsert] uploaded {len(points)} points. collection vectors_count={info.points_count}")


# --- argparse -----------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="RAG 인덱싱 파이프라인 (load-docs / chunk / embed / upsert)")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("load-docs", help="/docs/*.md -> /data/docs.jsonl").set_defaults(func=cmd_load_docs)

    p_chunk = sub.add_parser("chunk", help="/data/docs.jsonl -> /data/chunks.jsonl")
    p_chunk.add_argument("--chunk-size", type=int, default=512)
    p_chunk.add_argument("--chunk-overlap", type=int, default=64)
    p_chunk.set_defaults(func=cmd_chunk)

    p_embed = sub.add_parser("embed", help="/data/chunks.jsonl -> /data/embeddings.jsonl")
    p_embed.add_argument("--model", default="sentence-transformers/all-MiniLM-L6-v2")
    p_embed.set_defaults(func=cmd_embed)

    p_upsert = sub.add_parser("upsert", help="/data/embeddings.jsonl -> Qdrant")
    p_upsert.add_argument("--collection", default="rag-docs")
    p_upsert.set_defaults(func=cmd_upsert)

    return p


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
