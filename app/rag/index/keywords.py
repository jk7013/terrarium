import re

STOPWORDS = {
    "그리고", "그러나", "또한", "이것", "그것", "저것",
    "에서", "으로", "하다", "한다", "대한", "관련", "위한",
    "the", "and", "for", "with",
}


def extract_keywords(text: str, limit: int = 10) -> list[str]:
    article_patterns = re.findall(r"(제\s*\d+\s*조|별표\s*\d+)", text)
    tokens = re.findall(r"[A-Za-z0-9가-힣]{2,10}", text)
    candidates: list[str] = []
    seen: set[str] = set()
    for t in article_patterns + tokens:
        k = t.strip()
        if not k or k in STOPWORDS:
            continue
        if k in seen:
            continue
        seen.add(k)
        candidates.append(k)
        if len(candidates) >= limit:
            break
    return candidates
