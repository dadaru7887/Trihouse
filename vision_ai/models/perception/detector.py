"""Stage 1 -- find people and obstacles in one frame.

    detector = Detector(DetectorConfig(weights=..., person_class_id=1))
    detections = detector.detect(frame)      # -> list[Detection]

**Posture is not decided here.** `robot/perception/posture.py` measures it
from the mask and `robot/perception/policy.py` decides a fall over time. The
split is about cost, not tidiness: detection runs on every frame because the
robot's safety gate slows down on its output, while posture only has to run
when a person was found.

The heavy imports (`ultralytics`, `torch`) happen inside `load()`, so this
module can be read and tested on a machine with no GPU.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence
import json


@dataclass(frozen=True)
class DetectorConfig:
    """Mirrors the `inference` section of `configs/realtime.yaml`."""

    confidence: float = 0.25
    image_size: int = 640
    device: str = "auto"
    # Comes from `names: ['obstacle', 'person']` in data.yaml. Reordering the
    # classes changes it, so it is configured rather than hardcoded.
    person_class_id: int = 1
    # On, this runs track(persist=True) instead of predict, which yields a
    # track_id that survives across frames. Per-person state needs that
    # identity. Off by default because the tracker adds per-frame cost and
    # state that a caller watching one person has no reason to pay.
    tracking: bool = False

    def __post_init__(self) -> None:
        if not 0.0 < self.confidence <= 1.0:
            raise ValueError("confidence must be greater than 0 and at most 1")
        if self.image_size <= 0:
            raise ValueError("image_size must be positive")
        if self.person_class_id < 0:
            raise ValueError("person_class_id must be 0 or more")


@dataclass(frozen=True)
class Detection:
    """One detected instance. `mask` is a frame-sized bool array.

    `track_id` is filled only when tracking is on. An empty string means "a
    detection in this frame, with no identity across frames" -- whatever holds
    per-person state has to tell those apart.
    """

    class_id: int
    confidence: float
    mask: Any
    track_id: str = ""


def resolve_weights(value: Path) -> Path:
    """Resolve weights given either a best.pt or a selected_model.json.

    A multi-seed experiment records its representative model as
    selected_model.json. Deployment points at that file, so retraining with
    different seeds does not change the deployment command.
    """
    value = Path(value).expanduser().resolve()
    if value.suffix == ".json":
        selected = json.loads(value.read_text(encoding="utf-8"))
        value = Path(selected["weights"]).expanduser().resolve()
    if not value.is_file():
        raise FileNotFoundError(f"weights not found: {value}")
    return value


def select_best(detections: Sequence[Detection], class_id: int) -> Detection | None:
    """The most confident detection of that class, or `None`.

    Kept a pure function because it is the one decision here that can be
    tested; folded into the output parsing, none of it runs without a GPU.
    """
    candidates = [item for item in detections if item.class_id == class_id]
    if not candidates:
        return None
    return max(candidates, key=lambda item: item.confidence)


def detections_from_result(result: Any, mask_threshold: float = 0.5) -> list[Detection]:
    """Convert one ultralytics result object into a list of `Detection`.

    A result with no masks gives an empty list, never `None`, so a caller
    cannot confuse "nothing was detected" with "inference failed" -- a failure
    arrives as an exception.
    """
    masks = getattr(result, "masks", None)
    if masks is None or not len(masks.data):
        return []
    boxes = result.boxes
    classes = boxes.cls.detach().cpu().numpy().astype(int)
    scores = boxes.conf.detach().cpu().numpy()
    raw_ids = getattr(boxes, "id", None)
    ids = None if raw_ids is None else raw_ids.detach().cpu().numpy().astype(int)
    return [
        Detection(
            class_id=int(classes[index]),
            confidence=float(scores[index]),
            mask=masks.data[index].detach().cpu().numpy() > mask_threshold,
            track_id="" if ids is None else str(int(ids[index])),
        )
        for index in range(len(classes))
    ]


class Detector:
    """Load one set of weights and detect on each frame."""

    def __init__(self, weights: Path, config: DetectorConfig) -> None:
        self.weights = resolve_weights(weights)
        self.config = config
        self._model: Any = None
        self._device: Any = None

    def load(self) -> Any:
        """Prepare the model and device; reuse them if already prepared."""
        if self._model is not None:
            return self._device
        from ultralytics import YOLOE

        from vision_ai.utils.device import resolve_device

        self._device = resolve_device(self.config.device)
        self._model = YOLOE(str(self.weights))
        return self._device

    def detect(self, frame: Any) -> list[Detection]:
        device = self.load()
        options = dict(
            conf=self.config.confidence,
            imgsz=self.config.image_size,
            device=device.resolved,
            verbose=False,
        )
        if self.config.tracking:
            # Without persist=True the tracker restarts each frame and
            # renumbers, so a track_id would exist but mean nothing across
            # frames.
            result = self._model.track(frame, persist=True, **options)[0]
        else:
            result = self._model.predict(frame, **options)[0]
        return detections_from_result(result)

    def detect_person(self, frame: Any) -> Detection | None:
        return select_best(self.detect(frame), self.config.person_class_id)
