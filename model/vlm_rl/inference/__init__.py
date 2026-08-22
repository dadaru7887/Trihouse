"""Production-only recovery candidate inference."""

from typing import Any

__all__ = ["RLCandidate", "sample_candidate_group"]


def __getattr__(name: str) -> Any:
    """Load PyTorch-backed candidates only when inference actually requests them."""
    if name in __all__:
        from .candidate_generator import RLCandidate, sample_candidate_group

        return {"RLCandidate": RLCandidate, "sample_candidate_group": sample_candidate_group}[name]
    raise AttributeError(name)
