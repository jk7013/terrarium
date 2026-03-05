import logging
import asyncio
import uuid
import time
import os
import json
from datetime import datetime, timezone
"""
2.	RAG 파이프라인 (app/rag/pipeline.py)
	•	run_rag(request: QueryRequest) -> QueryResponse
	•	내부에서:
	•	쿼리 전처리/확장
	•	retriever 호출 (app/rag/retriever.py)
	•	reranker 호출 (bge-reranker 같은 거)
	•	context 선택
	•	LLM 호출(app/llm/client.py)
	•	trace 채우기
	•	최종적으로 QueryResponse 직접 만들어서 반환
"""

from app.api.schemas.query import (
    QueryRequest,
    QueryResponse,
    ContextItem,
    RetrievalTrace,
    LLMTrace,
    QueryMeta,
)
from app.llm.client import call_llm, OLLAMA_HOST, OLLAMA_MODEL
from app.tools.weather import get_weather, is_weather_query
from app.tools.time import get_current_time, is_time_query
from app.rag.retriever import retrieve_top_k
from app.store.pgvector_store import PgVectorStore
import httpx

logger = logging.getLogger(__name__)
DEBUG_LOG_PATH = "/Users/parkjinkyung/Documents/terrarium/.cursor/debug.log"

RAG_TOP_K = int(os.getenv("RAG_TOP_K", "6"))
RAG_MAX_CONTEXT_CHARS = int(os.getenv("RAG_MAX_CONTEXT_CHARS", "6000"))


def _build_retrieval_trace(
    query: str,
    *,
    vector_results: list[dict] | None = None,
) -> RetrievalTrace:
    return RetrievalTrace(
        query_expansions=_expand_query(query),
        bm25_results=[],
        vector_results=vector_results or [],
        reranked_results=[],
    )


def _limit_contexts_by_chars(
    contexts: list[ContextItem],
    *,
    max_chars: int,
) -> list[ContextItem]:
    total = 0
    selected: list[ContextItem] = []
    for ctx in contexts:
        text_len = len(ctx.text)
        if selected and total + text_len > max_chars:
            break
        selected.append(ctx)
        total += text_len
    return selected


def _build_llm_error_trace(message: str, latency_ms: float) -> LLMTrace:
    return LLMTrace(
        model=OLLAMA_MODEL,
        prompt="",
        output=message,
        latency_ms=latency_ms,
        input_tokens=None,
        output_tokens=None,
    )


def _debug_log(hypothesis_id: str, location: str, message: str, data: dict) -> None:
    payload = {
        "id": f"log_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}",
        "timestamp": int(time.time() * 1000),
        "runId": "regulation-routing-fix",
        "hypothesisId": hypothesis_id,
        "location": location,
        "message": message,
        "data": data,
    }
    # region agent log
    try:
        with open(DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass
    # endregion


def _is_weather_tool_context(contexts: list[ContextItem]) -> bool:
    if not contexts:
        return False
    if len(contexts) != 1:
        return False
    ctx = contexts[0]
    source = str(ctx.meta.get("source", "")) if ctx.meta else ""
    return ctx.document_id == "weather_tool" or source == "accuweather"


async def _safe_call_llm(
    request: QueryRequest,
    contexts: list[ContextItem],
    trace_id: str,
    *,
    error_prefix: str,
    fallback_answer: str | None = None,
) -> tuple[LLMTrace, str, str]:
    try:
        llm_trace, answer = await _call_llm_with_context(request, contexts)
        return llm_trace, answer, "success"
    except httpx.TimeoutException as e:
        logger.error(
            "LLM call timeout",
            extra={"trace_id": trace_id, "error": str(e), "timeout_seconds": 300, "context": error_prefix},
            exc_info=True,
        )
        llm_trace = _build_llm_error_trace(
            f"LLM 응답 시간 초과. {error_prefix}",
            300000,
        )
    except httpx.ConnectError as e:
        logger.error(
            "LLM server connection failed",
            extra={"trace_id": trace_id, "error": str(e), "host": OLLAMA_HOST, "context": error_prefix},
            exc_info=True,
        )
        llm_trace = _build_llm_error_trace(
            f"Ollama 서버에 연결할 수 없습니다. 서버가 실행 중인지 확인해주세요. (호스트: {OLLAMA_HOST})",
            0.0,
        )
    except Exception as e:
        logger.error(
            "LLM call failed",
            extra={"trace_id": trace_id, "error": str(e), "error_type": type(e).__name__, "context": error_prefix},
            exc_info=True,
        )
        llm_trace = _build_llm_error_trace(f"LLM 호출 실패: {str(e)}", 0.0)

    answer = fallback_answer if fallback_answer is not None else llm_trace.output
    return llm_trace, answer, "error"

def _expand_query(query: str) -> list[str]:
    """
    v0 쿼리 확장 (LLM 없이 규칙 기반).

    - 원 쿼리를 항상 포함한다.
    - 반말/정중 표현 등 자주 쓰는 꼬리 표현을 단순 제거한 버전을 추가한다.
    - "어떻게" 같은 표현을 "절차", "방법" 등으로 치환한 버전을 추가한다.
    - 나중에 형태소 분석기/동의어 사전 기반 로직으로 교체할 수 있다.
    """
    base = (query or "").strip()
    expansions: list[str] = []
    if not base:
        return expansions

    # 1) 원 쿼리 그대로
    expansions.append(base)

    # 2) 자주 쓰는 꼬리 표현 제거 버전
    polite_suffixes = [
        " 알려줘",
        " 알려 줘",
        " 알려 주세요",
        " 알려줘요",
        " 알려주세요",
        " 해줘",
        " 해 줘",
        " 해 주세요",
        " 해줘요",
        " 해주세요",
    ]
    for suffix in polite_suffixes:
        if base.endswith(suffix):
            core = base[: -len(suffix)].strip()
            if core and core not in expansions:
                expansions.append(core)

    # 3) "어떻게" → "절차"/"방법" 치환 버전
    if "어떻게" in base:
        replaced_procedure = base.replace("어떻게", "절차")
        replaced_method = base.replace("어떻게", "방법")
        for cand in (replaced_procedure, replaced_method):
            cand = cand.strip()
            if cand and cand not in expansions:
                expansions.append(cand)

    # 4) 도메인 동의어 기반 치환 버전 (사규/인사 도메인 예시)
    synonym_groups = [
        # 퇴직 관련
        ["퇴직금", "퇴직급여"],
        # 출장/여비
        ["출장비", "여비"],
        # 휴가/연차
        ["연차", "연가", "휴가"],
        # 성과급
        ["성과급", "경영평가 성과급"],
    ]
    for group in synonym_groups:
        for term in group:
            if term in base:
                for alt in group:
                    if alt == term:
                        continue
                    cand = base.replace(term, alt).strip()
                    if cand and cand not in expansions:
                        expansions.append(cand)

    # 5) 중복 제거
    seen: set[str] = set()
    unique: list[str] = []
    for q in expansions:
        if q not in seen:
            seen.add(q)
            unique.append(q)

    return unique

def _build_ephemeral_contexts(request: QueryRequest) -> list[ContextItem]:
    """
    ephemeral 모드에서 컨텍스트 목록을 만들어준다.

    v0:
    - raw_text 전체를 하나의 청크로 본다.
    - 나중에 여기서 청킹 로직을 교체/확장한다.
    """
    text = request.raw_text or ""
    if not text:
        return []

    context = ContextItem(
        chunk_id="c_1",
        document_id="d_ephemeral",
        text=text,
        score=1.0,
        meta={},
    )
    return [context]

async def _call_llm_with_tool_context(
    request: QueryRequest,
    tool_info: str,
    tool_name: str,
    tool_meta: dict,
    trace_id: str,
) -> tuple[LLMTrace, str, str, list[ContextItem]]:
    """
    툴 정보를 LLM 컨텍스트로 전달하여 답변 생성.
    모든 툴이 일관되게 LLM에 컨텍스트로 전달되도록 보장하는 공통 함수.
    
    Args:
        request: 쿼리 요청
        tool_info: 툴에서 가져온 정보 문자열
        tool_name: 툴 이름 (예: "weather", "time")
        tool_meta: 툴 메타데이터
        trace_id: 트레이스 ID
        
    Returns:
        tuple[LLMTrace, str, str, list[ContextItem]]: (LLM 트레이스, 답변, 상태, 컨텍스트)
    """
    # 툴 정보를 컨텍스트로 변환
    tool_context = ContextItem(
        chunk_id=f"{tool_name}_1",
        document_id=f"{tool_name}_tool",
        text=tool_info,
        score=1.0,
        meta=tool_meta,
    )
    contexts = [tool_context]
    
    llm_trace, answer, status = await _safe_call_llm(
        request,
        contexts,
        trace_id,
        error_prefix=f"{tool_name} 정보는 가져왔지만 답변 생성에 실패했습니다.",
        fallback_answer=tool_info,
    )

    return llm_trace, answer, status, contexts


async def _call_llm_with_context(
    request: QueryRequest, contexts: list[ContextItem]
) -> tuple[LLMTrace, str]:
    """
    실제 LLM 호출 (Ollama).

    - 컨텍스트와 질문을 조합해서 프롬프트를 만들고
    - app.llm.client의 call_llm을 호출한다.
    - 대화 히스토리가 있으면 멀티턴 대화로 처리한다.
    """
    # 컨텍스트 텍스트 조합
    context_text = ""
    if contexts:
        context_parts = [ctx.text for ctx in contexts]
        context_text = "\n\n".join(context_parts)
    
    # 프롬프트 구성
    if context_text:
        is_weather_context = _is_weather_tool_context(contexts)
        _debug_log(
            "H1",
            "app/rag/pipeline.py:_call_llm_with_context",
            "Prompt routing decision",
            {
                "query": request.query,
                "is_weather_context": is_weather_context,
                "context_count": len(contexts),
                "first_document_id": contexts[0].document_id if contexts else None,
                "first_source": contexts[0].meta.get("source") if contexts and contexts[0].meta else None,
            },
        )
        if is_weather_context:
            prompt = f"""다음 날씨 정보를 바탕으로 사용자의 질문에 자연스럽고 친절하게 답변해주세요.

날씨 정보:
{context_text}

사용자 질문: {request.query}

답변:"""
        else:
            prompt = f"""다음 컨텍스트를 바탕으로 질문에 답변해주세요.

컨텍스트:
{context_text}

질문: {request.query}

답변:"""
    else:
        prompt = f"질문: {request.query}\n\n답변:"
    
    # 대화 히스토리 준비 (멀티턴 대화용)
    chat_history = None
    if request.chat_history:
        # ChatMessage 객체를 dict로 변환
        chat_history = [
            {"role": msg.role, "content": msg.content}
            for msg in request.chat_history
        ]
    
    # 실제 LLM 호출 (대화 히스토리 포함)
    output_text, llm_trace = await call_llm(prompt, chat_history)
    
    return llm_trace, output_text

async def run_rag(request: QueryRequest) -> QueryResponse:
    """
    Terrarium RAG 파이프라인의 엔트리포인트.

    v0:
    - 쿼리 확장, 컨텍스트 구성, 실제 LLM 호출을 수행한다.
    - 나중에 검색/리랭킹 단계를 추가한다.
    """

    trace_id = str(uuid.uuid4())
    logger.info(
        "run_rag started",
        extra={
            "trace_id": trace_id,
            "mode": request.mode,
            "profile": request.profile,
        },
    )

    # 0) 툴 체크 (MCP 스타일) - 모든 툴이 LLM 컨텍스트로 전달됨
    if is_weather_query(request.query):
        logger.info(
            "Weather tool triggered",
            extra={"trace_id": trace_id, "query": request.query},
        )
        # 날씨 툴 호출하여 날씨 정보 가져오기
        weather_info = await asyncio.to_thread(get_weather)
        
        # 공통 함수를 통해 툴 정보를 LLM 컨텍스트로 전달
        llm_trace, answer, status, contexts = await _call_llm_with_tool_context(
            request=request,
            tool_info=weather_info,
            tool_name="weather",
            tool_meta={"source": "accuweather", "location": "seoul"},
            trace_id=trace_id,
        )
        
        # 검색 트레이스 구성
        retrieval_trace = _build_retrieval_trace(request.query)
        used_tool = "weather"  # 사용된 툴 이름
    elif is_time_query(request.query):
        logger.info(
            "Time tool triggered",
            extra={"trace_id": trace_id, "query": request.query},
        )
        # 시간 툴 호출하여 시간 정보 가져오기
        time_info = await asyncio.to_thread(get_current_time)
        
        # 공통 함수를 통해 툴 정보를 LLM 컨텍스트로 전달
        llm_trace, answer, status, contexts = await _call_llm_with_tool_context(
            request=request,
            tool_info=time_info,
            tool_name="time",
            tool_meta={"source": "system", "timezone": "Asia/Seoul"},
            trace_id=trace_id,
        )
        
        # 검색 트레이스 구성
        retrieval_trace = _build_retrieval_trace(request.query)
        used_tool = "time"  # 사용된 툴 이름
    else:
        # 일반 RAG 파이프라인 실행 (v1: pgvector 우선, 실패 시 ephemeral fallback)
        retrieval_started = time.perf_counter()
        top_k = request.options.top_k if request.options.top_k > 0 else RAG_TOP_K
        expansions = _expand_query(request.query)
        merged_contexts: list[ContextItem] = []
        merged_vector_results: list[dict] = []
        seen_chunk_ids: set[str] = set()

        for expanded in expansions:
            try:
                contexts_candidate, vector_results = await retrieve_top_k(
                    expanded, top_k
                )
            except Exception as e:
                logger.warning(
                    "pgvector retrieval failed for expansion",
                    extra={"trace_id": trace_id, "expanded_query": expanded, "error": str(e)},
                )
                continue

            for ctx, vr in zip(contexts_candidate, vector_results):
                if ctx.chunk_id in seen_chunk_ids:
                    continue
                seen_chunk_ids.add(ctx.chunk_id)
                merged_contexts.append(ctx)
                merged_vector_results.append(vr)
                if len(merged_contexts) >= top_k:
                    break
            if len(merged_contexts) >= top_k:
                break

        if merged_contexts:
            contexts = merged_contexts[: request.options.final_contexts]
            contexts = _limit_contexts_by_chars(contexts, max_chars=RAG_MAX_CONTEXT_CHARS)
            retrieval_trace = RetrievalTrace(
                query_expansions=expansions,
                bm25_results=[],
                vector_results=merged_vector_results[: top_k],
                reranked_results=[],
            )
        else:
            contexts = _build_ephemeral_contexts(request)
            retrieval_trace = RetrievalTrace(
                query_expansions=expansions,
                bm25_results=[],
                vector_results=[],
                reranked_results=[],
            )

        retrieval_latency_ms = int((time.perf_counter() - retrieval_started) * 1000)

        # 실제 LLM 호출 (Ollama)
        llm_trace, answer, status = await _safe_call_llm(
            request,
            contexts,
            trace_id,
            error_prefix="일반 질의 처리 중 오류가 발생했습니다.",
        )

        if retrieval_trace.vector_results:
            try:
                store = PgVectorStore()
                await asyncio.to_thread(
                    store.log_retrieval,
                    query=request.query,
                    expanded_query=" | ".join(expansions),
                    used_tool=None,
                    top_k=top_k,
                    results=retrieval_trace.vector_results,
                    latency_ms=retrieval_latency_ms,
                )
            except Exception as e:
                logger.warning(
                    "failed to persist retrieval_logs",
                    extra={"trace_id": trace_id, "error": str(e)},
                )
        used_tool = None  # 일반 RAG 파이프라인에서는 툴 미사용

    # 4) 메타데이터 구성
    meta = QueryMeta(
        mode=request.mode,
        profile=request.profile,
        timestamp=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        status=status,
        tool=used_tool,
        retrieval={
            "top_k": top_k if 'top_k' in locals() else request.options.top_k,
            "returned": len(retrieval_trace.vector_results),
            "source": "pgvector" if retrieval_trace.vector_results else "ephemeral",
            "sources_count": len({r.get("filepath") for r in retrieval_trace.vector_results if r.get("filepath")}),
            "model": os.getenv("OLLAMA_EMBED_MODEL", "bge-m3"),
            "latency": {
                "retrieval_ms": retrieval_latency_ms if 'retrieval_latency_ms' in locals() else None,
                "llm_ms": int(llm_trace.latency_ms) if llm_trace and llm_trace.latency_ms is not None else None,
            },
        },
    )

    # 5) 최종 응답 조립
    response = QueryResponse(
        trace_id=trace_id,
        answer=answer,
        contexts=contexts,
        retrieval_trace=retrieval_trace,
        llm_trace=llm_trace,
        meta=meta,
    )

    logger.info(
        "run_rag finished",
        extra={
            "trace_id": trace_id,
            "mode": request.mode,
            "profile": request.profile,
            "status": status,
        },
    )

    return response