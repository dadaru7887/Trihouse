# Vision, VLM+RL Recovery Integration Design

## 1. 목표

사람과 장애물을 YOLO segmentation으로 구분하고, 사람은 track별 쓰러짐 상태를
추적한다. Pinky가 Nav2와 로컬 규칙만으로 안전한 다음 행동을 결정하지 못하면 객체가
사람인지 장애물인지와 관계없이 VLM+RL 복구 파이프라인을 실행한다.

VLM+RL은 복구 방향과 좌표 후보를 제안한다. Control Tower의 Recovery Coordinator가
작업 상태와 안전 필터 결과를 검증하고 운영자 승인을 받은 후보 한 개만 Pinky에
전달한다. Pinky는 해당 명령을 Nav2 action으로 실행하며, 로컬 Safety Supervisor만
최종 `/cmd_vel`을 발행한다. 실제 실행 결과는 Gateway를 통해
`trihouse_recovery`에 기록한다.

이 문서는 다음을 하나의 통합 범위로 정한다.

- 기존 vision 코드를 `model/perception`, `model/worker`, `model/vlm_rl`로 재배치
- `origin/dev_driving`의 VLM+RL 아키텍처를 현재 FMS·ROS 안전 경계에 맞게 선택 이식
- 사람·장애물 공통의 판단 불가 trigger와 VLM+RL 복구 흐름
- 운영자 승인형 recovery command와 Pinky 실행·취소 계약
- 5080 persistent queue에서 Gateway를 거쳐 recovery DB에 적재하는 계약
- 역할별 Compose와 단계별 자동·실물 검증

## 2. 확정된 원칙

1. VLM+RL 진입 기준은 객체 종류가 아니라 Pinky가 기존 주행 계층으로 안전한 다음
   행동을 결정할 수 있는지다.
2. 사람 감지에 따른 즉시 감속·정지는 VLM 응답을 기다리지 않고 기존 Pinky Safety
   Supervisor가 수행한다.
3. VLM+RL의 전체 구조는 VLM 상태 해석, 9차원 RL 상태, 상위 TGRPO, 하위 SAC,
   후보군, R0~R6 필터, Nav2 실행, reward, episodic memory, offline training 순서를
   유지한다.
4. 5080은 MySQL, Pinky Nav2 action, `/cmd_vel`에 직접 연결하지 않는다.
5. 운영 기본 모드는 `operator_approved`다. 안전 필터를 통과한 후보도 4060 운영자의
   명시적 승인 전에는 실행하지 않는다.
6. Recovery Coordinator는 후보를 승인 가능한 명령으로 바꾸지만 물리 속도를 직접
   만들지 않는다.
7. Pinky Safety Supervisor는 좌표를 선택하지 않는다. `cmd_vel_nav`,
   `cmd_vel_dock`, `cmd_vel_manual` 중 선택된 속도를 센서와 안전 상태로 제한하고
   `/cmd_vel`을 발행한다.
8. DB에는 실제 실행한 복구 행동만 `recovery_steps`로 기록한다. 실행하지 않은 후보와
   filter report는 FMS event 또는 artifact로 남긴다.
9. `001_physical_v1_baseline.sql`은 수정하지 않는다. recovery ingestion에 새 테이블이나
   제약이 필요하면 `002_*.sql` migration으로 추가한다.
10. DB·FMS 명령에는 `PK_01`, `PK_02`를 사용하고 ROS namespace에는
    `pinky_01`, `pinky_02`를 사용한다.

## 3. 현재 상태와 간극

### 3.1 구현된 부분

- `vision_system/yolo_inference_server/detector.py`는 segmentation 결과에서 class,
  confidence, mask를 추출한다.
- `vision_system/person_worker/posture.py`와 `fall_monitor.py`는 mask 자세 측정과
  시간축 낙상 상태 전이를 구현한다.
- Gateway의 `POST /internal/v1/vision/person-detections`는 카메라 registry로 해당
  Pinky를 찾고 TCP downlink로 사람 관측을 전달한다.
- Pinky Safety Supervisor는 사람, LiDAR, 초음파, keep-out, 관제 연결, 비상 상태를
  검사하고 `/cmd_vel`의 유일한 운영 발행자 역할을 한다.
- DB baseline에는 `location_recovery_profiles`, `recovery_episodes`,
  `recovery_steps`가 있다.
- `compose.ai_5080.yaml`에는 모델·dataset·artifact·persistent recovery queue volume
  계약이 있다.

### 3.2 완성해야 하는 부분

- 실제 승인된 YOLO weight와 class mapping checksum
- 모든 person instance의 bbox·mask·track ID를 유지하는 다중 객체 추론
- 사람 낙상 확인 요청을 Gateway incident/event로 기록하는 경로
- obstacle observation worker와 판단 불가 trigger 연결
- strict VLM JSON contract, timeout, fallback, model lineage
- 승인된 RL checkpoint load와 policy version gate
- 실제 costmap·TF·Nav2·사람 veto에 연결된 R0~R6 filter
- Recovery Coordinator, 운영자 승인 API, recovery command downlink
- Pinky recovery command parser와 Nav2 action executor
- 지속 STOP과 EMERGENCY 시 recovery goal cancel·ACK
- 5080 persistent queue, Gateway ingestion API, repository transaction
- recovery DB export와 offline training 입력
- 5080 Compose entrypoint, command, healthcheck

## 4. 디렉터리 구조

기존 루트의 `vision_edge`, `vision_perception`, `vision_system` 세 폴더를 다음 구조로
통합한다. 기능 이전과 import·test·Compose·문서 갱신이 끝난 뒤 기존 루트 폴더는
남기지 않는다.

```text
model/
├── __init__.py
├── perception/
│   ├── dataset/
│   │   ├── calibration/
│   │   ├── augmentation/
│   │   ├── collection/
│   │   └── validation/
│   ├── segmentation/
│   │   ├── training/
│   │   ├── evaluation/
│   │   ├── contracts.py
│   │   └── inference.py
│   ├── configs/
│   │   └── segmentation_models.yaml
│   └── tests/
├── worker/
│   ├── common/
│   ├── media/
│   ├── person/
│   │   ├── worker.py
│   │   ├── tracker.py
│   │   ├── posture.py
│   │   ├── fall_monitor.py
│   │   └── policy.py
│   ├── obstacle/
│   │   └── worker.py
│   ├── marker/
│   ├── reporting/
│   └── tests/
└── vlm_rl/
    ├── contracts/
    ├── shared/
    │   └── policy_architecture.py
    ├── inference/
    │   ├── trigger.py
    │   ├── snapshot.py
    │   ├── vlm_interpreter.py
    │   ├── state_encoder.py
    │   ├── candidate_generator.py
    │   └── orchestrator.py
    ├── safety/
    │   ├── filters.py
    │   ├── geometric_rollout.py
    │   └── human_veto.py
    ├── recovery_memory/
    │   ├── queue.py
    │   ├── gateway_client.py
    │   └── replay_export.py
    ├── training/
    │   ├── offline_train.py
    │   ├── tgrpo.py
    │   ├── sac.py
    │   ├── reward.py
    │   └── replay_sampler.py
    ├── configs/
    │   └── recovery_models.yaml
    └── tests/
```

`posture.py`는 person mask의 자세와 움직임을 측정하므로 person worker 내부에 둔다.
독립 `model_registry` 서비스나 폴더는 만들지 않는다. 대신 segmentation과 VLM/RL의
설정 파일이 모델 이름, 버전, weight/checkpoint 경로, SHA-256, class mapping,
quantization, 승인 상태를 보관한다.

`shared/policy_architecture.py`는 학습과 추론이 동일한 checkpoint를 읽는 데
필요한 신경망 구조, state/skill/coord 차원, skill 순서만 보유한다. 기존
`origin/dev_driving`의 신경망 layer, activation, dimension, sampling 수식, 학습 수식과
hyperparameter는 바꾸지 않는다. 학습 entrypoint와 optimizer·gradient update는
`training`에만 두고, `inference`는 승인된 checkpoint를 읽어 `torch.no_grad()`로
후보를 만든다. 실물 5080 runtime image에는 `training` package와 학습
entrypoint를 포함하지 않는다.

이동 과정에서 제거 가능한 항목은 `__pycache__`, 의미 없는 `.gitkeep`, 완전히 대체된
중복 상태 머신, 절대경로 전용 옛 실행 스크립트다. 실측 데이터, notebook, weight,
영상, pickle은 생성물과 원본을 구분한 뒤 별도 승인 없이 삭제하지 않는다. 운영 artifact와
학습 결과는 Git source tree가 아니라 `/data`, `/models`, `/artifacts` volume에 둔다.

## 5. Perception과 Worker 흐름

### 5.1 Segmentation 계약

승인된 모델은 `obstacle=0`, `person=1` class mapping을 manifest와 SHA-256으로
검증한 뒤 로드한다. 결과 한 건은 최소 다음 필드를 갖는다.

```text
camera_id, frame_sequence, captured_at, class_id, confidence,
bbox, mask, track_id, model_name, model_version
```

검출 0건과 추론 실패를 구분한다. 검출 0건은 정상 빈 결과이고, decode 실패·GPU
오류·weight 불일치는 stream/inference health failure다.

### 5.2 사람 처리

모든 person instance에 tracker를 적용하고 `(camera_id, track_id)`마다 posture와
FallMonitor 상태를 유지한다.

```text
person mask
  -> bbox·centroid·aspect ratio·motion 측정
  -> NORMAL / FALL_SUSPECTED / FALLEN / IMMOBILE / EMERGENCY_CANDIDATE
  -> Gateway person observation
  -> attached Pinky Safety Supervisor
```

`EMERGENCY_CANDIDATE`는 비상 확정이 아니라 운영자 확인 요청이다. 근거 frame/clip URI,
track ID, 상태 지속 시간, 모델 버전을 함께 기록한다.

### 5.3 장애물 처리

Obstacle worker는 segmentation만으로 recovery를 시작하지 않는다. Nav2 state,
진행률, costmap, localization, sensor freshness와 결합해 판단 불가 상태를 만든다.
정상적인 Nav2 재계획이 가능하면 기존 목표를 계속한다.

## 6. 판단 불가 Trigger

VLM+RL 진입은 다음 조건을 모두 충족해야 한다.

1. 현재 작업과 목표가 식별 가능하다.
2. Nav2가 경로 생성 실패, 반복 abort, no-progress, sensor/perception conflict 중 하나를
   보고한다.
3. 기존 goal cancel을 요청하고 cancel ACK를 받는다.
4. odometry 기준 선속도·각속도가 정지 threshold 이하다.
5. RGB, segmentation, LiDAR, pose, costmap snapshot이 최대 staleness 이내다.
6. emergency latch가 없고 Safety Supervisor 상태를 읽을 수 있다.

Trigger type은 baseline schema의 `blocked`, `person`, `low_visibility`,
`localization`을 사용한다. 사람 또는 장애물은 trigger의 공간 문맥이며, 단순 검출 한
프레임은 판단 불가 증거가 아니다.

사람 관련 trigger에서는 기본 허용 skill을 `wait`, `stop`, 사람에게서 멀어지는
`retreat`, 재관측으로 제한한다. 사람 주변 `detour`는 track velocity와 예측 점유영역,
clearance가 검증되지 않으면 filter에서 거절한다.

## 7. VLM+RL Runtime

### 7.1 VLM 상태 계약

VLM 입력은 동기화된 snapshot, 현재 robot pose, goal, nominal trajectory,
segmentation instances, costmap summary다. 출력은 JSON Schema로 검증하며 설명문에서
정규식으로 첫 JSON을 추출하는 방식은 사용하지 않는다.

필수 출력은 상황 유형, 핵심 entity, 위험 방향, confidence, uncertainty,
recommended constraints다. timeout, schema violation, model unavailable이면 recovery
후보를 만들지 않고 `wait/stop + operator review`로 fail-closed한다.

### 7.2 RL 상태와 후보

기존 아키텍처의 9차원 상태를 유지한다.

```text
robot x, robot y, robot yaw,
goal x, goal y,
critical entity x, critical entity y,
VLM confidence, VLM uncertainty
```

상위 TGRPO가 skill을 고르고 하위 SAC가 상대 좌표와 yaw를 생성한다. Candidate group은
정책이 낸 값을 현재 robot pose와 map frame의 target pose로 바꾸고, recovery envelope와
정책별 최대 이동량을 적용한다. runtime은 `approved=true`이고 checksum이 일치하는
checkpoint만 로드한다. 매 episode마다 무학습 policy를 새로 초기화하지 않는다.

### 7.3 R0~R6 안전 필터

- R0: 로봇 정지, 이전 goal cancel ACK, sensor freshness, Safety Supervisor 상태
- R1: finite coordinate, map frame/revision, footprint, policy lineage, epoch
- R2: target costmap, footprint, keep-out, stopping distance, recovery envelope
- R3: critical memory, active reference, 사람 현재·예측 점유영역
- R4: 실제 Nav2 path 생성 가능성, 길이·시간 budget, reversing capability
- R5: 전체 경로 geometric rollout과 path clearance
- R6: 우승 후보 하나에 대해 최신 snapshot으로 재검사, TTL, safety clear, audit

위험 조건은 다른 점수로 상쇄하지 않는다. 하나의 hard rule이 실패하면 후보를
탈락시킨다. 필수 입력이 없으면 안전하다고 가정하지 않고 fail-closed한다.

## 8. 운영자 승인과 Recovery Command

### 8.1 승인 상태

Recovery Coordinator는 하나의 episode를 다음 상태로 관리한다.

```text
TRIGGERED
  -> INTERPRETING
  -> FILTERING
  -> AWAITING_OPERATOR_APPROVAL
  -> AUTHORIZED
  -> DISPATCHED
  -> RUNNING
  -> SUCCEEDED | FAILED | CANCELLED
```

후보가 없거나 VLM·filter가 실패하면 `AWAITING_OPERATOR_APPROVAL`로 진행하지 않고
정지 상태와 실패 근거를 운영 화면에 노출한다.

운영자는 camera evidence, 현재 pose, 목표, action type, target pose, filter report,
모델·정책 버전, 예상 이동 거리를 확인한다. 승인은 `worker_id`와 시각을 기록하며 같은
승인을 다른 좌표나 새 sensor epoch에 재사용하지 않는다.

### 8.2 명령 계약

Gateway가 Pinky에 내리는 명령에는 raw velocity가 아니라 승인된 고수준 행동이 들어간다.

```json
{
  "schema_version": 1,
  "message_id": "uuid",
  "type": "recovery_command",
  "recovery_episode_uuid": "uuid",
  "device_id": "PK_01",
  "assignment_revision": 7,
  "map_name": "new_map_2",
  "map_revision": "published-revision",
  "step_no": 1,
  "action_type": "retreat",
  "target_pose": {
    "frame_id": "map",
    "x": 1.25,
    "y": -0.42,
    "yaw": 3.14
  },
  "policy_name": "tgrpo-sac",
  "policy_version": "physical-v1",
  "sensor_epoch": 31,
  "expires_at": "RFC3339 timestamp",
  "approved_by_worker_id": "W-SAFETY-01"
}
```

Pinky는 device ID, assignment revision, map revision, step order, expiration,
current stationary state를 검증한다. 같은 `message_id`는 동일한 ACK를 반환하고 다른
payload로 재사용되면 거절한다.

### 8.3 Pinky 실행

Pinky recovery executor는 action type을 Nav2 action으로 변환한다. 실행 결과 속도는
Nav2의 `cmd_vel_nav`를 통해 Safety Supervisor에 들어간다. recovery executor나 5080이
`/cmd_vel`을 직접 발행하지 않는다.

```text
recovery_command
  -> Pinky command validation
  -> Nav2 action
  -> cmd_vel_nav
  -> Safety Supervisor
  -> cmd_vel
```

## 9. Safety Supervisor 최종 Veto와 취소

Safety Supervisor는 `cmd_vel_nav`, `cmd_vel_dock`, `cmd_vel_manual`에서 선택된 명령을
검사하고 `CLEAR`, `SLOW`, `STOP`, `EMERGENCY`를 낸다.

- sensor timeout, control link loss, keep-out, swept collision, stop distance 이내:
  속도를 0으로 만든다.
- 사람 또는 slow distance 이내: 허용 속도로 제한한다.
- emergency latch: 속도 0을 유지하고 명시적 해제 전 재개하지 않는다.

이 veto는 좌표 선택이 아니라 실제 모터 입력에 대한 최종 차단이다. 현재 STOP은 속도를
0으로 만들지만 Nav2 goal을 자동 취소하지 않는다. Recovery Coordinator와 Pinky
executor에 다음 취소 규칙을 추가한다.

- 일시 STOP: goal을 유지하되 실행 timer를 정지 상태로 표시
- 설정 시간을 넘긴 지속 STOP: recovery goal cancel 요청
- EMERGENCY: 즉시 cancel 요청
- cancel ACK 후 step을 `cancelled`로 종료
- 새 sensor epoch에서 VLM+RL을 다시 실행하고 새 운영자 승인을 요구

Safety state를 받지 못하거나 cancel ACK를 받지 못하면 새 recovery command를 허용하지
않는다.

## 10. Recovery DB와 ACK Queue

### 10.1 기록 경계

5080은 `/var/lib/trihouse/recovery_queue`에 전송 record를 먼저 원자적으로 기록하고
Gateway의 application ACK를 받을 때까지 같은 `message_id`로 재전송한다. Gateway만
MySQL transaction을 수행한다.

```text
5080 durable queue
  -> HTTP + Idempotency-Key/message_id
  -> Gateway validation
  -> trihouse_recovery transaction
  -> ACK
  -> 5080 queue record 제거
```

Gateway가 commit 후 ACK를 보내는 동안 연결이 끊기면 5080은 같은 message ID를
재전송한다. Gateway는 기존 결과를 반환해야 하며 중복 row를 만들지 않는다. 같은 ID와
다른 payload hash는 conflict로 거절한다.

기존 episode UUID와 `(recovery_episode_uuid, step_no)` unique key를 업무 중복 방지에
사용한다. 현재 `recovery_steps`의 state URI와 reward component만으로는 기존
학습 코드가 필요한 `(state, skill, coord, reward, next_state, done)`을 복원할 수
있다고 보장할 수 없다. `002_recovery_learning_transitions.sql`에 실제 실행된
step과 1:1인 `recovery_learning_transitions`를 추가해 9차원 state, 5개 skill ID,
3차원 상대 action, reward, next state, done을 명시적으로 저장한다.

같은 migration에 application ACK의 message ID와 payload hash를 영속적으로 대조하는
recovery ingestion receipt를 추가한다. 001 baseline은 수정하지 않는다. 학습 export는
완료된 episode·step·transition을 join해 기존 offline trainer가 읽는 JSONL tuple로
변환하며 pickle을 정본으로 사용하지 않는다.

### 10.2 API

- `POST /internal/v1/recovery/episodes`: episode open
- `POST /internal/v1/recovery/episodes/{uuid}/steps`: 실행 step open/update
- `POST /internal/v1/recovery/episodes/{uuid}/close`: terminal episode
- `GET /internal/v1/recovery/episodes/{uuid}`: queue reconciliation
- batch export endpoint 또는 artifact job: offline replay export

Gateway는 device, job, step, source event, map revision, reference node가 FMS 원장과
일치하는지 검사한다. 서로 다른 database 사이 FK는 추가하지 않는다.

`recovery_steps`에는 실행된 행동만 넣는다. 운영자에게 제시됐지만 실행되지 않은 후보,
VLM raw response, filter report는 `operation_events`와 artifact URI/SHA-256으로 남긴다.

## 11. Compose와 Runtime

`compose.ai_5080.yaml`의 단일 placeholder entrypoint를 실제 추론 프로세스로 구체화한다.
초기 운영에서는 한 컨테이너 안에서 supervisor가 여러 프로세스를 숨기는 방식보다
상태를 개별 확인할 수 있는 서비스를 사용한다.

- segmentation/person/obstacle worker
- VLM+RL recovery runtime
- recovery queue sender

각 서비스는 동일한 read-only model/config mount와 필요한 GPU를 공유하되 queue sender는
GPU를 요구하지 않는다. 5080에는 MySQL 환경변수를 전달하지 않는다. RTSP는 4060
MediaMTX canonical URL을 사용하고 원본 영상 보존은 4060이 담당한다.
실물 Compose는 `model.vlm_rl.inference`의 entrypoint만 실행한다. 학습은 로봇이
정지한 별도 학습 profile에서 DB export artifact를 입력으로 명시적으로 실행한다.

필수 환경값은 다음과 같다.

```dotenv
FMS_GATEWAY_URL=http://192.168.0.9:8080
VISION_RTSP_BASE_URL=rtsp://viewer:***@192.168.0.9:8554
VLM_RL_EXECUTION_MODE=operator_approved
ROS_DOMAIN_ID=12
TRIHOUSE_AI_MODEL_DIR=/srv/trihouse/ai/models
TRIHOUSE_AI_ARTIFACT_DIR=/srv/trihouse/ai/artifacts
TRIHOUSE_AI_QUEUE_DIR=/srv/trihouse/ai/recovery_queue
```

비밀이 포함된 RTSP URL은 로그와 doctor 출력에서 마스킹한다.

## 12. `origin/dev_driving` 선택 이식

다음 코드는 순수 로직과 테스트 가능한 알고리즘으로 분해해 이식한다.

- `vlm_contract_to_rl_state.py`: state encoder 개념
- `tgrpo_sac_hierarchical_v2.py`: TGRPO·SAC 알고리즘
- `rl_candidate_group.py`: candidate group과 상대 좌표 제한
- `recovery_filters.py`: R0~R6 rule ID와 fail-closed 구조
- `geometric_6c_lite.py`: geometric rollout
- `nav2_costmap_query.py`: query adapter 계약
- `real_reward.py`: reward component 계산
- `replay_sampler.py`: outcome bucket sampling
- offline training scripts: DB export 입력 기반 학습
- VLM 비교 JSON: model 선정 근거와 test fixture

다음 항목은 그대로 이식하지 않는다.

- `orchestrate_fms_vlm_rl_drive.py`: untested stub과 직접 제어 경계
- `nav_recovery_executor.py`: 5080에서 Nav2 action을 직접 소유
- `safe_execute.py`: 비활성화된 safety gate
- `recovery_data_collector.py`: random state와 pickle-only 원장
- hard-coded IP, `/workspace` 절대경로, hard-coded goal
- 출처와 schema가 불명확한 pickle·MP4 결과를 운영 데이터로 사용

원본 파일을 통째로 복사한 뒤 수정하지 않는다. 먼저 새 package의 contract test를 쓰고
필요한 함수와 알고리즘을 작은 모듈로 옮긴다. branch의 실험 문서는 provenance 참고자료로
남기되 운영 준비 상태의 증거로 사용하지 않는다.

## 13. 오류 처리

- RTSP decode 실패: 검출 0건으로 위장하지 않고 stream unhealthy
- YOLO weight/checksum 불일치: worker readiness 실패
- VLM timeout/schema 오류: 후보 생성 금지, stop/wait와 운영자 경고
- RL checkpoint 미승인·불일치: runtime readiness 실패
- sensor snapshot stale: R0 fail, 실행 금지
- 후보 전부 탈락: 로봇 정지 유지, 운영자에게 filter reason 노출
- 승인 만료·sensor epoch 변경: 승인 폐기
- Pinky command validation 실패: 실행 없이 명시적 NACK
- Safety 지속 STOP·EMERGENCY: cancel, terminal 상태 기록, 재승인 요구
- Gateway 일시 실패: queue 보존 후 bounded backoff 재시도
- queue disk full: 새 recovery 실행 금지, 기존 로컬 안전 정지는 유지
- DB commit 성공·ACK 유실: 같은 message ID 재전송 후 기존 결과 ACK

## 14. 테스트와 완료 기준

### 14.1 순수 단위 테스트

- segmentation class mapping과 checksum
- 다중 track별 posture/FallMonitor 독립성
- obstacle/person 판단 불가 trigger hysteresis
- strict VLM schema와 timeout fallback
- 9차원 state 변환
- TGRPO/SAC checkpoint load와 candidate bounds
- R0~R6 fail-closed rule
- reward와 replay bucket
- persistent queue crash/restart, duplicate ACK, payload conflict

### 14.2 Gateway·DB 테스트

- operator approval 필수와 worker ID 기록
- stale assignment/map/sensor epoch 거절
- 동일 message ID 재전송 멱등 응답
- 다른 payload hash의 동일 ID conflict
- episode open, step lifecycle, terminal close transaction
- 실행하지 않은 candidate가 recovery step에 들어가지 않음
- 5080 서비스에 MySQL 환경변수와 DB network가 없음

### 14.3 ROS·Pinky 테스트

- recovery command parser와 fencing
- action type별 Nav2 action 변환
- recovery velocity가 `cmd_vel_nav`로만 들어감
- `/cmd_vel` 운영 publisher가 Safety Supervisor 하나뿐임
- STOP 지속 시 cancel, EMERGENCY 즉시 cancel, cancel ACK 반영
- 취소 후 새 승인 없이 자동 재실행하지 않음

### 14.4 End-to-End

1. RTSP frame에서 person/obstacle segmentation과 track을 확인한다.
2. 정상 Nav2 재계획에서는 VLM+RL이 시작되지 않는지 확인한다.
3. 판단 불가를 만들고 episode가 `AWAITING_OPERATOR_APPROVAL`에 도달하는지 확인한다.
4. 운영자 승인 전 Pinky에 recovery command가 가지 않는지 확인한다.
5. 승인 후 Pinky가 명령을 ACK하고 Nav2 action을 실행하는지 확인한다.
6. Safety Supervisor가 실제 `/cmd_vel`의 단일 publisher인지 확인한다.
7. 실행 중 장애물을 두어 STOP과 cancel이 일어나는지 확인한다.
8. Gateway ACK를 의도적으로 끊고 재전송해 DB 중복 row가 없는지 확인한다.
9. `recovery_episodes`와 실행한 `recovery_steps`의 모델·정책·지도 계보가 일치하는지
   확인한다.

정적 테스트 통과만으로 실물 준비 완료를 주장하지 않는다. 실물 이동 전 E-stop
운영자, 비어 있는 경로, 센서 freshness, sole `/cmd_vel` publisher, 카메라 수신을
확인한다.

## 15. 구현 순서

1. 폴더 이동과 import·문서·테스트 경로 정리
2. segmentation contract, 다중 tracking, person·obstacle worker 정리
3. `origin/dev_driving`의 VLM state·policy·filter 순수 로직 선택 이식
4. recovery DB migration, Gateway API, repository, persistent queue
5. Recovery Coordinator와 operator approval API
6. Pinky recovery command·Nav2 executor·Safety cancel 연동
7. 5080 Compose runtime과 healthcheck
8. simulation E2E
9. 운영자 감독 실물 recovery test
10. DB export와 offline training/checkpoint promotion

각 단계는 독립 테스트가 통과한 확인된 변경만 커밋한다. 현재 worktree의 다른 미커밋
변경을 함께 커밋하지 않는다.

## 16. 대체되는 이전 설계와 비범위

`docs/claude/2026-08-18-recovery-ingestion-design.md`의 Nav2 관측을 사후 분류하는
recorder 구상은 이 설계의 명시적인 VLM+RL episode·step·ACK 계약으로 대체한다. 기존
문서는 조사 기록으로 유지하지만 새 구현의 정본으로 사용하지 않는다.

이번 범위에서 다음은 하지 않는다.

- 운영자 없는 자율 recovery 실행
- VLM/RL의 `/cmd_vel` 또는 Nav2 직접 호출
- 5080의 MySQL 직접 연결
- 실제 사람 안전 인증 주장
- 데이터가 부족한 neural world model의 운영 배포
- 승인되지 않은 online RL 학습 결과의 즉시 실물 반영
- 원본 dataset·실측 artifact의 자동 삭제
