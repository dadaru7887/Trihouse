"""ArUco 관측이 FMS를 거쳐 카메라 소속 Pinky에만 전달되는 계약."""

import asyncio
import json
from types import SimpleNamespace
import unittest

from pydantic import ValidationError

from fms_gateway.app.main import create_app
from fms_gateway.app.models import MarkerObservationReport
from fms_gateway.app.tcp_protocol import RobotLinkRegistry


ROUTE = "/internal/v1/vision/marker-observations"


class _Writer:
    def __init__(self) -> None:
        self.lines: list[dict] = []

    def write(self, payload: bytes) -> None:
        self.lines.append(json.loads(payload.decode("utf-8")))

    async def drain(self) -> None:
        return None


class _Repository:
    def ping(self) -> bool:
        return True

    def list_registered_robot_ids(self):
        return ("PK_01", "PK_02")


def _app(links: RobotLinkRegistry):
    app = create_app(_Repository())
    app.state.robot_links = links
    return app


def _endpoint(app):
    return next(
        route.endpoint
        for route in app.routes
        if getattr(route, "path", None) == ROUTE
    )


def _payload() -> dict:
    return {
        "camera_id": "CAM-PK-02",
        "marker_family": "DICT_5X5_50",
        "marker_id": "0",
        "translation_m": {"x": 0.4, "y": 0.02, "z": 0.8},
        "confidence": 0.9,
        "ttl_ms": 250,
        "observed_at_ms": 1000,
    }


class MarkerObservationPushTest(unittest.TestCase):
    def test_marker_observation_routes_pk02_camera_to_attached_robot(self) -> None:
        links = RobotLinkRegistry()
        writer = _Writer()
        links.attach("PK_02", writer)
        app = _app(links)
        response = asyncio.run(
            _endpoint(app)(MarkerObservationReport(**_payload()), SimpleNamespace(app=app))
        )

        self.assertEqual(
            response.model_dump(), {"robot_id": "PK_02", "delivered": True}
        )
        self.assertEqual(writer.lines, [{"type": "marker_observation", **_payload()}])

    def test_marker_observation_rejects_unmeasured_dictionary_and_robot_override(self) -> None:
        with self.assertRaises(ValidationError):
            MarkerObservationReport(**{**_payload(), "marker_family": "DICT_4X4_50"})
        with self.assertRaises(ValidationError):
            MarkerObservationReport(**{**_payload(), "robot_id": "PK_01"})
