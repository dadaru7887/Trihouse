"""FastAPI entry point for the only MySQL-writing FMS process."""

from fastapi import FastAPI, Header, HTTPException

from .config import get_settings
from .database import Database
from .models import DeviceView, InventoryAdjustment, InventoryLotView, JobView
from .repositories import (
    FmsRepository,
    IdempotencyConflict,
    InventoryLotNotFound,
    InventoryQuantityConflict,
    MySqlFmsRepository,
)


def _default_repository() -> MySqlFmsRepository:
    return MySqlFmsRepository(Database(get_settings()))


def create_app(repository: FmsRepository | None = None) -> FastAPI:
    app = FastAPI(title="Trihouse FMS Gateway", version="0.1.0")
    repo = repository or _default_repository()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    def ready() -> dict[str, str]:
        try:
            if not repo.ping():
                raise RuntimeError("database ping failed")
        except Exception as error:
            raise HTTPException(status_code=503, detail="database unavailable") from error
        return {"status": "ready", "database": "ok"}

    @app.get("/api/v1/devices", response_model=list[DeviceView])
    def devices():
        return repo.list_devices()

    @app.get("/api/v1/inventory/lots", response_model=list[InventoryLotView])
    def inventory():
        return repo.list_inventory()

    @app.post(
        "/api/v1/inventory/lots/{lot_id}/adjust",
        response_model=InventoryLotView,
    )
    def adjust_inventory(
        lot_id: int,
        adjustment: InventoryAdjustment,
        idempotency_key: str = Header(min_length=1, max_length=160),
    ):
        try:
            return repo.adjust_inventory(
                lot_id,
                adjustment.quantity_delta,
                adjustment.recorded_by,
                adjustment.note,
                idempotency_key,
            )
        except InventoryLotNotFound as error:
            raise HTTPException(status_code=404, detail="inventory lot not found") from error
        except InventoryQuantityConflict as error:
            raise HTTPException(
                status_code=409,
                detail="available quantity cannot be below reserved quantity",
            ) from error
        except IdempotencyConflict as error:
            raise HTTPException(
                status_code=409,
                detail="idempotency key was already used for another request",
            ) from error

    @app.get("/api/v1/jobs", response_model=list[JobView])
    def jobs():
        return repo.list_jobs()

    return app
