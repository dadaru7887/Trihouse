"""P0 인수: 두 비상 fixture의 보류·카메라 선택·운영자 결정·재개 재계획.

Fixture 1은 이동 중 Pinky 전도, Fixture 2는 창고 내 전도다. 두 경우 모두
영향받은 작업이 즉시 보류되고, 원인에 맞는 카메라가 열리고, 두 가지 운영자
결정이 서로 다른 결과를 남긴다. `작업 계속 진행`은 같은 Job의 Nav2 경로를
다시 계산하고 RMF 일정을 다시 등록한다.
"""

from __future__ import annotations

import pytest

from control_tower.gateway.operations_feed import (
    CAMERA_FIXTURES,
    IncidentView,
    OperationsFeed,
    PathProjection,
    select_event_cameras,
)
from control_tower.rmf_adapter.path_schedule import (
    AssignedPathRequest,
    PathScheduleCoordinator,
    PlannedNavPath,
)
from control_tower.task_manager.emergency_workflow import (
    EmergencyDecision,
    EmergencyWorkflow,
)
from fms_gateway.app.operations_ws import OperationsBroadcaster


MAP_REVISION = "trihouse_test_01:test"


def _path(robot: str, *, y: float, path_hash: str) -> PlannedNavPath:
    return PlannedNavPath(
        request=AssignedPathRequest(
            job_step_id=7,
            assignment_revision=1,
            robot_name=robot,
            map_revision=MAP_REVISION,
            goal_pose=(4.0, y, 0.0),
        ),
        poses=((0.0, y, 0.0), (2.0, y, 0.0), (4.0, y, 0.0)),
        travel_time_s=4.0,
        path_hash=path_hash,
    )


@pytest.fixture
def workflow() -> EmergencyWorkflow:
    return EmergencyWorkflow()


def test_fixture_1_pinky_travel_fall_holds_work_and_opens_that_pinky_camera(
    workflow: EmergencyWorkflow,
) -> None:
    incident = workflow.open_fixture(
        "INC-PK-01", kind="PINKY_FALL", robot_id="PK_01", job_id="J-1"
    )

    assert incident.held is True
    assert incident.camera_ids == ("CAM-PK-01",)
    assert workflow.is_held("J-1") is True


def test_fixture_2_warehouse_fall_holds_work_and_opens_the_fixed_camera(
    workflow: EmergencyWorkflow,
) -> None:
    incident = workflow.open_fixture(
        "INC-WH-01", kind="WAREHOUSE_FALL", location_id="WH-FRZ-01", job_id="J-2"
    )

    assert incident.held is True
    assert incident.camera_ids == ("CAM-FIXED-02",)
    assert workflow.is_held("J-2") is True


def test_raising_the_alarm_confirms_the_incident_and_keeps_the_hold(
    workflow: EmergencyWorkflow,
) -> None:
    workflow.open_fixture(
        "INC-PK-01", kind="PINKY_FALL", robot_id="PK_01", job_id="J-1"
    )

    outcome = workflow.decide(
        "INC-PK-01",
        EmergencyDecision(worker_id="W-OP-01", decision="RAISE_ALARM", reason="fall"),
    )

    assert outcome.confirmed is True
    assert outcome.hold_released is False
    assert workflow.is_held("J-1") is True


def test_continuing_work_resumes_the_same_job_with_a_replan(
    workflow: EmergencyWorkflow,
) -> None:
    workflow.open_fixture(
        "INC-WH-01", kind="WAREHOUSE_FALL", location_id="WH-FRZ-01", job_id="J-2"
    )

    outcome = workflow.decide(
        "INC-WH-01",
        EmergencyDecision(
            worker_id="W-OP-02", decision="CONTINUE_WORK", reason="area is clear"
        ),
    )

    assert outcome.hold_released is True
    assert outcome.worker_id == "W-OP-02"
    assert outcome.reason == "area is clear"
    # 새 Job이 아니라 같은 Job이 이어진다.
    assert outcome.resumed_job_id == "J-2"
    assert outcome.recompute_nav2_path is True
    assert outcome.reregister_rmf_itinerary is True
    assert workflow.is_held("J-2") is False


def test_resuming_actually_replaces_the_registered_itinerary(
    workflow: EmergencyWorkflow,
) -> None:
    """재개는 예전 경로를 반납하고 새 경로를 다시 등록한다."""
    schedule = PathScheduleCoordinator()
    first = _path("PK_01", y=0.0, path_hash="before-incident")
    schedule.register(first, start_time_s=0.0)
    schedule.acquire_override("PK_01", reason_code="EMERGENCY_HOLD")

    workflow.open_fixture(
        "INC-PK-01", kind="PINKY_FALL", robot_id="PK_01", job_id="J-1"
    )
    ticket = schedule.hold_for_replan("PK_01", reason_code="EMERGENCY_HOLD")

    assert ticket.released_path_hash == "before-incident"
    assert schedule.registration("PK_01") is None
    assert schedule.override_holder() == ""

    outcome = workflow.decide(
        "INC-PK-01",
        EmergencyDecision(worker_id="W-OP-01", decision="CONTINUE_WORK", reason="ok"),
    )
    assert outcome.recompute_nav2_path is True

    replanned = _path("PK_01", y=1.0, path_hash="after-incident")
    schedule.register(replanned, start_time_s=10.0)

    assert schedule.registration("PK_01").path_hash == "after-incident"
    assert schedule.may_move("PK_01") is True


def test_closing_the_dialog_changes_nothing(workflow: EmergencyWorkflow) -> None:
    workflow.open_fixture(
        "INC-PK-01", kind="PINKY_FALL", robot_id="PK_01", job_id="J-1"
    )

    outcome = workflow.dismiss("INC-PK-01")

    assert outcome.confirmed is False
    assert outcome.hold_released is False
    assert workflow.is_held("J-1") is True
    assert workflow.decisions("INC-PK-01") == ()


def test_the_incident_is_projected_to_the_ui_with_its_camera() -> None:
    feed = OperationsFeed()
    feed.upsert_path(
        PathProjection(
            robot_id="PK_01",
            map_revision=MAP_REVISION,
            nav2_global_path=((0.0, 0.0), (4.0, 0.0)),
            nav2_local_path=(),
            actual_trail=((0.0, 0.0),),
            rmf_timed_trajectory=((0.0, 0.0, 0.0), (3.0, 4.0, 0.0)),
            goal_pose=(4.0, 0.0, 0.0),
        )
    )
    feed.open_incident(
        IncidentView(
            incident_id="INC-PK-01",
            camera_id=select_event_cameras(kind="PINKY_FALL", robot_id="PK_01")
            .camera_ids[0],
            location_id="",
            occurred_at_s=12.0,
            acknowledged=False,
        )
    )

    payload = OperationsBroadcaster(feed).snapshot_message()["payload"]

    assert payload["incidents"][0]["camera_id"] == "CAM-PK-01"
    assert len(payload["cameras"]) == len(CAMERA_FIXTURES) == 6
    # 내부 bootstrap graph는 운영자에게 나가지 않는다.
    assert payload["bootstrap_graph_visible"] is False


def test_p0_registers_six_cameras_without_connecting_them() -> None:
    assert len(CAMERA_FIXTURES) == 6
    assert all(camera.map_pose is None for camera in CAMERA_FIXTURES)
    assert all(
        camera.mediamtx_path.startswith("fixtures/") for camera in CAMERA_FIXTURES
    )
