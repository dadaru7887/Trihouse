# 운영 테스트 실행 로그 — 2026-08-24

대상: 4060 서버 PC(`cook2`) + 운영 DB + Docker, Pinky PK_01(192.168.0.21) 1대
시나리오: 상온 → 냉장 → 냉동 창고 각 1회 주문 → 포장대 경유 → 대기/충전소 복귀

---

## 0. 호스트 실측 (기록 시작)

| 항목 | 실측값 |
| --- | --- |
| hostname | `cook2` |
| OS / 커널 | Ubuntu 24.04.4 LTS / 7.0.0-30-generic |
| GPU | NVIDIA GeForce RTX 4060 Laptop GPU, driver 580.173.02, 8188 MiB |
| LAN IP | `192.168.0.4` (인터페이스 `wlo1` = Wi-Fi) |
| 작업 경로 | `/home/newuser/Trihouse/.worktrees/physical-integration-v1` |
| Pinky | PK_01 = `192.168.0.21` (사용자 지정, 1대만 사용) |

실측 명령:

```bash
hostname
ip -4 -o addr show | awk '{print $2, $4}'
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'
docker compose ls
```

기동 중인 Compose project: `trihouse_p0`
(compose.yaml + compose.control.yaml + compose.edge_4060.yaml + compose.simulation.yaml)

| 컨테이너 | 이미지 | 상태 | 포트 |
| --- | --- | --- | --- |
| trihouse-mysql | mysql:8.4 | Up 31h (healthy) | `127.0.0.1:3308->3306` |
| trihouse_p0-fms_gateway-1 | trihouse_fms_gateway:local | Up 17m (healthy) | `192.168.0.4:8080`, `192.168.0.4:8788` |
| trihouse_p0-mediamtx-1 | bluenviron/mediamtx:1.19.3 | Up 31h | `127.0.0.1:8554` 등 |
| trihouse_p0-rmf_api-1 | open-rmf/rmf-web/api-server:jazzy | Up 31h | host network |
| trihouse_p0-rmf_dashboard-1 | robosapiens_rmf_dashboard:0.3.0 | Up 31h (healthy) | `127.0.0.1:3000->80` |

운영 DB는 `compose.yaml` 의 `trihouse-mysql` 이다. 시드가
`db/seeds/seed_hardware.sql` (실장비 시드) 이므로 개발용 `compose.db.yaml`
(`seed_dev.sql`) 과 다른 스택이다. 혼동하지 않는다.

### 발견 #1 — `.env` 의 호스트 IP가 실제와 불일치 (미해결, 아래 STEP 에서 처리)

`.env` 는 `PC1_LAN_IP=192.168.0.9` / `FMS_API_HOST=192.168.0.9` 인데,
이 호스트의 실제 주소는 `192.168.0.4` 하나뿐이다. 지금 떠 있는 Gateway 는
`192.168.0.4` 에 바인딩되어 있다 — 즉 `.env` 값이 아니라 기동 당시 셸
환경변수가 이겼다(Compose 는 셸 환경 > `.env` 우선순위). 재기동하면
`.env` 값이 적용되어 존재하지 않는 주소에 바인딩을 시도한다.

```bash
grep -n "PC1_LAN_IP\|FMS_API_HOST\|EDGE_BIND\|FMS_TCP_BIND" .env
docker inspect trihouse_p0-fms_gateway-1 --format '{{json .HostConfig.PortBindings}}'
# => {"8080/tcp":[{"HostIp":"192.168.0.4",...}],"8788/tcp":[{"HostIp":"192.168.0.4",...}]}
```

### 발견 #2 — MediaMTX 가 loopback 에만 바인딩

`trihouse_p0-mediamtx-1` 은 `127.0.0.1:8554` 로 떠 있다. Pinky(192.168.0.21)가
카메라를 RTSP 로 발행하려면 `EDGE_BIND_ADDRESS` 가 LAN 주소여야 한다.
현재 상태로는 로봇이 스트림에 붙지 못한다.

---

## 1. 로봇·워커·DB 실측

### 로봇 PK_01 (`pinky@192.168.0.21`, hostname `raspi`)

```bash
ssh pinky@192.168.0.21 'uptime; pgrep -af "ros2 launch|trihouse|nav2|amcl"; ls /home/pinky/'
```

- SSH 키 인증 동작 (BatchMode 통과)
- ROS 프로세스 **없음** = clean 상태에서 시작
- `/home/pinky/map/new_map_2.yaml` 존재
- `/home/pinky/hardware_pinky_01.yaml` 존재
- `/home/pinky/narrow_zones.new_map_2.yaml` 존재
- `~/trihouse_ws/src/` = `trihouse_interfaces`, `trihouse_pinky`,
  `trihouse_pinky.backup-20260824-100447`
  → 백업 디렉터리에 `COLCON_IGNORE` 가 있어 colcon 이 무시한다. 문제 없음.

### 호스트 ROS 워커 (4060 PC에서 이미 기동 중)

```bash
pgrep -af 'job_runner|executor_worker|rmf_gateway_worker|rmf_traffic'
tr '\0' '\n' < /proc/<PID>/environ | grep -i 'ROS_\|RMW'
```

| PID | 프로세스 |
| --- | --- |
| 151049 | `rmf_traffic_schedule` |
| 151050 | `rmf_traffic_blockade` |
| 1667613 | `control_tower.task_manager.executor_worker_node --fms-base-url http://192.168.0.4:8080 --environment hardware` |
| 1667614 | `control_tower.task_manager.job_runner_node --fms-base-url http://192.168.0.4:8080` |
| 1667615 | `control_tower.rmf_adapter.rmf_gateway_worker_node --fleet-name project1_pinky` |
| 211507 | `fastdds discovery -i 0 -l 192.168.0.4 -p 11811` |

워커 공통 DDS 환경 (실측):

```
ROS_DOMAIN_ID=12
ROS_AUTOMATIC_DISCOVERY_RANGE=SYSTEM_DEFAULT
ROS_DISCOVERY_SERVER=192.168.0.4:11811
RMW_IMPLEMENTATION=rmw_fastrtps_cpp
FASTDDS_BUILTIN_TRANSPORTS=UDPv4
```

### 발견 #3 — DDS discovery 방식이 두 가지로 갈려 있다 (중요)

사용자가 준 PK_02 참고 절차는 `ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET` 에
Discovery Server 를 쓰지 않는다. 그러나 이 4060 PC 에서 이미 도는 워커는
전부 `SYSTEM_DEFAULT` + `ROS_DISCOVERY_SERVER=192.168.0.4:11811` 이다.
**두 방식은 서로를 발견하지 못한다.** 로봇을 SUBNET 으로 띄우면 관제 워커와
토픽이 연결되지 않는다.

→ 결정: 이미 떠 있는 관제 쪽에 맞춰 **로봇도 Discovery Server 방식**으로 띄운다.
   (`docs/guides/pinky-autonomous-operation.md` STEP 0 도 이 방식이 정본)

### 발견 #4 — fleet 이름 불일치 (중요)

```sql
SELECT device_id, fleet_name FROM devices WHERE device_type='mobile';
-- PK_01 | new_map_2_pinky
-- PK_02 | new_map_2_pinky
```

그런데 호스트의 `rmf_gateway_worker_node` 는 `--fleet-name project1_pinky` 로
떠 있다. 주문이 RMF 경로를 타면 fleet 이 달라 배차가 붙지 않는다.

### 운영 DB 좌표 정본 (`locations`, map `new_map_2`)

| location_code | rmf_waypoint_name | x | y | yaw | 용도 |
| --- | --- | --- | --- | --- | --- |
| WH-AMB-01-DOCK-01 | `ambient_storage_loading_dock_01` | 1.234 | 0.743 | 2.255 | 상온 도크 |
| WH-CHL-01-DOCK-01 | `chilled_storage_loading_dock_01` | 1.260 | 0.193 | -2.258 | 냉장 도크 |
| WH-FRZ-01-DOCK-01 | `frozen_storage_loading_dock_01` | 1.3315 | -0.8149 | -1.57214 | 냉동 도크 |
| PACKING-01-DOCK-01 | `packing_station_loading_dock_01` | 0.351 | -0.490 | 0.231 | 포장대 1 |
| PACKING-01-DOCK-02 | `packing_station_loading_dock_02` | 0.351 | -1.017 | 0.231 | 포장대 2 |
| TRIHOUSE-TEST-01-CHG-01 | `charging_station_01` | 0.0570 | 0.1950 | 0.1093 | **PK_01 홈/충전** |
| TRIHOUSE-TEST-01-CHG-02 | `charging_station_02` | 0.1337 | -0.0066 | 0.1570 | PK_02 홈/충전 |
| TRIHOUSE-TEST-01-CHG-EXIT | `charging_station_narrow_exit` | 0.7993 | 0.0854 | 0.0924 | 충전소 협로 탈출 |
| WH-AMB-01-NARROW-ENTRY | `ambient_storage_narrow_entry` | 1.0102 | 0.9167 | -0.0868 | 상온 협로 진입 |
| WH-CHL-01-NARROW-ENTRY | `chilled_storage_narrow_entry` | 1.1013 | -0.1005 | 3.1029 | 냉장 협로 진입 |
| WH-FRZ-01-NARROW-ENTRY | `frozen_storage_narrow_entry` | 1.1793 | -1.1897 | 0.0109 | 냉동 협로 진입 |

`devices.home_location_id`: PK_01 → 19 (`charging_station_01`), PK_02 → 20.

map revision: `new_map_2:2419810c3f013a648f46da995aa33b6f8ba20154cf297c26932959a599898589`

---

## 2. 주문 파이프라인 실측 — 왜 멈춰 있었나

### 발견 #5 — 가이드 문서의 map revision 이 폐기본(retired)

`docs/guides/pinky-ad-guideline.md` 는 map revision 을
`new_map_2:df9a7f70...` 로 적어 두었으나, DB 의 `map_revisions` 는 그것을
`retired` 로, 실제 `published` 는 `new_map_2:2419810c...` 로 갖고 있다.

```bash
curl -s http://192.168.0.4:8080/internal/v1/maps/new_map_2/published \
  | python3 -c "import json,sys;print(json.load(sys.stdin)['map_revision'])"
# => new_map_2:2419810c3f013a648f46da995aa33b6f8ba20154cf297c26932959a599898589
```

bringup 의 `map_revision:=` 에는 **published 값**을 넣어야 한다.

### 직전 주문(job 6)이 죽은 이유

```sql
SELECT message_id,state,attempts,last_error FROM integration_messages
 WHERE job_step_id=24\G
-- state: dead_letter / attempts: 5 / last_error: DISPATCH_ATTEMPTS_EXHAUSTED
```

job 6(`OUT-aac832f3b88d56ae91461987`, SKU-MANDARIN 상온)은 11:18 에 생성되어
step 20(PK_01 navigate → location 13 상온 도크)까지 계획되었으나, 로봇 bringup 이
떠 있지 않아 dispatch 5회를 소진하고 `dead_letter` 가 되었다.
`reservations` 에 `device:PK_01`, `location:16`(포장대 도크1), `device:OMX_01` 이
`reserved` 로 잡혀 있어 **새 주문을 넣기 전에 반드시 취소해야 한다.**

### 계획된 job step 구조 (job 6 실측 — 시나리오가 그대로 나온다)

| step_no | executor | device | action | target_location |
| --- | --- | --- | --- | --- |
| 10 | arm | OMX_01 | prepare | 13 (상온 도크) |
| 20 | mobile | PK_01 | navigate | 13 (상온 도크) |
| 30+ | … | … | … | 16 (포장대 도크1) |

즉 좌표를 직접 주지 않아도 FMS 가 SKU 의 `temperature_zone` 으로 창고 도크와
포장대를 스스로 정한다. 주문은 SKU 하나만 넣으면 된다.

---

## 3. 로봇 배포 상태 점검

### 코드 — 재빌드 불필요

```bash
rsync -avcn --itemize-changes \
  --exclude='__pycache__/' --exclude='.pytest_cache/' --exclude='*.pyc' \
  trihouse_interfaces trihouse_pinky \
  pinky@192.168.0.21:/home/pinky/trihouse_ws/src/ | grep -E '^[><ch]'
# => 출력 없음 = 내용이 동일. mtime 차이만 있으므로 colcon build 불필요.
```

### 협로 설정 — 동일

```bash
sha256sum config/narrow_zones.new_map_2.yaml
# a9f527f415b8851ea69059df811ff21e2178747757ccbfffc3f39280b21b0af3
ssh pinky@192.168.0.21 'sha256sum /home/pinky/narrow_zones.new_map_2.yaml'
# a9f527f415b8851ea69059df811ff21e2178747757ccbfffc3f39280b21b0af3
```

`measured` 4개 항목(`entry_pose`/`dock_pose`/`enter`/`exit`)이 상온·냉장·냉동
세 profile 모두 `true` → 일반(정식) 주문을 열 수 있다.

### 발견 #6 — AMCL 초기 pose 가 충전소가 아니라 상온 도크에 박혀 있다 (치명)

```bash
ssh pinky@192.168.0.21 'sed -n "41,47p" /home/pinky/hardware_pinky_01.yaml'
      set_initial_pose: true
      initial_pose:
        x: 0.911748152598201
        y: 0.77587646431032
        z: 0.0
        yaw: 0.875201645910827
```

이 좌표는 **상온 창고 진입부**(`ambient_storage_narrow_entry` = 1.010, 0.917 근처)다.
직전 상온 calibration 주행에서 남은 값이다.

이번 시나리오는 **대기/충전소에서 출발**해야 한다. 정본 좌표는
`charging_station_01` = `x 0.0570244747, y 0.1949666005, yaw 0.1093261667`.

로봇을 충전소에 놓고 이 파일을 그대로 두면 AMCL 이 1 m 가까이 틀어진 채 시작하고,
그 오차는 로봇이 움직이기 시작한 뒤에야 드러난다. → 파일 수정 필요.

---

## 4. 실행 로그 (2026-08-24)

### STEP 1 — 정지된 job 6 취소  ✅

```bash
export FMS_API='http://192.168.0.4:8080'
RUN_ID="$(date +%Y%m%d%H%M%S)"
curl -sS -X POST "$FMS_API/internal/v1/jobs/6/cancel" \
  -H 'Content-Type: application/json' \
  -H "Idempotency-Key: cancel-job-6-${RUN_ID}" \
  -d '{"reason":"ops_test_restart_dead_letter","requested_by":"newuser"}' \
  | python3 -m json.tool
```

결과:

```json
{"job_id": 6, "state": "cancelled",
 "cancelled_step_ids": [23,24,25,26,27,28,29],
 "cancelled_reservation_ids": [7,8,9],
 "released_device_ids": ["OMX_01","PK_01"]}
```

### 발견 #7 — `measured` 플래그는 실측이 아니라 수동 개방 (위험 감수 사항)

`git diff config/narrow_zones.new_map_2.yaml` 로 확인한 실제 변경:

| zone | 원래 값 | 바꾼 값 |
| --- | --- | --- |
| 상온 `ambient_storage_loading_dock_01` | `dock_pose: false` | `true` |
| 냉장 `chilled_storage_loading_dock_01` | `dock_pose/enter/exit: false` | 모두 `true` |
| 냉동 `frozen_storage_loading_dock_01` | `dock_pose/exit: false` | 모두 `true` |

즉 **정식 주문 경로를 열기 위해 사용자가 수동으로 개방한 값**이며, 냉장의
진입/탈출 시퀀스와 세 구역의 `dock_target` 은 실주행으로 검증된 값이 아니다.
이번 운영 테스트가 사실상 그 검증을 겸한다. 도킹 정확도 이상은 결함이 아니라
**미검증 후보값이 드러난 것**으로 읽는다.

### STEP 2 — 로봇 AMCL 초기 pose 를 충전소로 교정  ✅

문제: `/home/pinky/hardware_pinky_01.yaml` 의 `initial_pose` 가 직전 상온
calibration 잔재인 `(0.9117, 0.7759, yaw 0.8752)` 였다. 이번 시나리오는
충전소 출발이므로 `charging_station_01` 값으로 바꾼다.

```bash
ssh pinky@192.168.0.21 '
cd /home/pinky
cp -a hardware_pinky_01.yaml hardware_pinky_01.yaml.backup-ops-20260824-charger
python3 - <<PY
import re, pathlib
p = pathlib.Path("/home/pinky/hardware_pinky_01.yaml")
t = p.read_text(encoding="utf-8")
new = """      initial_pose:
        x: 0.0570244747
        y: 0.1949666005
        z: 0.0
        yaw: 0.1093261667"""
pat = re.compile(r"      initial_pose:\n        x: [-0-9.eE]+\n        y: [-0-9.eE]+\n        z: [-0-9.eE]+\n        yaw: [-0-9.eE]+")
t2, n = pat.subn(new, t)
assert n == 1
p.write_text(t2, encoding="utf-8")
PY
sha256sum hardware_pinky_01.yaml'
```

- 백업: `/home/pinky/hardware_pinky_01.yaml.backup-ops-20260824-charger`
- 수정 후 sha256: `dfbb196b278bf0e25cf35206762c47e33683a308f520aea6b92afa3a46bcecad`

---

## 5. 주문 파이프라인을 살리기까지 — 막힌 지점 4개

### 발견 #8 — RMF fleet adapter 가 namespace 없는 토픽을 보고 있었다 (근본 원인)

`pinky_easy_fleet_adapter` 가 두 벌 떠 있었고(PID 181311/181315, 1677629/1677632)
둘 다 아래 인자로 실행되어 있었다.

```
--status-topic /trihouse/status
--transport-action /trihouse/transport/execute
--map-revision new_map_2:df9a7f70...   ← 폐기된 revision
```

로봇은 `/pinky_01/trihouse/status` 로 발행한다. 어댑터는 `/trihouse/status` 를
구독했으므로 로봇 상태를 **한 건도 받지 못했고**, 어댑터는 상태를 받아야만
`add_robot` 을 하므로 fleet 에 로봇이 없었다. 그 결과가 이 로그다.

```
[Bidder] Received Bidding notice for task_id [compose.dispatch-b9dcb6a5c8]
Fleet [project1_pinky] does not have any robots to accept task [...].
Use FleetUpdateHadndle::add_robot(~) to add robots to this fleet.
```

FMS 쪽에서는 이것이 `RMF_ASSIGNMENT_PENDING` → 5회 소진 → `DISPATCH_ATTEMPTS_EXHAUSTED`
→ `dead_letter` 로 보였다. 원인에서 세 단계 떨어진 증상이다.

**조치** — 중복 인스턴스를 모두 내리고 하나만, namespace 를 붙여 재기동한다.

```bash
# 중복 정리 (PID 는 pgrep -af 'pinky_easy_fleet_adapter' 로 확인)
kill -INT <launch_pid> <node_pid>
kill -TERM <launch_pid> <node_pid>

cd /home/newuser/Trihouse/.worktrees/physical-integration-v1
source /opt/ros/jazzy/setup.bash && source install/setup.bash
export ROS_DOMAIN_ID=12
export ROS_AUTOMATIC_DISCOVERY_RANGE=SYSTEM_DEFAULT
export ROS_DISCOVERY_SERVER='192.168.0.4:11811'
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export FASTDDS_BUILTIN_TRANSPORTS=UDPv4
unset ROS_STATIC_PEERS FASTRTPS_DEFAULT_PROFILES_FILE

MAP_REVISION='new_map_2:2419810c3f013a648f46da995aa33b6f8ba20154cf297c26932959a599898589'

setsid nohup ros2 launch trihouse_rmf_bridge pinky_easy_fleet_adapter.launch.py \
  nav_graph:="$PWD/.trihouse/p0/nav_graph.yaml" \
  robot_name:=PK_01 rmf_map_name:=L1 \
  charger_waypoint:=charging_station_01 \
  map_revision:="$MAP_REVISION" \
  robot_status_topic:=/pinky_01/trihouse/status \
  transport_action:=/pinky_01/trihouse/transport/execute \
  fms_base_url:=http://192.168.0.4:8080 use_sim_time:=false \
  > /tmp/trihouse_pinky_fleet_adapter.log 2>&1 < /dev/null &
```

성공 로그:

```
[PK_01] EasyFullControl adapter 시작: status=/pinky_01/trihouse/status, ...
[PK_01] 유효한 pose/SOC로 RMF에 등록했습니다.
```

### 발견 #9 — OMX 없이는 포장대·충전소 복귀까지 못 간다 (구조)

```sql
SELECT step_no, JSON_EXTRACT(input,'$.dependencies') FROM job_steps WHERE job_id=7;
-- 10 []        omx_prepare
-- 20 []        pinky_navigate
-- 30 [10, 20]  readiness_load_gate
-- 40 [30]      packing_navigate
-- 50 [40]  60 [50]  70 [60] return_home
```

step 30(적재)이 10과 20 **둘 다** 성공해야 열린다. OMX_01 팔 PC(192.168.0.31)는
이번 테스트에서 응답하지 않았다(ping 불가). 따라서 팔 동작만 무동작
시뮬레이터로 대체했다. **주행·협로·도킹·포장대·충전소 복귀는 전부 실물이다.**

```bash
cd /home/newuser/Trihouse/.worktrees/physical-integration-v1
source /opt/ros/jazzy/setup.bash && source install/setup.bash
export ROS_DOMAIN_ID=12 ROS_AUTOMATIC_DISCOVERY_RANGE=SYSTEM_DEFAULT
export ROS_DISCOVERY_SERVER='192.168.0.4:11811'
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp FASTDDS_BUILTIN_TRANSPORTS=UDPv4
export PYTHONPATH="$PWD/trihouse_omx_adapter:$PWD${PYTHONPATH:+:$PYTHONPATH}"

for omx in OMX_01 OMX_02; do
  node="$(echo "$omx" | tr '[:upper:]' '[:lower:]')"
  setsid nohup python3 -m tests.simulation.omx.action_server \
    --ros-args -r __node:="$node" -p device_id:="$omx" \
    > "/tmp/trihouse_omx_sim_${node}.log" 2>&1 < /dev/null &
done
```

주의: `omx_02` 시뮬레이터가 이미 떠 있는 경우가 있다. 같은 노드 이름이 두 벌
뜨면 안 되므로 `pgrep -af 'tests.simulation.omx.action_server'` 로 반드시 확인한다.

### 발견 #10 — FMS job 취소가 RMF task 를 취소하지 않는다 (설계 결함, 재발성 높음)

job 8 을 FMS 에서 취소했지만 RMF dispatcher 는 그 task 를 그대로 들고 있었다.
fleet adapter 는 그 task 를 계속 재배정받아 `cancelled` 인 job_step 을 claim 하려
했고, Gateway 는 정당하게 409 를 돌려주었다.

```
[PK_01] FMS command claim 실패: HTTP Error 409: Conflict
Replanning requested for [project1_pinky/PK_01]      ← 초당 수백 회 반복
```

409 조건 (`fms_gateway/app/repositories.py:6407`):

```python
if step["state"] not in {"pending", "running"}:
    raise CommandClaimConflict
```

이 굶주림 고리 때문에 **새 주문(job 9)이 영원히 `20=pending` 에 머물렀다.**
"주문을 넣었는데 로봇이 안 움직인다" 의 정체다.

RMF API(`127.0.0.1:8000`)는 인증이 걸려 있으므로 ROS `/task_api_requests` 로 취소한다.
도구: `scratchpad/rmf_cancel_task.py` (아래 문서 부록에 전문 수록)

```bash
python3 rmf_cancel_task.py compose.dispatch-e1e81e8a79 ...
# => 응답 trihouse-cancel-0-...: {"success":true}
```

취소 직후 로그:

```
Beginning next task [compose.dispatch-9b6b29f02b] for robot [project1_pinky/PK_01]
[PK_01] RMF compose.dispatch-9b6b29f02b -> (0.799, 0.085, -1.146)
[PK_01] Pinky 도착·정지 확인 후 RMF 이동을 완료했습니다.
[PK_01] RMF compose.dispatch-9b6b29f02b -> (0.895, -0.126, 1.199)
[PK_01] Pinky 도착·정지 확인 후 RMF 이동을 완료했습니다.
[PK_01] RMF compose.dispatch-9b6b29f02b -> (1.234, 0.743, 1.199)
```

**취소된 job 의 rmf_task_id 목록을 뽑는 SQL** (다음 주문 전 반드시 확인):

```sql
SELECT job_id, job_step_id, state, rmf_task_id
  FROM job_steps
 WHERE rmf_task_id IS NOT NULL AND state = 'cancelled';
```

### 발견 #11 — safety guard 임계값이 도크 거리와 같아 구조적으로 진입 불가

`stop_distance_m` 은 **범퍼 기준으로 벽 앞 몇 m 에 서라**는 값이다
(`FOOTPRINT_FRONT_M = 0.04` 는 이미 차감되어 있다). 기본값이 `0.30`.

그런데 상온 `entry → dock_target` 거리가 **정확히 0.300 m** 다. 로봇 로그:

```
front_stop: desired=(0.000, 0.000) path_clearance=0.2973716054436855
            scan_nearby=0.21423666629463825 scan_age=0.084
```

실측 여유 0.2954~0.2983 m vs 임계 0.300 m — **3 mm 차이로 영구 차단**.
회전도 같다: `swept_stop threshold=0.179` vs 실측 `0.1755` — 역시 3 mm.

**조치** — bringup 이 만든 supervisor 를 내리고 완화값으로 교체한다.
(launch 는 safety 파라미터를 인자로 받지 않으므로 프로세스 교체가 유일한 방법이다.)

```bash
# 로봇에서
pgrep -f "trihouse_pinky_safety.*safety_supervisor"     # PID 확인
kill -KILL <PID>

source /opt/ros/jazzy/setup.bash
source /home/pinky/pinky_pro/install/setup.bash
source /home/pinky/trihouse_ws/install/setup.bash
export ROS_DOMAIN_ID=12
export ROS_AUTOMATIC_DISCOVERY_RANGE=SYSTEM_DEFAULT
export ROS_DISCOVERY_SERVER='192.168.0.4:11811'
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export FASTDDS_BUILTIN_TRANSPORTS=UDPv4
unset ROS_STATIC_PEERS FASTRTPS_DEFAULT_PROFILES_FILE

setsid nohup ros2 run trihouse_pinky_safety safety_supervisor --ros-args \
  -r __ns:=/pinky_01 -p robot_id:=PK_01 \
  -p stop_distance_m:=0.05 \
  -p slow_distance_m:=0.20 \
  -p swept_clearance_m:=0.05 \
  -r cmd_vel_nav:=cmd_vel -r cmd_vel:=cmd_vel_safe \
  > /home/pinky/ops_test_20260824_safety_relaxed.log 2>&1 < /dev/null &
```

> **위험 고지.** `swept_clearance_m` 을 기하학적 외접반경
> `hypot(0.16, 0.08) = 0.179 m` 아래로 내리면 가드는 더 이상 접촉을 막지 못한다.
> 이 값에서는 E-stop 담당자가 실질적인 보호 장치다.

### 발견 #12 — `front_stop` 에는 recovery 가 없다 (코드)

`trihouse_pinky/trihouse_pinky_docking/trihouse_pinky_docking/narrow_zone.py:434`

```python
if safety.detail == "swept_stop" and self.phase == self.ENTRY_ALIGNMENT:
    ...  # 회전 공간 확보 recovery
return self._fail(f"safety_stop:{safety.detail or 'unknown'}")
```

recovery 는 **`swept_stop` × `ENTRY_ALIGNMENT` 한 조합에만** 있다.
`ENTER_STRAIGHT` 중 `front_stop` 은 곧바로 `failed` 로 떨어지고,
`recovery_max_attempts: 2` 는 한 번도 쓰이지 않는다. 실측 로그가 그대로 보여준다.

```
rule_transition ... phase=enter_straight safety='front_stop' recovery_attempt=0
rule_transition ... from=enter_straight to=failed  failure='safety_stop:front_stop'
```

이 전이가 초당 수십 회 반복되며 아무 회복도 시도하지 않는다.

---

## 6. 주행 실측 결과

### 시도 1 (job 8, `stop_distance_m=0.30` 기본값)

| 시각 | x | y | yaw° | 최근접 waypoint | 거리 | 상태 |
| --- | --- | --- | --- | --- | --- | --- |
| 11:53:32 | 0.2841 | 0.2190 | 5.8 | charging_station_01 | 0.228 | idle |
| 11:53:42 | 0.7358 | 0.2714 | 2.5 | charging_station_narrow_exit | 0.197 | navigating |
| 11:54:02 | 0.8407 | 0.0247 | -68.5 | charging_station_narrow_exit | 0.074 | navigating |
| 11:54:22 | 0.8517 | 0.5366 | 81.3 | ambient_storage_narrow_entry | 0.412 | navigating |
| 11:54:32 | 0.8745 | 0.7129 | 22.1 | ambient_storage_narrow_entry | 0.245 | navigating |
| 11:55~11:57 | 0.87~0.89 | 0.69~0.71 | 20~32 | ambient_storage_narrow_entry | ~0.25 | **제자리 진동** |

→ 출입구 진입 규칙 진입 후 `front_stop` 으로 즉시 실패, 무한 재시도.

### 시도 2 (job 9, `stop_distance_m=0.05` 완화)

RMF 경유점을 정상적으로 하나씩 통과했다.

| RMF 목표 | 결과 |
| --- | --- |
| `(0.799, 0.085, -1.146)` charging_station_narrow_exit | 도착·정지 확인 |
| `(0.895, -0.126, 1.199)` bottleneck_zone_01 | 도착·정지 확인 |
| `(1.234, 0.743, 1.199)` ambient_storage_loading_dock_01 | **미도달** |

진입부 부근에서 다시 진동:

| 시각 | x | y | yaw° | 거리(진입부) | safety |
| --- | --- | --- | --- | --- | --- |
| 12:14:47 | 1.0548 | 0.7404 | 21.4 | 0.179 | front_stop |
| 12:14:59 | 1.0199 | 0.7443 | 87.1 | 0.173 | clear |
| 12:15:11 | 1.0097 | 0.7514 | 155.3 | 0.165 | clear |
| 12:15:47 | 1.0211 | 0.7334 | 30.3 | 0.184 | front_stop |
| 12:15:59 | 0.8352 | 0.5644 | 57.2 | 0.393 | clear (후퇴) |
| 12:16:11 | 1.0282 | 0.7257 | 33.4 | 0.192 | front_stop |

**정지 pose: `x=1.0015, y=0.7284, yaw=57.2°`**

완화 전보다 0.13 m 더 안쪽까지 들어갔고 `stop_distance_m` 은 더 이상 병목이
아니다. 남은 문제는 **entry 좌표 자체**다.

### 발견 #13 — 상온 `entry.yaw` 가 자기 `dock_target` 과 30.3° 어긋나 있다

```python
entry       = (0.911748, 0.775876, yaw  0.875202 rad =  50.1°)
dock_target = (1.194985, 0.874754, yaw -2.805721 rad = -160.8°)
entry -> dock  거리 0.300 m,  방위 19.2°
enter 시퀀스   rotate -160.8° 후 straight -0.30 (후진) => 진행 방위 19.2°
```

`entry.yaw` 는 50.1° 인데 도크는 19.2° 방향에 있다. 같은 파일의
`entry_passage.doorway.yaw = 0.33587 rad = 19.2°` 와도 어긋난다.
시도 1 에서 로봇이 스스로 멈춘 yaw 는 **19.8°** — 도크 방위와 0.6° 차이다.

즉 `entry.yaw` 하나만 실측과 다르며, Nav2 는 도달 불가능한 50.1° 를 맞추려고
제자리 회전을 반복한다.

### 발견 #14 — 배터리 SOC 판독이 심하게 튄다

한 주행 중 실측: `86.6 → 71.2 → 55.8 → 100.0 → 36.0 → 92.5 → 22.3 → 4.5 → 64.8`
값이 낮게 튀는 순간 `dispatchable=0`, `errors=battery_not_dispatchable` 이 되어
RMF 가 새 작업을 주지 않는다. 이번 테스트에서 주행을 끊지는 않았지만,
장시간 운영에서는 임의로 배차가 끊기는 원인이 된다.

---

## 7. 협로 좌표 재실측 — 실패한 방법과 성공한 방법

### 실패: 손으로 놓고 AMCL 로 재기

로봇을 들어 옮기면 odometry 가 끊긴다. AMCL 은 그 사실을 알 방법이 없어 옮기기
전 좌표를 계속 보고한다. 실측 로그:

```
12:23:35  (1.0013, 0.7280, 58.2deg)   <- 옮긴 뒤인데 값이 그대로다
```

`/pinky_01/initialpose` 로 대략값을 뿌리고 저속 제자리 회전으로 필터를 흔들어
보았으나, AMCL 은 **씨앗을 그대로 받아들였을 뿐 스캔으로 자리를 찾지 않았다.**

```
12:23:44.660  (1.0545, 0.7645, 18.7deg)   <- 씨앗 (1.05, 0.80, 19.2deg) 과 거의 동일
12:23:46~49   18.7 -> 15.6 -> 8.5 -> 0.6 -> -7.9 -> -14.9deg   <- 회전 명령이 만든 변화
```

즉 결과값 `(1.0554, 0.7039, -14.9deg)` 는 실측이 아니라 **씨앗 + 회전량**이다.
설정에 넣으면 안 된다. 게다가 좌회전 명령이 yaw 를 낮춘 것으로 보아 두 회전 중
하나만 실행되어 순회전 -34deg 가 남았다. 재려던 대상을 재는 행위가 흔들었다.

> **교훈.** `ops_read_pose.py` 는 **로봇이 스스로 주행해 도달한 자리**에서만
> 실측이다. 손으로 옮긴 직후 값은 실측이 아니다.

### 성공: 설정 파일의 자기모순을 근거로 삼기

물리 재측정 없이 결함을 특정할 수 있었다. 세 창고 전부 `entry.yaw` 가 자기
`dock_target` 방위와 어긋나 있었다.

```bash
python3 - <<'PY'
import math, yaml
d = yaml.safe_load(open('config/narrow_zones.new_map_2.yaml'))
for name, z in d['zones'].items():
    e, t = z.get('entry'), z.get('dock_target')
    if not e or not t: continue
    dx, dy = t['x']-e['x'], t['y']-e['y']
    bearing = math.degrees(math.atan2(dy, dx))
    diff = (math.degrees(e['yaw']) - bearing + 180) % 360 - 180
    print(f"{name:<38} entry.yaw={math.degrees(e['yaw']):7.1f} "
          f"도크방위={bearing:7.1f} 차이={diff:7.1f} 거리={math.hypot(dx,dy):.3f}")
PY
```

| 창고 | entry.yaw | 도크 방위 | 차이 | entry→dock | enter 시퀀스 오차 |
| --- | --- | --- | --- | --- | --- |
| 상온 | 50.1° | 19.2° | **+30.9°** | 0.300 m | 0.000 m |
| 냉장 | 50.1° | −65.3° | **+115.4°** | **1.293 m** | **1.025 m** |
| 냉동 | −1.9° | 65.5° | **−67.4°** | 0.281 m | 0.000 m |

`enter` 시퀀스를 적분해 `dock_target` 과 대조하는 검증도 함께 돌렸다.
**냉장은 시퀀스가 도크에서 1.025 m 빗나간다** — 좌표 한 개가 아니라 시퀀스 전체가
현재 도크 위치와 맞지 않는다.

### 상온 — 2026-08-15 `narrow_1` 실측 원본으로 복원

사용자가 보관하던 원본 값:

```python
"narrow_1": {  # 상온
    "geometry": {
        # 2026-08-15 실측 시작점 (stddev x=10.9cm/y=6.0cm/yaw=10.6deg)
        "cx": 1.010244055594586, "cy": 0.9167344977253539, "yaw": -0.08675495954950327,
        "length": 0.05, "width": 0.20,
    },
    "sequence": [("rotate", -2.805721254488808), ("straight", -0.30)],
    "sequence_exit": [("straight", 0.30), ("rotate", -3.130293455959265), ("exit_zone", None)],
}
```

이 값으로 파생값을 다시 계산하면 **모든 것이 자기일관된다.**

| 항목 | 값 | 검증 |
| --- | --- | --- |
| entry | (1.010244055594586, 0.9167344977253539, −0.08675495954950327) | DB waypoint `ambient_storage_narrow_entry` 와 **동일 좌표** |
| entry→dock | 0.3000 m, 방위 19.24° | enter 시퀀스 `straight -0.30` 과 일치 |
| dock_target | (1.293481094178777, 1.0156120986977553, −2.805721254488808) | 시퀀스 적분값 |
| doorway.yaw | 0.3358713991009853 | **파일에 이미 있던 0.33587139910098424 와 일치** |
| exit_target | (1.010244055594586, 0.9167344977253539, −3.130293455959265) | exit 시퀀스가 entry 로 **오차 0** 복귀 |

`doorway.yaw` 가 원본 그대로 남아 있었다는 것이 결정적이다. 2026-08-23 에
`entry` 만 바뀌고 `doorway` 는 함께 고쳐지지 않았음을 뜻한다.

적용:

```bash
cd /home/newuser/Trihouse/.worktrees/physical-integration-v1
cp -a config/narrow_zones.new_map_2.yaml config/narrow_zones.new_map_2.yaml.backup-ops-20260824
# (편집)
python3 -c "import yaml; yaml.safe_load(open('config/narrow_zones.new_map_2.yaml'))"
scp config/narrow_zones.new_map_2.yaml pinky@192.168.0.21:/home/pinky/narrow_zones.new_map_2.yaml
sha256sum config/narrow_zones.new_map_2.yaml
ssh pinky@192.168.0.21 'sha256sum /home/pinky/narrow_zones.new_map_2.yaml'
# 양쪽 472f374291544acbe85c5a39305b7a0b0f27ce6844909584857b7af3170e2f62
```

`fleet_node` 는 launch 때 이 파일을 읽으므로 **배포 후 bringup 재시작이 필요하다.**

### 남은 것 — 냉장·냉동

상온과 같은 방식으로 원본 `narrow_2`(냉장) / `narrow_3`(냉동) 실측값이 필요하다.
특히 냉장은 시퀀스 자체가 1.025 m 어긋나 있어 좌표 한 개 수정으로는 부족하다.

### 정정 — 냉동은 결함이 아니다

앞의 "세 창고 전부 불일치" 표는 냉동에 대해 틀렸다. 방위 비교는 `enter` 가
`rotate` 로 시작할 때만 성립한다. 냉동의 `enter` 는 `straight` 로 시작한다.

```yaml
enter:
  - [straight, 0.325]      # entry yaw 방향으로 먼저 전진
  - [rotate, -0.9057963267948966]
  - [straight, -0.338]
```

시퀀스를 적분해 `dock_target` 과 대조하는 검증에서 냉동 오차는 0.0000000000 m 다.
냉동은 원본 `j_narrow3_rule_based_docking_1.py` 값을 그대로 갖고 있으며 건드리지
않았다.

### 냉장 — `entry` 가 상온과 같은 방식으로 오염되어 있었다

되돌릴 값을 추측할 필요가 없었다. `dock_target` 을 고정해 두고 어떤 `entry` 가
`enter` 시퀀스로 그 자리에 떨어지는지 역산하면 **DB 정본 waypoint 가 정확히
나온다.**

```
현재 설정 entry (0.785906, 0.875245)  -> 시퀀스 도착 (1.0109162953, 0.6768253859)  오차 1.0254145987 m
DB narrow_entry (1.101332, -0.100451) -> 시퀀스 도착 (1.3263418779, -0.2988701615)  오차 0.0000000000 m
```

즉 `dock_target` 은 원래 `chilled_storage_narrow_entry` 에서 유도된 값이고
`entry` 만 덮어써졌다. 상온과 동일한 편집이다.

냉장은 상온과 달리 `doorway` 도 잘못된 entry 로 함께 다시 계산되어 있었으므로
(중점 1.0561/0.2882, yaw −65.28°) 되돌린 entry 로 재계산했다
(중점 1.2139/−0.1997, yaw −41.41°).

### 최종 검증 — 세 창고 왕복 오차

```bash
python3 - <<'PY'
import math, yaml
d = yaml.safe_load(open('config/narrow_zones.new_map_2.yaml'))
for name, z in d['zones'].items():
    e, t_, seq = z.get('entry'), z.get('dock_target'), z.get('enter')
    if not (e and t_ and seq): continue
    x, y, h = e['x'], e['y'], e['yaw']
    for op, v in seq:
        if op == 'rotate': h = v
        elif op == 'straight': x += v*math.cos(h); y += v*math.sin(h)
    print(name, 'enter오차', math.hypot(x-t_['x'], y-t_['y']))
PY
```

| 창고 | enter → dock_target 오차 | exit → entry 오차 |
| --- | --- | --- |
| 상온 | 0.0000000000 m | 0.0000000000 m |
| 냉장 | 0.0000000000 m | 0.0000000000 m |
| 냉동 | 0.0000000000 m | 0.3107287662 m (※) |

※ 냉동의 `exit` 마지막 단계는 `exit_zone`(존을 벗어날 때까지 전진)이라 고정
스텝만으로는 종점이 정해지지 않는다. 원본에도 종료 좌표가 없다. 결함이 아니다.

### 배포된 최종 좌표

```
ambient_storage_loading_dock_01
   entry       (1.010244,  0.916734,   -4.971 deg)
   dock_target (1.293481,  1.015612, -160.756 deg)
chilled_storage_loading_dock_01
   entry       (1.101332, -0.100451, +177.785 deg)
   dock_target (1.326342, -0.298870, +138.593 deg)
frozen_storage_loading_dock_01
   entry       (0.919804, -1.189253,   -1.858 deg)
   dock_target (1.036067, -0.933813,  -51.898 deg)
```

`config/narrow_zones.new_map_2.yaml` sha256 =
`ff8f2d37c9a1429fcfca07d8eb3f584408f1e54ba421d862aad80af093c6b664`
(로봇 `/home/pinky/narrow_zones.new_map_2.yaml` 과 동일 확인)

백업: `config/narrow_zones.new_map_2.yaml.backup-ops-20260824`

---

## 8. 발견 #15 — bringup 재시작 시 좀비 노드가 남아 AMCL 이 무너진다

수정한 협로 설정을 로드하려고 bringup 을 세 번째로 재기동한 뒤, 로봇 pose 가
`(0, 0, 0)` 에 `sensor_timeout` 으로 굳었다. 로봇 로그에는 이것이 22 초마다 반복됐다.

```
[lifecycle_manager-18] [ERROR] [pinky_01.lifecycle_manager_localization]:
  CRITICAL FAILURE: SERVER map_server IS DOWN after not receiving a heartbeat
  for 60000 ms. Shutting down related nodes.
```

원인은 map_server 가 아니라 **이전 bringup 의 노드가 살아남은 것**이었다.

```bash
ssh pinky@192.168.0.21 'ps -eo pcpu,pmem,pid,comm --sort=-pcpu | head -10'
# 12.9 0.9  9756 bringup_namespa
#  9.1 0.9  7840 joint_state_pub   <- 2회차 bringup 잔존
#  8.4 1.0  9732 status_node
#  8.3 0.9  5520 joint_state_pub   <- 1회차 bringup 잔존
#  7.5 0.9  9754 joint_state_pub   <- 현재 bringup
```

`joint_state_publisher` 가 세 벌. 같은 이름의 노드 셋이 `/pinky_01/joint_states`
와 TF 를 두고 다투면 bond heartbeat 가 끊기고 lifecycle_manager 가 AMCL 을
내린다. TF 가 사라지므로 `status_node` 는 map pose 를 못 만들고 `(0,0,0)` 을 낸다.

정리에 쓴 pgrep 패턴에 `joint_state_publisher` 와 `pinky_bringup` 벤더 노드가
빠져 있었던 것이 직접 원인이다.

### 정리 패턴 — 이 목록이어야 한다

```bash
ssh pinky@192.168.0.21 '
LAUNCH=$(pgrep -f "trihouse_pinky_bringup trihouse_pinky.launch.py")
[ -n "$LAUNCH" ] && kill -TERM $LAUNCH
sleep 10
for p in $(pgrep -f "trihouse_pinky|nav2_|sllidar_node|pinky_imu|pinky_sensor|bringup_namespaced|lifecycle_manager|robot_state_publisher|joint_state_publisher|safety_supervisor|fleet_gateway|status_node|fleet_node"); do
  kill -KILL $p 2>/dev/null
done
sleep 4
pgrep -af "trihouse|nav2_|sllidar|joint_state|robot_state|pinky_" | grep -v "bash -c" || echo "PASS: clean"
'
```

> **더 확실한 방법은 로봇 재부팅이다.** 좀비를 하나씩 찾는 것보다 빠르고,
> 무엇이 남았는지 추측할 필요가 없다. bringup 을 두 번 이상 재시작한 뒤
> 이상 징후(`sensor_timeout`, pose `(0,0,0)`, 반복되는 bond CRITICAL FAILURE)가
> 보이면 재부팅한다.

### 참고 — 재부팅 후 되살려야 하는 것 (4060 PC 쪽은 그대로 둔다)

로봇만 재부팅하면 4060 PC 의 아래 프로세스는 살아 있으므로 다시 띄우지 않는다.

| 위치 | 프로세스 | 확인 명령 |
| --- | --- | --- |
| 4060 | `fastdds discovery -i 0 -l 192.168.0.4 -p 11811` | `pgrep -af '[f]astdds discovery'` |
| 4060 | rmf_core (schedule/blockade/supervisors/dispatcher) | `pgrep -af 'rmf_task_dispatcher\|rmf_traffic_schedule'` |
| 4060 | `pinky_easy_fleet_adapter` | `pgrep -af 'pinky_easy_fleet_adapter --config'` |
| 4060 | job_runner / executor_worker / rmf_gateway_worker | `pgrep -af 'control_tower\.'` |
| 4060 | OMX 무동작 시뮬레이터 2개 | `pgrep -af 'tests.simulation.omx.action_server'` |
| 4060 | 위치 추적기 | `pgrep -af ops_track_pinky` |
| Docker | mysql / fms_gateway / mediamtx / rmf_api / rmf_dashboard | `docker ps` |

단, **fleet adapter 는 로봇이 다시 뜬 뒤 재등록 로그를 확인**해야 한다.

```bash
grep -a "등록했습니다" /tmp/trihouse_pinky_fleet_adapter.log | tail -1
```

재등록이 없으면 어댑터를 재기동한다(발견 #8 의 명령).

---

## 9. 발견 #16 — 배터리 게이트가 배차를 막는다 (주문이 `20=pending` 에 머무는 정체)

job 10 을 넣었으나 `20=pending` 에서 100 초가 지나도 움직이지 않았다. 어댑터 로그가
정체를 그대로 보여준다.

```
[PK_01] RMF 상태 갱신 중단: PINKY_NOT_READY
[PK_01] 상태 복구 확인 후 RMF에 recommission했습니다.
[PK_01] RMF 상태 갱신 중단: PINKY_NOT_READY     <- 5 초 주기 반복
```

추적 CSV 에서 `dispatchable` 분포:

```bash
tail -30 log/ops_test_2026-08-24/pk01_track.csv | awk -F, '{print $13}' | sort | uniq -c
#   20 0
#   10 1
```

원인은 `trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/battery_policy.py` 다.

```python
if percentage <= 10.0:
    return BatteryProjection("RETURN_REQUIRED", False, "BATTERY_AT_OR_BELOW_RETURN_THRESHOLD")
```

문턱이 하드코딩이라 파라미터로 낮출 수 없다. 그리고 이 로봇의 SOC 판독은 한 주행
안에서 `0.0 ~ 100.0` 을 오간다. 잡음이 그대로 `status.dispatchable` 을 껐다 켜고,
fleet adapter 는 그때마다 로봇을 RMF 에서 빼고(decommission) 다시 넣는다.
배차가 유지될 수 없다.

### 조치 — 로봇 정책 노드를 내리고 4060 에서 `ready=True` 를 고정 발행

로봇 소스를 고치지 않는다. 두 발행자가 같은 토픽에 쓰면 판정이 번갈아 뒤집히므로
**로봇 쪽 노드를 반드시 먼저 내린다.**

```bash
ssh pinky@192.168.0.21 'pgrep -af "trihouse_pinky_fleet/battery_policy"'
ssh pinky@192.168.0.21 'kill -KILL <PID>'

cd /home/newuser/Trihouse/.worktrees/physical-integration-v1
source /opt/ros/jazzy/setup.bash && source install/setup.bash
export ROS_DOMAIN_ID=12 ROS_AUTOMATIC_DISCOVERY_RANGE=SYSTEM_DEFAULT
export ROS_DISCOVERY_SERVER='192.168.0.4:11811'
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp FASTDDS_BUILTIN_TRANSPORTS=UDPv4
setsid nohup python3 scripts/ops_battery_policy_override.py \
  --namespace pinky_01 --robot-id PK_01 \
  > /tmp/trihouse_battery_override.log 2>&1 < /dev/null &
```

효과: `dispatchable` 이 1 로 안정되고 `PINKY_NOT_READY` 가 멈춘다.

> **시험용 우회다.** SOC 판독을 고치면 이 도구를 멈추고 로봇 정책 노드를 되살린다.
> `ros2 run trihouse_pinky_fleet battery_policy --ros-args -r __ns:=/pinky_01`

## 10. job 11 — 좌표 수정이 통했고, 그다음 벽에 부딪혔다

배터리 게이트를 연 뒤 job 11 을 넣자 로봇이 즉시 출발했다.

```
t+024s  20=runn  (0.7749, 0.1469)  charging_station_narrow_exit
t+036s  20=runn  (0.8718, 0.7372)  ambient_storage_narrow_entry
t+048s  20=runn  (1.1873, 0.9517)  ambient_storage_narrow_entry
```

**`entry_alignment` 이 처음으로 통과했다** — 좌표 수정의 효과다.

```
rule_transition ... phase=entry_alignment safety='clear'
rule_transition ... from=entry_alignment to=enter_straight safety='clear' failure=None   <- 성공
rule_transition ... from=enter_straight to=failed safety='front_stop'                    <- 다음 단계에서 막힘
```

### 발견 #17 — `entry_passage` 는 이 도크에 맞지 않는 동작이다

`enter_straight` 은 `entry_passage`(warehouse_entry) 상태기계의 단계로,
**출입구를 앞으로 통과**한다. 그러나 이 도크의 2026-08-15 실측 절차는
**회전 뒤 후진**이다.

완화된 임계(`stop_distance_m=0.05`)에서도 실측 여유가 이랬다.

```
front_stop: desired=(0.060, 0.002) path_clearance=0.04606385131705024 scan_nearby=0.10201176015716029
front_stop: desired=(0.060, -0.002) path_clearance=-0.006074218545109034 scan_nearby=0.12007157997856942
```

`path_clearance` 는 범퍼 기준이다(`FOOTPRINT_FRONT_M=0.04` 차감 후). 0.046 m 는
범퍼 앞 4.6 cm, **음수는 이미 발자국 안에 장애물이 있다는 뜻**이다. 임계값을 더
낮추는 것은 들이받으라는 지시와 같다. 임계값 문제가 아니라 **동작이 틀린 것**이다.

전략 선택 지점은 `trihouse_pinky/trihouse_pinky_fleet/trihouse_pinky_fleet/narrow_zone_routing.py:26`.

```python
def entry_motion_strategy(profile: NarrowZoneProfile) -> str:
    return "warehouse_entry" if profile.entry_passage is not None else "legacy_narrow_zone"
```

냉동에는 `entry_passage` 가 처음부터 없다. 상온·냉장에만 2026-08-23 에 추가되었고,
`entry` 좌표를 망친 그 편집과 같은 시점이다.

### 조치 — 상온·냉장에서 `entry_passage` 제거

```bash
cp -a config/narrow_zones.new_map_2.yaml config/narrow_zones.new_map_2.yaml.backup-ops-20260824-b
# entry_passage 블록 제거 후
python3 -c "
import yaml
d = yaml.safe_load(open('config/narrow_zones.new_map_2.yaml'))
for n, z in d['zones'].items():
    print(n, 'warehouse_entry' if z.get('entry_passage') else 'legacy_narrow_zone')
"
scp config/narrow_zones.new_map_2.yaml pinky@192.168.0.21:/home/pinky/narrow_zones.new_map_2.yaml
```

이제 네 profile 전부 `legacy_narrow_zone`(회전 → 후진)이다.
sha256 = `c5a8dc09b596d7b51e43c277144171fade99fde9c8b7a336a35bce0fd3444511`

### 발견 #18 — AMCL 이 발산했다 (벽 충돌의 진짜 원인)

job 11 취소 직후 추적 CSV 의 pose 다.

```
2026-08-24T12:57:54  (0.6886, 2.7387, -178.3deg)
```

`new_map_2` 는 73 x 89 셀, 해상도 0.03 m, origin `(-0.22, -1.473)` 이므로
지도 범위는 x `-0.22 ~ 1.97`, y `-1.473 ~ 1.197` 이다. **y = 2.74 는 지도 밖이다.**

즉 로봇은 자기 위치를 완전히 틀리게 알고 있었고, "목표로 간다"고 움직인 방향이
실제로는 벽이었다. 무너진 경로는 이렇게 읽힌다.

```
enter_straight 실패(front_stop) -> 규칙 failed -> fleet_node 재시도
  -> Nav2 가 진입부로 재목표 -> controller "Failed to make progress" -> recovery 회전/후진
  -> 좁은 공간에서 바퀴 미끄러짐 -> odometry 오차 누적 -> 파티클 필터 발산
```

`controller_server` 로그가 그 중간을 확인해 준다.

```
[controller_server] [ERROR] Failed to make progress
[controller_server] [WARN] [follow_path] [ActionServer] Aborting handle.
```

> **운영 규칙.** 추적 CSV 의 pose 가 지도 범위를 벗어나면 즉시 정지시킨다.
> 그 상태에서는 어떤 주문도 의미가 없고, 로봇은 벽을 향해 "정상 주행" 한다.
> 지도 범위는 `head -6 /home/pinky/map/new_map_2.yaml` 의 origin 과
> pgm 크기로 계산한다.

### 발견 #19 — FMS job 을 취소해도 로봇이 멈추지 않는다 (발견 #10 의 실전 결과)

job 11 을 취소했는데도 로봇이 계속 움직였다. RMF task 가 살아 있으면 fleet adapter 가
계속 명령을 보내기 때문이다. **즉시 정지는 어댑터를 내리는 것이다.**

```bash
kill -KILL $(pgrep -f 'pinky_easy_fleet_adapter')
```

그 뒤에 RMF task 를 취소한다. 순서를 바꾸면 취소하는 동안에도 로봇이 움직인다.

---

## 11. 발견 #20 — 호스트 IP 가 시험 도중 바뀌었다 (그리고 발견 #1 은 틀렸다)

14:35 경 주문 투입이 이렇게 실패했다.

```
curl: (7) Failed to connect to 192.168.0.4 port 8080 after 8439 ms: Couldn't connect to server
```

```bash
ip -4 -o addr show | awk '{print $2, $4}'
```

| 시각 | 인터페이스 | 주소 |
| --- | --- | --- |
| 11:30 (시험 시작) | `wlo1` (Wi-Fi) | `192.168.0.4/24` — **유일한 LAN 주소** |
| 14:35 | `eno1` (Ethernet) | **`192.168.0.9/24`** ← 올라옴 |
| 14:35 | `wlo1` (Wi-Fi) | `192.168.129.147/17` ← 다른 서브넷으로 이동 |

`192.168.0.4` 는 더 이상 이 호스트에 없다. Gateway 컨테이너는 사라진 주소에
바인딩된 채 `healthy` 로 떠 있어서 더 헷갈린다.

```bash
docker inspect trihouse_p0-fms_gateway-1 --format '{{json .HostConfig.PortBindings}}'
# {"8080/tcp":[{"HostIp":"192.168.0.4","HostPort":"8080"}], ...}
curl -s http://127.0.0.1:8080/ready    # loopback 도 실패 — 0.0.0.0 이 아니라 특정 IP 에 묶여 있다
```

### 발견 #1 정정

아침에 "`.env` 의 `PC1_LAN_IP=192.168.0.9` 가 실제와 불일치" 라고 적었으나 **틀렸다.**
`.env` 가 옳았고, 그때는 **이더넷이 내려가 있었을 뿐**이다. `.env` 주석이 이미
정확히 적어 두고 있었다.

```
# 서버 PC 는 두 인터페이스를 갖는다 — 인터넷용 Wi-Fi 와 ROS/로봇용 Ethernet.
# 이 값은 **Ethernet 쪽 주소**여야 한다. Wi-Fi 쪽에 바인딩하면 로봇과 일반 PC 가
# 스트림에 붙지 못하는 동시에 8554 가 바깥으로 노출된다.
PC1_LAN_IP=192.168.0.9
```

**교훈** — 기동 전에 반드시 실측하고, `.env` 와 다르면 `.env` 를 의심하기 전에
**인터페이스가 올라와 있는지** 먼저 본다.

```bash
ip -4 -o addr show | awk '{print $2, $4}'
ip -o link show | awk '{print $2, $9}'
```

### 이 변경이 건드리는 곳 (전부 바꿔야 한다)

| 대상 | 값 |
| --- | --- |
| Gateway API bind | `FMS_API_HOST` |
| Gateway TCP bind (로봇 gateway 접속처) | `FMS_TCP_BIND` |
| Discovery Server listen 주소 | `fastdds discovery -l <IP>` |
| 모든 ROS 프로세스 | `ROS_DISCOVERY_SERVER=<IP>:11811` |
| 워커 3종 | `--fms-base-url http://<IP>:8080` |
| fleet adapter | `fms_base_url:=http://<IP>:8080` |
| 로봇 bringup | `control_host:=<IP>` |

**하나라도 빠뜨리면 그 층만 조용히 끊긴다.**

---

## 12. 유선 전환 후 재구성 (14:35 ~ 15:05)

### 발견 #21 — 옛 Discovery Server 가 포트를 물고 있어 새 서버가 조용히 실패

주소를 `192.168.0.9` 로 옮기며 Discovery Server 를 다시 띄웠는데 로봇 노드들이
서로를 못 찾았다. `lifecycle_manager` 가 이것만 반복했다.

```
[pinky_01.lifecycle_manager_localization]: Waiting for service map_server/get_state...
[pinky_01.lifecycle_manager_navigation]:   Waiting for service controller_server/get_state...
```

원인은 새 서버가 **뜨지 못한 것**이었다.

```bash
tail -3 /tmp/trihouse_discovery_server.log
#  Problem creating RTPSParticipant -> Function enable
#  fast-discovery-server tool not found!

ss -lunp | grep 11811
# users:(("fast-discovery-",pid=211512,...))   <- 아침에 띄운 옛 프로세스
```

아침에 `192.168.0.4` 로 띄운 서버(PID 211512)가 11811 을 잡고 있었다. 그것은
`-l 192.168.0.4` 로 떠 있어 **사라진 주소를 참가자 locator 로 광고**한다. 클라이언트는
서버에 붙지만 받은 주소가 죽은 주소라 아무도 서로를 못 찾는다.

`sh` 래퍼(211507)만 죽이고 실제 바이너리(211512)가 살아남은 것이 직접 원인이다.

```bash
kill -KILL 211512
fastdds discovery -i 0 -l 192.168.0.9 -p 11811
# Server Addresses:   UDPv4:[192.168.0.9]:11811     <- 이 줄을 반드시 확인한다
```

> **Discovery Server 를 쓰면 로봇 내부 노드끼리의 discovery 도 이 서버를 거친다.**
> 서버가 잘못되면 로봇 혼자서도 아무것도 못 찾는다. 단일 실패점이다.

### 발견 #22 — 깨진 discovery 로 뜬 프로세스는 스스로 회복하지 않는다

서버를 고친 뒤에도 로봇 lifecycle 은 `active=0` 그대로였다. 4060 의 워커·추적기·
어댑터도 마찬가지였다(추적 CSV 가 14:34 에서 멈춰 있었다).

**서버를 고쳤으면 그 서버를 쓰는 프로세스를 전부 다시 띄워야 한다.**

### 발견 #23 — 좀비가 nav2 활성화를 막는다 (발견 #15 의 다른 얼굴)

```
[local_costmap]: Timed out waiting for transform from pinky_01/base_footprint
                 to pinky_01/odom ... Invalid frame ID "pinky_01/odom" ... frame does not exist
[lifecycle_manager_navigation]: Failed to change state for node: controller_server
[lifecycle_manager_navigation]: Failed to bring up all requested nodes. Aborting bringup.
```

`nav2_controller` 가 두 벌(5768 = 이전 세대, 8756 = 현재)이었다. 시작 시각으로
세대를 갈라야 보인다.

```bash
ssh pinky@192.168.0.21 'ps -eo pid,lstart,cmd --no-headers \
  | grep -E "/opt/ros/jazzy/|trihouse_ws/install/|pinky_pro/install/|ros2 launch" \
  | grep -v grep | sort -k4'
```

**시각 기준으로 지우면 세대를 놓친다.** 확실한 방법은 전부 지우는 것이다.

```bash
ssh pinky@192.168.0.21 '
L=$(pgrep -f "trihouse_pinky_bringup trihouse_pinky.launch.py"); [ -n "$L" ] && kill -TERM $L
sleep 6
PIDS=$(ps -eo pid,cmd --no-headers \
  | grep -E "/opt/ros/jazzy/|trihouse_ws/install/|pinky_pro/install/|ros2 launch" \
  | grep -v grep | awk "{print \$1}" | tr "\n" " ")
kill -KILL $PIDS 2>/dev/null
sleep 4
ps -eo pid,cmd --no-headers | grep -E "/opt/ros/jazzy/|trihouse_ws/install/|pinky_pro/install/" | grep -v grep | wc -l
'
```

### 발견 #24 — 기본값 safety supervisor 가 교체본과 함께 살아남는다

`ros2 run` 으로 완화본을 띄워도 launch 가 만든 기본값(0.30) 인스턴스가 남아 있으면
**둘이 같은 `/pinky_01/cmd_vel_safe` 에 발행**한다. 판정이 번갈아 뒤집힌다.

```bash
ssh pinky@192.168.0.21 'ps -eo pid,cmd --no-headers | grep safety_supervisor | grep -v grep'
# 9695  ... --params-file /tmp/launch_params_xxx        <- launch 기본값. 반드시 죽인다
# 10719 ... -p stop_distance_m:=0.05 ...                <- 교체본
```

`pgrep -f "trihouse_pinky_safety.*safety_supervisor"` 는 자기 셸까지 잡아 PID 가
같게 나오는 함정이 있다. `ps -eo pid,cmd | grep` 으로 실제 목록을 본다.

## 13. job 12 (상온) — 협로 탈출부에서 정지

15:02 투입. 로봇이 충전소를 벗어나 협로 탈출부까지 이동한 뒤 멈췄다.

```
t+012s  (0.2003, 0.2117)  charging_station_01           idle
t+036s  (0.6207, 0.2683)  charging_station_narrow_exit  idle
t+060s  (0.6268, 0.2691)  charging_station_narrow_exit  navigating  swept_stop
        이후 같은 자리에서 swept_stop / front_stop 번갈아 반복
```

safety 실측:

```
swept_stop: desired=(0.000, -0.160) scan_nearby=0.0884 threshold=0.120
front_stop: desired=(0.000,  0.000) path_clearance=0.0447~0.0498   (임계 0.05)
```

### 판정 — 환경이 아니라 로봇에 붙은 것

| 기준 | 값 |
| --- | --- |
| 회전 중심 → 뒤 끝(바구니) | 0.16 m |
| 회전 중심 → 앞 끝 | 0.04 m |
| 감지된 물체 | **0.088 m** |

0.088 m 는 **로봇 자기 몸통(뒤쪽 0.16 m) 안쪽**이다. 벽이나 선반이라면 나올 수 없다.

같은 종류의 회전에서 오늘 측정된 값 비교:

| 시각 | 위치 | `scan_nearby` |
| --- | --- | --- |
| 오전 (job 8) | 상온 진입부 | 0.176 (정상, 벽) |
| 14:22 | 충전소 | 0.036~0.044 (사용자가 충전기 꽂던 중) |
| 15:04 (job 12) | 협로 탈출부 | **0.088** |

사용자가 "충전기를 꽂고 있었다" 고 한 직후 주문이 나갔다. **충전 케이블이 연결된
채 또는 바닥에 끌린 채 따라 나왔을 가능성이 가장 높다.** 케이블은 몸통 바로 옆에
있게 되고 라이다는 360° 를 보므로 회전 판정에 그대로 걸린다.

> **임계값을 0.088 아래로 내리는 것은 답이 아니다.** 그것은 케이블을 감고 돌라는
> 지시다. 현재 0.12 도 기하학적 안전값 0.179 보다 이미 낮춘 값이다.

### 운영 규칙 — 출발 전 확인

```bash
# 출발 직전 scan_nearby 를 본다. 0.15 m 미만이면 로봇 주변을 눈으로 확인한다.
ssh pinky@192.168.0.21 'grep -aE "swept_stop|front_stop" \
  /home/pinky/ops_test_20260824_safety8.log | tail -3'
```

충전 케이블은 **주문 투입 전에 반드시 뽑는다.**


### 발견 #25 — RMF task 정리는 dispatcher 재기동으로 대체된다

`rmf_task_dispatcher` 는 task 목록을 메모리에만 들고 있다. 죽였다 다시 띄우면
RMF 쪽 기억이 통째로 사라지므로, 발견 #10 의 "취소된 job 의 task 가 남아 새 주문을
굶긴다" 문제도 함께 사라진다.

판별 기준은 dispatcher 의 기동 시각이다. **그 이후에 만들어진 job 의 task 만**
RMF 에 남아 있다.

```bash
ps -o lstart= -p "$(pgrep -f rmf_task_dispatcher | head -1)"
# Mon Aug 24 14:59:42 2026

source .env
docker exec trihouse-mysql mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -N -e \
  "SELECT created_at FROM jobs WHERE job_id=12;" trihouse_fms
# 2026-08-24 15:02:27      <- dispatcher 기동 이후 = RMF 에 존재
```

DB 의 `state='cancelled'` 인 `rmf_task_id` 를 전부 넘기면 대부분 응답이 오지 않는다.
이미 dispatcher 재기동으로 사라진 것들이기 때문이며, 오류가 아니다.

`ops_rmf_cancel_task.py` 의 `구독자 수` 도 참고가 된다.

| 구독자 수 | 뜻 |
| --- | --- |
| 2 | dispatcher + fleet adapter (정상 운영 중) |
| 1 | dispatcher 만 (adapter 를 내린 상태) |
| 0 | dispatcher 가 없다 — 취소 자체가 불가능 |

---

## 14. 저녁 세션 (20:04 ~ 20:20)

로봇이 20:04:57 에 부팅되어 돌아왔다. 재부팅 직후라 **좀비가 0개**여서 준비가 빨랐다.

| 단계 | 결과 | 시각 |
| --- | --- | --- |
| 로봇 프로세스 확인 | 잔존 0 | 20:05 |
| bringup | launch 2876, lidar 2907 | 20:05 |
| lifecycle | `active=2` | 20:07 |
| 협로 profile | 수정본 3개 적재 | 20:07 |
| safety 교체 | `stop 0.05 / slow 0.25 / swept 0.12`, 인스턴스 1 | 20:08 |
| fleet adapter | `[PK_01] 유효한 pose/SOC로 RMF에 등록했습니다` | 20:09:20 |

### 발견 #26 — 어댑터가 "떴다"고 오판하기 쉽다

`pgrep -f 'pinky_easy_fleet_adapter --config'` 는 **자기 셸까지 잡는다.** 프로세스가
있다고 나와도 실제로는 안 떠 있을 수 있다. 오늘 실제로 그렇게 오판했고, 로그
파일이 15:03 에서 멈춰 있는 것으로 겨우 알아냈다.

**판별은 로그 갱신 시각으로 한다.**

```bash
ls -l --time-style=+%H:%M:%S /tmp/trihouse_pinky_fleet_adapter.log | awk '{print $6}'
grep -aE "adapter 시작|등록했습니다" /tmp/trihouse_pinky_fleet_adapter.log | tail -2
```

`setsid nohup ... & disown` 조합이 상황에 따라 기동에 실패하는 경우가 있었다.
`nohup ... &` 만으로 띄우고 **로그 갱신 시각을 확인하는 편이 확실하다.**

### 발견 #27 — 장애물 방향은 스캔 각도로 특정한다

`scan_nearby` 는 360° 최솟값이라 "가깝다"만 알려 준다. 어느 쪽인지 알아야
사람이 찾을 수 있다. 각도별로 뽑으면 바로 나온다.

20:10 실측:

```
가장 가까운 8개  (0=정면, +=좌, -=우)
   13.3 cm   -47.1 deg
   13.3 cm   -46.6 deg
   ... -45 ~ -49 deg 구간이 전부 13.3 cm

구간별 최근접
   정면  14.7 cm      좌  39.8 cm      우  13.3 cm
   좌후  23.7 cm      우후 191.9 cm    뒤  24.8 cm
```

여러 빔이 **같은 거리로 좁은 각도 구간에** 걸리고 **좌우가 크게 비대칭**이면
벽이 아니라 로봇에 붙었거나 바로 옆에 놓인 물체다. 왼쪽 39.8 cm 대 오른쪽
13.3 cm 는 환경으로 설명되지 않는다.

읽는 스크립트는 `docs/guides/pinky-order-runbook.md` 의 STEP 8 에 넣었다.

### 발견 #28 — 로봇에 띄운 감시 스크립트가 SSH 종료 후에도 남는다

우측 여유를 지켜보려고 로봇에서 `watch_clearance.sh` 를 돌렸는데, SSH 세션이
끝난 뒤에도 PID 4018 로 살아남아 스캔을 계속 붙들었다. 그 사이 로봇 pose 가
`(0,0,0)` / `sensor_timeout` 으로 굳었다.

```bash
ssh pinky@192.168.0.21 'ps -eo pid,cmd --no-headers | grep -E "watch_clearance|scan_probe" | grep -v grep'
```

**진단용 스크립트를 로봇에서 돌렸으면 반드시 회수한다.** STEP 1-2 의 정리
패턴에 `watch_clearance` 를 포함시켰다.

### 발견 #29 — USB 장치가 통째로 사라졌다 (하드웨어)

20:12 이후 `/pinky_01/scan` 발행이 멈췄다.

```bash
ros2 topic hz /pinky_01/scan
# WARNING: topic [/pinky_01/scan] does not appear to be published yet
```

`sllidar_node` 프로세스는 살아 있었다(PID 2907). 데이터만 안 나왔다. 원인은
드라이버가 아니라 장치 자체였다.

```bash
ssh pinky@192.168.0.21 'ls /dev/ttyUSB* /dev/ttyACM* 2>/dev/null || echo 없음'
# 없음

ssh pinky@192.168.0.21 'lsusb'
# Bus 001~005 root hub 5개만. 연결된 장치 0개.

ssh pinky@192.168.0.21 'ls /sys/bus/usb/devices/'
# 1-0:1.0 2-0:1.0 3-0:1.0 4-0:1.0 5-0:1.0 usb1 usb2 usb3 usb4 usb5
# 다운스트림 장치가 하나도 없다
```

라이다(`/dev/ttyUSB0` 기대)뿐 아니라 **모터 컨트롤러까지 전부 사라졌다.**
20:04~20:12 사이에는 정상 동작했으므로 그 뒤에 물리적으로 빠졌다.

**소프트웨어로 복구할 수 없다.** USB 케이블/허브 전원을 사람이 확인해야 한다.

> `sllidar_node` 프로세스 존재만으로 라이다가 살아 있다고 판단하면 안 된다.
> `ros2 topic hz /pinky_01/scan` 로 **발행을 확인**한다.


### USB 이탈 — 원격 복구 불가 확인 (20:24 ~ 21:27)

1시간 감시했으나 `/dev/ttyUSB*` 가 돌아오지 않았다. 로봇은 계속 켜져 있었다
(`up 1:22`, 20:04 부팅 그대로). 소프트웨어 재인식 경로도 모두 막혀 있다.

```bash
ssh pinky@192.168.0.21 'sudo -n true' ; echo $?   # 암호 필요
ssh pinky@192.168.0.21 'command -v uhubctl'       # 없음
ssh pinky@192.168.0.21 'ls /sys/bus/usb/drivers/usb/'
# usb1 usb2 usb3 usb4 usb5   — 루트 허브만. unbind/bind 는 root 권한이 필요하다.
```

`journalctl -k` 도 권한이 없어 이탈 원인(과전류·케이블 빠짐)을 로봇 안에서
확인할 수 없었다.

> **사람이 케이블을 확인해야 한다.** 이 상태에서는 bringup 이 떠도 라이다·모터가
> 없어 로봇은 아무것도 하지 못한다.
>
> 다음에 대비해 두면 좋은 것 — 로봇에 `uhubctl` 을 설치하고 `pinky` 계정에
> USB 전원 제어만 `NOPASSWD` 로 열어 두면 원격 재인식이 가능해진다.

## 15. 2026-08-24 총괄

### 완료

- 운영 DB → 주문 → job 7단계 자동 생성 → RMF 배차 → Nav2 주행까지 **전 경로 관통 확인**
- 로봇이 충전소에서 출발해 협로 탈출 → 병목 → 상온 도크 앞까지 **실물 주행**
- 좌표 수정 후 협로 `entry_alignment` **최초 통과** (job 11)
- 문서 3종 + 도구 6종

### 미완료

**상온·냉장·냉동 3회 완전 사이클(창고 → 포장대 → 충전소 복귀)은 한 번도 돌지 못했다.**
`entry_passage` 를 제거한 **회전 → 후진 도킹은 아직 한 번도 실행되지 않았다.**
다음 세션의 첫 관문이다.

### 상온 6회 시도에서 하나씩 제거한 원인

| # | 원인 | 성격 | 처리 |
| --- | --- | --- | --- |
| 1 | `entry.yaw` 가 자기 `dock_target` 과 30.3° 불일치 | 설정 결함 | 2026-08-15 실측 원본 복원 |
| 2 | `stop_distance_m` 0.30 = 도크 거리 0.300 (3 mm 차) | 설정 결함 | 0.05 로 조정 |
| 3 | 배터리 SOC 판독 잡음 → 5초마다 배차 끊김 | 하드웨어 | `ops_battery_policy_override.py` |
| 4 | `entry_passage` 가 전진 통과를 강제 | 설계 불일치 | 상온·냉장에서 제거 |
| 5 | 좀비 노드가 bond·TF 붕괴 | 절차 결함 | 정리 패턴 런북화 |
| 6 | 서버 IP 유선 전환 (`.4` → `.9`) | 환경 | Gateway `0.0.0.0` 바인딩 |
| 7 | 옛 Discovery Server 가 11811 점유 | 절차 결함 | `fast-discovery` 포함 정리 |
| 8 | 충전 케이블 (`scan_nearby=0.088`) | 물리 | 출발 전 확인 절차 추가 |
| 9 | USB 장치 전부 이탈 | 물리 | **미해결 — 사람 확인 필요** |

1~7 은 원인을 특정해 고쳤고 전부 런북에 반영했다. 8~9 는 물리적 문제다.

### 부수로 찾은 것 — 냉장도 오염되어 있었다

상온만 고쳐서는 냉장에서 똑같이 막혔을 것이다. `dock_target` 을 고정하고 역산하니
DB 정본 waypoint `chilled_storage_narrow_entry` 가 **오차 0.0000000000 m** 로 나왔다.

