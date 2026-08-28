from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ClassifierConfig:
    """person mask 위에 붙는 fallen/not-fallen 분류기 학습 설정.

    worker-fall-detection/pipeline/run_config.py의 TrainingConfig와 같은 패턴
    (frozen dataclass + __post_init__ 검증 + to_dict/from_dict)을 따름 -- 나중에
    팀 저장소로 옮길 때 그대로 맞춰 넣을 수 있게.
    """

    seg_weights: Path
    roboflow_export: Path
    run_root: Path
    name: str | None = None
    use_geometric_features: bool = True
    use_prompt_features: bool = True
    # 사람-사람/사람-장애물 접촉(mask 겹침 IoU) 피처. "기대는 낙상"처럼 aspect_ratio가
    # 안 변하는 케이스를 잡기 위해 2026-08-24 추가.
    use_contact_features: bool = True
    prompt_classes: tuple[str, ...] = ("standing person", "fallen person")
    # 클래스별 프롬프트 앙상블 -- {class_name: (문구1, 문구2, ...)}. 클래스가 여기 없으면
    # prompt_classes의 이름 자체를 문구 1개로 씀(기존 동작과 동일, 하위호환).
    # 여러 문구의 텍스트 임베딩을 평균 내는 CLIP zero-shot 앙상블 관행을 따름.
    prompt_phrasings: dict[str, tuple[str, ...]] | None = None
    model_type: str = "logreg"  # "logreg" 또는 "mlp"
    seed: int = 42
    deterministic: bool = True
    # threshold 선택용 k-fold(train+valid 풀에서만 돎, test는 절대 안 씀).
    n_folds: int = 5
    test_size: float = 0.2
    imgsz: int = 640
    device: str = "auto"
    min_recall: float = 0.85
    min_precision: float = 0.80

    def __post_init__(self) -> None:
        object.__setattr__(self, "seg_weights", Path(self.seg_weights).expanduser().resolve())
        object.__setattr__(self, "roboflow_export", Path(self.roboflow_export).expanduser().resolve())
        object.__setattr__(self, "run_root", Path(self.run_root).expanduser().resolve())
        if not self.use_geometric_features and not self.use_prompt_features and not self.use_contact_features:
            raise ValueError("피처 세 종류가 전부 False면 입력 피처가 없습니다")
        if self.model_type not in ("logreg", "mlp"):
            raise ValueError(f"model_type은 logreg 또는 mlp여야 합니다: {self.model_type}")
        if not 0.0 < self.test_size < 1.0:
            raise ValueError("test_size는 0..1 사이여야 합니다")
        for field_name in ("min_recall", "min_precision"):
            value = getattr(self, field_name)
            if value < 0 or value > 1:
                raise ValueError(f"{field_name}는 0..1 범위여야 합니다")

    def to_dict(self) -> dict[str, Any]:
        values = asdict(self)
        for key in ("seg_weights", "roboflow_export", "run_root"):
            values[key] = str(values[key])
        values["prompt_classes"] = list(values["prompt_classes"])
        if values["prompt_phrasings"] is not None:
            values["prompt_phrasings"] = {k: list(v) for k, v in values["prompt_phrasings"].items()}
        return values

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> "ClassifierConfig":
        allowed = cls.__dataclass_fields__.keys()
        filtered = {key: value for key, value in values.items() if key in allowed}
        if "prompt_classes" in filtered:
            filtered["prompt_classes"] = tuple(filtered["prompt_classes"])
        if filtered.get("prompt_phrasings") is not None:
            filtered["prompt_phrasings"] = {k: tuple(v) for k, v in filtered["prompt_phrasings"].items()}
        return cls(**filtered)
