"""
Prompt Pack Schema - PromptPack, RenderedPrompt 스키마 정의
"""
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
from dataclasses import dataclass


class PromptPack(BaseModel):
    """프롬프트 팩 정의"""
    id: str = Field(description="팩 ID (예: default, weather_assistant)")
    name: str = Field(description="표시용 이름")
    version: str = Field(default="v0.1.0", description="버전")
    system_template: str = Field(description="시스템 프롬프트 템플릿")
    developer_template: Optional[str] = Field(default=None, description="내부 규칙 템플릿")
    user_prefix_template: Optional[str] = Field(default=None, description="사용자 질문 prefix 템플릿")
    variables_schema: Dict[str, Any] = Field(default_factory=dict, description="변수 스키마 (JSON Schema)")
    defaults: Dict[str, Any] = Field(default_factory=dict, description="변수 기본값")
    tool_policy: Dict[str, Any] = Field(default_factory=dict, description="툴 정책")
    output_format: Dict[str, Any] = Field(default_factory=dict, description="출력 형식")


@dataclass
class RenderedPrompt:
    """렌더링된 프롬프트 (디버그용 출력)"""
    messages: List[Dict[str, str]]  # Ollama /api/chat에 넣는 최종 messages 배열
    variables_used: Dict[str, Any]  # 최종 적용된 변수들
    evidence_summary: str  # 컨텍스트 요약(툴/리트리벌)
    prompt_hash: str  # 동일성 비교용 해시


class PromptRenderRequest(BaseModel):
    """프롬프트 렌더링 요청"""
    pack_id: str = Field(default="default", description="팩 ID")
    variables: Dict[str, Any] = Field(default_factory=dict, description="변수 값")
    query: str = Field(description="사용자 질문")
    chat_history: List[Dict[str, str]] = Field(default_factory=list, description="대화 히스토리")
    contexts: List[Dict[str, Any]] = Field(default_factory=list, description="컨텍스트 (툴 결과 등)")


class PromptRenderResponse(BaseModel):
    """프롬프트 렌더링 응답"""
    pack_id: str
    prompt_hash: str
    variables_used: Dict[str, Any]
    messages: List[Dict[str, str]]
    evidence_summary: str



