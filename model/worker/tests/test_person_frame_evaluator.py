"""한 프레임의 사람 전원을 사람별 상태로 평가한다."""

import math

import numpy as np
import pytest

from model.perception.segmentation.runtime.detector import Detection
from model.worker.person.fall_monitor import FallState, MonitorConfig
from model.worker.person.posture import PostureConfig

SHAPE = (200, 200, 3)
DIAGONAL = math.hypot(200, 200)


def _mask(x: int, y: int, width: int, height: int):
    mask = np.zeros((200, 200), dtype=bool)
    mask[y:y + height, x:x + width] = True
    return mask


def lying(track_id: str, *, x: int = 0, y: int = 0, confidence: float = 0.9) -> Detection:
    return Detection(1, confidence, _mask(x, y, 60, 20), track_id)


def standing(track_id: str, *, x: int = 100, y: int = 0, confidence: float = 0.9) -> Detection:
    return Detection(1, confidence, _mask(x, y, 20, 60), track_id)


def evaluator(**overrides):
    from model.worker.person.frame import PersonFrameEvaluator

    values = {
        "camera_id": "cam-1",
        "posture": PostureConfig(),
        "monitor": MonitorConfig(fall_confirm_seconds=1.0, immobile_seconds=5.0,
                                 recovery_confirm_seconds=1.0),
    }
    values.update(overrides)
    return PersonFrameEvaluator(**values)


def test_an_empty_frame_reports_no_detection() -> None:
    verdict = evaluator().evaluate([], SHAPE, 0.0)

    assert verdict.state == "NO_DETECTION"
    assert verdict.events == ()


def test_obstacles_are_not_evaluated_as_people() -> None:
    obstacle = Detection(0, 0.99, _mask(0, 0, 60, 20), "9")

    assert evaluator().evaluate([obstacle], SHAPE, 0.0).state == "NO_DETECTION"


def test_the_frame_reports_the_most_severe_person_state() -> None:
    """A standing bystander must not mask someone on the floor."""
    instance = evaluator()
    instance.evaluate([lying("a"), standing("b")], SHAPE, 0.0)
    verdict = instance.evaluate([lying("a"), standing("b")], SHAPE, 1.5)

    assert verdict.state == FallState.FALLEN.value
    assert verdict.track_id == "a"


def test_one_persons_walking_does_not_keep_another_out_of_immobile() -> None:
    """The bug this replaces: a shared posture baseline and a shared monitor."""
    instance = evaluator()
    # t=0 FALL_SUSPECTED, t=1 FALLEN, t=2 IMMOBILE, so t=7 is five still seconds.
    for step, bystander_x in enumerate([100, 130, 160, 100, 130, 160, 100, 130]):
        verdict = instance.evaluate(
            [lying("a"), standing("b", x=bystander_x)], SHAPE, float(step)
        )

    assert verdict.state == FallState.EMERGENCY_CANDIDATE.value
    assert verdict.track_id == "a"
    assert [event.track_id for event in verdict.events] == ["a"]


def test_a_person_who_leaves_the_frame_keeps_their_verdict() -> None:
    instance = evaluator()
    instance.evaluate([lying("a")], SHAPE, 0.0)
    instance.evaluate([lying("a")], SHAPE, 1.5)
    instance.evaluate([standing("a")], SHAPE, 2.0)   # one upright reading

    instance.evaluate([], SHAPE, 2.5)                # walks out of frame

    verdict = instance.evaluate([standing("a")], SHAPE, 4.0)
    assert verdict.state == FallState.FALLEN.value


def test_untracked_detections_fall_back_to_the_single_best_person() -> None:
    """Without track ids there is no identity to key per-person state on.

    Evaluating everyone against one shared monitor would be worse than the
    single-person behaviour it replaces, so the most confident person wins.
    """
    instance = evaluator()
    verdict = instance.evaluate(
        [lying("", confidence=0.4), standing("", confidence=0.95)], SHAPE, 0.0
    )

    assert verdict.state == FallState.NORMAL.value
    assert verdict.confidence == 0.95
