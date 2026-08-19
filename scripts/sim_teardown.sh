#!/usr/bin/env bash
# 호스트 시뮬레이션 층만 완전히 내린다. Docker 층은 건드리지 않는다.
#
#   scripts/sim_teardown.sh              내린다
#   scripts/sim_teardown.sh --dry-run    죽일 후보의 pid 만 출력한다
#
# 모르는 인자를 받으면 아무것도 죽이지 않고 실패한다. 오타가 조용히 전체 teardown
# 으로 실행되면 되돌릴 수 없다.
#
# 이름 패턴으로 pkill 을 직접 쓰면 두 가지가 잘못된다.
#
# 첫째, 명령줄에 패턴이 그대로 들어가서 pkill 이 자기 자신을 죽인다. 그래서
# 패턴을 이 파일 안에 두고 스크립트로 실행한다.
#
# 둘째, Docker 컨테이너의 ROS 프로세스도 호스트 `ps` 에 보인다. `/opt/ros` 같은
# 패턴으로 걸면 `rmf_api` 컨테이너까지 함께 죽는다. 그래서 후보를 모은 뒤 cgroup
# 이 docker 인 것을 제외하고 죽인다.
#
# 놓친 종류가 있으면 조용히 누적된다. 이전 세대의 `status_node` 가 살아 있으면 같은
# 토픽에 여러 세대가 함께 발행해서 측정값 자체가 오염되고, DDS 참가자가 쌓여 서비스
# 발견이 timeout 된다. 실제로 세 세대가 겹쳐 load average 가 130 까지 갔고, 그
# 상태에서 읽은 status 는 어느 세대 것인지 말할 수 없었다. 노드를 새로 추가하면
# 아래 목록에도 반드시 추가한다.
set -u

DRY_RUN=false
for argument in "$@"; do
  case "$argument" in
    --dry-run) DRY_RUN=true ;;
    *)
      echo "모르는 인자입니다: $argument" >&2
      echo "사용법: scripts/sim_teardown.sh [--dry-run]" >&2
      exit 2
      ;;
  esac
done

# `pgrep -f` 는 명령줄 전체를 본다. 아래 PATTERNS 에는 `trihouse_rmf_bridge` 나
# `control_tower.task_manager` 같은 **경로 이름**이 들어 있어서, 그 경로를 인자로
# 받은 도구의 명령줄이 그대로 걸린다. 실제로 이 스크립트가 시뮬을 내리면서 같은
# 셸의 `pytest` 를 함께 죽여 테스트 실행이 통째로 사라졌다. 빌드도 마찬가지로
# 중간에 죽으면 install 이 반쯤 쓰인 채 남는다.
#
# teardown 이 내릴 것은 시뮬 층이지 그 층을 다루는 도구가 아니다.
EXCLUDE_PATTERNS=(
  'pytest'
  'colcon'
)

PATTERNS=(
  'p0_simulation_bringup'
  'two_pinky_order_demo'
  'rmf_core.launch'

  # Gazebo 와 bridge
  'gz sim'
  'ign gazebo'
  'ros_gz'
  'parameter_bridge'

  # Nav2
  'nav2_'
  'lifecycle_manager'
  'map_server'
  'amcl'
  'controller_server'
  'planner_server'
  'route_server'
  'smoother_server'
  'behavior_server'
  'bt_navigator'
  'waypoint_follower'
  'velocity_smoother'
  'collision_monitor'
  'opennav_docking'
  'robot_state_publisher'

  # Open-RMF
  'rmf_traffic'
  'rmf_task'
  'rmf_fleet'
  'door_supervisor'
  'lift_supervisor'
  'mutex_group_supervisor'
  'trihouse_rmf_bridge'
  'pinky_easy_fleet_adapter'

  # Trihouse 온보드 노드
  'status_node'
  'sim_hardware'
  'readiness_checker'
  'readiness_node'
  'battery_condition'
  'battery_policy'
  'fleet_gateway'
  'gateway_node'
  'trihouse_pinky_fleet'
  'trihouse_pinky_bringup'
  'gazebo_omx_adapter'
  'trihouse_omx_adapter'
  # 카메라 송신도 시뮬 층의 일부다. 빠져 있어서 세대마다 살아남았고, 그 유령
  # 발행자 때문에 `verify_robot_status.py` 가 `publishers=2` 를 보고 "이전 세대가
  # 남았다" 로 판정했다. 측정이 오염되면 그 위의 모든 판단이 흔들린다.
  'trihouse_pinky_vision'
  'camera_streamer'

  # 관제 워커
  'control_tower.task_manager'
  'control_tower.rmf_adapter'
)

excluded() {
  # 제외는 **실행 파일** 기준이다. 인자에 든 경로로 판정하면 안 된다.
  #
  # 예전에는 명령줄 전체를 부분 문자열로 봤다. 그래서 pytest 가 만든 임시 경로를
  # 인자로 받은 프로세스가 pytest 실행으로 오인되어 살아남았다. 실제로
  # `test_vision_launch.py` 가 남긴
  #   python3 .../ros2 launch trihouse_pinky_vision ... config_file:=/tmp/pytest-of-syw/...
  # 가 세대마다 쌓였고, 그 `camera_streamer` 3개가 RTSP 발행자를 계속 재시작해
  # RTF 를 0.09 까지 떨어뜨렸다. Nav2 controller 가 20 Hz 를 놓쳐 주행이 실패했다.
  local pid="$1" pattern program
  local -a argv programs
  mapfile -d '' -t argv < "/proc/$pid/cmdline" 2>/dev/null || return 1
  (( ${#argv[@]} )) || return 1

  # argv[0] 이 프로그램이다. 파이썬 인터프리터면 그다음 토큰까지 본다 —
  # `python -m pytest` 와 `python /path/to/colcon` 을 함께 덮기 위해서다.
  programs=("${argv[0]##*/}")
  if [[ "${programs[0]}" == python* ]]; then
    if [[ "${argv[1]:-}" == "-m" ]]; then
      programs+=("${argv[2]:-}")
    else
      programs+=("${argv[1]##*/}")
    fi
  fi

  for pattern in "${EXCLUDE_PATTERNS[@]}"; do
    for program in "${programs[@]}"; do
      [[ "$program" == "$pattern" ]] && return 0
    done
  done
  return 1
}

collect() {
  local pattern pid
  for pattern in "${PATTERNS[@]}"; do
    while read -r pid; do
      [[ -n "$pid" ]] || continue
      [[ "$pid" == "$$" || "$pid" == "$PPID" ]] && continue
      if grep -qs docker "/proc/$pid/cgroup" 2>/dev/null; then
        continue
      fi
      excluded "$pid" && continue
      echo "$pid"
    done < <(pgrep -f -- "$pattern" 2>/dev/null)
  done
}

mapfile -t victims < <(collect | sort -un)

if [[ "$DRY_RUN" == true ]]; then
  # 아무것도 죽이지 않는다. 후보만 보여 준다.
  printf '%s\n' "${victims[@]}"
  echo "candidates=${#victims[@]}"
  exit 0
fi

if ((${#victims[@]})); then
  kill -INT "${victims[@]}" 2>/dev/null
  # SIGINT 로 스스로 정리할 시간을 준 뒤 남은 것만 강제로 내린다.
  for _ in $(seq 1 10); do
    sleep 1
    still=0
    for pid in "${victims[@]}"; do
      kill -0 "$pid" 2>/dev/null && still=1
    done
    ((still)) || break
  done
  kill -9 "${victims[@]}" 2>/dev/null
  sleep 2
fi

mapfile -t leftover < <(collect | sort -un)
echo "killed=${#victims[@]} leftover=${#leftover[@]}"
if ((${#leftover[@]})); then
  ps -o pid,comm,args -p "$(IFS=,; echo "${leftover[*]}")" 2>/dev/null | head -20
fi

# 세그먼트는 프로세스보다 오래 살아남아 다음 실행을 오염시킨다. 프로세스가 모두
# 사라진 것을 확인한 뒤에만 지운다.
rm -f /dev/shm/fastrtps_* /dev/shm/sem.fastrtps_* 2>/dev/null
echo -n "fastrtps_shm_left="; ls /dev/shm/ 2>/dev/null | grep -c fastrtps
echo -n "docker_containers="; docker ps --format '{{.Names}}' 2>/dev/null | wc -l
