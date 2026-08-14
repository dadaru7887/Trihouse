"""world_model_ensemble.py의 앙상블을 실제 buffer로 지도학습(supervised)시키는 스크립트.
offline_train_from_buffer.py와 같은 buffer(real_recovery_buffer.pkl)를 쓰지만, 목적이 다름:
- offline_train_from_buffer.py: 정책(무엇을 할지)을 학습
- 이 스크립트: dynamics(무엇을 하면 어떻게 되는지)를 학습 -- 정책 학습과 독립적

**2026-08-15 작성, 아직 실제 buffer로 돌려본 적 없음.** 데이터 4개 미만이면 안 돌아가게
막아뒀지만, 의미 있으려면 최소 30~50개는 있어야 할 것으로 예상(정책 학습보다 dynamics
학습이 보통 더 많은 데이터를 요구함 -- state 전이 패턴 자체를 배워야 하니까).

실행: python3 train_world_model.py --epochs 100 [--n-members 5]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "02_pipeline_core"))

import numpy as np
import torch

from recovery_data_collector import PersistentRecoveryBuffer
from tgrpo_sac_hierarchical_v2 import STATE_DIM, N_SKILLS, COORD_DIM, DEVICE
from world_model_ensemble import WorldModelEnsemble

BUFFER_PATH = "../03_results/real_recovery_buffer.pkl"
CHECKPOINT_PATH = "./world_model_ensemble.pt"
MIN_TRANSITIONS = 4  # offline_train_from_buffer.py와 동일 원칙 -- 이 밑으론 스모크테스트도 무의미


def to_batch(transitions: list[dict]) -> dict[str, torch.Tensor]:
    states = torch.tensor(np.array([t["state"] for t in transitions]),
                           dtype=torch.float32, device=DEVICE)
    skills = torch.tensor([t["skill"] for t in transitions], dtype=torch.long, device=DEVICE)
    skill_onehot = torch.nn.functional.one_hot(skills, N_SKILLS).float()
    coords = torch.tensor(np.array([t["coord"] for t in transitions]),
                           dtype=torch.float32, device=DEVICE)
    next_states = torch.tensor(np.array([t["next_state"] for t in transitions]),
                                dtype=torch.float32, device=DEVICE)
    rewards = torch.tensor([t["reward"] for t in transitions],
                            dtype=torch.float32, device=DEVICE).unsqueeze(-1)
    return {"state": states, "skill_onehot": skill_onehot, "coord": coords,
            "next_state": next_states, "reward": rewards}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--n-members", type=int, default=5)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--val-split", type=float, default=0.2,
                         help="검증용으로 뗄 비율 -- overfitting 감시용(데이터 적을수록 중요)")
    args = parser.parse_args()

    buffer = PersistentRecoveryBuffer(save_path=BUFFER_PATH)
    n_total = len(buffer)
    transitions = [t for t in buffer.transitions if t.get("meta", {}).get("is_execution")]
    print(f"buffer 로드: 전체 {n_total}개 중 실제 실행 {len(transitions)}개만 사용")
    if len(transitions) < MIN_TRANSITIONS:
        print(f"실행된 transition이 너무 적음(<{MIN_TRANSITIONS}) -- world-model 학습은 "
              f"정책 학습보다도 데이터가 더 많이 필요함. 최소 30~50개 이상 모이면 재시도 권장.")
        return

    rng = np.random.default_rng(0)
    idx = rng.permutation(len(transitions))
    n_val = max(1, int(len(transitions) * args.val_split)) if len(transitions) >= 5 else 0
    val_idx, train_idx = idx[:n_val], idx[n_val:]
    train_set = [transitions[i] for i in train_idx]
    val_set = [transitions[i] for i in val_idx]
    print(f"train {len(train_set)}개 / val {len(val_set)}개")

    ensemble = WorldModelEnsemble(n_members=args.n_members)
    optimizers = [torch.optim.Adam(m.parameters(), lr=args.lr) for m in ensemble.members]

    train_batch = to_batch(train_set)
    val_batch = to_batch(val_set) if val_set else None

    for epoch in range(args.epochs):
        # 각 멤버를 서로 다른 bootstrap 리샘플(복원추출)로 학습 -- 앙상블 다양성 확보의
        # 표준 방법(bagging), 이래야 멤버들이 서로 다른 걸 보고 배워서 disagreement가
        # "진짜 불확실성"을 반영하게 됨(전부 같은 데이터로 학습하면 앙상블 의미 없음).
        for m, opt in zip(ensemble.members, optimizers):
            m.train()
            n = train_batch["state"].shape[0]
            boot_idx = torch.randint(0, n, (n,), device=DEVICE)
            s = train_batch["state"][boot_idx]
            z = train_batch["skill_onehot"][boot_idx]
            c = train_batch["coord"][boot_idx]
            ns_true = train_batch["next_state"][boot_idx]
            r_true = train_batch["reward"][boot_idx]

            delta_pred, r_pred = m(s, z, c)
            ns_pred = s + delta_pred
            loss = torch.nn.functional.mse_loss(ns_pred, ns_true) + \
                torch.nn.functional.mse_loss(r_pred, r_true)
            opt.zero_grad(); loss.backward(); opt.step()

        if (epoch + 1) % 10 == 0:
            msg = f"[epoch {epoch+1:3d}]"
            if val_batch is not None:
                with torch.no_grad():
                    val_losses = []
                    for m in ensemble.members:
                        m.eval()
                        delta_pred, r_pred = m(val_batch["state"], val_batch["skill_onehot"],
                                                val_batch["coord"])
                        ns_pred = val_batch["state"] + delta_pred
                        vl = torch.nn.functional.mse_loss(ns_pred, val_batch["next_state"]) + \
                            torch.nn.functional.mse_loss(r_pred, val_batch["reward"])
                        val_losses.append(vl.item())
                    msg += f" val_loss(멤버 평균)={np.mean(val_losses):.4f}"
            print(msg)

    ensemble.save(CHECKPOINT_PATH)
    print(f"world-model 앙상블 저장: {CHECKPOINT_PATH}")
    print("사용법: WorldModelEnsemble(n_members=...).load(path) 후 .predict()/.risk_ucb() 호출")


if __name__ == "__main__":
    main()
