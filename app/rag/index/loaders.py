import json
import hashlib
from pathlib import Path
from typing import Any


def _stable_doc_id(row: dict[str, Any]) -> str:
    raw = str(row.get("doc_id") or "").strip()
    if raw:
        return raw
    base = str(row.get("filepath") or row.get("title") or row.get("text") or "")
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:24]


def load_jsonl_records(path: str) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.exists() or not p.is_file():
        raise FileNotFoundError(f"jsonl file not found: {path}")
    if p.suffix.lower() != ".jsonl":
        raise ValueError("v1 only supports .jsonl input")

    out: list[dict[str, Any]] = []
    with p.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            text = str(row.get("text") or "").strip()
            if not text:
                continue
            row["doc_id"] = _stable_doc_id(row)
            row["text"] = text
            row.setdefault("title", None)
            row.setdefault("filepath", None)
            row.setdefault("fmt", None)
            row.setdefault("page_no", None)
            row.setdefault("chapter_title", None)
            row.setdefault("section_title", None)
            row.setdefault("article_title", None)
            row.setdefault("chapter_number", None)
            row.setdefault("section_number", None)
            row.setdefault("article_number", None)
            row.setdefault("article_sub_number", None)
            row["_line_no"] = line_no
            out.append(row)
    return out
