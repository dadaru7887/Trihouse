#!/usr/bin/env python3
"""OMX wrist 카메라를 MediaMTX로 RTSP 발행한다 (2단계: 영상 송신 확인).

trihouse_omx/ 바깥 코드를 재사용한다 — vision_system/stream_hub/ingress.py가
이미 "USB 카메라 -> MediaMTX" 계약(StreamIdentity, UsbIngressConfig,
build_usb_ingress_command)을 갖고 있어서, 이 스크립트는 그걸 import해서 쓰기만
한다. 그 파일은 수정하지 않는다 — 재발명하지 않는다는 원칙(map 문서 1절)을
그대로 지킨다.

**Python 버전 주의**: ingress.py는 `enum.StrEnum`(3.11+)을 쓴다. 우리
lerobot venv(~/venv/il)는 Python 3.10이라 이 파일을 못 읽는다. 이 스크립트는
lerobot/torch가 전혀 필요 없으므로, 시스템 기본 python3(3.12)로 따로 돌린다 —
venv/il을 activate하지 않은 채로 실행할 것.

카메라 역할 범위: config/cameras.yaml 기준 이 PC(OMX 부착 PC)가 발행할 책임은
wrist(role=omx_wrist, camera_id=CAM-OMX-01-WRIST) 카메라 하나뿐이다. front(선반)
카메라는 warehouse_fixed 역할로 4060이 발행하는 것이 팀 설계이고, 그 역할 자체가
아직 미정(front 카메라를 기존 고정 카메라로 쓸지 새 역할을 열지 결정 안 됨)이라
이 스크립트는 wrist만 다룬다.

실행 전: front/wrist 카메라 포트는 camera_config.py(set_cameras.py로 저장)를
그대로 재사용한다 — 1단계에서 이미 검증된 부분은 건드리지 않는다.

정책 추론(deliver.py/store.py)과 동시에 돌릴 때는 wrist 실물 카메라를 직접
열면 안 된다 (V4L2 장치 하나는 리더 하나만 지원, 실측 확인됨). camera_relay.py
를 먼저 띄워 실물 카메라를 v4l2loopback 가상장치 두 개(/dev/video10 정책용,
/dev/video11 송신용)로 분리한 뒤, 이 스크립트는 --wrist-cam /dev/video11
--input-format yuyv422로 가상장치를 읽는다. 자세한 내용은 camera_relay.py
docstring 참고.

기본 해상도/fps는 640x480@30으로 통일한다(camera_relay.py와 동일) — 정책
추론이 요구하는 학습 데이터 해상도이자, 실측 부하 테스트(GPU 인코더 0~1%,
CPU 코어 하나 기준 30% 이하)에서 30fps가 15fps 대비 전혀 부담 없었기 때문.

실행 예 (relay 경유, 로컬 스모크 테스트):
    python3 camera_relay.py &
    python3.12 stream_wrist_camera.py --mediamtx-url rtsp://127.0.0.1:8554 \\
        --wrist-cam /dev/video11 --input-format yuyv422

실행 예 (실제 PC1 대상):
    python3.12 stream_wrist_camera.py --mediamtx-url rtsp://<PC1_LAN_IP>:8554 \\
        --wrist-cam /dev/video11 --input-format yuyv422
"""

from __future__ import annotations

import argparse
import signal
import subprocess
import sys
import time
from pathlib import Path

# vision_system/stream_hub/ingress.py를 그대로 재사용하기 위해 저장소 루트를
# sys.path에 추가한다 — 파일은 안 건드리고 import만 한다.
_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

from vision_system.stream_hub.ingress import (  # noqa: E402
    StreamIdentity,
    UsbIngressConfig,
    UsbVideoFormat,
    VideoEncoder,
    build_usb_ingress_command,
)

import camera_config  # noqa: E402

# config/cameras.yaml의 CAM-OMX-01-WRIST와 role=omx_wrist(경로 접두사 "omx")를
# 그대로 따른다. OMX_02(두 번째 팔)를 다룰 일이 생기면 --camera-id로 바꾼다.
DEFAULT_CAMERA_ID = "CAM-OMX-01-WRIST"
DEFAULT_ROLE = "omx"


def run(args: argparse.Namespace) -> int:
    if args.wrist_cam:
        device = args.wrist_cam
    else:
        saved = camera_config.load()
        if saved is None:
            raise SystemExit(
                "wrist 카메라 포트를 모른다: --wrist-cam을 직접 주거나, "
                "먼저 `python3 set_cameras.py --front ... --wrist ...`로 저장해둘 것."
            )
        device = saved.wrist
        print(f"[camera] using saved wrist port (run set_cameras.py to change): {device}")

    identity = StreamIdentity(role=args.role, camera_id=args.camera_id)
    config = UsbIngressConfig(
        identity=identity,
        device=device,
        mediamtx_base_url=args.mediamtx_url,
        input_format=UsbVideoFormat(args.input_format),
        encoder=VideoEncoder(args.encoder),
        width=args.width,
        height=args.height,
        fps=args.fps,
        bitrate_kbps=args.bitrate_kbps,
    )
    command = build_usb_ingress_command(config)
    publish_url = identity.publish_url(args.mediamtx_url)

    print(f"[stream] path={identity.path}")
    print(f"[stream] publish_url={publish_url}")
    print(f"[stream] command: {' '.join(command)}")

    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    print(f"[stream] ffmpeg pid={process.pid} — Ctrl+C로 중단")

    # SIGTERM만 오면(예: 백그라운드 job kill, systemd stop) 기본 처리로는 이
    # 파이썬 프로세스만 죽고 ffmpeg 자식은 고아로 남아 계속 스트리밍한다 —
    # 실측으로 확인된 문제. SIGINT(KeyboardInterrupt)와 같은 경로로 보낸다.
    def _on_sigterm(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _on_sigterm)

    try:
        assert process.stdout is not None
        for line in process.stdout:
            print(f"[ffmpeg] {line.rstrip()}")
    except KeyboardInterrupt:
        print("\n[stream] interrupted, stopping ffmpeg…")
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
    return process.returncode or 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--mediamtx-url", required=True,
        help="RTSP origin, 경로 없이. 예: rtsp://127.0.0.1:8554 (로컬 테스트) 또는 rtsp://<PC1_LAN_IP>:8554",
    )
    parser.add_argument("--wrist-cam", default=None, help="생략하면 set_cameras.py로 저장해둔 값을 씀")
    parser.add_argument("--camera-id", default=DEFAULT_CAMERA_ID, help=f"기본 {DEFAULT_CAMERA_ID} (config/cameras.yaml 기준)")
    parser.add_argument("--role", default=DEFAULT_ROLE, help=f"기본 {DEFAULT_ROLE} (omx_wrist 역할의 경로 접두사)")
    parser.add_argument("--input-format", default="mjpeg", choices=["h264", "mjpeg", "yuyv422"])
    parser.add_argument("--encoder", default="h264_nvenc", choices=["copy", "h264_nvenc", "libx264"])
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--bitrate-kbps", type=int, default=3000)
    return parser


if __name__ == "__main__":
    sys.exit(run(_parser().parse_args()))
