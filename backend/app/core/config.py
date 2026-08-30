from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "LLM Programming Tutor"
    env: str = "dev"
    database_url: str = "sqlite+aiosqlite:///./data/app.db"
    # PyJWT 要求 HMAC-SHA256 密钥至少 32 字节，部署前必须替换为随机值
    jwt_secret: str = "dev-only-change-me-before-any-real-deployment"
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 30
    refresh_token_ttl_days: int = 7
    app_secret_path: str = ".secret_key"
    llm_provider: str = "mock"
    # Chroma 本地持久化目录（相对路径以 backend/ 为基准）
    chroma_persist_dir: str = "data/chroma"
    # 上传文件落盘目录（相对路径以 backend/ 为基准）
    upload_dir: str = "data/uploads"
    # 索引并发上限（spec §3.2 权衡 14）
    index_concurrency: int = 1


@lru_cache
def get_settings() -> Settings:
    return Settings()
