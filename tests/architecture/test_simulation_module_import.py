"""Simulation modules must win over dependency-local test packages."""

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_omx_action_server_imports_with_the_bringup_pythonpath() -> None:
    completed = subprocess.run(
        [
            "bash",
            "-c",
            "source /opt/ros/jazzy/setup.bash; source install/setup.bash; "
            "source pinky_pro/install/setup.bash; "
            "export PYTHONPATH=\"$PWD/trihouse_omx_adapter:$PWD${PYTHONPATH:+:$PYTHONPATH}\"; "
            "/usr/bin/python3 -c 'import tests.simulation.omx.action_server'",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
