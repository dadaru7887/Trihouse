#!/usr/bin/env bash
set -euo pipefail

BACKEND_ONLY=0
if [[ "${1:-}" == "--backend-only" ]]; then
  BACKEND_ONLY=1
  shift
fi
if [[ "$#" -ne 0 ]]; then
  echo "Usage: $0 [--backend-only]" >&2
  exit 2
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RMF_WS="${RMF_WS:-$ROOT_DIR/rmf_ws}"
RMF_API_URL="${RMF_API_URL:-http://127.0.0.1:8000}"
RMF_SERVER_URI="${RMF_SERVER_URI:-ws://127.0.0.1:8000/_internal}"
TRAJECTORY_SERVER_URL="${RMF_TRAJECTORY_SERVER_URL:-ws://127.0.0.1:8006}"
ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-0}"
API_IMAGE="${RMF_API_IMAGE:-ghcr.io/open-rmf/rmf-web/api-server:jazzy}"
API_CONTAINER="${RMF_API_CONTAINER:-robosapiens-rmf-api}"
API_WAIT_SECONDS="${RMF_API_WAIT_SECONDS:-60}"
MAP_WAIT_SECONDS="${RMF_MAP_WAIT_SECONDS:-90}"
HEADLESS="${RMF_HEADLESS:-false}"

if [[ ! "$API_WAIT_SECONDS" =~ ^[1-9][0-9]*$ ]] ||
   [[ ! "$MAP_WAIT_SECONDS" =~ ^[1-9][0-9]*$ ]]; then
  echo "RMF_API_WAIT_SECONDS and RMF_MAP_WAIT_SECONDS must be positive integers." >&2
  exit 1
fi
if [[ "$HEADLESS" != "true" && "$HEADLESS" != "false" ]]; then
  echo "RMF_HEADLESS must be either true or false." >&2
  exit 1
fi

for command in curl flutter; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "Required command not found: $command" >&2
    exit 1
  fi
done

if [[ ! -f /opt/ros/jazzy/setup.bash ]]; then
  echo "ROS 2 Jazzy was not found: /opt/ros/jazzy/setup.bash" >&2
  exit 1
fi

if [[ -z "${RMW_IMPLEMENTATION:-}" ]]; then
  if [[ -f /opt/ros/jazzy/lib/librmw_fastrtps_cpp.so ]]; then
    RMW_IMPLEMENTATION=rmw_fastrtps_cpp
  elif [[ -f /opt/ros/jazzy/lib/librmw_cyclonedds_cpp.so ]]; then
    RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
  else
    echo "No supported ROS 2 RMW implementation was found." >&2
    exit 1
  fi
fi
export ROS_DOMAIN_ID RMW_IMPLEMENTATION
if [[ "$RMW_IMPLEMENTATION" == "rmw_fastrtps_cpp" ]]; then
  FASTDDS_BUILTIN_TRANSPORTS="${FASTDDS_BUILTIN_TRANSPORTS:-UDPv4}"
  export FASTDDS_BUILTIN_TRANSPORTS
fi
STARTED_API=0
RMF_PID=""

cleanup() {
  trap - EXIT INT TERM
  if [[ -n "$RMF_PID" ]]; then
    kill -INT "$RMF_PID" 2>/dev/null || true
    wait "$RMF_PID" 2>/dev/null || true
  fi
  if [[ "$STARTED_API" == "1" ]]; then
    docker stop "$API_CONTAINER" >/dev/null 2>&1 || true
  fi
}

on_signal() {
  cleanup
  exit 130
}

trap cleanup EXIT
trap on_signal INT TERM

if [[ ! -f "$RMF_WS/install/setup.bash" ]]; then
  echo "Open-RMF workspace not found: $RMF_WS/install/setup.bash" >&2
  exit 1
fi

# A previous app can leave the ROS launch alive after its API container has
# disappeared. Starting another office instance would then collide on ports
# such as the fleet manager's 22011. Recover this repository's stale launch
# before creating a fresh API/backend pair.
if ! curl --silent --fail "$RMF_API_URL/time" >/dev/null 2>&1; then
  mapfile -t STALE_LAUNCH_PIDS < <(
    pgrep -u "$(id -u)" -f \
      "ros2 launch $ROOT_DIR/openrmf/launch/office_web.launch.xml" \
      2>/dev/null || true
  )
  mapfile -t STALE_FLEET_MANAGER_PIDS < <(
    pgrep -u "$(id -u)" -f \
      "$RMF_WS/install/rmf_demos_fleet_adapter/lib/rmf_demos_fleet_adapter/fleet_manager.*tinyRobot_config.yaml" \
      2>/dev/null || true
  )
  mapfile -t STALE_FLEET_ADAPTER_PIDS < <(
    pgrep -u "$(id -u)" -f \
      "$RMF_WS/install/rmf_demos_fleet_adapter/lib/rmf_demos_fleet_adapter/fleet_adapter.*tinyRobot_config.yaml" \
      2>/dev/null || true
  )
  STALE_OFFICE_PIDS=(
    "${STALE_LAUNCH_PIDS[@]}"
    "${STALE_FLEET_MANAGER_PIDS[@]}"
    "${STALE_FLEET_ADAPTER_PIDS[@]}"
  )
  if ((${#STALE_OFFICE_PIDS[@]} > 0)); then
    echo "Found stale Open-RMF office processes: ${STALE_OFFICE_PIDS[*]}"
    echo "Stopping stale backend before restart"
    "$ROOT_DIR/openrmf/scripts/stop_office.sh" --keep-supervisor
  fi
fi

if ! curl --silent --fail "$RMF_API_URL/time" >/dev/null 2>&1; then
  if ! command -v docker >/dev/null 2>&1; then
    echo "Required command not found: docker" >&2
    exit 1
  fi
  if ! docker info >/dev/null 2>&1; then
    echo "Docker daemon is not accessible. Add this user to the docker group or start rmf-web API manually." >&2
    exit 1
  fi
  if docker container inspect "$API_CONTAINER" >/dev/null 2>&1; then
    echo "Container '$API_CONTAINER' exists but its API is not responding." >&2
    echo "Stop or remove it, or set RMF_API_CONTAINER to another name." >&2
    exit 1
  fi
  echo "Starting rmf-web API container: $API_CONTAINER"
  docker run --detach --rm \
    --name "$API_CONTAINER" \
    --network host \
    --ipc host \
    -e "ROS_DOMAIN_ID=$ROS_DOMAIN_ID" \
    -e "RMW_IMPLEMENTATION=$RMW_IMPLEMENTATION" \
    -e "FASTDDS_BUILTIN_TRANSPORTS=${FASTDDS_BUILTIN_TRANSPORTS:-DEFAULT}" \
    -e "RMF_SERVER_USE_SIM_TIME=true" \
    "$API_IMAGE"
  STARTED_API=1
else
  echo "Using the rmf-web API already running at $RMF_API_URL"
fi

for ((second = 1; second <= API_WAIT_SECONDS; second++)); do
  if curl --silent --fail "$RMF_API_URL/time" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if ! curl --silent --fail "$RMF_API_URL/time" >/dev/null 2>&1; then
  echo "rmf-web API did not become ready at $RMF_API_URL" >&2
  exit 1
fi

set +u
source /opt/ros/jazzy/setup.bash
source "$RMF_WS/install/setup.bash"
set -u

if ! command -v ros2 >/dev/null 2>&1; then
  echo "ros2 was not found after sourcing the ROS and Open-RMF workspaces." >&2
  exit 1
fi

echo "Starting Open-RMF office simulation"
ros2 launch "$ROOT_DIR/openrmf/launch/office_web.launch.xml" \
  "server_uri:=$RMF_SERVER_URI" \
  "headless:=$HEADLESS" &
RMF_PID=$!

ADMIN_TOKEN="${RMF_API_TOKEN:-eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJzdHViIiwicHJlZmVycmVkX3VzZXJuYW1lIjoiYWRtaW4iLCJpYXQiOjE1MTYyMzkwMjIsImF1ZCI6InJtZl9hcGlfc2VydmVyIiwiaXNzIjoic3R1YiIsImV4cCI6MjA1MTIyMjQwMH0.zzX3zXp467ldkzmLVIadQ_AHr8M5uWVV43n4wEB0OhE}"
MAP_READY=0
echo "Waiting for the office building map"
for ((second = 1; second <= MAP_WAIT_SECONDS; second++)); do
  if curl --silent --fail \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    "$RMF_API_URL/building_map" >/dev/null 2>&1; then
    MAP_READY=1
    break
  fi
  if ! kill -0 "$RMF_PID" 2>/dev/null; then
    wait "$RMF_PID" || true
    echo "Open-RMF office simulation stopped before the map was ready." >&2
    exit 1
  fi
  sleep 1
done

if [[ "$MAP_READY" != "1" ]]; then
  echo "Building map did not become ready within ${MAP_WAIT_SECONDS}s." >&2
  if [[ "$STARTED_API" == "1" ]]; then
    echo "Check ROS topics and the API logs: docker logs $API_CONTAINER" >&2
  else
    echo "Check ROS topics and the rmf-web API logs at $RMF_API_URL." >&2
  fi
  exit 1
fi

cd "$ROOT_DIR/openrmf_app"
if [[ "$BACKEND_ONLY" == "1" ]]; then
  echo "RMF_BACKEND_READY"
  if [[ -n "${RMF_PARENT_PID:-}" ]]; then
    if [[ ! "$RMF_PARENT_PID" =~ ^[1-9][0-9]*$ ]]; then
      echo "RMF_PARENT_PID must be a positive integer." >&2
      exit 2
    fi
    while kill -0 "$RMF_PID" 2>/dev/null; do
      if ! kill -0 "$RMF_PARENT_PID" 2>/dev/null; then
        echo "Parent application exited; stopping Open-RMF backend."
        exit 0
      fi
      sleep 1
    done
  fi
  wait "$RMF_PID"
  exit $?
fi

echo "Preparing Flutter dependencies"
flutter pub get
echo "Starting the Open-RMF dashboard"
flutter run -d linux \
  --dart-define="RMF_API_URL=$RMF_API_URL" \
  --dart-define="RMF_API_TOKEN=$ADMIN_TOKEN" \
  --dart-define="RMF_TRAJECTORY_SERVER_URL=$TRAJECTORY_SERVER_URL"
