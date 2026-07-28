import asyncio
import time

from fastapi import APIRouter, HTTPException

from app.api.schemas.index import IndexRequest, IndexResponse, IndexStatusResponse
from app.rag.index.loaders import load_jsonl_records
from app.rag.index.store_pg import index_records_to_pg
from app.store.pgvector_store import PgVectorStore


router = APIRouter()


@router.post("/index", response_model=IndexResponse)
async def index_documents(request: IndexRequest) -> IndexResponse:
    started = time.perf_counter()
    try:
        records = await asyncio.to_thread(load_jsonl_records, request.path)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"인덱싱 준비 실패: {str(e)}") from e

    try:
        indexed_docs, indexed_chunks = await index_records_to_pg(
            records,
            rebuild=request.rebuild,
            tags=request.tags,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"인덱싱 실행 실패: {str(e)}") from e

    return IndexResponse(
        ok=True,
        docs=indexed_docs,
        chunks=indexed_chunks,
        elapsed_ms=int((time.perf_counter() - started) * 1000),
    )


@router.get("/index/status", response_model=IndexStatusResponse)
async def index_status() -> IndexStatusResponse:
    store = PgVectorStore()
    await asyncio.to_thread(store.ensure_schema)
    status = await asyncio.to_thread(store.status)
    return IndexStatusResponse(**status)
