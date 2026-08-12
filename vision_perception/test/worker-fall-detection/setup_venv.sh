#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
VENV_DIR="$REPO_ROOT/venv/yolo_segmentation"
PYTHON_BIN="${PYTHON312_BIN:-python3.12}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "[오류] Python 3.12가 필요합니다: $PYTHON_BIN" >&2
  exit 1
fi
"$PYTHON_BIN" -c 'import sys; assert sys.version_info[:2] == (3, 12), sys.version'
"$PYTHON_BIN" -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools wheel
"$VENV_DIR/bin/python" -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
"$VENV_DIR/bin/python" -m pip install -r "$SCRIPT_DIR/requirements/dev.txt"
"$VENV_DIR/bin/python" -c 'import sys, torch; assert sys.version_info[:2] == (3, 12); assert tuple(map(int, torch.version.cuda.split(".")[:2])) >= (12, 8); print("Python", sys.version.split()[0], "PyTorch", torch.__version__, "CUDA", torch.version.cuda)'
echo "완료: $VENV_DIR"
