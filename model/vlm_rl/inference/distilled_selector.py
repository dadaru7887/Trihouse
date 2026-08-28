"""Distilled high-level skill selector with an uncertainty fallback gate.

Ported from `dev_driving:driving_vlm_rm/07_distillation/distilled_selector_gate.py`
without changing the gating mathematics. The Trihouse form adds approved-checkpoint
verification and reuses the frozen `HighLevelPolicy`, so a bundle that disagrees with
the five-skill contract can never reach inference.

The gate only judges; it never executes. A learned skill still has to survive the
recovery motion boundary, Gateway approval, Nav2 planning, and the robot-side Safety
Supervisor exactly as before.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import math
from pathlib import Path

from model.vlm_rl.shared.contracts import N_SKILLS, SKILL_NAMES, STATE_DIM

from .checkpoint import load_checkpoint


# Both conditions must hold before the distilled selector is trusted. Conservative
# on purpose: 1.5 is about 62% of the five-class maximum entropy (ln 5 ≈ 1.61).
ENTROPY_THRESHOLD = 1.5
REQUIRE_UNANIMOUS_TOP1 = True


@dataclass(frozen=True)
class SelectorDecision:
    use_learned: bool
    skill: int | None
    skill_name: str | None
    mean_probs: tuple[float, ...]
    entropy: float
    unanimous: bool
    reason: str


class DistilledSelectorGate:
    selector_name = "high-level-distilled-ensemble"

    def __init__(self, ensemble_path: Path, ensemble_sha256: str, *, approved: bool = True,
                 device: str = "cpu", entropy_threshold: float = ENTROPY_THRESHOLD,
                 require_unanimous_top1: bool = REQUIRE_UNANIMOUS_TOP1):
        self.ensemble_path = Path(ensemble_path)
        self.ensemble_sha256 = ensemble_sha256.lower()
        self.approved = approved
        self.device = device
        self.entropy_threshold = entropy_threshold
        self.require_unanimous_top1 = require_unanimous_top1
        self.members: list = []

    def load(self) -> None:
        import torch

        from model.vlm_rl.shared.policy_architecture import HighLevelPolicy

        bundle = load_checkpoint(
            self.ensemble_path,
            self.ensemble_sha256,
            approved=self.approved,
            map_location=self.device,
        )
        self._verify_contract(bundle)
        members = []
        for state_dict in bundle["ensemble_state_dicts"]:
            member = HighLevelPolicy().to(self.device)
            member.load_state_dict(state_dict)
            member.eval()
            members.append(member)
        if not members:
            raise ValueError("distilled selector bundle contains no ensemble members")
        self.members = members

    @staticmethod
    def _verify_contract(bundle) -> None:
        if bundle.get("state_dim") != STATE_DIM or bundle.get("n_skills") != N_SKILLS:
            raise ValueError(
                "distilled selector bundle does not match the frozen state/skill dimensions"
            )
        if tuple(bundle.get("skill_names", ())) != SKILL_NAMES:
            raise ValueError(
                "distilled selector bundle does not match the frozen skill ontology"
            )

    def select_skill_or_fallback(self, state: tuple[float, ...]) -> SelectorDecision:
        if not self.members:
            self.load()
        import torch
        import torch.nn.functional as F

        state_tensor = torch.tensor(state, dtype=torch.float32, device=self.device).unsqueeze(0)
        with torch.no_grad():
            member_probs = [
                F.softmax(member(state_tensor), dim=-1).squeeze(0) for member in self.members
            ]
        top1 = [int(probs.argmax().item()) for probs in member_probs]
        unanimous = all(value == top1[0] for value in top1)
        stacked = torch.stack(member_probs).mean(dim=0)
        mean_probs = tuple(float(value) for value in stacked.cpu().tolist())
        entropy = -sum(value * math.log(value + 1e-9) for value in mean_probs)

        if entropy <= self.entropy_threshold and (unanimous or not self.require_unanimous_top1):
            skill = max(range(N_SKILLS), key=lambda index: mean_probs[index])
            return SelectorDecision(
                use_learned=True, skill=skill, skill_name=SKILL_NAMES[skill],
                mean_probs=mean_probs, entropy=entropy, unanimous=unanimous,
                reason=f"entropy={entropy:.2f}<={self.entropy_threshold}, unanimous={unanimous}",
            )
        return SelectorDecision(
            use_learned=False, skill=None, skill_name=None, mean_probs=mean_probs,
            entropy=entropy, unanimous=unanimous,
            reason=f"uncertain: entropy={entropy:.2f}, unanimous={unanimous}",
        )


def build_selector_from_env(env: Mapping[str, str]) -> DistilledSelectorGate | None:
    """Build the gate only when both the ensemble and its approved digest are declared.

    Leaving both unset keeps the pre-distillation behaviour: candidates are ranked by
    goal distance alone. Declaring one without the other is a deployment mistake, not
    an opt-out, so it raises instead of silently disabling the gate.
    """
    path = env.get("RECOVERY_SELECTOR_ENSEMBLE")
    digest = env.get("RECOVERY_SELECTOR_SHA256")
    if not path and not digest:
        return None
    if not path or not digest:
        raise ValueError(
            "RECOVERY_SELECTOR_ENSEMBLE and RECOVERY_SELECTOR_SHA256 must be set together"
        )
    return DistilledSelectorGate(
        Path(path), digest, approved=True, device=env.get("VLM_RL_DEVICE", "cuda")
    )
