#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
import time
from typing import Any

import psycopg
from psycopg import sql

from pg_ingest_law_article import create_kiwi, extract_keywords


DEFAULT_SOURCE_TABLE = "law_article"
DEFAULT_SAMPLE_TABLE = "law_articles_dev_small"
DEFAULT_SAMPLE_LAW_COUNT = 10
DEFAULT_VALIDATION_TEXT = "진폐의 예방과 진폐근로자의 보호 등에 관한 법률"
DEFAULT_INCLUDE_LAW_NAMES = [
    "대한민국헌법",
    "진폐의 예방과 진폐근로자의 보호 등에 관한 법률",
    "발전소주변지역 지원에 관한 법률",
]
LEGACY_STOPWORDS = {"및", "등"}
LEGACY_SPLIT_RE = re.compile(r"[\s\(\)\[\]\{\},.;:·ㆍ/<>\"'“”‘’\-]+")
LEGAL_REF_RE = re.compile(r"제\s?\d+\s?(?:조(?:의\s?\d+)?|항|호|목)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dsn", default=os.getenv("PG_DSN") or os.getenv("DATABASE_URL"))
    parser.add_argument("--source-table", default=DEFAULT_SOURCE_TABLE)
    parser.add_argument("--sample-table", default=DEFAULT_SAMPLE_TABLE)
    parser.add_argument("--law-count", type=int, default=DEFAULT_SAMPLE_LAW_COUNT)
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--validation-text", default=DEFAULT_VALIDATION_TEXT)
    parser.add_argument(
        "--include-law-name",
        action="append",
        default=None,
        help="샘플에 반드시 포함할 법령명. 여러 번 줄 수 있습니다.",
    )
    return parser.parse_args()


def legacy_preview_keywords(text: str) -> list[str]:
    keywords: list[str] = []
    for raw in LEGACY_SPLIT_RE.split(text):
        token = raw.strip()
        if not token:
            continue
        if token in LEGACY_STOPWORDS:
            continue
        if token.isdigit():
            continue
        if LEGAL_REF_RE.fullmatch(token):
            continue
        keywords.append(token)
    return keywords


def select_sample_law_ids(
    conn: psycopg.Connection[Any],
    *,
    source_table: str,
    law_count: int,
    validation_text: str,
    include_law_names: list[str] | None = None,
) -> list[tuple[str, str]]:
    include_names = list(include_law_names or [])
    if validation_text and validation_text not in include_names:
        include_names.append(validation_text)

    forced_pairs: list[tuple[str, str]] = []
    with conn.cursor() as cur:
        if include_names:
            cur.execute(
                sql.SQL(
                    """
                    SELECT law_id, min(law_name) AS law_name
                    FROM {table}
                    WHERE is_current = TRUE
                      AND law_name = ANY(%s)
                    GROUP BY law_id
                    ORDER BY law_id
                    """
                ).format(table=sql.Identifier(source_table)),
                (include_names,),
            )
            forced_pairs = [(str(row[0]), str(row[1])) for row in cur.fetchall()]

        cur.execute(
            sql.SQL(
                """
                SELECT law_id, min(law_name) AS law_name
                FROM {table}
                WHERE is_current = TRUE
                GROUP BY law_id
                ORDER BY law_id
                LIMIT %s
                """
            ).format(table=sql.Identifier(source_table)),
            (max(law_count * 3, law_count),),
        )
        fallback = [(str(row[0]), str(row[1])) for row in cur.fetchall()]

    selected: list[tuple[str, str]] = []
    seen_ids: set[str] = set()

    for pair in forced_pairs + fallback:
        law_id = pair[0]
        if law_id in seen_ids:
            continue
        selected.append(pair)
        seen_ids.add(law_id)
        if len(selected) >= law_count:
            break

    return selected


def rebuild_sample_table(
    conn: psycopg.Connection[Any],
    *,
    source_table: str,
    sample_table: str,
    sample_law_ids: list[str],
) -> int:
    if not sample_law_ids:
        raise RuntimeError("sample_law_ids is empty")

    with conn.cursor() as cur:
        cur.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(sample_table)))
        cur.execute(
            sql.SQL("CREATE TABLE {} AS SELECT * FROM {} WHERE FALSE").format(
                sql.Identifier(sample_table),
                sql.Identifier(source_table),
            )
        )
        cur.execute(
            sql.SQL(
                """
                INSERT INTO {sample_table}
                SELECT *
                FROM {source_table}
                WHERE is_current = TRUE
                  AND law_id = ANY(%s)
                ORDER BY law_id, article_number NULLS LAST, article_key NULLS LAST, article_pk
                """
            ).format(
                sample_table=sql.Identifier(sample_table),
                source_table=sql.Identifier(source_table),
            ),
            (sample_law_ids,),
        )
        cur.execute(
            sql.SQL("ALTER TABLE {} ADD PRIMARY KEY (article_pk)").format(sql.Identifier(sample_table))
        )
        cur.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(sample_table)))
        row_count = int(cur.fetchone()[0])
    conn.commit()
    return row_count


def refresh_sample_keywords(
    conn: psycopg.Connection[Any],
    *,
    sample_table: str,
    batch_size: int,
) -> int:
    kiwi = create_kiwi()
    total = 0
    last_pk = ""

    while True:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL(
                    """
                    SELECT article_pk, law_name, article_title, article_citation, article_text
                    FROM {sample_table}
                    WHERE article_pk > %s
                    ORDER BY article_pk
                    LIMIT %s
                    """
                ).format(sample_table=sql.Identifier(sample_table)),
                (last_pk, batch_size),
            )
            rows = cur.fetchall()

        if not rows:
            break

        updates = []
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        for article_pk, law_name, article_title, article_citation, article_text in rows:
            keywords = extract_keywords(kiwi, (article_title, article_citation, article_text, article_pk), law_name)
            updates.append((keywords, now, article_pk))

        with conn.cursor() as cur:
            cur.executemany(
                sql.SQL(
                    """
                    UPDATE {sample_table}
                    SET keywords = %s,
                        keyworded_at = %s::timestamptz
                    WHERE article_pk = %s
                    """
                ).format(sample_table=sql.Identifier(sample_table)),
                updates,
            )
        conn.commit()

        total += len(updates)
        last_pk = str(rows[-1][0])

    return total


def create_sample_gin(conn: psycopg.Connection[Any], *, sample_table: str) -> float:
    index_name = f"{sample_table}_keywords_gin"
    started = time.perf_counter()
    with conn.cursor() as cur:
        cur.execute(sql.SQL("DROP INDEX IF EXISTS {}").format(sql.Identifier(index_name)))
        cur.execute(
            sql.SQL("CREATE INDEX {} ON {} USING gin (keywords)").format(
                sql.Identifier(index_name),
                sql.Identifier(sample_table),
            )
        )
    conn.commit()
    return time.perf_counter() - started


def create_sample_hnsw(conn: psycopg.Connection[Any], *, sample_table: str) -> float:
    index_name = f"{sample_table}_hnsw"
    started = time.perf_counter()
    with conn.cursor() as cur:
        cur.execute(sql.SQL("DROP INDEX IF EXISTS {}").format(sql.Identifier(index_name)))
        cur.execute(
            sql.SQL(
                "CREATE INDEX {} ON {} USING hnsw (embedding vector_cosine_ops)"
            ).format(
                sql.Identifier(index_name),
                sql.Identifier(sample_table),
            )
        )
    conn.commit()
    return time.perf_counter() - started


def fetch_sample_keywords_for_text(
    conn: psycopg.Connection[Any],
    *,
    sample_table: str,
    validation_text: str,
) -> list[str] | None:
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL(
                """
                SELECT keywords
                FROM {sample_table}
                WHERE law_name = %s
                ORDER BY article_number NULLS LAST, article_pk
                LIMIT 1
                """
            ).format(sample_table=sql.Identifier(sample_table)),
            (validation_text,),
        )
        row = cur.fetchone()
    return list(row[0] or []) if row else None


def main() -> int:
    args = parse_args()
    if not args.dsn:
        raise SystemExit("DSN is required via --dsn or PG_DSN/DATABASE_URL")

    include_law_names = args.include_law_name or list(DEFAULT_INCLUDE_LAW_NAMES)

    legacy_keywords = legacy_preview_keywords(args.validation_text)
    kiwi = create_kiwi()
    new_keywords_preview = extract_keywords(kiwi, (None, None, args.validation_text, "preview"), args.validation_text)

    conn = psycopg.connect(args.dsn, autocommit=False)
    try:
        selected = select_sample_law_ids(
            conn,
            source_table=args.source_table,
            law_count=args.law_count,
            validation_text=args.validation_text,
            include_law_names=include_law_names,
        )
        sample_law_ids = [law_id for law_id, _ in selected]
        sample_row_count = rebuild_sample_table(
            conn,
            source_table=args.source_table,
            sample_table=args.sample_table,
            sample_law_ids=sample_law_ids,
        )
        refreshed_rows = refresh_sample_keywords(
            conn,
            sample_table=args.sample_table,
            batch_size=args.batch_size,
        )
        gin_seconds = create_sample_gin(conn, sample_table=args.sample_table)
        hnsw_seconds = create_sample_hnsw(conn, sample_table=args.sample_table)
        sample_keywords = fetch_sample_keywords_for_text(
            conn,
            sample_table=args.sample_table,
            validation_text=args.validation_text,
        )
    finally:
        conn.close()

    print(f"sample table: {args.sample_table}")
    print(f"sample row count: {sample_row_count}")
    print(f"selected law_id count: {len(sample_law_ids)}")
    print(f"selected law names: {', '.join(law_name for _, law_name in selected)}")
    print(f"selected law_ids: {', '.join(sample_law_ids)}")
    print(f"forced include law names: {include_law_names}")
    print(f"legacy preview keywords: {legacy_keywords}")
    print(f"new preview keywords: {new_keywords_preview}")
    print(f"sample keyword refresh rows: {refreshed_rows}")
    print(f"sample keywords from table: {sample_keywords}")
    print(f"sample GIN seconds: {gin_seconds:.3f}")
    print(f"sample HNSW seconds: {hnsw_seconds:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
