#!/usr/bin/env bash
# Pinky 카메라 실시간 inference 실행 스크립트 (X11 화면 표시 포함)
#
# 사용 예:
#   ./infer.sh --model "runs/segment/20260805_181217_yoloe-26s-seg_aug/weights/best.pt" \
#              --source http://192.168.129.37:8080/stream.mjpg
#   ./infer.sh --model ... --source ... --no-show   # 화면 없이 콘솔 로그만
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
