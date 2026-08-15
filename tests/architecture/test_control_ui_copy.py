from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
UPSTREAM_COMMIT = "5b4cafe65e257fd070fec925a1c8251315b005de"


def _git_output(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(ROOT), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _gitlink(*args: str) -> str:
    return next(
        field
        for field in _git_output(*args).split()
        if len(field) == 40
        and all(character in "0123456789abcdef" for character in field)
    )


def test_control_ui_preserves_copy_provenance_after_gateway_refactor() -> None:
    target = ROOT / "control_ui"

    assert (target / "UPSTREAM_CONTROL_SYSTEM_COMMIT").read_text().strip() == (
        UPSTREAM_COMMIT
    )
    assert _gitlink("ls-files", "--stage", "--", "control_system") == UPSTREAM_COMMIT
    assert _gitlink("ls-tree", "HEAD", "--", "control_system") == UPSTREAM_COMMIT
    assert not (target / ".git").exists()
    assert (target / "rmf_control_ui" / "lib" / "main.dart").is_file()
    assert (target / "rmf_control_ui" / "pubspec.yaml").is_file()
    assert (target / "rmf_control_ui" / "web").is_dir()
