# Terrarium - RAG Engine

**Terrarium**은 RAG에 필요한 모든 컴포넌트를 하나의 엔진에 담은 독립 RAG 백엔드 서비스입니다.
문서 인덱싱, 벡터 검색, LLM 호출, 툴 시스템까지 HTTP API 하나로 제공합니다.

## 핵심 기능

### 1. RAG 파이프라인
- **문서 인덱싱**: JSONL 파일 → 단락 인식 청킹 → BGE-m3 임베딩 → pgvector 저장
- **벡터 검색**: pgvector 코사인 유사도 검색 (HNSW 인덱스)
- **쿼리 확장**: 규칙 기반 동의어 치환, 표현 정규화
- **컨텍스트 구성**: 검색 결과 → 문자 수 기반 컨텍스트 선별 → LLM 프롬프트 조립
- **LLM 호출**: Ollama를 통한 로컬 LLM 추론 (멀티턴 대화 지원)
- **Ephemeral 모드**: 인덱싱 없이 raw_text를 직접 전달하는 1회성 RAG

### 2. 툴 시스템 (MCP 스타일)
- **날씨 툴**: AccuWeather 웹 스크래핑으로 서울 날씨 정보 제공
- **시간 툴**: 현재 날짜/시간/요일 정보 (서울 시간대)
- 툴 감지 → 실행 → 결과를 LLM 컨텍스트로 주입 → 자연어 답변 생성
- ToolRegistry/ToolRouter/ToolExecutor 확장 인프라 구축 완료

### 3. 프롬프트 팩 시스템 (GPTs 스타일)
- YAML 기반 프롬프트 템플릿 관리 (system/developer/user 분리)
- 변수 바인딩 + 컨텍스트 포매팅 → 최종 messages 배열 렌더링
- 프롬프트 해시로 동일성 비교 가능
- 기본 팩: `default`, `weather_assistant`, `dev_debug`

### 4. 추적 및 트레이싱
- **retrieval_trace**: 쿼리 확장, 벡터 검색 결과, 리랭킹 결과
- **llm_trace**: 모델, 프롬프트, 응답, 지연시간
- **retrieval_logs**: DB에 검색 이벤트 기록 (쿼리, 결과, 사용 툴)

### 5. 웹 채팅 UI
- Vanilla JS 채팅 인터페이스 (localStorage 영속)
- 메타 정보 표시 (모델, 모드, 프로파일, 툴)
- 대화 히스토리 관리 + JSON 내보내기/가져오기

## 기술 스택

| 영역 | 기술 | 비고 |
|------|------|------|
| Backend | FastAPI + Pydantic | 비동기, 자동 문서 생성 |
| LLM | Ollama | 로컬 추론 (qwen3:4b 기본) |
| Embedding | BGE-m3 via Ollama | 1024차원 벡터 |
| Vector DB | PostgreSQL + pgvector | HNSW 인덱스, 코사인 거리 |
| HTTP Client | httpx | 비동기 요청 |
| Web Scraping | BeautifulSoup + lxml | 날씨 툴 |
| Frontend | HTML/CSS/JS | 정적 파일 서빙 |
| Container | Docker Compose | pgvector + app |

## 프로젝트 구조

```
terrarium/
├── app/
│   ├── main.py                # FastAPI 엔트리포인트
│   ├── api/
│   │   ├── health.py          # GET /health
│   │   ├── routes/
│   │   │   ├── query.py       # POST /api/query
│   │   │   └── index.py       # POST /api/index, GET /api/index/status
│   │   └── schemas/
│   │       ├── query.py       # QueryRequest/Response, ContextItem, Traces
│   │       └── index.py       # IndexRequest/Response
│   ├── llm/
│   │   └── client.py          # Ollama chat + embedding 호출
│   ├── rag/
│   │   ├── pipeline.py        # RAG 파이프라인 (run_rag)
│   │   ├── retriever.py       # pgvector 벡터 검색
│   │   └── index/             # 인덱싱 파이프라인
│   │       ├── loaders.py     #   JSONL 로더
│   │       ├── chunker.py     #   단락 인식 청킹
│   │       ├── embedder.py    #   BGE-m3 임베딩
│   │       ├── keywords.py    #   키워드 추출
│   │       └── store_pg.py    #   pgvector 저장
│   ├── tools/
│   │   ├── weather.py         # 날씨 툴 (AccuWeather)
│   │   ├── time.py            # 시간 툴
│   │   ├── registry.py        # ToolSpec/ToolRegistry
│   │   ├── router.py          # ToolRouter (쿼리 → 툴 매칭)
│   │   ├── executor.py        # ToolExecutor (실행 + 타임아웃)
│   │   ├── bootstrap.py       # 툴 등록
│   │   └── adapters/          # 실행 어댑터 (local/mcp/http)
│   ├── prompts/
│   │   ├── schema.py          # PromptPack/RenderedPrompt
│   │   ├── registry.py        # 팩 로드/조회
│   │   ├── renderer.py        # 템플릿 렌더링
│   │   └── packs/             # YAML 프롬프트 템플릿
│   ├── store/
│   │   └── pgvector_store.py  # PgVectorStore (upsert, search, log)
│   └── db/
│       ├── connection.py      # DB 연결 URL 구성
│       └── schema.sql         # DDL (documents, chunks, retrieval_logs)
├── static/
│   └── index.html             # 웹 채팅 UI
├── docker/
│   ├── Dockerfile             # Python 3.11 + uvicorn
│   └── docker-compose.pgvector.yml  # pgvector + app
├── docs/                      # 문서
├── requirements.txt
└── env.example
```

## 빠른 시작

### 사전 요구사항

- Python 3.11+
- Ollama (로컬 LLM 서버)
- PostgreSQL 15+ with pgvector 확장 (또는 Docker)

### 1. Ollama 설치 및 모델 다운로드

```bash
# Ollama 설치 후
ollama serve
ollama pull qwen3:4b      # LLM 모델
ollama pull bge-m3         # 임베딩 모델
```

### 2. Docker Compose로 실행 (권장)

```bash
# pgvector DB + Terrarium 앱 함께 실행
docker compose -f docker/docker-compose.pgvector.yml up -d

# 접속
open http://localhost:9000/static/index.html
```

> 호스트의 Ollama를 사용합니다 (컨테이너 → host.docker.internal:11434)

### 3. 로컬 개발 서버

```bash
# 가상환경
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 환경변수
cp env.example .env
# .env에서 DB_* 값 확인

# 서버 실행 (포트 9000)
uvicorn app.main:app --reload --port 9000
```

### 접속 정보

| 서비스 | URL |
|--------|-----|
| Chat UI | http://localhost:9000/static/index.html |
| API | http://localhost:9000 |
| Swagger UI | http://localhost:9000/docs |
| Health | http://localhost:9000/health |

## API

### POST /api/query - RAG 쿼리

```json
// 요청
{
  "query": "계약 해지 절차를 알려줘",
  "mode": "corpus",
  "profile": "default",
  "chat_history": []
}

// 응답
{
  "trace_id": "uuid",
  "answer": "계약 해지 절차는 다음과 같습니다...",
  "contexts": [{ "chunk_id": "...", "text": "...", "score": 0.85 }],
  "retrieval_trace": { "query_expansions": [...], "vector_results": [...] },
  "llm_trace": { "model": "qwen3:4b", "latency_ms": 1234 },
  "meta": { "mode": "corpus", "status": "success", "tool": null }
}
```

### POST /api/index - 문서 인덱싱

```json
// 요청
{ "path": "data/documents/corpus.jsonl", "rebuild": false }

// 응답
{ "ok": true, "docs": 45, "chunks": 312, "elapsed_ms": 8500 }
```

### GET /api/index/status - 인덱싱 상태

```json
{ "document_count": 45, "chunk_count": 312, "latest_chunk_at": "2026-03-05T00:00:00Z" }
```

### GET /health - 헬스체크

```json
{ "status": "ok" }
```

자세한 API 스펙은 [docs/QUERY_API.md](docs/QUERY_API.md) 참조.

## 환경 변수

| 변수 | 설명 | 기본값 |
|------|------|--------|
| `OLLAMA_HOST` | Ollama 서버 주소 | `http://localhost:11434` |
| `OLLAMA_MODEL` | LLM 모델 | `qwen3:4b` |
| `OLLAMA_EMBED_MODEL` | 임베딩 모델 | `bge-m3` |
| `DB_HOST` | PostgreSQL 호스트 | `localhost` |
| `DB_PORT` | PostgreSQL 포트 | `5432` |
| `DB_NAME` / `DB_USER` / `DB_PASSWORD` | DB 접속 정보 | `terrarium` |
| `RAG_TOP_K` | 검색 후보 수 | `6` |
| `RAG_MAX_CONTEXT_CHARS` | 최대 컨텍스트 문자 수 | `6000` |

## 데이터베이스 스키마

### documents
문서 메타데이터 (doc_id, title, filepath, fmt)

### chunks
청크 데이터 + 임베딩 벡터 (1024차원)
- 구조 메타: page_no, chapter_title, section_title, article_title
- 탐색: prev_chunk_id, next_chunk_id
- 검색: keywords, embedding (HNSW 인덱스)

### retrieval_logs
검색 이벤트 기록 (query, results, latency_ms, used_tool)

## 로드맵

### 구현 완료
- [x] RAG 파이프라인 (쿼리 확장 → 벡터 검색 → LLM 호출)
- [x] 문서 인덱싱 (JSONL → 청킹 → 임베딩 → pgvector)
- [x] Ollama 연동 (chat + embedding)
- [x] 툴 시스템 (날씨, 시간)
- [x] 프롬프트 팩 시스템 (YAML 기반)
- [x] 웹 채팅 UI
- [x] Docker Compose (pgvector + app)
- [x] 추적/트레이싱 (retrieval_trace, llm_trace, retrieval_logs)

### 진행 예정
- [ ] BM25 검색 (하이브리드 검색)
- [ ] 리랭킹 (bge-reranker-v2-m3-ko)
- [ ] 코퍼스 관리 API
- [ ] 테스트 코드
- [ ] MCP/HTTP 툴 어댑터 구현
- [ ] OFFLINE 모드 (외부 크롤링 차단)

## 관련 프로젝트

- **[Jido](https://github.com/jk7013/jido)**: 프롬프트 운영 플랫폼. Terrarium을 HTTP API로 호출하여 RAG 실행 결과를 로깅/평가/비교합니다.

## 라이선스

이 프로젝트는 개인 포트폴리오/학습 목적으로 개발되었습니다.
