# openrmf_app 실행 가이드

이 문서는 Open-RMF 기본 office 시뮬레이션의 로봇 상태를 `rmf-web` API를
거쳐 Flutter 관제 화면에서 확인하는 순서를 설명합니다.

```text
Open-RMF office
  -> rmf-web 내부 WebSocket (ws://127.0.0.1:8000/_internal)
  -> rmf-web REST API (http://127.0.0.1:8000)
  -> openrmf_app
```

## 1. 사전 준비 확인

필요한 구성은 다음과 같습니다.

- Ubuntu 24.04
- ROS 2 Jazzy
- 빌드된 Open-RMF workspace: 기본값 `$HOME/rmf_ws`
- Docker
- Flutter Linux desktop

설치 상태를 확인합니다.

```bash
source /opt/ros/jazzy/setup.bash
source "$HOME/rmf_ws/install/setup.bash"

ros2 pkg prefix rmf_demos_gz
ros2 pkg prefix rmf_demos_fleet_adapter
docker info
flutter doctor
```

`docker info`가 권한 오류를 출력하면 현재 사용자를 Docker 그룹에 추가한 후
로그아웃하고 다시 로그인합니다.

```bash
sudo usermod -aG docker "$USER"
```

Flutter에서 Linux desktop이 비활성화되어 있다면 활성화합니다.

```bash
flutter config --enable-linux-desktop
flutter doctor
```

## 2. 자동 실행

가장 간단한 실행 방법입니다.

```bash
cd /home/gyi/robosapiens
./openrmf/scripts/run_office_flutter.sh
```

스크립트는 다음 작업을 순서대로 수행합니다.

1. `$HOME/rmf_ws/install/setup.bash` 존재 여부 확인
2. `rmf-web` API가 이미 실행 중인지 확인
3. API가 없으면 공식 `api-server:jazzy` Docker 컨테이너 실행
4. API의 `/time` 응답 대기
5. ROS 2 Jazzy와 Open-RMF workspace 환경 적용
6. office 시뮬레이션 실행
7. building map이 API에 등록될 때까지 대기
8. Flutter 의존성 확인 후 Linux 앱 실행

Gazebo 화면 없이 실행하려면 다음과 같이 지정합니다.

```bash
RMF_HEADLESS=true ./openrmf/scripts/run_office_flutter.sh
```

정상적으로 연결되면 Flutter 상단에 `API ONLINE`이 표시되고 office 지도 위에
`tinyRobot1`, `tinyRobot2`가 나타납니다.

Flutter 앱의 1상단 탭에서 다음 기능을 사용할 수 있습니다.

- `지도`: 다층 지도, 로봇 위치와 RMF 예상 궤적
- `태스크`: patrol/delivery/clean/custom compose 요청, 취소, 로그, 반복 예약
- `로봇`: fleet 필터, 배터리와 이슈, 운행 제외/복귀, mutex group 수동 해제
- `설비`: 도어 개폐, 리프트 호출, dispenser/ingestor 상태
- `알림`: 응답 대기 중인 RMF 알림 확인 및 응답

궤적 서버를 별도로 운영하는 경우
`RMF_TRAJECTORY_SERVER_URL=ws://호스트:8006`으로 지정합니다. 서버가 없으면
지도와 나머지 관제 기능은 그대로 작동하고 궤적만 표시되지 않습니다.

### 웹 대시보드 실행

Open-RMF 자체 웹 대시보드를 사용하려면 다음 스크립트를 실행합니다.

```bash
cd /home/gyi/robosapiens
./openrmf/scripts/run_office_web.sh
```

웹 대시보드 주소는 `http://localhost:3000`입니다. 자동 브라우저 실행을
비활성화하려면 `RMF_OPEN_BROWSER=false`를 지정합니다.

웹 전용 스크립트는 stable Jazzy API와 office 백엔드를 준비하고, 공식 rmf-web
0.3.0 소스 커밋을 고정한 자체 dashboard 이미지를 실행합니다. 첫 실행에만
`openrmf/docker/rmf-web-dashboard/Dockerfile`을 이용한 이미지 빌드가
수행됩니다. 깨진 nightly dashboard와 Flutter Web은 사용하지 않습니다.

### 다른 컴퓨터에서 웹 대시보드 실행

저장소를 다른 컴퓨터로 복제한 뒤 해당 컴퓨터에서도 같은 스크립트를
실행하면 됩니다. 저장소의 절대 경로와 사용자 이름은 달라도 됩니다.
스크립트가 자신의 위치를 기준으로 필요한 파일을 찾습니다.

```bash
git clone <이 저장소 주소> ~/robosapiens
cd ~/robosapiens
./openrmf/scripts/run_office_web.sh
```

필수 조건은 Ubuntu 24.04, ROS 2 Jazzy, 빌드된 Open-RMF workspace와 Docker
접근 권한입니다. Open-RMF workspace가 `~/rmf_ws`가 아닌 곳에 있다면 실행할
때 위치를 전달합니다.

```bash
RMF_WS=/home/myuser/custom_rmf_ws \
  ./openrmf/scripts/run_office_web.sh
```

집 컴퓨터에서는 처음 한 번 대시보드 소스를 내려받아 Docker 이미지를
빌드합니다. 따라서 첫 실행에는 인터넷 연결이 필요하고 시간이 걸릴 수
있습니다. 이후에는 로컬의 `robosapiens-rmf-dashboard:0.3.0` 이미지를
재사용합니다. 정상 빌드 여부는 다음 명령으로 확인합니다.

```bash
docker image inspect robosapiens-rmf-dashboard:0.3.0
```

자동으로 브라우저를 열 수 없는 환경에서는 다음과 같이 실행한 후 Chrome이나
Firefox에서 직접 `http://localhost:3000`을 엽니다.

```bash
RMF_OPEN_BROWSER=false ./openrmf/scripts/run_office_web.sh
```

Gazebo 창이 필요 없으면 자원 사용량을 줄이도록 headless 모드를 사용합니다.

```bash
RMF_HEADLESS=true ./openrmf/scripts/run_office_web.sh
```

스크립트는 Gazebo를 시작하기 전에 DRM GPU를 자동으로 확인합니다. NVIDIA 또는
다른 GPU가 있으면 하드웨어 렌더링을 사용하고, GPU 장치가 없을 때만 Mesa
소프트웨어 렌더링을 사용합니다. NVIDIA GPU가 있지만 `nvidia-smi`가 드라이버에
접근하지 못하면 경고를 출력하므로 NVIDIA 드라이버 상태를 확인해야 합니다.

### 웹 대시보드 빈 화면 원인과 해결 내용

확인된 빈 화면은 Open-RMF 백엔드나 Flutter 문제가 아니었습니다. 당시 사용한
`ghcr.io/open-rmf/rmf-web/demo-dashboard:jazzy-nightly` 이미지 안의
JavaScript 번들에서 React Router의 `useRoutes`가 Router 문맥 밖에서
실행되었습니다. 브라우저 콘솔에는 minify된 React Router invariant 오류가
발생했고 React가 최초 화면을 그리지 못해 페이지 전체가 비어 보였습니다.

추가로 다음 두 가지 때문에 컨테이너 환경 변수만 바꾸는 방법으로는 해결되지
않았습니다.

1. nightly 이미지는 날짜에 따라 내용이 바뀌므로 동일 태그라도 다른 컴퓨터나
   다른 날짜에 다른 결과가 생길 수 있습니다.
2. 해당 demo dashboard 번들은 API와 trajectory 주소
   `http://localhost:8000`, `ws://localhost:8006`을 빌드 시점에 포함하며,
   실행 시 `RMF_SERVER_URL` 같은 환경 변수를 넣어도 정적 JavaScript가
   변경되지 않습니다.

그래서 `run_office_web.sh`는 nightly 이미지를 직접 실행하지 않습니다.
[`openrmf/docker/rmf-web-dashboard/Dockerfile`](../docker/rmf-web-dashboard/Dockerfile)이
공식 `rmf-web` 0.3.0에 해당하는 커밋
`7aa265337936a5bd9a920b3fa2360a43244a015c`을 내려받고, pnpm `9.15.9`와
Node.js 20으로 dashboard를 빌드한 뒤 nginx 이미지로 제공합니다. 커밋과
빌드 도구를 고정했기 때문에 집 컴퓨터에서도 현재 컴퓨터와 같은 프런트엔드를
만들 수 있습니다.

수정 후 실제 전체 office 시뮬레이션으로 다음 항목을 확인했습니다.

- 상단 `MAP`, `ROBOTS`, `TASKS`, `CUSTOM` 메뉴 표시
- L1 building map 표시
- `tinyRobot1`, `tinyRobot2` 상태 및 지도 표식 수신
- rmf-web API `http://127.0.0.1:8000` 연결
- trajectory WebSocket `ws://127.0.0.1:8006` 연결

### 집 컴퓨터에서 다시 빈 화면이 나타날 때

먼저 API, dashboard HTML, 컨테이너 상태를 각각 확인합니다.

```bash
curl --fail http://127.0.0.1:8000/time
curl --fail http://127.0.0.1:3000
docker ps --filter name=robosapiens-rmf
docker logs robosapiens-rmf-api
docker logs robosapiens-rmf-dashboard
```

- `8000/time`만 실패하면 rmf-web API 또는 Docker/ROS 설정 문제입니다.
- `3000`만 실패하면 dashboard 컨테이너나 포트 3000 문제입니다.
- 둘 다 응답하지만 화면이 비면 브라우저 개발자 도구의 `Console`과
  `Network` 탭을 확인하고 강력 새로고침(`Ctrl+Shift+R`)합니다.
- 지도 영역만 비고 상단 메뉴는 보이면 WebGL 하드웨어 가속이 꺼졌는지
  확인합니다. Open-RMF 지도는 WebGL을 사용하므로 브라우저 설정에서
  하드웨어 가속을 활성화하고 브라우저를 다시 시작합니다.

포트 사용 여부는 다음과 같이 확인합니다.

```bash
ss -ltnp | grep -E ':(3000|8000|8006)\b'
```

이 저장소의 이전 실행이 남아 있으면 먼저 정리한 후 다시 실행합니다.

```bash
./openrmf/scripts/stop_office.sh
docker stop robosapiens-rmf-dashboard 2>/dev/null || true
docker rm robosapiens-rmf-dashboard 2>/dev/null || true
./openrmf/scripts/run_office_web.sh
```

로컬 dashboard 이미지가 손상되었거나 Dockerfile 변경분을 반영해야 할 때만
이미지를 다시 빌드합니다. 이 작업은 dashboard 이미지만 삭제하며 RMF
workspace나 사용자 데이터는 삭제하지 않습니다.

```bash
docker image rm robosapiens-rmf-dashboard:0.3.0
docker build \
  --tag robosapiens-rmf-dashboard:0.3.0 \
  ./openrmf/docker/rmf-web-dashboard
```

빌드가 소스 다운로드 단계에서 실패하면 인터넷/DNS/프록시가 GitHub와 pnpm
설치 서버에 접근할 수 있는지 확인합니다. `permission denied while trying to
connect to the Docker daemon socket` 오류는 Docker 그룹 권한 문제이므로 이
문서 1장의 Docker 설정을 적용한 뒤 로그아웃하고 다시 로그인합니다.

## 3. 수동 실행

구성요소별 로그를 따로 확인하려면 세 개의 터미널을 사용합니다.

### 터미널 1: rmf-web API

```bash
docker run --rm \
  --name robosapiens-rmf-api \
  --network host \
  --ipc host \
  -e ROS_DOMAIN_ID=0 \
  -e RMW_IMPLEMENTATION=rmw_fastrtps_cpp \
  -e FASTDDS_BUILTIN_TRANSPORTS=UDPv4 \
  -e RMF_SERVER_USE_SIM_TIME=true \
  ghcr.io/open-rmf/rmf-web/api-server:jazzy
```

API 응답과 문서를 확인합니다.

```bash
curl http://127.0.0.1:8000/time
```

브라우저 API 문서:

```text
http://127.0.0.1:8000/docs
```

### 터미널 2: Open-RMF office

```bash
cd /home/gyi/robosapiens

source /opt/ros/jazzy/setup.bash
source "$HOME/rmf_ws/install/setup.bash"

ros2 launch openrmf/launch/office_web.launch.xml \
  server_uri:=ws://127.0.0.1:8000/_internal
```

이 launch 파일은 dispatcher와 `tinyRobot` fleet adapter 양쪽에 rmf-web 주소를
전달합니다.

### 터미널 3: Flutter 관제 앱

```bash
cd /home/gyi/robosapiens/openrmf_app
flutter pub get
flutter run -d linux \
  --dart-define=RMF_API_URL=http://127.0.0.1:8000
```

Flutter 앱은 시작할 때 `/time`으로 백엔드를 확인합니다. 백엔드가 꺼져 있으면
기본적으로 `openrmf` API와 office 시뮬레이션을 자동 실행하고 building map이
준비된 후 관제 화면을 엽니다. 따라서 개발 중에는 터미널 1과 2를 생략하고
Flutter 앱만 직접 실행해도 됩니다. 앱이 시작한 백엔드는 앱 종료 시 함께
종료됩니다. 앱에서 자동 실행할 때는 기본적으로 headless 백그라운드 모드가
적용되어 Gazebo와 RViz 창을 열지 않습니다.

Gazebo 및 RViz 화면이 필요한 경우에만 다음과 같이 실행합니다.

```bash
RMF_HEADLESS=false flutter run -d linux
```

비정상 종료 후 기존 office launch 또는 그 자식인 fleet manager/fleet adapter만
남고 API가 사라진 상태라면 앱이 남은 프로세스를 먼저 종료한 뒤 새 백엔드를
시작합니다. 이를 통해 fleet manager의
`127.0.0.1:22011 address already in use` 중복 실행 오류를 방지합니다.

외부에서 관리하는 백엔드만 사용하려면 자동 시작을 끕니다.

```bash
flutter run -d linux \
  --dart-define=RMF_AUTO_START=false \
  --dart-define=RMF_API_URL=http://192.168.0.20:8000
```

빌드 결과물을 저장소 밖으로 옮긴 경우 실행 스크립트를 찾을 수 있도록
`RMF_ROOT=/home/gyi/robosapiens`를 지정합니다.

로컬 개발 환경에서는 rmf-web 공식 개발용 관리자 토큰이 기본 적용됩니다.
인증 서버를 사용하는 환경에서는 발급받은 토큰을 지정합니다.

```bash
flutter run -d linux \
  --dart-define=RMF_API_URL=https://rmf.example.com \
  --dart-define=RMF_API_TOKEN="$ACCESS_TOKEN"
```

## 4. 정상 작동 확인

다음 항목을 순서대로 확인합니다.

1. Gazebo에 office 공간과 `tinyRobot1`, `tinyRobot2`가 표시되는지 확인
2. Flutter 상단 연결 상태가 `API ONLINE`인지 확인
3. 왼쪽 로봇 목록에 두 로봇이 표시되는지 확인
4. 지도 위 로봇 마커가 Gazebo 로봇 이동에 맞춰 갱신되는지 확인
5. 오른쪽 `TASK ACTIVITY`에 RMF 태스크가 표시되는지 확인

로봇 이동을 확인하려면 별도 터미널에서 patrol 태스크를 요청합니다.

```bash
source /opt/ros/jazzy/setup.bash
source "$HOME/rmf_ws/install/setup.bash"

ros2 run rmf_demos_tasks dispatch_patrol \
  -p coe lounge \
  -n 3 \
  --use_sim_time
```

태스크가 배정되면 Flutter에서 로봇 상태가 `작업 중`으로 바뀌고, 지도 마커가
이동하며 오른쪽 태스크 목록에 진행 상태가 표시됩니다.

## 5. 종료

자동 실행 중에는 Flutter 터미널에서 `q`를 누르거나 `Ctrl+C`를 입력합니다.
통합 스크립트가 자신이 실행한 ROS 프로세스와 API 컨테이너를 함께 종료합니다.

앱이나 터미널이 비정상 종료되어 백그라운드 프로세스가 남았거나, 실행 중인
Open-RMF를 수동으로 모두 종료하려면 다음 스크립트를 사용합니다.

```bash
cd /home/gyi/robosapiens
./openrmf/scripts/stop_office.sh
```

스크립트는 다음 순서로 종료합니다.

1. `openrmf_app`이 시작한 backend supervisor
2. 이 저장소의 `office_web.launch.xml` ROS 2 launch
3. 비정상 종료로 남은 office fleet manager, fleet adapter 및 Gazebo 프로세스
4. `robosapiens-rmf-api` Docker 컨테이너

다른 ROS 2 프로젝트의 프로세스와 다른 Docker 컨테이너는 종료하지 않습니다.
종료 대기 시간의 기본값은 15초이며 필요한 경우 변경할 수 있습니다.

```bash
RMF_STOP_WAIT_SECONDS=30 ./openrmf/scripts/stop_office.sh
```

종료 상태는 다음과 같이 확인합니다.

```bash
curl --max-time 2 http://127.0.0.1:8000/time
docker ps --filter name=robosapiens-rmf-api
ps -ef | grep office_web.launch.xml
```

`curl`은 연결 실패하고, Docker 및 launch 프로세스 목록은 비어 있어야 합니다.

수동 실행한 경우 다음 순서로 종료합니다.

1. Flutter 터미널에서 `q` 또는 `Ctrl+C`
2. office launch 터미널에서 `Ctrl+C`
3. API 터미널에서 `Ctrl+C`

백그라운드 API 컨테이너가 남아 있다면 다음 명령으로 종료합니다.

```bash
docker stop robosapiens-rmf-api
```

## 6. 문제 해결

### `Docker daemon is not accessible`

```bash
docker info
groups
```

현재 사용자가 Docker 그룹에 포함되어 있는지 확인합니다. 그룹을 변경한 직후에는
로그아웃과 재로그인이 필요합니다.

### Flutter에 `API OFFLINE` 표시

```bash
curl http://127.0.0.1:8000/time
docker logs robosapiens-rmf-api
```

API 주소가 다른 경우 `RMF_API_URL`을 실제 주소로 지정합니다.

### API는 연결됐지만 로봇이 표시되지 않음

office launch가 API 내부 WebSocket 주소를 받았는지 확인합니다.

```bash
ros2 topic echo /fleet_states
```

`/fleet_states`에 데이터가 있지만 Flutter가 비어 있다면 API 컨테이너와 ROS의
`ROS_DOMAIN_ID`, `RMW_IMPLEMENTATION` 값이 같은지 확인합니다.

현재 설치된 RMW 구현은 다음 명령으로 확인할 수 있습니다.

```bash
ros2 doctor --report | grep -A2 "RMW MIDDLEWARE"
```

이 시스템의 기본 구현은 `rmw_fastrtps_cpp`입니다. 통합 실행 스크립트는 설치된
Fast DDS 또는 CycloneDDS 라이브러리를 자동으로 찾아 선택합니다.

Fast DDS 사용 시 스크립트는 `FASTDDS_BUILTIN_TRANSPORTS=UDPv4`를 ROS와 API
컨테이너에 함께 설정합니다. 호스트와 컨테이너가 서로 다른 공유 메모리를 사용해
building map이나 fleet state를 발견하지 못하는 문제를 방지하기 위한 설정입니다.

### building map이 표시되지 않음

```bash
ros2 topic echo /map --once
```

Flutter 앱을 먼저 실행했다면 office launch가 완전히 올라온 뒤 새로고침 버튼을
누릅니다. 앱은 기본적으로 1초마다 자동 갱신합니다.

### Open-RMF workspace가 다른 위치에 있음

자동 실행 전에 `RMF_WS`를 지정합니다.

```bash
RMF_WS=/path/to/rmf_ws ./openrmf/scripts/run_office_flutter.sh
```

### API 또는 ROS가 다른 장비에서 실행됨

```bash
RMF_API_URL=http://192.168.0.20:8000 \
RMF_SERVER_URI=ws://192.168.0.20:8000/_internal \
./openrmf/scripts/run_office_flutter.sh
```

방화벽에서 TCP `8000` 포트와 ROS 2 DDS 통신이 허용되어야 합니다.
