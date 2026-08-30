"""Explicit offline trainer; physical robot Compose never invokes this module."""

from __future__ import annotations

import argparse
from pathlib import Path
import random

import numpy as np
import torch

from .algorithms import DEVICE, SACAgent, tgrpo_update_from_buffer
from vision_ai.data_loader.recovery.dataset import load_training_jsonl
from vision_ai.data_loader.recovery.replay_sampler import BucketedReplaySampler, TransitionRecord
from vision_ai.models.recovery.policy_architecture import HighLevelPolicy, LowLevelPolicy, TwinQ


BATCH_SIZE = 32
MIN_TRANSITIONS_TO_TRAIN = 4
DEFAULT_EPOCHS = 20


def _as_dict(item):
    return {"state": item.state, "skill": item.skill, "coord": item.coord,
            "reward": item.reward, "next_state": item.next_state,
            "done": item.done, "meta": item.meta}


def train(dataset: Path, checkpoint: Path, epochs: int = DEFAULT_EPOCHS) -> None:
    transitions = load_training_jsonl(dataset)
    if len(transitions) < MIN_TRANSITIONS_TO_TRAIN:
        raise ValueError(f"at least {MIN_TRANSITIONS_TO_TRAIN} executed transitions are required")
    records = [TransitionRecord(
        state=item.state, skill=item.skill, coord=item.coord, reward=item.reward,
        next_state=item.next_state, done=item.done,
        timestamp=float(item.meta.get("timestamp", 0.0)),
        map_zone=str(item.meta.get("map_zone", item.meta.get("goal_waypoint", "unknown"))),
        terminal_critical=bool(item.meta.get("terminal_critical", False)),
        policy_name=item.meta.get("recovery_policy_name"),
        policy_version=item.meta.get("recovery_policy_version"),
    ) for item in transitions]
    sampler = BucketedReplaySampler()
    for record in records:
        sampler.add(record)
    high = HighLevelPolicy().to(DEVICE)
    low = LowLevelPolicy().to(DEVICE)
    q = TwinQ().to(DEVICE)
    q_target = TwinQ().to(DEVICE)
    q_target.load_state_dict(q.state_dict())
    reference = HighLevelPolicy().to(DEVICE)
    reference.load_state_dict(high.state_dict())
    reference.eval()
    for parameter in reference.parameters():
        parameter.requires_grad_(False)
    high_optimizer = torch.optim.Adam(high.parameters(), lr=3e-4)
    agent = SACAgent(
        policy=low, q=q, q_target=q_target,
        policy_opt=torch.optim.Adam(low.parameters(), lr=3e-4),
        q_opt=torch.optim.Adam(q.parameters(), lr=3e-4),
        log_alpha=torch.zeros(1, requires_grad=True, device=DEVICE), alpha_opt=None,
        target_entropy=-3.0,
    )
    agent.alpha_opt = torch.optim.Adam([agent.log_alpha], lr=3e-4)
    plain = [_as_dict(item) for item in transitions]
    batch_size = min(BATCH_SIZE, len(records))
    for _ in range(epochs):
        batch = sampler.sample(batch_size)
        tensors = (
            torch.tensor(np.array([r.state for r in batch]), dtype=torch.float32, device=DEVICE),
            torch.tensor([r.skill for r in batch], dtype=torch.float32, device=DEVICE),
            torch.tensor(np.array([r.coord for r in batch]), dtype=torch.float32, device=DEVICE),
            torch.tensor([r.reward for r in batch], dtype=torch.float32, device=DEVICE).unsqueeze(-1),
            torch.tensor(np.array([r.next_state for r in batch]), dtype=torch.float32, device=DEVICE),
            torch.tensor([float(r.done) for r in batch], dtype=torch.float32, device=DEVICE).unsqueeze(-1),
        )
        agent.update(tensors)
        state = plain[random.randrange(len(plain))]["state"]
        tgrpo_update_from_buffer(high, high_optimizer, plain, np.asarray(state), reference)
    torch.save({"high_policy": high.state_dict(), "low_policy": low.state_dict(),
                "q": q.state_dict(), "q_target": q_target.state_dict()}, checkpoint)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=DEFAULT_EPOCHS)
    args = parser.parse_args()
    train(args.dataset, args.checkpoint, args.epochs)


if __name__ == "__main__":
    main()
