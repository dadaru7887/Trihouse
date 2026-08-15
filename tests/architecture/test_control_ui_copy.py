from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "control_system"
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


def test_control_ui_is_full_source_copy_without_nested_git():
    target = ROOT / "control_ui"
    assert (target / "UPSTREAM_CONTROL_SYSTEM_COMMIT").read_text().strip() == (
        "5b4cafe65e257fd070fec925a1c8251315b005de"
    )
    assert not (target / ".git").exists()
    assert (target / "rmf_control_ui" / "lib" / "main.dart").is_file()
    assert (target / "rmf_control_ui" / "pubspec.yaml").is_file()
    source_files = set(_retained_files(SOURCE))
    assert set(_retained_files(target)) == source_files
    for path in source_files:
        assert (target / path).read_bytes() == (SOURCE / path).read_bytes()
