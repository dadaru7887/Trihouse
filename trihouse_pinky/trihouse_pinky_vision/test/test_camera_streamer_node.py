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
    """Provide a continuously healthy in-memory supervisor."""

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


class RestartingSupervisor(FakeSupervisor):
    """Simulate a publisher exit followed by a reset frame counter."""

    def __init__(self):
        super().__init__()
        self.poll_count = 0

    def poll(self, _now):
        self.poll_count += 1
        if self.poll_count == 1:
            progress = ProgressSample(100, 15.0, 100 / 15.0)
            alive = True
        elif self.poll_count == 2:
            progress = None
            alive = False
        else:
            progress = ProgressSample(1, 15.0, 1 / 15.0)
            alive = True
        return SupervisorSnapshot(
            processes_alive=alive,
            progress=progress,
            total_encoded_bytes=self.bytes_written,
            exit_reason='' if alive else 'publisher_exit:1',
            restart_delay=None,
        )

    def schedule_restart(self, _now):
        pass


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


def test_frame_timestamp_starts_unknown_and_accepts_counter_reset(ros_context):
    supervisor = RestartingSupervisor()
    times = iter([0.0, 1.0, 2.0])
    node = CameraStreamerNode(
        supervisor_factory=lambda *_args, **_kwargs: supervisor,
        monotonic=lambda: next(times),
    )
    try:
        assert node._last_frame_stamp.sec == 0
        assert node._last_frame_stamp.nanosec == 0

        node._on_timer()
        node._on_timer()
        node._on_timer()

        assert node._last_frame_count == 1
    finally:
        node.destroy_node()
