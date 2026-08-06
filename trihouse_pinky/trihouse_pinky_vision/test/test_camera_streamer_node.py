import time

import pytest
import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.parameter import Parameter

from trihouse_interfaces.msg import StreamHealth
from trihouse_pinky_vision.camera_streamer_node import CameraStreamerNode
from trihouse_pinky_vision.process_metrics import ProgressSample
from trihouse_pinky_vision.process_supervisor import SupervisorSnapshot


class FakeSupervisor:
    def __init__(self):
        self.started = False
        self.stopped = False
        self.frame = 0
        self.bytes_written = 1_000_000

    def start(self):
        self.started = True

    def poll(self, _now):
        self.frame += 15
        self.bytes_written += 250_000
        return SupervisorSnapshot(
            processes_alive=True,
            progress=ProgressSample(self.frame, 15.0, self.frame / 15.0),
            total_encoded_bytes=self.bytes_written,
            exit_reason='',
            restart_delay=None,
        )

    def restart_due(self, _now):
        return False

    def schedule_restart(self, _now):
        raise AssertionError('healthy stream must not schedule a restart')

    def restart(self):
        raise AssertionError('healthy stream must not restart')

    def mark_healthy(self, _now):
        pass

    def stop(self):
        self.stopped = True


@pytest.fixture
def ros_context():
    rclpy.init()
    yield
    rclpy.shutdown()


def test_publishes_stream_health_from_supervisor_progress(ros_context):
    supervisor = FakeSupervisor()
    node = CameraStreamerNode(
        supervisor_factory=lambda *_args, **_kwargs: supervisor,
        parameter_overrides=[
            Parameter('health_publish_hz', value=20.0),
            Parameter('healthy_after_sec', value=0.0),
        ],
    )
    observer = Node('stream_health_test_observer')
    messages = []
    observer.create_subscription(
        StreamHealth,
        '/trihouse/vision/stream_health',
        messages.append,
        10,
    )
    executor = SingleThreadedExecutor()
    executor.add_node(node)
    executor.add_node(observer)
    try:
        deadline = time.monotonic() + 2.0
        while not messages and time.monotonic() < deadline:
            executor.spin_once(timeout_sec=0.05)

        assert messages
        message = messages[-1]
        assert message.camera_id == 'pinky_1'
        assert message.state == StreamHealth.STATE_HEALTHY
        assert message.fps == pytest.approx(15.0)
        assert message.detail == 'healthy'
        assert supervisor.started
    finally:
        executor.remove_node(observer)
        executor.remove_node(node)
        observer.destroy_node()
        node.destroy_node()

    assert supervisor.stopped


def test_invalid_profile_refuses_to_create_supervisor(ros_context):
    def forbidden_factory(*_args, **_kwargs):
        raise AssertionError('supervisor must not be created')

    with pytest.raises(ValueError, match='width'):
        CameraStreamerNode(
            supervisor_factory=forbidden_factory,
            parameter_overrides=[Parameter('width', value=0)],
        )
