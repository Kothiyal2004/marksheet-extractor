from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Google Gemini LLM
    GEMINI_API_KEY: str
    GEMINI_MODEL: str = "gemini-2.5-flash"

    # JWT
    SECRET_KEY: str = "change-this-secret-key-in-production-min-32-chars"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # API credentials (single-user; extend to a DB for multi-user)
    API_USERNAME: str = "admin"
    API_PASSWORD: str = "admin123"

    # File handling
    MAX_FILE_SIZE_MB: int = 10
    UPLOAD_DIR: str = "uploads"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache()
def get_settings() -> Settings:
    return Settings()
