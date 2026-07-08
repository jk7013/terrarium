import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg

from app.db.connection import get_db_url


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{float(v):.8f}" for v in values) + "]"


@dataclass
class RetrievedChunk:
    chunk_id: str
    doc_id: str
    filepath: str | None
    page_no: int | None
    chunk_no: int | None
    text: str
    distance: float


class PgVectorStore:
    def __init__(self, db_url: str | None = None) -> None:
        self.db_url = db_url or get_db_url()
        self.schema_path = Path(__file__).parents[1] / "db" / "schema.sql"

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self.db_url, autocommit=True)

    def ensure_schema(self) -> None:
        schema_sql = self.schema_path.read_text(encoding="utf-8")
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(schema_sql)

    def rebuild(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("DROP TABLE IF EXISTS chunks CASCADE")
                cur.execute("DROP TABLE IF EXISTS documents CASCADE")
                cur.execute("DROP TABLE IF EXISTS retrieval_logs CASCADE")

    def upsert_document(
        self,
        *,
        doc_id: str,
        title: str | None,
        filepath: str | None,
        fmt: int | None,
    ) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO documents (doc_id, title, filepath, fmt)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (doc_id) DO UPDATE
                    SET title = EXCLUDED.title,
                        filepath = EXCLUDED.filepath,
                        fmt = EXCLUDED.fmt
                    """,
                    (doc_id, title, filepath, fmt),
                )

    def upsert_chunks(
        self,
        *,
        doc_id: str,
        chunks: list[dict[str, Any]],
    ) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                for item in chunks:
                    cur.execute(
                        """
                        INSERT INTO chunks (
                            chunk_id, doc_id, prev_chunk_id, next_chunk_id, chunk_no, page_no, text, lines,
                            chunk_len, tags, keywords, ngram, chapter_title, section_title, article_title,
                            chapter_number, section_number, article_number, article_sub_number, embedding
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s::vector
                        )
                        ON CONFLICT (chunk_id) DO UPDATE
                        SET prev_chunk_id = EXCLUDED.prev_chunk_id,
                            next_chunk_id = EXCLUDED.next_chunk_id,
                            chunk_no = EXCLUDED.chunk_no,
                            page_no = EXCLUDED.page_no,
                            text = EXCLUDED.text,
                            lines = EXCLUDED.lines,
                            chunk_len = EXCLUDED.chunk_len,
                            tags = EXCLUDED.tags,
                            keywords = EXCLUDED.keywords,
                            ngram = EXCLUDED.ngram,
                            chapter_title = EXCLUDED.chapter_title,
                            section_title = EXCLUDED.section_title,
                            article_title = EXCLUDED.article_title,
                            chapter_number = EXCLUDED.chapter_number,
                            section_number = EXCLUDED.section_number,
                            article_number = EXCLUDED.article_number,
                            article_sub_number = EXCLUDED.article_sub_number,
                            embedding = EXCLUDED.embedding
                        """,
                        (
                            item["chunk_id"],
                            doc_id,
                            item.get("prev_chunk_id"),
                            item.get("next_chunk_id"),
                            item.get("chunk_no"),
                            item.get("page_no"),
                            item["text"],
                            item.get("lines", item["text"]),
                            item["chunk_len"],
                            item.get("tags", []),
                            item.get("keywords", []),
                            item.get("ngram"),
                            item.get("chapter_title"),
                            item.get("section_title"),
                            item.get("article_title"),
                            item.get("chapter_number"),
                            item.get("section_number"),
                            item.get("article_number"),
                            item.get("article_sub_number"),
                            _vector_literal(item["embedding"]),
                        ),
                    )

    def search_cosine(self, query_embedding: list[float], top_k: int) -> list[RetrievedChunk]:
        vector = _vector_literal(query_embedding)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        c.chunk_id,
                        c.doc_id,
                        d.filepath,
                        c.page_no,
                        c.chunk_no,
                        c.text,
                        (c.embedding <=> %s::vector) AS distance
                    FROM chunks c
                    JOIN documents d ON d.doc_id = c.doc_id
                    WHERE c.embedding IS NOT NULL
                    ORDER BY c.embedding <=> %s::vector
                    LIMIT %s
                    """,
                    (vector, vector, top_k),
                )
                rows = cur.fetchall()

        return [
            RetrievedChunk(
                chunk_id=row[0],
                doc_id=row[1],
                filepath=row[2],
                page_no=row[3],
                chunk_no=row[4],
                text=row[5],
                distance=float(row[6]),
            )
            for row in rows
        ]

    def status(self) -> dict[str, Any]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM documents")
                document_count = int(cur.fetchone()[0])
                cur.execute("SELECT COUNT(*) FROM chunks")
                chunk_count = int(cur.fetchone()[0])
                cur.execute("SELECT MAX(created_at) FROM chunks")
                latest_chunk_at = cur.fetchone()[0]
        return {
            "document_count": document_count,
            "chunk_count": chunk_count,
            "latest_chunk_at": latest_chunk_at.isoformat() if latest_chunk_at else None,
        }

    def log_retrieval(
        self,
        *,
        query: str,
        expanded_query: str | None,
        used_tool: str | None,
        top_k: int,
        results: list[dict[str, Any]],
        latency_ms: int,
    ) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO retrieval_logs (query, expanded_query, top_k, results, latency_ms, used_tool)
                    VALUES (%s, %s, %s, %s::jsonb, %s, %s)
                    """,
                    (
                        query,
                        expanded_query,
                        top_k,
                        json.dumps(results, ensure_ascii=False),
                        latency_ms,
                        used_tool,
                    ),
                )
