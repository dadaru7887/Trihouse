
import os

import pytest
from fastapi.testclient import TestClient

from fms_gateway.app.config import Settings
from fms_gateway.app.database import Database
from fms_gateway.app.main import create_app
from fms_gateway.app.repositories import MySqlFmsRepository


pytestmark = pytest.mark.integration


def real_client() -> TestClient:
    settings = Settings(
        host=os.environ.get("FMS_DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("FMS_DB_PORT", "3307")),
        user=os.environ.get("FMS_DB_USER", "root"),
        password=os.environ.get("FMS_DB_PASSWORD", ""),
        database="trihouse_fms",
        pool_size=2,
    )
    repository = MySqlFmsRepository(Database(settings))
    return TestClient(create_app(repository))


def test_readiness_and_seeded_read_endpoints(seeded_schema):
    client = real_client()

    assert client.get("/ready").status_code == 200

    devices = client.get("/api/v1/devices")
    inventory = client.get("/api/v1/inventory/lots")
    jobs = client.get("/api/v1/jobs")

    assert devices.status_code == 200
    assert {row["device_id"] for row in devices.json()} == {
        "PK_01",
        "PK_02",
        "OMX_01",
        "OMX_02",
    }
    assert inventory.status_code == 200
    assert {row["lot_code"] for row in inventory.json()} == {
        "LOT-AMB-ORANGE-001",
        "LOT-AMB-STRAWBERRY-001",
        "LOT-AMB-MANDARIN-001",
        "LOT-CHL-COFFEE-001",
        "LOT-CHL-SANDWICH-001",
        "LOT-CHL-YOGURT-001",
        "LOT-CHL-MILK-001",
        "LOT-FRZ-PORKBELLY-001",
        "LOT-FRZ-DUMPLING-001",
        "LOT-FRZ-ICEBAR-001",
        "LOT-FRZ-ICECONE-001",
    }
    assert [row["lot_code"] for row in inventory.json()[:3]] == [
        "LOT-AMB-STRAWBERRY-001",
        "LOT-AMB-ORANGE-001",
        "LOT-AMB-MANDARIN-001",
    ]
    assert jobs.status_code == 200
    assert jobs.json()[0]["job_code"] == "JOB-DEV-001"
    assert jobs.json()[0]["due_at"].endswith("+09:00")
