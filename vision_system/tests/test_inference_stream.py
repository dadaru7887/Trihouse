"""PC2 Vision runtime의 RTSP 입력 계약 테스트."""

from pathlib import Path
import re
import unittest

from vision_system.inference_common.stream import (
    InferenceStreamConfig,
    build_ffmpeg_frame_command,
)


ROOT = Path(__file__).resolve().parents[2]
CANONICAL_URL = 'rtsp://10.0.0.40:8554/pinky/CAM-PK-01'


class InferenceStreamConfigTest(unittest.TestCase):
    def test_camera_id_is_derived_from_the_stream_path(self) -> None:
        # 경로가 논리 ID 를 싣게 된 이상 `VISION_CAMERA_ID` 는 중복 정보다.
        # 중복 정보는 어긋날 수 있고, `front` 와 `pinky_1` 이 갈라진 방식이
        # 정확히 그것이었다. 파생하면 어긋날 수 없다.
        config = InferenceStreamConfig.from_env({
            'VISION_RTSP_URL': CANONICAL_URL,
            'VISION_INFERENCE_FPS': '10',
        })

        self.assertEqual('CAM-PK-01', config.camera_id)
        self.assertEqual(10, config.inference_fps)

    def test_missing_url_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            InferenceStreamConfig.from_env({})

    def test_camera_id_environment_variable_is_no_longer_consulted(self) -> None:
        # 남아 있는 배포 환경이 옛 변수를 계속 넘기더라도 URL 이 이긴다.
        config = InferenceStreamConfig.from_env({
            'VISION_RTSP_URL': CANONICAL_URL,
            'VISION_CAMERA_ID': 'front',
        })

        self.assertEqual('CAM-PK-01', config.camera_id)

    def test_credentials_in_the_url_do_not_leak_into_the_camera_id(self) -> None:
        # read 가 계정으로 막혀 있으므로 PC2 의 URL 은 자격 증명을 달고 온다.
        config = InferenceStreamConfig(
            input_uri='rtsp://viewer:s3cret@10.0.0.40:8554/pinky/CAM-PK-01',
        )

        self.assertEqual('CAM-PK-01', config.camera_id)

    def test_trailing_slash_does_not_change_the_camera_id(self) -> None:
        self.assertEqual(
            'CAM-PK-01',
            InferenceStreamConfig(input_uri=CANONICAL_URL + '/').camera_id,
        )

    def test_url_whose_final_segment_is_not_a_safe_identifier_is_rejected(self) -> None:
        for uri in (
            'rtsp://10.0.0.40:8554/pinky/CAM PK 01',
            'rtsp://10.0.0.40:8554/pinky/-leading-dash',
            'rtsp://10.0.0.40:8554/pinky/' + 'x' * 65,
        ):
            with self.subTest(uri=uri), self.assertRaises(ValueError):
                InferenceStreamConfig(input_uri=uri)

    def test_decoder_outputs_unbuffered_bgr_frames_over_stdout(self) -> None:
        command = build_ffmpeg_frame_command(InferenceStreamConfig(
            input_uri=CANONICAL_URL,
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
            InferenceStreamConfig(input_uri='https://example/video')
        with self.assertRaises(ValueError):
            InferenceStreamConfig(input_uri=CANONICAL_URL, width=0)


class SingleStreamContractTest(unittest.TestCase):
    def test_the_camera_id_variable_is_gone_from_every_deployment_surface(self) -> None:
        # 정의를 찾는다. 이름이 산문에 나오는 것은 막지 않는다 — 왜 없앴는지
        # 설명하는 주석까지 실패로 만들면 설명을 지우는 쪽으로 압력이 간다.
        for relative, definition in (
            ('compose.ai_5080.yaml', r'^\s*VISION_CAMERA_ID\s*:'),
            ('.env.example', r'^\s*VISION_CAMERA_ID\s*='),
        ):
            with self.subTest(file=relative):
                text = (ROOT / relative).read_text(encoding='utf-8')

                self.assertIsNone(re.search(definition, text, re.MULTILINE))


if __name__ == '__main__':
    unittest.main()
