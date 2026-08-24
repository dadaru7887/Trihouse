# Pinky_01 자율주행·정식 주문 인수인계

`PK_01` 실물 주행을 정식 FMS/RMF 주문으로 시험하는 절차다. 직접 ROS
`ExecuteTransport` calibration action은 이 문서의 주문 절차에 사용하지 않는다.

## 고정 값과 터미널

| 항목 | 값 |
| --- | --- |
| 개발 PC | `192.168.0.4` |
| Pinky_01 | `192.168.0.21` |
| ROS domain / Discovery Server | `12` / `192.168.0.4:11811` |
| namespace / robot ID | `pinky_01` / `PK_01` |
| map revision | `new_map_2:df9a7f70eab87135a0e1a73c2b63a0a15aae2de3512a6c760a3259d0337a32ed` |
| FMS API | `http://192.168.0.4:8080` |

터미널은 네 개를 쓴다.

1. 개발 PC 1: Discovery Server
2. Pinky_01 1: bringup
3. Pinky_01 2: status와 로그
4. 개발 PC 2: FMS 주문과 job 감시

실물 이동 전에는 통로를 비우고 E-stop 담당자를 배치한다.

## 1. 협로 설정 배포

상온·냉장·냉동 일반 주문을 열려면 각 profile의 `measured` 값이 모두 아래와 같아야 한다.

```yaml
measured:
  entry_pose: true
  dock_pose: true
  enter: true
  exit: true
```

`fleet_node`는 launch 때 설정을 읽으므로, 변경 뒤 Pinky에 복사하고 bringup을 재시작한다.

```bash
# [개발 PC]
cd /home/newuser/Trihouse/.worktrees/physical-integration-v1

scp -P 22 \
  config/narrow_zones.new_map_2.yaml \
  pinky@192.168.0.21:/home/pinky/narrow_zones.new_map_2.yaml
```

```bash
# [Pinky_01]
sha256sum /home/pinky/narrow_zones.new_map_2.yaml
```

## 2. 개발 PC 터미널 1 — Discovery Server

```bash
cd /home/newuser/Trihouse/.worktrees/physical-integration-v1

source /opt/ros/jazzy/setup.bash
source install/setup.bash

export ROS_DOMAIN_ID=12
export ROS_AUTOMATIC_DISCOVERY_RANGE=SYSTEM_DEFAULT
export ROS_DISCOVERY_SERVER='192.168.0.4:11811'
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export FASTDDS_BUILTIN_TRANSPORTS=UDPv4
unset ROS_STATIC_PEERS
unset FASTRTPS_DEFAULT_PROFILES_FILE

pgrep -af '[f]astdds discovery' || \
  fastdds discovery -i 0 -l 192.168.0.4 -p 11811
```

이 터미널은 유지한다.

## 3. 개발 PC — 멈춘 주문 취소

`DISPATCH_ATTEMPTS_EXHAUSTED` 또는 dead-letter가 발생한 주문은 worker를
재시작해도 다시 claim되지 않는다. 새 주문 전에 해당 주문을 취소해 Pinky·OMX·도크와
재고 예약을 반드시 해제한다. 아래는 이번 실험에서 멈춘 job `4`, 대기 중이던 job `5`를
취소하는 명령이다.

```bash
# [개발 PC]
cd /home/newuser/Trihouse/.worktrees/physical-integration-v1

export FMS_API='http://192.168.0.4:8080'

cancel_job() {
  local job_id="$1"
  local run_id
  run_id="$(date +%Y%m%d%H%M%S)"

  curl -sS -X POST \
    "$FMS_API/internal/v1/jobs/$job_id/cancel" \
    -H 'Content-Type: application/json' \
    -H "Idempotency-Key: cancel-job-${job_id}-${run_id}" \
    -d '{"reason":"physical_test_restart_dead_letter","requested_by":"newuser"}' \
    | python3 -m json.tool
}

cancel_job 4
cancel_job 5
```

각 응답의 `state`가 `cancelled`여야 한다. 이 요청은 주문을 종료하고 예약을 해제하는
상태 변경이므로, 이미 물리 동작이 시작된 주문에는 사용하지 말고 먼저 정지 상태를 확인한다.

## 4. 개발 PC — FMS Docker·주문 worker 재기동

정식 주문은 Docker의 MySQL/FMS Gateway와 호스트의 세 worker가 모두 필요하다.
아래 명령은 MySQL volume을 삭제하지 않으므로 기존 주문·재고 데이터는 유지된다.

```bash
# [개발 PC]
cd /home/newuser/Trihouse/.worktrees/physical-integration-v1

# 현재 PC LAN IP를 명시한다. .env에 과거 IP가 남아 있으면 Docker가 존재하지 않는
# 주소에 8080/8788을 bind하려다 기동에 실패한다.
export FMS_API_HOST='192.168.0.4'
export FMS_TCP_BIND='192.168.0.4'

# mysql volume은 그대로 두고 FMS Gateway만 새 TCP session으로 재생성한다.
FMS_API_HOST="$FMS_API_HOST" FMS_TCP_BIND="$FMS_TCP_BIND" \
docker compose -p trihouse_p0 \
  -f compose.yaml \
  -f compose.control.yaml \
  up -d --force-recreate fms_gateway

FMS_API_HOST="$FMS_API_HOST" FMS_TCP_BIND="$FMS_TCP_BIND" \
docker compose -p trihouse_p0 \
  -f compose.yaml \
  -f compose.control.yaml \
  ps

until curl -fsS http://192.168.0.4:8080/ready > /dev/null; do
  sleep 2
done
echo 'PASS: FMS Gateway ready'
```

FMS를 재시작하면 기존 worker의 HTTP 연결도 함께 새로 잡는 것이 안전하다. **새 주문을
넣기 전에 아래 세 worker가 먼저 실행 중이어야 한다.** worker가 없으면 outbox가 lease
재시도 5회를 소진해 `dead_letter`가 되고 주문은 자동으로 재개되지 않는다.

`control_tower/task_manager/job_runner.py`를 수정한 경우에는 Pinky나 Docker를 다시
빌드하지 않는다. 개발 PC 작업트리에서 `python3 -m control_tower...`로 worker를 실행하므로,
아래 worker 재기동만 하면 수정본이 적용된다.

```bash
# [개발 PC]
pkill -INT -f '^python3 -m control_tower.task_manager.job_runner_node' \
  2>/dev/null || true
pkill -INT -f '^python3 -m control_tower.task_manager.executor_worker_node' \
  2>/dev/null || true
pkill -INT -f '^python3 -m control_tower.rmf_adapter.rmf_gateway_worker_node' \
  2>/dev/null || true

sleep 3

source /opt/ros/jazzy/setup.bash
source install/setup.bash

export ROS_DOMAIN_ID=12
export ROS_AUTOMATIC_DISCOVERY_RANGE=SYSTEM_DEFAULT
export ROS_DISCOVERY_SERVER='192.168.0.4:11811'
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export FASTDDS_BUILTIN_TRANSPORTS=UDPv4
export FMS_API='http://192.168.0.4:8080'
unset ROS_STATIC_PEERS
unset FASTRTPS_DEFAULT_PROFILES_FILE

setsid nohup python3 -m control_tower.task_manager.job_runner_node \
  --fms-base-url "$FMS_API" \
  --poll-interval-s 1 \
  >> /tmp/trihouse_job_runner.log 2>&1 < /dev/null &

setsid nohup python3 -m control_tower.task_manager.executor_worker_node \
  --fms-base-url "$FMS_API" \
  --environment hardware \
  --poll-interval-s 1 \
  >> /tmp/trihouse_executor_worker.log 2>&1 < /dev/null &

setsid nohup python3 -m control_tower.rmf_adapter.rmf_gateway_worker_node \
  --fms-base-url "$FMS_API" \
  --fleet-name project1_pinky \
  --worker-id trihouse-rmf-worker \
  --poll-interval-s 1 \
  >> /tmp/trihouse_rmf_gateway_worker.log 2>&1 < /dev/null &

sleep 3

pgrep -af \
  'control_tower.task_manager.job_runner_node|control_tower.task_manager.executor_worker_node|control_tower.rmf_adapter.rmf_gateway_worker_node'
```

Worker 로그:

```bash
tail -F /tmp/trihouse_job_runner.log \
        /tmp/trihouse_executor_worker.log \
        /tmp/trihouse_rmf_gateway_worker.log
```

## 5. Pinky_01 터미널 1 — 종료 및 bringup

실행 중인 foreground launch가 있으면 먼저 그 창에서 `Ctrl+C`를 누른다.

```bash
source /opt/ros/jazzy/setup.bash
source /home/pinky/pinky_pro/install/setup.bash
source /home/pinky/trihouse_ws/install/setup.bash

export ROS_DOMAIN_ID=12
export ROS_AUTOMATIC_DISCOVERY_RANGE=SYSTEM_DEFAULT
export ROS_DISCOVERY_SERVER='192.168.0.4:11811'
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export FASTDDS_BUILTIN_TRANSPORTS=UDPv4
unset ROS_STATIC_PEERS
unset FASTRTPS_DEFAULT_PROFILES_FILE

pkill -INT -f \
  '^/usr/bin/python3 /opt/ros/jazzy/bin/ros2 launch trihouse_pinky_bringup trihouse_pinky.launch.py' \
  2>/dev/null || true

pkill -INT -f \
  '^/usr/bin/python3 /opt/ros/jazzy/bin/ros2 launch pinky_bringup bringup_robot_namespaced.launch.xml' \
  2>/dev/null || true

sleep 10

ros2 daemon stop 2>/dev/null || true
sleep 2
ros2 daemon start
```

```bash
# [Pinky_01 터미널 1 — foreground 유지]
cd /home/pinky/trihouse_ws

source /opt/ros/jazzy/setup.bash
source /home/pinky/pinky_pro/install/setup.bash
source install/setup.bash

export ROS_DOMAIN_ID=12
export ROS_AUTOMATIC_DISCOVERY_RANGE=SYSTEM_DEFAULT
export ROS_DISCOVERY_SERVER='192.168.0.4:11811'
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export FASTDDS_BUILTIN_TRANSPORTS=UDPv4
export MAP_REVISION='new_map_2:df9a7f70eab87135a0e1a73c2b63a0a15aae2de3512a6c760a3259d0337a32ed'
unset ROS_STATIC_PEERS
unset FASTRTPS_DEFAULT_PROFILES_FILE

ros2 launch trihouse_pinky_bringup trihouse_pinky.launch.py \
  namespace:=pinky_01 \
  robot_id:=PK_01 \
  map:=/home/pinky/map/new_map_2.yaml \
  map_revision:="$MAP_REVISION" \
  nav2_params_file:=/home/pinky/hardware_pinky_01.yaml \
  lifecycle_bond_timeout_s:=60.0 \
  navigation_start_delay_s:=60.0 \
  narrow_zones_file:=/home/pinky/narrow_zones.new_map_2.yaml \
  narrow_map_name:=new_map_2 \
  allow_narrow_calibration:=true \
  control_host:=192.168.0.4 \
  control_port:=8788 \
  vision_enabled:=false \
  docking_enabled:=false \
  2>&1 | tee -a /tmp/trihouse_pinky_pinky01.log
```

Navigation lifecycle은 launch 후 약 60~100초 걸릴 수 있다.

## 6. Pinky_01 터미널 2 — 상태와 로그

```bash
source /opt/ros/jazzy/setup.bash
source /home/pinky/pinky_pro/install/setup.bash
source /home/pinky/trihouse_ws/install/setup.bash

export ROS_DOMAIN_ID=12
export ROS_AUTOMATIC_DISCOVERY_RANGE=SYSTEM_DEFAULT
export ROS_DISCOVERY_SERVER='192.168.0.4:11811'
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export FASTDDS_BUILTIN_TRANSPORTS=UDPv4
unset ROS_STATIC_PEERS
unset FASTRTPS_DEFAULT_PROFILES_FILE

sleep 100

timeout 30 ros2 topic echo \
  /pinky_01/trihouse/readiness \
  trihouse_interfaces/msg/Readiness \
  --once

timeout 30 ros2 topic echo \
  /pinky_01/trihouse/status \
  trihouse_interfaces/msg/RobotStatus \
  --once

timeout 30 ros2 topic echo \
  /pinky_01/trihouse/safety/state \
  trihouse_interfaces/msg/SafetyState \
  --once
```

주문 전 조건:

```text
readiness.state: 1
missing_interfaces: []
status.frame_id: map
status.ready: true
status.errors: []
safety.state: 0
safety.detail: clear
```

주행 로그:

```bash
tail -F /tmp/trihouse_pinky_pinky01.log |
grep -aEi \
  'rule_transition|NavigateToPose|front_stop|swept_stop|protective_zone|failed|error|SCHEMA_INVALID'
```

## 7. 개발 PC 터미널 2 — 정식 FMS 주문

좌표를 직접 전송하지 않는다. FMS가 SKU의 `temperature_zone`, location map, RMF 배정을
기반으로 목적지와 `command_source=rmf` context를 만든다.

```bash
cd /home/newuser/Trihouse/.worktrees/physical-integration-v1

export FMS_API='http://192.168.0.4:8080'

submit_order() {
  local zone="$1"
  local sku="$2"
  local run_id
  local order_file

  run_id="$(date +%Y%m%d%H%M%S)"
  order_file="/tmp/trihouse-${zone}-order-${run_id}.json"

  curl -fsS -X POST \
    "$FMS_API/api/v1/orders" \
    -H 'Content-Type: application/json' \
    -H "Idempotency-Key: ${zone}-live-${run_id}" \
    -d "{\"external_reference\":\"${zone}-LIVE-${run_id}\",\"priority\":\"normal\",\"allow_partial_fulfillment\":false,\"items\":[{\"product_code\":\"${sku}\",\"quantity\":1}]}" \
    | tee "$order_file" \
    | python3 -m json.tool

  echo "ORDER_FILE=$order_file"
}
```

현재 시험 재고 SKU:

| 구역 | 명령 |
| --- | --- |
| 상온 | `submit_order ambient SKU-MANDARIN` |
| 냉장 | `submit_order chilled SKU-SANDWICH` |
| 냉동 | `submit_order frozen SKU-PORKBELLY` |

한 번에 한 주문만 실행한다. 예를 들어 상온 주문:

```bash
submit_order ambient SKU-MANDARIN
```

## 8. 개발 PC 터미널 2 — job 감시

`submit_order`가 출력한 `ORDER_FILE`에서 job ID를 읽고 상태를 감시한다.

```bash
JOB_ID="$(
  python3 - "$ORDER_FILE" <<'PY'
import json
import sys
print(json.load(open(sys.argv[1], encoding='utf-8'))['job_id'])
PY
)"

echo "JOB_ID=$JOB_ID"

watch -n 2 \
  "curl -fsS '$FMS_API/api/v1/jobs/$JOB_ID' | python3 -m json.tool"
```

## 9. 오류 판단

| 상태/로그 | 의미 |
| --- | --- |
| `SCHEMA_INVALID type=robot_status` | direct calibration context는 FMS의 정식 RMF schema가 아니므로, FMS 주문으로 시험한다. |
| `NARROW_PROFILE_UNMEASURED` | Pinky에 일반 주문 설정이 배포되지 않았거나 bringup을 재시작하지 않았다. |
| `entry_alignment_timeout` | 출입구 방향 정렬 중 map yaw가 변하지 않았다. FMS schema와 별도로 `cmd_vel_dock → cmd_vel_safe → odom`을 진단한다. |
| `front_stop` 또는 `swept_stop` | Safety Supervisor가 물리 장애물 또는 회전 여유 부족으로 차단했다. |
| `robot is not ready` | readiness, map pose, battery 또는 safety 조건이 실패했다. |
| `DISPATCH_ATTEMPTS_EXHAUSTED` | worker가 실행되지 않았거나 dispatch 수락/결과 보고 전에 lease 재시도 5회를 소진했다. 해당 job을 취소하고 worker를 먼저 기동한 뒤 새 주문을 만든다. |
| job runner의 `HTTP Error 409` | 기존 outbox의 idempotency key와 재시도 요청 내용이 달라졌다. arm step은 `assigned_device_id`를 비워야 한다. 수정본이 반영된 개발 PC worker를 재시작하고, 이미 dead-letter가 된 job은 취소 후 새 주문으로 시작한다. |
