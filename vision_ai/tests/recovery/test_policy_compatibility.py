import pytest

from vision_ai.utils.contracts import COORD_DIM, SKILL_NAMES, STATE_DIM


def test_model_dimensions_and_skill_order_are_frozen() -> None:
    assert STATE_DIM == 9
    assert COORD_DIM == 3
    assert SKILL_NAMES == (
        "BACKUP", "REROUTE_LEFT", "REROUTE_RIGHT", "WAIT_REOBSERVE", "REJOIN"
    )


def test_parameter_shapes_match_dev_driving_v2() -> None:
    pytest.importorskip("torch")
    from vision_ai.models.recovery.policy_architecture import HighLevelPolicy, LowLevelPolicy

    assert [tuple(parameter.shape) for parameter in HighLevelPolicy().parameters()] == [
        (64, 9), (64,), (64, 64), (64,), (5, 64), (5,)
    ]
    assert [tuple(parameter.shape) for parameter in LowLevelPolicy().parameters()] == [
        (128, 14), (128,), (128, 128), (128,),
        (3, 128), (3,), (3, 128), (3,),
    ]
