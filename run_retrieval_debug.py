#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from typing import Any

import psycopg
from psycopg import sql

from pg_ingest_law_article import create_embedder, create_kiwi, quote_vector, tokenize_keyword_terms, compound_keywords
from app.rag.pipeline import (
    _extract_law_query_parts,
    _law_article_display_text,
    _score_law_keyword_candidate,
    _strip_spaces,
    LAW_QUERY_REGULATION_TOKENS,
    apply_law_aware_rerank,
)


DEFAULT_SAMPLE_TABLE = "law_articles_dev_small"
RRF_K = 60


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", required=True)
    parser.add_argument("--profile", default="law")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--table", default=DEFAULT_SAMPLE_TABLE)
    parser.add_argument("--dsn", default=os.getenv("PG_DSN") or os.getenv("DATABASE_URL"))
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    return parser.parse_args()


def extract_query_keywords(query: str) -> list[str]:
    kiwi = create_kiwi()
    tokens = tokenize_keyword_terms(kiwi, query)
    tokens.extend(compound_keywords(kiwi, query))
    unique: list[str] = []
    for token in tokens:
        if token not in unique:
            unique.append(token)
    return unique


def row_to_result(row: tuple[Any, ...], score_key: str, score_value: float) -> dict[str, Any]:
    metadata = {
        "article_number": row[5] if len(row) > 5 else None,
        "article_key": row[6] if len(row) > 6 else None,
        "article_title": row[2],
        "article_citation": row[3],
        "section_title": row[1],
        "law_name": row[1],
        "keywords": list(row[4] or []),
        "tags": ["law"],
        "filepath": f"law://{row[1]}",
        "source": "law",
        "is_current": True,
    }
    return {
        "article_pk": str(row[0]),
        "id": str(row[0]),
        "law_name": str(row[1]),
        "article_title": row[2],
        "article_citation": row[3],
        "score_key": score_key,
        "score": float(score_value),
        "keywords": list(row[4] or []),
        "content": _law_article_display_text(
            {
                "law_name": row[1],
                "article_title": row[2],
                "article_citation": row[3],
                "article_text": row[7] if len(row) > 7 and isinstance(row[7], str) else "",
            }
        ),
        "metadata": metadata,
        "rrf_score": 0.0,
        "rerank_score": float(score_value) if score_key == "rerank" else 0.0,
        "similarity": float(score_value) if score_key == "dense" else 0.0,
        "bm25_score": float(score_value) if score_key == "keyword" else 0.0,
    }


def fetch_exact_results(
    conn: psycopg.Connection[Any],
    *,
    table: str,
    query: str,
    top_k: int,
) -> list[dict[str, Any]]:
    info = _extract_law_query_parts(query)
    if not info["law_name_norm"]:
        return []

    where_parts = [
        "regexp_replace(law_name, '\\s+', '', 'g') = %s",
    ]
    params: list[Any] = [info["law_name_norm"]]
    if info["article_number"] is not None:
        where_parts.append("article_number = %s")
        params.append(info["article_number"])
    if info["article_sub_number"] is not None:
        where_parts.append("coalesce(article_citation, '') ~ %s")
        params.append(rf"제{info['article_number']}조의{info['article_sub_number']}")
    if not info["explicit_regulation"]:
        where_parts.append("law_name !~ '(시행령|시행규칙|규칙)'")
    params.append(top_k)

    query_sql = sql.SQL(
        """
        SELECT
            article_pk,
            law_name,
            article_title,
            article_citation,
            keywords,
            article_number,
            article_key,
            article_text
        FROM {table}
        WHERE {where_clause}
        ORDER BY
            CASE WHEN article_number IS NULL THEN 1 ELSE 0 END,
            article_number ASC NULLS LAST,
            article_key ASC NULLS LAST
        LIMIT %s
        """
    ).format(
        table=sql.Identifier(table),
        where_clause=sql.SQL(" AND ").join(sql.SQL(part) for part in where_parts),
    )

    with conn.cursor() as cur:
        cur.execute(query_sql, params)
        rows = cur.fetchall()

    results = [row_to_result(row, "exact", 3.0) for row in rows]
    for result in results:
        result["rrf_score"] = 3.0
        result["rerank_score"] = 3.0
        result["similarity"] = 3.0
    return results


def fetch_dense_results(
    conn: psycopg.Connection[Any],
    *,
    table: str,
    query_vec: list[float],
    top_k: int,
) -> list[dict[str, Any]]:
    vec = quote_vector(query_vec)
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL(
                """
                SELECT article_pk, law_name, article_title, article_citation, keywords,
                       article_number, article_key, article_text,
                       1 - (embedding <=> %s::vector) AS similarity
                FROM {table}
                WHERE embedding IS NOT NULL
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """
            ).format(table=sql.Identifier(table)),
            (vec, vec, top_k),
        )
        rows = cur.fetchall()
    return [row_to_result(row, "dense", float(row[8])) for row in rows]


def fetch_sparse_results(
    conn: psycopg.Connection[Any],
    *,
    table: str,
    query_sparse: dict[str, float],
    top_k: int,
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL(
                """
                SELECT article_pk, law_name, article_title, article_citation, keywords, article_number, article_key, article_text, sparse
                FROM {table}
                WHERE sparse IS NOT NULL
                """
            ).format(table=sql.Identifier(table))
        )
        rows = cur.fetchall()

    scored: list[dict[str, Any]] = []
    for row in rows:
        sparse = row[8] or {}
        score = 0.0
        for key, query_weight in query_sparse.items():
            doc_weight = sparse.get(str(key))
            if doc_weight is None:
                continue
            score += float(query_weight) * float(doc_weight)
        if score <= 0:
            continue
        scored.append(row_to_result(row, "sparse", score))

    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored[:top_k]


def fetch_keyword_results(
    conn: psycopg.Connection[Any],
    *,
    table: str,
    query: str,
    query_keywords: list[str],
    top_k: int,
) -> list[dict[str, Any]]:
    if not query_keywords:
        return []

    with conn.cursor() as cur:
        cur.execute(
            sql.SQL(
                """
                SELECT article_pk, law_name, article_title, article_citation, keywords, article_number, article_key, article_text,
                       CARDINALITY(ARRAY(
                         SELECT unnest(coalesce(keywords, ARRAY[]::text[]))
                         INTERSECT
                         SELECT unnest(%s::text[])
                       )) AS keyword_hits
                FROM {table}
                WHERE keywords && %s::text[]
                ORDER BY keyword_hits DESC, article_citation ASC NULLS LAST, article_pk ASC
                LIMIT %s
                """
            ).format(table=sql.Identifier(table)),
            (query_keywords, query_keywords, max(top_k * 4, 40)),
        )
        rows = cur.fetchall()
    scored: list[dict[str, Any]] = []
    for row in rows:
        result = row_to_result(row, "keyword", float(row[8]))
        score, details = _score_law_keyword_candidate(
            query=query,
            query_keywords=query_keywords,
            law_name=str(row[1] or ""),
            article_title=str(row[2] or ""),
            article_citation=str(row[3] or ""),
            keywords=list(row[4] or []),
        )
        result["score"] = score
        result["bm25_score"] = score
        result["metadata"]["keyword_match"] = details
        scored.append(result)
    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored[:top_k]


def fuse_results(groups: list[list[dict[str, Any]]], *, top_k: int) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for group in groups:
        for rank, item in enumerate(group, start=1):
            article_pk = item["article_pk"]
            payload = merged.setdefault(
                article_pk,
                {
                    "article_pk": article_pk,
                    "id": item["id"],
                    "law_name": item["law_name"],
                    "article_title": item["article_title"],
                    "article_citation": item["article_citation"],
                    "content": item["content"],
                    "metadata": item["metadata"],
                    "scores": {},
                    "rrf_score": 0.0,
                    "similarity": item.get("similarity", 0.0),
                    "rerank_score": item.get("rerank_score", 0.0),
                },
            )
            payload["scores"][item["score_key"]] = item["score"]
            payload["rrf_score"] += 1.0 / (RRF_K + rank)
            if item.get("similarity", 0.0) > payload.get("similarity", 0.0):
                payload["similarity"] = item.get("similarity", 0.0)
            if item.get("rerank_score", 0.0) > payload.get("rerank_score", 0.0):
                payload["rerank_score"] = item.get("rerank_score", 0.0)

    fused = list(merged.values())
    fused.sort(key=lambda item: item["rrf_score"], reverse=True)
    return fused[:top_k]


def main() -> int:
    args = parse_args()
    if args.profile != "law":
        raise SystemExit("현재 debug 스크립트는 --profile law 만 지원합니다.")
    if not args.dsn:
        raise SystemExit("DSN is required via --dsn or PG_DSN/DATABASE_URL")

    model = create_embedder(args.device)
    outputs = model.encode(
        [args.query],
        batch_size=1,
        return_dense=True,
        return_sparse=True,
        return_colbert_vecs=False,
    )
    dense_query = list(outputs["dense_vecs"][0])
    sparse_query = {str(k): float(v) for k, v in outputs["lexical_weights"][0].items()}
    query_keywords = extract_query_keywords(args.query)

    with psycopg.connect(args.dsn, autocommit=True) as conn:
        exact = fetch_exact_results(conn, table=args.table, query=args.query, top_k=args.top_k)
        dense = fetch_dense_results(conn, table=args.table, query_vec=dense_query, top_k=args.top_k)
        sparse = fetch_sparse_results(conn, table=args.table, query_sparse=sparse_query, top_k=args.top_k)
        keyword = fetch_keyword_results(conn, table=args.table, query=args.query, query_keywords=query_keywords, top_k=args.top_k)

    fused = fuse_results([exact, dense, sparse, keyword], top_k=args.top_k)
    reranked, rerank_info = apply_law_aware_rerank(
        args.query,
        fused,
        top_k=args.top_k,
        source="law",
        exact_candidates=exact,
        seed_exact_candidates=False,
    )

    print(
        json.dumps(
            {
                "table": args.table,
                "query": args.query,
                "profile": args.profile,
                "top_k": args.top_k,
                "query_keywords": query_keywords,
                "exact_top_k": exact,
                "dense_top_k": dense,
                "sparse_top_k": sparse,
                "keyword_top_k": keyword,
                "fused_top_k": fused,
                "law_aware_top_k": reranked,
                "law_rerank_info": rerank_info,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
