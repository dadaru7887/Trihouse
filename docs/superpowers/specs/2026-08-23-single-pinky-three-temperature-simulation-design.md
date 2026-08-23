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
- `pick/load`: 선반 측 접근, 그리퍼 닫기, Pinky 적재 위치로 이동, 그리퍼 열기
- terminal success: 관절이 안전 자세로 복귀하고 action result가 성공
- cancel/failure: 움직임을 정지하고 action result에 reason code 기록

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

한 회차 실패 후 다음 회차를 성공 횟수에 더하지 않는다. 원인을 수정하고 스택을 규정된 clean-start 상태로 되돌린 뒤 해당 시나리오의 연속 성공 횟수를 0부터 다시 센다.

## 검증 시나리오

실행 순서는 고정한다.

1. 상온 단일 주문 3회 연속
2. 냉장 단일 주문 3회 연속
3. 냉동 단일 주문 3회 연속
4. 상온·냉장·냉동 상품을 포함하는 다온도 주문 3회 연속

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

단위 테스트는 planner, step dependency, device assignment, 규칙 기반 profile, OMX phase와 trajectory mapping을 검증한다. 통합 테스트는 주문 하나의 전 구간을 검증한다. 최종 합격은 실제 Gazebo·RViz ROS graph에서 얻은 12개 연속 성공 회차의 증거로만 판정한다.

## 운영 문서 산출물

시뮬레이션 합격 후 `docs/guides`에 팀 재현용 runbook을 작성한다. 문서는 실제 성공한 명령과 경로만 사용하며 예시용 가상 경로를 넣지 않는다.

문서 구조는 다음과 같다.

1. 지원 OS, Docker/Compose, ROS 배포판, Gazebo, GPU/GUI 요구사항
2. PC 역할과 Docker/호스트 ROS 책임 경계
3. 저장소 clone, submodule, 이미지 build, ROS workspace build
4. 공통 환경 변수와 `.env` 설정
5. 터미널별 기동 순서와 각 터미널의 foreground/background 책임
6. Gazebo/RViz 및 robot/OMX 개수 확인
7. 주문 입력, 생성 시퀀스 확인, 시나리오 실행 명령
8. 회차 PASS/FAIL 판정과 증거 위치
9. 정상 종료, stale process 정리, DB/예약 상태 복구
10. 증상별 진단과 재시작 절차

runbook 검증은 깨끗한 shell에서 문서의 명령을 순서대로 실행하는 방식으로 수행한다. 개인 shell alias, 기존 background process, 미기록 환경 변수에 의존하면 실패로 본다.

## 실물 단계로의 이행 조건

12개 시뮬레이션 회차와 runbook 재현이 모두 합격해야 실물·Vision 단계 설계를 시작한다. 실물 단계는 다음 불변 조건을 유지한다.

- 동일한 canonical device ID와 주문/step schema
- 동일한 온도별 OMX 배정
- 동일한 Nav2와 규칙 기반 제어권 경계
- 동일한 FMS idempotency와 recovery 규칙
- Safety Supervisor의 최종 속도 권한

Vision 모델은 카메라 입력으로 상품/사람/파지 상태를 관측하고 승인된 결과만 action workflow에 전달한다. raw velocity, 임의 Nav2 pose 또는 무검증 OMX joint command를 발행하지 않는다.
