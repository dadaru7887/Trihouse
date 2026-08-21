"""Backward-compatible imports for the trainer implementation."""

from model.perception.segmentation.training.trainer.yoloe_trainer import YOLOEBackend, confusion_metrics, normalize_metrics, resolve_model

__all__ = ["YOLOEBackend", "confusion_metrics", "normalize_metrics", "resolve_model"]
