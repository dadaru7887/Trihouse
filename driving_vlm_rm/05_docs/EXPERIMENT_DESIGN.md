# 다음 학습 방향 제안 / Ablation Study 아이디어

`offline_train_from_buffer.py`에 이미 옵션으로 구현은 돼있지만 아직 "켜서 실측 비교"까지는
안 한 것들 위주로 정리. 전부 코드 수정 없이 상단 상수만 바꿔서 바로 실험 가능.

## 0. SAC vs CQL (하위 정책, 2026-08-15 추가)

- **변수**: `--low-rl sac`(기본) vs `--low-rl cql`
- **가설**: 순수 오프라인 학습(추가 rollout 없이 buffer만 replay)에서 SAC는 buffer에 없는
  action의 Q값을 과대추정하는 경향이 알려져 있음 -- CQL은 그 OOD action Q를 명시적으로
  누르는 penalty를 추가함. 데이터가 적을수록(우리 상황) 이 문제가 더 심할 것으로 예상.
- **실험**: 같은 buffer로 두 번 돌려서 (a) 학습된 정책이 실제로 buffer에 있던 action 근처로
  더 수렴하는지(action 분포 비교) (b) Q값 스케일 자체가 CQL 쪽이 더 보수적인지
  (`avg_critic_loss`/`avg_cql_loss`를 `train_log_*.csv`에서 비교) 확인. **우선순위 1순위로
  추천** -- 다른 ablation(1~8번)보다 이게 먼저 필요함, 나머지는 "어떤 정책이 좋은가"를
  다투는 거고 이건 "애초에 이 학습 방식이 오프라인 세팅에 맞는가"를 다투는 더 근본적인 질문임.

## 1. Advantage 정규화: std로 나누기 vs Dr. GRPO 방식

- **변수**: `ADVANTAGE_STD_NORM` (True/False)
- **가설**: 우리 규모(skill 5개, 그룹당 평균 6개 샘플)에서는 std 추정 자체가 노이즈라, 우연히
  std 작게 나온 그룹의 advantage가 과도하게 부풀려질 수 있음(Dr. GRPO 논문 지적).
- **실험**: 같은 buffer로 `True`/`False` 두 번 돌려서 (a) entropy 붕괴 속도 (b) 특정 skill로의
  쏠림 정도를 비교. 데이터가 지금보다 많아지면(그룹당 20개+) 차이가 줄어들 것으로 예상 —
  buffer 크기별로도 비교해보면 좋음.

## 2. SAC/TGRPO 데이터 소스 분리 (`SAC_CIRCULAR_MAXLEN`)

- **변수**: `None`(전체 사용, 기본값) vs 숫자(예: 15, 20)
- **이미 실측된 단서**: buffer 30개→15개로 자르면 SAC critic_loss는 좋아지고 TGRPO entropy는
  더 빨리 무너지는 반대 경향 확인됨(같은 소스 부분집합 비교, 노이즈 아님).
- **실험**: `SAC_CIRCULAR_MAXLEN`을 10/15/20/None으로 스윕하면서 SAC critic_loss와 TGRPO
  entropy를 같이 플롯 — "SAC엔 최신 데이터가 유리하고 TGRPO엔 데이터량이 유리하다"는 가설을
  buffer가 커진 뒤에도 재확인.

## 3. Reward soft-clip (`REWARD_SOFT_CLIP_SCALE`)

- **변수**: `None`(기본, 비활성) vs 숫자(예: 10.0)
- 지금은 buffer에 극단값이 없어서 꺼져있음. buffer가 커져서 진짜 극단적 실패/성공 사례가
  쌓이면, tanh 기반 soft clip(순서는 보존하면서 큰 값만 압축)을 켜서 학습 안정성에 영향
  있는지 확인할 가치 있음.

## 4. clip+KL 하이퍼파라미터 민감도

- **변수**: `CLIP_EPSILON`(현재 0.2, PPO 표준값), `KL_COEF`(현재 0.01)
- 지금 값은 "표준값을 가져다 썼다" 수준이지 우리 데이터 규모(30여 개)에 맞춰 튜닝된 게 아님.
- **실험**: `KL_COEF`를 0.005/0.01/0.02로 스윕, entropy 붕괴 방지 효과와 학습 속도(loss
  수렴 속도) 트레이드오프 확인.

## 5. 6C-Lite 앙상블 멤버 확장 (E=2 → E=3+)

- 지금 앙상블 멤버가 2개(`geometric_rollout_check`: 실시간 local_costmap+직선보간,
  `query_nav2_path_feasible`: 정적 global_costmap+실제 Nav2 planner)뿐. 둘 다 결국 Nav2
  costmap 계열이라 완전 독립은 아님.
- **아이디어**: 세 번째 멤버로 다른 성격의 체크 추가 — 예를 들어 LiDAR raw scan을 직접 쓰는
  체크(costmap을 안 거치는 독립 경로), 또는 다른 inflation 파라미터로 본 costmap.
  E가 늘어나면 `Risk_UCB = 평균 + kappa*표준편차`의 표준편차 추정이 더 의미 있어짐(§8 원래
  설계와 더 가까워짐).

## 6. 후보 개수 K×M 스윕

- 지금 기본값 `CANDIDATE_K=3, CANDIDATE_M=2`(트리거당 6개 후보) — 이 값 자체가 실측
  근거보다는 "일단 이 정도로 시작" 수준.
- **실험**: K/M을 늘렸을 때 (a) 6C-Lite survivor 비율 (b) 최종 선택된 후보의 목표 방향
  일치도(현재 offset 스케일 0.25m에서는 방향이 최대 -151도까지 벌어지는 경우 실측됨)가
  개선되는지 확인. 연산 예산(`K×M×E×n ≤ B_compute`)과의 트레이드오프도 같이 기록.

## 7. Envelope(offset clamp) 크기

- 지금 0.25m로 clamp(`COORD_SCALE=2.0`인 미학습 체크포인트가 너무 크게 튀어서 0.4m→0.25m로
  축소한 이력 있음). 정책이 더 학습되면(buffer가 커지면) 이 clamp를 다시 늘려도 되는지,
  아니면 학습 진행도에 따라 동적으로 조절하는 게 나을지 검토 가치 있음.

## 8. rejoin_bonus를 flat(+10) → 거리비례 스케일링

- 현재 `compute_real_reward()`가 mission rejoin 보너스를 flat(+10)으로 주는데, 거리
  비례(가까울수록 큰 보너스)로 바꾸면 "얼마나 잘 복귀했는지"까지 반영돼서 신호가 더
  촘촘해질 수 있음. 아직 실측 비교는 안 함.

---

## 우선순위 제안 (buffer가 지금보다 커진다는 전제)

1. **0번(SAC vs CQL)** — 가장 근본적인 질문(학습 방식 자체가 오프라인 세팅에 맞는가)이라
   제일 먼저. 다른 ablation 결과 해석이 이 선택에 따라 달라질 수 있음.
2. **6번(K×M 스윕)** — 방향 일치도 문제가 실측으로 이미 확인된 상태라 시급.
3. **2번(SAC/TGRPO 데이터 분리)** — 이미 실측 단서가 있어서 정식 실험으로 완성하기 쉬움.
4. **5번(6C-Lite 앙상블 확장)** — 안전 관련이라 우선순위 높지만 새 체크 로직 설계가 필요해서
   상대적으로 무거움.
5. 나머지(1, 3, 4, 7, 8)는 buffer 크기가 지금(30여 개)보다 충분히 커진 뒤(수백 개 이상)
   시도하는 게 신호 대 노이즈 비 측면에서 더 의미 있을 것으로 예상.
