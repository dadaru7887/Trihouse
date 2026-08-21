#!/usr/bin/env python3
"""wrist 카메라를 정책 추론과 RTSP 송신이 동시에 볼 수 있게 중계한다.

문제: 실측 결과 이 USB 카메라는 두 프로세스가 동시에 열 수 없다
(cv2.VideoCapture가 이미 열려 있는 장치를 ffmpeg가 열면 곧바로 실패, 반대도
마찬가지). 즉 deliver.py(정책 추론)와 stream_wrist_camera.py(RTSP 송신, QR
인식용)가 같은 물리 장치(/dev/video4)를 동시에 못 연다.

v4l2loopback 가상장치 하나로 우회를 시도했으나, 이것도 실측 결과 안 된다 —
exclusive_caps=1 + 기본 max_buffers=2 조합에서는 진짜 동시 활성 리더가 2개면
나중에 여는 쪽이 실패한다(먼저 한 테스트는 순차 open이라 착시였음).

해법: 실제 카메라는 이 relay 프로세스 **하나만** 열고, 가상장치를 **두 개**
만들어 각각 정확히 리더 하나씩만 붙인다.
    /dev/video10 (OMX_wrist_policy) -> deliver.py (정책 추론) 전용
    /dev/video11 (OMX_wrist_stream) -> stream_wrist_camera.py (RTSP 송신) 전용
이 relay 프로세스가 ffmpeg 출력을 두 장치에 동시에 씀으로써, 가상장치 각각은
"리더 하나"라는, 실측으로 확인된 안전한 조건을 유지한다.

해상도는 640x480 하나로 통일한다. 정책은 이 해상도가 필수(학습 데이터 고정)고,
QR 인식은 화면 표시용 고화질이 목적이 아니라 라벨 판독이 목적이라 640x480으로
충분하다 — 관제 화면 품질보다 QR 대조가 우선이라는 판단(대화 근거).

사전 준비 (한 번만, sudo 필요):
    sudo rmmod v4l2loopback
    sudo modprobe v4l2loopback video_nr=10,11 \\
        card_label="OMX_wrist_policy","OMX_wrist_stream" exclusive_caps=1,1

실행 예:
    python3 camera_relay.py
    # 다른 터미널에서 (정책 추론):
    source ~/venv/il/bin/activate && python3 deliver.py --zone frozen --port /dev/ttyACM0 \\
        --front-cam /dev/video7 --wrist-cam /dev/video10 --order "dumpling:1"
    # 또 다른 터미널에서 (RTSP 송신):
    python3.12 stream_wrist_camera.py --mediamtx-url rtsp://127.0.0.1:8554 \\
        --wrist-cam /dev/video11 --input-format yuyv422
"""

from __future__ import annotations

import argparse
import signal
import subprocess
import sys

import camera_config

DEFAULT_TARGETS = ["/dev/video10", "/dev/video11"]


def build_relay_command(
    *, source: str, targets: list[str], width: int, height: int, fps: int
) -> list[str]:
    command = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel", "warning",
        "-f", "v4l2",
        "-input_format", "mjpeg",
        "-video_size", f"{width}x{height}",
        "-framerate", str(fps),
        "-i", source,
    ]
    for target in targets:
        command += ["-pix_fmt", "yuyv422", "-f", "v4l2", target]
    return command


def run(args: argparse.Namespace) -> int:
    if args.source:
        source = args.source
    else:
        saved = camera_config.load()
        if saved is None:
            raise SystemExit(
                "wrist 카메라 포트를 모른다: --source를 직접 주거나, "
                "먼저 `python3 set_cameras.py --front ... --wrist ...`로 저장해둘 것."
            )
        source = saved.wrist
        print(f"[relay] using saved wrist port (run set_cameras.py to change): {source}")

    command = build_relay_command(
        source=source, targets=args.targets, width=args.width, height=args.height, fps=args.fps
    )
    print(f"[relay] {source} -> {args.targets} ({args.width}x{args.height}@{args.fps})")
    print(f"[relay] command: {' '.join(command)}")

    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    print(f"[relay] ffmpeg pid={process.pid} — Ctrl+C로 중단")

    def _on_sigterm(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _on_sigterm)

    try:
        assert process.stdout is not None
        for line in process.stdout:
            print(f"[ffmpeg] {line.rstrip()}")
    except KeyboardInterrupt:
        print("\n[relay] interrupted, stopping ffmpeg…")
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
    return process.returncode or 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", default=None, help="실제 wrist 카메라. 생략하면 set_cameras.py 저장값 사용")
    parser.add_argument(
        "--targets", nargs="+", default=DEFAULT_TARGETS,
        help=f"v4l2loopback 가상장치들 (공백으로 구분, 여러 개 가능). 기본 {DEFAULT_TARGETS}",
    )
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--fps", type=int, default=30)
    return parser


if __name__ == "__main__":
    sys.exit(run(_parser().parse_args()))
