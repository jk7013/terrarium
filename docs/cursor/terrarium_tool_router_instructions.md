# Terrarium: MCP Tool Router + 추가 Tool(계산/날짜/헬스체크/PII) 구현 지시서

> 목적: `pipeline.py`에 늘어나는 `if is_weather_query ... elif is_time_query ...` 패턴을 없애고,  
> **툴 라우팅/실행/컨텍스트 주입/에러처리**를 공통 파이프라인으로 묶는다.  
> 동시에 “툴이 잘 붙었는지” 검증에 좋은 **결정론적 툴(계산, 날짜)** + **운영진단(헬스체크)** + **보안(PII 마스킹)** 툴을 추가한다.

---

## 0) 현재 상태 요약

- `app/rag/pipeline.py`
  - `is_weather_query`, `is_time_query`로 툴 트리거
  - 툴 결과를 `ContextItem`으로 만들어 `_call_llm_with_context()`에 넣음 (이 구조는 좋음)
  - 문제: 툴이 늘어날수록 `pipeline.py`가 커지고 라우팅 규칙/실행/메타/예외가 흩어진다.

---

## 1) 목표 아키텍처

### 1.1 핵심 아이디어
- 툴을 “등록”하고, 라우터가 “선택”하고, 실행 결과를 “컨텍스트로 주입”하는 흐름을 **공통화**한다.

```
QueryRequest(query)
  -> ToolRouter.route(query) => ToolCall(name, args)
  -> ToolExecutor.execute(ToolCall) => tool_text, tool_meta
  -> ContextItem(tool_text, tool_meta)
  -> _call_llm_with_context(request, [ContextItem] + (기존 contexts))
  -> QueryResponse(meta.tool=tool_name)
```

### 1.2 파일 구성(권장)
- `app/tools/registry.py` : ToolSpec/ToolCall/ToolRegistry
- `app/tools/router.py`   : route(query) 로직 (rule-based 우선)
- `app/tools/executor.py` : execute(tool_call) 공통 실행/예외/타임아웃
- `app/tools/*.py`        : 개별 툴(날씨/시간/계산/날짜/헬스체크/PII)

> 너가 이미 “MCP까지 붙였다”고 했으니, executor는 **로컬 함수 호출** + **MCP 호출** 둘 다 지원하게 만들어.

---

## 2) 구현 단계

## 2.1 Tool 데이터 구조 만들기

### (A) `app/tools/registry.py` 생성
- 아래 클래스/타입을 만든다.

```python
from dataclasses import dataclass
from typing import Callable, Any, Optional

@dataclass(frozen=True)
class ToolCall:
    name: str
    args: dict

@dataclass(frozen=True)
class ToolResult:
    text: str
    meta: dict

@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    # query -> (matched: bool, args: dict)
    match: Callable[[str], tuple[bool, dict]]
    # args -> ToolResult (sync or async)
    run: Callable[[dict], Any]
    meta: dict

class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolSpec] = {}

    def register(self, tool: ToolSpec) -> None:
        self._tools[tool.name] = tool

    def all(self) -> list[ToolSpec]:
        return list(self._tools.values())
```

---

## 2.2 라우터 만들기 (rule-based)

### (A) `app/tools/router.py` 생성
- “정확한 트리거”가 가능한 툴(날씨/시간/계산/날짜/헬스)은 **룰 기반**으로 먼저 라우팅한다.
- 여러 툴이 동시에 매치될 수 있으면 **우선순위**를 둔다.

```python
from app.tools.registry import ToolRegistry, ToolCall

class ToolRouter:
    def __init__(self, registry: ToolRegistry):
        self.registry = registry

    def route(self, query: str) -> ToolCall | None:
        q = (query or "").strip()
        if not q:
            return None

        # 우선순위 순으로 평가
        for tool in self.registry.all():
            matched, args = tool.match(q)
            if matched:
                return ToolCall(name=tool.name, args=args)
        return None
```

> **중요:** `registry.all()`이 등록 순서를 유지하도록 등록 순서를 우선순위로 사용해.  
> (Python 3.7+ dict insertion order 보장)

---

## 2.3 실행기 만들기 (로컬/MC P 호출 + 예외 표준화)

### (A) `app/tools/executor.py` 생성
- 공통 정책:
  - 타임아웃
  - 예외 -> 표준 ToolResult(text/meta)
  - 실패해도 `pipeline`이 터지지 않게 “안전한 결과” 반환

```python
import asyncio
import httpx
from app.tools.registry import ToolRegistry, ToolCall, ToolResult

class ToolExecutor:
    def __init__(self, registry: ToolRegistry, timeout_seconds: float = 10.0):
        self.registry = registry
        self.timeout_seconds = timeout_seconds

    async def execute(self, call: ToolCall) -> ToolResult:
        tool = self.registry._tools.get(call.name)
        if not tool:
            return ToolResult(text=f"Unknown tool: {call.name}", meta={"error": "unknown_tool"})

        try:
            maybe_coro = tool.run(call.args)

            if asyncio.iscoroutine(maybe_coro):
                result = await asyncio.wait_for(maybe_coro, timeout=self.timeout_seconds)
            else:
                # sync도 허용
                result = maybe_coro

            # result가 ToolResult면 그대로, 아니면 (text, meta)로 감싼다
            if isinstance(result, ToolResult):
                return result
            if isinstance(result, tuple) and len(result) == 2:
                return ToolResult(text=result[0], meta=result[1])
            return ToolResult(text=str(result), meta={"source": call.name})
        except asyncio.TimeoutError:
            return ToolResult(
                text=f"{call.name} tool timeout ({self.timeout_seconds}s)",
                meta={"error": "timeout", "tool": call.name, "timeout_s": self.timeout_seconds},
            )
        except httpx.HTTPError as e:
            return ToolResult(
                text=f"{call.name} tool http error: {type(e).__name__}",
                meta={"error": "http_error", "tool": call.name, "detail": str(e)},
            )
        except Exception as e:
            return ToolResult(
                text=f"{call.name} tool failed: {type(e).__name__}",
                meta={"error": "exception", "tool": call.name, "detail": str(e)},
            )
```

---

## 2.4 툴 추가 (추천 4종)

> 네가 이미 `weather.py`, `time.py`는 있으니 “registry 등록 + match 함수”만 맞추면 된다.  
> 아래는 **새로 추가할 툴 3개 + 보안 1개**.

### (A) 계산기/단위변환: `app/tools/calc.py`
- 목표: “정답이 있는 질문”에 대해 LLM 없이 계산 결과를 제공
- 입력 예시:
  - “3.5시간을 분으로”
  - “부가세 포함 12300원 공급가”
  - “1.2GB를 MB로”

구현 방식(최소):
- 정규식으로 숫자/단위 추출
- 가능하면 기능을 2~3개만 먼저 (시간/분 변환, VAT 10%, KB/MB/GB)

`match(query)`는 “계산/변환” 키워드 + 패턴으로 판단.

**출력 텍스트는 사람이 읽기 좋게**:
- `결과: 210분`
- `공급가: 11,182원 / 부가세: 1,118원` (10% 기준)

### (B) 날짜/기간 계산: `app/tools/date_math.py`
- 목표: “3주 뒤”, “D-일” 같은 연쇄 질의 대응
- 함수:
  - `date_diff(start, end)` (days)
  - `add_days(date, n)` / `add_weeks(date, n)`
- 파싱:
  - `YYYY-MM-DD`
  - “오늘/내일/모레/어제”
  - “3주 뒤/5일 후”

출력:
- ISO 날짜 + 요일(Asia/Seoul 기준)

### (C) 헬스체크: `app/tools/health.py`
- 목표: “왜 답이 느린지/안나오는지” 원인 분리
- 기능:
  - `llm_ping` : `app.llm.client`가 바라보는 Ollama/Qwen endpoint에 간단 요청
  - `weather_ping` : 크롤링이 되는지 (실제 호출 or 캐시)
  - `time_ping` : 단순
- 출력:
  - 각 항목 `ok/fail`, latency_ms, endpoint, model

### (D) PII 마스킹: `app/tools/pii.py`
- 목표: trace/log/컨텍스트 저장 전에 개인정보 위험 줄이기
- v0 규칙:
  - 전화번호(010-xxxx-xxxx)
  - 이메일
  - 주민번호 패턴(#######-#######) **단, 오탐 가능**
- 출력:
  - 마스킹된 텍스트
  - meta에 `masked_fields` 목록

> 적용 위치(권장):  
> - “로그에 query 저장” 직전에 `mask_pii(query)`  
> - tool 결과를 context로 넣기 전에도 필요하면 적용

---

## 2.5 registry에 기존/신규 툴 등록

### (A) `app/tools/__init__.py` 또는 `app/tools/bootstrap.py` 만들기
- registry를 생성하고 툴을 등록하는 진입점 하나로 통일한다.

```python
from app.tools.registry import ToolRegistry, ToolSpec

from app.tools.weather import is_weather_query, get_weather
from app.tools.time import is_time_query, get_current_time

from app.tools.calc import match_calc, run_calc
from app.tools.date_math import match_date_math, run_date_math
from app.tools.health import match_health, run_health

def build_registry() -> ToolRegistry:
    reg = ToolRegistry()

    reg.register(ToolSpec(
        name="weather",
        description="Get current weather info",
        match=lambda q: (is_weather_query(q), {}),
        run=lambda args: (get_weather(), {"source": "accuweather", "location": "seoul"}),
        meta={"kind": "mcp_or_local"},
    ))

    reg.register(ToolSpec(
        name="time",
        description="Get current time in Asia/Seoul",
        match=lambda q: (is_time_query(q), {}),
        run=lambda args: (get_current_time(), {"source": "system", "timezone": "Asia/Seoul"}),
        meta={"kind": "local"},
    ))

    reg.register(ToolSpec(
        name="calc",
        description="Deterministic calculator/unit converter",
        match=match_calc,
        run=run_calc,
        meta={"kind": "local"},
    ))

    reg.register(ToolSpec(
        name="date_math",
        description="Date difference and date arithmetic",
        match=match_date_math,
        run=run_date_math,
        meta={"kind": "local"},
    ))

    reg.register(ToolSpec(
        name="health",
        description="Check tool/LLM health status",
        match=match_health,
        run=run_health,
        meta={"kind": "local"},
    ))

    return reg
```

> 우선순위: weather/time 같은 “명확한 툴”을 위에 두고, calc/date_math/health 순으로 간다.

---

## 2.6 `pipeline.py` 수정: if/elif 제거하고 공통 라우팅으로 교체

### 변경 포인트
- `run_rag()`의 “툴 체크” 블록을 아래 형태로 바꾼다.
- 기존 `_call_llm_with_tool_context()`는 그대로 재사용한다 (이미 잘 되어 있음)

**의사코드:**

```python
from app.tools.bootstrap import build_registry
from app.tools.router import ToolRouter
from app.tools.executor import ToolExecutor

_registry = build_registry()
_router = ToolRouter(_registry)
_executor = ToolExecutor(_registry, timeout_seconds=10.0)

tool_call = _router.route(request.query)

if tool_call:
    tool_result = await _executor.execute(tool_call)

    llm_trace, answer, status, contexts = await _call_llm_with_tool_context(
        request=request,
        tool_info=tool_result.text,
        tool_name=tool_call.name,
        tool_meta=tool_result.meta,
        trace_id=trace_id,
    )

    retrieval_trace = RetrievalTrace(
        query_expansions=_expand_query(request.query),
        bm25_results=[],
        vector_results=[],
        reranked_results=[],
    )
    used_tool = tool_call.name
else:
    # 기존 일반 RAG 흐름
```

---

## 3) 테스트 시나리오 (필수)

### 3.1 계산기
- “3.5시간을 분으로 바꿔줘” → `calc` 트리거 / 결과 210분
- “부가세 포함 12300원 공급가” → 공급가/부가세 분리

### 3.2 날짜
- “2025-12-23에서 3주 뒤” → 2026-01-13(요일 포함)
- “오늘부터 10일 후” → ISO 날짜

### 3.3 헬스체크
- “지금 llm 상태 어때?” → `health` 트리거 / endpoint/model/latency 출력

### 3.4 실패 처리
- 날씨 크롤링 실패 강제(네트워크 차단/timeout) → tool_result에 error meta / 파이프라인은 정상 응답
- LLM timeout → 지금처럼 tool_info를 fallback으로 내보내는지 확인

---

## 4) 보안/폐쇄망 기본값(필수)

- **ONLINE/OFFLINE 모드**를 env로 나눈다.
  - `TERRARIUM_MODE=OFFLINE`이면 외부 크롤링/외부 API 호출 금지 (weather는 캐시/비활성)
- 로그:
  - query/raw_text를 그대로 로그로 남기지 말고, 필요하면 `mask_pii()` 적용 후 남긴다.
  - tool_result도 민감할 수 있으니 동일 정책 적용.
- allowlist:
  - MCP/HTTP 호출은 사전 등록된 host만 허용 (env allowlist)

---

## 5) “완료 기준(Definition of Done)”
- `pipeline.py`에서 weather/time if/elif가 사라지고, router/executor 경유로 동작한다.
- `calc`, `date_math`, `health` 최소 1개씩 정상 트리거된다.
- 툴 timeout/예외 시에도 API는 200(또는 meta.status=error)로 안정적으로 응답한다.
- trace/meta에 `tool` 필드가 정확히 채워진다.

---

## 6) 작업 순서(권장)
1. `registry/router/executor` 뼈대 추가
2. weather/time을 registry 방식으로 이관
3. calc 추가(가장 쉬움)
4. date_math 추가
5. health 추가
6. pipeline 라우팅 교체
7. 테스트 케이스 실행 + 로그/PII 체크

