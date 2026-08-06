import os
from pathlib import Path
import sys
import time

import pytest

from trihouse_pinky_vision.process_supervisor import ProcessSupervisor, RestartBackoff


FIXTURES = Path(__file__).parent / 'fixtures'


def wait_for(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.02)
    raise AssertionError('condition was not met before timeout')


def commands(exit_after=0):
    camera = [sys.executable, str(FIXTURES / 'fake_camera.py')]
    publisher = [sys.executable, str(FIXTURES / 'fake_publisher.py')]
    if exit_after:
        publisher.extend(['--exit-after', str(exit_after)])
    return camera, publisher


def test_forwards_camera_data_and_collects_publisher_progress():
    camera, publisher = commands()
    supervisor = ProcessSupervisor(camera, publisher, sigint_timeout=0.2, sigterm_timeout=0.2)
    try:
        supervisor.start()

        def progressed():
            current = supervisor.poll(time.monotonic())
            return current if current.progress is not None else None

        snapshot = wait_for(progressed)

        assert snapshot.processes_alive
        assert snapshot.progress.frame_count > 0
        assert snapshot.total_encoded_bytes is None or snapshot.total_encoded_bytes > 0
    finally:
        supervisor.stop()


def test_detects_publisher_exit_and_reaps_both_children():
    camera, publisher = commands(exit_after=1)
    supervisor = ProcessSupervisor(camera, publisher, sigint_timeout=0.2, sigterm_timeout=0.2)
    supervisor.start()
    pids = supervisor.child_pids

    def exited():
        current = supervisor.poll(time.monotonic())
        return current if not current.processes_alive else None

    snapshot = wait_for(exited)
    supervisor.stop()

    assert snapshot.exit_reason.startswith('publisher_exit:7')
    for pid in pids:
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)


def test_restart_backoff_is_bounded_and_resets_after_thirty_healthy_seconds():
    backoff = RestartBackoff((1.0, 2.0, 4.0, 8.0, 16.0, 30.0), reset_after=30.0)

    assert [backoff.record_failure(float(i)) for i in range(7)] == [
        1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 30.0,
    ]
    backoff.record_healthy(100.0)
    backoff.record_healthy(130.0)

    assert backoff.record_failure(131.0) == 1.0
