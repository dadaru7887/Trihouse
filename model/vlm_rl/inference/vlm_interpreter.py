"""Qwen2.5-VL 7B 4-bit interpreter preserving the dev_driving JSON contract."""

from __future__ import annotations

import json
import re
from typing import Any, Sequence

from .worker import DetectionEvidence


MODEL_ID = "Qwen/Qwen2.5-VL-7B-Instruct"
CONTRACT_PROMPT_TEMPLATE = """Goal: {goal}

Detected by onboard segmentation model (System1):
{detections_text}

Respond with ONLY a JSON object (no other text) matching this exact schema:
{{
  "observations": [
    {{
      "region_id": "r1",
      "bbox_norm": [x0, y0, x1, y1],
      "semantic_label": "person" | "obstacle" | "unknown_dynamic",
      "risk": "low" | "moderate" | "critical",
      "confidence": 0.00,
      "motion_evidence": "track_summary" | "none"
    }}
  ],
  "robot_candidate_sectors": [
    {{"angle_deg": 0, "width_deg": 20, "preference": 0.00}}
  ],
  "uncertainty": 0.00
}}

bbox_norm is [x0,y0,x1,y1] normalized 0-1 by image width/height. robot_candidate_sectors
describes which direction (relative to current heading, 0=forward) the robot could safely
attempt a short recovery move, NOT the direction the detected object is moving. uncertainty
is your overall confidence (0=very uncertain, 1=very certain) in this whole assessment."""


def parse_json_response(text: str) -> dict[str, Any] | None:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match is None:
        return None
    try:
        value = json.loads(match.group())
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def build_detections_text(detections: Sequence[DetectionEvidence]) -> str:
    lines: list[str] = []
    for detection in detections:
        x0, y0, x1, y1 = detection.bbox_xyxy_norm
        center_x, center_y = (x0 + x1) / 2, (y0 + y1) / 2
        horizontal = "LEFT" if center_x < 1 / 3 else "RIGHT" if center_x > 2 / 3 else "CENTER"
        vertical = "TOP" if center_y < 1 / 3 else "BOTTOM" if center_y > 2 / 3 else "MIDDLE"
        lines.append(
            f"- {detection.class_name}: {vertical}-{horizontal} region, "
            f"confidence {detection.confidence:.2f}"
        )
    return "\n".join(lines) if lines else "- nothing detected"


class QwenVlmInterpreter:
    model_name = MODEL_ID

    def __init__(self, model_revision: str = "main"):
        self.model_revision = model_revision
        self.model = None
        self.processor = None

    def load(self) -> None:
        import torch
        from transformers import (
            AutoProcessor,
            BitsAndBytesConfig,
            Qwen2_5_VLForConditionalGeneration,
        )

        quantization = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_use_double_quant=True,
        )
        self.processor = AutoProcessor.from_pretrained(
            self.model_name, revision=self.model_revision
        )
        self.model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
            self.model_name,
            revision=self.model_revision,
            quantization_config=quantization,
            device_map="cuda",
        )
        self.model.eval()

    def interpret(
        self,
        frame: Any,
        detections: Sequence[DetectionEvidence],
        goal_text: str,
    ) -> dict[str, Any]:
        if self.model is None or self.processor is None:
            self.load()
        import torch
        from PIL import Image

        image = Image.fromarray(frame[:, :, ::-1]).convert("RGB")
        prompt = CONTRACT_PROMPT_TEMPLATE.format(
            goal=goal_text,
            detections_text=build_detections_text(detections),
        )
        messages = [{
            "role": "user",
            "content": [
                {"type": "image", "image": image},
                {"type": "text", "text": prompt},
            ],
        }]
        rendered = self.processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = self.processor(text=[rendered], images=[image], return_tensors="pt").to(
            self.model.device
        )
        with torch.no_grad():
            output_ids = self.model.generate(**inputs, max_new_tokens=400)
        raw = self.processor.batch_decode(
            output_ids[:, inputs["input_ids"].shape[1]:], skip_special_tokens=True
        )[0]
        parsed = parse_json_response(raw)
        return parsed if parsed is not None else {}
