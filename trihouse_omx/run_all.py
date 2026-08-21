#!/usr/bin/env python3
"""camera_relay.py + stream_wrist_camera.py + job_loop.py를 한 번에 상시 실행한다.

지금까지는 사람이 터미널 세 개를 열어서 이 셋을 따로 띄워야 했다. 이 스크립트는
셋을 subprocess로 띄우고, 하나가 죽으면 backoff 후 재시작하며, 시작 순서(카메라
가상장치가 준비된 뒤에 나머지 둘)와 종료 시 시그널 전파를 관리한다 —
camera_relay.py/stream_wrist_camera.py가 내부적으로 ffmpeg 자식을 관리하는
방식과 같은 스타일이다.

systemd는 아직 안 쓴다 — 이 저장소에 systemd 유닛 전례가 없고, 실제 OMX PC에
설치하는 건 코드 변경과 별개의 운영 결정이라서다. 이 스크립트는 나중에
`ExecStart=python3 run_all.py ...`로 그대로 감쌀 수 있다.

인터프리터 주의(1단계에서부터 쭉 지켜온 규칙, 그대로 반영):
  - camera_relay.py / job_loop.py: lerobot venv 파이썬 (torch/lerobot 필요)
  - stream_wrist_camera.py: 시스템 python3.12 (vision_system.stream_hub.ingress가
    쓰는 enum.StrEnum이 3.11+ 필요, lerobot venv는 3.10)
경로를 하드코딩하지 않고 --venv-python/--system-python 인자로 받는다 — 다른
머신에서 경로가 다를 수 있으므로.

실행 전: 이 스크립트 자체는 시스템 python3로 돌린다(lerobot/torch 불필요).
실행 예:
    python3 run_all.py --port /dev/ttyACM0 --zone frozen \\
        --gateway-url http://127.0.0.1:8080 --mediamtx-url rtsp://127.0.0.1:8554
"""

from __future__ import annotations

import argparse
import signal
import subprocess
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent

DEFAULT_VENV_PYTHON = str(Path.home() / "venv" / "il" / "bin" / "python3")
DEFAULT_SYSTEM_PYTHON = "python3.12"

# camera_relay.py가 실물 wrist 카메라를 열어 가상장치 두 개로 나눠준 뒤에야
# job_loop.py/stream_wrist_camera.py가 각자의 가상장치를 열 수 있다 — 그 전에
# 열면 장치가 없거나(아직 v4l2loopback에 프레임이 안 흐름) 실패한다.
DEFAULT_STARTUP_DELAY_S = 3.0

# 자식이 죽었을 때 곧바로 다시 띄우지 않는다 — 카메라가 뽑혔거나 포트가 잘못된
# 것처럼 즉시 재실패하는 상황에서 CPU를 계속 태우며 도는 걸 막는다.
DEFAULT_RESTART_BACKOFF_S = 5.0

RELAY_VIDEO10 = "/dev/video10"  # 정책 추론(job_loop.py) 전용
RELAY_VIDEO11 = "/dev/video11"  # RTSP 송신(stream_wrist_camera.py) 전용


class _Shutdown:
    def __init__(self) -> None:
        self.requested = False

    def install(self) -> None:
        signal.signal(signal.SIGINT, self._on_signal)
        signal.signal(signal.SIGTERM, self._on_signal)

    def _on_signal(self, signum, frame) -> None:  # noqa: ANN001
        del signum, frame
        self.requested = True


class _Child:
    """이름 붙은 subprocess 하나. 재시작 가능 상태를 스스로 들고 있는다."""

    def __init__(self, name: str, command: list[str]) -> None:
        self.name = name
        self.command = command
        self.process: subprocess.Popen | None = None

    def start(self) -> None:
        print(f"[run_all] starting {self.name}: {' '.join(self.command)}")
        self.process = subprocess.Popen(self.command)

    def is_alive(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def terminate(self, *, timeout_s: float = 5.0) -> None:
        if self.process is None or self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            print(f"[run_all] {self.name} did not exit in {timeout_s}s — killing")
            self.process.kill()


def _build_children(args: argparse.Namespace) -> list[_Child]:
    relay_cmd = [args.venv_python, str(_HERE / "camera_relay.py")]

    job_loop_cmd = [
        args.venv_python, str(_HERE / "job_loop.py"),
        "--port", args.port,
        "--zone", args.zone,
        "--gateway-url", args.gateway_url,
        "--wrist-cam", RELAY_VIDEO10,
    ]
    if args.front_cam:
        job_loop_cmd += ["--front-cam", args.front_cam]

    stream_cmd = [
        args.system_python, str(_HERE / "stream_wrist_camera.py"),
        "--mediamtx-url", args.mediamtx_url,
        "--wrist-cam", RELAY_VIDEO11,
        "--input-format", "yuyv422",
    ]

    return [
        _Child("camera_relay", relay_cmd),
        _Child("job_loop", job_loop_cmd),
        _Child("stream_wrist_camera", stream_cmd),
    ]


def run(args: argparse.Namespace) -> int:
    shutdown = _Shutdown()
    shutdown.install()

    children = _build_children(args)
    relay, rest = children[0], children[1:]

    relay.start()
    print(f"[run_all] waiting {args.startup_delay_s}s for camera_relay to set up v4l2loopback devices…")
    time.sleep(args.startup_delay_s)
    for child in rest:
        child.start()

    backoff_until: dict[str, float] = {}
    try:
        while not shutdown.requested:
            now = time.monotonic()
            for child in children:
                if child.is_alive():
                    continue
                if now < backoff_until.get(child.name, 0.0):
                    continue
                exit_code = child.process.returncode if child.process else None
                print(f"[run_all] {child.name} exited (code={exit_code}) — restarting in {args.restart_backoff_s}s")
                backoff_until[child.name] = now + args.restart_backoff_s
                child.start()
            time.sleep(0.5)
    finally:
        print("\n[run_all] shutting down — terminating children…")
        for child in children:
            child.terminate()

    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", required=True, help="OMX follower serial port, e.g. /dev/ttyACM0")
    parser.add_argument("--zone", required=True, choices=("frozen", "chilled", "ambient"))
    parser.add_argument("--gateway-url", required=True, help="job_loop.py --gateway-url에 그대로 넘김")
    parser.add_argument("--mediamtx-url", required=True, help="stream_wrist_camera.py --mediamtx-url에 그대로 넘김")
    parser.add_argument("--front-cam", default=None, help="생략하면 job_loop.py가 set_cameras.py 저장값을 씀")
    parser.add_argument("--venv-python", default=DEFAULT_VENV_PYTHON, help=f"lerobot venv 파이썬 경로. 기본 {DEFAULT_VENV_PYTHON}")
    parser.add_argument("--system-python", default=DEFAULT_SYSTEM_PYTHON, help=f"stream_wrist_camera.py용 시스템 파이썬. 기본 {DEFAULT_SYSTEM_PYTHON}")
    parser.add_argument("--startup-delay-s", type=float, default=DEFAULT_STARTUP_DELAY_S)
    parser.add_argument("--restart-backoff-s", type=float, default=DEFAULT_RESTART_BACKOFF_S)
    return parser


if __name__ == "__main__":
    sys.exit(run(_parser().parse_args()))
