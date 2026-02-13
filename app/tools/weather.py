"""
날씨 툴 - MCP 스타일
AccuWeather에서 서울의 현재 날씨를 가져옵니다.
"""

import re
from typing import Optional
import httpx
from bs4 import BeautifulSoup


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
        
        # 온도 추출 시도 (다양한 방법 시도)
        temperature = None
        condition = None
        
        # 방법 1: JSON-LD 스키마에서 추출
        json_ld_scripts = soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                import json
                data = json.loads(script.string)
                if isinstance(data, dict) and 'temperature' in data:
                    temperature = int(data['temperature'])
                if isinstance(data, dict) and 'condition' in data:
                    condition = data['condition']
            except:
                pass
        
        # 방법 2: data 속성에서 온도 찾기
        if not temperature:
            temp_elements = soup.find_all(attrs={'data-temp': True})
            if temp_elements:
                try:
                    temperature = int(temp_elements[0]['data-temp'])
                except:
                    pass
        
        # 방법 3: class에 "temp"가 포함된 요소 찾기
        if not temperature:
            temp_elements = soup.find_all(class_=re.compile(r'temp', re.I))
            for elem in temp_elements:
                text = elem.get_text(strip=True)
                temp_match = re.search(r'(-?\d+)', text)
                if temp_match:
                    try:
                        temp_val = int(temp_match.group(1))
                        # 합리적인 온도 범위 체크 (-50 ~ 50도)
                        if -50 <= temp_val <= 50:
                            temperature = temp_val
                            break
                    except:
                        pass
        
        # 방법 4: 정규식으로 JSON 데이터에서 추출
        if not temperature:
            # "temp": 숫자 또는 "temperature": 숫자 패턴
            temp_match = re.search(r'["\']temp(erature)?["\']\s*:\s*(-?\d+)', html, re.IGNORECASE)
            if temp_match:
                try:
                    temp_val = int(temp_match.group(2))
                    if -50 <= temp_val <= 50:
                        temperature = temp_val
                except:
                    pass
        
        # 날씨 상태 추출 (더 정확한 파싱)
        # 알림/광고 텍스트 필터링을 위한 블랙리스트
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
        
        # 방법 1: phrase 속성 찾기 (블랙리스트 필터링)
        if not condition:
            phrase_matches = re.findall(r'["\']phrase["\']\s*:\s*["\']([^"\']+)["\']', html, re.IGNORECASE)
            for match in phrase_matches:
                match_lower = match.lower()
                # 블랙리스트에 없는 것만 사용
                if not any(blackword in match_lower for blackword in blacklist):
                    # 합리적인 날씨 상태인지 확인 (너무 길지 않고, 날씨 관련 키워드 포함)
                    if len(match) < 50:  # 너무 긴 텍스트는 제외
                        weather_keywords = ["sunny", "cloudy", "rain", "snow", "clear", "partly", "mostly", 
                                          "맑음", "흐림", "비", "눈", "구름", "맑은", "흐린"]
                        if any(keyword in match_lower for keyword in weather_keywords) or len(match) < 20:
                            condition = match
                            break
        
        # 방법 2: condition 속성 찾기 (블랙리스트 필터링)
        if not condition:
            cond_matches = re.findall(r'["\']condition["\']\s*:\s*["\']([^"\']+)["\']', html, re.IGNORECASE)
            for match in cond_matches:
                match_lower = match.lower()
                if not any(blackword in match_lower for blackword in blacklist):
                    if len(match) < 50:
                        condition = match
                        break
        
        # 방법 3: HTML 요소에서 날씨 상태 찾기
        if not condition:
            # class에 "condition", "phrase", "weather" 등이 포함된 요소 찾기
            condition_elements = soup.find_all(class_=re.compile(r'(condition|phrase|weather|status)', re.I))
            for elem in condition_elements:
                text = elem.get_text(strip=True)
                if text and len(text) < 50:
                    text_lower = text.lower()
                    if not any(blackword in text_lower for blackword in blacklist):
                        # 날씨 관련 키워드가 있거나 짧은 텍스트면 사용
                        if any(keyword in text_lower for keyword in ["sunny", "cloudy", "rain", "snow", "clear", 
                                                                     "맑음", "흐림", "비", "눈"]) or len(text) < 20:
                            condition = text
                            break
        
        # 날씨 상태 정제 (온도 정보 제거, 불필요한 문자 제거)
        if condition:
            # "4°CCloudy" 같은 형식에서 온도 부분 제거
            condition = re.sub(r'-?\d+\s*°?[CF]', '', condition)  # 온도 단위 제거
            condition = condition.strip()
            # 특수문자나 기호 제거 (단, 한글/영문/공백만 허용)
            condition = re.sub(r'[^\w\s가-힣]', '', condition)
            condition = condition.strip()
            # 빈 문자열이 되면 None으로
            if not condition:
                condition = None
        
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
    
    # 단어 경계를 고려한 매칭 (예: "png"가 "비"로 인식되지 않도록)
    import re
    
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

