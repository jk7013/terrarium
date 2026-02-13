# Terrarium CONCEPTS

> Terrarium / Jido 개발하면서 헷갈리기 쉬운 개념들을 정리한 메모.

---

## 1. FastAPI와 Terrarium의 역할

### FastAPI

- 한 줄 정의: **HTTP API 서버를 만드는 프레임워크**
- 하는 일:
  - `/health`, `/query`, `/corpus` 같은 **엔드포인트(주소)** 를 정의
  - 브라우저/다른 서버에서 들어온 HTTP 요청을 받아서, **파이썬 함수**를 실행하고 JSON 응답을 돌려줌
- Terrarium에서 역할:
  - **“RAG 엔진의 입구(문)”**
  - 나중에 Jido, 웹 프론트, 다른 시스템이 모두 FastAPI를 통해 Terrarium에 접근

### Terrarium 내부

- FastAPI는 그냥 “문/복도”일 뿐이고,  
  실제 RAG 로직은 내부 모듈에서 수행:
  - `rag/chunking.py` : 청킹
  - `rag/embedding.py`: 임베딩
  - `rag/retriever.py`: 검색
  - `rag/reranker.py`: 리랭킹
  - `rag/pipeline.py`: 전체 파이프라인 orchestration
  - `llm/client.py`: LLM 호출

---

## 2. Pydantic이란?

### Pydantic 한 줄 정의

> **Pydantic = "JSON 데이터를 파이썬 클래스로 변환하고, 타입과 형식을 자동으로 검증해주는 라이브러리"**

### 왜 필요한가?

- FastAPI 엔드포인트에서 클라이언트가 보낸 JSON 요청을 받을 때:
  - 예: `POST /query`에 `{"mode": "ephemeral", "query": "질문", ...}` 같은 JSON이 들어옴
  - 이 JSON을 그냥 `dict`로 받으면:
    - 필수 필드가 빠졌는지 확인하기 어려움
    - 타입이 맞는지(예: `top_k`가 숫자인지) 확인하기 어려움
    - 잘못된 값이 들어와도 나중에야 에러가 발생
- **Pydantic 모델**을 사용하면:
  - 요청 JSON을 파이썬 클래스 객체로 자동 변환
  - 필수 필드 체크, 타입 검증을 자동으로 수행
  - 잘못된 요청이면 **요청 단계에서 바로 에러 반환** (422 Unprocessable Entity)

### 기본 사용법

```python
from pydantic import BaseModel

class QueryRequest(BaseModel):
    mode: str                    # 필수 필드
    query: str                   # 필수 필드
    raw_text: str | None = None  # 선택 필드 (None 가능)
    profile: str = "default"     # 기본값 있음
    options: dict = {}           # 기본값 있음

# 사용 예시
request_data = {
    "mode": "ephemeral",
    "query": "질문 텍스트"
}
request = QueryRequest(**request_data)  # 자동 검증 + 변환
print(request.query)  # "질문 텍스트"
```

### 딕셔너리 언패킹 (`**` 연산자)이란?

위 예시에서 `QueryRequest(**request_data)`의 `**`는 **딕셔너리 언패킹 연산자**입니다.

#### 한 줄 정의

> **`**` = "딕셔너리의 키-값 쌍을 키워드 인자로 풀어서 함수/클래스에 전달하는 문법"**

#### 동작 원리

```python
# 딕셔너리
request_data = {
    "mode": "ephemeral",
    "query": "질문 텍스트",
    "profile": "default"
}

# ** 없이 하면 (에러 발생)
# QueryRequest(request_data)  # 딕셔너리 전체를 하나의 인자로 전달 → 에러!

# ** 를 사용하면
QueryRequest(**request_data)
# 이것은 아래와 완전히 같습니다:
QueryRequest(mode="ephemeral", query="질문 텍스트", profile="default")
```

#### 왜 유용한가?

- API에서 받은 JSON 딕셔너리를 그대로 모델로 변환할 수 있습니다.
- 딕셔너리를 직접 전달하는 것보다 간단합니다.

```python
# API에서 받은 JSON (dict 형태)
json_data = {"mode": "ephemeral", "query": "질문"}

# ** 없이는 이렇게 해야 함 (번거로움)
request = QueryRequest(mode=json_data["mode"], query=json_data["query"])

# ** 있으면 이렇게 간단하게!
request = QueryRequest(**json_data)
```

#### 참고: `*` 연산자와의 차이

- `*` (단일 언패킹): 리스트/튜플을 위치 인자로 풀어줌
  - 예: `func(*[1, 2, 3])` → `func(1, 2, 3)`
- `**` (딕셔너리 언패킹): 딕셔너리를 키워드 인자로 풀어줌
  - 예: `func(**{"a": 1, "b": 2})` → `func(a=1, b=2)`

### FastAPI와의 연동

- FastAPI는 **함수 파라미터에 Pydantic 모델을 넣으면**:
  - 요청 본문(JSON)을 자동으로 해당 모델로 변환
  - 검증 실패 시 자동으로 422 에러 반환
  - OpenAPI 문서(Swagger)도 자동 생성

```python
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class QueryRequest(BaseModel):
    mode: str
    query: str

@app.post("/query")
async def query(request: QueryRequest):  # 여기서 자동 검증!
    # request는 이미 QueryRequest 객체로 변환됨
    return {"answer": f"받은 질문: {request.query}"}
```

### Terrarium에서의 역할

- `/query` 엔드포인트:
  - `QueryRequest` 모델: 요청 JSON 검증
  - `QueryResponse` 모델: 응답 JSON 구조 정의
- `/corpus` 엔드포인트 (향후):
  - `CorpusCreateRequest`, `CorpusResponse` 등
- **장점**:
  - 잘못된 요청을 일찍 차단 (클라이언트가 바로 알 수 있음)
  - 타입 힌트로 IDE 자동완성 지원
  - API 문서 자동 생성

### ORM(SQLAlchemy)과의 차이

- **Pydantic**: API 요청/응답 데이터 검증 및 변환 (메모리에서만 사용)
- **SQLAlchemy**: DB 테이블과 파이썬 객체 매핑 (실제 DB 저장/조회)

예시:
- 클라이언트 → `QueryRequest`(Pydantic) → 내부 로직 → `Document`(SQLAlchemy) → DB 저장
- DB 조회 → `Document`(SQLAlchemy) → `QueryResponse`(Pydantic) → 클라이언트

---

## 3. CORS (Cross-Origin Resource Sharing)

### CORS 한 줄 정의

> **브라우저가 “이 도메인에서 저 도메인으로 요청을 보내도 되냐?”를 체크하는 규칙**

- 브라우저는 기본적으로 **Same-Origin Policy(동일 출처 정책)** 을 적용:
  - 예: `https://jido.app`에서 열린 페이지가  
    `http://localhost:9000`(Terrarium)으로 AJAX 요청을 보내면,  
    “다른 출처인데 이 서버가 허용했는지 확인”을 함.
- 서버가 응답 헤더에 다음과 같은 값을 보내면 허용:
  - `Access-Control-Allow-Origin: *`  
    → 어디서든 호출 가능 (개발용)
  - `Access-Control-Allow-Origin: https://jido.app`  
    → 특정 출처만 허용 (운영용)

### FastAPI에서 CORS 설정

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 개발 환경용: 모든 도메인 허용
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

- 지금 Terrarium에서는 개발 편의를 위해 `allow_origins=["*"]` 상태.
- 나중에 서비스 시에는 실제 프론트엔드 도메인만 허용하도록 변경 예정.

---

## 4. Health 라우터 (헬스체크)

### Health 체크 한 줄 정의

> **“Terrarium 서버가 살아 있는지, HTTP로 접근 가능한지 확인하는 엔드포인트”**

- 예: `GET /health` → `{"status": "ok"}`

### 현재 의미

- 클라이언트(브라우저, Jido 백엔드, 모니터링 시스템 등)가 주기적으로 `/health`를 호출:
  - 200 OK + `{"status": "ok"}` 이면 **Terrarium FastAPI 앱이 구동 중**이라고 판단.
- 지금은 **“클라이언트 ↔ Terrarium FastAPI 서버 연결”** 상태만 체크.

### 나중에 확장 방향 (아이디어)

- `/health` 안에서 다음까지 같이 점검할 수 있음:
  - DB 연결 (SQLite/SQLAlchemy)
  - 벡터 스토어 연결 상태
  - LLM 서버 ping
- 예시 응답:

```jsonc
{
  "status": "ok",
  "db": "ok",
  "vector_store": "ok",
  "llm": "ok"
}
```

---

## 5. ORM (Object-Relational Mapping) 이란?

### 한 줄 정의

> **ORM = “DB 테이블(행/열)을 파이썬 클래스/객체처럼 다루는 기술”**

- 원래 RDB는 SQL로 직접 쿼리:
  - `SELECT * FROM documents WHERE id = 1;`
- ORM 사용 시:
  - `Document` 같은 파이썬 클래스를 만들고,
  - `session.query(Document).filter(Document.id == 1).first()` 처럼 사용.

### SQLAlchemy

- **파이썬 ORM 라이브러리**.
- Terrarium에서 쓴다면:
  - `Corpus`, `Document`, `Chunk` 테이블을 모델 클래스로 정의
  - 코퍼스/문서/청크 메타데이터를 Python 코드로 쉽게 CRUD.

### 중요한 점

- ORM(SQLAlchemy)은 **검색엔진이 아니다**.
- 역할:
  - “문서/청크/코퍼스 메타데이터를 RDB에 깔끔하게 저장/조회”
- 검색엔진/벡터 스토어와는 다른 레이어.

회사 솔루션 기준으로 보면:

- 회사 엔진: 전체 텍스트 검색 + 벡터 검색 + 랭킹 엔진
- SQLAlchemy: 엔진이 아닌, **DB와 통신하는 도우미/모델링 도구**

---

## 6. 실제 데이터는 어디에 저장되는가? (3층 구조)

RAG에서 다루는 “데이터”를 3개 층으로 나눌 수 있다.

### 6.1 원본 문서/파일 (파일 시스템 / 스토리지)

- PDF, HWP, DOCX, TXT 등 원본 파일.
- 저장 위치 예:
  - 로컬 디스크: `/data/raw/...`
  - 클라우드 스토리지: S3 등
- Terrarium 입장:
  - 파일 경로나 ID를 메타데이터로 기억
  - 필요할 때 파서가 파일을 읽어서 텍스트 추출 + 청킹

### 6.2 메타데이터/청크 정보 (RDB + ORM)

- 예시 테이블:
  - `corpus`:
    - 코퍼스 ID, 이름, 설명, 생성일
  - `documents`:
    - 문서 ID, 코퍼스 ID, 원본 파일명, 경로, 타입, 페이지 수 ...
  - `chunks`:
    - chunk_id, document_id, 텍스트, 섹션명, 페이지, 순서 등

- 이 부분을 담당하는 게:
  - **ORM(SQLAlchemy) + DB(SQLite/PostgreSQL 등)**

- Terrarium 구조에서는:
  - `app/store/sqlite.py` 또는 유사 모듈에서 구현.

### 6.3 임베딩/색인 데이터 (벡터 스토어 / 검색엔진)

- 내용:
  - 각 청크의 임베딩 벡터
  - 벡터 ID → chunk_id 매핑 정보

- 구현 방식 예시:
  1. Qdrant/Milvus/PGVector 같은 **전용 벡터 DB**
  2. 로컬 개발에서는 Faiss + numpy array + pickle 파일
  3. 회사 솔루션 엔진을 외부 검색엔진처럼 호출하는 방식도 가능

- Terrarium 구조에서는:
  - `app/store/vector.py`가 이 레이어를 감싸는 래퍼 역할.

### 요약 그림

```text
[원본 파일] (PDF/HWP/...)  →  디스크/S3 등
      │
      ▼
[파싱 + 청킹]
      │
      ├─ 메타데이터(문서/청크/코퍼스) → RDB(SQLite 등) + SQLAlchemy(ORM)
      │
      └─ 임베딩 벡터 → 벡터 스토어(Qdrant/Faiss 등)

검색 요청(query)
      │
      ▼
[벡터/BM25 검색 + 리랭킹] → 관련 청크들
      │
      ▼
[LLM 프롬프트 구성 + 호출] → 최종 답변
```

---

## 7. "이 작업은 어떤 층의 일을 하는 건지?" 체크하기

앞으로 코드를 추가할 때, 항상 아래 질문을 먼저 던지면 좋다.

1. **API 층(문/복도)을 다루는가?**
   - FastAPI, 라우터, Pydantic 요청/응답 모델
   - 예: `/query`, `/corpus`, `/health` 정의
2. **데이터 저장/관리 층을 다루는가?**
   - ORM, SQLAlchemy, DB 스키마
   - 예: Corpus/Document/Chunk 테이블 정의, 저장/조회
3. **검색/RAG 품질 층을 다루는가?**
   - 청킹, 임베딩, 벡터/BM25 검색, 리랭커, RAG 파이프라인
4. **LLM 호출 층을 다루는가?**
   - `llm/client.py`, 외부/로컬 LLM 엔드포인트, 프롬프트 구성

이렇게 나눠두면:
- “지금 내가 하는 작업이 FastAPI 때문인지, DB 때문인지, 검색 품질 때문인지”를 매번 명확하게 인지하면서 개발할 수 있다.
