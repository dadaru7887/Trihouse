# 핵심 코드별 변천사 (Evolution Notes)

VLM+RL 실차 복구(recovery) 파이프라인 개발 중 각 핵심 파일이 왜 지금 형태가 됐는지 정리한 문서.
버그를 어떻게 발견했는지까지 남겨서, 나중에 비슷한 증상이 재발했을 때 여기부터 확인할 수 있게 함.

---

## 1. `tgrpo_sac_hierarchical_v2.py` — 계층형 정책 (상위: TGRPO, 하위: SAC)

- **구조**: `HighLevelPolicy`(상태→skill 5종 중 선택, TGRPO로 학습) → `LowLevelPolicy`(상태+skill
  조건부→좌표(dx,dy,dyaw) 생성, SAC로 학습). skill one-hot이 SAC 입력에 실제로 concat되는
  조건부 생성 구조로 설계·검증됨.
- 이 파일 자체는 네트워크 구조 정의만 담당 — clip/KL 등 학습 안정화 로직은
  `offline_train_from_buffer.py`(학습 루프)에 있음. 두 파일을 같이 봐야 전체 그림이 보임.
- **2026-08-15 추가 — `SACAgent`에 CQL(Conservative Q-Learning) penalty 옵션**: 순수
  오프라인 학습(추가 rollout 없음)에서 SAC가 buffer에 없는 action의 Q를 과대추정하는
  문제(Fujimoto BCQ/Kumar CQL 논문)를 겨냥. `use_cql=True`면 critic loss에
  `logsumexp(Q(s, random/정책 action)) - Q(s, data action)` penalty를 추가해서 OOD action
  Q를 억제. `--low-rl cql`로 켬 — **fake 데이터로 학습 사이클만 확인, 실측 비교는 안 함**
  (`ALGORITHMS.md`, `EXPERIMENT_DESIGN.md` 0번 항목 참고).

## 2. `offline_train_from_buffer.py` — 오프라인 학습 루프 (실제 학습이 일어나는 곳)

가장 많이 바뀐 파일. 시간순 변천사:

1. **최초**: `recovery_buffer.pkl`/`recovery_policy_checkpoint.pt` 기준으로 짜여있었는데, 실제
   운영 흐름(`orchestrate_live_teleop.py`)이 쓰는 파일명(`real_recovery_buffer.pkl`,
   `sim_recovery_policy_checkpoint.pt`)과 안 맞아서 두 체크포인트로 갈라지는 문제 발견 → 경로 통일.
2. **`is_execution` 필터 추가**: buffer에 teleop 관찰 스냅샷(`skill=-1`, `reward=0`)이
   섞여있어서 `by_skill[-1]` KeyError로 죽던 버그 → 실제 실행된(`is_execution=True`) 것만 필터링.
3. **SAC 배치 샘플링 → BucketedReplaySampler 교체**: 균등 무작위 샘플링만 쓰면 원래 드문
   critical 사례가 배치에 거의 안 뽑힘 → SAFE/BOUNDARY/CRITICAL 목표비율(50/30/20) + recency
   importance weight 방식으로 교체(`replay_sampler.py`). 순환큐(오래된 데이터 삭제)는
   **의도적으로 채택 안 함** — SAC는 off-policy라 오래된 데이터도 유효하고, 데이터가 극히
   귀한 단계(30여 개)에서 버리는 건 손해라 판단.
4. **reward clip 검토 후 미채택**: PPO의 clip은 확률비율(ratio) clip이지 reward 값 clip이
   아니라서 "PPO가 안전하니 reward clip도 안전하다"는 근거가 성립 안 함 — DQN {-1,0,1} clip처럼
   서로 다른 크기의 성과를 구분 못 하게 만들 위험. tanh 기반 soft clip 옵션만 코드에 남겨두고
   기본은 꺼둠(지금 buffer엔 극단값이 없어서 필요 없음, 나중에 필요시 켤 수 있게만 해둠).
5. **Dr. GRPO advantage 정규화 이슈 조사**: reward std로 나누는 정규화가 그룹이 작을수록(우리는
   skill 5개/그룹당 평균 6개) std 추정 노이즈를 증폭시킨다는 논문 지적 확인 — 코드에 옵션만
   추가하고 기본값(기존 방식 유지)은 안 바꿈, 결정은 보류.
6. **SAC/TGRPO 데이터 소스 분리 옵션 추가**: 실측 결과 buffer를 30개→15개로 줄였을 때 SAC
   critic_loss는 오히려 좋아졌는데 TGRPO entropy는 더 빨리 무너지는 반대 경향 확인(노이즈
   아니라 실제 경향) — SAC는 최신 데이터에 강하고 TGRPO는 그룹평균 노이즈 줄이려면 데이터가
   많아야 한다는 결론. `SAC_CIRCULAR_MAXLEN`으로 SAC만 최근 N개로 제한 가능하게, TGRPO는
   항상 buffer 전체 사용.
7. **★ clip surrogate + KL penalty 추가 (가장 중요한 개선)**: 그동안 entropy 보너스만
   있었는데, 30개 데이터로 250 epoch 돌리면 TGRPO가 특정 skill에 과확신해서 entropy가
   1.59→0.28로 붕괴하는 걸 실측 확인. buffer엔 π_old의 log_prob이 저장 안 돼있어서 "학습
   시작 시점 로드한 checkpoint"를 reference로 얼려서 대신 사용(PPO가 "한 배치로 K epoch
   도는 동안 원본 정책 대비 clip"하는 것과 같은 논리). **결과: entropy 1.59→1.52로 거의
   안 무너짐(KL 0.02~0.05 유지)** — 명확한 개선이라 기본값 `True`로 채택.

## 2-1. 표준 TGRPO/GRPO 대비 구조 비교 (이 구현이 뭐가 같고 뭐가 다른가)

"이걸 TGRPO라고 부를 수 있나"를 이분법으로 따지기보다, 표준 대비 뭐가 같고 뭐가 다른지
구조적으로 비교하는 게 더 정확함. **결론: 딱 하나(그룹 구성/선택 방식)만 다르고, 나머지
안정화 장치는 전부 표준 그대로 구현돼있음.**

**표준과 동일한 부분:**
- Group-relative advantage: `advantage = reward - group_mean`(옵션으로 `/std`) — GRPO
  공식 그대로.
- Clipped surrogate objective(ratio clip, `CLIP_EPSILON=0.2`) — PPO/GRPO 표준값 그대로.
- KL penalty(reference policy 대비, `KL_COEF=0.01`) — 표준 안정화 장치.
- Entropy bonus(`ENTROPY_COEF=0.01`) — 표준 정책최적화 관행.
- 계층 구조(상위: skill 선택을 GRPO식으로, 하위: 좌표는 SAC로) 자체는 설계 문서(§9.2)의
  계층 구조를 그대로 따름.

**표준과 다른 유일한 지점 — "그룹을 어떻게 구성하는가":**
- **표준 GRPO/TGRPO**: 매 업데이트마다 **현재 정책**에서 K개 후보를 새로 샘플링 →
  각각 실제(또는 시뮬레이션) 환경에서 rollout해서 reward를 얻음 → 그 K개가 "그룹"이 되어
  group-relative advantage를 계산.
- **이 구현**: 오프라인 학습이라 실시간 rollout 환경이 없음 — 대신 **buffer에 과거에 실제로
  실행됐던 관측치**를 skill별로 모아(`by_skill` dict) 그 묶음을 그룹으로 대신 씀. reward도
  이번 스텝에 새로 rollout한 값이 아니라, buffer에 저장된 (다른 시점/다른 정책 버전으로
  실행됐을 수 있는) 과거 실행값들의 평균.

즉 "이번 스텝에 정책이 직접 낸 K개 fresh 샘플"이 아니라 "과거에 실행됐던 기록들"이 그룹
역할을 대신하는 것 — **on-policy 그룹 샘플링이 아니라 off-policy 근사**. 코드 자체 주석에도
이 한계가 명시돼있음("완전한 재시뮬레이션은 아님, 팀원 문서 §9.2의 이상적 형태보다 단순화된
버전 -- 진짜 rollout 환경 붙기 전까지의 임시 근사"). 진짜 rollout 환경이 붙으면 이 부분만
표준 방식으로 교체하면 되고, clip/KL/entropy 등 나머지 장치는 안 바꿔도 됨.

## 3. `vlm_contract_to_rl_state.py` — VLM 출력(JSON) → RL state 벡터 변환

- Qwen2.5-VL이 마크다운 코드펜스(` ```json `)로 감싸서 응답해도 정규식 기반 파서가 `{...}`만
  추출해서 문제없이 파싱하도록 이미 견고하게 구현돼있음(실측 확인).
- `robot_candidate_sectors` 필드는 처음엔 후보 좌표 생성에 썼었는데(`sectors_to_candidates()`),
  원래 설계(`tgrpo_sac_hierarchical_v2.py`)상 이 state 벡터엔 애초에 안 들어가는 무관한
  필드였음이 드러나서 **후보 생성은 VLM sectors가 아니라 RL(TGRPO-SAC)이 직접 하는 방식으로
  전환**함(`rl_candidate_group.py`). "학습 대상인 RL이 후보도 내야 학습이 의미 있다"는 원칙.

## 4. `recovery_filters.py` / `geometric_6c_lite.py` — 안전 필터 체인 (R0~R6)

- R0-06(bumper/e-stop/Safety Supervisor 관련)은 실제 로봇에 해당 토픽이 없어서 fail-closed로
  항상 막힘 — 사람이 로봇 옆에서 직접 감독하는 것으로 대체하기로 결정(무인 배포 시엔 필수 재구현).
- R5(6C-Lite, n-step 가상 rollout)는 원래 학습된 world-model 앙상블이 필요한데, 데이터가
  너무 적어서(수십 개) 학습이 불가능 → **기하학적 근사**(`geometric_6c_lite.py`)로 대체:
  costmap 기준 free space만 체크하는 규칙 기반 모듈, 사람/동적 장애물 예측은 안 함.
- **앙상블 멤버 2개로 확장**: 처음엔 `geometric_rollout_check`(local_costmap 실시간+직선보간)
  하나뿐이었는데, 이미 구현돼있던 `query_nav2_path_feasible`(Nav2 planner_server의 실제
  `compute_path_to_pose`, global_costmap 기반)를 두 번째 멤버로 추가. 완전 독립은 아니지만
  데이터 소스(실시간 vs 정적)와 경로 가정(직선 근사 vs 실제 탐색)이 달라 의미 있는
  disagreement 발생 확인됨.
- **`query_keepout_violation` 최초엔 구현 자체가 없었음**(`lambda x,y: False`로 항상 통과) —
  실제 출입금지구역 데이터가 아직 없어서 폴리곤 리스트 + point-in-polygon으로 틀만 먼저 구현,
  지금은 빈 리스트(0개 구역).

## 5. `nav_recovery_executor.py` — RL 후보를 Nav2 액션으로 실제 실행

- **좌표 프레임 버그(가장 심각했던 버그)**: BACKUP/REROUTE_LEFT/REROUTE_RIGHT/(원래)REJOIN이
  `coord`를 "로봇 기준 상대 offset"으로 해석하는데, 호출부가 절대 map 좌표를 그대로 넘기고
  있었음 — envelope 0.25m로 clamp해놨는데 실제로는 map 좌표값(최대 ~2m)만큼 움직이려 드는
  버그. "recovery가 너무 많이 간다"는 실측 관찰로 발견, `winner.offset`(SAC가 실제로 낸
  상대 dx,dy,dyaw)을 쓰도록 수정.
- **회전(dyaw) 미clamp**: 거리는 clamp했는데 회전각은 안 걸어놔서 최대 204도(거의 반바퀴)
  회전이 실측 확인됨 — `YAW_CLAMP_RAD=π/3(60도)` 추가.
- **REJOIN 방식 교체**: NavigateToPose로 최종 orientation까지 맞추려다 15초 타임아웃씩 걸리고
  실패하는 경우 발생, 위험근접 상황까지 한 번 이어짐 — Spin+DriveOnHeading(상대offset)
  방식으로 교체해서 모든 skill이 균일하게 상대offset을 쓰도록 단순화.
- **odom/map 프레임 혼동 버그**: `_get_pos()`가 `/odom`을 그대로 썼는데 이 값이 map 프레임
  기준 `dist_to_goal()`에 바로 들어가던 버그 — `orchestrate_live_teleop.py`에서 먼저 발견된
  것과 같은 패턴, TF(`map`→`base_footprint`) 우선 조회로 수정.
- Ctrl+C(KeyboardInterrupt) 시 goal 취소 안 하고 그냥 죽던 안전 버그 → 명시적
  `cancel_goal_async()` 호출 후 재전파하도록 패치(로봇이 스크립트 종료 후에도 계속 움직이는
  실제 사고 이력 있음).

## 6. `orchestrate_live_teleop.py` — 메인 오케스트레이션 진입점

- teleop 관찰 → `--execute` 플래그로 실제 Nav2 자율 실행까지 확장.
- **쿨다운이 실행시간에 먹히는 버그**: 실행+재관측(수 초)이 `VLM_COOLDOWN_SEC`(8초)을 거의
  다 소진해서 실행 직후 같은 장애물이 바로 재트리거되는 문제 → 실행 완료 시점부터 쿨다운
  재시작하도록 수정.
- **트리거 조건 정교화**: 처음엔 `--simple-trigger`(obstacle 감지=무조건 발동, 배선 검증용)
  로 시작 → `ObjectWatcher`의 3조건(신규출현확정/경로상물체/접근중)으로 정교화.
  `CONFIRM_FRAMES=3`(저confidence 노이즈 27~44%→7.7%로 감소), LiDAR 콘 각도 30도→75도
  확장(화면 가장자리 물체가 카메라엔 가까이 보이는데 LiDAR 콘 밖이라 못 잡던 문제 해결),
  "신규출현" 트리거에 위치 게이트(MIDDLE/BOTTOM만 인정, TOP 제외) 추가.
- **reward 파라미터를 실제 방 스케일(2.15×2.65m)에 맞게 재조정**: `MISSION_REJOINED_THRESHOLD_M`
  1.0→0.15m, `clearance_cost` 기준거리 1.5→0.3m — 이 방이 "테스트용 임시 작은 방"이 아니라
  **실제 배포 환경 자체**임을 확인한 뒤 반영(나중에 큰 창고로 옮기면 다시 조정할 값이 아님).

## 7. `rl_candidate_group.py` — K×M 후보 생성 (VLM sectors 대체)

- `HighLevelPolicy.sample(state,k)` + skill마다 `LowLevelPolicy.sample()` M번 호출로 K×M개
  후보 생성. 체크포인트가 거의 미학습이라 SAC 좌표 offset이 `COORD_SCALE=2.0`(최대 ~2m)에
  가깝게 튀는 경우가 잦아서 처음 0.4m로 clamp → survivor율 1.3%로 너무 낮아서 0.25m로 재조정.

## 8. `vlm_comparison_*.py` — VLM 모델 비교 실험

- `vlm_comparison_7b.py` / `vlm_comparison_3b_4bit.py`: Qwen2.5-VL 7B(품질 검증용, 5080에서
  주로 실행) vs 3B 4bit(오케스트레이션 테스트용 경량 모델) 개별 비교.
- `vlm_comparison_multi.py`: 여러 모델을 한 번에 비교하는 통합 버전.
- `objective_json_compare.py`: 응답 JSON을 정성적 판단이 아니라 정량적 기준으로 비교.
- `fair_speed_memory_compare.py`: 속도/메모리 사용량 공정 비교(조건 통일).
- 최종 파이프라인은 오케스트레이션 실시간성 때문에 **3B 4bit를 기본으로 채택**, 최종 학습
  데이터/모델 품질 검증은 7B로 별도 진행하는 이원화 전략.

---

## 다음 사람이 알아야 할 것

- **buffer 데이터가 아직 극히 적음(30여 개 transition)** — 지금 학습 결과(loss 수치 등)를
  "정답"으로 신뢰하지 말 것, 스모크테스트(코드가 안 죽고 도는지 확인) 성격.
- **`recovery_system_node.py`(통합 노드)는 TODO 상태** — 지금 학습된 checkpoint를 로드해서
  실제 관제에 쓰는 코드가 아직 없음. `offline_train_from_buffer.py`가 저장한 checkpoint를
  로드하는 코드를 추가해야 함.
- **R0-06/R5 안전필터가 완전한 형태가 아님** — 사람 감독으로 대체된 부분이 있어서, 무인 배포
  전에는 반드시 재검토 필요.
