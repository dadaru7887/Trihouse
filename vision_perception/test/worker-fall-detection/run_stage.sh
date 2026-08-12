#!/usr/bin/env bash
# 단계별 수동 실행용 컨테이너/conda wrapper.
set -euo pipefail

if [ "$#" -lt 1 ]; then
  echo "사용법: $0 {preflight|train|evaluate} [옵션...]" >&2
  exit 2
fi

STAGE="$1"
shift
case "$STAGE" in
  preflight) SCRIPT="preflight.py" ;;
  train) SCRIPT="train_stage.py" ;;
  evaluate) SCRIPT="evaluate_stage.py" ;;
  *) echo "알 수 없는 단계: $STAGE (preflight|train|evaluate)" >&2; exit 2 ;;
esac

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ ! -f /.dockerenv ]; then
  CONTAINER="${TRIHOUSE_TRAIN_CONTAINER:-trihouse_train}"
  CONTAINER_ROOT="${TRIHOUSE_CONTAINER_ROOT:-/workspace/Trihouse_segmentation/Trihouse}"
  if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
    echo "[에러] '$CONTAINER' 컨테이너가 실행 중이 아닙니다." >&2
    exit 1
  fi
  exec docker exec -i -w "$CONTAINER_ROOT" "$CONTAINER" \
    ./vision_perception/test/worker-fall-detection/run_stage.sh "$STAGE" "$@"
fi

source /opt/conda/etc/profile.d/conda.sh
set +u
conda activate unified_env_ver2
set -u
exec python3 "$SCRIPT_DIR/$SCRIPT" "$@"
