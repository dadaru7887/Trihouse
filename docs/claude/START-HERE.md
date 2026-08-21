# 새 창에서 여기부터 읽는다

이 폴더 안의 문서만으로 작업을 시작할 수 있게 만든 지도다. **바깥 문서는 옮기지
않고 여기서 가리킨다** — 정본을 두 곳에 두면 둘이 갈라지기 때문이다.

## 0. 지금 무엇을 하는 중인가

**UI 를 빼고 백엔드 다섯 층(DB → Gateway → 관제 → 로봇 → 로봇팔)이 이어 붙었을 때
실제로 도는지를 사람이 손으로 확인한다.** 기능은 대부분 코드로 끝나 있고 테스트도
붙어 있지만, 층을 이어 붙였을 때 도는지는 아직 끝까지 확인되지 않았다.

거기서 두 가지 구현이 갈라져 나왔다: 주행 중 복구 데이터를 쌓는 것과, 실기 로봇팔을
실제로 움직이는 것.

```text
1. 검증  ──▶  2. recovery 적재  ──▶  3. 로봇팔 + ACT
   (먼저)         (검증이 센 0행이       (실기 완주 전에
                   출발선)                끝나야 한다)
```

**순서를 지킨다.** 층이 도는 것을 확인하지 않은 채 구현을 얹으면 새 결함과 기존
결함을 가를 수 없다.

## 1. 이 폴더의 문서 (읽는 순서)

| # | 문서 | 무엇 | 상태 |
|---|---|---|---|
| 1 | [2026-08-18-backend-manual-test-design.md](2026-08-18-backend-manual-test-design.md) | 다섯 층 수동 검증 설계. **14절 부록에 개념 정리가 다 있다** | 사람 검토 대기 |
| 2 | [2026-08-18-recovery-ingestion-design.md](2026-08-18-recovery-ingestion-design.md) | `trihouse_recovery` 에 주행 중 데이터가 쌓이게 한다 | 사람 검토 대기 |
| 3 | [2026-08-18-omx-arm-hardware-design.md](2026-08-18-omx-arm-hardware-design.md) | 로봇팔 통신 패키지 + ACT 정책 + 실제 파지 | 사람 검토 대기 |
| 4 | [2026-08-18-reservation-scheduling-design.md](2026-08-18-reservation-scheduling-design.md) | 예약 기반 스케줄링. **승인된 설계, 구현 일부만 끝났다.** 8절 6번이 아직 없다 | 승인됨, 진행 중 |
| 5 | [2026-08-18-sim-to-hardware-p0-order-completion.md](2026-08-18-sim-to-hardware-p0-order-completion.md) | 시뮬 → 실기 주문 완주 계획. Task 2 는 4번으로 **대체됨**, Task 7 은 1번 B절에 **흡수됨** | 살아 있음 |
| — | [README.md](README.md) | 이 폴더의 규칙 | — |

계획서(`*-plan.md`)는 아직 없다. 설계 1~3 이 승인되면 그때 만든다.

## 2. 바깥의 정본 — 옮기지 않는다

여기 있는 설계가 **재발명하지 않고 참조하는** 문서들이다. 내용이 어긋나면 **바깥이
정본이고 여기가 틀린 것**이다.

### 2.1 어디서나 필요한 것

| 문서 | 줄 | 무엇의 정본 |
|---|---|---|
| [../database/database_guide.md](../database/database_guide.md) | 1727 | DB 전체. 5.17·5.18 이 recovery 두 테이블, MySQL 세 개의 역할 |
| [../architecture/system_overview.md](../architecture/system_overview.md) | 41 | 전체 흐름과 **금지 연결** |
| [../architecture/control_tower_boundary.md](../architecture/control_tower_boundary.md) | 35 | "DB transaction: FMS Gateway만 수행", "상태 전이: Task Manager만 확정" |
| [../development/code_guide.md](../development/code_guide.md) | 163 | 코드 관례 |
| `db/migrations/001_physical_v1_baseline.sql` | 1076 | **스키마 정본.** 성공 기준의 상태 문자열은 전부 여기 `CHECK` 에서 온다 |
| `scripts/control_stack` | — | 스택 lifecycle CLI |

### 2.2 검증(설계 1)에 필요한 것

| 문서 | 줄 | 무엇 때문에 |
|---|---|---|
| [../validation/2026-08-18-p0-manual-test.md](../validation/2026-08-18-p0-manual-test.md) | 743 | Docker/호스트 ROS 절차, **9.4 의 원인 분기표**, 8절의 실측 기록과 남은 벽 |
| [../validation/2026-08-18-pinky-hardware-nav2-smoke.md](../validation/2026-08-18-pinky-hardware-nav2-smoke.md) | 463 | **실기 L4 절차의 정본** — LED·부저·초음파·OLED·카메라 |
| [../handoff/2026-08-18-p0-handoff.md](../handoff/2026-08-18-p0-handoff.md) | 227 | 세션 인수인계. 첫 3분에 무엇을 확인하는지 |
| [../guideline/docker_permission_and_mysql_verification.md](../guideline/docker_permission_and_mysql_verification.md) | 457 | MySQL 권한 확인. `trihouse_recovery` 존재 확인 쿼리가 여기 있다 |
| [../validation/2026-08-16-p0-simulation.md](../validation/2026-08-16-p0-simulation.md) | 477 | 이전 세션 실측 |

### 2.3 recovery 적재(설계 2)에 필요한 것

| 문서 | 줄 | 무엇 때문에 |
|---|---|---|
| [../architecture/recovery_memory.md](../architecture/recovery_memory.md) | 33 | **실시간 기록 계약** — 로컬 queue 에 먼저 쓰고 ACK 까지 같은 `message_id` 로 재전송, Gateway 는 idempotent 하게 한 번만 반영. 금지 연결 4개 |
| [../superpowers/specs/2026-08-09-vlm-rl-recovery-schema-design.md](../superpowers/specs/2026-08-09-vlm-rl-recovery-schema-design.md) | 122 | 스키마를 만들면서 **무엇을 왜 미뤘는지** |
| [../superpowers/plans/2026-08-09-vlm-rl-recovery-schema.md](../superpowers/plans/2026-08-09-vlm-rl-recovery-schema.md) | 63 | 그 스키마를 만든 계획 |

### 2.4 로봇팔(설계 3)에 필요한 것

| 문서 | 줄 | 무엇 때문에 |
|---|---|---|
| [../superpowers/specs/2026-08-15-control-system-trihouse-integration-design.md](../superpowers/specs/2026-08-15-control-system-trihouse-integration-design.md) | 864 | **8절이 실기 계약의 정본** — 장비 경계, marker, ACT 설정 계약, pick attempt 정의 |
| [../architecture/robot_arm_safety.md](../architecture/robot_arm_safety.md) | 32 | 작업 흐름과 **금지 연결 4개** |
| [../architecture/vision_data_flow.md](../architecture/vision_data_flow.md) | 64 | **손목 카메라 RTSP 경로** `omx/CAM-OMX-01-WRIST`, 인가 정책 |
| [../superpowers/plans/2026-08-17-pinky-camera-stream-contract.md](../superpowers/plans/2026-08-17-pinky-camera-stream-contract.md) | 428 | `config/cameras.yaml` 이 카메라 신원의 정본 |
| [../superpowers/specs/2026-08-10-pinky-qr-aruco-calibration-design.md](../superpowers/specs/2026-08-10-pinky-qr-aruco-calibration-design.md) | 113 | ArUco **자세 추정** 방법 |
| [../superpowers/plans/2026-08-10-pinky-qr-aruco-calibration.md](../superpowers/plans/2026-08-10-pinky-qr-aruco-calibration.md) | 242 | 그 실측 절차 |
| [../guideline/interfaces.md](../guideline/interfaces.md) | 126 | **State/Action 분리 원칙** — 상태와 조치를 섞지 않는다 |

상류 저장소 둘: [robotis-git/open_manipulator](https://github.com/robotis-git/open_manipulator),
[ROBOTIS-GIT/physical_ai_tools](https://github.com/ROBOTIS-GIT/physical_ai_tools).

## 3. 손대기 전에 알아야 할 것

첫 턴에 이것부터 확인한다. **틀린 전제로 시작하면 몇 시간을 버린다.**

| 함정 | 옳은 것 |
|---|---|
| 도메인 | 시뮬 **0**, 실기 **52**. 절대 섞지 않는다. 모든 터미널에서 export |
| source | 3단: `/opt/ros/jazzy/setup.bash` → `install/setup.bash` → `pinky_pro/install/setup.bash` |
| 부하 | 12코어 PC. **단일 로봇(`TRIHOUSE_ROBOTS=PK_01`)이 기본**이다. 2대는 load average 60~90 까지 가고 Nav2 lifecycle 이 포기한다 |
| 프로세스 정리 | **`pkill -f` 를 직접 쓰지 않는다.** `scripts/sim_teardown.sh`. 단 이 스크립트는 같은 셸의 pytest 도 죽인다 |
| 상태 판정 | `ros2 topic list`/`node list`/`param get` 은 부하에 멈춘다. `scripts/verify_robot_status.py <namespace> <초>` 를 쓴다 |
| MySQL | **3308 이 운영이다.** 3307 은 tmpfs 테스트(`trihouse_fms` DB 자체가 없다), 3306 은 보존 개발 DB |
| Compose | 네 파일을 `-f` 로 묶고 `--project-name trihouse_p0 --env-file .env`. `scripts/control_stack` 이 이미 그렇게 한다 |
| Gateway 이미지 | 소스 마운트가 아니라 **빌드 이미지**다. 고치면 재빌드해야 새 라우트가 뜬다 |
| LED/부저 | `trihouse/indicator/state` 에 직접 publish 하지 않는다. `safety_supervisor` 가 20 Hz 로 덮어쓴다 |
| 카메라 | 영상은 **ROS 토픽으로 나가지 않는다.** MediaMTX RTSP 이고 ROS 에는 `stream_health` 만 |
| pytest | `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest`, `PYTHONPATH` 는 덮어쓰지 말고 **더한다**. e2e 는 3307 에서만 |
| worktree | **수동 검증은 worktree 에서 돌리지 않는다.** 스택이 `/home/syw/Trihouse` 기준이고 `.trihouse/p0/` 와 bind mount 가 그 경로에 묶여 있다 |

## 4. 이 폴더는 git 이 무시한다

`.gitignore:23` 이 `docs/claude/` 를 무시한다. 새로 만든 문서는 **`git add` 해도
잡히지 않는다** — 커밋하려면 `git add -f` 가 필요하다.

의도된 것으로 본다. 이 폴더는 **사람이 검토하고 승인하기 전의 작업 공간**이고,
승인된 결과물은 `docs/architecture/`·`docs/validation/` 같은 제자리로 간다.

예외가 하나 있다. `2026-08-18-reservation-scheduling-design.md` 는 원래
`docs/architecture/` 에서 커밋(`c2b675c0`)돼 있었고 여기로 옮겨 왔다. **이미
추적 중이므로 `.gitignore` 가 적용되지 않고 계속 버전 관리된다.**

## 5. 실측은 여기 적지 않는다

| 무엇 | 어디 |
|---|---|
| 무엇을 왜 하는가 (설계) | `docs/claude/*-design.md` |
| 무엇을 할 것인가 (계획, 체크박스) | `docs/claude/*-plan.md` |
| **무엇이 나왔는가 (실제 출력)** | **`docs/validation/`** |

계획 문서에서는 **체크박스만** 갱신한다. 실행하면서 그 자리에서 칠하고, 다 끝난 뒤
한꺼번에 칠하지 않는다.
