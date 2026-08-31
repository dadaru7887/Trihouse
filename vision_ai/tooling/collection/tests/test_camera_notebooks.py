import json
from pathlib import Path

import pytest


# 노트북은 한 단계 위(tooling/collection/)에 있고 여기에는 시험만 둔다.
COLLECTION_DIR = Path(__file__).resolve().parents[1]
RECORDING_NOTEBOOK = COLLECTION_DIR / "camera_recording.ipynb"
SLICING_NOTEBOOK = COLLECTION_DIR / "records_slicing.ipynb"


class MemorySocket:
    def __init__(self):
        self.buffer = bytearray()
        self.offset = 0

    def sendall(self, payload: bytes) -> None:
        self.buffer.extend(payload)

    def recv(self, size: int) -> bytes:
        payload = bytes(self.buffer[self.offset : self.offset + size])
        self.offset += len(payload)
        return payload


def load_notebook(path: Path) -> dict:
    with path.open(encoding="utf-8") as notebook_file:
        notebook = json.load(notebook_file)
    assert notebook["nbformat"] == 4
    assert any(cell["cell_type"] == "markdown" for cell in notebook["cells"])
    assert any(cell["cell_type"] == "code" for cell in notebook["cells"])
    return notebook


def load_tagged_namespace(path: Path, tag: str = "testable") -> dict:
    notebook = load_notebook(path)
    sources = []
    for cell in notebook["cells"]:
        tags = cell.get("metadata", {}).get("tags", [])
        if cell["cell_type"] == "code" and tag in tags:
            sources.append("".join(cell["source"]))
    assert sources, f"{path.name} has no {tag!r} code cells"
    namespace = {"__name__": "notebook_test"}
    exec(compile("\n\n".join(sources), str(path), "exec"), namespace)
    return namespace


@pytest.mark.parametrize("path", [RECORDING_NOTEBOOK, SLICING_NOTEBOOK])
def test_every_code_cell_compiles(path: Path):
    notebook = load_notebook(path)
    for index, cell in enumerate(notebook["cells"]):
        if cell["cell_type"] == "code":
            compile("".join(cell["source"]), f"{path.name}:cell-{index}", "exec")


def test_recording_notebook_protocol_round_trip():
    ns = load_tagged_namespace(RECORDING_NOTEBOOK)
    transport = MemorySocket()
    metadata = {"camera_id": "fixed_01", "width": 640, "height": 480, "fps": 30}
    ns["send_handshake"](transport, metadata)
    assert ns["recv_handshake"](transport) == metadata

    ns["send_frame"](transport, 123456789, b"jpeg-data")
    assert ns["recv_frame"](transport) == (123456789, b"jpeg-data")

    ns["send_end"](transport)
    assert ns["recv_frame"](transport) is None


def test_recording_notebook_rejects_duplicate_or_invalid_ports():
    ns = load_tagged_namespace(RECORDING_NOTEBOOK)
    assert ns["validate_port_map"]({"pinky_01": 5001, "fixed_01": 5002}) is None
    with pytest.raises(ValueError, match="중복"):
        ns["validate_port_map"]({"pinky_01": 5001, "fixed_01": 5001})
    with pytest.raises(ValueError, match="1~65535"):
        ns["validate_port_map"]({"pinky_01": 70000})


def test_slicing_notebook_builds_common_target_times():
    ns = load_tagged_namespace(SLICING_NOTEBOOK)
    assert ns["build_target_times"](3.0, 1.0, 0.0, 0.0) == [0.0, 1.0, 2.0]
    assert ns["build_target_times"](3.0, 0.5, 0.5, 0.5) == [0.5, 1.0, 1.5, 2.0]


def test_slicing_notebook_validates_intervals_and_offsets():
    ns = load_tagged_namespace(SLICING_NOTEBOOK)
    with pytest.raises(ValueError, match="INTERVAL_SEC"):
        ns["build_target_times"](3.0, 0.0, 0.0, 0.0)
    with pytest.raises(ValueError, match="구간"):
        ns["build_target_times"](3.0, 1.0, 2.0, 2.0)
