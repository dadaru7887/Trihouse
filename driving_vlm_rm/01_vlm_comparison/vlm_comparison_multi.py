"""VLM 후보군(base Qwen2.5-VL-3B vs SpaceThinker-Qwen2.5VL-3B) x (이미지만 vs 세그멘테이션
컨텍스트 포함) 비교. 어제(단일 이미지, 하드코딩 컨텍스트) 데모와 달리:
  - 여러 카테고리(clean/s1~s5/lowlight)에서 실제 GT 있는 이미지 여러 장 샘플링
  - 세그멘테이션 컨텍스트를 하드코딩이 아니라 실제 aug 모델 추론 결과로 생성
  - 결과 + 시각화(원본+박스, 프롬프트, 두 모델 답변)를 JSON으로 저장 -> 노트북에서 렌더링
"""

from __future__ import annotations

import glob
import json
import os
import sys

sys.path.insert(0, "/workspace/Trihouse_segmentation/Trihouse")

import cv2
import numpy as np
import torch
from PIL import Image
from train import mixed_augmentation  # noqa: F401
from ultralytics import YOLO
from transformers import AutoProcessor, Qwen2_5_VLForConditionalGeneration

DATASET_ROOT = "/workspace/Trihouse_segmentation/Trihouse_seg_dataset"
AUG_WEIGHTS = "/workspace/Trihouse_segmentation/weights/aug_best.pt"
CLASS_NAMES = ["obstacle", "person"]

MODELS = {
    "base": "Qwen/Qwen2.5-VL-3B-Instruct",
    "spacethinker": "remyxai/SpaceThinker-Qwen2.5VL-3B",
}

CATEGORIES_TO_SAMPLE = ["clean", "s1", "s3", "s4", "s5", "lowlight"]
N_PER_CATEGORY = 2

OUT_DIR = "/workspace/Trihouse_segmentation/vlm_comparison_assets"
os.makedirs(OUT_DIR, exist_ok=True)


def has_object(label_path: str) -> bool:
    if not os.path.exists(label_path) or os.path.getsize(label_path) == 0:
        return False
    with open(label_path) as f:
        return any(line.strip() for line in f)


def pick_images() -> list[tuple[str, str]]:
    """(category, image_path) 리스트. object 있는 프레임만, 카테고리당 N_PER_CATEGORY장."""
    picked = []
    for cat in CATEGORIES_TO_SAMPLE:
        img_dir = f"{DATASET_ROOT}/test_{cat}/images"
        lbl_dir = f"{DATASET_ROOT}/test_{cat}/labels"
        paths = sorted(glob.glob(f"{img_dir}/*.jpg"))
        count = 0
        for p in paths:
            base = os.path.splitext(os.path.basename(p))[0]
            if has_object(f"{lbl_dir}/{base}.txt"):
                picked.append((cat, p))
                count += 1
                if count >= N_PER_CATEGORY:
                    break
    return picked


def segmentation_context_and_viz(seg_model: YOLO, image_path: str, out_viz_path: str) -> tuple[str, list[dict]]:
    """실제 추론 -> (VLM에 줄 텍스트 컨텍스트, 구조화된 검출 리스트) + 박스 그려진 시각화 이미지 저장."""
    results = seg_model.predict(source=image_path, conf=0.25, verbose=False)
    r = results[0]
    img = cv2.imread(image_path)
    h, w = img.shape[:2]

    detections = []
    lines = []
    if r.boxes is not None and len(r.boxes) > 0:
        boxes = r.boxes.xywh.cpu().numpy()
        confs = r.boxes.conf.cpu().numpy()
        classes = r.boxes.cls.cpu().numpy().astype(int)
        for (cx, cy, bw, bh), conf, cls in zip(boxes, confs, classes):
            h_pos = "LEFT" if cx < w / 3 else ("RIGHT" if cx > 2 * w / 3 else "CENTER")
            v_pos = "TOP" if cy < h / 3 else ("BOTTOM" if cy > 2 * h / 3 else "MIDDLE")
            name = CLASS_NAMES[cls]
            lines.append(f"- {name}: {v_pos}-{h_pos} region, confidence {conf:.2f}")
            detections.append({"class": name, "confidence": float(conf), "position": f"{v_pos}-{h_pos}",
                                "bbox_xywh": [float(cx), float(cy), float(bw), float(bh)]})
            # 시각화
            x0, y0 = int(cx - bw / 2), int(cy - bh / 2)
            x1, y1 = int(cx + bw / 2), int(cy + bh / 2)
            color = (255, 0, 0) if name == "obstacle" else (255, 255, 0)
            cv2.rectangle(img, (x0, y0), (x1, y1), color, 2)
            cv2.putText(img, f"{name} {conf:.2f}", (x0, max(0, y0 - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
    cv2.imwrite(out_viz_path, img)

    if lines:
        context = "Detected by onboard segmentation model (System1):\n" + "\n".join(lines)
    else:
        context = "Detected by onboard segmentation model (System1): nothing detected."
    return context, detections


def ask(model, processor, image: Image.Image, prompt_text: str) -> str:
    messages = [{"role": "user", "content": [{"type": "image", "image": image}, {"type": "text", "text": prompt_text}]}]
    text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = processor(text=[text], images=[image], return_tensors="pt").to(model.device)
    with torch.no_grad():
        output_ids = model.generate(**inputs, max_new_tokens=200)
    generated = output_ids[:, inputs["input_ids"].shape[1]:]
    return processor.batch_decode(generated, skip_special_tokens=True)[0]


GOAL = "The robot is navigating a warehouse aisle toward the next waypoint."

PROMPT_A = (
    f"Goal: {GOAL}\n\nLook at this warehouse robot camera image. Identify any obstacles or "
    "people, describe roughly where they are in the frame, and judge whether it is currently "
    "safe to proceed forward. Be concise (3-4 sentences)."
)


def prompt_b(context: str) -> str:
    return (
        f"Goal: {GOAL}\n\n{context}\n\nUsing both the image and the detection info above, "
        "describe the obstacles/people and judge whether it is currently safe to proceed forward. "
        "Note if the detection confidence for any object seems too low to trust. Be concise (3-4 sentences)."
    )


def main() -> None:
    seg_model = YOLO(AUG_WEIGHTS)
    samples = pick_images()
    print(f"샘플 {len(samples)}장 선정")

    loaded = {}
    for key, model_id in MODELS.items():
        print(f"모델 로딩: {model_id}")
        processor = AutoProcessor.from_pretrained(model_id)
        model = Qwen2_5_VLForConditionalGeneration.from_pretrained(model_id, torch_dtype=torch.bfloat16, device_map="cuda")
        model.eval()
        loaded[key] = (model, processor)

    results = []
    for idx, (cat, img_path) in enumerate(samples):
        viz_path = f"{OUT_DIR}/sample_{idx}_{cat}_viz.jpg"
        context, detections = segmentation_context_and_viz(seg_model, img_path, viz_path)

        entry = {
            "idx": idx, "category": cat, "image_path": img_path, "viz_path": viz_path,
            "detections": detections, "segmentation_context": context, "answers": {},
        }
        pil_img = Image.open(img_path).convert("RGB")
        for key, (model, processor) in loaded.items():
            ans_a = ask(model, processor, pil_img, PROMPT_A)
            ans_b = ask(model, processor, pil_img, prompt_b(context))
            entry["answers"][key] = {"A_image_only": ans_a, "B_with_context": ans_b}
            print(f"[{idx}:{cat}] {key} done")
        results.append(entry)

    with open(f"{OUT_DIR}/comparison_results.json", "w") as f:
        json.dump({"prompt_A": PROMPT_A, "goal": GOAL, "samples": results}, f, indent=2, ensure_ascii=False)
    print(f"\n저장 완료: {OUT_DIR}/comparison_results.json")


if __name__ == "__main__":
    main()
