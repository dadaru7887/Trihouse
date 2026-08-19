# 로봇팔 통신 패키지와 실제 파지 — 설계 (2026-08-18)

## 0. 이 문서가 정하는 것

**실기 주문 완주에서 로봇팔이 실제로 움직여 물건을 집게 한다.** 모방학습한 ACT
정책을 불러오고, 파지까지 간다.

지금은 어느 환경에서도 팔이 움직이지 않는다. `executor_worker_node --environment
hardware` 는 duration 표본에 태그만 다르게 붙이고, 팔은 언제나
`OmxProtocolSimulator` 다. `hardware_adapter_node` 는 "motion remains disabled until
hardware plugin is approved" 인 진단 전용 skeleton 이다.

**전제 둘.**

1. [백엔드 다섯 층 수동 검증](2026-08-18-backend-manual-test-design.md)의 **시뮬 완주가
   먼저 통과해야 한다.** 특히 5절 L5 의 ROS 왕복(명령 계약면)과 B절의 arm step
   종료(Gateway ↔ 실행기 경로)가 통과하면, 이 설계는 **그 둘 사이에 실물 모션을 끼워
   넣는 일**로 좁혀진다.
2. 실기 완주(검증 문서 7.5)보다 **먼저 끝나야 한다.** 순서를 뒤집으면 팔의 결함과
   통합의 결함이 섞인다.

## 1. 재발명하지 않는다 — 이미 정해진 계약

[control_system-Trihouse 통합 설계 8절](../superpowers/specs/2026-08-15-control-system-trihouse-integration-design.md#L521)
이 실기 계약을 이미 정했다. 이 문서는 그것을 **실행 가능한 단계로 펴는 것**이지 다시
정하는 것이 아니다.

- **장비 경계**: `OMX_01`·`OMX_02` 는 각각 별도 PC 에 USB 로 연결하고 그 PC 의 ROS 2
  와 ROBOTIS driver 를 **로컬로** 유지한다. **모든 장비를 하나의 광역 DDS domain 에
  묶지 않는다.** PC 간 command/state/result 는 Gateway 의 versioned protocol 을 쓰고
  영상은 MediaMTX URI 로 간다.
- **모델**: `open_manipulator_x`
  ([gazebo-rmf-mysql 설계:345-346](../superpowers/specs/2026-08-12-gazebo-rmf-mysql-pinky-integration-design.md#L345-L346)).
- **marker**: 선반에 이미 붙은 `DICT_5X5_50` 의 0·1·2 를 그대로 쓴다. 새 ID 범위를
  만들지 않는다.
- **pick attempt 한 번의 정의**: `QR 확인 → ArUco pose 보정 → 물체 재검출 → ACT
  episode 실행 → 파지 후 물체가 그리퍼와 함께 움직이는지 확인 → 인계`.
- **ACT 설정 계약**: `repo_id`/`revision`/`profile` 세 값이 **모두** 실제 값일 때만
  hardware mode 가 열린다. 하나라도 `UNCONFIGURED` 면 fake 정책이다. 이 게이트는
  `ActPolicyLoader.real_motion_enabled` 에 **이미 구현돼 있다.**

그리고 [로봇팔 작업·안전 경계](../architecture/robot_arm_safety.md)의 금지 연결 네
가지가 그대로 유효하다. 특히 **"Pinky 도착 확인 전에 handover zone 을 활성화하지
않는다"** 와 **"QR 한 항목만으로 pick 을 승인하지 않는다"** 는 이 설계의 제약이다.

## 2. 참고할 상류 저장소

| 저장소 | 무엇을 가져오는가 |
|---|---|
| [robotis-git/open_manipulator](https://github.com/robotis-git/open_manipulator) | `open_manipulator_bringup`(하드웨어 기동), `open_manipulator_description`(URDF), `open_manipulator_moveit_config`(MoveIt), `ros2_controller`, `open_manipulator_teleop`, `open_manipulator_collision` |
| [ROBOTIS-GIT/physical_ai_tools](https://github.com/ROBOTIS-GIT/physical_ai_tools) | LeRobot ↔ ROS 2 연결. `physical_ai_server`, `physical_ai_manager`, `physical_ai_interfaces`, `rosbag_recorder`. LeRobot 을 submodule 로 들고 있다 |

**둘 다 벤더 코드로 다룬다.** `pinky_pro` 를 다루는 방식과 같다 — 고치지 않고,
source 순서에 넣고, 우리 패키지가 그 위에 얹힌다. 그래서 source 는 **4단**이 된다.

```bash
source /opt/ros/jazzy/setup.bash
source install/setup.bash
source pinky_pro/install/setup.bash
source open_manipulator_ws/install/setup.bash   # 새로 는다
```

**확인이 필요한 것 둘** — 상류 문서만으로는 확정할 수 없어 실물에서 30초면 끝난다.

1. **ROS 2 배포판.** `open_manipulator` 가 Jazzy 를 지원하는가. 아니면 그 PC 만 다른
   배포판이 되고 Gateway HTTP 로만 말하는 경계가 오히려 다행이 된다.
2. **모델이 X 인가 Y 인가.** 저장소가 OpenMANIPULATOR-X 와 OMY 를 모두 지원한다.
   이 저장소의 기존 설계는 `open_manipulator_x` 로 적혀 있으나 실물로 확인한다.

## 3. 무엇을 만들 것인가

새 패키지 하나와, 기존 두 곳의 게이트 해제다.

```text
trihouse_omx_adapter/                     ← 기존 패키지에 더한다
├─ hardware_adapter_node.py               ← skeleton 을 실물로 바꾼다
├─ act_runner.py                    (신규) ← ACT 정책을 불러 action 을 낸다
├─ pick_sequence.py                 (신규) ← pick attempt 한 번의 순수 상태 기계
└─ config/act.hardware.yaml         (신규) ← repo_id/revision/profile 실제 값

control_tower/task_manager/
└─ executor_worker_node.py                ← real motion 금지 게이트를 환경별로 연다
```

### 3.1 `pick_sequence.py` — 순서를 먼저 순수 함수로 만든다

1절이 정의한 여섯 단계를 **ROS 도 하드웨어도 없이** 도는 상태 기계로 만든다. 이
저장소가 `omx_workflow.py`·`stage_engine.py` 에서 이미 쓰는 방식이다.

```text
QR_REQUIRED → MARKER_ALIGNING → OBJECT_REDETECT → ACT_RUNNING
            → GRASP_VERIFYING → HANDOVER_READY
                      └→ (실패) RETRY_OFFSET → QR_REQUIRED
```

각 전이는 **관측을 입력으로 받고 결정을 낸다.** 관측을 스스로 만들지 않는다.
`omx_workflow.OmxWorkflow` 가 이미 갖고 있는 재시도 offset 정책
(`retry_offsets`, `PickRecovery`)을 여기서 실제로 쓴다 — **지금 테스트만 import 하는
그 모듈이 처음으로 런타임에 들어간다.**

**파지 확인이 핵심이다.** "ACT 가 끝났다" 는 성공이 아니다. 1절의 정의대로 **물체가
그리퍼와 함께 움직이는지**를 봐야 한다. 판정 근거는 둘 중 하나 이상이다.

- 그리퍼 joint 위치가 완전 닫힘보다 **덜 닫혔다**(물체가 끼어 있다)
- 손목 카메라에서 대상 ArUco 가 팔과 **함께 움직인다**

둘 다 없으면 `fail-closed` 로 중단한다. 안전 경계 문서가 "depth 또는 vision 신뢰도가
부족하면 fail-closed 로 중단하고 운영자 확인을 요청한다" 고 정한 그대로다.

### 3.2 `act_runner.py` — 정책을 불러 action 을 낸다

`ActPolicyLoader` 는 **정책 계보와 게이트만** 다루고 실제 추론은 하지 않는다
(`run_episode` 가 결정적 fake stage 열을 낼 뿐이다). 추론을 붙이는 것이 이 모듈이다.

- 입력: 손목 카메라 프레임 + joint state. `physical_ai_server` 가 LeRobot 정책을
  들고 있다면 그것을 호출하고, 아니면 LeRobot 을 직접 부른다. **어느 쪽인지는 2절의
  확인 뒤에 정한다.**
- 출력: joint trajectory. **직접 모터에 쓰지 않는다** — MoveIt 또는
  `joint_trajectory_controller` 를 거친다. 그래야
  `open_manipulator_collision` 의 충돌 검사가 살아 있다.
- 5080 에서 도는가 로컬에서 도는가: 1절 계약이 "OMEN 5080 서버는 ACT/VLM 추론을
  맡는다" 고 정했다. **먼저 로컬로 돌려 경로를 확인하고, 그 다음 5080 으로 옮긴다.**
  옮기는 것은 추론 위치만 바뀌는 일이고 이 설계의 계약을 바꾸지 않는다.

### 3.3 `hardware_adapter_node.py` — skeleton 을 실물로

지금은 endpoint 이름 4개를 파라미터로 선언해 두고 2초마다 "설정되지 않았다" 고
경고만 한다. 그 endpoint 를 실제로 물린다.

| 파라미터 | 무엇으로 채우는가 |
|---|---|
| `joint_state_topic` | `open_manipulator` 의 `joint_states` |
| `gripper_ack_topic` | gripper controller 의 결과 |
| `emergency_ack_topic` | 로컬 Safety 의 정지 확인 |
| `payload_limit_kg` | 실물 사양. `inventory_lots.unit_weight_kg` 와 대조한다 |

**`payload_limit_kg` 대조를 넣는 이유**: 재고 원장에 품목 무게가 이미 있다. pick 을
인가하기 전에 그 값이 한계를 넘는지 보면 물리적으로 못 드는 것을 시도하지 않는다.
지금은 아무도 그 열을 읽지 않는다.

### 3.4 실행기의 금지 게이트를 연다

`executor_worker_node._build_simulators` 는 `real_motion_enabled` 인 정책을 만나면
**`SystemExit` 한다.** P0 시뮬을 지키는 장치이고 옳다. 환경별로 갈라야 한다.

```text
--environment simulation → 지금 그대로. real motion 정책이면 SystemExit
--environment hardware   → real motion 정책을 허용하고, 대신 fake 정책을 거부한다
```

**양방향으로 막는 것이 중요하다.** 시뮬에서 실물이 도는 것도 사고지만, 실기에서
fake 정책이 조용히 도는 것도 사고다 — 팔이 안 움직이는데 step 은 `succeeded` 로
닫히고 아무도 눈치채지 못한다.

## 4. 단계 — 이 순서로만 간다

각 단계는 **앞 단계가 통과해야** 시작한다. 로봇팔은 되돌릴 수 없는 물리 운동을
하므로 층 건너뛰기의 대가가 다른 층보다 크다.

| # | 무엇 | 통과 기준 | 팔이 움직이는가 |
|---|---|---|---|
| A1 | 벤더 저장소를 붙이고 빌드한다 | `ros2 pkg prefix open_manipulator_bringup` 가 경로를 낸다. 2절의 배포판·모델 확인 완료 | 아니오 |
| A2 | 팔을 켜고 **관측만** 받는다 | `joint_states` 가 온다. `hardware_adapter_node` 의 "unconfigured" 경고가 사라진다 | 아니오 |
| A3 | teleop 으로 손으로 움직인다 | `open_manipulator_teleop` 으로 한 축을 움직이고 `joint_states` 가 따라온다 | **예. 사람이 조종한다** |
| A4 | MoveIt 으로 정해진 pose 로 간다 | `joint_trajectory_controller` 로 홈 pose 왕복. 충돌 검사가 살아 있다 | **예. 계획된 궤적** |
| A5 | 손목 카메라와 QR/ArUco | 대상 marker 의 상대 pose 가 나온다. 기존 `vision_edge` 디코더를 쓴다 | 아니오 |
| A6 | ACT 정책을 불러 **추론만** 한다 | 실제 checkpoint 를 로드하고 관측 하나에 action 을 낸다. **모터로 보내지 않는다** | 아니오 |
| A7 | ACT action 으로 실제 파지 | 물건 하나를 집고 3.1 의 파지 확인이 `true`. 실패하면 재시도 offset 이 돈다 | **예. 정책이 조종한다** |
| A8 | Gateway 계약에 물린다 | `omx` 채널 dispatch 를 받아 A7 을 돌리고 step 이 `succeeded` 로 닫힌다 | **예** |
| A9 | 실기 완주에 들어간다 | 검증 문서 7.5 의 B5 가 시뮬레이터가 아니라 실물로 통과한다 | **예** |

A3 과 A4 사이가 갈림길이다. **A3 까지는 사람이 명령을 준다.** A4 부터 소프트웨어가
궤적을 만든다. A7 부터는 학습된 정책이 만든다. **책임 주체가 세 번 바뀌므로 각
경계에서 멈추고 확인한다.**

## 5. 안전

물리 비상정지가 항상 우선이고 이 문서의 어떤 소프트웨어 장치도 그것을 대체하지
않는다. 그 위에 셋을 둔다.

1. **작업 공간을 비운다.** A3 부터 팔의 최대 도달 반경 안에 사람이 없어야 한다.
2. **`payload_limit_kg` 를 먼저 넣는다.** A2 에서 채운다. 한계를 모르는 채 A7 로
   가지 않는다.
3. **fail-closed 를 검사로 확인한다.** 파지 확인이 실패했을 때 실제로 멈추는지를
   A7 이전에 시험한다 — 빈 그리퍼로 ACT 를 돌려 `HANDOVER_READY` 로 가지 **않는**
   것을 본다. 성공 경로보다 이 실패 경로를 먼저 확인한다.

안전 경계 문서의 금지 연결 네 가지는 그대로 지킨다. 특히 **Pinky 도착 확인 전에
handover zone 을 활성화하지 않는다** — A8 에서 `load` 게이트 step 이 그 확인을 맡는다.

## 6. 승인 게이트

| # | 조작 | 시점 |
|---|---|---|
| O1 | 팔에 전원을 넣고 ROS 를 붙인다 | A2 |
| O2 | **팔이 처음 움직인다** (teleop) | A3. 작업 공간 확인 뒤 |
| O3 | 계획된 궤적으로 움직인다 | A4 |
| O4 | 학습 정책이 팔을 조종한다 | A7. fail-closed 시험을 먼저 통과한 뒤 |
| O5 | 실기 주문 완주에 넣는다 | A9 |

## 7. 검증

관례대로 **고치기 전에 실패하는 테스트를 먼저 쓴다.** 하드웨어 없이 돌 수 있는 것을
최대한 늘린다.

| 층 | 테스트 | 하드웨어 필요 |
|---|---|---|
| 순수 | `pick_sequence.py` 상태 기계 — 여섯 단계 전이, 파지 확인 실패 시 재시도 offset, fail-closed | 아니오 |
| 순수 | `payload_limit_kg` 초과 품목 거부 | 아니오 |
| 계약 | `--environment hardware` 에서 fake 정책이 거부되고 real 정책이 허용된다. simulation 은 그 반대 | 아니오 |
| 계약 | launch 파일이 절대 토픽을 쓰지 않는다 — `test_namespace_contract.py` 와 같은 규칙 | 아니오 |
| 통합 | `act_runner` 가 실제 checkpoint 를 로드하고 관측 하나에 action 을 낸다 | checkpoint 만 |
| 수동 | A1~A9 각 단계 | 예 |

## 8. 아직 정해지지 않은 것

**막고 있는 것 하나**: ACT checkpoint 의 `repo_id`/`revision`/`profile` 실제 값이
아직 없다. 기존 설계가 `UNCONFIGURED` 로 남겨 둔 그대로다. **A6 이전에 이 셋이
확정되어야 하고**, 확정되기 전까지 A1~A5 는 진행할 수 있다.

**정하지 않는 것**: VLM 을 이 경로에 넣는 것. 1절 계약에서 VLM 은 별개이고, 이
설계는 ACT 하나만 붙인다. `recovery_episodes.vlm_model_name` 이 NULL 로 남는 것과
같은 이유다([recovery 적재 설계 7절](2026-08-18-recovery-ingestion-design.md)).
