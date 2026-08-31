"""seed 하나로 학습·검증·test 를 돌린다. multi-seed 실험이 프로세스로 띄운다.

**모듈로 실행한다** — `python -m vision_ai.models.perception.trainer.seed_runner`.
스크립트 경로(`<project_dir>/train_seed.py`)로 부르면 실험이 자기 소스 위치를
알아야 하고, 그 경로는 폴더를 옮기는 순간 조용히 어긋난다. 모듈 이름은 설치
방식이 바뀌어도 같다.

seed 마다 프로세스를 새로 띄우는 이유는 재현성이다. `PYTHONHASHSEED` 는
인터프리터가 뜬 뒤에는 바꿀 수 없고, CUDA·cuDNN 의 전역 상태도 프로세스 안에
남는다. 같은 프로세스에서 seed 를 바꿔 가며 돌리면 앞 seed 가 뒤 seed 에
새어 든다.
"""

import argparse
import dataclasses
from pathlib import Path

from vision_ai.utils.config_loader import config_for_seed, load_experiment_config
from vision_ai.models.perception.trainer.orchestrator import run_pipeline
from vision_ai.models.perception.trainer.yoloe_trainer import YOLOEBackend


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run YOLOE train/validation/test for one seed")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--experiment-dir", type=Path, required=True)
    # 부모 실험이 --data 로 config 를 덮어썼다면 그 값이 여기까지 와야 한다.
    # 안 오면 자식은 config 파일의 경로로 조용히 학습한다.
    parser.add_argument("--data", type=Path)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    experiment = load_experiment_config(args.config, data_override=args.data)
    config = config_for_seed(experiment, args.seed)
    config = dataclasses.replace(config, run_root=args.experiment_dir.resolve())
    run_pipeline(config, YOLOEBackend())


if __name__ == "__main__":
    main()
