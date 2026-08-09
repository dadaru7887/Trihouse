"""재연결하는 작은 NDJSON client. ROS publisher와 모터 제어 권한은 소유하지 않는다."""
from __future__ import annotations

import json
import socket
import threading
import time
from collections.abc import Callable


class NdjsonClient:
    def __init__(self, host: str, port: int, on_message: Callable[[dict], None], on_state: Callable[[bool], None]) -> None:
        self.host, self.port, self.on_message, self.on_state = host, port, on_message, on_state
        self._lock = threading.Lock(); self._socket: socket.socket | None = None; self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None: self._thread.start()
    def stop(self) -> None:
        self._stop.set()
        with self._lock: sock, self._socket = self._socket, None
        if sock is not None: sock.close()
        self._thread.join(timeout=2.0)

    def send(self, payload: dict) -> None:
        wire = (json.dumps(payload, ensure_ascii=False, separators=(',', ':')) + '\n').encode('utf-8')
        with self._lock: sock = self._socket
        if sock is None: return
        try: sock.sendall(wire)
        except OSError: self._disconnect()

    def _disconnect(self) -> None:
        with self._lock: sock, self._socket = self._socket, None
        if sock is not None:
            try: sock.close()
            except OSError: pass
        self.on_state(False)

    def _run(self) -> None:
        delay = 0.5
        while not self._stop.is_set():
            try: sock = socket.create_connection((self.host, self.port), timeout=3.0)
            except OSError:
                self._stop.wait(delay); delay = min(delay * 2, 5.0); continue
            delay = 0.5; sock.settimeout(1.0)
            with self._lock: self._socket = sock
            self.on_state(True); buffer = b''
            while not self._stop.is_set():
                try: chunk = sock.recv(4096)
                except socket.timeout: continue
                except OSError: break
                if not chunk: break
                buffer += chunk
                while b'\n' in buffer:
                    raw, buffer = buffer.split(b'\n', 1)
                    try:
                        message = json.loads(raw.decode('utf-8'))
                        if isinstance(message, dict): self.on_message(message)
                    except (UnicodeDecodeError, ValueError):
                        continue
            self._disconnect()
