"""ROS 2 node that supervises Pinky's RTSP camera publisher."""

import time
from typing import Callable

from builtin_interfaces.msg import Time
import rclpy
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy

from trihouse_interfaces.msg import StreamHealth

from .command_builder import build_ffmpeg_command, build_rpicam_command, StreamConfig
from .process_metrics import EncodedBitrateSampler
from .process_supervisor import ProcessSupervisor
from .stream_health import StreamHealthStateMachine, StreamState


class CameraStreamerNode(Node):
    def __init__(
        self,
        *,
        supervisor_factory: Callable[..., ProcessSupervisor] = ProcessSupervisor,
        monotonic: Callable[[], float] = time.monotonic,
        parameter_overrides: list[Parameter] | None = None,
    ) -> None:
        super().__init__('camera_streamer', parameter_overrides=parameter_overrides)
        self._monotonic = monotonic
        self._stopped = False
        self._declare_parameters()
        config = self._stream_config()
        restart_delays = tuple(
            float(value) for value in self.get_parameter('restart_backoff_sec').value
        )
        if not restart_delays or any(value <= 0 for value in restart_delays):
            raise ValueError('restart_backoff_sec values must be positive')

        self._supervisor = supervisor_factory(
            build_rpicam_command(config),
            build_ffmpeg_command(config),
            restart_delays=restart_delays,
        )
        self._monitor = StreamHealthStateMachine(
            target_fps=config.fps,
            degraded_after_sec=float(self.get_parameter('degraded_after_sec').value),
            disconnected_after_sec=float(self.get_parameter('disconnected_after_sec').value),
            healthy_after_sec=float(self.get_parameter('healthy_after_sec').value),
        )
        self._bitrate = EncodedBitrateSampler()
        self._camera_id = config.camera_id
        self._last_frame_count: int | None = None
        self._last_frame_stamp = Time()
        qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.VOLATILE,
        )
        self._publisher = self.create_publisher(
            StreamHealth,
            '/trihouse/vision/stream_health',
            qos,
        )
        self._supervisor.start()
        rate = float(self.get_parameter('health_publish_hz').value)
        if rate <= 0:
            self._supervisor.stop()
            raise ValueError('health_publish_hz must be positive')
        self._timer = self.create_timer(1.0 / rate, self._on_timer)

    def _declare_parameters(self) -> None:
        defaults = StreamConfig()
        values = {
            'camera_id': defaults.camera_id,
            'camera_index': defaults.camera_index,
            'publish_uri': defaults.publish_uri,
            'width': defaults.width,
            'height': defaults.height,
            'fps': defaults.fps,
            'bitrate_kbps': defaults.bitrate_kbps,
            'keyframe_interval': defaults.keyframe_interval,
            'hflip': defaults.hflip,
            'vflip': defaults.vflip,
            'encoder': defaults.encoder,
            'encoder_preset': defaults.encoder_preset,
            'encoder_profile': defaults.encoder_profile,
            'transport': defaults.transport,
            'rpicam_executable': defaults.rpicam_executable,
            'ffmpeg_executable': defaults.ffmpeg_executable,
            'health_publish_hz': 1.0,
            'degraded_after_sec': 1.0,
            'disconnected_after_sec': 3.0,
            'healthy_after_sec': 5.0,
            'restart_backoff_sec': [1.0, 2.0, 4.0, 8.0, 16.0, 30.0],
        }
        for name, value in values.items():
            self.declare_parameter(name, value)

    def _stream_config(self) -> StreamConfig:
        return StreamConfig(
            camera_id=str(self.get_parameter('camera_id').value),
            camera_index=int(self.get_parameter('camera_index').value),
            publish_uri=str(self.get_parameter('publish_uri').value),
            width=int(self.get_parameter('width').value),
            height=int(self.get_parameter('height').value),
            fps=float(self.get_parameter('fps').value),
            bitrate_kbps=int(self.get_parameter('bitrate_kbps').value),
            keyframe_interval=int(self.get_parameter('keyframe_interval').value),
            hflip=bool(self.get_parameter('hflip').value),
            vflip=bool(self.get_parameter('vflip').value),
            encoder=str(self.get_parameter('encoder').value),
            encoder_preset=str(self.get_parameter('encoder_preset').value),
            encoder_profile=str(self.get_parameter('encoder_profile').value),
            transport=str(self.get_parameter('transport').value),
            rpicam_executable=str(self.get_parameter('rpicam_executable').value),
            ffmpeg_executable=str(self.get_parameter('ffmpeg_executable').value),
        )

    def _on_timer(self) -> None:
        now = self._monotonic()
        snapshot = self._supervisor.poll(now)
        bitrate = self._bitrate.sample(snapshot.total_encoded_bytes, now)
        health = self._monitor.update(snapshot.progress, snapshot.processes_alive, now, bitrate)

        if snapshot.progress is not None and (
            health.reason == 'frames_resumed'
            or self._last_frame_count is None
            or snapshot.progress.frame_count > self._last_frame_count
        ):
            self._last_frame_count = snapshot.progress.frame_count
            self._last_frame_stamp = self.get_clock().now().to_msg()

        if health.state == StreamState.HEALTHY:
            self._supervisor.mark_healthy(now)
        else:
            self._supervisor.mark_unhealthy()
            if health.state == StreamState.DISCONNECTED:
                self._supervisor.schedule_restart(now)

        message = StreamHealth()
        message.camera_id = self._camera_id
        message.state = int(health.state)
        message.fps = float(health.fps)
        message.bitrate_kbps = float(health.bitrate_kbps)
        message.last_frame_stamp = self._last_frame_stamp
        detail = [health.reason]
        if snapshot.exit_reason:
            detail.append(snapshot.exit_reason)
        if self._bitrate.unavailable_reason:
            detail.extend(['bitrate_unavailable', self._bitrate.unavailable_reason])
        message.detail = ':'.join(detail)
        message.stamp = self.get_clock().now().to_msg()
        self._publisher.publish(message)

        if self._supervisor.restart_due(now):
            self.get_logger().warning(f'restarting camera pipeline: {health.reason}')
            self._supervisor.restart()

    def destroy_node(self) -> bool:
        if not self._stopped:
            self._stopped = True
            self._supervisor.stop()
        return super().destroy_node()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = CameraStreamerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()
