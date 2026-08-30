"""base Qwen2.5-VL-3B-Instruct를 4bit(nf4)로 양자화했을 때 품질(A/B 프롬프트, 12장)이
bf16과 비교해 떨어지지 않는지 확인. 방금 속도/메모리 비교(fair_speed_memory_compare.py)에서
3B-4bit가 메모리(2.53GB)/속도(28.1 tok/s) 둘 다 압도적으로 유리한 게 나와서, 품질까지 유지되면
최종 추천을 base(bf16)에서 3B-4bit로 바꿔야 함.

세그멘테이션은 재추론 안 하고 comparison_results.json의 detections/segmentation_context 재사용,
같은 12장에 대해 A/B 프롬프트 재실행 (7B 스크립트와 동일 패턴)."""

from __future__ import annotations

import json

import torch
from PIL import Image
from transformers import AutoProcessor, BitsAndBytesConfig, Qwen2_5_VLForConditionalGeneration

OUT_DIR = "/workspace/Trihouse_segmentation/vlm_comparison_assets"
MODEL_ID = "Qwen/Qwen2.5-VL-3B-Instruct"

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


def ask(model, processor, image: Image.Image, prompt_text: str) -> str:
    messages = [{"role": "user", "content": [{"type": "image", "image": image}, {"type": "text", "text": prompt_text}]}]
    text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = processor(text=[text], images=[image], return_tensors="pt").to(model.device)
    with torch.no_grad():
        output_ids = model.generate(**inputs, max_new_tokens=200)
    generated = output_ids[:, inputs["input_ids"].shape[1]:]
    return processor.batch_decode(generated, skip_special_tokens=True)[0]


def main() -> None:
    with open(f"{OUT_DIR}/comparison_results.json") as f:
        base_data = json.load(f)

    print(f"모델 로딩: {MODEL_ID} (4bit)")
    processor = AutoProcessor.from_pretrained(MODEL_ID)
    quant_config = BitsAndBytesConfig(
        load_in_4bit=True, bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True,
    )
    model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
        MODEL_ID, quantization_config=quant_config, device_map="cuda"
    )
    model.eval()
    print("로딩 완료, GPU 메모리:", torch.cuda.memory_allocated() / 1e9, "GB")

    results = []
    for s in base_data["samples"]:
        pil_img = Image.open(s["image_path"]).convert("RGB")
        ans_a = ask(model, processor, pil_img, PROMPT_A)
        ans_b = ask(model, processor, pil_img, prompt_b(s["segmentation_context"]))
        results.append({
            "idx": s["idx"], "category": s["category"],
            "answers": {"A_image_only": ans_a, "B_with_context": ans_b},
        })
        print(f"[{s['idx']}:{s['category']}] 3b-4bit done")

    out_path = f"{OUT_DIR}/comparison_results_3b_4bit.json"
    with open(out_path, "w") as f:
        json.dump({"model": MODEL_ID, "quant": "4bit", "samples": results}, f, indent=2, ensure_ascii=False)
    print(f"\n저장 완료: {out_path}")


if __name__ == "__main__":
    main()
