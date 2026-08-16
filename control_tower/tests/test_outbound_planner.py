"""Product-only outbound planning contract tests."""

from datetime import date, datetime

from control_tower.task_manager.outbound_planner import (
    InventoryLotSnapshot,
    OrderLine,
    OutboundOrder,
    OutboundPlanner,
    PlanningLocations,
)
from control_tower.task_manager.outbound_sequence import planned_outbound_steps


LOCATIONS = PlanningLocations(
    zone_docks={"ambient": 101, "chilled": 102, "frozen": 103},
    packing_docks=(201, 202),
    charger_location_ids=(301, 302),
)


def lot(
    lot_id: int,
    product_code: str,
    zone: str,
    slot_location_id: int,
    available_qty: int,
    *,
    expiry_date: date | None,
    received_at: datetime | None,
) -> InventoryLotSnapshot:
    return InventoryLotSnapshot(
        lot_id=lot_id,
        lot_code=f"LOT-{lot_id}",
        product_code=product_code,
        item_name=product_code,
        temperature_zone=zone,
        slot_location_id=slot_location_id,
        available_qty=available_qty,
        reserved_qty=0,
        expiry_date=expiry_date,
        received_at=received_at,
    )


def order(*lines: tuple[str, int], allow_partial: bool = False) -> OutboundOrder:
    return OutboundOrder(
        order_identity="job-identity-001",
        external_reference="ORDER-001",
        requested_by="W-OP-01",
        priority="normal",
        allow_partial_fulfillment=allow_partial,
        items=tuple(
            OrderLine(line_no=index, product_code=code, quantity=quantity)
            for index, (code, quantity) in enumerate(lines, start=1)
        ),
    )


def test_full_only_shortage_rejects_the_entire_plan_without_allocations() -> None:
    """Removing the full-order shortage branch would leak partial allocations."""
    planner = OutboundPlanner()

    result = planner.plan(
        order(("SKU-ORANGE", 2)),
        (
            lot(
                1,
                "SKU-ORANGE",
                "ambient",
                11,
                1,
                expiry_date=date(2026, 8, 28),
                received_at=datetime(2026, 8, 1),
            ),
        ),
        LOCATIONS,
    )

    assert result.accepted is False
    assert result.reason_code == "INSUFFICIENT_STOCK"
    assert result.bundles == ()
    assert result.lines == ()


def test_fefo_uses_expiry_null_last_received_time_and_lot_id_ties() -> None:
    """Changing any FEFO key must change this hand-derived allocation order."""
    planner = OutboundPlanner()
    inventory = (
        lot(40, "SKU-MILK", "chilled", 14, 1, expiry_date=None, received_at=None),
        lot(
            30,
            "SKU-MILK",
            "chilled",
            13,
            1,
            expiry_date=date(2026, 8, 20),
            received_at=datetime(2026, 8, 3),
        ),
        lot(
            20,
            "SKU-MILK",
            "chilled",
            12,
            1,
            expiry_date=date(2026, 8, 20),
            received_at=datetime(2026, 8, 2),
        ),
        lot(
            10,
            "SKU-MILK",
            "chilled",
            11,
            1,
            expiry_date=date(2026, 8, 20),
            received_at=datetime(2026, 8, 2),
        ),
    )

    result = planner.plan(order(("SKU-MILK", 4)), inventory, LOCATIONS)

    assert [allocation.lot_id for allocation in result.lines[0].allocations] == [
        10,
        20,
        30,
        40,
    ]


def test_zone_order_and_two_ambient_products_make_one_pinky_visit() -> None:
    """Grouping by shelf instead of zone would create a duplicate ambient visit."""
    planner = OutboundPlanner()
    inventory = (
        lot(1, "SKU-ORANGE", "ambient", 11, 1, expiry_date=date(2026, 8, 28), received_at=None),
        lot(2, "SKU-MANDARIN", "ambient", 12, 1, expiry_date=date(2026, 9, 2), received_at=None),
        lot(3, "SKU-MILK", "chilled", 13, 1, expiry_date=date(2026, 9, 20), received_at=None),
        lot(4, "SKU-ICEBAR", "frozen", 14, 1, expiry_date=date(2027, 8, 25), received_at=None),
    )

    result = planner.plan(
        order(
            ("SKU-ORANGE", 1),
            ("SKU-MANDARIN", 1),
            ("SKU-MILK", 1),
            ("SKU-ICEBAR", 1),
        ),
        inventory,
        LOCATIONS,
    )

    assert [bundle.temperature_zone for bundle in result.bundles] == [
        "ambient",
        "chilled",
        "frozen",
    ]
    assert [item.product_code for item in result.bundles[0].items] == [
        "SKU-ORANGE",
        "SKU-MANDARIN",
    ]
    assert len({bundle.handover_group_id for bundle in result.bundles}) == 3


def test_opt_in_partial_records_literal_outstanding_quantity() -> None:
    """Order-time partial stock must retain the exact missing quantity per line."""
    result = OutboundPlanner().plan(
        order(("SKU-SANDWICH", 3), ("SKU-ICEBAR", 1), allow_partial=True),
        (
            lot(
                1,
                "SKU-SANDWICH",
                "chilled",
                11,
                2,
                expiry_date=date(2026, 9, 10),
                received_at=None,
            ),
            lot(2, "SKU-ICEBAR", "frozen", 12, 1, expiry_date=date(2027, 8, 25), received_at=None),
        ),
        LOCATIONS,
    )

    assert result.accepted is True
    totals = [
        (line.requested_qty, line.reserved_qty, line.outstanding_qty)
        for line in result.lines
    ]
    assert totals == [
        (3, 2, 1),
        (1, 1, 0),
    ]
    assert result.requested_quantity == 4
    assert result.fulfillable_quantity == 3
    assert result.outstanding_quantity == 1


def test_each_zone_has_parallel_branches_that_converge_before_loading() -> None:
    """A missing dependency could load before both Pinky and OMX are ready."""
    plan = OutboundPlanner().plan(
        order(("SKU-MILK", 1)),
        (
            lot(1, "SKU-MILK", "chilled", 11, 1, expiry_date=date(2026, 9, 20), received_at=None),
        ),
        LOCATIONS,
    )

    steps = planned_outbound_steps(plan)

    pick, navigate, load = steps[:3]
    assert pick.input["branch"] == "omx_prepare_pick"
    assert navigate.input["branch"] == "pinky_navigate"
    assert pick.input["handover_group_id"] == navigate.input["handover_group_id"]
    assert load.input["dependencies"] == [pick.step_no, navigate.step_no]
    assert load.input["gate"] == "PINKY_READY+OMX_READY"
    assert [(step.action_type, step.executor_type) for step in steps[-4:]] == [
        ("navigate", "mobile"),
        ("handover", "fms"),
        ("wait", "fms"),
        ("return_home", "mobile"),
    ]
    assert steps[-1].target_location_id is None
    assert steps[-1].input["target_role"] == "assigned_robot_home"
