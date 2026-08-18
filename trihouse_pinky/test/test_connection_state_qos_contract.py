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


def test_connection_state_publisher_latches_the_last_value():
    assert PUBLISHER_QOS.durability == QoSDurabilityPolicy.TRANSIENT_LOCAL
    assert PUBLISHER_QOS.reliability == QoSReliabilityPolicy.RELIABLE


def test_connection_state_subscriber_uses_the_same_profile_as_the_publisher():
    assert SUBSCRIBER_QOS.durability == PUBLISHER_QOS.durability
    assert SUBSCRIBER_QOS.reliability == PUBLISHER_QOS.reliability
    assert SUBSCRIBER_QOS.depth == PUBLISHER_QOS.depth
