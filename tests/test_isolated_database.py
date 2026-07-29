import os
import uuid
from urllib.parse import urlsplit

import psycopg
import pytest

from app.store.pgvector_store import PgVectorStore


def _isolated_test_db_url() -> str:
    db_url = os.getenv("TEST_DATABASE_URL", "")
    if not db_url:
        pytest.skip("TEST_DATABASE_URL is only provided by docker-compose.test.yml")

    parsed = urlsplit(db_url)
    if parsed.path != "/terrarium_test" or parsed.hostname != "terrarium-test-db":
        pytest.fail("integration tests refused a database outside the isolated test service")
    return db_url


@pytest.mark.integration
def test_pgvector_store_uses_isolated_database() -> None:
    db_url = _isolated_test_db_url()
    store = PgVectorStore(db_url=db_url)
    store.ensure_schema()

    doc_id = f"test-doc-{uuid.uuid4().hex}"
    chunk_id = f"{doc_id}:na:0"
    text = "isolated database smoke test"
    embedding = [0.0] * 1024
    embedding[0] = 1.0

    try:
        store.upsert_document(
            doc_id=doc_id,
            title="isolated test document",
            filepath="test://isolated",
            fmt=None,
        )
        store.upsert_chunks(
            doc_id=doc_id,
            chunks=[
                {
                    "chunk_id": chunk_id,
                    "chunk_no": 0,
                    "page_no": None,
                    "text": text,
                    "chunk_len": len(text),
                    "tags": ["test"],
                    "keywords": ["isolated", "test"],
                    "embedding": embedding,
                }
            ],
        )

        with psycopg.connect(db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT tags FROM chunks WHERE chunk_id = %s",
                    (chunk_id,),
                )
                assert cur.fetchone() == (["test"],)
    finally:
        with psycopg.connect(db_url, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM documents WHERE doc_id = %s", (doc_id,))
