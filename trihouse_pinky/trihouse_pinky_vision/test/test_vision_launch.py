import os
from pathlib import Path
import signal
import subprocess
import time

import rclpy
from rclpy.node import Node

from trihouse_interfaces.msg import StreamHealth


FIXTURES = Path(__file__).parent / 'fixtures'


def test_launch_publishes_healthy_state_with_hardware_free_processes(tmp_path):
    config = tmp_path / 'fixture.yaml'
    config.write_text(
        f'''camera_streamer:
  ros__parameters:
    camera_id: pinky_1
    publish_uri: rtsp://192.168.0.9:8554/pinky_1
    health_publish_hz: 20.0
    healthy_after_sec: 0.0
    rpicam_executable: {FIXTURES / "fake_camera.py"}
    ffmpeg_executable: {FIXTURES / "fake_publisher.py"}
''',
        encoding='utf-8',
    )
    environment = os.environ.copy()
    environment['ROS_DOMAIN_ID'] = '77'
    process = subprocess.Popen(
        [
            'ros2', 'launch', 'trihouse_pinky_vision', 'vision.launch.py',
            f'config_file:={config}',
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=environment,
    )
    os.environ['ROS_DOMAIN_ID'] = '77'
    rclpy.init()
    observer = Node('vision_launch_test_observer')
    messages = []
    observer.create_subscription(
        StreamHealth,
        '/trihouse/vision/stream_health',
        messages.append,
        10,
    )
    try:
        deadline = time.monotonic() + 8.0
        while time.monotonic() < deadline and not any(
            message.state == StreamHealth.STATE_HEALTHY for message in messages
        ):
            rclpy.spin_once(observer, timeout_sec=0.1)

        assert any(message.state == StreamHealth.STATE_HEALTHY for message in messages)
    finally:
        observer.destroy_node()
        rclpy.shutdown()
        process.send_signal(signal.SIGINT)
        output, _ = process.communicate(timeout=5.0)

    assert process.returncode == 0, output
