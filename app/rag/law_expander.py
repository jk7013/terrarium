"""
법령 연계법령 확장 모듈

검색 결과에 law 소스 청크가 있으면:
  1. 같은 조(article_title 기준) 전체 청크 수집
  2. linked_refs에서 참조 조문 청크 추가 수집
  3. 전체 컨텍스트 MAX_EXPAND_CHARS 이내로 제한

article_key 기반 매칭:
  - 제16조 → 0016001, 제16조의3 → 0016031 (서로 다른 조)
  - article_number INT로는 둘 다 16이라 구분 불가
  - article_title로 같은 조를 식별

조문 유형별 확장 정책:
  - substantive: 전체 확장 (ARTICLE_CAP 적용)
  - meta_penalty: 확장 제외 (벌칙/과태료, 면접 답변 무관)
  - meta_enumeration: 확장 제외 (조문 나열형)
  - meta_jungyong: 조건부 포함 (질문이 절차/결의/준용/적용기준일 때만)
  - meta_delegation: 조건부 포함 (직접 hit / 참조 대상 / 하위법령 트리거)
  - meta_definition: ARTICLE_CAP 적용

사용:
  expander = LawExpander(db_url)
  expanded = expander.expand(search_results, query="스톡옵션 행사가격")
"""

import json
import re
from typing import Optional

import psycopg

from app.db.connection import get_db_url

MAX_EXPAND_CHARS = 6_000
MAX_REF_ARTICLES = 3
ARTICLE_CAP = 1_500
REF_ARTICLE_CAP = 1_000

# 확장 무조건 제외 유형
SKIP_TYPES = {"meta_penalty", "meta_enumeration"}

# 준용규정 포함 트리거 키워드 (질문에 이 중 하나라도 있으면 준용규정 포함)
JUNGYONG_TRIGGER_KEYWORDS = {"절차", "결의", "준용", "적용기준", "적용 기준", "의결", "의결권"}


class ArticleFlags:
    """조문의 보조 플래그. 단일 분류만으로 잡히지 않는 복합 유형 표현."""
    __slots__ = ("is_exception", "has_delegation", "has_incorporation")

    def __init__(self, text: str):
        self.is_exception = bool(
            re.search(r"에도\s*불구하고", text)
            or re.search(r"다만[,\s]", text)
            or "예외로" in text
        )
        self.has_delegation = bool(
            re.search(
                r"(?:대통령령|부령|고시|대법원규칙)(?:으로|에서|로)\s*정(?:하[는은]|한)",
                text,
            )
        )
        self.has_incorporation = bool(re.search(r"준용", text))

    def __repr__(self) -> str:
        parts = []
        if self.is_exception:
            parts.append("exception")
        if self.has_delegation:
            parts.append("delegation")
        if self.has_incorporation:
            parts.append("incorporation")
        return f"Flags({','.join(parts) or 'none'})"


# exception 패턴: "에도 불구하고", "다만", "예외로", "제N항에도 불구하고", "제N조의M에도 불구하고"
_EXCEPTION_RE = re.compile(
    r"제\d+(?:조(?:의\d+)?|항)에도\s*불구하고|다만[,\s]|예외로"
)

# delegation 패턴: 대통령령/부령/고시/대법원규칙으로 정한/정하는/정한다
_DELEGATION_RE = re.compile(
    r"(?:대통령령|부령|고시|대법원규칙)(?:으로|에서|로)\s*정(?:하[는은]|한)"
)


def classify_article(article_title: str | None, text: str) -> tuple[str, ArticleFlags]:
    """
    조문 텍스트 기반 유형 분류.
    Returns (type_str, ArticleFlags).

    분류 우선순위:
      1. 준용규정 (title 기반)
      2. 벌칙/과태료 (title 기반)
      3. 정의/목적 (title 기반)
      4. 나열형 (본문 기반)
      5. exception ("에도 불구하고", "다만") → substantive (exception이 delegation보다 우선)
      6. delegation ("대통령령으로 정하는" 등)
      7. substantive (기본)
    """
    title = article_title or ""
    flags = ArticleFlags(text)

    if re.search(r"준용", title):
        return "meta_jungyong", flags
    if re.search(r"벌칙|과태료|징역|벌금", title):
        return "meta_penalty", flags
    if re.search(r"정의|목적", title):
        return "meta_definition", flags
    # 본문에 조문 참조가 5개 이상이고 짧으면 나열형
    if len(re.findall(r"제\d+조", text)) >= 5 and len(text) < 500:
        return "meta_enumeration", flags
    # exception 패턴이 있으면 delegation보다 우선 → substantive
    if _EXCEPTION_RE.search(text):
        return "substantive", flags
    # delegation 패턴 (정한/정하는 모두 포함)
    if _DELEGATION_RE.search(text):
        return "meta_delegation", flags
    return "substantive", flags


def _should_include_article(
    article_type: str,
    *,
    is_direct_hit: bool = False,
    is_referenced: bool = False,
    query: str = "",
) -> bool:
    """조문 유형별 확장 포함 여부 결정"""
    if article_type in SKIP_TYPES:
        return False

    if article_type == "meta_jungyong":
        # 질문이 절차/결의/준용/적용기준 관련이면 포함
        return any(kw in query for kw in JUNGYONG_TRIGGER_KEYWORDS)

    if article_type == "meta_delegation":
        # 직접 hit 또는 참조 대상이면 포함 (하위법령 탐색 트리거 역할)
        return is_direct_hit or is_referenced

    # substantive, meta_definition → 포함
    return True


def _parse_article_key(article_str: str) -> Optional[str]:
    """
    '제2조' → '0002001', '제16조의3' → '0016031'
    article_key 형식: NNNNXXY (N=조번호 4자리, XX=의X 2자리, Y=1 고정)
    """
    if not article_str:
        return None
    m = re.match(r"제(\d+)조(?:의(\d+))?", article_str)
    if not m:
        return None
    num = int(m.group(1))
    sub = int(m.group(2)) if m.group(2) else 0
    return f"{num:04d}{sub:02d}1"


class LawExpander:
    def __init__(self, db_url: str | None = None):
        self.db_url = db_url or get_db_url()

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self.db_url)

    def _fetch_article_chunks_by_title(
        self,
        cur,
        law_name: str,
        article_title: str,
    ) -> list[dict]:
        """같은 법률 + article_title의 청크 전부 조회"""
        cur.execute("""
            SELECT chunk_id, text, chunk_len, article_title, article_number,
                   article_key, linked_refs
            FROM chunks
            WHERE 'law' = ANY(tags)
              AND section_title = %s
              AND article_title = %s
            ORDER BY chunk_no
        """, (law_name, article_title))
        return [
            {
                "chunk_id": r[0],
                "text": r[1],
                "chunk_len": r[2],
                "article_title": r[3],
                "article_number": r[4],
                "article_key": r[5],
                "linked_refs": r[6],
                "law_name": law_name,
            }
            for r in cur.fetchall()
        ]

    def _fetch_article_chunks_by_key(
        self,
        cur,
        law_name: str,
        article_key: str,
    ) -> list[dict]:
        """같은 법률 + article_key의 청크 전부 조회"""
        cur.execute("""
            SELECT chunk_id, text, chunk_len, article_title, article_number,
                   article_key, linked_refs
            FROM chunks
            WHERE 'law' = ANY(tags)
              AND section_title = %s
              AND article_key = %s
            ORDER BY chunk_no
        """, (law_name, article_key))
        return [
            {
                "chunk_id": r[0],
                "text": r[1],
                "chunk_len": r[2],
                "article_title": r[3],
                "article_number": r[4],
                "article_key": r[5],
                "linked_refs": r[6],
                "law_name": law_name,
            }
            for r in cur.fetchall()
        ]

    def expand(self, search_results: list[dict], query: str = "") -> list[dict]:
        """
        검색 결과를 받아 law 소스 청크에 대해 연계법령 확장.
        상위 5개 law 청크만 확장 대상.
        """
        law_results = [
            r for r in search_results
            if r.get("metadata", {}).get("source") == "law"
            or (r.get("metadata", {}).get("tags") and "law" in r["metadata"]["tags"])
        ]

        if not law_results:
            return search_results

        # 상위 5개만 확장 대상
        law_results = law_results[:5]

        with self._connect() as conn:
            with conn.cursor() as cur:
                for result in law_results:
                    meta = result.get("metadata", {})
                    law_name = meta.get("section_title")
                    article_title = meta.get("article_title")

                    if not law_name or not article_title:
                        continue

                    expanded = self._expand_single(
                        cur, law_name, article_title,
                        query=query, is_direct_hit=True,
                    )
                    result["expanded_context"] = expanded

        return search_results

    def _expand_single(
        self,
        cur,
        law_name: str,
        article_title: str,
        *,
        query: str = "",
        is_direct_hit: bool = False,
    ) -> list[dict]:
        """단일 조문에 대한 확장 수행 (article_title 기준)"""
        context_parts: list[dict] = []
        total_chars = 0

        # 1단계: 같은 조(article_title) 전체 청크
        article_chunks = self._fetch_article_chunks_by_title(
            cur, law_name, article_title,
        )

        if not article_chunks:
            return context_parts

        # 조문 유형 분류 (전체 텍스트 기반)
        full_text = " ".join(c["text"] for c in article_chunks)
        article_type, flags = classify_article(article_title, full_text)

        # 유형별 확장 포함 여부 판단
        if not _should_include_article(
            article_type,
            is_direct_hit=is_direct_hit,
            is_referenced=False,
            query=query,
        ):
            return context_parts

        # ARTICLE_CAP 적용: 조 전체가 cap 초과 시 축약
        article_total = sum(c["chunk_len"] for c in article_chunks)
        if article_total > ARTICLE_CAP and len(article_chunks) > 2:
            # 앞 부분 + 마지막 = 핵심만
            article_chunks = article_chunks[:1] + article_chunks[-1:]

        for c in article_chunks:
            if total_chars + c["chunk_len"] > ARTICLE_CAP:
                break
            context_parts.append({
                "law_name": c["law_name"],
                "article_number": c["article_number"],
                "article_title": c["article_title"],
                "article_key": c.get("article_key"),
                "text": c["text"],
                "is_ref": False,
                "article_type": article_type,
                "flags": repr(flags),
            })
            total_chars += c["chunk_len"]

        # 2단계: linked_refs에서 참조 조문 수집
        all_refs = []
        for c in article_chunks:
            if c.get("linked_refs"):
                refs = c["linked_refs"]
                if isinstance(refs, str):
                    refs = json.loads(refs)
                all_refs.extend(refs)

        # 중복 제거 + 참조 대상 결정
        seen_refs: set[tuple[str, str]] = set()
        ref_targets: list[tuple[str, str]] = []

        # 현재 조의 article_key
        current_key = None
        for c in article_chunks:
            if c.get("article_key"):
                current_key = c["article_key"]
                break

        for ref in all_refs:
            ref_law = ref.get("law_name", "")
            ref_article_str = ref.get("article", "")
            ref_type = ref.get("type", "")

            if ref_type == "위임":
                continue

            ref_key = _parse_article_key(ref_article_str)
            if not ref_key:
                continue

            if ref_law == law_name and ref_key == current_key:
                continue

            key = (ref_law, ref_key)
            if key in seen_refs:
                continue
            seen_refs.add(key)
            ref_targets.append(key)

        ref_targets = ref_targets[:MAX_REF_ARTICLES]

        # 참조 조문 청크 조회
        for ref_law, ref_key in ref_targets:
            if total_chars >= MAX_EXPAND_CHARS:
                break

            ref_chunks = self._fetch_article_chunks_by_key(cur, ref_law, ref_key)
            if not ref_chunks:
                continue

            # 참조 조문도 유형 분류
            ref_full_text = " ".join(c["text"] for c in ref_chunks)
            ref_article_title = ref_chunks[0].get("article_title", "")
            ref_type, ref_flags = classify_article(ref_article_title, ref_full_text)

            if not _should_include_article(
                ref_type,
                is_direct_hit=False,
                is_referenced=True,
                query=query,
            ):
                continue

            # REF_ARTICLE_CAP 적용
            ref_total = sum(c["chunk_len"] for c in ref_chunks)
            if ref_total > REF_ARTICLE_CAP and len(ref_chunks) > 1:
                ref_chunks = ref_chunks[:1]

            for c in ref_chunks:
                if total_chars + c["chunk_len"] > MAX_EXPAND_CHARS:
                    break
                context_parts.append({
                    "law_name": c["law_name"],
                    "article_number": c["article_number"],
                    "article_title": c["article_title"],
                    "article_key": c.get("article_key"),
                    "text": c["text"],
                    "is_ref": True,
                    "article_type": ref_type,
                    "flags": repr(ref_flags),
                })
                total_chars += c["chunk_len"]

        return context_parts
