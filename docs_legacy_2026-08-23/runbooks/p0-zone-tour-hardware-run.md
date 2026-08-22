# P0 실물 세 구역 순회 주행 (`상온 → 냉장 → 냉동 → 충전소`)

기준은 `PK_01`, namespace `pinky_01`, 지도 `new_map_2`, 실기 `ROS_DOMAIN_ID` **12**다.
확인하려는 것은 하나다. **주문 한 건으로 한 대의 Pinky가 상온·냉장·냉동 도크를 한
번씩 들르고 포장 도크를 거쳐 충전소로 돌아오는가.**

테스트 코드는 다음 두 파일이다.

| 파일 | 역할 |
|---|---|
| `tests/hardware/test_zone_tour_full_stack.py` | 주행 gate·완주 판정 계약, opt-in 실기 순회 테스트 |
| `tests/hardware/zone_tour_client.py` | 주문 생성·진행 관측·작업자 확인·증거 기록 |
| `config/narrow_zones.new_map_2.zone_tour.yaml` | 도킹 없이 waypoint까지만 가는 순회 전용 협로 표 |

주문 한 건은 아래 13 step이 모두 `succeeded`이고 job이 `completed`여야 완주다.
`temperature_zone`은 step 번호가 아니라 각 step의 `input`이 정한다.

```text
10  arm/prepare     상온 물건 준비(사람이 바구니에 올린다)
20  mobile/navigate 상온 도크로 이동
30  fms/load        상온 적재 gate
40  arm/prepare     냉장 물건 준비
50  mobile/navigate 냉장 도크로 이동
60  fms/load        냉장 적재 gate
70  arm/prepare     냉동 물건 준비
80  mobile/navigate 냉동 도크로 이동
90  fms/load        냉동 적재 gate
100 mobile/navigate 포장 도크로 이동
110 fms/handover    인계 처리
120 fms/wait        작업자 완료 확인(테스트가 대신 호출)
130 mobile/return_home 충전소 복귀
```

---

## 0. 이 시험의 범위와 한계

**이번 순회는 창고 도크 waypoint까지만 간다. 선반 안쪽으로 후진 도킹하지 않는다.**

`config/narrow_zones.new_map_2.yaml`(운영 표)에서 상온·냉장은 `enabled: false`,
냉동은 `measured.exit: false`다. 즉 세 창고 모두 협로 규칙 실행 조건을 아직
만족하지 않으며, 그 상태로 이동 명령을 보내면 fleet가
`NARROW_PROFILE_DISABLED` / `NARROW_PROFILE_UNMEASURED`로 **정상적으로 거절한다.**

그래서 이 순회는 `config/narrow_zones.new_map_2.zone_tour.yaml`을 쓴다. 세 창고를
`approach_required: false`로 두어 Nav2가 실측 도크 waypoint까지만 가고 규칙 주행과
ArUco 도킹은 아예 실행되지 않는다. 충전소 두 곳의 탈출 규칙은 운영 표와 같은
실측값을 유지한다(그게 없으면 로봇이 충전 베이를 빠져나오지 못한다).

도킹까지 포함한 순회는 `docs/runbooks/p0-hardware-quick-run.md`의 3-5절 절차로
창고를 한 곳씩 실측해 `verified: true` + `enabled: true`로 바꾼 뒤,
`--narrow-zones-file config/narrow_zones.new_map_2.yaml`로 같은 테스트를 돌린다.
그때 gate는 자동으로 `narrow_dock` 경로를 요구한다.

## 0-1. 착수 gate

- `docs/runbooks/p0-hardware-quick-run.md` 1~2절이 끝나 new_map_2 실측 waypoint가
  JSONL에 반영되고 지도 revision이 발행돼 있다.
- `python3 scripts/p0_show_map.py new_map_2`에서 세 창고 도크가 모두 통과 가능하다.
- `python3 scripts/verify_robot_status.py pinky_01 20`이 `RESULT: PASS`다.
- `/pinky_01/cmd_vel` 발행자는 `safety_supervisor` 하나뿐이다.
- 물리 비상정지를 손에 잡고, 처음 한 바퀴는 최저 속도로 돈다.
- 세 창고 도크 앞에 사람이 서서 물건을 올릴 수 있다.

---

## 1. 터미널 배치

| 창 | 위치 | 프로세스 |
|---|---|---|
| C1 | 4060 | Docker/FMS |
| C2 | 4060 | RMF core |
| C3 | 4060 | PK_01 fleet adapter |
| C4 | 4060 | job runner |
| C5 | 4060 | executor worker |
| C6 | 4060 | RMF gateway worker |
| C7 | 4060 | OMX_01·OMX_02 무동작 Action 서버 |
| C8 | 4060 | 순회 테스트 실행 |
| C9 | 4060 | DB 진행 관측 |
| R1 | 로봇 | Pinky/Nav2 launch |
| R2 | 로봇 | 센서·안전 확인과 초기 pose |

### C2~C9 공통 환경

각 새 셸에서 먼저 실행한다.

```bash
cd /home/syw/Trihouse
source /opt/ros/jazzy/setup.bash
source install/setup.bash
source pinky_pro/install/setup.bash
export ROS_DOMAIN_ID=12
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export FASTDDS_BUILTIN_TRANSPORTS=UDPv4
export PYTHONPATH="/home/syw/Trihouse:$PYTHONPATH"
export MYSQL_PW="$(grep -E '^MYSQL_ROOT_PASSWORD=' .env | cut -d= -f2-)"
export REV=$(docker exec trihouse-mysql mysql -uroot -p"$MYSQL_PW" \
  -N -B -e "SELECT map_revision FROM trihouse_fms.map_revisions WHERE state='published' ORDER BY published_at DESC LIMIT 1;" 2>/dev/null)
echo "REV=$REV"
```

---

## 2. 터미널별 명령

### C1 — Docker/FMS

```bash
cd /home/syw/Trihouse
docker compose -p trihouse_p0 \
  -f compose.yaml -f compose.control.yaml -f compose.edge_4060.yaml up -d
until curl -fsS -m 2 http://127.0.0.1:8080/ready; do sleep 3; done; echo
```

순회 주문은 세 구역 재고를 하나씩 예약한다. 앞선 회차가 재고를 소진했으면 다시
seed한다(`ON DUPLICATE KEY UPDATE`라 수량만 원복된다).

```bash
docker exec -i trihouse-mysql mysql -uroot -p"$MYSQL_PW" trihouse_fms \
  < db/seeds/seed_hardware.sql
docker exec trihouse-mysql mysql -uroot -p"$MYSQL_PW" --table -e \
  "SELECT product_code,temperature_zone,available_qty,reserved_qty,state
     FROM trihouse_fms.inventory_lots
    WHERE product_code IN ('SKU-MANDARIN','SKU-YOGURT','SKU-ICEBAR');"
```

**팔이 없는 이동 시험 전용 조치.** 실기 seed는 heartbeat 없이 어떤 장비도 배차
가능으로 만들지 않는다. OMX 두 대에는 아직 상태 보고 경로가 없으므로, 그대로 두면
job runner가 `no free robot, arm, or dock`으로 배정을 멈춘다. 이 시험 동안만
두 팔을 `idle/ok`로 등록한다. 실제 팔을 붙일 때는 이 행을 지우고 실제 heartbeat를 쓴다.

```bash
docker exec trihouse-mysql mysql -uroot -p"$MYSQL_PW" -e \
  "INSERT INTO trihouse_fms.device_states
     (device_id, observed_at, state, health, battery_pct, progress, details)
   VALUES ('OMX_01', NOW(6), 'idle', 'ok', NULL, 0.0000,
           JSON_OBJECT('source','zone_tour_drive_test')),
          ('OMX_02', NOW(6), 'idle', 'ok', NULL, 0.0000,
           JSON_OBJECT('source','zone_tour_drive_test'))
   ON DUPLICATE KEY UPDATE observed_at=VALUES(observed_at), state=VALUES(state),
     health=VALUES(health), details=VALUES(details);"
```

### C2 — RMF core

```bash
ros2 launch trihouse_rmf_bridge rmf_core.launch.py \
  use_sim_time:=false start_visualization:=false \
  2>&1 | tee /tmp/tour_rmf_core.log
```

### C3 — PK_01 fleet adapter

```bash
ros2 launch trihouse_rmf_bridge pinky_easy_fleet_adapter.launch.py \
  nav_graph:=/home/syw/Trihouse/.trihouse/p0/nav_graph.yaml \
  robot_name:=PK_01 rmf_map_name:=L1 \
  charger_waypoint:=charging_station_01 \
  map_revision:="$REV" fms_base_url:=http://127.0.0.1:8080 \
  robot_status_topic:=/pinky_01/trihouse/status \
  transport_action:=/pinky_01/trihouse/transport/execute \
  use_sim_time:=false 2>&1 | tee /tmp/tour_adapter_pk01.log
```

### C4 — job runner

```bash
python3 -m control_tower.task_manager.job_runner_node \
  --fms-base-url http://127.0.0.1:8080 2>&1 | tee /tmp/tour_job_runner.log
```

### C5 — executor worker

```bash
python3 -m control_tower.task_manager.executor_worker_node \
  --fms-base-url http://127.0.0.1:8080 --environment hardware \
  2>&1 | tee /tmp/tour_executor.log
```

### C6 — RMF gateway worker

```bash
python3 -m control_tower.rmf_adapter.rmf_gateway_worker_node \
  --fms-base-url http://127.0.0.1:8080 \
  --fleet-name project1_pinky --worker-id trihouse-rmf-worker \
  2>&1 | tee /tmp/tour_rmf_worker.log
```

### C7 — OMX 무동작 Action 서버 두 대

`arm/prepare` step은 OMX Action 응답이 있어야 닫힌다. 이 서버는 모터 명령을
내보내지 않으며 시뮬레이션 bringup이 쓰는 것과 같은 구현이다.

```bash
python3 -m tests.simulation.omx.action_server --ros-args \
  -r __node:=omx_01 -p device_id:=OMX_01 2>&1 | tee /tmp/tour_omx_01.log &
python3 -m tests.simulation.omx.action_server --ros-args \
  -r __node:=omx_02 -p device_id:=OMX_02 2>&1 | tee /tmp/tour_omx_02.log
```

### R1 — 로봇 launch

순회 전용 협로 표를 먼저 로봇으로 보낸다(4060에서).

```bash
scp config/narrow_zones.new_map_2.zone_tour.yaml <로봇계정>@<PK_01 IP>:~/
```

```bash
ssh <로봇계정>@<PK_01 IP>
cd ~/trihouse_ws
source /opt/ros/jazzy/setup.bash
source install/setup.bash
source pinky_pro/install/setup.bash
export ROS_DOMAIN_ID=12
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
export REV='<C1에서 확인한 전체 revision>'

ros2 launch trihouse_pinky_bringup trihouse_pinky.launch.py \
  robot_id:=PK_01 namespace:=pinky_01 \
  map:=$HOME/maps/new_map_2.yaml map_revision:="$REV" \
  nav2_params_file:=$HOME/hardware_pinky_01.yaml \
  narrow_zones_file:=$HOME/narrow_zones.new_map_2.zone_tour.yaml \
  narrow_map_name:=new_map_2 \
  control_host:=<4060 Ethernet IP> control_port:=8788 \
  vision_enabled:=false docking_enabled:=false 2>&1 | tee /tmp/tour_hw.log
```

`marker_docks_file`과 `docking_enabled:=true`는 이번 순회에서 쓰지 않는다. 카메라
마커 도킹은 창고별 실측이 끝난 뒤의 별도 단계다.

### R2 — 로봇 판정과 초기 pose

```bash
ssh <로봇계정>@<PK_01 IP>
source /opt/ros/jazzy/setup.bash
source ~/trihouse_ws/install/setup.bash
export ROS_DOMAIN_ID=12
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
export NS=/pinky_01

grep -c 'Managed nodes are active' /tmp/tour_hw.log   # 기대 2
grep -E 'Failed to bring up all requested|Failed to change state' /tmp/tour_hw.log
ros2 topic info "$NS/cmd_vel" --verbose | grep -E 'Publisher count|Node name'
ros2 topic echo --once "$NS/trihouse/readiness" trihouse_interfaces/msg/Readiness
```

충전소에 세운 실제 시작 좌표로 초기 pose를 준다.

```bash
ros2 topic pub --once "$NS/initialpose" \
  geometry_msgs/msg/PoseWithCovarianceStamped \
  '{header: {frame_id: "map"}, pose: {pose: {position: {x: 0.057, y: 0.195, z: 0.0}, orientation: {z: 0.0546, w: 0.9985}}}}'
```

### C9 — 진행 관측

```bash
cd /home/syw/Trihouse
watch -n2 'docker exec trihouse-mysql mysql -uroot -p"$MYSQL_PW" --table -e \
  "SELECT s.step_no, s.executor_type, s.action_type, s.state,
          JSON_UNQUOTE(JSON_EXTRACT(s.input, \"$.temperature_zone\")) zone
     FROM trihouse_fms.job_steps s
     JOIN trihouse_fms.jobs j ON j.job_id = s.job_id
    WHERE j.job_id = (SELECT MAX(job_id) FROM trihouse_fms.jobs)
    ORDER BY s.step_no;"'
```

---

## 3. C8 — 순회 실행

주행 gate(세 창고 경로·충전소 탈출 실측)를 먼저 확인한다. 실물 주행 없이 계약만 돈다.

```bash
cd /home/syw/Trihouse
python3 -m pytest tests/hardware/test_zone_tour_full_stack.py -q
```

실제 순회. `--enable-full-stack`과 `--enable-motion`을 **둘 다** 줘야 주문을 만든다.

```bash
python3 -m pytest tests/hardware/test_zone_tour_full_stack.py \
  -m hardware -s -p no:cacheprovider \
  --enable-full-stack --enable-motion \
  --device-id PK_01 \
  --fms-url http://127.0.0.1:8080 \
  --narrow-zones-file config/narrow_zones.new_map_2.zone_tour.yaml \
  --narrow-map-name new_map_2 \
  --zone-items ambient=SKU-MANDARIN,chilled=SKU-YOGURT,frozen=SKU-ICEBAR \
  --packing-worker W-FIELD-01 \
  --full-stack-timeout 1200
```

테스트가 하는 일과 하지 않는 일은 다음과 같다.

- 한다: gate 판정, 주문 1건 생성, 진행 상황 JSONL 기록, `fms/wait`의 작업자 완료
  확인 호출, 완주 판정, 실패·중단 시 주문 취소.
- 하지 않는다: `/pinky_01/cmd_vel` 직접 발행, 창고 도킹, 물건 적재. 각 창고에서
  물건을 바구니에 올리는 것은 사람이 한다(`arm/prepare` 구간).

진행은 `[narrow-trace]` 줄로 그대로 흐르고, 같은 내용이 아래에 남는다.

```text
artifacts/zone_tour/zone_tour_<run>.jsonl   각 단계 즉시 기록
artifacts/zone_tour/zone_tour_<run>.json    최종 요약
```

## 4. 판정

성공은 다음을 모두 만족한 경우다.

- `mobile/navigate` 세 step이 `ambient → chilled → frozen` 순서로 `succeeded`.
- `mobile/return_home`이 `succeeded`.
- job이 `completed`.
- 로봇이 실제 충전 위치에 서 있다.

실패는 이유 코드로 남는다. 예: `ZONE_CHILLED_FAILED`(냉장 이동 실패),
`ZONE_ORDER_MISMATCH`(방문 순서가 계획과 다름), `RETURN_HOME_RUNNING`(제한 시간 안에
복귀 못 함), `NARROW_PROFILE_DISABLED`(주행 전 gate에서 차단), `RUNNER_ERROR`.

주행 뒤 실제 pose를 따로 확인한다(R2).

```bash
ros2 topic echo --once "$NS/amcl_pose" geometry_msgs/msg/PoseWithCovarianceStamped
```

## 5. 실패·중단 시

1. 물리 비상정지를 누른다.
2. 테스트를 Ctrl-C로 끊어도 주문은 자동 취소된다. 확인:

```bash
curl -sS http://127.0.0.1:8080/api/v1/jobs | python3 -m json.tool | head -40
```

3. 남은 예약이 있으면 취소로 반환된다. 다음 회차 전에 C1의 seed 재적용으로 재고를
   원복한다.
4. 로그: `/tmp/tour_hw.log`(로봇), `/tmp/tour_adapter_pk01.log`(배차),
   `/tmp/tour_job_runner.log`(배정), `artifacts/zone_tour/*.jsonl`(순회 증거).

## 6. 대안 — 주문 없이 이동만 확인

팔·재고·포장 인계를 빼고 순수 이동만 보고 싶으면 기존 경로 실행기를 쓴다. 목적지
`location_id`는 `--list`로 확인한다.

```bash
python3 tests/run_vlm_rl_dataset_route.py --list
python3 tests/run_vlm_rl_dataset_route.py \
  --location-ids <상온>,<냉장>,<냉동>,<충전소> \
  --execute --confirm-motion PK_01
```

이 경로도 R1의 순회 전용 협로 표를 그대로 쓴다. 창고 목적지 gate는 fleet가
적용하므로 운영 표로는 같은 이유로 거절된다.

## 절대 규칙

- 창고 도킹 실측 전에는 `verified: true` / `enabled: true`로 바꾸지 않는다.
- `$NS/cmd_vel`에 직접 속도를 보내지 않는다. 발행자는 항상 safety 하나다.
- 시험용 OMX `device_states` 행은 실제 팔을 붙일 때 반드시 지운다.
- gate가 막으면 gate를 낮추지 말고 실측을 한다.
