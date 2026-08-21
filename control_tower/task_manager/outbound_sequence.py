"""Pure templates for persisted outbound work."""

from dataclasses import dataclass
from typing import Any, Mapping

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


def planned_outbound_steps(
    plan: OutboundPlan,
    omx_by_temperature_zone: Mapping[str, str],
) -> tuple[PlannedOutboundStep, ...]:
    """계획된 온도 구역 방문을 DB에 저장할 step_no 10, 20, 30...으로 바꾼다.

    구역마다 ``arm/prepare + mobile/navigate → fms/load`` 세 단계가 생긴다.
    모든 구역 적재가 끝나면 포장 도크 이동 → 인계 → 작업자 확인 → 충전 복귀
    네 단계가 붙는다. 단일 구역 주문은 결과적으로 10~70의 7단계다.
    """

    if not plan.accepted:
        raise ValueError("a rejected order has no outbound steps")
    steps: list[PlannedOutboundStep] = []
    step_no = 10
    previous_gate: int | None = None
    # 온도 구역별 반복 구간: 물건 준비와 로봇 도착이 끝나야 load gate를 통과한다.
    for bundle in plan.bundles:
        try:
            omx_id = omx_by_temperature_zone[bundle.temperature_zone]
        except KeyError as error:
            raise ValueError(
                f"no OMX workcell is configured for {bundle.temperature_zone!r}"
            ) from error
        inherited_dependencies = [] if previous_gate is None else [previous_gate]
        product_codes = list(dict.fromkeys(item.product_code for item in bundle.items))
        common = {
            "handover_group_id": bundle.handover_group_id,
            "temperature_zone": bundle.temperature_zone,
            "omx_id": omx_id,
            "dock_location_id": bundle.dock_location_id,
            "product_codes": product_codes,
        }
        # Step 10 계열: OMX가 해당 구역 상품을 준비한다. P0 실물에서는 사람이
        # 물건을 올리는 절차가 이 구간을 보완한다.
        prepare_no = step_no
        steps.append(
            PlannedOutboundStep(
                prepare_no,
                "arm",
                "prepare",
                bundle.dock_location_id,
                {
                    **common,
                    "branch": "omx_prepare",
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
        # Step 20 계열: 배정된 Pinky가 해당 온도 구역 적재 도크로 이동한다.
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
        # Step 30 계열: 물건 준비와 로봇 도착 두 결과를 확인하는 적재 gate다.
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
                    "dependencies": [prepare_no, navigate_no],
                    "gate": "PINKY_READY+OMX_READY",
                },
            )
        )
        step_no += 10

    assert previous_gate is not None
    # 모든 구역 처리 뒤의 공통 마무리 4단계:
    # 포장 도크 이동 → 인계 장부 처리 → 작업자 완료 확인 → 로봇 충전소 복귀.
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
