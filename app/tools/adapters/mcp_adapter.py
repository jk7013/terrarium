"""
MCP Adapter - MCP 서버 호출
"""
import logging
from typing import Dict, Any
from app.tools.registry import ToolSpec

logger = logging.getLogger(__name__)


class MCPAdapter:
    """MCP 서버 호출 어댑터 (향후 구현)"""
    
    async def execute(
        self,
        spec: ToolSpec,
        arguments: Dict[str, Any],
        timeout: float = 30.0
    ) -> str:
        """
        MCP 서버 호출 (향후 구현)
        
        Args:
            spec: 툴 스펙
            arguments: MCP 호출 인자
            timeout: 타임아웃 (초)
            
        Returns:
            str: MCP 서버 응답
        """
        # TODO: MCP 프로토콜 구현
        logger.warning(
            f"MCP adapter not yet implemented for {spec.id}",
            extra={"tool_id": spec.id}
        )
        raise NotImplementedError("MCP adapter is not yet implemented")

