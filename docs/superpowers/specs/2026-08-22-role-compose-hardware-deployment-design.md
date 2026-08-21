# Trihouse 역할별 Compose 및 장비 식별자 통합 설계

## 목표

Trihouse를 여섯 개의 실제 호스트 역할과 한 개의 시뮬레이션 역할로 나누고, 각
호스트에서 한 명령으로 자기 역할의 Docker/ROS 2 계층을 기동·중지·진단한다.
장비를 지칭하는 모든 기계 통신은 `devices.device_id`만 사용하며 DB 표시명도 같은
값으로 고정한다. 모든 실제 ROS 2 호스트는 `ROS_DOMAIN_ID=12`와 같은 Wi-Fi
서브넷을 사용한다.

## 확정된 운영 원칙

1. 실제 장비 ID는 `PK_01`, `PK_02`, `OMX_01`, `OMX_02`다.
2. `devices.name = devices.device_id`를 DB 제약과 애플리케이션 검증으로 강제한다.
3. ROS namespace는 각각 `pinky_01`, `pinky_02`, `omx_01`, `omx_02`이며 DB나
   명령 ID로 사용하지 않는다.
4. 모든 장비가 현재의 같은 Wi-Fi 공유기와 같은 subnet을 사용한다.
5. 실제 시스템의 ROS 2 통신 계약은 다음과 같다.

   ```dotenv
   ROS_DOMAIN_ID=12
   ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
   RMW_IMPLEMENTATION=rmw_fastrtps_cpp
   FASTDDS_BUILTIN_TRANSPORTS=UDPv4
   ```

6. 카메라는 H.264 RTSP를 RTX 4060의 MediaMTX에 한 번 publish한다. RTX 5080은
   MediaMTX에서 같은 원본 스트림을 read-only로 구독한다.
7. `doctor`는 읽기 전용이다. 환경 파일을 만들거나 컨테이너를 시작하지 않는다.
8. `bootstrap`은 최초 로컬 설정을 준비하고, `up`은 preflight 이후 역할 스택을
   시작하며 healthcheck를 기다린다.

## 장비 식별자 경계

### 정식 ID와 namespace

| DB·FMS·RMF·메시지 ID | DB `name` | ROS namespace |
|---|---|---|
| `PK_01` | `PK_01` | `/pinky_01` |
| `PK_02` | `PK_02` | `/pinky_02` |
| `OMX_01` | `OMX_01` | `/omx_01` |
| `OMX_02` | `OMX_02` | `/omx_02` |

`assigned_mobile_id`, `assigned_device_id`, `integration_messages.device_id`, RMF
`robot_name`, `RobotStatus.robot_id`, `TaskEvent.robot_id`, OMX command `omx_id`와
모든 결과의 `actor_device_id`는 위 정식 ID만 받는다.

namespace는 ROS graph 격리에만 사용한다. namespace에서 업무 ID를 문자열
치환으로 추측하지 않는다. 각 역할의 환경 계약에 `DEVICE_ID`와 `ROS_NAMESPACE`를
별도 선언하고, 시작 전 고정 매핑과 일치하는지 검사한다. `PK-01`, `pinky_01`,
`OMX-01`, `omx_01` 같은 alias가 기계 ID 자리에 들어오면 자동 보정하지 않고
명시적으로 실패시킨다.

### DB 변경

- 기존 네 장비의 `name`을 각 `device_id`로 migration한다.
- MySQL 8.4 `CHECK (name = device_id)` 제약을 추가한다.
- 개발 seed와 map-project 장비 import는 `name=device_id`만 기록한다.
- 장비 등록·수정 API는 다른 `name`을 거절한다.
- UI가 친숙한 설명을 필요로 하면 통신과 무관한 별도 metadata를 사용한다. `name`을
  라우팅 alias로 재사용하지 않는다.
- 저장소·worker·adapter의 명령 선택은 `device_id` 또는 이를 참조하는 FK만 사용한다.

## 영상 경로

### 운영 데이터 흐름

```text
Pinky Pi / OMX PC / 4060 고정 카메라
             │ H.264 RTSP over TCP
             ▼
       RTX 4060 MediaMTX
        ├─ fMP4 원본 녹화
        ├─ QR·ArUco 처리
        ├─ 관제 화면 read
        └─ RTX 5080 read-only 구독
             ├─ YOLO
             ├─ VLM/RL
             └─ ACT 추론
```

카메라 송신기는 `config/cameras.yaml`의 정식 `camera_id`로 정해진 경로 하나에만
publish한다. 5080은 별도 카메라 ID 환경변수를 중복 보관하지 않고 MediaMTX base
URL과 마운트된 카메라 registry에서 구독 경로를 만든다.

초기 배포에서는 VLAN, 별도 SSID, 프레임 중계 API를 추가하지 않는다. Wi-Fi
대역폭 문제가 측정되면 먼저 H.264 720p, 10~15 FPS, 카메라당 2~4 Mbps로 제한하고,
그 다음 4060·5080만 유선으로 연결한다. 소프트웨어 경로 변경은 마지막 수단이다.

### 장애 경계

- 5080 장애: 4060 녹화·QR·관제와 로봇 제어는 계속된다.
- 4060 또는 MediaMTX 장애: 새 영상의 녹화·QR·AI 입력이 모두 중단되며 각 송신기는
  재연결한다. 로봇의 safety와 정지 판단은 영상 서버 응답에 의존하지 않는다.
- 인터넷 장애: 같은 Wi-Fi LAN 내부의 ROS 2와 RTSP는 계속 동작해야 한다.
- Wi-Fi AP의 client/AP isolation이 켜져 있으면 배포 전 검사에서 실패시킨다.

## 호스트 역할

| 역할 | 호스트 | 컨테이너 책임 |
|---|---|---|
| `control-4060` | RTX 4060 | MySQL, FMS Gateway, UI, RMF core/API/dashboard, job runner, executor 경계, MediaMTX, QR, 녹화 catalog |
| `ai-5080` | RTX 5080 | YOLO, VLM/RL, ACT 추론, model/data/artifact volume, ACK 기반 recovery queue |
| `pinky-01` | PK_01 Raspberry Pi | vendor sensor/motor driver, safety supervisor, Nav2, fleet/status/gateway, 주행 카메라 publisher |
| `pinky-02` | PK_02 Raspberry Pi | `pinky-01`과 동일하되 `DEVICE_ID=PK_02`, `ROS_NAMESPACE=pinky_02` |
| `omx-01` | OMX_01 연결 PC | 실기 OMX driver/adapter, 상태·ack, 손목 카메라 publisher |
| `omx-02` | OMX_02 연결 PC | `omx-01`과 동일하되 `DEVICE_ID=OMX_02`, `ROS_NAMESPACE=omx_02` |
| `simulation` | 개발/시연 PC | MySQL, Gateway, UI, MediaMTX fixture, RMF, Gazebo, 가상 Pinky/OMX, workers |

호스트가 다른 Compose project는 Docker bridge network를 공유하지 않는다. HTTP,
TCP, RTSP와 ROS 2 DDS는 호스트의 LAN 주소로 통신한다. ROS 2가 필요한 컨테이너는
`network_mode: host`와 `ipc: host`를 사용한다. USB·serial·camera 장치는 필요한
`devices`만 전달하고 전체 `privileged: true`는 사용하지 않는다.

## Compose 파일 구조

기존 서비스 정의를 재사용하고 역할별 overlay가 정확한 서비스 집합과 하드웨어
mount를 선택한다.

```text
compose.yaml                         공통 MySQL/FMS 기반
compose.control.yaml                 Gateway와 관제 UI
compose.edge_4060.yaml               MediaMTX·QR·녹화
compose.ai_5080.yaml                 5080 추론
compose.simulation.yaml              시뮬레이션 web 지원
compose.roles/control-4060.yaml      4060 RMF·worker 역할 overlay
compose.roles/pinky.yaml             두 Pinky Pi 공용 overlay
compose.roles/omx.yaml               두 OMX PC 공용 overlay
compose.roles/simulation.yaml        전체 headless simulation overlay
docker/ros/Dockerfile.control        x86_64 RMF·worker runtime
docker/ros/Dockerfile.omx            x86_64 OMX runtime
docker/ros/Dockerfile.pinky          arm64 Pinky runtime
```

`scripts/control_stack`이 역할과 mode에 따라 compose file 목록과 project name을
결정한다. 사용자가 여러 `-f` 옵션을 직접 조합하지 않는다.

## `.env` 계약

추적되는 정본은 `.env.example` 하나다. 각 호스트는 이를 `.env`로 복사하고 자기
역할 구간만 실제 값으로 채운다. `.env`는 Git에 포함하지 않는다. 빈 값이나
`change_me_*`, RFC 5737 문서용 IP가 남아 있으면 hardware `up`이 실패한다.

### 1. 공통 구간 — 모든 호스트

```dotenv
# [identity]
TRIHOUSE_MODE=hardware
TRIHOUSE_ROLE=control-4060
TZ=Asia/Seoul

# [ros2]
ROS_DOMAIN_ID=12
ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
RMW_IMPLEMENTATION=rmw_fastrtps_cpp
FASTDDS_BUILTIN_TRANSPORTS=UDPv4

# [lan]
CONTROL_4060_IP=192.168.0.40
AI_5080_IP=192.168.0.50
FMS_API_PORT=8080
FMS_TCP_PORT=8788
MEDIAMTX_RTSP_PORT=8554
```

`TRIHOUSE_ROLE`은 각 호스트에서 `control-4060`, `ai-5080`, `pinky-01`,
`pinky-02`, `omx-01`, `omx-02` 중 하나다. simulation 호스트만
`TRIHOUSE_MODE=simulation`, `TRIHOUSE_ROLE=simulation`을 사용한다.

### 2. 4060 관제 구간

```dotenv
# [control-4060/database]
MYSQL_ROOT_PASSWORD=change_me_root
FMS_DB_DATABASE=trihouse_fms
FMS_DB_USER=fms_gateway
FMS_DB_PASSWORD=change_me_gateway
FMS_DB_POOL_SIZE=5
FMS_DB_PORT=3308

# [control-4060/bind]
FMS_API_HOST=0.0.0.0
FMS_TCP_BIND=0.0.0.0
CONTROL_UI_HOST=0.0.0.0
CONTROL_UI_PORT=3100
EDGE_BIND_ADDRESS=192.168.0.40
RMF_DASHBOARD_PORT=3000

# [control-4060/media]
MTX_VIEWER_PASS=change_me_viewer
PINKY_PK_01_IP=192.168.0.11
PINKY_PK_02_IP=192.168.0.12
OMX_PC_01_IP=192.168.0.31
OMX_PC_02_IP=192.168.0.32
PC1_PUBLISHER_IP=192.168.0.40
TRIHOUSE_VIDEO_DIR=/srv/trihouse/video
TRIHOUSE_RECORD_SEGMENT_DURATION=60s
TRIHOUSE_RECORD_DELETE_AFTER=168h

# [control-4060/images]
TRIHOUSE_QR_IMAGE=trihouse_qr_worker:local
TRIHOUSE_RECORDING_IMAGE=trihouse_recording_catalog:local
TRIHOUSE_CONTROL_ROS_IMAGE=trihouse_control_ros:jazzy
```

hardware 모드에서는 API·TCP·UI·RTSP가 다른 LAN 장비에서 접근해야 하므로 4060의
LAN 주소 또는 `0.0.0.0`에 bind한다. 방화벽은 같은 운영 subnet만 허용한다. DB
포트는 계속 loopback으로만 노출한다.

### 3. 5080 AI 구간

```dotenv
# [ai-5080/endpoints]
FMS_GATEWAY_URL=http://192.168.0.40:8080
VISION_RTSP_BASE_URL=rtsp://viewer:change_me_viewer@192.168.0.40:8554

# [ai-5080/runtime]
TRIHOUSE_AI_IMAGE=trihouse_ai_5080:env
TRIHOUSE_AI_SHM_SIZE=16gb
TRIHOUSE_AI_MODEL_DIR=/srv/trihouse/ai/models
TRIHOUSE_AI_DATASET_DIR=/srv/trihouse/ai/data
TRIHOUSE_AI_ARTIFACT_DIR=/srv/trihouse/ai/artifacts
TRIHOUSE_AI_QUEUE_DIR=/srv/trihouse/ai/recovery_queue
VISION_FRAME_WIDTH=1280
VISION_FRAME_HEIGHT=720
VISION_INFERENCE_FPS=15
```

5080에는 MySQL host, user, password를 전달하지 않는다. `config/cameras.yaml`을
read-only로 마운트하고 `VISION_RTSP_BASE_URL` 뒤에 registry의 역할 경로와
`camera_id`를 붙인다.

### 4. Pinky Pi 구간

`pinky-01` 예시이며 두 번째 Pi는 ID·namespace·IP·카메라 ID만 바꾼다.

```dotenv
# [pinky/identity]
DEVICE_ID=PK_01
ROS_NAMESPACE=pinky_01
ROBOT_LAN_IP=192.168.0.11

# [pinky/control]
FMS_GATEWAY_URL=http://192.168.0.40:8080
FMS_TCP_HOST=192.168.0.40
MAP_NAME=trihouse_test_01
MAP_REVISION=trihouse_test_01:approved_revision
NAV2_MAP_FILE=/opt/trihouse/maps/trihouse_test_01/map.yaml
NAV2_PARAMS_FILE=/opt/trihouse/config/nav2/pinky_01.yaml
NARROW_ZONES_FILE=/opt/trihouse/config/narrow_zones.yaml
MARKER_DOCKS_FILE=/opt/trihouse/config/marker_docks.yaml

# [pinky/devices]
PINKY_CAMERA_DEVICE=/dev/video0
PINKY_SERIAL_DEVICE=/dev/ttyUSB0

# [pinky/media]
CAMERA_ID=CAM-PK-01
RTSP_PUBLISH_URL=rtsp://192.168.0.40:8554/pinky/CAM-PK-01
CAMERA_WIDTH=1280
CAMERA_HEIGHT=720
CAMERA_FPS=15
```

`MAP_REVISION`의 예시 문자열은 hardware에서 허용되는 값이 아니다. Gateway가
발행한 실제 revision과 지도 파일을 bootstrap 단계에서 내려받아 채워야 한다.

### 5. OMX PC 구간

`omx-01` 예시이며 두 번째 PC는 OMX/Pinky ID, namespace, IP와 카메라 ID를 바꾼다.

```dotenv
# [omx/identity]
DEVICE_ID=OMX_01
ROS_NAMESPACE=omx_01
PAIRED_PINKY_ID=PK_01
ROBOT_LAN_IP=192.168.0.31

# [omx/control]
FMS_GATEWAY_URL=http://192.168.0.40:8080
OMX_SERIAL_DEVICE=/dev/ttyUSB0
OMX_JOINT_STATE_TOPIC=joint_states
OMX_GRIPPER_ACK_TOPIC=gripper/ack
OMX_EMERGENCY_ACK_TOPIC=emergency/ack
OMX_PAYLOAD_LIMIT_KG=0.5

# [omx/media]
OMX_CAMERA_DEVICE=/dev/video0
CAMERA_ID=CAM-OMX-01-WRIST
RTSP_PUBLISH_URL=rtsp://192.168.0.40:8554/omx/CAM-OMX-01-WRIST
CAMERA_WIDTH=1280
CAMERA_HEIGHT=720
CAMERA_FPS=15
```

실기 OMX motion은 endpoint 이름을 채웠다는 이유만으로 활성화하지 않는다. 실제
driver의 command/ack 계약과 E-stop 검증을 통과한 hardware plugin만 motion을 낸다.

### 6. simulation 구간

```dotenv
# [simulation]
TRIHOUSE_MODE=simulation
TRIHOUSE_ROLE=simulation
ROS_DOMAIN_ID=12
TRIHOUSE_PROJECT=trihouse_test_01
TRIHOUSE_ROBOTS=PK_01,PK_02
TRIHOUSE_START_NAV2=true
TRIHOUSE_START_WORKER=true
TRIHOUSE_START_JOB_RUNNER=true
TRIHOUSE_START_EXECUTOR=true
TRIHOUSE_GUI=false
TRIHOUSE_RVIZ=false
TRIHOUSE_ACT_CONFIG=/opt/trihouse/config/act.simulation.yaml
```

simulation과 hardware는 같은 subnet에서 동시에 실행하지 않는다. 둘 다 domain 12를
사용하므로 `up`은 같은 호스트에 반대 mode project가 실행 중이면 거절하고, 운영
runbook은 전체 LAN에서 한 mode만 사용하도록 명시한다.

## Lifecycle CLI

공개 명령은 다음과 같다.

```bash
./scripts/control_stack bootstrap --mode hardware --role control-4060
./scripts/control_stack up        --mode hardware --role control-4060 --build
./scripts/control_stack status    --mode hardware --role control-4060
./scripts/control_stack logs      --mode hardware --role control-4060
./scripts/control_stack doctor    --mode hardware --role control-4060
./scripts/control_stack down      --mode hardware --role control-4060

./scripts/control_stack up        --mode simulation --role simulation --build
./scripts/control_stack doctor    --mode simulation --role simulation
```

명령행 `--role`을 생략하면 `.env`의 `TRIHOUSE_ROLE`을 사용한다.

### `bootstrap`

- `.env`가 없으면 `.env.example`을 `.env`로 복사한다.
- 역할별 runtime 디렉터리를 생성한다.
- Docker/Compose, CPU architecture, NVIDIA runtime, serial/video device, ROS 2
  network 전제조건을 역할에 맞게 검사한다.
- 비밀번호, IP, 실제 map revision 또는 장치 경로를 추측하지 않는다.
- root 권한 설치나 방화벽 변경은 자동 수행하지 않고 필요한 명령을 출력한다.

### `up`

- `.env` 필수값, canonical ID/namespace 매핑, `ROS_DOMAIN_ID=12`, IP와 장치 경로를
  먼저 검사한다.
- 역할에 맞는 Compose project와 overlay만 선택한다.
- `docker compose config --quiet` 이후 `up -d --wait`를 실행한다.
- healthcheck 실패 시 실패한 서비스와 다음 `logs` 명령을 출력한다.
- hardware에서 시뮬레이터 image나 mock cargo confirmation을 시작하지 않는다.

### `doctor`

어떠한 상태도 변경하지 않고 JSON을 출력한다. 공통 필드는 `mode`, `role`,
`ros_domain_id`, `checks`, `healthy`다.

- 4060: MySQL, Gateway `/ready`, UI, RMF schedule, workers, MediaMTX API/metrics,
  등록된 여섯 camera path를 검사한다.
- 5080: NVIDIA runtime, AI container, Gateway GET, 여섯 RTSP 경로의 bounded decode,
  recovery queue writeability를 검사한다.
- Pinky: serial/video device, ROS namespace, sensor freshness, status topic,
  `ExecuteTransport` action, safety가 실제 motor topic의 유일한 publisher인지 검사한다.
- OMX: serial/video device, namespace, joint state와 ack freshness, camera path,
  hardware motion plugin의 승인 상태를 검사한다.
- simulation: Docker services, RMF/Gazebo, 두 Pinky/Nav2, 두 OMX simulator, 세 worker를
  검사한다.

물리 이동 명령, 주문 생성, DB 쓰기, 컨테이너 시작과 장치 reset은 doctor에서 금지한다.

## 테스트 전략

1. DB migration integration test가 기존 표시명을 canonical ID로 바꾸고 다른 이름의
   INSERT/UPDATE를 거절하는지 검증한다.
2. API·repository 단위 테스트가 `name`, namespace, 하이픈 alias로 할당하거나
   명령을 claim하지 못하는지 검증한다.
3. `.env.example` 계약 테스트가 모든 구간, `ROS_DOMAIN_ID=12`, 역할별 필수 변수를
   검증한다.
4. 역할별 `docker compose config --quiet`를 placeholder가 아닌 test env로 실행한다.
5. lifecycle CLI 테스트는 역할별 compose 선택, fail-closed preflight와 doctor의
   무변경 계약을 검증한다.
6. ROS launch 계약 테스트는 host network, namespace와 canonical `DEVICE_ID`의 분리를
   검증한다.
7. MediaMTX 계약 테스트는 camera registry의 여섯 경로, publish IP와 viewer read
   권한을 검증한다.
8. 실제 호스트 검증은 정적·시뮬레이션 테스트와 구분해 기록한다. 하드웨어 준비 완료는
   각 PC에서 doctor와 bounded RTSP decode, ROS topic/action 실측이 통과한 뒤에만
   선언한다.

## 배포 순서

1. 공유기에서 여섯 호스트와 두 Pinky의 IP를 DHCP 예약하고 AP isolation을 끈다.
2. 4060에서 `bootstrap`, 비밀값·경로 설정, `up`, `doctor`를 수행한다.
3. 5080에서 NVIDIA 검증 후 `bootstrap`, `up`, `doctor`를 수행한다.
4. OMX PC 두 대에서 장치 경로와 E-stop을 확인한 뒤 각각 기동한다.
5. Pinky Pi 두 대에서 장치 경로와 safety publisher를 확인한 뒤 각각 기동한다.
6. 모든 호스트에서 `ROS_DOMAIN_ID=12`와 canonical ID 상태를 확인한다.
7. 영상 경로를 bounded decode한 뒤에만 주문 없는 상태의 ROS readiness를 검사한다.
8. E-stop 담당자와 빈 경로를 확보한 별도 절차에서 최초 물리 이동 시험을 수행한다.

## 완료 기준

- DB의 네 장비에서 `name=device_id`이며 다른 값은 DB와 API 모두 거절한다.
- 명령·상태·결과 payload가 canonical `device_id`만 사용한다.
- 각 호스트는 자기 `.env`와 한 번의 `control_stack up`으로 필요한 서비스를 띄운다.
- simulation과 hardware 모두 역할별 `doctor`가 지원된다.
- 실제 모든 ROS 2 컨테이너가 domain 12와 host networking을 사용한다.
- 여섯 카메라가 4060에 한 번 publish되고 5080은 read-only로 구독한다.
- doctor는 어떤 환경에서도 상태를 변경하지 않는다.
