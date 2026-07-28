#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Iterator

import psycopg
from dateutil import parser as date_parser
from tqdm import tqdm


UPSERT_BATCH_DEFAULT = 1000
EMBED_BATCH_CPU = 8
EMBED_BATCH_CUDA = 32
MAX_EMBED_TOKENS = 8192
LOG_DIR = Path("logs")

KEYWORD_KEEP_TAGS = {"NNG", "NNP", "SL", "SH", "SN"}
KEYWORD_ONE_CHAR_WHITELIST: set[str] = set()
KEYWORD_STOPWORDS = {
    "및", "등", "관한", "관련", "개정",
    "의", "에", "과", "와", "를", "을", "은", "는", "이", "가",
}
LEGAL_REF_FULL_RE = re.compile(r"제\s?\d+\s?(?:조(?:의\s?\d+)?|항|호|목)")
EOJEOL_SPLIT_RE = re.compile(r"\s+")


CREATE_EXTENSION_SQL = "CREATE EXTENSION IF NOT EXISTS vector;"

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS law_article (
  article_pk             TEXT PRIMARY KEY,
  law_id                 TEXT NOT NULL,
  law_name               TEXT NOT NULL,
  law_type               TEXT,
  department             TEXT,
  article_key            TEXT,
  article_number         INTEGER,
  article_title          TEXT,
  article_citation       TEXT,
  article_text           TEXT NOT NULL,
  proclamation_date      DATE,
  law_effective_date     DATE,
  article_effective_date DATE,
  embedding              vector(1024),
  sparse                 JSONB,
  keywords               TEXT[] NOT NULL DEFAULT '{}',
  truncated_for_embed    BOOLEAN NOT NULL DEFAULT FALSE,
  embedded_at            TIMESTAMPTZ,
  keyworded_at           TIMESTAMPTZ,
  is_current             BOOLEAN NOT NULL DEFAULT TRUE,
  created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

CREATE_BASE_INDEX_SQL = [
    "CREATE INDEX IF NOT EXISTS law_article_law_id_idx ON law_article (law_id);",
    "CREATE INDEX IF NOT EXISTS law_article_law_name_idx ON law_article (law_name);",
]

CREATE_FINAL_INDEX_SQL = [
    "SET maintenance_work_mem = '1GB';",
    """
    CREATE INDEX IF NOT EXISTS law_article_hnsw
      ON law_article
      USING hnsw (embedding vector_cosine_ops)
      WITH (m = 16, ef_construction = 200);
    """,
    "CREATE INDEX IF NOT EXISTS law_article_keywords_gin ON law_article USING gin (keywords);",
]

UPSERT_SQL = """
INSERT INTO law_article (
  article_pk, law_id, law_name, law_type, department,
  article_key, article_number, article_title, article_citation, article_text,
  proclamation_date, law_effective_date, article_effective_date
)
VALUES (
  %(article_pk)s, %(law_id)s, %(law_name)s, %(law_type)s, %(department)s,
  %(article_key)s, %(article_number)s, %(article_title)s, %(article_citation)s, %(article_text)s,
  %(proclamation_date)s, %(law_effective_date)s, %(article_effective_date)s
)
ON CONFLICT (article_pk) DO UPDATE SET
  law_id = EXCLUDED.law_id,
  law_name = EXCLUDED.law_name,
  law_type = EXCLUDED.law_type,
  department = EXCLUDED.department,
  article_key = EXCLUDED.article_key,
  article_number = EXCLUDED.article_number,
  article_title = EXCLUDED.article_title,
  article_citation = EXCLUDED.article_citation,
  article_text = EXCLUDED.article_text,
  proclamation_date = EXCLUDED.proclamation_date,
  law_effective_date = EXCLUDED.law_effective_date,
  article_effective_date = EXCLUDED.article_effective_date,
  embedding = CASE
    WHEN law_article.law_name IS DISTINCT FROM EXCLUDED.law_name
      OR law_article.article_citation IS DISTINCT FROM EXCLUDED.article_citation
      OR law_article.article_text IS DISTINCT FROM EXCLUDED.article_text
      OR law_article.article_title IS DISTINCT FROM EXCLUDED.article_title
    THEN NULL ELSE law_article.embedding END,
  sparse = CASE
    WHEN law_article.law_name IS DISTINCT FROM EXCLUDED.law_name
      OR law_article.article_citation IS DISTINCT FROM EXCLUDED.article_citation
      OR law_article.article_text IS DISTINCT FROM EXCLUDED.article_text
      OR law_article.article_title IS DISTINCT FROM EXCLUDED.article_title
    THEN NULL ELSE law_article.sparse END,
  keywords = CASE
    WHEN law_article.law_name IS DISTINCT FROM EXCLUDED.law_name
      OR law_article.article_citation IS DISTINCT FROM EXCLUDED.article_citation
      OR law_article.article_text IS DISTINCT FROM EXCLUDED.article_text
      OR law_article.article_title IS DISTINCT FROM EXCLUDED.article_title
    THEN '{}'::text[] ELSE law_article.keywords END,
  truncated_for_embed = CASE
    WHEN law_article.law_name IS DISTINCT FROM EXCLUDED.law_name
      OR law_article.article_citation IS DISTINCT FROM EXCLUDED.article_citation
      OR law_article.article_text IS DISTINCT FROM EXCLUDED.article_text
      OR law_article.article_title IS DISTINCT FROM EXCLUDED.article_title
    THEN FALSE ELSE law_article.truncated_for_embed END,
  embedded_at = CASE
    WHEN law_article.law_name IS DISTINCT FROM EXCLUDED.law_name
      OR law_article.article_citation IS DISTINCT FROM EXCLUDED.article_citation
      OR law_article.article_text IS DISTINCT FROM EXCLUDED.article_text
      OR law_article.article_title IS DISTINCT FROM EXCLUDED.article_title
    THEN NULL ELSE law_article.embedded_at END,
  keyworded_at = CASE
    WHEN law_article.law_name IS DISTINCT FROM EXCLUDED.law_name
      OR law_article.article_citation IS DISTINCT FROM EXCLUDED.article_citation
      OR law_article.article_text IS DISTINCT FROM EXCLUDED.article_text
      OR law_article.article_title IS DISTINCT FROM EXCLUDED.article_title
    THEN NULL ELSE law_article.keyworded_at END,
  updated_at = now();
"""


@dataclass
class Counters:
    total_rows: int = 0
    inserted_rows: int = 0
    embedded_rows: int = 0
    keyworded_rows: int = 0
    truncated_rows: int = 0


def nullify(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def parse_date_value(value: Any) -> date | None:
    raw = nullify(value)
    if not raw:
        return None
    text = str(raw)
    if re.fullmatch(r"\d{8}", text):
        text = f"{text[:4]}-{text[4:6]}-{text[6:]}"
    try:
        return date_parser.parse(text).date()
    except Exception:
        return None


def parse_int_value(value: Any) -> int | None:
    raw = nullify(value)
    if raw is None:
        return None
    try:
        return int(str(raw))
    except Exception:
        return None


def is_legal_ref_token(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    return bool(re.fullmatch(r"제\d+(?:조(?:의\d+)?|항|호|목)", compact))


def _stable_unique(tokens: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for token in tokens:
        if token in seen:
            continue
        seen.add(token)
        unique.append(token)
    return unique


def _extract_preserve_patterns(text: str | None) -> list[str]:
    if not text:
        return []
    return _stable_unique(re.sub(r"\s+", "", match.group(0)) for match in LEGAL_REF_FULL_RE.finditer(text))


def _normalize_keyword_form(form: str) -> str:
    normalized = form.strip()
    if not normalized:
        return ""
    normalized = re.sub(r"\s+", "", normalized)
    return normalized


def tokenize_keyword_terms(kiwi: Any, text: str | None) -> list[str]:
    if not text:
        return []

    tokens: list[str] = []
    tokens.extend(_extract_preserve_patterns(text))

    for token in kiwi.tokenize(text):
        form = _normalize_keyword_form(str(getattr(token, "form", "")))
        tag = str(getattr(token, "tag", ""))
        if not form:
            continue
        if is_legal_ref_token(form):
            tokens.append(form)
            continue
        if tag not in KEYWORD_KEEP_TAGS:
            continue
        if form in KEYWORD_STOPWORDS:
            continue
        if form.isdigit():
            continue
        if len(form) == 1 and form not in KEYWORD_ONE_CHAR_WHITELIST:
            continue
        tokens.append(form)

    return tokens


def compound_keywords(kiwi: Any, text: str | None) -> list[str]:
    if not text:
        return []

    compounds: list[str] = []
    for raw in EOJEOL_SPLIT_RE.split(text):
        token_text = raw.strip()
        if not token_text:
            continue
        parts = kiwi.tokenize(token_text)
        noun_forms: list[str] = []
        for token in parts:
            form = _normalize_keyword_form(str(getattr(token, "form", "")))
            tag = str(getattr(token, "tag", ""))
            if not form or tag not in KEYWORD_KEEP_TAGS:
                continue
            if form in KEYWORD_STOPWORDS:
                continue
            if form.isdigit():
                continue
            if is_legal_ref_token(form):
                continue
            if len(form) == 1 and form not in KEYWORD_ONE_CHAR_WHITELIST:
                continue
            noun_forms.append(form)
        if len(noun_forms) < 2:
            continue
        full = "".join(noun_forms)
        if full:
            compounds.append(full)
        for idx in range(len(noun_forms) - 1):
            compounds.append(noun_forms[idx] + noun_forms[idx + 1])
    return compounds


def build_keyword_input(row: dict[str, Any]) -> str:
    parts = [row.get("article_title"), row.get("article_citation"), row.get("article_text")]
    return " ".join(str(p) for p in parts if p)


def stream_jsonl(path: Path, limit: int | None = None) -> Iterator[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for idx, line in enumerate(handle, start=1):
            if limit is not None and idx > limit:
                break
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def coerce_row(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "article_pk": str(raw["article_pk"]).strip(),
        "law_id": str(raw["law_id"]).strip(),
        "law_name": str(raw["law_name"]).strip(),
        "law_type": nullify(raw.get("law_type")),
        "department": nullify(raw.get("department")),
        "article_key": nullify(raw.get("article_key")),
        "article_number": parse_int_value(raw.get("article_number")),
        "article_title": nullify(raw.get("article_title")),
        "article_citation": nullify(raw.get("article_citation")),
        "article_text": str(raw["article_text"]),
        "proclamation_date": parse_date_value(raw.get("proclamation_date")),
        "law_effective_date": parse_date_value(raw.get("law_effective_date")),
        "article_effective_date": parse_date_value(raw.get("article_effective_date")),
    }


def ensure_logs_dir() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def append_log(path: Path, message: str) -> None:
    ensure_logs_dir()
    with path.open("a", encoding="utf-8") as handle:
        handle.write(message.rstrip() + "\n")


def quote_vector(values: list[float]) -> str:
    return "[" + ",".join(f"{float(v):.8f}" for v in values) + "]"


def setup_schema(conn: psycopg.Connection[Any], *, dry_run: bool) -> None:
    ddl = [CREATE_EXTENSION_SQL, CREATE_TABLE_SQL, *CREATE_BASE_INDEX_SQL]
    if dry_run:
        for stmt in ddl:
            print(stmt.strip())
        return
    with conn.cursor() as cur:
        for stmt in ddl:
            cur.execute(stmt)
    conn.commit()


def maybe_drop_rebuild(conn: psycopg.Connection[Any], *, dry_run: bool) -> None:
    stmt = "DROP TABLE IF EXISTS law_article;"
    if dry_run:
        print(stmt)
        return
    with conn.cursor() as cur:
        cur.execute(stmt)
    conn.commit()


def maybe_delete_legacy_law(conn: psycopg.Connection[Any], *, dry_run: bool) -> None:
    stmts = [
        "DELETE FROM chunks WHERE 'law' = ANY(tags);",
        "DELETE FROM documents d WHERE NOT EXISTS (SELECT 1 FROM chunks c WHERE c.doc_id = d.doc_id);",
        "DELETE FROM retrieval_logs WHERE source = 'law';",
    ]
    if dry_run:
        for stmt in stmts:
            print(stmt)
        return
    with conn.cursor() as cur:
        for stmt in stmts:
            try:
                cur.execute(stmt)
            except Exception as exc:
                print(f"[warn] legacy law delete skipped for statement: {exc}", file=sys.stderr)
    conn.commit()


def ingest_jsonl(
    conn: psycopg.Connection[Any],
    *,
    jsonl_path: Path,
    batch_size: int,
    limit: int | None,
    counters: Counters,
    dry_run: bool,
) -> None:
    if dry_run:
        print("-- UPSERT SQL")
        print(UPSERT_SQL.strip())
        return

    batch: list[dict[str, Any]] = []
    progress = tqdm(desc="ingest", unit="row")

    def flush(current_batch: list[dict[str, Any]]) -> None:
        if not current_batch:
            return
        try:
            with conn.cursor() as cur:
                cur.executemany(UPSERT_SQL, current_batch)
            conn.commit()
            counters.inserted_rows += len(current_batch)
        except Exception as batch_exc:
            conn.rollback()
            append_log(LOG_DIR / "ingest_fail.log", f"[batch] failed size={len(current_batch)} reason={batch_exc}")
            for row in current_batch:
                try:
                    with conn.cursor() as cur:
                        cur.execute(UPSERT_SQL, row)
                    conn.commit()
                    counters.inserted_rows += 1
                except Exception as row_exc:
                    conn.rollback()
                    append_log(LOG_DIR / "ingest_fail.log", f"{row['article_pk']}\t{row_exc}")

    for raw in stream_jsonl(jsonl_path, limit=limit):
        counters.total_rows += 1
        try:
            batch.append(coerce_row(raw))
        except Exception as exc:
            append_log(LOG_DIR / "ingest_fail.log", f"{raw.get('article_pk','<missing>')}\t{exc}")
            continue
        if len(batch) >= batch_size:
            flush(batch)
            progress.update(len(batch))
            batch = []

    if batch:
        flush(batch)
        progress.update(len(batch))

    progress.close()


def create_embedder(device: str):
    from FlagEmbedding import BGEM3FlagModel

    use_fp16 = device == "cuda"
    return BGEM3FlagModel("BAAI/bge-m3", use_fp16=use_fp16, device=device)


def prepare_embedding_text(law_name: str, article_citation: str | None, article_text: str) -> str:
    prefix = f"[{law_name} / {article_citation or law_name}]"
    return f"{prefix}\n{article_text}"


def truncate_for_embedding(model: Any, text: str) -> tuple[str, bool, int]:
    tokens = model.tokenizer.encode(text, add_special_tokens=False)
    token_count = len(tokens)
    if token_count <= MAX_EMBED_TOKENS:
        return text, False, token_count
    prefix, body = text.split("\n", 1)
    prefix_tokens = model.tokenizer.encode(prefix + "\n", add_special_tokens=False)
    available = max(MAX_EMBED_TOKENS - len(prefix_tokens), 1)
    truncated_body_tokens = tokens[len(prefix_tokens): len(prefix_tokens) + available]
    truncated_body = model.tokenizer.decode(truncated_body_tokens, skip_special_tokens=True)
    return f"{prefix}\n{truncated_body}", True, token_count


def embed_pass(
    conn: psycopg.Connection[Any],
    *,
    embed_batch: int,
    device: str,
    counters: Counters,
    skip: bool,
) -> None:
    if skip:
        return

    model = create_embedder(device)
    started = time.perf_counter()
    done = 0
    truncated = 0

    while True:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT article_pk, law_name, article_citation, article_text
                FROM law_article
                WHERE embedded_at IS NULL
                ORDER BY article_pk
                LIMIT %s
                """,
                (embed_batch * 8,),
            )
            rows = cur.fetchall()
        if not rows:
            break

        payloads: list[tuple[str, str, bool, int]] = []
        for article_pk, law_name, article_citation, article_text in rows:
            embed_input = prepare_embedding_text(law_name, article_citation, article_text)
            prepared, was_truncated, token_count = truncate_for_embedding(model, embed_input)
            if was_truncated:
                truncated += 1
                append_log(LOG_DIR / "embed_fail.log", f"{article_pk}\ttruncated\t{token_count}")
            payloads.append((article_pk, prepared, was_truncated, token_count))

        texts = [item[1] for item in payloads]
        try:
            outputs = model.encode(
                texts,
                batch_size=embed_batch,
                return_dense=True,
                return_sparse=True,
                return_colbert_vecs=False,
            )
            dense_vecs = outputs["dense_vecs"]
            lexical_weights = outputs["lexical_weights"]
        except Exception as exc:
            for article_pk, _, _, _ in payloads:
                append_log(LOG_DIR / "embed_fail.log", f"{article_pk}\t{exc}")
            continue

        updates = []
        now = datetime.utcnow().isoformat()
        for (article_pk, _, was_truncated, _), dense, sparse in zip(payloads, dense_vecs, lexical_weights):
            updates.append(
                (
                    quote_vector(list(dense)),
                    json.dumps({str(k): float(v) for k, v in sparse.items()}, ensure_ascii=False),
                    was_truncated,
                    now,
                    article_pk,
                )
            )

        try:
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    UPDATE law_article
                    SET embedding = %s::vector,
                        sparse = %s::jsonb,
                        truncated_for_embed = %s,
                        embedded_at = %s::timestamptz
                    WHERE article_pk = %s
                    """,
                    updates,
                )
            conn.commit()
            done += len(updates)
            counters.embedded_rows += len(updates)
            counters.truncated_rows += sum(1 for _, _, was_truncated, _, _ in updates if was_truncated)
            if done % 5000 == 0:
                elapsed = time.perf_counter() - started
                rate = done / elapsed if elapsed else 0.0
                print(f"[pass=A] done={done} elapsed={elapsed:.1f}s rate={rate:.1f} rows/s", file=sys.stderr)
        except Exception as exc:
            conn.rollback()
            for _, _, _, _, article_pk in updates:
                append_log(LOG_DIR / "embed_fail.log", f"{article_pk}\t{exc}")


def create_kiwi():
    from kiwipiepy import Kiwi

    # kiwipiepy model_type names differ across releases. Prefer the
    # lightweight/default model but fall back safely so keywording can resume.
    for model_type in ("cong-global", "cong", "knlm", None):
        try:
            if model_type is None:
                return Kiwi()
            return Kiwi(model_type=model_type)
        except Exception:
            continue
    return Kiwi()


def extract_keywords(kiwi: Any, row: tuple[str, str | None, str | None, str], law_name: str) -> list[str]:
    article_title, article_citation, article_text, article_pk = row

    raw_tokens: list[str] = []

    for text in (law_name, article_title, article_citation, article_text):
        raw_tokens.extend(tokenize_keyword_terms(kiwi, text))
        raw_tokens.extend(compound_keywords(kiwi, text))

    return _stable_unique(raw_tokens)


def keyword_pass(
    conn: psycopg.Connection[Any],
    *,
    batch_size: int,
    counters: Counters,
    skip: bool,
) -> None:
    if skip:
        return

    kiwi = create_kiwi()
    started = time.perf_counter()
    done = 0

    while True:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT article_pk, law_name, article_title, article_citation, article_text
                FROM law_article
                WHERE keyworded_at IS NULL
                ORDER BY article_pk
                LIMIT %s
                """,
                (batch_size,),
            )
            rows = cur.fetchall()
        if not rows:
            break

        updates = []
        now = datetime.utcnow().isoformat()
        for article_pk, law_name, article_title, article_citation, article_text in rows:
            try:
                keywords = extract_keywords(kiwi, (article_title, article_citation, article_text, article_pk), law_name)
                updates.append((keywords, now, article_pk))
            except Exception as exc:
                append_log(LOG_DIR / "keyword_fail.log", f"{article_pk}\t{exc}")

        try:
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    UPDATE law_article
                    SET keywords = %s,
                        keyworded_at = %s::timestamptz
                    WHERE article_pk = %s
                    """,
                    updates,
                )
            conn.commit()
            done += len(updates)
            counters.keyworded_rows += len(updates)
            if done % 5000 == 0:
                elapsed = time.perf_counter() - started
                rate = done / elapsed if elapsed else 0.0
                print(f"[pass=B] done={done} elapsed={elapsed:.1f}s rate={rate:.1f} rows/s", file=sys.stderr)
        except Exception as exc:
            conn.rollback()
            for _, _, article_pk in updates:
                append_log(LOG_DIR / "keyword_fail.log", f"{article_pk}\t{exc}")


def create_final_indexes(conn: psycopg.Connection[Any], *, dry_run: bool) -> None:
    if dry_run:
        for stmt in CREATE_FINAL_INDEX_SQL:
            print(stmt.strip())
        return
    with conn.cursor() as cur:
        for stmt in CREATE_FINAL_INDEX_SQL:
            cur.execute(stmt)
    conn.commit()


def print_summary(conn: psycopg.Connection[Any], counters: Counters) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM law_article")
        total = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM law_article WHERE embedding IS NOT NULL")
        embedded = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM law_article WHERE coalesce(array_length(keywords, 1), 0) > 0")
        keyworded = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM law_article WHERE truncated_for_embed")
        truncated = cur.fetchone()[0]
    print(
        f"총 {counters.total_rows}건 / 적재 {total} / embedding {embedded} / keywords {keyworded} / truncated {truncated}",
        file=sys.stderr,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--jsonl", required=True)
    parser.add_argument("--dsn", default=os.getenv("PG_DSN") or os.getenv("DATABASE_URL"))
    parser.add_argument("--batch-size", type=int, default=UPSERT_BATCH_DEFAULT)
    parser.add_argument("--embed-batch", type=int, default=None)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--skip-ingest", action="store_true")
    parser.add_argument("--skip-embed", action="store_true")
    parser.add_argument("--skip-keywords", action="store_true")
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--delete-legacy-law", action="store_true")
    parser.add_argument("--skip-indexes", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.dsn:
        print("DSN is required via --dsn or PG_DSN/DATABASE_URL", file=sys.stderr)
        return 2

    jsonl_path = Path(args.jsonl)
    if not jsonl_path.exists():
        print(f"JSONL not found: {jsonl_path}", file=sys.stderr)
        return 2

    embed_batch = args.embed_batch or (EMBED_BATCH_CUDA if args.device == "cuda" else EMBED_BATCH_CPU)
    counters = Counters()

    conn = psycopg.connect(args.dsn, autocommit=False)
    try:
        if args.rebuild:
            maybe_drop_rebuild(conn, dry_run=args.dry_run)
        setup_schema(conn, dry_run=args.dry_run)
        if args.delete_legacy_law:
            maybe_delete_legacy_law(conn, dry_run=args.dry_run)
        if not args.skip_ingest:
            ingest_jsonl(
                conn,
                jsonl_path=jsonl_path,
                batch_size=args.batch_size,
                limit=args.limit,
                counters=counters,
                dry_run=args.dry_run,
            )
        if not args.dry_run:
            embed_pass(conn, embed_batch=embed_batch, device=args.device, counters=counters, skip=args.skip_embed)
            keyword_pass(conn, batch_size=args.batch_size, counters=counters, skip=args.skip_keywords)
            if not args.skip_indexes:
                create_final_indexes(conn, dry_run=False)
            print_summary(conn, counters)
        else:
            if not args.skip_indexes:
                create_final_indexes(conn, dry_run=True)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
