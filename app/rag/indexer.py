import json
import uuid
from pathlib import Path
from typing import Any

from app.llm.client import embed_texts


def _chunk_text(text: str, chunk_size: int, chunk_overlap: int) -> list[dict[str, Any]]:
    if not text.strip():
        return []
    step = max(1, chunk_size - chunk_overlap)
    chunks: list[dict[str, Any]] = []
    chunk_no = 0
    for start in range(0, len(text), step):
        end = min(len(text), start + chunk_size)
        piece = text[start:end].strip()
        if not piece:
            continue
        chunks.append(
            {
                "chunk_id": str(uuid.uuid4()),
                "chunk_no": chunk_no,
                "offset_start": start,
                "offset_end": end,
                "text": piece,
                "page": None,
            }
        )
        chunk_no += 1
        if end == len(text):
            break
    return chunks


def load_documents_from_path(path: str) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"index path not found: {path}")

    docs: list[dict[str, Any]] = []
    if p.is_file():
        docs.extend(_load_file(p))
    else:
        for file_path in sorted(p.rglob("*")):
            if file_path.is_file():
                docs.extend(_load_file(file_path))
    return docs


def _load_file(file_path: Path) -> list[dict[str, Any]]:
    suffix = file_path.suffix.lower()
    if suffix in {".txt", ".md"}:
        text = file_path.read_text(encoding="utf-8", errors="ignore")
        return [
            {
                "title": file_path.stem,
                "source_path": str(file_path),
                "doc_type": suffix.lstrip("."),
                "text": text,
            }
        ]
    if suffix == ".jsonl":
        out: list[dict[str, Any]] = []
        with file_path.open("r", encoding="utf-8") as f:
            for i, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                text = str(row.get("text", "")).strip()
                if not text:
                    continue
                out.append(
                    {
                        "title": str(row.get("title") or f"{file_path.stem}_{i}"),
                        "source_path": str(row.get("source_path") or file_path),
                        "doc_type": str(row.get("doc_type") or "jsonl"),
                        "text": text,
                    }
                )
        return out
    return []


async def build_chunks_with_embeddings(
    *,
    text: str,
    chunk_size: int,
    chunk_overlap: int,
) -> list[dict[str, Any]]:
    chunks = _chunk_text(text, chunk_size, chunk_overlap)
    if not chunks:
        return []

    embeddings = await embed_texts([c["text"] for c in chunks])
    if len(embeddings) != len(chunks):
        raise RuntimeError("embedding count mismatch")

    for c, emb in zip(chunks, embeddings):
        c["embedding"] = emb
    return chunks
