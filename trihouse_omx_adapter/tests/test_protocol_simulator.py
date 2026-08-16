"""두 OMX 시뮬레이터가 생산 메시지 계약 그대로 동작하는지 검증한다."""

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent))

from trihouse_omx_adapter.protocol_simulator import (  # noqa: E402
    OmxProtocolSimulator,
    OmxSimulatorError,
)


def prepare_command(
    *,
    omx_id: str = "OMX_01",
    revision: int = 5,
    command_uuid: str = "cmd-1",
    job_step_id: int = 11,
    expected_items: tuple[str, ...] = ("SKU-MILK",),
    marker_id: int = 1,
    kind: str = "prepare",
) -> dict:
    return {
        "command_uuid": command_uuid,
        "kind": kind,
        "job_step_id": job_step_id,
        "assignment_revision": revision,
        "omx_id": omx_id,
        "expected_items": list(expected_items),
        "marker_id": marker_id,
    }


@pytest.fixture
def simulator() -> OmxProtocolSimulator:
    return OmxProtocolSimulator(omx_id="OMX_01")


def test_simulator_emits_real_readiness_sequence(
    simulator: OmxProtocolSimulator,
) -> None:
    events = simulator.execute(prepare_command(omx_id="OMX_01", revision=5))

    assert [event.state for event in events] == ["PREPARING", "PICKING", "OMX_READY"]
    assert all(event.assignment_revision == 5 for event in events)
    assert all(event.omx_id == "OMX_01" for event in events)
    assert all(event.command_uuid == "cmd-1" for event in events)


def test_two_instances_answer_only_for_their_own_omx_id() -> None:
    first = OmxProtocolSimulator(omx_id="OMX_01")
    second = OmxProtocolSimulator(omx_id="OMX_02")

    assert first.execute(prepare_command(omx_id="OMX_01"))[-1].state == "OMX_READY"
    with pytest.raises(OmxSimulatorError, match="OMX_ID_MISMATCH"):
        second.execute(prepare_command(omx_id="OMX_01"))


def test_stale_assignment_revision_is_rejected(
    simulator: OmxProtocolSimulator,
) -> None:
    simulator.execute(prepare_command(revision=5))
    simulator.execute(prepare_command(command_uuid="cmd-2", kind="reset", revision=5))

    with pytest.raises(OmxSimulatorError, match="STALE_ASSIGNMENT"):
        simulator.execute(prepare_command(command_uuid="cmd-3", revision=4))


def test_replayed_command_uuid_returns_the_first_event_sequence(
    simulator: OmxProtocolSimulator,
) -> None:
    first = simulator.execute(prepare_command())
    replay = simulator.execute(prepare_command())

    assert [event.state for event in replay] == [event.state for event in first]
    assert [event.sequence_no for event in replay] == [
        event.sequence_no for event in first
    ]


def test_incomplete_command_is_rejected_before_any_state_change(
    simulator: OmxProtocolSimulator,
) -> None:
    for field in (
        "command_uuid",
        "job_step_id",
        "assignment_revision",
        "omx_id",
        "expected_items",
        "marker_id",
    ):
        command = prepare_command()
        del command[field]
        with pytest.raises(OmxSimulatorError):
            simulator.execute(command)
    assert simulator.state == "IDLE"


def test_unknown_kind_is_rejected(simulator: OmxProtocolSimulator) -> None:
    with pytest.raises(OmxSimulatorError, match="UNSUPPORTED_COMMAND"):
        simulator.execute(prepare_command(kind="dance"))


def test_load_requires_a_prepared_pick_and_emits_the_load_sequence(
    simulator: OmxProtocolSimulator,
) -> None:
    with pytest.raises(OmxSimulatorError, match="NOT_PREPARED"):
        simulator.execute(prepare_command(command_uuid="cmd-load", kind="load"))

    simulator.execute(prepare_command())
    events = simulator.execute(prepare_command(command_uuid="cmd-load", kind="load"))

    assert [event.state for event in events] == ["LOADING", "LOAD_COMPLETE"]


def test_hold_and_reset_return_the_simulator_to_a_known_state(
    simulator: OmxProtocolSimulator,
) -> None:
    simulator.execute(prepare_command())
    held = simulator.execute(prepare_command(command_uuid="cmd-hold", kind="hold"))
    assert [event.state for event in held] == ["HELD"]
    assert simulator.state == "HELD"

    reset = simulator.execute(prepare_command(command_uuid="cmd-reset", kind="reset"))
    assert [event.state for event in reset] == ["IDLE"]
    assert simulator.state == "IDLE"


def test_simulator_emits_no_physical_ros_endpoint(
    simulator: OmxProtocolSimulator,
) -> None:
    """P0는 물리 OMX ROS endpoint를 흉내내지 않는다."""
    assert simulator.published_ros_topics() == ()


def test_events_are_monotonic_and_carry_the_step(
    simulator: OmxProtocolSimulator,
) -> None:
    events = simulator.execute(prepare_command(job_step_id=42))

    assert [event.sequence_no for event in events] == [1, 2, 3]
    assert all(event.job_step_id == 42 for event in events)


def test_simulator_process_runs_two_namespaces_without_real_motion() -> None:
    """OMX_01/OMX_02 프로세스가 실제 motion 없이 이벤트만 낸다."""
    import io
    import json

    from trihouse_omx_adapter.simulator_node import run

    for omx_id in ("OMX_01", "OMX_02"):
        sink = io.StringIO()
        source = io.StringIO(
            json.dumps(prepare_command(omx_id=omx_id)) + "\n"
            + json.dumps(prepare_command(omx_id="OMX_99")) + "\n"
        )
        run(OmxProtocolSimulator(omx_id=omx_id), source=source, sink=sink)
        lines = [json.loads(line) for line in sink.getvalue().splitlines()]

        assert [line.get("state") for line in lines[:3]] == [
            "PREPARING", "PICKING", "OMX_READY",
        ]
        assert all(line["omx_id"] == omx_id for line in lines[:3])
        assert all(line["model_lineage"] == "fake-act/p0-v1" for line in lines[:3])
        assert all(line["real_motion_emitted"] is False for line in lines[:3])
        assert lines[0]["act_stages"] == [
            "OBSERVE", "POLICY", "GRASP", "VERIFY", "HANDOVER",
        ]
        assert lines[3]["error"] == "OMX_ID_MISMATCH"
