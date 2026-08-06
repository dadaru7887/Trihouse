import threading
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

    def mark_unhealthy(self):
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


class OrderingSupervisor(FakeSupervisor):
    """Record failure publication and restart ordering."""

    def __init__(self, events):
        super().__init__()
        self.events = events
        self.restarted = False
        self.restart_started = threading.Event()
        self.restart_release = threading.Event()
        self.restart_finished = threading.Event()

    def poll(self, _now):
        if self.restarted:
            return SupervisorSnapshot(
                processes_alive=True,
                progress=ProgressSample(1, 15.0, 1 / 15.0),
                total_encoded_bytes=self.bytes_written,
                exit_reason='',
                restart_delay=None,
            )
        return SupervisorSnapshot(
            processes_alive=False,
            progress=ProgressSample(100, 15.0, 100 / 15.0),
            total_encoded_bytes=None,
            exit_reason='publisher_exit:7',
            restart_delay=0.0,
        )

    def schedule_restart(self, _now):
        self.events.append('schedule')

    def restart_due(self, _now):
        return not self.restarted

    def restart(self):
        self.events.append('restart')
        self.restart_started.set()
        self.restart_release.wait(timeout=2.0)
        self.restarted = True
        self.restart_finished.set()


class RecordingPublisher:
    """Capture a published health message in a shared event list."""

    def __init__(self, events):
        self.events = events
        self.messages = []

    def publish(self, message):
        self.messages.append(message)
        self.events.append('publish')


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
        assert message.detail == 'healthy:bitrate_unavailable:warmup'
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


def test_publishes_disconnection_and_bitrate_reason_before_restart(ros_context):
    events = []
    supervisor = OrderingSupervisor(events)
    node = CameraStreamerNode(
        supervisor_factory=lambda *_args, **_kwargs: supervisor,
        monotonic=lambda: 10.0,
    )
    publisher = RecordingPublisher(events)
    node._publisher = publisher
    callback_done = threading.Event()

    def invoke_timer():
        node._on_timer()
        callback_done.set()

    callback_thread = threading.Thread(target=invoke_timer)
    try:
        callback_thread.start()
        assert supervisor.restart_started.wait(timeout=1.0)
        returned_before_restart_finished = callback_done.wait(timeout=0.2)

        if returned_before_restart_finished:
            node._on_timer()
            assert publisher.messages[-1].state == StreamHealth.STATE_RECOVERING
            assert publisher.messages[-1].detail.startswith('restart_in_progress')

        assert events[:3] == ['schedule', 'publish', 'restart']
        assert publisher.messages[0].state == StreamHealth.STATE_DISCONNECTED
        assert publisher.messages[0].bitrate_kbps == 0.0
        assert publisher.messages[0].detail.endswith(
            ':bitrate_unavailable:byte_counter_unavailable'
        )
        assert returned_before_restart_finished

        supervisor.restart_release.set()
        assert supervisor.restart_finished.wait(timeout=1.0)
        deadline = time.monotonic() + 1.0
        while node._restart_is_running() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert not node._restart_is_running()
        node._on_timer()

        assert node._last_frame_count == 1
        assert events.count('restart') == 1
    finally:
        supervisor.restart_release.set()
        callback_thread.join(timeout=1.0)
        node.destroy_node()
