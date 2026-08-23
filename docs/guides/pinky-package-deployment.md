# Pinky 내장 Raspberry Pi에 Trihouse 패키지 배포

## 목적과 범위

이 문서는 개발 PC의 다음 소스를 Pinky 내장 Raspberry Pi로 옮기고 ROS 2 overlay로
빌드하는 일반 절차다.

- `trihouse_interfaces`: Trihouse ROS 인터페이스
- `trihouse_pinky`: Pinky에서 실행할 bringup, IO, safety, fleet, docking, vision 패키지

`trihouse_omx_adapter`, 관제 서버, 데이터베이스, RMF 서버 코드는 Pinky에 배포하지 않는다.
OMX는 별도 장비에서 실행되고, 관제가 Pinky와 OMX를 연결한다.

이 절차의 완료 기준은 **코드 전송과 빌드 검증**이다. 빌드 성공만으로 실제 주행 준비가
증명되지는 않는다. 지도와 로봇별 설정은 런타임 자산이므로 기존 파일을 확인한 뒤 별도로
지정하며, 이 절차에서 덮어쓰지 않는다.

## 터미널 구분

명령은 두 종류의 터미널에서 실행한다.

- **Pinky 터미널**: Pinky에 모니터와 키보드로 접속했거나 SSH로 로그인한 터미널
- **개발 PC 터미널**: Trihouse 저장소가 있는 PC의 터미널

예시의 `<...>`는 실제 확인값으로 바꾼다. 꺾쇠괄호를 그대로 입력하지 않는다.

## 빠른 STEPS: 처음 배포부터 코드 갱신까지

아래 순서가 이 문서의 실행 흐름이다. 실제 로봇 이동은 11절의 안전 조건과 17절의
readiness를 모두 통과하기 전까지 포함하지 않는다.

| 단계 | 실행 터미널 | 하는 일 | 완료 기준 |
| --- | --- | --- | --- |
| 1 | `pinky@` | ROS 배포판·vendor overlay·Pinky 홈을 확인한다. | `pinky_bringup`, `pinky_navigation`을 찾는다. |
| 2 | `pinky@` | `~/trihouse_ws/src` workspace를 준비한다. | workspace와 `src`가 존재한다. |
| 3 | `pc@` | SSH 대상과 원격 workspace를 확인한다. | 호스트·사용자·경로가 Pinky 실물과 일치한다. |
| 4 | `pc@` | `trihouse_interfaces`, `trihouse_pinky`만 `rsync` dry-run 후 전송한다. | OMX/FMS/DB 코드는 Pinky에 복사되지 않는다. |
| 5 | `pinky@` | rosdep 확인 후 순차 `colcon build --symlink-install`을 한다. | 7개 Trihouse package가 build된다. |
| 6 | `pinky@` | underlay → vendor → Trihouse overlay 순으로 source한다. | `ros2 pkg prefix trihouse_pinky_bringup`가 `trihouse_ws/install`을 가리킨다. |
| 7 | `pinky@` | launch 하나, 센서·TF·Nav2·battery·safety·readiness를 확인한다. | `ready: true`, `errors: []`, final `/cmd_vel_safe` 발행자는 Safety Supervisor 하나다. |
| 8 | `pc@` → `pinky@` | 코드 수정분을 다시 전송하고 영향 package만 다시 build한 뒤 launch를 재기동한다. | 새 설치본과 새 process가 실행 중이다. |

### 코드 수정 후 갱신: rcp가 아니라 `rsync`

이 저장소의 갱신 수단은 `rcp`나 ROS link가 아니라 **SSH 위의 `rsync`**다.
`--symlink-install`은 workspace 내부에서 install Python entrypoint가 source를 가리키게
하지만, 이미 실행 중인 Python/launch process의 코드를 바꾸지는 않는다. 따라서 아래처럼
전송·build·재기동을 한 묶음으로 실행한다.

영향 범위가 불명확하면 6절의 전체 전송과 8절의 전체 build를 쓴다. 한 package의 Python
코드만 바뀐 것이 확실할 때는 다음 최소 절차를 쓴다.

```bash
# pc@ 개발 PC: 먼저 차이만 확인한다.
cd <trihouse-repository-root>
rsync -avnc --itemize-changes \
  --exclude='__pycache__/' --exclude='.pytest_cache/' --exclude='*.pyc' \
  trihouse_pinky/trihouse_pinky_<changed-package>/ \
  "$PINKY_TARGET:$PINKY_WS/src/trihouse_pinky/trihouse_pinky_<changed-package>/"

# pc@ 개발 PC: dry-run 출력이 맞을 때만 실제 전송한다.
rsync -avc --itemize-changes \
  --exclude='__pycache__/' --exclude='.pytest_cache/' --exclude='*.pyc' \
  trihouse_pinky/trihouse_pinky_<changed-package>/ \
  "$PINKY_TARGET:$PINKY_WS/src/trihouse_pinky/trihouse_pinky_<changed-package>/"
```

```bash
# pinky@ Pinky: 현재 운행 중이면 먼저 안전하게 정지하고, 이 package만 다시 build한다.
source /opt/ros/<ros-distro>/setup.bash
source <vendor-workspace>/install/setup.bash
cd <pinky-home>/trihouse_ws

colcon build --symlink-install --executor sequential \
  --packages-select trihouse_pinky_<changed-package> \
  --event-handlers console_direct+
source install/setup.bash

# 기존 launch 종료·새 launch 시작은 12절과 14절을 그대로 따른다.
```

`trihouse_interfaces`를 변경했거나 의존 package/launch file을 변경했다면 관련 package를
함께 build한다. 예를 들어 action/message 변경은 `trihouse_interfaces`와 이 interface를
쓰는 `trihouse_pinky_bringup`, `trihouse_pinky_fleet`, `trihouse_pinky_safety`를 모두
다시 build해야 한다. 실기에서는 코드 변경 직후 launch를 무중단 갱신하지 않는다.

## 1. Pinky 환경 확인

Pinky 터미널에서 먼저 실행한다.

```bash
whoami
hostname
ip -br addr
pwd
```

다음 세 값을 기록한다.

- `whoami` 결과: SSH 사용자명
- `ip -br addr`에서 실제 네트워크 인터페이스의 IPv4 주소
- 사용자의 홈 디렉터리

홈 디렉터리는 다음 명령으로 명확히 확인한다.

```bash
PINKY_HOME_DIR="$(getent passwd "$(whoami)" | cut -d: -f6)"
printf '%s\n' "$PINKY_HOME_DIR"
```

설치된 ROS 2 배포판과 기존 robot vendor workspace를 찾는다.

```bash
ls -1 /opt/ros

find "$PINKY_HOME_DIR" \
  -maxdepth 5 \
  -type f \
  -path '*/install/setup.bash' \
  -print 2>/dev/null | sort
```

후보 setup 파일을 무작정 전부 source하지 않는다. ROS 2 기본 환경과 Pinky vendor
overlay만 선택한다. 예를 들어 vendor workspace가 `pinky_pro`라면 다음처럼 확인한다.

```bash
source /opt/ros/<ros-distro>/setup.bash
source <vendor-workspace>/install/setup.bash

ros2 pkg prefix pinky_bringup
ros2 pkg prefix pinky_navigation
ros2 pkg prefix pinky_sensor_adc
```

세 명령 모두 vendor workspace 아래의 경로를 출력하면 사용할 overlay를 제대로 찾은
것이다. 출처를 알 수 없는 다른 `install/setup.bash`는 섞지 않는다.

## 2. Pinky workspace 생성

아래 명령은 Pinky 홈 아래에 workspace와 `src` 디렉터리를 만든다. 기존 디렉터리가
있어도 내용은 삭제하지 않는다.

Pinky 터미널에서 실행한다.

```bash
PINKY_HOME_DIR="$(getent passwd "$(whoami)" | cut -d: -f6)"
PINKY_WS="$PINKY_HOME_DIR/trihouse_ws"

mkdir -p "$PINKY_WS/src"
ls -ld "$PINKY_WS" "$PINKY_WS/src"
df -h "$PINKY_WS"
```

`ls`가 두 디렉터리를 표시하고 디스크 여유 공간이 충분하면 통과다.

## 3. 개발 PC에서 접속 변수 설정

이제 개발 PC 터미널에서 실행한다. 1단계에서 확인한 값으로 바꾼다.

```bash
cd <trihouse-repository-root>

export PINKY_TARGET='<pinky-user>@<pinky-ip>'
export PINKY_WS='<pinky-home>/trihouse_ws'
```

SSH 연결과 대상 경로를 확인한다.

```bash
ssh "$PINKY_TARGET" 'hostname; whoami; pwd'
ssh "$PINKY_TARGET" "ls -ld '$PINKY_WS' '$PINKY_WS/src'"
```

출력의 호스트, 사용자, 경로가 1단계 결과와 일치해야 한다. 일치하지 않으면 전송하지
말고 `PINKY_TARGET`과 `PINKY_WS`를 수정한다.

## 4. 전송할 소스 확인

개발 PC의 저장소 루트에서 실행한다.

```bash
test -f trihouse_interfaces/package.xml
test -d trihouse_pinky

find trihouse_interfaces trihouse_pinky \
  -maxdepth 3 \
  -name package.xml \
  -print | sort
```

현재 전송 대상은 다음 7개 ROS 패키지다.

```text
trihouse_interfaces
trihouse_pinky_bringup
trihouse_pinky_docking
trihouse_pinky_fleet
trihouse_pinky_io
trihouse_pinky_safety
trihouse_pinky_vision
```

## 5. rsync dry run

먼저 실제 파일을 변경하지 않는 dry run을 수행한다.

```bash
command -v rsync
ssh "$PINKY_TARGET" 'command -v rsync'

rsync -avnc --itemize-changes \
  --exclude='__pycache__/' \
  --exclude='.pytest_cache/' \
  --exclude='*.pyc' \
  trihouse_interfaces trihouse_pinky \
  "$PINKY_TARGET:$PINKY_WS/src/"
```

출력 대상이 `$PINKY_WS/src/trihouse_interfaces`와
`$PINKY_WS/src/trihouse_pinky` 아래인지 확인한다. 다른 workspace나 홈 디렉터리 자체가
대상으로 보이면 실제 전송을 진행하지 않는다.

## 6. 실제 코드 전송

dry run이 맞을 때만 개발 PC에서 `-n`을 제거해 실행한다.

```bash
rsync -avc --itemize-changes \
  --exclude='__pycache__/' \
  --exclude='.pytest_cache/' \
  --exclude='*.pyc' \
  trihouse_interfaces trihouse_pinky \
  "$PINKY_TARGET:$PINKY_WS/src/"
```

이 명령은 같은 이름의 파일을 갱신하지만 `--delete`를 사용하지 않으므로 대상의 다른
파일을 자동 삭제하지 않는다.

전송 결과를 개발 PC에서 확인한다.

```bash
ssh "$PINKY_TARGET" "find '$PINKY_WS/src' \
  -maxdepth 4 -name package.xml -print | sort"

ssh "$PINKY_TARGET" "find '$PINKY_WS/src' \
  -path '*trihouse_omx_adapter*' -print"
```

첫 명령은 위 7개 패키지의 `package.xml`을 표시해야 한다. 두 번째 명령은 아무것도
출력하지 않아야 한다.

## 7. 의존성 점검

Pinky 터미널에서 기본 ROS 2 환경과 확인된 vendor overlay를 순서대로 적용한다.

```bash
cd <pinky-home>/trihouse_ws

source /opt/ros/<ros-distro>/setup.bash
source <vendor-workspace>/install/setup.bash

colcon list
```

`colcon list`에 위 7개 패키지가 표시되어야 한다. 이어서 시스템 의존성을 점검한다.

```bash
rosdep check \
  --from-paths src/trihouse_interfaces src/trihouse_pinky \
  --ignore-src
```

정상 기준은 다음 메시지다.

```text
All system dependencies have been satisfied
```

의존성이 없다는 오류가 나오면 즉시 설치 명령을 추측하지 말고 오류에 표시된 패키지를
확인한다. 시스템 패키지 설치는 Pinky 운영 환경을 변경하므로 담당자가 검토한 뒤 수행한다.

## 8. colcon build

빌드는 코드를 `build/`, `install/`, `log/`에 생성하지만 노드를 실행하거나 로봇을
움직이지 않는다. Raspberry Pi의 메모리 부담을 낮추기 위해 순차 빌드를 사용한다.

Pinky 터미널에서 실행한다.

```bash
cd <pinky-home>/trihouse_ws

source /opt/ros/<ros-distro>/setup.bash
source <vendor-workspace>/install/setup.bash

colcon build \
  --symlink-install \
  --executor sequential \
  --event-handlers console_direct+
```

마지막 `Summary`에서 7개 패키지가 모두 완료되고 실패가 없어야 통과다.

## 9. 빌드 결과 확인

빌드 후에는 항상 underlay에서 overlay 순서로 source한다.

```bash
source /opt/ros/<ros-distro>/setup.bash
source <vendor-workspace>/install/setup.bash
source <pinky-home>/trihouse_ws/install/setup.bash
```

패키지 검색 경로를 확인한다.

```bash
ros2 pkg prefix trihouse_interfaces
ros2 pkg prefix trihouse_pinky_bringup
ros2 pkg prefix trihouse_pinky_fleet
ros2 pkg prefix trihouse_pinky_safety
```

각 출력이 `<pinky-home>/trihouse_ws/install/...` 아래면 Trihouse overlay가 적용된 것이다.
새 터미널에서는 위 세 `source` 명령을 다시 실행해야 한다.

설치된 Pinky launch에 OMX 인자가 다시 들어오지 않았는지도 정적으로 확인한다.

```bash
if ros2 launch trihouse_pinky_bringup trihouse_pinky.launch.py --show-args \
  | grep -Eiq 'omx|omx_station_id'; then
  echo 'FAIL: Pinky launch에 OMX 항목이 있습니다.'
else
  echo 'PASS: Pinky launch에 OMX 항목이 없습니다.'
fi
```

## 10. 지도와 로봇별 설정

지도 파일은 코드와 별도로 관리한다. Pinky에 기존 지도가 있다면 경로와 YAML 내부의
`image:` 참조를 먼저 확인한다.

```bash
find <pinky-home> -maxdepth 4 -type f \
  \( -name '*.yaml' -o -name '*.pgm' \) -print | sort

grep -n '^image:' <map-yaml-path>
```

실행 시에는 확인한 실제 경로를 launch 인자로 전달한다. 다른 Pinky에서도 같은 경로라고
가정하지 않는다.

```text
map:=<map-yaml-path>
```

로봇별 namespace, robot ID, 관제 주소, Nav2 파라미터, 좁은 구역 설정과 카메라 설정도
각 장비의 배치값을 확인한 뒤 지정한다.

## 11. 실물 주행 전 중지 지점

여기까지 성공하면 상태는 다음과 같다.

- **Implemented**: Trihouse 소스가 Pinky workspace에 존재한다.
- **Tested**: 7개 패키지의 Pinky 빌드가 오류 없이 끝났다.
- **Not measured**: 센서, Nav2, safety, 관제 연결과 실제 모터 동작은 아직 검증되지 않았다.

즉시 주행 명령을 보내지 않는다. 실제 launch와 주행은 별도의 물리 안전 점검에서 다음을
먼저 확인해야 한다.

- 모터 입력 토픽의 유일한 발행자가 safety supervisor인지 확인
- E-stop 담당자 배치 및 작동 확인
- 로봇 주변과 예정 경로가 비어 있는지 확인
- 지도, localization, TF, 센서 freshness 확인
- 영상 증거가 필요한 시험이면 카메라 수신 경로 확인

이 조건을 만족하기 전에는 **코드 배포와 빌드 성공**만 확인된 것이며 **실물 주행 준비
완료**로 판정하지 않는다.

## 12. 업데이트 빌드 전 실행 프로세스 정리

Python 노드는 시작할 때 모듈을 메모리에 읽는다. 실행 중에 소스 전송과 `colcon build`를
마쳐도 기존 프로세스는 이전 코드를 계속 사용한다. 업데이트 검증 전에는 Pinky launch를
정확히 하나만 남기거나 모두 종료한 뒤 새로 시작해야 한다.

```bash
pgrep -af '[r]os2 launch trihouse_pinky_bringup'
```

동일 launch가 둘 이상이면 먼저 foreground 터미널의 launch를 `Ctrl+C`로 종료한다.
부모 launch가 사라졌는데 자식 노드가 남았는지도 확인한다.

```bash
pgrep -af \
  '[b]attery_adapter|[r]eadiness_checker|[s]tatus_node|[f]leet_node|[r]ecovery_health'
```

고아 프로세스가 여러 개이거나 Fast DDS SHM 잠금 오류까지 반복되면 일부 PID를 추측해
정리하지 않는다. 로봇을 정지시키고 주변을 비운 뒤 Pinky를 재부팅하는 것이 안전하다.

```bash
sudo reboot
```

재접속 후 위 두 `pgrep` 결과가 비어 있는지 확인한다. launch를 background와 foreground로
동시에 시작하지 않는다.

## 13. 실기 런타임 환경과 네트워크 값 확인

Pinky의 모든 새 터미널에서 underlay부터 overlay 순서로 source한다. Fast DDS 공유 메모리
포트가 이전 비정상 종료와 충돌할 수 있으므로 실기 점검에서는 UDPv4 transport를 명시한다.

```bash
source /opt/ros/<ros-distro>/setup.bash
source <vendor-workspace>/install/setup.bash
source <pinky-home>/trihouse_ws/install/setup.bash

export ROS_DOMAIN_ID=<control-pc와-같은-domain-id>
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export FASTDDS_BUILTIN_TRANSPORTS=UDPv4
```

개발 PC와 Pinky가 같은 서브넷이고 실제 관제 주소로 통신하는지 확인한다.

개발 PC:

```bash
ip -br addr
ip route get <pinky-ip>
```

Pinky:

```bash
ip -br addr
nc -vz <control-pc-ip> <control-tcp-port>
```

Docker/FMS가 특정 host IP에 bind되었다면 `control_host`에도 그 현재 IP를 사용한다. 유선과
Wi-Fi가 바뀐 뒤 과거 IP를 재사용하지 않는다.

## 14. 단일 Pinky 실기 launch

아래는 namespace 없는 단일 Pinky smoke test 템플릿이다. 지도, revision, 관제 주소는
각 장비와 현재 publish artifact에서 확인한 값으로 바꾼다.

```bash
NAV2_PARAMS="$(ros2 pkg prefix pinky_navigation)/share/pinky_navigation/params/nav2_params.yaml"

ros2 launch trihouse_pinky_bringup trihouse_pinky.launch.py \
  namespace:=/ \
  robot_id:=<robot-id> \
  map:=<map-yaml-path> \
  map_revision:=<published-map-revision> \
  nav2_params_file:="$NAV2_PARAMS" \
  control_host:=<control-pc-ip> \
  control_port:=<control-tcp-port> \
  vision_enabled:=false \
  docking_enabled:=false
```

이 launch는 OMX adapter를 시작하지 않는다. OMX는 별도 장비에서 실행하고 관제가 작업을
연결한다. `namespace:=/`는 Trihouse launch가 벤더에 빈 namespace로 정규화하므로 벤더
URDF frame이 `//base_link`처럼 만들어지지 않아야 한다.

다중 Pinky에서 non-root namespace를 쓸 때는 Nav2 params의 root key, RMF adapter 토픽,
지도 revision과 `robot_id` 매핑을 같은 namespace 계약으로 생성해야 한다. 단일 smoke test
값을 그대로 복사하지 않는다.

## 15. TF, localization과 Nav2 검증

정적 TF에 이중 slash가 없는지 확인한다.

```bash
timeout 8 ros2 topic echo \
  /tf_static tf2_msgs/msg/TFMessage \
  --qos-reliability reliable \
  --qos-durability transient_local \
  --once | grep -E 'frame_id:|child_frame_id:'
```

정상 frame은 `base_footprint`, `base_link`, `rplidar_link`처럼 slash 없이 나온다.
`//base_link`가 하나라도 있으면 주행하지 말고 설치된
`trihouse_pinky_bringup`가 최신인지 다시 확인한다.

localization lifecycle을 확인한다.

```bash
for node in map_server amcl
do
  echo "=== /$node ==="
  timeout 8 ros2 lifecycle get "/$node"
done
```

둘 다 `active [3]`일 때만 지도에서 실측한 현재 위치를 발행한다.

```bash
ros2 topic pub --once \
  --qos-reliability best_effort \
  /initialpose geometry_msgs/msg/PoseWithCovarianceStamped \
  '{header: {frame_id: "map"}, pose: {pose: {position: {x: <x>, y: <y>, z: 0.0}, orientation: {z: <qz>, w: <qw>}}}}'
```

첫 discovery 경고가 아니라 실제 변환을 기다린다.

```bash
timeout 10 ros2 run tf2_ros tf2_echo map base_footprint 2>&1 \
  | grep -m1 'Translation:'
```

Nav2 핵심 노드는 모두 `active [3]`이어야 한다.

```bash
for node in controller_server planner_server bt_navigator velocity_smoother
do
  echo "=== /$node ==="
  timeout 8 ros2 lifecycle get "/$node"
done
```

## 16. LiDAR QoS와 배터리 adapter 검증

Pinky LiDAR는 `/scan`을 `BEST_EFFORT`로 발행한다. Trihouse readiness, status, fleet,
recovery 노드도 sensor-data QoS로 구독해야 한다.

```bash
ros2 topic info /scan --verbose
```

`sllidar_node` 발행자와 위 네 Trihouse 구독자의 Reliability가 `BEST_EFFORT`인지 확인한다.
구독자가 `RELIABLE`이면 코드는 전송됐어도 이전 프로세스가 실행 중일 수 있으므로 12절부터
다시 수행한다.

벤더 `/batt_state`는 전압만 채우고 `percentage: nan`, `present: false`를 낼 수 있다.
Trihouse battery adapter는 별도 `/battery/percent`를 합쳐 `/trihouse/battery`를 만든다.
벤더 퍼센트는 5초 주기이므로 launch 후 최소 7초 기다린다.

```bash
sleep 7
timeout 12 ros2 topic echo /battery/percent std_msgs/msg/Float32 --once
timeout 12 ros2 topic echo /trihouse/battery sensor_msgs/msg/BatteryState --once
```

`/trihouse/battery`의 정상 조건은 다음과 같다.

- `voltage`가 유한한 양수
- `percentage`가 `0.0`부터 `1.0` 사이의 유한한 값
- `present: true`

`percentage: 0.68`은 68%다. 임의의 퍼센트를 발행해 정책을 우회하지 않는다. 10% 이하는
복귀 필요 상태이고, 20% 이하에서는 운영 정책을 확인한 뒤 제한 작업만 수행한다.

## 17. 최종 Pinky readiness와 안전 판정

```bash
timeout 10 ros2 topic echo \
  /trihouse/readiness trihouse_interfaces/msg/Readiness --once
```

합격값은 `state: 1`, `missing_interfaces: []`다.

```bash
timeout 10 ros2 topic echo \
  /trihouse/status trihouse_interfaces/msg/RobotStatus --once
```

주문을 받을 수 있는 Pinky의 합격 조건은 다음과 같다.

- `frame_id: map`
- 실행 중인 지도와 동일한 `map_revision`
- `telemetry_valid: true`
- `execution_ready: true`
- `dispatchable: true`
- `ready: true`
- `errors: []`
- `battery_policy.ready: true`
- `safety.detail: clear`

모터 배선은 Nav2의 `/cmd_vel`을 safety supervisor가 받아 `/cmd_vel_safe`로 내보내고,
벤더 `pinky_bringup`만 최종 토픽을 구독해야 한다.

```bash
ros2 topic info /cmd_vel --verbose
ros2 topic info /cmd_vel_safe --verbose
```

`/cmd_vel_safe`의 발행자는 `safety_supervisor` 하나, 구독자는 `pinky_bringup` 하나여야 한다.

## 18. 이 문서의 완료 경계

1절부터 17절까지 통과하면 **다른 Pinky에 Trihouse 패키지를 배포하고 Pinky 자체를
주문 수신 가능한 상태까지 검증**할 수 있다. 장비마다 다음 값은 반드시 다시 측정하거나
조회한다.

- Pinky 사용자·홈·IP·vendor workspace
- ROS domain과 관제 PC IP/port
- `robot_id`와 namespace
- 지도 경로, publish revision, 초기 pose
- 배터리와 센서 실측 상태

이 문서 하나가 전체 주문 시스템을 기동하는 문서는 아니다. 다음은 관제 PC 또는 별도
장비의 책임이며 Pinky 배포 범위 밖이다.

- MySQL/FMS Gateway
- Open-RMF core와 Pinky fleet adapter
- job runner, executor worker, RMF gateway worker
- OMX station adapter와 실제 로봇팔
- 주문 POST, 진행 관측, 작업자 인계 완료 처리

따라서 다른 Pinky의 **onboard 배포와 주행 준비**에는 이 문서를 정본으로 사용하고,
냉동창고 주문의 end-to-end 실행에는 별도의 관제 runbook을 함께 사용한다.
