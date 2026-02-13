"""
Tool Router - query -> ToolCall 라우팅
"""
from typing import Optional
from app.tools.registry import ToolRegistry, ToolCall, ToolSpec


class ToolRouter:
    """툴 라우터: 쿼리를 분석하여 적절한 툴 호출 결정"""
    
    def __init__(self, registry: ToolRegistry):
        self.registry = registry
    
    def route(self, query: str) -> Optional[ToolCall]:
        """
        쿼리를 분석하여 ToolCall 반환
        
        Args:
            query: 사용자 질문
            
        Returns:
            ToolCall 또는 None (툴이 필요 없으면)
        """
        # 우선순위 순으로 툴 매칭
        tool_spec = self.registry.find_by_query(query)
        
        if tool_spec:
            return ToolCall(
                tool_id=tool_spec.id,
                arguments={}  # 기본적으로 빈 arguments, 필요시 확장
            )
        
        return None

