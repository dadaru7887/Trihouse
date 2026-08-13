#!/usr/bin/env python3
"""Control System export를 canonical FMS map-project API로 가져온다.

기본 동작은 DB를 바꾸지 않는 dry-run이다. ``--apply``를 줘야 draft를 저장하고,
``--publish``는 nav graph와 world의 hash까지 묶어 운영 projection을 갱신한다.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any
from urllib import error, request

import yaml


PROJECT1_LOCATION_CODES = {
    "픽업1": "A-SLOT-01",
    "드랍오프1": "OUT-DOCK-01",
    "충전1": "CHG-01",
    "충전2": "CHG-02",
    "대기1": "IN-WAIT-01",
    "대기3": "NARROW-WAIT-01",
    "설비1": "OMX-WS-01",
    "설비2": "OMX-WS-02",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _value(parameters: dict[str, Any], name: str, default: Any = None) -> Any:
    wrapped = parameters.get(name)
    if isinstance(wrapped, list) and len(wrapped) >= 2:
        return wrapped[1]
    return default


def _reference_scale(level: dict[str, Any]) -> float:
    measurements = level.get("measurements") or []
    vertices = level.get("vertices") or []
    if not measurements:
        raise ValueError("reference_image 지도에는 실제 길이 measurement가 필요합니다")
    start, end, parameters = measurements[0]
    distance = float(_value(parameters, "distance"))
    x1, y1 = map(float, vertices[int(start)][:2])
    x2, y2 = map(float, vertices[int(end)][:2])
    pixel_distance = math.hypot(x2 - x1, y2 - y1)
    if pixel_distance <= 0 or distance <= 0:
        raise ValueError("measurement 길이는 0보다 커야 합니다")
    return distance / pixel_distance


def _category(name: str) -> str:
    if name not in PROJECT1_LOCATION_CODES:
        return "일반"
    for prefix, category in (
        ("충전", "충전"),
        ("대기", "대기"),
        ("픽업", "픽업"),
        ("드랍오프", "드랍오프"),
        ("설비", "설비"),
    ):
        if name.startswith(prefix):
            return category
    return "일반"


def _robot(row: dict[str, Any], seq: int) -> dict[str, Any]:
    station = row.get("home_charger") or row.get("station")
    return {
        "robot_id": str(row["id"]),
        "seq": seq,
        "display_name": str(row.get("name") or row["id"]),
        "model": str(row.get("model") or "unknown"),
        "kind": str(row.get("kind") or "mobile"),
        "data_source": str(row.get("data_source") or "gazebo"),
        "gz_name": str(row.get("gz_name") or row["id"]),
        "zones": [str(value) for value in row.get("zones") or []],
        "charger_waypoint_name": station,
        "spawn_x": row.get("spawn_x"),
        "spawn_y": row.get("spawn_y"),
        "spawn_heading": float(row.get("spawn_heading") or 0.0),
    }


def build_project_request(building_path: Path, fleet_path: Path | None) -> dict[str, Any]:
    building = yaml.safe_load(building_path.read_text(encoding="utf-8"))
    map_name = str(building["name"])
    level_name = str(building.get("reference_level_name") or next(iter(building["levels"])))
    level = building["levels"][level_name]
    scale = _reference_scale(level)
    raw_vertices = level.get("vertices") or []
    first_measurement = (level.get("measurements") or [])[0]
    measure_start, measure_end, measure_parameters = first_measurement
    measured_distance = float(_value(measure_parameters, "distance"))
    measurement_indices = {
        int(index)
        for measurement in (level.get("measurements") or [])
        for index in measurement[:2]
    }
    waypoints: list[dict[str, Any]] = []
    by_index: dict[int, dict[str, Any]] = {}
    for index, vertex in enumerate(raw_vertices):
        if index in measurement_indices:
            continue
        name = str(vertex[3]).strip() if len(vertex) >= 4 else ""
        if not name or name.startswith("measurement_"):
            continue
        x, y, yaw = float(vertex[0]), float(vertex[1]), float(vertex[2])
        waypoint = {
            "point": [x, y],
            "mapPose": [x * scale, -y * scale, yaw],
            "name": name,
            "rmfWaypointName": name,
            "category": _category(name),
        }
        location_code = PROJECT1_LOCATION_CODES.get(name) if map_name == "project1" else None
        if location_code:
            waypoint["locationCode"] = location_code
        waypoints.append(waypoint)
        by_index[index] = waypoint

    lanes: list[dict[str, Any]] = []
    for start_index, end_index, parameters in level.get("lanes") or []:
        start = by_index.get(int(start_index))
        end = by_index.get(int(end_index))
        if start is None or end is None:
            continue
        lanes.append(
            {
                "start": start["point"],
                "end": end["point"],
                "direction": "양방향"
                if bool(_value(parameters, "bidirectional", False))
                else "정방향",
            }
        )

    walls = [
        [
            [float(raw_vertices[int(start)][0]), float(raw_vertices[int(start)][1])],
            [float(raw_vertices[int(end)][0]), float(raw_vertices[int(end)][1])],
        ]
        for start, end, _parameters in (level.get("walls") or [])
    ]
    editor_lanes = [[lane["start"], lane["end"]] for lane in lanes]

    drawing_name = str((level.get("drawing") or {}).get("filename") or "")
    drawing_path = building_path.parent / drawing_name
    drawing: dict[str, Any] = {"name": drawing_name}
    if drawing_name:
        drawing["extension"] = drawing_path.suffix.lstrip(".")
    if drawing_path.is_file():
        raw = drawing_path.read_bytes()
        drawing.update({"size": len(raw), "bytes": base64.b64encode(raw).decode("ascii")})

    fleet_data = (
        yaml.safe_load(fleet_path.read_text(encoding="utf-8")) if fleet_path else {}
    ) or {}
    robots = [
        _robot(row, seq)
        for seq, row in enumerate(fleet_data.get("robots") or [], start=1)
    ]
    fleet_name = str(fleet_data.get("fleet_name") or f"{map_name}_pinky")
    return {
        "format_version": 2,
        "payload": {
            "format": "robosapiens-map-project",
            "version": 2,
            "mapName": map_name,
            "drawing": drawing,
            "stage": 6,
            "measurement": {
                "start": [
                    float(raw_vertices[int(measure_start)][0]),
                    float(raw_vertices[int(measure_start)][1]),
                ],
                "end": [
                    float(raw_vertices[int(measure_end)][0]),
                    float(raw_vertices[int(measure_end)][1]),
                ],
                "length": measured_distance,
                "unit": "m",
            },
            "wallMask": None,
            "floorMask": None,
            "previousWallMask": None,
            "wallsDetected": bool(walls),
            "floorGenerated": bool(level.get("floors")),
            "wallColor": 0xFF2563EB,
            "floorColor": 0xFF22C55E,
            "manualWalls": walls,
            "wallVertexOverrides": [],
            "frozenAutoWalls": [],
            "recommendedLanes": editor_lanes,
            "waypoints": waypoints,
            "laneDirections": lanes,
            "activeLaneEndpoint": None,
        },
        "building_yaml": building_path.read_text(encoding="utf-8"),
        "building_yaml_name": building_path.name,
        "files": [],
        "fleet": {"fleet_name": fleet_name, "settings": {"fleetName": fleet_name}},
        "robots": robots,
    }


def _json_request(
    method: str,
    url: str,
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> Any:
    payload = None if body is None else json.dumps(body, ensure_ascii=False).encode()
    http_request = request.Request(
        url,
        data=payload,
        method=method,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            **(headers or {}),
        },
    )
    try:
        with request.urlopen(http_request, timeout=15) as response:
            return json.loads(response.read().decode())
    except error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"FMS Gateway {exc.code}: {detail}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("building_yaml", type=Path)
    parser.add_argument("--fleet-yaml", type=Path)
    parser.add_argument("--fms-url", default="http://127.0.0.1:8080")
    parser.add_argument("--apply", action="store_true", help="draft를 Gateway에 저장")
    parser.add_argument("--publish", action="store_true", help="저장 후 artifact revision 배포")
    parser.add_argument("--nav-graph", type=Path)
    parser.add_argument("--world", type=Path)
    parser.add_argument("--published-by", default="cli")
    args = parser.parse_args(argv)

    if args.publish:
        if not args.nav_graph or not args.world:
            parser.error("--publish에는 --nav-graph와 --world가 필요합니다")
        for artifact in (args.building_yaml, args.nav_graph, args.world):
            if not artifact.is_file():
                parser.error(f"artifact 파일이 없습니다: {artifact}")

    project = build_project_request(args.building_yaml, args.fleet_yaml)
    map_name = project["payload"]["mapName"]
    summary = {
        "mode": "apply" if args.apply or args.publish else "dry-run",
        "map_name": map_name,
        "waypoint_count": len(project["payload"]["waypoints"]),
        "lane_count": len(project["payload"]["laneDirections"]),
        "robot_count": len(project["robots"]),
        "operational_locations": {
            value["rmfWaypointName"]: value["locationCode"]
            for value in project["payload"]["waypoints"]
            if value.get("locationCode")
        },
    }
    if not args.apply and not args.publish:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    base = args.fms_url.rstrip("/")
    project_url = f"{base}/internal/v1/map-projects/{map_name}"
    current = None
    try:
        current = _json_request("GET", project_url)
    except RuntimeError as exc:
        if "FMS Gateway 404:" not in str(exc):
            raise
    if args.apply:
        if current:
            # UI가 생성한 files/fleet/robots를 importer가 빈 기본값으로 지우지 않는다.
            for key in ("files", "fleet", "robots"):
                project[key] = current.get(key) or project[key]
        saved = _json_request(
            "PUT",
            project_url,
            project,
            headers={"If-Match": f'"{current["draft_revision"]}"'} if current else None,
        )
        summary["draft_revision"] = saved["draft_revision"]
    elif args.publish:
        if current is None:
            raise RuntimeError("publish할 draft가 없습니다. 먼저 --apply를 실행하세요")
        summary["draft_revision"] = current["draft_revision"]
    validation = _json_request(
        "POST", f"{base}/internal/v1/map-projects/{map_name}/validate", {}
    )
    summary["validation"] = validation
    if not validation["valid"]:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 2
    if args.publish:
        building_content = args.building_yaml.read_text(encoding="utf-8")
        nav_graph_content = args.nav_graph.read_text(encoding="utf-8")
        world_content = args.world.read_text(encoding="utf-8")
        hashes = {
            "building_sha256": sha256_file(args.building_yaml),
            "nav_graph_sha256": sha256_file(args.nav_graph),
            "world_sha256": sha256_file(args.world),
        }
        content = json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode()
        map_revision = f"{map_name}:{hashlib.sha256(content).hexdigest()}"
        published = _json_request(
            "POST",
            f"{base}/internal/v1/map-projects/{map_name}/publish",
            {
                "map_revision": map_revision,
                **hashes,
                "building_yaml_content": building_content,
                "nav_graph_yaml_content": nav_graph_content,
                "world_content": world_content,
                "published_by": args.published_by,
                "manifest": {
                    "building_yaml": str(args.building_yaml),
                    "nav_graph": str(args.nav_graph),
                    "world": str(args.world),
                },
            },
        )
        summary["published"] = published
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
