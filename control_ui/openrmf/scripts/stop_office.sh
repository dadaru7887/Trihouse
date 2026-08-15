#!/usr/bin/env bash
set -euo pipefail

KEEP_SUPERVISOR=0
if [[ "${1:-}" == "--keep-supervisor" ]]; then
  KEEP_SUPERVISOR=1
  shift
fi
if [[ "$#" -ne 0 ]]; then
  echo "Usage: $0 [--keep-supervisor]" >&2
  exit 2
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RMF_WS="${RMF_WS:-$ROOT_DIR/rmf_ws}"
API_CONTAINER="${RMF_API_CONTAINER:-robosapiens-rmf-api}"
WAIT_SECONDS="${RMF_STOP_WAIT_SECONDS:-15}"

if [[ ! "$WAIT_SECONDS" =~ ^[1-9][0-9]*$ ]]; then
  echo "RMF_STOP_WAIT_SECONDS must be a positive integer." >&2
  exit 2
fi

find_user_processes() {
  local pattern="$1"
  pgrep -u "$(id -u)" -f "$pattern" 2>/dev/null || true
}

wait_for_processes() {
  local deadline=$((SECONDS + WAIT_SECONDS))
  local pid
  while ((SECONDS < deadline)); do
    local running=0
    for pid in "$@"; do
      # kill -0 also succeeds for zombies. A zombie has already exited and
      # cannot hold an RMF port, so do not delay the next backend startup.
      if kill -0 "$pid" 2>/dev/null &&
         [[ "$(ps -o stat= -p "$pid" 2>/dev/null)" != *Z* ]]; then
        running=1
        break
      fi
    done
    if [[ "$running" == "0" ]]; then
      return 0
    fi
    sleep 1
  done
  return 1
}

stop_processes() {
  local label="$1"
  shift
  local initial_signal="$1"
  shift
  local pids=("$@")
  if ((${#pids[@]} == 0)); then
    echo "$label: not running"
    return
  fi

  echo "Stopping $label: ${pids[*]}"
  kill "-$initial_signal" "${pids[@]}" 2>/dev/null || true
  if ! wait_for_processes "${pids[@]}"; then
    if [[ "$initial_signal" == "TERM" ]]; then
      echo "$label did not stop within ${WAIT_SECONDS}s; sending SIGKILL."
      kill -KILL "${pids[@]}" 2>/dev/null || true
    else
      echo "$label did not stop within ${WAIT_SECONDS}s; sending SIGTERM."
      kill -TERM "${pids[@]}" 2>/dev/null || true
    fi
  fi
}

if [[ "$KEEP_SUPERVISOR" == "0" ]]; then
  mapfile -t supervisor_pids < <(
    find_user_processes \
      "$ROOT_DIR/openrmf/scripts/run_office_flutter.sh --backend-only"
  )
  stop_processes "Open-RMF app backend supervisor" INT "${supervisor_pids[@]}"
else
  echo "Open-RMF app backend supervisor: keeping current process"
fi

mapfile -t launch_pids < <(
  find_user_processes \
    "ros2 launch $ROOT_DIR/openrmf/launch/office_web.launch.xml"
)
stop_processes "Open-RMF office launch" INT "${launch_pids[@]}"

# A force-closed launch terminal may leave some children re-parented to init.
# Match only the office demo's installed config/map paths so unrelated RMF
# deployments are not affected.
mapfile -t fleet_manager_pids < <(
  find_user_processes \
    "$RMF_WS/install/rmf_demos_fleet_adapter/lib/rmf_demos_fleet_adapter/fleet_manager.*tinyRobot_config.yaml"
)
stop_processes "orphan office fleet manager" TERM "${fleet_manager_pids[@]}"

mapfile -t fleet_adapter_pids < <(
  find_user_processes \
    "$RMF_WS/install/rmf_demos_fleet_adapter/lib/rmf_demos_fleet_adapter/fleet_adapter.*tinyRobot_config.yaml"
)
stop_processes "orphan office fleet adapter" TERM "${fleet_adapter_pids[@]}"

mapfile -t gazebo_office_pids < <(
  find_user_processes \
    "gz sim.*$RMF_WS/install/rmf_demos_maps/share/rmf_demos_maps/maps/office/office.world"
)
stop_processes "orphan office Gazebo server" TERM "${gazebo_office_pids[@]}"

if command -v docker >/dev/null 2>&1 &&
   docker container inspect "$API_CONTAINER" >/dev/null 2>&1; then
  if [[ "$(docker inspect -f '{{.State.Running}}' "$API_CONTAINER")" == "true" ]]; then
    echo "Stopping rmf-web API container: $API_CONTAINER"
    docker stop --time "$WAIT_SECONDS" "$API_CONTAINER" >/dev/null
  else
    echo "rmf-web API container is already stopped: $API_CONTAINER"
  fi
else
  echo "rmf-web API container not found: $API_CONTAINER"
fi

echo "Open-RMF office background services are stopped."
