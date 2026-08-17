"""Wire contract for the reservation-recovery boundary.

취소·만료 회수·이상 승인은 모두 Gateway 가 한다. Control Tower 는 DB 를 만지지
않는다 — 행 잠금과 상태 전이 불변식이 Gateway 저장소 안에 있어서, 두 곳에서 같은
전이를 하면 어긋나기 때문이다.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError

import pytest

from control_tower.gateway.fms_client import FMSGatewayHttpClient

from control_tower.tests.test_fms_gateway_client import RecordingOpener, _Response


def _client(opener: Any) -> FMSGatewayHttpClient:
    return FMSGatewayHttpClient("http://127.0.0.1:18080", opener=opener)


def _sent(opener: RecordingOpener) -> Any:
    return opener.requests[-1][0]


def test_cancel_job_posts_the_reason_with_a_required_idempotency_key() -> None:
    opener = RecordingOpener(
        _Response(
            {
                "job_id": 2,
                "state": "cancelled",
                "cancelled_step_ids": [20, 30],
                "cancelled_reservation_ids": [1, 2, 3],
                "released_device_ids": ["OMX_01", "PK_01"],
            },
            200,
        )
    )

    result = _client(opener).cancel_job(
        2,
        reason="P0 hardware test cleanup",
        requested_by="W-OP-01",
        idempotency_key="cancel-job-2",
    )

    request = _sent(opener)
    assert request.full_url == "http://127.0.0.1:18080/internal/v1/jobs/2/cancel"
    assert request.get_header("Idempotency-key") == "cancel-job-2"
    assert json.loads(request.data) == {
        "reason": "P0 hardware test cleanup",
        "requested_by": "W-OP-01",
    }
    assert result["released_device_ids"] == ["OMX_01", "PK_01"]


def test_expire_reservations_posts_to_the_sweep_route() -> None:
    opener = RecordingOpener(_Response({"expired": []}, 200))

    result = _client(opener).expire_reservations()

    assert _sent(opener).full_url == (
        "http://127.0.0.1:18080/internal/v1/reservations/expire"
    )
    assert result == {"expired": []}


def test_open_anomalies_are_read_from_the_operations_route() -> None:
    opener = RecordingOpener(
        _Response(
            [
                {
                    "correlation_uuid": "aaaaaaaa-0000-0000-0000-000000000001",
                    "job_id": 2,
                    "device_id": "PK_01",
                    "occurred_at": "2026-08-18T02:00:00+09:00",
                    "message": "released while the job still had work left",
                    "payload": {"reservation_id": 2},
                }
            ],
            200,
        )
    )

    anomalies = _client(opener).list_open_anomalies()

    assert _sent(opener).full_url == (
        "http://127.0.0.1:18080/api/v1/operations/anomalies?state=open"
    )
    assert [anomaly["job_id"] for anomaly in anomalies] == [2]


def test_acknowledging_names_the_person_who_closed_it() -> None:
    opener = RecordingOpener(
        _Response(
            {
                "correlation_uuid": "aaaaaaaa-0000-0000-0000-000000000001",
                "job_id": 2,
                "acknowledged_by": "W-OP-01",
                "note": "robot was parked",
            },
            200,
        )
    )

    result = _client(opener).acknowledge_anomaly(
        "aaaaaaaa-0000-0000-0000-000000000001",
        worker_id="W-OP-01",
        note="robot was parked",
    )

    request = _sent(opener)
    assert request.full_url == (
        "http://127.0.0.1:18080/api/v1/operations/anomalies/"
        "aaaaaaaa-0000-0000-0000-000000000001/acknowledge"
    )
    assert json.loads(request.data) == {
        "worker_id": "W-OP-01",
        "note": "robot was parked",
    }
    assert result["acknowledged_by"] == "W-OP-01"


class _MissingOpener:
    def open(self, request: Any, timeout: float) -> Any:
        raise HTTPError(request.full_url, 404, "Not Found", {}, None)  # type: ignore[arg-type]


def test_acknowledging_something_that_is_not_open_raises_lookup_error() -> None:
    """관제 UI 서버가 이 예외를 404 로 옮긴다 — 그 계약을 여기서 못박는다."""
    with pytest.raises(LookupError):
        _client(_MissingOpener()).acknowledge_anomaly(
            "ffffffff-0000-0000-0000-000000000000", worker_id="W-OP-01", note=""
        )
