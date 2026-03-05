import asyncio
import os

from app.api.schemas.query import ContextItem
from app.llm.client import embed_texts
from app.store.pgvector_store import PgVectorStore


async def retrieve_top_k(query: str, top_k: int) -> tuple[list[ContextItem], list[dict]]:
    if top_k <= 0:
        top_k = int(os.getenv("RAG_TOP_K", "6"))
    query_embedding = (await embed_texts([query]))[0]
    store = PgVectorStore()
    rows = await asyncio.to_thread(store.search_cosine, query_embedding, top_k)

    contexts: list[ContextItem] = []
    vector_results: list[dict] = []
    for row in rows:
        similarity = max(0.0, 1.0 - row.distance)
        preview = row.text[:120].replace("\n", " ")
        contexts.append(
            ContextItem(
                chunk_id=row.chunk_id,
                document_id=row.doc_id,
                text=row.text,
                score=similarity,
                meta={
                    "filepath": row.filepath,
                    "page_no": row.page_no,
                    "chunk_no": row.chunk_no,
                    "distance": row.distance,
                },
            )
        )
        vector_results.append(
            {
                "chunk_id": row.chunk_id,
                "score": similarity,
                "distance": row.distance,
                "doc_id": row.doc_id,
                "filepath": row.filepath,
                "page_no": row.page_no,
                "chunk_no": row.chunk_no,
                "text_preview": preview,
            }
        )
    return contexts, vector_results
