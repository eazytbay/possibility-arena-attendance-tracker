import os


def _db_url() -> str:
    url = os.environ.get("DATABASE_URL", "sqlite:///dev.db")
    # Newer SQLAlchemy may default to psycopg3; this project installs psycopg2.
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg2://" + url[len("postgresql://"):]
    return url


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "")
    SQLALCHEMY_DATABASE_URI = _db_url()
    CHURCH_NAME = os.environ.get("CHURCH_NAME", "Our Church")
    PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000")
    TIMEZONE = "Africa/Lagos"
    WTF_CSRF_TIME_LIMIT = None
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "false").lower() == "true"
    RATELIMIT_STORAGE_URI = "memory://"
