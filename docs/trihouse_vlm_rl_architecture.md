# Trihouse VLM + RL 아키텍처 코드 읽기 노트

> 목적: Trihouse의 VLM + RL 복구 흐름을 코드 근거로 이해하고, 이후 포트폴리오·LinkedIn·면접에서 **구현된 내용 / 검증된 내용 / 설계·계획**을 구분해 설명하기 위한 조사 노트다.
>
> 표기: 코드만 읽고 확인한 것은 `코드상 확인`, 실제 실행·측정한 것은 `실행 검증`, 아이디어만 있는 것은 `설계/계획`. 모든 사실에 `파일:함수` 를 남긴다.
>
> 2026-08-31 코드 기준. 경로는 `vision_ai/` 재구성 이후 기준이다. 짝 문서: 인지·낙상 쪽은 [obj_seg_n_person_fallen_detection_architecture.md](obj_seg_n_person_fallen_detection_architecture.md).
>
> **§7(본인 기여 범위)은 비워 두었다.** 내가 무엇을 했는지는 코드가 답할 수 없다.

## 0. 한 문장 요약

Nav2가 스스로 안전한 경로를 못 정한 예외에서만 VLM이 장면을 JSON으로 해석하고, 두 층 RL이 **허용된 5개 복구 skill과 반경 0.25 m 안의 작은 상대 이동**만 제안한다. 그 제안은 motion boundary → Gateway 사람 승인 → Nav2 계획 가능성 → 로봇 Safety Supervisor를 전부 통과해야 실제 움직임이 된다. 실행 결과는 보상과 함께 buffer에 남아 **오프라인으로만** 정책을 갱신한다.

---

## 1. 진입점과 파일

| 역할 | 파일 | 진입 함수/클래스 | 상태 |
| --- | --- | --- | --- |
| 검출(사람/장애물) | [detector.py](../vision_ai/models/perception/detector.py) | `Detector.detect` | 코드상 확인 |
| 트리거 판정 | [trigger.py](../vision_ai/robot/recovery/trigger.py) | `should_trigger_recovery` | 코드상 확인 |
| VLM 호출·프롬프트 | [vlm_interpreter.py](../vision_ai/models/recovery/vlm_interpreter.py) | `CONTRACT_PROMPT_TEMPLATE`, `QwenVlmInterpreter.interpret` | 코드상 확인 |
| JSON 파싱·스키마 검증 | [vlm_interpreter.py](../vision_ai/models/recovery/vlm_interpreter.py) · [worker.py](../vision_ai/robot/recovery/worker.py) | `parse_json_response` · `_validated_worst_observation` | 코드상 확인 |
| VLM → RL 상태 변환 | [worker.py](../vision_ai/robot/recovery/worker.py) | `RecoveryInferenceWorker.process` | 코드상 확인 |
| 정책망 | [policy_architecture.py](../vision_ai/models/recovery/policy_architecture.py) | `HighLevelPolicy` · `LowLevelPolicy` · `TwinQ` | 코드상 확인 |
| 후보 생성 | [candidate_generator.py](../vision_ai/robot/recovery/candidate_generator.py) | `sample_candidate_group` | 코드상 확인 |
| 승인된 체크포인트 적재 | [policy_runtime.py](../vision_ai/robot/recovery/policy_runtime.py) · [checkpoint.py](../vision_ai/models/recovery/checkpoint.py) | `ApprovedPolicyRuntime` · `load_checkpoint` | 코드상 확인 |
| distilled skill selector | [distilled_selector.py](../vision_ai/models/recovery/distilled_selector.py) | `DistilledSelectorGate` | 코드상 확인 |
| 안전 경계(정규화) | [motion_plan.py](../vision_ai/utils/motion_plan.py) | `canonicalize_recovery_action` | 코드상 확인 |
| Gateway 제안 | [proposal_client.py](../vision_ai/robot/recovery/proposal_client.py) | `GatewayProposalClient` | 코드상 확인 |
| 보상·전이 생성 | [completion_runtime.py](../vision_ai/robot/recovery/completion_runtime.py) | `_real_reward` · `build_completion` | 코드상 확인 |
| 유실 없는 전송 | [memory/](../vision_ai/robot/recovery/memory/) | `queue.py` · `sender.py` | 코드상 확인 |
| 오프라인 학습 | [offline_train.py](../vision_ai/models/recovery/trainer/offline_train.py) | `train` | 코드상 확인 |
| 학습 수식 | [algorithms.py](../vision_ai/models/recovery/trainer/algorithms.py) | `tgrpo_update_from_buffer` · `SACAgent.update` | 코드상 확인 |
| 위험도별 샘플링 | [replay_sampler.py](../vision_ai/data_loader/recovery/replay_sampler.py) | `BucketedReplaySampler` | 코드상 확인 |
| 로봇 최종 gate | [policy.py](../trihouse_pinky/trihouse_pinky_safety/trihouse_pinky_safety/policy.py) | `apply_safety_gate` | 코드상 확인 |

---

## 2. End-to-End 흐름

```text
RGB 프레임 ─▶ Detector.detect ─▶ should_trigger_recovery
                                        │ (사람/장애물 있고 AND Nav2가 못 정함)
                                        ▼
                        QwenVlmInterpreter.interpret  → JSON
                                        │
                        _validated_worst_observation  → 최고 위험 1건
                                        ▼
                              RecoveryStateV1 (9D)
                                        │
                    ┌───────────────────┴───────────────────┐
              HighLevelPolicy.sample(k=3)          DistilledSelectorGate (선택)
              → skill 3개                          → 확신할 때만 skill 지정
                    │
              LowLevelPolicy.sample(m=2) → skill 당 좌표 2개  = K×M = 6 후보
                                        ▼
                     canonicalize_recovery_action  ← 반경 0.25 m / ±60° 클램프
                                        │  (통과한 후보만)
                                        ▼
                     GatewayProposalClient.create → 사람 승인 대기
                                        ▼
                          Nav2 계획 가능성 + Safety Supervisor
                                        ▼
                                     실행
                                        │
                     build_completion → reward, next_state
                                        ▼
                     RecoveryMemory queue → Gateway → DB
                                        ▼
                        offline_train (운영 중 학습 없음)
```

| 단계 | 입력 | 출력 | 파일:함수 |
| --- | --- | --- | --- |
| 1. 트리거 | 검출 목록 + `NavigationContext` | bool | `trigger.py:should_trigger_recovery` |
| 2. VLM | 프레임 + 검출 텍스트 + goal | JSON dict | `vlm_interpreter.py:interpret` |
| 3. 상태 | 최고 위험 관측 + pose | 9-tuple | `worker.py:process` |
| 4. 후보 | 9D state | K×M 후보 | `candidate_generator.py:sample_candidate_group` |
| 5. 경계 | (skill, coord, pose) | `CanonicalRecoveryAction` 또는 `ValueError` | `motion_plan.py:canonicalize_recovery_action` |
| 6. 제안 | proposal dict | Gateway 응답 | `proposal_client.py:create` |
| 7. 보상 | pre/next state + 실행 결과 | reward + 전이 | `completion_runtime.py:build_completion` |

---

## 3. VLM: 무엇을 보고, 무엇을 말하는가

### 3-1. 호출 조건 — 코드상 확인

```python
relevant   = 검출에 person 또는 obstacle 이 있는가
undecidable = navigation_state ∈ {failed, stuck, undecidable}  OR  stuck_seconds ≥ 3.0
trigger = relevant AND undecidable
```

**AND 인 것이 핵심이다.** 사람이 보이기만 해서는 안 부르고, Nav2가 막힌 것만으로도 안 부른다. VLM은 초당 수 회 돌릴 수 없는 비용(7B 4-bit 기준 쿼리당 수 초)이라, 일상 주행이 아니라 **예외에만** 붙는다.

> 발표 자료의 트리거 조건(정체 ≥10초 OR 초음파 근접 OR 추적 급변)과 코드의 3.0초 기본값이 다르다. `stuck_threshold_seconds` 는 인자이므로 호출부에서 바꿀 수 있다 — 어느 값이 운영값인지는 [확인 필요].

### 3-2. 입력 — 코드상 확인

프레임 한 장 + 검출을 **텍스트로 요약한 것**이다. 좌표를 그대로 주지 않고 9분할 위치어로 바꾼다 (`build_detections_text`):

```
- person: MIDDLE-RIGHT region, confidence 0.80
- obstacle: TOP-CENTER region, confidence 0.88
```

가로는 1/3·2/3 기준 LEFT/CENTER/RIGHT, 세로는 TOP/MIDDLE/BOTTOM.

### 3-3. 출력 계약(JSON) — 코드상 확인

`CONTRACT_PROMPT_TEMPLATE` 이 스키마를 프롬프트에 박아 넣는다.

| 필드 | 허용값 | 검증 위치 |
| --- | --- | --- |
| `observations[].semantic_label` | `person` · `obstacle` · `unknown_dynamic` | `worker.py:_validated_worst_observation` |
| `observations[].risk` | `low` · `moderate` · `critical` | 같음 |
| `observations[].bbox_norm` | 길이 4, 각 0..1 | 같음 |
| `observations[].confidence` | 0..1 | 같음 |
| `robot_candidate_sectors[]` | angle_deg · width_deg · preference | 파싱만, state 에 안 들어감 |
| `uncertainty` | 유한수 0..1 | `worker.py` |

**주의 깊게 쓰인 프롬프트 한 줄**: `robot_candidate_sectors` 는 "로봇이 갈 수 있는 방향"이지 "물체가 가는 방향"이 아니라고 명시한다. 이 구분이 없으면 VLM이 반대로 답한다.

### 3-4. 실패 처리 — 코드상 확인

- 정규식 `\{.*\}` 로 첫 JSON 블록만 뽑는다 → 모델이 앞뒤에 말을 붙여도 견딘다.
- 파싱 실패 → `None`.
- 스키마 위반이 **하나라도** 있으면 `_validated_worst_observation` 이 `None` → `process` 가 곧바로 반환하고 **제안을 만들지 않는다.**
- 즉 VLM이 이상하게 답하면 복구가 조용히 잘못 도는 게 아니라 **아무 일도 일어나지 않는다.**

여러 관측 중 하나를 고르는 기준: `(risk 순위, confidence)` 최대값. risk 는 `low<moderate<critical`.

---

## 4. RL: 무엇을 선택하고, 무엇을 선택하지 않는가

### 4-1. 상태(state) — 코드상 확인

`RecoveryStateV1` ([contracts.py](../vision_ai/utils/contracts.py)), 고정 9차원. `state_schema_id = "trihouse.recovery-state.v1"`.

| # | 항목 | 출처 | 전처리·검증 |
| --- | --- | --- | --- |
| 1-3 | `robot_x/y/yaw` | `NavigationContext.robot_pose` (Gateway) | 유한수만 |
| 4-5 | `goal_x/y` | `NavigationContext.goal_pose` | 유한수만 |
| 6-7 | `risk_bbox_center_x/y_norm` | 최고 위험 관측 bbox 중심 | **0..1 강제** |
| 8 | `risk_confidence` | 그 관측의 confidence | **0..1 강제** |
| 9 | `vlm_uncertainty` | VLM `uncertainty` | **0..1 강제** |

**메모에 대한 답 — 최고 위험 객체 하나만 쓴다.** 다중 객체 관계는 state 에 안 들어간다. 표현 한계이자 의도된 단순화다: 9차원이 고정 계약이라 DB 컬럼·Gateway 검증·체크포인트 호환이 전부 여기 묶여 있고, 차원을 늘리면 그 넷이 동시에 깨진다. 대신 관측 **전부**는 `perception_evidence` 로 제안에 실려 사람이 본다.

범위를 벗어나면 `__post_init__` 이 `ValueError` — 잘못된 state 로 학습이 오염되지 않는다.

### 4-2. 행동(action) — 코드상 확인

**두 층으로 나뉜다.**

- `HighLevelPolicy` (9 → 64 → 64 → 5): **discrete skill 5개** 중 선택. `Categorical.sample((k,))` 로 K개 뽑는다.
- `LowLevelPolicy` (9+5 → 128 → 128 → mean/log_std): 그 skill 조건에서 **연속 좌표 (dx, dy, dyaw)** 를 tanh-squash 로 낸다. `COORD_SCALE = 2.0`.

allowlist는 정확히 5개다 (`SKILL_NAMES`):

| id | skill | action_family | 정규화 결과 |
| --- | --- | --- | --- |
| 0 | `BACKUP` | retreat | 후진 거리만 (`coord = (-d, 0, 0)`) |
| 1 | `REROUTE_LEFT` | detour | heading > 0 이어야 함 — 아니면 `ValueError` |
| 2 | `REROUTE_RIGHT` | detour | heading < 0 이어야 함 — 아니면 `ValueError` |
| 3 | `WAIT_REOBSERVE` | wait | `coord = (0,0,0)`, 1.0초 |
| 4 | `REJOIN` | rejoin | map 좌표 목표로 변환 |

**연속 명령을 직접 내지 않는가 — 안 낸다.** `canonicalize_recovery_action` 이 유일한 표현이고 거기서:

- 평면 이동은 `ENVELOPE_RADIUS_M = 0.25` 로 **크기 클램프**
- 회전은 `YAW_LIMIT_RAD = π/3` (±60°) 로 클램프
- skill 과 방향이 모순이면 (예: `REROUTE_LEFT` 인데 우측 heading) 후보를 **버린다**

저장소 어디에도 `/cmd_vel` 발행이 없다. 최종 속도는 로봇 쪽 `apply_safety_gate` 만 정한다.

### 4-3. 보상(reward) — 코드상 확인

`completion_runtime.py:_real_reward`. 실행이 **끝난 뒤** 실측값으로 계산한다.

```
R = Δd_goal − 5·max(0, 0.3 − d_obs)² − 2·I − 0.1·t + 10·1(rejoined)
terminal:  d_obs < 0.085 m  →  R = −100  (즉시 종료)
```

| 항목 | 값/식 | 의도 | 근거 |
| --- | --- | --- | --- |
| 진행 | `Δd_goal` = 전 거리 − 후 거리 | 목표에 가까워질수록 보상 | `_distance_to_goal` |
| 여유거리 | `−5·max(0, 0.3−d_obs)²` | 0.3 m 밖이면 벌점 0, 가까울수록 **제곱으로** 급증 | `clearance_cost` |
| 사람 개입 | `−2·I` | 개입 = "정책이 실패했다"는 신호 | `safety_intervened` |
| 시간 | `−0.1·t` | 안전한 선택지 중 더 빠른 쪽 선호 | `elapsed_seconds` |
| 복귀 | `+10` if `d_goal < 0.15 m` | recovery 목적은 회피가 아니라 **복귀** | `MISSION_REJOINED_THRESHOLD_M` |
| 충돌급 | `R = −100`, `done=True` | 로봇 몸체 반지름 0.06 m + 여유 | `TERMINAL_CRITICAL_DIST_M` |

**절벽형이 아니라 제곱 곡선인 이유**: 경계 근처에서 값이 급변하면 학습이 흔들린다. 여유가 있을 땐 자유롭게, 위험할수록 부드럽지만 강하게 밀어낸다.

`clearance_after_m` 이 음수거나 비유한수면 `ValueError` — 관측 없이 만든 보상은 학습에 안 들어간다.

### 4-4. 학습과 추론의 구분 — 코드상 확인

**운영 중 학습은 없다.** `offline_train.py` 첫 줄이 그것을 명시한다: *"physical robot Compose never invokes this module."* 그리고 로봇 이미지에 trainer 가 안 들어가는 것을 [test_inference_boundary.py](../vision_ai/tests/recovery/test_inference_boundary.py) 와 `Dockerfile.inference` COPY 목록이 강제한다.

**High-level (Tuned-TGRPO)** — `tgrpo_update_from_buffer`:

1. buffer 전체를 **skill 별로 묶어** 평균 reward 를 낸다. 개별 배치가 아니라 skill 그룹의 population 통계다.
2. 데이터가 있는 skill 이 2개 미만이면 **업데이트를 건너뛴다** — 비교 대상이 없으면 상대비교가 성립하지 않는다.
3. advantage = `(r − mean) / (std + 1e-6)` (`ADVANTAGE_STD_NORM = True`)
4. **PPO 형 clipped surrogate** (`CLIP_EPSILON = 0.2`) + **KL penalty** (`KL_COEF = 0.01`) + entropy 보너스 (`ENTROPY_COEF = 0.01`)

원본 TGRPO 대비 3·4가 추가분이다. **실행 검증(발표 자료)**: entropy 보너스만으로는 소량 데이터에서 policy 가 한쪽으로 쏠려 1.59 → 0.28 로 붕괴했고, clip + KL 을 넣어 1.59 → 1.52 로 유지, KL 0.02~0.05, clip_ratio 0.93~0.98 을 확인했다.

`USE_DAPO_STYLE` (비대칭 clip 0.2/0.28 + reward std 하한으로 dynamic sampling) 는 코드에 있으나 **기본 꺼짐**이다.

**Low-level (SAC)** — `SACAgent.update`: twin Q + target network(`tau=0.005`) + 자동 온도 조절(`log_alpha`, `target_entropy`). `use_cql=True` 면 CQL 항이 critic loss 에 더해진다(오프라인 RL 에서 분포 밖 행동의 Q 과대평가를 억제) — **기본 꺼짐**.

**샘플링** — `BucketedReplaySampler`: 전이를 `SAFE / BOUNDARY / CRITICAL` 로 나눠 목표 비율 `0.5 / 0.3 / 0.2` 로 강제 혼합한다. 위험한 순간은 드물어서 무작위로 뽑으면 표본에 거의 안 걸린다. 버킷 판정은 `terminal_critical` 이면 CRITICAL, 아니면 margin < 0.2 이면 BOUNDARY. 중요도 가중치는 `exp(−나이/3600s) / √(zone별 개수)` — 최근 것과 드문 zone 을 올린다.

**최소 데이터**: `MIN_TRANSITIONS_TO_TRAIN = 4` 미만이면 `ValueError`.

### 4-5. distilled skill selector — 코드상 확인

`HighLevelPolicy` 만 따로 지도학습으로 재현한 결과물이다. 6C-Lite 후보평가를 soft teacher 로 쓴다.

- 5-seed 앙상블. **만장일치 top1 AND 평균 entropy ≤ 1.5** 일 때만 학습 selector 를 신뢰하고, 아니면 기존 방식으로 fallback.
- 그 판단은 **이미 motion boundary 를 통과한 후보 중에서만** 승자를 바꾼다 — 안전 필터가 버린 동작을 되살릴 수 없다.
- 번들이 `state_dim`/`n_skills`/`skill_names` 계약과 다르면 적재 거부.
- **실행 검증(발표 자료)**: 앙상블 정확도 40.2%(random 20%의 2배), 실측 58% 신뢰 / 42% fallback.
- 기본 **꺼짐** — `RECOVERY_SELECTOR_ENSEMBLE` + `RECOVERY_SELECTOR_SHA256` 둘 다 있어야 켜진다.

---

## 5. 안전과 실행 권한

| 구성요소 | 담당 권한 | 하면 안 되는 것 | 코드 근거 |
| --- | --- | --- | --- |
| VLM | 장면 해석, 위험 등급, 여유 방향 제안 | 좌표·속도 생성 | 출력이 JSON 스키마로 고정 (`CONTRACT_PROMPT_TEMPLATE`) |
| RL | 5개 skill + 반경 0.25 m 상대 이동 제안 | 안전 우회, 직접 주행 | `motion_plan.py:canonicalize_recovery_action` |
| motion boundary | 후보를 유일한 표현으로 정규화·거부 | 검증 없는 목표 전달 | 같음 — 모순 후보는 `ValueError` |
| Gateway | 사람 승인, 계약 검증, 기록 | 승인 없이 전달 | `recovery_routes.py` · `RecoveryProposalCreate(extra="forbid")` |
| Nav2 | 경로 계획·추종·costmap | 최종 안전 판단 대체 | 계획 불가면 후보 탈락 |
| Safety Supervisor | 최종 stop/slow | VLM/RL 로 권한 이관 | `policy.py:apply_safety_gate` |

### 즉시 중단 경로 — 코드상 확인

`apply_safety_gate` 는 **위에서부터 순서대로** 끊는다. 앞이 걸리면 뒤는 보지 않는다.

```
1. emergency_latched      → EMERGENCY, 목표도 취소
2. control_link 끊김      → STOP (관제 대조 전까지 주행 안 함)
3. sensor stale           → STOP
4. keep_out zone          → STOP
5. swept_blocked          → STOP (제자리 회전이 쓸고 갈 범위)
6. front_distance ≤ 0.05  → STOP
7. 보호거리 안 + 쓰러진 사람 → STOP  ← pose_class 기반
8. 보호거리 안 + 사람     → SLOW (0.08 m/s)
9. 그 외                  → CLEAR
```

**VLM/RL 을 거치지 않는다.** 이 함수는 로봇 안에서 매 제어 주기 돌고 입력이 라이다·초음파·카메라 관측이다. 7번이 이번에 추가된 경로다(§ 인지 문서 참고).

물리 실행에는 추가로 `VLM_RL_EXECUTION_MODE=operator_approved` 가 필요하다.

---

## 6. Recovery Memory / Offline Buffer

### 저장 단위 — 코드상 확인

**transition 단위**다. `(state, skill, coord, reward, next_state, done, meta)` 7필드 고정.

- 만드는 곳: `completion_runtime.py:build_completion` — 실행이 **완료된 뒤**
- 보내는 곳: `memory/queue.py` (fsync 기반 pending 큐) → `memory/sender.py` (재시도)
- 최종 저장: Gateway → MySQL `recovery_learning_transitions` (migration `003`)
- 학습이 읽는 형식: `recovery_transitions.jsonl` (`data_loader/recovery/dataset.py:load_training_jsonl`)

**fsync 큐를 쓴 이유**: ACK 를 못 받아도 학습 데이터가 사라지면 안 된다. ACK 가 일치할 때만 큐에서 지운다.

### 저장 필드 — 코드상 확인

| 필드 | 저장되는가 | 용도 |
| --- | --- | --- |
| trigger reason | ✅ `proposal.trigger_type` (`blocked`/`person`/…) | 어떤 예외였는지 |
| VLM 파싱 JSON | ✅ 관측 전체가 `perception_evidence` | 사람이 판단 근거를 봄 |
| VLM 원문 | ❌ | 파싱본만 남는다 |
| state | ✅ 9D + `state_schema_id` | 학습 입력 |
| candidate/action | ✅ `candidate_evidence` (탈락 사유 포함) | 왜 그 후보가 이겼는지 |
| reward | ✅ + `reward_components` 분해 | 학습 신호 |
| post-observation | ✅ `next_state` | 학습 입력 |
| Safety/Nav2 거부 사유 | ✅ `candidate_evidence[].reason` | 경계가 실제로 작동했는지 |
| skill_selection | ✅ (migration `005`) | distilled selector fallback 비율 |

### 학습 오염 방지 — 코드상 확인

`validate_transition` 이 `meta.is_execution is not True` 면 거부한다. **관찰 전용, 거절된 제안, VLM 미확정 응답은 학습에 안 들어간다.**

### 재사용 범위

- 사후 분석: ✅ DB 에 남음 — 코드상 확인
- offline RL 재학습: ✅ `offline_train.py` — 코드상 확인 (이 저장소에서 실행하진 않음)
- 유사 예외 retrieval: ❌ 없음 — **설계/계획**

---

## 7. 본인 기여 범위

> 여기는 코드가 답할 수 없다. 아래 표는 자리만 만들어 둔 것이고, 채우는 것은 본인 몫이다.
> 채울 때 근거로 쓸 수 있는 것: `git log --author="$(git config user.email)" --oneline -- vision_ai/`

| 유형 | 내 기여 | 관련 파일·커밋 | 증거 수준 |
| --- | --- | --- | --- |
| 아키텍처 설계 | | | |
| VLM prompt/schema | | | |
| RL state/action/reward 설계 | | | |
| Recovery Memory 설계 | | | |
| 코드 작성·수정 | | | |
| 테스트·데모·측정 | | | |

---

## 8. 검증 현황: 주장 가능한 범위

| 항목 | 확인된 증거 | 아직 말하면 안 되는 주장 |
| --- | --- | --- |
| VLM JSON 계약 | 스키마 위반 시 제안을 안 만든다 — 단위 테스트 | 실제 현장에서 항상 올바른 해석을 낸다 |
| RL 정책 | 망 구조·후보 생성·경계 클램프가 테스트로 고정됨 | 현장 최적화됨 / 안전이 보장됨 |
| Tuned-TGRPO | entropy 붕괴 → clip+KL 로 1.52 유지 (30샘플·250epoch, 발표 자료) | 일반적으로 수렴한다 / 데이터가 충분하다 |
| distillation | 앙상블 40.2%, 58% 신뢰·42% fallback (발표 자료) | 이 저장소에서 재현함 |
| motion boundary | 반경·각도 클램프, 모순 후보 거부가 테스트로 고정됨 | 모든 장애물·예외에 대응한다 |
| Safety 연동 | `apply_safety_gate` 우선순위가 테스트로 고정됨 | E-stop 을 대체하거나 인증됨 |
| Recovery Memory | 계약 검증·유실 없는 큐가 테스트로 고정됨 | 장기 성능 향상이 검증됨 |

**수치의 출처를 반드시 구분할 것.** entropy·40.2%·58/42% 는 팀 발표 자료의 보고값이고 이 저장소에서 재현하지 않았다. 이 저장소에서 실행 검증된 것은 단위 테스트 수준의 계약·경계·상태전이다.

---

## 9. 문장 재료

### 구현·검증된 경우

> I implemented the recovery proposal boundary, which translates a VLM scene reading and a two-level RL policy into a bounded relative motion of at most 0.25 m, while human approval, Nav2 planning and the robot's safety supervisor retain final execution authority.

### 아키텍처를 설계·기여한 경우

> I contributed to the architecture for exception recovery in a multi-robot warehouse, designing a frozen nine-value state contract and a five-skill action allowlist so that recovery can be proposed without granting direct motion authority to the model.

### 계획 단계인 경우

> I explored a recovery-memory design that records only actually executed transitions with their reward decomposition, intended for offline policy updates rather than online learning on the robot.

---

## 10. 읽기 완료 체크

- [x] 이벤트 트리거부터 post-observation 까지 호출 순서를 파일·함수명과 함께 설명할 수 있다 (§2)
- [x] VLM 의 입력·출력 JSON·실패 처리를 설명할 수 있다 (§3)
- [x] RL 의 state, action, reward 와 TGRPO/SAC 의 역할을 구분할 수 있다 (§4)
- [x] VLM/RL 이 raw `/cmd_vel` 을 내보내지 않는 이유와 Nav2/Safety 의 권한을 설명할 수 있다 (§4-2, §5)
- [x] Recovery Memory 의 구현 범위와 계획 범위를 구분할 수 있다 (§6)
- [ ] 내 기여와 팀의 기여를 파일·커밋 근거로 나눠 말할 수 있다 (§7 — 본인이 채울 것)
- [x] 실행 검증 결과와 설계 제안을 혼동하지 않는다 (§8)

## 11. 남은 확인 필요

- 운영에서 쓰는 트리거 임계값 — 코드 기본 3.0초 vs 발표 자료 10초 (§3-1)
- `use_cql` 를 켠 학습을 실제로 돌렸는지 (코드상 기본 꺼짐)
- 발표 자료의 6C-Lite(R0–R6, n=8 스텝) 구현체가 이 저장소에 있는지 — `motion_plan.py` 는 단일 후보 클램프만 하고 경로 분할 검사는 없다
