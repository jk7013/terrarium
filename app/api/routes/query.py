import os

import httpx

from fastapi import APIRouter, HTTPException, Request
from app.rag.pipeline import run_rag, retrieve_only
from app.api.schemas.query import (
    QueryRequest,
    QueryResponse,
    RetrieveRequest,
    RetrieveResponse,
    ContextItem,
    RetrievalTrace,
    LLMTrace,
    QueryMeta,
)
from app.llm.client import DEFAULT_MODEL, is_openai_model


router = APIRouter()
OFFLINE_MODE = os.getenv("OFFLINE_MODE", "true").lower() == "true"
_INTERNAL_PROFILE_HEADER = "X-Jido-Internal"
_PUBLIC_PROFILES = {"fast", "default", "quality"}
_INTERNAL_ONLY_PROFILES = {"corpus_seed"}


def _resolve_allowed_profile(requested_profile: str, internal_request: bool) -> str:
    profile = (requested_profile or "default").strip().lower() or "default"
    if profile in _PUBLIC_PROFILES:
        return profile
    if profile in _INTERNAL_ONLY_PROFILES:
        if internal_request:
            return profile
        raise HTTPException(400, detail={
            "error_code": "UNSUPPORTED_PROFILE",
            "message": "지원하지 않는 retrieval profile입니다.",
        })
    return "default"


@router.get("/models")
async def list_models():
    """
    UI 드롭다운용 모델 목록.
    OpenAI 추천 모델 + Ollama 로컬 모델 목록을 함께 노출한다.
    검색/임베딩은 별도 인프라를 쓰더라도, 생성 모델 선택은 이 목록을 기준으로 한다.
    """
    models = []

    ollama_model = os.getenv("OLLAMA_MODEL", "qwen3:4b")
    seen_ids: set[str] = set()

    def add_model(model_id: str, name: str, provider: str) -> None:
        if not model_id or model_id in seen_ids:
            return
        seen_ids.add(model_id)
        models.append({
            "id": model_id,
            "name": name,
            "provider": provider,
        })

    if os.getenv("OPENAI_API_KEY") and not OFFLINE_MODE:
        for model_id, name in [
            ("gpt-4o-mini", "GPT-4o Mini"),
            ("o4-mini", "o4-mini"),
        ]:
            add_model(model_id, name, "openai")

    add_model(ollama_model, ollama_model, "ollama")

    ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=2.0)) as client:
            resp = await client.get(f"{ollama_host}/api/tags")
            resp.raise_for_status()
            data = resp.json()
        for item in data.get("models", []):
            name = item.get("name")
            if not name:
                continue
            add_model(name, name, "ollama")
    except Exception:
        # Ollama 목록 조회가 실패해도 최소 fallback 모델은 노출한다.
        pass

    default_model = DEFAULT_MODEL
    if default_model and is_openai_model(default_model) and OFFLINE_MODE:
        default_model = ollama_model
    if not any(model["id"] == default_model for model in models):
        default_model = models[0]["id"] if models else ollama_model

    return {
        "models": models,
        "default": default_model,
    }


@router.post("/query", response_model=QueryResponse)
async def query_endpoint(request: QueryRequest, http_request: Request) -> QueryResponse:
    profile = _resolve_allowed_profile(request.profile, http_request.headers.get(_INTERNAL_PROFILE_HEADER) == "1")
    return await run_rag(request.model_copy(update={"profile": profile}))


@router.post("/retrieve", response_model=RetrieveResponse)
async def retrieve_endpoint(request: RetrieveRequest, http_request: Request) -> RetrieveResponse:
    profile = _resolve_allowed_profile(request.profile, http_request.headers.get(_INTERNAL_PROFILE_HEADER) == "1")
    trace_id, contexts, retrieval_trace, meta, pipeline_stages = await retrieve_only(
        request.query,
        profile=profile,
        top_k=request.options.top_k,
        final_contexts=request.options.final_contexts,
        source=request.source,
    )
    return RetrieveResponse(
        trace_id=trace_id,
        query=request.query,
        contexts=contexts,
        retrieval_trace=retrieval_trace,
        meta=meta,
        pipeline_stages=pipeline_stages,
    )
