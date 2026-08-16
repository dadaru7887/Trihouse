#!/usr/bin/env bash
# 실제 4060 / OMEN 5080 호스트에서만 의미가 있는 계측 산출물을 모은다.
#
#   ./scripts/measure_control_hosts.sh <output_dir>
#
# P1 진입 게이트 1번 항목이 요구하는 정확한 명령을 그대로 실행하고 출력을
# 파일로 남긴다. 값을 추정하거나 대체하지 않는다. 명령이 없는 호스트에서는
# 그 사실을 파일에 기록하고 비정상 종료해, 빈 산출물이 계측으로 오인되지
# 않게 한다.
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 <output_dir>" >&2
  exit 2
fi

output_dir="$1"
mkdir -p "$output_dir"

missing=0

capture() {
  local name="$1"
  shift
  local target="$output_dir/$name"
  if ! command -v "$1" >/dev/null 2>&1; then
    printf 'UNAVAILABLE: %s is not installed on %s\n' "$1" "$(hostname)" >"$target"
    missing=1
    return
  fi
  if ! "$@" >"$target" 2>&1; then
    printf 'UNAVAILABLE: %s failed on %s\n' "$*" "$(hostname)" >>"$target"
    missing=1
  fi
}

capture nvidia_smi.txt nvidia-smi
capture free.txt free -h
capture lsblk.txt lsblk -o NAME,MODEL,TRAN,SIZE,FSTYPE,MOUNTPOINTS
capture df.txt df -h

printf '%s\n' "$(hostname)" >"$output_dir/host.txt"

if [[ $missing -ne 0 ]]; then
  echo "one or more measurements are unavailable on this host" >&2
  echo "throughput and retention remain UNMEASURED" >&2
  exit 1
fi

cat <<EOF
Captured nvidia-smi, free -h, lsblk and df -h into $output_dir.
camera_soak.json is still required; run scripts/camera_soak_test.py for at
least 1800 seconds across six streams on this host.
EOF
