"""
Prompt Renderer - 템플릿 렌더링
"""
import hashlib
import json
import logging
from typing import List, Dict, Any
from app.prompts.schema import PromptPack, RenderedPrompt, PromptRenderRequest
from app.prompts.registry import PromptRegistry

logger = logging.getLogger(__name__)


class PromptRenderer:
    """프롬프트 렌더러: 템플릿을 실제 프롬프트로 변환"""
    
    def __init__(self, registry: PromptRegistry):
        self.registry = registry
    
    def render(self, request: PromptRenderRequest) -> RenderedPrompt:
        """
        프롬프트 렌더링
        
        Args:
            request: 렌더링 요청
            
        Returns:
            RenderedPrompt: 렌더링된 프롬프트
        """
        pack = self.registry.get(request.pack_id)
        if not pack:
            # 기본 팩이 없으면 fallback
            logger.warning(f"Prompt pack {request.pack_id} not found, using default")
            pack = self.registry.get("default")
            if not pack:
                raise ValueError(f"Prompt pack {request.pack_id} not found and no default pack available")
        
        # 변수 병합 (기본값 + 요청 변수)
        variables = {**pack.defaults, **request.variables}
        
        # 시스템 프롬프트 렌더링
        system_content = self._render_template(pack.system_template, variables, request)
        
        # Developer 템플릿이 있으면 추가
        if pack.developer_template:
            developer_content = self._render_template(pack.developer_template, variables, request)
            system_content = f"{system_content}\n\n{developer_content}"
        
        # 사용자 프롬프트 구성
        user_content = request.query
        if pack.user_prefix_template:
            prefix = self._render_template(pack.user_prefix_template, variables, request)
            user_content = f"{prefix}\n\n{user_content}"
        
        # 컨텍스트가 있으면 추가
        if request.contexts:
            context_text = self._format_contexts(request.contexts)
            user_content = f"{user_content}\n\n컨텍스트:\n{context_text}"
        
        # Messages 배열 구성
        messages = []
        if system_content:
            messages.append({"role": "system", "content": system_content})
        
        # 대화 히스토리 추가
        messages.extend(request.chat_history)
        
        # 현재 사용자 질문 추가
        messages.append({"role": "user", "content": user_content})
        
        # Evidence 요약 생성
        evidence_summary = self._create_evidence_summary(request.contexts)
        
        # 프롬프트 해시 생성 (동일성 비교용)
        prompt_hash = self._compute_hash(messages)
        
        return RenderedPrompt(
            messages=messages,
            variables_used=variables,
            evidence_summary=evidence_summary,
            prompt_hash=prompt_hash
        )
    
    def _render_template(self, template: str, variables: Dict[str, Any], request: PromptRenderRequest) -> str:
        """템플릿 렌더링 (간단한 변수 치환)"""
        result = template
        for key, value in variables.items():
            result = result.replace(f"{{{{{key}}}}}", str(value))
        return result
    
    def _format_contexts(self, contexts: List[Dict[str, Any]]) -> str:
        """컨텍스트 포맷팅"""
        parts = []
        for i, ctx in enumerate(contexts, 1):
            text = ctx.get("text", "")
            meta = ctx.get("meta", {})
            source = meta.get("source", "unknown")
            parts.append(f"[{i}] {text} (출처: {source})")
        return "\n".join(parts)
    
    def _create_evidence_summary(self, contexts: List[Dict[str, Any]]) -> str:
        """Evidence 요약 생성"""
        if not contexts:
            return "컨텍스트 없음"
        
        summary_parts = []
        for ctx in contexts:
            meta = ctx.get("meta", {})
            tool_name = meta.get("source", "unknown")
            summary_parts.append(f"- {tool_name}")
        
        return f"사용된 컨텍스트 ({len(contexts)}개):\n" + "\n".join(summary_parts)
    
    def _compute_hash(self, messages: List[Dict[str, str]]) -> str:
        """프롬프트 해시 계산"""
        content = json.dumps(messages, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]



