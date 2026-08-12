#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
PYTHON="$REPO_ROOT/venv/yolo_segmentation/bin/python"
[ -x "$PYTHON" ] || { echo "[오류] 먼저 $SCRIPT_DIR/setup_venv.sh 를 실행하세요." >&2; exit 1; }
exec "$PYTHON" "$SCRIPT_DIR/train_multi_seed.py" "$@"
