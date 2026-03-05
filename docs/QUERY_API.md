# Terrarium API 스펙

> 기준일: 2026-03-05
> Base URL: `http://localhost:9000`

---

## POST /api/query

RAG 파이프라인을 실행하고 답변을 반환합니다.

### 요청

```json
{
  "query": "계약 해지 절차를 알려줘",
  "mode": "corpus",
  "profile": "default",
  "raw_text": null,
  "chat_history": [
    { "role": "user", "content": "이전 질문" },
    { "role": "assistant", "content": "이전 답변" }
  ],
  "options": {
    "top_k": 6,
    "final_contexts": 3
  }
}
```

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| query | string | O | 사용자 질문 |
| mode | string | X | `ephemeral` (raw_text 사용) / `corpus` (벡터 검색, 기본값) |
| profile | string | X | RAG 프로파일 (기본: `default`) |
| raw_text | string | X | ephemeral 모드 시 직접 전달할 텍스트 |
| chat_history | array | X | 멀티턴 대화 이력 |
| options.top_k | int | X | 검색 후보 수 (기본: 6) |
| options.final_contexts | int | X | LLM에 전달할 컨텍스트 수 (기본: 3) |

### 처리 흐름

```
1. 툴 감지 (날씨/시간 질문?)
   ├─ Yes → 툴 실행 → 결과를 컨텍스트로 LLM 호출
   └─ No → RAG 파이프라인
              ├─ 쿼리 확장 (동의어, 표현 정규화)
              ├─ 벡터 검색 (pgvector 코사인 유사도)
              ├─ 컨텍스트 선별 (문자 수 제한)
              └─ LLM 호출 (Ollama)
```

### 응답

```json
{
  "trace_id": "uuid",
  "answer": "최종 답변 텍스트",
  "contexts": [
    {
      "chunk_id": "c_1",
      "document_id": "d_1",
      "text": "선택된 컨텍스트 텍스트",
      "score": 0.85,
      "meta": {
        "filepath": "docs/contract.jsonl",
        "page_no": 3,
        "chunk_no": 12,
        "distance": 0.15
      }
    }
  ],
  "retrieval_trace": {
    "query_expansions": ["계약 해지 절차", "계약 해지 방법"],
    "bm25_results": [],
    "vector_results": [
      { "chunk_id": "c_1", "score": 0.85, "text": "..." }
    ],
    "reranked_results": []
  },
  "llm_trace": {
    "model": "qwen3:4b",
    "prompt": "시스템 프롬프트 + 컨텍스트 + 질문",
    "output": "LLM 원본 응답",
    "latency_ms": 1234,
    "input_tokens": null,
    "output_tokens": null
  },
  "meta": {
    "mode": "corpus",
    "profile": "default",
    "timestamp": "2026-03-05T12:00:00Z",
    "status": "success",
    "tool": null
  }
}
```

| 필드 | 설명 |
|------|------|
| trace_id | 요청 식별 UUID |
| answer | LLM 최종 답변 |
| contexts | LLM에 전달된 컨텍스트 목록 |
| retrieval_trace | 검색 과정 추적 (확장 쿼리, 벡터 결과) |
| llm_trace | LLM 호출 추적 (모델, 프롬프트, 지연시간) |
| meta.tool | 사용된 툴 (`weather` / `time` / `null`) |
| meta.status | `success` / `error` / `llm_error` |

---

## POST /api/index

JSONL 파일을 읽어 문서를 인덱싱합니다.

### 요청

```json
{
  "path": "data/documents/corpus.jsonl",
  "rebuild": false
}
```

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| path | string | O | JSONL 파일 경로 |
| rebuild | bool | X | true면 기존 데이터 삭제 후 재인덱싱 |

### 인덱싱 파이프라인

```
JSONL 로드 → 단락 인식 청킹 (900자/180자 오버랩)
           → BGE-m3 임베딩 (1024차원)
           → 키워드 추출
           → pgvector upsert (documents + chunks)
```

### 응답

```json
{
  "ok": true,
  "docs": 45,
  "chunks": 312,
  "elapsed_ms": 8500
}
```

---

## GET /api/index/status

인덱싱 상태를 조회합니다.

### 응답

```json
{
  "document_count": 45,
  "chunk_count": 312,
  "latest_chunk_at": "2026-03-05T00:00:00Z"
}
```

---

## GET /health

헬스체크 엔드포인트.

### 응답

```json
{ "status": "ok" }
```

---

## 프롬프트 팩 API

### POST /api/prompts/render

프롬프트 팩을 렌더링하여 최종 messages 배열을 반환합니다 (디버깅/테스트용).

```json
// 요청
{
  "pack_id": "default",
  "variables": { "tone": "concise", "language": "ko" },
  "query": "오늘 날씨 알려줘",
  "chat_history": [],
  "contexts": []
}

// 응답
{
  "pack_id": "default",
  "prompt_hash": "sha256...",
  "variables_used": { "tone": "concise", "language": "ko" },
  "messages": [
    { "role": "system", "content": "..." },
    { "role": "user", "content": "..." }
  ],
  "evidence_summary": []
}
```

### GET /api/prompts/packs

등록된 프롬프트 팩 목록을 반환합니다.

### GET /api/prompts/packs/{pack_id}

특정 팩의 템플릿, 변수 스키마, 정책을 조회합니다.
