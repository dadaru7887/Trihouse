"""호스트 ROS 층과 Docker ROS 층이 같은 DDS 설정으로 뜨는지 검증한다.

시뮬레이션의 ROS 2 그래프는 두 곳에서 뜬다. Gazebo·Nav2·adapter 는
`control_tower/bringup/p0_simulation_bringup.sh` 가 호스트에서 띄우고, RMF API 는
`compose.simulation.yaml` 이 컨테이너에서 띄운다. 둘은 같은 그래프에 참여하므로
domain 과 전송 방식이 모두 같아야 한다. 하나라도 어긋나면 오류가 아니라 침묵으로
나타난다 — 서로를 못 보거나, 더 나쁘게는 요청은 도착하는데 응답만 돌아오지 못한다.

실제로 그렇게 잃은 시간이 있다. 컨테이너는 `FASTDDS_BUILTIN_TRANSPORTS=UDPv4` 로
떴는데 호스트는 아무것도 정하지 않아 FastDDS 기본값(공유메모리 포함)으로 떴다.
그 상태에서 `map_server` 는 Configuring 을 끝냈는데도 lifecycle_manager 가 응답을
받지 못해(`failed to send response to .../change_state`) localization 이 그 자리에
멈췄고, AMCL 이 아예 기동하지 못했다. 로그에는 전송 계층 오류가 한 줄도 없었다.

`.env.example` 은 처음부터 UDPv4 를 적어 두었지만 어느 쪽도 `.env` 를 읽지
않는다. 그러니 정합을 지키는 것은 두 파일에 적힌 기본값이고, 그 일치를 지키는
것이 이 테스트다.
"""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
BRINGUP = ROOT / "control_tower" / "bringup" / "p0_simulation_bringup.sh"
COMPOSE = ROOT / "compose.simulation.yaml"

# 두 층이 반드시 합의해야 하는 변수.
#
# `ROS_AUTOMATIC_DISCOVERY_RANGE` 가 여기 있는 이유는 서버 PC 가 인터페이스를 둘 갖기
# 때문이다 — 인터넷용 Wi-Fi 와 ROS 전용 공유기로 가는 Ethernet. 범위를 좁히지 않으면
# discovery 를 Wi-Fi 쪽으로도 뿌린다. 한쪽 층만 좁히면 그 층은 상대를 못 본다.
SHARED_DDS_KEYS = (
    "ROS_DOMAIN_ID",
    "RMW_IMPLEMENTATION",
    "FASTDDS_BUILTIN_TRANSPORTS",
    "ROS_AUTOMATIC_DISCOVERY_RANGE",
)


def _bringup_defaults() -> dict[str, str]:
    """`: "${VAR:=default}"` 형태로 적힌 셸 기본값을 읽는다."""
    source = BRINGUP.read_text(encoding="utf-8")
    found = re.findall(r'^:\s*"\$\{([A-Z0-9_]+):=([^}]*)\}"', source, flags=re.MULTILINE)
    return dict(found)


def _compose_defaults() -> dict[str, str]:
    """`VAR: ${VAR:-default}` 형태로 적힌 Compose 기본값을 읽는다.

    yaml 로 읽어 값을 문자열로 받아도 되지만, 확인하려는 것은 치환식 안의
    기본값이라 그 형태를 그대로 보는 편이 정직하다.
    """
    source = COMPOSE.read_text(encoding="utf-8")
    found = re.findall(
        r'^\s*([A-Z0-9_]+):\s*\$\{([A-Z0-9_]+):-([^}]*)\}', source, flags=re.MULTILINE
    )
    return {key: default for key, _substituted, default in found}


def test_both_layers_declare_every_shared_dds_setting() -> None:
    """어느 한쪽이 값을 정하지 않으면 그쪽은 구현 기본값으로 떠 버린다."""
    host = _bringup_defaults()
    docker = _compose_defaults()

    assert [key for key in SHARED_DDS_KEYS if key not in host] == []
    assert [key for key in SHARED_DDS_KEYS if key not in docker] == []


def test_the_host_and_docker_defaults_are_the_same_value() -> None:
    host = _bringup_defaults()
    docker = _compose_defaults()

    mismatched = {
        key: (host.get(key), docker.get(key))
        for key in SHARED_DDS_KEYS
        if host.get(key) != docker.get(key)
    }
    assert mismatched == {}, f"호스트/Docker DDS 기본값 불일치: {mismatched}"


def test_shared_memory_is_not_the_transport() -> None:
    """UDPv4 를 명시하는 것이 요점이다. 기본값에는 공유메모리가 포함된다.

    컨테이너와 호스트는 `/dev/shm` 을 공유하지 않으므로 공유메모리 locator 는
    양쪽 사이에서 쓸 수 없는데도 광고된다. 값이 무엇이든 양쪽이 같기만 하면
    된다고 두면 둘 다 기본값으로 합의하는 것도 통과하므로 여기서 못박는다.
    """
    assert _bringup_defaults()["FASTDDS_BUILTIN_TRANSPORTS"] == "UDPv4"
    assert _compose_defaults()["FASTDDS_BUILTIN_TRANSPORTS"] == "UDPv4"
