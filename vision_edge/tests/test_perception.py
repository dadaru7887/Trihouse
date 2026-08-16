"""QR/ArUco 처리와 네 가지 적재 증거 판정."""

import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from vision_edge.perception import (  # noqa: E402
    ARUCO_DICTIONARY,
    VisionPerception,
    classify_load_evidence,
)


@pytest.fixture
def perception() -> VisionPerception:
    return VisionPerception()


def test_p0_uses_the_measured_aruco_dictionary() -> None:
    assert ARUCO_DICTIONARY == "DICT_5X5_50"


def test_marker_and_qr_are_both_required(perception: VisionPerception) -> None:
    result = perception.verify(
        qr="SKU-MILK", marker_id=1, expected_qr="SKU-MILK", expected_marker=1
    )
    assert result.accepted is True
    assert (
        perception.verify(
            qr="SKU-MILK", marker_id=0, expected_qr="SKU-MILK", expected_marker=1
        ).accepted
        is False
    )


def test_each_mismatch_has_its_own_reason(perception: VisionPerception) -> None:
    assert (
        perception.verify(
            qr="SKU-ORANGE", marker_id=1, expected_qr="SKU-MILK", expected_marker=1
        ).reason_code
        == "QR_MISMATCH"
    )
    assert (
        perception.verify(
            qr="SKU-MILK", marker_id=2, expected_qr="SKU-MILK", expected_marker=1
        ).reason_code
        == "MARKER_MISMATCH"
    )
    assert (
        perception.verify(
            qr=None, marker_id=1, expected_qr="SKU-MILK", expected_marker=1
        ).reason_code
        == "OBSERVATION_MISSING"
    )
    assert (
        perception.verify(
            qr="SKU-MILK", marker_id=None, expected_qr="SKU-MILK", expected_marker=1
        ).reason_code
        == "OBSERVATION_MISSING"
    )


def test_qr_detection_returns_value_and_bounding_box() -> None:
    class FakeDetector:
        def detectAndDecode(self, image):
            return "SKU-MILK", [[(1.0, 2.0), (3.0, 2.0), (3.0, 4.0), (1.0, 4.0)]], None

    observation = VisionPerception(detector=FakeDetector()).detect_qr(object())

    assert observation.value == "SKU-MILK"
    assert observation.bounding_box == ((1.0, 2.0), (3.0, 2.0), (3.0, 4.0), (1.0, 4.0))


def test_undecoded_qr_returns_no_observation() -> None:
    class EmptyDetector:
        def detectAndDecode(self, image):
            return "", None, None

    assert VisionPerception(detector=EmptyDetector()).detect_qr(object()) is None


def test_marker_detection_returns_id_corners_and_pose() -> None:
    class FakeAruco:
        def detect(self, image):
            corners = [[[(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)]]]
            return corners, [[2]], None

        def estimate_poses(self, corners, *, marker_length_m, camera_matrix, distortion):
            return [((0.1, 0.2, 0.3), (1.0, 2.0, 3.0))]

    markers = VisionPerception(aruco=FakeAruco()).detect_markers(object())

    assert len(markers) == 1
    assert markers[0].marker_id == 2
    assert markers[0].dictionary == "DICT_5X5_50"
    assert markers[0].corners == ((0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0))
    assert markers[0].rvec == (0.1, 0.2, 0.3)
    assert markers[0].tvec == (1.0, 2.0, 3.0)


def test_no_marker_in_frame_yields_no_synthetic_id() -> None:
    class EmptyAruco:
        def detect(self, image):
            return [], None, None

        def estimate_poses(self, *args, **kwargs):  # pragma: no cover - never reached
            raise AssertionError("pose estimation must not run without a marker")

    assert VisionPerception(aruco=EmptyAruco()).detect_markers(object()) == ()


# --- 네 가지 적재 결과 ---------------------------------------------------------


def test_all_three_criteria_confirm_the_load() -> None:
    evidence = classify_load_evidence(
        gripper_opened_over_roi=True,
        item_inside_roi_after_release=True,
        empty_gripper_retreated=True,
        evidence_refs=("clip://omx-01/wrist/1", "clip://fixed-01/roi/1"),
    )

    assert evidence.result == "LOAD_CONFIRMED"
    assert evidence.evidence_refs == (
        "clip://omx-01/wrist/1",
        "clip://fixed-01/roi/1",
    )


def test_item_leaving_the_basket_is_a_drop() -> None:
    evidence = classify_load_evidence(
        gripper_opened_over_roi=True,
        item_inside_roi_after_release=False,
        empty_gripper_retreated=True,
        item_seen_outside_roi=True,
    )

    assert evidence.result == "DROP_DETECTED"


def test_gripper_that_never_let_go_is_a_retained_grasp() -> None:
    evidence = classify_load_evidence(
        gripper_opened_over_roi=False,
        item_inside_roi_after_release=False,
        empty_gripper_retreated=False,
    )

    assert evidence.result == "GRASP_RETAINED"


def test_inconclusive_observation_is_uncertain_not_confirmed() -> None:
    evidence = classify_load_evidence(
        gripper_opened_over_roi=True,
        item_inside_roi_after_release=False,
        empty_gripper_retreated=True,
        item_seen_outside_roi=False,
    )

    assert evidence.result == "LOAD_UNCERTAIN"


def test_every_outcome_is_one_of_exactly_four_states() -> None:
    results = set()
    for opened in (True, False):
        for inside in (True, False):
            for retreated in (True, False):
                for outside in (True, False):
                    results.add(
                        classify_load_evidence(
                            gripper_opened_over_roi=opened,
                            item_inside_roi_after_release=inside,
                            empty_gripper_retreated=retreated,
                            item_seen_outside_roi=outside,
                        ).result
                    )

    assert results <= {
        "LOAD_CONFIRMED", "DROP_DETECTED", "LOAD_UNCERTAIN", "GRASP_RETAINED",
    }
