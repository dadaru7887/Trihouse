from builtin_interfaces.msg import Time

from trihouse_interfaces.msg import StreamHealth


def test_stream_health_contract_round_trips_all_fields():
    message = StreamHealth()
    message.camera_id = 'CAM-PK-01'
    message.state = StreamHealth.STATE_HEALTHY
    message.fps = 15.0
    message.bitrate_kbps = 2000.0
    message.last_frame_stamp = Time(sec=10, nanosec=20)
    message.detail = 'healthy'
    message.stamp = Time(sec=11, nanosec=30)

    assert StreamHealth.STATE_UNKNOWN == 0
    assert StreamHealth.STATE_HEALTHY == 1
    assert StreamHealth.STATE_DEGRADED == 2
    assert StreamHealth.STATE_DISCONNECTED == 3
    assert StreamHealth.STATE_RECOVERING == 4
    assert message.camera_id == 'CAM-PK-01'
    assert message.state == 1
    assert message.fps == 15.0
    assert message.bitrate_kbps == 2000.0
    assert message.last_frame_stamp == Time(sec=10, nanosec=20)
    assert message.detail == 'healthy'
    assert message.stamp == Time(sec=11, nanosec=30)
