import ast
from pathlib import Path

import pytest

from vision_ai.utils.contracts import RecoveryStateV1, SKILL_TO_ACTION_FAMILY


TRAINING_PREFIXES = (
    "vision_ai.models.perception.trainer",
    "vision_ai.models.recovery.trainer",
    "vision_ai.data_loader",
    "vision_ai.visualization",
)


def test_the_robot_process_never_imports_a_training_package() -> None:
    """로봇에 올라가는 트리 전체를 훑는다.

    전에는 한 디렉터리만 glob 했다. 그 디렉터리가 이동하자 glob 이 빈 목록이
    되어 **아무것도 검사하지 않으면서 통과**했다 — 그래서 여기서는 파일이
    실제로 잡혔는지부터 단언한다.
    """
    paths = sorted(Path("vision_ai/robot").rglob("*.py"))
    assert len(paths) > 20, f"로봇 트리를 못 찾았습니다: {len(paths)}개"

    offenders = []
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(TRAINING_PREFIXES):
                offenders.append(f"{path}: {node.module}")
            if isinstance(node, ast.Import):
                offenders += [f"{path}: {a.name}" for a in node.names
                              if a.name.startswith(TRAINING_PREFIXES)]
    assert not offenders, offenders


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
