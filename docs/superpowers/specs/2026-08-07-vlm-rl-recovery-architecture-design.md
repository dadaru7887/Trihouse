# Trihouse VLM + RL 위험·예외 복구 아키텍처 설계

- 작성일: 2026-08-07
- 대상: 실제 Pinky-Pro, Trihouse 임의 제작 map, ROS 2/Nav2
- 상태: 설계 명세 — 3개 미결정 항목은 문서 마지막에 명시
- 원칙: **Trigger 시 먼저 완전 정지하고, 검증된 짧은 복구 좌표 하나만 Nav2에 제안한다.**

## 1. 결론부터: 각 구성요소의 역할

이 시스템은 VLM이나 RL이 로봇을 직접 운전하게 만들지 않는다. 평상시에는 기존과 같이 FMS/Fleet Adapter가 Nav2에 임무 목표를 주고, Nav2가 경로를 계획하며, Safety Supervisor가 실제 속도 명령을 마지막으로 검사한다. 위험·예외 Trigger가 발생하면 로봇을 완전히 정지시킨 뒤 VLM, Memory, TGRPO, SAC가 **위험에서 벗어나기 위한 짧은 복구 좌표 후보**를 만든다. 모든 후보를 규칙과 가상 rollout으로 검사하고, 우승한 좌표도 최신 센서로 다시 검사한다. 그 좌표는 Fleet Adapter를 통해 Nav2에 전달되며, Nav2가 실제 경로를 다시 만들고 Safety Supervisor가 움직임을 허가하거나 정지시킨다.

쉽게 비유하면 다음과 같다.

- VLM은 “화면에서 무엇이 문제이고 어느 쪽이 덜 막혔는가”를 읽는 관찰자다.
- Reference Memory는 관리자가 확인한 도로 지도다.
- Episodic Memory는 로봇이 실제로 겪은 운행 일지다.
- TGRPO는 “후진, 좌측 우회, 대기 후 재관찰”처럼 **어떻게 벗어날지**를 고른다.
- SAC는 선택한 방법 안에서 **어느 좌표로 갈지**를 제안한다.
- 6C-Lite는 실제로 움직이지 않고 각 좌표의 가까운 미래를 짧게 시험한다.
- Nav2는 채택된 좌표까지 실제로 갈 수 있는 경로를 만드는 최종 경로 의사결정자다.
- Safety Supervisor는 실제 모터로 전달될 속도를 허가·감속·정지하는 최종 움직임 의사결정자다.

따라서 권한은 다음 한 문장으로 정리된다.

> **VLM + RL은 좌표를 추천하고, Nav2는 경로를 결정하며, Safety Supervisor는 실제 움직임을 허가한다.**

### 범위에 포함되는 것

- YOLO 모호성, 미지 객체, 센서 불일치, Nav2 진행 불가에 대한 복구 Trigger
- 완전 정지 후 짧은 복구 waypoint `(x, y, yaw)` 추천
- Reference/Episodic Memory 스키마와 현재성 갱신
- 후보의 0~6단계 필터, 6C-Lite 가상 rollout, RL sampler
- TGRPO 상위 정책과 SAC 하위 좌표 정책
- Fleet Adapter/Nav2/Safety Supervisor 연동과 검증 전략

### 범위에서 제외되는 것

- VLM/RL이 `/cmd_vel`을 직접 발행하는 것
- 복구 모듈이 Nav2 action client를 별도로 소유하는 것
- 의미 인식 결과만으로 비상정지를 보장하는 것
- 운행 중 RTX 5080에서 모델 학습과 운영 추론을 동시에 수행하는 것
- 검증되지 않은 Candidate 모델이 실제 로봇을 즉시 제어하는 것

## 2. 전체 아키텍처

```text
평상시
FMS ──> Fleet Adapter(유일한 Nav2 goal owner) ──> Nav2
                                                     │ /cmd_vel_nav
                                                     ▼
센서 ──> Safety Supervisor ──────────────────────> /cmd_vel ──> Pinky-Pro
          CLEAR / SLOW / STOP / EMERGENCY

위험·예외
YOLO·센서·Nav2 상태
        │
        ▼
Composite Trigger ──> Recovery epoch 발급 ──> 완전 STOP latch
                                              │
                         0속도 확인 + 기존 goal cancel ACK
                                              ▼
                              동기화된 센서 snapshot
                                              │
                   ┌──────────────────────────┼─────────────────────────┐
                   ▼                          ▼                         ▼
           VLM + LoRA                    Memory 검색               Recovery Envelope
       RGB/segmentation/track      Reference Node·Edge          map·pose·costmap·TF
       객체 위치·위험·후보각도     Safe/Boundary/Critical       footprint·keep-out
                   └──────────────────────────┼─────────────────────────┘
                                              ▼
                         후보 생성: Memory + TGRPO Top-K + SAC M개
                                              ▼
                      [0~3] 생성 시 1회 검사 + hard veto
                                              ▼
                  [4~5] 6C-Lite 전 후보 n-step 가상 rollout
                     경로·footprint·동적 장애물·불확실성
                                              ▼
                        사전식(lexicographic) 후보 Tournament
                                              ▼
                          우승 좌표 하나 (x, y, yaw)
                                              ▼
                     [6] 최신 snapshot으로 2~5 전체 재검사
                                              ▼
                Recovery Coordinator ──> Fleet Adapter ──> Nav2
                                              │               │
                                         goal/epoch       실제 재계획
                                                              ▼
                                          Safety Supervisor 최종 허가
                                                              ▼
                         짧게 실행 ──> 정지·재관찰 ──> 반복/임무 재합류
                                                              ▼
                                         Episode/Step/Outcome 갱신
```

새 ROS 2 패키지 `trihouse_pinky_recovery`는 Trigger 집계, 복구 상태기계, Memory API client, 후보 생성·필터, predictive tournament, 모델 버전 관리를 담당한다. 이 패키지는 `/cmd_vel`을 발행하지 않으며 Nav2 goal도 직접 소유하지 않는다.

## 3. Trigger와 완전 정지 상태기계

### 3.1 Composite Trigger

\[
T_{VLM}=T_{hard}\lor T_{ambiguity}\lor T_{disagreement}\lor T_{navigation}
\]

- `T_VLM`: VLM 복구 절차를 시작할지 나타내는 최종 신호다.
- `T_hard`: LiDAR 최소거리, bumper, emergency zone처럼 즉시 정지가 필요한 신호다.
- `T_ambiguity`: YOLO confidence가 낮거나 class가 불안정한 상태가 N-of-M 프레임 동안 지속되는 신호다.
- `T_disagreement`: YOLO, segmentation, LiDAR/depth가 서로 맞지 않는 신호다.
- `T_navigation`: Nav2 stuck, oscillation, 반복 replanning, progress timeout 신호다.
- `\lor`: 네 조건 중 하나라도 참이면 Trigger가 켜진다는 뜻이다.

단순히 `YOLO confidence < threshold`만 쓰면 조명 변화나 한 프레임 흔들림에도 VLM이 자주 호출된다. 따라서 hard 신호는 즉시 반응하고, 모호성은 N-of-M 프레임과 진입·해제 threshold가 다른 hysteresis를 사용한다. 학습하지 않은 객체는 YOLO가 정확한 이름을 맞히게 요구하지 않는다. **낮은 confidence, 불일치, 설명되지 않은 depth/segmentation 영역을 unknown obstacle로 표시하고 먼저 점유 공간으로 취급**한다. VLM은 그 뒤에 “사람과 비슷함”, “바닥 위 이동 가능한 물체”, “정체 불명 장애물”처럼 의미와 위험도를 보조한다.

### 3.2 Recovery lease/state machine

```text
NORMAL
  └─ Trigger → STOP_LATCHED
STOP_LATCHED
  └─ 실제 속도 0 확인 → CANCEL_MISSION_GOAL
CANCEL_MISSION_GOAL
  └─ Fleet Adapter cancel ACK → SNAPSHOT
SNAPSHOT
  └─ 같은 timestamp 범위의 RGB/seg/LiDAR/pose/costmap 확보 → REASONING
REASONING
  └─ 후보 생성·가상검사 → WINNER_REVALIDATION
WINNER_REVALIDATION
  ├─ 통과 → AUTHORIZE_ONE_GOAL
  └─ 실패/timeout/OOM → STOP_AND_REPORT
AUTHORIZE_ONE_GOAL
  └─ epoch가 붙은 복구 goal 1개만 Fleet Adapter가 Nav2에 제출 → EXECUTING
EXECUTING
  ├─ waypoint 도착 → STOP_REOBSERVE
  ├─ 새로운 Trigger/lease 위반 → STOP_AND_CANCEL
  └─ 임무 경로 재합류 → NORMAL
```

각 Trigger마다 증가하는 `recovery_epoch`를 발급한다. 센서 결과, VLM 결과, 후보, Nav2 goal은 모두 같은 epoch를 가져야 한다. 늦게 도착한 이전 epoch의 추론 결과는 폐기한다. 이를 통해 “취소 중인 옛 goal과 새 복구 goal이 동시에 살아 있는 문제”를 막는다.

완전 정지는 명령만 0으로 쓰는 것이 아니라 다음 네 조건을 모두 만족해야 한다.

1. Safety Supervisor의 STOP latch가 활성화되어 있다.
2. wheel odometry의 선속도·각속도가 정지 threshold 아래에서 정해진 시간 유지된다.
3. Fleet Adapter가 기존 Nav2 goal cancel을 확인했다.
4. 정지 이후 timestamp의 센서 snapshot이 준비되었다.

## 4. VLM 입력과 출력 계약

### 4.1 입력

- RGB 영상 프레임: 단일 또는 연속 프레임 방식은 D25에서 결정
- 같은 시점의 segmentation map
- YOLO detection/track 요약: bbox, class, confidence, track velocity, age
- 로봇 pose와 covariance, LiDAR/depth 요약, 현재 임무 방향
- VLM은 위험·예외 시에만 3B 또는 7B 4-bit 모델을 load/infer하고 LoRA adapter를 적용

VLM 출력은 자유문장이 아니라 검증 가능한 JSON으로 제한한다.

```json
{
  "observations": [
    {
      "region_id": "r3",
      "bbox_norm": [0.62, 0.08, 0.91, 0.74],
      "semantic_label": "person_or_unknown_dynamic",
      "risk": "critical",
      "confidence": 0.78,
      "motion_evidence": "track_summary"
    }
  ],
  "robot_candidate_sectors": [
    {"angle_deg": -90, "width_deg": 25, "preference": 0.73},
    {"angle_deg": 180, "width_deg": 20, "preference": 0.61}
  ],
  "uncertainty": 0.28
}
```

여기서 `bbox_norm`은 영상 너비·높이를 0~1로 정규화한 객체 위치이고, `robot_candidate_sectors`는 **객체의 이동 방향이 아니라 로봇이 복구를 시도할 화면상 방향**이다. pixel 결과를 calibration, TF, LiDAR/depth association으로 `base_link`와 `map` 좌표에 투영한다. association confidence가 낮거나 critical 객체가 3D 센서와 연결되지 않으면 해당 시야 부채꼴을 비어 있다고 가정하지 않고 보수적으로 occupied 처리한다.

VLM은 metric 좌표를 직접 생성하지 않는다. 최종 `(x,y,yaw)`는 Reference 좌표, 로봇 좌표계의 bounded offset, map/TF 변환, SAC가 함께 생성한다.

## 5. Memory 데이터 모델

Memory는 단순 FIFO buffer가 아니다. Memory는 출처·시간·지도 버전·결과를 보존하고 검색할 수 있는 장기 기록이고, replay sampler는 이 기록에서 학습 목적에 맞는 표본을 뽑는 임시 규칙이다.

### 5.1 관계 개요

```text
MapRevision
  ├─< ReferenceNode >─< ReferenceEdge >─ ReferenceNode
  │          │
  │          └─< RecoveryEpisode >─< EpisodeStep >─< CandidateRollout
  │                                  │        │
  │                                  │        ├─ IncidentFact (불변 사실)
  │                                  │        └─ OutcomeAssessment (갱신 가능 해석)
  │                                  └─ retrieved Reference/Episodic links
  └─ localization_epoch / TF snapshot

PolicyBundle ── TGRPO checkpoint + SAC checkpoint + skill ontology + schema versions
```

### 5.2 Reference Memory

#### `ReferenceNode` — 검증된 장소 점

| 필드 | 의미 |
|---|---|
| `node_id` | 변하지 않는 고유 ID |
| `map_id`, `map_revision` | 어떤 지도 버전의 점인지 |
| `x`, `y`, `yaw`, `frame_id` | 검증된 map 좌표와 방향 |
| `node_type` | 대기점, 회피점, 통로 입구, 임무 재합류점 등 |
| `recovery_roles[]` | 후진 완료, 사람 회피 대기, 재합류처럼 허용된 복구 용도 |
| `footprint_class` | 어떤 로봇 footprint에서 검증했는지 |
| `static_clearance_m` | 당시 정적 장애물과의 여유 거리 |
| `allowed_heading_range` | 이 점에서 허용되는 방향 범위 |
| `valid_from`, `last_verified_at` | 언제부터 유효했고 마지막 확인은 언제인지 |
| `verification_method` | 관리자 확인, 반복 성공, map survey 등 |
| `status` | `ACTIVE`, `SUSPECT`, `QUARANTINED`, `RETIRED` |
| `reliability_alpha`, `reliability_beta` | 성공/위험 관측을 누적하는 신뢰도 파라미터 |
| `source_hash` | 좌표·지도 출처의 변경 탐지 값 |

`ReferenceNode`는 “과거에 로봇이 서도 된다고 검증된 점”이다. Critical episode가 생겼다고 즉시 지우지 않는다. 그 점이 잘못됐는지, 사람이 일시적으로 있었는지 아직 모르기 때문이다. 대신 `SUSPECT` 또는 `QUARANTINED`로 바꾸고 현재 센서와 재검증한다.

#### `ReferenceEdge` — 검증된 점 사이의 이동 연결

| 필드 | 의미 |
|---|---|
| `edge_id`, `from_node_id`, `to_node_id` | 출발·도착 Node 연결 |
| `map_revision` | 검증 당시 지도 버전 |
| `path_polyline` | 검증된 기준 경로 좌표열 |
| `directionality` | 단방향/양방향 |
| `min_width_m`, `min_clearance_m` | 통로와 장애물 여유 |
| `speed_limit` | 이 연결에서 허용되는 최대 속도 |
| `allowed_recovery_skills[]` | 후진/좌우 우회/재합류 등 |
| `dynamic_risk_profile` | 사람 출현 시간대·구역 등의 통계 |
| `status`, `last_verified_at` | 현재 사용 가능 여부와 최신 확인 시각 |
| `reliability_alpha`, `reliability_beta` | 실행 결과로 갱신되는 신뢰도 |

Reference는 불변 지도가 아니라 **검증 이력을 가진 현재 지도**다. map revision이나 footprint가 달라지면 자동으로 유효하다고 간주하지 않는다.

### 5.3 Episodic Memory

#### `RecoveryEpisode` — Trigger부터 임무 재합류까지 한 묶음

| 필드 | 의미 |
|---|---|
| `episode_id`, `recovery_epoch` | 복구 사례와 실행 세대 ID |
| `robot_id`, `mission_id` | 어느 로봇·임무였는지 |
| `trigger_type`, `trigger_evidence` | 왜 복구를 시작했는지 |
| `started_at`, `ended_at` | 사례 시간 범위 |
| `map_id`, `map_revision`, `localization_epoch` | 공간 문맥 |
| `start_pose`, `start_covariance` | 시작 자세와 위치 불확실성 |
| `environment_embedding_ref` | 검색용 장면 embedding 위치 |
| `model_bundle_id`, `config_version` | 어떤 정책·규칙으로 판단했는지 |
| `terminal_status` | `SUCCESS`, `BOUNDARY`, `CRITICAL`, `PARTIAL`, `CENSORED` |
| `mission_rejoined` | 원 임무 경로로 돌아갔는지 |
| `attempt_count`, `distance_m`, `duration_ms` | 복구 budget 사용량 |

Episode는 후보 하나가 아니라 위험을 발견해 멈춘 순간부터 짧은 waypoint들을 실행하고 임무에 돌아가거나 포기할 때까지의 전체 이야기다.

#### `EpisodeStep` — 실제로 선택·실행한 좌표 한 번

| 필드 | 의미 |
|---|---|
| `step_id`, `episode_id`, `step_index` | Episode 안의 순서 |
| `snapshot_id`, `observed_at` | 결정을 내린 동기화 센서 상태 |
| `state_vector_ref` | pose, velocity, LiDAR, costmap, 객체 상태 |
| `retrieved_reference_ids[]` | 사용한 Node/Edge |
| `retrieved_episode_ids[]` | 참고한 과거 경험 |
| `high_action_z` | TGRPO가 고른 recovery skill |
| `selected_pose_p` | 최종 실행 좌표 `(x,y,yaw)` |
| `nav2_path_id`, `path_hash` | 실제 Nav2가 계획한 경로 |
| `commanded`, `executed`, `execution_fraction` | 명령·실행 여부와 실제 진행량 |
| `reward_components` | 안전, 진행, 시간, clearance, 재합류 보상 |
| `next_state_ref` | 실행·정지 후 재관찰 상태 |
| `done_reason` | 도착, veto, cancel, timeout, collision 등 |

**최종 선택된 좌표만 `EpisodeStep`이 된다.** 탈락한 좌표는 실제 결과가 없으므로 성공/실패 경험인 척 Episodic Memory에 넣지 않는다. 대신 다음 `CandidateRollout`에 예측 근거로만 기록한다.

#### `IncidentFact` — 나중에 덮어쓰지 않는 사실

| 필드 | 의미 |
|---|---|
| `incident_id`, `step_id` | 어느 실행에서 생긴 사실인지 |
| `fact_type` | collision, emergency stop, human-zone intrusion, localization jump 등 |
| `severity` | 물리적 심각도 |
| `sensor_evidence_refs[]` | 사실을 뒷받침하는 로그 |
| `occurred_at` | 발생 시각 |
| `immutable_hash` | 감사용 무결성 값 |

충돌이나 emergency stop은 후처리 모델이 “사실은 안전했다”고 바꿀 수 없다. 이 불변 사실이 있으면 outcome은 무조건 Critical이다.

#### `OutcomeAssessment` — 성공과 실패 사이를 표현하는 갱신 가능 해석

| 필드 | 의미 |
|---|---|
| `assessment_id`, `step_id` | 평가 대상 |
| `p_safe`, `p_boundary`, `p_critical` | 세 결과일 확률; 합은 1 |
| `safety_margin_min` | 실행 중 가장 작은 여유 거리 |
| `progress_ratio` | 복구·임무 재합류 진행도 |
| `intervention_level` | Safety/FMS/operator 개입 정도 |
| `label_confidence` | 평가 자체의 신뢰도 |
| `assessment_version` | 평가 규칙/모델 버전 |
| `assessed_at` | 마지막 평가 시각 |

Safe와 Critical을 별도 테이블로 쪼개지 않고 하나의 schema에 연속값을 둔다. 예를 들어 가까스로 통과했으면 `(p_safe=0.45, p_boundary=0.50, p_critical=0.05)`처럼 경계 사례로 남길 수 있다. `PARTIAL`, `CENSORED`, `CONTRADICTORY` 사례는 사실이 더 모일 때까지 safe replay에 넣지 않는다.

#### `CandidateRollout` — 실행하지 않은 후보의 가상 평가 로그

| 필드 | 의미 |
|---|---|
| `candidate_id`, `episode_id`, `decision_step_index` | 어느 결정의 후보인지 |
| `source_type`, `source_id` | Reference, retrieval, TGRPO+SAC 등 출처 |
| `high_action_z`, `candidate_pose_p` | 방법과 제안 좌표 |
| `filter_results` | 0~5 각 규칙의 통과/탈락 사유 |
| `predicted_trajectory_summary` | n-step 위치·clearance·진행 요약 |
| `risk_upper_bound`, `uncertainty` | 보수적 위험과 예측 불확실성 |
| `utility`, `exploration_value` | 안전 통과 후 비교에 쓰는 값 |
| `selected` | 실제 우승 여부 |
| `expires_at` | 일반 미선택 상세 로그의 만료 시각 |

가상 rollout은 한 번의 판단이 끝나면 GPU tensor와 전체 궤적을 버린다. 다만 후보 좌표, 탈락 이유, 위험·불확실성 요약은 디버깅과 학습 검증을 위해 TTL 동안 보존한다. 우승 후보, boundary/critical, operator/Safety 개입 사례의 핵심 감사 기록은 만료시키지 않는다.

### 5.4 현재성 갱신

Reference 신뢰도의 간단한 평균은 다음과 같다.

\[
R_{ref}=\frac{\alpha}{\alpha+\beta}\cdot e^{-\lambda\Delta t}\cdot C_{map}\cdot C_{loc}
\]

- `R_ref`: 지금 이 Reference를 얼마나 믿을지 나타내는 0~1 점수다.
- `alpha`: 안전하게 확인된 횟수에 해당하는 누적값이다.
- `beta`: 위험·불일치가 확인된 횟수에 해당하는 누적값이다.
- `Delta t`: 마지막 검증 뒤 지난 시간이다.
- `lambda`: 시간이 지날수록 얼마나 빨리 신뢰도를 낮출지 정하는 값이다.
- `C_map`: 현재 map revision과 맞으면 1에 가깝고 다르면 0에 가까운 값이다.
- `C_loc`: 현재 localization 품질이 좋으면 1에 가까운 값이다.

쉽게 말해 “여러 번 안전했어도 오래됐거나 지도가 바뀌었거나 로봇이 자기 위치를 잘 모르면 다시 의심한다”는 수식이다. Critical 실행이 Reference Node/Edge와 관련되면 즉시 삭제하지 않고 `SUSPECT`로 내린다. 충돌, 지도 불일치, 반복 critical이면 `QUARANTINED`로 바꾸고 관리자 또는 자동 재검증을 통과해야 `ACTIVE`로 돌아온다.

Episodic retrieval도 시간·환경 차이를 함께 반영한다.

\[
S_{episode}=w_e S_{embed}+w_g S_{geometry}+w_o S_{object}+w_m S_{map}-w_t\Delta t-w_u U
\]

- `S_episode`: 현재 상황과 과거 Episode의 최종 유사도다.
- `S_embed`: 영상·센서 장면 embedding의 유사도다.
- `S_geometry`: 통로 폭, pose, 장애물 배치 유사도다.
- `S_object`: 사람·unknown obstacle 종류와 위치 유사도다.
- `S_map`: map revision과 구역이 같은 정도다.
- `Delta t`: 경험의 나이다.
- `U`: 과거 평가의 불확실성이다.
- `w_*`: 각 항목의 중요도를 정하는 가중치다.

MySQL을 canonical source로 사용하고, RTX 5080 PC에는 FAISS embedding index, 최근 사례 cache, 네트워크 단절 시 append-only queue를 둔다. 모든 event에는 UUID, recovery epoch, episode ID, step index, schema/model version, checksum을 넣는다. 중복 event는 idempotently 무시하고 순서가 빠진 event는 pending으로 둔다. 로봇은 DB에 직접 접속하지 않고 API를 사용한다.

## 6. 후보 생성

### 6.1 후보 출처

1. **Reference 후보**: 현재 Recovery Envelope 안의 ACTIVE Node, Edge 위 재합류점, 검증 좌표
2. **Safe retrieval 후보**: 현재와 유사하고 최신성이 높은 safe/boundary Episode의 실제 실행 좌표
3. **Counterexample 후보**: Critical Episode와 비슷한 행동을 피하기 위한 반대 방향·정지·후퇴 제약
4. **RL 후보**: TGRPO Top-K skill 각각에 SAC가 M개의 좌표를 조건부 생성

상위·하위 정책은 순차 조건부 구조다.

\[
z_t^{(k)}\sim\pi_H(z\mid s_t),\qquad k=1,\ldots,K
\]

- `s_t`: 영상, segmentation, LiDAR, pose, Memory 검색 결과를 합친 현재 상태다.
- `pi_H`: TGRPO로 학습하는 상위 정책이다.
- `z`: 후진, 좌측 우회, 우측 우회, 대기 후 재관찰, 재합류 같은 고수준 action이다.
- `z_t^(k)`: 상위 정책이 제안한 k번째 recovery skill이다.
- `K`: 다음 단계로 넘길 상위 action 수다.

\[
p_t^{(k,m)}\sim\pi_L(p\mid s_t,z_t^{(k)}),\qquad p=(x,y,yaw),\quad m=1,\ldots,M
\]

- `pi_L`: SAC로 학습하는 하위 좌표 정책이다.
- `p_t^(k,m)`: k번째 recovery skill 조건에서 만든 m번째 좌표다.
- `(x,y,yaw)`: map frame의 위치와 방향이다.
- `M`: skill 하나마다 만들 좌표 후보 수다.

즉 TGRPO와 SAC가 서로 무관하게 동시에 답을 내는 것이 아니다. TGRPO가 Top-K 방법을 먼저 만들고, SAC가 각 방법을 조건으로 좌표를 만든다. 구현은 GPU batch로 함께 계산할 수 있지만 의미상으로는 `s → z → p`의 조건부 구조다.

### 6.2 직접 절대좌표 1안과 anchor-residual 2안

**1안(기존 방안 B) — 직접 bounded map pose(채택)**

SAC가 `(x,y,yaw)`를 직접 출력하되, 출력 범위는 현재 pose 중심의 동적 Recovery Envelope로 제한한다. 후보에는 `map_id`, `map_revision`, `localization_epoch`, TF snapshot, covariance, source timestamp가 반드시 붙는다. 지도 revision이 달라진 replay 좌표를 그대로 학습하거나 실행하지 않는다.

장점은 최종 출력이 명확한 좌표이고 Nav2와 연결하기 쉽다는 점이다. 단점은 map 변경과 localization 오차에 민감하고 학습 분포 밖 좌표가 나올 수 있다는 점이다.

**2안(기존 방안 A) — Reference anchor + bounded residual(대안)**

\[
p=p_{anchor}+\Delta p,\qquad \lVert\Delta p\rVert\le r_{max}
\]

- `p_anchor`: Reference Node/Edge 또는 검증된 local point다.
- `Delta p`: SAC가 제안하는 작은 위치·방향 보정량이다.
- `r_max`: 검증점에서 너무 멀어지지 않게 하는 최대 반경이다.

장점은 데이터 효율과 안전 경계 설명이 쉽다는 점이고, 단점은 Reference가 드문 미지 공간에서 유연성이 떨어진다는 점이다. 1안이 학습 불안정·OOD 문제를 보이면 2안으로 전환할 수 있게 schema는 둘 다 표현한다.

## 7. 0~6단계 1차 필터 규칙

핵심은 **점수로 위험을 상쇄하지 않는 것**이다. 사람 침범 후보가 임무 진행 점수가 높아도 탈락이다. 0~3은 후보 생성 직후, 4~5는 6C-Lite 전 후보 rollout 중, 6은 우승 좌표 하나에 대해 최신 센서로 수행한다.

### 0. 로봇·센서 상태 검사

| ID | 통과 조건 — 쉽게 말하면 |
|---|---|
| `R0-01 STOP_ACK` | wheel odometry의 선속도·각속도가 정지 기준 아래에서 유지되어야 한다. **차가 완전히 선 뒤에 생각한다.** |
| `R0-02 GOAL_CANCEL_ACK` | 이전 mission goal의 cancel을 Fleet Adapter가 확인해야 한다. **두 운전 지시가 겹치면 안 된다.** |
| `R0-03 SENSOR_FRESH` | RGB, segmentation, LiDAR/depth, pose, costmap의 age가 각 한계보다 작아야 한다. **오래된 사진으로 길을 고르지 않는다.** |
| `R0-04 SENSOR_SYNC` | 센서 timestamp 차이가 허용 범위 안이어야 한다. **서로 다른 순간의 장면을 한 장면처럼 섞지 않는다.** |
| `R0-05 LOCALIZATION_OK` | pose covariance와 map/odom TF jump가 기준 이하여야 한다. **로봇이 자기가 어디 있는지 모르면 움직이지 않는다.** |
| `R0-06 SAFETY_READY` | bumper, e-stop, Safety Supervisor 상태와 독립 안전 센서가 정상이어야 한다. **마지막 브레이크가 고장 났으면 출발하지 않는다.** |
| `R0-07 COMPUTE_READY` | GPU memory, 모델 load, absolute deadline 잔여 시간이 예산 안이어야 한다. **검사를 끝낼 시간이 없으면 추측하지 않는다.** |

하나라도 실패하면 좌표 생성 자체를 중단하고 STOP을 유지한다.

### 1. 후보 형식·출처 검사

| ID | 통과 조건 — 쉽게 말하면 |
|---|---|
| `R1-01 FINITE_POSE` | x, y, yaw가 NaN/Inf가 아니고 단위·범위가 맞아야 한다. **주소가 숫자로 제대로 적혀 있어야 한다.** |
| `R1-02 FRAME_MAP` | 좌표가 `map` frame이거나 검증 가능한 TF로 변환되어야 한다. **서로 다른 지도의 주소를 섞지 않는다.** |
| `R1-03 VERSION_MATCH` | map revision, localization epoch, footprint/config version이 현재 판단과 맞아야 한다. **옛 지도용 좌표를 새 지도에 쓰지 않는다.** |
| `R1-04 SOURCE_TRACE` | Reference/episode/policy와 checkpoint ID, 생성 timestamp를 추적할 수 있어야 한다. **누가 왜 제안했는지 모르는 좌표는 버린다.** |
| `R1-05 POLICY_ALLOWED` | Stable policy bundle이거나 승인된 low-risk Candidate canary여야 한다. **시험 모델은 허가된 운동장에서만 쓴다.** |
| `R1-06 ENVELOPE_BIND` | 후보가 현재 recovery epoch의 Recovery Envelope에 묶여야 한다. **이번 문제를 위해 정한 작은 운동장 밖으로 나가지 않는다.** |

### 2. 목표 좌표 자체 검사

| ID | 통과 조건 — 쉽게 말하면 |
|---|---|
| `R2-01 IN_RECOVERY_ENVELOPE` | 현재 pose에서 허용 반경·방향·구역 안이어야 한다. **복구는 짧게만 한다.** |
| `R2-02 COST_FREE` | inflated costmap에서 lethal/unknown 금지 cell이 아니어야 한다. **도착점 자체가 벽이나 모르는 구멍이면 안 된다.** |
| `R2-03 FOOTPRINT_FITS` | 목표 pose에서 전체 robot footprint가 free space 안에 들어가야 한다. **로봇 중심만 들어가는 것이 아니라 몸 전체가 들어가야 한다.** |
| `R2-04 CLEARANCE_MIN` | 정적·동적 장애물과 사람별 최소 clearance보다 커야 한다. **도착해서도 숨 쉴 공간이 있어야 한다.** |
| `R2-05 KEEP_OUT` | keep-out, human-only, cliff, restricted zone을 침범하지 않아야 한다. **금지선은 점수와 관계없이 넘지 않는다.** |
| `R2-06 HEADING_VALID` | yaw가 통로 폭, 센서 시야, 후속 재합류에 가능한 방향이어야 한다. **도착해도 몸이 끼는 방향이면 안 된다.** |
| `R2-07 STOPPABLE` | 제한 속도에서 후보까지 가는 동안 언제든 안전 정지할 거리 여유가 있어야 한다. **앞이 막히면 그 안에서 설 수 있어야 한다.** |

### 3. Critical Memory veto 검사

| ID | 통과 조건 — 쉽게 말하면 |
|---|---|
| `R3-01 NO_INCIDENT_MATCH` | collision/emergency/human intrusion IncidentFact와 동일한 구역·행동 조합이 아니어야 한다. **예전에 실제 사고 난 행동을 그대로 반복하지 않는다.** |
| `R3-02 RISK_DISTANCE` | Critical episode embedding/geometry와의 거리가 veto threshold보다 멀어야 한다. **위험 일지와 너무 닮았으면 먼저 버린다.** |
| `R3-03 BOUNDARY_MARGIN` | boundary 경험과 비슷하면 요구 clearance·불확실성 margin을 더 크게 적용해도 통과해야 한다. **간신히 성공한 길은 더 넉넉하게 확인한다.** |
| `R3-04 REFERENCE_STATUS` | 관련 Node/Edge가 ACTIVE여야 하고 QUARANTINED이면 사용할 수 없다. **의심받는 표지판은 다시 검사하기 전까지 따르지 않는다.** |
| `R3-05 HUMAN_HARD_VETO` | 사람의 현재·예측 점유영역을 침범하지 않아야 한다. **사람 안전은 학습 점수로 흥정하지 않는다.** |
| `R3-06 UNKNOWN_CONSERVATIVE` | 센서 association이 안 된 critical/unknown 영역을 occupied로 놓아도 통과해야 한다. **안 보인다고 빈 공간으로 세지 않는다.** |

### 4. Nav2 경로 생성 가능성 검사

| ID | 통과 조건 — 쉽게 말하면 |
|---|---|
| `R4-01 PLAN_EXISTS` | 현재 costmap snapshot에서 Nav2 planner가 후보까지 유효한 path를 만들어야 한다. **주소만 좋은 게 아니라 길이 있어야 한다.** |
| `R4-02 PLAN_VERSION` | plan의 costmap/map/TF version이 후보와 같아야 한다. **새 주소를 옛 교통정보로 검사하지 않는다.** |
| `R4-03 PATH_LENGTH` | path 길이와 detour가 Recovery Envelope와 복구 budget 안이어야 한다. **복구 waypoint가 새 장거리 임무가 되면 안 된다.** |
| `R4-04 KINEMATIC` | 최소 회전반경, 후진 허용, controller 제약에서 추종 가능해야 한다. **그려진 길을 실제 바퀴가 따라갈 수 있어야 한다.** |
| `R4-05 REJOIN_OR_SAFE_STOP` | 경로 끝이 임무 재합류 가능점이거나 다시 안전하게 정지·관찰할 수 있는 점이어야 한다. **도착 뒤 다음 수가 있어야 한다.** |

### 5. 전체 경로와 이동 공간 검사

| ID | 통과 조건 — 쉽게 말하면 |
|---|---|
| `R5-01 SWEPT_FOOTPRINT` | path 전체의 swept footprint가 장애물·벽·keep-out을 침범하지 않아야 한다. **도착점뿐 아니라 가는 동안 로봇 몸 전체를 검사한다.** |
| `R5-02 CLEARANCE_PROFILE` | 모든 path sample에서 class별 clearance가 최소값 이상이어야 한다. **길 중간 한 곳이라도 너무 좁으면 탈락이다.** |
| `R5-03 DYNAMIC_PREDICTION` | 사람·동적 장애물의 n-step 점유 예측과 시간적으로 겹치지 않아야 한다. **지금 빈 길도 사람이 곧 들어오면 가지 않는다.** |
| `R5-04 UNCERTAINTY_BOUND` | world-model ensemble의 위험 상한과 disagreement가 한계 이하여야 한다. **가상시험 모델끼리 의견이 너무 다르면 움직이지 않는다.** |
| `R5-05 STOPPING_CORRIDOR` | path 각 지점에서 독립 safety sensor 기준으로 정지 가능한 공간이 있어야 한다. **가는 내내 브레이크 거리를 남긴다.** |
| `R5-06 NO_OSCILLATION` | 최근 실행과 앞뒤로 반복되는 좌표·skill이 아니거나 budget 안에서 명시적 탈출 근거가 있어야 한다. **같은 두 점을 계속 왕복하지 않는다.** |
| `R5-07 BUDGET_OK` | 예상 시간·거리·attempt가 episode 복구 budget을 넘지 않아야 한다. **실패를 무한 반복하지 않는다.** |

### 6. 실행 직전 재검사

| ID | 통과 조건 — 쉽게 말하면 |
|---|---|
| `R6-01 EPOCH_CURRENT` | 후보·센서·goal의 recovery epoch가 현재 lease와 같아야 한다. **지난 문제의 답을 지금 실행하지 않는다.** |
| `R6-02 FRESH_SNAPSHOT` | 최신 동기화 snapshot으로 2~5 규칙 전체를 다시 통과해야 한다. **시험하는 동안 세상이 바뀌지 않았는지 다시 본다.** |
| `R6-03 WINNER_ONLY` | 우승 좌표 한 개와 Nav2 goal 한 개만 authorized 상태여야 한다. **운전 지시는 하나만 둔다.** |
| `R6-04 SAFETY_CLEAR` | Safety Supervisor가 emergency가 아니고, 출발 순간의 protection zone이 clear여야 한다. **마지막 신호등이 초록이어야 한다.** |
| `R6-05 DEADLINE_VALID` | 절대 판단 deadline을 넘지 않았고 VLM/model 결과가 TTL 안이어야 한다. **너무 오래 생각한 답은 폐기한다.** |
| `R6-06 AUDIT_COMMITTED` | 선택 근거, 모델·규칙 버전, path hash가 append-only log에 기록되어야 한다. **움직이기 전에 왜 움직였는지 영수증을 남긴다.** |

6단계에서 실패하면 2등 후보를 자동 실행하지 않는다. 최신 snapshot으로 남은 후보의 4~5 검사를 다시 돌리거나 전체 판단을 새 epoch/step으로 재시작한다. 안전한 후보가 하나도 없으면 STOP을 유지하고 상위 FMS/operator에 보고한다.

## 8. 6C-Lite: 전 후보 n-step 가상 rollout

0~3단계는 “애초에 말이 안 되는 좌표”를 빠르게 제거한다. 6C-Lite의 4~5단계는 남은 모든 후보에 대해 **실제로 1-step도 움직이지 않고** 가까운 미래를 가상으로 전개한다. 같은 규칙을 중복하는 이유가 아니라, 앞 단계는 현재 시점의 정적 입장권 검사이고 rollout은 미래 path 전체의 시간 변화 검사이기 때문이다.

6C-Lite는 영상 생성 모델이 아니다.

- Nav2 planner/controller의 geometry·motion rollout
- 사람·동적 장애물의 구조화된 state predictor
- 작은 world-model ensemble의 clearance/risk/uncertainty 예측
- receding-horizon 방식: 최종적으로 첫 번째 짧은 waypoint만 실행

후보 `i`의 가상 궤적은 다음과 같다.

\[
\tau_i=(\hat{s}_{i,0},\hat{s}_{i,1},\ldots,\hat{s}_{i,n})
\]

- `tau_i`: 후보 i를 택했을 때 예상되는 짧은 미래의 묶음이다.
- `s_hat_i,j`: j번째 가상 step의 로봇 pose, 사람·장애물 위치, clearance, 불확실성이다.
- `n`: 실제로 가지 않고 미리 볼 가까운 미래 step 수다.

world-model ensemble `e=1...E`가 서로 다른 미래를 예측한다. 위험은 평균만 보지 않고 보수적 상한을 쓴다.

\[
Risk_i^{UCB}=\frac{1}{E}\sum_{e=1}^{E}Risk_i^{(e)}+\kappa\,Std_e(Risk_i^{(e)})
\]

- `Risk_i^UCB`: 후보 i의 보수적 위험 상한이다.
- `E`: 서로 다른 world model 수다.
- `Risk_i^(e)`: e번째 모델이 예측한 위험이다.
- `Std`: 모델들이 얼마나 다르게 말하는지 나타낸다.
- `kappa`: 의견 불일치를 얼마나 위험하게 볼지 정한다.

사람, critical object, degraded sensing 상태에서는 exploration bonus를 0으로 만들고 deterministic veto만 적용한다. learned model은 deterministic Safety 규칙보다 더 보수적으로 탈락시킬 수는 있지만, 금지된 후보를 되살릴 수 없다.

### 8.1 후보 Tournament

후보는 하나의 가중합으로 뽑지 않고 사전식으로 정렬한다.

1. 0~5 hard rule을 모두 통과했는가
2. 사람·critical·unknown 위험 상한이 가장 낮은가
3. 불확실성이 허용 범위 안에서 더 낮은가
4. Nav2 경로 clearance와 정지 가능성이 더 좋은가
5. 위 조건이 비슷할 때만 임무 진행·시간·에너지·안전한 exploration 가치를 비교

\[
i^*=\arg\max_{i\in\mathcal{C}_{valid}}J_i,\qquad p^*=p_{i^*,0}
\]

- `C_valid`: hard filter를 모두 통과한 후보 집합이다.
- `J_i`: 위험 우선 사전식 비교 뒤 남은 후보의 진행·효율·탐험 가치다.
- `i*`: 가상시험에서 이긴 후보다.
- `p*`: 그 후보 궤적 전체가 아니라 실제로 Nav2에 줄 첫 번째 짧은 waypoint다.

실제 waypoint 실행 뒤에는 멈추고 다시 관찰한다. 가상 rollout tensor는 삭제하고, 요약·선택 근거와 실제 결과만 Memory에 남긴다.

### 8.2 GPU 계산 예산

\[
K\times M\times E\times n\le B_{compute}
\]

- `K`: TGRPO 상위 action 수다.
- `M`: action마다 SAC 좌표 수다.
- `E`: world-model ensemble 수다.
- `n`: 가상 미래 step 수다.
- `B_compute`: RTX 5080에서 deadline 안에 끝낼 수 있는 최대 계산량이다.

예산이 부족하면 먼저 중복 좌표를 합치고, 0~3단계에서 탈락시키고, 저해상도/짧은 horizon으로 1차 ranking한 뒤 상위 소수만 정밀 rollout한다. absolute deadline이 끝나면 부분 검증 후보를 실행하지 않고 STOP한다.

## 9. Episodic Memory 위의 replay samplers

Episodic Memory는 원본 운행 일지이고 sampler는 “이번 수업에 어떤 페이지를 보여줄지” 고르는 편집자다. 원본을 SAC/TGRPO용 별도 Memory로 복제하지 않는다.

### 9.1 SAC off-policy replay sampler

SAC는 실제로 실행된 `EpisodeStep`의 transition만 사용한다.

\[
\mathcal{D}_{SAC}=\{(s_t,z_t,p_t,r_t,s_{t+1},d_t)\}
\]

- `s_t`: 실행 전 상태다.
- `z_t`: 상위 recovery skill이다.
- `p_t`: 실제로 선택·실행한 좌표다.
- `r_t`: 안전·진행·clearance·시간을 합친 보상이다.
- `s_(t+1)`: 실행하고 정지·재관찰한 상태다.
- `d_t`: episode 종료 여부다.

sampling bucket은 `safe`, `boundary`, `critical`, `rare trigger`, `recent`, `map zone`으로 나누되 원본 outcome은 바꾸지 않는다. critical/rare를 더 자주 보여주고, importance weight로 표본 편향을 보정한다. collision/emergency 사실은 항상 높은 우선순위를 갖는다. safe 사례만 계속 학습해 경계선을 잊지 않도록 boundary를 별도 quota로 뽑는다.

### 9.2 TGRPO trajectory-group sampler

TGRPO에는 옛 행동의 trajectory를 일반 replay처럼 그대로 섞지 않는다. Episodic Memory에서 초기 상태와 환경을 뽑은 다음 **현재 Candidate checkpoint**가 같은 상태에서 여러 recovery trajectory를 6C-Lite/digital twin에 생성한다. 같은 출발점의 trajectory끼리 상대 비교해 단계 보상과 전체 복구 성공을 학습한다.

\[
G(s_0)=\{\tau^{(1)},\tau^{(2)},\ldots,\tau^{(G)}\},\qquad \tau^{(g)}\sim\pi_{current}
\]

- `s_0`: Episodic Memory에서 고른 현실적인 시작 상태다.
- `G(s_0)`: 같은 출발점에서 만든 trajectory 그룹이다.
- `tau^(g)`: 현재 정책이 생성한 g번째 가상 복구 과정이다.
- `pi_current`: 지금 학습 중인 Candidate 정책이다.

실제 로그는 시작 상태, sensor noise, reward calibration, incident constraint를 제공한다. trajectory group은 한 학습 step 뒤 버리는 임시 buffer다. 이 구분이 TGRPO의 on-current-policy 비교와 SAC의 persistent off-policy replay가 서로 충돌하지 않게 한다.

### 9.3 보상과 실제 결과 귀속

\[
r_t=w_p\Delta progress-w_c Cost_{clearance}-w_i I_{intervention}-w_t\Delta time+R_{rejoin}
\]

- `Delta progress`: 원 임무 경로로 가까워진 정도다.
- `Cost_clearance`: 사람·장애물에 가까울수록 커지는 비용이다.
- `I_intervention`: Safety stop, FMS cancel, operator 개입 강도다.
- `Delta time`: 복구에 쓴 시간이다.
- `R_rejoin`: 임무에 성공적으로 재합류했을 때 주는 보상이다.
- `w_*`: 각 항목의 중요도다.

충돌, 사람 영역 침범, emergency stop은 가중합 이전에 terminal critical 처리한다. 실제 결과 credit은 실행된 `EpisodeStep`에만 준다. 미선택 rollout은 실제 성공 label을 받지 않으며, 나중에 world-model 학습용 counterfactual로 사용할 때도 “predicted” provenance를 유지한다.

## 10. Stable–Candidate 모델 업데이트

일반 ML처럼 저장된 가중치를 계속 업데이트하는 것은 맞다. 다만 로봇에서는 “방금 업데이트한 가중치가 더 안전하다”는 보장이 없으므로 운영 중인 검증 모델과 새 학습 모델을 역할로 나눈다.

- **Stable bundle**: 현재 실제 운행에 허용된 TGRPO checkpoint, SAC checkpoint, skill ontology, input schema, reward/config 묶음
- **Candidate bundle**: Stable에서 시작해 새 Episode로 업데이트 중인 묶음

두 모델을 영원히 별도로 학습하는 것이 아니다. Candidate가 승격되면 그것이 새 Stable이 되고, 이전 Stable은 rollback checkpoint가 된다. TGRPO와 SAC는 인터페이스가 맞는 **PolicyBundle 단위**로 버전 관리하는 것이 기본안이다.

```text
Stable v12 ──copy/update──> Candidate v13
                              │
                              ├─ unit/schema test
                              ├─ offline holdout replay
                              ├─ simulation + 6C-Lite scenario test
                              ├─ Pinky-Pro HIL (정지·저위험)
                              └─ 제한 canary (탐험 0, 자동 rollback)
                                      │
                         pass ────────┴──> Stable v13
                         fail ───────────> 폐기, Stable v12 유지
```

운영 중에는 학습하지 않는다. RTX 5080 PC가 정지/docked 상태일 때 Candidate를 학습한다. 운행 시에는 YOLO를 계속 실행하고, 예외 시 YOLO를 낮은 주기로 유지하면서 VLM 3B/7B 4-bit와 6C-Lite를 실행한다. VLM load/infer, rollout, Nav2 validation이 메모리 부족이나 deadline을 넘으면 STOP으로 fail closed한다.

## 11. Nav2와 Safety Supervisor의 정확한 경계

Nav2는 최종 복구 좌표를 받더라도 VLM/RL이 상상한 좁은 선을 그대로 따라야 하는 것은 아니다. `Recovery Envelope`, keep-out, 사람 보호영역, 최대 거리·시간 같은 넓은 hard boundary 안에서 Nav2가 실제 costmap을 보고 자유롭게 재계획한다. virtual path와 실제 Nav2 path가 달라질 수 있으므로 실제 plan hash와 costmap version을 기록하고 Safety Supervisor가 실행 중 계속 감시한다.

Safety Supervisor는 planner가 아니라 **독립적인 속도 gate**다.

```text
Nav2 /cmd_vel_nav
       │
       ▼
Safety Supervisor
  - LiDAR protection zone
  - bumper / e-stop
  - current velocity + stopping distance
  - sensor freshness / TF health
  - recovery lease / envelope violation
       │
       ├─ CLEAR     : 제한 안에서 통과
       ├─ SLOW      : 안전 scale을 곱해 감속
       ├─ STOP      : 0속도 + latch
       └─ EMERGENCY : 즉시 0속도, goal cancel 요청, 수동/조건부 해제
       ▼
robot /cmd_vel
```

의미 기반 YOLO/VLM은 “무엇인지” 판단하는 데 도움을 주지만 유일한 비상정지 센서가 아니다. 최소거리, protection zone, bumper 같은 deterministic safety path는 VLM/GPU와 독립적으로 계속 동작해야 한다. Safety가 path/envelope 위반을 감지하면 0속도를 내고 Recovery Coordinator에 알리며, Fleet Adapter가 goal을 cancel한다.

복구에는 최대 attempt, 누적 거리, 누적 시간, oscillation 횟수 budget을 둔다. 초과하면 STOP, goal cancel, Episode를 BOUNDARY/CRITICAL로 닫고 FMS/operator 또는 mission failure로 승격한다.

## 12. 성능 모드와 deadline

RTX 5080 한 장에서 운영 우선순위는 다음과 같다.

1. deterministic Safety와 센서 처리는 항상 우선
2. YOLO는 평상시 연속 실행
3. Trigger 후 YOLO는 추적 연속성을 위해 낮은 주기로 유지
4. VLM 3B/7B 4-bit는 예외 시에만 load/infer
5. 후보는 progressive pruning 후 6C-Lite 수행
6. 학습은 운행·복구가 끝난 정지/docked window에서만 수행

각 stage timeout은 실제 Pinky-Pro benchmark의 p95에 margin을 붙여 설정하고, safety-critical stage는 p99.9와 관측 worst case도 시험한다. 전체에는 absolute recovery-decision deadline을 둔다. 예시 수치는 구현 전 측정으로 확정해야 하며, 임의의 “YOLO 2~5 FPS” 같은 값은 요구사항이 아니라 benchmark 시작점일 뿐이다.

| Stage | 측정 항목 | timeout 동작 |
|---|---|---|
| STOP/cancel | 명령부터 실제 0속도·cancel ACK까지 | emergency/STOP 유지, goal 격리 |
| sensor snapshot | freshness, sync skew, TF/covariance | 추론 금지, 재수집 또는 보고 |
| VLM | load, preprocess, tokens, JSON validation | 결과 폐기, Memory/rule fallback 또는 STOP |
| retrieval | MySQL/API, FAISS, cache age | stale 표식; local recent만으로 안전 보장 불가하면 STOP |
| candidate/filter | 후보 수, 0~3 탈락률 | budget 초과 후보 pruning |
| 6C-Lite | `K*M*E*n`, GPU memory, 4~5 검사 | 부분 결과 실행 금지, STOP |
| winner revalidation | 최신 snapshot 2~5 전체 검사 | winner 폐기, 재판단 |
| Nav2 goal | plan/action ACK | cancel·STOP·상위 보고 |

## 13. 실패 모드와 fail-closed 동작

| 실패 | 탐지 | 시스템 동작 |
|---|---|---|
| YOLO unknown/low confidence | N-of-M, class entropy, track instability | STOP 후 VLM; unknown 영역 occupied |
| VLM hallucination/JSON 오류 | schema·range·cross-sensor 검사 | VLM 결과 폐기; rule/Memory fallback 또는 STOP |
| RGB/seg/LiDAR 시간 불일치 | timestamp skew | snapshot 재수집; 움직이지 않음 |
| localization jump | covariance/TF discontinuity | 모든 map 좌표 무효화, STOP, relocalization |
| stale Reference | map/version/time/reliability | SUSPECT/QUARANTINED, 후보 제외 |
| Memory 서버 단절 | API timeout, queue backlog | verified local cache만 제한 사용; 증명 불가하면 STOP |
| world models disagreement | ensemble uncertainty | 후보 탈락; exploration 0 |
| 모든 후보 탈락 | empty valid set | STOP, FMS/operator 보고 |
| VLM/GPU OOM | allocator/health | VLM 종료·cache 해제, STOP; YOLO/Safety 복구 우선 |
| Nav2 actual path 변경 | path hash/envelope monitor | 범위 내면 허용; 위반 시 Safety STOP + Fleet cancel |
| stale asynchronous result | recovery epoch mismatch | 결과 폐기 |
| 반복 좌우 왕복 | recent skill/pose cycle | oscillation budget 차감; 초과 시 mission fail |
| Candidate 성능 저하 | canary guardrail | 자동 Stable rollback |

## 14. 검증 계획

### 14.1 테스트 피라미드

```text
                    실제 Pinky-Pro 제한 canary
                 (저위험, exploration 0, rollback)
                  Pinky-Pro HIL / safety stop test
              simulation + digital twin scenario suites
          offline replay / counterfactual / model-bundle eval
       pytest·ament unit / schema / property / fault-injection tests
```

### 14.2 필수 테스트 매트릭스

| 영역 | 대표 테스트 | 통과 기준 |
|---|---|---|
| Trigger | 한 프레임 low confidence, N-of-M, hard LiDAR, Nav2 stuck | false trigger/누락률 목표 충족; hard 즉시 |
| STOP lease | goal cancel race, 늦은 VLM 결과, epoch 교차 | 동시에 active goal 1개 이하; stale 실행 0 |
| VLM contract | malformed JSON, bbox 범위, unknown, pixel-depth 불일치 | 잘못된 출력 100% 거부 |
| Memory | map revision 변경, old node decay, critical quarantine | stale Reference 자동 제외/격리 |
| Outcome | collision 뒤 safe 재평가 시도 | IncidentFact가 Critical을 강제 |
| Filters | R0~R6 각 규칙 positive/negative fixture | hard violation 실행 0 |
| 6C-Lite | 사람이 path로 진입, ensemble disagreement, deadline | 후보 veto 또는 STOP; 부분 결과 실행 0 |
| SAC | 좌표 범위, OOD 상태, yaw/TF 변환 | envelope 밖 출력 실행 0 |
| TGRPO | 같은 시작점 group, old-policy trajectory 유입 | current-policy group만 학습 |
| Nav2 | virtual path와 다른 replan, envelope 이탈 | 범위 내 허용; 이탈 즉시 STOP/cancel |
| Safety | VLM/GPU kill, YOLO kill, sensor stale | 독립 STOP path 유지 |
| Recovery budget | 반복 실패/oscillation | 설정 횟수에서 확실히 종료·보고 |
| Performance | cold VLM load, 최대 후보, DB 지연, GPU pressure | stage/absolute deadline 충족 또는 fail closed |
| Promotion | Candidate regression, canary anomaly | Stable 승격 차단/자동 rollback |

실제 Pinky 시험 순서는 정지 상태 inference → 바퀴를 띄운 HIL → 빈 저속 구역 → 정적 장애물 → 보호자 동반 동적 장애물 순으로 넓힌다. 사람을 대상으로 exploration하지 않는다.

## 15. 구현 경계와 단계

### Phase 1 — deterministic recovery shell

- `trihouse_pinky_recovery` package, recovery epoch/lease, STOP/cancel ACK
- 0~6 filter와 Recovery Envelope
- Fleet Adapter 단일 Nav2 goal ownership 유지
- Safety Supervisor 독립 속도 gate 구현·검증
- VLM/RL 없이 Reference 후보만으로 end-to-end 시험

### Phase 2 — Memory와 VLM

- MySQL canonical schema와 API, append-only event, FAISS local index
- Reference Node/Edge 관리와 Episode/Step/Incident/Assessment 저장
- RGB/seg/YOLO track → strict JSON VLM contract
- unknown/cross-sensor disagreement Trigger와 association confidence

### Phase 3 — SAC 좌표와 6C-Lite

- bounded absolute map pose SAC, map/localization version gate
- Nav2 geometry rollout + dynamic state predictor ensemble
- progressive pruning, lexicographic tournament, winner full revalidation
- SAC replay sampler와 offline/HIL 평가

### Phase 4 — TGRPO와 Stable–Candidate

- recovery skill ontology와 Top-K policy
- same-state current-policy trajectory groups
- PolicyBundle 평가·승격·rollback
- simulation/HIL/저위험 canary

각 Phase는 앞 단계의 안전 경계를 대체하지 않고 그 안에 후보 생성 능력을 추가한다.

## 16. 가능한 대안과 선택 이유

### 1안(기존 방안 B) — TGRPO Top-K → SAC 좌표 → 6C-Lite 전 후보 → Nav2 (채택)

장점은 최종 출력이 좌표이고, 고수준 방법과 저수준 좌표를 설명할 수 있으며, 미래 위험과 불확실성을 실제 이동 전에 비교한다는 점이다. 단점은 구성요소가 많고 5080 계산 예산, 정책 간 버전 호환, simulator bias를 관리해야 한다는 점이다.

### 2안(기존 방안 A) — spatial action → deterministic 좌표 mapper → Nav2

VLM/상위 정책이 `left/right/back/wait`와 거리 bin만 내고, 검증된 local planner가 좌표로 바꾼다. 장점은 데이터가 적어도 안정적이고 설명·검증이 쉽다는 점이다. 단점은 복잡한 임의 map에서 좌표 적응성이 떨어지고 mapper 규칙이 커진다는 점이다. 1안의 SAC가 OOD로 불안정하면 안전한 fallback으로 유용하다.

### 단순 3-buffer 구조를 별도 운영하지 않는 이유

Reference, Safe, Critical을 물리적으로 서로 다른 replay buffer로 복제하면 동일 사건의 버전과 결과가 갈라지고 boundary 사례가 사라지기 쉽다. 이 설계는 Reference Memory와 하나의 Episodic Memory를 canonical record로 두고, outcome 확률과 sampler view로 Safe/Boundary/Critical을 나눈다. 필요할 때 sampler가 critical·rare·recent를 비율대로 뽑으므로 buffer의 장점은 유지하면서 기록의 일관성을 지킨다.

## 17. 선행 연구와 차별점

- [TGRPO](https://arxiv.org/abs/2506.08440)는 단계 수준과 trajectory 수준 feedback을 결합한 VLA online RL 방향을 제공한다. Trihouse에서는 직접 motor control이 아니라 고수준 recovery skill 후보 생성에 한정한다.
- [ReMemNav](https://arxiv.org/abs/2603.26788)는 zero-shot object navigation에서 bounded episodic working memory를 강조한다. Trihouse는 여기에 검증 지도 graph인 Reference Memory, 실제 결과의 soft outcome, immutable incident, map/version freshness를 분리한다.
- [Retrieval-Augmented RL](https://arxiv.org/abs/2202.08417)과 [RANa](https://arxiv.org/abs/2504.03524)는 과거 경험 검색을 정책 판단에 결합하는 근거가 된다. Trihouse에서는 검색 결과도 hard safety filter를 통과해야 한다.
- [EE-RL](https://openaccess.thecvf.com/content/CVPR2026/html/Li_EE-RL_Vision_Language_Guided_Reinforcement_Learning_with_Explorer_and_Expert_CVPR_2026_paper.html)은 explorer/expert와 replay 관점의 참고가 된다. Trihouse는 사람·critical 상황에서 exploration을 꺼서 실제 로봇 안전 경계를 우선한다.
- [PETS](https://proceedings.neurips.cc/paper_files/paper/2018/hash/3de568f8597b94bda53149c7d7f5958c-Abstract.html)와 [TD-MPC2](https://openreview.net/pdf?id=Oxh5CstDJU)는 ensemble/world-model 기반 짧은 horizon planning의 연구 배경이다. Trihouse 6C-Lite는 영상 생성이 아니라 구조화 상태와 Nav2 geometry로 계산량을 줄인다.
- [Nav2 MPPI Controller](https://docs.nav2.org/configuration/packages/configuring-mppic.html)와 [Collision Monitor](https://docs.nav2.org/tutorials/docs/using_collision_monitor.html)는 sampling rollout과 독립 collision monitoring의 실무 기반이다. Trihouse는 Fleet Adapter goal ownership과 별도의 recovery lease를 추가한다.

이 조합과 완전히 동일한 선행 시스템 하나를 그대로 복제하는 것은 아니다. **검증 map graph + soft-outcome episodic memory + current-policy TGRPO groups + SAC coordinate proposals + 모든 후보의 Lite rollout + winner fresh revalidation + Nav2/Safety 이중 권한 경계**를 실제 Pinky-Pro 단일 GPU 제약에 맞게 합친 것이 설계상의 차별점이다.

## 18. 결정 기록

| 결정 | 선택 |
|---|---|
| 최종 산출 | 짧은 map-frame `(x,y,yaw)` |
| Trigger 후 행동 | 완전 정지 후 추론 |
| VLM 운용 | 위험·예외 시 3B/7B 4-bit load/infer |
| YOLO | 평상시 연속; 복구 중 저주기 유지 |
| Memory | Reference Node/Edge + 단일 Episodic schema |
| outcome | Safe/Boundary/Critical 연속 확률 + immutable incident |
| 가상시험 | 6C-Lite로 모든 후보, 실제 이동 전 n-step |
| 상·하위 RL | TGRPO Top-K → 조건부 SAC M 좌표 |
| 좌표 표현 | 1안 직접 bounded absolute map pose; anchor-residual은 2안 |
| 후보 선택 | hard veto 후 위험 우선 사전식 tournament |
| 실행 직전 | winner 하나에 최신 센서로 2~5 전체 재검사 |
| Nav2 | Recovery Envelope 안의 최종 경로 의사결정자 |
| Safety | 실제 속도의 최종 허가자 |
| 모델 운영 | Stable–Candidate bundle, 검증 후 승격·rollback |
| 학습 | 운행/복구 중 금지, 정지/docked window |
| 저장 | MySQL canonical + local FAISS/cache/append-only queue |
| 복구 실패 | attempt/거리/시간/oscillation budget 후 STOP·보고 |

## 19. gstack 기반 엔지니어링 리뷰

### Review summary

| 관점 | 열린 이슈 | 상태 | 반영 내용 |
|---|---:|---|---|
| CEO/제품 | 0 | PASS | 위험 시 완전 정지, 짧은 복구, 임무 재합류로 범위 고정 |
| Codex/Outside voice | 0 | DONE_WITH_CONCERNS | stale epoch, Nav2 path 차이, human exploration, immutable incident, compute budget 반영 |
| Engineering | 3 | ISSUES_OPEN | D25·D26·D30은 구현 전에 팀 결정 필요 |
| Design/운영자 | 0 | PASS | STOP/보고/rollback과 판단 근거를 운영 상태로 노출 |
| DX/검증 | 0 | PASS | package 경계, 단계별 test matrix, fail-closed 기준 정의 |

### Coverage and failure-first conclusion

- 기능 경로뿐 아니라 stale sensor, stale inference, goal race, localization jump, GPU OOM, DB 단절, 모든 후보 탈락을 명시했다.
- safety-critical hard rule은 learned score와 분리했고, 실제 `cmd_vel` 권한은 Safety Supervisor에 남겼다.
- 성능은 후보 수를 고정 가정하지 않고 `K*M*E*n` budget과 progressive pruning으로 통제한다.
- 테스트는 unit → replay → simulation → Pinky HIL → 제한 canary로 단계화했고 Candidate 자동 rollback을 포함했다.

**VERDICT: ENGINEERING REVIEW COMPLETE WITH 3 UNRESOLVED DECISIONS**

**UNRESOLVED DECISIONS:**
- **D25 — VLM 시간 입력:** `연속 RGB+프레임별 segmentation`, `연속 RGB+최신 segmentation+YOLO track`, `단일 RGB+현재 segmentation` 중 선택. 팀원이 생기고 카메라 FPS·segmentation 지연을 측정한 뒤 결정한다.
- **D26 — 승격 단위:** TGRPO+SAC+skill ontology를 하나의 PolicyBundle로만 승격할지, 호환성 검사를 전제로 각각 승격할지 결정한다. 현재 문서의 안전 기본값은 bundle 승격이다.
- **D30 — SAC OOD 방어:** dataset-support hard gate, soft penalty, 또는 0~6 filter만 사용할지 결정한다. 실제 map의 state coverage와 false rejection 측정 전까지 미결정으로 유지한다.
