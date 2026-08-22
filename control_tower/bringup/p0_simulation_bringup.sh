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
# MediaMTX와 control_system 기반 RMF Dashboard는 `scripts/control_stack up`이 먼저 띄운다.
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
# 두 로봇과 관제가 한 domain 을 공유하고, 구분은 ROS namespace(pinky_01,
# pinky_02)가 맡는다. domain 을 갈라 놓으면 로봇끼리 서로를 못 보고 관제 PC 가
# domain 마다 따로 붙어야 한다.
#
# 여기서 명시적으로 못박는 이유는 이 값이 Docker 층(compose.simulation.yaml 의
# rmf_api)과 반드시 같아야 하기 때문이다. 예전에는 양쪽 다 아무것도 정하지
# 않아 우연히 0 으로 맞았는데, 그러면 한쪽만 바뀌었을 때 아무 오류 없이 서로를
# 못 보게 된다. 두 곳의 기본값을 같은 값으로 적어 두면 그 사고가 나지 않는다.
#
# 이미 다른 domain 으로 떠 있는 Docker 층에 붙이려면 이 값을 넘겨라:
#   ROS_DOMAIN_ID=12 control_tower/bringup/p0_simulation_bringup.sh
: "${ROS_DOMAIN_ID:=12}"
export ROS_DOMAIN_ID
# transport 도 domain 과 똑같은 이유로 못박는다. domain 이 같아도 전송 방식이
# 어긋나면 서로를 못 본다.
#
# Docker 층은 `compose.simulation.yaml` 에서 UDPv4 로 뜨는데 호스트는 아무것도
# 정하지 않아 FastDDS 기본값으로 떴다. 기본값은 공유메모리를 함께 광고하고,
# 그러면 요청은 도착하는데 응답이 돌아오지 못하는 상태가 된다. 실제로
# `map_server` 가 Configuring 을 끝냈는데도 lifecycle_manager 는 응답을 받지
# 못해 거기서 멈췄고(`failed to send response to .../change_state`), AMCL 이
# 아예 기동하지 못했다. 오류가 아니라 침묵으로 나타나므로 찾기 어렵다.
#
# `.env` 를 읽지 않는 것은 의도다. 거기엔 MySQL·MediaMTX 비밀값이 있고 source
# 하면 그것들이 모든 ROS 노드 환경으로 새어 나간다. 두 층의 기본값을 같은
# 값으로 적어 두는 쪽이 안전하고, 그 일치는 테스트가 지킨다.
# discovery 범위도 같은 이유로 못박는다. 서버 PC 는 인터페이스를 둘 갖는다 —
# 인터넷용 Wi-Fi 와 ROS 전용 공유기로 가는 Ethernet. 범위를 좁히지 않으면 discovery
# 를 Wi-Fi 쪽으로도 뿌리고, 한쪽 층만 좁히면 그 층은 상대를 보지 못한다.
: "${RMW_IMPLEMENTATION:=rmw_fastrtps_cpp}"
: "${FASTDDS_BUILTIN_TRANSPORTS:=UDPv4}"
: "${ROS_AUTOMATIC_DISCOVERY_RANGE:=SUBNET}"
export RMW_IMPLEMENTATION FASTDDS_BUILTIN_TRANSPORTS ROS_AUTOMATIC_DISCOVERY_RANGE
: "${FMS_BASE_URL:=http://127.0.0.1:8080}"
: "${TRIHOUSE_PROJECT:=new_map_2}"
# fleet 이름은 `trihouse_rmf_bridge/config/pinky_fleet.yaml` 의 `rmf_fleet.name`
# 과 반드시 같아야 한다. 다르면 dispatch worker 가 RMF 에 넘긴 작업을 어떤
# adapter 도 집어 가지 않는다. 이 이름은 worker/orchestrator 의 기본값이기도
# 하다(`control_tower/rmf_adapter/rmf_gateway_worker_node.py`).
: "${TRIHOUSE_FLEET_NAME:=project1_pinky}"
: "${TRIHOUSE_MAP_REVISION:=}"
# 띄울 로봇을 고른다. 비어 있으면 전부. 예: `TRIHOUSE_ROBOTS=PK_01`.
#
# 로봇 두 대의 전체 스택(Gazebo + Nav2 두 벌 + Open-RMF + 로봇당 온보드 노드 여섯
# 개)은 개발 PC 한 대의 용량을 넘는다. 부하가 높으면 Nav2 의 lifecycle manager 가
# `map_server/get_state` 를 기다리다 포기하고 새로 붙는 노드도 토픽을 발견하지 못한다.
# 주문 경로를 증명할 때는 한 대로 줄여 부하라는 변수를 먼저 없애라.
: "${TRIHOUSE_ROBOTS:=}"
# 두 로봇은 하나의 SLAM 지도를 공유하고 각자 AMCL 로 위치추정한다.
#
# 로봇마다 slam_toolbox 를 돌리면 같은 창고의 지도를 각자 따로 만들게 되고, 두
# `map` 프레임이 일치하지 않는다. 그러면 병목 예약도 lane 충돌도 근거를 잃고,
# 승인된 JSONL 의 좌표가 어느 지도 것인지도 말할 수 없게 된다. 지도가 저장소에
# 들어온 지금은 공유 지도가 정본이다. 초기 pose 는 각 로봇의 고정 충전기
# 좌표에서 오며 `p0_runtime_assets.py` 가 파생 파라미터에 심는다.
#
# 지도 없이 돌려야 하면 `TRIHOUSE_NAV2_SLAM=true` 로 되돌릴 수 있다.
: "${TRIHOUSE_NAV2_MAP:=$ROOT/pinky_pro_alpha/pinky_navigation/map/new_map_2.yaml}"
: "${TRIHOUSE_NAV2_SLAM:=false}"
: "${TRIHOUSE_START_NAV2:=true}"
# EN: Measured features are repository runtime data and never fall back to a UI copy.
# KO: 실측 feature는 저장소 런타임 데이터이며 UI 사본으로 fallback하지 않는다.
: "${PHYSICAL_FEATURES_FILE:=$ROOT/data/map_authoring/import/trihouse_test_01_physical_features.new_map_2.jsonl}"

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

if [[ "$TRIHOUSE_NAV2_SLAM" != true && ! -f "$TRIHOUSE_NAV2_MAP" ]]; then
  echo "공유 SLAM 지도가 없습니다: $TRIHOUSE_NAV2_MAP" >&2
  echo "지도 없이 각자 SLAM 으로 돌리려면 TRIHOUSE_NAV2_SLAM=true 를 주세요." >&2
  exit 1
fi

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
  echo "  TRIHOUSE_MAP_REVISION=new_map_2:<hash> $0" >&2
  exit 1
fi

# 발행된 지도 revision 을 launch 가 받을 수 있는 파일들로 펼친다.
# Gateway 는 지도를 내용으로만 주는데 launch 는 경로를 받으므로 이 단계가 없으면
# `nav_graph`/`world` 인자를 채울 수 없다.
: "${TRIHOUSE_RUNTIME_DIR:=$ROOT/.trihouse/p0}"
# EN: The vendor checkout is reproducible upstream input; Trihouse's measured
# footprint and inflation values live in the tracked alpha overlay.
# KO: 벤더 checkout은 재현 가능한 원본이고, Trihouse 실측 footprint와 inflation
# 값의 정본은 추적되는 alpha overlay다.
: "${PINKY_NAV2_PARAMS:=$ROOT/pinky_pro_alpha/pinky_navigation/params/nav2_params.yaml}"

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

: "${PINKY_WORLD:=$ROOT/control_tower/bringup/p0_world.sdf}"
: "${TRIHOUSE_FLEET_CONFIG:=$(ros2 pkg prefix trihouse_rmf_bridge)/share/trihouse_rmf_bridge/config/pinky_fleet.yaml}"
: "${P0_NARROW_ZONES_SOURCE:=$ROOT/config/narrow_zones.$TRIHOUSE_PROJECT.yaml}"

echo "[bringup] 발행된 지도 revision 을 펼칩니다: $TRIHOUSE_MAP_REVISION"
python3 "$ROOT/control_tower/bringup/p0_runtime_assets.py" \
  --fms-base-url "$FMS_BASE_URL" \
  --map-name "$TRIHOUSE_PROJECT" \
  --map-revision "$TRIHOUSE_MAP_REVISION" \
  --features "$PHYSICAL_FEATURES_FILE" \
  --nav2-source "$PINKY_NAV2_PARAMS" \
  --world-source "$PINKY_WORLD" \
  --narrow-zones-source "$P0_NARROW_ZONES_SOURCE" \
  --output-dir "$TRIHOUSE_RUNTIME_DIR" \
  $([[ "$TRIHOUSE_NAV2_SLAM" == true ]] || echo --map-yaml "$TRIHOUSE_NAV2_MAP") \
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
    narrow_zones_file:="$TRIHOUSE_RUNTIME_DIR/narrow_zones.yaml" \
    runtime_state_dir:="$TRIHOUSE_RUNTIME_DIR" \
    robots:="$TRIHOUSE_ROBOTS" \
    nav2_slam:="$TRIHOUSE_NAV2_SLAM" \
    nav2_map:="$([[ "$TRIHOUSE_NAV2_SLAM" == true ]] && echo "" || echo "$TRIHOUSE_NAV2_MAP")" \
    start_nav2:="$TRIHOUSE_START_NAV2" \
    fleet_config:="$TRIHOUSE_FLEET_CONFIG" \
    fleet_name:="$TRIHOUSE_FLEET_NAME" \
    fms_base_url:="$FMS_BASE_URL" \
    headless:="$([[ "$GUI" == true ]] && echo false || echo true)" \
    start_rmf_core:=false \
    start_rmf_worker:=false \
    start_job_runner:=false \
    start_executor_worker:=false

# 3) OMX 두 대. tests/simulation 구현도 실물과 같은 Action endpoint를 제공하며
# 모터 명령은 내보내지 않는다.
for omx in OMX_01 OMX_02; do
  node_name="$(echo "$omx" | tr '[:upper:]' '[:lower:]')"
  start "omx action simulator $omx" \
    python3 -m tests.simulation.omx.action_server --ros-args \
      -r __node:="$node_name" -p device_id:="$omx"
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
      --environment simulation
fi

# 6) RMF dispatch worker. Control Tower 가 고른 로봇으로만 작업을 넘긴다.
if [[ "$START_WORKER" == true ]]; then
  start "rmf dispatch worker" \
    python3 -m control_tower.rmf_adapter.rmf_gateway_worker_node \
      --fms-base-url "$FMS_BASE_URL" \
      --fleet-name "$TRIHOUSE_FLEET_NAME" \
      --worker-id trihouse-rmf-worker \
      --use-sim-time
fi

echo
echo "P0 ROS 층이 올라왔습니다. 확인:"
echo "  ros2 node list"
echo "  ./scripts/control_stack doctor --mode simulation"
echo "중지하려면 Ctrl+C 를 누르세요."
wait
