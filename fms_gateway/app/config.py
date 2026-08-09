"""Environment-backed Gateway configuration."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FMS_DB_", env_file=".env", extra="ignore"
    )

    host: str = "127.0.0.1"
    port: int = 3306
    user: str = "fms_app"
    password: str = "fms_app_dev"
    database: str = "trihouse_fms"
    pool_size: int = 5


@lru_cache
def get_settings() -> Settings:
    return Settings()
