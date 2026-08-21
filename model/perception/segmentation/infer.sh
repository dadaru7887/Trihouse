#!/usr/bin/env bash
# Pinky 카메라 실시간 inference 실행 스크립트 (X11 화면 표시 포함)
#
# 기본 입력은 PC1 MediaMTX 의 RTSP 다. 연구 경로와 운영 추론이 같은 픽셀을 보게
# 하려는 것이 이유이며, 자세한 근거는 PINKY_SEGMENTATION_PIPELINE.md §1 에 있다.
# 읽기는 계정 인증이므로 URL 에 viewer 자격 증명이 필요하다(PC1 .env 의
# MTX_VIEWER_PASS).
#
# 사용 예:
#   ./infer.sh --model "runs/segment/20260805_181217_yoloe-26s-seg_aug/weights/best.pt" \
#              --source "rtsp://viewer:<MTX_VIEWER_PASS>@<PC1_LAN_IP>:8554/pinky/CAM-PK-01"
#   ./infer.sh --model ... --source ... --no-show   # 화면 없이 콘솔 로그만
#
# 랩 세션에서 PC1 스택 전체가 필요 없으면 MediaMTX 만 단독으로 띄운다:
#   docker compose -f compose.edge_4060.yaml up mediamtx
#
# MJPEG 직송(pinky_camera_server.py, :8080/stream.mjpg)은 오프라인 랩 폴백일
# 뿐이다. 운영과 픽셀이 달라서 그 프레임은 학습 세트에 넣지 않는다.
#
# 호스트에서 바로 실행하면 자동으로 trihouse_train 컨테이너 안으로 넘어가서 실행됨
# (train.sh와 동일한 패턴). 화면을 보려면 먼저 호스트에서 한 번만:
#   xhost +local:root
# 를 실행해둬야 함 (재부팅/재로그인하면 다시 해줘야 할 수 있음).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 호스트(컨테이너 밖)에서 실행된 경우: trihouse_train 컨테이너 안의 같은 스크립트로 넘김
if [ ! -f /.dockerenv ]; then
  CONTAINER="trihouse_train"
  CONTAINER_DIR="/workspace/Trihouse_segmentation/Trihouse"
  # 호스트 터미널의 DISPLAY를 그대로 넘김. 못 찾으면 :1로 기본값
  # (재로그인 등으로 세션 번호가 바뀌면 이 기본값도 같이 바꿔줘야 함).
  DISPLAY_NUM="${DISPLAY:-:1}"

  if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
    echo "[에러] '$CONTAINER' 컨테이너가 안 떠 있어요." >&2
    exit 1
  fi

  exec docker exec -e DISPLAY="$DISPLAY_NUM" -it -w "$CONTAINER_DIR" "$CONTAINER" ./infer.sh "$@"
fi

# ── 여기부터는 컨테이너 안에서 실행되는 경우 ──

source /opt/conda/etc/profile.d/conda.sh
set +u
conda activate unified_env_ver2
set -u

python3 "${SCRIPT_DIR}/inference_stream.py" "$@"
