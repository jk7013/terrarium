import logging
import uuid
from datetime import datetime
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
import httpx

logger = logging.getLogger(__name__)

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
    
    # 쿼리 확장
    expansions = _expand_query(request.query)
    retrieval_trace = RetrievalTrace(
        query_expansions=expansions,
        bm25_results=[],
        vector_results=[],
        reranked_results=[],
    )
    
    # LLM 호출 (툴 정보를 컨텍스트로 전달)
    try:
        llm_trace, answer = await _call_llm_with_context(request, contexts)
        status = "success"
    except httpx.TimeoutException as e:
        logger.error(
            f"LLM call timeout ({tool_name})",
            extra={"trace_id": trace_id, "error": str(e)},
            exc_info=True,
        )
        llm_trace = LLMTrace(
            model=OLLAMA_MODEL,
            prompt="",
            output=f"LLM 응답 시간 초과. {tool_name} 정보는 가져왔지만 답변 생성에 실패했습니다.",
            latency_ms=300000,
            input_tokens=None,
            output_tokens=None,
        )
        answer = tool_info  # LLM 실패 시 툴 정보 직접 반환
        status = "error"
    except httpx.ConnectError as e:
        logger.error(
            f"LLM server connection failed ({tool_name})",
            extra={"trace_id": trace_id, "error": str(e)},
            exc_info=True,
        )
        llm_trace = LLMTrace(
            model=OLLAMA_MODEL,
            prompt="",
            output=f"Ollama 서버 연결 실패. {tool_name} 정보: {tool_info}",
            latency_ms=0.0,
            input_tokens=None,
            output_tokens=None,
        )
        answer = tool_info  # LLM 실패 시 툴 정보 직접 반환
        status = "error"
    except Exception as e:
        logger.error(
            f"LLM call failed ({tool_name})",
            extra={"trace_id": trace_id, "error": str(e)},
            exc_info=True,
        )
        llm_trace = LLMTrace(
            model=OLLAMA_MODEL,
            prompt="",
            output=f"LLM 호출 실패. {tool_name} 정보: {tool_info}",
            latency_ms=0.0,
            input_tokens=None,
            output_tokens=None,
        )
        answer = tool_info  # LLM 실패 시 툴 정보 직접 반환
        status = "error"
    
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
        # 날씨 정보인지 확인 (컨텍스트에 날씨 관련 키워드가 있는지)
        is_weather_context = any(keyword in context_text.lower() for keyword in 
                                 ["날씨", "기온", "온도", "흐림", "맑음", "비", "눈", "weather", "temperature", "cloudy", "sunny"])
        
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
        weather_info = get_weather()
        
        # 공통 함수를 통해 툴 정보를 LLM 컨텍스트로 전달
        llm_trace, answer, status, contexts = await _call_llm_with_tool_context(
            request=request,
            tool_info=weather_info,
            tool_name="weather",
            tool_meta={"source": "accuweather", "location": "seoul"},
            trace_id=trace_id,
        )
        
        # 검색 트레이스 구성
        expansions = _expand_query(request.query)
        retrieval_trace = RetrievalTrace(
            query_expansions=expansions,
            bm25_results=[],
            vector_results=[],
            reranked_results=[],
        )
        used_tool = "weather"  # 사용된 툴 이름
    elif is_time_query(request.query):
        logger.info(
            "Time tool triggered",
            extra={"trace_id": trace_id, "query": request.query},
        )
        # 시간 툴 호출하여 시간 정보 가져오기
        time_info = get_current_time()
        
        # 공통 함수를 통해 툴 정보를 LLM 컨텍스트로 전달
        llm_trace, answer, status, contexts = await _call_llm_with_tool_context(
            request=request,
            tool_info=time_info,
            tool_name="time",
            tool_meta={"source": "system", "timezone": "Asia/Seoul"},
            trace_id=trace_id,
        )
        
        # 검색 트레이스 구성
        expansions = _expand_query(request.query)
        retrieval_trace = RetrievalTrace(
            query_expansions=expansions,
            bm25_results=[],
            vector_results=[],
            reranked_results=[],
        )
        used_tool = "time"  # 사용된 툴 이름
    else:
        # 일반 RAG 파이프라인 실행
        # 0) 쿼리 확장 (v0: 규칙 기반)
        expansions = _expand_query(request.query)

        # 1) 컨텍스트 구성 (v0: raw_text 전체를 하나의 청크로 사용)
        contexts = _build_ephemeral_contexts(request)

        # 2) 검색 트레이스 (v0: 아직 검색/리랭킹 미구현이므로 빈 값)
        retrieval_trace = RetrievalTrace(
            query_expansions=expansions,
            bm25_results=[],
            vector_results=[],
            reranked_results=[],
        )

        # 3) 실제 LLM 호출 (Ollama)
        try:
            llm_trace, answer = await _call_llm_with_context(request, contexts)
            status = "success"
        except httpx.TimeoutException as e:
            logger.error(
                "LLM call timeout",
                extra={"trace_id": trace_id, "error": str(e), "timeout_seconds": 300},
                exc_info=True,
            )
            # 타임아웃 에러 발생 시 명확한 메시지
            llm_trace = LLMTrace(
                model=OLLAMA_MODEL,
                prompt="",
                output="LLM 응답 시간 초과 (5분). Ollama 서버가 응답을 생성하는데 시간이 너무 오래 걸립니다. 더 작은 모델을 사용하거나 서버 성능을 확인해주세요.",
                latency_ms=300000,
                input_tokens=None,
                output_tokens=None,
            )
            answer = llm_trace.output
            status = "error"
        except httpx.ConnectError as e:
            logger.error(
                "LLM server connection failed",
                extra={"trace_id": trace_id, "error": str(e), "host": OLLAMA_HOST},
                exc_info=True,
            )
            # 연결 에러 발생 시
            llm_trace = LLMTrace(
                model=OLLAMA_MODEL,
                prompt="",
                output=f"Ollama 서버에 연결할 수 없습니다. 서버가 실행 중인지 확인해주세요. (호스트: {OLLAMA_HOST})",
                latency_ms=0.0,
                input_tokens=None,
                output_tokens=None,
            )
            answer = llm_trace.output
            status = "error"
        except Exception as e:
            logger.error(
                "LLM call failed",
                extra={"trace_id": trace_id, "error": str(e), "error_type": type(e).__name__},
                exc_info=True,
            )
            # 기타 에러 발생 시
            llm_trace = LLMTrace(
                model=OLLAMA_MODEL,
                prompt="",
                output=f"LLM 호출 실패: {str(e)}",
                latency_ms=0.0,
                input_tokens=None,
                output_tokens=None,
            )
            answer = llm_trace.output
            status = "error"
        used_tool = None  # 일반 RAG 파이프라인에서는 툴 미사용

    # 4) 메타데이터 구성
    meta = QueryMeta(
        mode=request.mode,
        profile=request.profile,
        timestamp=datetime.utcnow().isoformat() + "Z",
        status=status,
        tool=used_tool,
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