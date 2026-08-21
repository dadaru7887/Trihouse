"""Camera-frame ArUco 관측을 검증된 TF로만 base-frame으로 변환한다."""

from __future__ import annotations

import rclpy
import tf2_geometry_msgs  # noqa: F401 - registers geometry message transforms
import tf2_ros
from geometry_msgs.msg import PoseStamped
from rclpy.duration import Duration
from rclpy.node import Node
from rclpy.qos import QoSDurabilityPolicy, QoSHistoryPolicy, QoSProfile, QoSReliabilityPolicy
from trihouse_interfaces.msg import MarkerObservation, Readiness


READY_QOS = QoSProfile(
    depth=1,
    history=QoSHistoryPolicy.KEEP_LAST,
    reliability=QoSReliabilityPolicy.RELIABLE,
    durability=QoSDurabilityPolicy.TRANSIENT_LOCAL,
)


class MarkerObservationTransformer(Node):
    """Camera pose를 base pose로 위장하지 않는 marker docking 안전 경계."""

    def __init__(self) -> None:
        super().__init__('marker_observation_transformer')
        self.declare_parameter('robot_id', 'PK_02')
        self.declare_parameter('camera_id', 'CAM-PK-02')
        self.declare_parameter('camera_frame', 'camera_optical_frame')
        self.declare_parameter('base_frame', 'base_footprint')
        self.declare_parameter('calibration_verified', False)
        self.declare_parameter('observation_timeout_s', 0.5)
        self.robot_id = str(self.get_parameter('robot_id').value)
        self.camera_id = str(self.get_parameter('camera_id').value)
        self.camera_frame = str(self.get_parameter('camera_frame').value)
        self.base_frame = str(self.get_parameter('base_frame').value)
        self.calibration_verified = bool(self.get_parameter('calibration_verified').value)
        self.timeout_s = float(self.get_parameter('observation_timeout_s').value)

        self.buffer = tf2_ros.Buffer()
        self.listener = tf2_ros.TransformListener(self.buffer, self)
        self.base_pub = self.create_publisher(
            MarkerObservation, 'trihouse/vision/marker_observation/base', 10
        )
        self.ready_pub = self.create_publisher(Readiness, 'trihouse/vision/readiness', READY_QOS)
        self.create_subscription(
            MarkerObservation,
            'trihouse/vision/marker_observation/camera',
            self._on_camera_observation,
            10,
        )
        self._publish_readiness(False, 'calibration_not_verified')

    def _publish_readiness(self, ready: bool, detail: str) -> None:
        message = Readiness()
        message.stamp = self.get_clock().now().to_msg()
        message.robot_id = self.robot_id
        message.state = Readiness.STATE_READY if ready else Readiness.STATE_NOT_READY
        message.missing_interfaces = [] if ready else [detail]
        message.details = [detail]
        self.ready_pub.publish(message)

    def _on_camera_observation(self, message: MarkerObservation) -> None:
        # sender와 transformer 설정이 다르면 다른 카메라의 좌표가 PK02를 움직일
        # 수 있다. 일치하지 않으면 조용히 변환하지 않고 명시적으로 NOT_READY다.
        if not self.calibration_verified:
            self._publish_readiness(False, 'calibration_not_verified')
            return
        if message.camera_id != self.camera_id or message.marker_family != 'DICT_5X5_50':
            self._publish_readiness(False, 'camera_or_dictionary_mismatch')
            return
        if message.header.frame_id != self.camera_frame:
            self._publish_readiness(False, 'camera_frame_mismatch')
            return
        if message.ttl_ms == 0 or message.ttl_ms / 1000.0 > self.timeout_s:
            self._publish_readiness(False, 'observation_ttl_invalid')
            return
        pose = PoseStamped()
        pose.header = message.header
        pose.pose = message.pose.pose
        try:
            transformed = self.buffer.transform(
                pose, self.base_frame, timeout=Duration(seconds=0.1)
            )
        except (
            tf2_ros.LookupException,
            tf2_ros.ConnectivityException,
            tf2_ros.ExtrapolationException,
            tf2_ros.TimeoutException,
        ):
            self._publish_readiness(False, 'camera_to_base_tf_unavailable')
            return
        output = MarkerObservation()
        output.header = transformed.header
        output.observation_id = message.observation_id
        output.robot_id = self.robot_id
        output.camera_id = message.camera_id
        output.marker_family = message.marker_family
        output.marker_id = message.marker_id
        output.pose.pose = transformed.pose
        output.pose.covariance = message.pose.covariance
        output.confidence = message.confidence
        output.ttl_ms = message.ttl_ms
        self.base_pub.publish(output)
        self._publish_readiness(True, 'camera_to_base_tf_verified')


def main() -> None:
    rclpy.init()
    node = MarkerObservationTransformer()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()
