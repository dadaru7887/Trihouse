# Open-RMF Office Flutter Console

This integration runs the stock Open-RMF office simulation, connects its
dispatcher and `tinyRobot` fleet adapter to the official `rmf-web` API server,
and renders that API in a dedicated Flutter desktop console.

한국어 실행 순서는
[`docs/OPENRMF_APP_RUN_GUIDE.md`](docs/OPENRMF_APP_RUN_GUIDE.md)를 참고합니다.

```text
rmf_demos_gz office
        |
        | ROS 2 + ws://127.0.0.1:8000/_internal
        v
rmf-web api-server
        |
        | GET /building_map, /fleets, /tasks
        v
openrmf_app (Flutter)
```

## Run everything

Prerequisites:

- Ubuntu 24.04, ROS 2 Jazzy and a built `~/rmf_ws`
- Docker access for the current user
- Flutter with Linux desktop support

```bash
cd /home/gyi/robosapiens
./openrmf/scripts/run_office_flutter.sh
```

## Stop background services

Normally, services started by `openrmf_app` are stopped when the app exits.
If the app or terminal closes unexpectedly, stop this repository's office
launch and rmf-web API container with:

```bash
cd /home/gyi/robosapiens
./openrmf/scripts/stop_office.sh
```

The script targets the `office_web.launch.xml` process from this repository,
its office fleet-manager/fleet-adapter/Gazebo processes, and the configured
API container (`robosapiens-rmf-api` by default). It does not stop unrelated
ROS 2 processes or Docker containers.

To verify that the services are stopped:

```bash
curl --max-time 2 http://127.0.0.1:8000/time
docker ps --filter name=robosapiens-rmf-api
```

The `curl` command should fail to connect and the container list should be
empty.

The Flutter Linux application also performs this bootstrap automatically.
When `flutter run -d linux` or the built `openrmf_app` binary is launched
directly, it checks the rmf-web `/time` endpoint. If the backend is offline,
the app starts the API server and office simulation, waits for the building
map, and then opens the dashboard. A backend started this way is stopped when
the app exits. App-managed startup defaults to headless mode so Open-RMF runs
in the background without Gazebo or RViz windows. Use
`RMF_HEADLESS=false flutter run -d linux` when those GUI windows are needed.

If a prior abnormal exit left this repository's office launch or orphaned
office fleet-manager/fleet-adapter processes alive while the API is offline,
startup automatically stops those stale processes before creating a new
backend. This prevents duplicate fleet managers from competing for port
`22011`.

Set `RMF_AUTO_START=false` at build time to use an externally managed backend:

```bash
flutter run -d linux --dart-define=RMF_AUTO_START=false
```

If the built application is moved outside this repository, set `RMF_ROOT` to
the repository root so it can locate the launcher script.

The script starts the official
`ghcr.io/open-rmf/rmf-web/api-server:jazzy` container, launches the office
world with the API URI forwarded to both RMF components, waits for the building
map, and starts Flutter.

For separate terminals:

```bash
# Terminal 1: API and office simulation
./openrmf/scripts/start_backend.sh

# Terminal 2: Flutter
cd openrmf_app
flutter run -d linux --dart-define=RMF_API_URL=http://127.0.0.1:8000
```

## Run the web dashboard

Open-RMF 자체 브라우저 대시보드를 사용하려면 별도 스크립트를 실행합니다.

```bash
cd /home/gyi/robosapiens
./openrmf/scripts/run_office_web.sh
```

준비가 끝나면 브라우저에서 <http://localhost:3000>을 엽니다. 스크립트는
rmf-web API, 고정된 공식 rmf-web 0.3.0 소스로 만든 자체 대시보드, office
시뮬레이션을 실행합니다. `Ctrl+C` 입력 시 스크립트가 시작한 구성요소를 함께
종료합니다.

첫 실행에서는 `openrmf/docker/rmf-web-dashboard/Dockerfile`로
`robosapiens-rmf-dashboard:0.3.0` 이미지를 빌드하므로 시간이 걸릴 수 있습니다.
이후 실행은 빌드된 이미지를 재사용합니다. 깨진 nightly dashboard 이미지는
사용하지 않으며 Flutter Web도 사용하지 않습니다.

빈 화면의 원인은 당시 `demo-dashboard:jazzy-nightly` JavaScript 번들에서
React Router가 Router 문맥 밖에서 실행되어 초기 렌더링이 중단된 것이었습니다.
nightly 태그는 내용이 바뀔 수 있고 정적 번들에 포함된 API 주소는 컨테이너
환경 변수로 교체되지 않으므로, 공식 rmf-web 0.3.0 커밋과 빌드 도구 버전을
Dockerfile에 고정했습니다.

다른 컴퓨터로 이전하는 절차, 최초 이미지 빌드, API/dashboard/포트별 진단,
WebGL 확인, 이미지 재빌드 방법은
[`웹 대시보드 빈 화면 원인과 해결 내용`](docs/OPENRMF_APP_RUN_GUIDE.md#웹-대시보드-빈-화면-원인과-해결-내용)에
정리되어 있습니다.

The API documentation is available at <http://127.0.0.1:8000/docs> while the
backend is running. The Flutter client polls RMF state once per second, while
the RMF dispatcher and fleet adapter publish their state to the API server's
internal WebSocket endpoint.

The app defaults to rmf-web's documented development `admin` token. For a
secured deployment, pass the identity provider token explicitly:

```bash
flutter run -d linux \
  --dart-define=RMF_API_URL=https://rmf.example.com \
  --dart-define=RMF_API_TOKEN="$ACCESS_TOKEN"
```

## Flutter dashboard capabilities

`openrmf_app` provides the operator-facing capabilities of the official demo
dashboard in one desktop application:

- multi-level building map, live robot state and planned trajectory overlays
- robot battery, issues, fleet filtering, commission/decommission and mutex
  group release
- patrol, delivery, clean and custom compose task dispatch
- active task cancellation, state/log inspection and recurring schedules
- door and lift state/control, dispenser and ingestor state
- actionable RMF alerts

The ROS 2 dispatcher, fleet adapters, rmf-web API and optional trajectory
server remain backend services. Unsupported optional endpoints on older Jazzy
API images are shown as empty dashboard sections instead of taking the whole
console offline.

## Configuration

| Variable | Default |
| --- | --- |
| `RMF_WS` | `$HOME/rmf_ws` |
| `RMF_API_URL` | `http://127.0.0.1:8000` |
| `RMF_SERVER_URI` | `ws://127.0.0.1:8000/_internal` |
| `ROS_DOMAIN_ID` | `0` |
| `RMW_IMPLEMENTATION` | 설치된 Fast DDS/CycloneDDS 구현 자동 선택 |
| `RMF_HEADLESS` | 앱 자동 실행은 `true`; 통합 스크립트 직접 실행은 `false` |
| `RMF_API_WAIT_SECONDS` | `60` |
| `RMF_MAP_WAIT_SECONDS` | `90` |
| `RMF_API_IMAGE` | `ghcr.io/open-rmf/rmf-web/api-server:jazzy` |
| `RMF_DASHBOARD_URL` | `http://localhost:3000` |
| `RMF_DASHBOARD_PORT` | `3000` |
| `RMF_DASHBOARD_IMAGE` | `robosapiens-rmf-dashboard:0.3.0` |
| `RMF_TRAJECTORY_SERVER_URL` | `ws://127.0.0.1:8006` |
| `RMF_OPEN_BROWSER` | `true` |
