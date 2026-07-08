# app/llm/client.py

import os
import time
from typing import Tuple, Optional, List, Dict

import httpx

from app.api.schemas.query import LLMTrace


# Ollama 설정
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:4b")
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "bge-m3")

# 기본 모델 (환경변수 또는 Ollama 기본값)
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", OLLAMA_MODEL)
OFFLINE_MODE = os.getenv("OFFLINE_MODE", "true").lower() == "true"

# OpenAI 계열 모델 접두사 — 이 접두사로 시작하면 OpenAI API로 라우팅
_OPENAI_PREFIXES = ("gpt-", "o1-", "o3-", "o4-")


def is_openai_model(model: str) -> bool:
    """모델명이 OpenAI 계열인지 판별."""
    return model.startswith(_OPENAI_PREFIXES)


async def call_llm(
    prompt: str,
    model: str | None = None,
    chat_history: Optional[List[Dict[str, str]]] = None,
) -> Tuple[str, LLMTrace]:
    """
    Terrarium에서 LLM 한 번 호출할 때 쓰는 공용 함수.
    모델명에 따라 OpenAI 또는 Ollama로 자동 라우팅.

    - model: 사용할 모델명 (None이면 DEFAULT_MODEL 사용)
    - prompt: 우리가 구성한 프롬프트 (질문 + 컨텍스트)
    - chat_history: 이전 대화 히스토리 (선택사항, 멀티턴 대화용)
    - return: (LLM이 생성한 텍스트, LLMTrace)
    """
    model = model or DEFAULT_MODEL

    if is_openai_model(model):
        if OFFLINE_MODE:
            raise RuntimeError("OFFLINE_MODE에서는 OpenAI 모델을 사용할 수 없습니다.")
        from app.llm.openai_client import call_openai
        return await call_openai(prompt, model=model, chat_history=chat_history)

    # Ollama 호출
    return await _call_ollama(prompt, model=model, chat_history=chat_history)


async def _call_ollama(
    prompt: str,
    model: str,
    chat_history: Optional[List[Dict[str, str]]] = None,
) -> Tuple[str, LLMTrace]:
    """Ollama 호출 (기존 로직)."""
    url = f"{OLLAMA_HOST}/api/chat"

    messages = []
    if chat_history:
        messages.extend(chat_history)
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
    }

    start = time.perf_counter()

    timeout = httpx.Timeout(300.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        try:
            data = resp.json()
        except ValueError as exc:
            raise RuntimeError("Ollama 응답이 JSON 형식이 아닙니다.") from exc

    elapsed_ms = int((time.perf_counter() - start) * 1000)

    message = data.get("message", {})
    if isinstance(message, dict):
        output_text = str(message.get("content", ""))
    else:
        output_text = str(data.get("response", ""))

    trace = LLMTrace(
        model=model,
        prompt=prompt,
        output=output_text,
        latency_ms=elapsed_ms,
        input_tokens=None,
        output_tokens=None,
    )

    return output_text, trace


async def embed_texts(texts: List[str]) -> List[List[float]]:
    """
    Ollama 임베딩 API를 사용해 여러 텍스트를 임베딩한다.
    """
    timeout = httpx.Timeout(120.0, connect=10.0)
    vectors: List[List[float]] = []
    async with httpx.AsyncClient(timeout=timeout) as client:
        for text in texts:
            embedding: List[float] | None = None

            # 구버전 호환: /api/embeddings
            resp = await client.post(
                f"{OLLAMA_HOST}/api/embeddings",
                json={"model": OLLAMA_EMBED_MODEL, "prompt": text},
            )
            if resp.status_code == 404:
                # 신버전 호환: /api/embed
                resp = await client.post(
                    f"{OLLAMA_HOST}/api/embed",
                    json={"model": OLLAMA_EMBED_MODEL, "input": text},
                )
                resp.raise_for_status()
                data = resp.json()
                embeds = data.get("embeddings")
                if isinstance(embeds, list) and embeds and isinstance(embeds[0], list):
                    embedding = [float(v) for v in embeds[0]]
            else:
                resp.raise_for_status()
                data = resp.json()
                emb = data.get("embedding")
                if isinstance(emb, list):
                    embedding = [float(v) for v in emb]

            if embedding is None:
                raise RuntimeError("Ollama 임베딩 응답 포맷이 올바르지 않습니다.")
            vectors.append(embedding)
    return vectors
