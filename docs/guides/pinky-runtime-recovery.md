# Pinky 기동 전 프로세스 정리와 배터리 복구

## 목적

이 문서는 Pinky에서 이전 `trihouse_pinky` launch가 남아 새 launch와 중복되거나,
`/battery/percent`는 정상인데 `/trihouse/battery.percentage`가 `.nan`으로 남는 경우를
복구하는 절차다. 실제 실기 점검에서 다음 순서로 복구하고 확인한 과정을 일반화했다.

```text
기존 launch와 남은 자식 노드 확인
→ 모든 기존 Pinky launch 종료
→ 고아 Trihouse 노드 종료
→ ROS/Fast DDS 환경 재설정
→ Pinky launch 하나만 재기동
→ 원본 배터리 → adapter 출력 → 최종 status 순서로 확인
```

이 절차는 프로세스를 종료하며, 실행 중인 주행 명령과 Nav2도 함께 중단된다. 로봇을
바닥에서 띄우거나 주행 공간을 비우고, 비상정지 담당자가 준비된 상태에서 수행한다.

## 정상 배터리 값의 단위

배터리 값은 토픽마다 단위가 다르다.

- `/battery/percent` (`std_msgs/msg/Float32`): Pinky 벤더 값, `0~100`
- `/trihouse/battery.percentage` (`sensor_msgs/msg/BatteryState`): ROS 표준 비율, `0.0~1.0`
- `/trihouse/status.battery_percentage`: 관제 표시용 퍼센트, `0~100`

예를 들어 `/battery/percent`가 `68.0`이면 `/trihouse/battery.percentage`는 약 `0.68`이어야
한다. 전압이 유한하고 0보다 크면 `/trihouse/battery.present`는 `true`여야 한다.

## 0. 모든 에러에 공통인 로그 수집 → 분기 STEPS

오류가 나면 launch를 바로 여러 번 다시 실행하지 않는다. 먼저 아래 읽기 전용 명령으로
**process, launch log, ROS status**를 같은 시각에 남긴다. 예시 log file은 이 문서의
launch command와 같을 때 사용한다. 다른 log file로 시작했다면 실제 경로를 쓴다.

```bash
# pinky@ Pinky: process와 최근 launch error
pgrep -af '[r]os2 launch trihouse_pinky_bringup trihouse_pinky.launch.py'
pgrep -af '[s]afety_supervisor|[f]leet_node|[f]leet_gateway|[b]attery_adapter|[a]mcl|[m]ap_server'
tail -n 120 /tmp/trihouse_pinky.log
grep -aE 'ERROR|FATAL|Traceback|process has died|Failed to bring up|Failed to change state' \
  /tmp/trihouse_pinky.log | tail -n 60

# pinky@ Pinky: command를 보내지 않는 ROS status 확인
timeout 10 ros2 topic echo /trihouse/readiness trihouse_interfaces/msg/Readiness --once
timeout 10 ros2 topic echo /trihouse/status trihouse_interfaces/msg/RobotStatus --once
timeout 10 ros2 topic echo /trihouse/safety/state trihouse_interfaces/msg/SafetyState --once
ros2 topic info /cmd_vel_safe --verbose
```

개발 PC의 Control Tower/network error도 동시에 확인한다.

```bash
# pc@ 개발 PC
ip route get <pinky-ip>
nc -vz -w 3 <pinky-ip> 22
nc -vz -w 3 <control-pc-ip> 8788
```

| log·관측 | 원인 판단 | 처리 명령 또는 다음 절 |
| --- | --- | --- |
| `process has died`, Python `Traceback` | 코드/의존성/launch 설정 오류 | 오류가 난 package만 4절 방식으로 build 후 3→5절 재기동 |
| launch 또는 동일 node가 두 개 이상 | 중복 launch·고아 process | 2절 확인 후 3절의 `SIGINT`/전용 PID 종료, 하나만 5절로 기동 |
| `RTPS_TRANSPORT_SHM ... open_and_lock_file failed` | Fast DDS SHM lock 충돌 | 1절의 `FASTDDS_BUILTIN_TRANSPORTS=UDPv4`를 새 terminal/새 launch에 적용 |
| readiness/status timeout | DDS·overlay·sensor/node 중 하나 미준비 | 1절 environment를 비교하고 7절(TF/Nav2), 8절(battery), 16절(Discovery Server)을 순서대로 확인 |
| `/trihouse/status.ready: false` 또는 `errors`가 비지 않음 | 주문 불가 status | `errors`의 첫 항목을 원인으로 삼아 해당 interface부터 recovery; action/order를 보내지 않음 |
| `/cmd_vel_safe` publisher가 Safety Supervisor 외 node이거나 motor path가 불명확 | final safety-control ownership 위반 | 9절에서 remap/subscriber를 확인하고, 원인이 확인될 때까지 launch와 order를 중지 |

이 표는 진단 순서를 정한 것이며, hardware wiring·실물 장애물·E-stop 문제를 remote command로
우회하는 절차가 아니다. SafetyState가 `CLEAR`가 아니거나 현장 시야가 확보되지 않았으면
모든 transport action을 보류한다.

## 1. Pinky 터미널 환경 설정

아래 명령은 모두 **Pinky 터미널**에서 실행한다. 경로가 다른 Pinky에서는 먼저
`docs/guides/pinky-package-deployment.md`에 따라 실제 workspace를 확인하고 값을 바꾼다.

```bash
source /opt/ros/jazzy/setup.bash
source /home/pinky/pinky_pro/install/setup.bash
source /home/pinky/trihouse_ws/install/setup.bash

export ROS_DOMAIN_ID=12
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export FASTDDS_BUILTIN_TRANSPORTS=UDPv4
```

`FASTDDS_BUILTIN_TRANSPORTS=UDPv4`는 실기 점검 중 발생했던
`RTPS_TRANSPORT_SHM Error ... open_and_lock_file failed`를 피하기 위해 사용한다. 개발 PC,
Pinky, OMX가 통신할 때는 `ROS_DOMAIN_ID`와 RMW 구현도 서로 같아야 한다.

## 2. 기동 전에 기존 프로세스 확인

먼저 종료 대상을 읽기 전용으로 확인한다.

```bash
echo '=== Pinky launch processes ==='
pgrep -af \
  '[r]os2 launch trihouse_pinky_bringup trihouse_pinky.launch.py' ||
  echo 'PASS: launch clean'

echo '=== possibly orphaned Trihouse nodes ==='
pgrep -af \
  '[b]attery_adapter|[r]eadiness_checker|[s]tatus_node|[f]leet_node|[r]ecovery_health|[f]leet_gateway|[s]afety_supervisor' ||
  echo 'PASS: Trihouse child clean'
```

둘 다 `PASS`이면 3단계의 종료 명령은 건너뛸 수 있다. PID가 출력되면 중복 launch나
고아 노드가 존재하므로 다음 단계에서 정리한다.

## 3. 기존 Pinky launch와 고아 노드 종료

실행 중인 모든 동일 Pinky launch에 먼저 `SIGINT`를 보내 ROS가 정상 종료할 시간을 준다.

```bash
LAUNCH_PIDS="$(
  pgrep -f \
    '/opt/ros/jazzy/bin/ros2 launch trihouse_pinky_bringup trihouse_pinky.launch.py' || true
)"

if [ -n "$LAUNCH_PIDS" ]; then
  kill -INT $LAUNCH_PIDS
  sleep 8
fi
```

launch가 종료되었는데도 이전에 생성된 Trihouse 자식 노드가 남았다면 해당 workspace의
노드에만 `SIGTERM`을 보낸다.

```bash
ORPHAN_PIDS="$(
  pgrep -f '/home/pinky/trihouse_ws/install/trihouse_pinky_' || true
)"

if [ -n "$ORPHAN_PIDS" ]; then
  ps -fp $ORPHAN_PIDS
  kill -TERM $ORPHAN_PIDS
  sleep 5
fi
```

정리 결과를 확인한다.

```bash
pgrep -af \
  '[r]os2 launch trihouse_pinky_bringup trihouse_pinky.launch.py' ||
  echo 'PASS: launch clean'

pgrep -af \
  '/home/pinky/trihouse_ws/install/trihouse_pinky_' ||
  echo 'PASS: Trihouse child clean'
```

두 `PASS`가 모두 나와야 새 launch를 시작한다. 프로세스가 계속 남으면 `kill -KILL`을
바로 사용하지 말고 `ps -fp <PID>`로 명령행을 확인해 다른 실험 프로세스가 아닌지 먼저
판단한다.

## 4. 배터리 adapter 코드가 갱신된 경우에만 다시 빌드

`battery_adapter.py`를 Pinky로 새로 전송한 직후라면 해당 패키지만 빌드한다. 코드가
바뀌지 않았다면 이 단계는 건너뛴다.

```bash
cd /home/pinky/trihouse_ws

source /opt/ros/jazzy/setup.bash
source /home/pinky/pinky_pro/install/setup.bash

colcon build \
  --symlink-install \
  --executor sequential \
  --packages-select trihouse_pinky_io \
  --event-handlers console_direct+

source /home/pinky/trihouse_ws/install/setup.bash
```

`Summary`에 실패가 없어야 다음 단계로 간다.

## 5. Pinky launch 하나만 재기동

개발 PC의 현재 Pinky 연결용 IPv4 주소를 `CONTROL_HOST`에 넣는다. 예를 들어 개발 PC에서
`ip route get <pinky-ip>`를 실행했을 때 `src 192.168.0.4`가 나오면 아래 값은
`192.168.0.4`다.

```bash
export CONTROL_HOST='192.168.0.4'
export PINKY_MAP='/home/pinky/map/new_map_2.yaml'
export MAP_REVISION='new_map_2:f6c507e469fd34eebc70ad8d6a6fcf23ff5d51d0c0704cf7bc3dd36762155e47'

NAV2_PARAMS="$(
  ros2 pkg prefix pinky_navigation
)/share/pinky_navigation/params/nav2_params.yaml"

nohup ros2 launch \
  trihouse_pinky_bringup \
  trihouse_pinky.launch.py \
  namespace:=/ \
  robot_id:=PK_01 \
  map:="$PINKY_MAP" \
  map_revision:="$MAP_REVISION" \
  nav2_params_file:="$NAV2_PARAMS" \
  control_host:="$CONTROL_HOST" \
  control_port:=8788 \
  vision_enabled:=false \
  docking_enabled:=false \
  > /tmp/trihouse_pinky.log 2>&1 &

echo $! | tee /tmp/trihouse_pinky_launch.pid
sleep 8
```

`namespace:=/`를 `namespace:=`처럼 빈 값으로 쓰면 launch 인자 형식 오류가 난다. 이
가이드는 실제 단일 Pinky 점검에서 사용한 루트 namespace 구성을 따른다.

launch가 하나만 존재하는지 확인한다.

```bash
echo '=== launch count ==='
pgrep -af \
  '[r]os2 launch trihouse_pinky_bringup trihouse_pinky.launch.py'

echo '=== recorded launch process ==='
ps -p "$(cat /tmp/trihouse_pinky_launch.pid)" \
  -o pid,ppid,stat,etimes,%cpu,%mem,args

echo '=== fatal launch errors ==='
grep -aE \
  'ERROR|FATAL|process has died|Failed to bring up|Failed to change state|Traceback' \
  /tmp/trihouse_pinky.log | tail -30
```

정상 기준은 launch 명령행이 한 개이고 기록한 PID가 살아 있으며, 마지막 명령에 치명적
오류가 없는 것이다.

## 6. 배터리 복구 확인

원본 퍼센트부터 순서대로 확인한다. 각 명령은 최대 대기시간 안에 메시지 하나를 받아야
한다.

```bash
echo '=== vendor percent: expected 0..100 ==='
timeout 12 ros2 topic echo \
  /battery/percent \
  std_msgs/msg/Float32 \
  --once

echo '=== vendor voltage ==='
timeout 12 ros2 topic echo \
  /batt_state \
  sensor_msgs/msg/BatteryState \
  --once

echo '=== Trihouse battery: expected percentage 0.0..1.0, present true ==='
timeout 12 ros2 topic echo \
  /trihouse/battery \
  sensor_msgs/msg/BatteryState \
  --once
```

같은 시점의 정상적인 변환 예시는 다음과 같다.

```text
/battery/percent: data: 68.0
/trihouse/battery: voltage: 7.95...
/trihouse/battery: percentage: 0.68...
/trihouse/battery: present: true
```

실기 복구 과정에서는 서로 다른 시점에 원본 `data: 100.0`, 변환 출력
`percentage: 0.680000007...`, `present: true`를 각각 확인했다. 원본과 변환 출력을
연속으로 조회하는 사이에도 배터리 측정값은 달라질 수 있으므로, 두 숫자가 완전히 같은
시점의 표본이라고 간주하지 않는다.

원본 `/battery/percent`는 정상인데 `/trihouse/battery.percentage`만 `.nan`이면 새
`battery_adapter`가 아닌 이전 프로세스를 보고 있을 가능성이 높다. 2~3단계로 돌아가
중복 `battery_adapter`를 정리하고, 코드가 갱신된 경우 4단계 빌드 후 다시 기동한다.

## 7. 최종 readiness와 status 확인

배터리 메시지가 정상이어도 주문 실행 준비가 끝났다는 뜻은 아니다. 준비 상태와 최종
로봇 상태를 각각 확인한다.

```bash
echo '=== readiness ==='
timeout 12 ros2 topic echo \
  /trihouse/readiness \
  trihouse_interfaces/msg/Readiness \
  --once

echo '=== final robot status ==='
timeout 12 ros2 topic echo \
  /trihouse/status \
  trihouse_interfaces/msg/RobotStatus \
  --once
```

실기 점검에서 최종 통과한 핵심 값은 다음과 같았다.

```text
/trihouse/readiness:
  state: 1
  missing_interfaces: []

/trihouse/status:
  battery_percentage: 61.98...
  battery_policy.ready: true
  battery_policy.reason_code: BATTERY_NORMAL
  safety.detail: clear
  telemetry_valid: true
  execution_ready: true
  dispatchable: true
  ready: true
  errors: []
```

`ready: true`와 `errors: []`가 모두 확인되어야 관제 주문 단계로 넘어간다. 이 검증은
배터리와 인터페이스 준비를 증명하지만, 모터 안전 경로·초기 위치·Nav2 lifecycle·OMX
준비 상태까지 자동으로 증명하지는 않는다.

## 실패 판정표

| 관측 결과 | 판정 | 다음 조치 |
|---|---|---|
| 동일 Pinky launch가 두 개 이상 | 중복 기동 | 3단계에서 모두 종료 후 하나만 재기동 |
| launch 종료 후 `battery_adapter` 등이 남음 | 고아 프로세스 | 해당 Trihouse workspace PID만 `SIGTERM` |
| Fast DDS SHM 잠금 오류 | 공유 메모리 전송 초기화 실패 | `FASTDDS_BUILTIN_TRANSPORTS=UDPv4` 설정 후 재확인 |
| `/battery/percent`가 안 나옴 | 벤더 배터리 퍼센트 입력 없음 | `pinky_sensor_adc`와 vendor bringup 상태 확인 |
| 원본 퍼센트 정상, 변환 퍼센트 `.nan` | adapter 미수신 또는 이전 adapter 잔존 | 중복 제거, 필요 시 IO 패키지 재빌드·재기동 |
| 전압 정상인데 `present: false` | 이전 adapter 또는 잘못된 overlay 가능성 | `ros2 pkg prefix trihouse_pinky_io`와 실행 PID 경로 확인 |
| status에 `battery_not_dispatchable` | 배터리 정책 준비 실패 | `/trihouse/battery`부터 다시 추적 |
| status에 `scan_stale` 또는 `nav_unavailable` | 배터리와 별개의 센서/Nav2 문제 | 주문하지 말고 scan, TF, Nav2 lifecycle을 별도로 점검 |

---

# new_map_2 냉동창고 규칙 주행 사전 점검 기록

## 현재 검증 범위

이 절은 2026-08-23 `PK_01` 실기 점검에서 **주행 명령을 보내기 직전까지** 통과한
환경과 복구 과정을 기록한다. 현재 로봇은 충전 중이며 다음 명령은 아직 수행하지 않는다.

- FMS 냉동 주문 생성
- RMF task dispatch
- `/trihouse/transport/execute` action goal 전송
- `/cmd_vel*` 직접 발행

따라서 이 절의 상태는 `PRE-DRIVE READY`이지 냉동창고 도킹 성공이 아니다. 실제 주행이
성공한 뒤 action 명령, 결과, 최종 pose와 안전 상태를 이 파일에 이어서 기록한다.

## 이번 실기의 확정값

```bash
export PINKY_TARGET='pinky@192.168.0.22'
export CONTROL_PC_IP='192.168.0.4'
export ROS_DOMAIN_ID=12
export MAP_FILE='/home/pinky/map/new_map_2.yaml'
export MAP_REVISION='new_map_2:df9a7f70eab87135a0e1a73c2b63a0a15aae2de3512a6c760a3259d0337a32ed'
export NARROW_PROFILE='/home/pinky/narrow_zones.new_map_2.yaml'
```

장비나 Wi-Fi가 바뀌면 IP를 그대로 재사용하지 않는다. 개발 PC에서 다음 결과의 `src`를
`CONTROL_PC_IP`로 사용한다.

```bash
ip -br addr
ip route get 192.168.0.22
```

## 터미널 역할

주행 전 점검에는 논리적으로 다음 세 역할이 필요하다. background 실행과 로그 파일을
사용하면 개발 PC 창 두 개, Pinky 창 한 개로 운영할 수 있다.

1. 개발 PC: Fast DDS Discovery Server, Docker FMS, RMF core, RMF adapter
2. Pinky: vendor/Trihouse bringup, localization, Nav2, safety
3. 개발 PC 감시: status, FMS/RMF 로그, 최종 go/no-go 판정

모든 역할에서 `ROS_DOMAIN_ID`, RMW 구현과 discovery 구성을 같게 한다.

## 1. Discovery Server 복구

### 실패 증상

- 양방향 일반 UDP와 ROS multicast probe는 통과하지만 `/trihouse/status`가 개발 PC에서
  보이지 않는다.
- Pinky 내부에서는 status publisher가 보이지만 개발 PC adapter에는 publisher count가
  0으로 나온다.
- `ros2 node list` 또는 `ros2 lifecycle get`이 실제 프로세스가 존재하는데도 간헐적으로
  `Node not found`를 출력한다.

### 복구

개발 PC에서 Discovery Server를 한 개만 실행한다.

```bash
pgrep -af '[f]astdds discovery' || {
  nohup fastdds discovery \
    -i 0 \
    -l 192.168.0.4 \
    -p 11811 \
    > /tmp/trihouse_discovery_server.log 2>&1 &
  echo $! > /tmp/trihouse_discovery_server.pid
}
```

개발 PC와 Pinky의 **새로 시작할 모든 ROS 프로세스**에 다음 환경을 사용한다.

```bash
export ROS_DOMAIN_ID=12
export ROS_AUTOMATIC_DISCOVERY_RANGE=SYSTEM_DEFAULT
unset ROS_STATIC_PEERS
export ROS_DISCOVERY_SERVER='192.168.0.4:11811'
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export FASTDDS_BUILTIN_TRANSPORTS=UDPv4
```

이 구성은 기존 `SUBNET` 설정을 실행 중인 프로세스에 덮어쓰는 것이 아니다. 프로세스는
시작할 때 환경을 읽으므로 Pinky bringup, RMF core와 adapter를 새 환경에서 다시 시작해야
한다.

Discovery Server 자체의 데이터 경로는 임시 토픽으로 확인할 수 있다. 아래 probe는 모터
명령을 발행하지 않는다.

개발 PC:

```bash
timeout 45 ros2 topic echo \
  --no-daemon \
  --spin-time 5 \
  /dds_server_probe \
  std_msgs/msg/String \
  --once
```

Pinky:

```bash
ros2 topic pub \
  --once \
  --max-wait-time-secs 15 \
  /dds_server_probe \
  std_msgs/msg/String \
  '{data: discovery-server-ok}'
```

개발 PC에 `data: discovery-server-ok`가 나와야 한다. Fast DDS SHM port 잠금 오류는
`FASTDDS_BUILTIN_TRANSPORTS=UDPv4`로 피한다.

### 실행 중 Discovery Server가 종료된 경우

2026-08-23 냉동 재시험 사전 점검에서 다음 증상이 새로 발생했다.

```text
Pinky launch와 readiness/status/safety 프로세스는 모두 살아 있음
개발 PC와 Pinky 로컬 모두 /trihouse/readiness timeout
pgrep -af '[f]astdds discovery' → 결과 없음
UDP 11811 listener 없음
discovery log 마지막 줄 → Server shut down
```

Discovery Server를 같은 주소로 다시 시작했지만 기존 Pinky participant는 제한시간 안에
자동 재연결되지 않았다. 따라서 다음 순서로 복구했다.

1. Discovery Server를 `setsid`의 독립 session으로 재기동한다.
2. UDP 11811 listener와 server PID를 확인한다.
3. 기존 Pinky launch의 전용 process group만 종료한다.
4. 동일한 `ROS_DISCOVERY_SERVER` 환경으로 Pinky bringup을 재기동한다.
5. readiness, safety, status를 실제 메시지로 다시 확인한다.

```bash
setsid nohup fastdds discovery \
  -i 0 \
  -l 192.168.0.4 \
  -p 11811 \
  > /tmp/trihouse_discovery_server.log 2>&1 < /dev/null &

echo $! > /tmp/trihouse_discovery_server.pid
sleep 3

ps -p "$(cat /tmp/trihouse_discovery_server.pid)" \
  -o pid,pgid,sid,stat,etimes,args
ss -lunp | grep ':11811'
```

복구 후 실제 확인값은 다음이었다.

```text
/trihouse/readiness.state: 1
/trihouse/readiness.missing_interfaces: []
/trihouse/safety.state: 0
/trihouse/safety.detail: clear
/trihouse/status.frame_id: map
/trihouse/status.ready: true
```

## 2. FMS 주소와 Docker bind 복구

### 실패 증상

```text
failed to bind host port 192.168.0.9:8080/tcp: cannot assign requested address
```

유선 주소 `192.168.0.9`가 사라지고 Wi-Fi 주소가 `192.168.0.4`로 바뀌었는데 이전 주소로
컨테이너를 bind한 것이 원인이었다.

### 복구

```bash
ip route get 192.168.0.22

export FMS_API_HOST='192.168.0.4'
export FMS_TCP_BIND='192.168.0.4'

docker compose \
  -p trihouse_p0 \
  -f compose.yaml \
  -f compose.control.yaml \
  up -d --wait mysql fms_gateway

curl -fsS http://192.168.0.4:8080/ready | python3 -m json.tool
nc -vz -w 3 192.168.0.4 8788
```

Pinky launch의 `control_host`도 같은 현재 주소를 사용한다.

## 3. 지도와 revision 동기화

Pinky가 사용하는 지도는 PC workspace 경로가 아니라 다음 장비 로컬 파일이다.

```text
/home/pinky/map/new_map_2.yaml
/home/pinky/map/new_map_2.pgm
```

지도 파일과 PC publish artifact가 같은지 checksum으로 확인한다.

```bash
ssh pinky@192.168.0.22 \
  'sha256sum /home/pinky/map/new_map_2.yaml /home/pinky/map/new_map_2.pgm'
```

이번에 publish된 revision은 다음이다.

```text
new_map_2:df9a7f70eab87135a0e1a73c2b63a0a15aae2de3512a6c760a3259d0337a32ed
```

Pinky launch, `/trihouse/status.map_revision`, FMS published map과 RMF adapter의
`map_revision`이 모두 이 문자열과 같아야 한다. `첫 버전` 같은 설명 문자열을 대신 넣지
않는다.

MySQL 좌표 round-trip에서 약 `1e-16` 차이 때문에 동일한 물리 좌표가 다르다고 판정되어
publish가 실패했던 경우, 현재 소스의 물리값 비교 로직이 포함된 FMS Gateway 이미지를
다시 빌드하고 컨테이너를 재기동했다. DB 값을 임의로 반올림해 덮어쓰지 않는다.

## 4. 중복 launch와 고아 노드 복구

### 실패 증상

- `kill -INT <launch-pid>` 후에도 launch가 남는다.
- launch PID가 두 개이거나 launch가 사라진 뒤 `battery_adapter`, `fleet_node`, Nav2가
  남는다.
- 동일 이름의 ROS 노드가 여러 개 보이고 Pinky가 느려지거나 SSH banner가 지연된다.

### 복구

먼저 전용 launch의 PID와 process group을 확인한다.

```bash
PID="$(pgrep -f \
  '^/usr/bin/python3 /opt/ros/jazzy/bin/ros2 launch trihouse_pinky_bringup trihouse_pinky.launch.py( |$)' \
  | head -1)"

ps -p "$PID" -o pid,ppid,pgid,sid,stat,etimes,args
```

`PGID`가 해당 `setsid` launch 전용임을 확인한 경우에만 그룹을 종료한다.

```bash
PGID="$(ps -o pgid= -p "$PID" | tr -d ' ')"
kill -TERM -- "-$PGID"
sleep 8
```

남은 노드를 확인한다.

```bash
pgrep -af '[r]os2 launch trihouse_pinky_bringup' || echo 'PASS: launch stopped'
pgrep -af \
  '[s]afety_supervisor|[p]inky_bringup/bringup|[v]elocity_smoother|[f]leet_node' ||
  echo 'PASS: motion nodes stopped'
```

process group에 사용자 shell이나 다른 실험이 포함됐는지 확인하지 않고 음수 PGID로
종료하면 안 된다. 전용 그룹이 아닐 때는 이 문서 3절의 개별 고아 노드 정리 절차를 쓴다.

## 5. 냉동 규칙 파일의 올바른 배포

개발 PC 원본과 Pinky 실행 파일은 다음 두 경로다.

```text
개발 PC: config/narrow_zones.new_map_2.yaml
Pinky:   /home/pinky/narrow_zones.new_map_2.yaml
```

현재 냉동 규칙은 다음 원본의 `narrow_3` 값을 사용한다.

```text
/home/newuser/Downloads/j_narrow3_rule_based_docking_1.py
```

확정된 원본값은 다음이다.

```text
entry = (0.9198039894575488, -1.1892528962848725, -0.03242978898931081)
entry_zone = length 0.10 m, width 0.20 m
enter = straight 0.325 m
        rotate to -0.9057963267948966 rad
        straight -0.338 m
```

원본 Python에는 별도의 최종 dock pose가 없다. YAML의 다음 값은 위 동작을 entry에서
적분한 **검증 전 예상값**이다.

```text
dock_target = (1.036067117750, -0.933812857015, -0.9057963267948966)
```

파일을 전송하고 checksum을 비교한다.

```bash
rsync -avc --itemize-changes \
  config/narrow_zones.new_map_2.yaml \
  pinky@192.168.0.22:/home/pinky/narrow_zones.new_map_2.yaml

sha256sum config/narrow_zones.new_map_2.yaml
ssh pinky@192.168.0.22 \
  'sha256sum /home/pinky/narrow_zones.new_map_2.yaml'
```

이번 배포에서 두 파일의 checksum은 다음과 같았다.

```text
2bef085cf59cd63c71bfadc594d2f9a9b258676627eb82a13f2a3b5e0f6ea19a
```

YAML 로더와 규칙 계약 테스트도 통과해야 한다.

```bash
pytest -q \
  trihouse_pinky/test/test_narrow_zone_profiles.py \
  trihouse_pinky/test/test_narrow_zone_pilot.py
```

이번 결과는 `20 passed, 3 skipped`였다.

### 잘못된 profile 실패 사례

`narrow_zones.new_map_2.zone_tour.yaml`은 창고의 `approach_required: false`를 사용하므로
냉동 최종 좌표를 Nav2가 직접 목표로 삼는다. 규칙 도킹 시험에서는 이 파일을 사용하지
않는다.

또한 이전 `narrow_zones.new_map_2.yaml`에는 `waypoint.md` 기반의 다음 값이 들어 있어
사용자가 지정한 Python 원본과 달랐다.

```text
straight 0.20 → rotate -1.572140 → straight -0.372569
```

이를 위의 Python 원본값으로 교체하고 PC/Pinky checksum을 다시 맞췄다.

## 6. 단일 Pinky bringup

Pinky 터미널에서 underlay와 overlay를 순서대로 source한다.

```bash
source /opt/ros/jazzy/setup.bash
source /home/pinky/pinky_pro/install/setup.bash
source /home/pinky/trihouse_ws/install/setup.bash

export ROS_DOMAIN_ID=12
export ROS_AUTOMATIC_DISCOVERY_RANGE=SYSTEM_DEFAULT
unset ROS_STATIC_PEERS
export ROS_DISCOVERY_SERVER='192.168.0.4:11811'
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export FASTDDS_BUILTIN_TRANSPORTS=UDPv4

export MAP_REVISION='new_map_2:df9a7f70eab87135a0e1a73c2b63a0a15aae2de3512a6c760a3259d0337a32ed'
NAV2_PARAMS="$(ros2 pkg prefix pinky_navigation)/share/pinky_navigation/params/nav2_params.yaml"
```

새 launch를 독립 session/process group으로 시작한다.

```bash
setsid nohup ros2 launch \
  trihouse_pinky_bringup \
  trihouse_pinky.launch.py \
  namespace:=/ \
  robot_id:=PK_01 \
  map:=/home/pinky/map/new_map_2.yaml \
  map_revision:="$MAP_REVISION" \
  nav2_params_file:="$NAV2_PARAMS" \
  narrow_zones_file:=/home/pinky/narrow_zones.new_map_2.yaml \
  narrow_map_name:=new_map_2 \
  allow_narrow_calibration:=false \
  control_host:=192.168.0.4 \
  control_port:=8788 \
  vision_enabled:=false \
  docking_enabled:=false \
  > /tmp/trihouse_pinky_rule.log 2>&1 < /dev/null &

echo $! > /tmp/trihouse_pinky_rule.pid
sleep 12
```

`trihouse_pinky.launch.py`는 OMX adapter를 시작하지 않는다. OMX는 별도 장비 또는 개발 PC
시험 worker가 담당한다.

다음 확인은 주행을 시작하지 않는다.

```bash
ps -p "$(cat /tmp/trihouse_pinky_rule.pid)" \
  -o pid,pgid,sid,stat,etimes,args

grep -a '협로 profile' /tmp/trihouse_pinky_rule.log | tail -2

grep -aE \
  'FATAL|process has died|Traceback|Failed to bring up|Failed to change state' \
  /tmp/trihouse_pinky_rule.log | tail -30
```

명령행에 반드시 다음이 있어야 한다.

```text
narrow_zones_file:=/home/pinky/narrow_zones.new_map_2.yaml
```

## 7. localization, TF와 Nav2 복구

### 실패 증상

- `/map_server`는 `active [3]`인데 `/amcl`이 `unconfigured [1]` 또는 `inactive [2]`다.
- lifecycle manager startup 결과가 `success=False`다.
- `/initialpose` publisher는 전송했지만 `map` frame이 없다.
- TF에 `//base_link`, `//rplidar_link` 같은 이중 slash가 나온다.

### 복구 순서

1. launch가 하나인지 확인한다.
2. `/tf_static` frame에 이중 slash가 없는지 확인한다.
3. map server와 AMCL lifecycle을 확인한다.
4. 실제 로봇 위치를 지도에서 확인한 뒤에만 initial pose를 발행한다.
5. 첫 discovery 경고가 아닌 실제 TF 샘플을 기다린다.

```bash
timeout 8 ros2 topic echo \
  /tf_static tf2_msgs/msg/TFMessage \
  --qos-reliability reliable \
  --qos-durability transient_local \
  --once | grep -E 'frame_id:|child_frame_id:'

for node in map_server amcl; do
  echo "=== /$node ==="
  timeout 8 ros2 lifecycle get "/$node"
done
```

AMCL이 active이고 로봇의 실물 시작 위치가 확인된 뒤 발행한다. 아래 좌표는 이번 시작점
예시이며 다른 위치에 놓았다면 그대로 사용하면 안 된다.

```bash
ros2 topic pub --once \
  --qos-reliability best_effort \
  /initialpose \
  geometry_msgs/msg/PoseWithCovarianceStamped \
  '{header: {frame_id: "map"}, pose: {pose: {position: {x: 0.0570244747, y: 0.1949666005, z: 0.0}, orientation: {z: 0.0546358647, w: 0.9985063456}}}}'

timeout 12 ros2 run tf2_ros tf2_echo map base_footprint 2>&1 |
  grep -m1 'Translation:'
```

Discovery Server 환경에서 CLI가 간헐적으로 `Node not found`를 내도 프로세스가 실제로
없다고 즉시 결론내리지 않는다. 다음 두 증거를 함께 본다.

```bash
ps -eo pid,ppid,stat,etimes,comm,args |
  grep -E \
  '[m]ap_server|[a]mcl|[c]ontroller_server|[p]lanner_server|[b]t_navigator|[v]elocity_smoother'

grep -a 'Managed nodes are active' /tmp/trihouse_pinky_rule.log
```

프로세스가 살아 있고 localization/navigation lifecycle manager가 각각
`Managed nodes are active`를 기록한 뒤 실제 `/trihouse/status` pose와 TF가 갱신되는지
확인한다. lifecycle service를 반복 호출해 active 노드를 불필요하게 재구성하지 않는다.

## 8. 배터리 초기화와 충전 판정

이번 재기동 직후 원본 `/battery/percent`는 `0.0`이었고 status는
`BATTERY_AT_OR_BELOW_RETURN_THRESHOLD`로 주문 배정을 차단했다. adapter는 한 개였으며
전압은 유한했으므로 고아 adapter 문제가 아니었다.

```bash
pgrep -af \
  '^/usr/bin/python3 /home/pinky/trihouse_ws/install/trihouse_pinky_io/lib/trihouse_pinky_io/battery_adapter'

timeout 15 ros2 topic echo \
  /battery/percent std_msgs/msg/Float32 --once

timeout 15 ros2 topic echo \
  /trihouse/battery sensor_msgs/msg/BatteryState --once
```

연속 표본은 `8.72 → 12.36 → 34.73`처럼 회복했다. 기동 직후 첫 0%만 보고 adapter를
다시 빌드하지 않는다. 단일 adapter인지 확인하고 ADC 표본이 안정될 시간을 준다.

다만 이후 다시 0%로 내려가 `dispatchable: false`가 되었으므로 이번에는 실제 충전을
진행한다. 배터리 값을 임의 발행하거나 정책을 속여 일반 주문을 넣지 않는다.

충전 후 다음 세 단계가 모두 정상이어야 한다.

```bash
timeout 12 ros2 topic echo \
  /battery/percent std_msgs/msg/Float32 --once

timeout 12 ros2 topic echo \
  /trihouse/battery sensor_msgs/msg/BatteryState --once

timeout 12 ros2 topic echo \
  /trihouse/status trihouse_interfaces/msg/RobotStatus --once
```

합격 조건:

- `/trihouse/battery.percentage`가 `0.0..1.0`의 유한수
- `/trihouse/battery.present: true`
- `battery_policy.ready: true`
- `battery_policy.reason_code: BATTERY_NORMAL`
- `telemetry_valid: true`
- `execution_ready: true`
- `dispatchable: true`
- 최종 `ready: true`, `errors: []`

## 9. 모터 경로 확인

주행 전에 토픽 연결만 확인한다. 테스트 Twist를 발행하지 않는다.

```bash
ros2 topic info /cmd_vel --verbose
ros2 topic info /cmd_vel_safe --verbose
```

현재 의도한 경로는 다음이다.

```text
Nav2 velocity_smoother
  cmd_vel_smoothed → /cmd_vel
SafetySupervisor
  /cmd_vel 구독 → /cmd_vel_safe 발행
vendor pinky_bringup
  /cmd_vel_safe 구독 → 모터
```

정상 조건:

- `/cmd_vel`의 구독자는 `safety_supervisor`
- `/cmd_vel_safe`의 발행자는 `safety_supervisor` 한 개
- `/cmd_vel_safe`의 구독자는 vendor `pinky_bringup`
- vendor motor node가 `/cmd_vel`을 직접 구독하지 않음

## 10. 개발 PC RMF 준비

Pinky가 준비된 뒤에도 RMF adapter보다 RMF core를 먼저 시작해야 한다.

```bash
cd /home/newuser/Trihouse/.worktrees/physical-integration-v1
source /opt/ros/jazzy/setup.bash
source install/setup.bash

export ROS_DOMAIN_ID=12
export ROS_AUTOMATIC_DISCOVERY_RANGE=SYSTEM_DEFAULT
unset ROS_STATIC_PEERS
export ROS_DISCOVERY_SERVER='192.168.0.4:11811'
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export FASTDDS_BUILTIN_TRANSPORTS=UDPv4

setsid nohup ros2 launch \
  trihouse_rmf_bridge rmf_core.launch.py \
  use_sim_time:=false \
  > /tmp/frozen_rmf_core.log 2>&1 < /dev/null &

echo $! > /tmp/frozen_rmf_core.pid
```

RMF core가 없을 때 adapter는 다음 오류로 종료됐다.

```text
RuntimeError: RMF adapter를 만들지 못했습니다.
rmf_traffic_schedule_primary를 확인하세요.
```

복구 후 확인:

```bash
pgrep -af \
  '[r]mf_traffic_schedule|[r]mf_traffic_blockade|[r]mf_task_dispatcher'

grep -aE 'ERROR|process has died|Traceback' \
  /tmp/frozen_rmf_core.log | tail -30
```

`trihouse_rmf_bridge`를 찾지 못했던 경우는 개발 PC overlay를 source하지 않은 것이
원인이었다.

```text
Package 'trihouse_rmf_bridge' not found, searching: ['/opt/ros/jazzy']
```

다음으로 복구한다.

```bash
cd /home/newuser/Trihouse/.worktrees/physical-integration-v1
source /opt/ros/jazzy/setup.bash
source install/setup.bash
ros2 pkg prefix trihouse_rmf_bridge
```

adapter는 Pinky에 설치하는 패키지가 아니라 개발 PC/RMF 측 패키지다.

## 11. 주행 직전 go/no-go 체크

아래는 읽기 전용 확인이다. 하나라도 실패하면 주문/action을 보내지 않는다.

```bash
echo '=== Pinky single launch ==='
ssh pinky@192.168.0.22 \
  "pgrep -af '^/usr/bin/python3 /opt/ros/jazzy/bin/ros2 launch trihouse_pinky_bringup'"

echo '=== exact rule profile argument ==='
ssh pinky@192.168.0.22 \
  "pgrep -af '^/usr/bin/python3 /opt/ros/jazzy/bin/ros2 launch trihouse_pinky_bringup' | grep -F 'narrow_zones_file:=/home/pinky/narrow_zones.new_map_2.yaml'"

echo '=== status ==='
timeout 15 ros2 topic echo \
  --no-daemon --spin-time 8 \
  /trihouse/status \
  trihouse_interfaces/msg/RobotStatus \
  --once

echo '=== safety ==='
timeout 15 ros2 topic echo \
  --no-daemon --spin-time 8 \
  /trihouse/safety/state \
  trihouse_interfaces/msg/SafetyState \
  --once

echo '=== motor ownership ==='
timeout 15 ros2 topic info /cmd_vel_safe --verbose
```

최종 합격 조건:

- Pinky launch 한 개
- 운영 규칙 파일 checksum 일치
- `frame_id: map`
- published `map_revision` 일치
- 현재 실물 위치와 status pose 일치
- localization 및 navigation managed nodes active
- `/scan`, `/odom`, `/tf`, `/tf_static` 갱신
- `readiness.state: 1`, `missing_interfaces: []`
- battery normal, `dispatchable: true`
- `safety.state < STATE_STOP`, `latched: false`
- `/cmd_vel_safe`의 유일한 발행자가 safety supervisor
- 경로 비움, E-stop 담당자 준비

## 12. 현재까지의 실패 → 복구 요약

| 실패 | 원인 | 복구/현재 판정 |
|---|---|---|
| Pinky SSH가 매우 느리거나 일시 단절 | 중복 ROS launch와 네트워크 불안정 | 중복 launch/고아 노드 정리, ping/22번 포트/부하를 분리 확인 |
| `/home/pinky/pinky_pro/install/setup.bash`만 source하지 않고 vendor package 미발견 | vendor overlay 누락 | `/opt/ros/jazzy` → `pinky_pro` → `trihouse_ws` 순서로 source |
| 개발 PC bind `192.168.0.9` 실패 | Wi-Fi 전환 후 현재 IP가 `192.168.0.4` | `ip route get` 결과로 FMS bind와 `control_host` 동기화 |
| DDS multicast는 되지만 status가 PC에 안 보임 | peer discovery가 불안정 | PC Discovery Server `192.168.0.4:11811` 사용, 모든 프로세스 재기동 |
| 실행 중 Discovery Server 종료 후 readiness/status timeout | 서버를 다시 띄워도 기존 participant가 제한시간 안에 재연결되지 않음 | 서버를 독립 session으로 재기동한 뒤 Pinky bringup도 같은 discovery 환경으로 재기동 |
| Fast DDS SHM port 오류 | 비정상 종료 뒤 공유 메모리 lock 충돌 | `FASTDDS_BUILTIN_TRANSPORTS=UDPv4` |
| `ros2 node list`가 비어 있음 | CLI graph 발견 지연 | 실제 PID, manager active 로그, 실제 토픽 메시지를 함께 확인 |
| AMCL unconfigured/inactive, map frame 없음 | localization lifecycle/initial pose 미완료 | AMCL active 확인 후 best-effort `/initialpose`, 실제 TF 샘플 확인 |
| TF frame이 `//base_link` | 빈 namespace가 vendor URDF에 중복 slash 생성 | bringup의 root namespace 정규화 코드 사용, 최신 패키지 배포/빌드 |
| `/trihouse/battery.percentage: nan`, `present: false` | 이전 adapter 또는 초기 샘플 미수신 | 단일 adapter 재기동, vendor percent → adapter → status 순서 확인 |
| 기동 직후 battery 0% | ADC 퍼센트 초기화 지연 | 연속 샘플 안정화 대기; 현재는 실제 충전 후 재검증 예정 |
| FMS `SCHEMA_INVALID robot_status` | 초기 invalid telemetry 또는 구버전 schema payload | battery/status 유효화 및 현재 Gateway 재빌드; 최근 로그에서 재발 없음 확인 |
| RMF adapter가 즉시 종료 | RMF schedule primary 미기동 | `rmf_core.launch.py`를 adapter보다 먼저 실행 |
| `trihouse_rmf_bridge` package not found | 개발 PC overlay 미-source | workspace `install/setup.bash` source |
| `/fleet_states`에 robot이 비어 있음 | adapter가 Pinky status를 발견하지 못함 | Discovery Server 환경 통일 후 status publisher 확인 |
| `zone_tour`에서 냉동 최종점까지 Nav2 사용 | profile의 `approach_required: false` | 운영 `narrow_zones.new_map_2.yaml`로 재기동 |
| 운영 YAML의 냉동 시퀀스가 사용자 원본과 다름 | `waypoint.md` 기반 값이 들어 있었음 | `j_narrow3_rule_based_docking_1.py`의 `narrow_3` 값으로 교체·배포·테스트 |
| 시작점 출발 규칙 뒤 목표 오차 0.170m | 완료 반경 0.150m보다 0.020m 큼 | goal 중단은 정상; 임계값을 임의 완화하지 않음. 다음 실기에서 출발값 재측정 필요 |
| 냉동 enter goal이 `NARROW_PROFILE_UNMEASURED` | 운영 gate는 미검증 exit까지 완료돼야 일반 배정 허용 | 일반 주문은 계속 차단. 사람 입회 1회 calibration enter와 정식 운영을 구분 |
| Nav2 회전 중 `swept_stop` | 최근접 scan 0.106m가 회전 swept clearance 0.199m 안 | safety 정지는 정상. 임계값을 낮추지 않고 entry에서 규칙 직진 후 회전하는 흐름 사용 |

## 13. 아직 성공으로 기록하지 않는 항목

- 충전 완료 후 battery policy 정상 복귀
- 새 profile 재기동 뒤 현재 실제 pose 재설정
- Nav2가 원본 entry `(0.919804, -1.189253)`까지만 이동
- entry zone에서 Nav2 goal 취소와 완전 정차
- entry pose 정렬
- `0.325m 직진 → -0.905796rad 회전 → 0.338m 후진`
- 예상 dock pose와 실제 AMCL pose 오차
- 도킹 중 safety state와 최종 정차
- 냉동 도크에서 빠져나오는 exit sequence
- OMX를 포함한 전체 냉동 주문 완료

사용자가 실물 결과를 `성공`으로 확인하기 전에는 위 항목을 완료로 바꾸지 않는다.

## 14. 2026-08-23 냉동 규칙 재시험 사전 점검

사용자가 Pinky를 냉동 entry에 수동 배치한 뒤 확인했다. 이 시점에는 action goal이나
속도 명령을 발행하지 않았다.

```text
Pinky launch count: 1
narrow profile: /home/pinky/narrow_zones.new_map_2.yaml
PC/Pinky profile SHA256:
  2bef085cf59cd63c71bfadc594d2f9a9b258676627eb82a13f2a3b5e0f6ea19a
readiness: state=1, missing_interfaces=[]
safety: state=0, latched=false, detail=clear
battery: 15.4%, BATTERY_LOCAL_WORK_ONLY
status: telemetry_valid=true, execution_ready=true, dispatchable=true, ready=true
localization manager: Managed nodes are active
navigation manager: Managed nodes are active
scan frame: rplidar_link
map -> base_footprint: Translation [0.920, -1.189, 0.000]
```

재기동 직후 status pose가 `(0,0)`이어서, 실물 배치가 완료됐음을 확인한 뒤 냉동 원본
entry pose를 `/initialpose`에 best-effort QoS로 발행했다. 이후 status와 TF가 다음으로
일치했다.

```text
x=0.9198039894576
y=-1.1892528962850
yaw=-0.0324297889893
```

`ros2 topic info /cmd_vel_safe --verbose`는 CLI graph 지연으로 `Unknown topic`을 출력했다.
대신 실행 프로세스 인자를 확인해 다음 remap을 검증했다.

```text
velocity_smoother: cmd_vel_smoothed → cmd_vel
safety_supervisor: cmd_vel_nav → cmd_vel, cmd_vel → cmd_vel_safe
vendor pinky_bringup: cmd_vel → cmd_vel_safe
```

배터리 정책은 local-only 시험을 허용했지만 15.4%는 세 구역 연속 시험에 충분하다고
판정하지 않는다. 냉동 한 구역을 마칠 때마다 SOC를 다시 확인하고, 낮아지면 다음 구역을
시작하지 않고 충전한다.

## 15. namespaced Pinky 단일 bringup

### 실패 증상과 확정 원인

`namespace:=pinky_02` 시험 중 다음 두 launch가 동시에 실행됐다.

```text
PID 19692: trihouse_pinky.launch.py namespace:=/
PID 22898: pinky_bringup bringup_robot.launch.xml namespace:=pinky_02
```

두 번째 명령은 namespaced 하드웨어 launch가 아니며 Nav2도 시작하지 않는다. 그래서
`robot_state_publisher`만 `/pinky_02` 아래에 있고 LiDAR, 배터리와 IMU는 루트에 남았다.
첫 번째 예전 Trihouse launch도 계속 살아 있어 루트 Nav2와 하드웨어 프로세스가 중복됐다.

```text
/scan               publisher namespace: /
/battery/percent    publisher namespace: /
/battery/voltage    publisher namespace: /
/imu_raw            publisher namespace: /
/pinky_02/odom      Unknown topic
/pinky_02/amcl      Node not found
```

토픽 목록에 한때 `/pinky_02/amcl_pose` 등이 보였더라도 실제 PID와 publisher가 없으면
정상 기동으로 판정하지 않는다. DDS graph의 이전 endpoint 또는 서로 다른 launch의
endpoint가 섞여 보일 수 있으므로 launch PID, 노드 PID와 실제 메시지를 함께 확인한다.

### 사용하면 안 되는 명령

다음 명령은 Trihouse, safety와 Nav2를 시작하지 않으므로 전체 시스템 bringup으로 사용하지
않는다.

```bash
# 사용하지 않는다.
ros2 launch pinky_bringup bringup_robot.launch.xml namespace:=pinky_02
```

`pinky_navigation/bringup_launch.xml`도 별도로 실행하지 않는다. 최신
`trihouse_pinky.launch.py`가 `localization_launch.xml`과 `navigation_launch.xml`을 직접
include하여 namespace를 각각 한 번만 적용한다.

### 1. 설치본 계약 확인

Pinky 터미널에서 overlay 순서와 설치 파일을 확인한다.

```bash
source /opt/ros/jazzy/setup.bash
source /home/pinky/pinky_pro/install/setup.bash
source /home/pinky/trihouse_ws/install/setup.bash

ros2 pkg prefix trihouse_pinky_bringup

test -f \
  /home/pinky/pinky_pro/install/pinky_bringup/share/pinky_bringup/launch/bringup_robot_namespaced.launch.xml &&
echo 'PASS: namespaced vendor bringup'

grep -nE \
  'bringup_robot_namespaced|localization_launch|navigation_launch|lifecycle_nodes' \
  /home/pinky/trihouse_ws/install/trihouse_pinky_bringup/share/trihouse_pinky_bringup/launch/trihouse_pinky.launch.py
```

설치된 Trihouse launch에 다음 계약이 모두 보여야 한다.

- `bringup_robot_namespaced.launch.xml` 사용
- 벤더 상위 `bringup_launch.xml` 미사용
- `localization_launch.xml`, `navigation_launch.xml` 직접 include
- localization lifecycle: `['map_server', 'amcl']`
- navigation lifecycle: controller, smoother, planner, behavior, BT, waypoint, velocity

### 2. namespaced Nav2 파라미터 생성과 검증

벤더 launch는 `RewrittenYaml(root_key=namespace)`를 사용하지 않는다. 따라서 frame과
토픽만 `pinky_02/...`로 바꾼 평면 YAML은 충분하지 않고, 문서 전체가 최상위
`pinky_02:` 아래에 있어야 한다.

실제 Pinky에 설치된 벤더 소스가 정본이다.

```text
/home/pinky/pinky_pro/src/pinky_pro/pinky_navigation/params/nav2_params.yaml
```

개발 PC submodule의 `pinky_pro/.../nav2_params.yaml`은 장비에서 조정한 값과 다를 수 있으므로
대신 사용하지 않는다. 먼저 Pinky 원본을 임시 파일로 가져온 뒤, 그 파일에서 namespaced
파생본을 생성한다. Pinky의 벤더 원본은 수정하지 않는다. 별도의 운영 YAML을 하나 더
관리하는 절차가 아니라, 생성 결과로 기존 `/home/pinky/hardware_pinky_02.yaml` 한 파일을
갱신한다.

기존 `hardware_pinky_02.yaml`에는 AMCL 시작 좌표 `(0.076, -0.013, 0.239)`가 들어 있었다.
이 값을 생략하고 다시 생성하면 벤더 원본의 잘못된 리스트형 `initial_pose`가 남으므로,
아래 명령은 기존 시작 좌표를 명시적으로 보존한다. 로봇의 승인된 시작 위치가 바뀌었다면
이 세 값을 새 참값으로 바꾼 뒤 생성한다.

```bash
cd /home/newuser/Trihouse/.worktrees/physical-integration-v1

rsync -avc --itemize-changes \
  pinky@192.168.0.22:/home/pinky/pinky_pro/src/pinky_pro/pinky_navigation/params/nav2_params.yaml \
  /tmp/pinky_02_vendor_nav2_params.yaml

python3 scripts/derive_hardware_nav2_params.py \
  --source /tmp/pinky_02_vendor_nav2_params.yaml \
  --namespace pinky_02 \
  --initial-pose 0.076,-0.013,0.239 \
  --output /tmp/hardware_pinky_02.yaml

python3 - <<'PY'
from pathlib import Path
import yaml

path = Path('/tmp/hardware_pinky_02.yaml')
document = yaml.safe_load(path.read_text(encoding='utf-8'))
assert list(document) == ['pinky_02'], list(document)
print('PASS: top-level namespace = pinky_02')
PY

rsync -avc --itemize-changes \
  /tmp/hardware_pinky_02.yaml \
  pinky@192.168.0.22:/home/pinky/hardware_pinky_02.yaml
```

Pinky에서 다시 확인한다.

```bash
python3 - <<'PY'
from pathlib import Path
import yaml

path = Path('/home/pinky/hardware_pinky_02.yaml')
document = yaml.safe_load(path.read_text(encoding='utf-8'))
assert list(document) == ['pinky_02'], list(document)
params = document['pinky_02']['amcl']['ros__parameters']
assert params['base_frame_id'] == 'pinky_02/base_footprint'
assert params['odom_frame_id'] == 'pinky_02/odom'
assert params['scan_topic'] == '/pinky_02/scan'
assert params['initial_pose'] == {'x': 0.076, 'y': -0.013, 'z': 0.0, 'yaw': 0.239}
behavior = document['pinky_02']['behavior_server']['ros__parameters']
assert behavior['local_frame'] == 'pinky_02/odom'
print('PASS: Pinky 02 Nav2 params contract')
PY
```

### 3. 기존 launch를 정확히 식별하고 정리

종료 전에 PID, PPID, PGID와 전체 명령행을 확인한다.

```bash
ps -eo pid,ppid,pgid,sid,stat,etimes,args |
grep -E \
  '[r]os2 launch trihouse_pinky_bringup|[r]os2 launch pinky_bringup|[r]os2 launch pinky_navigation'
```

이전 Trihouse launch와 잘못 실행한 단독 vendor launch의 전용 process group만 종료한다.
아래 PID는 예시가 아니라 현재 `pgrep` 결과로 다시 구한다.

```bash
for PATTERN in \
  '^/usr/bin/python3 /opt/ros/jazzy/bin/ros2 launch trihouse_pinky_bringup trihouse_pinky.launch.py' \
  '^/usr/bin/python3 /opt/ros/jazzy/bin/ros2 launch pinky_bringup '
do
  for PID in $(pgrep -f "$PATTERN" || true); do
    PGID="$(ps -o pgid= -p "$PID" | tr -d ' ')"
    ps -p "$PID" -o pid,ppid,pgid,sid,stat,etimes,args
    if [ -n "$PGID" ]; then
      kill -TERM -- "-$PGID"
    fi
  done
done

sleep 8

pgrep -af \
  '[r]os2 launch trihouse_pinky_bringup|[r]os2 launch pinky_bringup|[r]os2 launch pinky_navigation' ||
echo 'PASS: Pinky launch clean'
```

process group이 사용자 shell이나 다른 실험을 포함하는 경우에는 음수 PGID 종료를 사용하지
않고, 4절의 개별 PID 정리 절차를 따른다.

### 4. Trihouse launch 하나만 실행

Pinky 터미널에서 현재 개발 PC 주소와 map revision을 환경에 넣는다. 다른 네트워크에서는
`CONTROL_HOST`와 Discovery Server 주소를 그대로 재사용하지 않는다.

```bash
source /opt/ros/jazzy/setup.bash
source /home/pinky/pinky_pro/install/setup.bash
source /home/pinky/trihouse_ws/install/setup.bash

export ROS_DOMAIN_ID=12
export ROS_AUTOMATIC_DISCOVERY_RANGE=SYSTEM_DEFAULT
unset ROS_STATIC_PEERS
export ROS_DISCOVERY_SERVER='192.168.0.4:11811'
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export FASTDDS_BUILTIN_TRANSPORTS=UDPv4

export CONTROL_HOST='192.168.0.4'
export MAP_REVISION='new_map_2:df9a7f70eab87135a0e1a73c2b63a0a15aae2de3512a6c760a3259d0337a32ed'

setsid nohup ros2 launch \
  trihouse_pinky_bringup \
  trihouse_pinky.launch.py \
  namespace:=pinky_02 \
  robot_id:=PK_02 \
  map:=/home/pinky/map/new_map_2.yaml \
  map_revision:="$MAP_REVISION" \
  nav2_params_file:=/home/pinky/hardware_pinky_02.yaml \
  narrow_zones_file:=/home/pinky/narrow_zones.new_map_2.yaml \
  narrow_map_name:=new_map_2 \
  allow_narrow_calibration:=false \
  control_host:="$CONTROL_HOST" \
  control_port:=8788 \
  vision_enabled:=false \
  docking_enabled:=false \
  > /tmp/trihouse_pinky_02.log 2>&1 < /dev/null &

echo $! | tee /tmp/trihouse_pinky_02.pid
sleep 12
```

이 명령 하나가 namespaced 하드웨어, localization, Nav2, safety와 Trihouse onboard 노드를
모두 시작한다. 벤더 bringup이나 navigation을 다른 터미널에서 추가로 실행하지 않는다.

### 5. 주행 없이 namespace와 lifecycle 검증

```bash
echo '=== launch count ==='
pgrep -af \
  '^/usr/bin/python3 /opt/ros/jazzy/bin/ros2 launch trihouse_pinky_bringup trihouse_pinky.launch.py'

echo '=== double namespace must be empty ==='
ros2 topic list | grep '^/pinky_02/pinky_02/' ||
echo 'PASS: double namespace 없음'

echo '=== required topic publishers ==='
for TOPIC in \
  /pinky_02/scan \
  /pinky_02/odom \
  /pinky_02/battery/percent \
  /pinky_02/battery/voltage
do
  echo "--- $TOPIC ---"
  ros2 topic info "$TOPIC" --verbose |
  grep -E 'Publisher count|Node name|Node namespace'
done

echo '=== unexpected root publishers ==='
for TOPIC in /scan /battery/percent /battery/voltage /imu_raw; do
  echo "--- $TOPIC ---"
  ros2 topic info "$TOPIC" --verbose 2>/dev/null |
  grep -E 'Publisher count|Node name|Node namespace' || true
done

for NODE in \
  map_server amcl controller_server smoother_server planner_server \
  behavior_server bt_navigator waypoint_follower velocity_smoother
do
  echo "=== /pinky_02/$NODE ==="
  timeout 8 ros2 lifecycle get "/pinky_02/$NODE"
done
```

합격 조건:

- 전체 Trihouse launch가 정확히 한 개
- `/pinky_02/pinky_02/*` 없음
- `/pinky_02/scan`, `/odom`, 배터리 토픽에 publisher 존재
- 루트 `/scan`, `/battery/*`, `/imu_raw`에 robot publisher 없음
- localization과 navigation lifecycle 노드 모두 `active [3]`
- `/pinky_02/cmd_vel_safe`의 유일한 발행자가 namespaced safety supervisor

이번 관측은 중복 launch와 잘못된 vendor 단독 실행까지 원인을 확정한 상태다. 위 정리와
단일 재기동을 실제 수행하고 모든 합격 조건을 측정하기 전에는 복구 성공으로 기록하지
않는다.
