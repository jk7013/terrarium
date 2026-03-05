import os


def get_db_url() -> str:
    """
    DB 접속 URL 생성.
    DATABASE_URL이 있으면 우선 사용하고,
    없으면 DB_* 환경변수 조합으로 생성한다.
    """
    direct = os.getenv("DATABASE_URL")
    if direct:
        return direct

    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "5432")
    name = os.getenv("DB_NAME", "terrarium")
    user = os.getenv("DB_USER", "terrarium")
    password = os.getenv("DB_PASSWORD", "terrarium")
    return f"postgresql://{user}:{password}@{host}:{port}/{name}"
