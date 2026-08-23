"""orchestrate_live_teleop.py --execute가 실제 로봇 실행으로 쌓은 buffer(real_recovery_
buffer.pkl)를 불러와서 SAC(하위 정책)/TGRPO(상위 정책) 업데이트를 돌리는 오프라인 학습
스크립트.

이게 없으면 지금까지 만든 파이프라인은 "행동하고 기록만 하는" 상태였음 -- 이 스크립트가
실제로 정책을 gradient update 시키는 마지막 조각. 팀원 문서 §10 "운영 중에는 학습하지 않는다,
RTX 5080이 정지/docked 상태일 때 학습" 원칙과 일치 -- 로봇 운행 중이 아니라 이 스크립트를
따로 실행할 때만 학습.

2026-08-11 밤 정리 (원래 recovery_buffer.pkl/recovery_policy_checkpoint.pt 기준으로 짜여
있었는데 그날 밤 실제로 쓰기 시작한 파일들과 안 맞았던 것 수정):
- **buffer 경로**: `real_recovery_buffer.pkl`(orchestrate_live_teleop.py가 실제로 쓰는
  파일)로 맞춤. 기존 기본값(`recovery_buffer.pkl`)은 이 실행 흐름에서 안 씀.
- **checkpoint 경로**: `sim_recovery_policy_checkpoint.pt`로 맞춤 -- 오늘 라이브 테스트에서
  실제로 로드해서 썼던 그 체크포인트라, 여기서 이어 학습해야 "테스트했던 정책이 계속
  좋아지는" 흐름이 됨(별도의 `recovery_policy_checkpoint.pt`를 새로 만들면 서로 다른
  체크포인트 두 개로 갈라짐).
- **is_execution 필터 추가**: buffer엔 teleop 관찰 스냅샷(`is_execution=False`,
  `skill=-1`, `reward=0`, `next_state=state` placeholder)도 섞여있는데, 이게 안 걸러지면
  `tgrpo_update_from_buffer()`의 `by_skill[t["skill"]]`가 `skill=-1`에서 KeyError로 죽고,
  SAC replay에도 "아무 것도 안 한 것"이 진짜 action인 것처럼 섞여 들어감. 실제로 로봇이
  실행한 transition(`is_execution=True`)만 걸러서 씀.

2026-08-12 추가 (SAC 배치 샘플링을 균등 무작위 -> BucketedReplaySampler로 교체):
- 문제의식: buffer가 커질수록 실패/critical 사례는 원래 드문데(안전필터가 웬만하면 막으니까),
  균등 무작위 샘플링만 쓰면 critical 사례가 배치에 거의 안 뽑혀서 학습 신호에 잘 안 반영됨.
- 순환큐(오래된 거 강제 삭제)는 채택 안 함 -- SAC는 off-policy라 오래된 데이터도 원칙적으로
  유효하고, 지금처럼 실제 데이터가 극히 귀한 단계(30여 개)에서 데이터를 버리는 건 손해라고
  판단함(사용자 확인, 2026-08-12). 대신 replay_sampler.py의 BucketedReplaySampler를 그대로
  가져다 씀 -- SAFE/BOUNDARY/CRITICAL 버킷별 목표비율(50/30/20)로 뽑고, recency/rarity를
  importance weight로 반영(오래된 것도 버리지 않고 뽑힐 확률만 서서히 낮춤).
- TGRPO(`tgrpo_update_from_buffer`)는 원래대로 buffer 전체 raw 리스트를 그대로 씀(skill별
  전체 평균 reward를 쓰는 population 통계라 "배치 샘플링" 개념 자체가 없음) -- 오늘 바뀐 건
  SAC 배치 구성 방식뿐.
- **현재 buffer 실측(31개 실행 transition 기준)**: SAFE 8 / BOUNDARY 22 / CRITICAL 1.
  CRITICAL이 1개뿐이라 목표비율(20%)을 채우려면 매 배치마다 그 하나가 반복 추출됨 -- 새로운
  다양성이 생기는 게 아니라 그 사례 하나의 gradient 영향력이 커지는 것뿐임을 감안할 것.

SAC: buffer의 (state, skill, coord, reward, next_state, done)을 그대로 replay -- off-policy라
실행됐던 transition을 몇 번이고 재사용 가능.
TGRPO: buffer에 저장된 실제 state들을 "시작점"으로 재사용해서, 그 state에서 **현재(학습 중인)
정책**으로 여러 skill을 다시 샘플 -> 실제 env가 없으니 저장된 reward를 그 state 근방의
근사치로 사용(완전한 재시뮬레이션은 아님, 팀원 문서 §9.2의 이상적 형태보다 단순화된 버전 --
진짜 rollout 환경 붙기 전까지의 임시 근사).

실행: python3 offline_train_from_buffer.py [n_epochs]
"""

from __future__ import annotations

import math
import sys

import numpy as np
import torch

from recovery_data_collector import PersistentRecoveryBuffer
from replay_sampler import BucketedReplaySampler, TransitionRecord
from tgrpo_sac_hierarchical_v2 import (
    DEVICE, STATE_DIM, HighLevelPolicy, LowLevelPolicy, SACAgent, TwinQ, N_SKILLS,
)

import argparse

# 2026-08-15: train.sh CLI 래퍼용으로 argparse 추가. 기존 "python3 offline_train_from_buffer.py
# [n_epochs]" 위치 인자 방식도 --epochs 없이 그냥 숫자만 주면 동일하게 동작하게 남겨둠(하위 호환).
_parser = argparse.ArgumentParser(description=__doc__)
_parser.add_argument("epochs_positional", nargs="?", type=int, default=None,
                      help="(구버전 호환용) python3 offline_train_from_buffer.py 20 처럼 위치 인자로도 가능")
_parser.add_argument("--epochs", type=int, default=None)
_parser.add_argument("--high-rl", choices=["tgrpo", "dr_grpo", "dapo"], default="tgrpo",
                      help="상위 정책 학습 방식. tgrpo=advantage를 std로 정규화(기본, 표준 GRPO식). "
                           "dr_grpo=std 정규화 생략(Dr. GRPO 논문 지적 반영 -- 그룹이 작을수록 std "
                           "추정이 노이즈라는 문제 회피). dapo=비대칭 clip range(Clip-Higher) + "
                           "dynamic sampling(그룹 내 reward가 전부 동일해서 gradient가 0인 스텝은 "
                           "건너뜀) -- 2026-08-15 신규 추가, 아직 실측 비교는 안 해봄(스모크테스트만).")
_parser.add_argument("--sac-window", type=int, default=None,
                      help="SAC 배치 소스를 최근 N개로 제한(순환 큐). 기본은 None=buffer 전체 "
                           "사용. TGRPO 그룹통계는 이 값과 무관하게 항상 buffer 전체를 씀.")
_parser.add_argument("--low-rl", choices=["sac", "cql"], default="sac",
                      help="하위 정책 학습 방식. sac=바닐라(기본). cql=Conservative Q-Learning "
                           "penalty 추가 -- 순수 오프라인 학습(추가 rollout 없음)에서 SAC가 "
                           "buffer에 없는 action의 Q를 과대추정하는 문제를 완화. "
                           "2026-08-15 신규 추가, 아직 실측 비교 안 함(스모크테스트만).")
_args = _parser.parse_args()

BUFFER_PATH = "./real_recovery_buffer.pkl"
CHECKPOINT_PATH = "./sim_recovery_policy_checkpoint.pt"
BATCH_SIZE = 32
MIN_TRANSITIONS_TO_TRAIN = 4  # 이 밑으로는 배치 자체가 의미 없다고 보고 완전히 막음
N_EPOCHS = _args.epochs or _args.epochs_positional or 20

# 2026-08-12: reward clip은 검토 후 안 넣기로 함 -- PPO/GRPO의 clip은 확률비율(ratio) clip이지
# reward 값 clip이 아니라서 "PPO가 잘 되니 안전하다"는 근거가 성립 안 하고, reward 값을 직접
# clip하면 return 자체가 왜곡됨(DQN의 {-1,0,1} clip이 대표 사례, 서로 다른 크기의 성과를
# 구분 못 하게 만든 전례). reward=-100 문제는 애초에 버그 데이터라서 제외한 거지 "극단적이라서"가
# 아니었음 -- 진짜(버그 아닌) 극단적 실패 사례는 안전 신호로서 오히려 제일 중요하므로 clip으로
# 깎지 않기로 함(사용자 확인, 2026-08-12).
REWARD_CLIP = None  # 의도적으로 비활성 -- 아래에서 clip 미적용
# hard clip(min/max로 그냥 자르기) 대신 tanh 기반 soft clip -- 작은 값은 거의 그대로 통과,
# 큰 값일수록 압축되지만 순서(-100 < -50)는 항상 보존됨. DQN {-1,0,1} clip처럼 서로 다른
# 크기의 결과가 뭉개져서 구분 안 되는 문제를 피함(사용자 제안, 2026-08-12). 지금은 꺼둠
# (지금 buffer엔 극단값이 없음 -- 버그였던 -100은 이미 별도로 제외됨), 나중에 진짜 극단적인
# 실패 사례가 쌓이면 REWARD_SOFT_CLIP_SCALE에 숫자(예: 10.0)를 넣어서 켜면 됨.
REWARD_SOFT_CLIP_SCALE: float | None = None


# 2026-08-12 추가: Dr. GRPO 논문이 GRPO의 advantage 정규화(reward std로 나누기)가 편향을
# 만든다고 지적함 -- 그룹이 작을수록 std 추정 자체가 노이즈라, 우연히 std 작게 나온 그룹의
# advantage가 확 부풀려짐. 저희 skill 5개/그룹당 평균 6개(30/5)짜리라 이 문제에 취약한 규모.
# 기본값은 지금 동작(True=기존처럼 std로 나눔) 그대로 유지 -- 조사 결과만 반영해두고 결정은
# 사용자 판단으로 남겨둠. 2026-08-15: --high-rl dr_grpo로 CLI에서 바로 끌 수 있게 연결.
ADVANTAGE_STD_NORM = (_args.high_rl != "dr_grpo")

# 2026-08-12 추가: SAC/TGRPO가 buffer 크기에 반대로 반응하는 걸 실측 확인함(30개->15개로
# 줄였을 때 SAC critic_loss는 오히려 더 좋아졌는데, TGRPO entropy는 더 빨리 무너짐 -- 같은
# 소스를 15개로 자른 순수 부분집합 비교라 노이즈 아니라 실제 경향으로 판단, 사용자 확인
# 2026-08-12). SAC는 신선한/적은 데이터에 강하고 TGRPO는 그룹평균 노이즈 줄이려면 데이터가
# 많아야 해서 -- 그래서 둘의 데이터 소스를 분리함: SAC 배치는 최근 SAC_CIRCULAR_MAXLEN개(순환
# 큐)+bucket 샘플링, TGRPO 그룹통계는 항상 buffer 전체. 기본값 None = 기존과 동일(SAC도 전체
# 사용) -- 켜고 싶으면 숫자(예: 15) 지정.
SAC_CIRCULAR_MAXLEN: int | None = _args.sac_window

# 2026-08-12 추가: clip(surrogate ratio)/KL penalty -- 진짜 TGRPO/GRPO/PPO를 그것답게 만드는
# 안정화 장치인데 오늘까지 둘 다 없었음(엔트로피 보너스만 있었음). buffer엔 π_old(수집 당시
# 정책)의 log_prob이 저장 안 돼있어서, 대신 "이번 학습 실행 시작 시점에 로드한 checkpoint"를
# π_old/reference로 얼려두고 그 대비로 계산 -- PPO가 "한 배치로 K epoch 도는 동안 원본 정책
# 대비 clip"하는 것과 같은 논리, buffer 구조 변경 없이 구현 가능.
# **실측 결과로 기본값 True로 전환함(2026-08-12)**: 30개 데이터로 250 epoch 돌렸을 때
# entropy가 엔트로피 보너스만으론 1.59->0.28로 붕괴했는데, clip+KL 추가하니 1.59->1.52로
# 거의 안 무너짐(KL 0.02~0.05로 유지, clip_ratio_mean 0.93~0.98로 reference 근처 유지) --
# Dr.GRPO 때(거의 무효과)와 다르게 이번엔 명확한 개선이라 기본 채택. critic_loss(SAC)는
# 이 변경과 무관하게 그대로(격리 확인됨).
USE_CLIP_SURROGATE = True
CLIP_EPSILON = 0.2       # PPO 논문 표준값
USE_KL_PENALTY = (_args.high_rl != "dapo")  # DAPO 논문은 KL penalty를 아예 안 씀(clip만으로 제어)
KL_COEF = 0.01           # beta -- 작게 시작, 너무 크면 아예 못 움직임

# 2026-08-15 추가 -- DAPO(Decoupled Clip and Dynamic Sampling Policy Optimization) 스타일 옵션.
# 원 논문은 LLM 토큰 생성 세팅(overlong reward shaping 등 포함)이라 전부 그대로 옮길 순 없고,
# 우리(이산 skill 선택) 세팅에 이식 가능한 핵심 아이디어 2개만 반영함:
#   1) Clip-Higher(비대칭 clip range): 위쪽(good action 확률을 더 키우는 방향)은 더 널널하게
#      허용해서 entropy 붕괴(=특정 action에 조기 수렴)를 늦춤. 우리 문제(30여 개 데이터로도
#      entropy가 쉽게 무너짐)와 동기가 정확히 일치해서 이식함.
#   2) Dynamic sampling: 그룹 내 모든 skill의 reward가 사실상 동일하면(advantage 분산=0)
#      gradient가 안 나오는 스텝이라 원 논문은 그런 그룹/샘플을 걸러서 재표본. 여기선 오프라인
#      buffer라 "다시 뽑기"가 안 되니, 대신 해당 epoch의 TGRPO 업데이트를 건너뛰는 방식으로 근사.
# **아직 실측 비교 안 함** -- 코드만 준비, 실험은 EXPERIMENT_DESIGN.md 로드맵으로 남겨둠.
USE_DAPO_STYLE = (_args.high_rl == "dapo")
DAPO_CLIP_LOW = 0.2      # 논문 기본값
DAPO_CLIP_HIGH = 0.28    # 논문 기본값(Clip-Higher, 위쪽을 더 널널하게)
DAPO_MIN_REWARD_STD = 1e-4  # 이 밑이면 "그룹 내 전부 동일한 reward"로 보고 업데이트 스킵


def _scale_reward(r: float) -> float:
    if REWARD_CLIP is not None:
        return max(-REWARD_CLIP, min(REWARD_CLIP, r))
    if REWARD_SOFT_CLIP_SCALE is not None:
        return REWARD_SOFT_CLIP_SCALE * math.tanh(r / REWARD_SOFT_CLIP_SCALE)
    return r
# TGRPO가 30개 안 되는 데이터로 250 epoch 돌리면 특정 skill에 과확신(log_prob 계속 -로 발산,
# tgrpo_loss가 -10대까지 안 멈추고 커짐)하는 걸 실측 확인함 -- SAC의 alpha 같은 엔트로피 제약이
# TGRPO엔 없어서 생기는 문제. 표준 policy gradient 관행대로 엔트로피 보너스 추가해서 완화.
ENTROPY_COEF = 0.01


def to_transition_record(t: dict) -> TransitionRecord:
    """buffer의 plain dict(Transition을 asdict()한 것) -> BucketedReplaySampler가 쓰는
    TransitionRecord. map_zone은 아직 없어서 goal_waypoint(nominal waypoint id)로 대체."""
    meta = t.get("meta", {})
    return TransitionRecord(
        state=t["state"], skill=t["skill"], coord=t["coord"], reward=t["reward"],
        next_state=t["next_state"], done=t["done"],
        timestamp=meta.get("timestamp", 0.0),
        map_zone=meta.get("goal_waypoint", "unknown"),
        terminal_critical=bool(meta.get("terminal_critical", False)),
        policy_name=t.get("policy_name"), policy_version=t.get("policy_version"),
    )


def build_sac_batch(batch: list[TransitionRecord]) -> tuple:
    s = torch.tensor(np.array([r.state for r in batch]), dtype=torch.float32, device=DEVICE)
    z = torch.tensor([r.skill for r in batch], dtype=torch.float32, device=DEVICE)
    p = torch.tensor(np.array([r.coord for r in batch]), dtype=torch.float32, device=DEVICE)
    rewards = [_scale_reward(r.reward) for r in batch]
    r_ = torch.tensor(rewards, dtype=torch.float32, device=DEVICE).unsqueeze(-1)
    s2 = torch.tensor(np.array([r.next_state for r in batch]), dtype=torch.float32, device=DEVICE)
    done = torch.tensor([float(r.done) for r in batch], dtype=torch.float32, device=DEVICE).unsqueeze(-1)
    return s, z, p, r_, s2, done


def tgrpo_update_from_buffer(high_policy: HighLevelPolicy, high_opt: torch.optim.Optimizer,
                              transitions: list[dict], state: np.ndarray,
                              ref_policy: HighLevelPolicy | None = None) -> dict:
    """실제 rollout 환경 없이, buffer에 저장된 실제 (skill, reward) 관측치를 그룹으로 재사용.
    같은 state 근방에서 어떤 skill이 실제로 더 나은 결과였는지를 group-relative advantage로 학습.
    한계: 팀원 문서 §9.2처럼 "현재 정책으로 새로 trajectory 생성"이 아니라 "과거에 실행됐던
    관측치 재사용" -- off-policy에 가까운 근사(진짜 rollout 환경 붙으면 §9.2 방식으로 교체 권장).

    ref_policy: 이번 학습 실행 시작 시점 checkpoint를 얼려둔 스냅샷(π_old/reference 역할).
    USE_CLIP_SURROGATE/USE_KL_PENALTY가 켜져있으면 이걸로 clip ratio/KL을 계산함(둘 다
    꺼져있으면 ref_policy 없어도 됨, None 허용)."""
    state_t = torch.tensor(state, dtype=torch.float32, device=DEVICE)

    # buffer에서 skill별로 실제 관측된 reward들을 모음 (그룹 구성). SAC 배치와 동일 스케일링 정책.
    by_skill: dict[int, list[float]] = {k: [] for k in range(N_SKILLS)}
    for t in transitions:
        by_skill[t["skill"]].append(_scale_reward(t["reward"]))

    skills_with_data = [k for k, v in by_skill.items() if len(v) > 0]
    if len(skills_with_data) < 2:
        return {}  # 그룹 비교하려면 최소 2개 skill 데이터 필요

    logits = high_policy(state_t.unsqueeze(0)).squeeze(0)
    dist = torch.distributions.Categorical(logits=logits)

    skill_ids = torch.tensor(skills_with_data, device=DEVICE)
    log_probs = dist.log_prob(skill_ids)
    rewards = torch.tensor([np.mean(by_skill[k]) for k in skills_with_data],
                            dtype=torch.float32, device=DEVICE)

    # DAPO dynamic sampling 근사: 그룹 내 reward가 사실상 전부 동일하면 advantage가 0이라
    # gradient도 0 -- 원 논문은 이런 그룹을 걸러서 "새로 뽑기"를 하는데, 오프라인 buffer라
    # 재표본이 안 되니 대신 이번 업데이트를 건너뜀(빈 dict 반환 = 스킵).
    if USE_DAPO_STYLE and rewards.std().item() < DAPO_MIN_REWARD_STD:
        return {"skipped_dynamic_sampling": True, "n_skills_with_data": len(skills_with_data)}

    if ADVANTAGE_STD_NORM:
        advantage = (rewards - rewards.mean()) / (rewards.std() + 1e-6)
    else:
        advantage = rewards - rewards.mean()  # Dr. GRPO 방식 -- 작은 그룹의 std 노이즈 증폭 방지

    log: dict = {}
    if (USE_CLIP_SURROGATE or USE_KL_PENALTY) and ref_policy is not None:
        with torch.no_grad():
            ref_logits = ref_policy(state_t.unsqueeze(0)).squeeze(0)
        ref_dist = torch.distributions.Categorical(logits=ref_logits)
        ref_log_probs = ref_dist.log_prob(skill_ids)

    if USE_CLIP_SURROGATE and ref_policy is not None:
        # PPO/GRPO 표준 clipped surrogate -- ratio = exp(new_log_prob - old_log_prob),
        # advantage 부호에 따라 한쪽 방향으로만 과하게 안 움직이게 clip.
        ratio = torch.exp(log_probs - ref_log_probs.detach())
        if USE_DAPO_STYLE:
            # Clip-Higher: 위쪽(clip_high)을 더 널널하게 잡아서, 이미 낮은 확률인 action의
            # 확률이 커지는 쪽(entropy를 살리는 방향)을 덜 억제함 -- 원 논문의 entropy 붕괴
            # 완화 핵심 아이디어.
            clip_low, clip_high = DAPO_CLIP_LOW, DAPO_CLIP_HIGH
        else:
            clip_low, clip_high = CLIP_EPSILON, CLIP_EPSILON
        surrogate1 = ratio * advantage.detach()
        surrogate2 = torch.clamp(ratio, 1 - clip_low, 1 + clip_high) * advantage.detach()
        pg_loss = -torch.min(surrogate1, surrogate2).mean()
        log["clip_ratio_mean"] = ratio.mean().item()
    else:
        pg_loss = -(advantage.detach() * log_probs).mean()

    # 엔트로피 보너스: advantage만으로는 특정 skill에 계속 과확신하는 걸 막을 방법이 없어서
    # (SAC의 alpha 같은 제약이 TGRPO엔 없음) 표준 정책 엔트로피 항을 추가 -- entropy는 전체
    # 분포(logits) 기준으로 계산(그룹에 없는 skill 포함), 높을수록(덜 쏠릴수록) loss 감소.
    entropy = dist.entropy()
    loss = pg_loss - ENTROPY_COEF * entropy

    if USE_KL_PENALTY and ref_policy is not None:
        # 전체 skill 분포 기준 KL(현재정책 || reference) -- 이번 실행 시작 시점 checkpoint에서
        # 너무 멀리 안 벗어나게 억제. skills_with_data만 보는 log_probs와 달리 전체 분포로 계산.
        full_dist = torch.distributions.Categorical(logits=logits)
        with torch.no_grad():
            full_ref_logits = ref_policy(state_t.unsqueeze(0)).squeeze(0)
        full_ref_dist = torch.distributions.Categorical(logits=full_ref_logits)
        kl = torch.distributions.kl_divergence(full_dist, full_ref_dist)
        loss = loss + KL_COEF * kl
        log["kl"] = kl.item()

    high_opt.zero_grad(); loss.backward(); high_opt.step()
    log.update({"tgrpo_loss": loss.item(), "entropy": entropy.item(),
                "n_skills_with_data": len(skills_with_data)})
    return log


def main() -> None:
    buffer = PersistentRecoveryBuffer(save_path=BUFFER_PATH)
    n_total = len(buffer)
    buffer.transitions = [t for t in buffer.transitions if t.get("meta", {}).get("is_execution")]
    print(f"buffer 로드: 전체 {n_total}개 중 실제 실행(is_execution=True) {len(buffer.transitions)}개만 사용")
    if len(buffer) < MIN_TRANSITIONS_TO_TRAIN:
        print(f"실행된 transition 수({len(buffer)})가 너무 적음(<{MIN_TRANSITIONS_TO_TRAIN}) -- "
              f"더 모아야 학습 가능 (--execute로 orchestrate_live_teleop.py 더 돌리기)")
        return

    all_transitions = buffer.transitions  # TGRPO 그룹통계는 항상 이 전체를 씀(아래서 안 자름)

    sac_source = all_transitions
    if SAC_CIRCULAR_MAXLEN is not None:
        sac_source = sorted(all_transitions, key=lambda t: t.get("meta", {}).get("timestamp", 0.0))
        sac_source = sac_source[-SAC_CIRCULAR_MAXLEN:]
        print(f"SAC 배치 소스: 전체 {len(all_transitions)}개 중 최근 {len(sac_source)}개만 사용 "
              f"(TGRPO 그룹통계는 전체 {len(all_transitions)}개 그대로)")

    records = [to_transition_record(t) for t in sac_source]
    sampler = BucketedReplaySampler()
    for r in records:
        sampler.add(r)
    print(sampler.bucket_report())

    effective_batch_size = min(BATCH_SIZE, len(records))
    if effective_batch_size < BATCH_SIZE:
        print(f"경고: 실행된 transition이 {len(records)}개뿐이라 BATCH_SIZE를 "
              f"{BATCH_SIZE}->{effective_batch_size}로 줄여서 진행함. 이 실행은 스모크테스트 "
              f"성격(코드가 안 죽고 도는지 확인용) -- loss 수치 자체를 신뢰하지 말 것.")

    high_policy = HighLevelPolicy().to(DEVICE)
    low_policy = LowLevelPolicy().to(DEVICE)
    q = TwinQ().to(DEVICE)
    q_target = TwinQ().to(DEVICE)
    q_target.load_state_dict(q.state_dict())

    import os
    if os.path.exists(CHECKPOINT_PATH):
        ckpt = torch.load(CHECKPOINT_PATH, map_location=DEVICE)
        high_policy.load_state_dict(ckpt["high_policy"])
        low_policy.load_state_dict(ckpt["low_policy"])
        q.load_state_dict(ckpt["q"])
        q_target.load_state_dict(ckpt["q_target"])
        print(f"기존 checkpoint 로드: {CHECKPOINT_PATH}")

    # clip/KL용 reference policy -- 지금 막 로드한 checkpoint를 그대로 얼려서 π_old로 씀.
    # USE_CLIP_SURROGATE/USE_KL_PENALTY 둘 다 꺼져있으면 그냥 안 쓰이는 여분 사본일 뿐이라
    # 무해함(늘 만들어둠, 조건 분기 줄이려고).
    ref_policy = HighLevelPolicy().to(DEVICE)
    ref_policy.load_state_dict(high_policy.state_dict())
    ref_policy.eval()
    for p in ref_policy.parameters():
        p.requires_grad_(False)
    if USE_CLIP_SURROGATE or USE_KL_PENALTY:
        print(f"reference policy 스냅샷 완료 (clip={USE_CLIP_SURROGATE}, KL={USE_KL_PENALTY})")

    high_opt = torch.optim.Adam(high_policy.parameters(), lr=3e-4)
    agent = SACAgent(
        policy=low_policy, q=q, q_target=q_target,
        policy_opt=torch.optim.Adam(low_policy.parameters(), lr=3e-4),
        q_opt=torch.optim.Adam(q.parameters(), lr=3e-4),
        log_alpha=torch.zeros(1, requires_grad=True, device=DEVICE),
        alpha_opt=None, target_entropy=-3.0,
        use_cql=(_args.low_rl == "cql"),
    )
    agent.alpha_opt = torch.optim.Adam([agent.log_alpha], lr=3e-4)
    if agent.use_cql:
        print(f"CQL 활성화 (cql_alpha={agent.cql_alpha}, cql_n_samples={agent.cql_n_samples})")

    print(f"SAC 샘플 소스: {len(records)}개, TGRPO 그룹통계 소스: {len(all_transitions)}개, "
          f"low-rl={_args.low_rl}, {N_EPOCHS} epoch 학습 시작...")

    # 2026-08-15 추가: 그동안 학습 곡선(entropy, loss 등)이 print만 되고 파일로 안 남아서
    # 세션 끝나면 숫자가 텍스트 기록으로만 남던 문제 발견 -- epoch마다 CSV로 자동 저장.
    import csv as _csv
    import time as _time
    _log_path = f"./train_log_{_args.high_rl}_{int(_time.time())}.csv"
    _log_file = open(_log_path, "w", newline="")
    _log_writer = _csv.DictWriter(_log_file, fieldnames=[
        "epoch", "high_rl", "low_rl", "avg_critic_loss", "avg_cql_loss", "tgrpo_loss", "entropy", "kl",
        "clip_ratio_mean", "n_skills_with_data", "skipped_dynamic_sampling",
    ])
    _log_writer.writeheader()
    print(f"학습곡선 CSV 기록 시작 -> {_log_path}")

    n = len(records)
    n_batches_per_epoch = max(1, n // effective_batch_size)
    for epoch in range(N_EPOCHS):
        sac_losses = []
        cql_losses = []
        for _ in range(n_batches_per_epoch):
            # 균등 무작위 대신 SAFE/BOUNDARY/CRITICAL 목표비율 + recency weight로 샘플링
            batch_records = sampler.sample(batch_size=effective_batch_size)
            batch = build_sac_batch(batch_records)
            log = agent.update(batch)
            sac_losses.append(log["critic_loss"])
            if "cql_loss" in log:
                cql_losses.append(log["cql_loss"])

        # TGRPO는 population 통계(skill별 전체 평균 reward)라 버킷/순환큐 샘플링 대상이 아님 --
        # SAC_CIRCULAR_MAXLEN과 무관하게 항상 all_transitions(buffer 전체) 그대로 사용
        random_state = all_transitions[np.random.randint(len(all_transitions))]["state"]
        tgrpo_log = tgrpo_update_from_buffer(high_policy, high_opt, all_transitions, random_state,
                                              ref_policy=ref_policy)

        avg_critic_loss = np.mean(sac_losses) if sac_losses else float("nan")
        avg_cql_loss = np.mean(cql_losses) if cql_losses else None
        _log_writer.writerow({
            "epoch": epoch + 1, "high_rl": _args.high_rl, "low_rl": _args.low_rl,
            "avg_critic_loss": avg_critic_loss, "avg_cql_loss": avg_cql_loss,
            "tgrpo_loss": tgrpo_log.get("tgrpo_loss"), "entropy": tgrpo_log.get("entropy"),
            "kl": tgrpo_log.get("kl"), "clip_ratio_mean": tgrpo_log.get("clip_ratio_mean"),
            "n_skills_with_data": tgrpo_log.get("n_skills_with_data"),
            "skipped_dynamic_sampling": tgrpo_log.get("skipped_dynamic_sampling", False),
        })
        _log_file.flush()  # Ctrl+C로 중간에 끊겨도 그때까지 기록은 남게

        if (epoch + 1) % 5 == 0:
            print(f"[epoch {epoch+1:3d}] avg_critic_loss={avg_critic_loss:.3f} tgrpo={tgrpo_log}")

    _log_file.close()
    print(f"학습곡선 CSV 저장 완료: {_log_path}")

    torch.save({
        "high_policy": high_policy.state_dict(), "low_policy": low_policy.state_dict(),
        "q": q.state_dict(), "q_target": q_target.state_dict(),
    }, CHECKPOINT_PATH)
    print(f"\n학습 완료, checkpoint 저장: {CHECKPOINT_PATH}")
    print("다음 실행 시(로봇이 더 buffer를 채운 뒤) 이 checkpoint에서 이어서 학습 가능.")
    print("recovery_system_node.py에서도 이 checkpoint를 로드해서 학습된 정책으로 행동하게 해야 함")
    print("(현재 recovery_system_node.py는 TODO로만 표시되어 있고 실제 로드 코드는 없음).")


if __name__ == "__main__":
    main()
