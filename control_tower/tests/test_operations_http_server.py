"""Gateway REST read-model adapter의 통합 테스트."""
from __future__ import annotations

import json
import socket
import unittest
from urllib.request import urlopen

from control_tower.gateway.http_server import OperationsHttpServer
from control_tower.gateway.operations_feed import OperationsFeed, RobotView


class OperationsHttpServerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.feed = OperationsFeed()
        self.feed.upsert_robot(RobotView('PK-01', 1, 2, 0, 80, 'SAFE', '', 'IDLE', ''))
        self.server = OperationsHttpServer(self.feed, camera_playback_urls={'cam-1': 'https://video.example/live/cam-1.m3u8'})
        self.server.start()

    def tearDown(self) -> None:
        self.server.stop()

    def test_operations_snapshot_is_available_over_gateway_rest(self) -> None:
        """Browser UI reads the view model without a database or ROS connection."""
        with urlopen(f'{self.server.base_url}/api/v1/operations', timeout=2) as response:
            body = json.loads(response.read())
        self.assertEqual(200, response.status)
        self.assertEqual('PK-01', body['robots'][0]['robot_id'])

    def test_separate_trihouse_operations_ui_uses_only_gateway_routes(self) -> None:
        """RoboSapiens를 바꾸지 않는 별도 UI는 Gateway read model만 사용해야 한다."""
        with urlopen(f'{self.server.base_url}/', timeout=2) as response:
            page = response.read().decode()
        self.assertEqual(200, response.status)
        self.assertIn('Trihouse 통합 관제', page)
        self.assertIn('/operations.js', page)
        with urlopen(f'{self.server.base_url}/operations.js', timeout=2) as response:
            script = response.read().decode()
        self.assertIn('/api/v1/operations', script)
        self.assertIn('/api/v1/events/ws', script)

    def test_camera_playback_url_is_exposed_only_when_configured(self) -> None:
        """카메라를 선택한 UI만 Gateway의 재생 URL을 받는다."""
        with urlopen(f'{self.server.base_url}/api/v1/cameras/cam-1/playback', timeout=2) as response:
            body = json.loads(response.read())
        self.assertEqual('https://video.example/live/cam-1.m3u8', body['playback_url'])


    def test_event_endpoint_returns_priority_ordered_gateway_events(self) -> None:
        """A UI transport adapter can poll events until a WebSocket server is attached."""
        with urlopen(f'{self.server.base_url}/api/v1/events', timeout=2) as response:
            body = json.loads(response.read())
        self.assertEqual('ROBOT_UPDATED', body['events'][0]['kind'])

    def test_websocket_upgrade_pushes_gateway_event_payload(self) -> None:
        """A browser can upgrade to the read-only event endpoint without direct backend access."""
        host, port = self.server.base_url.removeprefix('http://').split(':')
        with socket.create_connection((host, int(port)), timeout=2) as client:
            client.sendall(
                b'GET /api/v1/events/ws HTTP/1.1\r\n'
                + f'Host: {host}:{port}\r\n'.encode()
                + b'Upgrade: websocket\r\nConnection: Upgrade\r\n'
                + b'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nSec-WebSocket-Version: 13\r\n\r\n'
            )
            chunks = []
            while True:
                chunk = client.recv(4096)
                if not chunk:
                    break
                chunks.append(chunk)
            response = b''.join(chunks)
        self.assertIn(b'101 Switching Protocols', response)
        self.assertIn(b'ROBOT_UPDATED', response)


if __name__ == '__main__':
    unittest.main()
