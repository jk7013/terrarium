"""
HTTP Adapter - HTTP API 호출
"""
import logging
import httpx
from typing import Dict, Any
from app.tools.registry import ToolSpec

logger = logging.getLogger(__name__)


class HTTPAdapter:
    """HTTP API 호출 어댑터"""
    
    async def execute(
        self,
        spec: ToolSpec,
        arguments: Dict[str, Any],
        timeout: float = 30.0
    ) -> str:
        """
        HTTP API 호출
        
        Args:
            spec: 툴 스펙
            arguments: HTTP 요청 인자
            timeout: 타임아웃 (초)
            
        Returns:
            str: HTTP 응답 본문
        """
        url = spec.adapter_config.get("url")
        method = spec.adapter_config.get("method", "GET")
        headers = spec.adapter_config.get("headers", {})
        
        if not url:
            raise ValueError(f"URL not found in adapter_config for {spec.id}")
        
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                if method.upper() == "GET":
                    response = await client.get(url, headers=headers, params=arguments)
                elif method.upper() == "POST":
                    response = await client.post(url, headers=headers, json=arguments)
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")
                
                response.raise_for_status()
                return response.text
        except httpx.TimeoutException:
            raise TimeoutError(f"HTTP request timeout after {timeout}s")
        except Exception as e:
            logger.error(
                f"HTTP adapter execution failed for {spec.id}",
                extra={"tool_id": spec.id, "url": url, "error": str(e)},
                exc_info=True
            )
            raise

