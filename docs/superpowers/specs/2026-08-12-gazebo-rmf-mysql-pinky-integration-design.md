# Gazebo·Open-RMF·MySQL Pinky 통합 시뮬레이션 설계

## 1. 목적

이 문서는 `control_system`의 project1 지도·로봇 설정을 Trihouse 코드와 정합성 있게
통합하고, 한 PC에서 Gazebo·Open-RMF·Control Tower·Pinky·OMX·FMS Gateway·MySQL을
모듈별 및 수직으로 검증한 뒤 같은 경계를 실물 장비 시험에 재사용하기 위한 기준 설계다.

목표는 단순히 Gazebo에서 로봇을 이동시키거나 DB에 임의 행을 넣는 것이 아니다. 다음을
하나의 추적 가능한 실행으로 증명해야 한다.

```text
Control Tower가 전체 Pinky·OMX·RMF·배터리·Safety·Vision 상태를 통합 관제
→ 정상 상황에서는 업무와 비이동 자원을 결정
→ Open-RMF가 이동 로봇·경로·traffic을 결정
→ Fleet Adapter가 선택된 Pinky에 이동을 명령
→ Pinky가 Nav2와 로컬 Safety를 통해 이동
→ Gazebo 또는 실물이 센서·배터리·결과를 생성
→ Gateway가 상태·이벤트를 검증하고 FMS Gateway로 전송
→ FMS Gateway가 MySQL에 최신 상태와 실행 이력을 원자적으로 반영
→ Control Tower가 결과를 확인하고 다음 Pinky·OMX 단계를 진행
→ 예외 상황에서는 rule·Vision·VLM/RL 근거를 종합해 hold, cancel, replan, 재배정,
  복구 또는 운영자 승인을 조정
```

통합 성공의 기준은 다음 다섯 가지다.

1. 업무, traffic, 장비 제어, 안전, 데이터 저장의 최종 권한이 서로 중복되지 않는다.
2. 하나의 RMF task가 하나의 DB job step과 실제 Pinky 실행 attempt로 추적된다.
3. 갑작스러운 물체, 협로, 작업자 진입·낙상, 배터리 제한과 Safety stop에서도 잘못된
   완료가 발생하지 않는다.
4. `control_system_test`에서 검증한 동일 commit과 artifact만
   `control_system_root`로 승격하여 Gazebo와 실물 시험에 사용한다.
5. Control Tower가 전체 상태와 예외 workflow를 관제하되 Open-RMF의 traffic, Nav2의 경로
   계산, Pinky/OMX의 로컬 안전 권한을 중복 구현하거나 우회하지 않는다.

이 문서의 범위는 통합 구조, 인터페이스 계약, 저장 경계, launch 입력, 시험 gate와
저장소 승격 절차다. 실물 질량·footprint·도킹 허용 오차·배터리 계수의 최종 수치는
시뮬레이션 후 실물 계측으로 보정하지만, 보정값을 넣을 위치와 검증 gate는 본 설계에
포함한다.

## 2. 전체 통합 아키텍처와 고정 결정

### 2.1 최적화 원칙

전체 구조는 다음 원칙을 고정한다.

- Control Tower는 전체 시스템 상태를 통합 관제하고, 물류 업무·단계 순서·재고·비이동
  자원과 시스템 간 예외 복구 workflow를 결정하는 최상위 감독 계층이다.
- Control Tower는 정상 운행에서 Open-RMF 기본 기능을 사용하고, 예외 시 RMF·Pinky·OMX·
  Safety·Vision 상태를 종합해 hold, cancel, replan, 재배정, bounded recovery 또는 운영자
  승인을 조정한다.
- Open-RMF만 이동 로봇 선택, lane itinerary, traffic negotiation과 RMF battery-aware
  dispatch를 결정한다.
- YOLO는 상황을 관측하고 VLM/RL은 복구 후보를 제안·평가한다. 이들은 직접 RMF task,
  Nav2 goal, `/cmd_vel` 또는 OMX joint command를 발행하지 않는다.
- Fleet Adapter만 RMF의 이동 명령을 Pinky 실행 명령으로 변환한다.
- Pinky의 로컬 Safety만 최종 속도 출력 허용 여부를 결정한다.
- OMX 로컬 controller만 관절 제한, 충돌 방지와 장비 interlock을 실시간 적용한다.
- FMS Gateway만 runtime MySQL을 변경한다. ROS 노드, adapter와 RMF worker는 MySQL에
  직접 접속하지 않는다.
- Gazebo와 실물은 동일한 상위 ROS·TCP 계약을 사용하고 hardware source만 교체한다.
- authoring 원본, 통합 후보, 검증된 운영본을 분리해 시험하지 않은 생성물을 실행하지 않는다.

### 2.2 논리 계층

| 계층 | 구성요소 | 핵심 책임 | 가지면 안 되는 책임 |
| --- | --- | --- | --- |
| L6 통합 관제·업무·복구 | Control Tower, 운영 UI/API | 전체 상태 관제, job·stage, priority, 재고, 비이동 자원 예약, 시스템 간 예외 분류·복구 조정 | RMF lane 예약, 직접 `/cmd_vel`·joint command, 직접 MySQL 쓰기 |
| L5A 이동 조정 | Open-RMF core·dispatcher | fleet/robot bidding, itinerary, traffic, mutex, 충전 계획, replan | 재고·OMX 업무 완료 판정, 로봇 저수준 제어 |
| L5B 인식·의사결정 지원 | YOLO, VLM, RL·rule recovery policy | 사람·물체·상황 관측, 복구 후보 생성·평가, confidence와 모델 계보 | 검증 없는 명령 실행, 직접 RMF/Nav2/actuator 제어 |
| L4 통합 adapter | `trihouse_rmf_bridge`, Pinky Fleet Adapter, OMX Adapter | RMF↔Pinky 및 업무↔OMX 계약 변환, TaskContext 전달 | 독자적인 업무·traffic 정책, 직접 DB 쓰기 |
| L3 장비 실행 | Pinky FleetNode·Nav2·Safety, OMX controller | 명령 수행·취소, 센서 관측, 즉시 안전, 실제 결과 생성 | 전역 배차, 업무 단계 임의 완료 |
| L2 물리·시뮬레이션 | 실물 Pinky/OMX 또는 Gazebo, `ros_gz_bridge` | 센서·actuator·simulation clock과 ROS transport | 업무·DB·RMF 정책 |
| L1 데이터 경계 | Pinky/OMX Gateway, FMS Gateway | wire 검증, ACK·재전송, projection, transaction, 내부 API | 이동 로봇 선택, Safety 판단 |
| L0 저장·증거 | MySQL, rosbag·영상·JSONL artifact | 최신 상태, 업무 이력, attempt, event, 시험 증거 | 명령 생성, 실행 권한 판단 |

L1 데이터 경계는 모든 계층의 상태를 횡단하지만 제어 권한은 갖지 않는다. 이름이 비슷한
두 bridge도 분리한다. `trihouse_rmf_bridge`는 RMF task를 Pinky 실행 계약으로 변환하는
응용 adapter이고, `ros_gz_bridge`는 Gazebo와 ROS topic을 연결하는 simulation transport다.

### 2.3 구성요소별 최종 역할

#### Control Tower

- FMS Gateway의 read model과 RMF observer를 통해 Pinky·OMX·RMF·배터리·Safety·Vision의
  전체 상태를 한 관제 상태로 구성한다. 원시 센서의 단일 원본을 복제하지 않는다.
- 주문을 job과 순서 있는 Pinky·OMX stage로 만든다.
- 업무 priority, 재고, cargo 조건과 OMX·도크·작업대 예약을 관리한다.
- 이동 stage가 준비되면 특정 robot을 선지정하지 않고 fleet 수준 RMF task를 제출한다.
- RMF 배정 결과와 Pinky terminal event를 함께 확인한 뒤 다음 stage로 전이한다.
- 예외를 로컬 안전, 이동·traffic, 업무·자원, 장비 고장, 통신, 모델 불확실성으로 분류한다.
- rule을 우선 적용하고 필요한 경우 VLM/RL 제안을 받는다. allowlist, confidence, 최신 관측,
  map/assignment revision과 Safety 조건을 통과한 bounded recovery만 승인한다.
- 승인 결과를 직접 저수준 제어로 실행하지 않고 RMF cancel/replan/reassign/decommission,
  Pinky recovery command, OMX cancel/retry/home 또는 운영자 승인 요청으로 변환한다.
- `traffic_reservation.py`는 RMF 운용 중 lane이나 mobile robot 시간 슬롯을 예약하지 않는다.
  비이동 업무 자원만 예약하거나 RMF 상태의 읽기 전용 projection으로 제한한다.

#### Open-RMF

- `project1_pinky` fleet에서 실제 이동할 PK_01 또는 PK_02를 선택한다.
- navigation graph, itinerary, traffic negotiation, mutex group과 charger 계획을 소유한다.
- RobotStatus의 SOC·위치·commission 상태를 사용하지만 Pinky 로컬 Safety를 우회하지 않는다.
- RMF의 navigate 완료는 물류 job 전체가 아니라 해당 이동 stage의 한 관측값이다.

#### Pinky Fleet Adapter와 `trihouse_rmf_bridge`

- `project1_pinky` fleet당 adapter process를 정확히 하나만 실행한다.
- 한 `FleetConfiguration`과 한 fleet handle 아래에서 PK_01·PK_02 child adapter를 관리한다.
- RMF booking ID를 assignment registry의 DB `job_id`·`job_step_id`·revision과 결합해
  `TaskContext`를 만든 뒤 `ExecuteTransport`를 호출한다.
- 매핑되지 않은 RMF task는 운영 모드에서 실행하지 않는다. 합성 ID는 명시적 simulation
  smoke-test 모드에서만 허용한다.
- `control_system_rmf.launch.py`, artifact preflight, runtime overlay와 CLI 경로 처리를 소유한다.

#### OMX Adapter

- OMX 명령, 상태, 완료·실패·취소와 timeout을 공용 업무 계약으로 변환한다.
- OMX는 이동 fleet이 아니며 Open-RMF robot bidding 대상이 아니다.
- 1차 통합에서는 Pinky 도착 완료 뒤 Control Tower가 OMX stage를 별도로 실행한다.
- 추후 RMF composed task의 `armLoad`를 사용할 때만 명시적인 action executor를 추가하고,
  OMX terminal 결과까지 RMF execution을 완료하지 않는다.

#### Pinky 장비 계층

- map pose, odometry, 센서 freshness, 실제 BatteryState, cargo와 navigation을 관측한다.
- Nav2 goal 수행·취소와 도착 후 pose·정지 상태를 확인한다.
- Safety Supervisor가 최종 `cmd_vel`을 독점하며 FMS·RMF·MySQL 장애 중에도 정지한다.
- 동일 evaluator에서 `telemetry_valid`, `execution_ready`, `dispatchable`을 계산해
  FleetNode 명령 수락과 RMF commission 판단에 함께 제공한다.

#### Pinky/OMX Gateway

- ROS 장비 상태와 TaskEvent를 versioned wire message로 직렬화한다.
- snapshot status는 최신 값으로 회복하고, TaskEvent는 durable outbox에 저장한 뒤 ACK까지
  같은 `event_id`로 재전송한다.
- Gateway는 업무 완료를 판단하거나 MySQL에 직접 쓰지 않는다.

#### FMS Gateway

- HTTP API와 TCP 8788 NDJSON 경계를 제공하고 runtime MySQL의 유일한 writer가 된다.
- ID·schema·session·sequence·map revision·TaskContext를 검증한다.
- device latest-state projection, event idempotency, offline watchdog와 업무 transaction을 소유한다.
- Control Tower와 RMF worker에는 DB credential 대신 내부 API를 제공한다.

#### MySQL

- 장비 마스터, 최신 상태, job·step·attempt, 업무 자원 reservation, integration message와
  operation event를 저장한다.
- RMF lane itinerary나 원시 sensor sample의 원본이 아니다.
- `control_system`의 authoring DB와 `trihouse_fms` runtime DB를 합치지 않는다.

#### Gazebo와 `ros_gz_bridge`

- Gazebo는 실물 대신 sensor, actuator, collision, simulation clock과 battery scenario를 제공한다.
- `ros_gz_bridge`는 topic transport만 수행하고 업무·traffic·DB 의미를 해석하지 않는다.
- 상위 Pinky stack, Fleet Adapter, Gateway 계약은 실물 시험에서도 그대로 유지한다.

### 2.4 예외 처리 계층

예외 처리는 위험의 시간 제약과 영향 범위에 따라 가장 가까운 계층이 먼저 처리한다.
Control Tower가 전체를 관제한다는 이유로 긴급 정지를 중앙 왕복에 의존하지 않는다.

| 예외 범위 | 최초 처리 | Control Tower의 역할 |
| --- | --- | --- |
| 충돌 위험, 사람 근접, sensor/control-link timeout | Pinky Safety 또는 OMX local interlock이 즉시 정지 | incident 관제, task hold, 안전 확인 뒤 복구 승인 |
| 일시적인 로컬 장애물·costmap 변화 | Nav2 recovery 또는 goal failure | 반복 실패·timeout을 감지해 상위 복구로 승격 |
| lane 충돌, robot 비가용, SOC 부족 | Open-RMF replan·decommission·재배정·충전 계획 | 업무 priority·비이동 자원 조건을 반영해 RMF에 요청 |
| Pinky·OMX 순서 불일치, 작업대 점유, 통신 단절 | Control Tower exception workflow | stage hold/cancel/retry, 자원 재예약, 운영자 승인 조정 |
| 사람·물체·비정형 상황 | YOLO 관측, 필요 시 VLM 해석과 RL 후보 평가 | 제안 기록·검증, 허용된 복구만 해당 실행 계층에 요청 |

예외 처리 순서는 다음으로 고정한다.

```text
예외 관측
→ 위험하면 로컬 Safety/interlock이 즉시 정지
→ Gateway가 상태·고유 event를 FMS Gateway에 전달
→ Control Tower가 전체 상태와 현재 TaskContext로 영향 범위를 분류
→ deterministic rule 우선, 필요할 때만 VLM/RL 후보 평가
→ allowlist·confidence·revision·Safety·운영자 승인 gate
→ RMF/Pinky/OMX의 공식 cancel·replan·recovery 인터페이스로 실행
→ terminal 결과 검증, DB 이력 기록, 정상 업무 복귀 또는 격리
```

VLM/RL timeout, 모델 오류, 낮은 confidence 또는 관측 stale이면 추론 결과를 실행하지 않는다.
fail-safe 기본값은 hold/stop과 rule-based recovery 또는 운영자 승인이다.

### 2.5 권한과 단일 원본

| 상태·결정 | 단일 원본 | 다른 구성요소의 사용 방식 |
| --- | --- | --- |
| 전체 관제 상태·job·stage·priority·재고 | Control Tower/FMS runtime model | RMF에는 준비된 이동 task와 제약만 제출 |
| 시스템 간 예외 분류·복구 workflow | Control Tower | 실행은 RMF·Pinky·OMX 공식 인터페이스에 위임 |
| mobile robot 배정·lane·traffic | Open-RMF | Control Tower와 DB는 결과를 projection |
| OMX·도크·작업대 점유 | Control Tower reservation | RMF traffic 예약과 분리 |
| pose·twist·battery·sensor 상태 | Pinky 실제 관측 | RMF·DB·UI가 검증된 projection 사용 |
| 즉시 정지와 최종 속도 | Pinky Safety Supervisor | 상위 계층은 상태를 관측하고 신규 배정 차단 |
| task 실행 context | FMS assignment registry + RMF booking | Adapter가 결합하고 장비가 그대로 반환 |
| runtime 영속 상태 | FMS Gateway transaction | 다른 process는 API/TCP로만 요청 |
| 지도 편집 원본 | `control_system` authoring DB의 project·Waypoint·Lane·설비 데이터 | generator/publisher가 만든 검증된 export artifact만 runtime 사용 |
| 비정형 상황 관측·복구 후보 | YOLO·VLM·RL | Control Tower가 검증하고 제안/승인/실행을 분리 |

### 2.6 전체 데이터·명령 흐름

업무 명령 흐름은 다음과 같다.

```text
Control Tower
→ FMS Gateway에 job/step 및 비이동 reservation 생성
→ RMF worker가 fleet 수준 task 제출
→ Open-RMF가 PK_01 또는 PK_02 배정·traffic 계획
→ 단일 Pinky Fleet Adapter가 assignment registry 조회
→ TaskContext가 포함된 ExecuteTransport
→ FleetNode → namespaced Nav2 → Safety Supervisor → cmd_vel
→ ros_gz_bridge → Gazebo 또는 실물 base
```

상태·결과 흐름은 다음과 같다.

```text
Gazebo/실물 sensor·BatteryState·Nav2 result
→ Pinky StatusNode/FleetNode
→ Pinky Gateway의 status snapshot 또는 durable TaskEvent outbox
→ TCP 8788
→ FMS Gateway 검증·transaction
→ MySQL projection/event/attempt
→ Control Tower observer가 다음 stage 결정
→ Open-RMF에는 fleet state와 task status를 필요한 범위로 반영
```

OMX 흐름은 `Control Tower → FMS Gateway command → OMX Adapter → OMX → TaskEvent →
FMS Gateway → Control Tower`로 분리한다. 1차 통합에서는 RMF 이동 action 안에 OMX 제어를
숨기지 않는다.

예외 상황에서는 정상 command path를 우회하지 않고 다음 supervisory loop를 추가한다.

```text
Pinky·OMX·RMF·Safety·Vision event
→ FMS Gateway projection
→ Control Tower exception coordinator
→ rule 우선 + 선택적 VLM/RL advisory
→ hold/cancel/replan/reassign/recovery/operator approval
→ RMF·Pinky·OMX 공식 adapter
→ 결과 검증과 다음 업무 상태 결정
```

### 2.7 control_system 통합·승격 모델

최종 저장소 흐름은 다음으로 고정한다.

```text
control_system
  원본/upstream, 수정 금지
        ↓ copy/clone
control_system_test
  Trihouse 통합 후보, 생성기·project1·경로 수정 및 시험
        ↓ 모든 gate 통과
control_system_root
  검증된 운영용 버전
```

- `/home/syw/Trihouse/control_system`과 `/home/syw/Trihouse/pinky_pro`는 읽기 전용 보호 대상이다.
- `control_system_test`는 단순 artifact 임시 폴더가 아니라 upstream commit을 추적하는 독립
  Git 후보본이다. `move`, 원본 삭제와 무검증 덮어쓰기를 금지한다.
- 생성 파일을 직접 수선하지 않고 `rmf_control_ui` generator를 수정한 뒤 project1을 다시
  export한다. Trihouse 전용 launch·remap·DB·제어 모드 overlay는 Trihouse 저장소가 소유한다.
- 최초 승격은 `control_system_test`의 검증된 정확한 commit을 copy/clone하여
  `control_system_root`를 만든다. 이후 `control_system_root`를 정식 release 기준으로
  유지하고 후보 branch/test clone에서 검증된 commit만 fast-forward 승격한다.
- 승격은 upstream SHA, candidate SHA, project, map revision, 필수 artifact SHA-256,
  `rmf_ws` commit과 test run ID가 든 release manifest를 남긴다.
- 통합 launch는 `control_system` 원본을 기본 실행 경로로 사용하지 않는다. 시험 중에는
  `control_system_root:=/home/syw/Trihouse/control_system_test`, 승격 후에는
  `/home/syw/Trihouse/control_system_root`를 사용한다.

새 구현은 `control_system_test`, 이후 승격된 `control_system_root`,
`trihouse_interfaces`, `trihouse_pinky`, `trihouse_rmf_bridge`, `trihouse_omx_adapter`,
`control_tower`, `fms_gateway`, `db`, 루트 Compose와 `docs` 범위에서만 수행한다.

### 2.8 장비 식별자

장비 식별자는 DB, ROS, RMF, TCP, UI read model과 측정 로그에서 동일한 값을 쓴다.

| 장비 | 통합 식별자 | 장비 유형 | RMF fleet |
| --- | --- | --- | --- |
| Pinky 1 | `PK_01` | `mobile` | `project1_pinky` |
| Pinky 2 | `PK_02` | `mobile` | `project1_pinky` |
| OMX 1 | `OMX_01` | `arm` | `NULL` |
| OMX 2 | `OMX_02` | `arm` | `NULL` |

`devices.device_id`, ROS `robot_id`·`omx_id`, RMF robot name과 모든 장비 FK에 위 값을
사용한다. `PK-01`, `PINKY-01`, `OMX-01` 같은 표기는 migration과 seed에서 한 번 변환한
뒤 runtime에서 거부한다. `fleet_name`은 실제 Open-RMF 이동 fleet에만 사용한다. OMX의
논리 그룹, station과 capability는 별도 필드에 저장하고 가상의 `omx_fleet`을 만들지 않는다.

### 2.9 control_system project1 입력 계약

후보 작성의 출발점은 `/home/syw/Trihouse/control_system/rmf_maps/project1`이고 runtime
입력은 동일 구조의 `control_system_test` 또는 `control_system_root` project1이다.

Waypoint·Lane·설비 위치의 편집 원본은 control_system UI가 사용하는 authoring MySQL의
`robosapiens.map_projects`, `map_project_waypoints`, `map_project_lanes`다. Open-RMF가 이
테이블을 runtime에 직접 조회하지 않는다. 지도 연결은 publish 경계로 고정한다.

```text
control_system_root UI
→ authoring MySQL에 프로젝트·Waypoint·Lane·설비 위치 저장
→ publish/export 검증
→ building.yaml 생성
→ nav_graphs/0.yaml과 Gazebo world/model 생성
→ Nav2 map·fleet config 결합
→ artifact SHA-256과 content-derived map revision 생성
→ Open-RMF·Gazebo가 검증된 파일을 읽어 실행
→ publish manifest의 운영 Waypoint만 FMS Gateway를 통해 trihouse_fms에 projection
```

DB는 편집 원본, YAML/nav graph/world는 RMF·Gazebo 실행 원본, release manifest는 두
표현이 같은 revision임을 증명하는 연결 고리다. authoring schema와 `trihouse_fms` runtime
schema는 같은 MySQL server를 사용해도 합치지 않고 writer와 lifecycle을 분리한다.

| 입력 | 원본으로 인정하는 필드 |
| --- | --- |
| `fleet.yaml` | robot ID, 표시 이름, kind, model, `gz_name`, zones, charger/station, spawn pose |
| `project1_pinky_config.yaml` | RMF fleet 이름, 이동 한계, footprint/vicinity, battery·mechanical 계수, charger 매핑 |
| authoring DB project | level, waypoint·lane·설비 위치와 도면의 편집 원본 |
| `project1.building.yaml` | authoring DB에서 publish한 Open-RMF building artifact |
| `nav_graphs/0.yaml` | RMF가 실제 실행할 waypoint·lane·charger graph |
| `nav2_map/project1.yaml` | Nav2 occupancy map과 원점·해상도 |
| `project1.world` | Gazebo world 입력 |
| `project1_gz_bridge.yaml` | Gazebo↔ROS topic 연결 |
| `robots/<ID>/*` | 개별 robot spawn, Nav2, URDF와 namespace 설정 |

preflight는 ID, charger, namespace, waypoint, footprint, reverse-driving, 지원 action과 필수
artifact를 교차 검증한다. `fleet.yaml`에 없는 RMF fleet 이름을 추측하지 않고
`project1_pinky_config.yaml`에서 읽는다. 생성기 변경과 export 결과가 일치하는지는 golden
manifest test로 검증한다.

현재 확인한 project1 장비 기준은 다음과 같다.

| device_id | kind | model | gz_name | home/station | zones |
| --- | --- | --- | --- | --- | --- |
| `PK_01` | `mobile` | `PINKY-GZ` | `pinky_01` | `충전1` | ambient, chilled, frozen |
| `PK_02` | `mobile` | `PINKY-GZ` | `pinky_02` | `충전2` | ambient, chilled, frozen |
| `OMX_01` | `workcell` | `open_manipulator_x` | `omx_01` | `설비1` | 없음 |
| `OMX_02` | `workcell` | `open_manipulator_x` | `omx_02` | `설비2` | 없음 |

DB 경계에서만 `kind=workcell → device_type=arm`으로 변환한다. ID, 이름, model과 namespace는
변환하지 않는다. 현재 RMF config의 `teleop`, `armLoad`는 Pinky Adapter가 지원하지 않으므로
1차 runtime overlay에서는 `actions: []`로 비활성화한다. action executor의 완료·실패·취소
계약이 통합 시험을 통과한 뒤에만 다시 활성화한다.

control_system UI는 지도 생성·편집·저장·publish 시에만 필수다. 검증된 배포본으로
시뮬레이션을 실행할 때는 UI에서 YAML과 map을 다시 수동 업로드하지 않는다. launch가
`control_system_root`, `project_name`과 release manifest를 받아 배포 artifact를 직접 읽는다.
UI를 모니터링 용도로 열 수는 있지만 실행 중 publish로 Building Map Server와 Fleet
Adapter를 교체하는 것은 금지한다.

### 2.10 지도 revision과 시간

- `map_revision`은 고정 `"1"`을 쓰지 않는다.
- exporter가 building YAML, nav graph, Nav2 yaml·image, fleet config와 world manifest의
  canonical SHA-256을 계산해 `project1:<12자리 해시>` 형식으로 생성한다.
- release manifest, launch, TaskContext, RobotStatus, DB `map_features`와 recovery 데이터가
  같은 revision을 사용한다. preflight는 실행 시 다시 계산해 불일치하면 시작을 거부한다.
- 운영 시각은 `Asia/Seoul`, UTC+9로 통일하고 모든 컨테이너에 `TZ=Asia/Seoul`을 설정한다.
- Gateway는 MySQL connection을 얻을 때마다 `SET time_zone = '+09:00'`을 실행한다.
- API의 외부 시각은 `+09:00` 오프셋을 포함한다.

Gazebo의 ROS simulation clock은 운영 시각이 아니다. `device_states.observed_at`에는 FMS
Gateway가 메시지를 받은 실제 KST 시각을 넣고 ROS simulation stamp는
`device_states.details.source_stamp`에 보존한다. simulation battery와 duration은 ROS clock
delta를 사용해 Gazebo pause와 simulation speed를 따른다. 실물 duration은 monotonic clock을
사용하고 `job_step_attempts.metrics.clock_source`로 구분한다.

## 3. 선택한 통합 방식

### 3.1 통신 경계

| 방식 | 판단 |
| --- | --- |
| 루프백 TCP로 실제 경계 유지 | 선택. 실물과 동일한 schema·ACK·재접속·중복 처리를 검증한다. |
| ROS 노드가 MySQL에 직접 저장 | 사용하지 않음. DB writer와 상태 원본이 늘어난다. |
| ROS 저장과 TCP 저장을 동시에 제공 | 사용하지 않음. 동일 이벤트의 이중 반영 위험이 있다. |

한 PC 시험에서는 Pinky/OMX Gateway가 `127.0.0.1:8788`로 FMS Gateway에 연결한다. ROS
노드, adapter, Control Tower RMF worker는 MySQL에 직접 연결하지 않는다.

### 3.2 runtime 배치

```text
Control Tower ──업무/비이동 자원──▶ FMS Gateway ──transaction──▶ MySQL
      │                                      ▲
      └──fleet 수준 task──▶ RMF worker ──▶ Open-RMF
                                             │ robot/traffic 결정
                                             ▼
                                  단일 project1_pinky Fleet Adapter
                                      ├─ PK_01 child adapter
                                      └─ PK_02 child adapter
                                             │ ExecuteTransport + TaskContext
                                             ▼
                                  Pinky FleetNode/Nav2/Safety
                                             │
                              ros_gz_bridge ─┴─ Gazebo 또는 실물
                                             │ status / unique TaskEvent
                                             ▼
                                  Pinky Gateway durable outbox
                                             └──TCP 8788──▶ FMS Gateway

Control Tower ──OMX stage──▶ FMS Gateway ──▶ OMX Adapter ──▶ OMX
                                                        └──event──▶ FMS Gateway
```

### 3.3 command authority

Pinky 명령 모드는 `RMF_MANAGED`, `MANUAL`, `RECOVERY`, `MAINTENANCE`로 구분한다. 정상
업무에서는 `RMF_MANAGED`만 허용하고 Adapter가 유일한 `ExecuteTransport` 생산자다. TCP
직접 이동 명령은 MANUAL 또는 RECOVERY에서만 허용하며, 먼저 활성 RMF task 취소,
decommission과 assignment revision 증가를 완료해야 한다. FleetNode는 현재 mode,
`command_id`, `assignment_revision`, `map_revision`이 모두 맞지 않으면 명령을 거부한다.

통합 launch 파일명은 프로젝트 이름을 포함하지 않는
`trihouse_rmf_bridge/launch/control_system_rmf.launch.py`로 고정한다. 동일 launch는
`control_system_root`, `project_name`과 artifact 경로를 CLI argument로 받아 후보본과
운영본에 동일하게 적용한다.

## 4. 상세 책임 경계

### 4.1 Control Tower

Control Tower는 전체 상태를 통합 관제하는 최상위 감독 계층이자 업무 규칙, 단계 진행과
시스템 간 예외 복구 workflow의 원본이다. FMS Gateway read model과 RMF observer를 통해
Pinky·OMX·RMF·배터리·Safety·Vision 상태를 결합하되 각 장비의 원시 관측 원본은 소유하지
않는다.

정상 상황에서는 주문·재고·priority·cargo gate와 Pinky/OMX stage 순서를 결정하고 RMF
운행에서 특정 Pinky를 먼저 고르지 않는다. 이동 stage의 요청 조건과 fleet capability를
전달하고 실제 robot 선택은 RMF 결과를 받아 projection한다. RMF completed와 Pinky
terminal 결과가 일치해야 이동 stage를 성공시키며 OMX·검수·인계가 남아 있으면 전체
job을 완료하지 않는다.

예외 상황에서는 현재 TaskContext, map/assignment revision과 모든 관련 상태를 기준으로
hold, cancel, retry, RMF replan·재배정·decommission, Pinky bounded recovery, OMX
cancel·retry·home 또는 운영자 승인을 결정한다. deterministic rule을 우선하고 VLM/RL은
제안·평가 역할로 제한한다. Control Tower는 `/cmd_vel`, Nav2 planner/controller와 OMX joint
command를 직접 소유하지 않으며 각 실행 계층의 공식 adapter를 통해서만 명령한다.

### 4.2 Open-RMF

Open-RMF는 이동 작업, mobile robot 배정과 traffic의 원본이다. navigation graph,
itinerary, negotiation, mutex, charger와 battery forecast를 사용한다. 실시간 SOC와
dispatchable 상태는 Pinky 관측을 사용한다. `reversible`, footprint, velocity와 battery
mechanical parameter는 Nav2/실물 값과 검증된 runtime config에서 일치해야 한다.

### 4.3 Pinky Fleet Adapter와 RMF Bridge

Fleet당 process 하나만 `add_easy_fleet`을 호출한다. 각 robot child adapter는 독립 pose,
SOC, command execution과 stop callback을 갖지만 fleet handle과 RMF participant ownership은
중복하지 않는다. Adapter는 assignment registry에서 정확한 TaskContext를 얻은 뒤에만
Pinky 명령을 발행한다. unknown task, stale revision, decommissioned robot과 unsupported
action은 실행하지 않고 안정적인 reason code를 반환한다.

### 4.4 Pinky

Pinky는 물리 관측과 즉시 안전의 원본이다. Nav2 결과뿐 아니라 목표 pose 허용 오차,
실제 정지와 Safety clear를 확인한 뒤 terminal event를 만든다. Safety stop은 FMS, MySQL
또는 RMF 응답을 기다리지 않는다. 실제 `BatteryState`가 runtime SOC의 원본이고 RMF의
mechanical/battery 값은 계획용 forecast parameter다. YOLO의 사람·물체 관측이 위험
조건을 만족하면 Control Tower 판단을 기다리지 않고 Safety가 우선 정지하고, 이후
Control Tower가 task hold와 복구 절차를 조정한다.

### 4.5 OMX Adapter

OMX Adapter는 arm/workcell의 명령 변환과 상태 관측만 담당한다. OMX는
`devices.fleet_name=NULL`이며 RMF traffic participant가 아니다. Control Tower가 위치·작업대
reservation과 stage 전이를 소유하고, FMS Gateway를 통해 멱등 command와 terminal event를
연결한다. 관절 제한, 충돌 방지, torque/current limit과 장비 interlock은 OMX 로컬
controller가 즉시 적용하고 Control Tower는 그 결과를 관제해 cancel·retry·home 또는
운영자 점검을 조정한다.

### 4.6 FMS Gateway와 MySQL

FMS Gateway는 HTTP/TCP 요청의 검증, assignment registry, outbox/inbox 상태, device
projection과 업무 transaction을 소유한다. 기존 Control Tower runtime repository의 직접
MySQL 접근은 FMS Gateway 내부 repository와 HTTP client로 분리한다. MySQL은 결과를
보존하지만 RMF·Safety·장비를 직접 제어하지 않는다.

### 4.7 Gazebo

Gazebo 시험은 동일한 Pinky stack 위에서 hardware source만 simulation으로 대체한다.
simulation battery는 ROS clock을 사용하며 pause·배속 시나리오를 검증한다. 실물 전환 시
launch profile이 world/spawn/`ros_gz_bridge`만 제외하고 RMF, Adapter, Gateway, DB 계약은
유지해야 한다.

## 5. 식별자 계약

### 5.1 공용 TaskContext

새 `trihouse_interfaces/msg/TaskContext.msg`를 정의한다.

```text
bool active
uint64 job_id
uint64 job_step_id
uint64 assignment_revision
string rmf_task_id
string command_id
string map_revision
string command_source
```

| 필드 | 단일 의미 |
| --- | --- |
| `job_id` | MySQL `jobs.job_id` |
| `job_step_id` | MySQL `job_steps.job_step_id` |
| `assignment_revision` | 늦은 이전 배정 결과를 거부하는 fencing 값 |
| `rmf_task_id` | Open-RMF booking ID |
| `command_id` | 개별 물리 실행 명령 UUID |
| `map_revision` | release manifest에서 검증한 content-derived 지도 revision |
| `command_source` | `rmf`, `manual`, `recovery` 중 명령 권한 출처 |

활성 작업이 없으면 `active=false`, 숫자는 `0`, 문자열은 빈 값으로 둔다. 문자열에서
DB 숫자를 추측하거나 `rmf:`·`rmf-nav:` 접두사를 해석하지 않는다.

Control Tower가 RMF task acceptance를 저장할 때 FMS Gateway assignment registry에
`rmf_task_id`, DB ID, assignment revision과 map revision을 결합한다. EasyFullControl
callback은 이 registry를 조회해 정확한 TaskContext를 얻은 뒤에만 `ExecuteTransport`를
호출한다. 운영 모드에서 DB ID를 얻지 못하면 명령을 만들지 않고
`ASSIGNMENT_CONTEXT_NOT_FOUND`로 거부한다. FMS Gateway는 장비가 돌려준 모든 ID가 registry의
같은 단계인지 다시 교차 검증한다.

`TaskContext`는 다음 계약에 포함하고 모든 producer·consumer를 한 migration에서 변경한다.

- `ExecuteTransport.action` goal
- `NavigationState.msg`
- `TaskEvent.msg`
- `RobotStatus.msg`

기존 중복 문자열 `job_id`, `job_step_id`, `goal_id`는 새 계약으로 교체한다. 숫자형 DB ID와
기존 문자열 ID가 섞인 중간 상태를 release하지 않으며 외부 wire payload도 같은 의미를
사용한다.

### 5.2 메시지와 이벤트 ID

- `integration_messages.message_id`: 전송 한 건의 UUID
- `TaskEvent.event_id`: 장비가 생성한 결과 이벤트 UUID
- `job_step_attempts.attempt_uuid`: 실행 시도 UUID
- `TaskContext.command_id`: 실제 실행 명령 UUID

서로 다른 식별자를 같은 값으로 재사용하지 않는다. 다만 command와 terminal event의
관계는 `job_step_attempts.command_uuid`, `event_uuid`로 명시한다.

## 6. RobotStatus 계약

현재 `RobotStatus.msg`의 `frame_id`, `pose`, `twist`, `navigation_state`는 동일 의미 필드를
새로 만들지 않고 실제 TCP와 DB 경계까지 전달한다. `map_revision`, 공용
`TaskContext task_context`와 계층화된 readiness 필드를 추가한다.

```text
builtin_interfaces/Time stamp
string robot_id
string software_version
string frame_id
string map_revision
geometry_msgs/PoseWithCovariance pose
geometry_msgs/Twist twist
float32 battery_percentage
trihouse_interfaces/BatteryPolicyState battery_policy
trihouse_interfaces/CargoState cargo
trihouse_interfaces/SafetyState safety
trihouse_interfaces/TaskContext task_context
float32 task_progress
uint8 navigation_state
bool telemetry_valid
bool execution_ready
bool dispatchable
bool ready
string[] errors
```

`StatusNode`는 다음 규칙으로 필드를 채운다.

- 신선한 `/amcl_pose`가 있으면 `frame_id=map`과 map pose를 사용한다.
- AMCL이 없으면 odom pose와 실제 odom frame을 넣고 RMF adapter가 등록을 거부한다.
- `twist`는 최신 `/odom.twist.twist`를 사용한다.
- `map_revision`은 preflight가 release manifest와 artifact hash로 검증한 값이다.
- navigation message가 제공한 공용 TaskContext를 그대로 보존한다.
- `telemetry_valid`는 map pose, scan, odom과 battery freshness가 모두 유효할 때만 참이다.
- `execution_ready`는 telemetry가 유효하고 Nav2 action server, control link와 Safety가 실행
  가능한 상태일 때만 참이다.
- `dispatchable`은 execution-ready 상태에서 battery policy, maintenance, cargo와 현재
  control mode가 신규 RMF 업무를 허용할 때만 참이다.
- 기존 `ready`는 wire compatibility 기간에만 `dispatchable`과 같은 값으로 제공하고 이후
  제거한다. FleetNode와 RMF commission/decommission은 동일 evaluator 결과를 사용한다.

### 6.1 TCP robot_status schema v3

```json
{
  "type": "robot_status",
  "schema_version": 3,
  "robot_id": "PK_01",
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "sequence": 123,
  "sent_at_ns": 123456789,
  "map_revision": "project1:4a8c1e52f719",
  "frame_id": "map",
  "pose": {"x": 1.2, "y": 3.4, "yaw": 0.5},
  "twist": {"linear_x_mps": 0.2, "angular_z_rps": 0.1},
  "navigation_state": 1,
  "task_progress": 0.4,
  "task_context": {
    "active": true,
    "job_id": 10,
    "job_step_id": 31,
    "assignment_revision": 2,
    "rmf_task_id": "rmf-task-10-31",
    "command_id": "1747bf84-6597-4b2f-9a71-bf65539b2836",
    "map_revision": "project1:4a8c1e52f719",
    "command_source": "rmf"
  },
  "battery_percentage": 74.5,
  "battery_condition": {
    "percentage": 74.5,
    "present": true,
    "power_supply_status": 2,
    "measurement_valid": true,
    "has_valid_sample": true,
    "telemetry_fresh": true
  },
  "battery_policy": {
    "state": 1,
    "ready": true,
    "reason_code": "BATTERY_NORMAL",
    "detail": "battery permits normal work"
  },
  "safety_state": 0,
  "cargo_state": 1,
  "telemetry_valid": true,
  "execution_ready": true,
  "dispatchable": true,
  "ready": true,
  "errors": []
}
```

`session_id`는 GatewayNode 기동마다 생성하는 UUID이고 `sequence`는 session 안에서 1씩
증가한다. FMS Gateway는 활성 connection의 session과 마지막 sequence보다 오래된 상태를
거부한다. 매초 상태 payload는 `integration_messages`에 넣지 않는다.

## 7. 장비 상태 projection

### 7.1 device_states

`device_states`는 장비당 최신 한 행만 보유한다.

| 입력 | 저장 대상 |
| --- | --- |
| 통합 `robot_id` | `device_id` |
| FMS 수신 KST 시각 | `observed_at` |
| 계산된 행동 상태 | `state` |
| 계산된 건강 상태 | `health` |
| 검증된 TaskContext | `current_job_step_id` |
| map pose | `pose_x`, `pose_y`, `pose_yaw` |
| 배터리 백분율 | `battery_pct` |
| 단계 진행률 | `progress` |
| frame, revision, twist, battery policy, cargo, safety, 원본 시각 | `details` |

위치와 속도를 매초 이력 행으로 만들지 않는다. 속도는 POC 동안
`details.motion.linear_x_mps`, `details.motion.angular_z_rps`에 둔다. 반복 조회·인덱스가
필요하다는 측정 근거가 생기기 전에는 전용 컬럼을 추가하지 않는다.

UPSERT는 incoming session·sequence가 현재 행보다 최신일 때만 적용한다. `REPLACE`는
사용하지 않는다.

### 7.2 state 우선순위

| 우선순위 | 조건 | `device_states.state` |
| --- | --- | --- |
| 1 | Safety emergency | `estop` |
| 2 | Safety stop | `blocked` |
| 3 | navigation failed 또는 치명적 error | `error` |
| 4 | battery policy CHARGING | `charging` |
| 5 | navigation active | `moving` |
| 6 | 활성 작업이 있으나 이동하지 않음 | `waiting` |
| 7 | 활성 작업 없이 정상 대기 | `idle` |

`docking`, `working`, `maintenance`는 해당 명시적 상태 입력이 들어오는 경우에만 사용한다.
관측되지 않은 행동을 추측하지 않는다.

### 7.3 health 우선순위

| 조건 | `device_states.health` |
| --- | --- |
| Safety stop 또는 emergency | `safety_hold` |
| navigation failure 또는 치명적 장비 오류 | `fault` |
| battery UNKNOWN·RETURN_REQUIRED 또는 telemetry stale | `warning` |
| 나머지 | `ok` |

`state`는 현재 행동이고 `health`는 작업 투입과 이상 여부다. 두 값을 하나의 열거값으로
합치지 않는다.

## 8. 작업 이벤트와 실행 이력

### 8.1 전체 작업·Segment·Attempt·Event 계층

하나의 입고·출고 업무 성공과 각 Waypoint 이동 성공을 같은 행에 합치지 않는다.

```text
jobs
  전체 입고·출고 업무의 현재 상태와 최종 결과
    └─ job_steps
       목적 Waypoint 사이의 이동 segment 또는 OMX·검수·인계 단계
         └─ job_step_attempts
            같은 단계를 실제로 실행한 한 번의 시도와 성공·실패 근거
              └─ operation_events
                 시작·도착·Safety·Vision·RMF replan 등 시간순 사실
```

권장 단위는 “Waypoint 하나”보다 “Waypoint A에서 B까지 이동하는 하나의 segment”입니다.
전체 작업은 다음처럼 순서 있는 step으로 구성한다.

```text
전체 출고 Job
├─ Step 10: 현재 위치 → 입고 대기점
├─ Step 20: 입고 대기점 → OMX_01 설비점
├─ Step 30: OMX_01 적재
├─ Step 40: 설비점 → 협로 대기점
├─ Step 50: 협로 대기점 → 출고 대기점
└─ Step 60: 출고 인계
```

`step_no`는 10 단위로 부여해 검증된 복구·대기 단계를 사이에 추가할 여지를 둔다. 각
navigate step의 `target_location_id`는 목적 Waypoint를 가리킨다. 계획 당시 출발점,
`sequence_id`와 `segment_no`는 우선 `job_steps.input`에 다음처럼 보존한다.

```json
{
  "source_location_id": 11,
  "target_location_id": 15,
  "sequence_id": "route-100-1",
  "segment_no": 2
}
```

출발 위치는 직전 성공 navigate step의 target, 첫 단계이면 `jobs.source_location_id`,
복구 뒤에는 검증된 RobotStatus 현재 위치 순서로 정한다. 출발 위치를 확정할 수 없으면
추측하지 않고 `SOURCE_LOCATION_UNCONFIRMED`로 hold한다. 조회 성능이나 FK 검증 요구가
측정되기 전에는 `job_steps.source_location_id` 컬럼을 추가하지 않는다.

Control Tower SequenceOrchestrator는 현재 step이 terminal success가 된 뒤에만 다음 step을
dispatch한다. 같은 목적지와 업무 의도를 재시도하면 같은 `job_step`에 새 attempt를 만든다.
목적 Waypoint, 행동 종류 또는 업무 순서가 바뀌면 기존 실패를 덮어쓰지 않고 새 recovery
step 또는 `parent_job_id`가 원래 job인 recovery job을 만든다.

현재 스키마의 `job_steps.state`에는 `held`가 없으므로 일시 정지는 새 상태값으로 저장하지
않는다. `jobs`의 workflow 상태와 reservation으로 후속 dispatch를 막고 현재 step은
`pending` 또는 `running`으로 유지하면서 `workflow.held` operation event에 hold 이유와
승인 주체를 기록한다. 실제 DB에 `held` 상태가 반드시 필요하다는 조회·운영 요구가 확인될
때만 별도 스키마 변경을 검토한다.

### 8.2 RMF task와 Waypoint step 연결

오늘의 단일 Pinky 시험은 navigate step 하나당 RMF task 하나를 제출해
`job_step_id ↔ rmf_task_id`를 직접 연결한다. 여러 목적지를 하나의 RMF composed task로
묶는 경우에는 각 `job_step`의 `rmf_phase_id`와 `rmf_event_id`로 목적지 callback을 연결한다.
화물을 보유한 연속 segment는 첫 RMF 배정에서 선택된 Pinky를 mobility session 동안
유지해야 하며, Control Tower는 robot affinity를 업무 제약으로 RMF 요청에 전달한다.

업무에 명시된 목적 Waypoint와 단순 transit graph vertex는 구분한다.

- 업무 목적 Waypoint: 독립 `job_step`과 성공·실패를 가진다.
- 중간 graph vertex와 lane 통과: 업무 상태가 아니라 `operation_events` checkpoint다.
- 협로 대기점처럼 업무·복구 판단에 필요한 지점: 명시적인 목적 Waypoint step으로 승격한다.

### 8.3 Route Checkpoint Tracker의 범위

Route Checkpoint Tracker는 active RMF route revision, 예상 graph vertex·lane, Nav2 path와
로봇 map pose를 비교해 `checkpoint entered/reached/skipped`, `lane entered/exited`, route
deviation을 발생시키는 저수준 관측기다. 업무 순서를 결정하거나 Nav2·RMF를 제어하지 않는다.

EasyFullControl의 Destination callback은 목적지 이름·좌표·graph index는 제공하지만 전체
중간 경로를 직접 제공하지 않고, RMF replan과 traffic negotiation으로 중간 route가 바뀔 수
있다. 따라서 모든 graph vertex를 `job_step`으로 만들지 않는다. 본 통합의 우선 구현은
SequenceOrchestrator이며 Route Checkpoint Tracker는 협로 내부 통과 시간, lane별 반복 실패,
RMF route와 실제 Nav2 path 비교 또는 graph-level RL 학습이 필요할 때 후속 모듈로 추가한다.

### 8.4 TaskEvent 처리

`TaskEvent`는 공용 TaskContext와 다음 안정 필드를 포함한다.

- `event_id`
- `robot_id`
- `event_type`: started, arrived, canceled, failed
- `reason_code`
- `method_code`
- `detail`

FleetNode는 STARTED, ARRIVED, CANCELED, FAILED 각각에 새 UUID를 생성한다. `event_id`에
`TaskContext.command_id`를 복사하지 않는다. 하나의 command와 여러 상태 전이의 관계는
TaskContext와 attempt의 `command_uuid`로 추적한다.

FMS Gateway는 event와 직전의 유효한 RobotStatus를 하나의 transaction에서 검증한다.
terminal 판정에 사용하는 status는 event와 같은 `robot_id`, `session_id`,
`TaskContext.command_id`, `assignment_revision`이어야 하며 FMS 수신 시각 기준 2초 이내여야
한다. 이 조건을 만족하는 status가 없으면 성공으로 추측하지 않고 불완전 결과로 분류한다.

| event | DB 처리 |
| --- | --- |
| started | matching attempt를 `running`, step을 `running`으로 전이 |
| arrived | 도착·정지·safety 기준을 분류한 뒤 attempt 종료 및 navigate step 성공 |
| canceled | attempt와 step을 `cancelled`로 종료 |
| failed | 표준 failure domain·reason을 분류하고 attempt와 step을 `failed`로 종료 |

`job_step_attempts`에는 한 번의 실행마다 다음을 채운다.

- 명령 생성 시: attempt UUID, command UUID, attempt number, actor, revision,
  method와 선택 이유
- 시작 시: `started_at`
- 종료 시: outcome, success, reason code, failure domain, detail, criteria,
  metrics와 `completed_at`
- 적용한 정책·모델이 있으면 이름과 버전을 쌍으로 기록
- 필요한 관측이 빠졌으면 성공으로 추측하지 않고 `data_quality_status=incomplete`,
  `outcome_reason_code=UNCLASSIFIED_RESULT`로 분류

### 8.5 실패·성공 이유 결정 규칙

Pinky, Nav2, Safety, Vision과 RMF는 각각 관측 사실과 source reason을 보고하고 최종 DB
reason code를 제각각 결정하지 않는다. FMS Gateway의 versioned `OutcomeClassifier`가 같은
TaskContext의 terminal event와 최신 RobotStatus를 결정 규칙에 넣어 하나의
`outcome_reason_code`와 `failure_domain`을 만든다. Control Tower는 이 결과를 사용해 다음
업무·복구 행동을 결정한다.

주원인 판정 우선순위는 다음과 같다.

1. TaskContext·map/assignment revision 불일치와 결과 데이터 부족
2. Safety emergency, 작업자 진입·낙상과 즉시 정지 원인
3. 운영자·Control Tower·RMF의 명시적인 cancel, hold 또는 replan 대체
4. localization·sensor·battery telemetry 이상
5. Nav2 planner/controller/result 실패
6. pose tolerance, 실제 정지와 Safety clear 성공 기준 미충족
7. segment timeout
8. 위 사실로 분류하지 못한 `UNCLASSIFIED_RESULT`

한 terminal 결과에 원인이 여러 개면 `outcome_reason_code`에는 최초 지배 원인 하나를 넣고
나머지는 `metrics.contributing_reasons`에 저장한다. 예를 들어 작업자 감지로 Safety가
정지해 Nav2가 aborted되면 주원인은 `SAFETY_WORKER_DETECTED`, 보조 원인은
`NAV2_ABORTED`다. 사람이 읽는 설명은 `detail`에 두며 분기 조건으로 사용하지 않는다.

| `failure_domain` | 표준 reason code 예시 |
| --- | --- |
| `none` | `WAYPOINT_REACHED`, `DOCKING_POSE_VERIFIED` |
| `navigation` | `NAV2_PATH_NOT_FOUND`, `NAV2_CONTROLLER_FAILED`, `GOAL_TOLERANCE_NOT_MET`, `ROBOT_NOT_STOPPED`, `OBSTACLE_BLOCKED_TIMEOUT`, `NARROW_PASSAGE_BLOCKED`, `LOCALIZATION_STALE`, `MAP_POSE_INVALID` |
| `safety` | `SAFETY_WORKER_DETECTED`, `SAFETY_FALLEN_WORKER_DETECTED`, `SAFETY_LATCHED` |
| `robot` | `BATTERY_RETURN_REQUIRED`, `BATTERY_TELEMETRY_INVALID`, `SENSOR_TELEMETRY_STALE` |
| `integration` | `RMF_REPLAN_REPLACED`, `RMF_TASK_CANCELLED`, `TASK_CONTEXT_MISMATCH`, `MAP_REVISION_MISMATCH`, `RESULT_DATA_INCOMPLETE` |
| `perception` | `VISION_CONFIDENCE_LOW`, `VLM_PROPOSAL_REJECTED` |

reason code는 영문 대문자 안정 코드로 저장하고 한국어 설명을 코드와 결합하지 않는다.
코드 목록, failure domain, 필수 관측과 우선순위는 versioned catalog로 관리하고 classifier
version을 attempt의 policy lineage에 기록한다.

POC navigation 성공 기준은 최소 다음 네 가지다.

| criterion | 성공 조건 |
| --- | --- |
| `NAV2_RESULT_SUCCEEDED` | 현재 command의 Nav2 결과가 성공 |
| `TARGET_POSE_WITHIN_TOLERANCE` | 최종 map pose가 목표 허용 오차 안 |
| `ROBOT_STOPPED` | 선속도·각속도가 정지 허용값 이하 |
| `SAFETY_CLEAR` | terminal 판정 시 safety가 CLEAR |

RMF `completed`는 위 Pinky terminal 결과를 대신하지 않는다. 두 결과가 불일치하면
`integration` failure event를 남기고 자동으로 전체 job을 완료하지 않는다.

각 segment는 최소 `navigation.segment.created`, `dispatched`, `started`,
`navigation.waypoint.arrived`, `navigation.segment.succeeded/failed/cancelled/replanned` 이벤트를
남긴다. 이벤트 payload에는 sequence/segment 번호, source·target Waypoint, RMF task/phase/event
ID, pose error, stop·Safety 기준, primary reason과 contributing reasons를 포함한다.

## 9. TCP 8788 서버

FMS Gateway의 FastAPI lifespan에서 `asyncio.start_server()`로 NDJSON server를 함께
시작한다. HTTP는 8080, TCP는 8788을 사용한다.

### 9.1 처리 메시지

| 메시지 | 처리 |
| --- | --- |
| `hello` | 등록 장비, schema version, session ID 검증 |
| `heartbeat` | connection 생존 시각 갱신 |
| `robot_status` | session·sequence·revision 검증 후 최신 상태 UPSERT |
| `task_event` | event UUID 중복 확인 후 업무·단계·attempt·event transaction |
| `command_ack` | outbound Pinky message 전달 상태 반영 |

한 TCP connection은 hello에서 선언한 장비 하나만 대표한다. 이후 payload의 robot ID가
다르면 connection을 종료한다. 한 줄의 최대 크기를 설정해 무제한 메모리 사용을 막고,
잘못된 UTF-8·JSON·schema는 DB에 넣지 않는다.

### 9.2 durable outbox, ACK와 재전송

- 상태는 ACK를 기다리지 않는다. 다음 1초 상태가 최신 snapshot을 회복한다.
- task event는 FMS transaction commit 뒤에만 ACK한다.
- DB 연결·transaction timeout 같은 일시 오류에는 terminal ACK를 보내지 않는다.
- 복구 불가능한 schema·ID·revision 검증 실패에는 `event_rejected`와 안정적인
  `reason_code`를 반환한다. Pinky는 해당 event의 자동 재시도를 끝내고 dead-letter 로그에
  남긴다.
- Pinky Gateway는 TaskEvent를 전송하기 전에 로컬 SQLite outbox에 원자적으로 저장하고,
  미확인 event를 같은 `event_id`와 동일 payload로 재전송한다.
- FMS는 `event_uuid` unique로 중복 효과를 막고 중복 event에도 같은 ACK를 반환한다.
- ACK를 받은 뒤에만 outbox row를 삭제한다. process 또는 PC 재시작 후에도 pending row를
  다시 읽어 전송한다.
- outbox는 `event_id`, immutable payload, created_at, retry_count, last_attempt_at을 가지며
  event UUID unique constraint를 둔다. 최대 보관량 초과 시 terminal event를 삭제하지 않고
  신규 업무를 차단해 운영자 조치를 요구한다.
- JSONL 측정 로그는 outbox가 아니며 재전송 여부를 결정하는 데 사용하지 않는다.

### 9.3 offline watchdog

마지막 유효 `robot_status` 이후 5초가 지나면 다음을 한 번 수행한다.

- `device_states.state=offline`
- `device_states.health=warning`
- 신규 작업 배정 차단
- `robot.offline` operation event 추가

다음 유효 상태가 오면 `robot.online` event를 한 번 기록하고 최신 projection으로 복귀한다.

## 10. RMF worker와 내부 API

FMS Gateway 내부 API는 운영 UI용 공개 API가 아니라 Control Tower, RMF Worker, Fleet
Adapter와 지도 Publisher가 runtime 상태 변경을 요청하는 service-to-service HTTP 경계다.
Pinky·OMX 장비의 RobotStatus와 TaskEvent는 TCP 8788을 사용하고, 사람이 조회·승인하는
기능은 `/api/v1`, 내부 process의 transaction 요청은 `/internal/v1`로 분리한다.

내부 API가 필요한 이유는 다음과 같다.

- Control Tower, RMF Worker와 Adapter에 MySQL credential을 배포하지 않는다.
- ID, map/assignment revision, 상태 전이와 schema를 한 경계에서 검증한다.
- 동일 요청의 멱등성과 늦은 이전 배정 결과의 fencing을 보장한다.
- job, step, attempt, message와 operation event를 하나의 transaction으로 변경한다.
- 8.5의 OutcomeClassifier가 모든 producer의 관측을 같은 reason catalog로 분류한다.
- DB schema가 바뀌어도 ROS·RMF·UI consumer의 계약을 유지한다.

FMS Gateway는 API를 통해 traffic, Nav2 경로 또는 Safety를 결정하지 않는다. 공식 실행
계층이 보고한 사실을 검증해 runtime 상태와 이력으로 일관되게 만드는 역할이다.

최소 API는 다음으로 고정한다.

| endpoint | caller | transaction 책임 |
| --- | --- | --- |
| `POST /internal/v1/maps/published` | control_system map Publisher | manifest/hash/revision 검증, 운영 Waypoint·설비 location projection |
| `POST /internal/v1/jobs` | Control Tower | 전체 job, 순서 있는 segment/OMX steps와 최초 operation event 생성 |
| `POST /internal/v1/job-steps/{id}/dispatch` | Control Tower SequenceOrchestrator | 현재 step 검증, outbound RMF/OMX message와 idempotency key 생성 |
| `POST /internal/v1/rmf/dispatches/claim` | RMF Worker | `FOR UPDATE SKIP LOCKED`로 전송할 RMF message 선점 |
| `POST /internal/v1/rmf/dispatches/{message_id}/acceptance` | RMF Worker | 수락·거절, `rmf_task_id`와 step 연결 |
| `POST /internal/v1/rmf/tasks/{rmf_task_id}/commands/claim` | Fleet Adapter | robot/execution/revision 검증, attempt·command UUID와 TaskContext 발급 |
| `POST /internal/v1/rmf/tasks/{rmf_task_id}/observations` | RMF Worker | RMF task/phase/event 상태 projection |
| `POST /internal/v1/execution-events` | RMF Worker·Adapter | segment·Waypoint·lane·replan 관측과 operation event 반영 |
| `GET /api/v1/jobs/{job_id}` | Control Tower UI | 전체 업무와 현재 step 조회 |
| `GET /api/v1/jobs/{job_id}/timeline` | Control Tower UI | segment·attempt·RMF·Vision·Safety 이벤트 시간순 조회 |

모든 변경 요청은 `request_id` 또는 `Idempotency-Key`, actor, 발생 시각과 관련 TaskContext를
포함한다. 같은 키와 같은 payload는 기존 결과를 반환하고, 같은 키에 다른 payload가 오면
409 conflict로 거부한다. POC internal API는 `127.0.0.1`로만 노출하고 외부 UI API와 경로를
분리한다. 운영 배포의 service 인증은 별도 배포 보안 gate에서 추가한다.

RMF Worker는 ROS 환경 때문에 호스트에서 실행하고 다음 순서로 내부 API를 사용한다.

```text
POST /internal/v1/rmf/dispatches/claim
→ FMS Gateway가 FOR UPDATE SKIP LOCKED로 outbound 행 선점

RMF worker
→ task_api_requests에 공식 dispatch_task_request 발행

POST /internal/v1/rmf/dispatches/{message_id}/acceptance
→ 수락·거절과 rmf_task_id를 job_step에 반영

POST /internal/v1/rmf/tasks/{rmf_task_id}/commands/claim
→ robot_id, RMF execution ID, map revision 검증
→ 동일 RMF execution ID 요청은 멱등하게 기존 command를 반환
→ robot assignment binding, attempt와 command UUID 생성
→ 완전한 TaskContext 반환

task_summaries 구독
→ POST /internal/v1/rmf/tasks/{rmf_task_id}/observations
→ job_steps RMF projection 반영
```

assignment registry는 별도 중복 상태 저장소가 아니라 unique `job_steps.rmf_task_id`, 현재
assignment revision, assigned device와 `job_step_attempts.command_uuid`의 transaction view다.
따라서 새 테이블은 기존 컬럼으로 불변식을 표현할 수 없는 경우에만 추가한다. Adapter는
위 claim API의 성공 응답 없이 `ExecuteTransport`를 호출하지 않는다.

### 10.1 RMF 상태 매핑

| RMF 상태 | `job_steps.rmf_status` | `job_steps.state` |
| --- | --- | --- |
| queued 또는 pending | 원본 안정 문자열 | `pending` |
| active | `active` | `running` |
| completed | `completed` | Pinky 결과까지 일치할 때 `succeeded` |
| failed | `failed` | `failed` |
| canceled | `canceled` | `cancelled` |

알 수 없는 task, 지원하지 않는 상태 또는 더 오래된 관측 시각은 현재 업무를 변경하지
않고 operation event에 기록한다. RMF 완료만으로 `jobs.state=completed`를 만들지 않는다.

## 11. MySQL 저장 책임

| 테이블 | 데이터 출처 | 저장 규칙 |
| --- | --- | --- |
| `locations` | RMF 지도·운영 설정 | waypoint, 슬롯, 충전기, 포장대의 논리 위치 |
| `map_features` | 지도·안전 설정 | release manifest와 같은 content-derived revision의 feature |
| `workers` | 계정 관리 | 운영자와 승인 권한 마스터 |
| `devices` | 장비 등록 | 네 개 통합 장비 ID의 불변 마스터 |
| `device_states` | RobotStatus·OMX status | 장비당 최신 한 행 UPSERT |
| `inventory_lots` | 재고 workflow | 현재 lot 수량·위치 |
| `inventory_moves` | 재고 확정 | 수량 변화 append-only 원장 |
| `jobs` | 주문·복구 workflow | 하나의 전체 입고·출고 업무 현재 상태와 최종 결과 |
| `job_items` | 주문·QR·lot 배정 | 업무 대상과 처리 수량 |
| `job_steps` | SequenceOrchestrator·RMF·OMX | Waypoint A→B segment 또는 OMX·검수 단계의 현재 상태와 최종 요약 |
| `job_step_attempts` | Pinky·OMX·FMS 실행 | 같은 step의 실제 실행·재시도 한 번당 방법·성공 기준·결과 한 행 |
| `reservations` | 업무 자원 정책 | 도크·포장대·OMX 점유. RMF lane·mobile robot 점유는 저장하지 않음 |
| `integration_messages` | RMF·Pinky·OMX 연동 | 명령·결과의 멱등·재전송 상태 |
| `incidents` | Safety·Vision·운영자 | 진행 중 안전 사건 |
| `operation_events` | segment·Waypoint·RMF·Vision·Safety 변화 | append-only 사실·판단·승인·결과와 학습 label |
| `artifacts` | rosbag·영상·JSONL | 파일 URI, SHA-256과 label 연결 |
| `location_recovery_profiles` | 검증된 safe node | 복구 후보 위치와 신뢰도 |
| `recovery_episodes` | 복구 workflow | 복구 사건과 정책·모델 계보 |
| `recovery_steps` | 실제 복구 행동 | 행동·전후 관측·보상·결과 |

### 11.1 project1 fleet와 DB 장비 마스터 동기화

launch는 DB를 수정하지 않는다. 별도 registry 동기화 단계가 project1 입력을 읽어 정규화된
장비 manifest를 만들고 FMS Gateway 내부 API를 통해 검증·반영한다. Control Tower나 ROS
노드가 MySQL에 직접 연결하지 않는다는 2.1과 4.6의 원칙을 유지한다.

지도 Publisher는 authoring DB에서 publish한 project manifest도 같은 API 경계로 전달한다.
FMS Gateway는 `map_revision`과 artifact hash를 먼저 검증한 뒤 업무에 사용되는 Waypoint,
충전기, 도크와 설비 위치만 `locations`에 upsert한다. RMF lane graph 전체를 runtime DB에서
재구성하거나 DB lane 예약으로 Open-RMF traffic을 대체하지 않는다.

동기화 입력과 DB 매핑은 다음과 같다.

| project1 입력 | DB 대상 |
| --- | --- |
| `fleet.yaml.robots[].id` | `devices.device_id` |
| `kind=mobile/workcell` | `devices.device_type=mobile/arm` |
| `name` | `devices.name` |
| `model` | `devices.model` |
| mobile + RMF config fleet name | `devices.fleet_name=project1_pinky` |
| workcell | `devices.fleet_name=NULL`, station·workcell group은 capabilities에 저장 |
| charger/station waypoint | `devices.home_location_id`과 `locations.rmf_waypoint_name` |
| `gz_name`, zones, data source, RMF robot name | `devices.capabilities` JSON |
| spawn pose | 초기 시험용 `device_states`가 아니라 capabilities의 simulation metadata |

`capabilities`의 최소 형식은 다음과 같다.

```json
{
  "data_source": "gazebo",
  "gz_name": "pinky_01",
  "rmf_robot_name": "PK_01",
  "zones": ["ambient", "chilled", "frozen"],
  "navigation": true,
  "rmf": true
}
```

초기 spawn pose를 최신 관측값처럼 `device_states`에 seed하지 않는다. Gazebo의 실제
RobotStatus가 들어오기 전에는 상태를 `offline` 또는 미관측으로 유지한다. 위치 seed는
`locations`의 charger/station 기준정보에만 사용한다.

동기화 명령은 기본적으로 diff만 출력한다. 명시적 `--apply`에서만 다음을 수행한다.

1. `충전1`, `충전2`, `설비1`, `설비2`가 building/nav graph에 존재하는지 확인한다.
2. 기존 `PINKY-01`, `PINKY-02`, `OMX-01`, `OMX-02`, `PK-01`, `PK-02` 참조를 보고한다.
3. FK와 논리 참조 migration이 준비되지 않았으면 적용을 거부한다.
4. FMS Gateway transaction으로 locations와 devices를 upsert한다.
5. 재조회해 네 장비의 ID, fleet, home location, capabilities가 manifest와 같은지 확인한다.

현재 `db/seed_dev.sql`의 `PINKY-01`, `PINKY-02`, `OMX-01`, `OMX-02`와 `pinky_fleet`은
project1 계약과 불일치한다. 구현 단계에서 12.3의 ID migration과 새 개발 seed를 함께
수정해야 하며 문자열 치환만으로 기존 FK를 깨뜨리면 안 된다.

### 11.2 원시 관측과 DB label 분리

다음 고빈도 원시 데이터는 MySQL에 매 sample INSERT하지 않는다.

- `/scan`, 원시 `/odom`, 전체 TF
- 카메라 frame과 point cloud
- 동일 상태의 1초 heartbeat

이 데이터는 rosbag·영상·JSONL 파일에 저장하고 `artifacts`가 URI와 해시를 가리킨다.
MySQL에는 최신 snapshot, 상태 변화, 작업 결과와 학습 label만 저장한다.

## 12. 스키마와 문서 정합성

### 12.1 확인된 문제

- `db/schema_mysql.sql`: 19개 테이블과 298개 컬럼의 현재 물리 기준
- `docs/database/data_dictionary.xlsx`: 18개 테이블과 253개 컬럼만 포함
- XLSX에는 `job_step_attempts` 전체와 최신 jobs·job_steps·operation_events 컬럼이 누락
- `004_add_korean_comments.sql`은 현재 `jobs.state DEFAULT 'queued'`와 달리 과거
  `DEFAULT 'pending'`을 포함
- 기존 metadata check는 XLSX에 존재하는 253행의 설명만 확인하고 누락 구조를 실패로
  판정하지 않음

### 12.2 단일 원본과 변경 방식

`db/schema_mysql.sql`을 유일한 물리 스키마 원본으로 삼는다.

1. 새 DB는 항상 이 파일로 생성한다.
2. 구현 전 실제 DB와 schema 원본을 diff한다. 필요한 컬럼·index·constraint가 이미 있으면
   구조 migration을 만들지 않고 기존 필드를 재사용한다.
3. 구조 차이가 확인된 경우에만 새 migration을 추가한다. 장비 ID·fleet 정리는 구조 변경과
   분리된 data migration으로 수행한다.
4. 이미 적용됐을 수 있는 `004`는 수정하지 않고 역사적 migration으로 유지한다.
5. XLSX를 현재 19개 테이블·298개 컬럼 전체로 재생성한다.
6. sync check가 SQL과 XLSX의 테이블·컬럼 집합 차이도 실패로 판정하게 한다.
7. `database_guide.md`의 과거 상태값·migration 예시를 현재 계약에 맞춘다.

### 12.3 장비 ID migration

FK 검사 비활성화로 문제를 숨기지 않고 다음 순서를 하나의 migration transaction으로
수행한다.

1. 기존 device 마스터를 새 ID로 복제한다.
2. `device_states`, jobs, job_steps, attempts, reservations, integration messages,
   operation events, artifacts의 FK를 새 ID로 갱신한다.
3. `trihouse_recovery.recovery_episodes.device_id` 논리 참조도 갱신한다.
4. RMF robot name과 capabilities를 새 ID로 정렬한다.
5. 참조가 남지 않았음을 검증한 뒤 옛 device 행을 제거한다.

일회용 `compose.db_test.yaml`은 갱신된 seed로 바로 새 ID를 만든다.

## 13. 오류 처리

| 상황 | 처리 |
| --- | --- |
| 잘못된 장비 ID | connection 또는 message 거부, DB 변경 없음 |
| map revision이 release manifest와 다름 | 명령·상태 작업 연결 거부, `MAP_REVISION_MISMATCH` 기록 |
| 오래된 session·sequence | 최신 상태 덮어쓰기 금지 |
| status 유실 | 다음 status로 snapshot 회복 |
| 5초 status timeout | offline 전이와 신규 배차 차단 |
| DB 일시 장애 | safety 운행은 계속, status는 다음 sample로 회복 |
| task event DB 실패 | ACK 보류, 같은 event ID 재전송 |
| task event 영구 검증 실패 | `event_rejected` 반환, 자동 재시도 중단과 dead-letter 기록 |
| 중복 task event | DB 효과 한 번, ACK는 재전송 |
| RMF 응답 timeout | 같은 request ID로 재시도 |
| 늦은 이전 배정 결과 | assignment revision 불일치로 거부 |
| 알 수 없는 RMF task | 업무 변경 없이 경고 event |
| RMF와 Pinky terminal 결과 불일치 | integration failure, 자동 job 완료 금지 |
| 동일 fleet adapter가 둘 이상 기동 | participant/fleet ownership preflight 실패 |
| `dispatchable=false` | RMF decommission, FleetNode 신규 명령 거부 |
| RMF와 direct TCP command 충돌 | control mode와 command source 불일치로 거부 |
| durable outbox 용량 한계 | event 삭제 금지, 신규 업무 차단과 운영 incident 생성 |

## 14. 통합 실행 구성

새 `compose.integration_test.yaml`은 다음 두 service만 시작한다.

```text
trihouse_integration_test
├─ mysql_test: MySQL 8.4, tmpfs, host 3307
└─ fms_gateway: HTTP 8080, TCP 8788
```

Gazebo, ROS 2, RMF schedule·dispatcher와 RMF worker는 호스트에서 실행한다. MySQL
tmpfs는 시험 종료 후 사라지므로 장기 실험 데이터는 영구 `compose.db.yaml`에서 별도로
수행한다.

전체 실행은 두 단계로 유지한다. Docker Compose가 MySQL과 FMS Gateway를 먼저 준비하고,
`trihouse_rmf_bridge/launch/control_system_rmf.launch.py`가 Gazebo, RMF core, Nav2, Pinky,
단일 Trihouse EasyFullControl Adapter와 선택적 OMX ROS graph를 시작한다. Docker lifecycle을
ROS launch 안에 숨기지 않는다.

### 14.1 `control_system_rmf.launch.py` 경계

launch는 선택한 `control_system_root`가 생성한 `project1.launch.xml`,
`project1_bringup.launch.xml`, `project1_nav2.launch.xml` 전체를 그대로 include하지 않는다.
이 파일들은 과거 절대경로, OMX 필수 의존성과 기존 `project1_nav2_adapter.py` 실행을
포함하고, 함께 제공되는 `run_project1.sh`는 source world 패치와 nav graph 생성을 수행하기
때문이다. 대신 검증된 project artifact 중 필요한 world, building, simulation bridge,
robot spawn과 robot Nav2 파일을 선택적으로 include하고 Trihouse Pinky stack과 fleet당
하나의 EasyFullControl adapter를 조합한다.

명령 소유권은 하나로 고정한다.

```text
Open-RMF
→ Trihouse EasyFullControl adapter
→ ExecuteTransport
→ Pinky FleetNode
→ namespaced Nav2 NavigateToPose
→ Safety Supervisor
→ namespaced final cmd_vel
→ ros_gz_bridge
→ Gazebo
```

`project1_nav2_adapter.py`와 중복 명령 경로인 기존 `project1_task_bridge.py`는 실행하지 않고
Trihouse EasyFullControl Adapter만 fleet adapter로 실행한다.
Nav2 controller의 원래 `/<namespace>/cmd_vel`은 `/<namespace>/cmd_vel_nav`으로 remap하고,
Safety Supervisor만 최종 `/<namespace>/cmd_vel`을 발행한다.

Pinky Adapter launch action은 `robot_ids`마다 process를 만들지 않는다. 하나의 process에
선택된 robot ID 목록을 넘기고, process 내부에서 한 fleet handle 아래 child adapter를
생성한다. 1차 시험 runtime overlay는 unsupported `teleop`, `armLoad`를 제거하고
`reversible=false`를 사용한다. 충전 시나리오에서만 검증된 overlay로
`finishing_request=charge`를 적용한다.

### 14.2 CLI argument 계약

필수·경로 인자는 ML/DL 실행 CLI처럼 launch invocation에서 명시적으로 덮어쓸 수 있어야
한다. 기본값은 현재 workspace에 맞추되 코드 로직에서 `/home/gyi`를 사용하지 않는다.

| argument | 기본값 또는 의미 |
| --- | --- |
| `control_system_root` | 승격 후 `/home/syw/Trihouse/control_system_root`; 후보 시험은 CLI로 `/home/syw/Trihouse/control_system_test` 지정 |
| `runtime_state_root` | event outbox 등 가변 상태를 보존하는 명시적 경로. `control_system_root` 외부여야 함 |
| `rmf_ws_root` | `/home/syw/rmf_ws`; setup 파일과 build/install 상태 검증 |
| `integration_profile` | `test` 또는 `release`; root와 manifest 상태가 profile에 맞지 않으면 실패 |
| `project_name` | `project1` |
| `map_dir` | `<control_system_root>/rmf_maps/<project_name>` |
| `release_manifest` | `<control_system_root>/trihouse_release_manifest.json` |
| `fleet_file` | `<map_dir>/fleet.yaml` |
| `rmf_fleet_config` | `<map_dir>/<project_name>_pinky_config.yaml` |
| `rmf_fleet_overlay` | unsupported action, reversible, finishing request 등 시험별 override |
| `building_yaml` | `<map_dir>/<project_name>.building.yaml` |
| `world` | `<map_dir>/<project_name>.world` |
| `nav_graph` | `<map_dir>/nav_graphs/0.yaml` |
| `nav2_map` | `<map_dir>/nav2_map/<project_name>.yaml` |
| `gz_bridge_config` | `<map_dir>/<project_name>_gz_bridge.yaml` |
| `robot_ids` | 첫 시험 `PK_01`; 쉼표로 `PK_01,PK_02` 선택. 단일 fleet process의 child filter |
| `start_omx` | 기본 `false`; OMX 패키지가 설치된 뒤에만 `true` |
| `start_gazebo`, `start_rmf_core`, `start_nav2` | 각 계층 독립 모듈 시험 스위치 |
| `start_pinky_stack`, `start_rmf_adapter` | Pinky 제어와 RMF adapter 독립 스위치 |
| `start_control_gateway` | 실제 TCP 8788 경계 실행 여부 |
| `headless`, `use_sim_time` | 기본 `true` |
| `map_revision` | 기본 `auto`; manifest와 artifact에서 계산하며 임의 문자열 override는 test에서만 허용 |
| `command_mode` | 기본 `RMF_MANAGED`; 수동·복구는 별도 절차와 fencing 필요 |
| `control_host`, `control_port` | 기본 `127.0.0.1`, `8788` |
| battery scenario 인자 | 초기 SOC, charging, 충·방전 가속률 |

개별 artifact 경로를 넘기면 `map_dir` 파생값보다 우선한다. 존재하지 않는 경로, project
이름과 맞지 않는 파일, fleet에 없는 robot ID, manifest hash가 다른 파일은 launch 시작 전
preflight 실패로 처리한다. 코드 로직과 생성 파일에 `/home/gyi` 같은 개발자별 절대경로를
남기지 않는다.

### 14.3 `control_system_test` 후보본 준비

`control_system` 직접 실행 모드는 제공하지 않는다. 새 후보본은 명시적인 copy/clone 명령으로
만들고 source SHA를 기록한다.

1. source가 유효한 `control_system` Git repository인지 확인한다.
2. destination `/home/syw/Trihouse/control_system_test`가 없을 때만 copy/clone한다.
3. upstream SHA를 candidate metadata에 기록한다.
4. 추적 중인 `.log`, `.err.log`, `.pgid`, schedule state와 build cache를 후보 정리 commit에서
   제거하고 ignore 규칙을 보완한다.
5. `/home/gyi`를 가리키는 외부 symlink와 절대경로는 CLI 인자 또는 workspace package
   dependency로 교체한다.
6. project1 생성 규칙은 `rmf_control_ui` generator에서 수정하고 다시 export한다.
7. `nav_graphs/0.yaml`, `generated_models/project1_L1`과 모든 필수 artifact를 같은 export
   run에서 생성한다.
8. golden manifest와 preflight를 통과한 뒤에만 launch한다.

현재 project1에는 `generated_models/project1_L1`과 `nav_graphs/0.yaml`이 없고 world는
`model://project1_L1`을 참조한다. 따라서 이 두 artifact가 준비되기 전에는 preflight가
실패해야 한다. 과거 backup의 파일은 현재 building hash와 같은 export run임을 증명하지
못하면 복사하지 않는다.

copy/clone 도구는 source root, destination root, project name을 CLI 인자로 받고 다음을
지킨다.

- `copy`만 사용하고 `move`를 사용하지 않는다.
- source가 control_system project인지 검증한다.
- destination project가 이미 있으면 덮어쓰거나 삭제하지 않고 실패한다.
- Git metadata를 보존하는 clone 방식 또는 명시적인 전체 copy 방식을 사용한다.
- source와 최초 candidate의 tracked file SHA-256 및 source commit을 비교한다.
- 이후 후보 변경은 별도 commit으로 남겨 upstream 변경과 Trihouse 변경을 구분한다.

### 14.4 `control_system_root` 승격

모든 gate가 성공한 candidate commit만 운영본으로 승격한다. 최초 승격은 검증된 commit을
새 `/home/syw/Trihouse/control_system_root`에 clone/copy하며 `move`하지 않는다. 승격
후 다음 필드를 가진 `trihouse_release_manifest.json`을 포함한다.

```text
upstream_commit
candidate_commit
release_commit
project_name
map_revision
building/nav_graph/nav2_map/world/fleet artifact SHA-256
rmf_ws_commit 또는 package version manifest
test_run_ids
promoted_at
```

release preflight는 manifest와 현재 파일 hash가 다르거나 필수 test run ID가 빠지면
실행을 거부한다. 이후 변경은 운영본을 직접 임시 수정하지 않고 candidate branch 또는
새 `control_system_test` clone에서 검증한 뒤 exact commit을 fast-forward 승격한다.

### 14.5 시작 순서

하나의 launch 안에서도 다음 event 순서를 보장한다.

1. preflight가 profile, repository SHA, release manifest, artifact hash, map revision,
   fleet·namespace·charger·지원 action·패키지를 검증한다.
2. Gazebo server와 clock bridge를 시작한다.
3. `/clock`과 world가 준비된 뒤 선택한 robot을 spawn한다.
4. RMF core와 building map server를 시작한다.
5. Nav2 map server, 선택한 robot의 AMCL·Nav2를 시작한다.
6. Pinky sensor/status/safety/fleet/gateway stack을 namespaced remap으로 시작한다.
7. 각 robot의 `telemetry_valid`와 `execution_ready`, TCP session을 확인한다.
8. 단일 fleet adapter process를 시작해 선택한 robot child를 등록한다.
9. `dispatchable=true`인 robot만 RMF에 commission한다.

고정 `sleep`만으로 준비를 추정하지 않는다. 프로세스 종료, `/clock`, action server, map pose,
control link, TCP connection과 fleet adapter ownership을 각각 관측하고 다음 계층을 시작하거나
명확한 timeout과 reason code로 실패한다.

## 15. 테스트 전략

### 15.1 정적·단위 테스트

- 네 개 통합 ID 외 값 거부
- TaskContext의 active·DB ID·command source·assignment·map revision 불변식
- quaternion에서 yaw 변환과 twist 직렬화
- state·health 우선순위
- 하나의 readiness evaluator가 `telemetry_valid`, `execution_ready`, `dispatchable`을 계산
- KST API 직렬화와 ROS simulation stamp 분리
- simulation battery가 ROS clock pause·배속을 따름
- session·sequence 순서 판정
- RMF 상태 매핑과 알 수 없는 상태 거부
- 예외 유형별 local Safety·RMF/Nav2·Control Tower 권한 라우팅
- VLM/RL 후보가 allowlist·confidence·freshness·revision gate 전에는 실행 명령이 되지 않음
- VLM/RL timeout·오류·낮은 confidence에서 hold와 deterministic fallback 선택
- Control Tower가 직접 `/cmd_vel`, Nav2 goal 또는 OMX joint command를 발행하지 않음
- STARTED·ARRIVED·FAILED·CANCELED가 서로 다른 event UUID 사용
- OutcomeClassifier 우선순위, primary reason과 contributing reasons 분리
- 같은 목적지 재시도는 같은 step의 새 attempt, 목적지 변경은 새 recovery step
- DB schema와 XLSX 구조 집합 일치
- CLI 경로 파생과 개별 artifact override 우선순위
- content-derived map revision 재계산과 artifact 변조 거부
- fleet.yaml과 RMF config의 robot·charger·fleet·action·reversible 교차 검증
- 한 fleet process가 선택한 PK_01·PK_02 child adapter를 모두 소유
- 동일 fleet adapter process 두 개의 기동 거부
- project1 `workcell → arm` 외 암묵적 ID 변환 거부
- OMX `fleet_name=NULL`과 Pinky `fleet_name=project1_pinky` 검증
- 기존 control_system 원본을 변경하지 않는 copy·preflight 계약
- 기존 destination 복사 거부와 runtime 파일 제외
- candidate와 release manifest의 commit·artifact hash 검증
- 선택하지 않은 OMX 패키지를 요구하지 않는 조건부 의존성
- robot namespace별 odom, scan, AMCL, Nav2 action, cmd_vel remap
- RMF_MANAGED 상태에서 TCP direct 이동 명령 거부

### 15.2 MySQL 통합 테스트

- RobotStatus UPSERT가 장비당 한 행만 유지
- 오래된 sequence가 최신 pose·battery를 덮어쓰지 않음
- 상태 변화만 operation event에 추가
- 하나의 command에 서로 다른 STARTED·ARRIVED event가 모두 반영
- started·arrived·failed·canceled의 step/attempt transaction
- assignment revision이 다른 결과 거부
- RMF task acceptance와 task summary 반영 및 command claim API 멱등성
- 매핑되지 않은 RMF task의 command claim 거부
- RMF 완료만으로 전체 job이 완료되지 않음
- 장비 ID migration 후 모든 FK와 logical reference 정합성
- project1 manifest dry-run이 기존 DB ID·fleet 불일치를 정확히 보고
- 명시적 apply 뒤 `PK_01`, `PK_02`, `OMX_01`, `OMX_02`와 home location 정합성
- 두 Pinky의 `capabilities.rmf_robot_name`과 `devices.fleet_name=project1_pinky` 정합성
- 두 OMX의 `devices.fleet_name IS NULL`과 workcell capability 정합성
- 같은 manifest 재적용의 멱등성과 fleet 파일 변경 시 차이 보고
- reservations가 OMX·도크·작업대만 소유하고 RMF lane을 중복 점유하지 않음
- 같은 exception에서 관측, VLM/RL 제안, Control Tower 승인, 실제 실행과 결과 event가
  서로 다른 ID와 시간으로 추적됨
- VLM/RL이 개입한 attempt의 model/policy 이름·버전·confidence와 승인 근거가 보존됨

### 15.3 순차 시험 gate

| Gate | 범위 | 통과 기준 |
| --- | --- | --- |
| A 정적·생성기 | candidate repo, generator, manifest, preflight | 원본 무변경, 필수 artifact/hash/ID/action 계약 일치 |
| B 상태 모듈 | Pinky mock sensor·status·battery·Safety | 지정한 telemetry/readiness/navigation/battery/Safety 상태값 출력 |
| C 지도·DB·Gateway | authoring publish·manifest·FMS API·MySQL | 운영 Waypoint projection, job→segment→attempt→event 조회 |
| D Pinky 단독 주행 | Gazebo·PK_01·Nav2·Safety | RMF 없이 goal 이동·정지, 최종 cmd_vel 단일 publisher |
| E RMF 수직 통합 | Control Tower·RMF worker·단일 adapter·PK_01·DB | RMF task↔segment step↔attempt 추적, 목적 Waypoint 성공 이유 저장 |
| F 배터리 | simulation battery·RobotStatus·RMF·DB | SOC·정책 반영, 신규 업무 허용/차단과 DB projection 정합 |
| G Vision 예외 | YOLO segmentation·worker fall detection·Safety | 물체·사람·낙상 관측과 즉시 정지, 표준 reason event 저장 |
| H 지능형 복구·다중 Pinky | VLM/RL advisory·Control Tower·PK_01/PK_02 | allowlist/fallback, RMF replan·재배정, traffic·독립 SOC 검증 |
| I 운영본·실물 | exact candidate를 `control_system_root`로 승격 후 real profile | manifest/hash 일치, 실물 보정·도킹·환경 예외 orchestration 검증 |

Gate A부터 순서대로 통과하며 이전 Gate가 실패한 상태에서 다음 계층을 붙이지 않는다.
Gate I가 끝나기 전에는 후보본을 운영본으로 부르지 않는다.

### 15.4 장애 주입 시나리오

- 주행 경로에 갑작스럽게 물체 출현
- 협로 진입, 대기, 통과 불가와 우회 판단
- 작업자가 주행로에 갑자기 진입
- 작업자가 주행로에 쓰러져 있음
- 고정 장애물로 현재 경로 사용 불가와 RMF replan
- YOLO 사람 위험 감지 시 Control Tower 응답이 없어도 local Safety 즉시 정지
- VLM/RL timeout·낮은 confidence·허용 목록 밖 행동 제안 시 hold와 rule fallback
- OMX interlock 발생 시 local 정지 후 Control Tower가 stage hold와 home/점검 절차 조정

TCP, FMS Gateway, MySQL 또는 RMF process 중단과 재시작은 현재 환경 장애 주입 범위에서
제외한다. ACK·idempotency·durable outbox 설계는 유지하지만 오늘·내일 시험 Gate와 성공
기준에는 포함하지 않는다.

### 15.5 성공 기준

- PK_01·PK_02 상태가 다른 ID 변환 없이 ROS·RMF·DB에 동일하게 나타난다.
- fleet adapter process 하나가 두 Pinky를 관리하고 RMF가 실제 robot을 선택한다.
- `RobotStatus`의 map pose, twist, navigation, battery와 readiness가 DB 최신 상태에
  반영된다.
- 하나의 전체 입출고 job이 순서 있는 Waypoint A→B segment와 OMX·인계 step으로 조회된다.
- 하나의 RMF 이동이 하나의 segment `job_step`과 하나 이상의 명시적 attempt로 연결된다.
- 각 목적 Waypoint step에서 성공·실패, primary reason, 보조 원인과 성공 기준을 조회한다.
- 성공·실패·취소가 reason, method, criteria, metrics와 함께 저장된다.
- 안전 정지는 DB·RMF 장애 중에도 Pinky 로컬에서 작동한다.
- RMF 이동 완료가 OMX·검수·인계 전 전체 job을 완료하지 않는다.
- RMF lane/robot 예약과 Control Tower 비이동 자원 예약이 중복되지 않는다.
- Control Tower가 전체 Pinky·OMX·RMF·배터리·Safety·Vision 상태를 한 업무 context에서
  관제하고 예외를 해당 권한 계층으로 정확히 전달한다.
- VLM/RL 제안은 승인 전 실행되지 않고 Safety/RMF/Nav2/OMX 로컬 제어를 우회하지 않는다.
- 승격된 운영본의 commit과 artifact hash가 시험한 후보본과 일치한다.
- 모든 DB 시각과 API 시각은 KST 의미를 유지하고 ROS simulation time과 섞이지 않는다.

### 15.6 당일·익일 시험 목표

오늘은 PK_01 한 대에 목적 Waypoint task 하나를 주는 최소 수직 흐름을 완성한다.

```text
패키지별 지정 상태값 확인
→ project1 artifact preflight
→ FMS Gateway·MySQL job/segment/attempt/event 확인
→ Gazebo PK_01·Nav2·Safety 주행
→ 단일 Trihouse EasyFullControl Adapter와 RMF task
→ 목적 Waypoint 도착과 표준 성공 이유 저장
→ battery SOC·policy·RMF·DB 반영 확인
```

내일은 같은 수직 흐름을 유지한 채 perception과 intelligent recovery를 단계적으로 붙인다.

```text
YOLO segmentation 단독 검증
→ worker fall-detection 단독 검증
→ camera 관측을 base/map frame과 Safety event로 변환
→ 갑작스러운 물체·작업자 진입·낙상 정지
→ VLM advisory와 RL allowlist 후보 평가
→ Control Tower exception coordinator 승인·fallback
→ RMF cancel/replan/reassign와 Nav2 새 goal
→ 협로·물체·사람·낙상 전체 시나리오
→ PK_02 추가 후 traffic·독립 SOC와 DB 실행 이력 확인
```

## 16. 구현 순서

### 16.1 오늘: 상태·단일 Pinky·배터리·DB 수직 통합

1. `control_system` upstream SHA 동결과 `control_system_test` copy/clone, runtime 파일·절대경로 정리
2. project1 authoring DB export, nav graph/world/model 생성, manifest와 content-derived revision preflight
3. 장비 ID·fleet·OMX `fleet_name=NULL`과 DB seed 정합성, 실제 schema diff 후 필요한 변경만 migration
4. TaskContext, 고유 TaskEvent와 공용 readiness evaluator 계약 테스트
5. Control Tower SequenceOrchestrator의 job→Waypoint segment steps 생성과 순차 dispatch
6. versioned reason catalog와 FMS Gateway OutcomeClassifier 단위 테스트
7. FMS Gateway map publish, job/step dispatch, RMF acceptance/command claim/observation, timeline API
8. MySQL job→segment→attempt→operation event transaction과 조회 테스트
9. Pinky mock sensor에서 telemetry/readiness/navigation/battery/Safety 지정 상태값 검증
10. Gazebo PK_01 spawn, AMCL·Nav2 goal과 Safety 단일 `/cmd_vel` 모듈 시험
11. fleet당 하나의 Trihouse EasyFullControl Adapter에 PK_01 등록, 기존 adapter 미실행 확인
12. Control Tower task 하나→RMF→Pinky→목적 Waypoint→DB 성공 이유 수직 시험
13. 정상·low SOC battery scenario와 RobotStatus→RMF→DB 값 확인
14. `control_system_rmf.launch.py`, Compose 선행 조건과 단계별 수동 실행 명령 정리

### 16.2 내일: Vision·VLM/RL·환경 예외와 다중 Pinky

1. YOLO segmentation과 worker fall-detection 모델을 각각 독립 검증
2. camera detection의 base/map frame 변환과 Vision event schema 연결
3. 사람·물체·낙상 위험을 Pinky local Safety 즉시 정지와 표준 reason으로 연결
4. Control Tower 전체 상태 projection과 exception coordinator state machine
5. deterministic recovery와 운영자 승인 계약
6. VLM advisory, RL 후보 평가와 allowlist·confidence·freshness·revision gate 및 fallback
7. RMF cancel·replan·재배정과 Pinky bounded recovery, Nav2 새 goal 연결
8. 갑작스러운 물체, 협로, 작업자 진입, 쓰러진 작업자 시나리오별 모듈 시험
9. 같은 사건의 Vision 관측→정책 제안→승인/거부→실행→결과 DB lineage 검증
10. PK_02 child adapter 추가, namespace·traffic·독립 SOC와 재배정 시험
11. exact candidate commit과 artifact를 `/home/syw/Trihouse/control_system_root`로 copy/clone 승격
12. 승격본 smoke test 뒤 OMX Adapter stage와 실물 보정 시험 준비

각 단계는 앞 단계의 계약 테스트를 통과한 뒤 진행한다. 보호 대상 경로는 어떤 단계에서도
수정하지 않는다. 구현과 실행은 분리하며, launch·Compose·실물 명령은 사용자가 단계별로
수동 실행할 수 있게 문서화한다. `control_system_root` 승격 전에는 운영 경로를 대상으로
실물 시험하지 않는다.
