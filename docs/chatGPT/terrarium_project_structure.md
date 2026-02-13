# 🌱 Terrarium 레포지토리 구조 제안

> 이 문서는 **Terrarium를 별도 레포지토리**로 구성할 때의 기본 구조를 정의한다.  
> Terrarium는 “병 속 작은 생태계”처럼, RAG에 필요한 모든 컴포넌트를 한 엔진 안에 담는 **독립 RAG 백엔드 서비스**다.

---

## 1. 레포 개요

- 레포 이름(예시): **`terrarium`**
- 역할:
  - 첨부파일 기반 Q&A (ephemeral RAG)
  - 사전 색인된 코퍼스 기반 Q&A
  - 단계별 trace가 보이는 RAG 파이프라인
- 외부(예: Jido)와의 연결은 **HTTP API**로만 이루어진다.
  - Jido는 `engine_id = "local-terrarium"` 같은 프로필로 Terrarium를 호출한다.
  - 코드 레벨 의존성 없음.

---

## 2. 루트 디렉토리 구조

```text
terrarium/
├── app/                       # FastAPI + RAG 엔진 메인 코드
│   ├── api/                   # HTTP 엔드포인트 (FastAPI 라우터)
│   ├── rag/                   # RAG 파이프라인 로직
│   ├── store/                 # 코퍼스/벡터 스토어 계층
│   ├── llm/                   # LLM 클라이언트 계층
│   ├── core/                  # 공통 설정/로깅 등
│   └── main.py                # FastAPI 엔트리포인트
│
├── tests/                     # 유닛/통합 테스트
│   ├── test_chunking.py
│   ├── test_retriever.py
│   ├── test_pipeline.py
│   └── ...
│
├── scripts/                   # 개발/운영 유틸 스크립트
│   ├── run_dev.sh             # 로컬 개발 서버 실행 (uvicorn)
│   ├── init_sample_corpus.py  # 샘플 코퍼스 초기화
│   └── ...
│
├── docker/                    # Docker/Compose 관련 파일
│   ├── Dockerfile             # Terrarium 이미지
│   └── docker-compose.local.yml  # Terrarium + 로컬 LLM 개발용
│
├── docs/                      # 문서
│   ├── OVERVIEW.md            # Terrarium 개념/아키텍처 개요
│   ├── API_SPEC.md            # /query, /corpus API 스펙
│   ├── RAG_PIPELINE.md        # 파이프라인 단계/trace 구조
│   └── DB_SCHEMA.md           # SQLite/스토어 스키마
│
├── data/                      # 샘플 데이터 / 테스트 코퍼스
│   ├── samples/
│   └── eval_sets/
│
├── chatGPT/                   # ChatGPT 설계/대화 로그 정리
│   └── terrarium_project_structure.md  # 이 문서
│
├── .env.example               # 환경변수 예시 (OFFLINE/ONLINE 설정 등)
├── pyproject.toml             # Python 패키지/빌드 설정 (또는 requirements.txt)
├── README.md                  # 최상위 소개 및 사용법
└── Makefile                   # (선택) make dev/test 등 단축 명령
```

---

## 3. `app/` 하위 구조

```text
app/
├── api/
│   ├── __init__.py
│   ├── query.py                # /query, /ephemeral 등 RAG 실행 API
│   ├── corpus.py               # 코퍼스/문서 업로드·관리 API
│   └── health.py               # 헬스체크 (/health)
│
├── rag/
│   ├── chunking.py             # 문서 청킹 로직
│   ├── parsing.py              # PDF/표/엑셀 파서 (초기엔 텍스트만)
│   ├── embedding.py            # BGE-m3-ko 임베딩
│   ├── retriever.py            # BM25/키워드/벡터 검색
│   ├── reranker.py             # bge-reranker-v2-m3-ko 리랭커
│   └── pipeline.py             # end-to-end RAG 파이프라인(run_rag)
│
├── store/
│   ├── schemas.py              # Document / Chunk / Corpus 스키마
│   ├── sqlite.py               # 메타데이터/코퍼스 저장 (SQLite)
│   └── vector.py               # 벡터 스토어 래퍼(Faiss/기타)
│
├── llm/
│   └── client.py               # 로컬/원격 LLM 호출 클라이언트
│
├── core/
│   ├── config.py               # 설정(OFFLINE/ONLINE, 모델 이름, LLM URL)
│   └── logging.py              # 로깅/트레이싱 설정
│
└── main.py                     # FastAPI 애플리케이션 엔트리포인트
```

---

## 4. `/query` 기본 요청/응답 스키마 (요약)

> v0에서는 **첨부파일 업로드 대신 `raw_text`만 지원**한다.  
> 파일 업로드(멀티파트)는 이후 단계에서 추가한다.

### 4.1 요청 (요약)

```jsonc
POST /query

{
  "mode": "ephemeral",                // v0에서는 우선 "ephemeral"만 사용
  "query": "사용자 질문 텍스트",
  "raw_text": "첨부 텍스트 (ephemeral 모드용)",
  "profile": "dummy_v0",
  "options": {
    "top_k": 5,
    "final_contexts": 3
  }
}
```

- `mode = "ephemeral"`:
  - `raw_text`를 받아서 **1회성 RAG** 수행
- 이후 `mode = "corpus"` + `corpus_id`는 v1에서 확장 예정

### 4.2 응답 (요약)

```jsonc
{
  "answer": "최종 LLM 답변 텍스트 (v0에서는 더미 문자열도 허용)",
  "contexts": [
    {
      "chunk_id": "c_1",
      "document_id": "d_ephemeral",
      "text": "청킹된 본문 일부",
      "score": 1.0,
      "meta": {}
    }
  ],
  "retrieval_trace": {
    "query_expansions": [],
    "bm25_results": [],
    "vector_results": [],
    "reranked_results": []
  },
  "llm_trace": {
    "prompt": "LLM에 실제로 던진 프롬프트 (또는 v0에서는 간단한 문자열)",
    "model": "dummy-llm-v0",
    "latency_ms": 0
  },
  "meta": {
    "profile": "dummy_v0",
    "mode": "ephemeral",
    "timestamp": "2025-01-01T12:34:56Z"
  }
}
```

---

## 5. v0 개발 시작 순서 (Cursor용 힌트)

v0의 목표는 **“구조와 API 껍데기”를 먼저 세우고, RAG 내부는 더미라도 한 번 끝까지 흐르게 하는 것**이다.

### 5.1 v0 목표

- `uvicorn app.main:app --reload` 로 Terrarium 서버 실행
- `/health` → `{"status": "ok"}` 응답
- `/query` → 위 응답 스키마 형태로 JSON 리턴
  - `answer`/`contexts`/`retrieval_trace`/`llm_trace`/`meta` 필드 존재
  - 내용은 더미여도 됨

### 5.2 v0 작업 리스트

1. **환경 설정**
   - `pyproject.toml` 또는 `requirements.txt`에 최소 의존성 추가
     - `fastapi`
     - `uvicorn[standard]`
     - `pydantic`
2. **FastAPI 엔트리포인트**
   - `app/main.py`에 FastAPI 인스턴스 생성
   - `include_router`로 `api.health`, `api.query` 연결
3. **헬스체크 API**
   - `app/api/health.py`에 `GET /health` 구현
4. **RAG 파이프라인 더미 구현**
   - `app/rag/pipeline.py`에 `run_rag(request) -> response` 골격 구현
   - 지금은 `raw_text`를 그대로 contexts[0].text로 넣고, answer는 `"echo: {query}"` 등으로 더미 처리
5. **/query API 구현**
   - `app/api/query.py`에 Pydantic Request/Response 모델 정의
   - `POST /query`에서 Request 파싱 → `run_rag` 호출 → Response 반환
6. **README.md**
   - 설치 방법 (venv, pip install -r requirements.txt)
   - 로컬 실행 방법 (uvicorn 명령)
   - 간단한 `/query` curl 예시 추가

이 문서는 **`chatGPT/terrarium_project_structure.md`**로 저장해서  
Cursor에게 “이 구조와 v0 작업 리스트를 기준으로 초기 코드를 만들어 달라”고 지시하는 용도로 사용한다.


http://www.law.go.kr/DRF/lawService.do?target=eflaw&OC=jinkyung.park&type=json&
http://www.law.go.kr/DRF/lawService.do?OC=test&target=eflaw&MST=1031013647&type=JSON
