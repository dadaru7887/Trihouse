"""Python 3.10 LeRobot worker served over one local Unix socket."""

from __future__ import annotations

import argparse
import os
import socketserver
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .ipc_protocol import (
    IpcProtocolError,
    MAX_FRAME_BYTES,
    ResultCache,
    decode_message,
    encode_message,
    validate_worker_command,
)


class WorkerCommandProcessor:
    """Validate identity and make command replay non-motional."""

    def __init__(
        self,
        device_id: str,
        execute: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> None:
        self._device_id = device_id
        self._execute = execute
        self._cache = ResultCache()

    def process(self, command: dict[str, Any]) -> dict[str, Any]:
        validated = validate_worker_command(command, local_device_id=self._device_id)
        cached = self._cache.lookup(validated)
        if cached is not None:
            return cached
        result = self._execute(validated)
        if not isinstance(result, dict) or not isinstance(result.get("success"), bool):
            raise IpcProtocolError("INVALID_EXECUTOR_RESULT")
        result.setdefault("command_uuid", validated["command_uuid"])
        self._cache.store(validated, result)
        return result


class _RequestHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        frame = self.rfile.readline(MAX_FRAME_BYTES + 1)
        try:
            command = decode_message(frame)
            result = self.server.processor.process(command)  # type: ignore[attr-defined]
        except Exception as error:  # noqa: BLE001
            result = {
                "success": False,
                "reason_code": type(error).__name__.upper(),
                "detail": str(error),
            }
        self.wfile.write(encode_message(result))


class UnixWorkerServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True

    def __init__(self, socket_path: str, processor: WorkerCommandProcessor) -> None:
        self.processor = processor
        super().__init__(socket_path, _RequestHandler)


def serve(socket_path: str, processor: WorkerCommandProcessor) -> None:
    path = Path(socket_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    server = UnixWorkerServer(str(path), processor)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        if path.exists():
            path.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device-id", default=os.environ.get("DEVICE_ID", ""))
    parser.add_argument(
        "--socket-path",
        default=os.environ.get("OMX_WORKER_SOCKET", "/run/trihouse-omx/worker.sock"),
    )
    args = parser.parse_args()
    if not args.device_id:
        raise SystemExit("DEVICE_ID is required")
    from .hardware_runtime import HardwareRuntime

    runtime = HardwareRuntime.from_environment(device_id=args.device_id)
    serve(args.socket_path, WorkerCommandProcessor(args.device_id, runtime.execute))


if __name__ == "__main__":
    main()
