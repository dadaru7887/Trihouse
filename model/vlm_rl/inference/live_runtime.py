"""5080 live loop: RTSP segmentation, stuck trigger, Qwen, policy, proposal."""

from __future__ import annotations

import os
from pathlib import Path
import json
import math
import time
from typing import Any, Sequence
from urllib import request

from model.perception.segmentation.runtime.detector import (
    Detector, DetectorConfig,
)
from model.worker.person.fall_monitor import MonitorConfig
from model.worker.person.frame import NO_DETECTION, PersonFrameEvaluator
from model.worker.person.posture import PostureConfig

from .completion_runtime import build_completion
from .distilled_selector import build_selector_from_env
from .navigation_context import GatewayNavigationContextSource
from .policy_runtime import ApprovedPolicyRuntime
from .proposal_client import GatewayProposalClient
from .vlm_interpreter import QwenVlmInterpreter
from .worker import DetectionEvidence, RecoveryInferenceWorker


class PersonSafetyReporter:
    """Send the worst person posture on this camera to the 4060 safety route.

    "Worst" rather than "most confident": a bystander standing in the foreground
    must not mask someone on the floor behind them. Per-person state lives in
    `PersonFrameEvaluator`, so one person recovering no longer clears another
    person's fall.
    """

    def __init__(self, gateway_url: str, camera_id: str, *, ttl_ms: int = 600,
                 person_class_id: int = 1):
        self.url = gateway_url.rstrip("/") + "/internal/v1/vision/person-detections"
        self.camera_id = camera_id
        self.ttl_ms = ttl_ms
        self.person_class_id = person_class_id
        self.evaluator = PersonFrameEvaluator(
            camera_id=camera_id,
            posture=PostureConfig(),
            monitor=MonitorConfig(fall_aspect_ratio=0.9),
        )
        self.last_report_at = 0.0
        self.last_state = ""

    def observe_frame(self, detections: Sequence[Any], frame_shape: tuple[int, ...],
                      now: float) -> None:
        verdict = self.evaluator.evaluate(
            detections, frame_shape, now, person_class_id=self.person_class_id
        )
        if verdict.state == NO_DETECTION:
            return
        state = verdict.state
        if state == self.last_state and now - self.last_report_at < self.ttl_ms / 2000.0:
            return
        payload = {
            "camera_id": self.camera_id,
            "confidence": verdict.confidence,
            "ttl_ms": self.ttl_ms,
            "observed_at_ms": int(time.time() * 1000),
            "pose_class": state,
        }
        if verdict.track_id:
            payload["track_id"] = verdict.track_id
        outgoing = request.Request(
            self.url,
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(outgoing, timeout=1.0) as response:
                response.read()
        except OSError:
            return
        self.last_state = state
        self.last_report_at = now


def detection_evidence(
    detections: Sequence[Any],
    frame_shape: tuple[int, ...],
    *,
    person_class_id: int,
) -> list[DetectionEvidence]:
    import numpy as np

    height, width = frame_shape[:2]
    evidence: list[DetectionEvidence] = []
    for index, detection in enumerate(detections):
        ys, xs = np.nonzero(detection.mask)
        if len(xs) == 0:
            continue
        bbox = (
            float(xs.min()) / width,
            float(ys.min()) / height,
            float(xs.max() + 1) / width,
            float(ys.max() + 1) / height,
        )
        evidence.append(DetectionEvidence(
            class_name="person" if detection.class_id == person_class_id else "obstacle",
            confidence=float(detection.confidence),
            bbox_xyxy_norm=bbox,
            track_id=f"frame-{index}",
        ))
    return evidence


def run_live_inference(*, safety_gate_enabled: bool) -> None:
    import cv2

    gateway_url = os.environ["FMS_GATEWAY_URL"]
    device_id = os.environ["RECOVERY_DEVICE_ID"]
    rtsp_url = os.environ["VISION_RTSP_URL"]
    person_class_id = int(os.environ.get("VISION_PERSON_CLASS_ID", "1"))
    detector = Detector(
        Path(os.environ["SEGMENTATION_WEIGHTS"]),
        DetectorConfig(
            confidence=float(os.environ.get("VISION_CONFIDENCE", "0.25")),
            image_size=int(os.environ.get("VISION_IMAGE_SIZE", "640")),
            device=os.environ.get("VISION_DEVICE", "cuda:0"),
            person_class_id=person_class_id,
            # 사람마다 상태를 따로 들려면 프레임을 넘는 신원이 있어야 한다.
            tracking=True,
        ),
    )
    vlm = QwenVlmInterpreter(os.environ.get("VLM_MODEL_REVISION", "main"))
    policy = ApprovedPolicyRuntime(
        Path(os.environ["RECOVERY_POLICY_CHECKPOINT"]),
        os.environ["RECOVERY_POLICY_SHA256"],
        device=os.environ.get("VLM_RL_DEVICE", "cuda"),
    )
    proposal_client = GatewayProposalClient(gateway_url)
    # Optional: absent selector environment keeps the pre-distillation ranking.
    skill_selector = build_selector_from_env(os.environ)
    worker = RecoveryInferenceWorker(
        vlm,
        policy,
        proposal_client,
        safety_gate_enabled=safety_gate_enabled,
        skill_selector=skill_selector,
    )
    context_source = GatewayNavigationContextSource(gateway_url, device_id)
    camera_id = rtsp_url.rstrip("/").rsplit("/", 1)[-1]
    person_reporter = PersonSafetyReporter(
        gateway_url, camera_id, person_class_id=person_class_id
    )
    capture = cv2.VideoCapture(rtsp_url)
    if not capture.isOpened():
        raise RuntimeError("5080 could not open the configured 4060 MediaMTX stream")
    inference_interval = 1.0 / float(os.environ.get("VISION_INFERENCE_FPS", "15"))
    proposal_cooldown = float(os.environ.get("VLM_PROPOSAL_COOLDOWN_SECONDS", "8"))
    pending_proposal: dict[str, Any] | None = None
    last_proposal_at = 0.0
    last_detection_count = -1
    last_open_lookup_at = 0.0
    try:
        while True:
            started = time.monotonic()
            ok, frame = capture.read()
            if not ok:
                raise RuntimeError("5080 MediaMTX stream stopped producing frames")
            raw_detections = detector.detect(frame)
            detections = detection_evidence(
                raw_detections, frame.shape, person_class_id=person_class_id
            )
            person_reporter.observe_frame(raw_detections, frame.shape, time.monotonic())
            try:
                context = context_source.get()
            except Exception:
                context = None
            if context is not None:
                if pending_proposal is not None:
                    execution_state = proposal_client.execution(pending_proposal["proposal_id"])
                    execution = execution_state.get("result")
                    if execution is not None:
                        next_state = worker.observe_state(frame, detections, context)
                        completion = build_completion(pending_proposal, execution, next_state)
                        proposal_client.complete(
                            pending_proposal, completion, execution["command_id"]
                        )
                        pending_proposal = None
                    elif execution_state["status"] in {"rejected", "failed", "expired"}:
                        pending_proposal = None
                else:
                    if time.monotonic() - last_open_lookup_at >= 1.0:
                        open_items = proposal_client.open_recoveries(device_id)
                        last_open_lookup_at = time.monotonic()
                        if open_items:
                            pending_proposal = open_items[0]["proposal"]
                            continue
                    # EN: Preserve the original 8-second same-scene anti-spam behavior.
                    # KO: 원본의 동일 장면 8초 재호출 방지 동작을 유지한다.
                    same_scene_cooldown = (
                        time.monotonic() - last_proposal_at < proposal_cooldown
                        and len(detections) == last_detection_count
                    )
                    if not same_scene_cooldown:
                        created = worker.process(frame, detections, context)
                        if created is not None:
                            pending_proposal = created["_local_proposal"]
                            last_proposal_at = time.monotonic()
                            last_detection_count = len(detections)
            remaining = inference_interval - (time.monotonic() - started)
            if remaining > 0:
                time.sleep(remaining)
    finally:
        capture.release()
