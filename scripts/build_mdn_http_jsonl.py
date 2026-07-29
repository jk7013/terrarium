#!/usr/bin/env python3
"""Build a deterministic Korean MDN HTTP JSONL corpus."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

FRONTMATTER_RE = re.compile(
    r"\A---[ \t]*\r?\n(?P<yaml>.*?)\r?\n---[ \t]*(?:\r?\n|\Z)",
    re.DOTALL,
)
MDN_MACRO_RE = re.compile(r"\{\{.*?\}\}", re.DOTALL)
MIN_BODY_CHARS = 200


@dataclass(frozen=True)
class DocumentSpec:
    doc_id: str
    relative_path: str


DOCUMENTS = (
    DocumentSpec("mdn-http-overview", "files/ko/web/http/guides/overview/index.md"),
    DocumentSpec("mdn-http-messages", "files/ko/web/http/guides/messages/index.md"),
    DocumentSpec("mdn-http-session", "files/ko/web/http/guides/session/index.md"),
    DocumentSpec("mdn-http-caching", "files/ko/web/http/guides/caching/index.md"),
    DocumentSpec("mdn-http-cookies", "files/ko/web/http/guides/cookies/index.md"),
    DocumentSpec("mdn-http-cors", "files/ko/web/http/guides/cors/index.md"),
    DocumentSpec(
        "mdn-http-status-codes", "files/ko/web/http/reference/status/index.md"
    ),
    DocumentSpec("mdn-http-headers", "files/ko/web/http/reference/headers/index.md"),
    DocumentSpec("mdn-http-methods", "files/ko/web/http/reference/methods/index.md"),
    DocumentSpec(
        "mdn-http-content-negotiation",
        "files/ko/web/http/guides/content_negotiation/index.md",
    ),
    DocumentSpec(
        "mdn-http-authentication",
        "files/ko/web/http/guides/authentication/index.md",
    ),
    DocumentSpec(
        "mdn-http-redirections",
        "files/ko/web/http/guides/redirections/index.md",
    ),
)


def parse_document(path: Path) -> tuple[dict[str, object], str]:
    raw = path.read_text(encoding="utf-8")
    match = FRONTMATTER_RE.match(raw)
    if match is None:
        raise ValueError("leading YAML frontmatter not found")

    metadata = yaml.safe_load(match.group("yaml"))
    if not isinstance(metadata, dict):
        raise ValueError("YAML frontmatter is not an object")

    title = metadata.get("title")
    slug = metadata.get("slug")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("frontmatter title is missing")
    if not isinstance(slug, str) or not slug.startswith("Web/HTTP/"):
        raise ValueError("frontmatter HTTP slug is missing or invalid")

    body = raw[match.end() :]
    body = MDN_MACRO_RE.sub("", body)
    if len(body.strip()) < MIN_BODY_CHARS:
        raise ValueError(f"processed body is shorter than {MIN_BODY_CHARS} characters")
    return metadata, body


def build_records(source_root: Path) -> tuple[list[dict[str, str]], list[str]]:
    records: list[dict[str, str]] = []
    skipped: list[str] = []

    for spec in DOCUMENTS:
        path = source_root / spec.relative_path
        if not path.is_file():
            skipped.append(f"{spec.relative_path}: file not found")
            continue
        try:
            metadata, body = parse_document(path)
        except (OSError, UnicodeError, ValueError, yaml.YAMLError) as exc:
            skipped.append(f"{spec.relative_path}: {exc}")
            continue

        records.append(
            {
                "doc_id": spec.doc_id,
                "title": str(metadata["title"]),
                "filepath": (
                    "https://developer.mozilla.org/ko/docs/" f"{metadata['slug']}"
                ),
                "text": body,
            }
        )

    return records, skipped


def write_jsonl(records: list[dict[str, str]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as output:
        for record in records:
            output.write(
                json.dumps(
                    record,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=False,
                )
            )
            output.write("\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a Korean MDN HTTP corpus in Terrarium JSONL format."
    )
    parser.add_argument(
        "source_root",
        type=Path,
        help="Root of a shallow mdn/translated-content checkout.",
    )
    parser.add_argument("output_path", type=Path, help="Destination .jsonl path.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    records, skipped = build_records(args.source_root.resolve())
    for reason in skipped:
        print(f"SKIP {reason}", file=sys.stderr)
    if len(records) < 10:
        print(
            f"Refusing to write corpus: only {len(records)} valid documents found.",
            file=sys.stderr,
        )
        return 1

    write_jsonl(records, args.output_path.resolve())
    print(f"Wrote {len(records)} documents to {args.output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
