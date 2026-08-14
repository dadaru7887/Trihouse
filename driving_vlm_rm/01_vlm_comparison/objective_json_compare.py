"""완전히 객관적인 비교: 자유 문장 대신 VLM한테 구조화된 JSON으로 답하게 해서, 사람이 읽거나
정규식으로 추측할 필요 없이 필드 대 필드로 기계적으로 채점. base-4bit vs 7b-4bit 두 후보만
결정적으로 비교(자원 비교에서 이미 이 둘이 남았으므로).

정답(rule, 애매함 없음): confidence >= 0.7 = high, 0.5~0.7 = moderate, < 0.5 = low.
채점 항목: (1) class 정확히 맞혔는가 (2) confidence 값 정확히 인용했는가
(3) risk_level이 위 규칙과 일치하는가 -- 전부 dict key/value 비교라 해석의 여지 없음.
"""

from __future__ import annotations

import json
import re
import sys

import torch
from PIL import Image
from transformers import AutoProcessor, BitsAndBytesConfig, Qwen2_5_VLForConditionalGeneration

OUT_DIR = "/workspace/Trihouse_segmentation/vlm_comparison_assets"
GOAL = "The robot is navigating a warehouse aisle toward the next waypoint."

CONFIGS = {
    "base-bf16": ("Qwen/Qwen2.5-VL-3B-Instruct", "bf16"),
    "base-4bit": ("Qwen/Qwen2.5-VL-3B-Instruct", "4bit"),
    "7b-4bit": ("Qwen/Qwen2.5-VL-7B-Instruct", "4bit"),
}


def expected_level(conf: float) -> str:
    if conf >= 0.7:
        return "high"
    if conf >= 0.5:
        return "moderate"
    return "low"


def build_prompt(detections: list[dict]) -> str:
    det_lines = "\n".join(
        f'  - class="{d["class"]}", position="{d["position"]}", confidence={d["confidence"]:.2f}'
        for d in detections
    )
    return (
        f"Goal: {GOAL}\n\n"
        f"Detected by onboard segmentation model (System1):\n{det_lines}\n\n"
        "Respond with ONLY a JSON object (no other text), one entry per detection above, "
        "in this exact format:\n"
        '{"detections": [{"class": "...", "confidence": 0.00, "risk_level": "high|moderate|low"}, ...], '
        '"safe_to_proceed": true|false}\n\n'
        "risk_level must reflect how much you'd trust this specific detection's confidence value "
        "(be internally consistent with the confidence number you report)."
    )


def parse_json_response(text: str) -> dict | None:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group())
    except json.JSONDecodeError:
        return None


def ask(model, processor, image: Image.Image, prompt_text: str) -> str:
    messages = [{"role": "user", "content": [{"type": "image", "image": image}, {"type": "text", "text": prompt_text}]}]
    text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = processor(text=[text], images=[image], return_tensors="pt").to(model.device)
    with torch.no_grad():
        output_ids = model.generate(**inputs, max_new_tokens=300)
    generated = output_ids[:, inputs["input_ids"].shape[1]:]
    return processor.batch_decode(generated, skip_special_tokens=True)[0]


def score(parsed: dict, ground_truth: list[dict]) -> dict:
    if parsed is None or "detections" not in parsed:
        return {"parse_failed": True, "class_correct": 0, "conf_correct": 0,
                "level_correct": 0, "total": len(ground_truth)}

    gt_sorted = sorted(ground_truth, key=lambda d: d["confidence"], reverse=True)
    pred_sorted = sorted(parsed.get("detections", []), key=lambda d: d.get("confidence", -1), reverse=True)

    class_correct = conf_correct = level_correct = 0
    n = min(len(gt_sorted), len(pred_sorted))
    for gt, pred in zip(gt_sorted[:n], pred_sorted[:n]):
        if str(pred.get("class", "")).lower() == gt["class"].lower():
            class_correct += 1
        try:
            if abs(float(pred.get("confidence", -1)) - gt["confidence"]) < 0.02:
                conf_correct += 1
        except (TypeError, ValueError):
            pass
        if str(pred.get("risk_level", "")).lower() == expected_level(gt["confidence"]):
            level_correct += 1

    return {"parse_failed": False, "class_correct": class_correct, "conf_correct": conf_correct,
            "level_correct": level_correct, "total": len(gt_sorted), "n_matched": n}


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "base-4bit"
    model_id, quant = CONFIGS[mode]

    with open(f"{OUT_DIR}/comparison_results.json") as f:
        base_data = json.load(f)

    print(f"모델 로딩: {model_id} ({quant}, {mode})")
    processor = AutoProcessor.from_pretrained(model_id)
    if quant == "4bit":
        quant_config = BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True,
        )
        model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
            model_id, quantization_config=quant_config, device_map="cuda"
        )
    else:
        model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
            model_id, torch_dtype=torch.bfloat16, device_map="cuda"
        )
    model.eval()

    results = []
    totals = {"class_correct": 0, "conf_correct": 0, "level_correct": 0, "total": 0, "parse_failures": 0}
    for s in base_data["samples"]:
        pil_img = Image.open(s["image_path"]).convert("RGB")
        prompt = build_prompt(s["detections"])
        raw = ask(model, processor, pil_img, prompt)
        parsed = parse_json_response(raw)
        sc = score(parsed, s["detections"])

        if sc["parse_failed"]:
            totals["parse_failures"] += 1
        else:
            totals["class_correct"] += sc["class_correct"]
            totals["conf_correct"] += sc["conf_correct"]
            totals["level_correct"] += sc["level_correct"]
        totals["total"] += sc["total"]

        results.append({"idx": s["idx"], "category": s["category"], "raw": raw,
                         "parsed": parsed, "score": sc})
        print(f"[{s['idx']}:{s['category']}] {mode} parse_failed={sc['parse_failed']} score={sc}")

    print(f"\n=== {mode} 요약 ===")
    print(f"파싱 실패: {totals['parse_failures']}/12")
    print(f"class 정확: {totals['class_correct']}/{totals['total']}")
    print(f"confidence 정확: {totals['conf_correct']}/{totals['total']}")
    print(f"risk_level 규칙 일치: {totals['level_correct']}/{totals['total']}")

    out_path = f"{OUT_DIR}/objective_compare_{mode}.json"
    with open(out_path, "w") as f:
        json.dump({"mode": mode, "model_id": model_id, "totals": totals, "results": results}, f,
                   indent=2, ensure_ascii=False)
    print(f"저장: {out_path}")


if __name__ == "__main__":
    main()
