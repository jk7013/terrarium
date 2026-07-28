# app/llm/openai_client.py

import os
import time
from typing import Tuple, Optional, List, Dict

import httpx

from app.api.schemas.query import LLMTrace


OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

_TIMEOUT_S = 120.0
_CONNECT_TIMEOUT_S = 10.0


async def call_openai(
    prompt: str,
    model: str | None = None,
    chat_history: Optional[List[Dict[str, str]]] = None,
) -> Tuple[str, LLMTrace]:
    """
    OpenAI Chat Completions API 호출.
    jido의 OpenAIProvider 패턴을 참고하되, terrarium 구조에 맞게 단순화.
    """
    model = model or OPENAI_DEFAULT_MODEL
    url = f"{OPENAI_BASE_URL.rstrip('/')}/chat/completions"

    messages: list[dict] = []
    if chat_history:
        messages.extend(chat_history)
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": model,
        "messages": messages,
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OPENAI_API_KEY}",
    }

    start = time.perf_counter()

    timeout = httpx.Timeout(_TIMEOUT_S, connect=_CONNECT_TIMEOUT_S)
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()

    elapsed_ms = int((time.perf_counter() - start) * 1000)

    # OpenAI 응답 파싱: choices[0].message.content
    try:
        output_text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise RuntimeError("OpenAI 응답 파싱 실패: choices[0].message.content 없음")

    usage = data.get("usage") or {}
    actual_model = data.get("model", model)

    trace = LLMTrace(
        model=actual_model,
        prompt=prompt,
        output=output_text,
        latency_ms=elapsed_ms,
        input_tokens=usage.get("prompt_tokens"),
        output_tokens=usage.get("completion_tokens"),
    )

    return output_text, trace
