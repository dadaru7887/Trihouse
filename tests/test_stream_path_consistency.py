"""운영 스트림 경로가 파일 경계를 넘어 한 벌로 유지되는지 검증한다.

경로 문자열은 저장소 안에서 네 곳에 나타난다. Pinky 송신 설정(`pinky_1.yaml`),
PC2 환경변수 예시(`.env.example`), 현장 검증 스크립트(`verify_rtsp.sh`), 그리고
등록 정본(`config/cameras.yaml`)이다. 앞의 셋은 정본에서 파생된 값을 적어둔
사본이므로, 사본이 정본과 어긋나면 배포는 성공한 것처럼 보이면서 프레임만
사라진다. `front` 와 `pinky_1` 이 갈라졌던 방식이 정확히 이것이다.

정본과 대조하는 방식으로 적는다. `pinky/CAM-PK-01` 이라는 리터럴을 테스트에
다시 적으면 정본이 넷이 아니라 다섯이 된다.
"""

from pathlib import Path
import re

import yaml

from control_tower.gateway.camera_registry import load_camera_registry


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "config" / "cameras.yaml"
PINKY_CONFIG = ROOT / "trihouse_pinky" / "trihouse_pinky_vision" / "config" / "pinky_1.yaml"
VERIFY_SCRIPT = (
    ROOT / "trihouse_pinky" / "trihouse_pinky_vision" / "scripts" / "verify_rtsp.sh"
)
ENV_EXAMPLE = ROOT / ".env.example"

PINKY_1_CAMERA_ID = "CAM-PK-01"


def _registry_record(camera_id: str):
    records = {record.camera_id: record for record in load_camera_registry(REGISTRY)}
    assert camera_id in records, f"{camera_id} is not registered in {REGISTRY}"
    return records[camera_id]


def _pinky_parameters() -> dict:
    document = yaml.safe_load(PINKY_CONFIG.read_text(encoding="utf-8"))
    return document["camera_streamer"]["ros__parameters"]


def test_pinky_publisher_uses_the_registered_camera_id() -> None:
    parameters = _pinky_parameters()

    assert parameters["camera_id"] == PINKY_1_CAMERA_ID


def test_pinky_publish_uri_path_is_the_registered_stream_path() -> None:
    record = _registry_record(PINKY_1_CAMERA_ID)
    parameters = _pinky_parameters()

    path = parameters["publish_uri"].split("//", 1)[1].split("/", 1)[1]

    assert path == record.stream_path


def test_pinky_publish_uri_last_segment_equals_camera_id() -> None:
    # `command_builder.StreamConfig` 가 강제하는 규칙과 같은 규칙이다. 설정
    # 파일이 이 규칙을 어기면 노드는 부팅 시점에 죽는다.
    parameters = _pinky_parameters()

    assert parameters["publish_uri"].rsplit("/", 1)[-1] == parameters["camera_id"]


def test_environment_example_points_pc2_at_the_registered_stream_path() -> None:
    record = _registry_record(PINKY_1_CAMERA_ID)
    example = ENV_EXAMPLE.read_text(encoding="utf-8")

    match = re.search(r"^VISION_RTSP_URL=(?P<url>\S+)$", example, re.MULTILINE)
    assert match is not None, "VISION_RTSP_URL is missing from .env.example"

    assert match.group("url").endswith(f"/{record.stream_path}")


def test_verify_script_default_uri_is_the_registered_stream_path() -> None:
    record = _registry_record(PINKY_1_CAMERA_ID)
    script = VERIFY_SCRIPT.read_text(encoding="utf-8")

    match = re.search(r'^uri="\$\{1:-(?P<url>[^}"]+)\}"$', script, re.MULTILINE)
    assert match is not None, "verify_rtsp.sh no longer carries a default URI"

    assert match.group("url").endswith(f"/{record.stream_path}")


def test_no_tracked_copy_still_carries_the_superseded_flat_path() -> None:
    # 옛 규약(`/pinky_1`, `pinky/PK_01/front`)이 어느 사본에도 남아 있으면
    # 안 된다. 남아 있으면 그 파일을 읽은 사람이 옛 경로로 배포한다.
    for source in (PINKY_CONFIG, VERIFY_SCRIPT, ENV_EXAMPLE):
        text = source.read_text(encoding="utf-8")
        assert "8554/pinky_1" not in text, f"{source} still uses the flat path"
        assert "pinky/PK_01" not in text, f"{source} still uses the three-segment path"
