
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from fms_gateway.app.main import create_app


SEOUL = ZoneInfo("Asia/Seoul")


class FakeRepository:
    def ping(self) -> bool:
        return True

    def list_devices(self):
        return [
            {
                "device_id": "PINKY-01",
                "device_type": "mobile",
                "name": "Pinky-Pro #1",
                "control_mode": "automatic",
                "state": "idle",
                "health": "ok",
                "battery_pct": 92.0,
                "observed_at": datetime(2026, 8, 3, 9, tzinfo=SEOUL),
            }
        ]

    def list_inventory(self):
        return [
            {
                "lot_id": 1,
                "lot_code": "LOT-DEV-001",
                "product_code": "SKU-AMBIENT-001",
                "item_name": "개발용 상온 상품 A",
                "temperature_zone": "ambient",
                "location_code": "A-SLOT-01",
                "expiry_date": date(2027, 1, 31),
                "available_qty": 100,
                "reserved_qty": 5,
                "state": "stored",
            }
        ]

    def list_jobs(self):
        return [
            {
                "job_id": 1,
                "job_code": "JOB-DEV-001",
                "operation_type": "outbound",
                "priority": "normal",
                "state": "pending",
                "due_at": datetime(2026, 8, 3, 10, tzinfo=SEOUL),
                "assigned_mobile_id": "PINKY-01",
                "item_count": 1,
                "step_count": 1,
            }
        ]


def test_health_and_readiness_contracts():
    client = TestClient(create_app(FakeRepository()))

    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/ready").json() == {"status": "ready", "database": "ok"}


def test_devices_inventory_and_jobs_contracts():
    client = TestClient(create_app(FakeRepository()))

    devices = client.get("/api/v1/devices")
    inventory = client.get("/api/v1/inventory/lots")
    jobs = client.get("/api/v1/jobs")

    assert devices.status_code == 200
    assert devices.json()[0]["device_id"] == "PINKY-01"
    assert devices.json()[0]["observed_at"] == "2026-08-03T09:00:00+09:00"
    assert inventory.status_code == 200
    assert inventory.json()[0]["lot_code"] == "LOT-DEV-001"
    assert inventory.json()[0]["expiry_date"] == "2027-01-31"
    assert jobs.status_code == 200
    assert jobs.json()[0]["item_count"] == 1
    assert jobs.json()[0]["due_at"] == "2026-08-03T10:00:00+09:00"


def test_zero_inventory_adjustment_is_rejected_before_repository_call():
    client = TestClient(create_app(FakeRepository()))

    response = client.post(
        "/api/v1/inventory/lots/1/adjust",
        headers={"Idempotency-Key": "zero-adjustment"},
        json={"quantity_delta": 0, "recorded_by": "W-OP-01"},
    )

    assert response.status_code == 422
