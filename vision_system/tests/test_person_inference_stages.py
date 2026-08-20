"""추론 세 단계가 각자 자기 몫만 하는지.

`realtime.py` 는 78 줄 안에 weight 해석·모델 로딩·캡처 루프·사람 선택·mask 기하·
낙상 판정·화면 그리기·이벤트 발행을 전부 담고 있었고 테스트가 하나도 없었다.
GPU 와 카메라 없이는 한 줄도 확인할 수 없는 구조였기 때문이다.

여기서 지키는 것은 **각 단계가 무거운 의존 없이 시험 가능하다**는 것이다.
"""

import json
import math
from pathlib import Path

import numpy as np
import pytest
import yaml

from vision_system.person_worker.fall_monitor import FallMonitor, FallState, MonitorConfig
from vision_system.person_worker.posture import (
    PostureConfig,
    PostureEstimator,
    mask_geometry,
)
from vision_system.person_worker.worker import load_settings, parse_source
from vision_system.yolo_inference_server.detector import (
    Detection,
    DetectorConfig,
    resolve_weights,
    select_best,
)


# ------------------------------------------------------------------ 1단계


def test_the_most_confident_person_wins() -> None:
    """한 프레임에 사람이 여럿이면 가장 확신이 높은 하나를 본다."""
    detections = [Detection(0, 0.99, None), Detection(1, 0.40, None), Detection(1, 0.80, None)]
    assert select_best(detections, 1).confidence == 0.80


def test_no_person_is_not_an_error() -> None:
    """검출 0 건과 추론 실패는 다르다. 앞의 것은 정상이다."""
    assert select_best([Detection(0, 0.9, None)], 1) is None
    assert select_best([], 1) is None


def test_the_person_class_id_is_configuration_not_a_constant() -> None:
    """`data.yaml` 의 클래스 순서가 바뀌면 이 값도 바뀐다."""
    assert DetectorConfig().person_class_id == 1
    assert DetectorConfig(person_class_id=0).person_class_id == 0


def test_an_impossible_detector_configuration_is_refused() -> None:
    """조용히 이상한 값으로 도는 것보다 뜨지 않는 편이 낫다."""
    for bad in ({"confidence": 0.0}, {"confidence": 1.5}, {"image_size": 0}):
        with pytest.raises(ValueError):
            DetectorConfig(**bad)


def test_the_selected_model_json_points_at_the_weights(tmp_path: Path) -> None:
    """multi-seed 실험은 대표 모델을 json 으로 남긴다.

    배포가 그 파일을 가리킬 수 있어야 seed 를 바꿔 다시 학습해도 배포 명령이
    그대로 남는다.
    """
    weights = tmp_path / "best.pt"
    weights.write_bytes(b"stub")
    selected = tmp_path / "selected_model.json"
    selected.write_text(json.dumps({"weights": str(weights)}), encoding="utf-8")
    assert resolve_weights(selected) == weights.resolve()
    assert resolve_weights(weights) == weights.resolve()


def test_a_missing_weight_fails_loudly(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        resolve_weights(tmp_path / "absent.pt")


# ------------------------------------------------------------------ 2단계


def _mask(rows: slice, columns: slice, size: int = 100) -> np.ndarray:
    mask = np.zeros((size, size), dtype=bool)
    mask[rows, columns] = True
    return mask


DIAGONAL = math.hypot(100, 100)


def test_a_lying_shape_is_low_posture() -> None:
    """가로가 세로보다 길면 누운 자세로 본다."""
    estimator = PostureEstimator(PostureConfig())
    measurement = estimator.measure(_mask(slice(48, 52), slice(10, 90)), DIAGONAL)
    assert measurement.low_posture and measurement.aspect_ratio > 1


def test_a_standing_shape_is_not_low_posture() -> None:
    estimator = PostureEstimator(PostureConfig())
    measurement = estimator.measure(_mask(slice(10, 90), slice(48, 52)), DIAGONAL)
    assert not measurement.low_posture and measurement.aspect_ratio < 1


def test_the_threshold_is_never_lowered_past_the_measured_floor() -> None:
    """2026-08-18 실측: 0.7 에서 `re_2` 에 오탐이 났다. 0.9 가 하한이다."""
    assert PostureConfig().fall_aspect_ratio >= 0.9


def test_the_first_frame_is_not_movement() -> None:
    """비교할 이전 위치가 없다. 그것을 이동 0 이 아니라 큰 이동으로 세면
    첫 프레임마다 정지 판정이 깨진다."""
    estimator = PostureEstimator(PostureConfig())
    assert estimator.measure(_mask(slice(48, 52), slice(10, 90)), DIAGONAL).motion == 0.0


def test_a_moved_person_is_moving() -> None:
    estimator = PostureEstimator(PostureConfig())
    estimator.measure(_mask(slice(48, 52), slice(10, 90)), DIAGONAL)
    moved = estimator.measure(_mask(slice(48, 52), slice(40, 120)), DIAGONAL)
    assert moved.moving and moved.motion > PostureConfig().motion_threshold


def test_losing_the_person_drops_the_movement_baseline() -> None:
    """사람이 사라졌다 다시 나타난 사이를 이동으로 세면 안 된다.

    그 간격은 몇 프레임일 수도 몇 초일 수도 있다. 그것을 이동으로 읽으면 실제로
    가만히 누워 있는 사람이 계속 "움직이는" 것으로 잡혀 `IMMOBILE` 에 영영
    도달하지 못한다.
    """
    estimator = PostureEstimator(PostureConfig())
    estimator.measure(_mask(slice(48, 52), slice(10, 90)), DIAGONAL)
    assert estimator.measure(np.zeros((100, 100), dtype=bool), DIAGONAL) is None
    resumed = estimator.measure(_mask(slice(48, 52), slice(40, 120)), DIAGONAL)
    assert resumed.motion == 0.0 and not resumed.moving


def test_an_empty_mask_has_no_geometry() -> None:
    assert mask_geometry(np.zeros((10, 10), dtype=bool)) is None


# ------------------------------------------------- 측정과 시간축의 분리


def test_the_state_machine_takes_a_finished_measurement() -> None:
    """`advance` 는 자세를 다시 재지 않는다. 그것이 갈아 끼울 수 있는 경계다."""
    monitor = FallMonitor(MonitorConfig(fall_confirm_seconds=1, immobile_seconds=2))
    assert monitor.advance(0, fallen=True, low_motion=True)["state"] == FallState.FALL_SUSPECTED.value
    assert monitor.advance(1, fallen=True, low_motion=True)["state"] == FallState.FALLEN.value
    assert monitor.advance(2, fallen=True, low_motion=True)["state"] == FallState.IMMOBILE.value
    result = monitor.advance(4, fallen=True, low_motion=True)
    assert result["state"] == FallState.EMERGENCY_CANDIDATE.value
    assert result["event"] is True


def test_measuring_and_deciding_agree_on_movement() -> None:
    """`posture.moving` 과 `advance(low_motion=...)` 이 같은 문턱을 봐야 한다.

    둘이 갈라지면 자세는 "정지" 인데 상태머신은 "움직인다" 로 읽어 `IMMOBILE`
    에 도달하지 못한다 — 증상은 "낙상을 놓친다" 로 나타나 원인에서 멀다.
    """
    settings = yaml.safe_load(
        (Path(__file__).resolve().parents[1] / "configs/realtime.yaml").read_text(encoding="utf-8")
    )
    posture = PostureConfig(
        fall_aspect_ratio=settings["monitor"]["fall_aspect_ratio"],
        motion_threshold=settings["monitor"]["motion_threshold"],
    )
    monitor = MonitorConfig(**settings["monitor"])
    assert posture.motion_threshold == monitor.motion_threshold
    assert posture.fall_aspect_ratio == monitor.fall_aspect_ratio


# ------------------------------------------------------------ 진입점 배선


def test_one_config_file_feeds_all_three_stages() -> None:
    """현장에서 함께 움직이는 값들이라 한 파일에 둔다."""
    detector, posture, monitor = load_settings(
        Path(__file__).resolve().parents[1] / "configs/realtime.yaml"
    )
    assert detector.person_class_id == 1
    assert posture.fall_aspect_ratio == monitor.fall_aspect_ratio
    assert monitor.recovery_confirm_seconds > 0


def test_a_camera_index_and_a_url_are_told_apart() -> None:
    assert parse_source("0") == 0
    assert parse_source("rtsp://host:8554/pinky/CAM-PK-01") == "rtsp://host:8554/pinky/CAM-PK-01"


# ------------------------------------------------------------- 카메라 신원

from vision_system.person_worker.worker import resolve_camera_id  # noqa: E402


def test_the_rtsp_url_already_carries_the_camera_id() -> None:
    """경로 규약이 `<역할>/<camera_id>` 다. 같은 사실을 두 곳에서 받지 않는다."""
    assert resolve_camera_id("rtsp://host:8554/pinky/CAM-PK-01", None) == "CAM-PK-01"
    assert resolve_camera_id("rtsp://host:8554/omx/CAM-OMX-01-WRIST", None) == "CAM-OMX-01-WRIST"


def test_a_local_camera_index_must_be_told_its_identity() -> None:
    """URL 이 없으면 파생할 근거가 없다. 지어내지 않고 멈춘다."""
    with pytest.raises(SystemExit):
        resolve_camera_id("0", None)
    assert resolve_camera_id("0", "CAM-PK-01") == "CAM-PK-01"
