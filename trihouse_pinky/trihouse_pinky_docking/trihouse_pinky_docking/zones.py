"""실측 구역 설정을 읽는다. ROS 와 분리해 시험 가능하게 둔다."""

from pathlib import Path

import yaml

from .sequence import DockStep


class ZoneError(ValueError):
    pass


def load_zones(path: Path | str) -> dict[str, dict]:
    """`zones.yaml` 을 읽어 구역별 설정을 낸다.

    **검증되지 않은 구역은 그대로 싣되 표시를 남긴다.** 지우면 다음 사람이 값이
    없는 줄 알고 다시 재고, 조용히 쓰면 검증 안 된 시퀀스로 로봇이 벽에 들어간다.
    """
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, dict) or "zones" not in document:
        raise ZoneError("zones.yaml 최상위에 zones 가 있어야 합니다")
    zones: dict[str, dict] = {}
    for name, raw in document["zones"].items():
        geometry = raw.get("geometry")
        for field in ("cx", "cy", "yaw", "length", "width"):
            if not isinstance(geometry, dict) or field not in geometry:
                raise ZoneError(f"{name}.geometry 에 {field} 가 없습니다")
        if geometry["length"] <= 0 or geometry["width"] <= 0:
            raise ZoneError(f"{name}.geometry 의 length/width 는 양수여야 합니다")
        zones[name] = {
            "geometry": geometry,
            "verified": bool(raw.get("verified", True)),
            "entry": _steps(name, "entry", raw),
            "exit": _steps(name, "exit", raw),
        }
    return zones


def _steps(name: str, key: str, raw: dict) -> tuple[DockStep, ...]:
    items = raw.get(key)
    if not isinstance(items, list) or not items:
        raise ZoneError(f"{name}.{key} 가 비어 있습니다")
    try:
        return tuple(DockStep(str(item["kind"]), float(item["value"])) for item in items)
    except (KeyError, TypeError) as error:
        raise ZoneError(f"{name}.{key} 단계에 kind/value 가 필요합니다") from error
    except ValueError as error:
        raise ZoneError(f"{name}.{key}: {error}") from error
