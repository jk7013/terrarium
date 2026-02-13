# 🌱 Terrarium - RAG 엔진

**Terrarium**은 "병 속 작은 생태계"처럼, RAG에 필요한 모든 컴포넌트를 한 엔진 안에 담는 독립 RAG 백엔드 서비스입니다.

## 🎯 주요 기능

- 문서 파싱/청킹
- 임베딩 (BGE-m3-ko)
- 검색 (BM25 / 키워드 / 벡터)
- 리랭킹 (dragonkue/bge-reranker-v2-m3-ko)
- LLM 프롬프트 생성 및 호출
- 단계별 trace (retrieval_trace, llm_trace)

## 🏗️ 프로젝트 구조

```
terrarium/
├── app/              # FastAPI + RAG 엔진 메인 코드
├── tests/            # 유닛/통합 테스트
├── scripts/          # 개발/운영 유틸 스크립트
├── docker/           # Docker/Compose 관련 파일
├── docs/             # 문서
└── data/             # 샘플 데이터 / 테스트 코퍼스
```

## 🚀 빠른 시작

### 개발 환경 설정

```bash
# 가상환경 생성
python3 -m venv venv
source venv/bin/activate

# 의존성 설치
pip install -r requirements.txt

# 개발 서버 실행
uvicorn app.main:app --reload --port 8080
```

### Docker로 실행

호스트에서 **Ollama가 먼저 실행 중**이어야 합니다 (`ollama serve`, 필요 시 `ollama pull qwen3:4b`).

```bash
# 이미지 빌드
docker build -t terrarium:latest -f docker/Dockerfile .

# 실행 (Mac/Windows: 컨테이너가 host.docker.internal로 호스트의 Ollama에 연결)
docker run -p 9000:9000 terrarium:latest
```

접속: **http://localhost:9000/static/index.html**

- **Linux**에서 호스트 Ollama에 연결하려면:  
  `docker run -p 9000:9000 -e OLLAMA_HOST=http://172.17.0.1:11434 terrarium:latest`  
  또는 `--network host` 사용 후 `OLLAMA_HOST=http://localhost:11434` 로 실행.

## 📚 문서

- **[프로젝트 전체 개요](./docs/PROJECT_OVERVIEW.md)** ⭐ (새로 추가)
- [프로젝트 개요 및 구조](./docs/chatGPT/terrarium_project_structure.md)
- [Jido와의 연동](./docs/chatGPT/jido_terrarium_overview.md)

## 🔗 관련 프로젝트

- **Jido**: 프롬프트 운영 플랫폼 (별도 레포)
  - Terrarium을 HTTP API로 호출하여 RAG 실행
  - 실행 결과를 로깅/평가/비교하는 허브 역할

---

_이 프로젝트는 Jido와 느슨하게 결합되어 있으며, 독립적으로 개발/배포 가능합니다._


