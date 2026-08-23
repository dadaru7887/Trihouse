# Single Pinky Three-Temperature Simulation Design

## 목적

한 대의 이동 로봇 `PK_01`과 두 대의 로봇팔 `OMX_01`, `OMX_02`가 RViz와 Gazebo에서 실제 주문 시퀀스를 수행한다. `PK_01`은 상온·냉장·냉동 적재 지점을 방문하고, 해당 OMX로부터 물건을 적재 받은 뒤 포장대를 거쳐 충전/대기소로 복귀한다.

시뮬레이션 단계에서는 Vision, VLM/RL, `compose.ai_5080.yaml`을 실행하지 않는다. 시뮬레이션이 합격한 뒤 별도 설계 단계에서 실물 로봇과 Vision 모델을 같은 주문·작업 계약에 연결한다.

## 완료 기준

다음 조건을 모두 만족해야 시뮬레이션 단계를 완료한 것으로 본다.

1. Gazebo에 `PK_01`, `OMX_01`, `OMX_02`와 상온·냉장·냉동 창고, 포장대, 충전/대기소가 표시된다.
2. RViz에서 `PK_01`의 지도, TF, odometry, costmap, Nav2 계획·실행 경로를 확인할 수 있다.
3. 주문 입력 직후 영속화된 작업 시퀀스를 사람이 읽을 수 있는 형태로 출력한다.
4. `PK_01`은 넓은 구간에서 Nav2를 사용하고, 검증된 창고 협로에서는 규칙 기반 진입·정렬·이탈 절차를 사용한다.
5. `OMX_01`은 상온과 냉장, `OMX_02`는 냉동 작업을 담당한다.
6. OMX의 `ExecuteOmx` action 상태와 Gazebo 관절 동작이 같은 작업을 나타낸다.
7. 단일 상온, 단일 냉장, 단일 냉동 시나리오를 이 순서로 각각 3회 연속 성공시킨다.
8. 상온→냉장→냉동 순서의 다온도 주문 시나리오를 3회 연속 성공시킨다.
9. 매 회차는 주문 접수부터 포장대 작업, 충전/대기소 복귀와 최종 정지까지 검증한다.
10. 팀원이 문서의 PC별·터미널별 절차만으로 동일한 실행과 판정을 재현할 수 있다.
11. OMX는 파지 시작부터 Pinky 적재 완료까지 정확히 15초 동안 실행 상태를 유지하고, `picking`과 `loading` 진행 상태를 계속 보고한다.
12. 상온, 냉장, 냉동, 다온도 단계는 각각 3회 연속 성공할 때까지 반복하며, 한 단계를 합격하면 다음 단계로 자동 진행하지 않고 결과를 요약해 보고한다.
13. 단일 Pinky 검증 후 CPU, RAM, GPU와 Gazebo real-time factor를 측정하고, 결과에 따라 GUI 또는 headless 방식으로 `PK_01`, `PK_02` 두 대의 주문 실행을 검증한다.
14. 두 Pinky가 같은 병목에 접근하면 먼저 예약한 로봇만 진입하고 다른 로봇은 병목 밖의 승인된 대기 자세에서 정지하며, 소유 로봇이 완전히 이탈한 뒤에만 다음 로봇이 예약을 얻는다.
15. OMX 작업은 단순 navigate 결과가 아니라 Pinky의 검증된 `docked` 상태를 입력 gate로 받아 시작한다.

## 범위 분리

### 1단계: 시뮬레이션

현재 설계와 다음 구현 계획의 범위다. Docker 기반 Control Tower 서비스를 최대한 재사용하고, Gazebo·RViz·Nav2처럼 GUI, DDS 또는 하드웨어 가속이 필요한 ROS 프로세스만 호스트에서 실행한다. Vision은 명시적으로 비활성화한다.

### 2단계: 실물 및 Vision

1단계 합격 후 별도 설계와 계획으로 진행한다. `docs/guides`의 실물 bringup, namespaced Nav2, readiness, safety, runtime recovery 절차를 기준으로 실물 `PK_01`, `OMX_01`, `OMX_02`를 연결한다. Vision은 관측과 승인된 판단 입력만 제공하며 Nav2, safety 또는 OMX action 계약을 우회하지 않는다.

## 권장 아키텍처

기존 P0 주문·FMS·오케스트레이션을 정본으로 유지하고, `control_system`의 3온도 Gazebo world 및 OMX 관절 자산을 현재 시뮬레이션 bringup에 연결한다.

```text
주문 CLI/API
  -> FMS Gateway + MySQL
  -> OutboundPlanner (FEFO, ambient -> chilled -> frozen)
  -> 영속 Job / JobStep + 시퀀스 출력
  -> Job Runner / Executor Worker
     -> OMX ExecuteOmx action
     -> RMF/Pinky transport dispatch
  -> PK_01 Nav2 이동
  -> 창고 entry에서 규칙 기반 진입/정렬/이탈
  -> OMX 관절 적재 동작
  -> 포장대 Nav2 이동 및 handover/wait
  -> 충전/대기소 return_home
  -> 회차 검증기와 증거 bundle
```

대안인 과거 `control_system` 전체 스택 중심 구성은 현재 Control Tower 계약과 경로가 섞일 위험이 있어 사용하지 않는다. action 상태만 모사하는 방식은 Gazebo 로봇팔 동작을 증명하지 못하므로 사용하지 않는다.

## 실행 책임 경계

### Open-RMF 감사 결과와 유지 결정

현재 P0 runtime에서 Open-RMF가 실제로 담당하는 범위는 다음과 같다.

- Job Runner가 `mobile` step을 RMF channel로 dispatch한다.
- RMF Gateway Worker가 RMF task를 만들고 결과를 FMS step으로 되돌린다.
- Pinky EasyFullControl adapter가 RMF 명령을 `ExecuteTransport`로 변환한다.
- Pinky adapter가 유효한 map pose와 SOC로 fleet robot을 등록·갱신한다.
- telemetry가 무효가 되면 decommission하고 복구되면 recommission한다.
- RMF traffic schedule과 task dispatcher process가 bringup에 포함된다.

다음 항목은 DB/FMS 또는 정적 설정의 책임이며 RMF가 선택하지 않는다.

- Job, step, device, location과 reservation의 정본은 MySQL이다.
- Job Runner가 DB/FMS 상태를 읽어 mobile과 OMX를 배정한다.
- `CHARGER_BY_MOBILE`의 고정 pairing과 published map location을 사용해 충전기를 선택·검증한다.
- 포장대 reservation과 resource 충돌은 Gateway transaction이 강제한다.

다음 항목은 관련 모듈과 단위 테스트가 있지만 현재 P0 주문 runtime에 연결됐다고 볼 근거가 없다.

- `Nav2PathExecutor`를 통한 직접 schedule participant itinerary 등록
- Control Tower의 별도 RMF 예상 종료 SOC estimator를 주문 배터리 gate에 공급하는 경로
- `BottleneckCoordinator` 또는 `TrafficReservationBook`을 실제 Pinky 접근 제어에 연결하는 경로

따라서 이 설계는 Open-RMF를 mobile dispatch와 fleet lifecycle 경로로 유지하되, DB/FMS 책임을 RMF의 기능으로 표현하지 않는다. Open-RMF를 제거하면 mobile dispatch, cancellation/result bridge와 fleet lifecycle을 대체해야 하므로 이번 단계에서 제거하지 않는다. 반대로 미연결 estimator나 병목 coordinator가 이미 동작한다고 가정하지 않는다.

### Docker 계층

기존 Compose 정의와 `scripts/control_stack`을 재사용한다.

- MySQL: 주문, 재고 예약, job, job step, 상태와 결과의 정본
- FMS Gateway: 주문 접수와 job/step API
- Control Tower 서비스: 주문 계획과 실행 제어에 필요한 서버
- RMF API 및 Dashboard
- MediaMTX: 실물 단계와 같은 배포 구조를 유지하되 시뮬레이션 Vision 입력은 사용하지 않음

시뮬레이션에서 `compose.ai_5080.yaml`과 Vision worker는 금지한다. Docker healthcheck와 `control_stack doctor`가 서비스 준비 상태를 판정한다.

### 호스트 ROS 계층

- Gazebo: 3온도 창고 world, `PK_01`, `OMX_01`, `OMX_02`
- RViz: `PK_01` Nav2 및 상태 시각화
- Open-RMF core와 bridge
- `PK_01` namespaced Nav2, fleet gateway, safety, readiness, battery/status 노드
- `/omx_01/execute`, `/omx_02/execute` action server와 Gazebo 관절 동작 adapter
- Control Tower job runner와 executor worker

ROS namespace와 canonical device ID를 분리한다.

| 장치 | Canonical ID | ROS namespace |
| --- | --- | --- |
| 이동 로봇 | `PK_01` | `/pinky_01` |
| 상온·냉장 OMX | `OMX_01` | `/omx_01` |
| 냉동 OMX | `OMX_02` | `/omx_02` |

## 주문과 작업 시퀀스

주문은 상품 코드와 수량을 입력으로 받는다. `OutboundPlanner`는 재고 lot을 FEFO로 선택하고 실제 배정된 온도 구역만 `ambient`, `chilled`, `frozen` 순으로 묶는다. 같은 온도 구역의 여러 상품은 한 번의 방문으로 합친다.

각 온도 bundle은 다음 의존 관계를 가진다.

1. 해당 OMX `prepare`
2. `PK_01`의 창고 적재 지점 `navigate`
3. Pinky readiness와 OMX readiness를 모두 요구하는 `load`

`navigate` step의 성공은 Pinky fleet node가 Nav2 접근, 규칙 기반 진입, 도크 목표 pose·yaw와 완전 정지를 검증한 뒤 발행한 `docked` event를 포함해야 한다. Control Tower의 load gate는 mobile step terminal state만 보지 않고 동일 job/step/robot/dock identity의 최신 `docked` event를 확인한다. 이 event가 없거나 stale하거나 다른 도크를 가리키면 OMX `picking`을 시작하지 않는다.

모든 온도 bundle이 끝나면 다음 단계를 수행한다.

1. 포장대 `navigate`
2. `handover`
3. 작업자 완료 또는 시뮬레이션 승인 입력을 기다리는 `wait`
4. 배정된 충전/대기소 `return_home`

주문 명령은 반환된 job ID뿐 아니라 `step_no`, action, executor, target, dependency, assigned device를 표 또는 JSON으로 출력한다. 출력 내용과 DB에 영속화된 step은 정확히 일치해야 한다.

## 이동 제어

Nav2는 창고 entry, 포장대, 충전/대기소까지의 전역·국소 경로를 담당한다. Safety Supervisor만 최종 속도 명령을 소유한다.

창고 내부의 검증된 협로에서는 실물 가이드와 같은 경계를 사용한다.

1. Nav2로 entry pose에 접근한다.
2. Nav2 goal을 완료 또는 취소하고 완전히 정지한다.
3. entry 자세 허용 오차를 검증한다.
4. 지도 revision에 연결된 규칙 기반 profile로 진입·정렬한다.
5. 도크 도착과 정지를 검증한 후 OMX load를 허용한다.
6. 규칙 기반 profile로 entry까지 이탈한다.
7. Nav2 제어권을 복구한다.

임의 좌표를 주문 또는 Vision이 직접 전달하지 않는다. 좌표와 협로 동작은 published map revision 및 versioned profile에서만 읽는다.

## OMX 시뮬레이션

`OMX_01`과 `OMX_02`는 실물과 동일한 `ExecuteOmx` action 계약을 제공한다. 각 action phase는 Gazebo 관절 궤적과 연결한다.

- `prepare`: 홈 자세에서 상품 접근 준비 자세로 이동
- `picking`: 선반 측 접근과 그리퍼 닫기. 7.5초 동안 진행한다.
- `loading`: Pinky 적재 위치로 이동하고 그리퍼를 연다. 7.5초 동안 진행한다.
- terminal success: 관절이 안전 자세로 복귀하고 action result가 성공
- cancel/failure: 움직임을 정지하고 action result에 reason code 기록

`picking` 시작 시각부터 `loading` 완료 시각까지의 시뮬레이션 시간은 정확히 15초다. wall clock이 아니라 ROS simulation clock을 정본으로 사용하므로 Gazebo real-time factor가 변해도 작업 의미는 바뀌지 않는다. 7.5초 경계와 총 15초는 공통 설정에서만 정의하며 OMX별 코드에 중복하지 않는다.

Action server는 terminal result만 보내지 않고 실행 중 1 Hz 이상의 feedback heartbeat를 발행한다. feedback에는 다음 필드를 포함한다.

- canonical OMX ID와 주문/job/step/handover group ID
- 현재 phase: `preparing`, `picking`, `loading`, `returning`, `succeeded`, `failed`, `cancelled`
- phase 시작 시각, phase 경과 시간, 전체 경과 시간
- 0~100 범위의 전체 진행률
- 현재 대상 상품과 배정된 Pinky ID
- 최신 joint-state timestamp와 trajectory tracking 상태

Control Tower는 이 feedback을 실행 중 상태로 계속 추적하고 job step 관측 API와 로그에 반영한다. heartbeat가 2초 넘게 끊기거나 phase가 역행하거나 15초 종료 전에 성공 result가 오면 해당 회차를 실패시킨다. `picking → loading` 전이와 terminal result는 회차 증거 bundle에 보존한다.

시뮬레이션은 인식 결과를 가장하지 않는다. 상품/파지 성공은 결정론적 scenario fixture와 action 상태로 주입하며 Vision topic이나 모델 process는 실행하지 않는다.

## 오류 처리와 반복 안정성

회차마다 고유 주문 ID와 idempotency key를 사용한다. 동일 step 재시도는 objective가 같을 때만 허용하며, 목적지가 바뀌거나 취소된 step은 replan을 요구한다.

다음 조건은 즉시 회차 실패다.

- Docker 또는 ROS readiness gate 실패
- `/pinky_01` TF, odometry, map revision, Nav2 lifecycle 이상
- 다른 이동 로봇이 활성 graph나 Gazebo world에 존재
- Vision/AI process가 실행됨
- 잘못된 OMX 배정
- 작업 시퀀스와 DB step 불일치
- Nav2와 규칙 기반 제어권 중복
- OMX action과 관절 terminal state 불일치
- step timeout, dead-letter, 중복 dispatch 또는 순서 위반
- 포장대 단계를 생략하거나 충전/대기소에서 정지하지 않음
- Pinky `docked` event 없이 OMX가 `picking`을 시작함

한 회차 실패 후 다음 회차를 성공 횟수에 더하지 않는다. 원인을 수정하고 스택을 규정된 clean-start 상태로 되돌린 뒤 해당 시나리오의 연속 성공 횟수를 0부터 다시 센다. 단계 runner는 합격할 때까지 같은 시나리오를 반복할 수 있지만, 실패 원인이 해소되지 않은 상태에서 무한 재주문하지 않는다. 실패 증거와 진단 결과를 남기고 clean-start gate가 다시 통과한 뒤에만 다음 attempt를 만든다.

## 검증 시나리오

실행 순서는 고정한다.

1. 상온 단일 주문 3회 연속
2. 냉장 단일 주문 3회 연속
3. 냉동 단일 주문 3회 연속
4. 상온·냉장·냉동 상품을 포함하는 다온도 주문 3회 연속

각 단계는 독립 실행 단위다. 한 단계가 3회 연속 성공하면 runner는 정지하고 다음 요약을 출력한다.

- attempt 수, 성공·실패 수와 최종 연속 성공 수
- 각 주문 ID, job ID, 시작·종료 시각과 소요 시간
- 생성된 step 순서와 실제 terminal 상태
- 사용한 Pinky/OMX, Nav2와 규칙 기반 이동 횟수
- OMX `picking`/`loading` heartbeat 수와 15초 duration 판정
- 실패가 있었다면 reason code, 복구 조치와 증거 경로
- 단계 합격 여부와 다음 단계 실행 명령

다음 단계는 요약 보고 후 별도 명령으로 시작한다. 이를 통해 상온 합격, 냉장 합격, 냉동 합격, 다온도 합격 시점마다 작업을 끊고 상황을 검토할 수 있다.

각 회차 검증기는 다음 증거를 한 디렉터리에 저장한다.

- 주문 request/response
- 생성된 시퀀스와 DB job/step snapshot
- OMX action feedback/result와 joint-state 요약
- Nav2 goal/result, 규칙 기반 enter/exit event
- Pinky pose, readiness, safety, battery/status의 시작·종료 snapshot
- 포장대와 충전/대기소 도착 판정
- 실행 중인 ROS node 및 Docker service 목록
- Vision/AI 미실행 판정
- 회차별 PASS/FAIL과 reason code

단위 테스트는 planner, step dependency, device assignment, 규칙 기반 profile, OMX phase와 trajectory mapping을 검증한다. 통합 테스트는 주문 하나의 전 구간을 검증한다. 단일 Pinky 단계 합격은 실제 Gazebo·RViz ROS graph에서 얻은 12개 연속 성공 회차의 증거로만 판정하며, 전체 시뮬레이션 합격에는 이어지는 두 Pinky 병목·주문 검증 3회도 필요하다.

## 단일 Pinky 이후 두 Pinky 단계

네 주문 단계가 모두 합격하면 같은 실행에서 수집한 자원 지표를 요약한다.

- 전체 및 process별 CPU 사용률
- RAM과 swap 최대 사용량
- GPU 사용률과 VRAM
- Gazebo real-time factor
- ROS callback·action heartbeat 지연과 missed deadline

GUI가 켜진 2대 검증은 관측 구간의 CPU 75% 이하, RAM 80% 이하, swap 증가 없음, GPU VRAM 85% 이하, Gazebo real-time factor 0.8 이상을 모두 만족할 때 사용한다. 하나라도 넘으면 Gazebo server와 ROS graph는 그대로 두고 Gazebo GUI와 RViz를 끈 headless 방식으로 2대 작업을 검증한다. 임계값과 실제 측정치를 단계 요약에 함께 기록한다.

두 Pinky 검증은 다음을 수행한다.

1. `PK_01`과 `PK_02`가 서로 반대편에서 같은 병목으로 접근한다.
2. 원자적 lease를 먼저 얻은 로봇만 병목에 진입한다.
3. 다른 로봇은 병목 footprint 밖의 versioned waiting pose에서 속도 0으로 대기한다.
4. 소유자는 병목을 완전히 벗어난 pose가 검증된 뒤 lease를 해제한다.
5. 대기자는 해제를 관측하고 lease를 얻은 뒤 통과한다.
6. 소유 순서를 바꿔 같은 검증을 반복한다.
7. 두 로봇이 포함된 주문 수행을 3회 연속 성공시킨다.

DB reservation table을 lease의 정본으로 사용해 process 재시작 후에도 소유권이 남도록 한다. Gateway transaction은 한 병목에 활성 holder가 하나뿐임을 강제한다. RMF schedule은 경로 계획과 fleet 실행을 유지하지만, 병목 진입의 최종 규칙 gate는 DB lease와 robot pose를 함께 확인한다.

예약을 얻지 못한 로봇은 현재 자세에서 임의로 멈추지 않는다. 병목에 너무 가까워 footprint를 침범하지 않도록 published map의 waiting pose까지 접근한 뒤 정지한다. lease heartbeat가 끊겨도 즉시 탈취하지 않고 expiry와 실제 holder pose를 모두 확인한다. E-stop 또는 safety hold 중인 holder의 lease는 운영자 확인 없이 해제하지 않는다.

## 운영 문서 산출물

시뮬레이션 합격 후 `docs/guides`에 팀 재현용 runbook을 작성한다. 문서는 실제 성공한 명령과 경로만 사용하며 예시용 가상 경로를 넣지 않는다.

문서는 시뮬레이션 runbook과 실물·Vision runbook으로 나눈다. 시뮬레이션 runbook은 1단계 합격 직후 확정한다. 실물·Vision runbook은 실제 네트워크, 카메라, 모델과 로봇 연결을 검증한 뒤 확정하며 시뮬레이션 값으로 실물 설정을 추정하지 않는다.

실물·Vision 문서는 다음 PC 역할을 기준으로 구성한다.

| 장비 | 주요 책임 |
| --- | --- |
| 4060 서버 PC | MySQL, FMS/Control Tower, MediaMTX, 중앙 상태·로그, 영상 녹화 저장소, 필요 시 RMF core/bridge |
| 5080 서버 PC | 중앙 Vision/VLM/RL 모델 실행과 모델 자산 관리; 시뮬레이션 단계에서는 실행 금지 |
| `OMX_02` 서버 PC | `/omx_02` ROS action과 로봇팔 bringup, 손목 영상의 로컬 추론; 원본/운영 영상은 4060 서버 PC MediaMTX·녹화 저장소로 전송 |
| `OMX_01` 일반 PC | `/omx_01` ROS action과 로봇팔 bringup, 카메라 송출 및 검증된 OMX 실행 runtime |
| Pinky onboard PC | `/pinky_01` namespaced Nav2, 센서, safety, fleet gateway와 상태 발행 |

각 PC 장에는 Docker/Compose 사용 범위와 호스트에서 직접 실행해야 하는 ROS/hardware process를 구분한다. Docker가 가능한 FMS, 데이터베이스, MediaMTX, 모델 서비스, OMX 상위 worker는 image tag와 compose profile로 재현한다. 장치 드라이버, Gazebo/RViz, DDS discovery 점검처럼 호스트 접근이 필요한 과정은 terminal 절차로 제공한다.

문서 구조는 다음과 같다.

1. 지원 OS, Docker/Compose, ROS 배포판, Gazebo, GPU/GUI 요구사항
2. 4060, 5080, OMX_02 서버, OMX_01 일반 PC, Pinky의 역할과 Docker/호스트 ROS 책임 경계
3. 각 PC의 유선·Wi-Fi 연결, 검증된 SSID, 고정/예약 IP, subnet, gateway, ROS 전용 interface와 인터넷 interface
4. Fast DDS Discovery Server 주소, `ROS_DOMAIN_ID`, RMW와 discovery 환경 및 PC 간 ping/port/topic 점검
5. 저장소 clone, submodule revision, Docker image pull/build, ROS workspace build
6. PC별 `.env`, compose profile, secret 주입과 volume 경로
7. PC별 Docker 기동 순서와 healthcheck
8. 각 PC와 Pinky의 터미널 번호별 source, export, bringup 명령 및 foreground/background 책임
9. Gazebo/RViz 또는 실물 robot/OMX/카메라/Vision 개수와 namespace 확인
10. OMX_02 로컬 추론과 4060 영상 저장 경로의 동시 확인
11. 주문 입력, 생성 시퀀스, OMX 실시간 phase, 시나리오 실행 명령
12. 단계별 PASS/FAIL 판정, 중간 요약과 증거 위치
13. 정상 종료, stale process 정리, DB/예약 상태 복구
14. 증상별 진단과 재시작 절차

Wi-Fi SSID, IP, interface 이름과 물리 경로는 실제 장비에서 확인한 값만 문서에 확정한다. 현재 실물 가이드에 기록된 과거 네트워크 값은 검증 없이 복사하지 않는다. runbook 검증은 깨끗한 shell과 재부팅 직후 상태에서 문서의 명령을 순서대로 실행하는 방식으로 수행한다. 개인 shell alias, 기존 background process, 미기록 환경 변수 또는 작성자만 아는 수동 GUI 조작에 의존하면 실패로 본다. 문장은 명확하고 간결하게 유지하되 명령, 기대 출력, PASS 조건과 실패 시 다음 행동은 생략하지 않는다.

## 실물 단계로의 이행 조건

단일 Pinky 12개 회차, 두 Pinky 병목·주문 3회와 runbook 재현이 모두 합격해야 실물·Vision 단계 설계를 시작한다. 실물 단계는 다음 불변 조건을 유지한다.

- 동일한 canonical device ID와 주문/step schema
- 동일한 온도별 OMX 배정
- 동일한 Nav2와 규칙 기반 제어권 경계
- 동일한 FMS idempotency와 recovery 규칙
- Safety Supervisor의 최종 속도 권한

Vision 모델은 카메라 입력으로 상품/사람/파지 상태를 관측하고 승인된 결과만 action workflow에 전달한다. raw velocity, 임의 Nav2 pose 또는 무검증 OMX joint command를 발행하지 않는다.

카메라별 책임은 다음과 같이 고정한다.

- Pinky 탑재 카메라: 사람과 장애물을 감지해 safety/관측 event를 발행한다. Nav2 costmap 또는 Safety Supervisor와의 결합은 별도 실물 설계에서 검증한다.
- OMX 손목 카메라: OpenCV로 상품 QR을 읽고 주문의 예상 상품/lot identity와 일치하는지 검증한다.
- 고정 카메라: OMX 작업 자세와 진행을 관측하고 사람 접근을 감지한다.

어떤 Vision 결과도 단독으로 motion command를 발행하지 않는다. 사람 감지는 보수적으로 safety hold를 요청하고, QR 불일치는 OMX `picking` 전에 작업을 보류하며, 고정 카메라의 작업 이상은 해당 OMX action을 실패 또는 운영자 검토 상태로 전환한다.
