import pytest

from vision_ai.robot.recovery.runtime import parse_runtime_args
from vision_ai.robot.safety.config import resolve_safety_gate


def test_safety_gate_defaults_to_enabled() -> None:
    assert resolve_safety_gate("physical", None, {}) is True


def test_cli_safety_gate_value_overrides_environment() -> None:
    assert resolve_safety_gate(
        "training_exploration",
        True,
        {"VLM_RL_SAFETY_GATE_ENABLED": "false"},
    ) is True


def test_training_exploration_can_disable_pre_execution_gate() -> None:
    assert resolve_safety_gate(
        "training_exploration",
        None,
        {"VLM_RL_SAFETY_GATE_ENABLED": "false"},
    ) is False


def test_physical_runtime_rejects_a_disabled_pre_execution_gate() -> None:
    with pytest.raises(ValueError, match="physical"):
        resolve_safety_gate("physical", False, {})


def test_safety_gate_rejects_ambiguous_boolean_text() -> None:
    with pytest.raises(ValueError, match="boolean"):
        resolve_safety_gate(
            "training_exploration",
            None,
            {"VLM_RL_SAFETY_GATE_ENABLED": "disabled"},
        )


def test_runtime_accepts_explicit_equals_style_safety_argument() -> None:
    args = parse_runtime_args(
        ["--runtime-mode=training_exploration", "--safety-gate-enabled=false"]
    )

    assert args.runtime_mode == "training_exploration"
    assert args.safety_gate_enabled is False


def test_runtime_prompt_version_is_an_argument_over_the_environment(monkeypatch) -> None:
    from vision_ai.models.recovery.vlm_interpreter import load_prompts

    monkeypatch.delenv("VLM_PROMPT_VERSION", raising=False)
    assert parse_runtime_args([]).prompt_version == load_prompts()["runtime_version"]
    monkeypatch.setenv("VLM_PROMPT_VERSION", "current")
    assert parse_runtime_args([]).prompt_version == "current"
    assert parse_runtime_args(["--prompt-version", "v1"]).prompt_version == "v1"
