"""실기 nav2 params 를 만드는 도구.

실기는 벤더 `pinky_navigation/launch/bringup_launch.xml` 을 쓰고 그것은 params 를
`<param from>` 으로 그대로 넘긴다. 시뮬의 `nav2_bringup` 이 해 주던
`RewrittenYaml(root_key=namespace)` 가 없으므로 우리가 미리 감싼 파일을 만들어야
한다. 시뮬 번들을 만드는 `p0_runtime_assets.main` 은 발행된 지도와 world.sdf 까지
요구하지만 실기에는 그 둘이 필요 없다 — 이 도구는 params 하나만 만든다.
"""

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "derive_hardware_nav2_params.py"

VENDOR_PARAMS = """\
amcl:
  ros__parameters:
    base_frame_id: base_footprint
    odom_frame_id: odom
    scan_topic: scan
controller_server:
  ros__parameters:
    controller_frequency: 20.0
bt_navigator:
  ros__parameters:
    wait_for_service_timeout: 1000
"""


def _module():
    spec = importlib.util.spec_from_file_location("derive_hardware_nav2_params", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["derive_hardware_nav2_params"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def vendor_params(tmp_path: Path) -> Path:
    source = tmp_path / "nav2_params.yaml"
    source.write_text(VENDOR_PARAMS, encoding="utf-8")
    return source


def test_the_document_is_wrapped_in_the_namespace(tmp_path, vendor_params) -> None:
    destination = tmp_path / "hardware_pinky_01.yaml"

    exit_code = _module().main(
        [
            "--source", str(vendor_params),
            "--namespace", "pinky_01",
            "--output", str(destination),
        ]
    )

    assert exit_code == 0
    document = yaml.safe_load(destination.read_text(encoding="utf-8"))
    assert set(document) == {"pinky_01"}
    assert (
        document["pinky_01"]["amcl"]["ros__parameters"]["base_frame_id"]
        == "pinky_01/base_footprint"
    )


def test_physical_bt_waits_for_action_discovery_on_the_discovery_server(
    tmp_path, vendor_params
) -> None:
    """벤더의 1초 값으로는 실기 `/follow_path` 발견 전에 BT activation이 실패한다."""
    destination = tmp_path / "hardware_pinky_01.yaml"

    assert _module().main(
        [
            "--source", str(vendor_params),
            "--namespace", "pinky_01",
            "--output", str(destination),
        ]
    ) == 0

    bt = yaml.safe_load(destination.read_text(encoding="utf-8"))["pinky_01"][
        "bt_navigator"
    ]["ros__parameters"]
    assert bt["wait_for_service_timeout"] == 10_000


def test_the_first_line_names_the_namespace(tmp_path, vendor_params) -> None:
    """실기 절차가 첫 줄로 성공을 판정한다."""
    destination = tmp_path / "hardware_pinky_01.yaml"

    _module().main(
        [
            "--source", str(vendor_params),
            "--namespace", "pinky_01",
            "--output", str(destination),
        ]
    )

    assert destination.read_text(encoding="utf-8").splitlines()[0] == "pinky_01:"


def test_an_empty_namespace_is_refused(tmp_path, vendor_params) -> None:
    """분기 B 는 벤더 기본 params 를 그대로 쓴다 — 감쌀 것이 없으므로 이 도구를 쓰지 않는다."""
    destination = tmp_path / "hardware.yaml"

    with pytest.raises(SystemExit):
        _module().main(
            [
                "--source", str(vendor_params),
                "--namespace", "",
                "--output", str(destination),
            ]
        )

    assert not destination.exists()


def test_the_initial_pose_is_written_inside_the_wrapper(tmp_path, vendor_params) -> None:
    destination = tmp_path / "hardware_pinky_01.yaml"

    _module().main(
        [
            "--source", str(vendor_params),
            "--namespace", "pinky_01",
            "--output", str(destination),
            "--initial-pose", "1.5,-2.0,0.25",
        ]
    )

    amcl = yaml.safe_load(destination.read_text(encoding="utf-8"))["pinky_01"]["amcl"]
    assert amcl["ros__parameters"]["set_initial_pose"] is True
    assert amcl["ros__parameters"]["initial_pose"] == {
        "x": 1.5,
        "y": -2.0,
        "z": 0.0,
        "yaw": 0.25,
    }


def test_a_malformed_initial_pose_is_refused(tmp_path, vendor_params) -> None:
    """조용히 무시하면 AMCL 이 지도 전체에 입자를 흩뿌린 채 시작한다."""
    destination = tmp_path / "hardware_pinky_01.yaml"

    with pytest.raises(SystemExit):
        _module().main(
            [
                "--source", str(vendor_params),
                "--namespace", "pinky_01",
                "--output", str(destination),
                "--initial-pose", "1.5,-2.0",
            ]
        )


def test_a_missing_source_is_refused_before_anything_is_written(
    tmp_path,
) -> None:
    destination = tmp_path / "hardware_pinky_01.yaml"

    with pytest.raises(SystemExit):
        _module().main(
            [
                "--source", str(tmp_path / "does-not-exist.yaml"),
                "--namespace", "pinky_01",
                "--output", str(destination),
            ]
        )

    assert not destination.exists()


def test_the_output_directory_is_created(tmp_path, vendor_params) -> None:
    destination = tmp_path / "nested" / "dir" / "hardware_pinky_01.yaml"

    assert _module().main(
        [
            "--source", str(vendor_params),
            "--namespace", "pinky_01",
            "--output", str(destination),
        ]
    ) == 0
    assert destination.is_file()


def test_the_vendor_source_is_never_modified(tmp_path, vendor_params) -> None:
    """`pinky_pro` 는 보호 경로다. 이 도구는 읽기만 한다."""
    before = vendor_params.read_text(encoding="utf-8")

    _module().main(
        [
            "--source", str(vendor_params),
            "--namespace", "pinky_01",
            "--output", str(tmp_path / "out.yaml"),
        ]
    )

    assert vendor_params.read_text(encoding="utf-8") == before
