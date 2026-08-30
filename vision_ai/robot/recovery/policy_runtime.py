"""Approved checkpoint adapter around the unchanged TGRPO+SAC policies."""

from __future__ import annotations

from pathlib import Path

from vision_ai.models.recovery.checkpoint import load_checkpoint


class ApprovedPolicyRuntime:
    policy_name = "TGRPO+SAC"

    def __init__(self, checkpoint_path: Path, checkpoint_sha256: str, *, device: str = "cuda"):
        self.checkpoint_path = Path(checkpoint_path)
        self.checkpoint_sha256 = checkpoint_sha256.lower()
        self.device = device
        self.high_policy = None
        self.low_policy = None

    def load(self) -> None:
        from vision_ai.models.recovery.policy_architecture import HighLevelPolicy, LowLevelPolicy

        checkpoint = load_checkpoint(
            self.checkpoint_path,
            self.checkpoint_sha256,
            approved=True,
            map_location=self.device,
        )
        self.high_policy = HighLevelPolicy().to(self.device)
        self.low_policy = LowLevelPolicy().to(self.device)
        self.high_policy.load_state_dict(checkpoint["high_policy"])
        self.low_policy.load_state_dict(checkpoint["low_policy"])
        self.high_policy.eval()
        self.low_policy.eval()

    def select(self, state: tuple[float, ...]) -> tuple[int, tuple[float, float, float]]:
        if self.high_policy is None or self.low_policy is None:
            self.load()
        import torch

        state_tensor = torch.tensor(state, dtype=torch.float32, device=self.device)
        with torch.no_grad():
            logits = self.high_policy(state_tensor.unsqueeze(0)).squeeze(0)
            skill = int(torch.argmax(logits).item())
            skill_tensor = torch.tensor([skill], device=self.device)
            coord, _ = self.low_policy.sample(
                state_tensor.unsqueeze(0), skill_tensor, deterministic=True
            )
        return skill, tuple(float(value) for value in coord.squeeze(0).cpu().tolist())

    def select_group(
        self,
        state: tuple[float, ...],
        *,
        k: int = 3,
        m: int = 2,
    ) -> list[tuple[int, tuple[float, float, float], float]]:
        """Preserve the original TGRPO K-skill × SAC M-coordinate sampling."""
        if self.high_policy is None or self.low_policy is None:
            self.load()
        import torch

        state_tensor = torch.tensor(state, dtype=torch.float32, device=self.device)
        candidates: list[tuple[int, tuple[float, float, float], float]] = []
        with torch.no_grad():
            skills, log_probs = self.high_policy.sample(state_tensor, k=k)
            for index in range(k):
                skill = int(skills[index].item())
                state_batch = state_tensor.unsqueeze(0).repeat(m, 1)
                skill_batch = skills[index:index + 1].repeat(m)
                coords, _ = self.low_policy.sample(state_batch, skill_batch)
                for coord in coords:
                    candidates.append((
                        skill,
                        tuple(float(value) for value in coord.cpu().tolist()),
                        float(log_probs[index].item()),
                    ))
        return candidates
