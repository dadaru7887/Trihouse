# 3온도 물류센터 — 주행 로봇 구현 체크리스트 (SR 기준)

> 작성일: 2026-08-05 (2026-08-06 개정: 좌표 저장 방식 DB로 변경, 담당 로봇 구분 추가, 캘리브레이션 절차 추가, 포장대 작업자 배치 흐름 추가)
>
> 범위: **주행 로봇(Pinky-Pro) 관점**. 로봇팔·중앙관제·DB·관제 UI는 다른 트랙 담당이지만, 주행 로봇과 맞물리는 항목은 담당을 표기해 함께 적었다.
>
> 근거 문서
> - 시나리오: [입고_workflow.pdf](./입고_workflow.pdf), [출고_workflow.pdf](./출고_workflow.pdf), [비상상황_workflow.pdf](./비상상황_workflow.pdf)
> - 요구사항: System Requirements (SR_01 ~ SR_51), Sprint2 구현 범위
> - 아키텍처: [영상 전송·추론·로봇 제어 아키텍처](../setup/system_environment/2026-08-05-vision-streaming-architecture-draft.md), [로봇팔 모방학습·안전 작업 수행 설계](../setup/system_environment/2026-08-05-robot-arm-imitation-safe-operation-draft.md)
> - 기존 코드: [pinky_pro/](../../pinky_pro/)

## 범례

| 표기 | 의미 |
|---|---|
| `[x]` | pinky_pro에 이미 구현되어 있음 (그대로 또는 소폭 수정으로 사용 가능) |
| `[ ]` | 신규 구현 필요 |
| 🔥 | **Sprint2 이번 주 필수** — Sprint2 구현 범위에 직접 명시된 항목 |
| 🔸 | Sprint2 필수 항목의 **전제조건** — 이게 없으면 🔥 항목이 동작하지 않음 |

### 담당 표기

각 항목 앞에 실제로 그 기능을 **구현·소유하는 주체**를 적었다. 여러 주체가 걸리면 모두 적고 역할을 구분한다.

| 표기 | 의미 |
|---|---|
| `[주행로봇]` | Pinky-Pro 온보드에서 구현 |
| `[로봇팔]` | OMX-AI 또는 그 호스트 PC에서 구현 |
| `[주행로봇+로봇팔]` | 양쪽에 같은 기능을 각각 구현해야 함 |
| `[관제]` | 중앙관제 시스템(RTX 4060)에서 구현 |
| `[관제 → 주행로봇]` | 관제가 판정·결정하고 주행 로봇은 결과를 받아 수행 |
| `[서버 추론]` | RTX 5080 추론 서버에서 구현 |

## 제외 사항 (명시적으로 구현하지 않음)

- **무게 기반 판정 일체 제외.** 로드셀·무게 센서 기반 적재 완료 판정, 바구니 잔량 무게 검증(입고 30·31), 무게 기반 파지 실패 판정(출고 5), SR_41 하위의 "센서로 무게를 감지한다" 항목은 모두 범위 밖이다. 적재 완료·인수인계 완료 판정은 **카메라 확인 + 로봇팔의 완료 신호**로만 처리한다.
- 로봇 상태 DB의 `최대 적재 무게`는 센서 값이 아니라 **로봇별 정적 파라미터**로만 제공한다 (관제가 작업 분할에 사용). 로봇은 무게를 측정하지 않는다.

---

## 0. 이미 확보된 기반 자산

신규 기능을 얹을 때 재활용할 기존 코드 목록이다. 아래 항목은 1장 체크리스트에서 "재활용" 참조로 계속 인용한다. 전부 `[주행로봇]` 자산이다.

| 자산 | 위치 | 제공하는 것 |
|---|---|---|
| 베이스 구동 | [bringup.py](../../pinky_pro/pinky_bringup/pinky_bringup/bringup.py) | `cmd_vel` 구독, Dynamixel RPM 제어, MAX_RPM 100 제한, 엔코더 odometry, `odom`→`base_footprint` TF, `joint_states` |
| LiDAR | [bringup_robot.launch.xml](../../pinky_pro/pinky_bringup/launch/bringup_robot.launch.xml) | sllidar C1 `/scan` (DenseBoost) |
| IMU | [pinky_imu_bno055](../../pinky_pro/pinky_imu_bno055/src/main_node.cpp) | BNO055 자세·각속도 |
| 근접 센서 | [pinky_sensor_adc](../../pinky_pro/pinky_sensor_adc/src/main_node.cpp) | `us_sensor/range`, `ir_sensor/range`, `batt_state` |
| 배터리 | [battery_publisher.py](../../pinky_pro/pinky_bringup/pinky_bringup/battery_publisher.py) | `battery/percent`, `battery/voltage` (5초 주기) |
| LED 링 | [led_server.py](../../pinky_pro/pinky_led/pinky_led/led_server.py) | `/set_led` (fill / set_pixel / clear), `/set_brightness` |
| 램프(WS2811 8구) | [pinky_lamp_control](../../pinky_pro/pinky_lamp_control/src/main_node.cpp) | `/set_lamp` — 색 + **모드(끄기/점멸/페이드 등) + 지속시간** |
| LCD | [emotion_server.py](../../pinky_pro/pinky_emotion/pinky_emotion/emotion_server.py) | `/set_emotion` (hello/basic/angry/bored/fun/happy/interest/sad) |
| SLAM | [map_building.launch.xml](../../pinky_pro/pinky_navigation/launch/map_building.launch.xml) | slam_toolbox 매핑, `/slam_toolbox/save_map` |
| 측위 | [localization_launch.xml](../../pinky_pro/pinky_navigation/launch/localization_launch.xml) | AMCL, `map`→`odom` TF |
| 내비게이션 | [nav2_params.yaml](../../pinky_pro/pinky_navigation/params/nav2_params.yaml) | NavFn 플래너, RegulatedPurePursuit 컨트롤러, local(voxel)·global(obstacle+static+inflation) costmap, spin/backup/drive_on_heading/wait 복구 behavior, velocity_smoother |
| 액션 I/F | Nav2 표준 | `navigate_to_pose`, `navigate_through_poses`, `navigate_to_pose/_action/status`, `.../cancel_goal` |
| 웹 브리지 | [nav2_web_server.py](../../pinky_pro/pinky_navigation/scripts/nav2_web_server.py) | goal 전송([:326](../../pinky_pro/pinky_navigation/scripts/nav2_web_server.py#L326)), 전체 goal 취소([:376](../../pinky_pro/pinky_navigation/scripts/nav2_web_server.py#L376)), TF 기반 pose 추출([:218](../../pinky_pro/pinky_navigation/scripts/nav2_web_server.py#L218)), 상태 스냅샷 JSON([:240](../../pinky_pro/pinky_navigation/scripts/nav2_web_server.py#L240)), 주행 여부 판정([:180](../../pinky_pro/pinky_navigation/scripts/nav2_web_server.py#L180)) |
| 시뮬레이션 | [pinky_gz_sim](../../pinky_pro/pinky_gz_sim/) | Gazebo 모델 + 카메라 image bridge (**시뮬 전용**) |

### 신규 패키지 배치 — 주행 로봇 폴더는 `trihouse_pinky`

```
src/
├── pinky_pro/                       # 벤더 서브모듈 — 수정 금지, 참조·호출만
├── trihouse_interfaces/             # 공용 msg/srv/action (주행로봇·로봇팔·관제가 함께 씀)
├── trihouse_pinky/                  # ★ 주행 로봇 폴더
│   ├── trihouse_pinky_bringup/      #   pinky_pro launch + 자체 노드 조합 launch
│   ├── trihouse_pinky_fleet/        #   관제 연동, 작업 상태 머신, 텔레메트리, 체크포인트
│   ├── trihouse_pinky_vision/       #   카메라 → H.264 → RTSP 송신, StreamHealth 발행
│   ├── trihouse_pinky_safety/       #   안전 정지 중재, 비상 상태 유지, keep-out zone
│   └── trihouse_pinky_docking/      #   ArUco 기반 정밀 정차·인수인계 확인
└── trihouse_omx/                    # 로봇팔 폴더 (B트랙)
```

*이름을 `trihouse_pinky`로 정한 이유*
- 벤더 서브모듈 `pinky_pro` 와 짝을 이뤄 **"Pinky 위에 올린 Trihouse 레이어"** 로 즉시 읽힌다.
- 로봇팔 쪽 `trihouse_omx` 와 대칭이고, 아키텍처 문서가 이미 `Pinky-Pro` / `OMX-AI` 라는 하드웨어 이름으로 서술하고 있어 용어가 일치한다.
- `trihouse_amr` 도 검토했으나 로봇팔 쪽 `trihouse_arm` 과 **한 글자 자리바꿈 차이(amr/arm)** 라 오타·혼동을 유발한다. 배제했다.

*`trihouse_interfaces` 를 폴더 밖에 둔 이유*: `DeliveryOrder`, `TaskEvent`, `HandoverReady` 는 주행 로봇과 로봇팔이 **함께** 쓰는 계약이다. 주행 로봇 폴더 안에 두면 로봇팔이 주행 로봇 패키지에 의존하는 이상한 구조가 된다.

*패키지명에 `trihouse_pinky_` 접두사를 반복하는 이유*: `ros2 pkg list` 는 폴더 구조를 보여주지 않고 패키지 이름만 나열한다. 접두사가 없으면 `trihouse_safety` 가 주행 로봇 것인지 로봇팔 것인지 구분되지 않는다.

### 각 폴더·패키지의 역할

#### `pinky_pro/` — 벤더 서브모듈 (수정 금지)

하드웨어 드라이버, URDF, Nav2/SLAM 설정, LED·램프·LCD 서비스가 들어 있다. 0장 표의 자산이 전부 여기다.

**수정하지 않는 이유**: 업스트림이 갱신되면 병합해야 하는데, 우리가 파일을 고쳐두면 매번 충돌을 푼다. 또 "어디까지가 벤더 코드고 어디부터 우리 코드인지"가 흐려지면 문제가 났을 때 원인 범위를 좁힐 수 없다.

**바꾸고 싶을 때의 우회로**: ① 파라미터는 launch에서 덮어쓴다, ② 토픽은 remap한다, ③ URDF는 우리 xacro에서 `<xacro:include>` 후 링크를 덧붙인다(카메라 링크가 이 경우다), ④ 그래도 안 되면 upstream에 PR을 보내거나, 최후에 fork 사유를 문서에 남기고 fork한다.

#### `trihouse_interfaces/` — 트랙 간 계약 (msg / srv / action 전용)

실행 코드가 없는 순수 인터페이스 패키지다. 주행로봇·로봇팔·관제가 **모두** 여기에 의존한다.

| 종류 | 정의 |
|---|---|
| msg | `DeliveryOrder`, `RobotStatus`, `TaskEvent`, `TaskTrace`, `HandoverReady`, `HandoverGo`, `HandoverDone`, `PackingAssistanceRequest`, `PackingDirective`, `PackingStationStatus`, `PersonDetection`, `MarkerObservation`, `StreamHealth`, `KeepOutZone`, `EmergencyAlert` |
| srv | `ClearEmergency`, `GetLocation` |
| action | `ExecuteTransport`, `Dock` |

**폴더 밖에 둔 이유**: `HandoverReady` 는 주행 로봇과 로봇팔이 함께 쓴다. 주행 로봇 폴더 안에 두면 로봇팔이 주행 로봇 패키지에 의존하는 구조가 된다.

**운영 규칙**: 여기가 바뀌면 세 트랙이 전부 재빌드된다. 필드 추가는 **뒤에 붙이기만** 하고, 이름 변경·삭제는 트랙 합의 후에만 한다.

#### `trihouse_pinky_bringup/` — 실행 조합과 배포 설정

로직이 거의 없고 **launch 파일과 파라미터 YAML만** 있는 패키지다.

- `pinky_bringup/bringup_robot.launch.xml` 과 `pinky_navigation/bringup_launch.xml` 을 `<include>` 한다
- 그 위에 `trihouse_pinky_*` 노드 4종을 띄운다
- 로봇별로 달라지는 값을 여기서 주입한다 — `robot_id`, 카메라 `/dev/v4l/by-id/` 경로, RTSP URL(`pinky_1`/`pinky_2`), `map_name`·`map_revision`, 관제 API 주소, 각종 임계값

**분리한 이유**: "어떤 노드를 어떤 파라미터로 띄우는가"는 1호기·2호기·시뮬레이션마다 다르다. 이걸 로직 패키지에 섞으면 로봇을 늘릴 때마다 코드를 고치게 된다.

#### `trihouse_pinky_fleet/` — 작업 두뇌

로봇이 "지금 무슨 작업의 몇 번째 단계에 있는가"를 아는 유일한 곳이다.

- `ExecuteTransport` 액션 서버 — 작업 상태 머신 (SR_15)
- Nav2 `navigate_to_pose` 액션 **클라이언트** — 실제 주행 명령
- `trihouse_pinky_docking` 의 `Dock` 액션 클라이언트
- 관제 API 클라이언트 (gRPC/HTTP) + heartbeat, 통신 두절 판정 (2.4)
- `RobotStatus` 주기 발행 (SR_20), `TaskEvent`·`TaskTrace` 발행 (SR_44·SR_50)
- 작업 체크포인트 영속화 (SR_36)
- 상태 → 표시 매핑: `pinky_led`·`pinky_lamp_control`·`pinky_emotion` 서비스 호출 (SR_45)
- 포장대 예외 에스컬레이션 (SR_49)

**여기에 넣지 않을 것**: `cmd_vel` 직접 발행. 속도 명령은 반드시 safety를 거친다.

#### `trihouse_pinky_vision/` — 영상 송신과 카메라 기하

카메라와 관련된 모든 것을 소유한다. **영상 본체는 ROS 2로 내보내지 않는다.**

- GStreamer 파이프라인 관리 (Python 바인딩) — H.264 인코딩 → RTSP publish (2.2)
- 버스 메시지·프레임 카운터를 읽어 `StreamHealth` 발행 (2.3)
- **캘리브레이션 소유** — intrinsics/extrinsics 파일을 로드하고 `camera_optical_frame` TF를 게시
- 서버가 내려주는 `MarkerObservation`·`PersonDetection`(카메라 프레임 기준)을 **`base_link` 기준으로 변환해 재발행**

**마커 좌표 변환을 여기에 둔 이유**: extrinsics를 소유한 패키지가 변환도 해야 한다. 캘리브레이션이 바뀌었는데 변환 코드가 다른 패키지에 있으면 둘이 어긋난 채로 돌아간다. docking·safety는 이미 `base_link` 기준으로 변환된 값만 받는다.

#### `trihouse_pinky_safety/` — 속도 게이트 (모든 명령의 최종 관문)

Nav2든 docking이든, **어떤 노드도 `cmd_vel` 을 직접 쓰지 않는다.** 전부 safety를 거친다.

```
Nav2 controller ──→ /cmd_vel_nav   ┐
                                    ├─→ [safety 게이트] ─→ /cmd_vel ─→ pinky_bringup
docking 제어    ──→ /cmd_vel_dock  ┘
```

- 게이트 판정: `/scan` 최소거리 + `us_sensor/range` + `PersonDetection` → `CLEAR` / `SLOW` / `STOP` (SR_26)
- `EMERGENCY` 상태 래치와 표시 keep-alive (SR_32)
- `KeepOutZone` 구독 → costmap filter 반영 + 진입 경로면 goal 취소 (SR_32)
- caution zone에서 `nav2_msgs/SpeedLimit` 발행 (SR_29)

**별도 패키지로 분리한 이유**: 안전 정지가 fleet의 상태 머신 버그나 docking의 제어 발산에 영향받으면 안 된다. 프로세스를 분리하면 다른 노드가 죽어도 게이트는 살아 있고, 코드 리뷰 기준도 따로 둘 수 있다.

#### `trihouse_pinky_docking/` — 마지막 수 cm

Nav2가 못 하는 정밀 정차 구간만 담당한다.

- `Dock` 액션 서버 (SR_14)
- `base_link` 기준 마커 pose 구독 → P 제어로 `/cmd_vel_dock` 발행
- 재시도 최대 3회, 마커 소실 시 즉시 정지, 실패 시 `DOCK_FAILED` 반환

**분리한 이유**: 수명주기가 짧고(수 초), 입출력이 명확해서 독립 테스트가 쉽다. Nav2 goal이 살아 있는 채로 도킹 제어가 돌면 두 컨트롤러가 싸우므로, fleet이 Nav2 goal을 끝낸 뒤에만 `Dock` 을 호출하는 순서를 액션 경계로 강제한다.

#### `trihouse_omx/` — 로봇팔 (B트랙)

주행 로봇 트랙의 범위 밖이지만 인터페이스가 맞물린다: `HandoverReady`(role: ARM) 발행, `HandoverGo` 구독, 손목캠·고정캠 RTSP 송신, hand-eye 캘리브레이션 소유, 파지·적재 실행.

#### 의존 방향 (한 방향으로만 흐르게 유지)

```
trihouse_interfaces          (아무것에도 의존하지 않음)
        ↑
        ├── trihouse_pinky_vision ──→ (calibration 파일)
        ├── trihouse_pinky_safety ──→ vision(검출), pinky_pro(센서·LED)
        ├── trihouse_pinky_docking ─→ vision(마커)
        └── trihouse_pinky_fleet ───→ docking, safety, vision, Nav2, pinky_pro(서비스)
                ↑
        trihouse_pinky_bringup       (launch만, 전부 참조)
```

`fleet` 이 가장 위에 있고 아무도 `fleet` 에 의존하지 않는다. 이 방향이 뒤집히면(예: safety가 fleet 상태를 조회) 순환 의존이 생기고 안전 계층이 작업 로직에 묶인다.

기존 `pinky_*` 패키지는 벤더 서브모듈이므로 **수정하지 않고 위 패키지에서 참조·호출**한다. `trihouse_pinky_bringup` 이 `pinky_bringup/bringup_robot.launch.xml` 을 `<include>` 하고 자체 노드를 덧붙이는 형태가 기본이다.

---

## 1. SR 기준 체크리스트

### 1.1 운반 — 작업 수행의 핵심 경로

#### 🔥 SR_15 운반 기능 — 주행 로봇이 상차된 물건을 목적지까지 옮긴다

- [x] **[주행로봇] 경로계획·추종·장애물 회피 주행** — Nav2 스택이 이미 완비되어 있다. `navigate_to_pose` 액션에 목표 Pose를 넣으면 NavFn이 전역 경로를, RegulatedPurePursuit이 추종을, voxel/obstacle costmap이 LiDAR 기반 회피를 처리한다.

- [ ] 🔥 **[관제(소유) · 주행로봇/로봇팔(소비)] 위치 좌표 레지스트리 — DB 소유, YAML seed 병행**

  *구현할 기능*: 상온/냉장/냉동 창고 입출구, 하차 위치, 선반, 포장대, 대기 존, 충전소의 `map` 프레임 좌표를 미리 티칭해 저장하고, 모든 소비자가 같은 값을 보게 한다. 출고 시나리오의 "상온 좌표 (23.33, 8.32)에 도착 여부/좌표를 검증한다"가 그대로 이 기능이다.

  *저장 방식 결정 — DB를 진실 소스로 한다*: 초안에서는 로봇 로컬 YAML + ROS 파라미터를 제안했으나 **DB로 정정한다.** 근거 세 가지.
  1. 출고 4번이 "시작 신호에 해당 목적지에 맞는 좌표를 담는다"고 명시했다. 좌표를 메시지에 실어 보내는 주체가 관제이므로 1차 소비자는 로봇이 아니라 **관제**다.
  2. SR_04(구역 자동 배정)·SR_06(선반 위치 자동 배정)·SR_07(재고 반영)이 모두 "선반 위치"를 키로 다룬다. 좌표를 YAML에, 재고를 DB에 두면 조인 키가 두 곳으로 갈라진다.
  3. 포장대는 정적 좌표와 동적 상태(작업자 유무·점유)가 같은 엔티티다. 동적 상태가 DB에 있어야 하는 이상 좌표만 파일로 떼는 것은 이중 관리다.

  *역할 분담*:

  | 구분 | 저장소 | 목적 |
  |---|---|---|
  | 런타임 진실 소스 | **DB (관제)** | 관제·로봇팔·주행로봇·관제 UI 4개 소비자의 단일 출처 |
  | Teach 결과 seed / 백업 / 버전관리 | **YAML (git)** | 좌표 티칭 결과의 재현·리뷰·롤백. DB 초기 적재와 복구에 사용 |
  | 로봇 로컬 캐시 | **최소 좌표만** | 충전소·대기 존만. 통신 두절 + 배터리 위급 시 물어볼 곳이 없으므로 |

  *기존 스키마와의 매핑*: 새 테이블을 만들 필요가 없다. [trihouse_fms_schema_v3](../db_schema/trihouse_fms_schema_v3_data_dictionary.xlsx)의 `locations` 테이블이 이미 필요한 필드를 대부분 갖고 있다.

  | 체크리스트에서 필요한 것 | `locations` 컬럼 | 비고 |
  |---|---|---|
  | 위치 식별자 | `location_id` (PK), `location_code` | |
  | 온도 구역 | `temperature_zone` | CHECK로 `ambient`/`chilled`/`frozen` 강제됨 — 3온도 요구와 정확히 일치 |
  | 위치 종류 | `location_type` | CHECK에 `inbound_dock`/`outbound_dock`/`charger`/`workstation`/`waypoint`/`staging`/`slot` 등 이미 포함 |
  | 좌표 | `pose_x`, `pose_y`, `pose_yaw` | |
  | 맵 식별 | `map_name` + **`map_revision`** | **2026-08-06 신규 추가** |
  | ArUco id | `map_features.marker_code` | `map_features.location_id` 로 `locations` 를 참조. `feature_type='fiducial'` 일 때만 값이 있도록 CHECK 되어 있음 |
  | 도착 tolerance | `metadata` (JSON) | 별도 컬럼을 만들지 말고 JSON에 `{"tol_xy":0.05,"tol_yaw":0.05}` 로 넣는다 |
  | 사용 가능 여부 | `state` | `available`/`reserved`/`occupied`/`blocked`/`maintenance` |

  *`map_revision` 추가 완료 (2026-08-06)*: `locations` 테이블에 다음을 반영했다.
  - 컬럼 `map_revision VARCHAR(128) NULL` (ordinal 9, `map_name` 바로 뒤). `map_features.map_revision` 과 이름·타입을 맞췄다.
  - 인덱스 `idx_locations_map_revision (map_name, map_revision)`
  - 제약 `chk_locations_map_pose CHECK ((pose_x IS NULL AND pose_y IS NULL AND pose_yaw IS NULL) OR (map_name IS NOT NULL AND map_revision IS NOT NULL))` — **좌표가 있으면 어느 맵의 좌표인지 반드시 밝히도록 강제**한다.

  *왜 필요한가*: SLAM 맵을 다시 만들면 원점이 바뀌어 기존 좌표가 전부 무효가 된다. 이걸 추적하지 못하면 로봇이 **조용히 엉뚱한 곳으로 간다.** 로봇이 로드한 맵의 revision과 작업 메시지의 `map_revision`이 다르면 **작업을 거절**하도록 만든다. 맵 파일([my_map.yaml](../../pinky_pro/pinky_navigation/map/my_map.yaml))과 DB 레코드에 같은 revision 문자열을 박아둔다. `map_features` 는 이미 `map_revision` 을 NOT NULL로 갖고 있었으므로, 이번 추가로 **좌표를 가진 두 테이블의 맵 버전 추적이 일관**해졌다.

  *추가 검토 필요 (미반영)*: `device_states` 에도 `map_revision` 을 넣으면 "로봇이 보고한 pose가 어느 맵 기준인지"가 명시된다. 지금은 `pose_x/y/yaw` 만 있어 맵 교체 직후 보고된 pose를 해석할 수 없다. 스키마 변경 범위라 임의로 반영하지 않았다.

  *티칭 절차*: 로봇을 각 지점에 수동 주행으로 정확히 세우고 `map`→`base_link` TF를 읽어 `(x, y, yaw)`를 기록한다. 관제 웹 UI에 "현재 위치를 이 location으로 저장" 버튼을 두면 사람이 좌표를 옮겨 적는 실수가 없어진다. 티칭 결과를 YAML로 export해 git에 커밋하고, DB에는 그 YAML을 적재한다.

  *재활용*: TF에서 `(x, y, yaw)`를 뽑는 로직은 [nav2_web_server.py:218 `update_pose_from_tf`](../../pinky_pro/pinky_navigation/scripts/nav2_web_server.py#L218)에 이미 있다. 티칭 UI는 [nav2_web_server.py](../../pinky_pro/pinky_navigation/scripts/nav2_web_server.py)의 Flask 라우트에 엔드포인트 하나만 추가하면 된다. goal 전송은 [:326 `send_goal`](../../pinky_pro/pinky_navigation/scripts/nav2_web_server.py#L326)이 yaw→quaternion 변환까지 이미 해둔다.

- [ ] 🔥 **[주행로봇] 작업 단위 주행 시퀀서**

  *구현할 기능*: 한 건의 입고/출고 작업은 "저장 구역 이동 → 정밀 정차 → 로봇팔 대기 → 인수인계 → 포장대 이동 → 하차 → 대기 존 복귀"로 이어지는 다단계 시퀀스다. 단일 `navigate_to_pose` 호출로는 표현되지 않는다.

  *구현 방법*: `trihouse_interfaces`에 `ExecuteTransport.action`을 정의하고(goal: `task_id`, `map_revision`, `pickup_location_id`, `dropoff_location_id`, `packing_station_id`, `item_summary` / feedback: `stage`, `current_pose`, `eta` / result: `outcome`, `failed_stage`), `trihouse_pinky_fleet`에 액션 서버를 둔다. 내부는 명시적 상태 머신(`IDLE → ASSIGNED → NAV_TO_PICKUP → DOCKING → WAIT_HANDOVER → LOADED → NAV_TO_PACKING → AT_PACKING → UNLOADING → UNLOADED → RETURNING → IDLE`)으로 구현하고, 각 전이마다 관제에 상태를 보고한다. 상태 전이 조건과 타임아웃을 코드가 아닌 파라미터로 뺀다.

  *재활용*: 각 `NAV_*` 단계 내부에서는 기존 Nav2 `navigate_to_pose` 액션 클라이언트를 그대로 호출한다. 주행 중/완료 판정은 [nav2_web_server.py:180 `nav_status_callback`](../../pinky_pro/pinky_navigation/scripts/nav2_web_server.py#L180)의 `GoalStatusArray` 구독 방식을 재사용한다.

#### 🔸 SR_09 작업 할당 기능 — (관제 발신) 로봇 측 수신부

- [ ] 🔸 **[주행로봇+로봇팔] 작업 할당 수신 인터페이스**

  *구현할 기능*: 관제가 `DeliveryOrder` 형태(order_id / item_name / destination PoseStamped)로 보내는 작업을 받아 큐잉하고, 수락·거절을 응답해야 한다. 로봇이 이미 작업 중이거나 배터리 부족이면 거절해야 관제가 재스케줄링할 수 있다(입고 12, 출고 7). **주행 로봇과 로봇팔이 각각 같은 구조의 수신부를 가져야 한다** — 관제는 양쪽에 동시에 시작 신호를 보낸다(출고 4: 병렬 수행).

  *구현 방법*: 위 `ExecuteTransport.action`의 액션 서버가 곧 수신부다. 액션은 goal 거절(`reject`)을 프로토콜 차원에서 지원하므로 별도 수락/거절 메시지가 필요 없다. 관제가 스케줄링에 쓸 `가용 여부 + 예상 완료 시각`은 별도로 `RobotStatus.msg`에 실어 주기 발행한다(SR_20 참조). 수락 조건은 `state == IDLE && battery_percent > 임계값 && 통신 정상 && map_revision 일치`로 명시한다.

  *재활용*: 없음. goal 좌표 변환은 SR_15의 좌표 레지스트리를 공유한다.

- [ ] **[주행로봇+로봇팔] 작업 중복 방지 (SR_19 로봇 측 몫)**

  *구현할 기능*: 관제가 중복 배정하지 않는 것이 원칙이지만, 통신 재시도로 같은 `task_id`가 두 번 도착할 수 있다. 로봇은 이를 재실행하지 않아야 한다.

  *구현 방법*: `task_id`를 키로 하는 멱등 처리 — 이미 처리 중이거나 완료된 `task_id`가 다시 오면 새 goal을 만들지 않고 **현재 상태를 그대로 응답**한다. 완료된 `task_id`는 최근 N건을 링버퍼로 유지하고, 체크포인트 파일에도 함께 남긴다(SR_36).

---

### 1.2 마커 인식 · 로봇 간 인수인계

#### SR_14 마커 인식 기능 — 캠으로 마커를 인식한다

- [ ] 🔸 **[관제(디코딩) → 주행로봇+로봇팔(소비)] ArUco 마커 인식 파이프라인**

  *구현할 기능*: 하차 위치, 선반, 포장대, 바구니가 모두 ArUco id로 식별된다(출고 5·6, 로봇팔 문서의 `place_basket`). 주행 로봇은 자기 앞의 마커 id와 상대 pose를 알아야 정밀 정차와 인수인계 확인이 가능하고, 로봇팔은 파지·적재 위치 결정에 쓴다.

  *구현 방법*: **아키텍처상 마커 디코딩은 RTX 4060에서 수행한다**(영상 문서 §3.2 `MARKER` 블록: 저주기 5~10 FPS 디코딩 → `marker observation` 생성). 따라서 로봇은 카메라 프레임을 RTSP로 올리기만 하고(2.2 참조), 결과를 `MarkerObservation.msg`(`camera_id`, `marker_id`, `pose` in camera frame, `capture_stamp`, `confidence`, `calibration_id`)로 **구독**한다. 로봇은 `camera_optical_frame`→`base_link` extrinsic으로 마커의 로봇 기준 상대 위치를 계산한다.

  *전제*: 카메라 intrinsics와 extrinsics 캘리브레이션이 선행되어야 한다. **절차와 담당은 [2.1 카메라 캘리브레이션](#21-카메라-캘리브레이션)에 별도로 정리했다.**

  *재활용*: URDF 확장은 [pinky_description](../../pinky_pro/pinky_description/)에, 시뮬레이션 검증은 [pinky_gz_sim](../../pinky_pro/pinky_gz_sim/)의 카메라 브리지로 먼저 해볼 수 있다.

- [ ] 🔥 **[주행로봇] 마커 기반 정밀 정차(도킹)**

  *구현할 기능*: Nav2 도착 오차(수 cm~십 cm)로는 로봇팔이 바구니를 잡을 수 없다. 입고 24("주행 로봇 위치·자세 보정")와 출고 10_주행로봇-4("적재 위치에 올바르게 주차했는가 → 아니오면 보정 후 재판정")가 요구하는 클로즈드 루프 보정이다.

  *구현 방법*: `trihouse_pinky_docking` 노드에 `Dock.action`(goal: `target_aruco_id`, `desired_offset`)을 만든다. Nav2로 마커가 보이는 근접 지점까지 간 뒤 **Nav2 goal을 종료하고**, 도킹 노드가 마커 상대 pose 오차를 P 제어로 `/cmd_vel_dock` 에 실어 보낸다(`cmd_vel` 직접 발행 금지 — safety 게이트를 거친다). 저속(선속도 0.05 m/s, 각속도 0.3 rad/s 상한)으로 제한하고, `xy < 2 cm && yaw < 3°`가 N 연속 프레임 유지되면 성공. 실패 시 후퇴 → 재접근을 최대 3회 반복하고, 그래도 실패하면 관제에 `DOCK_FAILED`를 보고한다. 마커가 프레임에서 사라지면 즉시 정지한다.

  *정면 카메라 제약 반영*: 2.1.4에서 정리한 대로 근접 시 마커가 시야를 벗어난다. **마커가 보이는 최소 거리까지만 클로즈드 루프**로 가고, 그 뒤 잔여 구간은 오픈루프 직진 + 정지로 마무리한다. 최소 거리는 마커 크기와 카메라 수직 화각으로 계산해 파라미터로 둔다.

  *재활용*: `cmd_vel` 최종 인터페이스는 [bringup.py:104 `twist_callback`](../../pinky_pro/pinky_bringup/pinky_bringup/bringup.py#L104)이 그대로 받는다. Nav2 goal을 먼저 취소해야 컨트롤러와 도킹 제어가 충돌하지 않으므로 [nav2_web_server.py:376 `cancel_goal`](../../pinky_pro/pinky_navigation/scripts/nav2_web_server.py#L376)의 방식을 재사용한다. 마커 미검출 시 후퇴는 Nav2 `backup` behavior 재사용 가능.

#### 🔥 SR_40 로봇 간 인수인계 확인 기능 — 서로 준비됐는지 카메라로 확인하고 넘긴다

- [ ] 🔥 **[주행로봇+로봇팔, 관제가 중재] 인수인계 핸드셰이크 프로토콜**

  *구현할 기능*: 입고에서는 주행 로봇이 `하차 준비 완료`를 보내고 로봇팔이 작업 가능해야 시작된다(입고 21·22). 출고에서는 주행 로봇의 `적재 준비 완료`와 로봇팔의 `물품 적재 준비 완료`가 **모두** 수신되어야 적재가 시작된다(출고 10_주행로봇-5, 10_로봇팔-8, 11). 즉 양방향 rendezvous다.

  *구현 방법*: 관제를 중재자로 두는 2단계 배리어. ① 주행 로봇이 도킹 성공 후 `HandoverReady{task_id, role: MOBILE, location_id, dock_pose, stamp}`를 발행하고, 로봇팔도 같은 메시지를 `role: ARM`으로 발행 → ② 관제가 양쪽 ready를 모으면 `HandoverGo{task_id}`를 양쪽에 브로드캐스트 → ③ 로봇팔 동작 중 주행 로봇은 **기계적으로 정지 유지**(`cmd_vel` 0, Nav2 goal 없음, 안전 정지 래치 ON) → ④ 로봇팔 완료 신호 수신 후 관제가 `HandoverDone` 발행. 로봇 대 로봇 직접 통신은 쓰지 않는다(관제가 상태를 기록해야 재할당이 가능하므로). 타임아웃은 출고 시나리오대로 **30초** — 초과 시 주행 로봇은 대기소로 복귀한다.

  *"카메라로 확인" 부분*: 주행 로봇 카메라가 자기 적재부 마커/영역을 보고, 그 프레임을 RTSP로 올려 4060이 마커 관측을 만들고, 관제가 `적재부 비어있음/점유됨`을 판정하는 경로로 구현한다. **무게로는 판정하지 않는다.**

  *역할 구분*: 주행 로봇은 `HandoverReady` 발행 + 정지 유지 + `HandoverGo`/`HandoverDone` 수신까지. 파지·적재 동작 자체와 그 성공 판정은 전부 로봇팔 트랙이다.

  *재활용*: 정지 유지는 [nav2_web_server.py:376 `cancel_goal`](../../pinky_pro/pinky_navigation/scripts/nav2_web_server.py#L376) + `cmd_vel` 0 발행. 준비 상태 표시는 `/set_lamp`·`/set_emotion`으로 시각화(SR_45와 통합).

- [ ] **[주행로봇+로봇팔, 관제가 판정] SR_41 인수인계 후 확인 기능**

  *구현할 기능*: 인계 후 실제로 물건이 실렸는지/내려졌는지 한 번 더 확인한다.

  *구현 방법*: `HandoverDone` 수신 직후 주행 로봇이 정지 상태를 2~3초 더 유지하면서 적재부 영상을 보내고, 관제가 마커/영역 점유 판정으로 `LOAD_CONFIRMED` 또는 `LOAD_MISMATCH`를 회신한다. `LOAD_MISMATCH`면 주행을 시작하지 않고 관제 지시를 기다린다. 로봇팔 측은 그리퍼가 비었는지를 자기 손목캠으로 함께 확인한다. **무게 검증은 하지 않는다.**

---

### 1.3 포장대 처리

#### 🔥 SR_43 포장공간 이송 기능 — 물건을 포장대까지 옮긴다

> **설계 변경 (2026-08-06): 포장대는 주행 시작 전에 관제가 미리 배정한다.** 로봇이 포장대를 순회하며 찾지 않는다. 출고 시나리오 6/17의 "ArUco id 오름차순 탐색"은 **관제의 배정 규칙**으로 옮긴다 — 관제가 작업을 만들 때 그 규칙으로 포장대를 고르면 된다.
>
> 로봇은 **배정된 포장대로 직행**하고, 예외가 생겼을 때만 관제에 물어본다. 순회 탐색을 없애면 로봇 로직이 크게 단순해지고(상태 하나 제거), 두 로봇이 같은 포장대를 동시에 노리는 경합도 사라진다.

- [ ] 🔥 **[주행로봇] 배정된 포장대로 직행 + 하차**

  *구현할 기능*: 작업 메시지에 담겨 온 `packing_station_id` 로 이동해 정차하고, 작업자에게 물품을 인계한다.

  *구현 방법*: `ExecuteTransport.action` goal에 `packing_station_id` 를 추가한다(관제가 작업 생성 시 확정). 상태 머신은 `NAV_TO_PACKING → AT_PACKING → UNLOADING → UNLOADED` 로 단순 직진한다. 좌표는 SR_15 레지스트리에서 `location_id` 로 조회한다. 도착 판정은 Nav2 완료 + 작업 레벨 tolerance 확인.

  *배정 규칙은 관제에 둔다*: "ArUco id가 작은 포장대부터", "작업자가 배치된 포장대 우선", "예약이 없는 포장대" 같은 선정 로직은 전부 **[관제]** 몫이다. 관제는 전체 로봇·전체 포장대 상태를 보지만 로봇은 자기 것만 본다 — 배정 결정은 정보를 다 가진 쪽이 해야 한다.

  *재활용*: 이동은 SR_15의 시퀀서와 Nav2 그대로. 정차 후 정지 유지는 도킹/핸드셰이크와 같은 안전 정지 래치.

#### SR_47 포장대 사용 중 인식 / SR_48 포장대 작업자 부재중 인식

- [ ] **[서버 추론/관제 → 주행로봇] 작업자·포장대 점유 상태 수신**

  *구현할 기능*: 로봇이 "작업자가 있는가"를 스스로 판단해야 하는 것처럼 보이지만, 아키텍처상 사람 검출은 서버 추론(RTX 5080) 또는 고정 웹캠 경로에서 처리한다.

  *포장대 배정이 사전에 이뤄지므로 용도가 달라졌다*: 이제 이 상태는 **탐색용이 아니라 두 곳에서 쓰인다.** ① **[관제]** 가 작업을 만들 때 어느 포장대를 배정할지 고르는 입력, ② **[주행로봇]** 이 배정된 포장대에 도착했을 때 에스컬레이션할지 판단하는 입력(SR_49의 `NO_WORKER_AT_ARRIVAL`).

  *구현 방법*: 로봇은 `PackingStationStatus.msg`(`station_id`, `occupied`, `worker_present`, `worker_id`, `stamp`, `source`)를 **구독만** 한다. 판정 주체는 ① 고정 웹캠(`fixed_1`/`fixed_2`) 영상 기반 서버 추론, ② 작업자의 포장 완료 처리 입력(SR_46) 두 경로. 로봇 카메라 영상도 함께 올라가므로 보조 신호로 쓸 수 있다. 로봇 측 구현은 **자기에게 배정된 `station_id` 하나만** 보면 되고, "메시지가 `stale_timeout`(예: 5초) 이상 갱신되지 않으면 `unknown`으로 간주하고 하차하지 않는다"는 안전 기본값을 넣는다.

  *역할 구분*: 검출 모델과 판정 로직은 서버 트랙, 포장대 상태 DB 관리와 브로드캐스트는 관제 트랙, 소비와 안전 기본값은 주행 로봇 트랙.

#### 🔥 SR_49 대기/재배정 — 포장 예외 에스컬레이션 (개정)

포장대는 **미리 배정**되므로(SR_43) 정상 경로에는 탐색도 협상도 없다. 이 절은 **정상 경로가 막혔을 때만** 타는 예외 처리다.

> **전제: 작업자용 단말이 없다 (2026-08-06 확인).** 따라서 "선택된 작업자에게 시스템이 직접 지시를 보낸다"는 설계는 성립하지 않는다. 아래 흐름은 **관제 화면과 로봇 자체가 유일한 알림 통로**라는 제약을 반영한 것이다.

- [ ] 🔥 **[주행로봇] 포장 예외 에스컬레이션 — "어떻게 할까요"를 관제에 묻는다**

  *구현할 기능*: 배정된 포장대에서 진행이 막혔을 때, 로봇이 스스로 판단하지 않고 관제에 지시를 요청한다. 로봇이 하는 일은 **막혔다는 사실과 그 이유를 정확히 보고하고, 받은 지시를 수행하는 것**뿐이다.

  *에스컬레이션 트리거 — 두 지점*:

  | 시점 | 조건 | 대기 타이머 | 사유 코드 |
  |---|---|---|---|
  | 도착 직후 | 배정된 포장대에 작업자가 없다 | `T1` (기본 **120초**) | `NO_WORKER_AT_ARRIVAL` |
  | 하차 후 | 수령·포장 확인이 오지 않아 **물품이 실제로 처리되고 있는지 알 수 없다** | `T2` (기본 **300초**) | `NO_RECEIPT_CONFIRM` |
  | 도착 시 | 배정된 포장대가 다른 작업으로 점유 중 | 즉시 | `STATION_OCCUPIED` |
  | 주행 중 | 배정된 포장대에 접근 불가 (통로 폐쇄·keep-out) | 즉시 | `STATION_UNREACHABLE` |

  *전체 흐름*:
  1. **[주행로봇]** 위 조건 중 하나 발생 → `PackingAssistanceRequest{task_id, robot_id, station_id, reason, waited_sec, current_pose, stamp}` 발행. **그 자리에서 정지 유지**하고 물품을 임의로 처리하지 않는다.
  2. **[주행로봇]** **현장 알림을 로봇이 대신한다.** LCD에 사유별 메시지("N번 포장대 — 작업자 필요" / "수령 확인 필요"), 램프 노랑 점멸(`/set_lamp`). 단말이 없으므로 **로봇 자신이 현장의 호출 장치**가 된다.
  3. **[관제]** 팝업 표시 — 사유·로봇·포장대·경과 시간과 함께 처리 선택지를 띄운다. `workers` 테이블의 `active=1` 목록과 사용 가능한 포장대 목록을 함께 보여준다. 표시 시간 **300초**.
  4. **[관제]** 관리자가 선택 → `PackingDirective{task_id, action, ...}` 를 로봇에 발행하고 DB에 결정 기록을 남긴다.

     | `action` | 의미 | 로봇의 동작 |
     |---|---|---|
     | `ASSIGN_WORKER{worker_id, deadline}` | 이 작업자를 보내겠다 | 현 위치에서 계속 대기, `worker_id` 를 `RobotStatus` 에 실어 보고 |
     | `REASSIGN_STATION{new_station_id}` | 다른 포장대로 가라 | (하차 전이면) 새 포장대로 이동 후 재시도 |
     | `WAIT_MORE{extend_sec}` | 조금 더 기다려라 | 타이머 연장 후 대기 |
     | `CONFIRM_MANUAL` | 관리자가 수령을 대신 확인했다 | 정상 완료 처리, `source=manual` 로 기록 |
     | `ABORT_RETURN{payload_action}` | 작업 중단 | 지시된 물품 처리 후 대기 존 복귀 |

     **작업자에게 실제로 알리는 것은 사람이 한다** — 관리자가 육성·무전으로 전달한다. 시스템은 "누구를 언제 배정했는지"를 기록할 뿐이며, 이것이 SR_46(전달 성공 유무 기록)의 근거가 된다.
  5. **[주행로봇]** 지시대로 수행. 지시 수행 후에도 조건이 해소되지 않으면 **1번으로 돌아가 다시 에스컬레이션**한다(무한 대기 금지). 반복 횟수 상한(기본 3회)을 넘으면 `PACKING_FAILED_HOLD` 상태로 고정하고 관제 결정만 기다린다.

  *`REASSIGN_STATION` 의 제약 — 하차 여부로 갈린다*
  - **하차 전**이면 단순하다. 새 포장대로 이동해 처음부터 다시 한다.
  - **하차 후**(`NO_RECEIPT_CONFIRM`)라면 물품이 이미 포장대에 있다. 로봇은 **물품을 다시 실을 수 없다**(로봇팔이 없는 위치다). 따라서 이 경우 `REASSIGN_STATION` 은 선택지에서 제외하고, `ASSIGN_WORKER` / `WAIT_MORE` / `CONFIRM_MANUAL` / `ABORT_RETURN` 만 제시해야 한다. **관제 UI에서 하차 여부에 따라 선택지를 걸러야 한다.**

  *수령·포장 확인 — 단말이 없을 때의 3단 fallback*:

  | 순위 | 방법 | 담당 | 비고 |
  |---|---|---|---|
  | 1 | 고정 웹캠 사람 검출 → `worker_present == true` | [서버 추론] | **유일한 완전 자동 경로.** 신원은 확인 못 하고 "사람이 있다"만 판정 |
  | 2 | 작업자가 본인 **ArUco 배지**를 로봇 정면 카메라에 제시 | [주행로봇] 촬영 → [관제] 판정 | 도착 + **신원**까지 동시 확인. 마커 파이프라인(SR_14)이 이미 필요하므로 추가 비용이 거의 없다 |
  | 3 | 관제 화면에서 관리자가 수동으로 확인 (`CONFIRM_MANUAL`) | [관제] | 최후 수단. 관리자가 현장을 못 볼 때는 부정확하므로 `source=manual` 로 기록 |

  > **2순위(ArUco 배지)를 권장한다.** 단말을 새로 도입하지 않고도 "누가 왔는지"까지 확인되며, 정면 카메라·마커 디코딩이 이미 구축 대상이라 재사용만 하면 된다. 배지는 작업자 목걸이·조끼에 인쇄한 ArUco 하나면 된다. **배지를 제시하는 행위 자체가 "도착 완료 버튼"을 대신한다.**
  > **필요한 스키마 변경(미반영)**: `workers` 테이블에 `badge_marker_code INT UNSIGNED NULL` 을 추가해 `worker_id ↔ ArUco id` 를 매핑해야 한다. `map_features.marker_code` 와 같은 타입으로 맞추고, ArUco id 대역을 **설비용과 배지용으로 분리**(예: 설비 1–199, 배지 200–299)해 충돌을 막는다. 스키마 변경 범위라 임의로 반영하지 않았다.

  *타임아웃 처리*:
  - 팝업 300초 내 **관리자 선택 없음** → **[관제]** 가 `PACKING_FAILED` 로 분류. **[주행로봇]** 은 스스로 실패 처리하지 않고 `PACKING_FAILED_HOLD` 로 정지 유지한 채 지시를 기다린다.
  - 대기 중에도 `RobotStatus` 발행은 계속되어야 관제 화면에서 "왜 안 움직이는지"가 보인다.
  - **로봇이 무한 대기에 빠지지 않게** 모든 대기 상태에 상한 타이머를 둔다. 상한 도달 시 다시 에스컬레이션하거나 `PACKING_FAILED_HOLD` 로 간다.

  *역할 구분*: 팝업 UI·작업자 목록·선택지 필터링·타이머·수령 확인 확정은 전부 **[관제] D트랙**이다. 주행 로봇은 `PackingAssistanceRequest` 발행 / 현장 알림 표시 / `PackingDirective` 구독 후 수행 / 배지 촬영 / 확인 신호 구독까지만 담당한다. **로봇이 작업자를 고르거나 포장대를 재선정하거나 실패를 판정하지 않는다.**

  *재활용*: 이동·대기는 SR_15 시퀀서, 현장 알림 표시는 SR_45 매핑([led_server.py](../../pinky_pro/pinky_led/pinky_led/led_server.py) · [pinky_lamp_control:62](../../pinky_pro/pinky_lamp_control/src/main_node.cpp#L62) · [emotion_server.py](../../pinky_pro/pinky_emotion/pinky_emotion/emotion_server.py)), 배지 인식은 SR_14 마커 파이프라인, 상태 보고는 SR_20 텔레메트리를 그대로 쓴다. 신규 코드는 메시지 2종(`PackingAssistanceRequest` / `PackingDirective`)과 상태 3개(`PACKING_WAIT_WORKER`, `PACKING_WAIT_CONFIRM`, `PACKING_FAILED_HOLD`) 추가 정도다.

  *장기 검토*: 작업자용 단말(태블릿·PDA·스마트워치) 또는 **포장대 물리 확인 버튼**이 생기면 4단계의 육성 전달과 fallback이 한 번에 정리된다. 지금 구조는 그것들이 추가돼도 **메시지 계약을 바꾸지 않고 확인 소스만 늘리면 되도록** 설계했다 — 확인 소스에 `source=terminal` 또는 `source=button` 을 하나 더하면 된다.

#### 🔥 SR_44 포장 준비완료 알림 기능 — 물건이 도착하면 관제 센터에 알린다

- [ ] 🔥 **[주행로봇] 도착·하차 완료 이벤트 송신**

  *구현할 기능*: 포장대 정차 완료 시점, 하차 완료 시점을 관제에 알린다(출고 18).

  *구현 방법*: `TaskEvent.msg`(`task_id`, `robot_id`, `event_type`, `location_id`, `pose`, `stamp`, `seq`)를 정의하고 단계 전이마다 발행한다. `event_type` 열거: `DEPARTED`, `ARRIVED`, `DOCKED`, `HANDOVER_READY`, `LOAD_CONFIRMED`, `AT_PACKING`, `PACKING_ASSIST_REQUESTED`, `PACKING_DIRECTIVE_APPLIED`, `UNLOAD_DONE`, `RETURNING`, `FAILED`. **at-least-once 전달**을 가정하고 `seq` 단조 증가 + `task_id` 기준 중복 제거를 관제 측에 요구한다. ACK를 못 받으면 지수 백오프로 재전송하고, 마지막 확인된 이벤트를 로컬 체크포인트에 남긴다(SR_36).

  *재활용*: "주행 완료" 판정은 [nav2_web_server.py:180](../../pinky_pro/pinky_navigation/scripts/nav2_web_server.py#L180)의 액션 상태 구독을 재사용.

#### SR_45 포장 준비완료 상태 표시 — LCD/LED로 표시

- [x] **[주행로봇] 표시 액추에이터** — LED 링(`/set_led`), 램프(`/set_lamp`, 색+모드+시간), LCD(`/set_emotion`) 모두 사용 가능.

- [ ] **[주행로봇] 상태 → 표시 매핑 노드**

  *구현할 기능*: 로봇의 현재 상태를 작업자가 한눈에 알 수 있게 색·패턴으로 표현한다.

  *구현 방법*: `trihouse_pinky_fleet`에 상태 구독 → 표시 서비스 호출 매핑 테이블을 둔다. 예: `IDLE` 흰색 상시등 / `NAV_*` 파랑 느린 페이드 / `HANDOVER_READY` 초록 점멸 / `AT_PACKING`(포장 준비완료) 초록 상시등 + LCD `happy` / `PACKING_WAIT_WORKER` 노랑 점멸 + LCD `bored` / `EMERGENCY` 빨강 빠른 점멸(SR_32와 공유) / `LOW_BATTERY` 주황 점멸. 상태가 바뀔 때만 서비스를 호출해 호출 폭주를 막고, 우선순위(비상 > 저전력 > 작업 상태)를 두어 낮은 우선순위가 비상 표시를 덮어쓰지 못하게 한다.

  *재활용*: [led_server.py](../../pinky_pro/pinky_led/pinky_led/led_server.py), [pinky_lamp_control:62](../../pinky_pro/pinky_lamp_control/src/main_node.cpp#L62)(mode/time 인자 그대로), [emotion_server.py](../../pinky_pro/pinky_emotion/pinky_emotion/emotion_server.py).

---

### 1.4 사람 감지 · 안전 주행

#### 🔥 SR_25 사람 감지 기능(주행로봇) — 주변 사람을 실시간 감지

> 로봇팔의 사람 감지는 SR_27/SR_28로 별도 항목이며 **[로봇팔]** 트랙 담당이다. 여기서는 다루지 않는다.

- [ ] 🔥 **[서버 추론 → 주행로봇] 서버 추론 결과 기반 사람 감지 수신**

  *구현할 기능*: 로봇 전방의 사람을 실시간 감지한다. 비상 워크플로우 1번(전방 대상 감지 → 사람/비사람 분류)의 입력이다.

  *구현 방법*: **로봇에서 추론하지 않는다.** Pinky-Pro는 카메라 프레임을 RTSP로 올리고(2.2), RTX 5080이 사람 검출을 수행해 `PersonDetection.msg`(`camera_id`, `track_id`, `bbox`, `pose_class`, `distance_estimate`, `capture_stamp`, `confidence`)를 내려준다. 로봇은 이를 구독해 `capture_stamp` 기준 지연을 계산하고, 지연이 임계(예: 500ms)를 넘으면 해당 검출을 신뢰하지 않는다. 검출 결과는 `base_link` 기준 방향·거리로 변환해 정지 판단에 쓴다.

  *네트워크 지연 대비 이중화*: 무선 왕복 지연 때문에 영상 기반 검출만으로는 근거리 안전을 보장할 수 없다. **LiDAR `/scan`과 초음파 `us_sensor/range` 기반 근접 정지를 로봇 온보드에 독립적으로 둔다.** 영상 경로가 죽어도 이 경로는 살아 있어야 한다.

  *재활용*: LiDAR `/scan`은 이미 발행 중([bringup_robot.launch.xml:12](../../pinky_pro/pinky_bringup/launch/bringup_robot.launch.xml#L12)), 초음파·IR은 [pinky_sensor_adc:27](../../pinky_pro/pinky_sensor_adc/src/main_node.cpp#L27)에서 발행 중이다. Nav2 `voxel_layer`가 `/scan`을 costmap에 반영하므로 "회피"는 되지만, "사람이라서 멈춘다"는 별도 로직이다.

#### 🔥 SR_26 사람 충돌 방지 기능(주행로봇) — 근거리 감지 시 일시정지 또는 우회

- [ ] 🔥 **[주행로봇] 안전 정지 중재 노드 (`trihouse_pinky_safety`)**

  *구현할 기능*: 사람이 근거리에 감지되면 즉시 감속·정지하고(비상 1-2), 상황이 해소되면 재개한다. 정적 장애물이면 우회, 동적이면 안전거리 유지 후 재확인(비상 1-9).

  *구현 방법*: `cmd_vel` 경로에 **속도 게이트**를 넣는다. Nav2 컨트롤러 출력을 `cmd_vel_nav`로 리매핑하고, `trihouse_pinky_safety`가 이를 구독해 `cmd_vel`로 재발행하되 정지 조건에서는 0을 낸다. 정지 조건은 세 입력의 OR: ① `/scan` 최소 거리 < 정지 반경, ② 초음파 근접, ③ 서버 `PersonDetection` 근거리. 상태는 `CLEAR / SLOW(감속 계수) / STOP(0 출력 + 래치)` 3단계로 두고, 해제는 **N초 연속 조건 해소 + 이력(hysteresis)** 으로만 이루어지게 해 채터링을 막는다.

  *정적/동적 분류*: 검출 메시지의 `track_id`를 프레임 간 유지하면서 위치 변화량을 누적한다. 일정 프레임(파라미터, 예: 30프레임) 이상 이동이 없으면 정적 → Nav2에 재계획 요청 또는 costmap 갱신으로 자연 우회시킨다. 움직이면 동적 → 안전거리 유지 상태로 대기하고 사람이 경로에서 벗어날 때까지 재확인한다(비상 1-7, 1-8).

  *재활용*: 우회 자체는 Nav2가 처리한다 — costmap에 장애물이 반영되면 `NavfnPlanner`가 재계획하고, `spin`/`backup` 복구 behavior도 이미 활성화되어 있다([nav2_params.yaml:293](../../pinky_pro/pinky_navigation/params/nav2_params.yaml#L293)). 최종 속도 상한은 [bringup.py:118](../../pinky_pro/pinky_bringup/pinky_bringup/bringup.py#L118)의 MAX_RPM 100 클램프와 `velocity_smoother max_velocity`([nav2_params.yaml:330](../../pinky_pro/pinky_navigation/params/nav2_params.yaml#L330))가 이미 2중으로 걸어준다.

#### SR_29 안전 주행 기능 — 사각지대·좁은 입구에서 감속 또는 정지 후 재주행

- [ ] **[주행로봇] 구역 기반 속도 프로파일**

  *구현할 기능*: 교차로·좁은 통로·문 앞 등 특정 구역에서 미리 감속한다.

  *구현 방법*: 맵 위에 `caution zone` 폴리곤을 정의하고(좌표 레지스트리와 같은 DB에 `zones` 테이블로 두는 편이 일관적이다), 로봇 pose가 폴리곤 안에 들어오면 감속한다. 커스텀 게이트보다 Nav2 `speed_limit` 토픽(`nav2_msgs/SpeedLimit`)을 이용하는 쪽이 안정적이다 — 컨트롤러가 직접 속도를 낮춰준다. 추가로 사각지대 진입 전 1초 정지 후 전방 확인(`STOP → 관측 → 재개`)을 상태 머신에 넣는다.

  *재활용*: `velocity_smoother`와 `controller_server`가 `speed_limit`을 이미 지원하므로 신규 코드는 zone 판정 + 토픽 발행뿐이다.

#### SR_42 로봇 간 충돌 방지 기능

- [ ] **[주행로봇(준수) · 관제(조율)] 멀티로봇 구성 + 시공간 경로 예약**

  *구현할 기능*: 입고 15("다른 로봇과 동일 시간대·동일 공간에서 경로가 충돌하는가")를 만족시키려면 로봇 2대가 같은 맵 위에서 서로를 인지해야 한다. 현재 pinky_pro는 **완전한 단일 로봇 전제**다.

  *구현 방법*: 두 단계로 나눈다.
  1. **[주행로봇] 네임스페이스 분리** — 각 로봇을 `/pinky_1`, `/pinky_2` 네임스페이스로 띄우고 TF prefix(`pinky_1/base_link`)를 적용한다. `map` 프레임만 공유하고 맵 서버는 단일 인스턴스로 띄운다. DDS 트래픽은 [README 트러블슈팅](../../pinky_pro/README.md)에 언급된 대로 공유기 병목이 되기 쉬우므로 `ROS_DOMAIN_ID` 분리 + 관제 경유 통신을 기본으로 하고, 로봇 간 직접 DDS 공유는 최소화한다.
  2. **[관제] 예약 발급 · [주행로봇] 예약 준수** — 관제가 시간대별 통로 점유를 배정하면 로봇은 자기 구간 진입 허가(`CorridorGrant`)를 받을 때까지 진입 지점에서 대기한다. 로봇 측은 "허가 없으면 진입 금지"만 지키면 된다. 상대 로봇 위치는 관제가 브로드캐스트하는 `RobotStatus`로 알 수 있고, 근거리에서는 SR_26의 LiDAR 정지가 최종 안전망이다.

  *재활용*: costmap `obstacle_layer`가 상대 로봇을 LiDAR로 이미 장애물로 인식하므로 근거리 회피는 동작한다. 부족한 것은 "미리 안 마주치게 하는" 상위 조율이다.

#### SR_23 저조도 적응 인식 기능

- [ ] **[주행로봇+로봇팔, 모델은 서버 추론] 저조도 대응**

  *구현할 기능*: 어둡거나 흐린 환경(특히 냉동 구역)에서도 검출 성능을 유지한다.

  *구현 방법*: 로봇 측(주행·팔 공통)은 ① 카메라 노출·게인 파라미터를 구역별로 조정(냉동 구역 진입 시 노출 상향 프로파일 전환), ② 기존 LED 링을 조명 보조로 상시 점등(`/set_led fill` 백색), ③ 저조도 판정(프레임 평균 휘도) 시 관제에 `LOW_LIGHT` 보고. 모델 측 대응(저조도 데이터 증강, 학습)은 **[서버 추론]** 트랙 몫이다. **LiDAR는 조도의 영향을 받지 않으므로 저조도 구간에서는 LiDAR 기반 안전 정지 비중을 높인다**(SR_26 감속 계수 조정).

  *주의*: 노출을 올리면 프레임 레이트가 떨어지고 모션 블러가 늘어 마커 인식이 나빠질 수 있다. 노출 프로파일을 바꾸면 **intrinsics는 그대로지만 검출 성능은 재검증**해야 한다.

  *재활용*: [led_server.py](../../pinky_pro/pinky_led/pinky_led/led_server.py)의 `fill` + `/set_brightness`를 조명으로 전용.

#### SR_24 미끄럼 보정 기능 (Priority: Low)

- [ ] **[주행로봇] 오도메트리 슬립 보정**

  *구현할 기능*: 바닥이 미끄러워도 정확히 이동한다. 냉동 구역 결로/성에가 있으면 실제로 발생 가능하다.

  *구현 방법*: 현재 odometry는 **엔코더 단독**이라 슬립이 그대로 오차가 된다([bringup.py:127](../../pinky_pro/pinky_bringup/pinky_bringup/bringup.py#L127)). `robot_localization`의 EKF로 엔코더 odom + BNO055 IMU(yaw rate)를 융합하면 회전 슬립이 크게 줄어든다. 이미 IMU 노드가 있으므로 **패키지 추가와 파라미터 작성만으로 구현 가능**하다. 추가로 엔코더 기대 이동량과 IMU/AMCL 실제 이동량 차이가 임계 초과 시 `SLIP_DETECTED`를 보고하고 감속한다. 최종 위치는 AMCL이, 정밀 위치는 SR_14 마커 도킹이 잡아주므로 우선순위는 낮다.

  *재활용*: [pinky_imu_bno055](../../pinky_pro/pinky_imu_bno055/src/main_node.cpp) 그대로 EKF 입력으로 사용. AMCL은 이미 `map`→`odom` 보정 중이다.

---

### 1.5 비상상황

#### SR_30 비상상황 감지 기능 / SR_31 비상 알림 전송 기능 — 주행 로봇 기여분

- [ ] **[서버 추론(판정) → 주행로봇(알림·정지)] 작업자 쓰러짐 의심 판정 및 알림**

  *구현할 기능*: 비상 워크플로우 1의 4~6번 — 대상이 사람인지, 자세가 일반적인 서 있기/보행과 다른지, 일정 프레임 이상 움직임이 없는지를 판정하고 관제에 알린다.

  *구현 방법*: 판정은 **[서버 추론]** (RTX 5080 pose estimation)이 하고 `PersonDetection.pose_class`(`standing`/`walking`/`abnormal`)와 `track_id`별 정지 프레임 수를 내려준다. **[주행로봇]** 은 ① `pose_class == abnormal`이고 ② 정지 프레임 수 > 임계값이면 안전거리를 유지한 채 `EmergencyAlert.msg`(`robot_id`, `zone_id`, `camera_id`, `detected_pose`(map 좌표), `detected_stamp`, `evidence_stream_uri`)를 발행한다. 위치는 검출 시점의 로봇 pose + 상대 거리로 계산한다. 알림은 최우선 QoS·재전송으로 보내고, 관제 응답(위급상황 확정 여부)을 기다린다(비상 1-6). 응답이 `아니오`면 일반 주행 로직(비상 1-8)으로 복귀한다.

  *고정 카메라 경로*: 비상 워크플로우 2(고정 카메라 쓰러짐 감지)는 **[관제]+[서버 추론]** 담당이며 주행 로봇 구현 범위가 아니다. 다만 그 결과로 발령되는 keep-out zone은 주행 로봇이 받아야 한다(아래).

  *재활용*: 안전거리 유지는 SR_26 정지 로직 재사용, 로봇 pose는 TF lookup([nav2_web_server.py:218](../../pinky_pro/pinky_navigation/scripts/nav2_web_server.py#L218)) 재사용.

#### SR_32 비상 대응 동작 기능 — 부저나 LED로 주변 작업자에게 알림

- [x] **[주행로봇] LED·램프 액추에이터 존재** — `/set_led`, `/set_lamp`(색+모드+시간), `/set_emotion` 모두 사용 가능.

- [ ] **[주행로봇] 비상 표시 시퀀스**

  *구현할 기능*: 비상 3-1 — 감지 주행 로봇이 빨간 LED 점등 + 부저 작동 + 안전 정지 상태를 **유지**한다.

  *구현 방법*: `trihouse_pinky_safety`에 `EMERGENCY` 최상위 상태를 두고 진입 시 ① `/set_lamp`에 빨강 + 점멸 모드 + 긴 지속시간, ② `/set_led fill(255,0,0)`, ③ LCD `angry`, ④ `cmd_vel` 0 래치 + Nav2 goal 전체 취소를 동시에 실행한다. 램프의 `time` 인자는 유한하므로 **주기적으로 재호출하는 keep-alive 타이머**를 두어 관리자 해제 전까지 표시가 꺼지지 않게 한다. 해제는 관제의 명시적 해제 메시지로만 가능하며, 로봇 자체 판단으로는 절대 풀지 않는다.

  *부저 — 미확정*: **Pinky-Pro에 부저가 있는지 확인되지 않았다.** 코드에도 부저 드라이버가 없다. 하드웨어 확인 후 없으면 ① GPIO 능동 부저 추가 + 서비스 노드 작성, 또는 ② 청각 경보를 포기하고 LED/램프 점멸 + 관제 측 사이렌으로 대체할지 결정이 필요하다.

  *재활용*: [pinky_lamp_control:62 `callback_set_lamp`](../../pinky_pro/pinky_lamp_control/src/main_node.cpp#L62)의 mode/time 인자, [led_server.py](../../pinky_pro/pinky_led/pinky_led/led_server.py), [emotion_server.py](../../pinky_pro/pinky_emotion/pinky_emotion/emotion_server.py).

- [ ] **[관제(발령) → 주행로봇(준수)] 비상 대응 구역(keep-out zone) 진입 금지**

  *구현할 기능*: 비상 3-2·3-3 — 관제가 설정한 비상 구역에 다른 로봇이 진입하지 못하게 하고, 진입 예정 로봇은 경로를 우회시킨다.

  *구현 방법*: **[관제]** 가 `KeepOutZone.msg`(폴리곤 + 유효기간)를 브로드캐스트하면 **[주행로봇]** 은 두 가지를 한다. ① Nav2 costmap keepout filter(`costmap_filter_info` + keepout mask)로 해당 영역을 치명 비용으로 마킹해 플래너가 자동 우회하게 한다. ② 현재 경로가 구역을 통과하면 즉시 goal을 취소하고 안전 위치까지 후퇴 후 재계획을 요청한다. 이미 구역 안에 있으면 정지 유지한다.

  *재활용*: costmap 레이어가 이미 `["static_layer", "obstacle_layer", "inflation_layer"]`로 구성되어 있어([nav2_params.yaml:228](../../pinky_pro/pinky_navigation/params/nav2_params.yaml#L228)) keepout filter 레이어를 추가하는 형태로 확장 가능하다. goal 취소는 [nav2_web_server.py:376](../../pinky_pro/pinky_navigation/scripts/nav2_web_server.py#L376).

#### SR_33 비상 대응 종료 기능 — 관리자가 관제 센터에서 직접 정지

- [ ] **[관제(승인) → 주행로봇(해제·자가점검)] 관리자 승인 기반 해제 + 자가 점검 보고**

  *구현할 기능*: 비상 3-7~3-11 — 관리자 승인 전까지 비상 상태 유지, 승인 후 대기 존·충전소 복귀, 위치·적재·통신·센서 상태 점검 결과 보고.

  *구현 방법*: 해제는 `ClearEmergency.srv`(요청자 ID + 사유 포함)로만 이루어지게 하고 요청자 정보를 로그에 남긴다. 해제 직후 `SELF_CHECK` 상태로 들어가 ① AMCL pose 공분산이 임계 이하인지(위치 신뢰도), ② 적재부 마커 관측이 정상인지, ③ 관제 heartbeat RTT가 정상인지, ④ LiDAR·IMU·초음파 토픽이 최근 N초 내 갱신되었는지를 점검해 `SelfCheckReport`를 보낸다. 하나라도 실패하면 `MAINTENANCE_WAIT` 상태로 남아 새 작업을 수락하지 않는다(비상 3-11).

  *재활용*: 토픽 신선도 판정은 스트림 헬스 로직(2.3)과 동일 패턴. 위치 복구가 필요하면 [nav2_web_server.py:349 `set_initial_pose`](../../pinky_pro/pinky_navigation/scripts/nav2_web_server.py#L349)로 관리자가 재설정할 수 있다.

#### SR_22 관리자 개입 기능 — 관리자가 로봇을 멈추거나 작업을 다시 배정

- [x] **[주행로봇] 모든 goal 취소(정지) 경로** — [nav2_web_server.py:376 `cancel_goal`](../../pinky_pro/pinky_navigation/scripts/nav2_web_server.py#L376)이 출처 무관하게 활성 goal 전체를 취소한다. 웹 API `/api/nav/stop`도 이미 있다.

- [ ] **[주행로봇+로봇팔] 작업 레벨 중단·재배정 수용**

  *구현할 기능*: 위 취소는 "주행만" 멈춘다. 작업 상태 머신을 안전하게 중단하고 재배정을 받는 경로가 없다.

  *구현 방법*: `ExecuteTransport.action`의 표준 cancel 경로를 구현해, cancel 수신 시 ① 현재 단계를 체크포인트에 기록, ② Nav2 goal 취소, ③ `cmd_vel` 0, ④ `ABORTED` result + `failed_stage` 반환을 수행한다. 물건을 실은 상태라면 임의로 내려놓지 않고 정지 유지 상태로 관제 지시를 기다린다. 재배정은 새 `task_id`의 새 goal로 들어온다. 로봇팔도 동일하게 파지 중 중단 시 안전 자세로 물건을 내려놓고 대기하는 경로가 필요하다(입고 35).

---

### 1.6 배터리 · 작업 연속성 (전부 `[주행로봇]`)

#### SR_34 절전 모드 전환 기능 — 배터리 20% 이하 시 가장 가까운 구역 주문만 수락

- [x] **[주행로봇] 배터리 잔량 측정** — [battery_publisher.py](../../pinky_pro/pinky_bringup/pinky_bringup/battery_publisher.py)가 `battery/percent`, `battery/voltage`를 5초 주기로 발행한다. [pinky_sensor_adc](../../pinky_pro/pinky_sensor_adc/src/main_node.cpp)도 `batt_state`(`sensor_msgs/BatteryState`)를 발행한다.

- [ ] **[주행로봇(상태 발행·거절) · 관제(배정 최적화)] 잔량 기반 작업 수락 정책**

  *구현할 기능*: 20% 이하에서 가까운 구역 작업만 수락한다. 현재는 6.8V 이하 **경고 로그만** 남기고 동작 변화가 없다([bringup.py:202](../../pinky_pro/pinky_bringup/pinky_bringup/bringup.py#L202)).

  *구현 방법*: `battery/percent`를 구독해 `NORMAL(>20%) / SAVER(10~20%) / CRITICAL(<10%)` 3단계 상태를 만들고 `RobotStatus.msg`에 실어 발행한다. `SAVER`에서는 goal 수락 시 목적지까지의 경로 길이를 플래너 경로 길이로 추정해 임계 거리를 넘으면 거절한다. 실제 배정 최적화는 **[관제]** 가 `RobotStatus`를 보고 하는 것이 정석이므로, 로봇 측은 **상태 발행 + 거절 권한**까지만 구현한다. 임계값은 파라미터로 뺀다.

  *주의*: 현재 임계값이 전압(6.8V) 기준이라 퍼센트 기준과 혼재한다. `battery_percentage()`의 매핑 곡선을 확인하고 기준을 **퍼센트로 통일**할 것.

#### SR_35 자동 충전 복귀 기능 — 10% 이하 시 포장대까지 마치고 충전소 복귀

- [ ] **[주행로봇] 충전소 복귀 시퀀스**

  *구현할 기능*: 진행 중이던 작업을 포장대까지는 완료한 뒤 가장 가까운 충전소로 돌아간다.

  *구현 방법*: `CRITICAL` 진입 시 즉시 중단하지 않고 상태 머신에 `finish_current_leg` 플래그를 세워 현재 작업의 하차까지 마치게 한 뒤, 신규 goal 수락을 차단하고 **로컬 캐시된 충전소 좌표** 중 현재 pose 기준 최근접 지점으로 `navigate_to_pose`를 건다(통신이 끊겼을 수도 있으므로 충전소·대기 존 좌표는 로봇에 캐시한다 — SR_15 참조). 도착 후 충전 도킹은 SR_14 마커 도킹과 동일 메커니즘. 배터리가 하드 임계(예: 5%) 아래로 떨어지면 작업 완료를 포기하고 즉시 복귀한다.

  *미확정 사항*: **자동 충전 도킹 하드웨어(충전 컨택트/도크)가 있는지 확인되지 않았다.** 없으면 "충전소 위치까지 이동 후 정지 + 관제에 수동 충전 요청 알림"까지만 구현하고 물리 도킹은 범위에서 제외한다.

#### SR_36 작업 재할당 기능 — 중단된 시점부터 다른 로봇이 이어받는다

- [ ] 🔸 **[주행로봇+로봇팔(체크포인트) · 관제(재할당 결정)] 작업 체크포인트 로컬 영속화**

  *구현할 기능*: 입고 34·35 — 통신이 끊겨도 각 로봇이 "작업 ID와 마지막 완료 단계"를 로컬에 저장하고, 복구 후 관제와 상호 대조해 마지막 확인된 단계부터 재개한다. 다른 로봇이 이어받으려면 이 정보가 관제에 정확히 올라가 있어야 한다.

  *구현 방법*: 상태 전이가 일어날 때마다 `~/.trihouse/checkpoint.json`에 `{task_id, stage, last_acked_seq, robot_pose, payload_state, map_revision, stamp}`를 **원자적 쓰기**(임시 파일 write + fsync + rename)로 저장한다. 노드 시작 시 이 파일을 읽어 미완 작업이 있으면 `RECOVERY` 상태로 진입하고, 주행을 시작하기 전에 관제와 상태를 대조한다(입고 34: 일치하면 진행, 불일치하면 마지막 확인 단계부터 재처리). 재개 조건은 명시적이어야 한다 — 아키텍처 §8.2대로 **재연결만으로는 재개하지 않고, 새 검증과 새 authorization을 받아야 재개**한다. 로봇팔도 동일한 체크포인트를 유지해야 인계가 성립한다.

  *재활용*: 없음(신규). 관제 이벤트 `seq`(SR_44)와 체크포인트의 `last_acked_seq`를 같은 카운터로 맞춰야 대조가 단순해진다.

---

### 1.7 관제 연동 · 기록

#### SR_20 로봇 상태 공유 기능 — 로봇이 자신의 위치를 중앙 시스템에 알린다 (High)

- [x] **[주행로봇] 위치 산출** — `map`→`base_link` TF에서 `(x, y, yaw)` 추출 로직이 [nav2_web_server.py:218](../../pinky_pro/pinky_navigation/scripts/nav2_web_server.py#L218)에 이미 있다. 상태 스냅샷 JSON 구성도 [:240](../../pinky_pro/pinky_navigation/scripts/nav2_web_server.py#L240)에 있다.

- [ ] 🔸 **[주행로봇] 주기 텔레메트리 발행**

  *구현할 기능*: 출고 5 — 목적지 이동 중 **10초 주기**로 현재 위치를 발행하고, 관제가 로봇 id별로 갱신한다. 로봇 상태 DB 필드(로봇 ID, 최대 적재 무게(정적), 배터리 level, 현재 위치, 목적지)를 채운다.

  *구현 방법*: `RobotStatus.msg`(`robot_id`, `stamp`, `pose`, `map_revision`, `state`, `current_task_id`, `destination_location_id`, `assigned_worker_id`, `battery_percent`, `battery_state`, `max_payload_kg`(정적 파라미터), `nav_status`, `stream_health`, `safety_state`)를 정의하고 `trihouse_pinky_fleet`에서 발행한다. **주기는 10초를 기본으로 하되 파라미터화**한다 — 관제 화면과 충돌 회피에는 10초가 너무 느리므로 정지 시 10초 / 주행 중 1~2초처럼 상태별 가변 주기를 권장한다. 전송은 관제 API(gRPC 또는 내부 HTTP)로 보내고, ROS 2 토픽으로도 로컬 디버깅용 미러를 발행한다.

  *로봇팔도 별도 필요*: 로봇팔 상태 DB(적재위치, 물품)는 **[로봇팔]** 트랙이 같은 방식으로 발행한다.

  *재활용*: TF lookup([:218](../../pinky_pro/pinky_navigation/scripts/nav2_web_server.py#L218)), 주행 여부 판정([:180](../../pinky_pro/pinky_navigation/scripts/nav2_web_server.py#L180)), 배터리 토픽([battery_publisher.py](../../pinky_pro/pinky_bringup/pinky_bringup/battery_publisher.py))을 조합하면 된다. **가장 빠르게 만들 수 있는 항목**이므로 Sprint2 초반에 먼저 세운다.

#### 🔥 SR_50 작업 이력 기록 기능 — 이동 경로, 작업 시간, 성공/실패

- [ ] 🔥 **[주행로봇(원천 데이터) · 관제(DB 기록)] 작업 이력 데이터 제공**

  *구현할 기능*: 출고 7 — 관제가 로봇의 이동 경로, 작업 시간, 성공/실패를 기록한다. DB 기록은 **[관제] D트랙**이지만 **원천 데이터는 로봇이 만든다.**

  *구현 방법*: SR_44의 `TaskEvent` 스트림이 이력의 뼈대다(각 단계 진입/이탈 timestamp → 단계별 소요 시간 자동 산출). 이동 경로는 두 가지 중 선택: ① Nav2 `/plan`(계획 경로)을 작업 시작 시 1회 스냅샷, ② 실제 주행 궤적을 1Hz 다운샘플링해 `TaskTrace.msg` 폴리라인으로 누적 후 작업 종료 시 일괄 전송. **②가 "실제 이동 경로"라는 요구에 맞고 대역폭도 작다.** 최종 결과는 `TaskResult`(`outcome: SUCCESS|PARTIAL|FAILED`, `failed_stage`, `duration_ms`, `trace`)로 보낸다.

  *재활용*: `/plan` 구독은 [nav2_web_server.py:191 `path_callback`](../../pinky_pro/pinky_navigation/scripts/nav2_web_server.py#L191)에 이미 있고, 궤적 누적은 [:218](../../pinky_pro/pinky_navigation/scripts/nav2_web_server.py#L218)의 TF pose를 타이머로 모으면 된다.

#### SR_21 통합 관제 화면 기능 — 로봇 측 기여분

- [x] **[주행로봇] 웹 대시보드 프로토타입** — [nav2_web_server.py](../../pinky_pro/pinky_navigation/scripts/nav2_web_server.py)가 맵·경로·local/global costmap·pose·주행상태를 JSON으로 제공하고 goal 전송/정지/initialpose까지 지원한다. **[관제] D트랙이 참고할 레퍼런스로 그대로 쓸 수 있다.**

- [ ] **[관제] 다중 로봇 대응**

  *구현할 기능*: 현재 웹 서버는 로봇 1대 전제(고정 프레임 이름, 단일 액션 클라이언트)다. 관제 화면은 2대 이상을 동시에 봐야 한다.

  *구현 방법*: 관제 화면은 로봇에서 직접 긁지 말고 **관제 서버(RTX 4060)가 각 로봇의 `RobotStatus`/`TaskEvent`를 집계해 단일 API로 제공**하는 구조로 간다. 로봇 측 웹 서버는 개별 로봇 디버깅용으로만 남긴다. 이렇게 하면 로봇 코드를 다중화 대응으로 고칠 필요가 없다.

---

## 2. SR에 없지만 시나리오·아키텍처상 반드시 필요한 항목

### 2.1 카메라 캘리브레이션

모든 마커 인식·정밀 도킹·인수인계 확인의 **정확도 상한을 결정하는 단계**다. 여기가 틀리면 뒤의 모든 좌표 계산이 조용히 틀어진다.

#### 2.1.1 담당 주체

| 카메라 | intrinsics 주체 | extrinsics 주체 | extrinsics 대상 |
|---|---|---|---|
| `pinky_1` / `pinky_2` 내장캠 | **[주행로봇]** | **[주행로봇]** | `camera_optical_frame` → `base_link` |
| `wrist_1` / `wrist_2` 손목캠 | **[로봇팔]** | **[로봇팔]** | `camera_optical_frame` → 그리퍼 flange (eye-in-hand) |
| `fixed_1` / `fixed_2` 고정웹캠 | **[로봇팔]** (작업대 소유) | **[로봇팔]** | `camera_optical_frame` → 작업대 원점 (eye-to-hand) |
| RealSense | 공장 캘리브 사용, 재검증만 | **[서버 추론]** | `camera_optical_frame` → 로봇팔 base |

**결과물 관리와 서버 배포는 [관제] 담당**이다 (2.1.6 참조).

#### 2.1.2 언제 다시 해야 하는가

- 최초 1회 (필수)
- 카메라를 물리적으로 재장착하거나 부딪힌 뒤 → **extrinsics만** 재수행
- 렌즈 초점·화각을 바꾼 뒤 → **intrinsics + extrinsics 둘 다**
- 스트림 해상도·크롭·종횡비 변경 → **intrinsics 재수행** (스케일링으로 때우지 말 것)
- 로봇 섀시·마운트 교체 → **extrinsics 재수행**
- 도킹 반복 정밀도가 목표를 벗어나기 시작할 때 → 진단 겸 재수행

#### 2.1.3 intrinsics 절차 — **운영 파이프라인을 그대로 통과한 프레임으로 한다**

가장 흔한 실수는 로봇 로컬에서 raw 프레임을 뽑아 캘리브레이션하고, 실제 추론은 RTSP로 내려온 프레임에 하는 것이다. 인코더가 크롭하거나 스케일하면 그 순간 `cx, cy, fx, fy`가 전부 어긋난다. **H.264 압축은 기하를 바꾸지 않으므로**, 디코드된 스트림으로 캘리브레이션하면 이 위험이 원천적으로 사라진다.

1. **운영 해상도·프로파일을 먼저 확정한다** (1280x720, 10–15fps). 이후 바꾸면 다시 해야 한다.
2. **ChArUco 보드**를 준비한다. 일반 체커보드보다 부분 가림·경계 잘림에 강해 실패율이 낮다. A3로 인쇄해 평평한 판(아크릴/포맥스)에 기포 없이 부착하고, **인쇄 후 실제 사각 한 변 길이를 자로 재서** 그 값을 쓴다. 인쇄 배율이 100%가 아닌 경우가 흔하다.
3. **프레임 수집은 RTSP 디코드 측에서 한다.** `rtsp://192.168.0.9:8554/pinky_1`을 디코딩해 저장한다. 로봇 로컬 파일 저장은 금지되어 있으므로(아키텍처 §6.3) 이 방식이 규칙과도 맞는다.
4. **30~50장**을 모은다. 보드가 화면의 네 코너·중앙에 각각 오도록, 기울임 ±30° 내외로 다양하게, 근거리(화면 70% 차지)와 원거리(20%)를 섞는다. 한 자세에 몰리면 왜곡 계수가 발산한다.
5. `cv2.aruco.CharucoDetector` + `cv2.aruco.calibrateCameraCharuco`로 `K`(카메라 행렬)와 `dist`(왜곡 계수)를 구한다.
6. **합격 기준**: 전체 재투영 RMS < **0.5 px**, 개별 뷰 최대 오차 < **1.0 px**. 넘으면 흐릿한 프레임을 제거하고 재수집한다.
7. 산출물을 ROS `camera_info` 호환 YAML로 저장한다 — `image_width`, `image_height`, `camera_matrix`, `distortion_model`, `distortion_coefficients`, `rectification_matrix`, `projection_matrix`. 여기에 `camera_id`, `calibrated_at`, `stream_profile`, `calibration_id`(내용 해시)를 덧붙인다.

#### 2.1.4 extrinsics — Pinky 내장캠 → `base_link` **[주행로봇]**

**Pinky-Pro 카메라는 정면(수평)을 향해 고정되어 있다.** 따라서 보드를 바닥에 눕히면 카메라 시야에 들어오지 않는다. **보드를 수직으로 세워 로봇 정면에 놓고**, 로봇 쪽을 알려진 위치에 정렬하는 방식으로 진행한다.

**먼저: 순수 motion-based hand-eye(AX=XB)를 쓰면 안 된다.** 차동구동은 평면 운동만 하므로 회전축이 z 하나뿐이고, 카메라 높이(z)·roll·pitch가 **관측 불가능하게 축퇴**한다. 해가 유일하지 않아 그럴듯한 오답이 나온다.

##### 좌표계 정의 (먼저 확정)

| 프레임 | 원점 | 축 |
|---|---|---|
| `base_link` | 좌우 구동축 중점을 바닥에 투영한 점 (z=0) | x 전방, y 좌측, z 상방 (REP-103) |
| `camera_link` | 카메라 몸체 기준점 | `base_link` 와 같은 축 규약 |
| `camera_optical_frame` | 카메라 광학 중심 | z 전방(광축), x 우측, y 하방 |

`camera_link` 와 `camera_optical_frame` 을 **반드시 분리**한다. OpenCV는 optical 규약을, ROS TF는 body 규약을 쓰므로 하나로 합치면 축이 90°씩 틀어진 채 "왜 안 맞지"를 반복하게 된다.

##### 준비물

- ChArUco 보드 A3 — 예: `7x5 squares, square 40 mm, marker 30 mm, DICT_5X5_100`. 평판(포맥스/아크릴)에 기포 없이 부착
- 보드를 **수직으로 세울 스탠드** — 이젤, 카메라 삼각대 + 클램프, 또는 벽면 부착
- 줄자, 직각자, 수평계(스마트폰 앱도 가능), 마스킹 테이프
- 다림추 또는 레이저 포인터 (로봇의 `base_link` 지점을 바닥에 투영하기 위해)

##### Step 1 — intrinsics: 로봇은 세워두고 보드를 사람이 든다

정면 카메라라도 intrinsics 수집은 어렵지 않다. **로봇을 고정하고 사람이 보드를 들고 움직이면 된다.**

1. 로봇을 정지시키고 RTSP 송신을 켠다.
2. 사람이 보드를 들고 카메라 앞 **0.3 ~ 1.5 m** 범위에서 이동한다. 화면 네 모서리와 중앙에 각각 오도록, 좌우·상하로 ±30° 기울여가며.
3. 프레임은 2.1.3대로 **4060에서 RTSP를 디코딩해** 저장한다.
4. 30~50장 확보 후 `calibrateCameraCharuco`.

##### Step 2 — extrinsics: 보드를 수직으로 세우고 로봇을 정렬한다

핵심은 **`T_base_board`(로봇 기준 보드의 위치·자세)를 계산이 아니라 실측으로 확정**하는 것이다. 그래야 `T_base_cam = T_base_board · (T_cam_board)⁻¹` 가 풀린다.

1. 평평한 바닥에 마스킹 테이프로 **기준선 L**을 곧게 긋는다.
2. 보드를 기준선에 **직각으로, 지면에 수직으로** 세운다. 수평계로 보드가 기울지 않았는지 확인한다. 보드 면이 기준선을 따라 오는 로봇의 정면을 향한다.
3. 보드 원점(좌하단 코너)의 **바닥 투영점**을 바닥에 표시하고, 그 원점의 **바닥으로부터 높이 `h`** 를 잰다.
4. 로봇을 기준선 위에 정렬한다.
   - 좌우 바퀴가 기준선에서 같은 거리 → yaw 정렬
   - 다림추/레이저로 `base_link` 지점(구동축 중점)을 바닥 표시와 맞춤 → x, y 정렬
   - **팁**: 로봇 섀시에 `base_link` 위치를 표시한 스티커를 한 번 붙여두면 이후 반복이 훨씬 쉬워진다.
5. 이제 `T_base_board` 를 안다 — 보드 원점이 로봇 정면 `d` m 앞, 좌우 오프셋 0, 높이 `h`, 회전은 보드 면이 로봇을 정면으로 마주봄.
6. 카메라로 보드를 관측해 `T_cam_board` 를 얻는다 (ChArUco 코너 → `solvePnP`).
7. `T_base_cam = T_base_board · (T_cam_board)⁻¹` 를 계산한다.
8. **`d` 를 바꿔가며(0.4 / 0.7 / 1.0 m), 로봇을 좌우로 옮기거나 yaw를 ±20° 틀어가며 5~8회 반복**한다. 매번 `T_base_board` 를 다시 실측한다.
9. 결과들을 최소제곱으로 최적화(또는 평균)한다. **산포가 크면 정렬 오차가 크다는 뜻**이므로 4번부터 다시 한다.

> **여러 자세로 반복하는 이유**: 한 자세만 쓰면 그 자세의 정렬 오차가 extrinsics에 그대로 박힌다. 여러 자세의 잔차를 함께 최소화하면 개별 측정 오차가 상쇄된다.
>
> **`T_base_board` 를 AMCL pose로 얻지 말 것**: AMCL 오차가 extrinsics에 섞이면 나중에 "도킹이 왜 어긋나는지"를 캘리브레이션 탓인지 측위 탓인지 분리할 수 없다.

##### Step 2의 간이 대안 — 로봇 정렬이 어려울 때

정면 카메라는 마운트가 단순해서 **`x, y, z` 는 자로 재도 ±5 mm 수준**으로 나온다. 실제로 문제를 일으키는 건 대개 **틸트(pitch)와 롤** 이다. 정밀 정렬이 어렵다면 각도만 보드로 추정한다.

1. `x, y, z` 는 CAD 또는 직접 측정값을 그대로 쓴다.
2. 보드를 로봇 **정면에 정확히 수직·정면**으로 세운다 (수평계·직각자로 확인). 거리는 아무 값이나 좋다.
3. 관측된 `T_cam_board` 의 **회전 성분**을 읽는다. 보드가 완벽히 수직·정면이라면, 카메라가 보드를 기울어져 보는 그 각도가 곧 **카메라 자신의 기울기(부호 반대)** 다.
4. 이 각도를 URDF의 `camera_link` 조인트 rpy에 반영한다.

정확도는 Step 2 정식 절차보다 낮지만 **훨씬 빠르고, 정면 카메라에는 대개 충분**하다. Sprint2에서는 이 방식으로 시작하고, 도킹 정밀도가 목표에 못 미치면 정식 절차로 올린다.

##### 합격 기준

- 보드를 로봇 정면 1.0 m, 좌 30°, 우 30° 세 위치에 세워 관측했을 때, 계산된 보드의 `base_link` 기준 위치와 실측값의 차이 **3 cm 이내**
- 같은 도크에 10회 접근한 최종 정차 pose 산포 **±2 cm, ±3°**

##### 정면 카메라의 구조적 제약 — 설비 설계에 반영해야 한다

캘리브레이션과 별개로, 카메라가 정면 고정이라는 사실이 **마커 설치 위치를 강제**한다. 이건 소프트웨어로 못 푼다.

1. **바닥 마커를 못 본다.** 도킹·바구니·포장대 마커는 전부 **로봇 카메라 높이의 수직면**에 붙여야 한다. Pinky는 차체가 낮아 카메라 높이가 낮으므로, 선반·포장대·도크 설계 시 그 높이에 마커 부착면을 만들어야 한다.
2. **근접하면 마커가 시야를 벗어난다.** 도킹 최종 구간에서 마커를 잃는다. 대응: 마커가 보이는 **최소 거리까지만 클로즈드 루프**로 접근하고, 그 뒤는 **오픈루프 직진 + 정지**로 마무리한다. 그 최소 거리는 마커 크기와 카메라 수직 화각으로 미리 계산해 파라미터로 박아둔다.
3. **완화책 두 가지**: ① 카메라를 아래로 약간 틸트(예: 10~15°)해 근거리 시야를 확보하거나, ② 마커를 크게 만들어 원거리에서 인식되게 한다. 틸트를 주면 extrinsics를 다시 잡아야 하므로 **Sprint2 시작 전에 결정**할 것.
4. **필요한 실측 두 가지**: 카메라 **수직·수평 화각**과 **설치 높이**. 이 둘이 있어야 "마커를 몇 cm 높이에, 몇 cm 크기로 붙여야 하는지"가 계산된다. 캘리브레이션 결과의 `fx, fy` 와 해상도로 화각이 나오므로 **Step 1 직후 바로 산출**한다.

#### 2.1.5 extrinsics — 손목캠 / 고정웹캠 **[로봇팔]**

- **손목캠 (eye-in-hand)**: 전형적인 hand-eye 문제다. ChArUco 보드를 작업대에 고정하고 로봇팔을 **15~20개 자세**로 옮기며 `(flange pose from FK, board pose from camera)` 쌍을 수집한 뒤 `cv2.calibrateHandEye`로 푼다. **자세 다양성이 핵심** — 회전이 한 축에 몰리면 여기서도 축퇴한다. 인접 자세 간 회전각이 **20° 이상** 차이 나게 구성한다. Tsai / Park / Daniilidis 중 두 가지 이상으로 풀어 결과가 서로 수 mm 내로 일치하는지 교차 검증한다.
  합격 기준: 서로 다른 자세에서 계산한 보드의 로봇팔 base 프레임 위치 산포 **3 mm 이내**.
- **고정웹캠 (eye-to-hand)**: 작업대 위 알려진 위치에 ChArUco 보드를 놓고 1회 관측해 `T_world_cam`을 구한다. 보드 위치는 실측한다. 카메라가 고정이므로 반복 수집은 필요 없지만, **작업대를 옮기면 반드시 다시 해야 한다.**

#### 2.1.6 결과물 저장·배포 **[관제]**

- **영상은 ROS 2로 가지 않으므로 `camera_info` 토픽에 의존할 수 없다.** 캘리브레이션 결과는 **디코딩하는 쪽**(마커 담당 RTX 4060, ACT 담당 RTX 5080)에 파일로 있어야 한다.
- repo의 `calibration/<camera_id>/{intrinsics.yaml, extrinsics.yaml}`를 진실 소스로 두고 git으로 관리한다. 배포 스크립트로 두 서버에 동기화한다.
- 각 파일에 `stream_profile`(해상도·fps)을 함께 기록해 프로파일이 바뀌면 **즉시 불일치를 감지**하게 한다.
- `MarkerObservation.msg`에 `calibration_id`(내용 해시)를 실어, 어떤 캘리브레이션으로 계산된 관측인지 사후 추적 가능하게 한다.

#### 2.1.7 기능 레벨 검증 (숫자로 확인)

캘리브레이션 수치가 좋아도 실제로 맞는지는 별도로 확인해야 한다.

1. **마커 위치 일치성** — `map`상 측량된 위치에 마커를 두고, 로봇이 서로 다른 3개 자세에서 관측한 map 프레임 추정치가 서로 2 cm 이내인지.
2. **도킹 반복 정밀도** — 같은 도크에 10회 접근해 최종 정차 pose의 산포를 측정. 목표 **±2 cm, ±3°**.
3. **로봇팔 파지 성공률** — 도킹된 로봇의 바구니를 로봇팔이 잡는 성공률. 여기서 실패가 몰리면 원인이 주행 도킹인지 로봇팔 hand-eye인지 **양쪽 검증 수치를 대조해 판별**한다.

### 2.2 🔸 카메라 영상 송신 (RTSP)

- [ ] 🔸 **[주행로봇] 내장 카메라 → H.264 → RTSP 송신** (로봇팔 캠은 **[로봇팔]** 호스트 PC에서 동일 방식)

  *구현할 기능*: Pinky-Pro 내장 카메라 영상을 `rtsp://192.168.0.9:8554/pinky_1`(2호기는 `pinky_2`)로 MediaMTX에 publish한다. 720p, 10–15fps, 1.5–3Mbps, 키프레임 간격 1초.

  *ROS 2 경계*: 영상 본체는 ROS 2로 보내지 않는다. `sensor_msgs/Image`, JPEG/PNG 프레임, H.264 조각, base64 영상 모두 금지다.

  *제약 준수*: **로봇에 영상 파일을 저장하지 않는다.** 파이프라인에 파일 sink를 두지 않고, 네트워크가 끊겨도 로컬 녹화로 전환하지 않으며 RAM 버퍼만 제한적으로 유지한다.

#### 2.2.1 H.264 압축 — 구체적 방법

**Step 0. 하드웨어와 카메라 능력부터 확인한다** (이걸 건너뛰면 뒤가 전부 추측이 된다)

```bash
# Pinky-Pro 보드 판별 — Pi 4 인지 Pi 5 인지가 결정적이다
cat /proc/device-tree/model

# 카메라 장치와 고정 경로
v4l2-ctl --list-devices
ls -l /dev/v4l/by-id/

# 이 카메라가 어떤 포맷을 내놓는가 (H264 / MJPG / YUYV)
v4l2-ctl -d /dev/video0 --list-formats-ext

# 카메라 내장 인코더 제어 가능 여부
v4l2-ctl -d /dev/video0 --list-ctrls | grep -i -E 'bitrate|i_frame|h264'
```

> **Raspberry Pi 5 주의**: Pi 4에는 하드웨어 H.264 인코더(`v4l2h264enc`)가 있지만 **Pi 5에서는 제거되었다.** Pi 5라면 소프트웨어 `x264enc` 밖에 선택지가 없고, CPU 여유를 반드시 실측해야 한다. `cat /proc/device-tree/model` 결과가 이후 모든 결정을 가른다.

**Step 1. 인코더 선택 우선순위**

| 순위 | 조건 | 방법 | CPU 비용 |
|---|---|---|---|
| 1 | 카메라가 H.264를 직접 출력 (UVC H.264) | **재인코딩 없음** | 거의 0 |
| 2 | Pi 4 + MJPG/YUYV 출력 | `v4l2h264enc` (하드웨어) | 낮음 (jpegdec 비용만) |
| 3 | Pi 5 또는 HW 인코더 없음 | `x264enc` (소프트웨어) | **높음 — 실측 필수** |

```bash
sudo apt install -y gstreamer1.0-tools gstreamer1.0-plugins-base \
  gstreamer1.0-plugins-good gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly \
  v4l-utils
# x264enc → plugins-ugly, rtspclientsink → plugins-bad

gst-inspect-1.0 | grep -i 264      # 사용 가능한 인코더 확인
```

**Step 2-A. 카메라가 H.264 직접 출력 (최선)**

```bash
gst-launch-1.0 -v \
  v4l2src device=/dev/v4l/by-id/usb-XXXX-video-index0 \
  ! video/x-h264,width=1280,height=720,framerate=15/1 \
  ! h264parse config-interval=1 \
  ! rtspclientsink location=rtsp://192.168.0.9:8554/pinky_1 protocols=tcp
```

`config-interval=1` 이 **중요**하다. SPS/PPS 헤더를 1초마다 다시 삽입해, 나중에 접속한 수신자(4060의 마커 디코더, 5080의 ACT)가 키프레임을 기다리지 않고 바로 디코딩을 시작할 수 있다. 이게 없으면 재접속 때마다 첫 화면이 안 뜬다.

비트레이트·키프레임 간격은 카메라 내장 인코더 설정이므로 `v4l2-ctl` 로 조정한다:
```bash
v4l2-ctl -d /dev/video0 -c video_bitrate=2000000 -c h264_i_frame_period=15
```

**Step 2-B. Pi 4 하드웨어 인코딩 (MJPG 입력)**

```bash
gst-launch-1.0 -v \
  v4l2src device=/dev/v4l/by-id/usb-XXXX-video-index0 \
  ! image/jpeg,width=1280,height=720,framerate=15/1 \
  ! jpegdec ! videoconvert ! video/x-raw,format=I420 \
  ! v4l2h264enc extra-controls="controls,video_bitrate=2000000,h264_i_frame_period=15,repeat_sequence_header=1" \
  ! video/x-h264,level=(string)4 \
  ! h264parse config-interval=1 \
  ! rtspclientsink location=rtsp://192.168.0.9:8554/pinky_1 protocols=tcp
```

- `repeat_sequence_header=1` 이 위 `config-interval=1` 과 같은 역할을 인코더 단에서 해준다.
- `h264_i_frame_period=15` @15fps = **키프레임 1초 간격** (아키텍처 §6.1 요구값).
- **MJPG vs YUYV**: YUYV는 `jpegdec` 비용이 없지만 USB 대역폭을 크게 먹는다 (720p15 YUYV ≈ 27 MB/s). USB 2.0이면 MJPG가 안전하다.

**Step 2-C. 소프트웨어 인코딩 (Pi 5 / HW 인코더 없음)**

```bash
gst-launch-1.0 -v \
  v4l2src device=/dev/v4l/by-id/usb-XXXX-video-index0 \
  ! image/jpeg,width=1280,height=720,framerate=15/1 \
  ! jpegdec ! videoconvert ! video/x-raw,format=I420 \
  ! queue leaky=downstream max-size-buffers=3 \
  ! x264enc tune=zerolatency speed-preset=veryfast bitrate=2000 \
            key-int-max=15 bframes=0 \
  ! video/x-h264,profile=baseline \
  ! h264parse config-interval=1 \
  ! rtspclientsink location=rtsp://192.168.0.9:8554/pinky_1 protocols=tcp
```

각 옵션의 이유:

| 옵션 | 값 | 이유 |
|---|---|---|
| `tune` | `zerolatency` | 인코더 내부 버퍼링 제거. 지연이 곧 안전 문제다 |
| `bframes` | `0` | B프레임은 미래 프레임을 기다리므로 지연을 만든다 |
| `speed-preset` | `veryfast` | `ultrafast`는 같은 화질에 비트레이트를 더 먹고, `medium` 이상은 Pi CPU가 못 버틴다 |
| `bitrate` | `2000` (kbps) | 아키텍처 §6.1의 1.5–3 Mbps 중간값 |
| `key-int-max` | `15` | 15fps에서 **키프레임 1초 간격** |
| `profile` | `baseline` | 디코더 호환성 최대. B프레임을 안 쓰므로 손해도 없다 |
| `queue leaky=downstream` | `max-size-buffers=3` | **"오래된 프레임 폐기, 최신 프레임 우선"**(§6.1 큐 정책)을 파이프라인에서 강제 |

**Step 3. CPU를 반드시 측정한다** (특히 2-C)

```bash
pidstat -p $(pgrep -f rtspclientsink) 1 30
```

Pi급 CPU에서 720p15 `veryfast` 는 코어 하나를 상당히 쓴다. Nav2·AMCL·LiDAR 와 같은 보드에서 공존해야 하므로, 여유가 없으면 이 순서로 낮춘다: **① fps 15→10 → ② 해상도 1280x720→960x540 → ③ 그래도 안 되면 Pi 4로 교체하거나 카메라를 UVC H.264 모델로 교체.** 화질보다 **주행 제어 주기를 지키는 것이 우선**이다.

**Step 4. 수신 검증 (RTX 4060에서)**

```bash
ffprobe -rtsp_transport tcp rtsp://192.168.0.9:8554/pinky_1
ffmpeg -rtsp_transport tcp -i rtsp://192.168.0.9:8554/pinky_1 -t 60 -f null -   # 실제 fps·드롭 확인
```

합격: 720p, 10–15fps, 10분 연속 유지, 프레임 드롭 1% 이하 (아키텍처 §10).

**Step 5. 상시 구동 — systemd**

검증이 끝나면 `gst-launch-1.0` 을 systemd 서비스로 감싼다.

```ini
[Unit]
Description=Trihouse Pinky camera RTSP publisher
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/bin/trihouse_pinky_stream.sh
Restart=always
RestartSec=3        # 아키텍처 §8의 "제한된 backoff 재접속"
# 로컬 저장 금지 원칙을 OS 차원에서 강제
ProtectHome=yes
ReadOnlyPaths=/

[Install]
WantedBy=multi-user.target
```

**운영 단계에서는 `gst-launch` 대신 노드로 감싼다.** `trihouse_pinky_vision` 이 GStreamer Python 바인딩으로 파이프라인을 직접 관리해야 버스 메시지(EOS, ERROR)와 프레임 카운터를 읽어 `StreamHealth` 를 발행할 수 있다(2.3). `gst-launch` 는 초기 검증용이다.

**Step 6. 환경 설정 — 이거 빼먹으면 스트림이 주기적으로 끊긴다**

```bash
iw dev wlan0 get power_save                                        # → "Power save: off"
nmcli -g 802-11-wireless.powersave connection show trihouse        # → "disable" (2)
nmcli connection modify trihouse 802-11-wireless.powersave 2       # 끄기
```

  *재활용*: [pinky_gz_sim](../../pinky_pro/pinky_gz_sim/)의 카메라 브리지로 파이프라인 없이 인지 로직을 선검증할 수 있다(시뮬 전용).

### 2.3 🔸 스트림 헬스 판정 및 단절 대응

- [ ] 🔸 **[주행로봇+로봇팔] 스트림 상태 발행 + 단절 시 안전 정지**

  *구현할 기능*: 아키텍처 §8 — 카메라 연결 상태, FPS, 비트레이트, 마지막 프레임 시각을 ROS 2/API로 알리고 단절을 판정해 대응한다.

  *구현 방법*: `trihouse_pinky_vision`가 GStreamer 버스 메시지와 프레임 카운터를 읽어 `StreamHealth.msg`(`camera_id`, `state`, `fps`, `bitrate_kbps`, `last_frame_stamp`)를 1Hz로 발행한다. 상태 판정은 문서의 초기값을 그대로 쓴다 — `DEGRADED`(1초 이상 새 프레임 없음 또는 FPS가 목표의 50% 미만), `DISCONNECTED`(3초 이상 없음 / 게시 세션 종료 / USB 제거), `RECOVERING`(재접속 중), `HEALTHY`(5초 연속 목표 FPS 90% 이상, timestamp 단조 증가).

  *단절 시 동작*: ① 영상에 의존하는 동작(도킹, 핸드셰이크, 영상 기반 사람 감지) 즉시 중단 및 안전 정지, ② 남은 action queue와 active authorization 폐기, ③ RAM 버퍼 폐기 후 제한된 backoff로 재접속, ④ **재연결만으로는 작업을 재개하지 않고 새 마커·DB 검증과 새 authorization을 받은 뒤에만 재개**. LiDAR 기반 안전 정지는 영상 단절과 무관하게 계속 동작해야 한다.

  *주의*: 단절된 카메라의 **마지막 프레임을 반복해 모델에 넣지 않는다**. 프레임 stale 판정은 발행 측과 수신 측 양쪽에 둔다.

### 2.4 🔸 관제 통신 계층 (heartbeat · 재전송 · 복구)

- [ ] 🔸 **[주행로봇+로봇팔] gRPC/내부 API 클라이언트와 통신 상태 관리**

  *구현할 기능*: 아키텍처 §7 — 로봇 상태·authorization·Action Proposal은 영상과 분리된 gRPC 또는 내부 API로 주고받는다. 입고 33·34는 통신 두절과 복구를 명시적으로 다룬다.

  *구현 방법*: `trihouse_pinky_fleet`에 관제 API 클라이언트를 두고 ① 양방향 heartbeat(로봇→관제 1Hz, 관제→로봇 응답)로 RTT와 연결 상태를 추적, ② heartbeat 3회 연속 실패 시 `COMM_LOST` 진입 → 신규 goal 수락 중단 + 진행 중 주행을 안전 위치까지만 마치고 정지 유지 + 체크포인트 기록(SR_36), ③ 복구 시 `task_id`와 마지막 완료 단계를 관제와 대조 후 재개(입고 34). 이벤트 전송은 at-least-once + `seq` 기반 중복 제거.

  *시각 동기화*: 영상·상태·이벤트의 capture timestamp 차이가 ±50ms 이내여야 한다(아키텍처 §10). 모든 호스트에 NTP(가능하면 로컬 NTP 서버로 4060 지정)를 설정하고, 로봇 부팅 시 시각 동기 여부를 확인해 미동기 상태에서는 작업을 수락하지 않는다.

### 2.5 3온도 환경 대응

- [ ] **[주행로봇, 운용 결정 선행]** 냉장·냉동 구역 운용 제약 확인

  *구현할 기능*: 냉동 구역(-18°C 급) 진입 시 배터리 용량 급감, 렌즈·LiDAR 창 결로/성에, 바닥 결빙에 따른 슬립이 실제 문제가 된다. 아키텍처 문서에도 언급이 없다.

  *구현 방법*: 구현 이전에 **운용 결정**이 먼저다 — 실제 저온 챔버에서 시연하는지, 구역을 논리적으로만 구분하는지. 논리 구분이면 좌표 테이블의 `zone` 필드만으로 충분하고 별도 구현이 없다. 실제 저온이면 ① 냉동 구역 체류 시간 상한 파라미터, ② 저온 구간 배터리 임계값 상향, ③ 진입/이탈 시 결로 대기 시간, ④ SR_23 저조도 + SR_24 슬립 보정 우선순위 상향이 필요하다. 렌즈 결로는 **캘리브레이션과 무관하게 마커 인식을 무력화**하므로 스트림 헬스와 별개로 "마커 미검출 지속" 감시가 필요하다.

---

## 3. Sprint2(이번 주) 실행 순서

Sprint2 구현 범위 중 주행 로봇 몫은 **SR_15 / SR_40 / SR_43 / SR_44 / SR_25 / SR_26 / SR_50**이다. 이들이 동작하려면 아래 순서로 쌓아야 한다.

| 순서 | 항목 | 담당 | 이유 |
|---|---|---|---|
| 1 | 🔸 SR_20 주기 텔레메트리 (`RobotStatus`) | 주행로봇 | 기존 코드 조합만으로 가능. 나머지 전부가 이 메시지 위에 얹힌다 |
| 2 | 🔸 `trihouse_interfaces` 메시지 정의 확정 | 주행로봇+로봇팔+관제 | 트랙 간 계약. 먼저 합의하지 않으면 전부 재작업 |
| 3 | 🔸 좌표 DB 스키마 + 티칭 UI + `map_revision` | 관제(+주행로봇 티칭) | 4번의 입력. 티칭 자체에 반나절 이상 소요 |
| 4 | 🔸 **[2.1] 카메라 캘리브레이션** + [2.2] RTSP 송신 | 주행로봇 / 로봇팔 각각 | SR_14·SR_25·SR_40 전부의 전제. **리드타임이 가장 길다** |
| 5 | 🔥 SR_15 작업 시퀀서 | 주행로봇 | 운반의 본체 |
| 6 | 🔥 SR_26 안전 정지 중재 (LiDAR 우선) | 주행로봇 | 영상 없이도 먼저 동작 가능. 사람 앞에서 로봇을 돌리기 전 필수 |
| 7 | 🔥 SR_25 서버 검출 결과 연동 | 서버 추론 → 주행로봇 | 4번 이후 6번 위에 얹는다 |
| 8 | 🔥 SR_14 도킹 → SR_40 인수인계 핸드셰이크 | 주행로봇+로봇팔 | 합동 테스트 필요. 캘리브레이션 검증 수치가 여기서 드러난다 |
| 9 | 🔥 SR_43 배정 포장대 직행 + SR_49 예외 에스컬레이션 + SR_44 이벤트 | 주행로봇+관제 | 출고 경로 마무리 |
| 10 | 🔥 SR_50 작업 이력 (`TaskTrace`) | 주행로봇 | 2·5번이 서면 거의 자동으로 따라온다 |

### Sprint2 시작 전 확정 필요 사항

**확정됨 (2026-08-06)**

- ✅ **주행 로봇 폴더명** — `trihouse_pinky` (0장 참조)
- ✅ **좌표 저장 방식** — `locations` 테이블(DB)이 진실 소스, YAML은 seed·백업
- ✅ **`map_revision` 필드** — `locations` 에 컬럼·인덱스·CHECK 반영 완료
- ✅ **작업자 단말** — 없음. 관제 화면 + 로봇 자체 표시가 유일한 알림 통로 (SR_49 참조)

**아직 열려 있음**

1. **메시지 스키마 합의** — `DeliveryOrder` / `RobotStatus` / `TaskEvent` / `HandoverReady` / `PackingAssistanceRequest` / `PackingDirective` / `PersonDetection` / `MarkerObservation`의 필드와 전송 채널(ROS 2 토픽 vs gRPC)을 주행로봇·로봇팔·관제 트랙이 함께 확정.
2. **Pinky-Pro 보드가 Pi 4인가 Pi 5인가** (2.2.1) — **Pi 5면 하드웨어 H.264 인코더가 없어** 소프트웨어 인코딩 CPU 여유부터 실측해야 한다. `cat /proc/device-tree/model` 한 줄이면 확인되고, 결과가 카메라 파이프라인 설계 전체를 가른다.
3. **카메라 틸트 여부** (2.1.4) — 정면 고정 그대로 갈지, 아래로 10~15° 틸트할지. **extrinsics 캘리브레이션 전에** 정해야 두 번 안 한다.
4. **마커 설치 높이·크기** (2.1.4) — 정면 카메라가 바닥 마커를 못 보므로 도크·포장대·바구니 마커를 카메라 높이 수직면에 붙여야 한다. **설비 제작 전에** 확정.
5. **작업자 도착 확인 방식** (SR_49) — 고정 웹캠 자동 판정만 쓸지, ArUco 배지를 도입할지. 배지를 쓰면 `workers.badge_marker_code` 컬럼 추가와 ArUco id 대역 분리가 필요하다.
6. **`map_revision` 운영 정책** — 맵 재생성 시 좌표 무효화·재티칭을 누가 언제 하는지. `device_states` 에도 `map_revision` 을 넣을지.
7. **캘리브레이션 담당·일정** — 2.1.1 표대로 배분하고, 보드 인쇄와 스탠드 준비 리드타임을 먼저 확보.
8. **사람 검출 추론 위치** — RTX 5080 서버 추론으로 확정할지, 지연 때문에 로봇 온보드 경량 모델을 병행할지.
9. **부저 하드웨어 유무** (SR_32) — 없으면 LED/램프 + 관제 사이렌으로 대체할지 결정.
10. **자동 충전 도크 유무** (SR_35) — 없으면 "충전소까지 이동 후 수동 충전 요청"으로 범위 축소.
11. **냉동 구역 물리 시연 여부** (2.5) — 논리 구분이면 관련 구현이 전부 빠진다.
12. **로봇 2대 동시 운용 시점** — Sprint2에 포함되면 SR_42 네임스페이스 분리가 1번보다 먼저 와야 한다.
