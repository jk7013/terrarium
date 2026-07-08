"""
시간/날짜 툴 - MCP 스타일
현재 시간, 날짜, 요일 정보를 제공합니다.
"""

from datetime import datetime
import re
import pytz


def get_current_time() -> str:
    """
    현재 시간 정보를 반환하는 툴.
    
    Returns:
        str: 현재 시간 정보 문자열 (서울 시간 기준)
    """
    # 서울 시간대 설정
    seoul_tz = pytz.timezone('Asia/Seoul')
    now = datetime.now(seoul_tz)
    
    # 날짜와 시간 포맷팅
    date_str = now.strftime("%Y년 %m월 %d일")
    time_str = now.strftime("%H시 %M분")
    weekday = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"][now.weekday()]
    
    return f"{date_str} {weekday} {time_str} (서울 시간)"


def is_time_query(query: str) -> bool:
    """
    질문이 시간/날짜 관련인지 확인.
    
    Args:
        query: 사용자 질문
        
    Returns:
        bool: 시간/날짜 관련 질문이면 True
    """
    query_lower = query.lower()
    
    # 명확한 시간/날짜 관련 키워드
    time_keywords = [
        "시간", "날짜", "요일", "지금", "현재", "오늘",
        "time", "date", "day", "now", "current", "today"
    ]
    
    # 단어 경계를 고려한 매칭
    for keyword in time_keywords:
        pattern = r'\b' + re.escape(keyword) + r'\b'
        if re.search(pattern, query_lower):
            return True
    
    return False


