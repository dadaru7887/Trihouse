"""PC1 MediaMTX로 들어가는 카메라 ingress 계약 테스트."""

import unittest

from vision_system.stream_hub.ingress import (
    StreamIdentity,
    UsbIngressConfig,
    UsbVideoFormat,
    VideoEncoder,
    build_usb_ingress_command,
)


class StreamIdentityTest(unittest.TestCase):
    def test_canonical_path_is_shared_by_native_rtsp_and_usb_publishers(self) -> None:
        identity = StreamIdentity(robot_id='PK_01', camera_id='front')

        self.assertEqual('pinky/PK_01/front', identity.path)
        self.assertEqual(
            'rtsp://10.0.0.40:8554/pinky/PK_01/front',
            identity.publish_url('rtsp://10.0.0.40:8554'),
        )

    def test_unsafe_identity_or_non_rtsp_base_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            StreamIdentity(robot_id='../PK_01', camera_id='front')
        with self.assertRaises(ValueError):
            StreamIdentity(robot_id='PK_01', camera_id='front').publish_url('http://10.0.0.40:8554')


class UsbIngressCommandTest(unittest.TestCase):
    def _config(self, **overrides: object) -> UsbIngressConfig:
        values: dict[str, object] = {
            'identity': StreamIdentity(robot_id='PK_01', camera_id='front'),
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
        self.assertEqual('rtsp://10.0.0.40:8554/pinky/PK_01/front', command[-1])

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
