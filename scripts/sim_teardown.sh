#!/usr/bin/env bash
# 호스트 시뮬레이션 층만 완전히 내린다. Docker 층은 건드리지 않는다.
#
#   scripts/sim_teardown.sh
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

  # 관제 워커
  'control_tower.task_manager'
  'control_tower.rmf_adapter'
)

collect() {
  local pattern pid
  for pattern in "${PATTERNS[@]}"; do
    while read -r pid; do
      [[ -n "$pid" ]] || continue
      [[ "$pid" == "$$" || "$pid" == "$PPID" ]] && continue
      if grep -qs docker "/proc/$pid/cgroup" 2>/dev/null; then
        continue
      fi
      echo "$pid"
    done < <(pgrep -f -- "$pattern" 2>/dev/null)
  done
}

mapfile -t victims < <(collect | sort -un)

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
