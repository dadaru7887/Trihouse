"""증강 모듈을 import 하는 것만으로 전역 난수 상태가 바뀌면 안 된다."""

import ast

import pytest
from pathlib import Path

RECIPES = Path("vision_ai/models/perception/trainer/augmentation_recipes.py")
RNG = Path("vision_ai/utils/augmentation/rng.py")
PRIMITIVES = Path("vision_ai/utils/augmentation/primitives.py")


def _module_level_calls(tree: ast.Module) -> list[str]:
    names = []
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            f = node.value.func
            if isinstance(f, ast.Attribute):
                base = f.value.id if isinstance(f.value, ast.Name) else ""
                names.append(f"{base}.{f.attr}")
    return names


@pytest.mark.parametrize("path", [RECIPES, RNG, PRIMITIVES], ids=lambda p: p.name)
def test_importing_the_recipes_does_not_seed_the_global_rngs(path) -> None:
    """`train()` 은 seed_everything 직후에 이 모듈을 import 한다.

    모듈 최상위에서 random.seed(42) 를 부르면 사용자가 --seed 로 준 값이
    그 자리에서 42 로 덮인다. 예외가 아니라 "재현이 안 된다" 로 나타나므로
    원인에서 가장 먼 종류의 버그다.
    """
    calls = _module_level_calls(ast.parse(path.read_text(encoding="utf-8")))

    forbidden = [c for c in calls
                 if c in {"random.seed", "np.random.seed", "torch.manual_seed"}]
    assert not forbidden, f"import 시점에 전역 seed 를 건드립니다: {forbidden}"


def test_the_seed_constant_is_defined_once() -> None:
    """같은 이름이 두 번 정의되면 어느 쪽이 유효한지 읽어서 알 수 없다."""
    tree = ast.parse(RECIPES.read_text(encoding="utf-8"))
    defs = [t.id for node in tree.body if isinstance(node, ast.Assign)
            for t in node.targets if isinstance(t, ast.Name) and t.id == "SEED"]

    assert len(defs) <= 1, f"SEED 가 {len(defs)}번 정의돼 있습니다"


def test_the_augmentation_stream_lives_in_one_place() -> None:
    """전역 seed 는 안 건드리되, 증강 전용 스트림은 있어야 한다."""
    rng_source = RNG.read_text(encoding="utf-8")

    assert "_augmentation_seed_stream" in rng_source
    assert "def configure_augmentation_seed" in rng_source
    # recipes 는 정의하지 않고 가져다 쓰기만 한다 — 스트림이 두 벌이면 seed 가 갈린다
    assert "_augmentation_seed_stream = " not in RECIPES.read_text(encoding="utf-8")
