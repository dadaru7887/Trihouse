#!/usr/bin/env bash

configure_p0_simulation_environment() {
  # EN: P0 is local simulation; every host-published endpoint must remain
  # reachable on loopback even when .env contains the physical 4060 LAN address.
  # KO: P0는 로컬 시뮬레이션이므로 .env에 실물 4060 LAN 주소가 있어도 호스트에
  # 공개한 모든 endpoint를 loopback에서 접근할 수 있어야 한다.
  export FMS_TCP_BIND="${P0_FMS_TCP_BIND:-127.0.0.1}"
  export FMS_API_HOST="${P0_FMS_API_HOST:-127.0.0.1}"
  export EDGE_BIND_ADDRESS="${P0_EDGE_BIND_ADDRESS:-127.0.0.1}"
}

configure_p0_ros_domain() {
  local env_file="${1:?environment file is required}"
  local file_domain
  file_domain="$(grep -E '^ROS_DOMAIN_ID=' "$env_file" | tail -n 1 | cut -d= -f2- || true)"

  # EN: An explicit P0 override isolates simulation without rewriting the
  # hardware .env shared by the physical bringup.
  # KO: 명시적인 P0 override로 실물 bringup이 공유하는 .env를 고치지 않고
  # 시뮬레이션 DDS domain만 격리한다.
  export ROS_DOMAIN_ID="${P0_ROS_DOMAIN_ID:-${ROS_DOMAIN_ID:-$file_domain}}"
  if [[ ! "$ROS_DOMAIN_ID" =~ ^[0-9]+$ ]] || (( ROS_DOMAIN_ID > 232 )); then
    echo "P0 ROS_DOMAIN_ID가 유효하지 않습니다: ${ROS_DOMAIN_ID:-<비어 있음>}" >&2
    return 2
  fi
}
