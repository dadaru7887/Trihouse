"""SR 재고 확정 규칙을 검증하는 메모리 기반 참조 구현.

운영 DB repository는 이 전이를 transaction으로 저장해야 하며, 이 클래스는 ROS/UI에 의존하지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass
class StockLot:
    lot_id: str
    item_id: str
    quantity: int
    expiry: date
    zone: str
    shelf_id: str
    slot_id: str
    reserved: int = 0


@dataclass
class Slot:
    zone: str
    shelf_id: str
    slot_id: str
    reserved_by: str | None = None
    occupied_by: str | None = None


class InventoryWorkflow:
    def __init__(self) -> None:
        self._lots: dict[str, StockLot] = {}
        self._slots: dict[tuple[str, str], Slot] = {}
        self._job_slots: dict[str, Slot] = {}
        self._outbound: dict[str, dict[str, int]] = {}
        self._finalized: set[str] = set()
        self.steps: dict[str, list[str]] = {}

    def add_slot(self, zone: str, shelf_id: str, slot_id: str) -> None:
        self._slots[(shelf_id, slot_id)] = Slot(zone, shelf_id, slot_id)

    def add_lot(self, lot: StockLot) -> None:
        if lot.lot_id in self._lots:
            raise ValueError(f'duplicate lot {lot.lot_id}')
        self._lots[lot.lot_id] = lot

    def record_step(self, job_id: str, step: str) -> None:
        self.steps.setdefault(job_id, []).append(step)

    def available_quantity(self, item_id: str) -> int:
        return sum(lot.quantity - lot.reserved for lot in self._lots.values() if lot.item_id == item_id)

    def physical_quantity(self, item_id: str) -> int:
        """원본 재고 수량이다. 예약만으로 이 값이 바뀌면 안 된다."""
        return sum(lot.quantity for lot in self._lots.values() if lot.item_id == item_id)

    def reserve_inbound_slot(self, job_id: str, zone: str) -> tuple[str, str]:
        if job_id in self._job_slots:
            slot = self._job_slots[job_id]
            return slot.shelf_id, slot.slot_id
        candidates = sorted((slot for slot in self._slots.values() if slot.zone == zone and slot.reserved_by is None and slot.occupied_by is None), key=lambda slot: (slot.shelf_id, slot.slot_id))
        if not candidates:
            raise ValueError(f'no available slot in {zone}')
        slot = candidates[0]; slot.reserved_by = job_id; self._job_slots[job_id] = slot
        return slot.shelf_id, slot.slot_id

    def cancel_job(self, job_id: str) -> None:
        if job_id in self._finalized:
            return
        slot = self._job_slots.pop(job_id, None)
        if slot is not None and slot.reserved_by == job_id:
            slot.reserved_by = None
        for lot_id, quantity in self._outbound.pop(job_id, {}).items():
            self._lots[lot_id].reserved -= quantity
        self.record_step(job_id, 'CANCELED')

    def reserve_outbound(self, job_id: str, item_id: str, quantity: int) -> tuple[str, ...]:
        if quantity <= 0:
            raise ValueError('quantity must be positive')
        if job_id in self._outbound:
            return tuple(self._outbound[job_id])
        remaining = quantity; reservation: dict[str, int] = {}
        candidates = sorted((lot for lot in self._lots.values() if lot.item_id == item_id and lot.quantity > lot.reserved), key=lambda lot: (lot.expiry, lot.shelf_id, lot.slot_id))
        for lot in candidates:
            take = min(remaining, lot.quantity - lot.reserved)
            if take:
                lot.reserved += take; reservation[lot.lot_id] = take; remaining -= take
            if remaining == 0:
                break
        if remaining:
            for lot_id, reserved in reservation.items(): self._lots[lot_id].reserved -= reserved
            raise ValueError('insufficient available inventory')
        self._outbound[job_id] = reservation
        self.record_step(job_id, 'OUTBOUND_RESERVED')
        return tuple(reservation)

    def finalize_outbound(self, job_id: str, delivered: dict[str, int]) -> None:
        if job_id in self._finalized:
            return
        reservation = self._outbound.get(job_id)
        if reservation is None:
            raise ValueError('job has no outbound reservation')
        for lot_id, quantity in delivered.items():
            if quantity < 0 or quantity > reservation.get(lot_id, 0):
                raise ValueError('delivered quantity exceeds reservation')
        for lot_id, reserved in reservation.items():
            delivered_quantity = delivered.get(lot_id, 0)
            lot = self._lots[lot_id]; lot.quantity -= delivered_quantity; lot.reserved -= reserved
        self._finalized.add(job_id); self.record_step(job_id, 'OUTBOUND_FINALIZED')

    def finalize_inbound(self, job_id: str, lot_id: str, item_id: str, quantity: int, expiry: date) -> None:
        if job_id in self._finalized:
            return
        slot = self._job_slots.get(job_id)
        if slot is None:
            raise ValueError('job has no inbound slot reservation')
        if quantity <= 0 or lot_id in self._lots:
            raise ValueError('invalid inbound lot')
        self._lots[lot_id] = StockLot(lot_id, item_id, quantity, expiry, slot.zone, slot.shelf_id, slot.slot_id)
        slot.reserved_by = None; slot.occupied_by = lot_id; self._finalized.add(job_id); self.record_step(job_id, 'INBOUND_FINALIZED')

    def location_of(self, lot_id: str) -> tuple[str, str]:
        lot = self._lots[lot_id]
        return lot.shelf_id, lot.slot_id
