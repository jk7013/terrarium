from typing import Any


def _sliding_chunks(text: str, chunk_size_chars: int, overlap_chars: int) -> list[tuple[str, int, int]]:
    step = max(1, chunk_size_chars - overlap_chars)
    out: list[tuple[str, int, int]] = []
    for start in range(0, len(text), step):
        end = min(len(text), start + chunk_size_chars)
        piece = text[start:end].strip()
        if piece:
            out.append((piece, start, end))
        if end >= len(text):
            break
    return out


def chunk_record(
    row: dict[str, Any],
    *,
    chunk_size_chars: int = 900,
    overlap_chars: int = 180,
) -> list[dict[str, Any]]:
    text = str(row.get("text") or "").strip()
    if not text:
        return []

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    pieces: list[tuple[str, int, int]] = []
    if not paragraphs:
        pieces = _sliding_chunks(text, chunk_size_chars, overlap_chars)
    else:
        offset = 0
        for p in paragraphs:
            # 원문 오프셋 추정
            idx = text.find(p, offset)
            if idx < 0:
                idx = offset
            offset = idx + len(p)
            if len(p) <= chunk_size_chars:
                pieces.append((p, idx, idx + len(p)))
            else:
                for sub, s, e in _sliding_chunks(p, chunk_size_chars, overlap_chars):
                    pieces.append((sub, idx + s, idx + e))

    chunks: list[dict[str, Any]] = []
    doc_id = row["doc_id"]
    page_no = row.get("page_no")
    source_chunk_id = row.get("chunk_id")
    for chunk_no, (piece, start, end) in enumerate(pieces):
        if source_chunk_id:
            chunk_id = str(source_chunk_id) if len(pieces) == 1 else f"{source_chunk_id}:{chunk_no}"
        else:
            chunk_id = f"{doc_id}:{page_no if page_no is not None else 'na'}:{chunk_no}"
        chunks.append(
            {
                "chunk_id": chunk_id,
                "doc_id": doc_id,
                "chunk_no": chunk_no,
                "page_no": page_no,
                "text": piece,
                "lines": piece,
                "chunk_len": len(piece),
                "offset_start": start,
                "offset_end": end,
                "chapter_title": row.get("chapter_title"),
                "section_title": row.get("section_title"),
                "article_title": row.get("article_title"),
                "chapter_number": row.get("chapter_number"),
                "section_number": row.get("section_number"),
                "article_number": row.get("article_number"),
                "article_sub_number": row.get("article_sub_number"),
            }
        )

    for i, c in enumerate(chunks):
        c["prev_chunk_id"] = chunks[i - 1]["chunk_id"] if i > 0 else None
        c["next_chunk_id"] = chunks[i + 1]["chunk_id"] if i + 1 < len(chunks) else None
    return chunks
