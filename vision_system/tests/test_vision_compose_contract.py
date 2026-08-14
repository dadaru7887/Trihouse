"""PC1/PC2 Compose 영상 경계의 정적 계약 테스트."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class VisionComposeContractTest(unittest.TestCase):
    def test_pc1_exposes_one_mediamtx_rtsp_ingress(self) -> None:
        compose = (ROOT / 'compose.edge_4060.yaml').read_text(encoding='utf-8')

        self.assertIn('${EDGE_BIND_ADDRESS:-127.0.0.1}:8554:8554/tcp', compose)
        self.assertIn('MTX_RTSPTRANSPORTS: tcp', compose)
        self.assertEqual(1, compose.count('image: bluenviron/mediamtx:'))

    def test_pc2_receives_rtsp_contract_without_database_credentials(self) -> None:
        compose = (ROOT / 'compose.ai_5080.yaml').read_text(encoding='utf-8')

        self.assertIn('VISION_RTSP_URL:', compose)
        self.assertIn('VISION_CAMERA_ID:', compose)
        self.assertIn('VISION_INFERENCE_FPS:', compose)
        self.assertNotIn('MYSQL_ROOT_PASSWORD', compose)
        self.assertNotIn('FMS_DB_PASSWORD', compose)

    def test_environment_example_has_separate_pc1_and_pc2_addresses(self) -> None:
        example = (ROOT / '.env.example').read_text(encoding='utf-8')

        self.assertIn('PC1_LAN_IP=', example)
        self.assertIn('VISION_RTSP_URL=rtsp://${PC1_LAN_IP}:8554/pinky/PK_01/front', example)


if __name__ == '__main__':
    unittest.main()
