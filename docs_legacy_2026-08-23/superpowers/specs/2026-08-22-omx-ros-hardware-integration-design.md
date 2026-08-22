# OMX ROS Hardware Integration Design

## Scope

`origin/usang/omx`의 LeRobot/ACT/카메라/파지 판정 코드를 현재 관제 흐름에 통합한다.
OMX PC는 Gateway 작업을 직접 claim하지 않는다. AI-Server-4060의 중앙 Executor가
Gateway의 유일한 OMX/FMS claim 소유자이며 DB `device_id`로 ROS Action을 선택한다.

## Identity and mapping

- DB 및 명령 ID: `OMX_01`, `OMX_02`
- ROS namespace: `/omx_01`, `/omx_02`
- Action endpoint: `/omx_01/execute`, `/omx_02/execute`
- 상품 DB 코드와 ACT policy key는 `config/omx_product_policies.yaml`에서 1:1 매핑한다.
- 장비별 온도 구역은 `devices.capabilities.temperature_zones`에서 조회한다.
- 코드에 장비 ID, serial path, camera path, calibration ID, 서버 URL을 하드코딩하지 않는다.

## Parallel workflow

한 온도 구역마다 `arm/prepare`와 `mobile/navigate`는 같은 선행 dependency를 가져
동시에 dispatch된다. `fms/load`는 두 step이 모두 성공해야 실행된다. 첫 실물 버전의
`prepare`는 USB, calibration, camera, policy cache, home pose를 확인할 뿐 물건을
미리 들지 않는다. Pinky가 docking하고 OMX가 준비된 뒤 `START_LOAD`가 전체 ACT
pick-and-place를 실행한다. OMX의 파지, 해제, policy 완료 결과가 품목별
`LOAD_CONFIRMED` 증거가 되고 그 뒤 Pinky가 포장대로 이동한다.

## Dependency semantics

생산 step은 `input.dependencies` 배열을 반드시 가진다. JobRunner는 pending step 중
모든 dependency가 succeeded인 step을 한 주기에 모두 dispatch한다. Gateway도 낮은
`step_no` 전체가 아니라 명시된 dependencies만 같은 transaction에서 검증한다.
누락되거나 존재하지 않는 dependency, 자기 자신 또는 뒤쪽 step dependency는
dispatch를 거부한다.

## ROS interface

`trihouse_interfaces/action/ExecuteOmx.action`은 JSON을 운반한다.

- Goal: `string command_json`
- Result: `bool success`, `uint16 code`, `string result_json`
- Feedback: `string event_json`

JSON은 `command_uuid`, `kind`, `job_id`, `job_step_id`, `assignment_revision`, `omx_id`,
`temperature_zone`, `items`를 포함한다. 동일 `command_uuid`는 실제 동작을 반복하지
않고 저장된 결과를 재생한다.

## Process and container boundary

각 OMX PC의 역할 Compose는 두 서비스를 실행한다. ROS bridge는 Ubuntu 24.04,
ROS 2 Jazzy, Python 3.12에서 Action server를 제공한다. LeRobot worker는 Python 3.10,
PyTorch, LeRobot을 사용하고 USB serial과 카메라를 단독 소유한다. 두 서비스는 같은
호스트의 `/run/trihouse-omx/worker.sock` Unix socket으로 NDJSON 명령과 결과를
교환한다. ROS bridge만 host network를 사용하며 LeRobot worker는 필요한 장치만
명시적으로 받는다.

## Simulation boundary

Simulation 구현은 `tests/simulation/omx`에만 둔다. Hardware와 같은
`ExecuteOmx.action`, endpoint, JSON, 상태명, 오류 코드를 사용하되 모터를 움직이지
않는다. Hardware 이미지에는 simulation 모듈을 넣지 않는다.

## Removed paths

- production `OmxProtocolSimulator` 주입
- production `mock_inputs.py`
- OMX PC의 Gateway polling `job_loop.py`
- hardcoded `OMX_01` fallback과 `OMX_DELIVER_MOCK`
- `CargoState`, `SetCargoLock`, `/trihouse/cargo/state`, cargo sensor 조건
- 진단만 하는 hardware adapter skeleton

정적 상품 속성인 `inventory_lots.unit_weight_kg`는 센서 데이터가 아니므로 유지한다.
적재 원장과 품목별 `LOAD_CONFIRMED`도 유지한다.

## Safety and verification

명령의 `omx_id`가 로컬 `DEVICE_ID`와 다르면 모션 전에 거부한다. 정책/카메라/serial
준비 실패, stale assignment, 알 수 없는 상품, zone mismatch는 fail-closed한다.

## 혼합 온도 주문 배정

한 Job에는 Pinky 한 대만 배정한다. `assignment.mobile_id`는 모든 창고 이동과
포장대·충전소 복귀에서 바뀌지 않는다. 필요한 OMX 작업셀은 방문 순서대로
`assignment.omx_ids`에 기록하고, 첫 작업셀은 기존 소비자 호환을 위해
`assignment.omx_id`에도 기록한다.

구역은 `ambient → chilled → frozen` 순서이며 주문에 없는 구역은 건너뛴다. 각
arm step의 `input.omx_id`와 `assigned_device_id`가 실제 명령 대상을 결정한다.
Pinky 한 대, 필요한 OMX 전체, 포장대와 충전소는 첫 이동 전에 한 트랜잭션으로
예약한다. 하나라도 사용할 수 없으면 부분 출발하지 않고 Job을 queued로 유지한다.
검증 순서는 no-motion Action, OMX_01 단일 품목, OMX_02 냉동 단일 품목, 수량 반복,
두 팔 동시 명령, 전체 주문 흐름이다.
