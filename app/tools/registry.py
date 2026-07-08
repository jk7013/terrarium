"""
Tool Registry - 툴 스펙, 호출, 결과, 레지스트리 정의
"""
from typing import Optional, Dict, Any, Callable
from dataclasses import dataclass
from enum import Enum


class ToolAdapterType(str, Enum):
    """툴 어댑터 타입"""
    LOCAL = "local"  # 파이썬 함수 직접 호출
    MCP = "mcp"      # MCP 서버 호출
    HTTP = "http"    # HTTP API 호출


@dataclass
class ToolSpec:
    """툴 스펙 정의"""
    id: str
    name: str
    description: str
    adapter_type: ToolAdapterType
    adapter_config: Dict[str, Any]  # 어댑터별 설정
    match_function: Optional[Callable[[str], bool]] = None  # query -> bool (선택사항)
    priority: int = 0  # 우선순위 (높을수록 먼저 매칭)


@dataclass
class ToolCall:
    """툴 호출 요청"""
    tool_id: str
    arguments: Dict[str, Any] = None


@dataclass
class ToolResult:
    """툴 실행 결과"""
    tool_id: str
    success: bool
    output: str
    error: Optional[str] = None
    metadata: Dict[str, Any] = None  # 실행 시간, 소스 등


class ToolRegistry:
    """툴 레지스트리"""
    
    def __init__(self):
        self._tools: Dict[str, ToolSpec] = {}
        self._tools_by_priority: list[ToolSpec] = []
    
    def register(self, spec: ToolSpec):
        """툴 등록"""
        if spec.id in self._tools:
            raise ValueError(f"Tool {spec.id} already registered")
        self._tools[spec.id] = spec
        self._tools_by_priority.append(spec)
        # 우선순위 순으로 정렬 (높은 우선순위가 먼저)
        self._tools_by_priority.sort(key=lambda x: x.priority, reverse=True)
    
    def get(self, tool_id: str) -> Optional[ToolSpec]:
        """툴 조회"""
        return self._tools.get(tool_id)
    
    def list_all(self) -> list[ToolSpec]:
        """모든 툴 목록 반환 (우선순위 순)"""
        return self._tools_by_priority.copy()
    
    def find_by_query(self, query: str) -> Optional[ToolSpec]:
        """쿼리로 툴 찾기 (우선순위 순으로 매칭)"""
        for spec in self._tools_by_priority:
            if spec.match_function and spec.match_function(query):
                return spec
        return None

