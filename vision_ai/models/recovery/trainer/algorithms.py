"""Unchanged SAC/CQL and group-relative high-policy update mathematics."""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
import torch
import torch.nn.functional as F

from vision_ai.utils.contracts import N_SKILLS
from vision_ai.models.recovery.policy_architecture import COORD_SCALE, HighLevelPolicy


DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
REWARD_CLIP = None
REWARD_SOFT_CLIP_SCALE: float | None = None
ADVANTAGE_STD_NORM = True
USE_CLIP_SURROGATE = True
CLIP_EPSILON = 0.2
USE_KL_PENALTY = True
KL_COEF = 0.01
USE_DAPO_STYLE = False
DAPO_CLIP_LOW = 0.2
DAPO_CLIP_HIGH = 0.28
DAPO_MIN_REWARD_STD = 1e-4
ENTROPY_COEF = 0.01


def scale_reward(reward: float) -> float:
    if REWARD_CLIP is not None:
        return max(-REWARD_CLIP, min(REWARD_CLIP, reward))
    if REWARD_SOFT_CLIP_SCALE is not None:
        return REWARD_SOFT_CLIP_SCALE * math.tanh(reward / REWARD_SOFT_CLIP_SCALE)
    return reward


@dataclass
class SACAgent:
    policy: object
    q: object
    q_target: object
    policy_opt: torch.optim.Optimizer
    q_opt: torch.optim.Optimizer
    log_alpha: torch.Tensor
    alpha_opt: torch.optim.Optimizer
    target_entropy: float
    gamma: float = 0.99
    tau: float = 0.005
    use_cql: bool = False
    cql_alpha: float = 1.0
    cql_n_samples: int = 10

    @property
    def alpha(self):
        return self.log_alpha.exp()

    def update(self, batch) -> dict:
        state, skill, coord, reward, next_state, done = batch
        with torch.no_grad():
            next_coord, next_log_prob = self.policy.sample(next_state, skill)
            q1_target, q2_target = self.q_target(next_state, skill, next_coord)
            q_target_min = torch.min(q1_target, q2_target) - self.alpha * next_log_prob
            target = reward + (1 - done) * self.gamma * q_target_min
        q1, q2 = self.q(state, skill, coord)
        critic_loss = F.mse_loss(q1, target) + F.mse_loss(q2, target)
        cql_log = {}
        if self.use_cql:
            count, coord_dim = state.shape[0], coord.shape[-1]
            state_repeated = state.repeat_interleave(self.cql_n_samples, dim=0)
            skill_repeated = skill.repeat_interleave(self.cql_n_samples, dim=0)
            random_actions = (
                torch.rand(count * self.cql_n_samples, coord_dim, device=state.device) * 2 - 1
            ) * COORD_SCALE
            with torch.no_grad():
                policy_actions, _ = self.policy.sample(state_repeated, skill_repeated)
            q1_random, q2_random = self.q(state_repeated, skill_repeated, random_actions)
            q1_policy, q2_policy = self.q(state_repeated, skill_repeated, policy_actions)
            cat1 = torch.cat([q1_random.view(count, self.cql_n_samples), q1_policy.view(count, self.cql_n_samples)], 1)
            cat2 = torch.cat([q2_random.view(count, self.cql_n_samples), q2_policy.view(count, self.cql_n_samples)], 1)
            cql_loss = self.cql_alpha * (
                (torch.logsumexp(cat1, dim=1, keepdim=True) - q1).mean()
                + (torch.logsumexp(cat2, dim=1, keepdim=True) - q2).mean()
            )
            critic_loss = critic_loss + cql_loss
            cql_log = {"cql_loss": cql_loss.item()}
        self.q_opt.zero_grad(); critic_loss.backward(); self.q_opt.step()
        new_coord, new_log_prob = self.policy.sample(state, skill)
        q1_new, q2_new = self.q(state, skill, new_coord)
        actor_loss = (self.alpha * new_log_prob - torch.min(q1_new, q2_new)).mean()
        self.policy_opt.zero_grad(); actor_loss.backward(); self.policy_opt.step()
        alpha_loss = -(self.log_alpha * (new_log_prob.detach() + self.target_entropy)).mean()
        self.alpha_opt.zero_grad(); alpha_loss.backward(); self.alpha_opt.step()
        with torch.no_grad():
            for parameter, target_parameter in zip(self.q.parameters(), self.q_target.parameters()):
                target_parameter.data.mul_(1 - self.tau).add_(self.tau * parameter.data)
        return {"critic_loss": critic_loss.item(), "actor_loss": actor_loss.item(),
                "alpha": self.alpha.item(), **cql_log}


def tgrpo_update_from_buffer(high_policy: HighLevelPolicy, high_opt, transitions: list[dict],
                             state: np.ndarray, ref_policy: HighLevelPolicy | None = None) -> dict:
    state_tensor = torch.tensor(state, dtype=torch.float32, device=DEVICE)
    by_skill = {skill: [] for skill in range(N_SKILLS)}
    for transition in transitions:
        by_skill[transition["skill"]].append(scale_reward(transition["reward"]))
    skills = [skill for skill, rewards in by_skill.items() if rewards]
    if len(skills) < 2:
        return {}
    logits = high_policy(state_tensor.unsqueeze(0)).squeeze(0)
    distribution = torch.distributions.Categorical(logits=logits)
    skill_ids = torch.tensor(skills, device=DEVICE)
    log_probs = distribution.log_prob(skill_ids)
    rewards = torch.tensor([np.mean(by_skill[skill]) for skill in skills], dtype=torch.float32, device=DEVICE)
    if USE_DAPO_STYLE and rewards.std().item() < DAPO_MIN_REWARD_STD:
        return {"skipped_dynamic_sampling": True, "n_skills_with_data": len(skills)}
    advantage = ((rewards - rewards.mean()) / (rewards.std() + 1e-6)
                 if ADVANTAGE_STD_NORM else rewards - rewards.mean())
    log = {}
    if (USE_CLIP_SURROGATE or USE_KL_PENALTY) and ref_policy is not None:
        with torch.no_grad():
            ref_logits = ref_policy(state_tensor.unsqueeze(0)).squeeze(0)
        ref_distribution = torch.distributions.Categorical(logits=ref_logits)
        ref_log_probs = ref_distribution.log_prob(skill_ids)
    if USE_CLIP_SURROGATE and ref_policy is not None:
        ratio = torch.exp(log_probs - ref_log_probs.detach())
        low, high = ((DAPO_CLIP_LOW, DAPO_CLIP_HIGH) if USE_DAPO_STYLE
                     else (CLIP_EPSILON, CLIP_EPSILON))
        policy_loss = -torch.min(
            ratio * advantage.detach(),
            torch.clamp(ratio, 1 - low, 1 + high) * advantage.detach(),
        ).mean()
        log["clip_ratio_mean"] = ratio.mean().item()
    else:
        policy_loss = -(advantage.detach() * log_probs).mean()
    entropy = distribution.entropy()
    loss = policy_loss - ENTROPY_COEF * entropy
    if USE_KL_PENALTY and ref_policy is not None:
        kl = torch.distributions.kl_divergence(
            torch.distributions.Categorical(logits=logits), ref_distribution
        )
        loss = loss + KL_COEF * kl
        log["kl"] = kl.item()
    high_opt.zero_grad(); loss.backward(); high_opt.step()
    log.update({"tgrpo_loss": loss.item(), "entropy": entropy.item(),
                "n_skills_with_data": len(skills)})
    return log
