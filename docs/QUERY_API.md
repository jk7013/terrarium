# /query API v0 스펙 (Terrarium)

## 목적

- Terrarium RAG 엔진의 핵심 엔드포인트.
- 한 번의 요청으로:
  - 사용자의 질문을 받고
  - RAG 파이프라인을 실행하고
  - 최종 답변 + 컨텍스트 + 트레이스를 함께 반환한다.

---

## Request (v0)

`POST /api/query`

```jsonc
{
  "mode": "ephemeral",        // "ephemeral" | "corpus" (v0는 ephemeral만 사용)
  "query": "사용자 질문 텍스트",
  "raw_text": "한 번에 던질 원문 텍스트(파일 대신)",

  "profile": "default",       // RAG 프로파일 이름 (향후 확장용)
  "options": {
    "top_k": 10,              // 리트리버 단계에서 가져올 최대 후보 수
    "final_contexts": 3       // LLM에 최종으로 넣을 컨텍스트 개수
  }
}
```

### 필드 설명

- **mode**
  - `"ephemeral"`: 요청마다 넘어오는 `raw_text`를 사용해 1회성 RAG 수행
  - `"corpus"`: 사전에 색인된 코퍼스를 사용하는 모드 (v0에서는 구현 X, 향후 추가)
- **query**
  - 사용자의 자연어 질문
- **raw_text**
  - `mode="ephemeral"`일 때만 사용.
  - 첨부파일 파싱의 초기 버전으로, 텍스트 전체를 한 번에 넣는 용도.
- **profile**
  - RAG 전략(임베딩 모델, 리랭커, 검색 조합 등)을 구분하기 위한 이름.
- **options.top_k**
  - 리트리버 단계에서 가져올 최대 후보 청크 수.
- **options.final_contexts**
  - LLM에 실제로 넣을 상위 컨텍스트 개수.

---

## Response (v0)

```jsonc
{
  "trace_id": "uuid-같은-값",

  "answer": "최종 답변 텍스트",

  "contexts": [
    {
      "chunk_id": "c_1",
      "document_id": "d_ephemeral",
      "text": "선택된 컨텍스트 텍스트",
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
    "model": "dummy-llm-v0",
    "prompt": "LLM에 실제로 전달된 프롬프트",
    "output": "LLM가 생성한 응답 텍스트",
    "latency_ms": 0,
    "input_tokens": null,
    "output_tokens": null
  },

  "meta": {
    "mode": "ephemeral",
    "profile": "default",
    "timestamp": "2025-11-27T12:34:56Z",
    "status": "success"
  }
}
```

### 필드 설명

- **trace_id**
  - 이 요청 전체를 식별하는 ID (로그/트레이스 연동용)
- **answer**
  - LLM 최종 답변 텍스트
- **contexts[]**
  - LLM에 들어간(또는 들어갈 수 있었던) 컨텍스트 목록
- **retrieval_trace**
  - RAG 검색/리랭킹 과정에서 어떤 후보들이 있었는지에 대한 요약
  - v0에서는 빈 배열 위주로 두고, 점점 채워 넣는다.
- **llm_trace**
  - 어떤 모델에 어떤 프롬프트를 넣어서 어떤 응답을 받았는지 기록
- **meta**
  - 모드/프로파일/시간/성공 여부 등 공통 메타데이터
