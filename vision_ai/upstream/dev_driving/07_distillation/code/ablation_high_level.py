"""HighLevelPolicy distillation ablation study -- 조건 4개를 똑같은 5-fold split/seed로
비교. distill_high_level.py의 아이디어를 조건별로 켜고 끄면서 재사용.

조건:
  A) hard_BC            : 실행된 skill 하나만 정답(one-hot)으로 BC. augmentation/pairwise 없음.
  B) soft_distill        : 6C-Lite 후보평가 기반 soft target(distill_high_level.py 기본형).
  C) soft_distill+mirror : B + state-only 좌우 미러링 augmentation.
  D) soft_distill+mirror+pairwise : C + 같은 트리거 내 후보 쌍 사이 pairwise ranking loss 추가
     (TGRPO의 "그룹 내 상대비교" 취지를 더 직접적으로 반영).

공통 평가지표(모든 조건에서 동일하게 비교 가능한 것 위주):
  - acc_vs_executed_skill : validation에서 예측 top1이 "실제로 실행된 skill"과 얼마나
    일치하는지(휴리스틱이 실제로 고른 것과 비교, hard label이라 조건 무관하게 항상 계산 가능)
  - top1_acc_vs_soft_teacher / mean_entropy : soft target 있는 조건(B/C/D)에서만 계산

버그 수정 사항(distill_high_level.py 대비): 미러링된 샘플이 원본과 다른 group으로 찍혀서
group k-fold split에서 원본은 train, 미러링본은 val(혹은 반대)로 갈라질 수 있었음 --
사실상 거의 동일한 샘플이 train/val에 나눠 들어가는 데이터 누수. 여기서는 미러링 샘플이
원본과 항상 "같은 group"을 갖도록 고쳐서 항상 같은 fold에 묶이게 함.

사용: python3 ablation_high_level.py (buffer 있는 ~/driving_pipeline/ 에서 실행)
"""

from __future__ import annotations

import math
import pickle
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

BUFFER_PATH = "./real_recovery_buffer.pkl"
STATE_DIM = 9
N_SKILLS = 5
SKILL_NAMES = ["BACKUP", "REROUTE_LEFT", "REROUTE_RIGHT", "WAIT_REOBSERVE", "REJOIN"]
SKILL_SWAP_MIRROR = {1: 2, 2: 1}
TEMPERATURE = 0.5
TAU_CONFIDENCE = 1.0
N_FOLDS = 5
HIDDEN = 64
EPOCHS = 300
LR = 1e-3
WEIGHT_DECAY = 1e-3
PAIRWISE_MARGIN = 0.0     # margin ranking loss margin
PAIRWISE_LOSS_WEIGHT = 0.3  # 주 distillation loss 대비 pairwise 항 가중치
GLOBAL_SEED = 42


class HighLevelPolicy(nn.Module):
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
    s = state.copy()
    rx, ry, ryaw = float(s[0]), float(s[1]), float(s[2])
    gx, gy = reflect_point(float(s[3]), float(s[4]), rx, ry, ryaw)
    s[3], s[4] = gx, gy
    s[5] = 1.0 - float(s[5])
    return s


def mirror_soft_target(target: np.ndarray) -> np.ndarray:
    t = target.copy()
    t[1], t[2] = target[2], target[1]
    return t


def mirror_pairs(pairs: list[tuple[int, float]]) -> list[tuple[int, float]]:
    return [(SKILL_SWAP_MIRROR.get(idx, idx), r) for idx, r in pairs]


def build_soft_target(candidates: list[dict]) -> tuple[np.ndarray | None, dict, list[tuple[int, float]]]:
    passed = [c for c in candidates if c.get("rollout_passed")]
    if not passed:
        return None, {}, []
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
        return None, {}, []
    finite = scores[mask]
    z = (finite - finite.max()) / TEMPERATURE
    probs = np.zeros(N_SKILLS, dtype=np.float64)
    probs[mask] = np.exp(z) / np.exp(z).sum()

    # pairwise용 -- 후보 개별(스킬당 여러 개 있으면 그 각각) (skill_idx, estimated_reward)
    name_to_idx = {n: i for i, n in enumerate(SKILL_NAMES)}
    raw_pairs = [(name_to_idx[c["skill_name"]], float(c["estimated_reward"])) for c in passed]
    return probs.astype(np.float32), best_per_skill, raw_pairs


def load_raw_samples() -> list[dict]:
    """미러링 전, augmentation 전의 원본 샘플만. 조건별로 여기서 파생시킴."""
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
        target, best_per_skill, pairs = build_soft_target(candidates)
        if target is None:
            continue

        state = np.asarray(it["state"], dtype=np.float32)
        actual_reward = float(it["reward"])
        skill_idx = it["skill"]
        if not (0 <= skill_idx < N_SKILLS):
            continue
        executed_name = SKILL_NAMES[skill_idx]
        estimated_for_selected = best_per_skill.get(executed_name)
        conf_weight = (math.exp(-abs(actual_reward - estimated_for_selected) / TAU_CONFIDENCE)
                       if estimated_for_selected is not None else 0.5)

        run_group = int(meta.get("timestamp", 0) // 300)

        samples.append({
            "state": state, "soft_target": target, "skill_idx": skill_idx,
            "weight": conf_weight, "pairs": pairs, "group": run_group,
        })
    return samples


def make_variant(samples: list[dict], use_mirror: bool) -> list[dict]:
    out = []
    for s in samples:
        out.append(dict(s, mirrored=False))
        if use_mirror:
            out.append({
                "state": mirror_state_only(s["state"]),
                "soft_target": mirror_soft_target(s["soft_target"]),
                "skill_idx": SKILL_SWAP_MIRROR.get(s["skill_idx"], s["skill_idx"]),
                "weight": s["weight"], "pairs": mirror_pairs(s["pairs"]),
                "group": s["group"],  # 원본과 같은 group -> 항상 같은 fold (누수 방지)
                "mirrored": True,
            })
    return out


def group_kfold_indices(groups: list[int], k: int, seed: int):
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


def pairwise_ranking_loss(logits_row: torch.Tensor, pairs: list[tuple[int, float]]) -> torch.Tensor:
    """같은 트리거의 후보들끼리: estimated_reward가 더 높은 skill의 로짓이 더 높아야 함
    (margin ranking loss). pairs가 2개 미만이면 0."""
    if len(pairs) < 2:
        return torch.tensor(0.0)
    losses = []
    for i in range(len(pairs)):
        for j in range(i + 1, len(pairs)):
            idx_a, r_a = pairs[i]
            idx_b, r_b = pairs[j]
            if idx_a == idx_b or r_a == r_b:
                continue
            hi, lo = (idx_a, idx_b) if r_a > r_b else (idx_b, idx_a)
            diff = logits_row[lo] - logits_row[hi] + PAIRWISE_MARGIN
            losses.append(F.relu(diff))
    if not losses:
        return torch.tensor(0.0)
    return torch.stack(losses).mean()


def train_eval_fold(variant_samples, train_idx, val_idx, seed, use_soft, use_pairwise):
    torch.manual_seed(seed)
    model = HighLevelPolicy()
    opt = torch.optim.Adam(model.parameters(), lr=LR, weight_decay=WEIGHT_DECAY)

    states = np.stack([s["state"] for s in variant_samples])
    X = torch.tensor(states, dtype=torch.float32)
    W = torch.tensor([s["weight"] for s in variant_samples], dtype=torch.float32)
    skill_idx_t = torch.tensor([s["skill_idx"] for s in variant_samples], dtype=torch.long)

    if use_soft:
        T = torch.tensor(np.stack([s["soft_target"] for s in variant_samples]), dtype=torch.float32)
    else:
        T = F.one_hot(skill_idx_t, N_SKILLS).float()

    Xtr, Ttr, Wtr = X[train_idx], T[train_idx], W[train_idx]
    train_pairs = [variant_samples[i]["pairs"] for i in train_idx]
    Xva, Tva = X[val_idx], T[val_idx]
    val_skill_idx = skill_idx_t[val_idx]

    best_val, best_state = float("inf"), None
    for epoch in range(EPOCHS):
        model.train()
        opt.zero_grad()
        logits = model(Xtr)
        logp = F.log_softmax(logits, dim=-1)
        loss_per_sample = -(Ttr * logp).sum(dim=-1)
        loss = (loss_per_sample * Wtr).sum() / Wtr.sum().clamp_min(1e-6)

        if use_pairwise:
            pw_terms = [pairwise_ranking_loss(logits[i], train_pairs[i]) for i in range(len(train_idx))]
            pw_loss = torch.stack(pw_terms).mean()
            loss = loss + PAIRWISE_LOSS_WEIGHT * pw_loss

        loss.backward()
        opt.step()

        if epoch % 10 == 0 or epoch == EPOCHS - 1:
            model.eval()
            with torch.no_grad():
                vlogits = model(Xva)
                vlogp = F.log_softmax(vlogits, dim=-1)
                vloss = (-(Tva * vlogp).sum(dim=-1)).mean()
                if vloss.item() < best_val:
                    best_val = vloss.item()
                    best_state = {k: v.clone() for k, v in model.state_dict().items()}

    model.load_state_dict(best_state)
    model.eval()
    with torch.no_grad():
        vlogits = model(Xva)
        vprobs = F.softmax(vlogits, dim=-1).numpy()
    top1_pred = vprobs.argmax(axis=1)

    acc_vs_executed = float((top1_pred == val_skill_idx.numpy()).mean())
    entropy = float((-vprobs * np.log(vprobs + 1e-9)).sum(axis=1).mean())

    result = {"acc_vs_executed_skill": acc_vs_executed, "mean_entropy": entropy, "val_loss": best_val}
    if use_soft:
        teacher_top1 = Tva.numpy().argmax(axis=1)
        result["top1_acc_vs_soft_teacher"] = float((top1_pred == teacher_top1).mean())
    return result


def run_condition(name, raw_samples, use_mirror, use_soft, use_pairwise):
    variant = make_variant(raw_samples, use_mirror=use_mirror)
    groups = [s["group"] for s in variant]

    fold_results = []
    for fi, (train_idx, val_idx) in enumerate(group_kfold_indices(groups, N_FOLDS, seed=GLOBAL_SEED)):
        r = train_eval_fold(variant, train_idx, val_idx, seed=GLOBAL_SEED + fi,
                             use_soft=use_soft, use_pairwise=use_pairwise)
        fold_results.append(r)

    agg = {}
    keys = fold_results[0].keys()
    for k in keys:
        vals = [r[k] for r in fold_results]
        agg[k] = (float(np.mean(vals)), float(np.std(vals)))

    print(f"\n=== [{name}] (샘플 {len(variant)}개, fold {len(fold_results)}개) ===")
    for k, (m, sd) in agg.items():
        print(f"  {k}: {m:.4f} (std {sd:.4f})")
    return {"name": name, "n_samples": len(variant), **{k: v[0] for k, v in agg.items()}}


def main():
    np.random.seed(GLOBAL_SEED)
    torch.manual_seed(GLOBAL_SEED)

    raw = load_raw_samples()
    print(f"원본(미러 전) 샘플 수: {len(raw)}개")

    conditions = [
        ("A_hard_BC", dict(use_mirror=False, use_soft=False, use_pairwise=False)),
        ("B_soft_distill", dict(use_mirror=False, use_soft=True, use_pairwise=False)),
        ("C_soft+mirror", dict(use_mirror=True, use_soft=True, use_pairwise=False)),
        ("D_soft+mirror+pairwise", dict(use_mirror=True, use_soft=True, use_pairwise=True)),
    ]

    summary = []
    for name, kwargs in conditions:
        summary.append(run_condition(name, raw, **kwargs))

    print("\n\n=== 최종 비교 표 ===")
    header = ["name", "n_samples", "acc_vs_executed_skill", "top1_acc_vs_soft_teacher", "mean_entropy", "val_loss"]
    print(" | ".join(header))
    for row in summary:
        vals = [str(row.get(h, "-")) for h in header]
        print(" | ".join(vals))


if __name__ == "__main__":
    main()
