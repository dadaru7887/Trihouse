#!/usr/bin/env bash
# YOLOE 세그멘테이션 GPU 학습 실행 스크립트 (RTX5080 / 도커 환경 기준)
#
# 사용 예:
#   ./train.sh --model 26s --augmentation yes --data /path/to/data.yaml
#   ./train.sh --model 11m --augmentation no  --data /path/to/data.yaml --epochs 100
#   ./train.sh --model 26s --data /path/to/data.yaml --workers 2 --project /workspace/runs
#
# 결과 폴더/가중치는 기본적으로 "학습시작시각(KST)_모델명"으로 저장됩니다
# (--name으로 직접 지정 가능).
#
# 받은 인자를 그대로 train.py로 넘깁니다 (별도 파싱 없음).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 호스트(컨테이너 밖)에서 실행된 경우: trihouse_train 컨테이너 안의 같은 스크립트로
# 그대로 넘김 (/.dockerenv는 도커 컨테이너 안에서만 존재하는 표준 마커 파일).
# -> 컨테이너에 미리 안 들어가고 호스트에서 바로 ./train.sh 쳐도 되게 함.
if [ ! -f /.dockerenv ]; then
  CONTAINER="trihouse_train"
  CONTAINER_DIR="/workspace/Trihouse_segmentation/Trihouse"

  if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
    echo "[에러] '$CONTAINER' 컨테이너가 안 떠 있어요. 먼저 띄워주세요 (ros.sh/trihouse.sh/run.sh 참고)." >&2
    exit 1
  fi

  exec docker exec -it -w "$CONTAINER_DIR" "$CONTAINER" ./train.sh "$@"
fi

# ── 여기부터는 컨테이너 안에서 실행되는 경우 ──

# 컨테이너 기본 python3는 conda base 환경이라 ultralytics/albumentations가 없음 --
# 실제 패키지들이 깔린 unified_env_ver2를 먼저 activate해야 함.
# conda의 activate.d 스크립트(MKL 등)가 정의 안 된 변수를 참조해서 set -u랑 충돌하므로
# activate 하는 동안만 -u를 꺼둠.
source /opt/conda/etc/profile.d/conda.sh
set +u
conda activate unified_env_ver2
set -u

python3 "${SCRIPT_DIR}/train.py" "$@"
