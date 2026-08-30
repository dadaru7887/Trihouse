"""geometric_6c_lite.py의 2-멤버 앙상블(실시간 costmap / Nav2 planner)이 buffer 안에서
서로 얼마나 자주 의견이 갈렸는지(n_disagree) 집계하는 스크립트. 로드맵 1번(제일 쉬운 것) --
새 알고리즘이 아니라 이미 기록되고 있는 값을 정리해서 보여주기만 함.

**2026-08-15 작성, 아직 실제 buffer로 돌려본 적 없음**(로컬 buffer엔 n_disagree 필드가
채워진 실행 transition이 아직 없음 -- is_execution=True가 0개라서). 구조만 확인됨.

실행: python3 disagreement_report.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "02_pipeline_core"))

from recovery_data_collector import PersistentRecoveryBuffer

BUFFER_PATH = "../03_results/real_recovery_buffer.pkl"


def main() -> None:
    buffer = PersistentRecoveryBuffer(save_path=BUFFER_PATH)
    transitions = [t for t in buffer.transitions if t.get("meta", {}).get("is_execution")]
    print(f"실제 실행 transition {len(transitions)}개 중 분석")

    with_field = [t for t in transitions if "n_disagree" in t.get("meta", {})]
    print(f"n_disagree 필드가 있는 것: {len(with_field)}개")
    if not with_field:
        print("!! n_disagree 기록이 하나도 없음 -- geometric_6c_lite.py가 실제로 이 필드를 "
              "채우고 있는지 nav_recovery_executor.py 호출부에서 재확인 필요할 수 있음.")
        return

    n_disagree_counts: dict[int, int] = {}
    for t in with_field:
        n = t["meta"]["n_disagree"]
        n_disagree_counts[n] = n_disagree_counts.get(n, 0) + 1

    print("\nn_disagree 값별 분포 (0 = 두 멤버가 항상 같은 판정):")
    for n, cnt in sorted(n_disagree_counts.items()):
        pct = 100.0 * cnt / len(with_field)
        print(f"  n_disagree={n}: {cnt}개 ({pct:.1f}%)")

    disagree_rate = sum(cnt for n, cnt in n_disagree_counts.items() if n > 0) / len(with_field)
    print(f"\n전체 disagreement 비율: {disagree_rate*100:.1f}%")
    print("-- 이 값이 너무 낮으면(예: <5%) 두 멤버가 사실상 같은 신호를 중복 체크하는 "
          "것뿐이라 앙상블 의미가 약함(EXPERIMENT_DESIGN.md 5번 항목 참고, 세 번째 독립적인 "
          "멤버 추가 검토 신호가 될 수 있음).")


if __name__ == "__main__":
    main()
