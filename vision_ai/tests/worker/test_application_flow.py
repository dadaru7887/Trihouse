from vision_ai.models.perception.trainer.pipeline import build_parser


def test_main_parser_exposes_ml_workflow_stages() -> None:
    parser = build_parser()
    assert parser.parse_args(["labels"]).stage == "labels"
    assert parser.parse_args(["train"]).stage == "train"
    assert parser.parse_args(["analyze", "--experiment-dir", "/tmp/run"]).stage == "analyze"

