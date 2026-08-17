"""PC1 MediaMTX로 들어가는 카메라 ingress 계약 테스트."""

from pathlib import Path
import unittest

from control_tower.gateway.camera_registry import load_camera_registry
from vision_system.stream_hub.ingress import (
    StreamIdentity,
    UsbIngressConfig,
    UsbVideoFormat,
    VideoEncoder,
    build_usb_ingress_command,
)


REGISTRY = Path(__file__).resolve().parents[2] / 'config' / 'cameras.yaml'


class StreamIdentityTest(unittest.TestCase):
    def test_canonical_path_is_shared_by_native_rtsp_and_usb_publishers(self) -> None:
        identity = StreamIdentity(role='fixed', camera_id='CAM-FIXED-01')

        self.assertEqual('fixed/CAM-FIXED-01', identity.path)
        self.assertEqual(
            'rtsp://10.0.0.40:8554/fixed/CAM-FIXED-01',
            identity.publish_url('rtsp://10.0.0.40:8554'),
        )

    def test_composed_path_matches_the_registry_for_every_registered_camera(self) -> None:
        # ingress 는 등록 정본을 실행 시점에 읽지 않는다. Pinky 부팅 경로와 마찬가지로
        # 파일 의존을 늘리지 않기 위해서다. 대신 두 경로 규칙이 같은 문자열을 만드는지
        # 여기서 대조한다. 규칙이 갈라지면 배포 전에 이 테스트가 먼저 깨진다.
        for record in load_camera_registry(REGISTRY):
            role = record.stream_path.split('/', 1)[0]
            identity = StreamIdentity(role=role, camera_id=record.camera_id)

            self.assertEqual(record.stream_path, identity.path)

    def test_unsafe_identity_or_non_rtsp_base_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            StreamIdentity(role='../pinky', camera_id='CAM-PK-01')
        with self.assertRaises(ValueError):
            StreamIdentity(role='pinky', camera_id='CAM-PK-01').publish_url(
                'http://10.0.0.40:8554'
            )


class UsbIngressCommandTest(unittest.TestCase):
    def _config(self, **overrides: object) -> UsbIngressConfig:
        values: dict[str, object] = {
            'identity': StreamIdentity(role='fixed', camera_id='CAM-FIXED-01'),
            'device': '/dev/video0',
            'mediamtx_base_url': 'rtsp://10.0.0.40:8554',
        }
        values.update(overrides)
        return UsbIngressConfig(**values)

    def test_camera_h264_is_copied_without_reencoding(self) -> None:
        command = build_usb_ingress_command(
            self._config(input_format=UsbVideoFormat.H264, encoder=VideoEncoder.COPY)
        )

        self.assertEqual('h264', command[command.index('-input_format') + 1])
        self.assertEqual('copy', command[command.index('-c:v') + 1])
        self.assertEqual('tcp', command[command.index('-rtsp_transport') + 1])
        self.assertEqual('rtsp://10.0.0.40:8554/fixed/CAM-FIXED-01', command[-1])

    def test_raw_usb_uses_nvenc_low_latency_profile(self) -> None:
        command = build_usb_ingress_command(
            self._config(input_format=UsbVideoFormat.YUYV422, encoder=VideoEncoder.NVENC)
        )

        self.assertEqual('h264_nvenc', command[command.index('-c:v') + 1])
        self.assertEqual('15', command[command.index('-r') + 1])
        self.assertEqual('15', command[command.index('-g') + 1])
        self.assertEqual('0', command[command.index('-bf') + 1])
        self.assertEqual('3000k', command[command.index('-b:v') + 1])

    def test_copy_is_rejected_for_non_h264_usb_input(self) -> None:
        with self.assertRaises(ValueError):
            self._config(input_format=UsbVideoFormat.MJPEG, encoder=VideoEncoder.COPY)


if __name__ == '__main__':
    unittest.main()
