from pydantic_settings import BaseSettings
from functools import lru_cache

class Settings(BaseSettings):
    APP_NAME: str = "TaIQ"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: str = "development"
    SECRET_KEY: str = "change-me-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24h

    DATABASE_URL: str = "postgresql+asyncpg://taiq:taiq_secret@localhost:5432/taiq_db"
    REDIS_URL: str = "redis://localhost:6379/0"

    CORS_ORIGINS: list[str] = ["http://localhost", "http://localhost:8090", "http://localhost:3000"]

    # Email settings (SMTP)
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_NAME: str = "TaIQ"
    SMTP_FROM_EMAIL: str = "noreply@taiq.us"
    EMAIL_ENABLED: bool = False   # set True in .env once SMTP creds are configured

    # Frontend base URL (used in email links)
    FRONTEND_URL: str = "http://localhost:8090"

    # Backend's own public base URL — used to build the OAuth callback redirect URI
    BACKEND_URL: str = "http://localhost:8000"

    # OAuth (Google / GitHub login)
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GITHUB_CLIENT_ID: str = ""
    GITHUB_CLIENT_SECRET: str = ""

    # Anthropic API key — used for AI-powered job file parsing
    ANTHROPIC_API_KEY: str = ""

    class Config:
        env_file = ".env"

@lru_cache
def get_settings() -> Settings:
    return Settings()

settings = get_settings()
