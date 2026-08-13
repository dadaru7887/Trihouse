from pathlib import Path

import pytest

from trihouse_pinky_fleet.event_outbox import EventOutbox


def test_event_outbox_replays_after_reopen_and_deletes_only_after_ack(tmp_path: Path):
    path = tmp_path / "events.sqlite3"
    payload = {"event_id": "event-1", "type": "task_event", "value": 7}
    EventOutbox(path).enqueue(payload)

    reopened = EventOutbox(path)
    assert reopened.pending() == (payload,)
    reopened.mark_attempted("event-1")
    assert reopened.pending() == (payload,)
    reopened.acknowledge("event-1")
    assert reopened.pending() == ()


def test_event_id_payload_is_immutable_and_rejection_moves_to_dead_letter(tmp_path: Path):
    outbox = EventOutbox(tmp_path / "events.sqlite3")
    outbox.enqueue({"event_id": "event-1", "value": 1})

    with pytest.raises(ValueError, match="immutable"):
        outbox.enqueue({"event_id": "event-1", "value": 2})

    outbox.reject("event-1", "TASK_CONTEXT_MISMATCH")
    assert outbox.pending() == ()


def test_session_and_status_sequence_survive_gateway_restart(tmp_path: Path):
    path = tmp_path / "events.sqlite3"
    first = EventOutbox(path)

    assert first.session_id == EventOutbox(path).session_id
    assert first.next_status_sequence() == 1
    assert EventOutbox(path).next_status_sequence() == 2


def test_pending_event_keeps_compatible_terminal_status_evidence(tmp_path: Path):
    outbox = EventOutbox(tmp_path / "events.sqlite3")
    context = {"job_step_id": 20, "command_id": "command-1"}
    event = {
        "event_id": "event-1", "event_type": "arrived",
        "task_context": context,
    }
    active = {"sequence": 1, "navigation_state": 1, "task_context": context}
    succeeded = {"sequence": 2, "navigation_state": 2, "task_context": context}

    outbox.enqueue(event, status_payload=active)
    assert outbox.pending_records() == ((event, None),)
    outbox.attach_status_evidence(succeeded)
    assert outbox.pending_records() == ((event, succeeded),)


def test_capacity_is_a_soft_safety_gate_for_new_work(tmp_path: Path):
    outbox = EventOutbox(tmp_path / "events.sqlite3", max_pending=1)
    assert not outbox.is_full
    outbox.enqueue({"event_id": "event-1"})
    assert outbox.is_full
