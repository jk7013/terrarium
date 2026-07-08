"""
/api/search 엔드포인트
검색 모드: vector | hybrid | rerank
소스 필터: law | zuzu | None(전체)
expand=true 시 법령 연계법령 확장
"""

from fastapi import APIRouter, Query

router = APIRouter()


@router.get("/search")
async def search_endpoint(
    q: str = Query(..., description="검색 쿼리"),
    mode: str = Query("vector", description="검색 모드: vector | hybrid | rerank"),
    source: str | None = Query(None, description="소스 필터: law | zuzu | None(전체)"),
    top_k: int = Query(5, description="반환 개수"),
    expand: bool = Query(False, description="법령 연계법령 확장 여부"),
    profile: str = Query("default", description="검색 프로파일: fast | default | quality"),
):
    """
    검색 API.
    - mode=vector  : 기존 pgvector cosine distance 검색
    - mode=hybrid  : BM25 + 벡터 + RRF
    - mode=rerank  : hybrid + Cross-Encoder 리랭킹
    - expand=true  : law 결과에 대해 같은 조 + 연계법령 확장
    """
    import asyncio
    import time

    start = time.perf_counter()
    profile_name = profile if profile in {"fast", "default", "quality"} else "default"
    candidate_k = {"fast": max(top_k * 2, 8), "default": max(top_k * 4, 20), "quality": max(top_k * 6, 30)}[profile_name]

    if mode == "vector":
        from app.rag.hybrid_retriever import HybridRetriever
        retriever = HybridRetriever()
        results = await asyncio.to_thread(
            retriever.search_vector_only, q, top_k, source
        )

    elif mode == "hybrid":
        from app.rag.hybrid_retriever import HybridRetriever
        retriever = HybridRetriever()
        results = await asyncio.to_thread(
            retriever.search, q, top_k, source, False, candidate_k
        )

    elif mode == "rerank":
        from app.rag.reranker import retrieve_and_rerank
        results = await asyncio.to_thread(
            retrieve_and_rerank, q, top_k, candidate_k, source
        )

    else:
        return {"error": f"지원하지 않는 mode: {mode}. (vector | hybrid | rerank)"}

    # 법령 연계법령 확장
    if expand:
        from app.rag.law_expander import LawExpander
        expander = LawExpander()
        results = await asyncio.to_thread(expander.expand, results)

    elapsed_ms = int((time.perf_counter() - start) * 1000)

    return {
        "query": q,
        "mode": mode,
        "source": source,
        "top_k": top_k,
        "expand": expand,
        "profile": profile_name,
        "count": len(results),
        "latency_ms": elapsed_ms,
        "results": results,
    }
