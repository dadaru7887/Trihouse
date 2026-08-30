"""1단계 — 프레임 한 장에서 사람/장애물을 검출한다.

`model_registry` 가 고른 weight 를 싣고, 프레임을 받아 `Detection` 목록을 낸다.
**자세는 여기서 판단하지 않는다.** 자세는 `person_worker/posture.py` 가 mask 를
받아 재고, 낙상 여부는 `person_worker/policy.py` 가 시간축으로 정한다. 셋을 나눈
이유는 `docs` 가 아니라 비용에 있다 — 검출은 매 프레임 돌아야 하고(로봇 안전
gate 가 이 결과로 감속한다), 자세 판정은 사람이 잡혔을 때만 돌면 된다.

무거운 import(`ultralytics`, `torch`)는 `load()` 안에서만 한다. 그래야 GPU 가 없는
곳에서도 이 모듈을 읽고 시험할 수 있다.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence
import json


@dataclass(frozen=True)
class DetectorConfig:
    """`configs/realtime.yaml` 의 `inference` 절과 같은 모양."""

    confidence: float = 0.25
    image_size: int = 640
    device: str = "auto"
    # `data.yaml` 의 `names: ['obstacle', 'person']` 에서 온다. 클래스 순서가
    # 바뀌면 이 값도 바뀌므로 코드에 숫자를 박지 않고 설정으로 받는다.
    person_class_id: int = 1
    # 켜면 `predict` 대신 `track(persist=True)` 로 돌려 프레임을 넘는 track_id 를
    # 받는다. 사람별로 상태를 따로 들고 있으려면 이 신원이 있어야 한다. 기본이
    # 꺼짐인 이유는 tracker 가 매 프레임 비용과 상태를 더하기 때문이다 — 사람
    # 하나만 보는 호출부는 그 값을 치를 이유가 없다.
    tracking: bool = False

    def __post_init__(self) -> None:
        if not 0.0 < self.confidence <= 1.0:
            raise ValueError("confidence 는 0 초과 1 이하여야 합니다")
        if self.image_size <= 0:
            raise ValueError("image_size 는 양수여야 합니다")
        if self.person_class_id < 0:
            raise ValueError("person_class_id 는 0 이상이어야 합니다")


@dataclass(frozen=True)
class Detection:
    """한 인스턴스의 검출 결과. `mask` 는 프레임 크기의 bool 배열이다.

    `track_id` 는 tracking 을 켰을 때만 채워진다. 빈 문자열은 "이 프레임의
    검출일 뿐 프레임을 넘는 신원은 없다" 는 뜻이다 — 사람별 상태를 들고 있는
    쪽이 그 차이를 알아야 한다.
    """

    class_id: int
    confidence: float
    mask: Any
    track_id: str = ""


def resolve_weights(value: Path) -> Path:
    """`best.pt` 를 직접 받거나 `selected_model.json` 을 거쳐 찾는다.

    multi-seed 실험은 대표 모델을 `selected_model.json` 으로 남긴다. 배포 쪽이
    그 파일을 그대로 가리킬 수 있어야 seed 를 바꿔 학습해도 배포 명령이 안 바뀐다.
    """
    value = Path(value).expanduser().resolve()
    if value.suffix == ".json":
        selected = json.loads(value.read_text(encoding="utf-8"))
        value = Path(selected["weights"]).expanduser().resolve()
    if not value.is_file():
        raise FileNotFoundError(f"weight 가 없습니다: {value}")
    return value


def select_best(detections: Sequence[Detection], class_id: int) -> Detection | None:
    """그 클래스에서 가장 확신이 높은 하나. 없으면 `None`.

    순수 함수로 떼어 둔 이유는 이것이 시험 가능한 유일한 판단이기 때문이다.
    모델 출력 파싱과 붙여 두면 GPU 없이는 한 줄도 확인할 수 없다.
    """
    candidates = [item for item in detections if item.class_id == class_id]
    if not candidates:
        return None
    return max(candidates, key=lambda item: item.confidence)


def detections_from_result(result: Any, mask_threshold: float = 0.5) -> list[Detection]:
    """ultralytics 결과 객체 하나를 `Detection` 목록으로 옮긴다.

    mask 가 없는 결과(검출 0건)는 빈 목록이다. `None` 을 돌려주지 않는 이유는
    호출부가 "검출이 없다" 와 "추론이 실패했다" 를 섞지 않게 하기 위해서다 —
    추론 실패는 예외로 올라온다.
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
    """weight 하나를 싣고 프레임마다 검출을 낸다."""

    def __init__(self, weights: Path, config: DetectorConfig) -> None:
        self.weights = resolve_weights(weights)
        self.config = config
        self._model: Any = None
        self._device: Any = None

    def load(self) -> Any:
        """모델과 device 를 준비한다. 이미 준비됐으면 그대로 쓴다."""
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
            # persist=True 가 없으면 tracker 가 프레임마다 새로 시작해 번호를
            # 다시 매긴다 — track_id 가 있어도 프레임을 넘는 신원이 아니게 된다.
            result = self._model.track(frame, persist=True, **options)[0]
        else:
            result = self._model.predict(frame, **options)[0]
        return detections_from_result(result)

    def detect_person(self, frame: Any) -> Detection | None:
        return select_best(self.detect(frame), self.config.person_class_id)
