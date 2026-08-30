#!/usr/bin/env bash
# VLM+RL 오프라인 학습 CLI
#
# 사용법:
#   ./train.sh                                        # 기본값: real buffer, tgrpo, sac, 20 epoch
#   ./train.sh --source real --high-rl dapo --epochs 50
#   ./train.sh --source real --high-rl dr_grpo
#   ./train.sh --source sim  --epochs 20
#   ./train.sh --mode compare-vlm --vlm 3b_4bit
#
# --source real   : real_recovery_buffer.pkl (실제 로봇 실행 데이터, teleop 데모 데이터 -> 데이터 재수집 필요)
# --source sim    : sim_recovery_buffer.pkl (시뮬레이션 데이터, --high-rl 옵션 미지원 -- 구버전 스크립트)
# --high-rl       : tgrpo(기본, std 정규화) | dr_grpo(std 정규화 생략) | dapo(비대칭 clip+dynamic
#                    sampling, 2026-08-15 신규, 아직 실측 비교 안 함) -- --source real 에서만 동작
# --low-rl        : sac(기본) | cql(Conservative Q-Learning penalty 추가, 순수 오프라인 학습의
#                    OOD action Q 과대추정 문제 완화 목적, 2026-08-15 신규, 아직 실측 비교 안 함)
#                    -- --source real 에서만 동작(sim 스크립트는 구버전, sac 고정)
# --mode          : train(기본, 학습 실행) | compare-vlm(VLM 모델 비교 실험 실행, 학습 아님)
# --vlm           : compare-vlm 모드에서만 사용. 7b | 3b_4bit | multi
set -e

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODE="train"
SOURCE="real"
HIGH_RL="tgrpo"
LOW_RL="sac"
EPOCHS=20
VLM="3b_4bit"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode) MODE="$2"; shift 2 ;;
    --source) SOURCE="$2"; shift 2 ;;
    --high-rl) HIGH_RL="$2"; shift 2 ;;
    --low-rl) LOW_RL="$2"; shift 2 ;;
    --epochs) EPOCHS="$2"; shift 2 ;;
    --vlm) VLM="$2"; shift 2 ;;
    -h|--help)
      sed -n '2,17p' "${BASH_SOURCE[0]}"
      exit 0 ;;
    *)
      echo "알 수 없는 옵션: $1" >&2
      exit 1 ;;
  esac
done

if [[ "$LOW_RL" != "sac" && "$LOW_RL" != "cql" ]]; then
  echo "!! --low-rl=$LOW_RL 은 미구현 -- sac 또는 cql만 가능" >&2
  exit 1
fi

export PYTHONPATH="$HERE/02_pipeline_core:$PYTHONPATH"

if [[ "$MODE" == "compare-vlm" ]]; then
  cd "$HERE/01_vlm_comparison"
  case "$VLM" in
    7b) python3 vlm_comparison_7b.py ;;
    3b_4bit) python3 vlm_comparison_3b_4bit.py ;;
    multi) python3 vlm_comparison_multi.py ;;
    *) echo "--vlm 은 7b | 3b_4bit | multi 중 하나" >&2; exit 1 ;;
  esac
  exit 0
fi

cd "$HERE/03_results"   # buffer/checkpoint .pkl/.pt가 상대경로(./xxx.pkl)로 여기 있다고 가정

case "$SOURCE" in
  real)
    echo "[train.sh] real_recovery_buffer.pkl 기준, high-rl=${HIGH_RL}, low-rl=${LOW_RL}, ${EPOCHS} epoch 학습"
    python3 "$HERE/04_training/offline_train_from_buffer.py" --epochs "$EPOCHS" --high-rl "$HIGH_RL" --low-rl "$LOW_RL"
    ;;
  sim)
    if [[ "$HIGH_RL" != "tgrpo" || "$LOW_RL" != "sac" ]]; then
      echo "!! --source sim 은 --high-rl/--low-rl 옵션 미지원(구버전 스크립트, tgrpo+sac 고정)" >&2
      exit 1
    fi
    echo "[train.sh] sim_recovery_buffer.pkl 기준, ${EPOCHS} epoch 학습"
    python3 "$HERE/04_training/offline_train_from_sim_buffer.py" "$EPOCHS"
    ;;
  *)
    echo "--source는 real 또는 sim 이어야 함 (입력값: $SOURCE)" >&2
    exit 1
    ;;
esac
