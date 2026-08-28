# VLM+RL 주행 통합

원본 `dev_driving:driving_vlm_rm`의 전체 파일은
[`upstream_dev_driving/`](upstream_dev_driving/)에 기준 커밋
`1da96984762834c77ddc093cdc1a5c28e54dce40`(2026-08-25) 그대로 보관했다. 그 보관본은 비교 실험,
학습 스크립트, 결과 샘플, world-model 초안, high-level skill selector distillation을 포함한다.
운영에 쓰는 코드는 원본을 직접 실행하지 않고 현재 `model/vlm_rl`의 계약 검증·체크포인트
검증·Gateway 제안 경계를 사용한다.

## 세 분리 경로

| 경로 | 역할 | 실행 |
| --- | --- | --- |
| `collection/` | Nav2 자율주행과 규칙 기반 주행의 이벤트를 계속 기록하고, 실제 완료된 복구 전이만 학습 데이터로 기록 | `python -m vision_system.vlm_rl.collection.ingest_jsonl events.jsonl --dataset-dir dataset/vlm_rl` |
| `training/` | `recovery_transitions.jsonl`만 읽어 TGRPO+SAC 정책을 오프라인 학습 | `python -m vision_system.vlm_rl.training.train_policy --dataset-dir dataset/vlm_rl --checkpoint artifacts/recovery.pt` |
| `runtime/` | 검출→엄격 JSON VLM 프롬프트→승인 checkpoint 정책→Gateway proposal을 실행 | `python -m vision_system.vlm_rl.runtime.run_emergency_inference --runtime-mode simulation` |

`navigation_events.jsonl`은 정상/규칙 주행 분석·재현용이고, 그대로 RL 학습에 섞이지 않는다.
`recovery_transitions.jsonl`은 실제로 실행되어 완료된 VLM+RL 복구 전이만 담는다. 따라서
관찰 전용, 거절된 제안, VLM의 미확정 응답은 학습 오염을 일으키지 않는다.

## Distilled skill selector

`upstream_dev_driving/07_distillation/`은 원본이 2026-08-25에 추가한 high-level skill selector
distillation이다. 6C-Lite 후보평가를 soft teacher로 써서 `HighLevelPolicy`만 지도학습으로 다시
맞춘 결과물이고(5-seed 앙상블, 원본 보고 정확도 40.2%), 앙상블 만장일치 + 평균 entropy ≤ 1.5일
때만 학습된 selector를 신뢰한다.

운영 이식본은
[`model/vlm_rl/inference/distilled_selector.py`](../../model/vlm_rl/inference/distilled_selector.py)다.
게이팅 수식은 원본 그대로이고, Trihouse 쪽에서 다음을 더한다.

- 앙상블은 `load_checkpoint`의 승인·SHA-256 검증을 통과해야 적재된다.
- bundle의 `state_dim`/`n_skills`/`skill_names`가 `shared/contracts.py`의 고정 계약과
  다르면 적재를 거부한다. 별도 `HighLevelPolicy` 정의를 두지 않고 운영 정책망을 그대로 쓴다.
- selector는 **이미 motion boundary를 통과한 후보 중에서만** 승자를 바꾼다. 학습된 skill에
  해당하는 안전 후보가 없으면 기존 goal-distance 승자를 유지한다. 즉 selector가 안전 필터에
  걸린 동작을 되살릴 수 없다.

판단 근거는 제안의 `skill_selection`에 실려 Gateway와 DB(`recovery_proposals.skill_selection`,
migration `005`)에 남는다. `source`가 `distilled_ensemble`이면 학습 selector가 승자를 정한
것이고, `goal_distance_fallback`이면 게이트가 자신 없어서(또는 안전 후보가 없어서) 기존 방식으로
돌아간 것이다. fallback 비율은 이 컬럼만 집계하면 나온다.

기본값은 **비활성**이다. `RECOVERY_SELECTOR_ENSEMBLE`과 `RECOVERY_SELECTOR_SHA256`을 둘 다
설정해야 켜지고, 하나만 설정하면 런타임이 기동을 거부한다. 둘 다 비우면 distillation 도입 전과
동일하게 goal-distance 후보 선택만 쓴다.

원본 `07_distillation/README.md`가 참조하는
`docs/vlm_rl_distillation_final_report_2026-08-25.md`와
`docs/vlm_rl_small_data_conservative_selector_proposal_2026-08-25.md`는 `dev_driving`에
커밋되어 있지 않다. 보관본에도 없으니 수치를 인용할 때는 원본 README의 요약만 근거로 쓴다.

## 실시간 실행 경계

기본 자율주행은 Nav2, 배터리·비상 같은 결정론적 조건은 규칙 기반 경로가 처리한다. VLM은
Nav2가 막힘/위험을 판정한 예외에만 호출된다. 프롬프트는
[`model/vlm_rl/inference/vlm_interpreter.py`](../../model/vlm_rl/inference/vlm_interpreter.py)의
`CONTRACT_PROMPT_TEMPLATE`로 고정되어 있으며, `observations`, 후보 섹터, 불확실도를 JSON으로
강제한다. RL은 5개 제한된 복구 skill과 작은 상대 이동 후보만 제안한다.

어느 경로도 raw `/cmd_vel`을 발행하지 않는다. Gateway 승인, Nav2 계획 가능성, 그리고
로봇 측 Safety Supervisor의 최종 허용을 모두 통과해야만 실제 움직임이 발생한다. 물리 실행은
추가로 `VLM_RL_EXECUTION_MODE=operator_approved`가 필요하다.

## 수집 envelope 예시

```json
{"kind":"navigation","event":{"source":"nav2","event_type":"state","device_id":"PK-01","navigation_state":"navigating","frame_ref":"recording://episode/42"}}
{"kind":"navigation","event":{"source":"rule","event_type":"intervention","device_id":"PK-01","rule_id":"battery_critical","action":"return_to_charge"}}
```

복구 완료 envelope는 Gateway가 받은 `build_completion(...)` 결과를 `completion` 필드에 그대로
넣는다. 완료되지 않았거나 `meta.is_execution`이 `true`가 아닌 레코드는 거부된다.
