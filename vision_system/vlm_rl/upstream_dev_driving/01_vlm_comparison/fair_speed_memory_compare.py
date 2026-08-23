"""공정한 비교: 3B(bf16/4bit) vs 7B(4bit/8bit) 메모리 + 속도(생성 시간) 전부 같은 조건에서 측정.
지금까지는 3B는 bf16만, 7B는 4bit/8bit만 쟀었음(양자화 수준이 안 맞는 비교) + 속도는 아예 안 쟀음.
같은 이미지 1장, 같은 프롬프트(B, 컨텍스트 포함), max_new_tokens=200 고정으로 4개 조합 전부 측정.
"""

from __future__ import annotations

import time

import torch
from PIL import Image
from transformers import AutoProcessor, BitsAndBytesConfig, Qwen2_5_VLForConditionalGeneration

TEST_IMAGE = "/workspace/Trihouse_segmentation/Trihouse_seg_dataset/test_clean/images/frame_0000-00s_jpg.rf.73ede5b3dcf491afd195d582638be125.jpg"
CONTEXT = ("Detected by onboard segmentation model (System1):\n"
           "- obstacle: TOP-LEFT region, confidence 0.92\n"
           "- person: MIDDLE-CENTER region, confidence 0.66\n"
           "- person: MIDDLE-CENTER region, confidence 0.44")
GOAL = "The robot is navigating a warehouse aisle toward the next waypoint."
PROMPT = (f"Goal: {GOAL}\n\n{CONTEXT}\n\nUsing both the image and the detection info above, "
          "describe the obstacles/people and judge whether it is currently safe to proceed forward. "
          "Note if the detection confidence for any object seems too low to trust. Be concise (3-4 sentences).")

CONFIGS = [
    ("3B-bf16", "Qwen/Qwen2.5-VL-3B-Instruct", "bf16"),
    ("3B-4bit", "Qwen/Qwen2.5-VL-3B-Instruct", "4bit"),
    ("7B-4bit", "Qwen/Qwen2.5-VL-7B-Instruct", "4bit"),
    ("7B-8bit", "Qwen/Qwen2.5-VL-7B-Instruct", "8bit"),
]


def load_model(model_id: str, mode: str):
    if mode == "4bit":
        qc = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                 bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True)
        return Qwen2_5_VLForConditionalGeneration.from_pretrained(model_id, quantization_config=qc, device_map="cuda")
    elif mode == "8bit":
        qc = BitsAndBytesConfig(load_in_8bit=True)
        return Qwen2_5_VLForConditionalGeneration.from_pretrained(model_id, quantization_config=qc, device_map="cuda")
    else:
        return Qwen2_5_VLForConditionalGeneration.from_pretrained(model_id, torch_dtype=torch.bfloat16, device_map="cuda")


def main() -> None:
    image = Image.open(TEST_IMAGE).convert("RGB")
    results = []

    for name, model_id, mode in CONFIGS:
        print(f"\n=== {name} ({model_id}) ===")
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()

        processor = AutoProcessor.from_pretrained(model_id)
        model = load_model(model_id, mode)
        model.eval()
        load_mem = torch.cuda.max_memory_allocated() / 1e9
        print(f"  로딩 후 peak 메모리: {load_mem:.2f} GB")

        messages = [{"role": "user", "content": [{"type": "image", "image": image}, {"type": "text", "text": PROMPT}]}]
        text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = processor(text=[text], images=[image], return_tensors="pt").to(model.device)

        # 워밍업 1회(첫 호출은 CUDA 커널 컴파일 등으로 느리게 나올 수 있어서 측정에서 제외)
        with torch.no_grad():
            model.generate(**inputs, max_new_tokens=10)
        torch.cuda.synchronize()

        n_runs = 3
        times = []
        for _ in range(n_runs):
            torch.cuda.synchronize()
            t0 = time.time()
            with torch.no_grad():
                output_ids = model.generate(**inputs, max_new_tokens=200)
            torch.cuda.synchronize()
            times.append(time.time() - t0)
        avg_time = sum(times) / len(times)
        n_new_tokens = output_ids.shape[1] - inputs["input_ids"].shape[1]
        tok_per_sec = n_new_tokens / avg_time

        peak_mem = torch.cuda.max_memory_allocated() / 1e9
        print(f"  200토큰 생성 평균 시간: {avg_time:.2f}초 (3회: {[f'{t:.2f}' for t in times]})")
        print(f"  속도: {tok_per_sec:.1f} tok/s")
        print(f"  전체 peak 메모리(로딩+추론): {peak_mem:.2f} GB")

        results.append({"name": name, "load_mem_gb": load_mem, "peak_mem_gb": peak_mem,
                         "avg_gen_time_s": avg_time, "tok_per_sec": tok_per_sec})

        del model, processor
        torch.cuda.empty_cache()

    print("\n\n=== 요약 ===")
    print(f"{'모델':12s} {'로딩메모리':>10s} {'peak메모리':>10s} {'200토큰시간':>12s} {'tok/s':>8s}")
    for r in results:
        print(f"{r['name']:12s} {r['load_mem_gb']:9.2f}GB {r['peak_mem_gb']:9.2f}GB "
              f"{r['avg_gen_time_s']:11.2f}s {r['tok_per_sec']:7.1f}")


if __name__ == "__main__":
    main()
