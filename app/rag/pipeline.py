import logging
import asyncio
import uuid
import time
import os
import json
import re
import psycopg
from datetime import datetime, timezone
"""
2.	RAG 파이프라인 (app/rag/pipeline.py)
	•	run_rag(request: QueryRequest) -> QueryResponse
	•	내부에서:
	•	쿼리 전처리/확장
	•	retriever 호출 (app/rag/retriever.py)
	•	reranker 호출 (bge-reranker 같은 거)
	•	context 선택
	•	LLM 호출(app/llm/client.py)
	•	trace 채우기
	•	최종적으로 QueryResponse 직접 만들어서 반환
"""

from app.api.schemas.query import (
    QueryRequest,
    QueryResponse,
    ContextItem,
    RetrievalTrace,
    LLMTrace,
    QueryMeta,
)
from app.llm.client import call_llm, OLLAMA_HOST, OLLAMA_MODEL, DEFAULT_MODEL
from app.tools.weather import get_weather, is_weather_query
from app.tools.time import get_current_time, is_time_query
from app.rag.retriever import retrieve_top_k
from app.db.connection import get_db_url
from app.store.pgvector_store import PgVectorStore
import httpx

logger = logging.getLogger(__name__)
DEBUG_LOG_PATH = os.getenv("DEBUG_LOG_PATH", "")
OFFLINE_MODE = os.getenv("OFFLINE_MODE", "true").lower() == "true"

RAG_TOP_K = int(os.getenv("RAG_TOP_K", "6"))
RAG_MAX_CONTEXT_CHARS = int(os.getenv("RAG_MAX_CONTEXT_CHARS", "6000"))

PROFILE_CONFIGS = {
    "fast": {
        "candidate_k": 10,
        "final_contexts": 2,
        "use_rerank": False,
        "use_law_expansion": False,
        "label": "빠른 응답",
    },
    "default": {
        "candidate_k": 20,
        "final_contexts": 3,
        "use_rerank": True,
        "use_law_expansion": True,
        "label": "기본",
    },
    "quality": {
        "candidate_k": 36,
        "final_contexts": 5,
        "use_rerank": True,
        "use_law_expansion": True,
        "label": "정밀 검색",
    },
    "corpus_seed": {
        "candidate_k": 100,
        "final_contexts": 12,
        "use_rerank": False,
        "use_law_expansion": False,
        "label": "코퍼스 시드 (내부)",
    },
}

LAW_QUERY_ARTICLE_RE = re.compile(r"^(?P<law>.+?)\s*제\s*(?P<num>\d+)\s*조(?:의\s*(?P<sub>\d+))?$")
LAW_QUERY_ARTICLE_RE_COMPACT = re.compile(r"^(?P<law>.+?)제(?P<num>\d+)조(?:의(?P<sub>\d+))?$")
LAW_QUERY_REGULATION_TOKENS = ("시행령", "시행규칙", "규칙", "시행")


def _collapse_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _strip_spaces(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def normalize_law_query(query: str) -> str:
    normalized = _collapse_spaces(query)
    normalized = re.sub(r"제\s+(\d+)\s+조", r"제\1조", normalized)
    normalized = re.sub(r"(\S)\s+(\d+)조", r"\1 제\2조", normalized)
    normalized = normalized.replace("대한민국 헌법", "대한민국헌법")
    normalized = re.sub(r"\s*제\s*(\d+)\s*조\s*의\s*(\d+)", r" 제\1조의\2", normalized)
    normalized = re.sub(r"\s*제\s*(\d+)\s*조", r" 제\1조", normalized)
    return _collapse_spaces(normalized)


def _extract_law_query_parts(query: str) -> dict:
    normalized = normalize_law_query(query)
    compact = _strip_spaces(normalized)
    match = LAW_QUERY_ARTICLE_RE.match(normalized) or LAW_QUERY_ARTICLE_RE_COMPACT.match(compact)
    law_name = ""
    article_number = None
    article_sub_number = None
    if match:
        law_name = _strip_spaces(match.group("law"))
        article_number = int(match.group("num"))
        sub = match.group("sub")
        article_sub_number = int(sub) if sub else None
    return {
        "original_query": query,
        "normalized_query": normalized,
        "normalized_compact": compact,
        "law_name_norm": law_name,
        "article_number": article_number,
        "article_sub_number": article_sub_number,
        "explicit_regulation": any(token in normalized for token in LAW_QUERY_REGULATION_TOKENS),
    }


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{float(v):.8f}" for v in values) + "]"


def _law_article_display_text(row: dict) -> str:
    title = str(row.get("law_name") or "").strip()
    citation = str(row.get("article_citation") or "").strip()
    article_title = str(row.get("article_title") or "").strip()
    article_text = str(row.get("article_text") or "").strip()
    header = " ".join(part for part in (title, citation, article_title) if part).strip()
    if header and article_text:
        return f"{header}\n{article_text}"
    return header or article_text


def _law_query_keywords(query: str) -> list[str]:
    normalized = normalize_law_query(query)
    tokens = re.findall(r"[0-9A-Za-z가-힣]+", normalized)
    unique: list[str] = []
    for token in tokens:
        token = token.strip()
        if token and token not in unique:
            unique.append(token)
    return unique


def _count_token_text_hits(tokens: list[str], text: str) -> int:
    compact_text = _strip_spaces(text)
    if not compact_text:
        return 0
    return sum(1 for token in tokens if token and token in compact_text)


def _score_law_keyword_candidate(
    *,
    query: str,
    query_keywords: list[str],
    law_name: str,
    article_title: str,
    article_citation: str,
    keywords: list[str],
) -> tuple[float, dict]:
    overlap_count = len(set(query_keywords) & set(keywords or []))
    query_compact = _strip_spaces(query)
    title_compact = _strip_spaces(article_title)
    citation_compact = _strip_spaces(article_citation)
    title_exact = bool(title_compact and query_compact == title_compact)
    title_contains_query = bool(title_compact and query_compact and query_compact in title_compact)
    citation_contains_query = bool(citation_compact and query_compact and query_compact in citation_compact)
    title_token_hits = _count_token_text_hits(query_keywords, article_title)
    compound_hits = sum(1 for token in query_keywords if len(token) >= 4 and token in (keywords or []))

    score = float(overlap_count)
    if title_exact:
        score += 4.0
    elif title_contains_query:
        score += 2.5
    if citation_contains_query:
        score += 1.0
    score += title_token_hits * 0.8
    score += compound_hits * 0.7

    details = {
        "raw_overlap": overlap_count,
        "title_exact": title_exact,
        "title_contains_query": title_contains_query,
        "citation_contains_query": citation_contains_query,
        "title_token_hits": title_token_hits,
        "compound_hits": compound_hits,
        "law_name": law_name,
        "keyword_score": score,
    }
    return score, details


def _fetch_law_exact_candidates(query: str, limit: int = 8) -> list[dict]:
    info = _extract_law_query_parts(query)
    if not info["law_name_norm"]:
        return []

    law_name_norm = info["law_name_norm"]
    explicit_regulation = info["explicit_regulation"]
    article_number = info["article_number"]
    article_sub_number = info["article_sub_number"]

    where_parts = [
        "is_current = TRUE",
        "regexp_replace(law_name, '\\s+', '', 'g') = %s",
    ]
    params: list[object] = [law_name_norm]

    if article_number is not None:
        where_parts.append("article_number = %s")
        params.append(article_number)

    if article_sub_number is not None:
        where_parts.append("coalesce(article_citation, '') ~ %s")
        params.append(rf"제{article_number}조의{article_sub_number}")

    if not explicit_regulation:
        where_parts.append("law_name !~ '(시행령|시행규칙|규칙)'")

    params.append(limit)
    sql = f"""
        SELECT
            article_pk,
            law_name,
            article_title,
            article_citation,
            article_text,
            article_number,
            article_key,
            keywords,
            is_current
        FROM law_article
        WHERE {' AND '.join(where_parts)}
        ORDER BY
            CASE WHEN article_number IS NULL THEN 1 ELSE 0 END,
            article_number ASC NULLS LAST,
            article_key ASC NULLS LAST
        LIMIT %s
    """

    with psycopg.connect(get_db_url(), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

    candidates: list[dict] = []
    for row in rows:
        payload = {
            "article_pk": row[0],
            "law_name": row[1],
            "article_title": row[2],
            "article_citation": row[3],
            "article_text": row[4],
            "article_number": row[5],
            "article_key": row[6],
            "keywords": row[7] or [],
            "is_current": row[8],
        }
        candidates.append({
            "id": payload["article_pk"],
            "content": _law_article_display_text(payload),
            "rrf_score": 3.0,
            "rerank_score": 3.0,
            "similarity": 3.0,
            "metadata": {
                "article_number": payload["article_number"],
                "article_key": payload["article_key"],
                "article_title": payload["article_title"],
                "article_citation": payload["article_citation"],
                "section_title": payload["law_name"],
                "law_name": payload["law_name"],
                "keywords": payload["keywords"],
                "tags": ["law"],
                "filepath": f"law://{payload['law_name']}",
                "source": "law",
                "is_current": payload["is_current"],
            },
        })
    return candidates


def apply_law_aware_rerank(
    query: str,
    results: list[dict],
    *,
    top_k: int,
    source: str | None,
    exact_candidates: list[dict] | None = None,
    seed_exact_candidates: bool = True,
) -> tuple[list[dict], dict]:
    info = _extract_law_query_parts(query)
    if source != "law" or not results:
        return results[:top_k], {**info, "law_rerank_applied": False}

    merged_results: list[dict] = []
    seen_ids: set[str] = set()
    for item in results:
        chunk_id = item.get("id", "")
        if not chunk_id or chunk_id in seen_ids:
            continue
        seen_ids.add(chunk_id)
        merged_results.append(item)

    if exact_candidates is None and seed_exact_candidates:
        exact_candidates = _fetch_law_exact_candidates(query)
    elif exact_candidates is None:
        exact_candidates = []
    for item in exact_candidates:
        chunk_id = item.get("id", "")
        if not chunk_id or chunk_id in seen_ids:
            continue
        seen_ids.add(chunk_id)
        merged_results.append(item)

    results = merged_results

    base_law_exact_exists = False
    for result in results:
        meta = result.get("metadata") or {}
        section_norm = _strip_spaces(meta.get("section_title", ""))
        if info["law_name_norm"] and section_norm == info["law_name_norm"] and not any(token in section_norm for token in LAW_QUERY_REGULATION_TOKENS):
            base_law_exact_exists = True
            break

    rescored: list[dict] = []
    for result in results:
        meta = dict(result.get("metadata") or {})
        base_score = result.get("rerank_score", result.get("rrf_score", result.get("similarity", 0.0)))
        section_norm = _strip_spaces(meta.get("section_title", ""))
        article_number = meta.get("article_number")
        article_key = str(meta.get("article_key") or "")

        law_exact = bool(info["law_name_norm"] and section_norm == info["law_name_norm"])
        law_partial = bool(section_norm and section_norm in info["normalized_compact"])
        article_exact = bool(info["article_number"] and article_number == info["article_number"])
        article_sub_exact = bool(
            info["article_sub_number"] is not None
            and article_key
            and article_key[-3:-1].isdigit()
            and int(article_key[-3:-1]) == info["article_sub_number"]
        )
        regulation_penalty_applied = bool(
            base_law_exact_exists
            and not info["explicit_regulation"]
            and any(token in section_norm for token in LAW_QUERY_REGULATION_TOKENS)
        )

        law_match_boost = 0.0
        if law_exact and info["article_number"] is not None:
            law_match_boost = 2.4
        elif law_exact:
            law_match_boost = 1.5
        elif law_partial:
            law_match_boost = 0.8

        article_match_boost = 0.0
        if article_exact:
            article_match_boost += 2.6
        if article_sub_exact:
            article_match_boost += 0.8

        regulation_penalty = -0.85 if regulation_penalty_applied else 0.0
        final_score = base_score + law_match_boost + article_match_boost + regulation_penalty

        meta["match_flags"] = {
            "law_exact_match": law_exact,
            "law_partial_match": law_partial,
            "article_exact_match": article_exact,
            "article_sub_exact_match": article_sub_exact,
            "law_match_boost": law_match_boost,
            "article_match_boost": article_match_boost,
            "regulation_penalty_applied": regulation_penalty_applied,
            "regulation_penalty": regulation_penalty,
            "law_rerank_score": final_score,
        }

        rescored.append({
            **result,
            "metadata": meta,
            "law_rerank_score": final_score,
        })

    rescored.sort(key=lambda item: item.get("law_rerank_score", 0.0), reverse=True)
    return rescored[:top_k], {**info, "law_rerank_applied": True}


def retrieve_law_article_candidates_with_trace(
    query: str,
    *,
    candidate_k: int,
    top_k: int,
    use_rerank: bool,
) -> tuple[list[dict], list[dict]]:
    from app.rag.hybrid_retriever import embed_query

    query_vec = embed_query(query)
    vec_str = _vector_literal(query_vec)
    keyword_terms = _law_query_keywords(query)

    vector_sql = """
        SELECT
            article_pk,
            law_name,
            article_title,
            article_citation,
            article_text,
            article_number,
            article_key,
            keywords,
            is_current,
            1 - (embedding <=> %s::vector) AS similarity
        FROM law_article
        WHERE is_current = TRUE
          AND embedding IS NOT NULL
        ORDER BY embedding <=> %s::vector
        LIMIT %s
    """
    keyword_sql = """
        SELECT
            article_pk,
            law_name,
            article_title,
            article_citation,
            article_text,
            article_number,
            article_key,
            keywords,
            is_current,
            CARDINALITY(ARRAY(
                SELECT unnest(coalesce(keywords, '{}'::text[]))
                INTERSECT
                SELECT unnest(%s::text[])
            )) AS keyword_hits
        FROM law_article
        WHERE is_current = TRUE
          AND keywords && %s::text[]
        ORDER BY keyword_hits DESC, article_number ASC NULLS LAST, article_key ASC NULLS LAST
        LIMIT %s
    """

    started = time.perf_counter()
    with psycopg.connect(get_db_url(), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(vector_sql, (vec_str, vec_str, candidate_k))
            vector_rows = cur.fetchall()
            if keyword_terms:
                keyword_limit = max(candidate_k * 4, 40)
                cur.execute(keyword_sql, (keyword_terms, keyword_terms, keyword_limit))
                keyword_rows = cur.fetchall()
            else:
                keyword_rows = []
    vector_ms = int((time.perf_counter() - started) * 1000)

    def _row_to_candidate(row: tuple, *, score_key: str, score_index: int) -> dict:
        payload = {
            "article_pk": row[0],
            "law_name": row[1],
            "article_title": row[2],
            "article_citation": row[3],
            "article_text": row[4],
            "article_number": row[5],
            "article_key": row[6],
            "keywords": row[7] or [],
            "is_current": row[8],
        }
        return {
            "id": payload["article_pk"],
            "content": _law_article_display_text(payload),
            "metadata": {
                "article_number": payload["article_number"],
                "article_key": payload["article_key"],
                "article_title": payload["article_title"],
                "article_citation": payload["article_citation"],
                "section_title": payload["law_name"],
                "law_name": payload["law_name"],
                "keywords": payload["keywords"],
                "tags": ["law"],
                "filepath": f"law://{payload['law_name']}",
                "source": "law",
                "is_current": payload["is_current"],
            },
            score_key: float(row[score_index]),
        }

    exact_results = _fetch_law_exact_candidates(query, limit=min(top_k, 8))
    vector_results = [_row_to_candidate(row, score_key="similarity", score_index=9) for row in vector_rows]
    keyword_results = []
    for row in keyword_rows:
        candidate = _row_to_candidate(row, score_key="bm25_score", score_index=9)
        payload_keywords = list(row[7] or [])
        score, details = _score_law_keyword_candidate(
            query=query,
            query_keywords=keyword_terms,
            law_name=row[1],
            article_title=str(row[2] or ""),
            article_citation=str(row[3] or ""),
            keywords=payload_keywords,
        )
        candidate["bm25_score"] = score
        candidate["metadata"]["keyword_match"] = details
        keyword_results.append(candidate)
    keyword_results.sort(key=lambda item: item.get("bm25_score", 0.0), reverse=True)
    keyword_results = keyword_results[:candidate_k]

    merged: list[dict] = []
    seen_ids: set[str] = set()
    for group in (exact_results, vector_results, keyword_results):
        for item in group:
            cid = item.get("id", "")
            if not cid or cid in seen_ids:
                continue
            seen_ids.add(cid)
            merged.append(item)

    stages = [
        {
            "name": "Law Article Exact",
            "description": "법령명/조문번호 정확 매칭",
            "count": len(exact_results),
            "latency_ms": 0,
            "results": [{"id": r["id"], "content": r["content"], "score": 1, "score_label": "exact", "metadata": r.get("metadata", {})} for r in exact_results],
        },
        {
            "name": "Law Article Vector",
            "description": f"law_article dense vector, top {len(vector_results)}",
            "count": len(vector_results),
            "latency_ms": vector_ms,
            "results": [{"id": r["id"], "content": r["content"], "score": r.get("similarity", 0), "score_label": "cosine similarity", "metadata": r.get("metadata", {})} for r in vector_results],
        },
        {
            "name": "Law Article Keyword",
            "description": "law_article keywords overlap",
            "count": len(keyword_results),
            "latency_ms": 0,
            "results": [{"id": r["id"], "content": r["content"], "score": r.get("bm25_score", 0), "score_label": "keyword overlap", "metadata": r.get("metadata", {})} for r in keyword_results],
        },
    ]

    final_results = merged
    if use_rerank and merged:
        from app.rag.reranker import Reranker

        reranker = Reranker()
        rerank_started = time.perf_counter()
        final_results = reranker.rerank(query, merged, top_k=candidate_k)
        rerank_ms = int((time.perf_counter() - rerank_started) * 1000)
        stages.append({
            "name": "Law Article Rerank",
            "description": f"Cross-Encoder ({reranker._model_name}), top {min(candidate_k, len(final_results))}",
            "count": len(final_results),
            "latency_ms": rerank_ms,
            "results": [{"id": r["id"], "content": r["content"], "score": r.get("rerank_score", 0), "score_label": "rerank score", "metadata": r.get("metadata", {})} for r in final_results],
        })

    final_results, law_rerank_info = apply_law_aware_rerank(query, final_results, top_k=top_k, source="law")
    if law_rerank_info.get("law_rerank_applied"):
        stages.append({
            "name": "Law-aware Rerank",
            "description": f"normalized: {law_rerank_info['normalized_query']}",
            "count": len(final_results),
            "latency_ms": 0,
            "results": [{"id": r.get("id", ""), "content": r.get("content", ""), "score": r.get("law_rerank_score", 0), "score_label": "law rerank", "metadata": r.get("metadata", {})} for r in final_results],
        })

    return final_results[:top_k], stages


def resolve_profile(profile: str, top_k: int, final_contexts: int) -> tuple[str, dict]:
    profile_name = profile if profile in PROFILE_CONFIGS else "default"
    config = dict(PROFILE_CONFIGS[profile_name])
    config["top_k"] = max(top_k, 1)
    config["candidate_k"] = max(config["candidate_k"], config["top_k"])
    requested_final = final_contexts if final_contexts and final_contexts > 0 else config["final_contexts"]
    config["final_contexts"] = max(1, min(requested_final, config["candidate_k"]))
    return profile_name, config


def _extend_pipeline_stages_from_hybrid(pipeline_stages: list[dict], hybrid_trace: dict) -> None:
    pipeline_stages.extend([
        {"name": "Vector Search", "count": len(hybrid_trace["vector_results"]),
         "latency_ms": hybrid_trace["embed_ms"] + hybrid_trace["vector_ms"],
         "results": [{"id": r["id"], "content": r["content"], "score": r.get("similarity", 0), "score_label": "cosine", "metadata": r.get("metadata", {})} for r in hybrid_trace["vector_results"]]},
        {"name": "BM25 Search", "count": len(hybrid_trace["bm25_results"]),
         "latency_ms": hybrid_trace["bm25_ms"] + hybrid_trace.get("bm25_load_ms", 0),
         "description": f"BM25 corpus {hybrid_trace.get('bm25_corpus_size', 0):,}건",
         "results": [{"id": r["id"], "content": r["content"], "score": r.get("bm25_score", 0), "score_label": "BM25", "metadata": r.get("metadata", {})} for r in hybrid_trace["bm25_results"]]},
        {"name": "RRF Merge", "count": len(hybrid_trace["rrf_results"]),
         "latency_ms": hybrid_trace["rrf_ms"],
         "results": [{"id": r["id"], "content": r["content"], "score": r.get("rrf_score", 0), "score_label": "RRF", "metadata": r.get("metadata", {})} for r in hybrid_trace["rrf_results"]]},
    ])


def _build_retrieval_trace(
    query: str,
    *,
    vector_results: list[dict] | None = None,
) -> RetrievalTrace:
    return RetrievalTrace(
        query_expansions=_expand_query(query),
        bm25_results=[],
        vector_results=vector_results or [],
        reranked_results=[],
    )


def _limit_contexts_by_chars(
    contexts: list[ContextItem],
    *,
    max_chars: int,
) -> list[ContextItem]:
    total = 0
    selected: list[ContextItem] = []
    for ctx in contexts:
        text_len = len(ctx.text)
        if selected and total + text_len > max_chars:
            break
        selected.append(ctx)
        total += text_len
    return selected


def _build_llm_error_trace(message: str, latency_ms: float, model: str | None = None) -> LLMTrace:
    return LLMTrace(
        model=model or DEFAULT_MODEL,
        prompt="",
        output=message,
        latency_ms=latency_ms,
        input_tokens=None,
        output_tokens=None,
    )


def _debug_log(hypothesis_id: str, location: str, message: str, data: dict) -> None:
    payload = {
        "id": f"log_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}",
        "timestamp": int(time.time() * 1000),
        "runId": "regulation-routing-fix",
        "hypothesisId": hypothesis_id,
        "location": location,
        "message": message,
        "data": data,
    }
    # region agent log
    try:
        with open(DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass
    # endregion


def _has_law_context(contexts: list[ContextItem]) -> bool:
    """컨텍스트 중 law 태그가 있는 것이 하나라도 있으면 True"""
    return any(
        c.meta and "law" in (c.meta.get("tags") or [])
        for c in contexts
    )


def _is_weather_tool_context(contexts: list[ContextItem]) -> bool:
    if not contexts:
        return False
    if len(contexts) != 1:
        return False
    ctx = contexts[0]
    source = str(ctx.meta.get("source", "")) if ctx.meta else ""
    return ctx.document_id == "weather_tool" or source == "accuweather"


async def _safe_call_llm(
    request: QueryRequest,
    contexts: list[ContextItem],
    trace_id: str,
    *,
    error_prefix: str,
    fallback_answer: str | None = None,
) -> tuple[LLMTrace, str, str]:
    model = request.model
    try:
        llm_trace, answer = await _call_llm_with_context(request, contexts)
        return llm_trace, answer, "success"
    except httpx.TimeoutException as e:
        logger.error(
            "LLM call timeout",
            extra={"trace_id": trace_id, "error": str(e), "timeout_seconds": 300, "context": error_prefix},
            exc_info=True,
        )
        llm_trace = _build_llm_error_trace(
            f"LLM 응답 시간 초과. {error_prefix}",
            300000,
            model=model,
        )
    except httpx.ConnectError as e:
        logger.error(
            "LLM server connection failed",
            extra={"trace_id": trace_id, "error": str(e), "host": OLLAMA_HOST, "context": error_prefix},
            exc_info=True,
        )
        from app.llm.client import is_openai_model
        if model and is_openai_model(model):
            msg = f"OpenAI API 연결 실패. API 키와 네트워크를 확인해주세요."
        else:
            msg = f"Ollama 서버에 연결할 수 없습니다. 서버가 실행 중인지 확인해주세요. (호스트: {OLLAMA_HOST})"
        llm_trace = _build_llm_error_trace(msg, 0.0, model=model)
    except Exception as e:
        logger.error(
            "LLM call failed",
            extra={"trace_id": trace_id, "error": str(e), "error_type": type(e).__name__, "context": error_prefix},
            exc_info=True,
        )
        llm_trace = _build_llm_error_trace(f"LLM 호출 실패: {str(e)}", 0.0, model=model)

    answer = fallback_answer if fallback_answer is not None else llm_trace.output
    return llm_trace, answer, "error"

def _expand_query(query: str) -> list[str]:
    """
    v0 쿼리 확장 (LLM 없이 규칙 기반).

    - 원 쿼리를 항상 포함한다.
    - 반말/정중 표현 등 자주 쓰는 꼬리 표현을 단순 제거한 버전을 추가한다.
    - "어떻게" 같은 표현을 "절차", "방법" 등으로 치환한 버전을 추가한다.
    - 나중에 형태소 분석기/동의어 사전 기반 로직으로 교체할 수 있다.
    """
    base = (query or "").strip()
    expansions: list[str] = []
    if not base:
        return expansions

    # 1) 원 쿼리 그대로
    expansions.append(base)

    # 2) 자주 쓰는 꼬리 표현 제거 버전
    polite_suffixes = [
        " 알려줘",
        " 알려 줘",
        " 알려 주세요",
        " 알려줘요",
        " 알려주세요",
        " 해줘",
        " 해 줘",
        " 해 주세요",
        " 해줘요",
        " 해주세요",
    ]
    for suffix in polite_suffixes:
        if base.endswith(suffix):
            core = base[: -len(suffix)].strip()
            if core and core not in expansions:
                expansions.append(core)

    # 3) "어떻게" → "절차"/"방법" 치환 버전
    if "어떻게" in base:
        replaced_procedure = base.replace("어떻게", "절차")
        replaced_method = base.replace("어떻게", "방법")
        for cand in (replaced_procedure, replaced_method):
            cand = cand.strip()
            if cand and cand not in expansions:
                expansions.append(cand)

    # 4) 도메인 동의어 기반 치환 버전 (사규/인사 도메인 예시)
    synonym_groups = [
        # 퇴직 관련
        ["퇴직금", "퇴직급여"],
        # 출장/여비
        ["출장비", "여비"],
        # 휴가/연차
        ["연차", "연가", "휴가"],
        # 성과급
        ["성과급", "경영평가 성과급"],
        # 스톡옵션/주식매수선택권
        ["스톡옵션", "주식매수선택권"],
        # 투자계약
        ["투자계약서", "투자계약", "투자자 동의권"],
        # 벤처/스타트업
        ["스타트업", "벤처기업"],
    ]
    for group in synonym_groups:
        for term in group:
            if term in base:
                for alt in group:
                    if alt == term:
                        continue
                    cand = base.replace(term, alt).strip()
                    if cand and cand not in expansions:
                        expansions.append(cand)

    # 5) 중복 제거
    seen: set[str] = set()
    unique: list[str] = []
    for q in expansions:
        if q not in seen:
            seen.add(q)
            unique.append(q)

    return unique

def _build_ephemeral_contexts(request: QueryRequest) -> list[ContextItem]:
    """
    ephemeral 모드에서 컨텍스트 목록을 만들어준다.

    v0:
    - raw_text 전체를 하나의 청크로 본다.
    - 나중에 여기서 청킹 로직을 교체/확장한다.
    """
    text = request.raw_text or ""
    if not text:
        return []

    context = ContextItem(
        chunk_id="c_1",
        document_id="d_ephemeral",
        text=text,
        score=1.0,
        meta={},
    )
    return [context]

async def _call_llm_with_tool_context(
    request: QueryRequest,
    tool_info: str,
    tool_name: str,
    tool_meta: dict,
    trace_id: str,
) -> tuple[LLMTrace, str, str, list[ContextItem]]:
    """
    툴 정보를 LLM 컨텍스트로 전달하여 답변 생성.
    모든 툴이 일관되게 LLM에 컨텍스트로 전달되도록 보장하는 공통 함수.
    
    Args:
        request: 쿼리 요청
        tool_info: 툴에서 가져온 정보 문자열
        tool_name: 툴 이름 (예: "weather", "time")
        tool_meta: 툴 메타데이터
        trace_id: 트레이스 ID
        
    Returns:
        tuple[LLMTrace, str, str, list[ContextItem]]: (LLM 트레이스, 답변, 상태, 컨텍스트)
    """
    # 툴 정보를 컨텍스트로 변환
    tool_context = ContextItem(
        chunk_id=f"{tool_name}_1",
        document_id=f"{tool_name}_tool",
        text=tool_info,
        score=1.0,
        meta=tool_meta,
    )
    contexts = [tool_context]
    
    llm_trace, answer, status = await _safe_call_llm(
        request,
        contexts,
        trace_id,
        error_prefix=f"{tool_name} 정보는 가져왔지만 답변 생성에 실패했습니다.",
        fallback_answer=tool_info,
    )

    return llm_trace, answer, status, contexts


async def _call_llm_with_context(
    request: QueryRequest, contexts: list[ContextItem]
) -> tuple[LLMTrace, str]:
    """
    실제 LLM 호출 (Ollama).

    - 컨텍스트와 질문을 조합해서 프롬프트를 만들고
    - app.llm.client의 call_llm을 호출한다.
    - 대화 히스토리가 있으면 멀티턴 대화로 처리한다.
    """
    # 컨텍스트 텍스트 조합
    context_text = ""
    if contexts:
        context_parts = [ctx.text for ctx in contexts]
        context_text = "\n\n".join(context_parts)
    
    # 프롬프트 구성
    if context_text:
        is_weather_context = _is_weather_tool_context(contexts)
        _debug_log(
            "H1",
            "app/rag/pipeline.py:_call_llm_with_context",
            "Prompt routing decision",
            {
                "query": request.query,
                "is_weather_context": is_weather_context,
                "context_count": len(contexts),
                "first_document_id": contexts[0].document_id if contexts else None,
                "first_source": contexts[0].meta.get("source") if contexts and contexts[0].meta else None,
            },
        )
        if is_weather_context:
            prompt = f"""다음 날씨 정보를 바탕으로 사용자의 질문에 자연스럽고 친절하게 답변해주세요.

날씨 정보:
{context_text}

사용자 질문: {request.query}

답변:"""
        elif _has_law_context(contexts):
            prompt = f"""당신은 한국 법률 전문가입니다. 아래 법령 조문을 근거로 질문에 답변해주세요.

규칙:
- 답변에 근거가 되는 조문을 반드시 인용하세요 (예: "상법 제340조의2에 따르면...")
- 연계법령이 있으면 함께 설명하세요
- 컨텍스트에 없는 내용은 추측하지 마세요

법령 조문:
{context_text}

질문: {request.query}

답변:"""
        else:
            prompt = f"""다음 컨텍스트를 바탕으로 질문에 답변해주세요.

컨텍스트:
{context_text}

질문: {request.query}

답변:"""
    else:
        prompt = f"질문: {request.query}\n\n답변:"
    
    # 대화 히스토리 준비 (멀티턴 대화용)
    chat_history = None
    if request.chat_history:
        # ChatMessage 객체를 dict로 변환
        chat_history = [
            {"role": msg.role, "content": msg.content}
            for msg in request.chat_history
        ]
    
    # 실제 LLM 호출 (모델 선택 + 대화 히스토리 포함)
    output_text, llm_trace = await call_llm(prompt, model=request.model, chat_history=chat_history)
    
    return llm_trace, output_text


async def retrieve_only(
    query: str,
    *,
    profile: str = "default",
    top_k: int = 6,
    final_contexts: int = 3,
    source: str | None = None,
) -> tuple[str, list[ContextItem], RetrievalTrace, QueryMeta, list[dict]]:
    trace_id = str(uuid.uuid4())
    original_query = query
    query = normalize_law_query(query) if source == "law" else query
    retrieval_started = time.perf_counter()
    profile_name, profile_config = resolve_profile(profile, top_k, final_contexts)
    candidate_k = profile_config["candidate_k"]
    final_contexts = profile_config["final_contexts"]
    pipeline_stages: list[dict] = []

    try:
        if source == "law":
            reranked, pipeline_stages = await asyncio.to_thread(
                retrieve_law_article_candidates_with_trace,
                query,
                candidate_k=candidate_k,
                top_k=top_k,
                use_rerank=profile_config["use_rerank"],
            )
        elif profile_config["use_rerank"]:
            from app.rag.reranker import retrieve_and_rerank_with_trace
            reranked, stages = await asyncio.to_thread(
                retrieve_and_rerank_with_trace,
                query,
                candidate_k,
                candidate_k,
                source,
            )
            pipeline_stages.extend(stages)
        else:
            from app.rag.hybrid_retriever import HybridRetriever
            retriever = HybridRetriever()
            reranked, hybrid_trace = await asyncio.to_thread(
                retriever.search_with_trace, query, candidate_k, source, False, candidate_k,
            )
            _extend_pipeline_stages_from_hybrid(pipeline_stages, hybrid_trace)
    except Exception as e:
        logger.warning(
            "Rerank retrieval failed, falling back to hybrid",
            extra={"trace_id": trace_id, "error": str(e)},
        )
        try:
            if source == "law":
                reranked, pipeline_stages = await asyncio.to_thread(
                    retrieve_law_article_candidates_with_trace,
                    query,
                    candidate_k=candidate_k,
                    top_k=top_k,
                    use_rerank=False,
                )
            else:
                from app.rag.hybrid_retriever import HybridRetriever
                retriever = HybridRetriever()
                reranked, hybrid_trace = await asyncio.to_thread(
                    retriever.search_with_trace, query, candidate_k, source, False, candidate_k,
                )
                _extend_pipeline_stages_from_hybrid(pipeline_stages, hybrid_trace)
        except Exception as e2:
            logger.error("Hybrid retrieval also failed", extra={"trace_id": trace_id, "error": str(e2)})
            reranked = []

    law_rerank_info = {"normalized_query": normalize_law_query(query), "law_rerank_applied": source == "law"}
    if source != "law":
        reranked, law_rerank_info = apply_law_aware_rerank(query, reranked, top_k=top_k, source=source)
    if source != "law" and law_rerank_info.get("law_rerank_applied"):
        pipeline_stages.append({
            "name": "Law-aware Rerank",
            "description": f"normalized: {law_rerank_info['normalized_query']}",
            "count": len(reranked),
            "latency_ms": 0,
            "results": [
                {
                    "id": r.get("id", ""),
                    "content": r.get("content", ""),
                    "score": r.get("law_rerank_score", 0),
                    "score_label": "law rerank",
                    "metadata": r.get("metadata", {}),
                }
                for r in reranked
            ],
        })

    contexts: list[ContextItem] = []
    vector_results_for_trace: list[dict] = []
    seen_chunk_ids: set[str] = set()

    for r in reranked:
        cid = r.get("id", "")
        if cid in seen_chunk_ids:
            continue
        seen_chunk_ids.add(cid)
        meta = r.get("metadata", {})
        contexts.append(ContextItem(
            chunk_id=cid,
            document_id=meta.get("filepath", ""),
            text=r.get("content", ""),
            score=r.get("rerank_score", r.get("rrf_score", r.get("similarity", 0.0))),
            meta=meta,
        ))
        vector_results_for_trace.append({
            "chunk_id": cid,
            "score": r.get("rerank_score", r.get("rrf_score", r.get("similarity", 0.0))),
            "content": r.get("content", ""),
            "filepath": meta.get("filepath", ""),
            "tags": meta.get("tags", []),
            "section_title": meta.get("section_title", ""),
            "article_title": meta.get("article_title", ""),
            "article_number": meta.get("article_number"),
        })

    if contexts:
        contexts = _limit_contexts_by_chars(contexts[:final_contexts], max_chars=RAG_MAX_CONTEXT_CHARS)

    retrieval_latency_ms = int((time.perf_counter() - retrieval_started) * 1000)
    retrieval_trace = _build_retrieval_trace(query, vector_results=vector_results_for_trace)
    meta = QueryMeta(
        mode="retrieve",
        profile=profile_name,
        timestamp=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        status="success",
        tool=None,
        retrieval={
            "top_k": top_k,
            "source": source,
            "final_contexts": final_contexts,
            "candidate_k": candidate_k,
            "latency_ms": retrieval_latency_ms,
            "label": profile_config["label"],
            "normalized_query": law_rerank_info["normalized_query"] if source == "law" else original_query,
            "law_rerank_applied": law_rerank_info.get("law_rerank_applied", False),
        },
    )
    return trace_id, contexts, retrieval_trace, meta, pipeline_stages

async def run_rag(request: QueryRequest) -> QueryResponse:
    """
    Terrarium RAG 파이프라인의 엔트리포인트.

    v0:
    - 쿼리 확장, 컨텍스트 구성, 실제 LLM 호출을 수행한다.
    - 나중에 검색/리랭킹 단계를 추가한다.
    """

    trace_id = str(uuid.uuid4())
    original_query = request.query
    if request.source == "law" and request.mode == "corpus":
        request = request.model_copy(update={"query": normalize_law_query(request.query)})
    profile_name = request.profile if request.profile in PROFILE_CONFIGS else "default"
    logger.info(
        "run_rag started",
        extra={
            "trace_id": trace_id,
            "query": request.query,
            "mode": request.mode,
            "profile": profile_name,
            "chat_history_len": len(request.chat_history) if request.chat_history else 0,
        },
    )

    # 0) chat 모드: 검색 없이 LLM 직접 대화
    if request.mode == "chat":
        logger.info("Chat mode - direct LLM call", extra={"trace_id": trace_id})

        chat_history = None
        if request.chat_history:
            chat_history = [
                {"role": msg.role, "content": msg.content}
                for msg in request.chat_history
            ]

        try:
            output_text, llm_trace = await call_llm(
                request.query, model=request.model, chat_history=chat_history
            )
            answer = output_text
            status = "success"
        except Exception as e:
            logger.error("Chat LLM call failed", extra={"trace_id": trace_id, "error": str(e)}, exc_info=True)
            llm_trace = _build_llm_error_trace(f"LLM 호출 실패: {str(e)}", 0.0, model=request.model)
            answer = llm_trace.output
            status = "error"

        meta = QueryMeta(
            mode="chat",
            profile=profile_name,
            timestamp=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            status=status,
            tool=None,
            retrieval=None,
        )
        return QueryResponse(
            trace_id=trace_id,
            answer=answer,
            contexts=[],
            retrieval_trace=RetrievalTrace(),
            llm_trace=llm_trace,
            meta=meta,
        )

    # 1) 툴 체크 (MCP 스타일) - 모든 툴이 LLM 컨텍스트로 전달됨
    if is_weather_query(request.query) and not OFFLINE_MODE:
        logger.info(
            "Weather tool triggered",
            extra={"trace_id": trace_id, "query": request.query},
        )
        # 날씨 툴 호출하여 날씨 정보 가져오기
        weather_info = await asyncio.to_thread(get_weather)
        
        # 공통 함수를 통해 툴 정보를 LLM 컨텍스트로 전달
        llm_trace, answer, status, contexts = await _call_llm_with_tool_context(
            request=request,
            tool_info=weather_info,
            tool_name="weather",
            tool_meta={"source": "accuweather", "location": "seoul"},
            trace_id=trace_id,
        )
        
        # 검색 트레이스 구성
        retrieval_trace = _build_retrieval_trace(request.query)
        used_tool = "weather"  # 사용된 툴 이름
    elif is_time_query(request.query):
        logger.info(
            "Time tool triggered",
            extra={"trace_id": trace_id, "query": request.query},
        )
        # 시간 툴 호출하여 시간 정보 가져오기
        time_info = await asyncio.to_thread(get_current_time)
        
        # 공통 함수를 통해 툴 정보를 LLM 컨텍스트로 전달
        llm_trace, answer, status, contexts = await _call_llm_with_tool_context(
            request=request,
            tool_info=time_info,
            tool_name="time",
            tool_meta={"source": "system", "timezone": "Asia/Seoul"},
            trace_id=trace_id,
        )
        
        # 검색 트레이스 구성
        retrieval_trace = _build_retrieval_trace(request.query)
        used_tool = "time"  # 사용된 툴 이름
    else:
        # 일반 RAG 파이프라인: HybridRetriever + rerank + 법령 확장
        retrieval_started = time.perf_counter()
        top_k = request.options.top_k if request.options.top_k > 0 else RAG_TOP_K
        requested_final_contexts = request.options.final_contexts if request.options.final_contexts > 0 else 3
        profile_name, profile_config = resolve_profile(request.profile, top_k, requested_final_contexts)
        candidate_k = profile_config["candidate_k"]
        final_contexts = profile_config["final_contexts"]
        pipeline_stages: list[dict] = []

        # source 필터: regulation은 항상 제외
        source_filter = request.source  # "law" | "zuzu" | None

        try:
            if source_filter == "law":
                reranked, pipeline_stages = await asyncio.to_thread(
                    retrieve_law_article_candidates_with_trace,
                    request.query,
                    candidate_k=candidate_k,
                    top_k=top_k,
                    use_rerank=profile_config["use_rerank"],
                )
            elif profile_config["use_rerank"]:
                from app.rag.reranker import retrieve_and_rerank_with_trace
                reranked, stages = await asyncio.to_thread(
                    retrieve_and_rerank_with_trace,
                    request.query,
                    candidate_k,
                    candidate_k,
                    source_filter,
                )
                pipeline_stages.extend(stages)
            else:
                from app.rag.hybrid_retriever import HybridRetriever
                retriever = HybridRetriever()
                reranked, hybrid_trace = await asyncio.to_thread(
                    retriever.search_with_trace, request.query, candidate_k, source_filter, False, candidate_k,
                )
                _extend_pipeline_stages_from_hybrid(pipeline_stages, hybrid_trace)
        except Exception as e:
            logger.warning(
                "Rerank retrieval failed, falling back to hybrid",
                extra={"trace_id": trace_id, "error": str(e)},
            )
            try:
                if source_filter == "law":
                    reranked, pipeline_stages = await asyncio.to_thread(
                        retrieve_law_article_candidates_with_trace,
                        request.query,
                        candidate_k=candidate_k,
                        top_k=top_k,
                        use_rerank=False,
                    )
                else:
                    from app.rag.hybrid_retriever import HybridRetriever
                    retriever = HybridRetriever()
                    reranked, hybrid_trace = await asyncio.to_thread(
                        retriever.search_with_trace, request.query, candidate_k, source_filter, False, candidate_k,
                    )
                    _extend_pipeline_stages_from_hybrid(pipeline_stages, hybrid_trace)
            except Exception as e2:
                logger.error("Hybrid retrieval also failed", extra={"trace_id": trace_id, "error": str(e2)})
                reranked = []

        law_rerank_info = {"normalized_query": request.query, "law_rerank_applied": source_filter == "law"}
        if source_filter != "law":
            reranked, law_rerank_info = apply_law_aware_rerank(
                request.query,
                reranked,
                top_k=top_k,
                source=source_filter,
            )
        if source_filter != "law" and law_rerank_info.get("law_rerank_applied"):
            pipeline_stages.append({
                "name": "Law-aware Rerank",
                "description": f"normalized: {law_rerank_info['normalized_query']}",
                "count": len(reranked),
                "latency_ms": 0,
                "results": [
                    {
                        "id": r.get("id", ""),
                        "content": r.get("content", ""),
                        "score": r.get("law_rerank_score", 0),
                        "score_label": "law rerank",
                        "metadata": r.get("metadata", {}),
                    }
                    for r in reranked
                ],
            })

        # 검색 결과 → ContextItem 변환
        contexts: list[ContextItem] = []
        vector_results_for_trace: list[dict] = []
        seen_chunk_ids: set[str] = set()

        for r in reranked:
            cid = r.get("id", "")
            if cid in seen_chunk_ids:
                continue
            seen_chunk_ids.add(cid)
            meta = r.get("metadata", {})
            contexts.append(ContextItem(
                chunk_id=cid,
                document_id=meta.get("filepath", ""),
                text=r.get("content", ""),
                score=r.get("rerank_score", r.get("rrf_score", r.get("similarity", 0.0))),
                meta=meta,
            ))
            vector_results_for_trace.append({
                "chunk_id": cid,
                "score": r.get("rerank_score", r.get("rrf_score", r.get("similarity", 0.0))),
                "content": r.get("content", ""),
                "filepath": meta.get("filepath", ""),
                "tags": meta.get("tags", []),
                "section_title": meta.get("section_title", ""),
                "article_title": meta.get("article_title", ""),
                "article_number": meta.get("article_number"),
                "article_key": meta.get("article_key"),
            })

        if contexts:
            contexts = _limit_contexts_by_chars(contexts[:final_contexts], max_chars=RAG_MAX_CONTEXT_CHARS)

            # 법령 연계법령 확장
            law_contexts = [
                c for c in contexts
                if c.meta and "law" in (c.meta.get("tags") or [])
            ]
            if law_contexts and profile_config["use_law_expansion"]:
                try:
                    from app.rag.law_expander import LawExpander
                    t_expand = time.perf_counter()
                    expander = LawExpander()
                    fake_results = [
                        {"id": c.chunk_id, "content": c.text, "metadata": c.meta or {}}
                        for c in law_contexts
                    ]
                    expanded_results = await asyncio.to_thread(
                        expander.expand, fake_results, query=request.query,
                    )
                    expand_items = []
                    for r in expanded_results:
                        for idx, exp_ctx in enumerate(r.get("expanded_context", [])):
                            # article_key로 구분 (article_number는 제16조/제16조의3 구분 불가)
                            ak = exp_ctx.get("article_key", "")
                            exp_id = f"ref:{exp_ctx['law_name']}:{ak}:{idx}"
                            if exp_id not in seen_chunk_ids:
                                seen_chunk_ids.add(exp_id)
                                expand_items.append(exp_ctx)
                                contexts.append(ContextItem(
                                    chunk_id=exp_id,
                                    document_id=f"law://{exp_ctx['law_name']}",
                                    text=exp_ctx["text"],
                                    score=0.0,
                                    meta={
                                        "source": "law",
                                        "tags": ["law"],
                                        "section_title": exp_ctx["law_name"],
                                        "article_number": exp_ctx["article_number"],
                                        "article_title": exp_ctx["article_title"],
                                        "is_ref": exp_ctx["is_ref"],
                                    },
                                ))
                    expand_ms = int((time.perf_counter() - t_expand) * 1000)
                    pipeline_stages.append({
                        "name": "Law Expansion",
                        "description": f"같은 조 + 연계법령 확장 ({len(expand_items)}건 추가)",
                        "count": len(expand_items),
                        "latency_ms": expand_ms,
                        "results": [
                            {
                                "id": f"{e['law_name']} 제{e['article_number']}조",
                                "content": e["text"],
                                "score": 0,
                                "score_label": "ref" if e["is_ref"] else "self",
                                "metadata": {"law_name": e["law_name"], "article_number": e["article_number"], "article_title": e["article_title"], "is_ref": e["is_ref"]},
                            }
                            for e in expand_items
                        ],
                    })
                    contexts = _limit_contexts_by_chars(contexts[:max(final_contexts, len(contexts))], max_chars=RAG_MAX_CONTEXT_CHARS)
                except Exception as e:
                    logger.warning(
                        "Law expansion failed, using original contexts",
                        extra={"trace_id": trace_id, "error": str(e)},
                    )

            # Context Selection 단계
            pipeline_stages.append({
                "name": "Context Selection",
                "description": f"최종 LLM 컨텍스트 (max {RAG_MAX_CONTEXT_CHARS}자)",
                "count": len(contexts),
                "latency_ms": 0,
                "results": [
                    {
                        "id": c.chunk_id,
                        "content": c.text,
                        "score": c.score,
                        "score_label": "final",
                        "metadata": c.meta,
                    }
                    for c in contexts
                ],
            })

            retrieval_trace = RetrievalTrace(
                query_expansions=[request.query],
                bm25_results=[],
                vector_results=vector_results_for_trace[:top_k],
                reranked_results=vector_results_for_trace[:top_k],
            )
        else:
            contexts = _build_ephemeral_contexts(request)
            retrieval_trace = RetrievalTrace(
                query_expansions=[request.query],
                bm25_results=[],
                vector_results=[],
                reranked_results=[],
            )

        retrieval_latency_ms = int((time.perf_counter() - retrieval_started) * 1000)

        # 실제 LLM 호출
        llm_trace, answer, status = await _safe_call_llm(
            request,
            contexts,
            trace_id,
            error_prefix="일반 질의 처리 중 오류가 발생했습니다.",
        )

        # LLM 단계 추가
        pipeline_stages.append({
            "name": "LLM Call",
            "description": f"{llm_trace.model} ({int(llm_trace.latency_ms)}ms)",
            "count": 1,
            "latency_ms": int(llm_trace.latency_ms),
            "results": [{
                "id": "llm",
                "content": llm_trace.prompt,
                "score": 0,
                "score_label": "prompt",
                "metadata": {
                    "model": llm_trace.model,
                    "input_tokens": llm_trace.input_tokens,
                    "output_tokens": llm_trace.output_tokens,
                },
            }],
        })

        if retrieval_trace.vector_results:
            try:
                store = PgVectorStore()
                await asyncio.to_thread(
                    store.log_retrieval,
                    query=request.query,
                    expanded_query=request.query,
                    used_tool=None,
                    top_k=top_k,
                    results=retrieval_trace.vector_results,
                    latency_ms=retrieval_latency_ms,
                )
            except Exception as e:
                logger.warning(
                    "failed to persist retrieval_logs",
                    extra={"trace_id": trace_id, "error": str(e)},
                )
        used_tool = None

    # 4) 메타데이터 구성
    meta = QueryMeta(
        mode=request.mode,
        profile=profile_name,
        timestamp=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        status=status,
        tool=used_tool,
        retrieval={
            "top_k": top_k if 'top_k' in locals() else request.options.top_k,
            "returned": len(retrieval_trace.vector_results),
            "source": "pgvector" if retrieval_trace.vector_results else "ephemeral",
            "sources_count": len({r.get("filepath") for r in retrieval_trace.vector_results if r.get("filepath")}),
            "model": os.getenv("OLLAMA_EMBED_MODEL", "bge-m3"),
            "normalized_query": request.query if request.source == "law" and request.mode == "corpus" else original_query,
            "law_rerank_applied": law_rerank_info.get("law_rerank_applied", False) if 'law_rerank_info' in locals() else False,
            "latency": {
                "retrieval_ms": retrieval_latency_ms if 'retrieval_latency_ms' in locals() else None,
                "llm_ms": int(llm_trace.latency_ms) if llm_trace and llm_trace.latency_ms is not None else None,
            },
        },
    )

    # 5) 최종 응답 조립
    response = QueryResponse(
        trace_id=trace_id,
        answer=answer,
        contexts=contexts,
        retrieval_trace=retrieval_trace,
        llm_trace=llm_trace,
        meta=meta,
        pipeline_stages=pipeline_stages if 'pipeline_stages' in locals() else [],
    )

    logger.info(
        "run_rag finished",
        extra={
            "trace_id": trace_id,
            "mode": request.mode,
            "profile": profile_name,
            "status": status,
        },
    )

    return response
