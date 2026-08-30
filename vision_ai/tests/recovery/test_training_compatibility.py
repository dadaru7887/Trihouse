import ast
from pathlib import Path


def test_frozen_offline_defaults_are_preserved() -> None:
    source = Path("vision_ai/models/recovery/trainer/offline_train.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    values = {
        node.targets[0].id: ast.literal_eval(node.value)
        for node in tree.body if isinstance(node, ast.Assign)
        and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id in {"BATCH_SIZE", "MIN_TRANSITIONS_TO_TRAIN", "DEFAULT_EPOCHS"}
    }
    assert values == {"BATCH_SIZE": 32, "MIN_TRANSITIONS_TO_TRAIN": 4, "DEFAULT_EPOCHS": 20}


def test_reward_clipping_and_soft_clipping_remain_disabled() -> None:
    source = Path("vision_ai/models/recovery/trainer/algorithms.py").read_text(encoding="utf-8")
    assert "REWARD_CLIP = None" in source
    assert "REWARD_SOFT_CLIP_SCALE: float | None = None" in source
    assert "ADVANTAGE_STD_NORM = True" in source
    assert "USE_CLIP_SURROGATE = True" in source
    assert "CLIP_EPSILON = 0.2" in source
