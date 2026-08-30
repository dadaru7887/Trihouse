"""distill_high_level.py가 만든 앙상블(high_level_distilled_ensemble.pt)로 uncertainty
기반 fallback 게이팅을 제공. orchestrate_live_teleop.py가 후보 winner를 정하기 직전에
이 모듈의 select_skill_or_fallback()을 호출해서 쓰면 됨.

게이팅 규칙(코덱스 제안 그대로):
  앙상블 예측이 일치(top1 skill 다수결 만장일치) AND 평균 entropy 낮음
      -> 학습된 selector의 top1 skill 확률 사용
  그 외(앙상블 disagreement 있음 OR entropy 높음)
      -> None 반환 -> 호출부가 기존 6C-Lite 선택 방식으로 fallback

이 모듈은 판단만 하고 실행은 안 함 -- 안전 관련 로직은 여기 안 건드림.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

DEFAULT_ENSEMBLE_PATH = Path("./distill_high_level_out/high_level_distilled_ensemble.pt")

# 게이팅 임계값 -- 둘 다 만족해야 학습된 selector를 신뢰. 보수적으로 시작(발표 전
# 안전 우선), 나중에 fallback 발동 비율 보고 조정할 것.
ENTROPY_THRESHOLD = 1.5   # 5-class 최대 entropy(ln5≈1.61)의 약 62% 이하일 때만 신뢰
REQUIRE_UNANIMOUS_TOP1 = True  # 앙상블 전원이 같은 top1 skill을 골라야 신뢰


class HighLevelPolicy(nn.Module):
    def __init__(self, state_dim: int, n_skills: int, hidden: int):
        super().__init__()
        self.net = nn.Sequential(nn.Linear(state_dim, hidden), nn.ReLU(),
                                  nn.Linear(hidden, hidden), nn.ReLU(),
                                  nn.Linear(hidden, n_skills))

    def forward(self, state: torch.Tensor) -> torch.Tensor:
        return self.net(state)


class DistilledSelectorGate:
    def __init__(self, ensemble_path: Path = DEFAULT_ENSEMBLE_PATH):
        bundle = torch.load(ensemble_path, map_location="cpu", weights_only=False)
        self.skill_names = bundle["skill_names"]
        self.models = []
        for sd in bundle["ensemble_state_dicts"]:
            m = HighLevelPolicy(bundle["state_dim"], bundle["n_skills"], bundle["hidden"])
            m.load_state_dict(sd)
            m.eval()
            self.models.append(m)

    def _ensemble_probs(self, state: np.ndarray) -> np.ndarray:
        x = torch.tensor(state, dtype=torch.float32).unsqueeze(0)
        probs = []
        with torch.no_grad():
            for m in self.models:
                p = F.softmax(m(x), dim=-1).squeeze(0).numpy()
                probs.append(p)
        return np.stack(probs)  # (n_ensemble, n_skills)

    def select_skill_or_fallback(self, state: np.ndarray) -> dict:
        """반환: {"use_learned": bool, "skill_name": str|None, "skill_idx": int|None,
        "mean_probs": np.ndarray, "entropy": float, "unanimous": bool, "reason": str}."""
        ens_probs = self._ensemble_probs(state)  # (n_ensemble, n_skills)
        top1_per_model = ens_probs.argmax(axis=1)
        unanimous = bool((top1_per_model == top1_per_model[0]).all())

        mean_probs = ens_probs.mean(axis=0)
        entropy = float(-(mean_probs * np.log(mean_probs + 1e-9)).sum())

        use_learned = entropy <= ENTROPY_THRESHOLD and (unanimous or not REQUIRE_UNANIMOUS_TOP1)

        if use_learned:
            top1_idx = int(mean_probs.argmax())
            return {
                "use_learned": True, "skill_name": self.skill_names[top1_idx],
                "skill_idx": top1_idx, "mean_probs": mean_probs, "entropy": entropy,
                "unanimous": unanimous,
                "reason": f"entropy={entropy:.2f}<={ENTROPY_THRESHOLD}, unanimous={unanimous}",
            }
        return {
            "use_learned": False, "skill_name": None, "skill_idx": None,
            "mean_probs": mean_probs, "entropy": entropy, "unanimous": unanimous,
            "reason": f"불확실 -- entropy={entropy:.2f}, unanimous={unanimous} -> 6C-Lite로 fallback",
        }


def _demo() -> None:
    gate = DistilledSelectorGate()
    rng = np.random.default_rng(0)
    fallback_count = 0
    n = 30
    for _ in range(n):
        fake_state = rng.normal(size=9).astype(np.float32)
        result = gate.select_skill_or_fallback(fake_state)
        tag = "LEARNED" if result["use_learned"] else "FALLBACK"
        print(f"[{tag}] {result['reason']} -> skill={result['skill_name']}")
        if not result["use_learned"]:
            fallback_count += 1
    print(f"\n임의 state {n}개 중 fallback 비율: {fallback_count}/{n} "
          f"({fallback_count/n*100:.0f}%) -- 랜덤 state라 대부분 fallback되는 게 정상")


if __name__ == "__main__":
    _demo()
