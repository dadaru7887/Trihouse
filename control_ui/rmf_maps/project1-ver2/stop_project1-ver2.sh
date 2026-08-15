#!/usr/bin/env bash
# project1-ver2 프로젝트로 띄운 프로세스를 내린다.
# rmf_control_ui 가 맵 프로젝트에서 생성했다.
#
# 이 프로젝트의 launch 경로로 시작한 것만 고른다. 다른 맵으로 띄운 RMF 나
# 관계없는 Gazebo 는 건드리지 않는다.
set -euo pipefail

MAP_DIR="${MAP_DIR:-/home/gyi/robosapiens/rmf_maps/project1-ver2}"

# 이 프로젝트가 쓰는 로봇 네임스페이스. 인자에 맵 경로가 없는 노드는 이 이름으로
# 찾는다 — robot_state_publisher 같은 것은 URDF 만 들고 있어 경로가 없다.
ROBOT_NAMESPACES="pinky_01 pinky_02 omx_03 omx_04"
APP_ROOT="${ROBOSAPIENS_ROOT:-$(cd "$MAP_DIR/../.." && pwd)}"
RMF_WS="${RMF_WS:-$APP_ROOT/rmf_ws}"
LOCK_FILE="$MAP_DIR/.project1-ver2.run.lock"

# INT → TERM → KILL 로 올려 가며 내린다.
#
# rclpy 노드는 TERM 을 받고도 종료 중에 스레드가 서로를 기다리며 굳는 일이
# 있다. 거기서 멈추면 노드가 살아남아 다음 실행에서 이름이 겹친다.
stop_pids() {
  local label="$1"
  shift
  local pids=("$@") remaining=() pid
  if ((${#pids[@]} == 0)); then
    echo "$label: 실행 중이 아님"
    return
  fi
  echo "$label 중지: ${pids[*]}"
  local signal
  for signal in INT TERM KILL; do
    remaining=()
    for pid in "${pids[@]}"; do
      # 좀비는 이미 끝난 것이다. 기다릴 것이 없다.
      if kill -0 "$pid" 2>/dev/null &&
         [[ "$(ps -o stat= -p "$pid" 2>/dev/null)" != *Z* ]]; then
        remaining+=("$pid")
      fi
    done
    if ((${#remaining[@]} == 0)); then
      return
    fi
    [[ "$signal" == "KILL" ]] &&
      echo "  $label: 응답이 없어 강제 종료합니다 (${remaining[*]})"
    kill "-$signal" "${remaining[@]}" 2>/dev/null || true
    sleep 3
  done
}

stop_matching() {
  local label="$1" pattern="$2"
  mapfile -t pids < <(pgrep -u "$(id -u)" -f "$pattern" 2>/dev/null || true)
  stop_pids "$label" "${pids[@]}"
}

# ros2 launch 가 죽으면 자식이 init 으로 재부모화된다. 그룹도 잃고
# `ros2 launch <경로>` 라는 이름도 잃어서, 이름이나 PGID 로는 잡히지 않는다.
# 이 맵 디렉터리를 인자로 물고 있으면 이 프로젝트가 띄운 것이다.
sweep_map_dir() {
  local label="$1" pids=() pid args
  while read -r pid; do
    [[ -z "$pid" || "$pid" == "$$" || "$pid" == "$PPID" ]] && continue
    # pgrep 과 여기 사이에 끝난 프로세스가 있을 수 있다. 없으면 조용히 넘긴다.
    [[ -r "/proc/$pid/cmdline" ]] || continue
    # 2>/dev/null 을 먼저 건다. 뒤에 걸면 입력 리다이렉트가 먼저 실패하면서
    # 셸이 그 오류를 그대로 찍는다 — pgrep 과 여기 사이에 끝난 프로세스가 있다.
    args="$(tr '\0' ' ' 2>/dev/null < "/proc/$pid/cmdline" || true)"
    # 이 스크립트 자신과 이것을 부른 셸은 건드리지 않는다.
    [[ "$args" == *"stop_project1-ver2.sh"* ]] && continue
    [[ "$args" == *"$MAP_DIR"* ]] || continue
    pids+=("$pid")
  done < <(pgrep -u "$(id -u)" -f "$MAP_DIR" 2>/dev/null || true)
  if ((${#pids[@]} == 0)); then
    echo "$label: 남은 것 없음"
    return
  fi
  stop_pids "$label" "${pids[@]}"
}

stop_matching "Open-RMF (project1-ver2)" "ros2 launch $MAP_DIR/project1-ver2.launch.xml"
stop_matching "Gazebo bringup (project1-ver2)" \
  "ros2 launch $MAP_DIR/project1-ver2_bringup.launch.xml"
stop_matching "Gazebo 서버 (project1-ver2)" "gz sim.*$MAP_DIR/project1-ver2.world"

# 실행 스크립트가 남긴 프로세스 그룹을 통째로 끊는다. 이름으로 못 찾은 자식이
# 있어도 여기서 정리된다.
PGID_FILE="$MAP_DIR/.project1-ver2.pgid"
if [[ -f "$PGID_FILE" ]]; then
  PGID="$(cat "$PGID_FILE")"
  if [[ "$PGID" =~ ^[0-9]+$ ]] && kill -0 -- "-$PGID" 2>/dev/null; then
    echo "프로세스 그룹 $PGID 중지"
    kill -INT -- "-$PGID" 2>/dev/null || true
    sleep 3
    kill -TERM -- "-$PGID" 2>/dev/null || true
  fi
  rm -f "$PGID_FILE"
fi

# 마지막으로 재부모화되어 살아남은 것을 쓸어낸다. fleet_manager 처럼 launch 가
# 죽어도 혼자 도는 것들이 여기서 잡힌다.
sweep_map_dir "이 맵을 물고 남은 노드 (project1-ver2)"

# 네임스페이스로 한 번 더 쓸어낸다.
#
# robot_state_publisher 같은 노드는 인자에 맵 경로가 없다. 대신 ROS 가 넣어 준
# `__ns:=/<gz 이름>` 을 들고 있다. 이 프로젝트가 쓰는 이름은 우리가 정한
# 것이므로 다른 것과 겹치지 않는다.
sweep_namespaces() {
  local pids=() pid ns
  for ns in $ROBOT_NAMESPACES; do
    while read -r pid; do
      [[ -z "$pid" || "$pid" == "$$" || "$pid" == "$PPID" ]] && continue
      pids+=("$pid")
    done < <(pgrep -u "$(id -u)" -f -- "__ns:=/$ns\b" 2>/dev/null || true)
  done
  if ((${#pids[@]} == 0)); then
    echo "로봇 네임스페이스 (project1-ver2): 남은 것 없음"
    return
  fi
  stop_pids "로봇 네임스페이스 (project1-ver2)" "${pids[@]}"
}

sweep_namespaces

# 마지막으로 RMF core 를 쓸어낸다.
#
# schedule node 나 supervisor 는 인자에 맵 경로도 로봇 네임스페이스도 없다.
# launch 가 죽고 PGID 파일도 없으면 어떤 방법으로도 못 찾는다. RMF core 는
# 한 번에 하나만 뜰 수 있으므로, 백엔드를 내리기로 한 이상 이것이 대상이다.
sweep_rmf_core() {
  mapfile -t pids < <(
    pgrep -u "$(id -u)" -f "$RMF_WS/install/rmf_" 2>/dev/null || true
  )
  if ((${#pids[@]} == 0)); then
    echo "RMF core: 남은 것 없음"
    return
  fi
  stop_pids "RMF core" "${pids[@]}"
}

sweep_rmf_core

# Gazebo 다리를 쓸어낸다.
#
# `parameter_bridge` 는 인자에 맵 경로가 있는 것도 있지만, `/clock` 하나만 잇는
# 것은 인자가 `/clock@rosgraph_msgs...` 뿐이라 위 그물에 하나도 안 걸린다.
# 부모마저 systemd 로 바뀌면 프로세스 그룹으로도 못 잡는다.
#
# 그러면 다음 실행에서 **/clock 을 두 곳이 낸다.** 두 시계가 번갈아 나오니
# 시각이 앞뒤로 튀고, tf2 가 `Detected jump back in time` 으로 버퍼를 통째로
# 비운다. AMCL 은 위치추정을 잃고 Nav2 는 명령을 멈춘다 — 로봇은 멀쩡한데
# 가만히 서 있고, 그 원인이 한 시간 전에 남은 프로세스라는 것은 어디에도
# 안 보인다. 실제로 그렇게 39번 튀었다.
sweep_bridges() {
  mapfile -t pids < <(
    pgrep -u "$(id -u)" -f "ros_gz_bridge/parameter_bridge" 2>/dev/null || true
  )
  if ((${#pids[@]} == 0)); then
    echo "Gazebo 다리: 남은 것 없음"
    return
  fi
  stop_pids "Gazebo 다리" "${pids[@]}"
}

sweep_bridges

# 실행 셸의 FD 9는 모든 자식에게 상속된다. launch가 죽은 뒤 이름도 경로도 없는
# lifecycle_manager가 고아로 남아도 이 잠금 FD만큼은 그대로 들고 있다. 따라서
# 이름 검색이 모두 실패한 뒤 잠금 파일을 연 PID를 직접 찾아 마지막으로 끊는다.
sweep_lock_holders() {
  local pass fd target pid pids=()
  for pass in 1 2 3; do
    pids=()
    for fd in /proc/[0-9]*/fd/*; do
      target="$(readlink "$fd" 2>/dev/null || true)"
      [[ "$target" == "$LOCK_FILE" ]] || continue
      pid="${fd#/proc/}"
      pid="${pid%%/*}"
      [[ "$pid" == "$$" || "$pid" == "$PPID" ]] && continue
      [[ " ${pids[*]} " == *" $pid "* ]] || pids+=("$pid")
    done
    ((${#pids[@]} == 0)) && return
    stop_pids "실행 잠금 보유 프로세스 (project1-ver2, 확인 $pass)" "${pids[@]}"
  done
}

sweep_lock_holders

# 종료 성공은 이름 검색 결과가 아니라 새 실행이 잠금을 잡을 수 있는지로 판정한다.
# 좀비는 FD를 보유하지 않으므로 잠금 검사를 통과하며, 살아 있는 숨은 프로세스는
# 반드시 실패시킨다. 실패를 성공처럼 표시하지 않도록 0이 아닌 코드로 끝낸다.
if ! flock -n "$LOCK_FILE" true; then
  echo "오류: project1-ver2 실행 잠금이 아직 사용 중입니다." >&2
  echo "확인: fuser -v $LOCK_FILE" >&2
  exit 1
fi

remaining_zombies="$(ps -u "$(id -u)" -o pid=,ppid=,pgid=,stat=,args= |
  awk -v map="$MAP_DIR" '$4 ~ /^Z/ && index($0, map) {print}')"
if [[ -n "$remaining_zombies" ]]; then
  echo "오류: project1-ver2 관련 좀비 프로세스가 남았습니다:" >&2
  echo "$remaining_zombies" >&2
  exit 1
fi

echo "project1-ver2 프로젝트 프로세스를 정리했습니다."
