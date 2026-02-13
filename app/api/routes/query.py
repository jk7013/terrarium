from fastapi import APIRouter
from app.rag.pipeline import run_rag
from app.api.schemas.query import (
    QueryRequest,
    QueryResponse,
    ContextItem,
    RetrievalTrace,
    LLMTrace,
    QueryMeta,
)


router = APIRouter()


@router.post("/query", response_model=QueryResponse)
async def query_endpoint(request: QueryRequest) -> QueryResponse:
    return await run_rag(request)
