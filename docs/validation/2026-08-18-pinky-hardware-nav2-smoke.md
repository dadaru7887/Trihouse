# 실기 Pinky — Nav2 + 온보드 패키지 + 카메라 수동 확인 (2026-08-18)

## 0. 이 문서의 범위

**관제(FMS Gateway)·RMF·주문은 쓰지 않는다.** 로봇 한 대를 켜서 다음 셋만 본다.

| 무엇 | 확인하는 것 |
|---|---|
| Nav2 | lifecycle 활성, `map -> base` 변환, 목표 하나 주행 |
| 온보드 패키지 | `trihouse_pinky_io` / `_safety` / `_fleet` / `_bringup` 가 실제 값을 낸다 |
| 카메라 | RTSP 가 MediaMTX 에 도달하고 `stream_health` 가 healthy |

확인하지 **않는** 것: 주문 → job → RMF dispatch → 완주. 그것은
[2026-08-18-p0-manual-test.md](2026-08-18-p0-manual-test.md) 와
[sim-to-hardware 계획서 Task 7](../claude/2026-08-18-sim-to-hardware-p0-order-completion.md) 이 다룬다.

이 테스트에서 `control_link_offline` 오류가 나는 것은 **정상이다.** 관제를 안 켰기
때문이다. 그 오류만 남고 나머지가 비어 있으면 통과다.

## 1. 안전

바퀴를 바닥에서 띄우거나 전방 2 m 이상 비운다. 비상정지를 손 닿는 곳에 둔다.
7절(주행)에 가기 전까지는 로봇이 스스로 움직이지 않는다 — 6절까지는 관측만 한다.

`/cmd_vel` 발행자는 **`safety_supervisor` 하나여야 한다.** Nav2 는 `cmd_vel_nav`
로 나가고 safety 가 그것을 받아 모터용 `cmd_vel` 을 단독으로 소유한다. 발행자가
둘이면 안전 gate 를 우회하는 경로가 생긴 것이므로 즉시 멈춘다.

## 2. 전제

### 도메인은 52 다

```bash
export ROS_DOMAIN_ID=52
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
```

시뮬은 0, 실기는 52 이며 **절대 섞지 않는다.** 도메인이 다르면 같은 이름의
`pinky_01` 이 서로를 보지 못한다. 로봇과 이 PC 의 값이 같아야 한다.

### source 는 3단이다

```bash
cd /home/syw/Trihouse
source /opt/ros/jazzy/setup.bash
source install/setup.bash
source pinky_pro/install/setup.bash
```

하나라도 빠지면 메시지 타입이나 벤더 패키지를 찾지 못한다.

## 3. 빌드

`pinky_pro` 를 source 한 **뒤에** 빌드한다. 벤더 패키지에 의존하는 것이 있다.

```bash
colcon build --symlink-install \
  --packages-select \
    trihouse_interfaces \
    trihouse_pinky_io \
    trihouse_pinky_safety \
    trihouse_pinky_fleet \
    trihouse_pinky_bringup \
    trihouse_pinky_vision
```

벤더와 자체 패키지가 모두 보이는지 확인한다.

```bash
for pkg in pinky_bringup pinky_navigation trihouse_pinky_bringup trihouse_pinky_vision; do
  printf '%-24s %s\n' "$pkg" "$(ros2 pkg prefix $pkg 2>&1)"
done
```

넷 다 경로를 출력해야 한다.

## 4. Nav2 파라미터 — 분기 A 인지 B 인지 먼저 정한다

벤더 `pinky_navigation/launch/bringup_launch.xml` 은 params 를 `<param from>` 으로
그대로 넘기고 `RewrittenYaml` 을 쓰지 않는다. 그래서 **namespace 를 쓰면** 벤더
params 의 맨 키(`amcl:`, `controller_server:` …)가 `/pinky_01/amcl` 노드와
매칭되지 않아 **파라미터가 한 개도 적용되지 않는다.**

**분기 A — namespace 를 쓴다 (`pinky_01`).** 파생 params 를 만든다.

```bash
scripts/derive_hardware_nav2_params.py \
  --source pinky_pro/pinky_navigation/params/nav2_params.yaml \
  --namespace pinky_01 \
  --output .trihouse/p0/nav2/hardware_pinky_01.yaml

head -1 .trihouse/p0/nav2/hardware_pinky_01.yaml
```

기대: 첫 줄이 `pinky_01:`. 이 파일을 로봇으로 복사한다.

**분기 B — namespace 없이 단일 로봇.** nav2 노드가 루트에 있어 벤더 맨 키가 그대로
맞는다. 파생하지 않고 벤더 기본 params 를 쓴다(`nav2_params_file` 를 주지 않는다).

로봇 한 대만 켜는 이 테스트에서는 **B 가 더 단순하다.** 다만 이후 두 대로 갈
것이라면 A 로 해 두는 편이 낫다. 아래 명령은 A 를 기준으로 적고 B 는 차이만 밝힌다.

## 5. 기동

로봇에서. 지도 파일과 `map_revision` 은 관제에서 발행한 것과 같아야 한다.

```bash
ros2 launch trihouse_pinky_bringup trihouse_pinky.launch.py \
  robot_id:=PK_01 \
  namespace:=pinky_01 \
  map:=/path/to/map.yaml \
  map_revision:=trihouse_test_01:730111d2e446f5141c5ef069e5f2c1c8c5383aea79bdeffd05d3d34f2094b7ff \
  nav2_params_file:=/path/to/hardware_pinky_01.yaml \
  vision_enabled:=true \
  2>&1 | tee /tmp/hw.log
```

분기 B 는 `namespace:=''` 로 주고 `nav2_params_file` 을 뺀다.

`control_host` 는 주지 않는다 — 기본값 `127.0.0.1:8788` 로 두면 `fleet_gateway`
가 붙지 못하고 `control_link_offline` 만 남는다. 이 테스트에서는 그것이 의도다.

아래 명령은 **다른 셸**에서 돌린다. 2절의 export 와 source 를 그 셸에서도 한다.

## 6. 위에서부터 하나씩 확인한다

층을 건너뛰면 어느 층의 문제인지 말할 수 없게 된다. 실패하면 그 자리에서 멈춘다.

### 6.1 Nav2 lifecycle

```bash
grep -c 'Managed nodes are active' /tmp/hw.log
grep -E 'Failed to bring up all requested|Failed to change state' /tmp/hw.log
```

기대: 첫 명령이 **2**(localization 1 + navigation 1), 두 번째가 빈 출력.

실기에는 Gazebo 도 두 번째 로봇도 없다. 시뮬에서 이 단계를 무너뜨리던 부하 문제가
여기에는 없으므로, **여기서 실패하면 부하가 아니라 실제 결함이다.**

### 6.2 벤더 센서 — 여기부터 값이 있어야 위층이 산다

```bash
NS=/pinky_01   # 분기 B 면 NS= (빈 값)

ros2 topic echo --once $NS/scan       sensor_msgs/msg/LaserScan      | head -5
ros2 topic echo --once $NS/odom       nav_msgs/msg/Odometry          | head -5
ros2 topic echo --once $NS/batt_state sensor_msgs/msg/BatteryState
ros2 topic echo --once $NS/us_sensor/range sensor_msgs/msg/Range
```

넷 다 값이 나와야 한다. **`batt_state` 와 `us_sensor/range` 가 여기서 비면 6.3 은
반드시 빈다** — 그 어댑터들이 이 둘을 그대로 받아 옮기기 때문이다.

이 넷이 `$NS` 아래가 아니라 루트에 있다면 벤더 bringup 이 namespace 를 물지 않은
것이다. 분기 B 로 다시 하거나 launch 의 `PushRosNamespace` 적용을 확인한다.

### 6.3 내가 만든 어댑터가 값을 옮기는가 (`trihouse_pinky_io`)

```bash
ros2 topic echo --once $NS/trihouse/battery        sensor_msgs/msg/BatteryState
ros2 topic echo --once $NS/trihouse/proximity/front sensor_msgs/msg/Range
```

`battery_adapter` 는 `batt_state` → `trihouse/battery`, `ultrasonic_adapter` 는
`us_sensor/range` → `trihouse/proximity/front` 로 옮긴다. 6.2 는 나오는데 여기가
비면 **어댑터 노드가 안 떠 있거나 namespace 밖에 있다.**

```bash
ros2 node list | grep -E 'battery_adapter|ultrasonic_adapter|led_indicator|buzzer_indicator|destination_display'
```

다섯 개가 `$NS` 아래에 보여야 한다.

### 6.4 LED·부저·표시를 실제로 켜 본다

여기까지는 관측만 했다. 이제 명령을 넣는다. **로봇이 움직이지는 않는다.**

**`trihouse/indicator/state` 에 직접 publish 하지 않는다.** `safety_supervisor`
가 같은 토픽을 **20 Hz(50 ms 주기)로 계속 발행**하므로 수동으로 넣은 값은 그
자리에서 덮어씌워진다. LED 와 부저는 safety 상태의 **결과**이지 입력이 아니다.
실제 경로로 켠다.

**비상 표시 — LED 와 부저를 함께 켠다**

```bash
ros2 topic pub --once $NS/trihouse/safety/emergency_request \
  std_msgs/msg/Bool '{data: true}'
```

기대: LED 가 비상 색으로 바뀌고 부저가 운다. **눈과 귀로 확인하는 단계다.**

같은 순간 safety 가 `cmd_vel` 을 0 으로 잠근다. 확인한다.

```bash
ros2 topic echo --once $NS/trihouse/indicator/state trihouse_interfaces/msg/IndicatorState
ros2 topic echo --once $NS/trihouse/safety/state     trihouse_interfaces/msg/SafetyState
```

기대: `IndicatorState.state: 2`(EMERGENCY), `SafetyState.state: 3`(EMERGENCY),
`latched: true`.

**해제 — 래치는 서비스로만 풀린다**

`emergency_request` 에 `false` 를 보내도 풀리지 않는다. 래치이기 때문이다.
`operator_id` 가 비어 있으면 거부된다.

```bash
ros2 service call $NS/trihouse/safety/clear_emergency \
  trihouse_interfaces/srv/ClearEmergency \
  '{robot_id: "PK_01", operator_id: "W-OP-01", request_id: "manual-led-1", reason: "led check done"}'
```

기대: `accepted=true`. LED 가 꺼지고 `SafetyState.latched` 가 `false` 로 돌아온다.

**7 절(주행)로 가기 전에 반드시 해제한다.** 래치가 남아 있으면 로봇은 목표를 받고도
움직이지 않는다.

**사람 감지 표시 (LED 만, 부저 없음)**

`STATE_PERSON_DETECTED` 는 사람이 보호 거리 안에 있을 때 켜진다. 카메라 없이
확인하려면 감지 메시지를 직접 넣는다. `ttl_ms` 안에서만 유지되므로 `--once` 가
아니라 반복 발행해야 눈으로 볼 수 있다.

```bash
ros2 topic pub -r 5 $NS/trihouse/vision/person_detection/base \
  trihouse_interfaces/msg/PersonDetection \
  '{confidence: 0.9, ttl_ms: 1000, pose: {pose: {position: {x: 0.3, y: 0.0, z: 0.0}}}}'
```

기대: LED 가 사람 감지 색으로 바뀐다. `Ctrl-C` 로 멈추면 `ttl_ms` 뒤 꺼진다.

**목적지 표시(OLED)**

이 토픽은 `destination_display` 만 구독하고 다른 발행자가 없으므로 직접 넣어도 된다.

```bash
ros2 topic pub --once $NS/trihouse/display/destination_code \
  std_msgs/msg/String '{data: "WH-AMB-01-DOCK-01"}'
```

`font_path` 를 주지 않았으면 기본 폰트를 쓴다. 글자가 깨지면 launch 에
`font_path:=/usr/share/fonts/...` 를 준다.

**LED 가 안 바뀔 때**

`led_indicator_client` 는 벤더 `set_led` 서비스를 부른다. 그 서비스부터 본다.

```bash
ros2 service list | grep set_led
ros2 service type $NS/set_led
```

### 6.5 안전·준비·상태 (`_safety`, `_bringup`, `_fleet`)

```bash
ros2 topic echo --once $NS/trihouse/safety/state    trihouse_interfaces/msg/SafetyState
ros2 topic echo --once $NS/trihouse/readiness       trihouse_interfaces/msg/Readiness
ros2 topic echo --once $NS/trihouse/battery/condition trihouse_interfaces/msg/BatteryCondition
ros2 topic echo --once $NS/trihouse/battery/policy_state trihouse_interfaces/msg/BatteryPolicyState
```

읽는 곳:

- `SafetyState.state` — `0=CLEAR` 이어야 주행이 허용된다. `2=STOP`/`3=EMERGENCY`
  면 `source` 와 `detail` 이 누가 걸었는지 알려 준다.
- `Readiness.missing_interfaces` — **비어 있어야 한다.** 무엇이 아직 안 왔는지
  이름으로 알려 주므로 6.2~6.4 중 어디로 돌아갈지 여기서 정해진다.
- `BatteryCondition.telemetry_fresh` — `true`. `false` 면 `batt_state` 가 끊긴 것이다.
- `BatteryPolicyState.state` — `1=NORMAL` 이면 정상. `reason_code` 가 아니면
  무엇 때문인지 말해 준다.

`/cmd_vel` 발행자가 하나인지 여기서 확인한다.

```bash
ros2 topic info $NS/cmd_vel
ros2 topic info $NS/cmd_vel_nav
```

`cmd_vel` 의 Publisher count 는 **1** 이어야 하고 그것이 `safety_supervisor` 다.

### 6.6 종합 판정

관제 PC 든 로봇이든, 도메인 52 인 셸에서:

```bash
ROS_DOMAIN_ID=52 python3 scripts/verify_robot_status.py pinky_01 20
```

기대:

```
publishers      : {'status': 1, 'scan': 1, 'amcl_pose': 1}
frame_id        : map
dispatchable    : true
errors          : ['control_link_offline']
```

- `publishers` 가 전부 **1**. 2 이상이면 이전 세대가 남아 있고 나머지 값은 못 믿는다.
- `frame_id` 가 **`map`**. `pinky_01/odom` 이면 AMCL 이 위치추정을 못 하고 있다 —
  초기 pose 를 주지 않았을 때 가장 흔하다.
- `errors` 에 **`control_link_offline` 만** 남는 것이 이 테스트의 통과 조건이다.
  관제를 안 켰으므로 그것은 결함이 아니다.

분기 B 라면 토픽이 루트에 있으므로 이 스크립트의 namespace 인자를 그에 맞게 준다.

### 6.7 카메라

**카메라 영상은 ROS 토픽으로 나가지 않는다.** `camera_streamer` 가 `rpicam-vid`
와 `ffmpeg` 로 MediaMTX 에 RTSP 를 밀고, 서버가 그것을 읽어 QR·ArUco 를 본다.
그래서 확인이 두 갈래다.

**(1) ROS 쪽 — 송신 상태만 나온다**

```bash
ros2 topic echo --once $NS/trihouse/vision/stream_health \
  trihouse_interfaces/msg/StreamHealth
```

기대: `state: 1`(HEALTHY), `fps` 가 설정값 15 근처, `camera_id: CAM-PK-01`.
`3`(DISCONNECTED)이면 MediaMTX 에 못 붙은 것이니 (2) 로 간다.

설정 정본은 `trihouse_pinky/trihouse_pinky_vision/config/pinky_1.yaml` 이고
송신 주소는 `rtsp://<PC1_LAN_IP>:8554/pinky/CAM-PK-01` 이다. 로봇에서 그 주소가
닿는지 먼저 본다.

```bash
nc -z <PC1_LAN_IP> 8554 && echo 'mediamtx reachable'
```

**(2) 서버 쪽 — 프레임이 실제로 오는가**

MediaMTX 가 도는 PC 에서:

```bash
docker ps --format '{{.Names}}' | grep mediamtx
docker logs --tail 50 trihouse_p0-mediamtx-1 2>&1 | grep -i 'CAM-PK-01\|publish\|auth'
```

프레임 한 장을 실제로 받아 본다.

```bash
cd /home/syw/Trihouse
source .venv/bin/activate 2>/dev/null || true
python3 - <<'PY'
import os, cv2
url = os.environ.get("VISION_RTSP_URL", "rtsp://127.0.0.1:8554/pinky/CAM-PK-01")
capture = cv2.VideoCapture(url)
ok, frame = capture.read()
capture.release()
print("url  :", url)
print("frame:", "received" if ok else "NOT received")
if ok:
    print("shape:", frame.shape)
PY
```

기대: `frame: received`, `shape: (720, 1280, 3)`.

QR 디코더까지 보려면:

```bash
python3 - <<'PY'
import os, cv2
from model.worker.marker.edge_perception import VisionPerception
capture = cv2.VideoCapture(os.environ["VISION_RTSP_URL"])
ok, frame = capture.read()
capture.release()
assert ok, "RTSP frame not received"
print(VisionPerception().detect_qr(frame))
PY
```

화면에 QR 이 없으면 `None` 이 정상이다. **`None` 이어도 스트림 도달과 디코더
동작은 확인된다** — 이 단계의 목적은 그것이다.

MediaMTX 인가는 발행을 **주소로** 제한한다. 로봇 IP 가 DHCP 로 바뀌면 발행이
거부된다. `config/mediamtx.yml` 과 위의 `grep -i auth` 로 확인한다.

## 7. 주행 한 번 — Nav2 에 직접 목표를 준다

**여기서 로봇이 움직인다.** 1절의 안전 조건을 다시 확인한다.

6.5 의 `SafetyState.state` 가 `0=CLEAR` 인지 먼저 본다. `CLEAR` 가 아니면 safety
가 `cmd_vel` 을 막으므로 로봇은 어차피 움직이지 않는다.

초기 pose 를 준다. 이것을 건너뛰면 AMCL 이 지도 전체에 입자를 흩뿌린 채 시작하고,
그 실패는 로봇이 움직이기 시작한 뒤에야 보인다.

```bash
ros2 topic pub --once $NS/initialpose \
  geometry_msgs/msg/PoseWithCovarianceStamped \
  '{header: {frame_id: "map"}, pose: {pose: {position: {x: 0.065, y: 0.227, z: 0.0},
    orientation: {z: 0.0, w: 1.0}}}}'
```

좌표는 로봇이 실제로 서 있는 자리다. 위 값은 `charging_station_01` 예시다.

목표를 준다. **가까운 곳부터.** 0.3 m 정도면 충분하다.

```bash
ros2 action send_goal $NS/navigate_to_pose nav2_msgs/action/NavigateToPose \
  '{pose: {header: {frame_id: "map"}, pose: {position: {x: 0.351, y: -0.49, z: 0.0},
    orientation: {z: 0.0, w: 1.0}}}}' --feedback
```

관측한다.

```bash
ros2 topic echo $NS/trihouse/navigation/state trihouse_interfaces/msg/NavigationState
ros2 topic echo $NS/cmd_vel geometry_msgs/msg/Twist
```

기대: `cmd_vel` 에 0 이 아닌 값이 흐르고 로봇이 목표로 간다. action 이
`SUCCEEDED` 로 끝난다.

멈추려면 비상 래치를 건다 — safety 가 `cmd_vel` 을 즉시 0 으로 잠근다.

```bash
ros2 topic pub --once $NS/trihouse/safety/emergency_request \
  std_msgs/msg/Bool '{data: true}'
```

풀 때는 6.4 의 `clear_emergency` 서비스를 쓴다. `emergency_request` 에 `false` 를
보내도 풀리지 않는다.

**물리 비상정지가 항상 우선이다.** 위 명령은 보조 수단이지 대체 수단이 아니다.

## 8. 정리

로봇에서 launch 를 `Ctrl-C` 로 내린다. 이 문서의 절차는 **관제 PC 의 Docker 층을
건드리지 않는다** — `scripts/sim_teardown.sh` 는 시뮬용이며 여기서는 쓰지 않는다.

## 9. 함정

- **`ros2 topic echo` 에 타입을 같이 준다.** 타입 없이 부르면 그래프에서 타입을
  찾는데, 참가자가 많거나 부하가 높으면 그 열거가 멈춘다. 위 명령들이 전부
  `<토픽> <타입>` 형태인 이유다.
- **`pkill -f <패턴>` 을 직접 쓰지 않는다.** 명령줄에 패턴이 들어가서 자기 자신을
  죽인다.
- **`status_node` 를 고치면 재빌드해야 한다.** install 이 복사본이다. launch 파일은
  symlink 이므로 재빌드가 필요 없다.
- **절대 토픽 이름(`/scan`)을 소스에 적으면 namespace 가 통째로 무시된다.**
  `test_namespace_contract.py` 가 이것을 지킨다.
- **`vision_config_file` 을 빈 문자열로 주지 않는다.** `camera_streamer` 가 빈
  문자열을 params 파일로 읽으려다 죽는다. 주지 않으면 기본값이 쓰인다.
- **도메인 0 과 52 를 섞지 않는다.** 시뮬이 떠 있는 PC 에서 실기를 보려면 그 셸의
  `ROS_DOMAIN_ID` 가 52 인지 매번 확인한다.

## 10. 결과 기록

각 절의 실제 출력을 아래에 붙인다. **실패한 것을 성공한 것과 함께 그대로 적는다.**

| 절 | 항목 | 결과 | 비고 |
|---|---|---|---|
| 6.1 | Nav2 lifecycle `Managed nodes are active` = 2 | | |
| 6.2 | `scan` / `odom` / `batt_state` / `us_sensor/range` | | |
| 6.3 | `trihouse/battery` / `trihouse/proximity/front` | | |
| 6.4 | LED / 부저 / OLED 표시 | | |
| 6.5 | `safety/state` / `readiness` / 배터리 정책 / `cmd_vel` 발행자 1 | | |
| 6.6 | `verify_robot_status.py` — `frame_id=map`, `dispatchable=true` | | |
| 6.7 | `stream_health` HEALTHY / RTSP 프레임 수신 | | |
| 7 | `navigate_to_pose` SUCCEEDED | | |
