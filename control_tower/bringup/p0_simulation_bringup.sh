#!/usr/bin/env bash
# P0 시뮬레이션의 호스트 ROS 2 층을 한 번에 띄운다.
#
#   control_tower/bringup/p0_simulation_bringup.sh [--gui] [--rviz] [--no-worker]
#
# 함께 올라가는 것:
#   - Open-RMF traffic schedule (RMF core)
#   - Gazebo + Pinky 두 대 (PK_01/pinky_01, PK_02/pinky_02) 와 각자의 Nav2
#   - 두 대의 fleet adapter
#   - OMX 프로토콜 시뮬레이터 두 개 (OMX_01, OMX_02)
#   - RMF dispatch worker (control_tower.rmf_adapter.rmf_gateway_worker_node)
#
# 이들은 rclpy/DDS/GPU 가 필요해 Docker 로 옮기지 않았다. MySQL, FMS Gateway,
# MediaMTX, control_ui 는 `scripts/control_stack up` 이 Docker 로 먼저 띄운다.
#
# Ctrl+C 한 번으로 여기서 띄운 프로세스를 모두 정리한다.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

GUI=false
RVIZ=false
START_WORKER=true
while [[ $# -gt 0 ]]; do
  case "$1" in
    --gui) GUI=true ;;
    --rviz) RVIZ=true ;;
    --no-worker) START_WORKER=false ;;
    -h|--help) sed -n '2,20p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

: "${ROS_DISTRO_SETUP:=/opt/ros/jazzy/setup.bash}"
: "${FMS_BASE_URL:=http://127.0.0.1:8080}"
: "${TRIHOUSE_PROJECT:=trihouse_test_01}"
: "${TRIHOUSE_FLEET_NAME:=trihouse_pinky}"
: "${TRIHOUSE_MAP_REVISION:=}"
: "${PHYSICAL_FEATURES_FILE:=$ROOT/control_system_test/rmf_control_ui/data/import/trihouse_test_01_physical_features.jsonl}"

if [[ ! -f "$ROS_DISTRO_SETUP" ]]; then
  echo "ROS 2 setup script not found: $ROS_DISTRO_SETUP" >&2
  exit 1
fi
# shellcheck disable=SC1090
source "$ROS_DISTRO_SETUP"

# 이 저장소의 워크스페이스 오버레이가 빌드되어 있으면 함께 얹는다.
if [[ -f "$ROOT/install/setup.bash" ]]; then
  # shellcheck disable=SC1091
  source "$ROOT/install/setup.bash"
fi

# control_tower 와 fms_gateway 는 ROS 패키지가 아니라 저장소 경로로 import 한다.
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"

if [[ ! -f "$PHYSICAL_FEATURES_FILE" ]]; then
  echo "승인된 physical-feature JSONL 이 없습니다: $PHYSICAL_FEATURES_FILE" >&2
  echo "P0 좌표는 이 파일에서만 옵니다. 경로를 PHYSICAL_FEATURES_FILE 로 지정하세요." >&2
  exit 1
fi

# Gateway 가 떠 있어야 fleet adapter 와 worker 가 작업 문맥을 받을 수 있다.
if ! curl -fsS --max-time 3 "$FMS_BASE_URL/ready" >/dev/null 2>&1; then
  echo "FMS Gateway 가 $FMS_BASE_URL 에서 준비되지 않았습니다." >&2
  echo "먼저 ./scripts/control_stack up --mode simulation 을 실행하세요." >&2
  exit 1
fi

if [[ -z "$TRIHOUSE_MAP_REVISION" ]]; then
  echo "TRIHOUSE_MAP_REVISION 이 비어 있습니다." >&2
  echo "발행된 지도 revision 을 명시해야 작업 문맥이 일치합니다. 예:" >&2
  echo "  TRIHOUSE_MAP_REVISION=trihouse_test_01:<hash> $0" >&2
  exit 1
fi

PIDS=()
cleanup() {
  echo
  echo "P0 ROS 층을 정리합니다..."
  for pid in "${PIDS[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

start() {
  local label="$1"
  shift
  echo "[bringup] $label"
  "$@" &
  PIDS+=($!)
}

# 1) RMF core. 두 fleet adapter 가 같은 schedule 에 붙는다.
start "rmf traffic schedule" \
  ros2 launch rmf_traffic_ros2 common.launch.xml use_sim_time:=true

sleep 3

# 2) Gazebo + 두 Pinky + 두 Nav2 + 두 fleet adapter.
#    spawn pose 는 승인된 JSONL 의 충전 스테이션 기록에서만 읽는다.
start "two pinky order demo" \
  ros2 launch trihouse_rmf_bridge two_pinky_order_demo.launch.py \
    physical_features_file:="$PHYSICAL_FEATURES_FILE" \
    map_revision:="$TRIHOUSE_MAP_REVISION" \
    fleet_name:="$TRIHOUSE_FLEET_NAME" \
    fms_base_url:="$FMS_BASE_URL" \
    headless:="$([[ "$GUI" == true ]] && echo false || echo true)" \
    start_rmf_core:=false \
    start_rmf_worker:=false

# 3) OMX 프로토콜 시뮬레이터 두 개. 실제 OMX motion 은 나가지 않는다.
for omx in OMX_01 OMX_02; do
  start "omx simulator $omx" \
    python3 -m trihouse_omx_adapter.simulator_node --omx-id "$omx"
done

# 4) RMF dispatch worker. Control Tower 가 고른 로봇으로만 작업을 넘긴다.
if [[ "$START_WORKER" == true ]]; then
  start "rmf dispatch worker" \
    python3 -m control_tower.rmf_adapter.rmf_gateway_worker_node \
      --fms-base-url "$FMS_BASE_URL" \
      --fleet-name "$TRIHOUSE_FLEET_NAME" \
      --worker-id trihouse-rmf-worker
fi

if [[ "$RVIZ" == true ]]; then
  start "rviz" ros2 launch rmf_visualization visualization.launch.xml \
    use_sim_time:=true
fi

echo
echo "P0 ROS 층이 올라왔습니다. 확인:"
echo "  ros2 node list"
echo "  ./scripts/control_stack doctor --mode simulation"
echo "중지하려면 Ctrl+C 를 누르세요."
wait
