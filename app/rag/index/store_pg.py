import asyncio
from typing import Any

from app.rag.index.chunker import chunk_record
from app.rag.index.embedder import embed_chunks
from app.rag.index.keywords import extract_keywords
from app.store.pgvector_store import PgVectorStore


async def index_records_to_pg(
    records: list[dict[str, Any]],
    *,
    rebuild: bool,
    tags: list[str] | None = None,
) -> tuple[int, int]:
    store = PgVectorStore()
    if rebuild:
        await asyncio.to_thread(store.rebuild)
    await asyncio.to_thread(store.ensure_schema)

    doc_ids: set[str] = set()
    chunks_total = 0
    for row in records:
        await asyncio.to_thread(
            store.upsert_document,
            doc_id=row["doc_id"],
            title=row.get("title"),
            filepath=row.get("filepath"),
            fmt=row.get("fmt"),
        )
        chunks = chunk_record(row, chunk_size_chars=900, overlap_chars=180)
        if not chunks:
            continue
        vectors = await embed_chunks([c["text"] for c in chunks])
        for chunk, vec in zip(chunks, vectors):
            chunk["embedding"] = vec
            chunk["keywords"] = extract_keywords(chunk["text"], limit=10)
            chunk["tags"] = list(tags or [])
            chunk["ngram"] = None
        await asyncio.to_thread(store.upsert_chunks, doc_id=row["doc_id"], chunks=chunks)
        doc_ids.add(row["doc_id"])
        chunks_total += len(chunks)
    return len(doc_ids), chunks_total
