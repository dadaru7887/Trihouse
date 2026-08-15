"""Environment-backed Gateway configuration."""

from functools import lru_cache
from pathlib import Path

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


class TcpSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FMS_TCP_", extra="ignore")

    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 8788
    max_line_bytes: int = 65536


class MapRuntimeSettings(BaseSettings):
    """Map upload/deployment filesystem limits outside canonical MySQL storage."""

    model_config = SettingsConfigDict(env_prefix="FMS_MAP_", extra="ignore")

    runtime_root: Path = Path("runtime")
    source_token_ttl_seconds: float = 900
    source_max_bytes: int = 20 * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_tcp_settings() -> TcpSettings:
    return TcpSettings()


@lru_cache
def get_map_runtime_settings() -> MapRuntimeSettings:
    return MapRuntimeSettings()
