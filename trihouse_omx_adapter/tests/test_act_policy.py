"""ACT 설정이 완전할 때만 실제 motion이 열린다."""

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent))

from trihouse_omx_adapter.act_policy import (  # noqa: E402
    FAKE_MODEL_LINEAGE,
    ActConfigurationError,
    ActPolicyLoader,
)


CONFIG = ROOT.parent / "config" / "act.simulation.yaml"


@pytest.fixture
def loader() -> ActPolicyLoader:
    return ActPolicyLoader()


def test_unconfigured_act_never_enables_real_motion(loader: ActPolicyLoader) -> None:
    policy = loader.load(repo_id="UNCONFIGURED", mode="simulation")

    assert policy.is_fake is True
    assert policy.real_motion_enabled is False


def test_shipped_simulation_config_is_unconfigured_and_fake(
    loader: ActPolicyLoader,
) -> None:
    policy = loader.load_file(CONFIG)

    assert policy.repo_id == "UNCONFIGURED"
    assert policy.revision == "UNCONFIGURED"
    assert policy.profile == "UNCONFIGURED"
    assert policy.mode == "deterministic_fake"
    assert policy.is_fake is True
    assert policy.real_motion_enabled is False


def test_hardware_mode_requires_every_value_to_be_specified(
    loader: ActPolicyLoader,
) -> None:
    for repo, revision, profile in (
        ("UNCONFIGURED", "abc123", "omx-pick-v1"),
        ("org/act-omx", "UNCONFIGURED", "omx-pick-v1"),
        ("org/act-omx", "abc123", "UNCONFIGURED"),
        ("org/act-omx", "abc123", "   "),
    ):
        with pytest.raises(ActConfigurationError):
            loader.load(
                repo_id=repo, revision=revision, profile=profile, mode="hardware"
            )


def test_fully_specified_hardware_policy_opens_real_motion(
    loader: ActPolicyLoader,
) -> None:
    policy = loader.load(
        repo_id="org/act-omx",
        revision="9f3c1d2e",
        profile="omx-pick-v1",
        mode="hardware",
        model_lineage="org/act-omx@9f3c1d2e",
    )

    assert policy.is_fake is False
    assert policy.real_motion_enabled is True


def test_unknown_mode_is_rejected(loader: ActPolicyLoader) -> None:
    with pytest.raises(ActConfigurationError, match="unsupported ACT mode"):
        loader.load(repo_id="org/act-omx", mode="autonomous")


def test_fake_episode_emits_the_five_stages_and_records_lineage(
    loader: ActPolicyLoader,
) -> None:
    policy = loader.load_file(CONFIG)

    episode = policy.run_episode(command_uuid="cmd-1", assignment_revision=5)

    assert [stage.name for stage in episode.stages] == [
        "OBSERVE", "POLICY", "GRASP", "VERIFY", "HANDOVER",
    ]
    assert [stage.sequence_no for stage in episode.stages] == [1, 2, 3, 4, 5]
    assert episode.model_lineage == FAKE_MODEL_LINEAGE
    assert all(stage.model_lineage == FAKE_MODEL_LINEAGE for stage in episode.stages)
    assert episode.real_motion_emitted is False
    assert episode.assignment_revision == 5


def test_fake_episode_is_deterministic(loader: ActPolicyLoader) -> None:
    policy = loader.load_file(CONFIG)

    first = policy.run_episode(command_uuid="cmd-1", assignment_revision=5)
    second = policy.run_episode(command_uuid="cmd-1", assignment_revision=5)

    assert first == second
