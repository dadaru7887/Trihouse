"""Open-RMF POC 파라미터 가이드의 필수 계약을 확인한다."""

from pathlib import Path


GUIDELINE_ROOT = Path(__file__).resolve().parents[2] / "docs" / "guideline"


def parameter_document() -> str:
    return (GUIDELINE_ROOT / "parameters_for_rmf.md").read_text(encoding="utf-8")


def test_guideline_covers_measured_inputs_rmf_outputs_and_jsonl_logs():
    document = parameter_document()

    for required in (
        "직접 측정해야 하는 최소 파라미터",
        "Open-RMF에서 받는 값",
        "finish_state_of_charge",
        "travel_duration_s",
        "적재",
        "충전",
        "battery_telemetry_<robot_id>.jsonl",
        "rmf_energy_estimates.jsonl",
        "battery_policy_decisions.jsonl",
        "EstimateTaskEnergy",
    ):
        assert required in document


def test_guideline_separates_office_reference_from_measured_pinky_values():
    document = parameter_document()

    for required in (
        "미측정",
        "초기 참고값",
        "측정 완료",
        "검증 완료",
        "office_bridge.yaml",
        "실제 Pinky 설정 반영 금지",
        "원본 로그",
        "측정일",
        "적용 승인",
    ):
        assert required in document


def test_guideline_maps_every_bridge_parameter_to_a_measurement():
    document = parameter_document()

    for parameter in (
        "linear_velocity",
        "linear_acceleration",
        "angular_velocity",
        "angular_acceleration",
        "footprint_radius",
        "vicinity_radius",
        "nominal_voltage",
        "capacity",
        "charging_current",
        "mass",
        "moment_of_inertia",
        "friction_coefficient",
        "ambient_power",
        "expected_loading_duration_s",
        "expected_handover_duration_s",
        "task_time_buffer_s",
    ):
        assert f"`{parameter}`" in document
