# PK_01 한 대 VLM+RL 자율주행 데이터 수집 런북

이 문서는 명령어만 제공한다. 각 장비의 운영자가 직접 실행한다.

목표:

```text
등록 목적지 선택
→ PK_01 한 대 RMF/Nav2 자율주행
→ 5080 VLM+RL recovery proposal 생성
→ 운영자 승인과 PK_01 실제 recovery 실행
→ 4060 MySQL trihouse_recovery에 transition 적재
→ training JSONL export
```

정상 주행만 하고 recovery trigger가 발생하지 않으면 영상은 MediaMTX에 저장되지만
`recovery_learning_transitions` 행은 생기지 않는다. DB 학습 행은 proposal 승인,
실제 recovery 실행 결과, 5080 next-state completion까지 끝나야 생성된다.

## 0. 팀 공유용 빠른 실행

실행 파일은 저장소의 다음 한 파일이다.

```text
tests/run_vlm_rl_dataset_route.py
```

이 파일은 `PK_01` 한 대에 대해 다음 두 방식을 모두 지원한다.

```text
--target-location-id ID       목적지 하나만 주행
--location-ids ID,ID,...      지정한 순서대로 배치 순회
--all                         DB 목적지 전체를 location_id 순으로 한 번씩 순회
```

### 0-1. 4060 환경값과 Docker

4060의 새 터미널에서 실제 저장소 경로와 로봇 LAN에 붙은 이 PC의 주소를 지정한다.
`PC1_LAN_IP`는 다른 PC 주소가 아니라 `ip -br addr`에 실제로 보이는 4060 주소여야 한다.

```bash
export TRIHOUSE_ROOT=/path/to/physical-integration-v1
cd "$TRIHOUSE_ROOT"

export PC1_LAN_IP=192.168.0.9
export FMS_API_HOST="$PC1_LAN_IP"
export FMS_TCP_BIND="$PC1_LAN_IP"
export EDGE_BIND_ADDRESS="$PC1_LAN_IP"
export FMS_API_BASE_URL="http://${PC1_LAN_IP}:8080"

ip -br addr | grep -F "$PC1_LAN_IP"

docker compose -p trihouse_p0 \
  -f compose.yaml \
  -f compose.control.yaml \
  -f compose.edge_4060.yaml \
  up -d mysql

until [ "$(docker inspect -f '{{.State.Health.Status}}' trihouse-mysql)" = healthy ]; do
  sleep 3
done

docker compose -p trihouse_p0 \
  -f compose.yaml \
  -f compose.control.yaml \
  -f compose.edge_4060.yaml \
  up -d --no-deps --force-recreate fms_gateway mediamtx

curl -fsS "$FMS_API_BASE_URL/ready" | python3 -m json.tool
```

Gateway를 로컬에서만 사용할 구성이라면 위 네 주소 값을 `127.0.0.1`로 통일할 수 있다.
다만 이 경우 별도 5080 PC와 PK_01은 4060 Gateway/MediaMTX에 직접 접속할 수 없으므로
다중 PC 실물 수집에는 `192.168.0.9` 같은 실제 LAN 주소를 사용한다.

### 0-2. 나머지 터미널 기동

Docker 준비 후 아래 상세 절차를 순서대로 실행하고 각 프로세스 터미널을 유지한다.

```text
C2: 5장 RMF core
C3: 6장 PK_01 RMF adapter
R1: 7장 PK_01 Nav2/Safety/Gateway/Camera
R2: 8장 PK_01 안전 상태 확인
A1: 9장 5080 VLM+RL runtime
C4: 10장 RMF Gateway worker
```

### 0-3. 목적지 조회와 dry-run

4060의 새 터미널에서 실행한다. 이 단계는 로봇을 움직이지 않는다.

```bash
export TRIHOUSE_ROOT=/path/to/physical-integration-v1
cd "$TRIHOUSE_ROOT"
export FMS_API_BASE_URL=http://192.168.0.9:8080

python3 tests/run_vlm_rl_dataset_route.py --list

python3 tests/run_vlm_rl_dataset_route.py \
  --target-location-id 12

python3 tests/run_vlm_rl_dataset_route.py \
  --location-ids 12,15,18
```

`--list` 출력은 차례대로 `location_id`, `rmf_waypoint_name`, `pose_x`, `pose_y`이다.
반드시 실제 출력의 ID로 위 예시 `12,15,18`을 바꾼다.

### 0-4. 실제 단일 목적지 수집

E-stop 담당자가 준비되어 있고 경로가 비어 있으며 R2 안전 확인이 PASS인 경우에만
다음 명령을 실행한다.

```bash
python3 tests/run_vlm_rl_dataset_route.py \
  --api-base-url "$FMS_API_BASE_URL" \
  --target-location-id 12 \
  --execute \
  --confirm-motion PK_01
```

실행기는 job 생성, RMF dispatch, job 종료 대기를 한 번 수행한다.

### 0-5. 실제 지정 배치 순회

각 목적지는 독립된 job이다. 앞 job이 `completed`가 된 뒤에만 다음 job을 생성한다.
`failed`, `cancelled`, timeout이 발생하면 다음 목적지를 보내지 않고 즉시 멈춘다.

```bash
python3 tests/run_vlm_rl_dataset_route.py \
  --api-base-url "$FMS_API_BASE_URL" \
  --location-ids 12,15,18 \
  --execute \
  --confirm-motion PK_01 \
  --timeout-seconds 600
```

### 0-6. DB 등록 목적지 전체 순회

`--all`은 `new_map_2`에서 `rmf_waypoint_name`이 있는 모든 목적지를 `location_id`
오름차순으로 한 번씩 방문한다. 충전기, 좁은 구역, 운영상 제외해야 할 지점까지 포함될
수 있으므로 먼저 `--list`로 경로를 검토한다. 실물 수집에서는 검토한 ID만 넣는
`--location-ids` 방식을 권장한다.

```bash
python3 tests/run_vlm_rl_dataset_route.py \
  --api-base-url "$FMS_API_BASE_URL" \
  --all \
  --execute \
  --confirm-motion PK_01 \
  --timeout-seconds 600
```

### 0-7. 수집 결과 확인

정상 주행 영상은 MediaMTX 쪽에 남는다. `trihouse_recovery`의 학습 transition은
장애물/stuck trigger, proposal 승인, 실제 recovery, next-state completion까지 발생한
경우에만 추가된다.

```bash
docker exec trihouse-mysql sh -lc \
  'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" --table -e \
  "SELECT recovery_step_id,skill_name,reward_total,done,created_at \
   FROM trihouse_recovery.recovery_learning_transitions \
   ORDER BY created_at DESC LIMIT 20"' 2>/dev/null
```

### 0-8. 팀 공유 전 코드 자체 검증

이 명령은 가짜 로컬 Gateway만 사용하며 로봇과 운영 DB를 건드리지 않는다.

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  pytest -q tests/test_vlm_rl_dataset_route_runner.py
```

## 1. 장비 구성

| 장비 | 역할 | 예시 LAN 주소 |
|---|---|---|
| 4060 PC | MySQL, FMS Gateway, MediaMTX, RMF core/adapter/worker | `192.168.0.9` |
| 5080 PC | YOLO/VLM/RL inference | `192.168.0.7` |
| PK_01 | Nav2, Safety, Fleet Gateway, 주행 카메라 | `192.168.0.21` |

DB는 4060 Docker 안에만 둔다. 5080과 PK_01은 DB에 직접 접속하지 않는다.

```text
5080 → 4060:8080       FMS/recovery HTTP API
5080 → 4060:8554       PK_01 RTSP 읽기
PK_01 → 4060:8788      Gateway TCP
4060 ROS ↔ PK_01 ROS   DDS, ROS_DOMAIN_ID=12
```

각 PC에서 저장소 경로가 다를 수 있으므로 아래 값을 해당 PC의 실제 경로로 바꾼다.

```bash
export TRIHOUSE_ROOT=/path/to/physical-integration-v1
```

PK_01에서는 다음을 실제 ROS workspace 경로로 바꾼다.

```bash
export ROBOT_WS=/path/to/pk01/trihouse_ws
```

## 2. 터미널과 실행 순서

| 순서 | 터미널 | 장비 | 실행 내용 |
|---:|---|---|---|
| 1 | C1 | 4060 | Docker: MySQL, Gateway, MediaMTX |
| 2 | C2 | 4060 | RMF core |
| 3 | C3 | 4060 | PK_01 RMF adapter |
| 4 | R1 | PK_01 | Nav2, Safety, Gateway, 카메라 |
| 5 | R2 | PK_01 | 안전·상태 확인 |
| 6 | A1 | 5080 | VLM+RL runtime |
| 7 | C4 | 4060 | RMF Gateway worker |
| 8 | C5 | 4060 | 목적지 job 생성·자율주행 시작·proposal 승인 |
| 9 | C6 | 4060 | DB 확인·JSONL export |

이 런에서는 다음을 실행하지 않는다.

```text
scripts/p0_up.sh
control_tower/bringup/p0_simulation_bringup.sh
control_tower.task_manager.job_runner_node
control_tower.task_manager.executor_worker_node
PK_02 또는 OMX 관련 launch
```

## 3. 선택 사항 — 4060의 이전 시뮬레이션 종료

새 4060 PC이거나 관련 프로세스가 없으면 생략한다. 이 명령은 Docker와 DB를 삭제하지
않지만 4060에서 실행 중인 호스트 ROS/시뮬레이션 프로세스를 종료한다. 실물 C2를 시작하기
전에만 실행한다.

### C0 — 4060

```bash
export TRIHOUSE_ROOT=/path/to/physical-integration-v1
cd "$TRIHOUSE_ROOT"

scripts/sim_teardown.sh --dry-run
```

출력된 PID가 이전 시뮬레이션인지 확인한 뒤:

```bash
scripts/sim_teardown.sh
pkill -TERM -f 'python3 -m tests[.]simulation[.]omx[.]action_server' 2>/dev/null || true
sleep 3

pgrep -af \
  'p0_simulation_bringup|two_pinky_order_demo|tests[.]simulation[.]omx|rmf_core[.]launch' \
  || echo 'PASS: old host ROS/simulation stopped'
```

이후 `scripts/p0_up.sh`를 실행하지 않는다.

## 4. C1 — 4060 Docker 기동

4060의 새 터미널에서 실행한다.

```bash
export TRIHOUSE_ROOT=/path/to/physical-integration-v1
cd "$TRIHOUSE_ROOT"

export PC1_LAN_IP=192.168.0.9
export FMS_API_HOST=192.168.0.9
export FMS_TCP_BIND=192.168.0.9
export EDGE_BIND_ADDRESS=192.168.0.9

ip -br addr
```

4060 NIC에 `192.168.0.9`가 있을 때만 실행한다.

```bash
docker compose -p trihouse_p0 \
  -f compose.yaml \
  -f compose.control.yaml \
  -f compose.edge_4060.yaml \
  up -d mysql

until [ "$(docker inspect -f '{{.State.Health.Status}}' trihouse-mysql)" = healthy ]; do
  sleep 3
done

docker compose -p trihouse_p0 \
  -f compose.yaml \
  -f compose.control.yaml \
  -f compose.edge_4060.yaml \
  up -d --no-deps --force-recreate fms_gateway mediamtx

until curl -fsS -m 2 http://192.168.0.9:8080/ready; do
  sleep 3
done
echo

docker inspect trihouse_p0-fms_gateway-1 \
  --format '{{json .HostConfig.PortBindings}}'
```

PASS:

```text
192.168.0.9:8080 → Gateway
192.168.0.9:8788 → PK_01 TCP
192.168.0.9:8554 → MediaMTX
{"status":"ready","database":"ok"}
```

### C1 — 기존 job 확인

비종료 job이 있으면 C4 worker가 이전 작업을 먼저 처리할 수 있다.

```bash
docker exec trihouse-mysql sh -lc \
  'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" --table -e \
  "SELECT job_id,job_code,state,state_reason_code,created_at \
   FROM trihouse_fms.jobs \
   WHERE state NOT IN (\"completed\",\"cancelled\",\"failed\") \
   ORDER BY job_id"' 2>/dev/null
```

취소할 이전 job을 사람이 확인한 경우에만 ID를 지정한다. 다음 POST는 DB에 취소 이력을
남기고 해당 job의 pending outbox와 자원 할당을 닫는다.

```bash
export STALE_JOB_ID=<취소할_JOB_ID>

curl -fsS -X POST \
  "http://192.168.0.9:8080/internal/v1/jobs/${STALE_JOB_ID}/cancel" \
  -H 'Content-Type: application/json' \
  -H "Idempotency-Key: physical-cleanup-${STALE_JOB_ID}" \
  -d '{"reason":"Cancel stale job before PK_01 VLM-RL collection","requested_by":"W-CONTROL-01"}' \
  | python3 -m json.tool
```

C4를 켜기 전 비종료 job 조회가 빈 결과여야 한다.

### C1 — map revision과 등록 목적지

```bash
export REV=$(docker exec trihouse-mysql sh -lc \
  'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -N -B -e \
  "SELECT map_revision FROM trihouse_fms.map_revisions \
   WHERE state=\"published\" ORDER BY published_at DESC LIMIT 1"' 2>/dev/null)

printf 'REV=%s\n' "$REV"

python3 - "$REV" <<'PY'
import json, pathlib, sys
summary = json.loads(pathlib.Path('.trihouse/p0/summary.json').read_text())
assert summary['map_revision'] == sys.argv[1], (summary['map_revision'], sys.argv[1])
print('PASS: DB revision == local RMF/Nav2 assets')
PY

docker exec trihouse-mysql sh -lc \
  'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" --table -e \
  "SELECT location_id,location_code,rmf_waypoint_name,pose_x,pose_y,pose_yaw,state \
   FROM trihouse_fms.locations \
   WHERE map_name=\"new_map_2\" AND rmf_waypoint_name IS NOT NULL \
   ORDER BY location_id"' 2>/dev/null
```

출력된 `REV` 전체 문자열을 PK_01 운영자에게 전달한다.

## 5. C2 — 4060 RMF core

4060의 새 터미널에서 실행하고 계속 유지한다.

```bash
export TRIHOUSE_ROOT=/path/to/physical-integration-v1
cd "$TRIHOUSE_ROOT"

source /opt/ros/jazzy/setup.bash
source install/setup.bash
source pinky_pro/install/setup.bash

export ROS_DOMAIN_ID=12
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export FASTDDS_BUILTIN_TRANSPORTS=UDPv4

ros2 launch trihouse_rmf_bridge rmf_core.launch.py \
  use_sim_time:=false \
  start_visualization:=false \
  2>&1 | tee /tmp/vlm_dataset_rmf_core.log
```

## 6. C3 — 4060 PK_01 RMF adapter

4060의 새 터미널에서 실행하고 계속 유지한다.

```bash
export TRIHOUSE_ROOT=/path/to/physical-integration-v1
cd "$TRIHOUSE_ROOT"

source /opt/ros/jazzy/setup.bash
source install/setup.bash
source pinky_pro/install/setup.bash

export ROS_DOMAIN_ID=12
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export FASTDDS_BUILTIN_TRANSPORTS=UDPv4

export REV=$(docker exec trihouse-mysql sh -lc \
  'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -N -B -e \
  "SELECT map_revision FROM trihouse_fms.map_revisions \
   WHERE state=\"published\" ORDER BY published_at DESC LIMIT 1"' 2>/dev/null)

ros2 launch trihouse_rmf_bridge pinky_easy_fleet_adapter.launch.py \
  config_file:="$TRIHOUSE_ROOT/trihouse_rmf_bridge/config/pinky_fleet.yaml" \
  nav_graph:="$TRIHOUSE_ROOT/.trihouse/p0/nav_graph.yaml" \
  robot_name:=PK_01 \
  rmf_map_name:=L1 \
  charger_waypoint:=charging_station_01 \
  map_revision:="$REV" \
  fms_base_url:=http://192.168.0.9:8080 \
  robot_status_topic:=/pinky_01/trihouse/status \
  transport_action:=/pinky_01/trihouse/transport/execute \
  use_sim_time:=false \
  2>&1 | tee /tmp/vlm_dataset_adapter_pk01.log
```

## 7. R1 — PK_01 로봇 기동

PK_01에 SSH 접속한 터미널에서 실행하고 계속 유지한다. 아래 map/config 경로가 실제
로봇에 존재하는지 먼저 확인한다.

```bash
export ROBOT_WS=/path/to/pk01/trihouse_ws
cd "$ROBOT_WS"

source /opt/ros/jazzy/setup.bash
source install/setup.bash
source pinky_pro/install/setup.bash

export ROS_DOMAIN_ID=12
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export FASTDDS_BUILTIN_TRANSPORTS=UDPv4

export REV='<C1에서_출력된_전체_map_revision>'

test -f "$ROBOT_WS/maps/new_map_2.yaml"
test -f "$ROBOT_WS/config/hardware_pinky_01.yaml"
test -f "$ROBOT_WS/config/narrow_zones.new_map_2.yaml"
test -f "$ROBOT_WS/config/marker_docks.new_map_2.yaml"
nc -vz 192.168.0.9 8788
```

모두 성공한 후:

```bash
ros2 launch trihouse_pinky_bringup trihouse_pinky.launch.py \
  robot_id:=PK_01 \
  namespace:=pinky_01 \
  map:="$ROBOT_WS/maps/new_map_2.yaml" \
  map_revision:="$REV" \
  nav2_params_file:="$ROBOT_WS/config/hardware_pinky_01.yaml" \
  narrow_zones_file:="$ROBOT_WS/config/narrow_zones.new_map_2.yaml" \
  marker_docks_file:="$ROBOT_WS/config/marker_docks.new_map_2.yaml" \
  narrow_map_name:=new_map_2 \
  control_host:=192.168.0.9 \
  control_port:=8788 \
  vision_enabled:=true \
  docking_enabled:=true \
  2>&1 | tee /tmp/vlm_dataset_pk01.log
```

## 8. R2 — PK_01 안전·상태 확인

PK_01의 새 터미널에서 실행한다.

```bash
export ROBOT_WS=/path/to/pk01/trihouse_ws
cd "$ROBOT_WS"

source /opt/ros/jazzy/setup.bash
source install/setup.bash

export ROS_DOMAIN_ID=12
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export FASTDDS_BUILTIN_TRANSPORTS=UDPv4

ros2 action list | grep -E \
  '/pinky_01/(trihouse/transport/execute|trihouse/recovery/execute|navigate_to_pose)'

ros2 topic info /pinky_01/cmd_vel --verbose
ros2 topic echo --once /pinky_01/trihouse/safety/state
ros2 topic echo --once /pinky_01/trihouse/health
ros2 topic echo --once /pinky_01/trihouse/readiness \
  trihouse_interfaces/msg/Readiness
ros2 topic echo --once /pinky_01/trihouse/vision/stream_health \
  trihouse_interfaces/msg/StreamHealth
```

PASS 조건:

- 세 action이 모두 보인다.
- `/pinky_01/cmd_vel` publisher는 Safety Supervisor 하나다.
- emergency가 아니며 health/readiness가 정상이다.
- camera stream health가 연결 상태다.
- E-stop 담당자가 로봇 옆에 있고 경로가 비어 있다.

## 9. A1 — 별도 5080 PC VLM+RL runtime

5080의 새 터미널에서 실제 clone/worktree 경로를 지정한다.

```bash
export TRIHOUSE_ROOT=/path/to/physical-integration-v1
cd "$TRIHOUSE_ROOT"

curl -fsS http://192.168.0.9:8080/ready
echo
nc -vz 192.168.0.9 8554
```

5080의 `.env`에 다음 값을 설정한다. DB 계정은 넣지 않는다.

```dotenv
FMS_GATEWAY_URL=http://192.168.0.9:8080
VISION_RTSP_URL=rtsp://viewer:<MTX_VIEWER_PASS>@192.168.0.9:8554/pinky/CAM-PK-01
RECOVERY_DEVICE_ID=PK_01

TRIHOUSE_AI_MODEL_DIR=./runtime/ai/models
TRIHOUSE_AI_ARTIFACT_DIR=./runtime/ai/artifacts
TRIHOUSE_AI_QUEUE_DIR=./runtime/ai/recovery_queue
SEGMENTATION_WEIGHTS_FILE=<실제_segmentation_weights_파일명>
RECOVERY_POLICY_CHECKPOINT_FILE=<승인된_policy_checkpoint_파일명>
RECOVERY_POLICY_SHA256=<checkpoint의_64자리_lowercase_SHA256>
VLM_MODEL_REVISION=<승인된_VLM_revision>
```

모델과 checksum을 확인한다.

```bash
export POLICY_FILE=$(grep '^RECOVERY_POLICY_CHECKPOINT_FILE=' .env | cut -d= -f2-)
test -f "runtime/ai/models/$POLICY_FILE"
sha256sum "runtime/ai/models/$POLICY_FILE"
```

checksum이 `.env`와 같을 때만 기동한다.

```bash
docker compose -p trihouse_ai \
  -f compose.ai_5080.yaml config --quiet

docker compose -p trihouse_ai \
  -f compose.ai_5080.yaml up -d --build ai_runtime

docker compose -p trihouse_ai \
  -f compose.ai_5080.yaml exec ai_runtime python -c \
  'import torch; print(torch.version.cuda, torch.cuda.get_device_name(0))'

docker compose -p trihouse_ai \
  -f compose.ai_5080.yaml logs -f ai_runtime
```

A1 로그에 RTSP open, checkpoint, CUDA 오류가 없어야 한다.

## 10. C4 — 4060 RMF Gateway worker

R2와 A1이 PASS한 뒤 4060의 새 터미널에서 실행하고 계속 유지한다.

```bash
export TRIHOUSE_ROOT=/path/to/physical-integration-v1
cd "$TRIHOUSE_ROOT"

source /opt/ros/jazzy/setup.bash
source install/setup.bash
source pinky_pro/install/setup.bash

export ROS_DOMAIN_ID=12
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export FASTDDS_BUILTIN_TRANSPORTS=UDPv4
export PYTHONPATH="$TRIHOUSE_ROOT:${PYTHONPATH:-}"

python3 -m control_tower.rmf_adapter.rmf_gateway_worker_node \
  --fms-base-url http://192.168.0.9:8080 \
  --fleet-name project1_pinky \
  --worker-id trihouse-rmf-worker \
  2>&1 | tee /tmp/vlm_dataset_rmf_worker.log
```

정상 대기 출력:

```text
RMF dispatch cycle: claimed=0 accepted=0 rejected=0 indeterminate=0
```

## 11. C5 — 4060 목적지 job 생성과 자율주행 시작

4060의 새 터미널에서 실행한다.

```bash
export TRIHOUSE_ROOT=/path/to/physical-integration-v1
cd "$TRIHOUSE_ROOT"

source /opt/ros/jazzy/setup.bash
source install/setup.bash
source pinky_pro/install/setup.bash

export ROS_DOMAIN_ID=12
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export FASTDDS_BUILTIN_TRANSPORTS=UDPv4
```

목적지를 조회한다.

```bash
docker exec trihouse-mysql sh -lc \
  'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" --table -e \
  "SELECT location_id,rmf_waypoint_name,pose_x,pose_y,pose_yaw,state \
   FROM trihouse_fms.locations \
   WHERE map_name=\"new_map_2\" AND rmf_waypoint_name IS NOT NULL \
   ORDER BY location_id"' 2>/dev/null
```

이동할 `location_id`를 선택한다.

```bash
export TARGET_LOCATION_ID=<선택한_location_id>
export RUN_ID="vlmrl-pk01-$(date +%Y%m%d-%H%M%S)"
```

단일 navigate job을 생성한다. 이 POST는 DB에 job/step을 추가하지만 아직 로봇 이동을
시작하지 않는다.

```bash
export JOB_REQUEST=$(python3 - "$RUN_ID" "$TARGET_LOCATION_ID" <<'PY'
import json, sys
run_id = sys.argv[1]
target = int(sys.argv[2])
print(json.dumps({
    "job_code": run_id,
    "operation_type": "outbound",
    "priority": "normal",
    "requested_by": "W-CONTROL-01",
    "destination_location_id": target,
    "context": {
        "source": "vlm_rl_dataset_collection",
        "collection_run_id": run_id,
        "device_id": "PK_01"
    },
    "steps": [{
        "step_no": 10,
        "action_type": "navigate",
        "executor_type": "mobile",
        "target_location_id": target,
        "input": {
            "dependencies": [],
            "fleet_name": "project1_pinky"
        }
    }]
}, separators=(",", ":")))
PY
)

export CREATED=$(curl -fsS -X POST \
  http://192.168.0.9:8080/internal/v1/jobs \
  -H 'Content-Type: application/json' \
  -d "$JOB_REQUEST")

echo "$CREATED" | python3 -m json.tool

export JOB_ID=$(echo "$CREATED" | python3 -c \
  'import json,sys; print(json.load(sys.stdin)["job_id"])')
export JOB_STEP_ID=$(echo "$CREATED" | python3 -c \
  'import json,sys; print(json.load(sys.stdin)["steps"][0]["job_step_id"])')

printf 'RUN_ID=%s JOB_ID=%s JOB_STEP_ID=%s\n' \
  "$RUN_ID" "$JOB_ID" "$JOB_STEP_ID"
```

이동 직전 안전 gate:

```bash
python3 scripts/verify_robot_status.py pinky_01 20
ros2 topic info /pinky_01/cmd_vel --verbose
curl -fsS "http://192.168.0.9:8080/api/v1/jobs/$JOB_ID" \
  | python3 -m json.tool
```

E-stop 담당자, 빈 경로, Safety 단독 publisher를 확인한 뒤에만 실행한다. 다음 POST부터
실제 PK_01 자율주행이 시작될 수 있다.

```bash
curl -fsS -X POST \
  "http://192.168.0.9:8080/internal/v1/job-steps/${JOB_STEP_ID}/dispatch" \
  -H 'Content-Type: application/json' \
  -H "Idempotency-Key: dataset-dispatch-${RUN_ID}" \
  -d '{"actor":"W-CONTROL-01","assigned_device_id":"PK_01"}' \
  | python3 -m json.tool
```

PASS 응답:

```text
channel=rmf
message_type=dispatch_task_request
state=pending
```

## 12. C6 — 4060 주행·proposal·DB 관측

4060의 새 터미널에서 C5의 `JOB_ID`를 지정한다.

```bash
export JOB_ID=<C5에서_출력된_JOB_ID>

docker exec trihouse-mysql sh -lc \
  'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" --table -e \
  "SELECT j.job_id,j.state AS job_state,js.job_step_id,js.state AS step_state, \
          js.assigned_device_id,js.rmf_task_id,js.target_location_id \
   FROM trihouse_fms.jobs j \
   JOIN trihouse_fms.job_steps js ON js.job_id=j.job_id \
   WHERE j.job_id='"$JOB_ID"'"' 2>/dev/null
```

주행 중 navigation context 확인:

```bash
curl -fsS \
  http://192.168.0.9:8080/internal/v1/recovery/navigation-context/PK_01 \
  | python3 -m json.tool
```

`robot_pose`, `goal_pose`, `navigation_state`, `map_revision`이 나와야 한다.

열린 proposal 확인:

```bash
export OPEN=$(curl -fsS \
  http://192.168.0.9:8080/internal/v1/recovery/devices/PK_01/open)

echo "$OPEN" | python3 -m json.tool

export PROPOSAL_ID=$(echo "$OPEN" | python3 -c \
  'import json,sys; rows=json.load(sys.stdin); print(rows[0]["proposal"]["proposal_id"] if rows else "")')

printf 'PROPOSAL_ID=%s\n' "$PROPOSAL_ID"
```

정상 주행으로 막힘이 없으면 proposal이 없는 것이 정상이다. proposal이 있으면 evidence,
`selected_skill_name`, `canonical_action`, map revision을 사람이 확인한다. 첫 물리 검증에서는
`WAIT_REOBSERVE`만 승인한다.

다음 승인은 실제 recovery 동작을 발생시킬 수 있다. E-stop과 경로를 재확인한 뒤 실행한다.

```bash
if [ -z "$PROPOSAL_ID" ]; then
  echo '승인할 열린 proposal이 없습니다'
  return 1 2>/dev/null || exit 1
fi

curl -fsS -X POST \
  "http://192.168.0.9:8080/api/v1/recovery/proposals/${PROPOSAL_ID}/decision" \
  -H 'Content-Type: application/json' \
  -d '{"worker_id":"W-CONTROL-01","decision":"approved","reason":"E-stop ready; path clear; PK_01 proposal and map verified"}' \
  | python3 -m json.tool
```

최종 `trihouse_recovery` 적재 확인:

```bash
docker exec trihouse-mysql sh -lc \
  'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" --table -e \
  "SELECT p.proposal_id,p.selected_skill_name,p.status, \
          c.delivery_status,r.execution_status,r.success \
   FROM trihouse_recovery.recovery_proposals p \
   LEFT JOIN trihouse_recovery.recovery_command_outbox c ON c.proposal_id=p.proposal_id \
   LEFT JOIN trihouse_recovery.recovery_execution_results r ON r.command_id=c.command_id \
   ORDER BY p.created_at DESC LIMIT 10; \
   SELECT recovery_step_id,skill_name,reward_total,done,created_at \
   FROM trihouse_recovery.recovery_learning_transitions \
   ORDER BY created_at DESC LIMIT 10;"' 2>/dev/null
```

## 13. C6 — training JSONL export

4060에서 실행한다.

```bash
export TRIHOUSE_ROOT=/path/to/physical-integration-v1
cd "$TRIHOUSE_ROOT"
mkdir -p runtime/ai/data

curl -fsS \
  http://192.168.0.9:8080/internal/v1/recovery/training-export.jsonl \
  -o "runtime/ai/data/recovery-$(date +%Y%m%d-%H%M%S).jsonl"

ls -lh runtime/ai/data/recovery-*.jsonl
```

한 transition은 다음 항목을 포함한다.

```text
state[9], skill, skill_name, coord[3], reward, next_state[9], done, meta
```

## 14. 종료

진행 중 job/recovery가 없을 때 foreground 터미널에서 `Ctrl+C`로 종료한다.

```text
C4 RMF worker
C3 PK_01 adapter
C2 RMF core
R1 PK_01 stack
```

5080:

```bash
export TRIHOUSE_ROOT=/path/to/physical-integration-v1
cd "$TRIHOUSE_ROOT"
docker compose -p trihouse_ai -f compose.ai_5080.yaml stop ai_runtime
```

DB와 녹화 보존을 위해 다음 명령은 사용하지 않는다.

```text
docker compose down -v
scripts/p0_reset.sh
```
