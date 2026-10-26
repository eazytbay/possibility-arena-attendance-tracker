import os


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "")
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "sqlite:///dev.db")
    CHURCH_NAME = os.environ.get("CHURCH_NAME", "Our Church")
    PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000")
    TIMEZONE = "Africa/Lagos"
    DEMO_MODE = os.environ.get("DEMO_MODE", "false").lower() == "true"
    WTF_CSRF_TIME_LIMIT = None
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "false").lower() == "true"
    RATELIMIT_STORAGE_URI = "memory://"
    # SMS greetings. Nothing is sent unless SMS_ENABLED=true and a token is set.
    SMS_ENABLED = os.environ.get("SMS_ENABLED", "false").lower() == "true"
    SMS_API_TOKEN = os.environ.get("SMS_API_TOKEN", "")
    SMS_SENDER_ID = os.environ.get("SMS_SENDER_ID", "")
    SMS_GATEWAY = os.environ.get("SMS_GATEWAY", "direct-corporate")
    SMS_TEXT_BIRTHDAY = os.environ.get(
        "SMS_TEXT_BIRTHDAY",
        "Happy birthday, {first_name}! God bless you with more years of joy and favour. "
        "RCCG Possibility Arena. To opt out, see the welcome team.")
    SMS_TEXT_NEW_MONTH = os.environ.get(
        "SMS_TEXT_NEW_MONTH",
        "Happy new month, {first_name}! May {month} bring you God's favour and joy. "
        "RCCG Possibility Arena. To opt out, see the welcome team.")
