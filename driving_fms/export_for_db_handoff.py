#!/usr/bin/env python3
"""fms_feature_points.jsonl + aruco_recognition_distance_tests.jsonl을 실제 Trihouse DB
스키마(db/schema_mysql.sql)의 locations/map_features 필드명에 맞춰 변환해서 관제팀에
넘겨줄 파일을 만든다.

**이 스크립트는 원본 파일을 전혀 안 건드림** -- 읽기만 하고 새 파일(fms_db_handoff.jsonl)로만
출력. 원본은 계속 mission_goal_state_machine.py가 그대로 씀(map_x/map_y/map_yaw 등 우리
필드명 유지).

**주의(2026-08-13 밤 조사 결과)**: 이 출력을 그냥 DB에 넣으면 바로 동작하는 게 아님 -- DB는
location_id(auto-increment PK), map_revision, locations<->map_features FK가 필요해서
실제 등록은 Traffic Editor + /internal/v1/map-projects publish 과정을 거쳐야 함(관제팀
쪽에 Traffic Editor가 이미 있을 것으로 추정, 그쪽에서 이 파일 참고해서 등록하면 됨). 이
스크립트의 목적은 "관제팀이 옮겨적을 필요 없이 필드명 그대로 참고할 수 있게"까지만.

매핑 근거는 project_vlm_rl_fms_db_schema_mapping.md 메모 참고:
  safe_zone           -> location_type='safe_node'  (location_recovery_profiles 테이블 주석에서 확정)
  start_zone/end_zone -> location_type='charger'     (추정, 충전 가능하다고 확인됨)
  sub_sub_midgoal_N   -> location_type='slot' + temperature_zone(ambient/chilled/frozen)
  middle_goal_N       -> location_type='outbound_dock' (추정)
  bottleneck_N        -> map_features.feature_type='bottleneck'
  ArUco 마커           -> map_features.feature_type='fiducial', marker_code
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).parent
FMS_POINTS_PATH = HERE / "fms_feature_points.jsonl"
ARUCO_PATH = HERE / "aruco_recognition_distance_tests.jsonl"
OUTPUT_PATH = HERE / "fms_db_handoff.jsonl"

MAP_NAME = "final_map_08"

# label 접두어 -> (location_type, temperature_zone)
LABEL_TO_LOCATION_TYPE = {
    "safe_zone": ("safe_node", None),
    "start_zone": ("charger", None),
    "end_zone": ("charger", None),
    "middle_goal": ("outbound_dock", None),
    "sub_sub_midgoal_1": ("slot", "ambient"),   # 상온
    "sub_sub_midgoal_2": ("slot", "chilled"),   # 냉장
    "sub_sub_midgoal_3": ("slot", "frozen"),    # 냉동
}


def _location_type_for(label: str) -> tuple[str, str | None]:
    if label in LABEL_TO_LOCATION_TYPE:
        return LABEL_TO_LOCATION_TYPE[label]
    for prefix, val in LABEL_TO_LOCATION_TYPE.items():
        if label.startswith(prefix) and not label[len(prefix):].isdigit() is False:
            pass
    # start_zone_1/2, end_zone_1/2, middle_goal_1/2 처럼 번호 붙은 경우 접두어로 재확인
    for prefix in ("start_zone", "end_zone", "middle_goal"):
        if label.startswith(prefix):
            return LABEL_TO_LOCATION_TYPE[prefix]
    return ("waypoint", None)  # 매핑 안 되는 건 안전하게 범용 waypoint


def convert_locations() -> list[dict]:
    """locations 테이블 형태로 변환 -- bottleneck은 여기 안 넣음(map_features 쪽)."""
    rows = []
    if not FMS_POINTS_PATH.exists():
        return rows
    with FMS_POINTS_PATH.open() as f:
        for line in f:
            if not line.strip():
                continue
            e = json.loads(line)
            label = e.get("label", "")
            if label.startswith("bottleneck_"):
                continue  # map_features로 따로 처리
            location_type, temp_zone = _location_type_for(label)
            rows.append({
                "_target_table": "locations",
                "location_code": label,
                "location_type": location_type,
                "temperature_zone": temp_zone,
                "map_name": MAP_NAME,
                "rmf_waypoint_name": None,  # Traffic Editor에서 확정 시 채울 것
                "pose_x": e.get("map_x"),
                "pose_y": e.get("map_y"),
                "pose_yaw": e.get("map_yaw"),
                "state": "available",
                "metadata": {
                    "amcl_xy_stddev_m": e.get("amcl_xy_stddev_m"),
                    "radius_m": e.get("radius_m"),
                    "marker_id": e.get("marker_id"),
                    "measured_at": e.get("timestamp"),
                    "note_ko": e.get("note"),
                },
            })
    return rows


def convert_map_features() -> list[dict]:
    """map_features 테이블 형태로 변환 -- bottleneck(fms_feature_points.jsonl) +
    ArUco 마커(aruco_recognition_distance_tests.jsonl)."""
    rows = []
    if FMS_POINTS_PATH.exists():
        with FMS_POINTS_PATH.open() as f:
            for line in f:
                if not line.strip():
                    continue
                e = json.loads(line)
                label = e.get("label", "")
                if not label.startswith("bottleneck_"):
                    continue
                rows.append({
                    "_target_table": "map_features",
                    "feature_code": label,
                    "feature_type": "bottleneck",
                    "map_name": MAP_NAME,
                    "marker_code": None,
                    "geometry": {
                        "type": "circle",
                        "center": {"x": e.get("map_x"), "y": e.get("map_y")},
                        "radius_m": e.get("radius_m"),
                    },
                    "properties": {
                        "amcl_xy_stddev_m": e.get("amcl_xy_stddev_m"),
                        "measured_at": e.get("timestamp"),
                        "note_ko": e.get("note"),
                    },
                    "active": True,
                })
    if ARUCO_PATH.exists():
        with ARUCO_PATH.open() as f:
            for line in f:
                if not line.strip():
                    continue
                e = json.loads(line)
                if not str(e.get("label", "")).startswith("aruco_marker_"):
                    continue
                rows.append({
                    "_target_table": "map_features",
                    "feature_code": e.get("label"),
                    "feature_type": "fiducial",
                    "map_name": MAP_NAME,
                    "marker_code": e.get("marker_id"),
                    "geometry": {
                        "type": "point",
                        "x": e.get("map_x"),
                        "y": e.get("map_y"),
                    },
                    "properties": {
                        "dict": e.get("dict"),
                        "pixel_size_at_measure": e.get("pixel_size"),
                        "amcl_xy_stddev_m": e.get("amcl_xy_stddev_m"),
                        "measured_at": e.get("timestamp"),
                        "note_ko": e.get("note"),
                    },
                    "active": True,
                })
    return rows


def main() -> None:
    rows = convert_locations() + convert_map_features()
    with OUTPUT_PATH.open("w") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    n_loc = sum(1 for r in rows if r["_target_table"] == "locations")
    n_feat = sum(1 for r in rows if r["_target_table"] == "map_features")
    print(f"{OUTPUT_PATH} 생성 완료: locations {n_loc}개, map_features {n_feat}개")
    print("주의: 원본 fms_feature_points.jsonl/aruco_recognition_distance_tests.jsonl은 "
          "안 건드렸음. 이 출력은 관제팀 handoff 참고용, 직접 DB에 넣는 건 아님 "
          "(Traffic Editor + map-projects publish 과정 필요, 스크립트 docstring 참고).")


if __name__ == "__main__":
    main()
