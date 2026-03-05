CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
    doc_id TEXT PRIMARY KEY,
    title TEXT NULL,
    filepath TEXT NULL,
    fmt SMALLINT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    prev_chunk_id TEXT NULL,
    next_chunk_id TEXT NULL,
    chunk_no INT NULL,
    page_no INT NULL,
    text TEXT NOT NULL,
    lines TEXT NULL,
    chunk_len INT NOT NULL,
    tags TEXT[] NOT NULL DEFAULT '{}',
    keywords TEXT[] NOT NULL DEFAULT '{}',
    ngram TEXT NULL,
    chapter_title TEXT NULL,
    section_title TEXT NULL,
    article_title TEXT NULL,
    chapter_number INT NULL,
    section_number INT NULL,
    article_number INT NULL,
    article_sub_number INT NULL,
    embedding VECTOR(1024) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS retrieval_logs (
    id BIGSERIAL PRIMARY KEY,
    query TEXT NOT NULL,
    expanded_query TEXT NULL,
    top_k INT NOT NULL,
    results JSONB NOT NULL,
    latency_ms INT NOT NULL,
    used_tool TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chunks_embedding_hnsw
    ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_chunks_doc_id ON chunks(doc_id);
CREATE INDEX IF NOT EXISTS idx_chunks_filepath ON documents(filepath);
CREATE INDEX IF NOT EXISTS idx_chunks_page_no ON chunks(page_no);
