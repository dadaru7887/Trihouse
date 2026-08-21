"""Checkpoint-compatible networks copied from dev_driving without math changes."""

from __future__ import annotations

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

from .contracts import COORD_DIM, N_SKILLS, STATE_DIM


LOG_STD_MIN, LOG_STD_MAX = -5.0, 2.0
COORD_SCALE = 2.0


class HighLevelPolicy(nn.Module):
    def __init__(self, state_dim: int = STATE_DIM, n_skills: int = N_SKILLS, hidden: int = 64):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(state_dim, hidden), nn.ReLU(),
            nn.Linear(hidden, hidden), nn.ReLU(),
            nn.Linear(hidden, n_skills),
        )

    def forward(self, state: torch.Tensor) -> torch.Tensor:
        return self.net(state)

    def sample(self, state: torch.Tensor, k: int) -> tuple[torch.Tensor, torch.Tensor]:
        logits = self.forward(state.unsqueeze(0)).squeeze(0)
        distribution = torch.distributions.Categorical(logits=logits)
        skills = distribution.sample((k,))
        return skills, distribution.log_prob(skills)


class LowLevelPolicy(nn.Module):
    def __init__(self, state_dim: int = STATE_DIM, n_skills: int = N_SKILLS,
                 coord_dim: int = COORD_DIM, hidden: int = 128):
        super().__init__()
        self.n_skills = n_skills
        self.net = nn.Sequential(
            nn.Linear(state_dim + n_skills, hidden), nn.ReLU(),
            nn.Linear(hidden, hidden), nn.ReLU(),
        )
        self.mean_head = nn.Linear(hidden, coord_dim)
        self.log_std_head = nn.Linear(hidden, coord_dim)

    def _skill_onehot(self, skill: torch.Tensor) -> torch.Tensor:
        return F.one_hot(skill.long(), num_classes=self.n_skills).float()

    def forward(self, state: torch.Tensor, skill: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        hidden = self.net(torch.cat([state, self._skill_onehot(skill)], dim=-1))
        return self.mean_head(hidden), self.log_std_head(hidden).clamp(LOG_STD_MIN, LOG_STD_MAX)

    def sample(self, state: torch.Tensor, skill: torch.Tensor, deterministic: bool = False):
        mean, log_std = self.forward(state, skill)
        std = log_std.exp()
        pre_tanh = mean if deterministic else mean + std * torch.randn_like(mean)
        coord = torch.tanh(pre_tanh) * COORD_SCALE
        normal_log_prob = (
            -0.5 * ((pre_tanh - mean) / (std + 1e-6)) ** 2
            - log_std - 0.5 * np.log(2 * np.pi)
        ).sum(-1, keepdim=True)
        log_prob = normal_log_prob - torch.log(
            COORD_SCALE * (1 - torch.tanh(pre_tanh) ** 2) + 1e-6
        ).sum(-1, keepdim=True)
        return coord, log_prob


class TwinQ(nn.Module):
    def __init__(self, state_dim: int = STATE_DIM, n_skills: int = N_SKILLS,
                 coord_dim: int = COORD_DIM, hidden: int = 128):
        super().__init__()
        self.n_skills = n_skills
        input_dim = state_dim + n_skills + coord_dim

        def make_q() -> nn.Sequential:
            return nn.Sequential(
                nn.Linear(input_dim, hidden), nn.ReLU(),
                nn.Linear(hidden, hidden), nn.ReLU(), nn.Linear(hidden, 1),
            )

        self.q1 = make_q()
        self.q2 = make_q()

    def forward(self, state: torch.Tensor, skill: torch.Tensor, coord: torch.Tensor):
        onehot = F.one_hot(skill.long(), num_classes=self.n_skills).float()
        state_skill_action = torch.cat([state, onehot, coord], dim=-1)
        return self.q1(state_skill_action), self.q2(state_skill_action)
