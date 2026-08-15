"""관제센터(robo_control)와의 NDJSON/TCP 링크.

한 줄 = JSON 한 건. 관제센터가 서버(기본 127.0.0.1:8788), 로봇 에이전트가
클라이언트다. 연결이 끊기면 백그라운드 스레드가 자동으로 재접속하며,
그동안 로봇은 마지막 명령을 유지하지 않고 안전 정지한다.

프로토콜(proto 1)
─────────────────
로봇 → 관제
  hello      최초 1회. 로봇 마스터 데이터 + 현재 포즈.
  telemetry  주기 보고. 위치(unit) · 방위 · 배터리 · 속도 · 남은 웨이포인트.
  log        로봇이 관제 이력에 남기고 싶은 사건(라이다 정지 등).

관제 → 로봇
  welcome    좌표계 파라미터(scale/width/height).
  path       주행 웨이포인트 목록(unit). 빈 배열이면 정지.
  hold       안전 정지 래치(on/off) + 사유.
  speed      허용 속도 상한(unit/s). 구획 환경·안전 필드가 반영된 값.
  charge     충전 개시/종료.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from collections import deque
from typing import Callable


class ControlLink:
    PROTO = 1

    def __init__(
        self,
        host: str,
        port: int,
        hello: dict,
        on_message: Callable[[dict], None],
        on_state: Callable[[bool], None] | None = None,
        logger=None,
    ) -> None:
        self._host = host
        self._port = port
        self._hello = dict(hello)
        self._on_message = on_message
        self._on_state = on_state
        self._log = logger

        self._sock: socket.socket | None = None
        self._lock = threading.Lock()
        self._outbox: deque[dict] = deque(maxlen=64)
        self._connected = False
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    # ────────────────────────────────────────────────────────── 공개 API

    @property
    def connected(self) -> bool:
        return self._connected

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            sock, self._sock = self._sock, None
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()
        self._thread.join(timeout=2.0)

    def send(self, payload: dict) -> None:
        """한 건 전송. 미연결 상태면 조용히 버린다(텔레메트리는 최신값이 곧 진실)."""
        with self._lock:
            sock = self._sock
        if sock is None:
            return
        line = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        try:
            sock.sendall(line)
        except OSError:
            self._drop()

    # ────────────────────────────────────────────────────────── 내부

    def _info(self, msg: str) -> None:
        if self._log is not None:
            self._log.info(msg)

    def _drop(self) -> None:
        with self._lock:
            sock, self._sock = self._sock, None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        if self._connected:
            self._connected = False
            self._info("관제 링크 끊김 — 재접속 대기")
            if self._on_state is not None:
                self._on_state(False)

    def _run(self) -> None:
        backoff = 0.5
        while not self._stop.is_set():
            try:
                sock = socket.create_connection((self._host, self._port), timeout=3.0)
            except OSError:
                time.sleep(backoff)
                backoff = min(backoff * 1.6, 5.0)
                continue

            backoff = 0.5
            sock.settimeout(1.0)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            with self._lock:
                self._sock = sock
            self._connected = True
            self._info(f"관제 링크 접속 {self._host}:{self._port}")
            if self._on_state is not None:
                self._on_state(True)

            self.send({"t": "hello", "proto": self.PROTO, **self._hello})
            self._read_loop(sock)
            self._drop()

    def _read_loop(self, sock: socket.socket) -> None:
        buf = b""
        while not self._stop.is_set():
            try:
                chunk = sock.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                return
            if not chunk:
                return
            buf += chunk
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    msg = json.loads(raw.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    continue
                try:
                    self._on_message(msg)
                except Exception as exc:  # 콜백 예외가 링크를 죽이지 않게 한다
                    if self._log is not None:
                        self._log.error(f"관제 메시지 처리 실패: {exc}")
