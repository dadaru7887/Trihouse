"""Clean frozen-order cycle runner behavior contracts."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = ROOT / "tests" / "simulation" / "run_frozen_cycle.py"


def _load_runner():
    assert RUNNER_PATH.is_file(), "clean frozen cycle runner is missing"
    spec = importlib.util.spec_from_file_location("run_frozen_cycle", RUNNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _job(*, state: str = "assigned", step_state: str = "succeeded") -> dict:
    return {
        "job_id": 2,
        "state": state,
        "context": {
            "assignment": {"packing_dock_code": "PACKING-01-DOCK-01"}
        },
        "items": [{"job_item_id": 9}],
        "steps": [
            {
                "step_no": number,
                "state": step_state,
                "executor_type": "mobile" if number in (20, 40, 70) else "fms",
                "action_type": "return_home" if number == 70 else "navigate",
                "result": None,
            }
            for number in (10, 20, 30, 40, 50, 60, 70)
        ],
    }


def test_simulation_config_requires_domain_zero(tmp_path) -> None:
    runner = _load_runner()
    config = tmp_path / "cycle.yaml"
    config.write_text(
        "simulation:\n  ros_domain_id: 12\n  map_name: new_map_2\n"
        "order:\n  items:\n    - product_code: SKU-PORKBELLY\n      quantity: 1\n"
        "packing_worker_by_dock:\n  PACKING-01-DOCK-01: W-FIELD-01\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="ros_domain_id must be 0"):
        runner.load_cycle_config(config)


def test_cycle_environment_overrides_domain_without_mutating_the_source() -> None:
    runner = _load_runner()
    original = {"ROS_DOMAIN_ID": "12", "UNCHANGED": "yes"}

    cycle = runner.build_cycle_environment(original, domain_id=0)

    assert original == {"ROS_DOMAIN_ID": "12", "UNCHANGED": "yes"}
    assert cycle["ROS_DOMAIN_ID"] == "0"
    assert cycle["P0_ROS_DOMAIN_ID"] == "0"
    assert cycle["UNCHANGED"] == "yes"


def test_only_a_completed_job_with_all_seven_steps_is_a_pass() -> None:
    runner = _load_runner()
    completed = _job(state="completed")

    result = runner.evaluate_cycle(completed, latest_safety_detail="clear")

    assert result == {"passed": True, "reason_code": "COMPLETED"}


def test_swept_stop_is_preserved_as_the_primary_timeout_reason() -> None:
    runner = _load_runner()
    stuck = _job(step_state="pending")
    stuck["steps"][1]["state"] = "running"

    result = runner.evaluate_cycle(stuck, latest_safety_detail="swept_stop")

    assert result == {"passed": False, "reason_code": "SWEPT_STOP"}


def test_worker_is_selected_from_the_assigned_dock_mapping() -> None:
    runner = _load_runner()

    worker = runner.select_worker_id(
        _job(),
        {
            "PACKING-01-DOCK-01": "W-FIELD-01",
            "PACKING-01-DOCK-02": "W-FIELD-02",
        },
    )

    assert worker == "W-FIELD-01"


def test_cycle_result_is_written_as_machine_readable_json(tmp_path) -> None:
    runner = _load_runner()
    result_path = tmp_path / "cycle_001" / "result.json"

    runner.write_json(result_path, {"passed": False, "reason_code": "SWEPT_STOP"})

    assert json.loads(result_path.read_text(encoding="utf-8")) == {
        "passed": False,
        "reason_code": "SWEPT_STOP",
    }
