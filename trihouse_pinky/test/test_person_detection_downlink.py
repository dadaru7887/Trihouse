"""관제가 내려보낸 사람 관측이 안전 gate 까지 닿는 계약.

## 왜 이 경로인가

`system_overview.md` 의 **금지 연결**에 `VLM/RL → Safety Supervisor 우회` 가 있다.
5080 의 추론 결과는 로봇에 직접 꽂히지 않고 4060 관제를 거친다. 로봇 쪽 마지막
한 홉이 `gateway_node` 이고, `keep_out_zones` 가 이미 같은 길로 온다.

## 왜 명령이 아니라 관측인가

`keep_out_zone` 은 명령이라 `message_id` 로 중복을 거르고 건건이 ack 한다. 사람
감지는 10~15 Hz 로 흐르는 **관측**이다. 같은 처리를 하면 `seen` 목록이 무한히
커지고 ack 가 초당 열몇 개씩 역류해 링크를 채운다. 최신 값만 의미가 있고
신선도는 `ttl_ms` 가 싣는다 — `safety_supervisor._on_person` 이 그것으로 만료를
본다.

## 왜 pose 를 비우는가

카메라 내부 파라미터가 없다. `config/cameras.yaml` 이 같은 이유로 `map_pose` 를
`null` 로 두며 **"좌표를 지어내지 않는다"** 고 적었다. (0, 0) 으로 채우면 거리 0,
즉 최대 위험으로 읽혀 안전해 **보이지만**, 나중에 진짜 값이 들어와도 아무도
차이를 느끼지 못해 캘리브레이션이 안 된 것을 영영 모른다.

비워도 안전은 동작한다 — gate 는 `confidence > 0` 을 `person_detected` 로 읽고,
정책은 거리와 무관하게 SLOW 를 건다. 캘리브레이션은 나중에 이것을 **좁히는**
역할이다(5 m 밖의 사람에는 감속하지 않도록).
"""

import sys
from pathlib import Path

import pytest

PINKY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PINKY / "trihouse_pinky_fleet"))

from trihouse_pinky_fleet.protocol import (  # noqa: E402
    ProtocolError,
    parse_person_detection,
)


def _payload(**overrides) -> dict:
    payload = {
        "type": "person_detection",
        "camera_id": "CAM-PK-01",
        "confidence": 0.82,
        "observed_at_ms": 1_787_000_000_000,
        "ttl_ms": 600,
    }
    payload.update(overrides)
    return payload


def test_a_detection_carries_what_the_gate_needs() -> None:
    observation = parse_person_detection(_payload())
    assert observation.camera_id == "CAM-PK-01"
    assert observation.confidence == pytest.approx(0.82)
    assert observation.ttl_ms == 600


def test_the_pose_is_absent_until_the_camera_is_calibrated() -> None:
    """지어낸 좌표를 싣지 않는다. 없는 것은 없는 채로 온다."""
    assert parse_person_detection(_payload()).pose is None


def test_a_calibrated_sender_may_carry_a_pose() -> None:
    """캘리브레이션이 끝나면 같은 계약으로 거리가 실린다 — 파서를 안 바꾼다."""
    observation = parse_person_detection(_payload(pose={"x": 1.2, "y": -0.4}))
    assert observation.pose == (pytest.approx(1.2), pytest.approx(-0.4))


def test_a_bounding_box_is_optional_but_kept_whole() -> None:
    """일부만 온 bbox 는 없는 것으로 본다. 반쪽 사각형은 쓸 데가 없다."""
    assert parse_person_detection(_payload()).bbox is None
    boxed = parse_person_detection(
        _payload(bbox={"x_offset": 10, "y_offset": 20, "width": 30, "height": 40})
    )
    assert boxed.bbox == (10, 20, 30, 40)
    with pytest.raises(ProtocolError):
        parse_person_detection(_payload(bbox={"x_offset": 10, "width": 30}))


def test_a_detection_without_confidence_is_refused() -> None:
    """`confidence` 가 gate 의 유일한 판단 근거다. 없으면 통과시키지 않는다."""
    payload = _payload()
    del payload["confidence"]
    with pytest.raises(ProtocolError):
        parse_person_detection(payload)


def test_confidence_outside_zero_to_one_is_refused() -> None:
    for value in (-0.1, 1.5):
        with pytest.raises(ProtocolError):
            parse_person_detection(_payload(confidence=value))


def test_a_zero_confidence_detection_is_refused() -> None:
    """gate 가 `confidence > 0` 으로 읽으므로 0 은 관측이 아니다.

    "사람이 없다" 를 confidence 0 으로 보내면 gate 에서 조용히 무시된다.
    보내지 않는 것과 구분되지 않으므로 아예 받지 않는다.
    """
    with pytest.raises(ProtocolError):
        parse_person_detection(_payload(confidence=0.0))


def test_a_detection_without_a_camera_is_refused() -> None:
    """어느 카메라가 봤는지 모르면 나중에 오검출을 되짚을 수 없다."""
    with pytest.raises(ProtocolError):
        parse_person_detection(_payload(camera_id=""))


def test_a_missing_ttl_falls_back_to_a_short_life() -> None:
    """만료가 없으면 한 번 본 사람이 영원히 옆에 서 있는 것이 된다."""
    payload = _payload()
    del payload["ttl_ms"]
    assert parse_person_detection(payload).ttl_ms > 0


def test_a_negative_ttl_is_refused() -> None:
    with pytest.raises(ProtocolError):
        parse_person_detection(_payload(ttl_ms=-1))


def test_the_wrong_message_type_is_refused() -> None:
    with pytest.raises(ProtocolError):
        parse_person_detection(_payload(type="keep_out_zone"))


def test_an_observation_needs_no_message_id() -> None:
    """관측은 명령이 아니다. `message_id` 도 ack 도 요구하지 않는다.

    10~15 Hz 로 흐르는 것에 명령 규약을 씌우면 `seen` 목록이 무한히 커지고
    ack 가 역류해 링크를 채운다.
    """
    payload = _payload()
    assert "message_id" not in payload
    assert parse_person_detection(payload).confidence > 0


# ------------------------------------------------------- 노드 배선 계약

import inspect  # noqa: E402

from trihouse_pinky_fleet import gateway_node  # noqa: E402

HANDLER = inspect.getsource(gateway_node.GatewayNode._handle_person_detection)
DRAIN = inspect.getsource(gateway_node.GatewayNode._drain)


def test_the_observation_reaches_the_topic_the_gate_listens_on() -> None:
    """`safety_supervisor` 가 구독하는 이름과 한 글자라도 다르면 조용히 끊긴다."""
    source = inspect.getsource(gateway_node.GatewayNode.__init__)
    assert "'trihouse/vision/person_detection/base'" in source

    safety = inspect.getsource(
        __import__(
            'trihouse_pinky_safety.safety_supervisor_node',
            fromlist=['SafetySupervisor'],
        ).SafetySupervisor.__init__
    )
    assert "'trihouse/vision/person_detection/base'" in safety


def test_an_observation_is_never_acknowledged() -> None:
    """10~15 Hz 관측에 ack 를 붙이면 역방향 링크가 초당 열몇 개로 찬다."""
    assert "'command_ack'" not in HANDLER


def test_an_observation_is_not_deduplicated_by_message_id() -> None:
    """`seen` 에 쌓으면 목록이 무한히 커진다. 관측은 최신 값만 의미가 있다."""
    assert "self.seen" not in HANDLER


def test_a_broken_observation_does_not_block_the_ones_behind_it() -> None:
    """하나가 깨졌다고 뒤따르는 정상 관측까지 버리면 사람이 보여도 안 느려진다."""
    assert "return" in HANDLER and "raise" not in HANDLER


def test_the_frame_is_only_claimed_when_a_pose_is_carried() -> None:
    """좌표가 없는데 `base_footprint` 를 적으면 없는 측정을 주장하는 것이다."""
    assert "'base_footprint' if observation.pose else ''" in HANDLER


def test_the_drain_loop_dispatches_person_detection() -> None:
    """분기를 빠뜨리면 관측이 inbox 에서 조용히 버려진다."""
    assert "'person_detection'" in DRAIN
    assert "_handle_person_detection" in DRAIN
