FROM python:3.11-slim

WORKDIR /app

# 시스템 의존성 설치
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Python 의존성 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 애플리케이션 코드 복사
COPY app/ ./app/
COPY static/ ./static/
COPY data/ ./data/

# 데이터 디렉토리 생성
RUN mkdir -p /app/data

# Docker에서 호스트의 Ollama에 연결 (Mac/Windows: host.docker.internal)
# Linux에서는 실행 시 -e OLLAMA_HOST=http://172.17.0.1:11434 또는 --network host 로 덮어쓸 수 있음
ENV OLLAMA_HOST=http://host.docker.internal:11434
ENV OLLAMA_MODEL=qwen3:4b

# 포트 노출
EXPOSE 9000

# 애플리케이션 실행
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9000"]


