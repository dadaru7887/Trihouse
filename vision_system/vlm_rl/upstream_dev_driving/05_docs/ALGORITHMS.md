# 알고리즘 구현 현황 — 뭐가 진짜 되고 뭐가 로드맵인지

`train.sh`로 바로 실험 돌리기 전에 이 표부터 볼 것. **"코드에 옵션이 있다" ≠ "실측 검증됐다"**를
명확히 구분해뒀음.

| 항목 | 상태 | 비고 |
|---|---|---|
| TGRPO (std 정규화 + clip + KL) | 구현+실측 검증됨 | 2026-08-12, entropy 1.59→1.52로 붕괴 방지 확인 (기본값) |
| Dr. GRPO (std 정규화 생략) | 구현+부분 검증 | 옵션은 실측했으나 "거의 무효과"로 판단, 기본 채택 안 함 |
| DAPO (Clip-Higher + dynamic sampling) | 구현만 완료, 실측 안 함| 2026-08-15 신규 추가, 단위테스트(synthetic data)만 통과 확인. 실제 buffer로 ablation 실험 필요 |
| SAC (하위 정책) | 구현+검증됨 | 기본값(`--low-rl sac`) |
| CQL (SAC + Conservative penalty) | 구현만 완료, 실측 안 함 | 2026-08-15 신규 추가. 순수 오프라인 학습(추가 rollout 없음)에서 SAC의 OOD action Q 과대추정 문제(Fujimoto BCQ/Kumar CQL)를 겨냥한 선택 -- 우리 세팅(buffer만으로 학습)에 이론적으로 잘 맞음. `--low-rl cql`로 켬. fake 데이터로 학습 사이클(critic+cql loss 둘 다 CSV에 기록됨)만 확인, 실제 buffer 비교는 안 해봄 |
| 학습된(neural) world-model | 없음 | 2026-08-11에 조사 후 "데이터 부족(수십 개)으로 지금은 불가능"이라 결론, 대안(VLM을 언어기반 저비용 world-model 대용으로 쓰는 아이디어)기록|
| 6C-Lite(규칙 기반 근사) |구현+검증됨 | `geometric_6c_lite.py` — costmap 직선보간 체크. 순수 기하학적 규칙|
| 6C-Lite 2-멤버 앙상블 disagreement | 기록만 됨, 분석 스크립트 없음| `geometric_rollout_check`(실시간 costmap)+`query_nav2_path_feasible`(Nav2 planner) 두 규칙 기반 체크가 서로 다른 판정 내는 비율을 `n_disagree`로 buffer meta에 남기지만, 둘 다 결국 Nav2 costmap 계열이라 완전 독립은 아님 |
| VLM 비교 (7B vs 3B-4bit) | 구현+실측 완료 | `01_vlm_comparison/` 참고, 결과 JSON까 |

## DAPO 실측 전 체크리스트 (5080에서 처음 돌릴 때)

1. `real_recovery_buffer.pkl`에 `is_execution=True` transition이 최소 4개 이상 있는지 확인
   (`python3 -c "import pickle; b=pickle.load(open('real_recovery_buffer.pkl','rb')); print(sum(1 for t in b if t.get('meta',{}).get('is_execution')))"`)
   — 지금 로컬 buffer는 0개라 실제 학습 루프 자체가 안 돌아감(설계상 안전하게 막힘).
2. 부족하면 `orchestrate_live_teleop.py --execute`를 실물 로봇에서 더 돌려서 채워야 함(사람
   감독 하에 Nav2가 실제로 실행).
3. 충분해지면: `./train.sh --source real --high-rl tgrpo` vs `--high-rl dapo`를 같은 buffer로
   비교 — entropy 붕괴 속도, `clip_ratio_mean`, `tgrpo_loss` 수렴 양상 비교.
4. `EXPERIMENT_DESIGN.md`에 이미 정리된 다른 ablation(SAC window, advantage 정규화 등)과
   같이 묶어서 실험표로 정리하면 좋음.

**단계별로 필요할 수 있는 것 (데모코드)**:
1. 지금 있는 규칙 기반 2-멤버 disagreement 리포트 
2. VLM을 world-model 대용
3. 학습된 neural world-model (buffer내 데이터 많이 필요)


| 파일 | 로드맵 단계 | 상태 |
|---|---|---|
| `disagreement_report.py` | 1번| 구조 확인됨 |
| `world_model_ensemble.py` + `train_world_model.py` | 3번| fake 데이터로 학습→저장→로드까지 전체 사이클 확인됨. 작은 MLP 5개 앙상블(PETS/MBPO류 model-based RL의 표준 패턴), bootstrap resampling 최소 30~50개 실행 transition 있어야 의미 있는 학습 기대 가능(정책 학습보다 dynamics 학습이 데이터를 더 요구함) |
| `vlm_world_model_demo.py` | 2번| 파싱/변환 로직만 확인됨(fake 텍스트로) — 프롬프트가 이 JSON 형식을 안정적으로 내는지는 5080에서 처음부터 실측 조정 필요|

