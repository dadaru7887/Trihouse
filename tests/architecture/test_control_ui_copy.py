from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "control_system"
UPSTREAM_COMMIT = "5b4cafe65e257fd070fec925a1c8251315b005de"
EXCLUDED_PATH_PARTS = {".git", ".dart_tool", "build", "__pycache__", ".pytest_cache"}


def _is_excluded_generated_file(path: Path) -> bool:
    return (
        "ephemeral" in path.parts
        or path.name in {
            ".flutter-plugins-dependencies",
            "Generated.xcconfig",
            "flutter_export_environment.sh",
            "local.properties",
        }
        or path.name.startswith("GeneratedPluginRegistrant.")
        or path.suffix == ".log"
    )


def _retained_files(root: Path):
    for path in root.rglob("*"):
        relative_path = path.relative_to(root)
        if (
            EXCLUDED_PATH_PARTS.isdisjoint(relative_path.parts)
            and not _is_excluded_generated_file(relative_path)
            and relative_path != Path("UPSTREAM_CONTROL_SYSTEM_COMMIT")
            and path.is_file()
        ):
            yield relative_path


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
        if len(field) == 40 and all(character in "0123456789abcdef" for character in field)
    )


def test_control_ui_is_full_source_copy_without_nested_git():
    target = ROOT / "control_ui"
    assert (target / "UPSTREAM_CONTROL_SYSTEM_COMMIT").read_text().strip() == (
        UPSTREAM_COMMIT
    )
    assert _gitlink("ls-files", "--stage", "--", "control_system") == UPSTREAM_COMMIT
    assert _gitlink("ls-tree", "HEAD", "--", "control_system") == UPSTREAM_COMMIT
    assert not (target / ".git").exists()
    assert (target / "rmf_control_ui" / "lib" / "main.dart").is_file()
    assert (target / "rmf_control_ui" / "pubspec.yaml").is_file()
    committed_copy_paths = {
        Path(path) for path in _git_output("ls-tree", "-r", "--name-only", "HEAD", "--", "control_ui").splitlines()
    }
    prohibited_paths = [
        path
        for path in committed_copy_paths
        if not EXCLUDED_PATH_PARTS.isdisjoint(path.parts)
        or _is_excluded_generated_file(path)
    ]
    assert not prohibited_paths
    source_files = set(_retained_files(SOURCE))
    assert set(_retained_files(target)) == source_files
    for path in source_files:
        assert (target / path).read_bytes() == (SOURCE / path).read_bytes()
