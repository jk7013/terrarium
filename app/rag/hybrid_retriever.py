"""
Terrarium 하이브리드 검색 모듈
bge-m3 벡터 + BM25 + RRF (k=60)

실제 Terrarium DB 스키마 기준:
  - chunks.chunk_id, chunks.text, chunks.tags (source 필터: 'law' = ANY(tags))
  - chunks.embedding VECTOR(1024)
"""

import os
from typing import Optional
import time

import psycopg
import requests
from rank_bm25 import BM25Okapi

from app.db.connection import get_db_url

OLLAMA_URL  = os.getenv("OLLAMA_HOST", "http://localhost:11434")
EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "bge-m3")
RRF_K       = 60
CANDIDATE_K = 20
_BM25_CACHE: dict[str, dict] = {}


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{float(v):.8f}" for v in values) + "]"


def embed_query(text: str) -> list[float]:
    """쿼리 -> bge-m3 임베딩"""
    resp = requests.post(
        f"{OLLAMA_URL}/api/embeddings",
        json={"model": EMBED_MODEL, "prompt": text},
        timeout=60,
    )
    if resp.status_code == 404:
        resp = requests.post(
            f"{OLLAMA_URL}/api/embed",
            json={"model": EMBED_MODEL, "input": text},
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()["embeddings"][0]
    resp.raise_for_status()
    return resp.json()["embedding"]


def tokenize(text: str) -> list[str]:
    """BM25 토크나이저 (공백 분리)"""
    return text.split()


class HybridRetriever:
    """
    chunks 테이블 기반 하이브리드 검색.
    - 벡터: pgvector cosine distance (bge-m3 1024dim)
    - BM25: rank_bm25 인메모리 인덱스
    - RRF: Reciprocal Rank Fusion (k=60)

    source 필터: tags 배열에 'law' 포함 여부로 필터링
    """

    def __init__(self, db_url: str | None = None):
        self.db_url = db_url or get_db_url()
        self._bm25: Optional[BM25Okapi] = None
        self._chunk_ids: list[str] = []
        self._chunk_texts: list[str] = []
        self._chunk_meta: list[dict] = []
        self._current_filter: Optional[str] = None
        self._bm25_load_ms: int = 0

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self.db_url)

    def _load_chunks(self, source_filter: Optional[str] = None, reload_bm25: bool = False):
        """BM25 인메모리 인덱스 구성. source_filter별 캐시 사용."""
        cache_key = source_filter or "__all__"
        if not reload_bm25 and cache_key in _BM25_CACHE:
            cached = _BM25_CACHE[cache_key]
            self._bm25 = cached["bm25"]
            self._chunk_ids = list(cached["chunk_ids"])
            self._chunk_texts = list(cached["chunk_texts"])
            self._chunk_meta = list(cached["chunk_meta"])
            self._current_filter = source_filter
            self._bm25_load_ms = 0
            return

        started = time.perf_counter()
        with self._connect() as conn:
            with conn.cursor() as cur:
                if source_filter:
                    cur.execute("""
                        SELECT c.chunk_id, c.text,
                               c.article_title, c.article_number, c.section_title,
                               c.tags, c.keywords,
                               d.filepath
                        FROM chunks c
                        JOIN documents d ON d.doc_id = c.doc_id
                        WHERE %s = ANY(c.tags)
                    """, (source_filter,))
                else:
                    cur.execute("""
                        SELECT c.chunk_id, c.text,
                               c.article_title, c.article_number, c.section_title,
                               c.tags, c.keywords,
                               d.filepath
                        FROM chunks c
                        JOIN documents d ON d.doc_id = c.doc_id
                        WHERE NOT ('regulation' = ANY(c.tags))
                    """)
                rows = cur.fetchall()

        chunk_ids = [r[0] for r in rows]
        chunk_texts = [r[1] for r in rows]
        chunk_meta = [
            {
                "article_title":  r[2],
                "article_number": r[3],
                "section_title":  r[4],
                "tags":           r[5] or [],
                "keywords":       r[6] or [],
                "filepath":       r[7],
                "source":         "law" if r[5] and "law" in r[5] else "other",
            }
            for r in rows
        ]
        tokenized = [tokenize(c) for c in chunk_texts]
        bm25 = BM25Okapi(tokenized)
        self._bm25_load_ms = int((time.perf_counter() - started) * 1000)

        _BM25_CACHE[cache_key] = {
            "bm25": bm25,
            "chunk_ids": chunk_ids,
            "chunk_texts": chunk_texts,
            "chunk_meta": chunk_meta,
        }
        self._bm25 = bm25
        self._chunk_ids = chunk_ids
        self._chunk_texts = chunk_texts
        self._chunk_meta = chunk_meta
        self._current_filter = source_filter

    def _vector_search(
        self,
        query_vec: list[float],
        top_k: int,
        source_filter: Optional[str] = None,
    ) -> list[dict]:
        """pgvector cosine distance 검색"""
        vec_str = _vector_literal(query_vec)

        with self._connect() as conn:
            with conn.cursor() as cur:
                if source_filter:
                    cur.execute("""
                        SELECT c.chunk_id, c.text,
                               c.article_title, c.article_number, c.section_title,
                               c.tags, d.filepath,
                               1 - (c.embedding <=> %s::vector) AS similarity
                        FROM chunks c
                        JOIN documents d ON d.doc_id = c.doc_id
                        WHERE %s = ANY(c.tags)
                          AND c.embedding IS NOT NULL
                        ORDER BY c.embedding <=> %s::vector
                        LIMIT %s
                    """, (vec_str, source_filter, vec_str, top_k))
                else:
                    cur.execute("""
                        SELECT c.chunk_id, c.text,
                               c.article_title, c.article_number, c.section_title,
                               c.tags, d.filepath,
                               1 - (c.embedding <=> %s::vector) AS similarity
                        FROM chunks c
                        JOIN documents d ON d.doc_id = c.doc_id
                        WHERE c.embedding IS NOT NULL
                          AND NOT ('regulation' = ANY(c.tags))
                        ORDER BY c.embedding <=> %s::vector
                        LIMIT %s
                    """, (vec_str, vec_str, top_k))

                rows = cur.fetchall()

        return [
            {
                "id":         r[0],
                "content":    r[1],
                "metadata":   {
                    "article_title": r[2],
                    "article_number": r[3],
                    "section_title": r[4],
                    "tags": r[5] or [],
                    "filepath": r[6],
                    "source": "law" if r[5] and "law" in r[5] else "other",
                },
                "similarity": float(r[7]),
            }
            for r in rows
        ]

    def _bm25_search(self, query: str, top_k: int) -> list[dict]:
        """BM25 인메모리 검색"""
        scores = self._bm25.get_scores(tokenize(query))
        ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]

        return [
            {
                "id":         self._chunk_ids[i],
                "content":    self._chunk_texts[i],
                "metadata":   self._chunk_meta[i],
                "bm25_score": float(scores[i]),
            }
            for i in ranked
        ]

    @staticmethod
    def _rrf_merge(
        vector_results: list[dict],
        bm25_results: list[dict],
        k: int = RRF_K,
        top_k: int = 5,
    ) -> list[dict]:
        """Reciprocal Rank Fusion: score(d) = 1/(k+rank_vec) + 1/(k+rank_bm25)"""
        scores: dict[str, float] = {}
        meta_map: dict[str, dict] = {}
        content_map: dict[str, str] = {}

        for rank, r in enumerate(vector_results):
            cid = r["id"]
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)
            meta_map[cid]    = r["metadata"]
            content_map[cid] = r["content"]

        for rank, r in enumerate(bm25_results):
            cid = r["id"]
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)
            if cid not in meta_map:
                meta_map[cid]    = r["metadata"]
                content_map[cid] = r["content"]

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]

        return [
            {
                "id":        cid,
                "content":   content_map[cid],
                "metadata":  meta_map[cid],
                "rrf_score": score,
            }
            for cid, score in ranked
        ]

    def search(
        self,
        query: str,
        top_k: int = 5,
        source_filter: Optional[str] = None,
        reload_bm25: bool = False,
        candidate_k: int = CANDIDATE_K,
    ) -> list[dict]:
        """
        하이브리드 검색 메인 인터페이스.

        Args:
            query:         검색 쿼리
            top_k:         최종 반환 개수
            source_filter: 'law' | None(전체)
            reload_bm25:   청크 추가 후 BM25 재구성 시 True
        """
        if self._bm25 is None or reload_bm25 or self._current_filter != source_filter:
            self._load_chunks(source_filter, reload_bm25=reload_bm25)

        query_vec = embed_query(query)
        vector_results = self._vector_search(query_vec, candidate_k, source_filter)
        bm25_results   = self._bm25_search(query, candidate_k)

        return self._rrf_merge(vector_results, bm25_results, k=RRF_K, top_k=top_k)

    def search_with_trace(
        self,
        query: str,
        top_k: int = 5,
        source_filter: Optional[str] = None,
        reload_bm25: bool = False,
        candidate_k: int = CANDIDATE_K,
    ) -> tuple[list[dict], dict]:
        """
        하이브리드 검색 + 각 단계 트레이스 반환.

        Returns:
            (rrf_results, trace_dict)
            trace_dict = {
                "vector_results": [...],
                "bm25_results": [...],
                "rrf_results": [...],
                "bm25_corpus_size": int,
            }
        """
        import time

        if self._bm25 is None or reload_bm25 or self._current_filter != source_filter:
            self._load_chunks(source_filter, reload_bm25=reload_bm25)

        t0 = time.perf_counter()
        query_vec = embed_query(query)
        embed_ms = int((time.perf_counter() - t0) * 1000)

        t0 = time.perf_counter()
        vector_results = self._vector_search(query_vec, candidate_k, source_filter)
        vector_ms = int((time.perf_counter() - t0) * 1000)

        t0 = time.perf_counter()
        bm25_results = self._bm25_search(query, candidate_k)
        bm25_ms = int((time.perf_counter() - t0) * 1000)

        t0 = time.perf_counter()
        rrf_results = self._rrf_merge(vector_results, bm25_results, k=RRF_K, top_k=top_k)
        rrf_ms = int((time.perf_counter() - t0) * 1000)

        trace = {
            "vector_results": vector_results,
            "bm25_results": bm25_results,
            "rrf_results": rrf_results,
            "bm25_corpus_size": len(self._chunk_ids),
            "embed_ms": embed_ms,
            "vector_ms": vector_ms,
            "bm25_ms": bm25_ms,
            "rrf_ms": rrf_ms,
            "bm25_load_ms": self._bm25_load_ms,
        }

        return rrf_results, trace

    def search_vector_only(
        self,
        query: str,
        top_k: int = 5,
        source_filter: Optional[str] = None,
    ) -> list[dict]:
        """벡터 검색만"""
        query_vec = embed_query(query)
        return self._vector_search(query_vec, top_k, source_filter)
