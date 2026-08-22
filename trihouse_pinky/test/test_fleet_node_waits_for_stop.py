"""Nav2 SUCCEEDED 와 "정차 완료" 사이를 기다리는 계약.

Nav2 `NavigateToPose` 는 goal tolerance 안에 들어오면 SUCCEEDED 를 주고 속도 0 을
요구하지 않는다. `velocity_smoother` → `collision_monitor` 때문에 `cmd_vel` 은 그 뒤
0.2~0.5초 더 감쇠한다. 결과가 온 순간 한 번만 물으면 `TransportWorkflow` 가
`"waiting for stop"` 을 돌려주고 phase 가 `NAVIGATING` 에 갇힌다. 그러면 이후 모든
`ExecuteTransport` 가 `"robot is not idle"` 로 거절되고, 로봇은 재기동 전까지 못 쓴다.

`arrival.may_report_arrival` 이 그 대기를 위해 이미 존재하지만 `fleet_node` 가
쓰지 않았다. 이 파일은 그 배선을 고정한다.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NODE = ROOT / "trihouse_pinky_fleet" / "trihouse_pinky_fleet" / "fleet_node.py"


def _source() -> str:
    return NODE.read_text(encoding="utf-8")


def test_fleet_node_uses_the_arrival_settlement_helper():
    source = _source()

    assert "may_report_arrival" in source, (
        "정차 대기 판정을 쓰지 않는다 — Nav2 SUCCEEDED 를 그대로 도착으로 읽는다"
    )


def test_fleet_node_waits_before_reporting_arrival():
    """도착 보고 전에 정차를 기다려야 한다. 단일 호출이면 레이스가 남는다.

    대기 로직은 별도 메서드에 있으므로 `_execute` 안에서는 그 **호출**이
    도착 보고보다 앞서는지를 본다.
    """
    source = _source()

    wait_call = source.index("await self._settle_before_arrival()")
    report_call = source.index("arrived = self.workflow.nav_result(")

    assert wait_call < report_call, "정차를 기다리기 전에 도착을 보고한다"


def test_the_wait_is_bounded():
    """끝내 멈추지 않는 것은 실제 결함이다. 무한히 기다리지 않는다."""
    source = _source()

    assert "arrival_stop_timeout_s" in source, "정차 대기에 상한이 없다"
