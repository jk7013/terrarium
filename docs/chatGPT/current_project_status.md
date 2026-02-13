# 🌱 Terrarium 현재 프로젝트 상태 (ChatGPT용)

> 이 문서는 Terrarium 프로젝트의 **현재 구현 상태**와 각 파일의 역할을 ChatGPT에게 설명하기 위한 문서입니다.  
> 프로젝트 구조를 이해하고 코드를 작성/수정할 때 참고하세요.

---

## 📋 프로젝트 개요

**Terrarium**은 독립적인 RAG(Retrieval-Augmented Generation) 백엔드 서비스입니다.

- **목적**: 문서 파싱, 임베딩, 검색, 리랭킹, LLM 호출을 포함한 완전한 RAG 파이프라인 제공
- **기술 스택**: FastAPI, Pydantic, SQLAlchemy (향후 추가 예정)
- **현재 버전**: v0 (API 구조 및 더미 구현 단계)

---

## 📁 프로젝트 디렉토리 구조

```
terrarium/
├── app/                          # 메인 애플리케이션 코드
│   ├── __init__.py
│   ├── main.py                   # FastAPI 엔트리포인트
│   │
│   ├── api/                      # HTTP API 엔드포인트
│   │   ├── __init__.py
│   │   ├── health.py             # GET /health 엔드포인트
│   │   ├── routes/               # API 라우터들
│   │   │   └── query.py          # POST /api/query 엔드포인트
│   │   └── schemas/              # Pydantic 모델 정의
│   │       └── query.py          # QueryRequest, QueryResponse 등
│   │
│   ├── rag/                      # RAG 파이프라인 로직 (현재 빈 디렉토리)
│   │   └── __init__.py
│   │
│   ├── llm/                      # LLM 클라이언트 (현재 빈 디렉토리)
│   │   └── __init__.py
│   │
│   ├── store/                    # 데이터 저장 계층 (현재 빈 디렉토리)
│   │   └── __init__.py
│   │
│   └── core/                     # 공통 설정/로깅 (현재 빈 디렉토리)
│       └── __init__.py
│
├── docs/                         # 문서
│   ├── chatGPT/                  # ChatGPT용 문서
│   │   ├── current_project_status.md  # 이 문서
│   │   ├── terrarium_project_structure.md
│   │   └── jido_terrarium_overview.md
│   ├── concepts/                 # 개념 정리
│   │   └── CONCEPTS.md           # FastAPI, Pydantic, CORS 등 개념 설명
│   ├── cursor/                   # Cursor 사용 가이드
│   │   └── repository_separation.md
│   ├── CURSOR_GUIDE.md           # Cursor 사용 규칙
│   └── QUERY_API.md              # /query API 스펙
│
├── data/                         # 샘플 데이터
│   ├── eval_sets/
│   └── samples/
│
├── docker/                       # Docker 관련
│   └── Dockerfile
│
├── scripts/                      # 유틸리티 스크립트 (현재 빈 디렉토리)
├── tests/                        # 테스트 (현재 빈 디렉토리)
│
├── requirements.txt              # Python 의존성
├── env.example                   # 환경변수 예시
└── README.md                     # 프로젝트 소개
```

---

## 📄 주요 파일 상세 설명

### 1. `app/main.py` - FastAPI 애플리케이션 엔트리포인트

**역할**: FastAPI 앱 인스턴스 생성 및 전역 설정

**현재 구현 상태**:
- FastAPI 앱 생성 (`title`, `description`, `version` 설정)
- CORS 미들웨어 설정 (개발용: 모든 출처 허용)
- 라우터 등록:
  - `health.router` → `/health`
  - `query.router` → `/api/query` (prefix 포함)

**주의사항**:
- 현재 `query` import가 누락되어 있음 (25번 줄에서 `query.router` 사용하지만 import 없음)
- 수정 필요: `from app.api.routes import query` 추가 필요

**코드 구조**:
```python
app = FastAPI(...)
app.add_middleware(CORSMiddleware, ...)
app.include_router(health.router)
app.include_router(query.router, prefix="/api")
```

---

### 2. `app/api/health.py` - 헬스체크 API

**역할**: 서버 상태 확인 엔드포인트

**엔드포인트**: `GET /health`

**현재 구현**:
- 간단한 `{"status": "ok"}` 응답 반환
- 향후 확장 가능: DB 연결, 벡터 스토어, LLM 서버 상태 체크

**코드**:
```python
@router.get("/health")
async def health_check():
    return {"status": "ok"}
```

---

### 3. `app/api/routes/query.py` - RAG 쿼리 API

**역할**: RAG 파이프라인 실행 엔드포인트

**엔드포인트**: `POST /api/query`

**현재 구현 상태**:
- ✅ Pydantic 모델 기반 요청/응답 처리
- ✅ 더미 응답 생성 (실제 RAG 파이프라인 미구현)
- ⚠️ TODO: `run_rag(request)` 호출로 변경 예정

**요청 처리 흐름**:
1. `QueryRequest` 모델로 요청 검증
2. 더미 데이터 생성:
   - `ContextItem`: `raw_text`를 그대로 사용
   - `RetrievalTrace`: 빈 리스트들
   - `LLMTrace`: echo 응답 (`"echo: {query}"`)
   - `QueryMeta`: 요청 정보 기반
3. `QueryResponse` 객체 생성 및 반환

**향후 변경 예정**:
```python
# 현재 (더미)
response = QueryResponse(...)  # 하드코딩된 더미 데이터

# 향후 (실제 RAG)
from app.rag.pipeline import run_rag
response = run_rag(request)
```

---

### 4. `app/api/schemas/query.py` - Pydantic 모델 정의

**역할**: `/api/query` 엔드포인트의 요청/응답 스키마 정의

**정의된 모델들**:

#### 요청 모델
- **`QueryOptions`**: 검색 옵션 (`top_k`, `final_contexts`)
- **`QueryRequest`**: 전체 요청 본문
  - `mode`: `"ephemeral"` | `"corpus"` (v0는 ephemeral만)
  - `query`: 사용자 질문 (필수)
  - `raw_text`: 원문 텍스트 (ephemeral 모드용, 선택)
  - `profile`: RAG 프로파일 이름
  - `options`: `QueryOptions` 객체

#### 응답 모델
- **`ContextItem`**: 단일 컨텍스트(청크) 정보
- **`RetrievalTrace`**: 검색/리랭킹 과정 요약
- **`LLMTrace`**: LLM 호출 정보
- **`QueryMeta`**: 공통 메타데이터
- **`QueryResponse`**: 전체 응답 본문

**특징**:
- 모든 필드에 타입 힌트와 기본값 설정
- `Field`를 사용한 설명 추가 (OpenAPI 문서 자동 생성)
- `Literal` 타입으로 `mode` 제한

---

## 🔄 현재 구현 상태 요약

### ✅ 완료된 부분

1. **FastAPI 기본 구조**
   - 앱 생성, CORS 설정, 라우터 등록

2. **헬스체크 API**
   - `GET /health` 구현 완료

3. **Query API 구조**
   - Pydantic 모델 정의 완료
   - 엔드포인트 구현 완료 (더미 응답)

4. **프로젝트 구조**
   - 디렉토리 구조 정리
   - 모듈 분리 (`routes/`, `schemas/`)

### ⚠️ 수정 필요

1. **`app/main.py`**
   - `query` import 누락: `from app.api.routes import query` 추가 필요

### 🚧 미구현 부분 (향후 작업)

1. **RAG 파이프라인** (`app/rag/`)
   - `pipeline.py`: `run_rag()` 함수
   - `chunking.py`: 문서 청킹
   - `embedding.py`: 임베딩 생성
   - `retriever.py`: 검색 로직
   - `reranker.py`: 리랭킹

2. **LLM 클라이언트** (`app/llm/`)
   - `client.py`: LLM 호출 로직

3. **데이터 저장** (`app/store/`)
   - `sqlite.py`: 메타데이터 저장
   - `vector.py`: 벡터 스토어 래퍼

4. **설정 관리** (`app/core/`)
   - `config.py`: 환경변수/설정 관리
   - `logging.py`: 로깅 설정

---

## 🎯 다음 단계 작업 가이드

### 1단계: `main.py` 수정 (즉시 필요)

```python
# app/main.py에 추가
from app.api.routes import query
```

### 2단계: RAG 파이프라인 골격 구현

1. `app/rag/pipeline.py` 생성
2. `run_rag(request: QueryRequest) -> QueryResponse` 함수 시그니처 작성
3. 현재 `query.py`의 더미 로직을 `run_rag()`로 이동
4. `query.py`에서 `run_rag()` 호출하도록 변경

### 3단계: 각 RAG 컴포넌트 구현

- 청킹 → 임베딩 → 검색 → 리랭킹 → LLM 호출 순서로 구현

---

## 📚 참고 문서

- **API 스펙**: `docs/QUERY_API.md`
- **개념 정리**: `docs/concepts/CONCEPTS.md`
- **Cursor 사용법**: `docs/CURSOR_GUIDE.md`
- **프로젝트 구조 설계**: `docs/chatGPT/terrarium_project_structure.md`

---

## 💡 ChatGPT에게 요청할 때 사용할 프롬프트 예시

### 예시 1: main.py 수정
```
app/main.py의 25번 줄에서 query.router를 사용하고 있지만, 
query import가 누락되어 있습니다. 
from app.api.routes import query를 추가해주세요.
```

### 예시 2: RAG 파이프라인 함수 생성
```
app/rag/pipeline.py 파일을 생성하고, 
run_rag(request: QueryRequest) -> QueryResponse 함수를 만들어주세요.
현재 app/api/routes/query.py의 더미 로직을 참고해서 
동일한 구조의 응답을 반환하도록 구현해주세요.
```

### 예시 3: Pydantic 모델 이해
```
app/api/schemas/query.py의 QueryRequest와 QueryResponse 모델을 
기반으로 run_rag 함수의 시그니처를 작성해주세요.
```

---

**마지막 업데이트**: 2025-01-27  
**프로젝트 버전**: v0.1.0

