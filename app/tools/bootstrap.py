"""
Tool Bootstrap - 툴 등록(레지스트리 빌드)
"""
from app.tools.registry import ToolRegistry, ToolSpec, ToolAdapterType
from app.tools.weather import get_weather, is_weather_query
from app.tools.time import get_current_time, is_time_query


def build_registry() -> ToolRegistry:
    """
    모든 툴을 등록하여 ToolRegistry 반환
    
    Returns:
        ToolRegistry: 등록된 툴들이 포함된 레지스트리
    """
    registry = ToolRegistry()
    
    # 날씨 툴 등록
    registry.register(ToolSpec(
        id="weather",
        name="날씨 정보",
        description="AccuWeather에서 서울 날씨 정보를 가져옵니다",
        adapter_type=ToolAdapterType.LOCAL,
        adapter_config={
            "function": get_weather
        },
        match_function=is_weather_query,
        priority=10  # 높은 우선순위
    ))
    
    # 시간 툴 등록
    registry.register(ToolSpec(
        id="time",
        name="시간 정보",
        description="현재 시간/날짜/요일 정보를 제공합니다",
        adapter_type=ToolAdapterType.LOCAL,
        adapter_config={
            "function": get_current_time
        },
        match_function=is_time_query,
        priority=10  # 높은 우선순위
    ))
    
    return registry

