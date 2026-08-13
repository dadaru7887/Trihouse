"""Contract tests for the pure outbound job-step template."""

from dataclasses import asdict

from control_tower.task_manager.outbound_sequence import outbound_segment_template


def test_outbound_segment_template_preserves_the_six_business_segments() -> None:
    """A reordered, merged, or wrongly targeted segment must fail this contract."""
    actual = tuple(asdict(step) for step in outbound_segment_template())

    assert actual == (
        {
            "step_no": 10,
            "executor_type": "mobile",
            "action_type": "navigate",
            "source": "current",
            "target": "inbound_waiting",
            "assigned_device_id": None,
        },
        {
            "step_no": 20,
            "executor_type": "mobile",
            "action_type": "navigate",
            "source": "inbound_waiting",
            "target": "OMX_01_station",
            "assigned_device_id": None,
        },
        {
            "step_no": 30,
            "executor_type": "arm",
            "action_type": "load",
            "source": "OMX_01_station",
            "target": "OMX_01_station",
            "assigned_device_id": "OMX_01",
        },
        {
            "step_no": 40,
            "executor_type": "mobile",
            "action_type": "navigate",
            "source": "OMX_01_station",
            "target": "narrow_waiting",
            "assigned_device_id": None,
        },
        {
            "step_no": 50,
            "executor_type": "mobile",
            "action_type": "navigate",
            "source": "narrow_waiting",
            "target": "outbound_waiting",
            "assigned_device_id": None,
        },
        {
            "step_no": 60,
            "executor_type": "fms",
            "action_type": "handover",
            "source": "outbound_waiting",
            "target": "outbound_waiting",
            "assigned_device_id": None,
        },
    )


def test_each_template_call_returns_a_fresh_immutable_tuple() -> None:
    """Consumers must not be able to mutate global sequence state between jobs."""
    first = outbound_segment_template()
    second = outbound_segment_template()

    assert isinstance(first, tuple)
    assert first == second
    assert first is not second
