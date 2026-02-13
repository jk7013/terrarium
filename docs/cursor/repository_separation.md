# Terrarium 레포지토리 분리 작업 (for ChatGPT)

## 📋 작업 개요

**작업 일시**: 2025-11-26  
**목적**: Jido와 Terrarium을 별도 레포지토리로 분리하여 독립적인 개발/배포 환경 구축

---

## 🎯 작업 배경

### 결정 사항
- **별도 레포지토리로 분리** 결정
- Jido와 Terrarium은 HTTP API로만 연동 (코드 레벨 의존성 없음)
- 각각 독립적으로 개발/배포/스케일링 가능하도록 구조화

### 참고 문서
- `docs/chatGPT/jido_terrarium_overview.md` - Jido와 Terrarium의 역할 분리 및 연동 방식
- `docs/chatGPT/terrarium_project_structure.md` - Terrarium 레포지토리 구조 설계

---

## ✅ 완료된 작업

### 1. Terrarium 레포지토리 디렉토리 구조 생성

```
terrarium/
├── app/                       # FastAPI + RAG 엔진 메인 코드
│   ├── api/                   # HTTP 엔드포인트 (FastAPI 라우터)
│   │   ├── __init__.py
│   │   └── health.py          # 헬스체크 API (구현 완료)
│   ├── rag/                   # RAG 파이프라인 로직 (구조만 생성)
│   ├── store/                 # 코퍼스/벡터 스토어 계층 (구조만 생성)
│   ├── llm/                   # LLM 클라이언트 계층 (구조만 생성)
│   ├── core/                  # 공통 설정/로깅 등 (구조만 생성)
│   ├── __init__.py
│   └── main.py                # FastAPI 엔트리포인트 (기본 구현 완료)
│
├── tests/                     # 유닛/통합 테스트 (디렉토리만 생성)
├── scripts/                   # 개발/운영 유틸 스크립트 (디렉토리만 생성)
├── docker/                    # Docker/Compose 관련 파일
│   └── Dockerfile             # Terrarium 이미지 (기본 구성 완료)
│
├── docs/                      # 문서
│   ├── chatGPT/               # ChatGPT 소통용 문서
│   │   ├── jido_terrarium_overview.md      # Jido와 Terrarium 연동 개요
│   │   └── terrarium_project_structure.md  # 프로젝트 구조 설계
│   └── cursor/                 # Cursor 작업 기록 (이 디렉토리)
│       └── repository_separation.md         # 이 문서
│
├── data/                      # 샘플 데이터 / 테스트 코퍼스
│   ├── samples/
│   └── eval_sets/
│
├── README.md                  # 프로젝트 소개 및 사용법
├── requirements.txt           # Python 의존성 (기본 패키지 포함)
├── env.example                # 환경 변수 예시
└── .gitignore                 # Git 무시 파일
```

### 2. 기본 파일 생성

#### README.md
- 프로젝트 소개
- 주요 기능 요약
- 빠른 시작 가이드
- 관련 프로젝트(Jido) 링크

#### requirements.txt
- FastAPI, Uvicorn, Pydantic 등 기본 웹 프레임워크
- SQLAlchemy (데이터베이스)
- HTTP 클라이언트 (httpx, requests)
- 개발/테스트 도구 (pytest, black, flake8)
- RAG 라이브러리는 주석 처리 (향후 추가 예정)

#### env.example
- OFFLINE/ONLINE 모드 설정
- 서버 설정 (API_HOST, API_PORT=9000)
- LLM 설정 (LLM_BASE_URL, LLM_MODEL)
- 임베딩/리랭커 모델 설정
- 데이터 저장소 경로

#### app/main.py
- FastAPI 애플리케이션 초기화
- CORS 미들웨어 설정
- health 라우터 등록
- 루트 엔드포인트 (`/`, `/health`)

#### app/api/health.py
- `GET /health` 엔드포인트 구현
- 기본 헬스체크 응답: `{"status": "ok"}`

#### docker/Dockerfile
- Python 3.11-slim 기반
- 포트 9000 노출
- 기본 의존성 설치 구성

#### .gitignore
- Python 관련 무시 파일 (__pycache__, venv 등)
- IDE 설정 파일
- 데이터 파일 (*.db, data/)
- 환경 변수 파일 (.env)

### 3. 문서 파일 이동

**이동된 파일:**
- `jido/chatGPT/jido_terrarium_overview.md` → `terrarium/docs/chatGPT/jido_terrarium_overview.md`
- `jido/chatGPT/terrarium_project_structure.md` → `terrarium/docs/chatGPT/terrarium_project_structure.md`

**삭제된 파일 (jido 레포에서):**
- `jido/chatGPT/jido_terrarium_overview.md`
- `jido/chatGPT/terrarium_project_structure.md`

---

## 📍 현재 상태

### 완료된 부분
- ✅ 디렉토리 구조 생성
- ✅ 기본 파일 생성 (README, requirements, env.example, .gitignore)
- ✅ FastAPI 기본 앱 구조 (main.py, health API)
- ✅ Docker 기본 구성
- ✅ 문서 정리 및 이동

### 미구현 부분 (v0 목표)
- ⏳ `/query` API 구현 (RAG 파이프라인 더미 구현)
- ⏳ RAG 파이프라인 모듈 (chunking, embedding, retriever, reranker, pipeline)
- ⏳ 코퍼스 관리 API (`/corpus`)
- ⏳ 실제 RAG 로직 구현

---

## 🔗 Jido와의 관계

### 독립성
- **코드 레벨 의존성 없음**: Jido는 Terrarium을 HTTP API로만 호출
- **독립 배포 가능**: 각각 별도로 배포/스케일링 가능
- **버전 관리 분리**: 각각 독립적인 Git 레포지토리

### 연동 방식
```
[Jido Frontend] → [Jido Backend] → HTTP API → [Terrarium] → [LLM Server]
```

- Jido Backend는 `engine_id = "local-terrarium"` 같은 프로필로 Terrarium 호출
- Terrarium은 `/query` API로 RAG 실행 결과 반환
- 응답에는 `answer`, `contexts`, `retrieval_trace`, `llm_trace` 포함

---

## 🚀 다음 단계 (v0 개발)

### 우선순위
1. **환경 설정 완료**
   - 가상환경 생성 및 의존성 설치
   - `.env` 파일 설정

2. **FastAPI 기본 구조 확장**
   - `/query` API 라우터 추가
   - Pydantic Request/Response 모델 정의

3. **RAG 파이프라인 더미 구현**
   - `app/rag/pipeline.py`에 `run_rag()` 함수 골격 구현
   - 더미 응답 반환 (실제 RAG 로직은 이후 구현)

4. **테스트 및 문서화**
   - `/query` API curl 예시 추가
   - README에 실행 방법 보완

---

## 📝 ChatGPT에게 전달할 정보

이 문서를 ChatGPT에게 전달하면:

1. **현재 상태 파악**: Terrarium 레포가 어떻게 구성되어 있는지
2. **작업 이력 이해**: 왜 분리했는지, 어떤 구조로 되어 있는지
3. **다음 작업 방향**: v0 개발을 위한 우선순위와 목표

ChatGPT는 이 정보를 바탕으로:
- Terrarium의 현재 구조를 이해하고
- 다음 단계 개발 작업을 도와줄 수 있습니다

---

## 🔍 참고 파일 위치

- **프로젝트 구조 설계**: `docs/chatGPT/terrarium_project_structure.md`
- **Jido 연동 개요**: `docs/chatGPT/jido_terrarium_overview.md`
- **프로젝트 루트**: `README.md`

---

_이 문서는 Terrarium 레포지토리 분리 작업을 기록하고, ChatGPT와의 효율적인 소통을 위해 작성되었습니다._


