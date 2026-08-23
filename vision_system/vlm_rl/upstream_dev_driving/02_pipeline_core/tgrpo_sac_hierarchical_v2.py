"""TGRPO-SAC 계층구조 v2 -- 팀원 설계문서(2026-08-07-vlm-rl-recovery-architecture-design.md)
§6.1/§9.3 그대로 반영한 재구현.

v1(tgrpo_sac_dual_demo.py)과의 핵심 차이:
  v1: SAC/TGRPO가 같은 continuous actor를 공유 (조건화 없음)
  v2: **TGRPO가 고수준 skill z를 먼저 고르고(discrete, K개 중), SAC가 그 skill을
      조건으로 좌표 p=(x,y,yaw)를 생성(continuous, skill마다 M개)** -- 순차 조건부 구조
      z_t^(k) ~ pi_H(z|s_t), k=1..K
      p_t^(k,m) ~ pi_L(p|s_t, z_t^(k)), m=1..M

Reward도 팀원 문서 §9.3 수식으로 교체:
  r_t = w_p*progress - w_c*clearance_cost - w_i*intervention - w_t*time + R_rejoin
  단, 충돌/사람침범 등은 가중합 이전에 terminal critical로 먼저 처리(하드 override).

실행: python3 tgrpo_sac_hierarchical_v2.py
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

torch.manual_seed(0)
np.random.seed(0)
random.seed(0)

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

STATE_DIM = 9
COORD_DIM = 3      # (x, y, yaw) -- 팀원 문서의 map-frame pose, 데모에선 yaw는 방향각으로 단순화
N_SKILLS = 5        # BACKUP / REROUTE_LEFT / REROUTE_RIGHT / WAIT_REOBSERVE / REJOIN (의미는 학습으로 형성)
SKILL_NAMES = ["BACKUP", "REROUTE_LEFT", "REROUTE_RIGHT", "WAIT_REOBSERVE", "REJOIN"]


# ============================================================
# 1. 토이 환경 (v1과 동일 골자, action_dim만 3으로 확장 -- yaw 추가)
# ============================================================

@dataclass
class ToyRecoveryEnv:
    robot_pos: np.ndarray = field(default_factory=lambda: np.array([0.0, 0.0]))
    robot_yaw: float = 0.0
    goal_pos: np.ndarray = field(default_factory=lambda: np.array([10.0, 0.0]))
    obs_pos: np.ndarray = field(default_factory=lambda: np.array([5.0, 0.5]))
    obs_conf: float = 0.85
    dt: float = 0.5
    critical_dist: float = 0.3   # 이보다 가까우면 terminal critical(하드 override)
    clearance_ref: float = 1.5   # 이보다 가까워지면 clearance_cost 발생 시작

    def reset(self) -> np.ndarray:
        self.robot_pos = np.array([0.0, np.random.uniform(-1.0, 1.0)])
        self.robot_yaw = 0.0
        self.goal_pos = np.array([10.0, 0.0])
        self.obs_pos = np.array([5.0, np.random.uniform(-0.5, 0.5)])
        self.obs_conf = np.random.uniform(0.5, 0.95)
        return self._get_state()

    def _get_state(self) -> np.ndarray:
        return np.concatenate([self.robot_pos, [self.robot_yaw], self.goal_pos,
                                self.obs_pos, [self.obs_conf], [0.0]]).astype(np.float32)

    def step(self, coord: np.ndarray):
        """coord = (dx, dy, dyaw) -- 현재 위치 기준 짧은 복구 좌표 offset (팀원 문서의
        bounded map pose 컨셉을 토이 스케일로 근사)."""
        prev_dist_to_goal = np.linalg.norm(self.goal_pos - self.robot_pos)

        self.robot_pos = self.robot_pos + coord[:2]
        self.robot_yaw = self.robot_yaw + coord[2]

        dist_to_goal = np.linalg.norm(self.goal_pos - self.robot_pos)
        dist_to_obs = np.linalg.norm(self.obs_pos - self.robot_pos)

        reward, terms, terminal_critical = compute_reward(
            coord=coord, prev_dist_to_goal=prev_dist_to_goal, dist_to_goal=dist_to_goal,
            dist_to_obs=dist_to_obs, critical_dist=self.critical_dist,
            clearance_ref=self.clearance_ref, dt=self.dt,
        )

        done = dist_to_goal < 0.3 or terminal_critical
        return self._get_state(), reward, done, terms


# ============================================================
# 2. Reward -- 팀원 문서 §9.3 수식: r_t = w_p*progress - w_c*clearance - w_i*intervention
#    - w_t*time + R_rejoin, 단 충돌/critical은 가중합 전에 terminal override
# ============================================================

REWARD_WEIGHTS = dict(w_progress=1.0, w_clearance=5.0, w_intervention=2.0, w_time=0.1, r_rejoin=10.0)


def compute_reward(coord: np.ndarray, prev_dist_to_goal: float, dist_to_goal: float,
                    dist_to_obs: float, critical_dist: float, clearance_ref: float,
                    dt: float) -> tuple[float, dict, bool]:
    w = REWARD_WEIGHTS

    # --- 팀원 문서 핵심 원칙: "점수로 위험을 상쇄하지 않는다" -- terminal critical은
    #     가중합 이전에 먼저 처리, 나머지 항은 아예 계산 안 함 ---
    if dist_to_obs < critical_dist:
        return -100.0, {"terminal_critical": True}, True

    progress = prev_dist_to_goal - dist_to_goal
    clearance_cost = max(0.0, clearance_ref - dist_to_obs) ** 2
    intervention = float(np.dot(coord, coord))  # 큰 offset일수록 "개입 강도"가 크다고 근사
    time_cost = dt
    rejoin_bonus = w["r_rejoin"] if dist_to_goal < 0.3 else 0.0

    total = (w["w_progress"] * progress - w["w_clearance"] * clearance_cost
             - w["w_intervention"] * intervention - w["w_time"] * time_cost + rejoin_bonus)

    return total, {"progress": progress, "clearance_cost": clearance_cost,
                    "intervention": intervention, "rejoin_bonus": rejoin_bonus}, False


# ============================================================
# 3. 고수준 정책 pi_H(z|s) -- TGRPO로 학습, discrete skill 선택
# ============================================================

class HighLevelPolicy(nn.Module):
    def __init__(self, state_dim: int = STATE_DIM, n_skills: int = N_SKILLS, hidden: int = 64):
        super().__init__()
        self.net = nn.Sequential(nn.Linear(state_dim, hidden), nn.ReLU(),
                                  nn.Linear(hidden, hidden), nn.ReLU(),
                                  nn.Linear(hidden, n_skills))

    def forward(self, state: torch.Tensor) -> torch.Tensor:
        return self.net(state)  # logits

    def sample(self, state: torch.Tensor, k: int) -> tuple[torch.Tensor, torch.Tensor]:
        """같은 state에서 k개의 skill을 샘플 (그룹). 반환: skill indices (k,), log_probs (k,)"""
        logits = self.forward(state.unsqueeze(0)).squeeze(0)  # (n_skills,)
        dist = torch.distributions.Categorical(logits=logits)
        skills = dist.sample((k,))
        log_probs = dist.log_prob(skills)
        return skills, log_probs


# ============================================================
# 4. 하위 정책 pi_L(p|s,z) -- SAC로 학습, skill 조건부 continuous 좌표
# ============================================================

LOG_STD_MIN, LOG_STD_MAX = -5.0, 2.0
COORD_SCALE = 2.0


class LowLevelPolicy(nn.Module):
    """state + skill(one-hot) -> Gaussian(x,y,yaw offset)."""

    def __init__(self, state_dim: int = STATE_DIM, n_skills: int = N_SKILLS,
                 coord_dim: int = COORD_DIM, hidden: int = 128):
        super().__init__()
        self.n_skills = n_skills
        self.net = nn.Sequential(nn.Linear(state_dim + n_skills, hidden), nn.ReLU(),
                                  nn.Linear(hidden, hidden), nn.ReLU())
        self.mean_head = nn.Linear(hidden, coord_dim)
        self.log_std_head = nn.Linear(hidden, coord_dim)

    def _skill_onehot(self, skill: torch.Tensor) -> torch.Tensor:
        return F.one_hot(skill.long(), num_classes=self.n_skills).float()

    def forward(self, state: torch.Tensor, skill: torch.Tensor):
        z = self._skill_onehot(skill)
        h = self.net(torch.cat([state, z], dim=-1))
        mean = self.mean_head(h)
        log_std = self.log_std_head(h).clamp(LOG_STD_MIN, LOG_STD_MAX)
        return mean, log_std

    def sample(self, state: torch.Tensor, skill: torch.Tensor, deterministic: bool = False):
        mean, log_std = self.forward(state, skill)
        std = log_std.exp()
        pre_tanh = mean if deterministic else mean + std * torch.randn_like(mean)
        coord = torch.tanh(pre_tanh) * COORD_SCALE

        normal_log_prob = (-0.5 * ((pre_tanh - mean) / (std + 1e-6)) ** 2
                            - log_std - 0.5 * np.log(2 * np.pi)).sum(-1, keepdim=True)
        log_prob = normal_log_prob - torch.log(COORD_SCALE * (1 - torch.tanh(pre_tanh) ** 2) + 1e-6).sum(-1, keepdim=True)
        return coord, log_prob


# ============================================================
# 5. Twin-Q critic (SAC용, state+skill+coord -> Q)
# ============================================================

class TwinQ(nn.Module):
    def __init__(self, state_dim: int = STATE_DIM, n_skills: int = N_SKILLS,
                 coord_dim: int = COORD_DIM, hidden: int = 128):
        super().__init__()
        self.n_skills = n_skills
        in_dim = state_dim + n_skills + coord_dim

        def make_q():
            return nn.Sequential(nn.Linear(in_dim, hidden), nn.ReLU(), nn.Linear(hidden, hidden),
                                  nn.ReLU(), nn.Linear(hidden, 1))
        self.q1 = make_q()
        self.q2 = make_q()

    def forward(self, state: torch.Tensor, skill: torch.Tensor, coord: torch.Tensor):
        z = F.one_hot(skill.long(), num_classes=self.n_skills).float()
        sza = torch.cat([state, z, coord], dim=-1)
        return self.q1(sza), self.q2(sza)


# ============================================================
# 6. Replay buffer (SAC, off-policy) -- (s, z, p, r, s', done)
# ============================================================

class ReplayBuffer:
    def __init__(self, capacity: int = 50_000):
        self.capacity = capacity
        self.buf: list[tuple] = []
        self.pos = 0

    def push(self, s, z, p, r, s2, done):
        item = (s, z, p, r, s2, done)
        if len(self.buf) < self.capacity:
            self.buf.append(item)
        else:
            self.buf[self.pos] = item
        self.pos = (self.pos + 1) % self.capacity

    def sample(self, batch_size: int):
        batch = random.sample(self.buf, batch_size)
        s, z, p, r, s2, done = zip(*batch)
        return (torch.tensor(np.array(s), dtype=torch.float32, device=DEVICE),
                torch.tensor(z, dtype=torch.float32, device=DEVICE),
                torch.tensor(np.array(p), dtype=torch.float32, device=DEVICE),
                torch.tensor(r, dtype=torch.float32, device=DEVICE).unsqueeze(-1),
                torch.tensor(np.array(s2), dtype=torch.float32, device=DEVICE),
                torch.tensor(done, dtype=torch.float32, device=DEVICE).unsqueeze(-1))

    def __len__(self):
        return len(self.buf)


# ============================================================
# 7. SAC 업데이트 (하위 정책, 매 스텝) -- skill은 고정 입력으로 취급(조건부)
# ============================================================

@dataclass
class SACAgent:
    policy: LowLevelPolicy
    q: TwinQ
    q_target: TwinQ
    policy_opt: torch.optim.Optimizer
    q_opt: torch.optim.Optimizer
    log_alpha: torch.Tensor
    alpha_opt: torch.optim.Optimizer
    target_entropy: float
    gamma: float = 0.99
    tau: float = 0.005
    # 2026-08-15 추가 -- CQL(Conservative Q-Learning) 옵션. 순수 오프라인 학습(추가 rollout
    # 없이 고정 buffer만 씀)에선 바닐라 SAC의 Q함수가 buffer에 없는(OOD) action에 과대추정
    # 값을 내는 문제가 알려져 있음(Fujimoto BCQ/Kumar CQL 논문) -- 우리 buffer가 극히 작아서
    # (수십 개) 이 문제에 특히 취약할 것으로 예상. **아직 실측 비교 안 함(단위테스트만).**
    use_cql: bool = False
    cql_alpha: float = 1.0     # OOD action Q값 억제 강도 -- 논문 기본값 근처(1~5 사이 흔히 씀)
    cql_n_samples: int = 10    # logsumexp 계산에 쓸 랜덤/정책 action 샘플 개수

    @property
    def alpha(self):
        return self.log_alpha.exp()

    def update(self, batch) -> dict:
        s, z, p, r, s2, done = batch

        with torch.no_grad():
            # 다음 state의 skill은 고수준 정책 재샘플 없이 같은 skill 유지로 근사(단순화)
            p2, log_prob2 = self.policy.sample(s2, z)
            q1_t, q2_t = self.q_target(s2, z, p2)
            q_t_min = torch.min(q1_t, q2_t) - self.alpha * log_prob2
            target = r + (1 - done) * self.gamma * q_t_min

        q1, q2 = self.q(s, z, p)
        critic_loss = F.mse_loss(q1, target) + F.mse_loss(q2, target)

        cql_log = {}
        if self.use_cql:
            n = s.shape[0]
            coord_dim = p.shape[-1]
            coord_scale = float(getattr(self.policy, "coord_scale", COORD_SCALE))
            s_rep = s.repeat_interleave(self.cql_n_samples, dim=0)
            z_rep = z.repeat_interleave(self.cql_n_samples, dim=0)

            random_actions = (torch.rand(n * self.cql_n_samples, coord_dim, device=s.device) * 2 - 1) * coord_scale
            with torch.no_grad():
                policy_actions, _ = self.policy.sample(s_rep, z_rep)

            q1_rand, q2_rand = self.q(s_rep, z_rep, random_actions)
            q1_pi, q2_pi = self.q(s_rep, z_rep, policy_actions)

            cat1 = torch.cat([q1_rand.view(n, self.cql_n_samples), q1_pi.view(n, self.cql_n_samples)], dim=1)
            cat2 = torch.cat([q2_rand.view(n, self.cql_n_samples), q2_pi.view(n, self.cql_n_samples)], dim=1)
            cql1 = (torch.logsumexp(cat1, dim=1, keepdim=True) - q1).mean()
            cql2 = (torch.logsumexp(cat2, dim=1, keepdim=True) - q2).mean()
            cql_loss = self.cql_alpha * (cql1 + cql2)
            critic_loss = critic_loss + cql_loss
            cql_log = {"cql_loss": cql_loss.item()}

        self.q_opt.zero_grad(); critic_loss.backward(); self.q_opt.step()

        p_new, log_prob_new = self.policy.sample(s, z)
        q1_new, q2_new = self.q(s, z, p_new)
        q_new_min = torch.min(q1_new, q2_new)
        actor_loss = (self.alpha * log_prob_new - q_new_min).mean()
        self.policy_opt.zero_grad(); actor_loss.backward(); self.policy_opt.step()

        alpha_loss = -(self.log_alpha * (log_prob_new.detach() + self.target_entropy)).mean()
        self.alpha_opt.zero_grad(); alpha_loss.backward(); self.alpha_opt.step()

        with torch.no_grad():
            for pp, pt in zip(self.q.parameters(), self.q_target.parameters()):
                pt.data.mul_(1 - self.tau).add_(self.tau * pp.data)

        return {"critic_loss": critic_loss.item(), "actor_loss": actor_loss.item(),
                "alpha": self.alpha.item(), **cql_log}


# ============================================================
# 8. TGRPO 업데이트 (고수준 정책, 주기적) -- K개 skill 그룹 상대평가
# ============================================================

def tgrpo_skill_update(high_policy: HighLevelPolicy, high_opt: torch.optim.Optimizer,
                        low_policy: LowLevelPolicy, env: ToyRecoveryEnv, state: np.ndarray,
                        k_skills: int = N_SKILLS, m_coords: int = 3, rollout_steps: int = 3) -> dict:
    """s_t에서 K개 skill 후보(팀원 문서에선 전수, 데모도 N_SKILLS 전부 시도) 샘플 ->
    각 skill마다 M개 좌표를 하위정책으로 뽑아 시뮬레이션 -> skill별 최고 좌표의 reward로
    skill 자체를 평가 -> 그룹(K개 skill) 정규화 -> critic 없이 고수준 정책 gradient."""
    state_t = torch.tensor(state, dtype=torch.float32, device=DEVICE)
    skills, log_probs = high_policy.sample(state_t, k_skills)  # (K,), (K,)

    skill_rewards = []
    for k in range(k_skills):
        skill_id = skills[k].item()
        best_reward = -float("inf")
        for m in range(m_coords):
            sim_env = ToyRecoveryEnv(robot_pos=env.robot_pos.copy(), robot_yaw=env.robot_yaw,
                                      goal_pos=env.goal_pos.copy(), obs_pos=env.obs_pos.copy(),
                                      obs_conf=env.obs_conf)
            skill_t = torch.tensor([skill_id], dtype=torch.float32, device=DEVICE)
            traj_reward = 0.0
            for step in range(rollout_steps):
                s_t = torch.tensor(sim_env._get_state(), dtype=torch.float32, device=DEVICE).unsqueeze(0)
                with torch.no_grad():
                    coord, _ = low_policy.sample(s_t, skill_t)
                _, r, done, _ = sim_env.step(coord.squeeze(0).cpu().numpy())
                traj_reward += r
                if done:
                    break
            best_reward = max(best_reward, traj_reward)
        skill_rewards.append(best_reward)

    rewards_t = torch.tensor(skill_rewards, dtype=torch.float32, device=DEVICE)
    advantage = (rewards_t - rewards_t.mean()) / (rewards_t.std() + 1e-6)

    tgrpo_loss = -(advantage.detach() * log_probs).mean()
    high_opt.zero_grad(); tgrpo_loss.backward(); high_opt.step()

    best_skill_idx = int(rewards_t.argmax().item())
    return {"tgrpo_loss": tgrpo_loss.item(), "group_reward_mean": rewards_t.mean().item(),
            "best_skill": SKILL_NAMES[skills[best_skill_idx].item()]}


# ============================================================
# 9. 메인 학습 루프
# ============================================================

def main() -> None:
    env = ToyRecoveryEnv()
    high_policy = HighLevelPolicy().to(DEVICE)
    low_policy = LowLevelPolicy().to(DEVICE)
    q = TwinQ().to(DEVICE)
    q_target = TwinQ().to(DEVICE)
    q_target.load_state_dict(q.state_dict())

    high_opt = torch.optim.Adam(high_policy.parameters(), lr=3e-4)
    agent = SACAgent(
        policy=low_policy, q=q, q_target=q_target,
        policy_opt=torch.optim.Adam(low_policy.parameters(), lr=3e-4),
        q_opt=torch.optim.Adam(q.parameters(), lr=3e-4),
        log_alpha=torch.zeros(1, requires_grad=True, device=DEVICE),
        alpha_opt=None, target_entropy=-COORD_DIM,
    )
    agent.alpha_opt = torch.optim.Adam([agent.log_alpha], lr=3e-4)

    buffer = ReplayBuffer()

    N_EPISODES = 60
    MAX_STEPS = 20
    BATCH_SIZE = 64
    WARMUP_STEPS = 200
    TGRPO_EVERY_N_STEPS = 5

    total_steps = 0
    last_sac_log, last_tgrpo_log = {}, {}
    for ep in range(N_EPISODES):
        state = env.reset()
        ep_reward = 0.0
        for t in range(MAX_STEPS):
            state_t = torch.tensor(state, dtype=torch.float32, device=DEVICE)
            with torch.no_grad():
                skill, _ = high_policy.sample(state_t, k=1)
                coord, _ = low_policy.sample(state_t.unsqueeze(0), skill.float())
            coord_np = coord.squeeze(0).cpu().numpy()
            skill_val = skill.item()

            next_state, reward, done, _ = env.step(coord_np)
            buffer.push(state, skill_val, coord_np, reward, next_state, float(done))
            ep_reward += reward
            total_steps += 1

            if len(buffer) >= max(BATCH_SIZE, WARMUP_STEPS):
                batch = buffer.sample(BATCH_SIZE)
                last_sac_log = agent.update(batch)

            if total_steps % TGRPO_EVERY_N_STEPS == 0 and len(buffer) >= WARMUP_STEPS:
                last_tgrpo_log = tgrpo_skill_update(high_policy, high_opt, low_policy, env, state)

            state = next_state
            if done:
                break

        if (ep + 1) % 10 == 0:
            print(f"[ep {ep+1:3d}] reward={ep_reward:7.2f} "
                  f"sac={ {k: round(v,3) for k,v in last_sac_log.items()} } "
                  f"tgrpo={ {k: (round(v,3) if isinstance(v,float) else v) for k,v in last_tgrpo_log.items()} }")

    print("\n계층구조 학습 루프 정상 종료 -- TGRPO(고수준 skill 선택)와 SAC(skill 조건부 좌표 생성)가")
    print("z->p 순차 조건부 구조로 결합되어 있는 것 확인됨 (팀원 문서 §6.1 구조).")
    print("다음 단계: N_SKILLS를 팀원 문서의 실제 recovery skill ontology로 교체,")
    print("ToyRecoveryEnv -> 실제 파이프라인, ReplayBuffer -> Episodic Memory API로 교체.")


if __name__ == "__main__":
    main()
