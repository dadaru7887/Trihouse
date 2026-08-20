"""5080 추론이 4060 관제를 거쳐 로봇까지 닿는 경로.

## 왜 관제를 거치나

`docs/architecture/system_overview.md` 의 금지 연결에 `VLM/RL → Safety Supervisor
우회` 가 있다. 5080 은 로봇에 직접 꽂히지 않는다. 그리고 `5080 → MySQL 직접 연결`
도 금지라 5080 은 원장도 만지지 않는다 — 관측만 올린다.

## 왜 어느 로봇인지 물어보지 않나

`config/cameras.yaml` 의 `attached_to` 가 이미 답이다. 로봇에 붙은 카메라는 그
로봇이 수신자다. 요청에 `robot_id` 를 실으면 카메라 명부와 어긋날 수 있고, 그
어긋남은 "엉뚱한 로봇이 감속한다" 로 나타나 원인에서 멀다.

고정 카메라(`attached_to` 없음)는 아직 라우팅할 수 없다. 사람과 로봇의 위치를
둘 다 알아야 하는데 캘리브레이션이 없다. 지어내지 않고 거절한다.

## 왜 TCP 서버에 연결 레지스트리가 필요한가

기존 서버는 로봇이 보낸 줄에 **응답만** 했다. 서버가 먼저 말을 거는 경로가 없어
관측을 밀어 넣을 수 없었다.
"""

import asyncio
import json

import pytest

from fms_gateway.app.tcp_protocol import RobotLinkRegistry


class _Writer:
    """`asyncio.StreamWriter` 중 push 가 쓰는 부분만."""

    def __init__(self) -> None:
        self.lines: list[dict] = []
        self.closed = False

    def write(self, payload: bytes) -> None:
        if self.closed:
            raise ConnectionResetError('writer is closed')
        self.lines.append(json.loads(payload.decode('utf-8')))

    async def drain(self) -> None:
        return None


def test_a_registered_robot_receives_a_push() -> None:
    registry = RobotLinkRegistry()
    writer = _Writer()
    registry.attach('PK_01', writer)
    assert asyncio.run(registry.push('PK_01', {'type': 'person_detection'})) is True
    assert writer.lines == [{'type': 'person_detection'}]


def test_pushing_to_an_absent_robot_is_reported_not_raised() -> None:
    """로봇이 아직 안 붙었거나 끊긴 것은 오류가 아니라 사실이다.

    예외로 올리면 관측 하나가 5080 쪽 전송 루프를 멈춘다. 사람이 보이는 동안
    관측은 계속 오므로, 못 보낸 것은 보고하고 다음 것을 보낸다.
    """
    registry = RobotLinkRegistry()
    assert asyncio.run(registry.push('PK_01', {'type': 'person_detection'})) is False


def test_a_detached_robot_stops_receiving() -> None:
    registry = RobotLinkRegistry()
    writer = _Writer()
    registry.attach('PK_01', writer)
    registry.detach('PK_01', writer)
    assert asyncio.run(registry.push('PK_01', {'type': 'person_detection'})) is False


def test_a_reconnect_replaces_the_stale_link() -> None:
    """같은 로봇이 다시 붙으면 옛 연결로 보내지 않는다.

    옛 소켓으로 계속 밀면 관측이 아무도 안 듣는 곳으로 사라지고, 로봇은 사람이
    보이는데도 감속하지 않는다.
    """
    registry = RobotLinkRegistry()
    stale, fresh = _Writer(), _Writer()
    registry.attach('PK_01', stale)
    registry.attach('PK_01', fresh)
    asyncio.run(registry.push('PK_01', {'type': 'person_detection'}))
    assert stale.lines == [] and len(fresh.lines) == 1


def test_detaching_a_stale_writer_does_not_unhook_the_live_one() -> None:
    """끊긴 옛 연결이 뒤늦게 정리될 때 새 연결까지 떼면 안 된다."""
    registry = RobotLinkRegistry()
    stale, fresh = _Writer(), _Writer()
    registry.attach('PK_01', stale)
    registry.attach('PK_01', fresh)
    registry.detach('PK_01', stale)
    assert asyncio.run(registry.push('PK_01', {'type': 'person_detection'})) is True


def test_a_broken_socket_detaches_itself() -> None:
    """끊긴 연결에 계속 쓰려 하면 매 관측마다 예외가 난다."""
    registry = RobotLinkRegistry()
    writer = _Writer()
    registry.attach('PK_01', writer)
    writer.closed = True
    assert asyncio.run(registry.push('PK_01', {'type': 'person_detection'})) is False
    writer.closed = False
    assert asyncio.run(registry.push('PK_01', {'type': 'person_detection'})) is False


def test_each_robot_has_its_own_link() -> None:
    registry = RobotLinkRegistry()
    first, second = _Writer(), _Writer()
    registry.attach('PK_01', first)
    registry.attach('PK_02', second)
    asyncio.run(registry.push('PK_02', {'type': 'person_detection'}))
    assert first.lines == [] and len(second.lines) == 1


# ------------------------------------------------- 카메라 -> 로봇 라우팅

from fms_gateway.app.tcp_protocol import (  # noqa: E402
    PersonDetectionRoutingError,
    route_person_detection,
)
from control_tower.gateway.camera_registry import CameraRecord  # noqa: E402

CAMERAS = (
    CameraRecord(camera_id='CAM-PK-01', role='pinky_travel', attached_to='PK_01',
                 simulation_path='fixtures/pinky_01_travel', map_pose=None),
    CameraRecord(camera_id='CAM-FIXED-01', role='warehouse_fixed', attached_to=None,
                 simulation_path='fixtures/warehouse_fixed_01', map_pose=None),
)


def test_the_camera_registry_decides_which_robot_slows_down() -> None:
    """요청에 robot_id 를 싣지 않는다. 명부와 어긋나면 엉뚱한 로봇이 감속한다."""
    assert route_person_detection('CAM-PK-01', CAMERAS) == 'PK_01'


def test_a_fixed_camera_cannot_be_routed_yet() -> None:
    """어느 로봇이 감속해야 하는지는 사람과 로봇의 위치를 둘 다 알아야 정해진다.

    캘리브레이션이 없다. 아무 로봇에나 보내면 관계없는 로봇이 멈춰 서고, 그
    원인을 현장에서 되짚기가 매우 어렵다. 지어내지 않고 거절한다.
    """
    with pytest.raises(PersonDetectionRoutingError):
        route_person_detection('CAM-FIXED-01', CAMERAS)


def test_an_unknown_camera_is_refused() -> None:
    """명부에 없는 카메라는 어디서 온 관측인지 알 수 없다."""
    with pytest.raises(PersonDetectionRoutingError):
        route_person_detection('CAM-GHOST-99', CAMERAS)


# ----------------------------------------------------- 서버 연결 수명주기

import inspect  # noqa: E402

from fms_gateway.app import tcp_protocol  # noqa: E402

HANDLE = inspect.getsource(tcp_protocol.TcpIngestionServer._handle_connection)


def test_the_server_registers_a_link_when_the_robot_says_hello() -> None:
    """hello 전에는 robot_id 를 모른다. 그 시점에 등록해야 push 가 닿는다."""
    assert "self.links.attach" in HANDLE


def test_the_server_releases_the_link_when_the_socket_closes() -> None:
    """떼지 않으면 끊긴 소켓으로 계속 밀어 관측이 사라진다."""
    assert "self.links.detach" in HANDLE
    assert "finally:" in HANDLE


def test_the_registry_is_reachable_from_the_server() -> None:
    """HTTP 층이 이 레지스트리로 관측을 밀어 넣는다."""
    server = tcp_protocol.TcpIngestionServer(
        host="127.0.0.1", port=0, registered_robot_ids=lambda: (), on_message=lambda _: None
    )
    assert isinstance(server.links, tcp_protocol.RobotLinkRegistry)


# --------------------------------------------------------- HTTP 수신 라우트

from fastapi.testclient import TestClient  # noqa: E402

from fms_gateway.app.main import create_app  # noqa: E402


class _FakeRepository:
    def ping(self) -> bool:
        return True

    def list_registered_robot_ids(self):
        return ('PK_01', 'PK_02')


def _client(links: RobotLinkRegistry) -> TestClient:
    app = create_app(_FakeRepository())
    app.state.robot_links = links
    return TestClient(app)


ROUTE = '/internal/v1/vision/person-detections'


def test_an_observation_reaches_the_attached_robot() -> None:
    links = RobotLinkRegistry()
    writer = _Writer()
    links.attach('PK_01', writer)
    with _client(links) as client:
        response = client.post(ROUTE, json={'camera_id': 'CAM-PK-01', 'confidence': 0.82})
    assert response.status_code == 200
    assert response.json()['robot_id'] == 'PK_01'
    assert writer.lines[0]['type'] == 'person_detection'
    assert writer.lines[0]['confidence'] == 0.82


def test_an_unknown_camera_is_answered_not_swallowed() -> None:
    """현장에서 관측이 안 갈 때 5080 화면에 이유가 찍혀야 한다.

    멀티캐스트 대신 HTTP 를 쓰는 이유가 이것이다 — 조용히 유실되면 5080·4060·
    로봇 셋 중 어디가 문제인지 알 수 없다.
    """
    with _client(RobotLinkRegistry()) as client:
        response = client.post(ROUTE, json={'camera_id': 'CAM-GHOST', 'confidence': 0.5})
    assert response.status_code == 400
    assert 'CAM-GHOST' in response.json()['detail']


def test_a_disconnected_robot_is_reported_as_such() -> None:
    """로봇이 아직 안 붙은 것과 카메라 ID 오타는 다른 문제다. 구분해서 답한다."""
    with _client(RobotLinkRegistry()) as client:
        response = client.post(ROUTE, json={'camera_id': 'CAM-PK-01', 'confidence': 0.5})
    assert response.status_code == 409
    assert 'PK_01' in response.json()['detail']


def test_a_detection_without_confidence_is_refused() -> None:
    with _client(RobotLinkRegistry()) as client:
        response = client.post(ROUTE, json={'camera_id': 'CAM-PK-01'})
    assert response.status_code == 422


def test_the_request_never_carries_a_robot_id() -> None:
    """카메라 명부가 정본이다. 요청이 로봇을 지정하면 둘이 어긋날 수 있다."""
    links = RobotLinkRegistry()
    writer = _Writer()
    links.attach('PK_01', writer)
    with _client(links) as client:
        response = client.post(
            ROUTE, json={'camera_id': 'CAM-PK-01', 'confidence': 0.5, 'robot_id': 'PK_02'}
        )
    assert response.status_code == 422, '알 수 없는 field 는 거절한다'
