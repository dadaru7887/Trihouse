#!/usr/bin/env bash
# 단계별 수동 실행용 Python 3.12 venv wrapper.
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
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
PYTHON="$REPO_ROOT/venv/yolo_segmentation/bin/python"
[ -x "$PYTHON" ] || { echo "[오류] 먼저 $SCRIPT_DIR/setup_venv.sh 를 실행하세요." >&2; exit 1; }
exec "$PYTHON" "$SCRIPT_DIR/$SCRIPT" "$@"
