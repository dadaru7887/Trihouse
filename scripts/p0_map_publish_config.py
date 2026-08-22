"""지도 발행 CLI가 연결할 Gateway 주소를 한 곳에서 정한다."""

from __future__ import annotations

from typing import Mapping


def map_projects_api_base(environ: Mapping[str, str]) -> str:
    gateway = environ.get("FMS_GATEWAY_BASE_URL", "http://127.0.0.1:8080")
    return f"{gateway.rstrip('/')}/api/v1/map-projects"


def map_project_name(environ: Mapping[str, str]) -> str:
    return environ.get("FMS_MAP_PROJECT", "new_map_2").strip()


def physical_features_file(environ: Mapping[str, str]) -> str | None:
    value = environ.get("FMS_PHYSICAL_FEATURES_FILE", "").strip()
    return value or None
