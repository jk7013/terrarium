"""
Tool Executor - 툴 실행, 타임아웃, 에러 표준화
"""
import logging
from typing import Optional
from app.tools.registry import ToolRegistry, ToolCall, ToolResult, ToolSpec
from app.tools.adapters.local_adapter import LocalAdapter
from app.tools.adapters.mcp_adapter import MCPAdapter
from app.tools.adapters.http_adapter import HTTPAdapter

logger = logging.getLogger(__name__)


class ToolExecutor:
    """툴 실행기: 타임아웃, 재시도, 에러 처리 표준화"""
    
    def __init__(self, registry: ToolRegistry):
        self.registry = registry
        self._adapters = {
            "local": LocalAdapter(),
            "mcp": MCPAdapter(),
            "http": HTTPAdapter(),
        }
    
    async def execute(self, call: ToolCall, timeout: float = 30.0) -> ToolResult:
        """
        툴 실행
        
        Args:
            call: ToolCall 객체
            timeout: 타임아웃 (초)
            
        Returns:
            ToolResult
        """
        tool_spec = self.registry.get(call.tool_id)
        if not tool_spec:
            return ToolResult(
                tool_id=call.tool_id,
                success=False,
                output="",
                error=f"Tool {call.tool_id} not found in registry"
            )
        
        adapter = self._adapters.get(tool_spec.adapter_type.value)
        if not adapter:
            return ToolResult(
                tool_id=call.tool_id,
                success=False,
                output="",
                error=f"Adapter {tool_spec.adapter_type.value} not found"
            )
        
        try:
            logger.info(
                f"Executing tool {call.tool_id} with adapter {tool_spec.adapter_type.value}",
                extra={"tool_id": call.tool_id, "adapter": tool_spec.adapter_type.value}
            )
            
            output = await adapter.execute(tool_spec, call.arguments or {}, timeout)
            
            return ToolResult(
                tool_id=call.tool_id,
                success=True,
                output=output,
                metadata={"adapter": tool_spec.adapter_type.value}
            )
        except TimeoutError as e:
            logger.error(
                f"Tool {call.tool_id} execution timeout",
                extra={"tool_id": call.tool_id, "timeout": timeout},
                exc_info=True
            )
            return ToolResult(
                tool_id=call.tool_id,
                success=False,
                output="",
                error=f"Execution timeout after {timeout}s",
                metadata={"adapter": tool_spec.adapter_type.value}
            )
        except Exception as e:
            logger.error(
                f"Tool {call.tool_id} execution failed",
                extra={"tool_id": call.tool_id, "error": str(e)},
                exc_info=True
            )
            return ToolResult(
                tool_id=call.tool_id,
                success=False,
                output="",
                error=str(e),
                metadata={"adapter": tool_spec.adapter_type.value}
            )

