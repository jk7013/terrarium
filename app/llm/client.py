# app/llm/client.py

import os
import time
from typing import Tuple, Optional, List, Dict

import httpx

from app.api.schemas.query import LLMTrace


# 나중에 .env로 바꾸기 쉽게 환경변수로 빼두자
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:4b")
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "bge-m3")


async def call_llm(
    prompt: str, 
    chat_history: Optional[List[Dict[str, str]]] = None
) -> Tuple[str, LLMTrace]:
    """
    Terrarium에서 LLM 한 번 호출할 때 쓰는 공용 함수.
    - prompt: 우리가 구성한 프롬프트 (질문 + 컨텍스트)
    - chat_history: 이전 대화 히스토리 (선택사항, 멀티턴 대화용)
    - return: (LLM이 생성한 텍스트, LLMTrace)
    """
    url = f"{OLLAMA_HOST}/api/chat"

    # 대화 히스토리 구성
    messages = []
    if chat_history:
        # 이전 대화를 messages에 추가
        messages.extend(chat_history)
    
    # 현재 프롬프트를 user 메시지로 추가
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": False,  # 일단 스트리밍은 끔
    }

    start = time.perf_counter()

    # LLM 응답이 오래 걸릴 수 있으므로 타임아웃을 길게 설정 (5분)
    timeout = httpx.Timeout(300.0, connect=10.0)
    
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        try:
            data = resp.json()
        except ValueError as exc:
            raise RuntimeError("Ollama 응답이 JSON 형식이 아닙니다.") from exc

    elapsed_ms = int((time.perf_counter() - start) * 1000)

    # Ollama 응답 포맷에서 message.content 꺼내기
    message = data.get("message", {})
    if isinstance(message, dict):
        output_text = str(message.get("content", ""))
    else:
        # 비정상 응답 포맷도 안전하게 처리해 파이프라인이 깨지지 않도록 한다.
        output_text = str(data.get("response", ""))

    trace = LLMTrace(
        model=OLLAMA_MODEL,
        prompt=prompt,
        output=output_text,
        latency_ms=elapsed_ms,
        input_tokens=None,   # Ollama가 토큰 정보를 안 주니까 일단 None
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