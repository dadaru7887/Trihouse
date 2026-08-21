"""front/wrist 카메라 포트를 파일 하나에 저장해두고 재사용한다.

USB 재연결·재부팅마다 /dev/videoN 번호가 바뀔 수 있어서(teleoperate 화면으로
직접 확인해야 함), 매번 deliver.py/store.py 명령에 --front-cam/--wrist-cam을
길게 다시 치는 대신, set_cameras.py로 한 번만 저장해두면 이후 실행은 그 값을
자동으로 읽는다. --front-cam/--wrist-cam을 CLI에서 직접 주면 그 값이 항상
우선한다(저장된 값은 fallback일 뿐).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "var" / "camera_ports.json"


@dataclass(frozen=True)
class CameraPorts:
    front: str
    wrist: str


def save(front: str, wrist: str) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps({"front": front, "wrist": wrist}, indent=2))


def load() -> CameraPorts | None:
    """저장된 값이 없으면 None (파일이 아예 없거나 처음 쓰는 경우)."""
    if not CONFIG_PATH.exists():
        return None
    data = json.loads(CONFIG_PATH.read_text())
    return CameraPorts(front=data["front"], wrist=data["wrist"])
