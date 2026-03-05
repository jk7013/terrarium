from pydantic import BaseModel, Field


class IndexRequest(BaseModel):
    path: str = Field(default="data/documents/corpus.jsonl", description="색인할 jsonl 경로")
    rebuild: bool = Field(default=False, description="true면 기존 index를 비우고 다시 적재")


class IndexResponse(BaseModel):
    ok: bool
    docs: int
    chunks: int
    elapsed_ms: int


class IndexStatusResponse(BaseModel):
    document_count: int
    chunk_count: int
    latest_chunk_at: str | None = None
