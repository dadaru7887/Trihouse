import json
from pathlib import Path

from vision_ai.robot.recovery.memory.queue import RecoveryMessage, enqueue, pending
from vision_ai.robot.recovery.memory.sender import send_pending


MESSAGE_ID = "33333333-3333-4333-8333-333333333333"


def message() -> RecoveryMessage:
    return RecoveryMessage(MESSAGE_ID, "recovery_step_completion", "/complete", {"value": 1})


def test_enqueue_is_restart_discoverable_and_carries_payload_hash(tmp_path: Path) -> None:
    path = enqueue(tmp_path, message())
    assert pending(tmp_path) == [path]
    envelope = json.loads(path.read_text(encoding="utf-8"))
    assert len(envelope["payload_sha256"]) == 64
    assert not list(tmp_path.glob("*.tmp"))


def test_matching_ack_removes_pending_file(tmp_path: Path) -> None:
    enqueue(tmp_path, message())
    report = send_pending(tmp_path, "http://gateway", transport=lambda *_: (
        200, {"message_id": MESSAGE_ID, "acknowledged": True}
    ))
    assert report.acknowledged == (MESSAGE_ID,)
    assert pending(tmp_path) == []


def test_timeout_preserves_message_and_conflict_moves_dead_letter(tmp_path: Path) -> None:
    enqueue(tmp_path, message())
    report = send_pending(tmp_path, "http://gateway", transport=lambda *_: (_ for _ in ()).throw(TimeoutError()), sleep=lambda _: None)
    assert report.pending == (MESSAGE_ID,)
    assert pending(tmp_path)
    report = send_pending(tmp_path, "http://gateway", transport=lambda *_: (409, {}))
    assert report.dead_letter == (MESSAGE_ID,)
    assert (tmp_path / "dead_letter" / f"{MESSAGE_ID}.json").is_file()
