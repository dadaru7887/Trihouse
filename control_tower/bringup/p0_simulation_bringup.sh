#!/usr/bin/env bash
# P0 시뮬레이션의 호스트 ROS 2 층을 한 번에 띄운다.
#
#   control_tower/bringup/p0_simulation_bringup.sh [--gui] [--rviz] [--no-worker]
#                                                  [--no-job-runner] [--no-executor]
#
# 함께 올라가는 것:
#   - Open-RMF traffic schedule (RMF core)
#   - Gazebo + Pinky 두 대 (PK_01/pinky_01, PK_02/pinky_02) 와 각자의 Nav2
#   - 두 대의 fleet adapter
#   - OMX 프로토콜 시뮬레이터 두 개 (OMX_01, OMX_02)
#   - Job 러너 (control_tower.task_manager.job_runner_node)
#   - 실행기 워커 (control_tower.task_manager.executor_worker_node)
#   - RMF dispatch worker (control_tower.rmf_adapter.rmf_gateway_worker_node)
#
# Job 러너와 dispatch worker 는 짝이다. 러너가 `queued` Job 에 자원을 배정하고
# 현재 Step 을 outbox 로 내보내면, worker 가 그 행을 claim 해 RMF 로 넘긴다.
# 러너가 없으면 worker 는 claim 할 것이 없어 주문이 로봇을 움직이지 못한다.
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
START_JOB_RUNNER=true
START_EXECUTOR=true
while [[ $# -gt 0 ]]; do
  case "$1" in
    --gui) GUI=true ;;
    --rviz) RVIZ=true ;;
    --no-worker) START_WORKER=false ;;
    --no-job-runner) START_JOB_RUNNER=false ;;
    --no-executor) START_EXECUTOR=false ;;
    -h|--help) sed -n '2,26p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

: "${ROS_DISTRO_SETUP:=/opt/ros/jazzy/setup.bash}"
: "${FMS_BASE_URL:=http://127.0.0.1:8080}"
: "${TRIHOUSE_PROJECT:=trihouse_test_01}"
# fleet 이름은 `trihouse_rmf_bridge/config/pinky_fleet.yaml` 의 `rmf_fleet.name`
# 과 반드시 같아야 한다. 다르면 dispatch worker 가 RMF 에 넘긴 작업을 어떤
# adapter 도 집어 가지 않는다. 이 이름은 worker/orchestrator 의 기본값이기도
# 하다(`control_tower/rmf_adapter/rmf_gateway_worker_node.py`).
: "${TRIHOUSE_FLEET_NAME:=project1_pinky}"
: "${TRIHOUSE_MAP_REVISION:=}"
# Nav2 는 지도 없이 slam_toolbox 로 돈다. P0 의 승인된 SLAM 지도는
# `control_system_test/` 아래라 gitignore 대상이고, 두 로봇이 같은 지도를
# 공유하려면 초기 pose 정합이 따로 필요하다. 지도를 쓰려면
# `TRIHOUSE_NAV2_SLAM=false` 로 두고 launch 에 `nav2_map:=` 을 넘긴다.
: "${TRIHOUSE_ACT_CONFIG:=$ROOT/config/act.simulation.yaml}"
: "${TRIHOUSE_NAV2_SLAM:=true}"
: "${TRIHOUSE_START_NAV2:=true}"
# 승인된 좌표 원본. `control_ui/` 쪽이 git 에 들어 있는 정본이고 지도 발행과
# 자동 테스트가 모두 이 파일을 쓴다. `control_system_test/` 사본은 gitignore
# 대상이라 새 클론에는 없으므로 되돌아갈 자리로만 남긴다.
: "${PHYSICAL_FEATURES_FILE:=$ROOT/control_ui/rmf_control_ui/data/import/trihouse_test_01_physical_features.jsonl}"
if [[ ! -f "$PHYSICAL_FEATURES_FILE" ]]; then
  PHYSICAL_FEATURES_FILE="$ROOT/control_system_test/rmf_control_ui/data/import/trihouse_test_01_physical_features.jsonl"
fi

if [[ ! -f "$ROS_DISTRO_SETUP" ]]; then
  echo "ROS 2 setup script not found: $ROS_DISTRO_SETUP" >&2
  exit 1
fi
# ROS 의 setup 스크립트들은 AMENT_TRACE_SETUP_FILES 같은 변수를 설정 여부 확인
# 없이 읽는다. `set -u` 를 켠 채로 source 하면 거기서 바로 죽으므로, 이 구간
# 에서만 끄고 다시 켠다.
set +u
# shellcheck disable=SC1090
source "$ROS_DISTRO_SETUP"

# 이 저장소의 워크스페이스 오버레이가 빌드되어 있으면 함께 얹는다.
if [[ -f "$ROOT/install/setup.bash" ]]; then
  # shellcheck disable=SC1091
  source "$ROOT/install/setup.bash"
fi
set -u

# control_tower / fms_gateway 는 ROS 패키지가 아니라 저장소 경로로 import 한다.
#
# 주의: ROS 패키지는 `<pkg>/<pkg>/` 구조라서 저장소 루트만 넣으면 바깥
# 디렉터리가 namespace package 로 먼저 잡혀
# `python3 -m trihouse_omx_adapter.simulator_node` 가 실패한다. 안쪽 패키지
# 디렉터리를 루트보다 앞에 둔다.
export PYTHONPATH="$ROOT/trihouse_omx_adapter:$ROOT${PYTHONPATH:+:$PYTHONPATH}"

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

# 발행된 지도 revision 을 launch 가 받을 수 있는 파일들로 펼친다.
# Gateway 는 지도를 내용으로만 주는데 launch 는 경로를 받으므로 이 단계가 없으면
# `nav_graph`/`world` 인자를 채울 수 없다.
: "${TRIHOUSE_RUNTIME_DIR:=$ROOT/.trihouse/p0}"
: "${PINKY_NAV2_PARAMS:=$ROOT/pinky_pro/pinky_navigation/params/nav2_params.yaml}"

# pinky_pro 는 별도 colcon 워크스페이스다. Pinky 의 URDF·world·Gazebo plugin 을
# 쓰려면 이 오버레이도 얹어야 한다. 이 저장소에서 고치는 파일은 없다.
if [[ -f "$ROOT/pinky_pro/install/setup.bash" ]]; then
  set +u
  # shellcheck disable=SC1091
  source "$ROOT/pinky_pro/install/setup.bash"
  set -u
else
  echo "pinky_pro 워크스페이스가 빌드되어 있지 않습니다: $ROOT/pinky_pro/install" >&2
  echo "Pinky URDF 와 Gazebo world 가 여기서 옵니다." >&2
  exit 1
fi

PINKY_WORLD="$(ros2 pkg prefix pinky_gz_sim)/share/pinky_gz_sim/worlds/empty.world"
: "${TRIHOUSE_FLEET_CONFIG:=$(ros2 pkg prefix trihouse_rmf_bridge)/share/trihouse_rmf_bridge/config/pinky_fleet.yaml}"

echo "[bringup] 발행된 지도 revision 을 펼칩니다: $TRIHOUSE_MAP_REVISION"
python3 "$ROOT/control_tower/bringup/p0_runtime_assets.py" \
  --fms-base-url "$FMS_BASE_URL" \
  --map-name "$TRIHOUSE_PROJECT" \
  --map-revision "$TRIHOUSE_MAP_REVISION" \
  --features "$PHYSICAL_FEATURES_FILE" \
  --nav2-source "$PINKY_NAV2_PARAMS" \
  --world-source "$PINKY_WORLD" \
  --output-dir "$TRIHOUSE_RUNTIME_DIR" \
  --robot PK_01:pinky_01 \
  --robot PK_02:pinky_02 >/dev/null

PIDS=()
# 워커는 SIGTERM 을 걸쇠로 받아 진행 중인 주기(claim → 실행 → 보고)를 마치고
# 나간다. 그 시간을 주지 않고 즉시 죽이면 claim 한 작업이 주인 없이 남고,
# 다음 기동에서 lease 가 만료될 때까지 그 Job 이 멈춘다.
: "${TRIHOUSE_SHUTDOWN_GRACE_S:=10}"

cleanup() {
  echo
  echo "P0 ROS 층을 정리합니다..."
  for pid in "${PIDS[@]}"; do
    kill "$pid" 2>/dev/null || true
  done

  # 우아한 종료를 기다리되 무한정은 아니다. 멈춘 프로세스 하나가 스크립트를
  # 붙잡으면 스택을 내릴 방법이 없어진다.
  local deadline=$((SECONDS + TRIHOUSE_SHUTDOWN_GRACE_S))
  while (( SECONDS < deadline )); do
    local alive=false
    for pid in "${PIDS[@]}"; do
      if kill -0 "$pid" 2>/dev/null; then
        alive=true
        break
      fi
    done
    if [[ "$alive" == false ]]; then
      break
    fi
    sleep 0.2
  done

  for pid in "${PIDS[@]}"; do
    if kill -0 "$pid" 2>/dev/null; then
      echo "[bringup] $pid 가 ${TRIHOUSE_SHUTDOWN_GRACE_S}s 안에 끝나지 않아 강제 종료합니다"
      kill -9 "$pid" 2>/dev/null || true
    fi
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
#    `rmf_traffic_ros2` 에는 common.launch.xml 이 없다. control_system 이 검증한
#    노드 구성을 rmf_core.launch.py 로 옮겨 두었다.
start "rmf core" \
  ros2 launch trihouse_rmf_bridge rmf_core.launch.py \
    use_sim_time:=true \
    start_visualization:="$([[ "$RVIZ" == true ]] && echo true || echo false)"

sleep 3

# 2) Gazebo + 두 Pinky + 두 Nav2 + 두 fleet adapter.
#    spawn pose 는 승인된 JSONL 의 충전 스테이션 기록에서만 읽는다.
start "two pinky order demo" \
  ros2 launch trihouse_rmf_bridge two_pinky_order_demo.launch.py \
    physical_features_file:="$PHYSICAL_FEATURES_FILE" \
    map_revision:="$TRIHOUSE_MAP_REVISION" \
    nav_graph:="$TRIHOUSE_RUNTIME_DIR/nav_graph.yaml" \
    world:="$TRIHOUSE_RUNTIME_DIR/world.sdf" \
    nav2_params_file:="$PINKY_NAV2_PARAMS" \
    nav2_params_dir:="$TRIHOUSE_RUNTIME_DIR/nav2" \
    nav2_slam:="$TRIHOUSE_NAV2_SLAM" \
    start_nav2:="$TRIHOUSE_START_NAV2" \
    fleet_config:="$TRIHOUSE_FLEET_CONFIG" \
    fleet_name:="$TRIHOUSE_FLEET_NAME" \
    fms_base_url:="$FMS_BASE_URL" \
    headless:="$([[ "$GUI" == true ]] && echo false || echo true)" \
    start_rmf_core:=false \
    start_rmf_worker:=false \
    start_job_runner:=false \
    start_executor_worker:=false

# 3) OMX 두 대. 실제 OMX motion 은 나가지 않는다.
#
# `simulator_node` 는 ROS 노드가 아니라 stdin/stdout NDJSON 필터라서, 여기서
# 배경 프로세스로 띄우면 stdin 이 바로 EOF 가 되어 즉시 끝난다. ROS 층에서
# OMX 존재를 나타내는 것은 `gazebo_adapter_node` 다. 노드 이름이 코드에
# 박혀 있으므로 두 대가 부딪히지 않게 실행 시 이름을 갈라 준다.
declare -A OMX_ROBOTS=([OMX_01]=PK_01 [OMX_02]=PK_02)
for omx in OMX_01 OMX_02; do
  node_name="$(echo "$omx" | tr '[:upper:]' '[:lower:]')"
  start "omx adapter $omx" \
    ros2 run trihouse_omx_adapter gazebo_omx_adapter --ros-args \
      -r __node:="$node_name" \
      -p omx_id:="$omx" \
      -p robot_id:="${OMX_ROBOTS[$omx]}" \
      -p use_sim_time:=true
done

# 4) Job 러너. `queued` 주문에 로봇·OMX·포장 Dock 을 배정하고 현재 Step 을
#    outbox 로 내보낸다. 아래 worker 보다 먼저 띄워 첫 주문이 곧바로 흐르게 한다.
if [[ "$START_JOB_RUNNER" == true ]]; then
  start "job runner" \
    python3 -m control_tower.task_manager.job_runner_node \
      --fms-base-url "$FMS_BASE_URL"
fi

# 5) 실행기 워커. OMX(`omx`)·FMS(`pinky`) 채널 dispatch 를 claim 해 실행하고
#    결과를 Step 에 반영한다. 이게 없으면 주문이 첫 `pick` 에서 멈추고 뒤따르는
#    `navigate` 가 RMF 로 나가지 못한다.
if [[ "$START_EXECUTOR" == true ]]; then
  start "executor worker" \
    python3 -m control_tower.task_manager.executor_worker_node \
      --fms-base-url "$FMS_BASE_URL" \
      --environment simulation \
      --act-config "$TRIHOUSE_ACT_CONFIG"
fi

# 6) RMF dispatch worker. Control Tower 가 고른 로봇으로만 작업을 넘긴다.
if [[ "$START_WORKER" == true ]]; then
  start "rmf dispatch worker" \
    python3 -m control_tower.rmf_adapter.rmf_gateway_worker_node \
      --fms-base-url "$FMS_BASE_URL" \
      --fleet-name "$TRIHOUSE_FLEET_NAME" \
      --worker-id trihouse-rmf-worker
fi

echo
echo "P0 ROS 층이 올라왔습니다. 확인:"
echo "  ros2 node list"
echo "  ./scripts/control_stack doctor --mode simulation"
echo "중지하려면 Ctrl+C 를 누르세요."
wait
