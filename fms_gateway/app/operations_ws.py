"""운영 화면이 구독하는 공개 WebSocket 투영.

UI는 DB·RMF·ROS를 직접 보지 않는다. 이 모듈은 `operation_events` 행을
`OperationEventView`와 **같은 모양**으로 직렬화해 새 이벤트만 순서대로
내보낸다. UI의 `OperationsEventDto.fromJson`이 그대로 읽는 계약이다.

`list_operation_events`는 최신순으로 페이지를 돌려주므로, tailer가 마지막으로
보낸 `event_id` 이후 것만 골라 오름차순으로 다시 정렬해 보낸다. 같은 이벤트를
두 번 보내지 않는다.

내부 bootstrap graph, nav graph, lane 같은 저작 레이어는 어떤 메시지에도
싣지 않는다. 지도 화면의 1차 정보는 Nav2가 실제로 계산한 경로와 로봇이 지나온
궤적이며, 그 값들은 이벤트 `payload`로 전달된다.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Iterable, Protocol


# UI가 해석하는 이벤트 필드. `OperationEventView`와 1:1로 맞춘다.
EVENT_FIELDS = (
    "event_id",
    "event_uuid",
    "occurred_at",
    "actor_worker_id",
    "device_id",
    "job_id",
    "job_step_id",
    "incident_id",
    "severity",
    "category",
    "event_type",
    "message",
    "payload",
)

# 운영자 레이어가 아니므로 어떤 메시지에도 실리지 않는다.
FORBIDDEN_PROJECTION_KEYS = ("bootstrap_graph", "nav_graph", "lanes")

# 한 번에 훑는 최신 이벤트 수. 폴링 간격 안에 이보다 많이 쌓이면 다음 폴링이
# 이어서 가져간다.
DEFAULT_PAGE_SIZE = 200


class OperationEventSource(Protocol):
    def list_operation_events(
        self,
        from_at: datetime | None,
        to_at: datetime | None,
        limit: int,
        before_at: datetime | None = None,
        before_event_id: int | None = None,
    ) -> list[dict[str, Any]]: ...


def serialize_event(event: dict[str, Any]) -> dict[str, Any]:
    """한 행을 UI가 읽는 JSON 안전 형태로 바꾼다."""
    payload = {field: event.get(field) for field in EVENT_FIELDS}
    occurred_at = payload.get("occurred_at")
    if isinstance(occurred_at, datetime):
        payload["occurred_at"] = occurred_at.isoformat()
    raw = payload.get("payload")
    if isinstance(raw, (str, bytes, bytearray)):
        try:
            payload["payload"] = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload["payload"] = None
    return _guard(payload)


class OperationEventTailer:
    """마지막으로 보낸 event_id 이후의 이벤트만 오름차순으로 돌려준다."""

    def __init__(
        self,
        source: OperationEventSource,
        *,
        page_size: int = DEFAULT_PAGE_SIZE,
        last_event_id: int = 0,
    ) -> None:
        if page_size <= 0:
            raise ValueError("page_size must be positive")
        self._source = source
        self._page_size = page_size
        self._last_event_id = last_event_id

    @property
    def last_event_id(self) -> int:
        return self._last_event_id

    def start_from_latest(self) -> None:
        """구독 시점 이전의 과거 이벤트를 다시 흘려보내지 않는다."""
        newest = self._source.list_operation_events(None, None, 1)
        if newest:
            self._last_event_id = int(newest[0]["event_id"])

    def poll(self) -> list[dict[str, Any]]:
        events = self._source.list_operation_events(None, None, self._page_size)
        fresh = [
            event
            for event in events
            if int(event["event_id"]) > self._last_event_id
        ]
        if not fresh:
            return []
        fresh.sort(key=lambda event: int(event["event_id"]))
        self._last_event_id = int(fresh[-1]["event_id"])
        return [serialize_event(event) for event in fresh]


def _guard(message: dict[str, Any]) -> dict[str, Any]:
    """운영자에게 내보내면 안 되는 키가 실렸는지 확인한다."""
    encoded = json.dumps(message, ensure_ascii=False, default=str)
    for key in FORBIDDEN_PROJECTION_KEYS:
        if f'"{key}"' in encoded:
            raise ValueError(f"{key} must never be projected to the operations UI")
    return message


def guard_all(messages: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_guard(message) for message in messages]


__all__ = [
    "DEFAULT_PAGE_SIZE",
    "EVENT_FIELDS",
    "FORBIDDEN_PROJECTION_KEYS",
    "OperationEventSource",
    "OperationEventTailer",
    "guard_all",
    "serialize_event",
]
