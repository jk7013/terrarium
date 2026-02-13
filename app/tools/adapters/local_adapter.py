"""
Local Adapter - 파이썬 함수 직접 호출
"""
import asyncio
import logging
from typing import Dict, Any, Callable
from app.tools.registry import ToolSpec

logger = logging.getLogger(__name__)


class LocalAdapter:
    """로컬 파이썬 함수 호출 어댑터"""
    
    async def execute(
        self,
        spec: ToolSpec,
        arguments: Dict[str, Any],
        timeout: float = 30.0
    ) -> str:
        """
        로컬 함수 실행
        
        Args:
            spec: 툴 스펙
            arguments: 함수 인자 (현재는 사용하지 않음)
            timeout: 타임아웃 (초)
            
        Returns:
            str: 함수 실행 결과
        """
        function = spec.adapter_config.get("function")
        if not function:
            raise ValueError(f"Function not found in adapter_config for {spec.id}")
        
        if not callable(function):
            raise ValueError(f"Function is not callable for {spec.id}")
        
        # 동기 함수를 비동기로 실행
        try:
            if asyncio.iscoroutinefunction(function):
                result = await asyncio.wait_for(function(**arguments), timeout=timeout)
            else:
                # 동기 함수를 별도 스레드에서 실행
                loop = asyncio.get_event_loop()
                result = await asyncio.wait_for(
                    loop.run_in_executor(None, lambda: function(**arguments)),
                    timeout=timeout
                )
            
            return str(result) if result is not None else ""
        except asyncio.TimeoutError:
            raise TimeoutError(f"Tool {spec.id} execution timeout after {timeout}s")
        except Exception as e:
            logger.error(
                f"Local adapter execution failed for {spec.id}",
                extra={"tool_id": spec.id, "error": str(e)},
                exc_info=True
            )
            raise

