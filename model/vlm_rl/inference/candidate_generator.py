"""Generate bounded recovery candidates using the unchanged hierarchical policy."""

from __future__ import annotations

from dataclasses import dataclass
import math

import torch

from model.vlm_rl.shared.contracts import SKILL_NAMES


ENVELOPE_RADIUS_M = 0.25
YAW_CLAMP_RAD = math.pi / 3


def _clamp_offset(dx: float, dy: float, radius_m: float = ENVELOPE_RADIUS_M) -> tuple[float, float]:
    distance = math.hypot(dx, dy)
    if distance <= radius_m or distance == 0:
        return dx, dy
    scale = radius_m / distance
    return dx * scale, dy * scale


def _clamp_yaw(dyaw: float, limit_rad: float = YAW_CLAMP_RAD) -> float:
    return max(-limit_rad, min(limit_rad, dyaw))


@dataclass(frozen=True)
class RLCandidate:
    skill: int
    skill_name: str
    offset: tuple[float, float, float]
    map_x: float
    map_y: float
    map_yaw: float
    skill_log_prob: float


def sample_candidate_group(high_policy, low_policy, state, robot_pose: tuple[float, float, float],
                           k: int, m: int, device: str = "cuda") -> list[RLCandidate]:
    rx, ry, ryaw = robot_pose
    state_tensor = state if torch.is_tensor(state) else torch.tensor(state, dtype=torch.float32)
    state_tensor = state_tensor.to(device)
    candidates: list[RLCandidate] = []
    with torch.no_grad():
        skills, skill_log_probs = high_policy.sample(state_tensor, k=k)
        for index in range(k):
            skill_id = int(skills[index].item())
            skill_batch = skills[index:index + 1].repeat(m)
            state_batch = state_tensor.unsqueeze(0).repeat(m, 1)
            coords, _ = low_policy.sample(state_batch, skill_batch)
            for coord in coords:
                dx, dy, dyaw = coord.cpu().numpy().tolist()
                dx, dy = _clamp_offset(dx, dy)
                dyaw = _clamp_yaw(dyaw)
                candidates.append(RLCandidate(
                    skill=skill_id,
                    skill_name=SKILL_NAMES[skill_id],
                    offset=(dx, dy, dyaw),
                    map_x=rx + dx * math.cos(ryaw) - dy * math.sin(ryaw),
                    map_y=ry + dx * math.sin(ryaw) + dy * math.cos(ryaw),
                    map_yaw=ryaw + dyaw,
                    skill_log_prob=float(skill_log_probs[index].item()),
                ))
    return candidates
