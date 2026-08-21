import pytest

from trihouse_omx_hardware.ipc_protocol import (
    IpcProtocolError,
    ResultCache,
    decode_message,
    encode_message,
    validate_worker_command,
)
from trihouse_omx_hardware.worker_server import WorkerCommandProcessor


def command(**overrides):
    value = {
        "schema_version": 1,
        "command_uuid": "cmd-1",
        "kind": "load",
        "job_id": 7,
        "job_step_id": 30,
        "assignment_revision": 1,
        "omx_id": "OMX_01",
        "temperature_zone": "chilled",
        "items": [{"job_item_id": 11, "product_code": "SKU-MILK", "quantity": 1}],
    }
    value.update(overrides)
    return value


def test_ndjson_round_trip_is_deterministic() -> None:
    encoded = encode_message(command())

    assert encoded.endswith(b"\n")
    assert decode_message(encoded) == command()
    assert encode_message(decode_message(encoded)) == encoded


def test_worker_rejects_a_command_for_the_other_physical_arm() -> None:
    with pytest.raises(IpcProtocolError, match="DEVICE_MISMATCH"):
        validate_worker_command(command(omx_id="OMX_02"), local_device_id="OMX_01")


def test_malformed_and_oversized_frames_fail_closed() -> None:
    with pytest.raises(IpcProtocolError):
        decode_message(b"not-json\n")
    with pytest.raises(IpcProtocolError):
        decode_message(b"{}")
    with pytest.raises(IpcProtocolError):
        decode_message(b" " * 1_048_577 + b"\n")


def test_result_cache_replays_only_the_same_command() -> None:
    cache = ResultCache()
    result = {"success": True, "command_uuid": "cmd-1"}
    cache.store(command(), result)

    assert cache.lookup(command()) == result
    with pytest.raises(IpcProtocolError, match="COMMAND_UUID_CONFLICT"):
        cache.lookup(command(job_step_id=31))


def test_worker_processor_replays_result_without_repeating_motion() -> None:
    calls = []

    def execute(value):
        calls.append(value)
        return {"success": True, "command_uuid": value["command_uuid"], "items": []}

    processor = WorkerCommandProcessor("OMX_01", execute)

    first = processor.process(command())
    replay = processor.process(command())

    assert replay == first
    assert len(calls) == 1
