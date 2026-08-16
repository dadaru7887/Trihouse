"""P0 인수: 동시 주문 두 건이 서로 다른 로봇/Dock으로 배정되고 통로에서 충돌하지 않는다.

배정과 자원 예약은 실제 MySQL 트랜잭션으로 확인하고, 경로 등록·bottleneck
lease·15초 우회는 Control Tower 정책으로 확인한다. Gazebo/Nav2 실제 모션은
`scripts/control_stack up` 으로 스택이 떠 있을 때만 의미가 있으므로, 여기서는
그 앞단 계약까지를 결정적으로 검증한다.
"""

from __future__ import annotations

import json

import pytest

from control_tower.rmf_adapter.bottleneck import (
    BottleneckCoordinator,
    BottleneckZone,
    RobotFootprint,
)
from control_tower.rmf_adapter.path_schedule import (
    AssignedPathRequest,
    PathScheduleCoordinator,
    PlannedNavPath,
)
from control_tower.rmf_adapter.task_api import GoToPlaceRequest, build_dispatch_request
from e2e_support import requires_mysql  # type: ignore
from test_outbound_order_repository import DEMO_ORDERS, install_active_map, rows  # type: ignore
from test_read_api import real_client  # type: ignore
from test_worker_completion_repository import _repository  # type: ignore

from fms_gateway.app.repositories import ResourceUnavailable


PINKY = RobotFootprint(radius_m=0.11, safety_margin_m=0.05, stopping_distance_m=0.09)
MAP_REVISION = "trihouse_test_01:test"


def _assignment(mobile: str, omx: str, dock: str, charger: str) -> dict:
    return {
        "revision": 1,
        "mobile_id": mobile,
        "omx_id": omx,
        "packing_dock_code": dock,
        "charger_code": charger,
    }


def _path(robot: str, *, start_x: float, end_x: float, y: float) -> PlannedNavPath:
    span = end_x - start_x
    return PlannedNavPath(
        request=AssignedPathRequest(
            job_step_id=7,
            assignment_revision=1,
            robot_name=robot,
            map_revision=MAP_REVISION,
            goal_pose=(end_x, y, 0.0),
        ),
        poses=tuple(
            (start_x + span * index / 4.0, y, 0.0) for index in range(5)
        ),
        travel_time_s=4.0,
        path_hash=f"{robot}-{start_x}-{end_x}-{y}",
    )


# --- 실제 MySQL 배정 ----------------------------------------------------------


@pytest.mark.integration
@requires_mysql
def test_two_concurrent_orders_get_distinct_robots_arms_and_docks(
    seeded_schema,
) -> None:
    install_active_map()
    client = real_client()
    job_ids = []
    for index, example in enumerate((DEMO_ORDERS[5], DEMO_ORDERS[1])):
        request = dict(example["request"])
        request["external_reference"] = f"E2E-TRAFFIC-{index}"
        response = client.post(
            "/api/v1/orders",
            headers={"Idempotency-Key": f"e2e-traffic-{index}"},
            json=request,
        )
        assert response.status_code == 201
        job_ids.append(response.json()["job_id"])

    repository = _repository()
    repository.assign_job_resources(
        job_ids[0],
        _assignment("PK_01", "OMX_01", "PACKING-01-DOCK-01", "TRIHOUSE-TEST-01-CHG-01"),
    )
    repository.assign_job_resources(
        job_ids[1],
        _assignment("PK_02", "OMX_02", "PACKING-01-DOCK-02", "TRIHOUSE-TEST-01-CHG-02"),
    )

    assignments = []
    for job_id in job_ids:
        raw = rows("SELECT context FROM jobs WHERE job_id=%s", (job_id,))[0]["context"]
        context = json.loads(raw) if isinstance(raw, str) else raw
        assignments.append(context["assignment"])

    assert {item["mobile_id"] for item in assignments} == {"PK_01", "PK_02"}
    assert {item["omx_id"] for item in assignments} == {"OMX_01", "OMX_02"}
    assert len({item["packing_dock_code"] for item in assignments}) == 2
    # 충전기는 로봇에 고정되어 있다.
    assert {item["mobile_id"]: item["charger_code"] for item in assignments} == {
        "PK_01": "TRIHOUSE-TEST-01-CHG-01",
        "PK_02": "TRIHOUSE-TEST-01-CHG-02",
    }


@pytest.mark.integration
@requires_mysql
def test_a_second_job_cannot_take_a_reserved_robot(seeded_schema) -> None:
    install_active_map()
    client = real_client()
    job_ids = []
    # 두 주문은 서로 다른 품목을 쓴다. 재고 부족이 아니라 자원 경합을 본다.
    for index, example in enumerate((DEMO_ORDERS[5], DEMO_ORDERS[1])):
        request = dict(example["request"])
        request["external_reference"] = f"E2E-CONTENTION-{index}"
        response = client.post(
            "/api/v1/orders",
            headers={"Idempotency-Key": f"e2e-contention-{index}"},
            json=request,
        )
        assert response.status_code == 201
        job_ids.append(response.json()["job_id"])

    repository = _repository()
    assignment = _assignment(
        "PK_01", "OMX_01", "PACKING-01-DOCK-01", "TRIHOUSE-TEST-01-CHG-01"
    )
    repository.assign_job_resources(job_ids[0], assignment)

    with pytest.raises(ResourceUnavailable):
        repository.assign_job_resources(job_ids[1], assignment)


# --- 경로 등록과 통행 ---------------------------------------------------------


def test_no_robot_moves_before_its_itinerary_clears() -> None:
    schedule = PathScheduleCoordinator()

    assert schedule.may_move("PK_01") is False
    schedule.register(_path("PK_01", start_x=0.0, end_x=4.0, y=0.0), start_time_s=0.0)
    assert schedule.may_move("PK_01") is True


def test_head_on_paths_hold_the_later_robot_until_the_first_clears() -> None:
    schedule = PathScheduleCoordinator()
    schedule.register(_path("PK_01", start_x=0.0, end_x=4.0, y=0.0), start_time_s=0.0)
    schedule.register(_path("PK_02", start_x=4.0, end_x=0.0, y=0.0), start_time_s=0.0)

    blocked = schedule.clearance("PK_02")
    assert blocked.cleared is False
    assert blocked.conflict_with == "PK_01"

    schedule.release("PK_01")
    assert schedule.clearance("PK_02").cleared is True


def test_each_dispatch_pins_its_own_robot() -> None:
    payloads = [
        build_dispatch_request(
            GoToPlaceRequest(
                request_id=f"req-{robot}",
                job_step_id=7,
                waypoint="packing_station_loading_dock_01",
                fleet_name="trihouse_pinky",
                robot_name=robot,
                request_time_ms=1,
            )
        )["request"]
        for robot in ("PK_01", "PK_02")
    ]

    assert [payload["robot_name"] for payload in payloads] == ["PK_01", "PK_02"]
    assert all(payload["fleet_name"] == "trihouse_pinky" for payload in payloads)


def test_first_arrival_holds_the_bottleneck_and_a_detour_is_tried_after_15s() -> None:
    coordinator = BottleneckCoordinator(
        zones=(
            BottleneckZone("bottleneck_01", x=0.841, y=-0.111),
            BottleneckZone("bottleneck_02", x=0.367, y=-0.762),
        )
    )

    assert coordinator.request("PK_02", "bottleneck_01", at_s=0).acquired is True
    denied = coordinator.request("PK_01", "bottleneck_01", at_s=1, priority="critical")
    assert denied.acquired is False
    assert denied.holder == "PK_02"

    assert (
        coordinator.poll("PK_01", "bottleneck_01", at_s=14.0).detour_requested is False
    )
    assert coordinator.poll("PK_01", "bottleneck_01", at_s=16.0).detour_requested is True

    # 유효한 우회가 없으면 계속 기다린다.
    coordinator.record_detour("PK_01", "bottleneck_01", valid=False, at_s=17.0)
    assert coordinator.is_waiting("PK_01", "bottleneck_01") is True

    coordinator.release(
        "PK_02", "bottleneck_01", robot_x=0.841, robot_y=2.0, footprint=PINKY
    )
    assert coordinator.request("PK_01", "bottleneck_01", at_s=20.0).acquired is True


def test_an_emergency_stop_inside_the_passage_keeps_the_lease() -> None:
    coordinator = BottleneckCoordinator(
        zones=(BottleneckZone("bottleneck_02", x=0.367, y=-0.762),)
    )
    coordinator.request("PK_01", "bottleneck_02", at_s=0)
    coordinator.hold("PK_01", "bottleneck_02", reason_code="EMERGENCY_STOP")

    assert (
        coordinator.release(
            "PK_01", "bottleneck_02", robot_x=9.0, robot_y=9.0, footprint=PINKY
        )
        is False
    )
    assert coordinator.request("PK_02", "bottleneck_02", at_s=5).acquired is False


def test_the_two_robots_never_hold_a_stubborn_override_together() -> None:
    schedule = PathScheduleCoordinator()

    assert schedule.acquire_override("PK_01", reason_code="BOTTLENECK_WAIT") is True
    assert schedule.acquire_override("PK_02", reason_code="BOTTLENECK_WAIT") is False
    schedule.release_override("PK_01")
    assert schedule.acquire_override("PK_02", reason_code="BOTTLENECK_WAIT") is True
