"""
Cross-Encoder 리랭킹 모듈
모델: BAAI/bge-reranker-v2-m3

파이프라인:
  HybridRetriever (bge-m3 + BM25 + RRF, top_k=20)
      -> Reranker (bge-reranker-v2-m3, top_k=5)
      -> LLM 컨텍스트 주입
"""

from __future__ import annotations

import os
from typing import Optional


RERANKER_MODEL  = os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")
RERANKER_DEVICE = os.getenv("RERANKER_DEVICE", "cpu")
MAX_SEQ_LENGTH  = 512


class Reranker:
    """
    Cross-Encoder 기반 리랭커.
    싱글톤 패턴: 모델은 프로세스 내 최초 1회만 로드.
    """

    _instance: Optional[Reranker] = None
    _model = None

    def __new__(cls, model_name: str = RERANKER_MODEL):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._loaded = False
        return cls._instance

    def __init__(self, model_name: str = RERANKER_MODEL):
        if self._loaded:
            return

        from sentence_transformers import CrossEncoder

        print(f"[reranker] 모델 로드 중: {model_name}")
        self._model = CrossEncoder(
            model_name,
            max_length=MAX_SEQ_LENGTH,
            device=RERANKER_DEVICE,
        )
        self._model_name = model_name
        self._loaded = True
        print(f"[reranker] 로드 완료")

    def rerank(
        self,
        query: str,
        candidates: list[dict],
        top_k: int = 5,
    ) -> list[dict]:
        """
        Cross-Encoder 리랭킹.

        Args:
            query:      검색 쿼리
            candidates: HybridRetriever.search() 결과 ('content' 키 필수)
            top_k:      최종 반환 개수

        Returns:
            rerank_score 내림차순 정렬된 상위 top_k개
        """
        if not candidates:
            return []

        pairs = [(query, c["content"]) for c in candidates]

        scores = self._model.predict(
            pairs,
            batch_size=16,
            show_progress_bar=False,
        )

        scored = [
            {**candidate, "rerank_score": float(score)}
            for candidate, score in zip(candidates, scores)
        ]
        scored.sort(key=lambda x: x["rerank_score"], reverse=True)

        return scored[:top_k]


def retrieve_and_rerank(
    query: str,
    top_k: int = 5,
    candidate_k: int = 20,
    source_filter: Optional[str] = None,
    db_url: str | None = None,
) -> list[dict]:
    """
    Hybrid 검색 -> Cross-Encoder 리랭킹 원스텝 인터페이스.
    """
    from app.rag.hybrid_retriever import HybridRetriever

    retriever = HybridRetriever(db_url=db_url)
    reranker  = Reranker()

    candidates = retriever.search(query, top_k=candidate_k, source_filter=source_filter)
    return reranker.rerank(query, candidates, top_k=top_k)


def retrieve_and_rerank_with_trace(
    query: str,
    top_k: int = 5,
    candidate_k: int = 20,
    source_filter: Optional[str] = None,
    db_url: str | None = None,
) -> tuple[list[dict], list[dict]]:
    """
    Hybrid 검색 -> Cross-Encoder 리랭킹 + 파이프라인 단계별 트레이스.

    Returns:
        (final_results, pipeline_stages)
        pipeline_stages = [
            {"name": "Vector Search", "results": [...], "latency_ms": ...},
            {"name": "BM25 Search", ...},
            {"name": "RRF Merge", ...},
            {"name": "Rerank", ...},
        ]
    """
    import time
    from app.rag.hybrid_retriever import HybridRetriever

    retriever = HybridRetriever(db_url=db_url)
    reranker  = Reranker()

    # Hybrid search with trace
    candidates, hybrid_trace = retriever.search_with_trace(
        query, top_k=candidate_k, source_filter=source_filter,
    )

    stages: list[dict] = []

    # Stage 1: Vector Search
    stages.append({
        "name": "Vector Search",
        "description": f"pgvector cosine distance (bge-m3 1024dim), top {len(hybrid_trace['vector_results'])}",
        "count": len(hybrid_trace["vector_results"]),
        "latency_ms": hybrid_trace["embed_ms"] + hybrid_trace["vector_ms"],
        "results": [
            {
                "id": r["id"],
                "content": r["content"],
                "score": r.get("similarity", 0),
                "score_label": "cosine similarity",
                "metadata": r.get("metadata", {}),
            }
            for r in hybrid_trace["vector_results"]
        ],
    })

    # Stage 2: BM25 Search
    stages.append({
        "name": "BM25 Search",
        "description": f"rank_bm25 인메모리 (corpus: {hybrid_trace['bm25_corpus_size']:,}건)",
        "count": len(hybrid_trace["bm25_results"]),
        "latency_ms": hybrid_trace["bm25_ms"],
        "results": [
            {
                "id": r["id"],
                "content": r["content"],
                "score": r.get("bm25_score", 0),
                "score_label": "BM25 score",
                "metadata": r.get("metadata", {}),
            }
            for r in hybrid_trace["bm25_results"]
        ],
    })

    # Stage 3: RRF Merge
    stages.append({
        "name": "RRF Merge",
        "description": f"Reciprocal Rank Fusion (k=60), top {len(hybrid_trace['rrf_results'])}",
        "count": len(hybrid_trace["rrf_results"]),
        "latency_ms": hybrid_trace["rrf_ms"],
        "results": [
            {
                "id": r["id"],
                "content": r["content"],
                "score": r.get("rrf_score", 0),
                "score_label": "RRF score",
                "metadata": r.get("metadata", {}),
            }
            for r in hybrid_trace["rrf_results"]
        ],
    })

    # Stage 4: Cross-Encoder Rerank
    t0 = time.perf_counter()
    reranked = reranker.rerank(query, candidates, top_k=top_k)
    rerank_ms = int((time.perf_counter() - t0) * 1000)

    stages.append({
        "name": "Rerank",
        "description": f"Cross-Encoder ({reranker._model_name}), top {top_k}",
        "count": len(reranked),
        "latency_ms": rerank_ms,
        "results": [
            {
                "id": r["id"],
                "content": r["content"],
                "score": r.get("rerank_score", 0),
                "score_label": "rerank score",
                "metadata": r.get("metadata", {}),
            }
            for r in reranked
        ],
    })

    return reranked, stages
