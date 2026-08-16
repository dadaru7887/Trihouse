"""운영 WebSocket 투영이 실제 경로를 1차 정보로 내보내는지 검증한다."""

import asyncio

import pytest

from control_tower.gateway.operations_feed import (
    IncidentView,
    JobView,
    OperationsFeed,
    PathProjection,
    RobotView,
)
from fms_gateway.app.operations_ws import (
    FORBIDDEN_PROJECTION_KEYS,
    OPERATIONS_EVENT_KINDS,
    OperationsBroadcaster,
)


@pytest.fixture
def feed() -> OperationsFeed:
    feed = OperationsFeed(path_tolerance_m=0.25)
    feed.upsert_robot(
        RobotView(
            robot_id="PK_01", x=1.0, y=2.0, yaw=0.5, battery_percent=91.0,
            safety_state="normal", job_id="J-1", stage="navigate", error="",
        )
    )
    feed.upsert_job(
        JobView(
            job_id="J-1", order_id="O-1", item_ids=("I-1",),
            robot_id="PK_01", stage="navigate", state="running",
        )
    )
    feed.upsert_path(
        PathProjection(
            robot_id="PK_01",
            map_revision="trihouse_test_01:7",
            nav2_global_path=((0.0, 0.0), (4.0, 0.0)),
            nav2_local_path=((1.0, 0.0),),
            actual_trail=((0.0, 0.0), (1.0, 0.0)),
            rmf_timed_trajectory=((0.0, 0.0, 0.0), (3.0, 4.0, 0.0)),
            goal_pose=(4.0, 0.0, 0.0),
        )
    )
    feed.open_incident(
        IncidentView(
            incident_id="INC-1", camera_id="CAM-PK-01", location_id="WH-AMB-01",
            occurred_at_s=10.0, acknowledged=False,
        )
    )
    return feed


def test_snapshot_carries_actual_paths_cameras_and_no_bootstrap_graph(
    feed: OperationsFeed,
) -> None:
    message = OperationsBroadcaster(feed).snapshot_message()
    payload = message["payload"]

    assert message["kind"] == "SNAPSHOT"
    assert payload["paths"][0]["nav2_global_path"] == [[0.0, 0.0], [4.0, 0.0]]
    assert payload["paths"][0]["actual_trail"] == [[0.0, 0.0], [1.0, 0.0]]
    assert payload["paths"][0]["rmf_timed_trajectory"]
    assert payload["bootstrap_graph_visible"] is False
    assert len(payload["cameras"]) == 6
    assert all(camera["map_pose"] is None for camera in payload["cameras"])
    assert payload["robots"][0]["battery_percent"] == 91.0
    assert payload["incidents"][0]["incident_id"] == "INC-1"


def test_projection_never_leaks_an_operator_bootstrap_layer(
    feed: OperationsFeed,
) -> None:
    encoded = str(OperationsBroadcaster(feed).snapshot_message())

    for key in FORBIDDEN_PROJECTION_KEYS:
        assert f"'{key}'" not in encoded


def test_subscriber_receives_the_snapshot_then_incremental_events(
    feed: OperationsFeed,
) -> None:
    broadcaster = OperationsBroadcaster(feed)
    queue = broadcaster.subscribe()
    feed.drain_events()  # 구독 전 이벤트는 스냅숏에 이미 반영되어 있다.

    feed.upsert_path(
        PathProjection(
            robot_id="PK_01",
            map_revision="trihouse_test_01:7",
            nav2_global_path=((0.0, 0.0), (4.0, 0.0)),
            nav2_local_path=(),
            actual_trail=(),
            # RMF 일정이 Nav2 목표와 3 m 어긋난다.
            rmf_timed_trajectory=((0.0, 0.0, 0.0), (3.0, 4.0, 3.0)),
            goal_pose=(4.0, 0.0, 0.0),
        )
    )
    published = broadcaster.publish_pending()

    assert queue.get_nowait()["kind"] == "SNAPSHOT"
    kinds = [message["kind"] for message in published]
    assert "PATH_UPDATED" in kinds
    assert "PATH_SCHEDULE_MISMATCH" in kinds
    assert feed.is_held("PK_01") is True
    assert [queue.get_nowait()["kind"] for _ in published] == kinds


def test_only_known_event_kinds_reach_the_ui(feed: OperationsFeed) -> None:
    broadcaster = OperationsBroadcaster(feed)
    published = broadcaster.publish_pending()

    assert published
    assert all(message["kind"] in OPERATIONS_EVENT_KINDS for message in published)


def test_unsubscribed_queue_stops_receiving(feed: OperationsFeed) -> None:
    broadcaster = OperationsBroadcaster(feed)
    queue = broadcaster.subscribe()
    queue.get_nowait()
    broadcaster.unsubscribe(queue)

    feed.upsert_robot(
        RobotView(
            robot_id="PK_02", x=0.0, y=0.0, yaw=0.0, battery_percent=50.0,
            safety_state="normal", job_id="", stage="idle", error="",
        )
    )
    broadcaster.publish_pending()

    with pytest.raises(asyncio.QueueEmpty):
        queue.get_nowait()
