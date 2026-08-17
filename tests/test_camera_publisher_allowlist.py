"""발행 허용 목록이 카메라가 실제로 붙어 있는 장비와 어긋나지 않는지 검증한다.

MediaMTX 의 publish 는 출발지 IP 허용목록이다. 그 목록은 `config/mediamtx.yml` 에
있고 주소는 `compose.edge_4060.yaml` 이 환경변수로 주입한다. 정책은 fail closed 라서
어긋나면 오류가 아니라 **조용한 발행 실패**로 나타난다. 그래서 테스트로 고정한다.

실제로 그렇게 어긋나 있었다. OMX 손목 카메라 두 대가 `PC1_PUBLISHER_IP` 하나를 함께
쓰고 있었는데, 그 값은 4060 의 주소다. 팔은 각각 다른 일반 PC 에 붙어 있으므로 두
카메라 모두 발행이 거절될 상태였다.
"""

from pathlib import Path
import re

import yaml


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "config" / "cameras.yaml"
COMPOSE = ROOT / "compose.edge_4060.yaml"
POLICY = ROOT / "config" / "mediamtx.yml"
ENV_EXAMPLE = ROOT / ".env.example"

# `authInternalUsers` 에서 publish 권한을 가진 항목의 색인 순서. 이 순서가 곧
# `MTX_AUTHINTERNALUSERS_<n>_IPS` 의 `<n>` 이다.
PUBLISH_INDEXES = (0, 1, 2, 3, 4, 5)


def _registry_devices() -> list[str | None]:
    """정본에 적힌 순서대로 각 카메라가 붙어 있는 장비를 낸다."""
    document = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    return [camera["attached_to"] for camera in document["cameras"]]


def _injected_variables() -> dict[int, str]:
    """색인 -> 주입되는 환경변수 이름."""
    pattern = re.compile(
        r"MTX_AUTHINTERNALUSERS_(\d+)_IPS:\s*\$\{([A-Z0-9_]+)"
    )
    return {
        int(index): name
        for index, name in pattern.findall(COMPOSE.read_text(encoding="utf-8"))
    }


def test_every_publish_slot_gets_an_address() -> None:
    """빠진 색인은 익명 발행이 아니라 기동 실패로 끝나지만, 조용히 어긋날 수 있다."""
    injected = _injected_variables()

    assert sorted(injected) == list(PUBLISH_INDEXES)


def test_cameras_on_different_devices_never_share_one_variable() -> None:
    """한 변수를 나눠 쓰면 주소 하나만 허용되어 나머지는 조용히 거절된다."""
    devices = _registry_devices()
    injected = _injected_variables()

    assert len(devices) == len(PUBLISH_INDEXES), (
        "정본의 카메라 수와 발행 슬롯 수가 다르다. 한쪽만 늘리면 색인이 밀린다."
    )

    # 장비가 있는 카메라(로봇·팔)는 장비마다 자기 변수를 가져야 한다.
    per_device: dict[str, set[str]] = {}
    for index, device in zip(PUBLISH_INDEXES, devices, strict=True):
        if device is None:
            # 창고 고정 카메라는 붙어 있는 장비가 없다. 한 호스트가 USB 로 함께
            # 발행하므로 변수를 나눠 쓰는 것이 맞다.
            continue
        per_device.setdefault(device, set()).add(injected[index])

    for device, names in per_device.items():
        assert len(names) == 1, f"{device} 가 변수 여러 개에 걸쳐 있다: {sorted(names)}"

    used = {name for names in per_device.values() for name in names}
    assert len(used) == len(per_device), (
        f"장비 {len(per_device)}개가 변수 {len(used)}개를 나눠 쓴다: {sorted(used)}"
    )


def test_every_injected_variable_is_documented() -> None:
    """예시에 없는 변수는 아무도 채울 수 없고, 채우지 않으면 스택이 뜨지 않는다."""
    documented = {
        line.split("=", 1)[0].strip()
        for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    }

    missing = sorted(set(_injected_variables().values()) - documented)
    assert missing == [], f".env.example 에 없는 변수: {missing}"


def test_the_policy_file_documents_the_same_index_order() -> None:
    """정책 파일의 색인 주석이 낡으면 다음 사람이 로봇에게 남의 경로를 열어 준다."""
    policy = POLICY.read_text(encoding="utf-8")

    for index in PUBLISH_INDEXES:
        assert f"MTX_AUTHINTERNALUSERS_{index}_IPS" in policy
