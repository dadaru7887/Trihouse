"""GPU 있는 머신(5080)에서 돌리는 원격 ACT 추론 서버.

`remote_policy_runtime.py`(OMX_01에서 실행되는 클라이언트)가 관측(카메라
JPEG+관절 상태)을 HTTP로 보내면, 여기서 `policy_runtime.load_policy()`/
`policy_runtime.infer_chunk()`를 그대로 불러 실제 GPU 추론을 하고 action
청크(raw float, 100개)를 돌려준다. `dataset_features` 이름 매핑
(`make_robot_action`)은 클라이언트만 갖고 있으므로 여기선 하지 않는다.

`control_tower/gateway/http_server.py`와 같은 stdlib
(`http.server.BaseHTTPRequestHandler` + `ThreadingHTTPServer`) 스타일 —
Flask/FastAPI를 새로 끌어오지 않는다.

실행 전 준비(5080): `source ~/venv/ys_il/bin/activate` (Python 3.10.20,
lerobot은 `~/ys_workspace/il_ws/src/lerobot`에서 editable 설치돼 있어야
`import policy_runtime`이 lerobot을 찾는다 — 사용자 확인 완료).

실행: `~/venv/ys_il/bin/python3 remote_infer_server.py --host 0.0.0.0 --port 8765`
"""

from __future__ import annotations

import argparse
import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import cv2
import numpy as np

import policy_runtime

_POLICY_CACHE: dict[str, policy_runtime.LoadedPolicy] = {}
_session_by_repo: dict[str, str] = {}
_lock = threading.Lock()


def _decode_observation(observation: dict) -> dict:
    """remote_policy_runtime._encode_observation_frame()의 역함수."""
    decoded = {}
    for name, field in observation.items():
        if "jpeg_b64" in field:
            jpeg_bytes = base64.b64decode(field["jpeg_b64"])
            array = cv2.imdecode(np.frombuffer(jpeg_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
            if array is None:
                raise ValueError(f"{name} JPEG 디코딩 실패")
            decoded[name] = array
        else:
            decoded[name] = np.asarray(field["values"], dtype=np.float32)
    return decoded


def _reset(request: dict) -> dict:
    """정책을 처음이면 로드하고(체크포인트의 device: cuda 그대로), 세션을 기록한다."""
    repo_id = str(request["repo_id"])
    session_id = str(request["session_id"])
    with _lock:
        loaded = _POLICY_CACHE.get(repo_id)
        if loaded is None:
            loaded = policy_runtime.load_policy(repo_id)
            _POLICY_CACHE[repo_id] = loaded
        loaded.reset()
        _session_by_repo[repo_id] = session_id
    return {"ok": True}


def _infer_chunk(request: dict) -> dict:
    repo_id = str(request["repo_id"])
    session_id = str(request["session_id"])
    with _lock:
        current_session = _session_by_repo.get(repo_id)
        loaded = _POLICY_CACHE.get(repo_id)
    if current_session != session_id or loaded is None:
        raise PermissionError(f"{repo_id}: reset() 없이 infer_chunk 호출됨(세션 불일치)")

    observation_frame = _decode_observation(request["observation"])
    actions = policy_runtime.infer_chunk(
        observation_frame,
        loaded,
        task=str(request["task"]),
        robot_type=str(request["robot_type"]),
    )
    return {"actions": actions}


def _make_handler() -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            path = urlsplit(self.path).path
            try:
                length = int(self.headers.get("Content-Length") or 0)
                request = json.loads(self.rfile.read(length) or b"{}")
            except (ValueError, json.JSONDecodeError):
                self._json(400, {"error": "invalid request body"})
                return

            if path == "/v1/reset":
                self._handle(200, lambda: _reset(request))
                return
            if path == "/v1/infer_chunk":
                self._handle(200, lambda: _infer_chunk(request))
                return
            self._json(404, {"error": "not found"})

        def _handle(self, ok_status: int, action) -> None:
            try:
                self._json(ok_status, action())
            except PermissionError as error:
                self._json(409, {"error": str(error)})
            except (KeyError, ValueError) as error:
                self._json(400, {"error": str(error)})

        def _json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
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
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), _make_handler())
    print(f"[remote_infer_server] listening on {args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
