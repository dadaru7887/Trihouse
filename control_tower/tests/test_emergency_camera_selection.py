"""사건 원인이 여는 카메라와 두 비상 fixture의 운영자 결정."""

import pytest

from control_tower.gateway.operations_feed import (
    CAMERA_FIXTURES,
    CameraSelection,
    OperationsFeed,
    PathProjection,
    RobotView,
    select_event_cameras,
)
from control_tower.task_manager.emergency_workflow import (
    EmergencyDecision,
    EmergencyWorkflow,
)


# --- 카메라 선택 --------------------------------------------------------------


def test_six_camera_fixtures_are_registered() -> None:
    assert len(CAMERA_FIXTURES) == 6
    assert {camera.role for camera in CAMERA_FIXTURES} == {
        "pinky_travel", "omx_wrist", "warehouse_fixed",
    }
    # P1 캘리브레이션 전까지 지도 좌표는 없다.
    assert all(camera.map_pose is None for camera in CAMERA_FIXTURES)


def test_pinky_travel_fall_selects_that_pinky_camera() -> None:
    selection = select_event_cameras(kind="PINKY_FALL", robot_id="PK_01")

    assert selection == CameraSelection(("CAM-PK-01",), auto_close_on_success=False)


def test_the_other_pinky_fall_selects_its_own_camera() -> None:
    assert select_event_cameras(kind="PINKY_FALL", robot_id="PK_02").camera_ids == (
        "CAM-PK-02",
    )


def test_warehouse_fall_selects_the_relevant_fixed_camera() -> None:
    selection = select_event_cameras(kind="WAREHOUSE_FALL", location_id="WH-AMB-01")

    assert selection.camera_ids == ("CAM-FIXED-01",)
    assert selection.auto_close_on_success is False


def test_pick_and_load_open_the_omx_wrist_and_its_fixed_camera() -> None:
    selection = select_event_cameras(
        kind="OMX_LOAD", omx_id="OMX_01", location_id="WH-AMB-01"
    )

    assert selection.camera_ids == ("CAM-OMX-01-WRIST", "CAM-FIXED-01")
    # 성공하면 자동으로 닫히고, 재시도/드랍/불확실/비상에서는 열려 있다.
    assert selection.auto_close_on_success is True


def test_manual_normal_travel_request_opens_the_pinky_camera() -> None:
    selection = select_event_cameras(kind="MANUAL_TRAVEL_VIEW", robot_id="PK_02")

    assert selection.camera_ids == ("CAM-PK-02",)
    assert selection.auto_close_on_success is True


def test_pinky_camera_is_never_selected_as_omx_load_evidence() -> None:
    selection = select_event_cameras(
        kind="OMX_LOAD", omx_id="OMX_02", location_id="WH-FRZ-01"
    )

    assert not any(camera_id.startswith("CAM-PK-") for camera_id in selection.camera_ids)


def test_unknown_event_kind_opens_no_camera() -> None:
    assert select_event_cameras(kind="UNKNOWN").camera_ids == ()


def test_fall_without_its_subject_is_rejected_instead_of_guessed() -> None:
    with pytest.raises(ValueError, match="robot_id"):
        select_event_cameras(kind="PINKY_FALL")
    with pytest.raises(ValueError, match="location_id"):
        select_event_cameras(kind="WAREHOUSE_FALL")


# --- 운영 투영 ----------------------------------------------------------------


def test_projection_prefers_the_actual_nav2_path_and_hides_bootstrap_graph() -> None:
    feed = OperationsFeed()
    feed.upsert_robot(
        RobotView(
            robot_id="PK_01", x=1.0, y=2.0, yaw=0.0, battery_percent=88.0,
            safety_state="normal", job_id="J-1", stage="navigate", error="",
        )
    )
    feed.upsert_path(
        PathProjection(
            robot_id="PK_01",
            map_revision="trihouse_test_01:7",
            nav2_global_path=((0.0, 0.0), (1.0, 2.0)),
            nav2_local_path=((1.0, 2.0),),
            actual_trail=((0.0, 0.0), (0.5, 1.0), (1.0, 2.0)),
            rmf_timed_trajectory=((0.0, 0.0, 0.0), (4.0, 4.0, 4.0)),
            goal_pose=(4.0, 4.0, 1.57),
        )
    )
    snapshot = feed.snapshot()

    assert snapshot.paths[0].nav2_global_path
    assert snapshot.paths[0].actual_trail
    assert snapshot.bootstrap_graph_visible is False


def test_path_schedule_mismatch_holds_the_robot() -> None:
    feed = OperationsFeed(path_tolerance_m=0.25)
    feed.upsert_path(
        PathProjection(
            robot_id="PK_01",
            map_revision="trihouse_test_01:7",
            nav2_global_path=((0.0, 0.0), (4.0, 0.0)),
            nav2_local_path=(),
            actual_trail=(),
            # (t_s, x, y): RMF ends 3 m away from the Nav2 goal.
            rmf_timed_trajectory=((0.0, 0.0, 0.0), (3.0, 4.0, 3.0)),
            goal_pose=(4.0, 0.0, 0.0),
        )
    )

    events = feed.drain_events()
    mismatch = [event for event in events if event.kind == "PATH_SCHEDULE_MISMATCH"]
    assert len(mismatch) == 1
    assert feed.is_held("PK_01") is True


def test_matching_paths_do_not_hold_the_robot() -> None:
    feed = OperationsFeed(path_tolerance_m=0.25)
    feed.upsert_path(
        PathProjection(
            robot_id="PK_01",
            map_revision="trihouse_test_01:7",
            nav2_global_path=((0.0, 0.0), (4.0, 0.0)),
            nav2_local_path=(),
            actual_trail=(),
            # (t_s, x, y): RMF ends exactly at the Nav2 goal.
            rmf_timed_trajectory=((0.0, 0.0, 0.0), (3.0, 4.0, 0.0)),
            goal_pose=(4.0, 0.0, 0.0),
        )
    )

    assert feed.is_held("PK_01") is False
    assert not [
        event for event in feed.drain_events()
        if event.kind == "PATH_SCHEDULE_MISMATCH"
    ]


# --- 두 비상 fixture ----------------------------------------------------------


@pytest.fixture
def workflow() -> EmergencyWorkflow:
    return EmergencyWorkflow()


def test_pinky_fall_fixture_holds_work_and_opens_that_pinky_camera(
    workflow: EmergencyWorkflow,
) -> None:
    incident = workflow.open_fixture(
        "INC-1", kind="PINKY_FALL", robot_id="PK_01", job_id="J-1"
    )

    assert incident.held is True
    assert incident.camera_ids == ("CAM-PK-01",)
    assert workflow.is_held("J-1") is True


def test_warehouse_fall_fixture_holds_work_and_opens_the_fixed_camera(
    workflow: EmergencyWorkflow,
) -> None:
    incident = workflow.open_fixture(
        "INC-2", kind="WAREHOUSE_FALL", location_id="WH-CHL-01", job_id="J-2"
    )

    assert incident.held is True
    assert incident.camera_ids == ("CAM-FIXED-01",)


def test_raise_alarm_confirms_the_incident_and_preserves_the_hold(
    workflow: EmergencyWorkflow,
) -> None:
    workflow.open_fixture("INC-1", kind="PINKY_FALL", robot_id="PK_01", job_id="J-1")

    outcome = workflow.decide(
        "INC-1",
        EmergencyDecision(
            worker_id="W-1", decision="RAISE_ALARM", reason="fallen pinky"
        ),
    )

    assert outcome.confirmed is True
    assert outcome.hold_released is False
    assert outcome.resumed_job_id == ""
    assert workflow.is_held("J-1") is True


def test_continue_work_records_the_worker_and_resumes_the_same_job(
    workflow: EmergencyWorkflow,
) -> None:
    workflow.open_fixture("INC-1", kind="PINKY_FALL", robot_id="PK_01", job_id="J-1")

    outcome = workflow.decide(
        "INC-1",
        EmergencyDecision(
            worker_id="W-9", decision="CONTINUE_WORK", reason="false positive"
        ),
    )

    assert outcome.confirmed is False
    assert outcome.hold_released is True
    assert outcome.worker_id == "W-9"
    assert outcome.reason == "false positive"
    # 재개는 새 Job이 아니라 같은 Job의 경로 재계산과 RMF 재등록이다.
    assert outcome.resumed_job_id == "J-1"
    assert outcome.recompute_nav2_path is True
    assert outcome.reregister_rmf_itinerary is True
    assert workflow.is_held("J-1") is False


def test_closing_the_dialog_does_nothing(workflow: EmergencyWorkflow) -> None:
    workflow.open_fixture("INC-1", kind="PINKY_FALL", robot_id="PK_01", job_id="J-1")

    outcome = workflow.dismiss("INC-1")

    assert outcome.confirmed is False
    assert outcome.hold_released is False
    assert workflow.is_held("J-1") is True
    # 닫기는 감사 기록도 남기지 않는다.
    assert workflow.decisions("INC-1") == ()


def test_decision_requires_a_worker_and_a_supported_choice(
    workflow: EmergencyWorkflow,
) -> None:
    workflow.open_fixture("INC-1", kind="PINKY_FALL", robot_id="PK_01", job_id="J-1")

    with pytest.raises(ValueError, match="worker_id"):
        workflow.decide(
            "INC-1", EmergencyDecision(worker_id=" ", decision="RAISE_ALARM", reason="x")
        )
    with pytest.raises(ValueError, match="decision"):
        workflow.decide(
            "INC-1",
            EmergencyDecision(worker_id="W-1", decision="IGNORE", reason="x"),
        )


def test_repeated_decision_returns_the_recorded_first_outcome(
    workflow: EmergencyWorkflow,
) -> None:
    workflow.open_fixture("INC-1", kind="PINKY_FALL", robot_id="PK_01", job_id="J-1")
    first = workflow.decide(
        "INC-1",
        EmergencyDecision(worker_id="W-1", decision="CONTINUE_WORK", reason="ok"),
    )
    replay = workflow.decide(
        "INC-1",
        EmergencyDecision(worker_id="W-2", decision="RAISE_ALARM", reason="changed"),
    )

    assert replay == first
    assert len(workflow.decisions("INC-1")) == 1
