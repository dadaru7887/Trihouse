import json

from control_tower.rmf_adapter.energy_estimator import RmfEstimateResponse
from control_tower.rmf_adapter.estimate_energy_cli import main


def test_cli_prints_machine_readable_success(capsys):
    def service(request, timeout_s):
        assert request.robot_id == "tinyRobot1"
        assert request.waypoint_ids == ("pantry", "hardware_2")
        assert timeout_s == 2.0
        return RmfEstimateResponse(
            True, 90.0, 165.0, 0.04, 0.76, "OK", "estimated"
        )

    code = main(
        [
            "--robot-id",
            "tinyRobot1",
            "--waypoint",
            "pantry",
            "--waypoint",
            "hardware_2",
        ],
        service=service,
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["success"] is True
    assert payload["finish_state_of_charge"] == 0.76
    assert payload["reason_code"] == "OK"


def test_cli_returns_one_for_server_failure(capsys):
    response = RmfEstimateResponse(
        False,
        0.0,
        0.0,
        0.0,
        0.0,
        "RMF_WAYPOINT_NOT_FOUND",
        "missing waypoint",
    )

    code = main(
        ["--waypoint", "missing"],
        service=lambda request, timeout_s: response,
    )

    assert code == 1
    assert json.loads(capsys.readouterr().out)["reason_code"] == (
        "RMF_WAYPOINT_NOT_FOUND"
    )
