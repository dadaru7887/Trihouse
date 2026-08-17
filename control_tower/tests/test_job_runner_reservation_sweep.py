"""러너가 배정을 계산하기 전에 만료된 예약을 먼저 걷어내는지.

순서가 뒤집히면 그 주기의 배정은 이미 죽은 예약이 쥔 자원을 계속 비어 있지 않다고
읽는다. 그러면 `no free robot` 이 한 주기 더 반복되고, 실패한 시험마다 로봇이 한 대씩
묶인다(설계 8절 4번).
"""

import pytest

from control_tower.task_manager.job_runner import JobRunner

from control_tower.tests.test_job_runner import FakeGateway, _order_job


class _SweepingGateway(FakeGateway):
    """호출 순서를 기록한다. 무엇을 하는가보다 언제 하는가가 계약이다."""

    def __init__(self, details, devices=None, *, sweep_error=None):
        super().__init__(details, devices)
        self.calls: list[str] = []
        self.sweep_error = sweep_error
        self.sweeps = 0

    def expire_reservations(self):
        self.calls.append("expire")
        self.sweeps += 1
        if self.sweep_error is not None:
            raise self.sweep_error
        return {"expired": []}

    def list_jobs(self):
        self.calls.append("list_jobs")
        return super().list_jobs()

    def assign_job_resources(self, job_id, request):
        self.calls.append("assign")
        return super().assign_job_resources(job_id, request)


def test_the_sweep_runs_before_anything_is_assigned() -> None:
    gateway = _SweepingGateway([_order_job(1)])

    JobRunner(gateway).run_once()

    assert gateway.calls[0] == "expire"
    assert "assign" in gateway.calls
    assert gateway.calls.index("expire") < gateway.calls.index("assign")


def test_the_sweep_runs_even_when_there_is_nothing_to_advance() -> None:
    """자원을 쥔 job 이 하나도 없어도 죽은 예약은 걷어야 한다."""
    gateway = _SweepingGateway([])

    JobRunner(gateway).run_once()

    assert gateway.sweeps == 1


def test_what_the_sweep_released_is_reported() -> None:
    gateway = _SweepingGateway([_order_job(1)])
    gateway.expire_reservations = lambda: {
        "expired": [
            {"reservation_id": 2, "job_id": 2, "device_id": "PK_01", "job_active": True},
            {"reservation_id": 5, "job_id": 3, "device_id": "PK_02", "job_active": False},
        ]
    }

    report = JobRunner(gateway).run_once()

    assert report.expired == (2, 5)
    assert report.blocked == (
        "job 2: reservation 2 expired while the job still had work left",
    )


def test_a_failing_sweep_does_not_stop_the_cycle() -> None:
    """회수가 실패해도 이미 배정된 job 은 계속 전진해야 한다."""
    gateway = _SweepingGateway(
        [_order_job(1)], sweep_error=RuntimeError("gateway is restarting")
    )

    report = JobRunner(gateway).run_once()

    assert report.errors == ("reservation sweep: gateway is restarting",)
    assert report.assigned == (1,)


def test_a_gateway_without_the_sweep_route_still_runs() -> None:
    """구버전 Gateway 를 상대로도 러너가 죽지 않는다."""
    gateway = FakeGateway([_order_job(1)])

    report = JobRunner(gateway).run_once()

    assert report.assigned == (1,)
    assert report.expired == ()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
