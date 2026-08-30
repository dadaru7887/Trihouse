import math
from pathlib import Path

import pytest

from vision_ai.utils.contracts import SKILL_NAMES

torch = pytest.importorskip("torch")


def _member_state_dict(logit_bias: list[float]) -> dict:
    """A HighLevelPolicy whose output is exactly `logit_bias` for any state."""
    from vision_ai.models.recovery.policy_architecture import HighLevelPolicy

    policy = HighLevelPolicy()
    state = policy.state_dict()
    for key in state:
        state[key] = torch.zeros_like(state[key])
    state["net.4.bias"] = torch.tensor(logit_bias, dtype=torch.float32)
    return state


def _write_bundle(tmp_path, member_biases, **overrides):
    import hashlib

    bundle = {
        "ensemble_state_dicts": [_member_state_dict(bias) for bias in member_biases],
        "state_dim": 9,
        "n_skills": 5,
        "hidden": 64,
        "skill_names": list(SKILL_NAMES),
        "temperature": 0.5,
    }
    bundle.update(overrides)
    path = tmp_path / "ensemble.pt"
    torch.save(bundle, path)
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


CONFIDENT_BACKUP = [8.0, 0.0, 0.0, 0.0, 0.0]
STATE = (1.0, 2.0, 0.3, 4.0, 5.0, 0.25, 0.75, 0.8, 0.1)


def test_gate_trusts_the_ensemble_when_unanimous_and_low_entropy(tmp_path) -> None:
    from vision_ai.models.recovery.distilled_selector import DistilledSelectorGate

    path, digest = _write_bundle(tmp_path, [CONFIDENT_BACKUP] * 5)
    gate = DistilledSelectorGate(path, digest, approved=True, device="cpu")

    decision = gate.select_skill_or_fallback(STATE)

    assert decision.use_learned is True
    assert decision.skill == 0
    assert decision.skill_name == "BACKUP"
    assert decision.unanimous is True
    assert decision.entropy <= 1.5


def test_gate_falls_back_when_the_ensemble_disagrees(tmp_path) -> None:
    from vision_ai.models.recovery.distilled_selector import DistilledSelectorGate

    disagreeing = [
        [8.0, 0.0, 0.0, 0.0, 0.0],
        [8.0, 0.0, 0.0, 0.0, 0.0],
        [8.0, 0.0, 0.0, 0.0, 0.0],
        [0.0, 8.0, 0.0, 0.0, 0.0],
        [0.0, 0.0, 8.0, 0.0, 0.0],
    ]
    path, digest = _write_bundle(tmp_path, disagreeing)
    gate = DistilledSelectorGate(path, digest, approved=True, device="cpu")

    decision = gate.select_skill_or_fallback(STATE)

    assert decision.use_learned is False
    assert decision.skill is None
    assert decision.unanimous is False


def test_gate_falls_back_when_mean_entropy_exceeds_the_threshold(tmp_path) -> None:
    from vision_ai.models.recovery.distilled_selector import DistilledSelectorGate

    # Flat logits: every member picks skill 0, so the ensemble is unanimous, but the
    # mean distribution is uniform (entropy ln 5 ≈ 1.61 > 1.5).
    path, digest = _write_bundle(tmp_path, [[0.0] * 5] * 5)
    gate = DistilledSelectorGate(path, digest, approved=True, device="cpu")

    decision = gate.select_skill_or_fallback(STATE)

    assert decision.unanimous is True
    assert decision.entropy > 1.5
    assert decision.use_learned is False
    assert decision.skill is None


def test_gate_rejects_a_bundle_that_breaks_the_frozen_skill_ontology(tmp_path) -> None:
    from vision_ai.models.recovery.distilled_selector import DistilledSelectorGate

    path, digest = _write_bundle(
        tmp_path, [CONFIDENT_BACKUP] * 5,
        skill_names=["BACKUP", "REROUTE_RIGHT", "REROUTE_LEFT", "WAIT_REOBSERVE", "REJOIN"],
    )
    gate = DistilledSelectorGate(path, digest, approved=True, device="cpu")

    with pytest.raises(ValueError, match="skill ontology"):
        gate.select_skill_or_fallback(STATE)


def test_gate_rejects_a_bundle_trained_on_a_different_state_dimension(tmp_path) -> None:
    from vision_ai.models.recovery.distilled_selector import DistilledSelectorGate

    path, digest = _write_bundle(tmp_path, [CONFIDENT_BACKUP] * 5, state_dim=11)
    gate = DistilledSelectorGate(path, digest, approved=True, device="cpu")

    with pytest.raises(ValueError, match="state/skill dimensions"):
        gate.select_skill_or_fallback(STATE)


def test_gate_refuses_an_unapproved_ensemble(tmp_path) -> None:
    from vision_ai.models.recovery.distilled_selector import DistilledSelectorGate

    path, digest = _write_bundle(tmp_path, [CONFIDENT_BACKUP] * 5)
    gate = DistilledSelectorGate(path, digest, approved=False, device="cpu")

    with pytest.raises(PermissionError):
        gate.select_skill_or_fallback(STATE)


def test_gate_refuses_an_ensemble_whose_checksum_does_not_match(tmp_path) -> None:
    from vision_ai.models.recovery.distilled_selector import DistilledSelectorGate

    path, _ = _write_bundle(tmp_path, [CONFIDENT_BACKUP] * 5)
    gate = DistilledSelectorGate(path, "0" * 64, approved=True, device="cpu")

    with pytest.raises(ValueError, match="SHA-256"):
        gate.select_skill_or_fallback(STATE)


REAL_ENSEMBLE = Path(
    "vision_ai/upstream/dev_driving/07_distillation/weights"
    "/high_level_distilled_ensemble.pt"
)
REAL_ENSEMBLE_SHA256 = "82c2f49745d95d31fe2f2d2019da5f67f3f59bdde3620d07004949b3192811bf"


def test_the_shipped_dev_driving_ensemble_loads_into_the_frozen_high_level_policy() -> None:
    from vision_ai.models.recovery.distilled_selector import DistilledSelectorGate

    if not REAL_ENSEMBLE.exists():
        pytest.skip("upstream distillation mirror is not checked out")
    gate = DistilledSelectorGate(REAL_ENSEMBLE, REAL_ENSEMBLE_SHA256, approved=True, device="cpu")

    decision = gate.select_skill_or_fallback(STATE)

    assert len(gate.members) == 5
    assert len(decision.mean_probs) == 5
    assert decision.entropy == pytest.approx(
        -sum(p * math.log(p + 1e-9) for p in decision.mean_probs), abs=1e-6
    )
    if decision.use_learned:
        assert decision.skill_name in SKILL_NAMES


def test_absent_selector_environment_keeps_the_unchanged_goal_distance_path() -> None:
    from vision_ai.models.recovery.distilled_selector import build_selector_from_env

    assert build_selector_from_env({}) is None


def test_selector_environment_builds_a_gate_bound_to_the_declared_checksum() -> None:
    from vision_ai.models.recovery.distilled_selector import build_selector_from_env

    gate = build_selector_from_env({
        "RECOVERY_SELECTOR_ENSEMBLE": "/opt/trihouse/ensemble.pt",
        "RECOVERY_SELECTOR_SHA256": "A" * 64,
        "VLM_RL_DEVICE": "cpu",
    })

    assert gate is not None
    assert gate.ensemble_path == Path("/opt/trihouse/ensemble.pt")
    assert gate.ensemble_sha256 == "a" * 64
    assert gate.device == "cpu"


@pytest.mark.parametrize("env", [
    {"RECOVERY_SELECTOR_ENSEMBLE": "/opt/trihouse/ensemble.pt"},
    {"RECOVERY_SELECTOR_SHA256": "a" * 64},
])
def test_half_configured_selector_fails_loudly_instead_of_silently_disabling(env) -> None:
    from vision_ai.models.recovery.distilled_selector import build_selector_from_env

    with pytest.raises(ValueError, match="RECOVERY_SELECTOR"):
        build_selector_from_env(env)
