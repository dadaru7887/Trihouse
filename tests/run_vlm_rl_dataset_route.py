#!/usr/bin/env python3
"""PK_01 VLM+RL 데이터 수집용 단일 목적지/배치 자율주행 실행기.

기본값은 dry-run이다. 실제 움직임은 --execute --confirm-motion PK_01을
동시에 지정한 경우에만 Gateway에 job 생성/dispatch 요청을 보낸다.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


SUCCESS_STATE = "completed"
FAILURE_STATES = {"failed", "cancelled"}


class RouteError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="PK_01 단일 목적지 또는 배치 순회 VLM+RL 데이터 수집"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--target-location-id", type=int, metavar="ID")
    mode.add_argument("--location-ids", metavar="ID,ID,...")
    mode.add_argument("--all", action="store_true", help="DB 목적지를 location_id 순으로 순회")
    mode.add_argument("--list", action="store_true", help="DB 목적지만 조회하고 종료")
    parser.add_argument(
        "--api-base-url",
        default=os.environ.get("FMS_API_BASE_URL", "http://127.0.0.1:8080"),
    )
    parser.add_argument("--device-id", default="PK_01")
    parser.add_argument("--fleet-name", default="project1_pinky")
    parser.add_argument("--map-name", default="new_map_2")
    parser.add_argument("--mysql-container", default="trihouse-mysql")
    parser.add_argument("--docker-bin", default="docker", help=argparse.SUPPRESS)
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--timeout-seconds", type=float, default=600.0)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm-motion", metavar="DEVICE_ID")
    args = parser.parse_args()
    if args.execute and args.confirm_motion != args.device_id:
        parser.error(f"실제 주행에는 --confirm-motion {args.device_id} 이 필요합니다")
    if args.list and args.execute:
        parser.error("--list와 --execute는 함께 사용할 수 없습니다")
    if args.poll_seconds <= 0 or args.timeout_seconds <= 0:
        parser.error("poll/timeout 값은 0보다 커야 합니다")
    return args


def database_locations(args: argparse.Namespace) -> list[tuple[int, str, str, str]]:
    safe_map = args.map_name.replace("'", "''")
    sql = (
        "SELECT location_id,rmf_waypoint_name,pose_x,pose_y "
        "FROM trihouse_fms.locations "
        f"WHERE map_name='{safe_map}' AND rmf_waypoint_name IS NOT NULL "
        "ORDER BY location_id"
    )
    command = [
        args.docker_bin,
        "exec",
        args.mysql_container,
        "sh",
        "-lc",
        'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -N -B -e ' + json.dumps(sql),
    ]
    result = subprocess.run(command, text=True, capture_output=True)
    if result.returncode != 0:
        detail = result.stderr.strip() or "docker/mysql 조회 실패"
        raise RouteError(detail)
    locations: dict[int, tuple[int, str, str, str]] = {}
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        fields = line.split("\t")
        if len(fields) != 4:
            raise RouteError(f"예상하지 못한 location 조회 결과: {line}")
        location_id = int(fields[0])
        locations[location_id] = (location_id, fields[1], fields[2], fields[3])
    return [locations[key] for key in sorted(locations)]


def selected_route(args: argparse.Namespace) -> list[int]:
    if args.target_location_id is not None:
        route = [args.target_location_id]
    elif args.location_ids:
        try:
            route = [int(value.strip()) for value in args.location_ids.split(",")]
        except ValueError as error:
            raise RouteError("--location-ids는 쉼표로 구분한 정수여야 합니다") from error
    else:
        route = [location[0] for location in database_locations(args)]
    route = list(dict.fromkeys(route))
    if not route or any(location_id < 1 for location_id in route):
        raise RouteError("목적지 location_id가 없습니다")
    return route


def request_json(
    method: str,
    url: str,
    body: dict[str, object] | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, object]:
    data = None if body is None else json.dumps(body, separators=(",", ":")).encode()
    request_headers = {"Accept": "application/json", **(headers or {})}
    if data is not None:
        request_headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=request_headers, method=method)
    try:
        with urlopen(request, timeout=5) as response:
            return json.load(response)
    except HTTPError as error:
        detail = error.read().decode(errors="replace")
        raise RouteError(f"HTTP {error.code} {url}: {detail}") from error
    except (URLError, TimeoutError) as error:
        raise RouteError(f"Gateway 연결 실패 {url}: {error}") from error


def job_payload(run_id: str, location_id: int, args: argparse.Namespace) -> dict[str, object]:
    return {
        "job_code": run_id,
        "operation_type": "outbound",
        "priority": "normal",
        "requested_by": "W-CONTROL-01",
        "destination_location_id": location_id,
        "context": {
            "source": "vlm_rl_dataset_collection",
            "collection_run_id": run_id,
            "device_id": args.device_id,
        },
        "steps": [
            {
                "step_no": 10,
                "action_type": "navigate",
                "executor_type": "mobile",
                "target_location_id": location_id,
                "input": {"dependencies": [], "fleet_name": args.fleet_name},
            }
        ],
    }


def execute_destination(location_id: int, index: int, args: argparse.Namespace) -> int:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_id = f"vlmrl-pk01-{stamp}-{index:02d}-l{location_id}"
    base = args.api_base_url.rstrip("/")
    created = request_json(
        "POST", f"{base}/internal/v1/jobs", job_payload(run_id, location_id, args)
    )
    job_id = int(created["job_id"])
    step_id = int(created["steps"][0]["job_step_id"])
    print(f"CREATE location_id={location_id} job_id={job_id} step_id={step_id}", flush=True)
    dispatched = request_json(
        "POST",
        f"{base}/internal/v1/job-steps/{step_id}/dispatch",
        {"actor": "W-CONTROL-01", "assigned_device_id": args.device_id},
        {"Idempotency-Key": f"dataset-dispatch-{run_id}"},
    )
    print(
        f"DISPATCH job_id={job_id} channel={dispatched.get('channel')} "
        f"state={dispatched.get('state')}",
        flush=True,
    )
    deadline = time.monotonic() + args.timeout_seconds
    last_state = None
    while time.monotonic() < deadline:
        detail = request_json("GET", f"{base}/api/v1/jobs/{job_id}")
        state = str(detail.get("state"))
        if state != last_state:
            print(f"STATUS job_id={job_id} state={state}", flush=True)
            last_state = state
        if state == SUCCESS_STATE:
            return job_id
        if state in FAILURE_STATES:
            raise RouteError(f"job_id={job_id} location_id={location_id} state={state}")
        time.sleep(args.poll_seconds)
    raise RouteError(f"job_id={job_id} location_id={location_id} timeout")


def main() -> int:
    args = parse_args()
    try:
        if args.list:
            for location in database_locations(args):
                print("\t".join(str(value) for value in location))
            return 0
        route = selected_route(args)
        print(f"route={','.join(str(value) for value in route)} device={args.device_id}")
        if not args.execute:
            print("DRY-RUN: 실제 주행 없음. 실행 시 --execute --confirm-motion PK_01 추가")
            return 0
        request_json("GET", f"{args.api_base_url.rstrip('/')}/ready")
        for index, location_id in enumerate(route, start=1):
            execute_destination(location_id, index, args)
        print(f"PASS: {len(route)}개 목적지 순회 완료")
        return 0
    except (RouteError, KeyError, TypeError, ValueError) as error:
        print(f"FAIL: {error}", file=sys.stderr, flush=True)
        return 1
    except KeyboardInterrupt:
        print("STOP: 사용자 중단. 현재 job은 자동 취소되지 않았습니다.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
