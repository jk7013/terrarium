# 🧠 Jido + Terrarium 프로젝트 개요

## 📋 프로젝트 소개

**Jido**는 LLM/RAG 기반 서비스 개발을 위한 프롬프트 운영 플랫폼이다.  
프롬프트 버전 관리, A/B 테스트, 로그/트레이싱 통합, 기본 보안 정책을 제공하며,  
여러 LLM/RAG 엔진을 하나의 인터페이스로 실행·비교·평가하는 허브 역할을 한다.

**Terrarium**은 문서·임베딩·검색·리랭킹·LLM 응답까지를 하나의 “작은 생태계”처럼 담는 RAG 엔진이다.  
Jido가 실험·평가·로그 허브라면, Terrarium은 그 위에서 돌아가는 실제 RAG 세계(백엔드 엔진)다.

- Jido: 프롬프트/실행/평가/로그 UI + API
- Terrarium: 첨부파일/코퍼스 기반 RAG 검색과 답변을 수행하는 HTTP 엔진
- 둘은 HTTP API 규격(Engine API Contract)만 공유하고, 코드 레벨 의존성은 분리한다.

---

## 🏗️ 현재 Jido 프로젝트 구조 (실제 디렉토리 기준)

> 이 구조는 **현재 jido 레포 상태**를 나타낸다.  
> Terrarium는 별도 디렉토리/레포로 추가될 예정이며, 아래에 별도 섹션으로 설계 구조를 정의한다.

```text
jido/
├── backend/                    # FastAPI 백엔드 (현재 최소 앱 구성)
│   ├── app/
│   │   ├── __init__.py
│   │   └── main.py            # FastAPI 엔트리포인트 (헬스체크 포함)
│   ├── config/
│   │   └── error_hints.json
│   ├── requirements.txt       # Python 의존성 (Py3.14 호환 버전 적용)
│   └── Dockerfile             # 백엔드 컨테이너
│
├── frontend/                   # React + TypeScript + Vite
│   ├── src/
│   │   ├── app/
│   │   │   ├── App.tsx
│   │   │   └── routes.tsx
│   │   ├── components/
│   │   │   ├── Header.tsx
│   │   │   ├── ABPanel.tsx
│   │   │   ├── JsonViewer.tsx
│   │   │   ├── MetaChips.tsx
│   │   │   ├── RawProcessedTabs.tsx
│   │   │   ├── PromptCard.tsx
│   │   │   └── PromptSideSheet.tsx
│   │   ├── pages/
│   │   │   ├── IndexPage.tsx        # 온보딩(연결 마법사 모달 골격 포함)
│   │   │   ├── DashboardPage.tsx
│   │   │   ├── ResultsSinglePage.tsx / ResultsABPage.tsx
│   │   │   └── LogsSinglePage.tsx / LogsABPage.tsx
│   │   ├── styles/
│   │   │   ├── jido-theme.css        # 기본 테마 + 누락 클래스 보완
│   │   │   └── results.css
│   │   ├── api/
│   │   │   ├── client.ts
│   │   │   └── runs.ts
│   │   └── utils/
│   │       └── extractAnswer.ts
│   ├── index.html
│   └── Dockerfile
│
├── docs/                        # 스펙/보안/ADR
│   ├── API_SPEC.md              # API 스펙 (한글 복원 완료)
│   ├── DB_SCHEMA.md             # DB 스키마 요약 (한글 복원 완료)
│   ├── SECURITY.md              # 보안/듀얼모드 정책 (한글 복원 완료)
│   └── adr/                     # 아키텍처 결정 기록(ADR)
│       ├── 001-dual-mode.md
│       ├── 002-db-choice.md
│       ├── 003-tracing-model.md
│       ├── 004-logging-policy.md
│       ├── 005-container-security.md
│       ├── 006-release-profiles.md
│       ├── 007-rate-limit-and-cost-cap.md
│       ├── 008-secrets-and-key-rotation.md
│       └── 009-egress-control-and-network-policies.md
│
├── cursor/                      # 설계/지시 문서
│   ├── index_onboarding_cursor_patch_instructions_for_cursor.md  # 연결 마법사 상세 지시
│   ├── index_onboarding_enterprise_fixes_for_cursor.md            # a11y/보안 보완 지시
│   ├── ui_polish_and_log_nav.md, unified_header_refactor.md 등
│   └── jido_project_structure.md
│
├── compose/                     # 테스트 프로파일
│   └── docker-compose.offline-test.yml
│
├── docker-compose.yml           # 멀티 컨테이너 실행
├── docker-compose.override.yml  # 개발용 보안 완화/포트 노출 설정
├── env.example                  # 환경 변수 예시
└── README.md
```

---

## 🌱 Terrarium 개요

**Terrarium**은 “병 속 작은 생태계”처럼, RAG에 필요한 모든 요소를 한 엔진 안에 담는 프로젝트다.

- 문서 파싱/청킹
- 임베딩(BGE-m3-ko)
- 검색(BM25 / 키워드 / 벡터)
- 리랭킹(dragonkue/bge-reranker-v2-m3-ko)
- LLM 프롬프트 생성 및 호출
- 단계별 trace (retrieval_trace, llm_trace)

을 **표준화된 HTTP API**로 제공한다.

Jido 입장에서는 Terrarium이 **엔진 하나(local-terrarium)** 로 보이고,  
Terrarium은 내부에서 RAG 파이프라인을 투명하게 실행·로깅한다.

### 🎯 Terrarium의 목표

1. **표준적인 RAG 백엔드 엔진**
   - 첨부파일 기반 Q&A
   - 미리 색인된 코퍼스 기반 Q&A
2. **단계별 디버깅 가능한 구조**
   - 청킹/검색/리랭크/LLM 각 단계를 분리하고 trace로 공개
3. **Jido와의 느슨한 결합**
   - Jido는 Engine API 규격에만 의존 (코드 의존성 없음)
   - Terrarium은 독립 서비스로 개발/배포 가능

---

## 🏗️ Terrarium 설계 디렉토리 구조 (제안)

> 이 구조는 **새로 추가할 Terrarium 엔진 레포/디렉토리**에 대한 설계다.  
> 실제 구현 시 `jido/` 옆에 `terrarium/` sibling 디렉토리로 두거나, 별도 레포로 분리할 수 있다.

```text
terrarium/
├── app/
│   ├── api/                        # FastAPI 라우터
│   │   ├── __init__.py
│   │   ├── query.py                # /query, /ephemeral 등 RAG 실행 API
│   │   ├── corpus.py               # 코퍼스/문서 업로드·관리 API
│   │   └── health.py               # 헬스체크
│   │
│   ├── rag/                        # RAG 파이프라인 핵심 로직
│   │   ├── chunking.py             # 문서 청킹 로직
│   │   ├── parsing.py              # PDF/표/엑셀 파서
│   │   ├── embedding.py            # BGE-m3-ko 임베딩
│   │   ├── retriever.py            # BM25/키워드/벡터 검색
│   │   ├── reranker.py             # bge-reranker-v2-m3-ko 리랭커
│   │   └── pipeline.py             # end-to-end RAG 파이프라인
│   │
│   ├── store/                      # 코퍼스/벡터 스토어 계층
│   │   ├── schemas.py              # Document / Chunk 스키마
│   │   ├── sqlite.py               # 메타데이터/코퍼스 저장 (SQLite 등)
│   │   └── vector.py               # 벡터 스토어 래퍼(Faiss/기타)
│   │
│   ├── llm/                        # LLM 클라이언트 계층
│   │   └── client.py               # 로컬/원격 LLM 호출 클라이언트
│   │
│   ├── core/
│   │   ├── config.py               # Terrarium 설정 (OFFLINE/ONLINE 모드 등)
│   │   └── logging.py              # 로깅 설정
│   │
│   └── main.py                     # Terrarium FastAPI 엔트리포인트
│
├── tests/
│   ├── test_chunking.py
│   ├── test_retriever.py
│   ├── test_pipeline.py
│   └── ...
│
├── Dockerfile
└── README.md
```

---

## 🔗 Jido ↔ Terrarium 연동 방식

### 구조 요약

```text
[Jido Frontend] ──> [Jido Backend] ──HTTP──> [Terrarium API] ──> [LLM Server]
                                              │
                                              └─> [Embedding / Vector Store / Reranker / SQLite]
```

- Jido Backend는 `engine_id = "local-terrarium"` 같은 프로필을 통해 Terrarium을 호출한다.
- Jido는 Terrarium의 `/query` API 응답을 받아, 실행 로그/평가용 데이터로 저장하고 UI에 렌더링한다.
- Terrarium은 RAG 파이프라인의 각 단계를 trace 구조로 포함해 반환한다.

### 요청/응답 기본 형태 (요약)

요청 예시:

```jsonc
POST /query

{
  "mode": "corpus",              // "ephemeral" | "corpus"
  "query": "이 계약서에서 위약금 조항 알려줘",
  "corpus_id": "contracts_v1",
  "profile": "bm25_vec_rerank_v1",
  "options": {
    "top_k": 10,
    "final_contexts": 5
  }
}
```

응답 예시:

```jsonc
{
  "answer": "위약금 조항은 제12조에 정의되어 있으며, ...",
  "contexts": [
    {
      "chunk_id": "c_123",
      "document_id": "d_10",
      "text": "...",
      "score": 0.92,
      "meta": {
        "section": "제12조(위약금)",
        "page": 5
      }
    }
  ],
  "retrieval_trace": {
    "query_expansions": [...],
    "bm25_results": [...],
    "vector_results": [...],
    "reranked_results": [...]
  },
  "llm_trace": {
    "prompt": "...최종 LLM 프롬프트...",
    "model": "qwen-local-7b",
    "latency_ms": 1234
  },
  "meta": {
    "profile": "bm25_vec_rerank_v1",
    "mode": "corpus",
    "timestamp": "2025-01-01T12:34:56Z"
  }
}
```

> Jido 레포에서는 Terrarium를 직접 import하지 않고,  
> 단지 “엔진 API 스펙” 문서와 `engine_id`/`base_url` 설정만 알고 있는 상태를 유지한다.

---

## 📦 Docker / Compose 계획 (요약)

- **Jido 단독 실행용 (오픈소스/테스트)**  
  - 기존 `docker-compose.yml` / `compose/docker-compose.offline-test.yml` 활용
- **Jido + Terrarium + 로컬 LLM 개발용**  
  - 별도 compose: `docker-compose.local-terrarium.yml` (예시)
  - 서비스 예시:
    - `jido-backend`
    - `jido-frontend`
    - `terrarium`
    - `local-llm`

이 파일은 Cursor에게:

- Terrarium 디렉토리/모듈 설계 기준,
- Jido와 Terrarium의 역할 분리,
- 두 프로젝트 간 HTTP 연동 구조

를 설명하기 위한 기준 문서로 사용한다.
