"""Pure, ordered template for the minimal outbound transport segment."""

from dataclasses import dataclass


@dataclass(frozen=True)
class OutboundStepTemplate:
    """One logical step before runtime location IDs and a mobile are assigned."""

    step_no: int
    executor_type: str
    action_type: str
    source: str
    target: str
    assigned_device_id: str | None = None


def outbound_segment_template() -> tuple[OutboundStepTemplate, ...]:
    """Return a fresh immutable description of the minimal outbound sequence."""

    return (
        OutboundStepTemplate(10, "mobile", "navigate", "current", "inbound_waiting"),
        OutboundStepTemplate(
            20,
            "mobile",
            "navigate",
            "inbound_waiting",
            "OMX_01_station",
        ),
        OutboundStepTemplate(
            30,
            "arm",
            "load",
            "OMX_01_station",
            "OMX_01_station",
            "OMX_01",
        ),
        OutboundStepTemplate(
            40,
            "mobile",
            "navigate",
            "OMX_01_station",
            "narrow_waiting",
        ),
        OutboundStepTemplate(
            50,
            "mobile",
            "navigate",
            "narrow_waiting",
            "outbound_waiting",
        ),
        OutboundStepTemplate(
            60,
            "fms",
            "handover",
            "outbound_waiting",
            "outbound_waiting",
        ),
    )
