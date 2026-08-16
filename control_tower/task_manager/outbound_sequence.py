"""Pure templates for persisted outbound work."""

from dataclasses import dataclass
from typing import Any

from .outbound_planner import OutboundPlan


@dataclass(frozen=True)
class OutboundStepTemplate:
    """One logical step before runtime location IDs and a mobile are assigned."""

    step_no: int
    executor_type: str
    action_type: str
    source: str
    target: str
    assigned_device_id: str | None = None


def outbound_segment_template() -> tuple[OutboundStepTemplate, ...]:
    """Return a fresh immutable description of the minimal outbound sequence."""

    return (
        OutboundStepTemplate(10, "mobile", "navigate", "current", "inbound_waiting"),
        OutboundStepTemplate(
            20,
            "mobile",
            "navigate",
            "inbound_waiting",
            "OMX_01_station",
        ),
        OutboundStepTemplate(
            30,
            "arm",
            "load",
            "OMX_01_station",
            "OMX_01_station",
            "OMX_01",
        ),
        OutboundStepTemplate(
            40,
            "mobile",
            "navigate",
            "OMX_01_station",
            "narrow_waiting",
        ),
        OutboundStepTemplate(
            50,
            "mobile",
            "navigate",
            "narrow_waiting",
            "outbound_waiting",
        ),
        OutboundStepTemplate(
            60,
            "fms",
            "handover",
            "outbound_waiting",
            "outbound_waiting",
        ),
    )


@dataclass(frozen=True)
class PlannedOutboundStep:
    """One stable branch or gate persisted before hardware assignment."""

    step_no: int
    executor_type: str
    action_type: str
    target_location_id: int | None
    input: dict[str, Any]


def planned_outbound_steps(plan: OutboundPlan) -> tuple[PlannedOutboundStep, ...]:
    """Build parallel OMX/Pinky branches and their explicit convergence gates."""

    if not plan.accepted:
        raise ValueError("a rejected order has no outbound steps")
    steps: list[PlannedOutboundStep] = []
    step_no = 10
    previous_gate: int | None = None
    for bundle in plan.bundles:
        inherited_dependencies = [] if previous_gate is None else [previous_gate]
        product_codes = list(dict.fromkeys(item.product_code for item in bundle.items))
        common = {
            "handover_group_id": bundle.handover_group_id,
            "temperature_zone": bundle.temperature_zone,
            "dock_location_id": bundle.dock_location_id,
            "product_codes": product_codes,
        }
        pick_no = step_no
        steps.append(
            PlannedOutboundStep(
                pick_no,
                "arm",
                "pick",
                bundle.dock_location_id,
                {
                    **common,
                    "branch": "omx_prepare_pick",
                    "dependencies": inherited_dependencies,
                    "items": [
                        {
                            "line_no": item.line_no,
                            "product_code": item.product_code,
                            "lot_id": item.lot_id,
                            "slot_location_id": item.slot_location_id,
                            "reserved_quantity": item.reserved_qty,
                        }
                        for item in bundle.items
                    ],
                },
            )
        )
        step_no += 10
        navigate_no = step_no
        steps.append(
            PlannedOutboundStep(
                navigate_no,
                "mobile",
                "navigate",
                bundle.dock_location_id,
                {
                    **common,
                    "branch": "pinky_navigate",
                    "dependencies": inherited_dependencies,
                },
            )
        )
        step_no += 10
        previous_gate = step_no
        steps.append(
            PlannedOutboundStep(
                previous_gate,
                "fms",
                "load",
                bundle.dock_location_id,
                {
                    **common,
                    "branch": "readiness_load_gate",
                    "dependencies": [pick_no, navigate_no],
                    "gate": "PINKY_READY+OMX_READY",
                },
            )
        )
        step_no += 10

    assert previous_gate is not None
    packing_dock = plan.packing_dock_location_id
    steps.extend(
        (
            PlannedOutboundStep(
                step_no,
                "mobile",
                "navigate",
                packing_dock,
                {
                    "branch": "packing_navigate",
                    "dependencies": [previous_gate],
                    "packing_dock_location_id": packing_dock,
                },
            ),
            PlannedOutboundStep(
                step_no + 10,
                "fms",
                "handover",
                packing_dock,
                {"dependencies": [step_no], "packing_dock_location_id": packing_dock},
            ),
            PlannedOutboundStep(
                step_no + 20,
                "fms",
                "wait",
                packing_dock,
                {
                    "dependencies": [step_no + 10],
                    "wait_for": "worker_completion",
                },
            ),
            PlannedOutboundStep(
                step_no + 30,
                "mobile",
                "return_home",
                None,
                {
                    "dependencies": [step_no + 20],
                    "target_role": "assigned_robot_home",
                    "charger_location_ids": list(plan.charger_location_ids),
                },
            ),
        )
    )
    return tuple(steps)
