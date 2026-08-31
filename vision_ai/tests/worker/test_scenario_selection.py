"""시나리오를 골라서 학습에 넣거나 빼는 규칙 (leave-one-out 실험용)."""

import pytest

pytest.importorskip("albumentations")
pytest.importorskip("cv2")

from vision_ai.utils.augmentation import scenarios


def test_every_pool_function_has_a_scenario_tag() -> None:
    """태그 없는 함수가 있으면 제외가 조용히 실패한다."""
    for fn in scenarios.MIXED_POOL:
        assert fn.__name__ in scenarios.SCENARIO_OF, fn.__name__


def test_the_tags_match_the_documented_counts() -> None:
    counts = {}
    for fn in scenarios.MIXED_POOL:
        counts[scenarios.SCENARIO_OF[fn.__name__]] = counts.get(scenarios.SCENARIO_OF[fn.__name__], 0) + 1

    assert counts == {"S1": 3, "S2": 1, "S3": 1, "S4": 2, "S5": 5}


def test_holding_out_a_scenario_removes_exactly_its_functions() -> None:
    pool = scenarios.pool_for(exclude={"S4"})
    tags = {scenarios.SCENARIO_OF[fn.__name__] for fn in pool}

    assert "S4" not in tags
    assert len(pool) == len(scenarios.MIXED_POOL) - 2


def test_holding_out_nothing_returns_the_whole_pool() -> None:
    assert scenarios.pool_for(exclude=set()) == scenarios.MIXED_POOL


def test_an_unknown_scenario_is_refused() -> None:
    """오타로 아무것도 안 빠진 채 실험이 도는 것을 막는다."""
    with pytest.raises(ValueError, match="S9"):
        scenarios.pool_for(exclude={"S9"})


def test_holding_out_everything_is_refused() -> None:
    with pytest.raises(ValueError, match="empty"):
        scenarios.pool_for(exclude={"S1", "S2", "S3", "S4", "S5"})


def test_one_scenario_can_be_applied_on_its_own_for_evaluation() -> None:
    """평가는 손상 하나를 지목해서 건다."""
    import numpy as np

    image = np.random.default_rng(0).integers(0, 255, (80, 100, 3), dtype=np.uint8)
    scenarios.configure_augmentation_seed(42)

    out = scenarios.apply_scenario(image, "S4")

    assert out.shape == image.shape
    assert out.dtype == image.dtype
    assert not np.array_equal(out, image)


def test_applying_an_unknown_scenario_is_refused() -> None:
    import numpy as np

    with pytest.raises(ValueError, match="S9"):
        scenarios.apply_scenario(np.zeros((10, 10, 3), dtype="uint8"), "S9")
