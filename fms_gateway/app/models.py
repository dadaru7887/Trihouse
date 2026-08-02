"""Public FMS API response models."""

from datetime import date, datetime

from pydantic import BaseModel


class DeviceView(BaseModel):
    device_id: str
    device_type: str
    name: str
    control_mode: str
    state: str | None = None
    health: str | None = None
    battery_pct: float | None = None
    observed_at: datetime | None = None


class InventoryLotView(BaseModel):
    lot_id: int
    lot_code: str
    product_code: str
    item_name: str | None = None
    temperature_zone: str
    location_code: str | None = None
    expiry_date: date
    available_qty: int
    reserved_qty: int
    state: str


class JobView(BaseModel):
    job_id: int
    job_code: str
    operation_type: str
    priority: str
    state: str
    due_at: datetime | None = None
    assigned_mobile_id: str | None = None
    item_count: int
    step_count: int
