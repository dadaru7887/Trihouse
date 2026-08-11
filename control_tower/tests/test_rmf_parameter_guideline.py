"""Open-RMF POC 파라미터 가이드의 필수 계약을 확인한다."""

from pathlib import Path


def test_guideline_covers_measured_inputs_rmf_outputs_and_jsonl_logs():
    document = (
        Path(__file__).resolve().parents[2]
        / "docs"
        / "guideline"
        / "parameters_for_rmf.md"
    ).read_text(encoding="utf-8")

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
