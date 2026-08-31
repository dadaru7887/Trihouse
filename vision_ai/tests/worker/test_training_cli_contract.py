"""학습 CLI 계약: 증강 플래그와 모델 이름."""

import pytest

from vision_ai.models.perception.trainer.cli import config_from_args
from vision_ai.models.perception.trainer.pipeline import build_parser


def _run(argv):
    return build_parser().parse_args(["run", "--data", "/d.yaml", *argv])


# ---------------------------------------------- 증강 플래그


def test_augmentation_is_on_by_default() -> None:
    assert _run([]).augmentation is True


def test_the_no_prefix_turns_augmentation_off() -> None:
    """`--no-augmentation` 하나로 끈다. 값을 따로 적지 않는다."""
    assert _run(["--no-augmentation"]).augmentation is False


def test_the_bare_flag_turns_augmentation_on() -> None:
    assert _run(["--augmentation"]).augmentation is True


def test_the_flag_reaches_the_config_as_a_bool() -> None:
    config = config_from_args(_run(["--no-augmentation"]), run_root="/tmp/r", name="t")

    assert config.augmentation is False


@pytest.mark.parametrize("legacy", [["--augmentation", "yes"], ["--augmentation", "no"]])
def test_the_old_yes_no_form_is_rejected(legacy) -> None:
    """조용히 무시되면 증강 없이 학습한 걸 모르고 지나간다."""
    with pytest.raises(SystemExit):
        _run(legacy)


# ---------------------------------------------- 모델 이름


def test_the_model_name_is_used_exactly_as_given() -> None:
    """축약어를 확장하지 않는다 — 실제로 쓰이는 이름이 곧 적은 이름이어야 한다."""
    from vision_ai.models.perception.trainer.yoloe_trainer import resolve_model

    for name in ("yoloe-26s-seg.pt", "yoloe-11m-seg.pt", "/models/custom.pt"):
        assert resolve_model(name) == name


def test_a_bare_shorthand_is_refused_rather_than_guessed() -> None:
    """`26s` 가 어떤 파일이 되는지는 코드를 열어야만 알 수 있었다."""
    from vision_ai.models.perception.trainer.yoloe_trainer import resolve_model

    with pytest.raises(ValueError, match="26s"):
        resolve_model("26s")


def test_the_default_model_is_a_full_name() -> None:
    assert _run([]).model.endswith(".pt")
