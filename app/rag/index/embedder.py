from app.llm.client import embed_texts


async def embed_chunks(texts: list[str]) -> list[list[float]]:
    vectors = await embed_texts(texts)
    for i, v in enumerate(vectors):
        if len(v) != 1024:
            raise RuntimeError(f"embedding dim mismatch at index={i}: expected 1024, got {len(v)}")
    return vectors
