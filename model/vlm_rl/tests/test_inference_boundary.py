import ast
from pathlib import Path

import pytest

from model.vlm_rl.shared.contracts import RecoveryStateV1, SKILL_TO_ACTION_FAMILY


def test_inference_never_imports_training_package() -> None:
    for path in Path("model/vlm_rl/inference").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        assert all(not name.startswith("model.vlm_rl.training") for name in imported)


def test_named_state_v1_serializes_in_the_frozen_model_order() -> None:
    state = RecoveryStateV1(
        robot_x_m=1.0,
        robot_y_m=2.0,
        robot_yaw_rad=0.3,
        goal_x_m=4.0,
        goal_y_m=5.0,
        risk_bbox_center_x_norm=0.25,
        risk_bbox_center_y_norm=0.75,
        risk_confidence=0.8,
        vlm_uncertainty=0.1,
    )

    assert state.to_vector() == (1.0, 2.0, 0.3, 4.0, 5.0, 0.25, 0.75, 0.8, 0.1)
    assert state.state_schema_id == "trihouse.recovery-state.v1"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("risk_bbox_center_x_norm", -0.01),
        ("risk_bbox_center_y_norm", 1.01),
        ("risk_confidence", float("nan")),
        ("vlm_uncertainty", 1.1),
    ],
)
def test_named_state_v1_rejects_values_outside_the_external_contract(field: str, value: float) -> None:
    values = {
        "robot_x_m": 1.0,
        "robot_y_m": 2.0,
        "robot_yaw_rad": 0.3,
        "goal_x_m": 4.0,
        "goal_y_m": 5.0,
        "risk_bbox_center_x_norm": 0.25,
        "risk_bbox_center_y_norm": 0.75,
        "risk_confidence": 0.8,
        "vlm_uncertainty": 0.1,
    }
    values[field] = value

    with pytest.raises(ValueError):
        RecoveryStateV1(**values)


def test_detour_skills_keep_direction_while_sharing_the_aggregation_family() -> None:
    assert SKILL_TO_ACTION_FAMILY[1] == "detour"
    assert SKILL_TO_ACTION_FAMILY[2] == "detour"
