"""Qwen2.5-VL 7B 4-bit interpreter; prompt versions come from
vision_ai/robot/configs/vlm_prompts.yaml.

    vlm = QwenVlmInterpreter("main", prompt_version="v1",
                             response_log=Path("runs/recovery/vlm_responses.jsonl"))
    result = vlm.interpret(frame_bgr, evidence)                       # robot
    result = vlm.interpret(frame_bgr, evidence, version="current")    # comparison

Flow: render the version's sections around the detection list -> generate
greedily with the shared settings -> parse the JSON -> return it with the raw
text and the prompt sent, and append all of it to the response log when one
is set. Every version answers `scene_confidence` (1 = certain).

The raw text is returned even when the JSON cannot be parsed; that text is
the only way to tell a truncated answer from a malformed one.
"""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import re
import time
from typing import Any, Sequence
from uuid import uuid4

from vision_ai.robot.recovery.worker import DetectionEvidence


MODEL_ID = "Qwen/Qwen2.5-VL-7B-Instruct"
PROMPTS_PATH = Path(__file__).resolve().parents[2] / "robot" / "configs" / "vlm_prompts.yaml"


def load_prompts(path: Path = PROMPTS_PATH) -> dict[str, Any]:
    """vlm_prompts.yaml as a dict: runtime_version, generation, versions, sections."""
    import yaml

    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def parse_json_response(text: str) -> dict[str, Any] | None:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match is None:
        return None
    try:
        value = json.loads(match.group())
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def build_detections_text(detections: Sequence[DetectionEvidence], style: str = "legacy") -> str:
    """The detection list the prompt shows, one line per detection (see vlm_prompts.yaml)."""
    lines: list[str] = []
    for detection in detections:
        x0, y0, x1, y1 = detection.bbox_xyxy_norm
        center_x, center_y = (x0 + x1) / 2, (y0 + y1) / 2
        horizontal = "LEFT" if center_x < 1 / 3 else "RIGHT" if center_x > 2 / 3 else "CENTER"
        vertical = "TOP" if center_y < 1 / 3 else "BOTTOM" if center_y > 2 / 3 else "MIDDLE"
        if style == "legacy":
            lines.append(
                f"- {detection.class_name}: {vertical}-{horizontal} region, "
                f"confidence {detection.confidence:.2f}"
            )
        else:
            box = ", ".join(f"{value:.3f}" for value in detection.bbox_xyxy_norm)
            lines.append(
                f"- region_id={detection.region_id}, class={detection.class_name}, "
                f"yoloe_confidence={detection.confidence:.2f}, bbox_norm=[{box}], "
                f"position={vertical}-{horizontal}, track_id={detection.track_id or 'null'}"
            )
    return "\n".join(lines) if lines else "- nothing detected"


def render_prompt(version: str, detections: Sequence[DetectionEvidence],
                  prompts: dict[str, Any]) -> str:
    """The full text prompt one version sends for these detections."""
    spec = prompts["versions"][version]
    text = "\n\n".join(prompts["sections"][name] for name in spec["sections"])
    return text.replace("{yoloe_detections}", build_detections_text(detections, spec["reference"]))


class QwenVlmInterpreter:
    model_name = MODEL_ID

    def __init__(self, model_revision: str = "main", *, prompt_version: str | None = None,
                 response_log: Path | None = None, prompts_path: Path = PROMPTS_PATH):
        self.model_revision = model_revision
        self.prompts = load_prompts(prompts_path)
        self.prompt_version = prompt_version or self.prompts["runtime_version"]
        if self.prompt_version not in self.prompts["versions"]:
            raise ValueError(f"unknown prompt version: {self.prompt_version}")
        self.response_log = Path(response_log) if response_log else None
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
        version: str | None = None,
    ) -> dict[str, Any]:
        """BGR frame + detections -> parsed answer plus raw_response, the prompt
        sent, prompt_version, response_id, output_tokens and truncated."""
        if self.model is None or self.processor is None:
            self.load()
        import torch
        from PIL import Image

        version = version or self.prompt_version
        generation = self.prompts["generation"]
        image = Image.fromarray(frame[:, :, ::-1]).convert("RGB")
        prompt = render_prompt(version, detections, self.prompts)
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
        started = time.monotonic()
        with torch.no_grad():
            output_ids = self.model.generate(
                **inputs,
                max_new_tokens=int(generation["max_new_tokens"]),
                do_sample=bool(generation["do_sample"]),
            )
        new_ids = output_ids[:, inputs["input_ids"].shape[1]:]
        raw = self.processor.batch_decode(new_ids, skip_special_tokens=True)[0]
        result = {
            **(parse_json_response(raw) or {}),          # {} when there is no JSON; raw stays
            "raw_response": raw,
            "prompt": prompt,
            "prompt_version": version,
            "response_id": str(uuid4()),
            "output_tokens": int(new_ids.shape[1]),
            "truncated": int(new_ids.shape[1]) >= int(generation["max_new_tokens"]),
            "seconds": round(time.monotonic() - started, 3),
        }
        if self.response_log is not None:
            self.response_log.parent.mkdir(parents=True, exist_ok=True)
            with self.response_log.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({
                    "logged_at": time.time(), "model": self.model_name,
                    "revision": self.model_revision,
                    "detections": [asdict(detection) for detection in detections],
                    **result,
                }, ensure_ascii=False) + "\n")
        return result
