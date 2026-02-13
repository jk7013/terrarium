# 🌱 Terrarium 프로젝트 전체 개요

> **Terrarium**은 "병 속 작은 생태계"처럼, RAG에 필요한 모든 컴포넌트를 한 엔진 안에 담는 독립 RAG 백엔드 서비스입니다.

---

## 📋 목차

1. [프로젝트 개요](#프로젝트-개요)
2. [주요 기능](#주요-기능)
3. [시스템 아키텍처](#시스템-아키텍처)
4. [프로젝트 구조](#프로젝트-구조)
5. [파일별 상세 설명](#파일별-상세-설명)
6. [데이터 흐름](#데이터-흐름)
7. [툴 시스템](#툴-시스템)
8. [API 엔드포인트](#api-엔드포인트)
9. [개발 환경 설정](#개발-환경-설정)

---

## 프로젝트 개요

### 목적
- **독립적인 RAG 백엔드 서비스**: 문서 파싱, 임베딩, 검색, 리랭킹, LLM 호출을 포함한 완전한 RAG 파이프라인 제공
- **HTTP API 기반**: 외부 시스템(예: Jido)과 느슨하게 결합되어 HTTP API로만 통신
- **확장 가능한 툴 시스템**: MCP 스타일의 툴 시스템으로 외부 기능 통합

### 기술 스택
- **백엔드**: FastAPI (Python)
- **LLM**: Ollama (로컬 LLM 서버)
- **데이터 검증**: Pydantic
- **HTTP 클라이언트**: httpx
- **웹 스크래핑**: BeautifulSoup, lxml
- **프론트엔드**: HTML/CSS/JavaScript (정적 파일)

### 현재 버전
- **v0**: 기본 RAG 파이프라인 + 툴 시스템 구현 완료
- 향후 계획: 임베딩, 벡터 검색, 리랭킹 단계 추가

---

## 주요 기능

### 1. RAG 파이프라인
- **쿼리 확장**: 규칙 기반 쿼리 확장 (동의어, 표현 변형)
- **컨텍스트 구성**: Ephemeral 모드에서 raw_text 기반 컨텍스트 생성
- **LLM 호출**: Ollama를 통한 LLM 응답 생성
- **멀티턴 대화**: 대화 히스토리 지원

### 2. 툴 시스템 (MCP 스타일)
- **날씨 툴**: AccuWeather에서 서울 날씨 정보 가져오기
- **시간 툴**: 현재 시간/날짜/요일 정보 제공
- **확장 가능**: 새로운 툴을 쉽게 추가 가능

### 3. 웹 인터페이스
- **채팅 UI**: 사용자 친화적인 채팅 인터페이스
- **메타 정보 표시**: model, mode, profile, tool 정보 표시
- **대화 히스토리**: 사이드바에 대화 목록 표시

### 4. 추적 및 로깅
- **Trace 정보**: retrieval_trace, llm_trace 제공
- **메타데이터**: mode, profile, timestamp, status, tool 정보 포함

---

## 시스템 아키텍처

### 전체 구조

```
┌─────────────────┐
│  Web Browser    │
│  (index.html)   │
└────────┬────────┘
         │ HTTP
         ▼
┌─────────────────┐
│  FastAPI Server │
│  (app/main.py)  │
└────────┬────────┘
         │
    ┌────┴────┐
    │         │
    ▼         ▼
┌────────┐ ┌──────────┐
│  API   │ │   RAG     │
│ Routes │ │ Pipeline  │
└───┬────┘ └─────┬─────┘
    │            │
    │      ┌─────┴─────┐
    │      │           │
    ▼      ▼           ▼
┌──────┐ ┌──────┐ ┌────────┐
│Tools │ │ LLM  │ │Schemas │
│      │ │Client│ │        │
└──────┘ └───┬──┘ └────────┘
             │
             ▼
      ┌──────────┐
      │  Ollama  │
      │  Server  │
      └──────────┘
```

### 데이터 흐름

1. **사용자 질문 입력** → 웹 인터페이스 (`static/index.html`)
2. **API 요청** → `POST /api/query` (`app/api/routes/query.py`)
3. **RAG 파이프라인 실행** → `app/rag/pipeline.py`
   - 툴 체크 (날씨/시간 질문 감지)
   - 쿼리 확장
   - 컨텍스트 구성
   - LLM 호출
4. **LLM 응답 생성** → `app/llm/client.py` → Ollama 서버
5. **응답 반환** → 웹 인터페이스에 표시

---

## 프로젝트 구조

```
terrarium/
├── app/                          # 메인 애플리케이션 코드
│   ├── __init__.py
│   ├── main.py                   # FastAPI 엔트리포인트
│   │
│   ├── api/                      # HTTP API 엔드포인트
│   │   ├── __init__.py
│   │   ├── health.py             # GET /health
│   │   ├── routes/
│   │   │   └── query.py          # POST /api/query
│   │   └── schemas/
│   │       └── query.py          # Pydantic 모델 정의
│   │
│   ├── rag/                      # RAG 파이프라인 로직
│   │   ├── __init__.py
│   │   └── pipeline.py           # run_rag 함수
│   │
│   ├── llm/                      # LLM 클라이언트
│   │   ├── __init__.py
│   │   └── client.py             # Ollama 호출
│   │
│   ├── tools/                    # 툴 시스템
│   │   ├── __init__.py
│   │   ├── bootstrap.py           # 툴 등록(레지스트리 빌드)
│   │   ├── registry.py            # ToolSpec/ToolCall/ToolRegistry
│   │   ├── router.py              # query -> ToolCall 라우팅
│   │   ├── executor.py            # 실행/타임아웃/에러 표준화
│   │   ├── adapters/              # 실행 어댑터(MCP/로컬/HTTP)
│   │   │   ├── mcp_adapter.py
│   │   │   ├── local_adapter.py
│   │   │   └── http_adapter.py
│   │   ├── weather.py             # 날씨 툴
│   │   └── time.py                # 시간 툴
│   │
│   ├── prompts/                   # GPTs 스타일 프롬프트 팩 시스템
│   │   ├── __init__.py
│   │   ├── schema.py              # PromptPack/RenderedPrompt 스키마
│   │   ├── registry.py            # 팩 등록/조회
│   │   ├── renderer.py            # 템플릿 렌더링
│   │   └── packs/                 # YAML/JSON 템플릿
│   │       ├── default.yaml
│   │       ├── weather_assistant.yaml
│   │       └── dev_debug.yaml
│
├── static/                       # 정적 파일
│   └── index.html                # 웹 인터페이스
│
├── docs/                         # 문서
│   ├── chatGPT/                  # ChatGPT용 문서
│   ├── concepts/                 # 개념 문서
│   ├── cursor/                   # Cursor용 문서
│   └── PROJECT_OVERVIEW.md       # 이 문서
│
├── tests/                        # 테스트 코드
├── data/                         # 샘플 데이터
├── docker/                       # Docker 설정
├── scripts/                      # 유틸리티 스크립트
│
├── requirements.txt              # Python 의존성
├── README.md                     # 프로젝트 소개
└── env.example                   # 환경변수 예시
```

---

## 파일별 상세 설명

### 1. `app/main.py`
**역할**: FastAPI 애플리케이션의 엔트리포인트

**주요 내용**:
- FastAPI 앱 초기화
- CORS 미들웨어 설정
- API 라우터 등록 (`/health`, `/api/query`)
- 정적 파일 서빙 (`/static`)

**엔드포인트**:
- `GET /`: 루트 엔드포인트 (상태 확인)
- `GET /health`: 헬스체크
- `POST /api/query`: RAG 쿼리 실행

---

### 2. `app/api/routes/query.py`
**역할**: RAG 쿼리 API 엔드포인트

**주요 내용**:
- `POST /api/query` 엔드포인트 정의
- `QueryRequest`를 받아 `run_rag` 호출
- `QueryResponse` 반환

---

### 3. `app/api/schemas/query.py`
**역할**: API 요청/응답 스키마 정의 (Pydantic 모델)

**주요 모델**:
- `QueryRequest`: 사용자 질문, mode, profile, raw_text, chat_history
- `QueryResponse`: answer, contexts, retrieval_trace, llm_trace, meta
- `ContextItem`: 컨텍스트 청크 정보
- `RetrievalTrace`: 검색 과정 추적 정보
- `LLMTrace`: LLM 호출 추적 정보
- `QueryMeta`: mode, profile, timestamp, status, **tool** (툴 정보)

---

### 4. `app/rag/pipeline.py`
**역할**: RAG 파이프라인의 핵심 로직

**주요 함수**:

#### `_expand_query(query: str) -> list[str]`
- 규칙 기반 쿼리 확장
- 정중 표현 제거, 동의어 치환, "어떻게" → "절차"/"방법" 변환

#### `_build_ephemeral_contexts(request: QueryRequest) -> list[ContextItem]`
- Ephemeral 모드에서 raw_text를 ContextItem으로 변환
- 현재는 raw_text 전체를 하나의 청크로 사용

#### `_call_llm_with_tool_context(...) -> tuple[LLMTrace, str, str, list[ContextItem]]`
- **공통 툴 처리 함수**: 모든 툴이 일관되게 LLM에 컨텍스트로 전달되도록 보장
- 툴 정보를 ContextItem으로 변환
- LLM 호출 및 에러 처리

#### `_call_llm_with_context(request, contexts) -> tuple[LLMTrace, str]`
- 컨텍스트와 질문을 조합하여 프롬프트 생성
- 날씨/일반 컨텍스트에 따라 프롬프트 조정
- `call_llm` 호출

#### `run_rag(request: QueryRequest) -> QueryResponse`
- **RAG 파이프라인의 엔트리포인트**
- 툴 체크 (날씨/시간 질문 감지)
- 쿼리 확장
- 컨텍스트 구성
- LLM 호출
- 최종 응답 조립

**툴 처리 로직**:
```python
if is_weather_query(request.query):
    # 날씨 툴 호출 → LLM 컨텍스트로 전달
elif is_time_query(request.query):
    # 시간 툴 호출 → LLM 컨텍스트로 전달
else:
    # 일반 RAG 파이프라인
```

---

### 5. `app/llm/client.py`
**역할**: Ollama LLM 서버와의 통신

**주요 함수**:

#### `call_llm(prompt: str, chat_history: Optional[List[Dict]]) -> Tuple[str, LLMTrace]`
- Ollama `/api/chat` 엔드포인트 호출
- 멀티턴 대화 지원 (chat_history)
- 타임아웃: 5분 (300초)
- LLMTrace 생성 (model, prompt, output, latency_ms)

**환경변수**:
- `OLLAMA_HOST`: Ollama 서버 주소 (기본값: `http://localhost:11434`)
- `OLLAMA_MODEL`: 사용할 모델 (기본값: `qwen3:4b`)

---

### 6. `app/tools/weather.py`
**역할**: 날씨 정보 툴

**주요 함수**:

#### `get_weather() -> str`
- AccuWeather에서 서울 날씨 정보 스크래핑
- 온도와 날씨 상태 추출
- 여러 파싱 전략 사용 (JSON-LD, data 속성, 정규식)
- 한글 날씨 상태로 변환

#### `is_weather_query(query: str) -> bool`
- 질문이 날씨 관련인지 감지
- 단어 경계 고려하여 오인식 방지
- "비", "눈" 같은 키워드는 맥락 확인

---

### 7. `app/tools/time.py`
**역할**: 시간/날짜 정보 툴

**주요 함수**:

#### `get_current_time() -> str`
- 현재 시간/날짜/요일 정보 반환
- 서울 시간대 기준
- 포맷: "2024년 12월 23일 월요일 11시 30분 (서울 시간)"

#### `is_time_query(query: str) -> bool`
- 질문이 시간/날짜 관련인지 감지
- 키워드: "시간", "날짜", "요일", "지금", "현재", "오늘" 등

---

### 8. `static/index.html`
**역할**: 웹 채팅 인터페이스

**주요 기능**:
- 채팅 UI (사용자/어시스턴트 메시지)
- 사이드바 (대화 히스토리)
- 입력창 (Enter 전송, Shift+Enter 줄바꿈)
- 한국어 IME 입력 처리 (`isComposing` 체크)
- 메타 정보 표시 (model, mode, profile, **tool**)
- 스크롤 관리 (고정 헤더/푸터, 스크롤 가능한 채팅 영역)

**JavaScript 함수**:
- `callBackend(query, chatHistory)`: API 호출
- `renderChat()`: 채팅 렌더링
- `renderMessage(m)`: 메시지 렌더링
- `scrollToBottom()`: 스크롤 하단으로 이동

---

## 데이터 흐름

### 1. 사용자 질문 → API 요청

```javascript
// static/index.html
const response = await fetch('/api/query', {
  method: 'POST',
  body: JSON.stringify({
    query: "오늘 날씨 알려줘",
    mode: "ephemeral",
    profile: "default",
    chat_history: [...]
  })
});
```

### 2. API 라우터 → RAG 파이프라인

```python
# app/api/routes/query.py
@router.post("/query")
async def query_endpoint(request: QueryRequest):
    return await run_rag(request)
```

### 3. RAG 파이프라인 실행

```python
# app/rag/pipeline.py
async def run_rag(request: QueryRequest):
    # 1. 툴 체크
    if is_weather_query(request.query):
        weather_info = get_weather()
        # 툴 정보를 LLM 컨텍스트로 전달
        llm_trace, answer, status, contexts = await _call_llm_with_tool_context(...)
        used_tool = "weather"
    
    # 2. 쿼리 확장
    expansions = _expand_query(request.query)
    
    # 3. 컨텍스트 구성
    contexts = _build_ephemeral_contexts(request)
    
    # 4. LLM 호출
    llm_trace, answer = await _call_llm_with_context(request, contexts)
    
    # 5. 응답 조립
    return QueryResponse(...)
```

### 4. LLM 호출

```python
# app/llm/client.py
async def call_llm(prompt, chat_history):
    # Ollama API 호출
    response = await client.post(f"{OLLAMA_HOST}/api/chat", json={
        "model": OLLAMA_MODEL,
        "messages": [...],
        "stream": False
    })
    return output_text, llm_trace
```

### 5. 응답 반환 → 웹 인터페이스

```javascript
// static/index.html
const data = await res.json();
// data.answer, data.meta.tool 등 표시
```

---

## 툴 시스템

### 아키텍처

모든 툴은 **일관된 패턴**을 따릅니다:

1. **감지 함수**: `is_*_query(query: str) -> bool`
   - 질문이 해당 툴을 사용해야 하는지 판단

2. **실행 함수**: `get_*() -> str`
   - 툴의 실제 기능 실행
   - 정보를 문자열로 반환

3. **통합**: `_call_llm_with_tool_context()`
   - 툴 정보를 ContextItem으로 변환
   - LLM에 컨텍스트로 전달
   - LLM이 자연스러운 답변 생성

### 현재 구현된 툴

#### 1. 날씨 툴 (`app/tools/weather.py`)
- **기능**: AccuWeather에서 서울 날씨 정보 가져오기
- **감지 키워드**: "날씨", "기온", "온도", "비", "눈" 등
- **반환 형식**: "서울의 현재 날씨는 2도이고, 비입니다"

#### 2. 시간 툴 (`app/tools/time.py`)
- **기능**: 현재 시간/날짜/요일 정보 제공
- **감지 키워드**: "시간", "날짜", "요일", "지금", "현재" 등
- **반환 형식**: "2024년 12월 23일 월요일 11시 30분 (서울 시간)"

### 새로운 툴 추가 방법

1. **툴 파일 생성** (`app/tools/new_tool.py`):
```python
def get_new_tool() -> str:
    # 툴 기능 구현
    return "툴 결과"

def is_new_tool_query(query: str) -> bool:
    # 질문 감지 로직
    return False
```

2. **툴 등록** (`app/tools/__init__.py`):
```python
from app.tools.new_tool import get_new_tool, is_new_tool_query
```

3. **파이프라인에 통합** (`app/rag/pipeline.py`):
```python
elif is_new_tool_query(request.query):
    tool_info = get_new_tool()
    llm_trace, answer, status, contexts = await _call_llm_with_tool_context(
        request=request,
        tool_info=tool_info,
        tool_name="new_tool",
        tool_meta={"source": "..."},
        trace_id=trace_id,
    )
    used_tool = "new_tool"
```

---

---

## v0.1 리팩터링 지시서: Tool Orchestration + Prompt Pack(GPTs 스타일)

지금은 `app/rag/pipeline.py`에서 `is_weather_query`/`is_time_query`로 분기하고, 툴 결과를 컨텍스트로 넣어서 LLM이 답하게 하는 흐름이야. 이건 v0로는 충분히 좋고, 다음 단계는 **MCP/툴을 구조적으로 확장 가능**하게 만들고, 동시에 **GPTs처럼 “프롬프트를 싸서(render) 출력/디버깅”**하는 기능까지 넣는 거야.

아래 지시대로 정리하면 툴이 2개에서 20개로 늘어도 `pipeline.py`가 안 터지고, “프롬프트가 실제로 어떻게 구성됐는지”도 UI/trace로 확인 가능해져.

### 1) 목표 아키텍처(레이어 분리)

#### 1.1 레이어 5개로 고정
- **Orchestrator**: 전체 흐름(툴 쓸지/멀티툴 체인/실패 정책/툴 budget)
- **Router/Planner**: query → ToolCall 결정(룰 우선 + LLM fallback)
- **Tool Executor**: MCP/로컬/HTTP 실행을 한 곳에 모음(타임아웃/재시도/에러 표준화/allowlist)
- **Context Builder**: 툴 결과를 “증거(evidence)” 규격으로 정규화해서 LLM에 주입
- **Answer Generator**: 최종 LLM 호출(프롬프트 팩 적용 + 근거 사용 규칙)

핵심 원칙은 이거야:
- **MCP는 transport 레이어(호출 방법)로만 둔다**
- **툴 의미(what)와 호출 방식(how)을 분리한다**
- **툴 결과는 반드시 Evidence 스키마로 통일한다**

### 2) 폴더/파일 구조(추가)

#### 2.1 Tools 리팩터링(등록/라우팅/실행 공통화)
`app/tools/` 아래를 이렇게 확장해.

- `app/tools/registry.py`
  - `ToolSpec`, `ToolCall`, `ToolResult`, `ToolRegistry`
- `app/tools/router.py`
  - `ToolRouter.route(query) -> ToolCall | None`
  - 등록 순서 = 우선순위 (weather/time처럼 명확한 툴을 위에 둠)
- `app/tools/executor.py`
  - `ToolExecutor.execute(call) -> ToolResult`
  - 타임아웃/예외/표준 에러 메타
- `app/tools/adapters/`
  - `mcp_adapter.py` (MCP 서버 호출)
  - `local_adapter.py` (파이썬 함수 호출)
  - `http_adapter.py` (내부 REST 호출)
- `app/tools/bootstrap.py`
  - `build_registry()`로 모든 툴 등록(한 곳에서만)

> v0의 `weather.py`, `time.py`는 그대로 두고, “registry에 등록 + match 함수”만 붙이면 돼.

#### 2.2 Prompts(프롬프트 팩) 시스템 추가(GPTs 스타일)
`app/prompts/`를 새로 만들고 프롬프트를 “팩”으로 관리해.

- `app/prompts/schema.py`
  - `PromptPack`, `PromptRenderRequest`, `PromptRenderResponse`
- `app/prompts/registry.py`
  - `PromptRegistry` (팩 등록/조회)
- `app/prompts/renderer.py`
  - `render(pack_id, variables, tool_contexts, chat_history, user_query) -> RenderedPrompt`
- `app/prompts/packs/`
  - `default.yaml` (기본 팩)
  - `weather_assistant.yaml` (툴 증거 기반 답변 강화)
  - `dev_debug.yaml` (디버깅/프롬프트 출력용)

> “GPTs처럼”의 핵심은: **팩을 선택하면 system/developer/user 템플릿과 변수 스키마가 고정**되고, 실제로 LLM에 들어가는 최종 프롬프트를 **render 결과로 출력/저장/비교**할 수 있어야 한다는 거야.

### 3) Prompt Pack 설계(필수 필드)

#### 3.1 PromptPack 최소 스키마
- `id`: 문자열 (예: `default`, `weather_assistant`)
- `name`: 표시용 이름
- `version`: `v0.1.0` 같은 버전
- `system_template`: 시스템 프롬프트 템플릿
- `developer_template`(옵션): 내부 규칙(형식/안전/근거 사용 규칙)
- `user_prefix_template`(옵션): 사용자 질문 앞에 붙일 prefix
- `variables_schema`: 변수 정의(JSON Schema 느낌)
- `defaults`: 변수 기본값
- `tool_policy`:
  - `allowed_tools`: allowlist
  - `max_tool_calls`: 예: 2
  - `require_evidence`: True/False
- `output_format`:
  - `style`: `concise`/`detailed`
  - `citations`: `none`/`evidence_only`

#### 3.2 RenderedPrompt(디버그용 출력)
- `messages`: Ollama `/api/chat`에 넣는 최종 messages 배열
- `variables_used`: 최종 적용된 변수들
- `evidence_summary`: 컨텍스트 요약(툴/리트리벌)
- `prompt_hash`: 동일성 비교용 해시

### 4) 파이프라인 통합 포인트(중요)

#### 4.1 `run_rag()` 흐름을 이렇게 바꿔
1) `ToolRouter`로 ToolCall 결정
2) `ToolExecutor`로 실행
3) 결과를 `ContextItem`(Evidence 규격)으로 변환
4) `PromptRenderer`로 “최종 messages”를 만든다
5) `call_llm(messages=...)`로 호출한다

즉, 기존의 `_call_llm_with_tool_context()`는 유지하되, 내부에서 **프롬프트를 문자열로 만들기보다 messages 기반 렌더링**으로 전환하는 게 목표야.

#### 4.2 Evidence(ContextItem) 규격 강화
`ContextItem`의 meta에 아래를 넣는 방향으로 정리해.
- `type`: `tool` | `retrieval` | `memory`
- `title`: 예: `서울 날씨(AccuWeather)`
- `provenance`: `tool_name`, `fetched_at`, `ttl_s`, `endpoint`
- `confidence`: `high|medium|low`
- `privacy`: `pii_masked: true|false`

LLM 프롬프트 규칙:
- Evidence에 없는 내용은 **추측하지 말기**
- 충돌하면(서로 다른 툴 결과) `fetched_at` 최신 우선 + 충돌을 명시

### 5) API 추가(프롬프트 싸서 출력 테스트)

#### 5.1 Prompt Render API (디버깅/테스트용)
- `POST /api/prompts/render`
  - 입력: `pack_id`, `variables`, `query`, `chat_history`, `contexts`
  - 출력: `RenderedPrompt`(최종 messages + 해시)

#### 5.2 Prompt Packs 목록/조회
- `GET /api/prompts/packs`
  - 등록된 pack 목록
- `GET /api/prompts/packs/{pack_id}`
  - pack 상세(템플릿/스키마)

#### 5.3 Query API에 pack_id 연결
- `POST /api/query`에 `pack_id`(옵션) 추가
  - 없으면 `default` 사용

### 6) OFFLINE/ONLINE 모드(폐쇄망 기본값)

환경변수로 모드 고정:
- `TERRARIUM_MODE=OFFLINE|ONLINE`

정책:
- OFFLINE: 외부 크롤링/외부 API 금지
  - `weather`는 “캐시/비활성” 중 하나로 동작(정책 선택)
- ONLINE: allowlist에 등록된 도메인만 허용

### 7) 테스트 시나리오(최소)

#### 7.1 Prompt render 확인
- `pack_id=default`로 `/api/prompts/render` 호출 → messages 배열 확인
- 같은 입력이면 `prompt_hash`가 동일해야 함

#### 7.2 Tool + PromptPack 결합
- “오늘 서울 날씨 알려줘”
  - tool: weather
  - pack: `weather_assistant`
  - evidence_summary에 날씨 툴 결과가 들어가고, 답변이 근거 기반으로 나오는지 확인

#### 7.3 Debug pack
- `pack_id=dev_debug`
  - 답변 대신 “내가 본 evidence, 적용 변수, 선택 툴”을 짧게 요약해서 출력하게 만들어
  - 이 팩은 개발 때만 쓰고 운영에서는 비활성(allowlist)

### 8) 완료 기준(DoD)
- `pipeline.py`의 툴 if/elif가 사라지고 `ToolRouter/ToolExecutor`로 동작
- `/api/prompts/render`로 최종 messages를 확인 가능
- `/api/query`에서 `pack_id`를 바꾸면 답변 스타일/규칙이 달라짐
- OFFLINE 모드에서 외부 호출이 차단되고, trace에 정책이 남음

---

## API 엔드포인트

### 1. `GET /health`
**설명**: 헬스체크 엔드포인트

**응답**:
```json
{
  "status": "ok"
}
```

---

### 2. `POST /api/query`
**설명**: RAG 쿼리 실행

**요청 본문** (`QueryRequest`):
```json
{
  "query": "오늘 날씨 알려줘",
  "mode": "ephemeral",
  "profile": "default",
  "raw_text": "선택사항: 문서 텍스트",
  "chat_history": [
    {
      "role": "user",
      "content": "이전 질문"
    },
    {
      "role": "assistant",
      "content": "이전 답변"
    }
  ]
}
```

**응답 본문** (`QueryResponse`):
```json
{
  "trace_id": "uuid",
  "answer": "서울의 현재 날씨는 2도이고, 비입니다...",
  "contexts": [
    {
      "chunk_id": "weather_1",
      "document_id": "weather_tool",
      "text": "서울의 현재 날씨는 2도이고, 비입니다",
      "score": 1.0,
      "meta": {
        "source": "accuweather",
        "location": "seoul"
      }
    }
  ],
  "retrieval_trace": {
    "query_expansions": ["오늘 날씨 알려줘", "오늘 날씨"],
    "bm25_results": [],
    "vector_results": [],
    "reranked_results": []
  },
  "llm_trace": {
    "model": "qwen3:4b",
    "prompt": "...",
    "output": "...",
    "latency_ms": 1234,
    "input_tokens": null,
    "output_tokens": null
  },
  "meta": {
    "mode": "ephemeral",
    "profile": "default",
    "timestamp": "2024-12-23T11:30:00Z",
    "status": "success",
    "tool": "weather"
  }
}
```

---

### 3. `POST /api/prompts/render`
**설명**: 선택한 Prompt Pack 기준으로 “최종 LLM messages”를 렌더링해서 반환 (디버깅/비교/테스트용)

**요청 본문** (예시):
```json
{
  "pack_id": "default",
  "variables": {
    "tone": "concise",
    "language": "ko"
  },
  "query": "오늘 서울 날씨 알려줘",
  "chat_history": [],
  "contexts": []
}
```

**응답 본문** (예시):
```json
{
  "pack_id": "default",
  "prompt_hash": "...",
  "variables_used": {
    "tone": "concise",
    "language": "ko"
  },
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "..."}
  ]
}
```

---

### 4. `GET /api/prompts/packs`
**설명**: 사용 가능한 Prompt Pack 목록 반환

---

### 5. `GET /api/prompts/packs/{pack_id}`
**설명**: 특정 Prompt Pack의 템플릿/변수 스키마/정책 조회

---

## 개발 환경 설정

### 1. 가상환경 생성 및 활성화

```bash
python3 -m venv .venv
source .venv/bin/activate  # macOS/Linux
# 또는
.venv\Scripts\activate  # Windows
```

### 2. 의존성 설치

```bash
pip install -r requirements.txt
```

**주요 의존성**:
- `fastapi`: 웹 프레임워크
- `uvicorn`: ASGI 서버
- `pydantic`: 데이터 검증
- `httpx`: HTTP 클라이언트
- `beautifulsoup4`, `lxml`: 웹 스크래핑
- `pytz`: 시간대 처리

### 3. 환경변수 설정 (선택사항)

`.env` 파일 생성:
```bash
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=qwen3:4b
```

### 4. Ollama 서버 실행

```bash
# Ollama가 설치되어 있어야 함
ollama serve
```

### 5. 개발 서버 실행

```bash
uvicorn app.main:app --reload --port 8080
```

### 6. 웹 인터페이스 접속

브라우저에서 `http://localhost:8080/static/index.html` 접속

---

## 향후 계획

### v1 (향후 구현)
- [ ] 문서 파싱 (PDF, 엑셀 등)
- [ ] 임베딩 (BGE-m3-ko)
- [ ] 벡터 검색 (Faiss)
- [ ] BM25 검색
- [ ] 리랭킹 (bge-reranker-v2-m3-ko)
- [ ] 코퍼스 모드 (사전 색인된 문서 검색)

### 툴 확장
- [ ] 계산기 툴
- [ ] 단위 변환 툴
- [ ] 웹 검색 툴

---

## 참고 문서

- [프로젝트 구조](./chatGPT/terrarium_project_structure.md)
- [Jido와의 연동](./chatGPT/jido_terrarium_overview.md)
- [API 스펙](./QUERY_API.md)
- [Cursor 가이드](./CURSOR_GUIDE.md)

---

**마지막 업데이트**: 2024년 12월 23일
