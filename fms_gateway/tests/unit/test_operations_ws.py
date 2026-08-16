"""운영 WebSocket이 UI가 읽는 이벤트 계약 그대로 흘려보내는지 검증한다."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from fms_gateway.app.main import create_app
from fms_gateway.app.models import OperationEventView
from fms_gateway.app.operations_ws import (
    EVENT_FIELDS,
    FORBIDDEN_PROJECTION_KEYS,
    OperationEventTailer,
    serialize_event,
)
from fms_gateway.app.repositories import InMemoryFmsRepository


SEOUL = timezone(timedelta(hours=9))


def _event(event_id: int, **overrides) -> dict:
    event = {
        "event_id": event_id,
        "event_uuid": f"00000000-0000-0000-0000-{event_id:012d}",
        "occurred_at": datetime(2026, 8, 16, 12, 0, event_id, tzinfo=SEOUL),
        "actor_worker_id": None,
        "device_id": "PK_01",
        "job_id": 7,
        "job_step_id": 11,
        "incident_id": None,
        "severity": "info",
        "category": "operations",
        "event_type": "PATH_UPDATED",
        "message": None,
        "payload": {"robot_id": "PK_01"},
    }
    event.update(overrides)
    return event


class FakeSource:
    """`list_operation_events`처럼 최신순으로 돌려준다."""

    def __init__(self, events: list[dict] | None = None) -> None:
        self.events = list(events or [])
        self.calls: list[int] = []

    def list_operation_events(
        self, from_at, to_at, limit, before_at=None, before_event_id=None
    ) -> list[dict]:
        self.calls.append(limit)
        newest_first = sorted(
            self.events, key=lambda event: event["event_id"], reverse=True
        )
        return newest_first[:limit]


# --- 직렬화 계약 ---------------------------------------------------------------


def test_serialized_event_matches_the_public_view_model() -> None:
    serialized = serialize_event(_event(1))

    assert set(serialized) == set(EVENT_FIELDS)
    # UI의 OperationsEventDto가 읽는 필드와 정확히 같아야 한다.
    assert set(serialized) == set(OperationEventView.model_fields)


def test_timestamps_are_serialized_as_iso_strings() -> None:
    serialized = serialize_event(_event(1))

    assert isinstance(serialized["occurred_at"], str)
    assert datetime.fromisoformat(serialized["occurred_at"]).tzinfo is not None


def test_a_json_string_payload_is_decoded_for_the_ui() -> None:
    serialized = serialize_event(_event(1, payload='{"robot_id": "PK_02"}'))

    assert serialized["payload"] == {"robot_id": "PK_02"}


def test_an_undecodable_payload_becomes_null_instead_of_raw_text() -> None:
    serialized = serialize_event(_event(1, payload="{not json"))

    assert serialized["payload"] is None


def test_an_operator_authoring_layer_is_never_projected() -> None:
    for key in FORBIDDEN_PROJECTION_KEYS:
        with pytest.raises(ValueError, match=key):
            serialize_event(_event(1, payload={key: ["do-not-ship"]}))


# --- tailer ------------------------------------------------------------------


def test_only_events_newer_than_the_last_sent_one_are_returned() -> None:
    source = FakeSource([_event(1), _event(2)])
    tailer = OperationEventTailer(source)

    first = tailer.poll()
    assert [event["event_id"] for event in first] == [1, 2]
    assert tailer.last_event_id == 2

    source.events.append(_event(3))
    assert [event["event_id"] for event in tailer.poll()] == [3]
    # 새 이벤트가 없으면 아무것도 보내지 않는다.
    assert tailer.poll() == []


def test_events_are_sent_in_ascending_order_despite_newest_first_paging() -> None:
    source = FakeSource([_event(3), _event(1), _event(2)])

    sent = OperationEventTailer(source).poll()

    assert [event["event_id"] for event in sent] == [1, 2, 3]


def test_a_new_subscriber_does_not_replay_history() -> None:
    source = FakeSource([_event(1), _event(2), _event(3)])
    tailer = OperationEventTailer(source)

    tailer.start_from_latest()
    assert tailer.last_event_id == 3
    assert tailer.poll() == []

    source.events.append(_event(4))
    assert [event["event_id"] for event in tailer.poll()] == [4]


def test_starting_from_latest_on_an_empty_log_sends_everything_after_it() -> None:
    source = FakeSource([])
    tailer = OperationEventTailer(source)

    tailer.start_from_latest()
    assert tailer.last_event_id == 0

    source.events.append(_event(1))
    assert [event["event_id"] for event in tailer.poll()] == [1]


def test_page_size_must_be_positive() -> None:
    with pytest.raises(ValueError, match="page_size"):
        OperationEventTailer(FakeSource(), page_size=0)


# --- 실제 라우트 --------------------------------------------------------------


def test_the_public_route_streams_new_events_to_a_subscriber() -> None:
    """UI가 구독하는 경로가 실제로 존재하고 이벤트를 밀어 준다."""
    repository = InMemoryFmsRepository()
    client = TestClient(create_app(repository))

    with client.websocket_connect("/api/v1/operations/ws") as websocket:
        # 실제 쓰기 경로가 남기는 이벤트를 그대로 받는다.
        repository.create_job(
            {
                "job_code": "WS-1",
                "operation_type": "outbound",
                "priority": "normal",
                "context": {"source": "public_product_order"},
                "steps": [
                    {
                        "step_no": 10,
                        "action_type": "wait",
                        "executor_type": "fms",
                        "target_location_id": 99,
                        "input": {"wait_for": "worker_completion"},
                    }
                ],
            }
        )
        message = websocket.receive_json()

    assert message["event_type"] == "job.created"
    assert set(message) == set(EVENT_FIELDS)
    assert isinstance(message["event_id"], int)
