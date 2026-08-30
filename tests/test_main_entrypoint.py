"""학습 진입점과 로봇 진입점, 그리고 둘 사이의 경계.

로봇 프로세스가 학습 패키지를 끌어오면 물리 로봇에 ultralytics 학습 스택과
scikit-learn 이 딸려 들어간다. 그것을 막는 것이 이 파일의 요점이다.
"""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TRAIN_MAIN = ROOT / "vision_ai" / "main.py"
ROBOT_MAIN = ROOT / "vision_ai" / "robot" / "main.py"


def test_training_entrypoint_exposes_train_and_eval() -> None:
    from vision_ai.main import build_parser

    choices = build_parser()._subparsers._group_actions[0].choices
    assert "train" in choices and "eval" in choices


@pytest.mark.parametrize("model", ["perception", "recovery"])
def test_both_models_can_be_trained_from_one_entrypoint(model: str) -> None:
    """모델 2개가 같은 진입점을 쓴다 — 어느 쪽인지는 인자로 정한다."""
    from vision_ai.main import build_parser

    args = build_parser().parse_args(["train", "--model", model, "--data", "/d.yaml"])

    assert args.model == model


def test_dataset_paths_are_arguments_not_defaults() -> None:
    from vision_ai.main import build_parser

    args = build_parser().parse_args(
        ["train", "--model", "perception", "--data", "/some/where/data.yaml"])

    assert str(args.data) == "/some/where/data.yaml"


def test_robot_entrypoint_takes_the_camera_source() -> None:
    from vision_ai.robot.main import build_parser

    args = build_parser().parse_args(
        ["--source", "rtsp://cam/CAM-PK-01", "--weights", "/models/best.pt"])

    assert args.source == "rtsp://cam/CAM-PK-01"


def test_no_training_import_at_module_scope_of_the_robot_entrypoint() -> None:
    """import 는 각 갈래 안에서만. 최상위에서 끌어오면 언제나 같이 딸려 온다."""
    tree = ast.parse(ROBOT_MAIN.read_text(encoding="utf-8"))
    top = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    names = [n.module or "" for n in top if isinstance(n, ast.ImportFrom)]
    names += [a.name for n in top if isinstance(n, ast.Import) for a in n.names]

    assert not [n for n in names if "trainer" in n or "data_loader" in n]


def test_running_the_robot_entrypoint_never_imports_a_trainer() -> None:
    """정적 검사로는 간접 import 를 못 잡는다.

    로봇에 올라가는 경로라 이 보장은 주장이 아니라 측정이어야 한다 — 실제
    프로세스를 띄워 `sys.modules` 를 읽는다.
    """
    program = (
        "import sys;"
        " from vision_ai.robot.main import main;"
        " main(['--source', '0', '--weights', '/nonexistent.pt', '--dry-run']);"
        " leaked = [m for m in sys.modules"
        "   if '.trainer' in m or 'data_loader' in m or 'visualization' in m];"
        " heavy = [m for m in sys.modules"
        "   if m.split('.')[0] in ('sklearn', 'ultralytics', 'albumentations')];"
        " print('LEAKED=' + repr(leaked) + ' HEAVY=' + repr(heavy))"
    )
    result = subprocess.run(
        [sys.executable, "-c", program], cwd=ROOT, capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
    assert "LEAKED=[] HEAVY=[]" in result.stdout, result.stdout
