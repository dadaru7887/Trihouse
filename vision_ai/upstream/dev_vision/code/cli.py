"""fallen 분류기 학습 CLI.

worker-fall-detection/pipeline/cli.py와 같은 argparse 패턴(플랫하게 인자 나열 후
config_from_args로 dataclass 변환)을 따름.

사용 예:
    python -m pipeline.cli \\
        --seg-weights ~/Trihouse_segmentation/weights/aug_best.pt \\
        --roboflow-export ~/Trihouse_segmentation/fallen_roboflow_export \\
        --run-root runs/fallen_classifier --seed 42
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.run_config import ClassifierConfig  # noqa: E402
from trainer.classifier_trainer import train  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="fallen person 분류기 학습")
    parser.add_argument("--seg-weights", type=Path, required=True, help="기존 YOLOE segmentation 가중치(예: aug_best.pt)")
    parser.add_argument("--roboflow-export", type=Path, required=True, help="Roboflow YOLOv8-seg export 루트")
    parser.add_argument("--run-root", type=Path, default=Path("runs/fallen_classifier"))
    parser.add_argument("--name")
    parser.add_argument("--no-geometric", action="store_true", help="기하학적 피처(비율/방향) 끄기")
    parser.add_argument("--no-prompt", action="store_true", help="YOLOE 프롬프트 피처(fallen person) 끄기")
    parser.add_argument(
        "--no-contact", action="store_true",
        help="사람-사람/사람-장애물 접촉(mask 겹침 IoU) 피처 끄기(기본 켜짐)",
    )
    parser.add_argument("--prompt-classes", nargs="+", default=["standing person", "fallen person"])
    parser.add_argument(
        "--prompt-phrasings", type=Path,
        help="클래스별 프롬프트 앙상블 JSON({class_name: [문구, ...]}). 생략하면 "
             "trainer.classifier_trainer.DEFAULT_PROMPT_PHRASINGS 사용",
    )
    parser.add_argument("--model-type", choices=("logreg", "mlp"), default="logreg")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--n-folds", type=int, default=5, help="threshold 선택용 k-fold 수(train+valid 풀)")
    parser.add_argument("--test-size", type=float, default=0.2)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--min-recall", type=float, default=0.85)
    parser.add_argument("--min-precision", type=float, default=0.80)
    return parser


def config_from_args(args: argparse.Namespace) -> ClassifierConfig:
    prompt_phrasings = None
    if args.prompt_phrasings is not None:
        prompt_phrasings = {
            k: tuple(v) for k, v in json.loads(args.prompt_phrasings.read_text(encoding="utf-8")).items()
        }
    return ClassifierConfig(
        seg_weights=args.seg_weights,
        roboflow_export=args.roboflow_export,
        run_root=args.run_root,
        name=args.name,
        use_geometric_features=not args.no_geometric,
        use_prompt_features=not args.no_prompt,
        use_contact_features=not args.no_contact,
        prompt_classes=tuple(args.prompt_classes),
        prompt_phrasings=prompt_phrasings,
        model_type=args.model_type,
        seed=args.seed,
        n_folds=args.n_folds,
        test_size=args.test_size,
        device=args.device,
        min_recall=args.min_recall,
        min_precision=args.min_precision,
    )


def main() -> None:
    args = build_parser().parse_args()
    config = config_from_args(args)
    print(json.dumps(config.to_dict(), ensure_ascii=False, indent=2))
    weights_path = train(config)
    print(f"저장됨: {weights_path}")


if __name__ == "__main__":
    main()
