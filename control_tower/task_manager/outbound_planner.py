"""Pure FEFO planning for product-only outbound orders.

The planner receives already resolved canonical inventory and active-map location
IDs.  It neither chooses hardware nor invents poses or routes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Mapping
import uuid


ZONE_ORDER = ("ambient", "chilled", "frozen")


@dataclass(frozen=True)
class OrderLine:
    line_no: int
    product_code: str
    quantity: int


@dataclass(frozen=True)
class OutboundOrder:
    order_identity: str
    external_reference: str | None
    requested_by: str
    priority: str
    allow_partial_fulfillment: bool
    items: tuple[OrderLine, ...]


@dataclass(frozen=True)
class InventoryLotSnapshot:
    lot_id: int
    lot_code: str
    product_code: str
    item_name: str | None
    temperature_zone: str
    slot_location_id: int
    available_qty: int
    reserved_qty: int
    expiry_date: date | None
    received_at: datetime | None

    @property
    def reservable_qty(self) -> int:
        return max(0, self.available_qty - self.reserved_qty)


@dataclass(frozen=True)
class PlanningLocations:
    zone_docks: Mapping[str, int]
    packing_docks: tuple[int, ...]
    charger_location_ids: tuple[int, ...]


@dataclass(frozen=True)
class LotAllocation:
    lot_id: int
    lot_code: str
    slot_location_id: int
    reserved_qty: int


@dataclass(frozen=True)
class PlannedLine:
    line_no: int
    product_code: str
    requested_qty: int
    reserved_qty: int
    outstanding_qty: int
    allocations: tuple[LotAllocation, ...]


@dataclass(frozen=True)
class PlannedItem:
    line_no: int
    product_code: str
    lot_id: int
    lot_code: str
    slot_location_id: int
    requested_qty: int
    reserved_qty: int
    outstanding_qty: int


@dataclass(frozen=True)
class ZoneBundle:
    handover_group_id: str
    temperature_zone: str
    dock_location_id: int
    items: tuple[PlannedItem, ...]


@dataclass(frozen=True)
class OutboundPlan:
    accepted: bool
    reason_code: str
    lines: tuple[PlannedLine, ...]
    bundles: tuple[ZoneBundle, ...]
    packing_dock_location_id: int | None
    charger_location_ids: tuple[int, ...]

    @property
    def requested_quantity(self) -> int:
        return sum(line.requested_qty for line in self.lines)

    @property
    def fulfillable_quantity(self) -> int:
        return sum(line.reserved_qty for line in self.lines)

    @property
    def outstanding_quantity(self) -> int:
        return sum(line.outstanding_qty for line in self.lines)


class OutboundPlanner:
    """Allocate lots deterministically and group allocations into zone visits."""

    def plan(
        self,
        order: OutboundOrder,
        inventory: tuple[InventoryLotSnapshot, ...],
        locations: PlanningLocations,
    ) -> OutboundPlan:
        self._validate_order(order)
        lots_by_product: dict[str, list[InventoryLotSnapshot]] = {}
        for candidate in inventory:
            lots_by_product.setdefault(candidate.product_code, []).append(candidate)
        for candidates in lots_by_product.values():
            candidates.sort(key=self._fefo_key)

        planned_lines: list[PlannedLine] = []
        zone_items: dict[str, list[PlannedItem]] = {zone: [] for zone in ZONE_ORDER}
        remaining_by_lot = {candidate.lot_id: candidate.reservable_qty for candidate in inventory}

        for requested in order.items:
            remaining = requested.quantity
            allocations: list[LotAllocation] = []
            for candidate in lots_by_product.get(requested.product_code, []):
                reservable = remaining_by_lot[candidate.lot_id]
                if reservable <= 0:
                    continue
                reserved = min(remaining, reservable)
                remaining_by_lot[candidate.lot_id] -= reserved
                remaining -= reserved
                allocations.append(
                    LotAllocation(
                        lot_id=candidate.lot_id,
                        lot_code=candidate.lot_code,
                        slot_location_id=candidate.slot_location_id,
                        reserved_qty=reserved,
                    )
                )
                zone_items[candidate.temperature_zone].append(
                    PlannedItem(
                        line_no=requested.line_no,
                        product_code=requested.product_code,
                        lot_id=candidate.lot_id,
                        lot_code=candidate.lot_code,
                        slot_location_id=candidate.slot_location_id,
                        requested_qty=requested.quantity,
                        reserved_qty=reserved,
                        outstanding_qty=0,
                    )
                )
                if remaining == 0:
                    break
            planned_lines.append(
                PlannedLine(
                    line_no=requested.line_no,
                    product_code=requested.product_code,
                    requested_qty=requested.quantity,
                    reserved_qty=requested.quantity - remaining,
                    outstanding_qty=remaining,
                    allocations=tuple(allocations),
                )
            )

        has_shortage = any(line.outstanding_qty for line in planned_lines)
        has_stock = any(line.reserved_qty for line in planned_lines)
        if not has_stock or (has_shortage and not order.allow_partial_fulfillment):
            return OutboundPlan(False, "INSUFFICIENT_STOCK", (), (), None, ())

        line_by_number = {line.line_no: line for line in planned_lines}
        bundles = []
        for zone in ZONE_ORDER:
            items = zone_items[zone]
            if not items:
                continue
            if zone not in locations.zone_docks:
                raise ValueError(f"active map has no loading dock for {zone}")
            last_index_by_line = {
                line_no: max(index for index, item in enumerate(items) if item.line_no == line_no)
                for line_no in {item.line_no for item in items}
            }
            normalized_items = tuple(
                PlannedItem(
                    **{
                        **item.__dict__,
                        "outstanding_qty": (
                            line_by_number[item.line_no].outstanding_qty
                            if last_index_by_line[item.line_no] == index
                            else 0
                        ),
                    }
                )
                for index, item in enumerate(items)
            )
            group_id = str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"trihouse:outbound:{order.order_identity}:{zone}",
                )
            )
            bundles.append(
                ZoneBundle(
                    handover_group_id=group_id,
                    temperature_zone=zone,
                    dock_location_id=int(locations.zone_docks[zone]),
                    items=normalized_items,
                )
            )
        if not locations.packing_docks:
            raise ValueError("active map has no packing dock")
        if not locations.charger_location_ids:
            raise ValueError("active map has no charger locations")
        return OutboundPlan(
            True,
            "",
            tuple(planned_lines),
            tuple(bundles),
            min(locations.packing_docks),
            tuple(sorted(locations.charger_location_ids)),
        )

    @staticmethod
    def _fefo_key(candidate: InventoryLotSnapshot) -> tuple[bool, date, bool, datetime, int]:
        return (
            candidate.expiry_date is None,
            candidate.expiry_date or date.max,
            candidate.received_at is None,
            candidate.received_at or datetime.max,
            candidate.lot_id,
        )

    @staticmethod
    def _validate_order(order: OutboundOrder) -> None:
        if not order.order_identity or not order.requested_by or not order.items:
            raise ValueError("order identity, requester, and at least one item are required")
        if order.priority not in {"normal", "high", "critical"}:
            raise ValueError("unsupported outbound priority")
        if len({item.line_no for item in order.items}) != len(order.items):
            raise ValueError("line numbers must be unique")
        if len({item.product_code for item in order.items}) != len(order.items):
            raise ValueError("products must be unique within an order")
        if any(
            item.line_no <= 0 or not item.product_code or item.quantity <= 0
            for item in order.items
        ):
            raise ValueError("each order line needs a product and positive quantity")
