"""운영 read model을 REST/WebSocket으로 내보내는 작은 Gateway adapter.

UI에는 Gateway가 소유한 view만 공개한다. 인증과 지속 WebSocket fan-out은 배포 단계에서 추가한다.
"""
from __future__ import annotations

from dataclasses import asdict
import base64
from hashlib import sha1
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from threading import Thread
from typing import Mapping
from urllib.parse import unquote, urlsplit

from .operations_feed import OperationsFeed


class OperationsHttpServer:
    def __init__(self, feed: OperationsFeed, *, camera_playback_urls: Mapping[str, str] | None = None, host: str = '127.0.0.1', port: int = 0) -> None:
        self._feed = feed
        handler = self._make_handler(feed, dict(camera_playback_urls or {}))
        self._server = ThreadingHTTPServer((host, port), handler)
        self._thread = Thread(target=self._server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self._server.server_address[:2]
        return f'http://{host}:{port}'

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2)

    @staticmethod
    def _make_handler(feed: OperationsFeed, camera_playback_urls: Mapping[str, str]) -> type[BaseHTTPRequestHandler]:
        operations_ui = Path(__file__).resolve().parents[1] / 'ui' / 'operations'
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                path = urlsplit(self.path).path
                if path == '/':
                    self._static(operations_ui / 'index.html', 'text/html; charset=utf-8')
                    return
                if path == '/operations.js':
                    self._static(operations_ui / 'operations.js', 'application/javascript; charset=utf-8')
                    return
                if path == '/api/v1/operations':
                    snapshot = feed.snapshot()
                    self._json(200, {
                        'robots': [asdict(robot) for robot in snapshot.robots],
                        'jobs': [asdict(job) for job in snapshot.jobs],
                        'incidents': [asdict(incident) for incident in snapshot.incidents],
                    })
                    return
                if path == '/api/v1/events':
                    self._json(200, {'events': [asdict(event) for event in feed.drain_events()]})
                    return
                if path == '/api/v1/events/ws':
                    self._websocket_events()
                    return
                if path.startswith('/api/v1/cameras/') and path.endswith('/playback'):
                    camera_id = unquote(path.removeprefix('/api/v1/cameras/').removesuffix('/playback')).strip('/')
                    playback_url = camera_playback_urls.get(camera_id)
                    self._json(200, {'camera_id': camera_id, 'playback_url': playback_url}) if playback_url else self._json(404, {'error': 'camera playback is not configured'})
                    return
                self._json(404, {'error': 'not found'})

            def _json(self, status: int, payload: dict) -> None:
                body = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
                self.send_response(status)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _static(self, path: Path, content_type: str) -> None:
                """독립 Trihouse UI asset만 제공한다. RoboSapiens 파일은 읽거나 수정하지 않는다."""
                try:
                    body = path.read_bytes()
                except OSError:
                    self._json(404, {'error': 'operations UI asset not found'})
                    return
                self.send_response(200); self.send_header('Content-Type', content_type); self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)

            def _websocket_events(self) -> None:
                key = self.headers.get('Sec-WebSocket-Key', '')
                if self.headers.get('Upgrade', '').lower() != 'websocket' or not key:
                    self._json(400, {'error': 'websocket upgrade required'})
                    return
                accept = base64.b64encode(sha1((key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
                self.send_response(101, 'Switching Protocols')
                self.send_header('Upgrade', 'websocket')
                self.send_header('Connection', 'Upgrade')
                self.send_header('Sec-WebSocket-Accept', accept)
                self.end_headers()
                payload = json.dumps({'events': [asdict(event) for event in feed.drain_events()]}, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
                if len(payload) >= 126:
                    raise ValueError('one-shot event payload exceeds minimal WebSocket frame size')
                self.wfile.write(bytes((0x81, len(payload))) + payload)
                self.wfile.flush()
                self.close_connection = True

            def log_message(self, format: str, *args: object) -> None:
                return

        return Handler
