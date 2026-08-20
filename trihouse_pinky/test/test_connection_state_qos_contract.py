"""Control Tower 연결 상태 토픽의 QoS 계약.

`trihouse/fms/state` 는 흘러가는 사건이 아니라 **최신 값이 계속 유효한 사실**이다.
`gateway_node` 는 연결 상태가 바뀔 때만 발행하므로, 늦게 뜬 구독자가 그 한 번을
놓치면 영원히 모른다. 실제로 TCP 는 `ESTAB` 인데 `status_node` 가 로봇을
`control_link_offline` 로 굳혀 RMF 가 로봇을 받지 않는 일이 반복됐다.

문자열이 아니라 실제 QoS 객체를 본다. 그리고 양쪽이 **같은** 프로필이어야 한다 —
한쪽만 transient_local 이면 QoS 가 맞지 않아 아예 연결되지 않는다.
"""

from rclpy.qos import QoSDurabilityPolicy, QoSReliabilityPolicy

from trihouse_pinky_fleet.gateway_node import (
    CONNECTION_STATE_QOS as PUBLISHER_QOS,
)
from trihouse_pinky_fleet.status_node import (
    CONNECTION_STATE_QOS as SUBSCRIBER_QOS,
)
from trihouse_pinky_safety.safety_supervisor_node import (
    CONNECTION_STATE_QOS as SAFETY_QOS,
)


def test_connection_state_publisher_latches_the_last_value():
    assert PUBLISHER_QOS.durability == QoSDurabilityPolicy.TRANSIENT_LOCAL
    assert PUBLISHER_QOS.reliability == QoSReliabilityPolicy.RELIABLE


def test_connection_state_subscriber_uses_the_same_profile_as_the_publisher():
    assert SUBSCRIBER_QOS.durability == PUBLISHER_QOS.durability
    assert SUBSCRIBER_QOS.reliability == PUBLISHER_QOS.reliability
    assert SUBSCRIBER_QOS.depth == PUBLISHER_QOS.depth


def test_the_safety_gate_uses_the_same_profile_as_the_publisher():
    """`status_node` 만 고치고 `safety_supervisor` 를 빠뜨렸던 자리다.

    2026-08-20 실측: supervisor 를 다시 띄우자 TRANSIENT_LOCAL 구독은 1 개를
    받는데 VOLATILE 구독은 0 개였다. supervisor 는 `control_link_online` 을
    False 로 굳혀 `control_link_lost` STOP 을 걸었고, 그 STOP 이 `safety_blocked`
    -> `dispatchable=False` 로 이어져 로봇이 RMF 에서 빠졌다. TCP 는 내내
    ESTAB 이었고 Gateway 는 `STATE_ONLINE` 을 이미 발행한 뒤였다.

    이 gate 는 모터 `/cmd_vel` 의 유일한 발행자다. 여기서 놓치면 나머지 층이
    아무리 옳아도 로봇은 움직이지 않는다.
    """
    assert SAFETY_QOS.durability == PUBLISHER_QOS.durability
    assert SAFETY_QOS.reliability == PUBLISHER_QOS.reliability
    assert SAFETY_QOS.depth == PUBLISHER_QOS.depth
