"""환경 변수로부터 DB/TCP 실행 설정을 만드는 모듈.

접두사를 분리해 DB 비밀정보(`FMS_DB_*`)와 로봇 수집 서버 설정
(`FMS_TCP_*`)이 서로 섞이지 않도록 한다.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """MySQL 연결 풀 설정. `.env`도 읽되 정의하지 않은 값은 무시한다."""
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
    """로봇 상태와 작업 이벤트를 받는 asyncio TCP 서버 설정."""
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
    """프로세스에서 동일한 DB 설정 객체를 재사용한다."""
    return Settings()


@lru_cache
def get_tcp_settings() -> TcpSettings:
    """프로세스에서 동일한 TCP 설정 객체를 재사용한다."""
    return TcpSettings()


@lru_cache
def get_map_runtime_settings() -> MapRuntimeSettings:
    return MapRuntimeSettings()
