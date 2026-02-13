"""
헬스체크 API
"""
from fastapi import APIRouter

router = APIRouter()

@router.get("/health")
async def health_check():
    """헬스체크 엔드포인트"""
    return {"status": "ok"}


