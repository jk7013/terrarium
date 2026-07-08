"""
날씨 툴 - MCP 스타일
AccuWeather에서 서울의 현재 날씨를 가져옵니다.
"""

import re
import json
from typing import Optional
import httpx
from bs4 import BeautifulSoup


def _is_valid_temperature(value: int) -> bool:
    return -50 <= value <= 50


def _extract_temperature(soup: BeautifulSoup, html: str) -> Optional[int]:
    # 방법 1: JSON-LD 스키마에서 추출
    json_ld_scripts = soup.find_all('script', type='application/ld+json')
    for script in json_ld_scripts:
        try:
            data = json.loads(script.string or "")
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and 'temperature' in data:
            try:
                temp_val = int(data['temperature'])
            except (TypeError, ValueError):
                continue
            if _is_valid_temperature(temp_val):
                return temp_val

    # 방법 2: data-temp 속성에서 추출
    temp_elements = soup.find_all(attrs={'data-temp': True})
    if temp_elements:
        try:
            temp_val = int(temp_elements[0]['data-temp'])
            if _is_valid_temperature(temp_val):
                return temp_val
        except (TypeError, ValueError):
            pass

    # 방법 3: class에 "temp"가 포함된 요소에서 추출
    temp_elements = soup.find_all(class_=re.compile(r'temp', re.I))
    for elem in temp_elements:
        text = elem.get_text(strip=True)
        temp_match = re.search(r'(-?\d+)', text)
        if not temp_match:
            continue
        try:
            temp_val = int(temp_match.group(1))
        except (TypeError, ValueError):
            continue
        if _is_valid_temperature(temp_val):
            return temp_val

    # 방법 4: 정규식으로 JSON 데이터에서 추출
    temp_match = re.search(r'["\']temp(erature)?["\']\s*:\s*(-?\d+)', html, re.IGNORECASE)
    if temp_match:
        try:
            temp_val = int(temp_match.group(2))
        except (TypeError, ValueError):
            return None
        if _is_valid_temperature(temp_val):
            return temp_val

    return None


def _extract_condition(soup: BeautifulSoup, html: str) -> Optional[str]:
    blacklist = [
        "get accuweather",
        "browser notifications",
        "alerts",
        "subscribe",
        "download",
        "install",
        "sign up",
        "create account",
        "advertisement",
        "ad",
        "cookie",
        "privacy policy"
    ]
    weather_keywords = [
        "sunny", "cloudy", "rain", "snow", "clear", "partly", "mostly",
        "맑음", "흐림", "비", "눈", "구름", "맑은", "흐린"
    ]

    # 방법 1: phrase 속성
    phrase_matches = re.findall(r'["\']phrase["\']\s*:\s*["\']([^"\']+)["\']', html, re.IGNORECASE)
    for match in phrase_matches:
        match_lower = match.lower()
        if any(blackword in match_lower for blackword in blacklist):
            continue
        if len(match) < 50 and (any(keyword in match_lower for keyword in weather_keywords) or len(match) < 20):
            return match

    # 방법 2: condition 속성
    cond_matches = re.findall(r'["\']condition["\']\s*:\s*["\']([^"\']+)["\']', html, re.IGNORECASE)
    for match in cond_matches:
        match_lower = match.lower()
        if any(blackword in match_lower for blackword in blacklist):
            continue
        if len(match) < 50:
            return match

    # 방법 3: HTML 요소에서 상태 추출
    condition_elements = soup.find_all(class_=re.compile(r'(condition|phrase|weather|status)', re.I))
    for elem in condition_elements:
        text = elem.get_text(strip=True)
        if not text or len(text) >= 50:
            continue
        text_lower = text.lower()
        if any(blackword in text_lower for blackword in blacklist):
            continue
        if any(keyword in text_lower for keyword in ["sunny", "cloudy", "rain", "snow", "clear", "맑음", "흐림", "비", "눈"]) or len(text) < 20:
            return text

    return None


def _clean_condition(condition: Optional[str]) -> Optional[str]:
    if not condition:
        return None
    cleaned = re.sub(r'-?\d+\s*°?[CF]', '', condition).strip()
    cleaned = re.sub(r'[^\w\s가-힣]', '', cleaned).strip()
    return cleaned or None


def get_weather() -> str:
    """
    AccuWeather에서 서울의 현재 날씨 정보를 가져오는 툴.
    
    Returns:
        str: 날씨 정보 문자열 (실패 시 에러 메시지)
    """
    try:
        # AccuWeather 서울 날씨 페이지 URL
        # 서울의 location code는 226081
        url = "https://www.accuweather.com/en/kr/seoul/226081/current-weather/226081"
        
        # User-Agent를 설정하여 봇 차단 방지
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        
        # HTTP 요청 (타임아웃 10초)
        timeout = httpx.Timeout(10.0, connect=5.0)
        with httpx.Client(timeout=timeout, headers=headers, follow_redirects=True) as client:
            response = client.get(url)
            response.raise_for_status()
            html = response.text
        
        # BeautifulSoup으로 HTML 파싱
        soup = BeautifulSoup(html, 'lxml')
        
        temperature = _extract_temperature(soup, html)
        condition = _clean_condition(_extract_condition(soup, html))
        
        # 결과 구성 (자연스러운 문장)
        if temperature is not None:
            if condition:
                # 날씨 상태를 한글로 변환 (간단한 매핑)
                condition_kr = _translate_weather_condition(condition)
                result = f"서울의 현재 날씨는 {temperature}도이고, {condition_kr}입니다"
            else:
                result = f"서울의 현재 날씨는 {temperature}도입니다"
            return result
        else:
            # 파싱 실패 시 기본 메시지
            return "서울의 현재 날씨 정보를 가져올 수 없습니다. AccuWeather 페이지 구조가 변경되었을 수 있습니다."
            
    except httpx.TimeoutException:
        return "날씨 정보를 가져오는 중 시간이 초과되었습니다."
    except httpx.RequestError as e:
        return f"날씨 정보를 가져오는 중 오류가 발생했습니다: {str(e)}"
    except Exception as e:
        return f"날씨 정보를 가져오는 중 예상치 못한 오류가 발생했습니다: {str(e)}"


def _translate_weather_condition(condition: str) -> str:
    """
    날씨 상태를 한글로 변환.
    
    Args:
        condition: 영어 날씨 상태
        
    Returns:
        str: 한글 날씨 상태
    """
    if not condition:
        return ""
    
    condition_lower = condition.lower()
    
    # 날씨 상태 매핑
    weather_map = {
        "sunny": "맑음",
        "clear": "맑음",
        "mostly sunny": "대체로 맑음",
        "partly sunny": "약간 흐림",
        "partly cloudy": "약간 흐림",
        "mostly cloudy": "대체로 흐림",
        "cloudy": "흐림",
        "overcast": "흐림",
        "rain": "비",
        "rainy": "비",
        "showers": "소나기",
        "snow": "눈",
        "snowy": "눈",
        "snow showers": "눈 소나기",
        "fog": "안개",
        "foggy": "안개",
        "windy": "바람",
        "haze": "연무",
    }
    
    # 정확한 매칭 시도
    for eng, kor in weather_map.items():
        if eng in condition_lower:
            return kor
    
    # 매칭되지 않으면 원본 반환 (이미 한글이거나 알 수 없는 상태)
    return condition


def is_weather_query(query: str) -> bool:
    """
    질문이 날씨 관련인지 확인.
    
    Args:
        query: 사용자 질문
        
    Returns:
        bool: 날씨 관련 질문이면 True
    """
    query_lower = query.lower()
    
    # 명확한 날씨 관련 키워드 (단어 단위로 매칭)
    weather_keywords = [
        "날씨", "기온", "온도", "폭설", 
        "맑음", "흐림", "바람", "습도", "강수",
        "weather", "temperature"
    ]
    
    # 명확한 날씨 키워드 확인
    for keyword in weather_keywords:
        # 단어 경계를 고려한 정규식 패턴
        pattern = r'\b' + re.escape(keyword) + r'\b'
        if re.search(pattern, query_lower):
            return True
    
    # "비", "눈" 같은 단어는 더 엄격하게 체크 (다른 단어의 일부가 아닌지 확인)
    rain_snow_keywords = ["비", "눈", "rain", "snow"]
    for keyword in rain_snow_keywords:
        # 단어 경계나 공백 앞뒤에 있는지 확인
        pattern = r'(^|\s)' + re.escape(keyword) + r'(\s|$|[가-힣])'
        if re.search(pattern, query_lower):
            # 추가 컨텍스트 확인: 날씨 관련 맥락이 있는지
            weather_context = ["오늘", "내일", "날씨", "기온", "온도", "weather", "temperature", "하늘", "공기"]
            if any(ctx in query_lower for ctx in weather_context):
                return True
    
    return False

