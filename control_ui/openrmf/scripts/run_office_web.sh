#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RMF_WS="${RMF_WS:-$ROOT_DIR/rmf_ws}"
RMF_API_URL="${RMF_API_URL:-http://127.0.0.1:8000}"
RMF_SERVER_URI="${RMF_SERVER_URI:-ws://127.0.0.1:8000/_internal}"
RMF_DASHBOARD_PORT="${RMF_DASHBOARD_PORT:-3000}"
RMF_DASHBOARD_URL="${RMF_DASHBOARD_URL:-http://localhost:$RMF_DASHBOARD_PORT}"
RMF_TRAJECTORY_SERVER_URL="${RMF_TRAJECTORY_SERVER_URL:-ws://127.0.0.1:8006}"
ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-0}"
API_IMAGE="${RMF_API_IMAGE:-ghcr.io/open-rmf/rmf-web/api-server:jazzy}"
DASHBOARD_IMAGE="${RMF_DASHBOARD_IMAGE:-robosapiens-rmf-dashboard:0.3.0}"
API_CONTAINER="${RMF_API_CONTAINER:-robosapiens-rmf-api}"
DASHBOARD_CONTAINER="${RMF_DASHBOARD_CONTAINER:-robosapiens-rmf-dashboard}"
API_WAIT_SECONDS="${RMF_API_WAIT_SECONDS:-60}"
DASHBOARD_WAIT_SECONDS="${RMF_DASHBOARD_WAIT_SECONDS:-60}"
MAP_WAIT_SECONDS="${RMF_MAP_WAIT_SECONDS:-90}"
HEADLESS="${RMF_HEADLESS:-false}"
OPEN_BROWSER="${RMF_OPEN_BROWSER:-true}"

configure_gazebo_rendering() {
  local vendor_file
  local has_drm_gpu=0
  local has_nvidia_gpu=0

  for vendor_file in /sys/class/drm/card*/device/vendor; do
    [[ -r "$vendor_file" ]] || continue
    has_drm_gpu=1
    if [[ "$(<"$vendor_file")" == "0x10de" ]]; then
      has_nvidia_gpu=1
      break
    fi
  done

  if [[ "$has_nvidia_gpu" == "1" ]]; then
    # Ogre2 selects the NVIDIA DRM device directly. Forcing Mesa software
    # rendering at the same time can crash the Gazebo GUI during startup.
    unset LIBGL_ALWAYS_SOFTWARE
    unset MESA_LOADER_DRIVER_OVERRIDE
    echo "Gazebo rendering: NVIDIA GPU detected; using hardware rendering."
    if ! command -v nvidia-smi >/dev/null 2>&1 ||
       ! nvidia-smi -L >/dev/null 2>&1; then
      echo "Warning: NVIDIA GPU exists, but nvidia-smi cannot access its driver." >&2
      echo "Gazebo will start without software-rendering overrides." >&2
    fi
  elif [[ "$has_drm_gpu" == "1" ]]; then
    unset LIBGL_ALWAYS_SOFTWARE
    unset MESA_LOADER_DRIVER_OVERRIDE
    echo "Gazebo rendering: non-NVIDIA GPU detected; using hardware rendering."
  else
    export LIBGL_ALWAYS_SOFTWARE=1
    unset MESA_LOADER_DRIVER_OVERRIDE
    echo "Gazebo rendering: no DRM GPU detected; using software rendering."
  fi
}

if [[ ! "$API_WAIT_SECONDS" =~ ^[1-9][0-9]*$ ]] ||
   [[ ! "$DASHBOARD_WAIT_SECONDS" =~ ^[1-9][0-9]*$ ]] ||
   [[ ! "$MAP_WAIT_SECONDS" =~ ^[1-9][0-9]*$ ]] ||
   [[ ! "$RMF_DASHBOARD_PORT" =~ ^[1-9][0-9]*$ ]]; then
  echo "Wait times must be positive integers." >&2
  exit 1
fi
if [[ "$HEADLESS" != "true" && "$HEADLESS" != "false" ]]; then
  echo "RMF_HEADLESS must be either true or false." >&2
  exit 1
fi
if [[ "$OPEN_BROWSER" != "true" && "$OPEN_BROWSER" != "false" ]]; then
  echo "RMF_OPEN_BROWSER must be either true or false." >&2
  exit 1
fi

for command in curl docker; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "Required command not found: $command" >&2
    exit 1
  fi
done
if [[ ! -f /opt/ros/jazzy/setup.bash ]]; then
  echo "ROS 2 Jazzy was not found: /opt/ros/jazzy/setup.bash" >&2
  exit 1
fi
if [[ ! -f "$RMF_WS/install/setup.bash" ]]; then
  echo "Open-RMF workspace not found: $RMF_WS/install/setup.bash" >&2
  exit 1
fi
if ! docker info >/dev/null 2>&1; then
  echo "Docker daemon is not accessible. Start Docker or check user permissions." >&2
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
STARTED_DASHBOARD=0
RMF_PID=""

cleanup() {
  trap - EXIT INT TERM
  if [[ -n "$RMF_PID" ]]; then
    kill -INT "$RMF_PID" 2>/dev/null || true
    for _ in {1..10}; do
      kill -0 "$RMF_PID" 2>/dev/null || break
      sleep 1
    done
    if kill -0 "$RMF_PID" 2>/dev/null; then
      kill -TERM "$RMF_PID" 2>/dev/null || true
      for _ in {1..3}; do
        kill -0 "$RMF_PID" 2>/dev/null || break
        sleep 1
      done
    fi
    if kill -0 "$RMF_PID" 2>/dev/null; then
      kill -KILL "$RMF_PID" 2>/dev/null || true
    fi
    wait "$RMF_PID" 2>/dev/null || true
  fi
  if [[ "$STARTED_DASHBOARD" == "1" ]]; then
    docker stop "$DASHBOARD_CONTAINER" >/dev/null 2>&1 || true
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

container_name_available() {
  local name="$1"
  if docker container inspect "$name" >/dev/null 2>&1; then
    echo "Container '$name' already exists but its service is not responding." >&2
    echo "Stop it, or configure a different container name." >&2
    return 1
  fi
}

wait_for_url() {
  local label="$1"
  local url="$2"
  local timeout="$3"
  local second
  for ((second = 1; second <= timeout; second++)); do
    if curl --silent --fail "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  echo "$label did not become ready within ${timeout}s: $url" >&2
  return 1
}

if curl --silent --fail "$RMF_API_URL/time" >/dev/null 2>&1; then
  echo "Using the rmf-web API already running at $RMF_API_URL"
else
  container_name_available "$API_CONTAINER"
  echo "Starting rmf-web API: $API_CONTAINER"
  docker run --detach --rm \
    --name "$API_CONTAINER" \
    --network host \
    --ipc host \
    -e "ROS_DOMAIN_ID=$ROS_DOMAIN_ID" \
    -e "RMW_IMPLEMENTATION=$RMW_IMPLEMENTATION" \
    -e "FASTDDS_BUILTIN_TRANSPORTS=${FASTDDS_BUILTIN_TRANSPORTS:-DEFAULT}" \
    -e "RMF_SERVER_USE_SIM_TIME=true" \
    "$API_IMAGE" >/dev/null
  STARTED_API=1
fi
wait_for_url "rmf-web API" "$RMF_API_URL/time" "$API_WAIT_SECONDS"

if curl --silent --fail "$RMF_DASHBOARD_URL" 2>/dev/null |
   grep -q "RMF Dashboard"; then
  echo "Using the Open-RMF web dashboard already running at $RMF_DASHBOARD_URL"
elif curl --silent --fail "$RMF_DASHBOARD_URL" >/dev/null 2>&1; then
  echo "Port $RMF_DASHBOARD_PORT is occupied by a different web application." >&2
  echo "Stop the existing dashboard before running this script." >&2
  exit 1
else
  container_name_available "$DASHBOARD_CONTAINER"
  if ! docker image inspect "$DASHBOARD_IMAGE" >/dev/null 2>&1; then
    echo "Building pinned Open-RMF web dashboard image: $DASHBOARD_IMAGE"
    docker build \
      --tag "$DASHBOARD_IMAGE" \
      "$ROOT_DIR/openrmf/docker/rmf-web-dashboard"
  fi
  echo "Starting Open-RMF web dashboard: $DASHBOARD_CONTAINER"
  docker run --detach --rm \
    --name "$DASHBOARD_CONTAINER" \
    --publish "127.0.0.1:$RMF_DASHBOARD_PORT:80" \
    "$DASHBOARD_IMAGE" >/dev/null
  STARTED_DASHBOARD=1
fi
wait_for_url "rmf-web dashboard" "$RMF_DASHBOARD_URL" "$DASHBOARD_WAIT_SECONDS"

set +u
source /opt/ros/jazzy/setup.bash
source "$RMF_WS/install/setup.bash"
set -u
if ! command -v ros2 >/dev/null 2>&1; then
  echo "ros2 was not found after sourcing the ROS and Open-RMF workspaces." >&2
  exit 1
fi

configure_gazebo_rendering

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
  exit 1
fi

echo
echo "Open-RMF web dashboard is ready: $RMF_DASHBOARD_URL"
echo "Press Ctrl+C to stop the services started by this script."
if [[ "$OPEN_BROWSER" == "true" ]] &&
   [[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]] &&
   command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$RMF_DASHBOARD_URL" >/dev/null 2>&1 &
fi

wait "$RMF_PID"
