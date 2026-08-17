"""카메라 등록 정본(`config/cameras.yaml`)을 검증해 적재한다.

정본을 파일 하나로 두는 이유는 두 가지다. 첫째, `map_revisions.manifest` 는
스키마가 불변으로 못박혀 있어서 카메라 한 대의 주소가 바뀔 때마다 지도 내용이
그대로인 새 revision 을 발행해야 한다. 그 revision 은 RMF 와 Pinky 가 참조하므로
카메라 교체가 주행 revision 을 흔들게 된다. 둘째, Pinky 의 `camera_streamer` 는
부팅 시 이 값이 필요한데, 네트워크 조회에 의존하면 네트워크 장애를 진단할
수단이 네트워크에 묶인다.

운영 경로(`stream_path`)는 저장하지 않고 역할 접두사와 `camera_id` 로 파생한다.
저장하면 둘이 어긋날 수 있지만 파생하면 어긋날 수 없다. 반면 P0 fixture 경로는
카메라마다 이름 규칙이 달라 파생할 수 없으므로 `simulation_path` 로 적는다.
명부를 두 파일로 나누지 않는 이유가 이것이다. 나누면 정체성이 두 벌이 되고,
그 중복을 감시하는 테스트가 또 필요해진다.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

import yaml


_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")

# 역할별 RTSP 경로 접두사. MediaMTX 는 이 접두사 단위로 publish 권한과 녹화
# 보존 정책을 나눈다.
ROLE_STREAM_PREFIX: Mapping[str, str] = {
    "pinky_travel": "pinky",
    "omx_wrist": "omx",
    "warehouse_fixed": "fixed",
}

# P0 fixture 스트림은 실스트림과 경로만으로 구분되어야 한다.
SIMULATION_PATH_PREFIX = "fixtures/"

DEFAULT_REGISTRY_PATH = Path(__file__).resolve().parents[2] / "config" / "cameras.yaml"


class CameraRegistryError(ValueError):
    """등록 정본이 계약을 어겼을 때 올린다."""


@dataclass(frozen=True)
class CameraRecord:
    camera_id: str
    role: str
    attached_to: str | None
    simulation_path: str
    map_pose: tuple[float, float, float] | None

    @property
    def stream_path(self) -> str:
        return f"{ROLE_STREAM_PREFIX[self.role]}/{self.camera_id}"

    def publish_url(self, mediamtx_base_url: str) -> str:
        return f"{mediamtx_base_url.rstrip('/')}/{self.stream_path}"


def load_camera_registry(path: Path | str = DEFAULT_REGISTRY_PATH) -> tuple[CameraRecord, ...]:
    """정본 YAML 을 읽어 검증된 카메라 목록을 돌려준다."""
    source = Path(path)
    try:
        document = yaml.safe_load(source.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise CameraRegistryError(f"camera registry not found: {source}") from error
    except yaml.YAMLError as error:
        raise CameraRegistryError(f"camera registry is not valid YAML: {source}") from error
    return parse_camera_registry(document)


def parse_camera_registry(document: Any) -> tuple[CameraRecord, ...]:
    """이미 적재된 문서를 검증한다. 파일 접근 없이 계약만 확인한다."""
    if not isinstance(document, Mapping):
        raise CameraRegistryError("camera registry must be a mapping")
    entries = document.get("cameras")
    if not isinstance(entries, Sequence) or isinstance(entries, (str, bytes)) or not entries:
        raise CameraRegistryError("camera registry must contain a non-empty cameras list")

    records: list[CameraRecord] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        record = _parse_entry(entry, index)
        if record.camera_id in seen:
            raise CameraRegistryError(f"duplicate camera_id: {record.camera_id}")
        seen.add(record.camera_id)
        records.append(record)
    return tuple(records)


def _parse_entry(entry: Any, index: int) -> CameraRecord:
    if not isinstance(entry, Mapping):
        raise CameraRegistryError(f"camera entry {index} must be a mapping")

    camera_id = entry.get("camera_id")
    if not isinstance(camera_id, str) or not _IDENTIFIER.fullmatch(camera_id):
        raise CameraRegistryError(f"camera entry {index} has an unsafe camera_id: {camera_id!r}")

    role = entry.get("role")
    if role not in ROLE_STREAM_PREFIX:
        raise CameraRegistryError(f"{camera_id} has an unknown role: {role!r}")

    attached_to = entry.get("attached_to")
    if attached_to is not None and (
        not isinstance(attached_to, str) or not _IDENTIFIER.fullmatch(attached_to)
    ):
        raise CameraRegistryError(f"{camera_id} has an unsafe attached_to: {attached_to!r}")

    simulation_path = entry.get("simulation_path")
    if not isinstance(simulation_path, str) or not simulation_path.startswith(
        SIMULATION_PATH_PREFIX
    ):
        raise CameraRegistryError(
            f"{camera_id} simulation_path must start with {SIMULATION_PATH_PREFIX!r}"
        )

    map_pose = _parse_map_pose(entry.get("map_pose"), camera_id)
    if attached_to is not None and map_pose is not None:
        # 로봇과 함께 움직이는 카메라에 고정 좌표를 주면 그 좌표는 언제나 거짓이다.
        raise CameraRegistryError(f"{camera_id} is robot-mounted and must not carry a map_pose")

    return CameraRecord(
        camera_id=camera_id,
        role=role,
        attached_to=attached_to,
        simulation_path=simulation_path,
        map_pose=map_pose,
    )


def _parse_map_pose(value: Any, camera_id: str) -> tuple[float, float, float] | None:
    if value is None:
        return None
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or len(value) != 3
        or not all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in value)
    ):
        raise CameraRegistryError(f"{camera_id} map_pose must be null or three numbers")
    return (float(value[0]), float(value[1]), float(value[2]))


__all__ = [
    "CameraRecord",
    "CameraRegistryError",
    "DEFAULT_REGISTRY_PATH",
    "ROLE_STREAM_PREFIX",
    "SIMULATION_PATH_PREFIX",
    "load_camera_registry",
    "parse_camera_registry",
]
