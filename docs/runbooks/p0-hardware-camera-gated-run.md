# P0 실물 촬영용 게이트 런북 — 카메라 송수신 → 1대 → 2대

이 문서는 **앞 단계가 PASS일 때만 다음 단계로 넘어가는** 현장 실행 순서다.
상세한 주문/DB 판정은 [p0-hardware-quick-run.md](p0-hardware-quick-run.md), 코드상
공백의 근거는
[2026-08-20-hardware-readiness-gaps.md](../claude/2026-08-20-hardware-readiness-gaps.md),
영상 구현 위치는
[2026-08-20-video-streaming-implementation-map.md](../claude/2026-08-20-video-streaming-implementation-map.md)를
따른다.

목표 순서는 다음과 같다.

```text
정적 검사 → MediaMTX → PK_01 카메라 송신 → 4060 수신/디코딩
→ 단절/재접속 → 로봇 안전/센서 → 수동 Nav2 → 주문 1건
→ 단일 로봇 3회 → PK_02 카메라 동일 검증 → 주문 2건/로봇 2대
```

## 0. 현재 코드 기준 결론 — 출발 전에 읽는다

아래 항목은 촬영 현장에서 발견할 문제가 아니라 **주행 전에 해결하고 확인할 문제**다.

| ID | 현재 상태 | 판정 |
|---|---|---|
| B1 | `trihouse_pinky.launch.py`의 `GroupAction` 안 `SetRemap(cmd_vel → cmd_vel_nav)`가 safety 노드에도 적용된다. 코드 주석과 실제 scope가 다르다 | 모터 입력 토픽의 유일한 publisher가 safety인지 실기에서 확인 전 **자율 주행 금지** |
| B2 | `config/narrow_zones.new_map_2.yaml`이 없다 | 협로/도크가 포함된 출고 주행 **금지** |
| B3 | `trihouse_pinky_vision/config/pinky_2.yaml`이 없다. PK_01 설정을 PK_02에 쓰면 둘 다 `CAM-PK-01` 경로로 publish한다 | PK_02 카메라 설정 추가·검증 전 **2대 촬영 금지** |
| B4 | PK_01 설정의 MediaMTX 주소가 `192.168.0.9`로 추적돼 있다 | 실제 `PC1_LAN_IP`와 다르면 설정 수정·재빌드 전 송신 불가 |
| B5 | `scripts/camera_soak_test.py`의 실제 sampler는 아직 placeholder다 | 이 스크립트로 30분 실측 완료를 주장할 수 없음. 아래 `verify_rtsp.sh`로 스트림별 연속 디코딩을 남긴다 |
| B6 | 원격 영상 UI와 5080 AI image entrypoint는 완성 상태가 아니다 | 촬영 영상 확인은 `ffplay`, 기술 판정은 `ffprobe`/`ffmpeg`로 한다 |
| B7 | `p0_runtime_assets.py`가 아직 RMF가 읽지 않는 `mutex_group:` 키를 출력한다 | 출력 코드가 `mutex:`를 만들고 생성된 graph로 확인하기 전 **2대 협로 주행 금지** |
| B8 | 기존 실측 문서에는 협로 규칙 주행 중 RMF step 20 취소가 재현돼 있다 | 현재 코드로 시뮬 주문 1건이 step 20을 넘어 완주한다는 재검증 전 **실기 주문 금지** |

**오늘의 최소 촬영선:** PK_01 카메라 양방향 확인 + 안전 게이트 PASS + 수동 Nav2
목표 1회 + 주문 1건 완주. B1 또는 B2가 FAIL이면 바퀴를 띄운 상태의 카메라/노드
촬영까지만 하고 자율 주행 장면은 찍지 않는다.

## 1. 공통 규칙과 터미널 배치

- 실기 ROS domain은 모든 장비에서 `52`다. 시뮬 domain과 섞지 않는다.
- `<PC1_IP>`, `<PK_01_IP>`, `<PK_02_IP>`, `<REV>`, `<실측x>` 같은 표기는 실제값으로
  바꾼다. 꺾쇠를 포함한 채 실행하지 않는다.
- 로봇 주행 중 한 사람은 물리 E-stop만 담당한다.
- 모든 셸은 명령 실행 전 `date -Is`를 남긴다. 촬영 영상과 로그 시각을 맞추기 위해서다.

| 터미널 | 호스트 | 역할 |
|---|---|---|
| C1 | 4060 | Docker, Gateway, MediaMTX |
| C2 | 4060 | RMF core와 adapter/worker |
| C3 | 4060 | RTSP 수신 검증과 화면 |
| C4 | 4060 | 주문, DB 상태, mutex 관측 |
| R1 | PK_01 | 통합 bringup + 카메라 송신 |
| R2 | PK_01 | 센서, safety, StreamHealth 검사 |
| R3/R4 | PK_02 | 2대 단계에서 R1/R2와 동일 |

모든 ROS 셸에서:

```bash
export ROS_DOMAIN_ID=52
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export FASTDDS_BUILTIN_TRANSPORTS=UDPv4
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
source /opt/ros/jazzy/setup.bash
```

4060에서는 이어서:

```bash
cd /home/newuser/Trihouse
source pinky_pro/install/setup.bash
source install/setup.bash
export PYTHONPATH="/home/newuser/Trihouse:${PYTHONPATH:-}"
```

로봇에서는 이어서:

```bash
source ~/trihouse_ws/install/setup.bash
```

## Gate 1. 정적 검사와 실제 주소 확정

4060에서 저장소 파일과 설치본을 먼저 확인한다.

```bash
cd /home/newuser/Trihouse
test -f .env
test -f config/narrow_zones.new_map_2.yaml
test -f trihouse_pinky/trihouse_pinky_vision/config/pinky_1.yaml
test -f trihouse_pinky/trihouse_pinky_vision/config/pinky_2.yaml
```

현재 저장소에서는 뒤의 두 `test` 중 `pinky_2.yaml`과 narrow-zone 검사가 실패하는 것이
예상된다. 실패한 항목은 만들고 정적 테스트를 통과시킨 뒤에만 계속한다.

비밀번호를 출력하지 않고 `.env` 필수값이 비어 있거나 예시값인지 확인한다.

```bash
python3 - <<'PY'
from pathlib import Path

required = (
    'PC1_LAN_IP', 'EDGE_BIND_ADDRESS', 'FMS_TCP_BIND',
    'PINKY_PK_01_IP', 'PINKY_PK_02_IP',
    'OMX_PC_01_IP', 'OMX_PC_02_IP', 'PC1_PUBLISHER_IP', 'MTX_VIEWER_PASS',
)
values = {}
for line in Path('.env').read_text().splitlines():
    if line and not line.lstrip().startswith('#') and '=' in line:
        key, value = line.split('=', 1)
        values[key] = value.strip()
for key in required:
    value = values.get(key, '')
    bad = not value or 'change_me' in value or value.startswith('192.0.2.')
    print(f'{key}: {"FAIL" if bad else "SET"}')
PY
```

PK_01/PK_02의 vision YAML에서 `publish_uri`가 실제 4060 Ethernet 주소와 각자의 경로를
가리키는지 확인한다. 비밀번호는 publish URL에 넣지 않는다.

```bash
grep -E 'camera_id:|publish_uri:' \
  trihouse_pinky/trihouse_pinky_vision/config/pinky_1.yaml \
  trihouse_pinky/trihouse_pinky_vision/config/pinky_2.yaml
```

기대값:

```text
PK_01: CAM-PK-01, rtsp://<PC1_IP>:8554/pinky/CAM-PK-01
PK_02: CAM-PK-02, rtsp://<PC1_IP>:8554/pinky/CAM-PK-02
```

카메라 및 launch 계약 테스트:

```bash
source /opt/ros/jazzy/setup.bash
source pinky_pro/install/setup.bash
source install/setup.bash
export ROS_LOG_DIR=/tmp/trihouse-ros-test-logs
pytest -q \
  tests/test_camera_registry.py \
  tests/test_camera_publisher_allowlist.py \
  tests/test_stream_path_consistency.py \
  model/worker/tests/test_vision_compose_contract.py \
  trihouse_pinky/trihouse_pinky_vision/test/test_command_builder.py \
  trihouse_pinky/trihouse_pinky_vision/test/test_verify_rtsp_script.py \
  trihouse_pinky/trihouse_pinky_bringup/test/test_trihouse_pinky_launch.py
```

**PASS:** 필수 파일 4개 존재, 주소/ID가 장비별로 일치, pytest 모두 통과.

## Gate 2. 4060 Docker와 MediaMTX

C1에서:

```bash
cd /home/newuser/Trihouse
docker compose -p trihouse_p0 \
  -f compose.yaml -f compose.control.yaml -f compose.edge_4060.yaml \
  config --quiet
```

```bash
docker compose -p trihouse_p0 \
  -f compose.yaml -f compose.control.yaml -f compose.edge_4060.yaml \
  up -d
```

```bash
docker compose -p trihouse_p0 \
  -f compose.yaml -f compose.control.yaml -f compose.edge_4060.yaml ps
until curl -fsS -m 2 http://127.0.0.1:8080/ready; do sleep 3; done
curl -fsS http://127.0.0.1:9997/v3/paths/list | python3 -m json.tool
curl -fsS http://127.0.0.1:9998/metrics | grep -E 'paths|readers|publishers' || true
ss -lnt | grep -E ':8080|:8554|:8788|:9997'
```

MediaMTX 컨테이너 이름은 Compose가 결정하므로 하드코딩하지 않는다.

```bash
docker compose -p trihouse_p0 \
  -f compose.yaml -f compose.control.yaml -f compose.edge_4060.yaml \
  logs --tail=100 mediamtx
```

**PASS:** Gateway가 `database: ok`, MediaMTX API가 JSON 반환, 8554/tcp가 실제
`PC1_LAN_IP`에 열림, MediaMTX 로그에 설정/인가 오류 없음.

## Gate 3. PK_01 카메라 송신

먼저 PK_01에서 장비와 서버 연결을 확인한다. 이 단계에서는 바퀴를 띄우거나 E-stop을
누른 상태로 진행해도 된다.

```bash
date -Is
test -x /usr/local/bin/rpicam-vid
test -x /usr/bin/ffmpeg
rpicam-vid --list-cameras
nc -zv <PC1_IP> 8554
```

R1에서 통합 launch를 카메라와 함께 실행한다. PK_01용 설정을 명시해 설치본의 기본값에
의존하지 않는다.

```bash
ros2 launch trihouse_pinky_bringup trihouse_pinky.launch.py \
  robot_id:=PK_01 namespace:=pinky_01 \
  map:=$HOME/maps/new_map_2.yaml map_revision:="<REV>" \
  nav2_params_file:=$HOME/hardware_pinky_01.yaml \
  control_host:=<PC1_IP> control_port:=8788 \
  vision_enabled:=true \
  vision_config_file:=$(ros2 pkg prefix --share trihouse_pinky_vision)/config/pinky_1.yaml \
  2>&1 | tee /tmp/hw_pk01.log
```

R2에서:

```bash
ros2 topic echo --once /pinky_01/trihouse/vision/stream_health \
  trihouse_interfaces/msg/StreamHealth
pgrep -af 'rpicam-vid|ffmpeg'
```

**PASS:** `camera_id: CAM-PK-01`, `state: 1`, FPS가 15 근처, bitrate가 0보다 큼,
`rpicam-vid`와 `ffmpeg`가 각각 한 파이프라인만 존재.

`state: 3`이면 다음 순서로만 조사한다.

```bash
nc -zv <PC1_IP> 8554
grep -aEi 'camera|ffmpeg|rpicam|disconnect|restart|error' /tmp/hw_pk01.log | tail -50
```

C1에서:

```bash
docker compose -p trihouse_p0 \
  -f compose.yaml -f compose.control.yaml -f compose.edge_4060.yaml \
  logs --tail=100 mediamtx | grep -Ei 'CAM-PK-01|publish|auth|error'
```

## Gate 4. 4060 수신, 실제 디코딩, 화면 확인

C3에서 read 자격 증명이 들어간 URL을 셸 변수로 만든다. 명령 자체를 영상에 크게 띄우면
비밀번호가 촬영되므로 URL은 화면 공유 전에 입력한다.

```bash
cd /home/newuser/Trihouse
set -a
source .env
set +a
export PK01_RTSP="rtsp://viewer:${MTX_VIEWER_PASS}@${PC1_LAN_IP}:8554/pinky/CAM-PK-01"
```

메타데이터와 60초 연속 디코딩을 확인하고 로그를 남긴다.

```bash
mkdir -p runtime/validation
date -Is | tee runtime/validation/pk01-camera-start.txt
trihouse_pinky/trihouse_pinky_vision/scripts/verify_rtsp.sh \
  "$PK01_RTSP" 60 2>&1 | tee runtime/validation/pk01-rtsp-60s.log
```

기대값은 `codec_name=h264`, `width=1280`, `height=720`, `avg_frame_rate=15/1`,
FFmpeg 종료 코드 0이다.

실제 프레임 한 장의 해시도 남긴다.

```bash
timeout 15 ffmpeg -nostdin -v error -rtsp_transport tcp -i "$PK01_RTSP" \
  -map 0:v:0 -frames:v 1 -f framemd5 - \
  | tee runtime/validation/pk01-frame.md5
```

촬영 구도/방향/지연은 사람이 화면으로 확인한다.

```bash
ffplay -fflags nobuffer -flags low_delay -rtsp_transport tcp "$PK01_RTSP"
```

동시에 MediaMTX 녹화 segment가 생성되는지 확인한다.

```bash
find runtime/video/pinky/CAM-PK-01 -type f -mmin -5 -printf '%TY-%Tm-%Td %TH:%TM:%TS %s %p\n' | tail
```

**PASS:** 60초 decode 오류 0, 한 프레임 MD5 출력, 사람이 움직이는 장면/방향 확인,
최근 녹화 파일 크기 증가.

## Gate 5. 단절 감지와 자동 재접속

로봇 launch는 그대로 두고 C1에서 MediaMTX만 잠시 멈춰 네트워크 장애를 재현한다.

```bash
docker compose -p trihouse_p0 \
  -f compose.yaml -f compose.control.yaml -f compose.edge_4060.yaml \
  stop mediamtx
```

R2에서 10초 동안 상태를 본다.

```bash
timeout 10 ros2 topic echo /pinky_01/trihouse/vision/stream_health \
  trihouse_interfaces/msg/StreamHealth
```

3초 안팎 뒤 `state: 3`(DISCONNECTED)이 관측돼야 한다. C1에서 서버를 복구한다.

```bash
docker compose -p trihouse_p0 \
  -f compose.yaml -f compose.control.yaml -f compose.edge_4060.yaml \
  start mediamtx
```

R2에서 `state: 4`(RECOVERING)를 거쳐 최소 5초 연속 프레임 뒤 `state: 1`이 되는지 본다.

```bash
timeout 45 ros2 topic echo /pinky_01/trihouse/vision/stream_health \
  trihouse_interfaces/msg/StreamHealth
```

C3에서 다시 30초 디코딩한다.

```bash
trihouse_pinky/trihouse_pinky_vision/scripts/verify_rtsp.sh \
  "$PK01_RTSP" 30 2>&1 | tee runtime/validation/pk01-rtsp-after-reconnect.log
```

**PASS:** `3 → 4 → 1` 상태 전이와 복구 후 decode 오류 0. 이 확인 전에는 주문을 넣지 않는다.

## Gate 6. 로봇 안전, 센서, 위치추정

R2에서 위에서 아래 순서로 실행한다.

```bash
grep -c 'Managed nodes are active' /tmp/hw_pk01.log
grep -E 'Failed to bring up all requested|Failed to change state' /tmp/hw_pk01.log
```

첫 출력은 2, 둘째는 빈 출력이어야 한다.

```bash
ros2 topic echo --once /pinky_01/scan sensor_msgs/msg/LaserScan | head -5
ros2 topic echo --once /pinky_01/odom nav_msgs/msg/Odometry | head -5
ros2 topic echo --once /pinky_01/trihouse/battery sensor_msgs/msg/BatteryState | head -5
ros2 topic echo --once /pinky_01/trihouse/readiness trihouse_interfaces/msg/Readiness
```

모터가 실제로 구독하는 토픽을 먼저 식별하고 verbose 정보를 저장한다.

```bash
ros2 topic list | grep -E '/pinky_01/(cmd_vel|cmd_vel_nav|cmd_vel_motor)$'
ros2 topic info /pinky_01/cmd_vel --verbose | tee /tmp/pk01-cmd-vel-info.txt
```

**PASS 조건은 “모터 입력 토픽의 publisher가 정확히 1개이며 그 노드가
`safety_supervisor`”다.** `/cmd_vel`의 개수만 보고 판단하지 말고 실제 모터 드라이버의
subscription과 연결된 토픽을 `--verbose` 결과로 확인한다. 2개 이상이거나 safety가
아니면 즉시 E-stop을 유지하고 주행하지 않는다.

초기 pose를 실제 충전 위치로 준다.

```bash
ros2 topic pub --once /pinky_01/initialpose \
  geometry_msgs/msg/PoseWithCovarianceStamped \
  '{header: {frame_id: "map"}, pose: {pose: {position: {x: <실측x>, y: <실측y>, z: 0.0}, orientation: {z: <실측z>, w: <실측w>}}}}'
```

4060 C4에서:

```bash
cd /home/newuser/Trihouse
source /opt/ros/jazzy/setup.bash
source pinky_pro/install/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=52
python3 scripts/verify_robot_status.py pinky_01 20
```

**PASS:** publisher 전부 1, `frame_id=map`, `dispatchable=true`, `errors=[]`, readiness의
missing interface가 비어 있음, B2의 narrow-zone 파일 존재.

## Gate 7. 주문 전 수동 Nav2 왕복

사람과 장애물을 치우고 E-stop 담당자가 준비된 뒤 짧고 넓은 구간의 실측 좌표로 먼저
왕복한다. 협로와 도크는 아직 사용하지 않는다.

```bash
ros2 action send_goal /pinky_01/navigate_to_pose nav2_msgs/action/NavigateToPose \
  '{pose: {header: {frame_id: "map"}, pose: {position: {x: <안전목표x>, y: <안전목표y>, z: 0.0}, orientation: {w: 1.0}}}}' \
  --feedback
```

카메라 화면을 동시에 열어 둔다.

```bash
ffplay -fflags nobuffer -flags low_delay -rtsp_transport tcp "$PK01_RTSP"
```

**PASS:** action `SUCCEEDED`, 로봇 정지, 영상이 주행 내내 멈추지 않음, 주행 뒤
`StreamHealth state=1`. 같은 방법으로 시작점에 복귀까지 성공해야 한다.

## Gate 8. 4060 관제 ROS 층과 주문 1건

Gate 1~7이 모두 PASS일 때만 수행한다. 지도 발행과 `REV`, nav graph 생성은
[p0-hardware-quick-run.md의 2부](p0-hardware-quick-run.md#2부-매-회차--4060-관제-층)를
그대로 실행한다. 생성물에 mutex 키가 있는지 확인한다.

```bash
grep -A1 'BOTTLENECK' .trihouse/p0/nav_graph.yaml | grep -E 'mutex:'
```

C2에서 순서대로 시작한다.

```bash
ros2 launch trihouse_rmf_bridge rmf_core.launch.py \
  use_sim_time:=false start_visualization:=false \
  > /tmp/hw_rmf_core.log 2>&1 &
sleep 5
```

```bash
ros2 launch trihouse_rmf_bridge pinky_easy_fleet_adapter.launch.py \
  nav_graph:=/home/newuser/Trihouse/.trihouse/p0/nav_graph.yaml \
  robot_name:=PK_01 rmf_map_name:=L1 charger_waypoint:=charging_station_01 \
  map_revision:="$REV" fms_base_url:=http://127.0.0.1:8080 \
  robot_status_topic:=/pinky_01/trihouse/status \
  transport_action:=/pinky_01/trihouse/transport/execute \
  use_sim_time:=false > /tmp/hw_adapter_pk01.log 2>&1 &
```

```bash
python3 -m control_tower.task_manager.job_runner_node \
  --fms-base-url http://127.0.0.1:8080 > /tmp/hw_job_runner.log 2>&1 &
python3 -m control_tower.task_manager.executor_worker_node \
  --fms-base-url http://127.0.0.1:8080 --environment hardware \
  --act-config /home/newuser/Trihouse/config/act.simulation.yaml \
  > /tmp/hw_executor.log 2>&1 &
python3 -m control_tower.rmf_adapter.rmf_gateway_worker_node \
  --fms-base-url http://127.0.0.1:8080 --fleet-name project1_pinky \
  --worker-id trihouse-rmf-worker > /tmp/hw_rmf_worker.log 2>&1 &
```

주문 직전 마지막 확인:

```bash
python3 scripts/verify_robot_status.py pinky_01 20
ros2 topic echo --once /pinky_01/trihouse/vision/stream_health \
  trihouse_interfaces/msg/StreamHealth
```

둘 다 PASS면 C4에서 주문한다.

```bash
ORDER=$(curl -fsS -X POST http://127.0.0.1:8080/api/v1/orders \
  -H 'Content-Type: application/json' \
  -H "Idempotency-Key: hw-film-$(date +%s)" \
  -d '{"requested_by":"W-OP-01","priority":"normal","items":[{"product_code":"SKU-DUMPLING","quantity":1}]}')
echo "$ORDER" | python3 -m json.tool
export JOB=$(echo "$ORDER" | python3 -c 'import json,sys; print(json.load(sys.stdin)["job_id"])')
```

진행 중에는 DB와 카메라 health를 별도 터미널에서 계속 본다.

```bash
watch -n2 'docker exec trihouse-mysql mysql -uroot -p"$(grep -E "^MYSQL_ROOT_PASSWORD=" /home/newuser/Trihouse/.env | cut -d= -f2-)" --table -e "SELECT step_no,executor_type,action_type,state,final_outcome_reason_code FROM trihouse_fms.job_steps WHERE job_id='"$JOB"' ORDER BY step_no;" 2>/dev/null'
```

```bash
ros2 topic echo /pinky_01/trihouse/vision/stream_health \
  trihouse_interfaces/msg/StreamHealth
```

step 60에서는 기존 런북의 worker-completion 호출이 반드시 필요하다. 완료 판정은 job이
`completed`, 7개 step이 모두 `succeeded`, 카메라가 주행 전 구간에서 `state=1`인 것이다.

## Gate 9. 단일 로봇 3회

초기화하지 않고 아래 순서로 한 건씩 수행한다.

1. `SKU-DUMPLING` (frozen)
2. `SKU-YOGURT` (chilled)
3. `SKU-ORANGE` (ambient)

각 회차의 시작과 끝에서 다음 네 가지를 저장한다.

```bash
date -Is
python3 scripts/verify_robot_status.py pinky_01 20
ros2 topic echo --once /pinky_01/trihouse/vision/stream_health \
  trihouse_interfaces/msg/StreamHealth
trihouse_pinky/trihouse_pinky_vision/scripts/verify_rtsp.sh "$PK01_RTSP" 30
```

**PASS:** 세 job 모두 완주하고 세 회차 모두 카메라 송수신/디코딩 PASS. 한 번이라도
DISCONNECTED 또는 decode error가 있으면 해당 회차는 촬영 성공 횟수로 세지 않는다.

## Gate 10. PK_02 카메라와 로봇

Gate 9가 끝나고 `pinky_2.yaml`이 Gate 1을 통과한 뒤에만 시작한다. PK_02에서 PK_01과
동일하게 Gate 3~7을 반복하되 다음 값만 바꾼다.

```text
robot_id             PK_02
namespace            pinky_02
nav2 params          $HOME/hardware_pinky_02.yaml
vision config        .../config/pinky_2.yaml
camera_id            CAM-PK-02
RTSP path            pinky/CAM-PK-02
charger              charging_station_02
```

C3에서:

```bash
export PK02_RTSP="rtsp://viewer:${MTX_VIEWER_PASS}@${PC1_LAN_IP}:8554/pinky/CAM-PK-02"
trihouse_pinky/trihouse_pinky_vision/scripts/verify_rtsp.sh \
  "$PK02_RTSP" 60 2>&1 | tee runtime/validation/pk02-rtsp-60s.log
```

**PASS:** 두 로봇의 StreamHealth가 각각 자기 camera ID로 `state=1`, 두 URL이 동시에
60초 decode, 화면을 가렸을 때 서로 다른 로봇 영상임을 사람이 확인.

## Gate 11. 로봇 2대, 주문 2건

두 로봇 모두 Gate 6~7을 통과하고 nav graph의 `mutex:`를 확인한 뒤 PK_02 adapter를
추가한다.

```bash
ros2 launch trihouse_rmf_bridge pinky_easy_fleet_adapter.launch.py \
  nav_graph:=/home/newuser/Trihouse/.trihouse/p0/nav_graph.yaml \
  robot_name:=PK_02 rmf_map_name:=L1 charger_waypoint:=charging_station_02 \
  map_revision:="$REV" fms_base_url:=http://127.0.0.1:8080 \
  robot_status_topic:=/pinky_02/trihouse/status \
  transport_action:=/pinky_02/trihouse/transport/execute \
  use_sim_time:=false > /tmp/hw_adapter_pk02.log 2>&1 &
```

```bash
python3 scripts/verify_robot_status.py pinky_01 20
python3 scripts/verify_robot_status.py pinky_02 20
```

둘 다 PASS면 서로 다른 온도 구역 주문을 넣는다.

```bash
for sku in SKU-ICEBAR SKU-MILK; do
  curl -fsS -X POST http://127.0.0.1:8080/api/v1/orders \
    -H 'Content-Type: application/json' \
    -H "Idempotency-Key: hw2-${sku}-$(date +%s%N)" \
    -d "{\"requested_by\":\"W-OP-01\",\"priority\":\"normal\",\"items\":[{\"product_code\":\"${sku}\",\"quantity\":1}]}" \
    | python3 -m json.tool
done
```

관측 터미널:

```bash
ros2 topic echo /mutex_group_states rmf_fleet_msgs/msg/MutexGroupStates
```

```bash
ffplay -fflags nobuffer -flags low_delay -rtsp_transport tcp "$PK01_RTSP"
ffplay -fflags nobuffer -flags low_delay -rtsp_transport tcp "$PK02_RTSP"
```

**PASS:** 두 job이 서로 다른 로봇에 배정, 병목에서 한 로봇만 mutex 보유, 두 job 모두
완주, 두 카메라 모두 전 구간 `state=1` 및 decode 유지.

## 실패 시 즉시 정지 순서

1. 물리 E-stop을 누른다.
2. 새 주문을 넣지 않는다.
3. `JOB`, 시각, StreamHealth, 로봇 status, 관련 로그를 저장한다.
4. 원인을 확인하기 전 launch를 무작정 재기동하지 않는다. 중복 publisher가 생길 수 있다.

4060 로그:

```bash
for f in /tmp/hw_rmf_core.log /tmp/hw_adapter_pk01.log /tmp/hw_adapter_pk02.log \
  /tmp/hw_job_runner.log /tmp/hw_executor.log /tmp/hw_rmf_worker.log; do
  test -f "$f" || continue
  echo "== $f"
  grep -aE '\[(ERROR|WARN)\]|Traceback' "$f" | tail -20
done
```

로봇 로그:

```bash
grep -aEi '\[(ERROR|WARN)\]|camera|ffmpeg|disconnect|restart' /tmp/hw_pk01.log | tail -50
```

MediaMTX 로그:

```bash
docker compose -p trihouse_p0 \
  -f compose.yaml -f compose.control.yaml -f compose.edge_4060.yaml \
  logs --since=10m mediamtx | tee runtime/validation/mediamtx-last-10m.log
```

## 정상 종료

먼저 로봇 launch를 각 로봇에서 `Ctrl-C`로 종료하고 Nav2 lifecycle 종료를 기다린다.
그 다음 4060의 ROS 프로세스를 자신이 실행한 셸에서 종료한다. 마지막으로 Docker를 내린다.

```bash
cd /home/newuser/Trihouse
docker compose -p trihouse_p0 \
  -f compose.yaml -f compose.control.yaml -f compose.edge_4060.yaml down
```

영상 보존이 필요하면 `down -v`를 쓰지 않는다. `runtime/video`와
`runtime/validation`을 촬영 날짜별 디렉터리로 복사한 뒤 파일 수와 용량을 기록한다.
