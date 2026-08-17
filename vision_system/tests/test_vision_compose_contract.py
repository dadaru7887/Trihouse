"""PC1/PC2 Compose 영상 경계의 정적 계약 테스트."""

from pathlib import Path
import re
import unittest

import yaml

from control_tower.gateway.camera_registry import load_camera_registry


ROOT = Path(__file__).resolve().parents[2]
MEDIAMTX_CONFIG = ROOT / 'config' / 'mediamtx.yml'

# 2026-08-06 물리 검증(599.93초 / 8,997 프레임)이 돌아간 판본. 증거가 가리키는
# 판본과 다른 판본을 배포하면 그 증거가 무효가 된다.
MEDIAMTX_VERSION = '1.19.3'


def _registered_stream_paths() -> set[str]:
    return {record.stream_path for record in load_camera_registry(ROOT / 'config' / 'cameras.yaml')}


def _mediamtx_document() -> dict:
    return yaml.safe_load(MEDIAMTX_CONFIG.read_text(encoding='utf-8'))


class VisionComposeContractTest(unittest.TestCase):
    def test_pc1_exposes_one_mediamtx_rtsp_ingress(self) -> None:
        compose = (ROOT / 'compose.edge_4060.yaml').read_text(encoding='utf-8')

        self.assertIn('${EDGE_BIND_ADDRESS:-127.0.0.1}:8554:8554/tcp', compose)
        self.assertEqual(1, compose.count('image: bluenviron/mediamtx:'))

    def test_pc1_pins_the_physically_validated_mediamtx_version(self) -> None:
        compose = (ROOT / 'compose.edge_4060.yaml').read_text(encoding='utf-8')

        self.assertIn(f'image: bluenviron/mediamtx:{MEDIAMTX_VERSION}', compose)


class MediamtxAuthorizationContractTest(unittest.TestCase):
    """MediaMTX 인가 정책이 파일로 존재하고 마운트되는지 확인한다.

    설정을 마운트하지 않으면 MediaMTX 는 익명 publish/read/playback 기본값으로
    뜬다. Pinky 가 원격에서 publish 해야 해서 8554 는 LAN 에 열려 있으므로,
    설정이 없다는 것은 곧 LAN 의 아무 호스트나 스트림을 덮어쓰거나 들여다볼 수
    있다는 뜻이다.
    """

    def test_compose_mounts_the_authorization_configuration(self) -> None:
        compose = (ROOT / 'compose.edge_4060.yaml').read_text(encoding='utf-8')

        self.assertIn('./config/mediamtx.yml:/mediamtx.yml:ro', compose)

    def test_configuration_file_exists_and_uses_internal_authentication(self) -> None:
        document = _mediamtx_document()

        self.assertEqual('internal', document.get('authMethod'))

    def test_anonymous_read_and_playback_are_absent(self) -> None:
        # `user: any` 는 익명 접속을 포함한다. 그 항목이 read 나 playback 을 들고
        # 있으면 계정 인증은 장식일 뿐이다.
        for entry in _mediamtx_document()['authInternalUsers']:
            if entry.get('user') != 'any':
                continue
            actions = {permission['action'] for permission in entry.get('permissions') or []}

            self.assertEqual(set(), actions & {'read', 'playback'}, entry)

    def test_every_publish_permission_is_scoped_to_a_registered_path(self) -> None:
        registered = _registered_stream_paths()
        publish_paths = [
            permission.get('path')
            for entry in _mediamtx_document()['authInternalUsers']
            for permission in entry.get('permissions') or []
            if permission['action'] == 'publish'
        ]

        self.assertTrue(publish_paths, 'no publish permission is declared')
        for path in publish_paths:
            self.assertIn(path, registered)

    def test_every_publish_entry_is_restricted_to_an_address_list(self) -> None:
        # publish 는 계정이 아니라 출발지 IP 로 막는다. RTSP 는 자격 증명을 URL
        # 안에만 실을 수 있어서, 계정으로 막으면 로봇의 package-share YAML 과
        # `ps` 출력에 비밀번호가 노출된다.
        for entry in _mediamtx_document()['authInternalUsers']:
            actions = {permission['action'] for permission in entry.get('permissions') or []}
            if 'publish' not in actions:
                continue

            self.assertTrue(entry.get('ips'), f'publish entry without an address list: {entry}')

    def test_read_requires_a_named_account(self) -> None:
        readers = [
            entry
            for entry in _mediamtx_document()['authInternalUsers']
            if any(
                permission['action'] == 'read' for permission in entry.get('permissions') or []
            )
        ]

        self.assertTrue(readers, 'no read account is declared')
        for entry in readers:
            self.assertNotEqual('any', entry['user'])

    def test_no_password_literal_is_tracked(self) -> None:
        # 비밀번호는 추적되는 파일에 들어가지 않는다. 파일에는 빈 자리만 두고
        # 실제 값은 Compose 가 `MTX_AUTHINTERNALUSERS_<i>_PASS` 로 주입한다.
        for entry in _mediamtx_document()['authInternalUsers']:
            self.assertIn(entry.get('pass'), (None, ''), f'{entry["user"]} carries a password')

    def test_declared_paths_cover_every_publish_permission(self) -> None:
        # MediaMTX 는 `paths` 에 없는 경로를 400 으로 거절한다. 마운트한 설정이
        # 기본 설정을 통째로 대체하므로, `paths` 를 빠뜨리면 인가가 아무리
        # 옳아도 스트림이 하나도 붙지 않는다.
        document = _mediamtx_document()
        declared = set((document.get('paths') or {}).keys())
        publish_paths = {
            permission.get('path')
            for entry in document['authInternalUsers']
            for permission in entry.get('permissions') or []
            if permission['action'] == 'publish'
        }

        self.assertTrue(publish_paths <= declared, publish_paths - declared)

    def test_environment_example_carries_placeholders_not_values(self) -> None:
        example = (ROOT / '.env.example').read_text(encoding='utf-8')

        self.assertIn('MTX_VIEWER_PASS=', example)
        self.assertIn('PINKY_PK_01_IP=', example)
        self.assertIn('PINKY_PK_02_IP=', example)
        self.assertIn('PC1_PUBLISHER_IP=', example)

        match = re.search(r'^MTX_VIEWER_PASS=(?P<value>.*)$', example, re.MULTILINE)
        assert match is not None
        self.assertIn('change_me', match.group('value'))

    def test_compose_injects_the_viewer_password_from_the_environment(self) -> None:
        compose = (ROOT / 'compose.edge_4060.yaml').read_text(encoding='utf-8')

        self.assertIn('MTX_VIEWER_PASS', compose)
        self.assertNotIn('MTX_RECORD:', compose)


class Pc2StreamContractTest(unittest.TestCase):
    def test_pc2_receives_rtsp_contract_without_database_credentials(self) -> None:
        compose = (ROOT / 'compose.ai_5080.yaml').read_text(encoding='utf-8')

        self.assertIn('VISION_RTSP_URL:', compose)
        self.assertIn('VISION_INFERENCE_FPS:', compose)
        self.assertNotIn('MYSQL_ROOT_PASSWORD', compose)
        self.assertNotIn('FMS_DB_PASSWORD', compose)

    def test_no_separate_camera_id_variable_is_defined(self) -> None:
        # 카메라 정체는 URL 의 마지막 segment 에서 파생한다. 변수로 또 받으면
        # 둘이 어긋날 수 있다. 정의만 금지하고 산문 속 언급은 허용한다 —
        # 왜 없는지 설명하는 주석까지 막으면 설명을 지우는 쪽으로 압력이 간다.
        compose = (ROOT / 'compose.ai_5080.yaml').read_text(encoding='utf-8')
        example = (ROOT / '.env.example').read_text(encoding='utf-8')

        self.assertIsNone(re.search(r'^\s*VISION_CAMERA_ID\s*:', compose, re.MULTILINE))
        self.assertIsNone(re.search(r'^\s*VISION_CAMERA_ID\s*=', example, re.MULTILINE))

    def test_environment_example_has_separate_pc1_and_pc2_addresses(self) -> None:
        example = (ROOT / '.env.example').read_text(encoding='utf-8')

        self.assertIn('PC1_LAN_IP=', example)
        self.assertIn('VISION_RTSP_URL=rtsp://${PC1_LAN_IP}:8554/pinky/CAM-PK-01', example)


if __name__ == '__main__':
    unittest.main()
