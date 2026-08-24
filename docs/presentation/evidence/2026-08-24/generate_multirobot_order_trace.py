"""Generate presentation evidence from the production planning/orchestration code.

This is a deterministic code-level dry run. It does not write to MySQL or move a robot.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime
import json
from pathlib import Path
import sys

from PIL import Image, ImageDraw, ImageFont

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from control_tower.gateway.fms_client import (
    DeviceSummary,
    JobAssignmentResponse,
    JobDetailResponse,
    JobStepDetail,
    JobSummary,
    StepDispatchResponse,
)
from control_tower.task_manager.job_runner import JobRunner
from control_tower.task_manager.outbound_planner import (
    InventoryLotSnapshot,
    OrderLine,
    OutboundOrder,
    OutboundPlanner,
    PlanningLocations,
)
from control_tower.task_manager.outbound_sequence import planned_outbound_steps


OUT_DIR = Path(__file__).resolve().parent
KOREAN_FONT = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
MONO_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"


def _lot(
    lot_id: int,
    code: str,
    product: str,
    zone: str,
    slot: int,
    quantity: int,
    expiry: date,
) -> InventoryLotSnapshot:
    return InventoryLotSnapshot(
        lot_id=lot_id,
        lot_code=code,
        product_code=product,
        item_name=product,
        temperature_zone=zone,
        slot_location_id=slot,
        available_qty=quantity,
        reserved_qty=0,
        expiry_date=expiry,
        received_at=datetime(2026, 8, 1),
    )


class TraceGateway:
    """Record the calls made by the production JobRunner."""

    def __init__(self, detail: JobDetailResponse) -> None:
        self.detail = detail
        self.assignments = []
        self.dispatches = []
        self.devices = tuple(
            DeviceSummary(device_id, device_type, "automatic", "idle", "ok")
            for device_type, ids in (
                ("mobile", ("PK_01", "PK_02")),
                ("arm", ("OMX_01", "OMX_02")),
            )
            for device_id in ids
        )

    def list_jobs(self):
        return (JobSummary(self.detail.job_id, self.detail.job_code, self.detail.state),)

    def get_job(self, job_id):
        return self.detail if job_id == self.detail.job_id else None

    def list_devices(self):
        return self.devices

    def assign_job_resources(self, job_id, request):
        self.assignments.append((job_id, request))
        assignment = asdict(request)
        self.detail = JobDetailResponse(
            job_id=self.detail.job_id,
            job_code=self.detail.job_code,
            state="assigned",
            context={**self.detail.context, "assignment": assignment},
            steps=self.detail.steps,
        )
        return JobAssignmentResponse(job_id=job_id, **assignment)

    def dispatch_step(self, job_step_id, request):
        self.dispatches.append((job_step_id, request))
        step = next(step for step in self.detail.steps if step.job_step_id == job_step_id)
        channel = "rmf" if step.executor_type == "mobile" else step.executor_type
        return StepDispatchResponse(
            message_id=f"trace-message-{job_step_id}",
            idempotency_key=request.idempotency_key,
            job_id=self.detail.job_id,
            job_step_id=job_step_id,
            channel=channel,
            message_type=step.action_type,
            state="pending",
            payload={},
        )


def build_trace() -> dict:
    order = OutboundOrder(
        order_identity="presentation-order-001",
        external_reference="ORDER-DEMO-001",
        requested_by="W-OP-01",
        priority="high",
        allow_partial_fulfillment=False,
        items=(
            OrderLine(1, "SKU-AMBIENT-A", 6),
            OrderLine(2, "SKU-CHILLED-B", 3),
            OrderLine(3, "SKU-FROZEN-C", 2),
        ),
    )
    inventory = (
        _lot(1002, "LOT-A-LATE", "SKU-AMBIENT-A", "ambient", 1102, 5, date(2026, 9, 5)),
        _lot(1001, "LOT-A-EARLY", "SKU-AMBIENT-A", "ambient", 1101, 4, date(2026, 8, 28)),
        _lot(2001, "LOT-B-CHILLED", "SKU-CHILLED-B", "chilled", 1201, 10, date(2026, 8, 30)),
        _lot(3001, "LOT-C-FROZEN", "SKU-FROZEN-C", "frozen", 1301, 5, date(2026, 9, 1)),
    )
    locations = PlanningLocations(
        zone_docks={"ambient": 101, "chilled": 102, "frozen": 103},
        packing_docks=(201, 202),
        charger_location_ids=(301, 302),
    )
    omx_by_zone = {"ambient": "OMX_01", "chilled": "OMX_01", "frozen": "OMX_02"}

    plan = OutboundPlanner().plan(order, inventory, locations)
    planned_steps = planned_outbound_steps(plan, omx_by_zone)
    job_steps = tuple(
        JobStepDetail(
            job_step_id=1000 + index,
            step_no=step.step_no,
            action_type=step.action_type,
            executor_type=step.executor_type,
            state="pending",
            target_location_id=step.target_location_id,
            input=step.input,
        )
        for index, step in enumerate(planned_steps, start=1)
    )
    detail = JobDetailResponse(
        job_id=501,
        job_code="OUT-PRESENTATION-001",
        state="queued",
        context={"source": "public_product_order", "zone_order": ["ambient", "chilled", "frozen"]},
        steps=job_steps,
    )
    gateway = TraceGateway(detail)
    runner_report = JobRunner(gateway).run_once()
    assignment = gateway.assignments[0][1]
    dispatched_ids = {job_step_id for job_step_id, _request in gateway.dispatches}

    step_rows = []
    for step in job_steps:
        if step.executor_type == "mobile":
            assigned_device = assignment.mobile_id
        elif step.executor_type == "arm":
            assigned_device = step.input.get("omx_id")
        else:
            assigned_device = None
        step_rows.append(
            {
                "job_step_id": step.job_step_id,
                "step_no": step.step_no,
                "temperature_zone": step.input.get("temperature_zone", "common"),
                "branch": step.input.get("branch", step.input.get("wait_for", "common")),
                "executor_type": step.executor_type,
                "action_type": step.action_type,
                "target_location_id": step.target_location_id,
                "dependencies": step.input.get("dependencies", []),
                "assigned_device_id": assigned_device,
                "initial_runner_state": "DISPATCHED" if step.job_step_id in dispatched_ids else "WAITING",
            }
        )

    trace = {
        "evidence_boundary": {
            "type": "CODE_LEVEL_DRY_RUN",
            "production_code_executed": [
                "OutboundPlanner.plan",
                "planned_outbound_steps",
                "JobRunner.run_once",
            ],
            "mysql_written": False,
            "robot_moved": False,
        },
        "stage_1_order": {
            "external_reference": order.external_reference,
            "priority": order.priority,
            "items": [asdict(item) for item in order.items],
        },
        "stage_2_inventory_candidates": [
            {
                **asdict(lot),
                "expiry_date": lot.expiry_date.isoformat() if lot.expiry_date else None,
                "received_at": lot.received_at.isoformat() if lot.received_at else None,
                "reservable_qty": lot.reservable_qty,
            }
            for lot in inventory
        ],
        "stage_3_fefo_allocation": [
            {
                "line_no": line.line_no,
                "product_code": line.product_code,
                "requested_qty": line.requested_qty,
                "reserved_qty": line.reserved_qty,
                "allocations": [asdict(allocation) for allocation in line.allocations],
            }
            for line in plan.lines
        ],
        "stage_4_zone_bundles": [
            {
                "temperature_zone": bundle.temperature_zone,
                "dock_location_id": bundle.dock_location_id,
                "omx_id": omx_by_zone[bundle.temperature_zone],
                "lot_codes": [item.lot_code for item in bundle.items],
                "product_codes": [item.product_code for item in bundle.items],
            }
            for bundle in plan.bundles
        ],
        "stage_5_generated_job_steps": step_rows,
        "stage_6_resource_assignment": {
            **asdict(assignment),
            "job_id": 501,
            "available_devices_seen": [asdict(device) for device in gateway.devices],
        },
        "stage_7_first_dispatch": {
            "runner_report": asdict(runner_report),
            "dispatched_steps": [row for row in step_rows if row["initial_runner_state"] == "DISPATCHED"],
            "interpretation": "OMX preparation and Pinky navigation start in parallel, then converge at step 30.",
        },
    }

    assert plan.accepted
    assert [allocation.lot_code for allocation in plan.lines[0].allocations] == [
        "LOT-A-EARLY",
        "LOT-A-LATE",
    ]
    assert [allocation.reserved_qty for allocation in plan.lines[0].allocations] == [4, 2]
    assert len(step_rows) == 13
    assert assignment.mobile_id == "PK_01"
    assert assignment.omx_ids == ("OMX_01", "OMX_02")
    assert assignment.packing_dock_code == "PACKING-01-DOCK-01"
    assert assignment.charger_code == "TRIHOUSE-TEST-01-CHG-01"
    assert {row["step_no"] for row in trace["stage_7_first_dispatch"]["dispatched_steps"]} == {10, 20}
    return trace


def write_markdown(trace: dict) -> None:
    allocations = trace["stage_3_fefo_allocation"]
    steps = trace["stage_5_generated_job_steps"]
    assignment = trace["stage_6_resource_assignment"]
    lines = [
        "# 멀티로봇 주문 처리 코드 Trace",
        "",
        "> Production planning/orchestration code dry-run. MySQL 저장과 실제 로봇 이동은 수행하지 않음.",
        "",
        "## 1. 주문 입력",
        "",
        "| 상품 | 요청 수량 |",
        "|---|---:|",
    ]
    lines.extend(
        f"| {item['product_code']} | {item['quantity']} |"
        for item in trace["stage_1_order"]["items"]
    )
    lines.extend(["", "## 2. FEFO Lot 배정", "", "| 상품 | 선택 Lot | 예약 수량 |", "|---|---|---:|"])
    for line in allocations:
        for allocation in line["allocations"]:
            lines.append(
                f"| {line['product_code']} | {allocation['lot_code']} | {allocation['reserved_qty']} |"
            )
    lines.extend(
        [
            "",
            "## 3. 자원 할당",
            "",
            f"- AMR: **{assignment['mobile_id']}**",
            f"- Robot arms: **{', '.join(assignment['omx_ids'])}**",
            f"- Packing dock: **{assignment['packing_dock_code']}**",
            f"- Charger: **{assignment['charger_code']}**",
            "",
            "## 4. 생성된 작업 시퀀스",
            "",
            "| Step | 구역/분기 | 실행 주체 | 동작 | 할당 장비 | 의존 Step | 최초 상태 |",
            "|---:|---|---|---|---|---|---|",
        ]
    )
    for step in steps:
        dependencies = ", ".join(map(str, step["dependencies"])) or "-"
        lines.append(
            f"| {step['step_no']} | {step['temperature_zone']} / {step['branch']} | "
            f"{step['executor_type']} | {step['action_type']} | "
            f"{step['assigned_device_id'] or '-'} | {dependencies} | {step['initial_runner_state']} |"
        )
    lines.extend(
        [
            "",
            "최초 polling에서 Step 10(OMX 준비)과 Step 20(Pinky 이동)이 동시에 dispatch되고,",
            "두 단계가 모두 완료되어야 Step 30(load gate)이 진행된다.",
            "",
        ]
    )
    (OUT_DIR / "multirobot_order_trace.md").write_text("\n".join(lines), encoding="utf-8")


def _font(size: int):
    return ImageFont.truetype(KOREAN_FONT, size)


def _mono(size: int):
    return ImageFont.truetype(MONO_FONT, size)


def _card(draw, box, fill="#FFFFFF", outline="#D8D3C8"):
    draw.rounded_rectangle(box, radius=22, fill=fill, outline=outline, width=2)


def render_plan(trace: dict) -> None:
    image = Image.new("RGB", (1600, 900), "#F3F0E8")
    draw = ImageDraw.Draw(image)
    draw.text((85, 58), "주문 → FEFO 재고 계획", font=_font(54), fill="#181817")
    draw.text((88, 132), "Production OutboundPlanner 실행 결과", font=_font(25), fill="#68655E")

    _card(draw, (80, 195, 555, 700))
    draw.text((115, 230), "1  ORDER", font=_mono(25), fill="#7257C8")
    draw.text((115, 278), "ORDER-DEMO-001", font=_mono(28), fill="#20201E")
    y = 345
    for item in trace["stage_1_order"]["items"]:
        draw.text((115, y), item["product_code"], font=_mono(22), fill="#3E3D39")
        draw.text((465, y), f"x {item['quantity']}", font=_mono(22), fill="#3E3D39")
        y += 66

    _card(draw, (590, 195, 1515, 700))
    draw.text((625, 230), "2  FEFO LOT ALLOCATION", font=_mono(25), fill="#7257C8")
    draw.text((625, 285), "Product", font=_mono(18), fill="#77736C")
    draw.text((940, 285), "Selected lot", font=_mono(18), fill="#77736C")
    draw.text((1300, 285), "Qty", font=_mono(18), fill="#77736C")
    y = 330
    for line in trace["stage_3_fefo_allocation"]:
        first = True
        for allocation in line["allocations"]:
            draw.text((625, y), line["product_code"] if first else "", font=_mono(20), fill="#282825")
            draw.text((940, y), allocation["lot_code"], font=_mono(20), fill="#282825")
            draw.text((1310, y), str(allocation["reserved_qty"]), font=_mono(20), fill="#047857")
            y += 54
            first = False
        y += 14
    draw.text((625, 650), "LOT-A-EARLY(4) → LOT-A-LATE(2)", font=_mono(19), fill="#047857")

    zones = trace["stage_4_zone_bundles"]
    x = 80
    colors = {"ambient": "#F5E8B8", "chilled": "#CDE8F5", "frozen": "#D9D6F5"}
    for index, zone in enumerate(zones):
        width = 475 if index < 2 else 470
        draw.rounded_rectangle((x, 744, x + width, 838), radius=18, fill=colors[zone["temperature_zone"]])
        label = f"{zone['temperature_zone'].upper()}  →  {zone['omx_id']}  /  Dock {zone['dock_location_id']}"
        draw.text((x + 25, 775), label, font=_mono(19), fill="#272725")
        x += width + 30
    image.save(OUT_DIR / "01_order_to_fefo_plan.png", optimize=True)


def render_sequence(trace: dict) -> None:
    image = Image.new("RGB", (1600, 900), "#F3F0E8")
    draw = ImageDraw.Draw(image)
    draw.text((70, 42), "작업 시퀀스 생성 → 멀티로봇 할당", font=_font(50), fill="#181817")
    assignment = trace["stage_6_resource_assignment"]
    draw.text(
        (74, 112),
        f"AMR {assignment['mobile_id']}  ·  Arms {', '.join(assignment['omx_ids'])}  ·  "
        f"Dock {assignment['packing_dock_code']}  ·  Charger CHG-01",
        font=_mono(20),
        fill="#5F5C56",
    )

    headers = ("STEP", "ZONE / BRANCH", "EXECUTOR", "ACTION", "ASSIGNED", "DEP.", "INITIAL")
    xs = (75, 165, 560, 755, 930, 1140, 1270)
    for x, header in zip(xs, headers):
        draw.text((x, 177), header, font=_mono(17), fill="#716D65")
    draw.line((70, 207, 1530, 207), fill="#BFB9AE", width=2)

    y = 216
    zone_color = {"ambient": "#F7EBC0", "chilled": "#D4EBF6", "frozen": "#DEDCF6", "common": "#E8E5DE"}
    for step in trace["stage_5_generated_job_steps"]:
        fill = zone_color[step["temperature_zone"]]
        draw.rounded_rectangle((65, y, 1535, y + 36), radius=8, fill=fill)
        dependencies = ",".join(map(str, step["dependencies"])) or "-"
        state_color = "#047857" if step["initial_runner_state"] == "DISPATCHED" else "#6B6862"
        values = (
            str(step["step_no"]),
            f"{step['temperature_zone']} / {step['branch']}",
            step["executor_type"],
            step["action_type"],
            step["assigned_device_id"] or "-",
            dependencies,
            step["initial_runner_state"],
        )
        for x, value in zip(xs, values):
            draw.text((x, y + 7), value, font=_mono(14), fill=state_color if x == xs[-1] else "#292927")
        y += 42

    draw.rounded_rectangle((70, 823, 1530, 875), radius=14, fill="#162033")
    draw.text(
        (95, 838),
        "FIRST POLL: Step 10 OMX prepare  ||  Step 20 PK_01 navigate  →  Step 30 load gate",
        font=_mono(18),
        fill="#A7F3D0",
    )
    image.save(OUT_DIR / "02_sequence_and_assignment.png", optimize=True)


def main() -> None:
    trace = build_trace()
    (OUT_DIR / "multirobot_order_trace.json").write_text(
        json.dumps(trace, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_markdown(trace)
    render_plan(trace)
    render_sequence(trace)
    print(
        json.dumps(
            {
                "trace": "PASS",
                "steps": len(trace["stage_5_generated_job_steps"]),
                "assigned_mobile": trace["stage_6_resource_assignment"]["mobile_id"],
                "assigned_arms": trace["stage_6_resource_assignment"]["omx_ids"],
                "first_dispatched_step_nos": [
                    row["step_no"] for row in trace["stage_7_first_dispatch"]["dispatched_steps"]
                ],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
