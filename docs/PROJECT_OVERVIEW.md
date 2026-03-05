# Terrarium 프로젝트 전체 개요

> 최종 수정일: 2026-03-05
> 이 문서는 프로젝트 구조와 구현 상태를 파악하기 위한 기술 문서입니다.

---

## 한 줄 정의

**Terrarium**은 문서 인덱싱, 벡터 검색, LLM 호출, 툴 시스템을 하나의 HTTP API로 제공하는 독립 RAG 백엔드 서비스입니다.

---

## 시스템 아키텍처

```
┌─────────────────┐
│  Chat UI        │  static/index.html (Vanilla JS)
└────────┬────────┘
         │ HTTP
         ▼
┌─────────────────┐
│  FastAPI Server  │  app/main.py
├─────────────────┤
│ /api/query      │──→ RAG Pipeline (app/rag/pipeline.py)
│ /api/index      │──→ Indexing Pipeline (app/rag/index/)
│ /api/prompts/*  │──→ Prompt Pack System (app/prompts/)
│ /health         │──→ Health Check
└────────┬────────┘
         │
    ┌────┼────────────┐
    ▼    ▼            ▼
┌──────┐┌──────────┐┌──────────┐
│Tools ││ LLM      ││ pgvector │
│      ││ (Ollama) ││ Store    │
└──────┘└──────────┘└──────────┘
 weather  chat+embed   search+
 time                  upsert
```

---

## 모듈별 구현 상태

### Backend Core

| 모듈 | 파일 | 상태 | 설명 |
|------|------|------|------|
| API 엔트리 | `app/main.py` | ✅ | FastAPI 앱, CORS, 라우터 등록 |
| Health | `app/api/health.py` | ✅ | `GET /health` |
| Query API | `app/api/routes/query.py` | ✅ | `POST /api/query` |
| Index API | `app/api/routes/index.py` | ✅ | `POST /api/index`, `GET /api/index/status` |
| Query Schema | `app/api/schemas/query.py` | ✅ | Request/Response/Trace Pydantic 모델 |
| Index Schema | `app/api/schemas/index.py` | ✅ | Index Request/Response 모델 |

### RAG Pipeline

| 모듈 | 파일 | 상태 | 설명 |
|------|------|------|------|
| 파이프라인 | `app/rag/pipeline.py` | ✅ | run_rag() - 툴 감지, 쿼리 확장, 검색, LLM 호출 |
| 벡터 검색 | `app/rag/retriever.py` | ✅ | pgvector 코사인 유사도 검색 |
| JSONL 로더 | `app/rag/index/loaders.py` | ✅ | JSONL 파싱 + doc_id 안정화 |
| 청킹 | `app/rag/index/chunker.py` | ✅ | 단락 인식 청킹 (900자/180자 오버랩) |
| 임베딩 | `app/rag/index/embedder.py` | ✅ | BGE-m3 1024차원 임베딩 |
| 키워드 | `app/rag/index/keywords.py` | ✅ | 한국어/영어 키워드 추출 |
| DB 저장 | `app/rag/index/store_pg.py` | ✅ | pgvector upsert (문서 + 청크) |

### LLM

| 모듈 | 파일 | 상태 | 설명 |
|------|------|------|------|
| LLM Client | `app/llm/client.py` | ✅ | Ollama chat + embedding API 호출 |

### 툴 시스템

| 모듈 | 파일 | 상태 | 설명 |
|------|------|------|------|
| 날씨 툴 | `app/tools/weather.py` | ✅ | AccuWeather 스크래핑, 쿼리 감지 |
| 시간 툴 | `app/tools/time.py` | ✅ | 서울 시간대 현재 시간 |
| Registry | `app/tools/registry.py` | ✅ | ToolSpec/ToolCall/ToolResult/ToolRegistry |
| Router | `app/tools/router.py` | ✅ | 쿼리 → ToolCall 매칭 (인프라만) |
| Executor | `app/tools/executor.py` | ✅ | 어댑터 기반 실행 + 타임아웃 (인프라만) |
| Bootstrap | `app/tools/bootstrap.py` | ✅ | 툴 등록 |
| Local Adapter | `app/tools/adapters/local_adapter.py` | ✅ | 파이썬 함수 직접 호출 |
| MCP Adapter | `app/tools/adapters/mcp_adapter.py` | ⬜ | 스텁 |
| HTTP Adapter | `app/tools/adapters/http_adapter.py` | ⬜ | 스텁 |

> 현재 파이프라인에서는 직접 if/elif로 툴을 호출합니다. Router/Executor 통합은 v2 예정.

### 프롬프트 팩

| 모듈 | 파일 | 상태 | 설명 |
|------|------|------|------|
| Schema | `app/prompts/schema.py` | ✅ | PromptPack/RenderedPrompt |
| Registry | `app/prompts/registry.py` | ✅ | YAML 로드/조회 |
| Renderer | `app/prompts/renderer.py` | ✅ | 템플릿 렌더링 + 해시 |
| default.yaml | `app/prompts/packs/` | ✅ | 기본 팩 |
| weather_assistant.yaml | `app/prompts/packs/` | ✅ | 날씨 답변 강화 |
| dev_debug.yaml | `app/prompts/packs/` | ✅ | 디버깅용 |

### 데이터베이스

| 모듈 | 파일 | 상태 | 설명 |
|------|------|------|------|
| DB 연결 | `app/db/connection.py` | ✅ | DATABASE_URL 구성 |
| DDL | `app/db/schema.sql` | ✅ | documents, chunks (pgvector), retrieval_logs |
| Store | `app/store/pgvector_store.py` | ✅ | PgVectorStore 클래스 (upsert, search, log) |

### 기타

| 항목 | 상태 | 설명 |
|------|------|------|
| Chat UI | ✅ | `static/index.html` (Vanilla JS) |
| Dockerfile | ✅ | Python 3.11, uvicorn, 포트 9000 |
| docker-compose | ✅ | pgvector + app |
| 테스트 | ⬜ | 미작성 |

---

## 미구현 (v2 예정)

| 기능 | 설명 |
|------|------|
| BM25 검색 | 하이브리드 검색 (벡터 + 키워드) |
| 리랭킹 | bge-reranker-v2-m3-ko 교차 인코더 |
| MCP/HTTP 어댑터 | 외부 툴 서버 연동 |
| Pipeline 리팩터링 | if/elif → ToolRouter/ToolExecutor 통합 |
| OFFLINE 모드 | 외부 크롤링 차단 정책 |
| 코퍼스 관리 API | 코퍼스 CRUD |
| 테스트 코드 | pytest 테스트 |
