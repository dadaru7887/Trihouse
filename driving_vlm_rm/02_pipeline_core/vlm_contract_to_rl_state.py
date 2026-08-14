"""팀원 설계문서 §4.1 VLM 출력 계약을 실제로 구현하고, 그 결과를 오늘 만든 계층형
TGRPO-SAC(tgrpo_sac_hierarchical_v2.py)의 state로 변환하는 어댑터.

파이프라인: 실제 이미지 -> 세그멘테이션(aug_best.pt) -> VLM(7B-4bit, §4.1 JSON 계약) ->
state_adapter -> RL state 벡터

이게 "VLM+segmentation+trigger"와 "SAC-TGRPO 이중구조"를 실제로 잇는 첫 연결점.
아직 real env/replay 연동은 아니고, "state가 실제로 만들어질 수 있는가"까지 검증.

원격 GPU(unified_env_ver2)에서 실행. 로컬 것과 별도.
"""

from __future__ import annotations

import json
import re
import sys

import torch
from PIL import Image
from transformers import AutoProcessor, BitsAndBytesConfig, Qwen2_5_VLForConditionalGeneration

sys.path.insert(0, "/workspace/Trihouse_segmentation/Trihouse")
from train import mixed_augmentation  # noqa: F401
from ultralytics import YOLO
import cv2
import numpy as np

MODEL_ID = "Qwen/Qwen2.5-VL-7B-Instruct"  # §20 최종 확정
AUG_WEIGHTS = "/workspace/Trihouse_segmentation/weights/aug_best.pt"
CLASS_NAMES = ["obstacle", "person"]
GOAL = "The robot is navigating a warehouse aisle toward the next waypoint."

# --- 팀원 문서 §4.1 그대로: risk 판단 기준 문구까지 프롬프트에 명시 ---
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


def build_detections_text(detections: list[dict]) -> str:
    lines = []
    for d in detections:
        lines.append(f'- {d["class"]}: {d["position"]} region, confidence {d["confidence"]:.2f}')
    return "\n".join(lines) if lines else "- nothing detected"


def segment_image(seg_model: YOLO, image_path: str) -> tuple[list[dict], tuple[int, int]]:
    results = seg_model.predict(source=image_path, conf=0.25, verbose=False)
    r = results[0]
    img = cv2.imread(image_path)
    h, w = img.shape[:2]
    detections = []
    if r.boxes is not None and len(r.boxes) > 0:
        boxes = r.boxes.xywh.cpu().numpy()
        confs = r.boxes.conf.cpu().numpy()
        classes = r.boxes.cls.cpu().numpy().astype(int)
        for (cx, cy, bw, bh), conf, cls in zip(boxes, confs, classes):
            h_pos = "LEFT" if cx < w / 3 else ("RIGHT" if cx > 2 * w / 3 else "CENTER")
            v_pos = "TOP" if cy < h / 3 else ("BOTTOM" if cy > 2 * h / 3 else "MIDDLE")
            detections.append({"class": CLASS_NAMES[cls], "confidence": float(conf),
                                "position": f"{v_pos}-{h_pos}",
                                "bbox_xywh": [float(cx), float(cy), float(bw), float(bh)]})
    return detections, (w, h)


def parse_json_response(text: str) -> dict | None:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group())
    except json.JSONDecodeError:
        return None


def call_vlm_contract(model, processor, image: Image.Image, detections: list[dict]) -> dict | None:
    prompt = CONTRACT_PROMPT_TEMPLATE.format(goal=GOAL, detections_text=build_detections_text(detections))
    messages = [{"role": "user", "content": [{"type": "image", "image": image}, {"type": "text", "text": prompt}]}]
    text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = processor(text=[text], images=[image], return_tensors="pt").to(model.device)
    with torch.no_grad():
        output_ids = model.generate(**inputs, max_new_tokens=400)
    raw = processor.batch_decode(output_ids[:, inputs["input_ids"].shape[1]:], skip_special_tokens=True)[0]
    return parse_json_response(raw), raw


# ============================================================
# state adapter: VLM JSON(§4.1 계약) -> RL state 벡터
#   (tgrpo_sac_hierarchical_v2.py의 STATE_DIM=9 포맷에 맞춤, 필요시 확장 가능)
# ============================================================

RISK_TO_FLOAT = {"low": 0.2, "moderate": 0.6, "critical": 1.0}


def normalize_bbox_if_needed(bbox: list[float], img_wh: tuple[int, int]) -> tuple[list[float], bool]:
    """VLM이 지시(0~1 정규화)를 안 지키고 픽셀 좌표를 그대로 줬으면, 우리가 이미 알고 있는
    이미지 크기(w,h)로 나눠서 보정. 값 중 하나라도 1.0을 넘으면 '픽셀 좌표였다'고 판단
    (정상적인 0~1 정규화 값은 절대 1을 넘을 수 없으므로 이 판단 기준은 안전함).
    반환: (보정된 bbox, 보정이 실제로 일어났는지 여부 -- 로그/의심 신호로 남기기 위함)"""
    if max(bbox) <= 1.0:
        return bbox, False  # 이미 정규화되어 있음, 그대로 사용
    w, h = img_wh
    fixed = [bbox[0] / w, bbox[1] / h, bbox[2] / w, bbox[3] / h]
    return fixed, True


def vlm_json_to_state(vlm_json: dict, robot_pos: tuple[float, float], robot_yaw: float,
                       goal_pos: tuple[float, float], img_wh: tuple[int, int]) -> np.ndarray:
    """§4.1 VLM 출력을 tgrpo_sac_hierarchical_v2.STATE_DIM(9) 벡터로 변환.
    실제로는 observations가 여러 개일 수 있어 여기선 risk 제일 높은 것 하나만 대표로 사용
    (단순화 -- 실제로는 여러 observation을 별도 임베딩하는 게 맞음, 다음 단계 과제)."""
    obs_list = vlm_json.get("observations", [])
    if obs_list:
        worst = max(obs_list, key=lambda o: RISK_TO_FLOAT.get(o.get("risk", "low"), 0.0))
        bbox = worst.get("bbox_norm", [0.5, 0.5, 0.5, 0.5])
        bbox, was_corrected = normalize_bbox_if_needed(bbox, img_wh)
        if was_corrected:
            print(f"⚠️  bbox_norm이 정규화 안 된 픽셀값이었음 -- 이미지크기({img_wh})로 보정함. "
                  f"(이 응답의 다른 부분도 의심 신호로 남겨둘 것)")
        obs_x = (bbox[0] + bbox[2]) / 2
        obs_y = (bbox[1] + bbox[3]) / 2
        obs_conf = float(worst.get("confidence", 0.5))
    else:
        obs_x, obs_y, obs_conf = 0.5, 0.5, 0.0

    uncertainty = float(vlm_json.get("uncertainty", 0.5))

    state = np.array([
        robot_pos[0], robot_pos[1], robot_yaw,
        goal_pos[0], goal_pos[1],
        obs_x, obs_y, obs_conf,
        uncertainty,
    ], dtype=np.float32)
    return state


def main() -> None:
    with open("/workspace/Trihouse_segmentation/vlm_comparison_assets/comparison_results.json") as f:
        sample_data = json.load(f)
    test_sample = sample_data["samples"][0]  # idx0, clean, obstacle+2person 있는 이미지

    print("모델 로딩...")
    seg_model = YOLO(AUG_WEIGHTS)
    processor = AutoProcessor.from_pretrained(MODEL_ID)
    quant_config = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                       bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True)
    model = Qwen2_5_VLForConditionalGeneration.from_pretrained(MODEL_ID, quantization_config=quant_config,
                                                                device_map="cuda")
    model.eval()

    detections, (w, h) = segment_image(seg_model, test_sample["image_path"])
    print(f"세그멘테이션 결과: {len(detections)}개 detection")

    image = Image.open(test_sample["image_path"]).convert("RGB")
    vlm_json, raw = call_vlm_contract(model, processor, image, detections)

    print("\n=== VLM 원본 출력 ===")
    print(raw)

    if vlm_json is None:
        print("\n❌ JSON 파싱 실패 -- §13 실패모드 테이블의 'VLM hallucination/JSON 오류' 케이스")
        return

    print("\n✅ JSON 파싱 성공:")
    print(json.dumps(vlm_json, indent=2, ensure_ascii=False))

    state = vlm_json_to_state(vlm_json, robot_pos=(0.0, 0.0), robot_yaw=0.0, goal_pos=(10.0, 0.0),
                               img_wh=(w, h))
    print(f"\n=== RL state 벡터로 변환 ===\n{state}")
    print("\n-> 이 state를 tgrpo_sac_hierarchical_v2.py의 HighLevelPolicy/LowLevelPolicy에")
    print("   그대로 넣을 수 있음 (STATE_DIM=9 일치 확인).")


if __name__ == "__main__":
    main()
