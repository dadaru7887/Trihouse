"""시뮬 층 teardown 이 무엇을 죽이고 무엇을 남기는가.

패턴 목록에 `trihouse_rmf_bridge` 나 `control_tower.task_manager` 같은 **경로
이름**이 들어 있다. `pgrep -f` 는 명령줄 전체를 보므로, 그 경로를 인자로 받은
`pytest` 나 `colcon` 명령줄이 그대로 걸린다. 2026-08-18 세션에서 실제로 그렇게
테스트 실행이 통째로 죽었다 — teardown 이 자기 일이 아닌 프로세스를 죽인 것이다.

여기서는 실제 프로세스를 죽이지 않는다. 스크립트가 후보를 고르는 규칙만 본다.
"""

import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "sim_teardown.sh"


def _selects(command: list[str], *, script: Path = SCRIPT) -> bool:
    """스크립트의 선택 규칙이 이 명령줄을 후보로 고르는가.

    `--dry-run` 으로 돌려 아무것도 죽이지 않고 후보만 받는다. 대상 프로세스가
    `/proc` 에 확실히 보인 뒤에 한 번만 조회한다 — 반복 호출은 그 자체로 느리고,
    실패를 "아직 안 보임" 과 구분하지 못한다.
    """
    victim = subprocess.Popen(command)
    try:
        cmdline = Path(f"/proc/{victim.pid}/cmdline")
        for _ in range(100):
            if cmdline.exists() and cmdline.read_bytes():
                break
            time.sleep(0.05)
        else:  # pragma: no cover - 프로세스가 뜨지 않으면 테스트가 무의미하다
            pytest.fail("대상 프로세스가 /proc 에 나타나지 않았다")

        listing = subprocess.run(
            [str(script), "--dry-run"], capture_output=True, text=True
        )
        assert listing.returncode == 0, listing.stderr
        return str(victim.pid) in listing.stdout.split()
    finally:
        victim.terminate()
        victim.wait(timeout=5)


def test_a_test_run_over_the_ros_packages_is_not_a_teardown_target() -> None:
    """teardown 은 시뮬 층만 내린다. 테스트 실행은 그 층이 아니다."""
    assert not _selects(
        [
            sys.executable,
            "-c",
            "import time; time.sleep(30)  # pytest -q trihouse_rmf_bridge/test "
            "control_tower/tests trihouse_pinky/trihouse_pinky_bringup/test",
        ]
    )


def test_a_colcon_build_of_a_listed_package_is_not_a_teardown_target() -> None:
    """빌드를 중간에 죽이면 install 이 반쯤 쓰인 채 남는다."""
    assert not _selects(
        [
            sys.executable,
            "-c",
            "import time; time.sleep(30)  # colcon build --packages-select "
            "trihouse_pinky_bringup --symlink-install",
        ]
    )


def test_a_real_simulation_process_is_still_a_teardown_target() -> None:
    """제외 규칙이 넓어져 정작 시뮬을 못 내리면 다음 측정이 전부 오염된다."""
    assert _selects(
        [
            sys.executable,
            "-c",
            "import time; time.sleep(30)  # ros2 run trihouse_pinky_fleet status_node",
        ]
    )


def test_dry_run_kills_nothing() -> None:
    """`--dry-run` 이 실제로 죽이면 이 테스트 파일 자체가 위험해진다."""
    victim = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)  # status_node"]
    )
    try:
        subprocess.run([str(SCRIPT), "--dry-run"], capture_output=True, text=True)
        time.sleep(0.5)
        assert victim.poll() is None
    finally:
        victim.terminate()
        victim.wait(timeout=5)


def test_the_script_documents_its_exclusions() -> None:
    """왜 제외하는지가 파일 안에 없으면 다음 사람이 다시 넣는다."""
    text = SCRIPT.read_text(encoding="utf-8")

    assert "EXCLUDE_PATTERNS" in text
    assert "pytest" in text


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))


def test_the_camera_streamer_is_a_teardown_target() -> None:
    """카메라 송신 노드도 시뮬 층의 일부다. 남기면 세대가 겹친다.

    `trihouse_pinky_vision/camera_streamer` 가 패턴에 없어서 세대마다 살아남았다.
    2026-08-19 실측으로 **3개**가 동시에 떠 있었고, 그 유령 발행자 때문에
    `verify_robot_status.py` 가 `publishers=2` 를 보고 "이전 세대가 남았다" 로
    판정했다. 측정이 오염되면 그 위의 모든 판단이 흔들린다.
    """
    assert _selects(
        [
            sys.executable,
            "-c",
            "import time; time.sleep(30)",
            "/home/syw/Trihouse/install/trihouse_pinky_vision/lib/"
            "trihouse_pinky_vision/camera_streamer",
        ]
    )


def test_a_leaked_launch_is_still_a_target_even_with_a_pytest_path_in_its_arguments() -> None:
    """제외는 **실행 파일** 기준이어야 한다. 인자에 든 경로가 아니다.

    `test_vision_launch.py` 는 fixture 를 pytest 임시 디렉터리에 만들고 그 경로를
    launch 인자로 넘긴다. 그 테스트가 실패하면 launch 프로세스가 남는데, 명령줄이
    이렇게 생겼다.

    ```
    python3 /opt/ros/jazzy/bin/ros2 launch trihouse_pinky_vision vision.launch.py \\
        config_file:=/tmp/pytest-of-syw/pytest-122/.../fixture.yaml
    ```

    `EXCLUDE_PATTERNS` 가 부분 문자열로 걸리므로 `/tmp/pytest-of-...` 때문에
    **pytest 실행으로 오인되어 살아남는다.** 2026-08-19 실측에서 그렇게 남은
    `camera_streamer` 3개가 각자 RTSP 발행자를 계속 재시작해 RTF 를 0.09 까지
    떨어뜨렸고, Nav2 controller 가 20 Hz 를 놓쳐 주행이 실패했다.

    누수 자체(그 테스트가 프로세스를 남기는 것)는 별개 문제다. 여기서는 teardown
    이 그것을 치울 수 있어야 한다는 것만 고정한다.
    """
    assert _selects(
        [
            sys.executable,
            "-c",
            "import time; time.sleep(30)",
            "trihouse_pinky_vision",
            "config_file:=/tmp/pytest-of-someone/pytest-1/x/fixture.yaml",
        ]
    )


def test_a_pytest_run_is_still_excluded_when_invoked_through_python() -> None:
    """`python -m pytest` 도 보호해야 한다. 실행 파일 판정이 그것도 덮는지 본다."""
    assert not _selects(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "trihouse_pinky_vision",
        ]
    )
