import ast
import json
from pathlib import Path
import re

import cv2
import numpy as np
import pytest


NOTEBOOK_PATH = Path(__file__).resolve().with_name(
    "test_pinky_qr_aruco_notebook.ipynb"
)


@pytest.fixture(scope="module")
def notebook():
    return json.loads(NOTEBOOK_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def notebook_namespace(notebook):
    namespace = {}
    for cell in notebook["cells"]:
        tags = cell.get("metadata", {}).get("tags", [])
        if cell["cell_type"] == "code" and "testable" in tags:
            exec(compile("".join(cell["source"]), "<notebook-cell>", "exec"), namespace)
    return namespace


def _qr_frame(payload):
    encoder = cv2.QRCodeEncoder_create()
    qr = encoder.encode(payload)
    qr = cv2.resize(qr, (300, 300), interpolation=cv2.INTER_NEAREST)
    return cv2.copyMakeBorder(
        cv2.cvtColor(qr, cv2.COLOR_GRAY2BGR),
        80,
        80,
        80,
        80,
        cv2.BORDER_CONSTANT,
        value=(255, 255, 255),
    )


def _aruco_frame(dictionary_id, marker_id):
    dictionary = cv2.aruco.getPredefinedDictionary(dictionary_id)
    if hasattr(cv2.aruco, "generateImageMarker"):
        marker = cv2.aruco.generateImageMarker(dictionary, marker_id, 240)
    else:
        marker = np.zeros((240, 240), dtype=np.uint8)
        cv2.aruco.drawMarker(dictionary, marker_id, 240, marker, 1)
    frame = np.full((400, 400, 3), 255, dtype=np.uint8)
    frame[80:320, 80:320] = cv2.cvtColor(marker, cv2.COLOR_GRAY2BGR)
    return frame


def test_qr_detector_decodes_generated_payload(notebook_namespace):
    _, results = notebook_namespace["detect_qr_codes"](
        _qr_frame("TRIHOUSE-QR-001")
    )

    assert [item["data"] for item in results] == ["TRIHOUSE-QR-001"]


def test_5x5_aruco_detector_finds_marker_id_23(notebook_namespace):
    dictionary_id = cv2.aruco.DICT_5X5_100

    _, results = notebook_namespace["detect_aruco_markers"](
        _aruco_frame(dictionary_id, 23),
        [("DICT_5X5_100", dictionary_id, 0.03)],
    )

    assert [(item["dictionary"], item["id"]) for item in results] == [
        ("DICT_5X5_100", 23)
    ]


def test_aruco_pose_is_only_reported_with_calibration(notebook_namespace):
    dictionary_id = cv2.aruco.DICT_5X5_100
    frame = _aruco_frame(dictionary_id, 23)
    specs = [("DICT_5X5_100", dictionary_id, 0.03)]

    _, uncalibrated = notebook_namespace["detect_aruco_markers"](frame, specs)
    assert uncalibrated[0]["rvec"] is None
    assert uncalibrated[0]["tvec_m"] is None

    camera_matrix = np.array(
        [[600.0, 0.0, 200.0], [0.0, 600.0, 200.0], [0.0, 0.0, 1.0]],
        dtype=np.float64,
    )
    dist_coeffs = np.zeros((5, 1), dtype=np.float64)
    _, calibrated = notebook_namespace["detect_aruco_markers"](
        frame,
        specs,
        camera_matrix,
        dist_coeffs,
    )

    assert len(calibrated[0]["rvec"]) == 3
    assert len(calibrated[0]["tvec_m"]) == 3
    assert calibrated[0]["tvec_m"][2] > 0


def test_notebook_is_valid_and_all_code_cells_compile(notebook):
    assert notebook["nbformat"] == 4
    for index, cell in enumerate(notebook["cells"]):
        if cell["cell_type"] == "code":
            compile("".join(cell["source"]), f"cell-{index}", "exec")


def test_nbformat_45_cells_have_unique_valid_ids(notebook):
    cell_ids = [cell.get("id") for cell in notebook["cells"]]

    assert all(
        isinstance(cell_id, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", cell_id)
        for cell_id in cell_ids
    )
    assert len(cell_ids) == len(set(cell_ids))


def test_operational_cells_cover_capture_calibration_live_and_cleanup(notebook):
    roles = {
        cell.get("metadata", {}).get("trihouse_role")
        for cell in notebook["cells"]
    }

    assert {"capture", "calibrate", "live-detection", "cleanup"} <= roles


def test_configured_checkerboard_has_9_by_7_internal_corners(notebook):
    settings_cell = next(
        cell for cell in notebook["cells"] if cell.get("id") == "environment-settings"
    )
    tree = ast.parse("".join(settings_cell["source"]))
    assignment = next(
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "CHECKERBOARD"
            for target in node.targets
        )
    )

    assert ast.literal_eval(assignment.value) == (9, 7)
