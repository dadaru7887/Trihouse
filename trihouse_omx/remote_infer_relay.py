"""4060에 띄우는, 아무것도 이해하지 않는 순수 전달자(pass-through relay).

실제 운영 흐름은 OMX_01(로봇팔) -> 0.31(연결된 PC, remote_policy_runtime.py가
여기서 돈다) -> 4060 -> 5080(remote_infer_server.py, 실제 GPU 추론)이다.
팀원 확인대로 이 채널 전체(이미지+관절 상태+action 왕복)가 4060을 거쳐야
하므로, 4060에도 뭔가 떠 있어야 한다 — 이 파일이 그 자리를 채운다.

**추론도, JSON 해석도 하지 않는다.** `/v1/reset`/`/v1/infer_chunk` 요청
바디를 손대지 않고 그대로 `--backend-url`(오늘은 임시로 5080 대신 GPU 있는
다른 PC, 나중엔 진짜 5080)로 넘기고, 응답도 그대로 돌려준다 — 그래서
lerobot/cv2/torch가 전혀 필요 없고, 4060의 시스템 python3(3.12)로 바로
돌아간다(별도 venv 설치 불필요). backend가 5080이든 다른 PC든 이 파일은
안 바뀐다 — `--backend-url` 하나만 바꾸면 된다.

remote_policy_runtime.py(클라이언트)는 이미 `base_url` 하나에 그대로 POST할
뿐이라, `--remote-infer-url`을 5080 직접 주소 대신 이 중계 주소로 바꾸는 것
말고는 아무 코드도 안 바뀐다.

control_tower/gateway/http_server.py와 같은 stdlib
(`http.server.BaseHTTPRequestHandler` + `ThreadingHTTPServer`) 스타일.

실행: python3 remote_infer_relay.py --host 0.0.0.0 --port 8766 \\
    --backend-url http://192.168.0.32:8765
"""

from __future__ import annotations

import argparse
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

_RELAY_PATHS = ("/v1/reset", "/v1/infer_chunk")


def _make_handler(backend_url: str, timeout_s: float) -> type[BaseHTTPRequestHandler]:
    backend_url = backend_url.rstrip("/")

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            path = urlsplit(self.path).path
            if path not in _RELAY_PATHS:
                self._json(404, b'{"error": "not found"}')
                return

            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length)
            request = urllib.request.Request(
                backend_url + path, data=body, method="POST",
                headers={"Content-Type": "application/json"},
            )
            try:
                with urllib.request.urlopen(request, timeout=timeout_s) as response:
                    self._json(response.status, response.read())
            except urllib.error.HTTPError as error:
                # backend가 4xx/5xx로 응답한 것 그대로 전달(예: infer_chunk 세션 불일치 409)
                self._json(error.code, error.read())
            except (urllib.error.URLError, TimeoutError, OSError) as error:
                self._json(502, f'{{"error": "backend unreachable: {error}"}}'.encode())

        def _json(self, status: int, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument(
        "--backend-url", required=True,
        help="실제 추론 서버(remote_infer_server.py) 주소. 오늘은 임시 GPU PC, 나중엔 5080.",
    )
    parser.add_argument("--backend-timeout-s", type=float, default=30.0)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), _make_handler(args.backend_url, args.backend_timeout_s))
    print(f"[remote_infer_relay] listening on {args.host}:{args.port} -> backend {args.backend_url}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
