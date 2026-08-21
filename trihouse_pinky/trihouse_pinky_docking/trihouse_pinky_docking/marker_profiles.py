"""지도에 묶인 ArUco 협로 도킹 실측값을 검증해 읽는다."""

from pathlib import Path

import yaml

from .marker_controller import DockProfile


class MarkerProfileError(ValueError):
    pass


REQUIRED_MEASUREMENTS = (
    "minimum_confidence",
    "stable_observations",
    "observation_timeout_s",
    "standoff_m",
    "distance_tolerance_m",
    "bearing_tolerance_rad",
    "turn_direction",
    "reverse_distance_m",
    "activation_x_m",
    "activation_y_m",
    "activation_radius_m",
)


def load_marker_profiles(path: Path | str, *, map_name: str) -> dict[str, DockProfile]:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise MarkerProfileError("마커 도킹 설정이 객체가 아니다")
    declared = str(document.get("map_name", ""))
    if declared != map_name:
        raise MarkerProfileError(
            f"마커 도킹 표는 {declared!r} 지도 값인데 현재 지도는 {map_name!r} 이다"
        )
    result: dict[str, DockProfile] = {}
    for destination, raw in (document.get("docks") or {}).items():
        if not isinstance(raw, dict):
            raise MarkerProfileError(f"{destination}: 설정이 객체가 아니다")
        # 미실측 항목은 파일에 남겨 현장 작업 목록으로 쓰되 절대 실행하지 않는다.
        if not bool(raw.get("verified", False)):
            continue
        missing = [name for name in REQUIRED_MEASUREMENTS if raw.get(name) is None]
        if raw.get("marker_id") is None:
            missing.insert(0, "marker_id")
        if missing:
            raise MarkerProfileError(
                f"{destination}: 실측값이 없다: {', '.join(missing)}"
            )
        try:
            result[str(destination)] = DockProfile(
                marker_id=str(raw["marker_id"]),
                minimum_confidence=float(raw["minimum_confidence"]),
                stable_observations=int(raw["stable_observations"]),
                observation_timeout_s=float(raw["observation_timeout_s"]),
                standoff_m=float(raw["standoff_m"]),
                distance_tolerance_m=float(raw["distance_tolerance_m"]),
                bearing_tolerance_rad=float(raw["bearing_tolerance_rad"]),
                turn_direction=int(raw["turn_direction"]),
                reverse_distance_m=float(raw["reverse_distance_m"]),
                max_linear_mps=float(raw.get("max_linear_mps", 0.04)),
                max_angular_rps=float(raw.get("max_angular_rps", 0.30)),
                yaw_tolerance_rad=float(raw.get("yaw_tolerance_rad", 0.04)),
                reverse_position_tolerance_m=float(
                    raw.get("reverse_position_tolerance_m", 0.015)
                ),
                phase_timeout_s=float(raw.get("phase_timeout_s", 30.0)),
                activation_x_m=float(raw["activation_x_m"]),
                activation_y_m=float(raw["activation_y_m"]),
                activation_radius_m=float(raw["activation_radius_m"]),
            )
        except (TypeError, ValueError) as error:
            raise MarkerProfileError(f"{destination}: 잘못된 실측값: {error}") from error
    return result


__all__ = ["MarkerProfileError", "load_marker_profiles"]
