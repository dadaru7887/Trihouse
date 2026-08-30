"""로드맵 2번: "VLM 자체를 언어 기반 저비용 world-model 대용으로 쓰기" -- 2026-08-11에
아이디어만 나오고 구현은 전혀 안 됐던 것. **여기 있는 코드는 전부 데모/스텁이고 실제 VLM
API로 단 한 번도 실행해본 적 없음** -- 프롬프트가 실제로 이 형식의 JSON을 안정적으로
뱉는지는 검증 필요(과거 vlm_contract_to_rl_state.py의 CONTRACT_PROMPT_TEMPLATE도 여러 번
실측하면서 다듬어진 거라, 이것도 최소 수십 회 실측 조정이 필요할 것으로 예상).

핵심 아이디어: 학습된 neural world-model(로드맵 3번)은 데이터가 너무 적어서 당장 불가능한데,
VLM은 이미 파이프라인에 붙어있고(vlm_contract_to_rl_state.py) 방대한 사전학습으로 "이런
상황에서 이렇게 하면 대충 어떻게 될지"에 대한 상식을 이미 갖고 있음 -- 그 상식을 구조화된
예측으로 뽑아내자는 것. `world_model_ensemble.py`(로드맵 3번, 학습 필요)와 인터페이스를
맞춰서(`predict()` 시그니처 동일), 나중에 둘 중 뭐가 더 나은지 바로 비교 가능하게 설계함.
"""
from __future__ import annotations

import json
import re

# 기존 vlm_contract_to_rl_state.py의 CONTRACT_PROMPT_TEMPLATE에 이 블록을 이어붙이는 걸
# 전제로 설계함(완전히 새 프롬프트를 짜는 대신, 이미 실측 검증된 기존 프롬프트에 예측
# 필드만 추가하는 게 실패 위험이 적음 -- 기존 필드 파싱을 안 건드림).
PREDICTION_PROMPT_SUFFIX = """

추가로, 다음 3가지 후보 행동 각각에 대해 "몇 초 뒤 어떻게 될 것 같은지" 예측해서
JSON의 "predictions" 필드(리스트)에 추가하세요. 각 항목은 다음 형식:
{{
  "action": "<후보 행동 설명, 예: '왼쪽으로 0.3m 우회'>",
  "predicted_outcome": "<safe|risky|collision_likely 중 하나>",
  "confidence": <0.0~1.0>,
  "reasoning": "<한 문장 근거>"
}}
candidates: {candidates_text}
"""


def build_candidates_text(candidates: list[dict]) -> str:
    """rl_candidate_group.py가 만든 K*M 후보 리스트를 프롬프트에 넣을 텍스트로 변환.
    candidates: [{"skill": int, "coord": [dx,dy,dyaw]}, ...] 형태를 가정."""
    lines = []
    for i, c in enumerate(candidates):
        lines.append(f"  {i}: skill={c['skill']}, coord=(dx={c['coord'][0]:.2f}, "
                      f"dy={c['coord'][1]:.2f}, dyaw={c['coord'][2]:.2f})")
    return "\n".join(lines)


def parse_predictions(vlm_raw_text: str) -> list[dict] | None:
    """VLM 응답에서 predictions 필드만 뽑아냄. 기존 parse_json_response와 같은 방식
    (정규식으로 {...} 추출 -> json.loads)이지만, predictions 필드가 없으면 None 반환해서
    호출부가 "이 VLM 응답엔 예측이 없다"를 구분할 수 있게 함."""
    match = re.search(r"\{.*\}", vlm_raw_text, re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group())
    except json.JSONDecodeError:
        return None
    return parsed.get("predictions")


_OUTCOME_TO_REWARD_PROXY = {"safe": 1.0, "risky": 0.0, "collision_likely": -1.0}


def vlm_predictions_to_risk_scores(predictions: list[dict]) -> dict[int, float]:
    """world_model_ensemble.py의 risk_ucb()와 비교 가능한 형태로 변환 -- candidate index별
    risk score(낮을수록 안전). confidence를 표준편차 프록시처럼 씀(확신 낮을수록 위험
    쪽으로 보수적으로 잡음, world_model_ensemble의 kappa*std 항과 같은 역할)."""
    scores = {}
    for i, p in enumerate(predictions):
        outcome_val = _OUTCOME_TO_REWARD_PROXY.get(p.get("predicted_outcome"), 0.0)
        confidence = float(p.get("confidence", 0.5))
        # confidence가 낮으면(불확실하면) risk를 보수적으로 올림 -- risk_ucb의 +kappa*std와
        # 같은 방향(불확실할수록 위험하게 취급).
        risk = -outcome_val + (1.0 - confidence) * 0.5
        scores[i] = risk
    return scores


if __name__ == "__main__":
    # 실제 VLM 호출 없이, 파싱/변환 로직만 확인하는 데모.
    fake_vlm_response = """
    여기 상황을 봤을 때 이렇게 예측됩니다:
    {"predictions": [
        {"action": "왼쪽 우회", "predicted_outcome": "safe", "confidence": 0.8, "reasoning": "왼쪽이 열려있음"},
        {"action": "오른쪽 우회", "predicted_outcome": "risky", "confidence": 0.4, "reasoning": "벽이 가까움"},
        {"action": "후진 대기", "predicted_outcome": "safe", "confidence": 0.9, "reasoning": "빈 공간"}
    ]}
    """
    preds = parse_predictions(fake_vlm_response)
    print("파싱된 predictions:", preds)
    if preds:
        scores = vlm_predictions_to_risk_scores(preds)
        print("risk score (낮을수록 안전):", scores)
        best = min(scores, key=scores.get)
        print(f"-> VLM 예측 기준 최선 후보: index {best} ({preds[best]['action']})")
    print("\n-- 파싱/변환 로직만 확인됨. 실제 VLM이 이 형식을 안정적으로 뱉는지는 미검증 --")
