"""person mask 위에 붙는 fallen/not-fallen 분류기 학습.

입력 피처 두 종류를 합쳐서 씀 (ClassifierConfig.use_geometric_features /
use_prompt_features로 각각 켜고 끌 수 있음):
  1. 기하학적 피처 -- mask polygon에서 aspect_ratio, PCA 주축 각도
     (worker-fall-detection/docs의 lego_worker_fall_detection_plan.md §5~6과 동일한
     정의: width/height, PCA orientation_angle)
  2. YOLOE 프롬프트 피처 -- 같은 YOLOE segmentation 모델에 "person"/"fallen person"
     프롬프트를 같이 줘서 나오는 클래스별 confidence 차이(추가 모델 호출 없음,
     세그멘테이션 추론 1번으로 같이 나옴)

분류기 자체는 가벼운 sklearn LogisticRegression(기본) 또는 작은 MLP -- 데이터가
아직 적어서(라벨링 초기 단계) 무거운 모델은 과적합 위험이 큼.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import numpy as np

from dataloader.roboflow_labels import LabelRecord, load_roboflow_export, summarize
from pipeline.reproducibility import seed_everything
from pipeline.run_config import ClassifierConfig


def mixed_augmentation(image, **kwargs):
    """aug_best.pt 체크포인트 unpickle 호환용 더미.

    aug_best.pt는 원 학습 스크립트(model/perception/segmentation/train.py)를
    `python train.py`로 직접 실행해서 만들어졌고, 그 스크립트의 __main__ 네임스페이스에
    있던 mixed_augmentation(S1~S5 augmentation Lambda)이 체크포인트에 pickle로
    같이 저장돼 있다. 다른 진입점(cli.py/video_monitor.py 등)에서 torch.load로 읽으면
    unpickler가 그 이름을 그 진입점의 __main__에서 찾다가 AttributeError가 난다.
    추론(피처 추출)에서는 이 콜백이 실제로 호출되지 않으므로, 항등함수로 대체해서
    이름만 있으면 unpickle이 통과하게 함. YOLOE(...)를 로드하는 모든 진입점에서
    `from trainer.classifier_trainer import ...`를 거치므로 여기 한 곳에서 등록.
    """
    return image


sys.modules["__main__"].mixed_augmentation = mixed_augmentation

# 일부 체크포인트(예: multi-seed 학습 파이프라인이 만든 best.pt)는 __main__이 아니라
# 특정 모듈 경로("trihouse_segmentation_train")로 mixed_augmentation을 pickle에 박아둔
# 경우가 있음(어떤 스크립트/셸로 학습을 돌렸는지에 따라 다름). 그 이름의 가짜 모듈을
# 미리 등록해서 어느 경로로 찍혀 있어도 unpickle이 통과하게 함.
if "trihouse_segmentation_train" not in sys.modules:
    _compat_stub = types.ModuleType("trihouse_segmentation_train")
    _compat_stub.mixed_augmentation = mixed_augmentation
    sys.modules["trihouse_segmentation_train"] = _compat_stub


def resolve_device(device: str) -> str:
    """"auto"/"0"/"cpu"/"cuda:0" 등을 torch.Tensor.to()가 받는 형태로 정규화.
    ultralytics는 predict()/train()에 넘기는 bare 인덱스("0")를 알아서 처리하지만,
    여기서는 torch.nn.Module.to()를 직접 부르므로 "cuda:0" 형태가 필요함."""
    import torch
    if device == "auto":
        return "cuda:0" if torch.cuda.is_available() else "cpu"
    if device == "cpu" or device.startswith("cuda"):
        return device
    return f"cuda:{device}"

# 클래스당 여러 자연스러운 문구를 준비해서 텍스트 임베딩을 평균 -- CLIP zero-shot
# 분류에서 흔히 쓰는 prompt ensembling 관행(단일 label보다 caption 스타일 문구
# 여러 개 평균이 더 안정적). "person"만 쓰면 서 있든 누워있든 다 걸려서 대비가
# 약하므로, standing/fallen이 구조는 같고 자세 단어만 다르게 대비되도록 함.
DEFAULT_PROMPT_PHRASINGS: dict[str, tuple[str, ...]] = {
    "standing person": ("standing person", "person standing upright", "person walking"),
    "fallen person": ("fallen person", "person lying on the ground", "collapsed person"),
}


def polygon_to_geometric_features(polygon: list[tuple[float, float]]) -> np.ndarray:
    """(aspect_ratio, pca_orientation_angle_deg, centroid_y) -- 앞의 둘은
    lego_worker_fall_detection_plan.md §5.1/§6과 같은 정의. polygon은 0..1 정규화 좌표.

    centroid_y(mask 중심의 세로 위치, 0=위/1=아래)는 2026-08-24에 추가함 -- "모양이
    어떻게 생겼나"인 aspect_ratio/각도와 달리 "화면 어디에 있나"라는 다른 축의 정보라
    중복 위험이 적음(elongation은 aspect_ratio랑 사실상 같은 정보라 효과 없었음, 반면
    이건 독립적). 쓰러지면 mask 중심이 바닥 쪽(아래)으로 가는 경향을 이용.
    """
    pts = np.asarray(polygon, dtype=np.float64)
    xs, ys = pts[:, 0], pts[:, 1]
    width, height = xs.max() - xs.min(), ys.max() - ys.min()
    aspect_ratio = width / max(height, 1e-6)
    centroid_y = float(ys.mean())

    centered = pts - pts.mean(axis=0)
    cov = np.cov(centered.T)
    eigvals, eigvecs = np.linalg.eigh(cov)  # 오름차순 정렬됨
    principal = eigvecs[:, np.argmax(eigvals)]
    angle_deg = float(np.degrees(np.arctan2(principal[1], principal[0])) % 180.0)

    return np.array([aspect_ratio, angle_deg, centroid_y], dtype=np.float32)


class PromptFeatureExtractor:
    """YOLOE에 prompt_classes(예: standing person / fallen person)를 같이 넣어서 얻는
    클래스별 confidence를 피처로 반환. 세그멘테이션 추론 1회로 같이 나옴 --
    별도 모델 추가 호출 아님(B 아이디어를 A의 입력 피처로 흡수).

    학습(정지 이미지 + GT polygon)과 실시간 추론(영상 프레임 + 모델이 직접 찾은
    person box) 양쪽에서 재사용함 -- extract()의 target_polygon은 GT여도 되고
    모델 자신의 person 검출 polygon이어도 됨, IoU 매칭 로직은 동일."""

    def __init__(
        self, weights: Path, prompt_classes: tuple[str, ...], device: str,
        phrasings: dict[str, tuple[str, ...]] | None = None,
    ):
        from ultralytics import YOLOE
        self.model = YOLOE(str(weights))
        self.model.to(resolve_device(device))
        self.prompt_classes = list(prompt_classes)
        phrasings = phrasings or {}
        # 클래스마다 문구 여러 개(없으면 클래스 이름 자체 1개)의 텍스트 임베딩을 평균.
        # get_text_pe(texts)는 (1, len(texts), dim)을 반환(배치 차원 포함) --
        # 문구 차원(dim=1)으로 평균 내고, 클래스들은 그 dim=1을 따라 이어붙여야
        # set_classes가 기대하는 (1, num_classes, dim) 형태가 됨.
        class_embeddings = []
        for name in self.prompt_classes:
            variants = list(phrasings.get(name, (name,)))
            variant_pe = self.model.get_text_pe(variants)  # (1, len(variants), dim)
            class_embeddings.append(variant_pe.mean(dim=1, keepdim=True))  # (1, 1, dim)
        import torch
        self.model.set_classes(self.prompt_classes, torch.cat(class_embeddings, dim=1))

    def extract(self, image, target_polygon: list[tuple[float, float]]) -> np.ndarray:
        """target_polygon(정답 또는 모델이 찾은 person instance)과 IoU가 가장 큰 예측
        detection을 골라 그 detection의 클래스별 confidence를 반환. image는 파일
        경로(Path/str) 또는 이미 읽어들인 프레임(np.ndarray, BGR/RGB 모두 ultralytics가
        처리) 둘 다 받음. 매칭되는 detection이 없으면 0벡터."""
        source = str(image) if isinstance(image, Path) else image
        result = self.model.predict(source, imgsz=640, verbose=False)[0]
        target = np.asarray(target_polygon, dtype=np.float64)
        target_box = (target[:, 0].min(), target[:, 1].min(), target[:, 0].max(), target[:, 1].max())

        best_iou, best_idx = 0.0, None
        if result.boxes is not None:
            h, w = result.orig_shape
            for i, box in enumerate(result.boxes.xyxyn.cpu().numpy()):
                iou = _box_iou(target_box, tuple(box))
                if iou > best_iou:
                    best_iou, best_idx = iou, i

        scores = np.zeros(len(self.prompt_classes), dtype=np.float32)
        if best_idx is not None:
            cls_id = int(result.boxes.cls[best_idx].item())
            conf = float(result.boxes.conf[best_idx].item())
            if cls_id < len(scores):
                scores[cls_id] = conf
        return scores


def _box_iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    area_a = max(0.0, ax1 - ax0) * max(0.0, ay1 - ay0)
    area_b = max(0.0, bx1 - bx0) * max(0.0, by1 - by0)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _polygon_bbox(polygon: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    pts = np.asarray(polygon, dtype=np.float64)
    return float(pts[:, 0].min()), float(pts[:, 1].min()), float(pts[:, 0].max()), float(pts[:, 1].max())


def contact_features(
    target_polygon: list[tuple[float, float]],
    other_instances: list[tuple[str, list[tuple[float, float]]]],
) -> np.ndarray:
    """(사람-사람 최대 접촉 IoU, 사람-장애물 최대 접촉 IoU) -- "기대는 낙상"처럼
    aspect_ratio가 거의 안 변하는 케이스를 잡기 위한 신호(2026-08-24 추가).
    171307("기대는 낙상") 실측: 기대기 전 IoU=0.000 -> 기댄 뒤 0.05~0.13대로 꾸준히
    상승, GT 타임라인과 정확히 일치했음(aspect_ratio는 이 구간에서 거의 무신호였음).
    사람-사람과 사람-장애물을 분리하는 이유는 신뢰도가 다를 것으로 판단해서
    (사용자 판단, 사람-사람이 더 확실한 신호) -- 분류기가 각각 다른 가중치를 배우게 함.
    자기 자신과 거의 같은 polygon(IoU>=0.95)은 자기 자신으로 보고 제외."""
    from dataloader.roboflow_labels import FALLEN_CLASS_NAMES, NOT_FALLEN_CLASS_NAMES

    target_box = _polygon_bbox(target_polygon)
    person_max, obstacle_max = 0.0, 0.0
    for name, polygon in other_instances:
        other_box = _polygon_bbox(polygon)
        iou = _box_iou(target_box, other_box)
        if iou >= 0.95:
            continue  # 자기 자신으로 판단, 제외
        lowered = name.strip().lower()
        is_person_type = lowered in NOT_FALLEN_CLASS_NAMES or lowered in FALLEN_CLASS_NAMES or "fallen" in lowered
        if is_person_type:
            person_max = max(person_max, iou)
        else:
            obstacle_max = max(obstacle_max, iou)
    return np.array([person_max, obstacle_max], dtype=np.float32)


def contact_from_predictions(
    target_box: tuple[float, float, float, float], result, exclude_idx: int, person_class_id: int,
) -> np.ndarray:
    """contact_features()의 추론(예측 detection 기반) 버전 -- GT가 없는 실전에서
    모델이 실제로 찾아낸 다른 detection들과의 (사람-사람, 사람-장애물) 최대 접촉 IoU를
    잰다. `retrain_on_predicted_masks.py`/`eval_end_to_end.py`/`video_monitor.py`가
    공유해서 씀."""
    person_max, obstacle_max = 0.0, 0.0
    if result.boxes is not None:
        for i, cls_id in enumerate(result.boxes.cls.cpu().numpy()):
            if i == exclude_idx:
                continue
            box = tuple(result.boxes.xyxyn[i].cpu().numpy().tolist())
            iou = _box_iou(target_box, box)
            if int(cls_id) == person_class_id:
                person_max = max(person_max, iou)
            else:
                obstacle_max = max(obstacle_max, iou)
    return np.array([person_max, obstacle_max], dtype=np.float32)


def build_feature_matrix(
    records: list[LabelRecord], config: ClassifierConfig, prompt_extractor: PromptFeatureExtractor | None,
    instances_by_image: dict[Path, list[tuple[str, list[tuple[float, float]]]]] | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    feature_rows, labels = [], []
    for record in records:
        parts = []
        if config.use_geometric_features:
            parts.append(polygon_to_geometric_features(record.polygon))
        if config.use_prompt_features:
            assert prompt_extractor is not None
            parts.append(prompt_extractor.extract(record.image_path, record.polygon))
        if config.use_contact_features:
            assert instances_by_image is not None
            others = instances_by_image.get(record.image_path, [])
            parts.append(contact_features(record.polygon, others))
        feature_rows.append(np.concatenate(parts))
        labels.append(1 if record.is_fallen else 0)
    return np.stack(feature_rows), np.array(labels, dtype=np.int64)


def _select_threshold(y_true: np.ndarray, y_proba: np.ndarray, min_recall: float) -> tuple[float, dict]:
    """recall>=min_recall인 threshold 중 precision이 제일 높은 걸 고름 -- recall 우선
    정책([[project_fallen_detection_options_and_progress]] 근거: 오탐은 사람이 한 번 더
    확인하는 비용, 미탐은 실제 낙상을 놓치는 비용이라 recall을 우선함). min_recall을
    만족하는 threshold가 하나도 없으면 recall이 제일 높은 threshold로 대체하고
    호출부에서 gate_passed=False로 표시하게 함."""
    from sklearn.metrics import precision_score, recall_score

    candidates = np.linspace(0.05, 0.95, 19)
    rows = []
    for t in candidates:
        pred = (y_proba >= t).astype(int)
        rows.append({
            "threshold": float(t),
            "precision": float(precision_score(y_true, pred, zero_division=0)),
            "recall": float(recall_score(y_true, pred, zero_division=0)),
        })
    passing = [r for r in rows if r["recall"] >= min_recall]
    best = max(passing, key=lambda r: r["precision"]) if passing else max(rows, key=lambda r: r["recall"])
    return best["threshold"], best


def train(config: ClassifierConfig) -> Path:
    seed_everything(config.seed, config.deterministic)
    run_dir = config.run_root / (config.name or "run")
    run_dir.mkdir(parents=True, exist_ok=True)

    records = load_roboflow_export(config.roboflow_export)
    if not records:
        raise ValueError(f"라벨 레코드가 없습니다: {config.roboflow_export}")
    (run_dir / "dataset_summary.json").write_text(
        json.dumps(summarize(records), ensure_ascii=False, indent=2), encoding="utf-8"
    )

    prompt_extractor = None
    if config.use_prompt_features:
        phrasings = config.prompt_phrasings if config.prompt_phrasings is not None else DEFAULT_PROMPT_PHRASINGS
        prompt_extractor = PromptFeatureExtractor(config.seg_weights, config.prompt_classes, config.device, phrasings)

    instances_by_image = None
    if config.use_contact_features:
        from dataloader.roboflow_labels import load_all_instances_by_image
        instances_by_image = load_all_instances_by_image(config.roboflow_export)

    # threshold는 train+valid를 합친 "브로드한" 풀에서 k-fold cross-validation으로만
    # 고른다 -- test는 여기서 절대 안 봄(안 그러면 test에 맞춰 기준을 끼워맞추는 게 됨).
    # valid 단독(fallen instance 수십 개)은 표본이 작아 불안정하므로 train+valid를
    # 합쳐 더 많은 fallen instance로 재는 게 목적.
    train_records = [r for r in records if r.split == "train"]
    valid_records = [r for r in records if r.split == "valid"]
    test_records = [r for r in records if r.split == "test"]
    cv_pool_records = train_records + valid_records
    if not cv_pool_records:
        raise ValueError("train+valid 레코드가 없습니다")

    x_pool, y_pool = build_feature_matrix(cv_pool_records, config, prompt_extractor, instances_by_image)
    x_test, y_test = (
        build_feature_matrix(test_records, config, prompt_extractor, instances_by_image)
        if test_records else (None, None)
    )

    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import precision_score, recall_score
    from sklearn.model_selection import StratifiedKFold
    from sklearn.neural_network import MLPClassifier
    from sklearn.preprocessing import StandardScaler

    def make_clf():
        if config.model_type == "logreg":
            return LogisticRegression(max_iter=1000, random_state=config.seed, class_weight="balanced")
        return MLPClassifier(hidden_layer_sizes=(16,), max_iter=2000, random_state=config.seed)

    n_fallen_pool = int(y_pool.sum())
    n_splits = max(2, min(config.n_folds, n_fallen_pool, len(y_pool) - n_fallen_pool))
    skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=config.seed)
    oof_proba = np.zeros(len(y_pool))
    for fold_train_idx, fold_val_idx in skf.split(x_pool, y_pool):
        fold_scaler = StandardScaler().fit(x_pool[fold_train_idx])
        fold_clf = make_clf()
        fold_clf.fit(fold_scaler.transform(x_pool[fold_train_idx]), y_pool[fold_train_idx])
        oof_proba[fold_val_idx] = fold_clf.predict_proba(fold_scaler.transform(x_pool[fold_val_idx]))[:, 1]
    threshold, threshold_report = _select_threshold(y_pool, oof_proba, config.min_recall)

    # 최종 모델은 train+valid 전체로 재학습(k-fold는 threshold 선택 전용, 최종 fit이
    # 데이터를 제일 많이 써야 함).
    scaler = StandardScaler().fit(x_pool)
    clf = make_clf()
    clf.fit(scaler.transform(x_pool), y_pool)

    cv_metrics = {
        "n_folds": n_splits, "threshold": threshold,
        "precision_at_threshold": threshold_report["precision"],
        "recall_at_threshold": threshold_report["recall"],
        "n_pool": len(y_pool), "n_fallen_pool": n_fallen_pool,
    }

    test_metrics = None
    if x_test is not None and len(y_test):
        y_test_proba = clf.predict_proba(scaler.transform(x_test))[:, 1]
        y_test_pred = (y_test_proba >= threshold).astype(int)
        test_metrics = {
            "precision": float(precision_score(y_test, y_test_pred, zero_division=0)),
            "recall": float(recall_score(y_test, y_test_pred, zero_division=0)),
            "n_test": len(y_test), "n_fallen_test": int(y_test.sum()),
        }

    metrics = {"cv": cv_metrics, "test": test_metrics}
    (run_dir / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")

    import joblib
    weights_path = run_dir / "fallen_classifier.joblib"
    joblib.dump(
        {"scaler": scaler, "clf": clf, "threshold": threshold, "config": config.to_dict()}, weights_path
    )

    gate_passed = bool(
        test_metrics is not None
        and test_metrics["recall"] >= config.min_recall
        and test_metrics["precision"] >= config.min_precision
    )
    (run_dir / "status.json").write_text(json.dumps({
        "gate_passed": gate_passed, "metrics": metrics, "threshold": threshold, "weights": str(weights_path),
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        f"[CV] {n_splits}-fold, train+valid {len(y_pool)}개(fallen {n_fallen_pool}개) -> "
        f"threshold={threshold:.2f} (CV precision={cv_metrics['precision_at_threshold']:.3f}, "
        f"recall={cv_metrics['recall_at_threshold']:.3f})"
    )
    if test_metrics:
        print(
            f"[TEST, 딱 한 번] precision={test_metrics['precision']:.3f} recall={test_metrics['recall']:.3f} "
            f"gate_passed={gate_passed} (min_recall={config.min_recall}, min_precision={config.min_precision})"
        )
    else:
        print("[경고] test 레코드가 없어 최종 평가를 못 함 -- gate_passed는 항상 False")
    return weights_path
