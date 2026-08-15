#!/usr/bin/env bash
# project1 프로젝트 실행.
# rmf_control_ui 가 맵 프로젝트에서 생성했다. 손으로 고치면 다음 저장 때
# 덮어써진다.
#
# 순서가 중요하다. Gazebo 가 먼저 떠야 /clock 이 나오고, 그래야 use_sim_time 을
# 쓰는 RMF 노드가 시간을 맞춘다. 반대로 하면 RMF 가 시간이 멈춘 줄 알고 멈춰
# 있는다.
set -euo pipefail

# ROS 도메인. 같은 도메인끼리만 서로를 본다.
#
# 이것이 어긋나면 **아무 오류도 안 나면서** 아무것도 안 통한다. 앱이 띄운
# 것과 터미널에서 띄운 것이 서로를 못 보던 일이 그래서 생겼다 — 앱은
# 비대화형 셸로 스크립트를 돌리므로 ~/.bashrc 의 export 를 못 읽는다.
# 그래서 맵 프로젝트가 정한 값을 여기 박아 둔다.
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-22}"

MAP_DIR="${MAP_DIR:-/home/gyi/robosapiens/rmf_maps/project1}"
APP_ROOT="${ROBOSAPIENS_ROOT:-$(cd "$MAP_DIR/../.." && pwd)}"
ROS_SETUP="${ROS_SETUP:-/opt/ros/jazzy/setup.bash}"
RMF_WS="${RMF_WS:-$APP_ROOT/rmf_ws}"
PINKY_WS="${PINKY_WS:-$APP_ROOT/robot_model/pinky_pro}"
OMX_WS="${OMX_WS:-$APP_ROOT/robot_model/open_manipulator}"

# 이 프로젝트의 로봇이 실제로 쓰는 패키지. 등록된 로봇에서 뽑았다.
REQUIRED_PACKAGES="rmf_demos rmf_demos_fleet_adapter rmf_building_map_tools ros_gz_sim pinky_description robot_state_publisher joint_state_publisher open_manipulator_description"

# 창을 띄울지 말지. Gazebo 와 RViz 를 따로 고른다.
#
# 예전에는 HEADLESS 하나가 둘을 함께 껐다 켰다 했다. 그런데 보고 싶은 것이
# 서로 다르다 — 로봇이 물리적으로 어디 있는지는 Gazebo 창에서, 계획한 경로와
# 코스트맵은 RViz 에서 본다. 하나만 보려고 둘을 다 띄우면 이 컴퓨터에서
# 프레임이 떨어져 시뮬레이션까지 느려졌다.
#
# 둘 다 안 띄워도 라이다·카메라는 돈다. Gazebo 서버는 언제나 헤드리스
# 렌더링으로 뜨기 때문이다. 창은 보는 용도일 뿐 데이터와는 무관하다.
#
# 앱이 실행할 때 환경 변수로 넘긴다. 터미널에서 직접 띄울 때는 이렇게 쓴다:
#   GAZEBO_GUI=true RVIZ=true ./run_project1.sh
is_true() {
  case "${1,,}" in
    true|1|yes|on) return 0 ;;
    *) return 1 ;;
  esac
}

# HEADLESS 만 준 예전 방식도 그대로 받는다. 따로 준 값이 있으면 그쪽이 이긴다.
if is_true "${HEADLESS:-true}"; then
  GUI_DEFAULT=false
else
  GUI_DEFAULT=true
fi
GAZEBO_GUI="${GAZEBO_GUI:-$GUI_DEFAULT}"
RVIZ="${RVIZ:-$GUI_DEFAULT}"

# launch 인자는 반대말(headless)이다. 여기서 한 번만 뒤집는다.
if is_true "$GAZEBO_GUI"; then GAZEBO_HEADLESS=false; else GAZEBO_HEADLESS=true; fi
if is_true "$RVIZ"; then RVIZ_HEADLESS=false; else RVIZ_HEADLESS=true; fi

BUILDING_YAML="$MAP_DIR/project1.building.yaml"
NAV_GRAPH="$MAP_DIR/nav_graphs/0.yaml"

if [[ ! -f "$BUILDING_YAML" ]]; then
  echo "없는 파일: $BUILDING_YAML" >&2
  echo "앱의 맵 관리에서 배포하기와 RMF 설정 내보내기를 먼저 하세요." >&2
  exit 1
fi

set +u
# shellcheck disable=SC1090
source "$ROS_SETUP"
[[ -f "$RMF_WS/install/setup.bash" ]] && source "$RMF_WS/install/setup.bash"
[[ -f "$PINKY_WS/install/setup.bash" ]] && source "$PINKY_WS/install/setup.bash"
[[ -f "$OMX_WS/install/setup.bash" ]] && source "$OMX_WS/install/setup.bash"
set -u

# C++ RMF 라이브러리와 Python 바인딩이 다른 설치본에서 섞이면 다중 로봇
# 등록 중 SIGSEGV가 날 수 있으므로 작업공간 설치본만 허용한다.
RMF_ADAPTER_MODULE="$(python3 -c 'import rmf_adapter; print(rmf_adapter.__file__)' 2>/dev/null || true)"
case "$RMF_ADAPTER_MODULE" in
  "$RMF_WS"/install/*) ;;
  *)
    echo "호환되지 않는 rmf_adapter가 선택됐습니다: ${RMF_ADAPTER_MODULE:-찾지 못함}" >&2
    echo "필요한 경로: $RMF_WS/install 아래" >&2
    echo "RMF↔Nav2 어댑터를 시작하지 않습니다." >&2
    exit 1
    ;;
esac
echo "RMF adapter: $RMF_ADAPTER_MODULE"

# nav_graphs/0.yaml 은 building.yaml 에서 파생된다. 맵에서 Waypoint 나 Lane 을
# 고쳐도 이 파일이 그대로면 RMF 는 옛날 지도를 본다. 없는 것이 아니라 낡은
# 것이라 오류가 나지 않는다 — 충전 Waypoint 를 방금 이었는데도 RMF 가 "충전
# 지점을 못 찾겠다"고 하는 것이 이 경우다. 그래서 매번 다시 만든다.
if [[ ! -f "$NAV_GRAPH" || "$BUILDING_YAML" -nt "$NAV_GRAPH" ]]; then
  echo "nav_graphs/0.yaml 을 building.yaml 에서 다시 만든다."
  mkdir -p "$MAP_DIR/nav_graphs"
  if ! ros2 run rmf_building_map_tools building_map_generator nav \
      "$BUILDING_YAML" "$MAP_DIR/nav_graphs"; then
    echo "nav graph 생성 실패. rmf_building_map_tools 가 있는지 보세요." >&2
    exit 1
  fi
fi

if [[ ! -f "$NAV_GRAPH" ]]; then
  echo "없는 파일: $NAV_GRAPH" >&2
  exit 1
fi

# 모든 출력을 로그 파일로 보낸다.
#
# 앱이 이 스크립트를 파이프에 물려 띄우면, 그 파이프를 읽는 쪽이 없을 때
# 64KB 가 차는 순간 Gazebo 가 write 에서 영원히 멈춘다. 물리가 돌지 않아
# 모델도 안 올라오고 토픽에 값도 오지 않는다. 파일로 보내면 막힐 일이 없고,
# 무슨 일이 있었는지 나중에 볼 수도 있다.
#
# 다만 그대로 두면 감당이 안 된다. Gazebo 의 ODE 가 메시끼리 닿을 때마다
# 같은 경고 한 줄을 물리 스텝마다 찍어, 시간당 1.8GB 씩 찼다. 그래서 거른다.
#
#   1. launch 접두사만 있고 내용이 없는 줄은 버린다.
#   2. 바로 앞과 똑같은 줄은 세기만 하고, 다른 줄이 오면 "몇 번 더" 로 접는다.
#   3. 그래도 넘치면 한 번 밀어 두고 새로 쓴다 (최대 2 배까지만 남는다).
#
# 에러만 남기지는 않는다. 지금까지 원인을 알려 준 것은 대부분 ERROR 가 아니라
# 뜨는 순서였다 — Gazebo 가 먼저인지, /clock 이 나왔는지, 다리가 어느 토픽을
# 걸었는지. 대신 ERROR·경고·역추적만 따로 모은 파일을 하나 더 쓴다.
LOG_FILE="$MAP_DIR/project1.log"
ERR_FILE="$MAP_DIR/project1.err.log"
LOG_MAX_MB="${LOG_MAX_MB:-200}"

# UI의 두 실행 경로가 거의 동시에 눌려도 두 번째 스크립트가 기존 로그를
# 비우거나 같은 월드를 한 벌 더 띄우지 못하게 한다. 잠금 FD는 이 셸이 끝날
# 때까지 유지된다.
LOCK_FILE="$MAP_DIR/.project1.run.lock"
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "project1 프로젝트가 이미 실행 중입니다." >&2
  exit 1
fi
: > "$ERR_FILE"

# mawk 는 detached 세션의 프로세스 치환 파이프에서 읽기가 멈춘 사례가 있다.
# unbuffered Python 수집기는 시작할 때 파일을 먼저 열고 한 줄씩 즉시 기록한다.
exec > >(exec python3 -u "$APP_ROOT/openrmf/scripts/log_collector.py" \
  --out "$LOG_FILE" --err "$ERR_FILE" --max-mb "$LOG_MAX_MB") 2>&1
echo "=== $(date '+%Y-%m-%d %H:%M:%S') project1 실행 ==="
# 창을 띄웠는지 안 띄웠는지 로그만 봐도 알게 한다. "화면이 안 뜬다" 는 물음이
# 실은 안 띄우기로 고른 것이었던 적이 여러 번이다.
echo "Gazebo 창: $GAZEBO_GUI · RViz: $RVIZ · ROS_DOMAIN_ID: $ROS_DOMAIN_ID"

# 자기 프로세스 그룹 번호를 남긴다. 중지 스크립트가 이 그룹을 통째로 끊는다.
# 앱이 detached 로 띄우면 이 셸의 PID 는 그룹 리더가 아니므로, PID 가 아니라
# 실제 PGID 를 적어야 한다.
PGID_FILE="$MAP_DIR/.project1.pgid"
ps -o pgid= -p $$ | tr -d ' ' > "$PGID_FILE"

cleanup() {
  echo "정리 중..."
  kill $(jobs -p) 2>/dev/null || true
  # PGID 파일은 지우지 않는다.
  #
  # 이 셸이 먼저 끝나고 자식이 살아남는 일이 있다. 그때 파일까지 지우면
  # 그 그룹을 끊을 손잡이가 사라져, 중지 스크립트도 다음 실행의 남은 항목
  # 검사도 그 프로세스를 영영 못 찾는다. 파일은 중지 스크립트가 지운다.
}
trap cleanup EXIT INT TERM

# 필요한 패키지가 없으면 launch 가 통째로 예외를 내며 멈춘다. 그러면 다른
# 로봇까지 안 뜨는데, 화면에는 찾아본 경로 목록만 잔뜩 나와 원인을 알기 어렵다.
missing=()
for pkg in $REQUIRED_PACKAGES; do
  ros2 pkg prefix "$pkg" >/dev/null 2>&1 || missing+=("$pkg")
done
if ((${#missing[@]} > 0)); then
  echo "없는 ROS 패키지: ${missing[*]}" >&2
  echo "" >&2
  echo "이 프로젝트의 로봇을 띄우려면 아래를 빌드하고 다시 실행하세요." >&2
  for pkg in "${missing[@]}"; do
    case "$pkg" in
      pinky_*) echo "  $pkg  ->  cd $PINKY_WS && colcon build" >&2 ;;
      open_manipulator_*) echo "  $pkg  ->  cd $OMX_WS && colcon build" >&2 ;;
      *) echo "  $pkg" >&2 ;;
    esac
  done
  exit 1
fi

# 월드에 센서 시스템을 채운다.
#
# 월드는 rmf_building_map_tools 가 제 템플릿(gz_world.sdf)에서 만드는데, 거기에는
# Physics · UserCommands · SceneBroadcaster 셋뿐이다. RMF 의 시범 로봇(slotcar)은
# 라이다를 안 쓰므로 필요가 없었다.
#
# 우리 핑키는 gpu_lidar · camera · imu 를 단다. 센서 시스템이 없으면 이 센서들이
# **하나도 발행하지 않는다.** 토픽 이름은 보이는데 데이터가 영영 안 온다. 라이다가
# 없으면 AMCL 도 Nav2 도 불가능하다.
#
# 배포할 때마다 월드가 다시 만들어지므로 여기서 매번 채운다. 이미 있으면 넘어간다.
ensure_world_sensors() {
  local world="$1"
  [ -f "$world" ] || return 0
  python3 - "$world" <<'PYTHON'
import sys

path = sys.argv[1]
with open(path, encoding='utf-8') as handle:
    world = handle.read()

# 이름으로 찾는다. filename 은 앞에 lib 이 붙기도 하고 안 붙기도 한다.
wanted = [
    ('gz::sim::systems::Sensors',
     '    <plugin filename="gz-sim-sensors-system"\n'
     '            name="gz::sim::systems::Sensors">\n'
     '      <render_engine>ogre2</render_engine>\n'
     '    </plugin>\n'),
    ('gz::sim::systems::Imu',
     '    <plugin filename="gz-sim-imu-system"\n'
     '            name="gz::sim::systems::Imu">\n'
     '    </plugin>\n'),
]
added = [name for name, _ in wanted if name not in world]
if not added:
    print('월드에 센서 시스템이 이미 있습니다.')
    sys.exit(0)

block = ''.join(snippet for name, snippet in wanted if name not in world)
# <world ...> 바로 다음에 넣는다. 시스템 플러그인은 월드의 자식이어야 한다.
marker = world.index('>', world.index('<world')) + 1
with open(path, 'w', encoding='utf-8') as handle:
    handle.write(world[:marker] + '\n' + block + world[marker:])
print('월드에 센서 시스템을 넣었습니다: ' + ', '.join(added))
PYTHON
}
ensure_world_sensors "$MAP_DIR/project1.world"

# 월드의 충돌 검출기를 bullet 으로 바꾼다.
#
# 기본값은 ODE 인데, 메시끼리 닿으면 무너진다. 우리 로봇은 충돌 도형이 전부
# 메시(핑키의 base_link.stl 따위)이고, 건물 바닥·벽도 배포가 만든 메시
# (generated_models/<맵>_L1/meshes/floor_1.obj)다. 그래서 로봇이 바닥에 서 있는
# 것만으로도 메시 대 메시다.
#
# 로봇 두 대가 겹쳐 놓이면 접점이 폭발해 여기서 죽는다:
#
#   ODE Message 2: Trimesh-trimesh contact hash table bucket overflow   (103번)
#   ODE INTERNAL ERROR 1: assertion "keyindex < lastkeyindex || ..." failed
#     in UpdateArbitraryContactInNode() [collision_trimesh_trimesh.cpp:285]
#   [ERROR] [gazebo-1]: process has died ... exit code 134
#
# 자리를 안 고른 로봇은 전부 지도 원점에 놓이므로 두 대만 있어도 이렇게 된다.
# 실제로 스폰 4초 만에 Gazebo 가 죽었고, 그 뒤 RMF 와 Nav2 만 살아남아 토픽
# 이름은 있는데 값은 하나도 안 오는 상태로 30분을 돌았다.
#
# bullet 은 같은 조건에서 경고 한 줄 없이 버틴다. 주행 거리도 ODE 와 같다
# (0.2 m/s 로 4초에 ODE 0.811 m · bullet 0.807 m). 자리를 겹쳐 놓는 것 자체는
# 여전히 잘못이지만, 그것 때문에 시뮬레이터가 죽지는 않게 한다.
#
# 배포할 때마다 월드가 다시 만들어지므로 여기서 매번 채운다. 이미 있으면 넘어간다.
ensure_world_collision_detector() {
  local world="$1"
  [ -f "$world" ] || return 0
  python3 - "$world" <<'PYTHON'
import re
import sys

path = sys.argv[1]
with open(path, encoding='utf-8') as handle:
    world = handle.read()

if '<collision_detector>' in world:
    print('월드에 충돌 검출기가 이미 지정돼 있습니다.')
    sys.exit(0)

block = ('      <dart>\n'
         '        <collision_detector>bullet</collision_detector>\n'
         '      </dart>\n')

opening = re.search(r'<physics\b[^>]*?(/?)>', world)
if opening is None:
    # 월드를 못 고쳐도 실행은 계속한다. 여기서 멈추면 다른 로봇까지 안 뜬다.
    sys.stderr.write('<physics> 가 없어 충돌 검출기를 못 넣었습니다.\n')
    sys.exit(0)

if opening.group(1):
    # <physics ... /> 처럼 닫혀 있으면 열어서 넣는다.
    head = opening.group(0)[:-2].rstrip() + '>\n'
    world = (world[:opening.start()] + head + block + '    </physics>'
             + world[opening.end():])
else:
    end = world.find('</physics>', opening.end())
    if end < 0:
        sys.stderr.write('</physics> 가 없어 충돌 검출기를 못 넣었습니다.\n')
        sys.exit(0)
    # 닫는 태그가 놓인 줄의 맨 앞에서 자른다. 태그 바로 앞에서 자르면 그 줄의
    # 들여쓰기가 우리 블록 앞에 붙고 </physics> 가 1열로 밀린다.
    head = world.rfind('\n', 0, end) + 1
    if world[head:end].strip():
        head = end
    world = world[:head] + block + world[head:]

with open(path, 'w', encoding='utf-8') as handle:
    handle.write(world)
print('월드의 충돌 검출기를 bullet 으로 바꿨습니다.')
PYTHON
}
ensure_world_collision_detector "$MAP_DIR/project1.world"

# Gazebo 가 실제로 떴는지 보고 다음 단계로 넘어간다.
#
# 예전에는 `&` 로 띄우고 `sleep 12` 만 했다. 뜬 줄 알고 넘어간 것이지 확인한
# 것이 아니었다. 그래서 Gazebo 가 스폰 4초 만에 죽었는데도(ODE 메시 충돌
# 어서션, exit 134) RMF 와 Nav2 가 그 시체 위에 올라갔다. 프로세스는 15개가
# 30분 넘게 살아 있었고 토픽 이름도 다 나왔지만 발행자는 0개였다 — 이름은
# 다리와 구독자가 남긴 것이다. 무엇이 잘못됐는지 어디에도 안 보였다.
#
# 두 가지를 본다. 월드를 물고 있는 `gz sim` 이 있는가, 그리고 /clock 이 나오는가.
# 떠 있는 것과 물리가 도는 것은 다르다. use_sim_time 을 쓰는 RMF 노드는 /clock
# 이 없으면 시간이 멈춘 줄 알고 그대로 멈춰 있는다.
GAZEBO_WAIT="${GAZEBO_WAIT:-90}"
wait_for_gazebo() {
  local world="$1"
  local deadline=$((SECONDS + GAZEBO_WAIT))
  while ((SECONDS < deadline)); do
    if pgrep -u "$(id -u)" -f "gz sim.*$world" >/dev/null 2>&1 &&
       timeout 5 ros2 topic echo /clock --once >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  return 1
}

echo "[1/3] Gazebo bringup"
ros2 launch "$MAP_DIR/project1_bringup.launch.xml" headless:="$GAZEBO_HEADLESS" &
if ! wait_for_gazebo "$MAP_DIR/project1.world"; then
  echo "" >&2
  echo "Gazebo 가 $GAZEBO_WAIT 초 안에 뜨지 않았습니다." >&2
  echo "RMF 와 Nav2 는 띄우지 않고 여기서 멈춥니다 — 월드가 없으면 그 둘은" >&2
  echo "토픽 이름만 만들어 놓고 값은 하나도 못 받습니다." >&2
  echo "" >&2
  echo "무엇이 있었는지: $LOG_FILE" >&2
  echo "오류만 모은 것: $ERR_FILE" >&2
  exit 1
fi

echo "[2/3] Open-RMF"
ros2 launch "$MAP_DIR/project1.launch.xml" headless:="$RVIZ_HEADLESS" &
sleep 12

# RMF↔Nav2 어댑터가 뜨고 계속 살아 있는지 지켜본다.
#
# 이 어댑터가 죽어도 Gazebo·Nav2·RMF core 는 그대로 남는다. 그래서 토픽은 잘
# 오는데 주문만 안 먹는 상태가 된다. 화면에는 `RMF 가 답하지 않았습니다` 로만
# 보이고 무엇이 죽었는지는 어디에도 안 나왔다.
#
# 실제로 로봇 ID 에 하이픈이 있어(`PK-01`) 어댑터가 로봇을 플릿에 붙이는 순간
# 죽은 일이 있다. RMF 가 `rmf/dynamic_event/begin/<플릿>/<로봇>` 토픽을 만드는데
# ROS 2 토픽 이름에는 하이픈을 못 쓰기 때문이다.
ADAPTER_WAIT="${ADAPTER_WAIT:-90}"
# launch 의 respawn_delay 보다 넉넉해야 한다. 짧으면 다시 뜨는 중인 것을 두고
# 죽었다고 알린다.
ADAPTER_RESPAWN_WAIT="${ADAPTER_RESPAWN_WAIT:-30}"
ADAPTER_HEALTH_GRACE="${ADAPTER_HEALTH_GRACE:-120}"
ADAPTER_HEALTH_INTERVAL="${ADAPTER_HEALTH_INTERVAL:-30}"
ADAPTER_HEALTH_FAILURES="${ADAPTER_HEALTH_FAILURES:-3}"
EXPECTED_FLEET_ROBOTS="pinky_01 pinky_02"
watch_fleet_adapter() {
  local pattern="$MAP_DIR/project1_nav2_adapter.py"
  local deadline=$((SECONDS + ADAPTER_WAIT))
  while ((SECONDS < deadline)); do
    pgrep -u "$(id -u)" -f "$pattern" >/dev/null 2>&1 && break
    sleep 2
  done
  if ! pgrep -u "$(id -u)" -f "$pattern" >/dev/null 2>&1; then
    echo "" >&2
    echo "RMF↔Nav2 어댑터가 $ADAPTER_WAIT 초 안에 뜨지 않았습니다." >&2
    echo "RMF 는 주문을 받아도 배차할 플릿이 없습니다." >&2
    echo "오류만 모은 것: $ERR_FILE" >&2
    return
  fi
  echo "RMF↔Nav2 어댑터가 떴습니다."
  local health_after=$((SECONDS + ADAPTER_HEALTH_GRACE))
  local last_health=0
  local failed_health=0
  # 뜬 다음 죽는 것이 진짜 문제다. 계속 지켜본다.
  #
  # 다만 launch 가 respawn 으로 다시 띄운다. 사라진 그 순간에 죽었다고 알리면
  # 5초 뒤 멀쩡히 살아난 것을 두고 사람을 뛰게 만든다. 돌아오기를 기다렸다가,
  # 정말 안 돌아올 때만 알린다.
  while :; do
    if pgrep -u "$(id -u)" -f "$pattern" >/dev/null 2>&1; then
      if ((SECONDS >= health_after && SECONDS - last_health >= ADAPTER_HEALTH_INTERVAL)); then
        last_health=$SECONDS
        local fleet_state
        fleet_state="$(timeout 12 ros2 topic echo /fleet_states --once 2>/dev/null || true)"
        local missing=0
        local robot
        for robot in $EXPECTED_FLEET_ROBOTS; do
          if ! grep -Fq "name: $robot" <<<"$fleet_state"; then
            missing=1
            echo "RMF fleet state에 $robot 등록이 없습니다." >&2
          fi
        done
        if ((missing)); then
          failed_health=$((failed_health + 1))
          if ((failed_health >= ADAPTER_HEALTH_FAILURES)); then
            echo "fleet 등록 확인이 $failed_health 회 연속 실패했습니다. 어댑터를 재기동합니다." >&2
            pkill -u "$(id -u)" -f "$pattern" || true
            failed_health=0
            health_after=$((SECONDS + ADAPTER_HEALTH_GRACE))
          fi
        else
          failed_health=0
        fi
      fi
      sleep 5
      continue
    fi
    local back=$((SECONDS + ADAPTER_RESPAWN_WAIT))
    local revived=0
    while ((SECONDS < back)); do
      sleep 2
      if pgrep -u "$(id -u)" -f "$pattern" >/dev/null 2>&1; then
        revived=1
        break
      fi
    done
    if ((revived)); then
      echo "RMF↔Nav2 어댑터가 죽었다가 다시 떴습니다." >&2
      continue
    fi
    break
  done
  echo "" >&2
  echo "RMF↔Nav2 어댑터가 죽었고 다시 뜨지도 않았습니다." >&2
  echo "이제 RMF 는 주문을 받지 못하고, RViz 에서는 경로와 로봇이 사라집니다 —" >&2
  echo "그 둘을 내는 /nav_graphs · /fleet_states 가 이 어댑터에서만 나옵니다." >&2
  echo "Gazebo 와 Nav2 는 그대로 살아 있어 토픽은 계속 옵니다. 그래서 겉으로는" >&2
  echo "멀쩡해 보입니다." >&2
  echo "" >&2
  echo "먼저 위에 출력된 RMF adapter 경로가 rmf_ws/install 아래인지 확인하세요." >&2
  echo "C++ 라이브러리와 Python 바인딩의 설치본이 섞이면 다중 로봇 등록 중" >&2
  echo "SIGSEGV가 날 수 있습니다." >&2
  echo "또 다른 원인은 로봇 ID 입니다. RMF 가 ID 로 토픽을 만드는데" >&2
  echo "(rmf/dynamic_event/begin/<플릿>/<로봇>) 영문·숫자·밑줄만 쓸 수 있습니다." >&2
  echo "하이픈이 들어간 ID 는 로봇을 플릿에 붙이는 순간 어댑터를 죽입니다." >&2
  echo "" >&2
  echo "무엇이 있었는지: $LOG_FILE" >&2
  echo "오류만 모은 것: $ERR_FILE" >&2
}

# Nav2 와 RMF↔Nav2 어댑터. 이것이 없으면 RMF 가 배차해도 로봇이 안 움직인다 —
# /<로봇>/cmd_vel 에 발행하는 것이 아무것도 없기 때문이다.
#
# RMF core 다음이라야 한다. 어댑터는 뜨자마자 schedule node 를 찾는다.
echo "[3/3] Nav2 와 RMF 어댑터"
watch_fleet_adapter &
ros2 launch "$MAP_DIR/project1_nav2.launch.xml"
