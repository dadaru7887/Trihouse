# Trihouse P0 시뮬레이션 검증 기록

- **작성일:** 2026-08-16
- **계획:** `docs/superpowers/plans/2026-08-15-control-tower-integration.md`
- **설계:** `docs/superpowers/specs/2026-08-15-control-system-trihouse-integration-design.md` (commit `8b2466b6`)
- **검증 대상 commit:** Task 10 커밋 직전 `6241755b` + 본 문서 커밋

## 1. 무엇을 실행했고 무엇을 아직 실행하지 못했는가

이 문서는 **실제로 돌린 것만** 기록한다. 아래 2절은 이 저장소에서 통과를
확인한 자동 검증이고, 3절은 실행 조건이 갖춰지지 않아 **미실행**으로 남은
항목이다. 미실행 항목을 통과로 적지 않는다.

이 워크스테이션에서 확인한 조건:

- MySQL 8.4 테스트 인스턴스가 `127.0.0.1:3307`에서 동작한다.
- ROS 2 Jazzy가 `/opt/ros/jazzy`에 설치되어 있다.
- Flutter/Dart 툴체인이 설치되어 있다.
- **Docker 데몬에 접근 권한이 없다** (`permission denied ... /var/run/docker.sock`).
  따라서 `./scripts/control_stack up` 으로 스택 전체를 기동하는 절차와
  Gazebo/Nav2/RMF 실제 모션 관측은 실행하지 못했다.

## 2. 실행하고 통과한 검증

### 2.1 실행 환경

```bash
source /opt/ros/jazzy/setup.bash
export PYTHONPATH="/tmp/trihouse-task6-venv/lib/python3.12/site-packages:$PYTHONPATH"
export FMS_DB_HOST=127.0.0.1 FMS_DB_PORT=3307
export FMS_DB_USER=fms_gateway FMS_DB_PASSWORD=test_gateway_password
export FMS_DB_DATABASE=trihouse_fms
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
```

### 2.2 명령과 결과

| 명령 | 결과 |
|---|---|
| `pytest -q db/tests control_tower/tests trihouse_rmf_bridge/test trihouse_omx_adapter/tests trihouse_pinky/test vision_edge/tests media tests --ignore=trihouse_rmf_bridge/test/test_office_service.py` | **576 passed**, 8 subtests passed |
| `cd fms_gateway && pytest -q tests` (실제 MySQL) | **271 passed**, 1 skipped |
| `cd control_ui/rmf_control_ui && flutter test` | **211 passed** |
| `cd control_ui/rmf_control_ui && flutter analyze` | **No issues found** |
| `./scripts/control_stack doctor --mode simulation` | 실행됨, 종료 코드 1 (아래 3절 참고) |

첫 명령에는 `tests/e2e` 24건이 포함되어 있다. 위 두 pytest 명령은 같은 테스트
MySQL 인스턴스를 초기화하므로 **동시에 돌리면 안 된다**. 병렬로 실행하면 한쪽이
상대의 스키마를 지워 `Unknown database 'trihouse_fms'`로 깨진다. 순차로 돌린
결과가 위 표다.

`trihouse_rmf_bridge/test/test_office_service.py`는 빌드된 ROS 워크스페이스에
서비스가 떠 있어야 하는 launch 통합 시험이라 이 실행에서 제외했다. 이는
P0 이전부터 있던 조건이며 본 계획으로 바뀌지 않았다.

### 2.3 신선 seed 여섯 주문 (A–F)

`tests/e2e/test_trihouse_test_01_orders.py`가 A–F 각각에 대해
`db/schema_mysql.sql` + `db/seed_dev.sql`을 다시 만들고, UI가 쓰는 것과 같은
공개 `POST /api/v1/orders`로 제출한 결과다.

| 예시 | 요청 | HTTP | 구역 순서 | 요청/가능/미충족 |
|---|---|---|---|---|
| A | 전 구역 | 201 | ambient → chilled → frozen | 3 / 3 / 0 |
| B | 냉장·냉동 (상온 없음) | 201 | chilled → frozen | 2 / 2 / 0 |
| C | 전량 출고 + 재고 부족 | 409 `INSUFFICIENT_STOCK` | — | Job·Step·예약 **0건 생성** |
| D | critical | 201 | ambient → frozen | 2 / 2 / 0 |
| E | 부분 출고 허용 | 201 | chilled → frozen | 4 / 3 / **1** |
| F | 상온 2품목·Dock 1회 | 201 | ambient | 2 / 2 / 0 |

추가로 확인한 것:

- 한 구역은 선반 수와 무관하게 Pinky Dock 방문이 **한 번**이다.
- F 주문 한 건을 배정 → 품목별 적재 시도 → 작업자 완료 → 포장 Dock 해제 →
  고정 충전기 복귀까지 끝냈다. 모든 적재 시도가 `LOAD_CONFIRMED`로 남았고,
  `return_home` 단계가 정확히 하나 생성되며 배정된 충전기를 가리킨다.
- 같은 `Idempotency-Key`로 작업자 완료를 다시 부르면 첫 응답을 그대로
  돌려주고 재고를 두 번 확정하지 않는다.

### 2.4 두 Pinky 동시 운용

`tests/e2e/test_two_pinky_traffic.py` 결과:

- 동시 주문 두 건이 서로 다른 Pinky·OMX·포장 Dock으로 배정된다.
- `PK_01 → TRIHOUSE-TEST-01-CHG-01`, `PK_02 → TRIHOUSE-TEST-01-CHG-02` 고정이
  실제 MySQL 트랜잭션에서 유지된다.
- 이미 예약된 로봇을 두 번째 Job이 가져가면 `ResourceUnavailable`로 막힌다.
- 경로가 등록되기 전에는 어떤 로봇도 이동 승인을 받지 못한다.
- 마주 오는 두 itinerary는 나중 등록분이 보류되고, 앞 로봇이 경로를 반납한
  뒤에 승인된다.
- dispatch payload가 fleet과 robot을 모두 고정한다. RMF는 다른 Pinky로
  대체 배정할 수 없다.
- bottleneck은 먼저 도착한 로봇이 이기고 `critical`이 순서를 바꾸지 못한다.
  15초를 넘겨야 우회를 계산하고, 유효한 우회가 없으면 계속 기다린다.
- 구역 안에서 비상 정지하면 lease가 유지된다.
- 두 로봇이 동시에 stubborn override handle을 쥐지 못한다.

### 2.5 OMX 계약 시뮬레이션

`trihouse_omx_adapter/tests` 결과:

- `OMX_01`, `OMX_02` 두 인스턴스가 각자의 `omx_id` 명령만 실행한다.
- prepare 명령이 `PREPARING → PICKING → OMX_READY`를 낸다.
- `command_uuid` 재전송은 첫 이벤트 열을 그대로 돌려준다.
- 오래된 `assignment_revision`은 `STALE_ASSIGNMENT`로 거절된다.
- 필수 필드가 하나라도 없으면 상태가 전혀 바뀌지 않는다.
- 물리 OMX ROS endpoint를 발행하지 않는다.

### 2.6 ACT와 카메라

- `config/act.simulation.yaml`의 repo/revision/profile은 모두 `UNCONFIGURED`,
  mode는 `deterministic_fake`다. 로더가 `real_motion_enabled = False`를 낸다.
- fake episode가 `OBSERVE → POLICY → GRASP → VERIFY → HANDOVER`를 내고
  lineage를 `fake-act/p0-v1`로 기록한다.
- hardware mode는 세 값이 모두 실제 값일 때만 열린다.
- 카메라 여섯 대를 등록만 하고 연결하지 않는다. `map_pose`는 전부 `null`이며
  P1 캘리브레이션 전까지 좌표를 만들지 않는다.
- Pinky 영상은 OMX 적재 증거로 선택되지도, 허용되지도 않는다.
- 적재 결과는 `LOAD_CONFIRMED` / `DROP_DETECTED` / `LOAD_UNCERTAIN` /
  `GRASP_RETAINED` 네 가지뿐이다.

### 2.7 비상 fixture 두 건

`tests/e2e/test_emergency_fixtures.py` 결과:

| fixture | 여는 카메라 | 즉시 보류 |
|---|---|---|
| 1. 이동 중 Pinky 전도 (`PK_01`) | `CAM-PK-01` | 예 |
| 2. 창고 내 전도 (`WH-FRZ-01`) | `CAM-FIXED-02` | 예 |

- `비상경보 발령`은 사건을 확정하고 보류를 유지한다.
- `작업 계속 진행`은 작업자와 사유를 남기고 보류를 풀며, **같은 Job**의
  Nav2 경로를 다시 계산하고 RMF 일정을 다시 등록한다.
- 대화상자를 닫으면 상태도 감사 기록도 바뀌지 않는다.
- 재개가 실제로 이전 경로 해시를 반납하고 새 해시를 등록하는 것까지 확인했다.

### 2.8 UI 경계

- `flutter analyze` 무경고.
- 운영 화면이 Nav2 전역/지역 경로와 실제 이동 궤적을 1차로 그리고,
  내부 bootstrap graph 위젯은 존재하지 않는다.
- RMF 예정 궤적은 `RMF 진단` 토글을 켰을 때만 나타난다.
- 카메라 여섯 장이 등록 카드로만 있고, 사건이 연 카메라만 디코딩한다.
- 적재 성공은 자동으로 닫히고 드랍은 열린 채로 남는다.

## 3. 미실행으로 남은 항목

아래는 **통과하지 않았다**. 조건이 갖춰지면 그때 실행하고 이 문서를 갱신해야
한다.

0. **스택이 두 층으로 나뉜다.** `up` 은 Docker 층(MySQL, Gateway, MediaMTX,
   RMF API/Dashboard, control_ui)만 올린다. RMF core, Gazebo, Nav2, fleet
   adapter, OMX 시뮬레이터, RMF dispatch worker 는 rclpy 와 DDS 가 필요해
   호스트에서 돈다. `control_stack ros` 또는
   `control_tower/bringup/p0_simulation_bringup.sh` 가 그 층을 한 번에 띄운다.
   수동 절차는 `docs/runbooks/2026-08-16-p0-manual-test.md` 에 있다.
1. **`./scripts/control_stack up --mode simulation --project trihouse_test_01`
   전체 기동과 `doctor` 실측.** 이 호스트에 Docker 데몬 접근 권한이 없다.
   `doctor`를 실행한 실제 출력은 다음과 같다. 열한 개 필수 항목을 모두
   보고하지만 스택이 떠 있지 않으므로 전부 `absent`이고 종료 코드는 1이다.

   ```json
   {
     "act_contract": "deterministic_fake",
     "ai_5080_started": false,
     "checks": {
       "control_tower": "absent", "control_ui": "absent",
       "fms_gateway": "absent", "gazebo": "absent",
       "mediamtx": "absent", "mysql": "absent",
       "nav2:PK_01": "absent", "nav2:PK_02": "absent",
       "omx:OMX_01": "absent", "omx:OMX_02": "absent",
       "rmf_schedule": "absent"
     },
     "healthy": false,
     "mode": "simulation",
     "project": "trihouse_p0"
   }
   ```

   CLI
   계약(서브커맨드, 단일 Compose project, 기동 순서, 필수 점검 항목,
   `compose.ai_5080.yaml` 제외, headless 기본값, `STARTUP_ORDER`의 모든
   서비스가 compose에 정의되어 있음)은 `tests/test_control_stack_cli.py`
   13개로 검증했지만, 실제 컨테이너 기동은 미실행이다.
2. **Gazebo/Nav2/Open-RMF 실제 모션 관측.** 두 Pinky가 실제로 경로를 따라
   움직이는 장면, 실제 costmap, 실제 RMF 충돌 해소는 스택 기동이 필요하다.
   Task 7이 만든 계약(경로 계산 후 등록, 승인 전 무이동, 재계획 시 보류와
   override 반납)은 단위 수준에서 결정적으로 검증했다.
3. **비상 화면 스크린샷.** UI 위젯 동작은 `flutter test`로 검증했으나 실제
   브라우저 화면 캡처는 스택 기동이 필요하다.
4. **artifact/log URI.** P0는 fixture 이벤트 클립만 등록하며, 실제 클립이
   생성되려면 MediaMTX가 떠 있어야 한다. 카탈로그 로직
   (`media/event_catalog/catalog.py`)은 9개 테스트로 검증했다.

## 4. 계측 상태: `UNMEASURED`

`scripts/measurement_gate.py`의 판정은 현재 `UNMEASURED`다. 4060/5080 동시성,
저장 모드, 보존 기간은 아래가 **모두** 실제 호스트에서 나오기 전까지 바뀌지
않는다.

| 필요한 산출물 | 생성 방법 | 현재 |
|---|---|---|
| `nvidia_smi.txt` | `scripts/measure_control_hosts.sh <dir>` | 없음 |
| `free.txt` | 같음 | 없음 |
| `lsblk.txt` | 같음 | 없음 |
| `df.txt` | 같음 | 없음 |
| `camera_soak.json` | `scripts/camera_soak_test.py`, 6스트림 ≥1800초 | 없음 |

게이트는 다음도 함께 요구한다. 짧은 fixture 실행이 상태를 바꾸지 못하도록
한 장치다.

- soak 길이 1800초 이상, 스트림 정확히 6개.
- 스트림마다 코덱·해상도·소스 FPS·디코딩 FPS·비트레이트·드롭·QR/ArUco
  지연·CPU·GPU·RAM·기록 바이트가 모두 기록되어야 한다.
- 산출물이 실제 호스트 이름을 담아야 한다 (`fixture` 라벨은 거절).

`scripts/camera_soak_test.py`는 실제 계측기가 주입되지 않으면
`RuntimeError`를 내고 숫자를 만들어 내지 않는다.

### 4.1 계획과 달라진 파일 위치

계획은 게이트를 `tools/measurement_gate.py`에 두라고 했지만, 이 저장소의
`.gitignore`는 `tools/` 전체를 무시한다(예외는 `db/tools/`). 그 경로에 두면
파일이 버전 관리되지 않으므로 `scripts/measurement_gate.py`로 옮겼다.
`tests/test_measurement_gate.py`가 그 경로에서 `evaluate_measurements`를
불러온다.

## 5. 승인된 좌표 출처에 대한 기록

P0의 유일한 pose 출처는
`control_system_test/rmf_control_ui/data/import/trihouse_test_01_physical_features.jsonl`
(13줄: waypoint 8, bottleneck 2, fiducial 3) 이다.

이번 작업에서 이 파일의 **병목 기록 2건(9·10번 줄)의 출처 표기**를 계획
Task 3 Step 4대로 수정했다. `source_radius_m: 0.2` → `source_diameter_m: 0.2`,
측정 주석의 "반경 20cm" → "지름 20cm, 반지름 10cm". 실행 반경
`radius_m: 0.1`과 모든 좌표는 손대지 않았다.

**주의:** 이 파일이 있는 `control_system_test/`는 `.gitignore`에 있어 저장소가
버전 관리하지 않는다. 따라서 이 수정은 커밋에 담기지 않으며, 새 작업 환경에서는
같은 수정을 다시 적용해야 한다. 수정 전에는 importer가
`line 9: missing field source_diameter_m`으로 실패한다.

## 6. P1 진입 게이트 재확인

계획 마지막 절의 여섯 입력 중 이 저장소에서 준비된 것은 6번(P0 회귀 증거,
이 문서)뿐이다. 1~5번은 실제 장비에서만 얻을 수 있으며, 그때까지 물리
프로파일은 막혀 있고 처리량·보존 기간은 `UNMEASURED`로 남는다.
