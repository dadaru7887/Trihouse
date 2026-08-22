# Vision, VLM+RL, and Approved Recovery Integration Design

## 1. 목표와 고정 조건

Pinky가 Nav2의 기본 재계획과 recovery로 해결하지 못한 사람·장애물 상황을 5080에서 해석하고, 4060 관제 운영자의 승인 뒤에만 제한된 recovery action을 Pinky가 실행한다. 실행 결과는 `trihouse_recovery`에 원래 TGRPO+SAC 학습 tuple로 저장한다.

- ROS 통신은 `ROS_DOMAIN_ID=12`를 사용한다.
- 로봇 명령 라우팅은 DB `device_id`만 사용한다.
- VLM/RL 모델의 9차원 state, 5개 skill, 3차원 action 수학과 네트워크 구조는 변경하지 않는다.
- 모델 입력의 의미와 실행 좌표 변환은 버전이 있는 명시적 계약으로 고정한다.
- VLM/RL은 직접 `cmd_vel`을 발행하지 않는다.
- 최종 모터 입력 `cmd_vel`은 각 Pinky의 Safety Supervisor만 발행한다.
- 실제 recovery 실행은 4060의 `safety_manager` 승인과 Pinky의 최종 안전 검사를 모두 통과해야 한다.
- 4060은 카메라 영상을 MediaMTX로 수신·보관·제공하고 관제·Gateway·DB를 수행한다. 5080은 그 스트림을 읽어 추론하며 4060에서는 영상 추론하지 않는다.

## 2. 원본 모델 계약

### 2.1 State V1

모델 입력 배열의 순서는 다음과 같이 고정한다.

| Index | Field | Unit/range |
|---:|---|---|
| 0 | `robot_x_m` | map frame, m |
| 1 | `robot_y_m` | map frame, m |
| 2 | `robot_yaw_rad` | rad |
| 3 | `goal_x_m` | map frame, m |
| 4 | `goal_y_m` | map frame, m |
| 5 | `risk_bbox_center_x_norm` | image normalized, 0..1 |
| 6 | `risk_bbox_center_y_norm` | image normalized, 0..1 |
| 7 | `risk_confidence` | 0..1 |
| 8 | `vlm_uncertainty` | 0..1 |

원본 `dev_driving` adapter와 동일하게 VLM observations 중 risk가 가장 높은 객체 하나가 index 5~7을 대표한다. 모든 객체는 proposal의 perception evidence에 별도로 보존하며, 사람 veto와 감사에는 전체 목록을 사용한다.

외부 HTTP 계약은 raw vector를 받지 않는다. 이름 있는 `RecoveryStateV1`을 받아 Gateway 또는 공용 adapter가 유일하게 `to_vector()`를 수행한다. `state_schema_id`는 `trihouse.recovery-state.v1`로 고정한다.

### 2.2 Skill과 action type

| skill | skill name | DB action type |
|---:|---|---|
| 0 | `BACKUP` | `retreat` |
| 1 | `REROUTE_LEFT` | `detour` |
| 2 | `REROUTE_RIGHT` | `detour` |
| 3 | `WAIT_REOBSERVE` | `wait` |
| 4 | `REJOIN` | `rejoin` |

`skill`은 정책이 고르는 구체적인 방향 포함 행동이고 `action_type`은 DB 집계·상태기계가 사용하는 행동 계열이다. 좌·우 detour는 서로 다른 skill이므로 어느 항목도 삭제하지 않는다.

### 2.3 Coord V1

모델 출력은 기존과 동일한 `(dx, dy, dyaw)` 상대 좌표다. 실행 전 `canonicalize_recovery_action()`이 반경 0.25 m와 yaw ±π/3을 적용하고 skill별 실제 실행 파라미터를 만든다. Safety 검사, 실제 실행, DB transition은 모두 동일한 canonical 결과를 사용한다.

- `BACKUP`: translation magnitude를 뒤쪽 거리로 변환하고 저장 coord는 `(-distance, 0, 0)`이다.
- `REROUTE_LEFT/RIGHT`: `atan2(dy, dx)`와 `hypot(dx, dy)`로 회전·직진을 만들며 skill 방향과 heading 부호가 모순이면 거절한다.
- `WAIT_REOBSERVE`: 저장 coord와 실행 coord는 `(0, 0, 0)`이다.
- `REJOIN`: 상대 coord를 현재 map pose 기준 절대 target pose로 한 번 변환하고 Nav2와 Safety가 그 target을 공유한다.

## 3. 종단 아키텍처

### 3.1 데이터와 명령 흐름

```text
Pinky camera
→ 4060 MediaMTX ingest/archive
→ 5080 RTSP consumer
→ YOLO segmentation event
→ navigation-decision trigger
→ Qwen2.5-VL-7B-Instruct 4-bit
→ RecoveryStateV1
→ unchanged HighLevelPolicy + LowLevelPolicy
→ bounded/canonical recovery proposals
→ 4060 Gateway proposal API + DB
→ W-CONTROL-01 safety_manager approval
→ existing device_id-routed Pinky TCP control link
→ ExecuteRecovery ROS action
→ Nav2 behavior action
→ cmd_vel_nav
→ Safety Supervisor
→ cmd_vel
→ observed post-state/result
→ Gateway completion API
→ trihouse_recovery transition
→ JSONL offline training export
```

### 3.2 현재 간극

- 5080 runtime은 recovery completion 재전송만 하며 실제 VLM 모델을 로드하지 않는다.
- segmentation 결과와 navigation undecidable 상태를 결합하는 trigger가 없다.
- Gateway에 proposal·승인·승인 명령 outbox 계약이 없다.
- Pinky TCP protocol과 ROS interface에 recovery 명령이 없다.
- 기존 팀원 executor는 `dy`를 실행에 사용하지 않고 REJOIN의 상대/절대 의미가 Safety와 다르다.
- 기존 safety gate는 학습 모드 상수로 꺼져 있고 현재 namespaced Pinky launch에 연결되지 않는다.
- AI Docker build context에서 `model/`이 `.dockerignore`에 의해 제외된다.
- 개발 TestClient는 Starlette 1.6의 deprecated `httpx` fallback을 사용한다.

## 4. 5080 inference runtime

한 프로세스가 프레임 수명과 GPU 모델 수명을 소유하되 내부 구성요소는 분리한다.

- `SegmentationSource`: MediaMTX RTSP에서 프레임을 읽고 모든 person/obstacle detection을 구조화한다.
- `NavigationContextSource`: Gateway에서 해당 `device_id`의 goal, pose, Nav2 상태, 진행 정체 시간을 읽는다.
- `RecoveryTrigger`: detection만으로 발동하지 않는다. Nav2 반복 실패 또는 진행 정체와 person/obstacle이 함께 있을 때만 발동한다.
- `VlmInterpreter`: 원본 Qwen2.5-VL prompt/JSON 계약을 사용하고 JSON·bbox·confidence·uncertainty를 검증한다.
- `StateAdapter`: 가장 위험한 객체 하나를 State V1에 넣고 전체 detection은 evidence로 보존한다.
- `PolicyRuntime`: 승인된 checksum의 기존 HighLevel/LowLevel checkpoint만 로드한다.
- `ProposalClient`: 후보와 evidence lineage를 Gateway로 보내며 어떤 ROS 또는 velocity 명령도 발행하지 않는다.
- `CompletionSender`: 기존 durable queue와 application ACK를 유지한다.

사람 검출의 즉시 정지/감속 경로는 VLM과 독립적으로 기존 Safety 경로를 우선한다. VLM은 정지 후 복구 방향을 제안할 뿐 emergency를 해제하지 않는다.

## 5. Gateway 승인과 DB

`004_recovery_proposals_and_approvals.sql`은 immutable baseline 이후 추가 migration으로 만든다. proposal에는 episode, step, `device_id`, named pre-state, 전체 perception evidence, policy/VLM lineage, canonical candidates, 선택 후보, proposal hash를 기록한다. approval에는 `W-CONTROL-01`, 결정, 시각, 사유를 기록한다.

- 5080은 proposal 생성과 completion 제출만 할 수 있다.
- 승인 endpoint는 DB role이 `safety_manager`인 작업자만 허용한다.
- 승인된 proposal hash와 명령 payload hash가 일치해야 outbox에 들어간다.
- command worker는 `device_id`로 기존 Pinky TCP connection을 선택한다.
- 동일 approval/command ID 재전송은 동일 결과를 반환하고 motion을 반복하지 않는다.
- 거절·만료·Safety veto 후보는 학습 transition에 넣지 않고 operation event로만 남긴다.

## 6. Pinky recovery action

`trihouse_interfaces/action/ExecuteRecovery.action`은 command/episode/step/device/map/approval/proposal identity, skill, canonical coord를 goal로 전달한다. result는 status, 실제 pre/post pose, 전후 최소 clearance, elapsed time, Safety 개입, terminal 여부를 반환한다.

기존 `FleetNode`가 `ExecuteTransport`와 `ExecuteRecovery`를 함께 소유하여 두 motion이 경쟁하지 않게 한다. active transport는 recovery 전에 취소·정차가 확인되어야 하며, emergency·stale approval·map mismatch·다른 device ID·비정차 상태는 goal 단계에서 거절한다.

Nav2의 `backup`, `spin`, `drive_on_heading`, `wait`, `navigate_to_pose` action을 사용한다. Nav2 출력은 기존 remap을 통해 `cmd_vel_nav`로 들어가고 Safety Supervisor만 실제 `cmd_vel`을 발행한다.

ROS namespace는 선택적이다. launch argument 기본값은 빈 문자열이며, 빈 값이면 root 상대 이름(`navigate_to_pose`, `odom`, `scan`)을 사용하고 `pinky_01`이면 해당 namespace 안에서 같은 상대 이름을 사용한다. 코드에 `/odom`·`/scan` 같은 절대 이름을 넣지 않는다.

## 7. Safety gate

Safety gate는 정책 후보가 실행되기 전에 형식, 정차, 센서 freshness, recovery envelope, costmap, footprint, Nav2 path, 사람 점유를 순서대로 검사하는 사전 차단 계층이다. 학습 탐색 다양성을 위해 원본에서 꺼졌지만 운영자 승인 실물 모드에서는 비활성화를 허용하지 않는다.

사전 gate 통과는 실행 허가의 필요조건일 뿐 최종 안전 보장이 아니다. 실행 중 local costmap/Nav2 controller와 Safety Supervisor가 계속 veto할 수 있으며, emergency latch는 별도 관리자 절차 없이는 해제되지 않는다.

## 8. Docker 환경

기존 되돌려진 env commit `09dbe388`의 Ubuntu 24.04, Python 3.12, 명시적 CUDA/PyTorch 고정 원칙은 참고한다. PyTorch 2.5/CUDA 12.4, 최대 architecture 9.0, Pointcept/ROS/flash-attn 전체 결합 이미지는 5080 inference 이미지에 이식하지 않는다.

5080 inference는 기존 `compose.ai_5080.yaml`과 `docker/ai/Dockerfile.inference`를 유지하되 기본 base image를 `pytorch/pytorch:2.7.1-cuda12.8-cudnn9-runtime`으로 고정하고 배포 manifest에서 image digest를 검증한다. Qwen2.5-VL, qwen-vl-utils, bitsandbytes, Ultralytics, OpenCV headless와 Gateway client만 추가하며 weights/cache는 read-only volume이다. training Dockerfile은 별도로 유지하고 실물 Compose는 training package나 entrypoint를 실행하지 않는다.

4060은 같은 Dockerfile을 빌드해 filesystem/import/CPU fake-pipeline을 검증한다. GPU kernel과 실제 7B 모델 smoke는 NVIDIA driver와 5080이 정상인 AI-Server-5080에서 별도 검증한다.

## 9. 테스트와 실물 도입 순서

1. State V1 named/vector round-trip과 잘못된 범위·schema 거절
2. 기존 `dy` 무시와 REJOIN frame mismatch를 재현하는 failing tests
3. canonical motion plan과 동일 target의 Safety/executor 사용
4. proposal·approval·outbox·idempotency의 Gateway/MySQL 통합 테스트
5. optional namespace와 `ExecuteRecovery` ROS contract/launch 테스트
6. fake detector/VLM/policy/Pinky를 사용한 Docker 종단 테스트
7. 4060 image build, import smoke, FastAPI TestClient (`httpx2==2.9.1`)
8. 5080 real GPU/import/checkpoint/single-frame VLM smoke
9. Pinky에서 움직임 없는 `WAIT_REOBSERVE`
10. E-stop 담당자와 빈 공간에서 최대 0.05 m BACKUP
11. detour/rejoin target 일치와 Safety veto 확인
12. 실제 completion이 한 건의 trainable JSONL transition으로 왕복되는지 확인

자동 검증은 물리 성공으로 표시하지 않는다. 4060 Docker build는 `Tested`, 5080 GPU 결과는 해당 호스트 로그가 있어야 `Measured`, Pinky motion은 E-stop·경로·sole Safety publisher 확인 후에만 `Measured`로 기록한다.
