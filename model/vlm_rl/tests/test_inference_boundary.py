import ast
from pathlib import Path


def test_inference_never_imports_training_package() -> None:
    for path in Path("model/vlm_rl/inference").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        assert all(not name.startswith("model.vlm_rl.training") for name in imported)
