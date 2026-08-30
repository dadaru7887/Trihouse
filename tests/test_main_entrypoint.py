"""`main.py` 의 train / eval 갈래.

`eval` 은 로봇에서 도는 쪽이다. 그 경로가 학습 패키지를 끌어오면 물리 로봇
프로세스에 학습 의존이 딸려 들어간다 — 그것을 막는 것이 이 파일의 요점이다.
"""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "main.py"


def test_main_exposes_train_and_eval() -> None:
    from main import build_parser

    for mode in ("train", "eval"):
        assert mode in build_parser()._subparsers._group_actions[0].choices


def test_train_takes_the_dataset_as_an_argument() -> None:
    from main import build_parser

    args = build_parser().parse_args(
        ["train", "--task", "segmentation", "--data", "/some/data.yaml"]
    )

    assert args.mode == "train"
    assert args.task == "segmentation"
    assert str(args.data) == "/some/data.yaml"


def test_eval_takes_the_camera_source_as_an_argument() -> None:
    from main import build_parser

    args = build_parser().parse_args(
        ["eval", "--source", "rtsp://cam/CAM-PK-01", "--weights", "/models/best.pt"]
    )

    assert args.mode == "eval"
    assert args.source == "rtsp://cam/CAM-PK-01"


def test_no_training_import_happens_at_module_scope() -> None:
    """import 는 각 갈래 안에서만. 최상위에서 끌어오면 eval 도 같이 끌고 온다."""
    tree = ast.parse(MAIN.read_text(encoding="utf-8"))
    top_level = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
    names = [node.module or "" for node in top_level if isinstance(node, ast.ImportFrom)]
    names += [alias.name for node in top_level if isinstance(node, ast.Import) for alias in node.names]

    assert not [name for name in names if "training" in name or "perception" in name]


def test_running_eval_never_imports_a_training_package() -> None:
    """실제로 프로세스를 띄워서 sys.modules 를 확인한다.

    정적 검사만으로는 간접 import 를 못 잡는다. 로봇에 올라가는 경로라 이
    보장은 주장이 아니라 측정이어야 한다.
    """
    program = (
        "import sys, main;"
        " main.main(['eval', '--source', '0', '--weights', '/nonexistent.pt', '--dry-run']);"
        " leaked = [m for m in sys.modules"
        "   if 'segmentation.training' in m or 'person.training' in m"
        "   or 'vlm_rl.training' in m];"
        " print('LEAKED=' + repr(leaked))"
    )
    result = subprocess.run(
        [sys.executable, "-c", program], cwd=ROOT, capture_output=True, text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "LEAKED=[]" in result.stdout, result.stdout
