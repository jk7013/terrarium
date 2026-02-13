from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field
from typing_extensions import Literal


class QueryOptions(BaseModel):
    """/query 옵션값 (top_k, final_contexts 등)."""

    top_k: int = Field(
        default=10,
        description="리트리버 단계에서 가져올 최대 후보 수",
    )
    final_contexts: int = Field(
        default=3,
        description="LLM에 최종으로 넣을 컨텍스트 개수",
    )


class ChatMessage(BaseModel):
    """대화 메시지 (멀티턴 대화용)."""
    
    role: Literal["user", "assistant"] = Field(
        description="메시지 역할 (user 또는 assistant)"
    )
    content: str = Field(
        description="메시지 내용"
    )


class QueryRequest(BaseModel):
    """/query 요청 본문 구조.

    v0에서는 mode=ephemeral + raw_text 기반 1회성 RAG만 사용한다.
    """

    mode: Literal["ephemeral", "corpus"] = Field(
        default="ephemeral",
        description="RAG 모드 (v0는 ephemeral만 지원)",
    )
    query: str = Field(
        description="사용자 질문 텍스트",
    )
    raw_text: Optional[str] = Field(
        default=None,
        description="ephemeral 모드에서 사용할 원문 텍스트 (파일 파싱 전 단계)",
    )
    profile: str = Field(
        default="default",
        description="RAG 프로파일 이름 (임베딩/리랭커 조합 등을 구분)",
    )
    options: QueryOptions = Field(
        default_factory=QueryOptions,
        description="검색/컨텍스트 선택 옵션",
    )
    chat_history: Optional[List[ChatMessage]] = Field(
        default=None,
        description="이전 대화 히스토리 (멀티턴 대화용)",
    )


class ContextItem(BaseModel):
    """LLM에 전달되거나 후보로 선택된 단일 컨텍스트(청크)."""

    chunk_id: str
    document_id: str
    text: str
    score: float
    meta: Dict[str, Any] = Field(default_factory=dict)


class RetrievalTrace(BaseModel):
    """RAG 검색/리랭킹 과정 요약 정보."""

    query_expansions: List[str] = Field(default_factory=list)
    bm25_results: List[Dict[str, Any]] = Field(default_factory=list)
    vector_results: List[Dict[str, Any]] = Field(default_factory=list)
    reranked_results: List[Dict[str, Any]] = Field(default_factory=list)


class LLMTrace(BaseModel):
    """LLM 호출 관련 정보."""

    model: str
    prompt: str
    output: str
    latency_ms: float
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None


class QueryMeta(BaseModel):
    """공통 메타데이터."""

    mode: str
    profile: str
    timestamp: str
    status: Literal["success", "error"] = "success"
    tool: Optional[str] = Field(
        default=None,
        description="사용된 툴 이름 (예: weather, time)",
    )


class QueryResponse(BaseModel):
    """/query 응답 본문 구조."""

    trace_id: str
    answer: str
    contexts: List[ContextItem]
    retrieval_trace: RetrievalTrace
    llm_trace: LLMTrace
    meta: QueryMeta
