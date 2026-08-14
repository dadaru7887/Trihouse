"""PC2 Vision runtime의 RTSP 입력 계약 테스트."""

import unittest

from vision_system.inference_common.stream import (
    InferenceStreamConfig,
    build_ffmpeg_frame_command,
)


class InferenceStreamConfigTest(unittest.TestCase):
    def test_environment_requires_canonical_rtsp_input(self) -> None:
        config = InferenceStreamConfig.from_env({
            'VISION_RTSP_URL': 'rtsp://10.0.0.40:8554/pinky/PK_01/front',
            'VISION_CAMERA_ID': 'front',
            'VISION_INFERENCE_FPS': '10',
        })

        self.assertEqual('front', config.camera_id)
        self.assertEqual(10, config.inference_fps)

        with self.assertRaises(ValueError):
            InferenceStreamConfig.from_env({})

    def test_decoder_outputs_unbuffered_bgr_frames_over_stdout(self) -> None:
        command = build_ffmpeg_frame_command(InferenceStreamConfig(
            input_uri='rtsp://10.0.0.40:8554/pinky/PK_01/front',
            camera_id='front',
            width=640,
            height=384,
            inference_fps=10,
        ))

        self.assertEqual('tcp', command[command.index('-rtsp_transport') + 1])
        self.assertIn('nobuffer', command)
        # FFmpeg가 허용하는 최소 probesize는 32 byte다.
        self.assertEqual('32', command[command.index('-probesize') + 1])
        self.assertEqual('0', command[command.index('-analyzeduration') + 1])
        self.assertEqual('bgr24', command[command.index('-pix_fmt') + 1])
        self.assertEqual('rawvideo', command[command.index('-f') + 1] if command.count('-f') == 1 else command[-2])
        self.assertEqual('pipe:1', command[-1])

    def test_non_rtsp_and_invalid_dimensions_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            InferenceStreamConfig(input_uri='https://example/video', camera_id='front')
        with self.assertRaises(ValueError):
            InferenceStreamConfig(
                input_uri='rtsp://10.0.0.40:8554/pinky/PK_01/front',
                camera_id='front',
                width=0,
            )


if __name__ == '__main__':
    unittest.main()
