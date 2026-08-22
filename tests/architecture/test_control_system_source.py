import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EXPECTED_COMMIT = "06ce0f9e06b98510b3a8b5765eb89a9b87fba0e0"


def test_control_system_is_the_pinned_web_control_source() -> None:
    completed = subprocess.run(
        ["git", "ls-files", "--stage", "control_system"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )

    mode, commit, _stage, path = completed.stdout.strip().split()
    assert mode == "160000"
    assert commit == EXPECTED_COMMIT
    assert path == "control_system"


def test_legacy_control_ui_is_not_tracked() -> None:
    completed = subprocess.run(
        ["git", "ls-files", "control_ui"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )

    assert completed.stdout == ""
