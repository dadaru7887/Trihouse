"""정밀 정차 허용오차는 Nav2 의 goal tolerance 보다 좁으면 안 된다.

## 왜

Nav2 는 `xy_goal_tolerance` 안에 들어오면 그 자리에서 멈추고 SUCCEEDED 를 준다.
그보다 **좁은** 기준으로 도착을 다시 판정하면, Nav2 가 정상적으로 끝낸 이동을
우리가 거절하게 된다. 로봇은 더 갈 이유가 없으므로 다시 시도해도 같은 자리에
선다 — 재시도로 풀리지 않는 실패다.

2026-08-19 실측: step 20 이 `final_outcome_reason_code=GOAL_TOLERANCE_NOT_MET` 으로
죽었다. 그때 우리 기준은 `xy 0.05 / yaw 0.0873`, Nav2 는 `xy 0.1 / yaw 0.25` 였다.

## 값의 정본은 벤더 params 다

`pinky_pro/pinky_navigation/params/nav2_params.yaml` 은 **실물 주행으로 튜닝한
값**이다. 이쪽을 우리 편의로 조이지 않는다. 대신 우리 판정이 그 값을 따라간다.

AMCL 실측 stddev 가 10~12 cm 이므로 그보다 좁은 허용오차는 위치추정 정확도로도
만족시킬 수 없다. Nav2 의 0.1 m 는 그 실측과도 맞는다.

## 이 테스트가 지키는 것

벤더 params 를 다시 튜닝했을 때 우리 판정이 조용히 어긋나지 않게 한다.
`tests/test_ros_dds_agreement.py` 가 두 층의 DDS 기본값을 묶어 두는 것과 같은 성격이다.
"""

import sys
from pathlib import Path

import pytest
import yaml

PINKY = Path(__file__).resolve().parents[1]
REPOSITORY = PINKY.parent
VENDOR_PARAMS = (
    REPOSITORY / "pinky_pro" / "pinky_navigation" / "params" / "nav2_params.yaml"
)

sys.path.insert(0, str(PINKY / "trihouse_pinky_fleet"))


def _vendor_goal_tolerances() -> tuple[float, float]:
    """벤더 params 에서 controller 의 goal checker 값을 읽는다."""
    if not VENDOR_PARAMS.exists():
        pytest.skip(f"벤더 params 가 없다: {VENDOR_PARAMS}")
    document = yaml.safe_load(VENDOR_PARAMS.read_text(encoding="utf-8"))

    xy = yaw = None

    def walk(node: object) -> None:
        nonlocal xy, yaw
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "xy_goal_tolerance" and isinstance(value, (int, float)):
                    xy = float(value)
                elif key == "yaw_goal_tolerance" and isinstance(value, (int, float)):
                    yaw = float(value)
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(document)
    if xy is None or yaw is None:
        pytest.skip("벤더 params 에서 goal tolerance 를 찾지 못했다")
    return xy, yaw


def test_the_precise_stop_check_is_not_tighter_than_nav2() -> None:
    """우리 기준이 더 좁으면 Nav2 가 끝낸 이동을 우리가 거절한다."""
    fleet_node = pytest.importorskip("trihouse_pinky_fleet.fleet_node")
    vendor_xy, vendor_yaw = _vendor_goal_tolerances()

    assert fleet_node.PRECISE_STOP_XY_TOLERANCE_M >= vendor_xy, (
        f"우리 기준 {fleet_node.PRECISE_STOP_XY_TOLERANCE_M} m 가 Nav2 의 "
        f"{vendor_xy} m 보다 좁다 — Nav2 가 정상 종료한 이동을 거절하게 되고, "
        "로봇은 더 갈 이유가 없어 재시도해도 같은 자리에 선다"
    )
    assert fleet_node.PRECISE_STOP_YAW_TOLERANCE_RAD >= vendor_yaw, (
        f"우리 yaw 기준 {fleet_node.PRECISE_STOP_YAW_TOLERANCE_RAD} rad 가 "
        f"Nav2 의 {vendor_yaw} rad 보다 좁다"
    )


def test_the_tolerance_is_not_absurdly_loose() -> None:
    """넓히는 것으로 문제를 덮지 않는다. Dock 인계는 물리적 한계가 있다.

    Pinky footprint 가 0.12 m 정사각이고 통로가 좁다. 도착 판정이 로봇 한 대
    크기를 넘어가면 "도착" 이 의미를 잃는다.
    """
    fleet_node = pytest.importorskip("trihouse_pinky_fleet.fleet_node")

    assert fleet_node.PRECISE_STOP_XY_TOLERANCE_M <= 0.25
    assert fleet_node.PRECISE_STOP_YAW_TOLERANCE_RAD <= 0.60
