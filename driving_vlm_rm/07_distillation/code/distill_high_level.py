"""6C-Lite 후보평가(candidate_reward_estimates)를 soft teacher로 써서 HighLevelPolicy만
지도학습(distillation)한다. 코덱스 제안(vlm_rl_small_data_conservative_selector_proposal_
2026-08-25.md) 그대로 구현. LowLevelPolicy/SAC critic/Nav2 safety filter는 전혀 안 건드림 --
이 스크립트는 HighLevelPolicy 파라미터만 만든다.

핵심 로직:
  1. 각 실행 transition마다 candidate_reward_estimates에서 rollout_passed=True인 것만 남김
  2. skill별로 그 중 최고 estimated_reward를 skill 점수로 사용 (후보 없으면 mask)
  3. temperature softmax로 5-skill soft target distribution 생성
  4. HighLevelPolicy(state) 출력과 soft target 사이 KL divergence 최소화
  5. sample weight = exp(-|actual_reward - selected_estimated_reward| / tau) --
     실제로 선택된 skill의 실측 reward와 6C-Lite 추정치가 얼마나 가까웠는지로 teacher 신뢰도 반영.
     단, clearance 버그 수정 전(49개) 데이터는 actual_reward 자체가 회피신호 없이 계산된
     거라 이 가중치를 그대로 믿지 말라는 게 코덱스 지적 -- weight_confidence_valid=False로
     별도 표시만 하고 지우지는 않음(제거하면 84->35개로 데이터가 너무 줄어듦).
  6. state-only 제한 미러링(next_state 안 씀, augment_mirror.py의 전체 transition 버전과
     다름)으로 augmentation.
  7. 5-fold CV (session/run 단위로 group split -- 같은 run 안 트리거들이 train/val에
     동시에 안 들어가게).
  8. 앙상블 5개(다른 seed) 학습 -- 나중에 uncertainty fallback 게이팅에 씀.

사용:
    python3 distill_high_level.py
(buffer 있는 ~/driving_pipeline/ 에서 실행, real_recovery_buffer.pkl 읽음)
"""

from __future__ import annotations

import math
import pickle
from collections import defaultdict
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

BUFFER_PATH = "./real_recovery_buffer.pkl"
OUT_DIR = Path("./distill_high_level_out")
STATE_DIM = 9
N_SKILLS = 5
SKILL_NAMES = ["BACKUP", "REROUTE_LEFT", "REROUTE_RIGHT", "WAIT_REOBSERVE", "REJOIN"]
SKILL_SWAP_MIRROR = {1: 2, 2: 1}
TEMPERATURE = 0.5   # softmax temperature (낮을수록 1등 후보에 확신 쏠림)
TAU_CONFIDENCE = 1.0  # teacher_weight = exp(-|actual-estimated|/tau)
N_ENSEMBLE = 5
N_FOLDS = 5
HIDDEN = 64
EPOCHS = 300
LR = 1e-3
WEIGHT_DECAY = 1e-3  # 소량 데이터라 과적합 방지 위해 다소 세게

# 재현성 -- fold split(seed=0), 각 fold 모델(seed=fi), 앙상블 멤버(seed=100+seed) 전부
# 이 상수 하나로부터 파생. 같은 GLOBAL_SEED면 매번 같은 결과 나옴(torch/numpy 둘 다 고정).
GLOBAL_SEED = 42


class HighLevelPolicy(nn.Module):
    """tgrpo_sac_hierarchical_v2.HighLevelPolicy와 동일 구조(체크포인트 호환용)."""

    def __init__(self, state_dim: int = STATE_DIM, n_skills: int = N_SKILLS, hidden: int = HIDDEN):
        super().__init__()
        self.net = nn.Sequential(nn.Linear(state_dim, hidden), nn.ReLU(),
                                  nn.Linear(hidden, hidden), nn.ReLU(),
                                  nn.Linear(hidden, n_skills))

    def forward(self, state: torch.Tensor) -> torch.Tensor:
        return self.net(state)


def reflect_point(px, py, pivot_x, pivot_y, axis_theta):
    dx, dy = px - pivot_x, py - pivot_y
    c, s = math.cos(-axis_theta), math.sin(-axis_theta)
    local_x = dx * c - dy * s
    local_y = -(dx * s + dy * c)
    c2, s2 = math.cos(axis_theta), math.sin(axis_theta)
    wx = local_x * c2 - local_y * s2
    wy = local_x * s2 + local_y * c2
    return pivot_x + wx, pivot_y + wy


def mirror_state_only(state: np.ndarray) -> np.ndarray:
    """distillation 전용 -- next_state는 아예 안 씀. state의 goal 반사 + obs_x flip만."""
    s = state.copy()
    rx, ry, ryaw = float(s[0]), float(s[1]), float(s[2])
    gx, gy = reflect_point(float(s[3]), float(s[4]), rx, ry, ryaw)
    s[3], s[4] = gx, gy
    s[5] = 1.0 - float(s[5])
    return s


def build_soft_target(candidates: list[dict]) -> tuple[np.ndarray | None, dict]:
    """rollout_passed 후보들 중 skill별 최고 estimated_reward -> temperature softmax.
    후보가 하나도 안 남으면 None 반환(이 샘플은 스킵)."""
    passed = [c for c in candidates if c.get("rollout_passed")]
    if not passed:
        return None, {}
    best_per_skill: dict[str, float] = {}
    for c in passed:
        name = c["skill_name"]
        r = c["estimated_reward"]
        if name not in best_per_skill or r > best_per_skill[name]:
            best_per_skill[name] = r

    scores = np.full(N_SKILLS, -np.inf, dtype=np.float64)
    for i, name in enumerate(SKILL_NAMES):
        if name in best_per_skill:
            scores[i] = best_per_skill[name]

    mask = np.isfinite(scores)
    if not mask.any():
        return None, {}
    finite = scores[mask]
    z = (finite - finite.max()) / TEMPERATURE
    probs = np.zeros(N_SKILLS, dtype=np.float64)
    probs[mask] = np.exp(z) / np.exp(z).sum()
    return probs.astype(np.float32), best_per_skill


def mirror_soft_target(target: np.ndarray) -> np.ndarray:
    t = target.copy()
    t[1], t[2] = target[2], target[1]  # REROUTE_LEFT<->REROUTE_RIGHT 확률 스왑
    return t


def load_samples() -> list[dict]:
    with open(BUFFER_PATH, "rb") as f:
        items = pickle.load(f)

    samples = []
    for it in items:
        meta = it.get("meta", {})
        if not meta.get("is_execution"):
            continue
        candidates = meta.get("candidate_reward_estimates")
        if not candidates:
            continue
        target, best_per_skill = build_soft_target(candidates)
        if target is None:
            continue

        state = np.asarray(it["state"], dtype=np.float32)
        actual_reward = float(it["reward"])
        executed_skill_name = SKILL_NAMES[it["skill"]] if 0 <= it["skill"] < N_SKILLS else None
        estimated_for_selected = best_per_skill.get(executed_skill_name)
        if estimated_for_selected is not None:
            conf_weight = math.exp(-abs(actual_reward - estimated_for_selected) / TAU_CONFIDENCE)
        else:
            conf_weight = 0.5  # 선택된 skill이 rollout_passed 후보에 없었던 드문 경우 -- 중간값

        # clearance 버그 수정 이전 데이터(진행도 신호만) 표시 -- 코덱스 지적대로 신뢰도
        # 계산에 그대로 못 믿는다는 걸 남겨둠(제거는 안 함, 그냥 태그).
        clearance_valid = meta.get("reward_components", {}).get("clearance_cost", None) not in (0.0, None) \
            or any(c.get("clearance_cost_est") not in (0.0, None) for c in candidates)

        run_id = meta.get("timestamp", 0) // 300  # 대략 5분 단위로 세션 묶어서 group split용

        samples.append({
            "state": state, "target": target, "weight": conf_weight,
            "clearance_valid": clearance_valid, "group": int(run_id),
        })

        # state-only 제한 미러링 -- next_state 안 씀, distillation 전용이라 안전
        samples.append({
            "state": mirror_state_only(state), "target": mirror_soft_target(target),
            "weight": conf_weight, "clearance_valid": clearance_valid,
            "group": int(run_id) + 1_000_000,  # 원본과 다른 fold에 갈 수도 있게 구분(원치 않으면 같게 둬도 됨)
        })

    return samples


def group_kfold_indices(groups: list[int], k: int, seed: int = 0):
    rng = np.random.default_rng(seed)
    uniq = list(sorted(set(groups)))
    rng.shuffle(uniq)
    folds = [uniq[i::k] for i in range(k)]
    for fi in range(k):
        val_groups = set(folds[fi])
        val_idx = [i for i, g in enumerate(groups) if g in val_groups]
        train_idx = [i for i, g in enumerate(groups) if g not in val_groups]
        if val_idx and train_idx:
            yield train_idx, val_idx


def train_one(states, targets, weights, train_idx, val_idx, seed: int):
    torch.manual_seed(seed)
    model = HighLevelPolicy()
    opt = torch.optim.Adam(model.parameters(), lr=LR, weight_decay=WEIGHT_DECAY)

    X = torch.tensor(states, dtype=torch.float32)
    T = torch.tensor(targets, dtype=torch.float32)
    W = torch.tensor(weights, dtype=torch.float32)

    Xtr, Ttr, Wtr = X[train_idx], T[train_idx], W[train_idx]
    Xva, Tva, Wva = X[val_idx], T[val_idx], W[val_idx]

    best_val = float("inf")
    best_state = None
    for epoch in range(EPOCHS):
        model.train()
        opt.zero_grad()
        logits = model(Xtr)
        logp = F.log_softmax(logits, dim=-1)
        loss_per_sample = -(Ttr * logp).sum(dim=-1)
        loss = (loss_per_sample * Wtr).sum() / Wtr.sum().clamp_min(1e-6)
        loss.backward()
        opt.step()

        if epoch % 10 == 0 or epoch == EPOCHS - 1:
            model.eval()
            with torch.no_grad():
                vlogits = model(Xva)
                vlogp = F.log_softmax(vlogits, dim=-1)
                vloss = (-(Tva * vlogp).sum(dim=-1) * Wva).sum() / Wva.sum().clamp_min(1e-6)
                if vloss.item() < best_val:
                    best_val = vloss.item()
                    best_state = {k: v.clone() for k, v in model.state_dict().items()}

    model.load_state_dict(best_state)
    return model, best_val


def evaluate(model, states, targets) -> dict:
    model.eval()
    with torch.no_grad():
        X = torch.tensor(states, dtype=torch.float32)
        logits = model(X)
        probs = F.softmax(logits, dim=-1).numpy()
    top1_pred = probs.argmax(axis=1)
    top1_teacher = targets.argmax(axis=1)
    top1_acc = float((top1_pred == top1_teacher).mean())

    top2_pred = np.argsort(-probs, axis=1)[:, :2]
    top2_recall = float(np.mean([t in row for t, row in zip(top1_teacher, top2_pred)]))

    entropy = float((-probs * np.log(probs + 1e-9)).sum(axis=1).mean())
    skill_dist = np.bincount(top1_pred, minlength=N_SKILLS) / len(top1_pred)
    return {
        "top1_acc_vs_teacher": top1_acc, "top2_recall_vs_teacher": top2_recall,
        "mean_entropy": entropy,
        "pred_skill_distribution": {SKILL_NAMES[i]: float(skill_dist[i]) for i in range(N_SKILLS)},
    }


def main() -> None:
    np.random.seed(GLOBAL_SEED)
    torch.manual_seed(GLOBAL_SEED)

    samples = load_samples()
    print(f"distillation 샘플 수(원본+미러 합산): {len(samples)}개")

    states = np.stack([s["state"] for s in samples])
    targets = np.stack([s["target"] for s in samples])
    weights = np.array([s["weight"] for s in samples], dtype=np.float32)
    groups = [s["group"] for s in samples]
    n_invalid = sum(1 for s in samples if not s["clearance_valid"])
    print(f"clearance 신뢰도 계산 불가(수정 전 데이터 유래) 샘플: {n_invalid}개 -- 학습엔 포함, "
          f"weight 해석만 주의")

    OUT_DIR.mkdir(exist_ok=True)

    fold_metrics = []
    for fi, (train_idx, val_idx) in enumerate(group_kfold_indices(groups, N_FOLDS, seed=GLOBAL_SEED)):
        model, val_loss = train_one(states, targets, weights, train_idx, val_idx, seed=GLOBAL_SEED + fi)
        metrics = evaluate(model, states[val_idx], targets[val_idx])
        metrics["fold"] = fi
        metrics["val_loss"] = val_loss
        metrics["n_train"] = len(train_idx)
        metrics["n_val"] = len(val_idx)
        fold_metrics.append(metrics)
        print(f"[fold {fi}] val_loss={val_loss:.4f} top1={metrics['top1_acc_vs_teacher']:.2f} "
              f"top2_recall={metrics['top2_recall_vs_teacher']:.2f} entropy={metrics['mean_entropy']:.2f}")

    print()
    print("=== 5-fold 평균 ===")
    for key in ["val_loss", "top1_acc_vs_teacher", "top2_recall_vs_teacher", "mean_entropy"]:
        vals = [m[key] for m in fold_metrics]
        print(f"  {key}: {np.mean(vals):.4f} (std {np.std(vals):.4f})")

    print()
    print(f"=== 앙상블 {N_ENSEMBLE}개 학습 (uncertainty fallback용, 전체 데이터로) ===")
    all_idx = list(range(len(samples)))
    ensemble = []
    for seed in range(N_ENSEMBLE):
        rng = np.random.default_rng(GLOBAL_SEED + seed)
        boot_idx = rng.choice(all_idx, size=len(all_idx), replace=True).tolist()
        val_idx = list(set(all_idx) - set(boot_idx)) or all_idx[:5]
        model, _ = train_one(states, targets, weights, boot_idx, val_idx, seed=GLOBAL_SEED + 100 + seed)
        ensemble.append(model.state_dict())

    torch.save({
        "ensemble_state_dicts": ensemble,
        "state_dim": STATE_DIM, "n_skills": N_SKILLS, "hidden": HIDDEN,
        "skill_names": SKILL_NAMES, "temperature": TEMPERATURE,
    }, OUT_DIR / "high_level_distilled_ensemble.pt")
    print(f"앙상블 저장: {OUT_DIR / 'high_level_distilled_ensemble.pt'}")
    print()
    print("다음 단계: 이 앙상블로 예측 분산(disagreement) 계산해서, 분산 크면 6C-Lite 기존 "
          "선택 방식으로 fallback하는 게이팅 로직을 orchestrate_live_teleop.py 쪽에 연결.")


if __name__ == "__main__":
    main()
