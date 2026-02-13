# app/llm/client.py

import os
import time
from typing import Tuple, Optional, List, Dict

import httpx

from app.api.schemas.query import LLMTrace


# 나중에 .env로 바꾸기 쉽게 환경변수로 빼두자
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:4b")


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
        data = resp.json()

    elapsed_ms = int((time.perf_counter() - start) * 1000)

    # Ollama 응답 포맷에서 message.content 꺼내기
    message = data.get("message", {})
    output_text: str = message.get("content", "")

    trace = LLMTrace(
        model=OLLAMA_MODEL,
        prompt=prompt,
        output=output_text,
        latency_ms=elapsed_ms,
        input_tokens=None,   # Ollama가 토큰 정보를 안 주니까 일단 None
        output_tokens=None,
    )

    return output_text, trace