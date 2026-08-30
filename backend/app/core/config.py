from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "LLM Programming Tutor"
    env: str = "dev"
    database_url: str = "sqlite+aiosqlite:///./data/app.db"
    jwt_secret: str = "dev-only-change-me"
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 30
    refresh_token_ttl_days: int = 7
    app_secret_path: str = ".secret_key"
    llm_provider: str = "mock"


@lru_cache
def get_settings() -> Settings:
    return Settings()
