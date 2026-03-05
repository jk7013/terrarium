# Terrarium Engineering Note 3
## 코드베이스 전체 리뷰와 안정화 리팩토링 (Runtime-safe pass)

이번 글은 Terrarium v0 코드베이스를 전수 리뷰한 뒤, 실제로 적용한 안정화/리팩토링 작업을 개발자 관점에서 기록한 문서다.  
목표는 두 가지였다.

1. 런타임 리스크를 줄여 "서비스가 덜 깨지게" 만들기
2. 함수/로직 중복을 줄여 "다음 기능 개발이 쉬운 형태"로 정리하기

---

## 1) 리뷰에서 확인한 주요 문제

### A. 비동기 파이프라인에서 동기 툴 직접 호출

`run_rag()`는 async 함수인데, 내부에서 `get_weather()` / `get_current_time()`를 동기 호출하고 있었다.  
이 구조는 요청이 몰릴 때 이벤트 루프를 블로킹할 수 있다.

- 영향: 동시 처리량 저하, tail latency 증가
- 조치: `asyncio.to_thread()`로 동기 툴 호출을 워커 스레드로 오프로딩

---

### B. LLM 예외 처리 로직 중복

툴 경로와 일반 경로에서 LLM 호출 예외 처리(타임아웃/연결 실패/기타)가 거의 동일하게 중복되어 있었다.

- 영향: 수정 포인트 다중화, 메시지/동작 불일치 가능성
- 조치: `_safe_call_llm()` 공통 함수로 통합

---

### C. 날씨 툴의 단일 대형 함수

`get_weather()`가 파싱/정제/후처리/문장 생성까지 모두 포함해 길고 복잡했다.

- 영향: 테스트 어려움, 파싱 규칙 수정 비용 증가
- 조치: 온도 추출/상태 추출/정제 함수를 분리

---

### D. 어댑터/클라이언트 예외 처리의 안정성 빈틈

- `HTTPAdapter` 타임아웃 예외 타입이 실제 HTTPX 계열과 불일치
- `LLM client`에서 JSON 파싱 실패 시 보호 로직 부족
- `LocalAdapter` 이벤트 루프 API 사용 방식 개선 필요

---

## 2) 실제 반영한 변경 사항

### 2-1. `app/rag/pipeline.py`

핵심 공통화 함수 추가:

- `_build_retrieval_trace(query)`
- `_build_llm_error_trace(message, latency_ms)`
- `_safe_call_llm(request, contexts, trace_id, ...)`

핵심 동작 개선:

- 툴 호출:
  - `await asyncio.to_thread(get_weather)`
  - `await asyncio.to_thread(get_current_time)`
- 일반 경로/툴 경로 모두 `_safe_call_llm()` 경유
- UTC timestamp 생성 시 timezone-aware 방식 적용

결과:

- LLM 예외 처리 정책 일관화
- 이벤트 루프 블로킹 완화
- `run_rag()` 내 중복 코드 감소

---

### 2-2. `app/tools/weather.py`

함수 분리:

- `_is_valid_temperature`
- `_extract_temperature`
- `_extract_condition`
- `_clean_condition`

추가 개선:

- parsing 단계 `bare except` 제거 (구체 예외 사용)
- 기존 동작(최대한 파싱 후 한국어 문장 생성)은 유지

결과:

- 파싱 규칙 단위 테스트 가능 구조 확보
- 가독성/수정 용이성 개선

---

### 2-3. `app/llm/client.py`

안정성 보강:

- `resp.json()` 실패 시 명시적 예외 변환
- `message` 필드 타입 체크 후 fallback 처리

결과:

- 비정상 응답 포맷에서 파이프라인이 예상 불가하게 깨질 확률 감소

---

### 2-4. 어댑터/유틸 보정

- `app/tools/adapters/http_adapter.py`
  - `httpx.TimeoutException` 기준으로 타임아웃 처리 정리
- `app/tools/adapters/local_adapter.py`
  - `get_event_loop()` → `get_running_loop()`
- `app/tools/time.py`
  - 함수 내부 중복 import 정리

---

## 3) 검증 결과 (runtime evidence)

이번 변경 후 최소 런타임 검증:

- `python3 -m compileall app` 성공
- 수정 파일 대상 lint 진단 오류 없음
- 테스트 실행 환경 확인:
  - `pytest` 실행 가능 (프로젝트 `.venv` 기준)
  - 현재 테스트 케이스는 아직 없음 (`no tests ran`)

즉, 문법/정적 검증 관점에서 회귀 없이 통과했고, 다음 단계는 테스트 추가가 필요하다.

---

## 4) 이번 리팩토링에서 의도적으로 "안 건드린 것"

아래 항목은 구조상 중요하지만 이번 패스에서는 안정화 우선 원칙으로 보류했다.

- `prompts/*` 모듈을 파이프라인에 실제 연결
- `tools/bootstrap/executor/router` 계층 통합 리팩토링
- `mode=corpus` / BM25 / vector / reranker 실제 구현
- 문서/환경변수 정합성 전체 정리 (`env.example` 포함)

이유:

- 현재 서비스가 실제로 동작 중인 경로를 먼저 안전화해야 했고,
- 도메인 로직 확장은 별도 설계 라운드에서 진행하는 편이 리스크가 낮다.

---

## 5) 다음 액션 (권장)

1. API/파이프라인 최소 테스트 3종 추가
   - 일반 질의 성공
   - weather tool 분기
   - LLM 연결 실패 graceful fallback
2. 문서 정합성 정리
   - `env.example` ↔ 실제 env 이름 통일
   - `docs/QUERY_API.md`에 `chat_history`와 `meta.tool` 반영
3. 벡터 검색 단계 착수
   - FAISS 기반 저장/로드 + `vector_results` 채우기

---

## 마무리

이번 작업은 기능 추가보다 **코드베이스의 운영 안정성**과 **변경 가능성**을 높이는 데 초점을 맞췄다.  
결론적으로, Terrarium은 "동작하는 v0"에서 "확장 가능한 v0"로 한 단계 올라온 상태다.
