#!/usr/bin/env bash
# LEGO worker YOLOE preflight -> train -> val gate -> test 전체 실행.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ ! -f /.dockerenv ]; then
  CONTAINER="${TRIHOUSE_TRAIN_CONTAINER:-trihouse_train}"
  CONTAINER_ROOT="${TRIHOUSE_CONTAINER_ROOT:-/workspace/Trihouse_segmentation/Trihouse}"
  if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
    echo "[에러] '$CONTAINER' 컨테이너가 실행 중이 아닙니다." >&2
    exit 1
  fi
  exec docker exec -i -w "$CONTAINER_ROOT" "$CONTAINER" \
    ./vision_perception/test/worker-fall-detection/run_pipeline.sh "$@"
fi

source /opt/conda/etc/profile.d/conda.sh
set +u
conda activate unified_env_ver2
set -u

exec python3 "$SCRIPT_DIR/run_pipeline.py" "$@"
