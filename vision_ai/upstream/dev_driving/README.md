# VLM+RL 복구(Recovery) 파이프라인 — 정리본

실차 장애물 회피/복구 파이프라인(세그멘테이션 트리거 → VLM 상태 판단 → RL 후보 생성 →
안전 필터 → Nav2 실행 → reward 계산 → 오프라인 학습)의 핵심 코드/결과/문서 모음.

> 이 폴더는 2026-08-14~15 야간 세션에 로컬 백업(5080→4060 마이그레이션 이전 코드 포함)에서
> 큐레이션한 것. **4060에만 있고 여기 없는 것들(최신 checkpoint, 추가 buffer 데이터 등)은
> 내일 직접 4060 접속해서 보강 예정.**

## 폴더 구조

```
01_vlm_comparison/   VLM 모델 비교 실험 (7B vs 3B-4bit, 속도/메모리/품질)
02_pipeline_core/    핵심 파이프라인 코드 (트리거→VLM→RL→안전필터→Nav2실행)
03_results/          실행 결과물 (trigger 로그 CSV, buffer pkl, 트리거 프레임/영상)
04_training/         오프라인 학습 스크립트 (SAC+TGRPO/Dr.GRPO/DAPO)
05_docs/             변천사(EVOLUTION.md), 알고리즘 현황(ALGORITHMS.md), 실험 제안(EXPERIMENT_DESIGN.md), 시나리오 가이드(SCENARIO_DESIGN.md)
06_world_model/      학습된 world-model 앙상블 + VLM-world-model 데모 (전부 미검증, 코드만 준비됨)
07_distillation/      HighLevelPolicy(고수준 skill 선택) distillation — soft teacher 학습 +
                       ablation + 배포용 uncertainty fallback 게이팅 (2026-08-25, 정확도 40.2%)
train.sh             CLI 진입점 (학습 + VLM 비교 둘 다 여기서)
```

## 빠른 시작

```bash
# 학습 (기본: 실제 로봇 buffer, TGRPO, 20 epoch)
./train.sh

# 알고리즘 비교
./train.sh --high-rl dr_grpo
./train.sh --high-rl dapo        # 2026-08-15 신규, 아직 실측 안 함 -- 05_docs/ALGORITHMS.md 먼저 볼 것

# VLM 비교 실험
./train.sh --mode compare-vlm --vlm 3b_4bit
```

**먼저 읽을 것**: `05_docs/ALGORITHMS.md` — 뭐가 실측 검증됐고 뭐가 "구현만 되고 아직
안 돌려본 것"인지 표로 정리해뒀음. 특히 DAPO는 코드는 동작하지만(단위테스트만 통과)
실제 buffer로 ablation 비교는 아직 안 함.

## 알아야 할 핵심 제약

- **buffer 데이터가 아직 극히 적음** (`real_recovery_buffer.pkl` 기준 실제 실행된
  transition 0~30여 개 수준). 학습 결과 수치를 "정답"으로 보지 말고 "코드가 안 죽고
  도는지" 스모크테스트 성격으로 볼 것.
- **`recovery_system_node.py`(통합 관제 노드)는 아직 없음** — 여기 있는 코드들은 각자
  검증됐지만, 학습된 checkpoint를 로드해서 실제로 로봇을 관제하는 조립 코드가 빠져있음.
- **안전필터(R0-06, R5) 일부가 사람 감독으로 대체됨** — 무인 배포 전에는 재구현 필요
  (자세한 건 `05_docs/EVOLUTION.md` 4번 항목).

## 자세한 내용

- 각 핵심 파일이 왜 지금 형태가 됐는지(버그/실측 이력 포함): `05_docs/EVOLUTION.md`
- 표준 TGRPO/GRPO 대비 이 구현이 뭐가 같고 다른지: `05_docs/EVOLUTION.md` 2-1절
- **전체 흐름도(카메라→트리거→VLM→RL→안전필터→Nav2→reward→buffer→학습)**: `05_docs/ARCHITECTURE.md`
- 다음에 시도해볼 ablation 아이디어 8개 + 우선순위: `05_docs/EXPERIMENT_DESIGN.md`
- 데이터 수집 시나리오(스토리형 8개 + 운행 체크리스트 + 비상상황 우선순위): `05_docs/SCENARIO_DESIGN.md`
- world-model 로드맵 데모 코드(구조만 확인됨, 미검증): `06_world_model/`
- HighLevelPolicy distillation(soft teacher 학습, ablation, 배포용 fallback 게이팅): `07_distillation/README.md`
