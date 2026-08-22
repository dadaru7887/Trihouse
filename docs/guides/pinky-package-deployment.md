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
