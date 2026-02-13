# Terrarium Portfolio Note 1
## FastAPI + Tool-Routed RAG v0 구현과 운영 이슈 해결

이 글은 Terrarium을 포트폴리오 관점에서 기술적으로 설명한 문서입니다.  
대상 독자는 개발자이며, 현재 코드베이스 기준으로 "무엇이 구현되었고, 어떤 의사결정을 했으며, 어떤 이슈를 어떻게 해결했는가"를 정확히 정리합니다.

---

## 1) 프로젝트 목표와 현재 범위

Terrarium은 독립 배포 가능한 RAG 백엔드입니다. 현재 v0 범위는 다음에 집중되어 있습니다.

- HTTP API 기반 질의응답 파이프라인
- Tool-first 분기(날씨/시간) + LLM 후처리 응답
- 멀티턴 입력(`chat_history`) 지원
- 추적 가능한 응답 구조(`retrieval_trace`, `llm_trace`, `meta`)

아직 미구현(또는 골격 단계)인 부분:

- 실제 BM25/벡터 검색/리랭킹
- 코퍼스 인덱싱 파이프라인
- 벡터 스토어 연동(FAISS 예정)

---

## 2) 아키텍처 개요

### API 레이어

- 엔트리포인트: `app/main.py`
  - CORS 설정
  - `/health`, `/api/query` 라우터 등록
  - `/static` 정적 파일 서빙

- Query 라우팅: `app/api/routes/query.py`
  - `POST /api/query` 요청을 `run_rag()`로 위임

### 스키마 레이어

- `app/api/schemas/query.py`
  - `QueryRequest`: `mode`, `query`, `raw_text`, `options`, `chat_history`
  - `QueryResponse`: `contexts`, `retrieval_trace`, `llm_trace`, `meta`
  - 관찰 가능한 디버깅/운영 정보를 응답에 포함하는 구조

### 파이프라인 레이어

- `app/rag/pipeline.py`
  - 쿼리 확장(`_expand_query`)
  - 컨텍스트 구성(`_build_ephemeral_contexts`)
  - tool routing (weather/time)
  - LLM 호출 + 예외 처리 + 응답 조립

### LLM 어댑터

- `app/llm/client.py`
  - Ollama `/api/chat` 호출
  - 환경변수: `OLLAMA_HOST`, `OLLAMA_MODEL`
  - 긴 응답 대비 타임아웃(총 300s, connect 10s)

---

## 3) 요청 처리 플로우 (현재 구현)

`POST /api/query` 기준 실제 흐름:

1. 요청 검증 (`QueryRequest`)
2. `run_rag()` 진입, `trace_id` 생성
3. 질의 의도 분기:
   - 날씨 질문이면 `weather` tool 실행
   - 시간 질문이면 `time` tool 실행
   - 아니면 일반 컨텍스트 기반 LLM 호출
4. LLM 응답 생성 (`call_llm`)
5. `QueryResponse` 반환:
   - `answer`
   - `contexts`
   - `retrieval_trace` (현재 검색 결과는 빈 리스트)
   - `llm_trace` (모델, 프롬프트, 지연시간)
   - `meta` (`status`, `tool` 포함)

핵심 포인트는 **tool 결과를 즉시 문자열로 반환하지 않고 LLM 컨텍스트로 전달해 최종 답변 품질을 통일**한 점입니다.

---

## 4) Tool Routing 설계 포인트

### Weather tool

- 구현: `app/tools/weather.py`
- 기능:
  - AccuWeather 페이지 스크래핑
  - 온도/상태 다중 파싱 전략
  - 노이즈 텍스트 필터링
  - 상태 한글화 매핑

### Pipeline 통합 방식

- `is_weather_query(query)`로 intent detection
- `get_weather()` 결과를 `ContextItem`으로 감싼 뒤 `_call_llm_with_tool_context()`에서 LLM 호출
- `meta.tool = "weather"`로 실행 경로를 응답에 노출

같은 패턴으로 `time` tool도 통합되어 있으며, tool 확장이 쉬운 형태입니다.

---

## 5) 운영 이슈와 해결 기록

### 이슈 A: `/static/index.html` 404

- 증상: 컨테이너 실행 후 UI 접근 실패
- 원인: 이미지 빌드 시 `static/` 미복사
- 조치: `docker/Dockerfile`에 `COPY static/ ./static/` 추가
- 결과: UI 정상 노출

### 이슈 B: Docker 내 Ollama 연결 실패

- 증상: "Ollama 서버 연결 불가"
- 원인: 컨테이너 내부 `localhost`는 호스트가 아님
- 조치:
  - Docker 기본 환경변수로 `OLLAMA_HOST=http://host.docker.internal:11434` 설정
  - 문서에 Linux 예외 케이스(`172.17.0.1` 또는 `--network host`) 명시
- 결과: 환경 맞춤 설정 시 연결 가능

### 이슈 C: 포트 바인딩 실패

- 런타임 로그: `Bind for 0.0.0.0:9000 failed: port is already allocated`
- 원인: 호스트 9000 포트 선점
- 조치: 기존 점유 프로세스/컨테이너 정리 또는 다른 포트 매핑

---

## 6) 기술적 선택과 트레이드오프

### 선택 1: FastAPI + Pydantic 스키마 우선

- 장점: API 계약이 명확하고 OpenAPI 문서화가 쉬움
- 트레이드오프: 실제 검색 계층이 아직 비어 있어 응답 trace와 실제 검색 품질 간 간극 존재

### 선택 2: Tool-first 분기

- 장점: 특정 도메인 질의(날씨/시간)에서 정확도 및 제어성 확보
- 트레이드오프: 키워드 기반 분기이므로 intent detection 고도화 필요

### 선택 3: Ollama 직접 호출

- 장점: 로컬 모델 운영과 비용 예측 용이
- 트레이드오프: 배포 환경(Docker 네트워크/모델 로딩 시간)에서 운영 이슈 관리 필요

---

## 7) 다음 단계 (벡터 인덱싱 DB 연결)

현재 문서와 의존성 코멘트 기준으로 FAISS를 우선 후보로 두고 있습니다.

실행 계획:

1. 임베딩 생성기 도입 (`sentence-transformers` 계열)
2. 인덱스 저장/로딩 계층 분리 (`app/store/vector.py` 신설)
3. `pipeline.py`에서 `vector_results` 실제 채우기
4. `mode="corpus"` 경로 활성화
5. retrieval trace를 평가 가능한 포맷으로 확장

---

## 8) 포트폴리오 관점에서 강조할 성과

- 단순 데모가 아니라, API 계약/trace/예외처리를 갖춘 실행 가능한 백엔드 파이프라인 구축
- Tool orchestration을 파이프라인 내부로 일관되게 통합
- Docker 운영 이슈를 코드/문서 레벨로 함께 해결
- 다음 확장(벡터 검색, 리랭킹, 코퍼스 모드)이 가능한 구조 확보

---

작성 기준: 현재 `main` 워크스페이스 코드 상태 (v0.1.0 계열)
