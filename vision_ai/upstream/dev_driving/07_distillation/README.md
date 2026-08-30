# High-level Skill Selector Distillation — 2026-08-25

`02_pipeline_core`의 TGRPO `HighLevelPolicy`(discrete skill 선택)를, 매 스텝 6C-Lite 후보평가를
soft teacher로 쓰는 지도학습(distillation)으로 별도 재현·검증한 결과물. `LowLevelPolicy`/SAC
critic/Nav2 안전필터는 전혀 건드리지 않음 — 여기서 만드는 건 `HighLevelPolicy` 파라미터뿐.

## 핵심 결과

- 최종 앙상블(5-seed) 정확도: **40.2%** (실제 실행된 skill과 일치하는지 기준, random baseline 20%의 2배)
- 하이퍼파라미터 27조합 전수 스윕 결과 현재 설정(hidden=64, weight_decay=1e-3, temperature=0.5)이 이미 최적
- 배포 시 안전장치: 앙상블 5개가 top1 만장일치 + 평균 entropy ≤ 1.5일 때만 학습된 selector를 신뢰하고,
  그 외엔 기존 6C-Lite 방식으로 자동 fallback (`distilled_selector_gate.py`). 실측 데이터 기준 58%는
  selector 신뢰, 42%는 fallback.
- 전체 조건 비교(A~D, ablation)와 데이터/학습 조건 상세는 `docs/vlm_rl_distillation_final_report_2026-08-25.md` 참고.

## 폴더 구성

```
code/
  distill_high_level.py      -- 최종 학습 스크립트 (soft target + pairwise + 미러링 + 5-fold + 앙상블)
  ablation_high_level.py     -- 조건 A/B/C/D 비교용 (distill_high_level.py와 동일 split/seed 재사용)
  distilled_selector_gate.py -- 배포용: 앙상블 로드 + uncertainty fallback 게이팅
weights/
  high_level_distilled_ensemble.pt  -- 학습된 5-seed 앙상블 (distill_high_level.py 출력물)
data/
  real_recovery_buffer.pkl   -- 학습에 실제로 쓴 버퍼(154 레코드, 84 실행분). 02_pipeline_core와
                                 별개로 여기 동봉 — 03_results의 buffer는 2026-08-15 스냅샷이라
                                 이 결과를 그대로 재현하려면 이 파일 기준이어야 함.
docs/
  vlm_rl_distillation_final_report_2026-08-25.md          -- 최종 결과 리포트 (데이터/학습조건/정확도/게이팅)
  vlm_rl_small_data_conservative_selector_proposal_2026-08-25.md -- 이 학습법을 왜 이렇게 설계했는지 원 제안서
```

## 어떻게 연결하는지

`distilled_selector_gate.py`의 `select_skill_or_fallback()`을 `orchestrate_live_teleop.py`가 후보
winner를 정하기 직전에 호출하면 됨. 판단만 하고 실행은 안 하므로 안전 관련 로직(6C-Lite, Nav2 필터)은
그대로 유지된 채 위에 얹는 구조.

## 재현 명령어

```bash
# 최종 학습 (앙상블 5개 생성)
python3 code/distill_high_level.py   # data/real_recovery_buffer.pkl 기준, ./distill_high_level_out/ 에 출력

# ablation (A/B/C/D 조건 비교)
python3 code/ablation_high_level.py
```
