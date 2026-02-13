"""
Terrarium - RAG 엔진 FastAPI 애플리케이션
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.api import health
from app.api.routes import query

app = FastAPI(
    title="Terrarium RAG Engine",
    description="독립 RAG 백엔드 서비스 - 문서 파싱, 임베딩, 검색, 리랭킹, LLM 호출",
    version="0.1.0"
)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 개발 환경용, 프로덕션에서는 특정 도메인만 허용
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API 라우터 등록
app.include_router(health.router)
app.include_router(query.router, prefix="/api")

# Static 파일 서빙 (HTML 등)
import os
static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
async def root():
    """루트 엔드포인트"""
    return {
        "message": "Terrarium RAG Engine",
        "version": "0.1.0",
        "status": "running"
    }

