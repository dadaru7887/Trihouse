"""Open-RMF 에너지 추정 port의 응답 검증·retry·fallback 테스트."""

import json
import tempfile
import unittest
from pathlib import Path

from control_tower.monitoring.measurement_log import MeasurementLogWriter
from control_tower.rmf_adapter.energy_estimator import (
    EnergyEstimateError,
    EstimateRequest,
    RmfEnergyEstimator,
    RmfEstimateResponse,
)


class EnergyEstimatorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.request = EstimateRequest(
            robot_id="PK-01",
            task_id="job-1",
            map_revision="map-v1",
            waypoint_ids=("FROZEN_PICKUP_01", "PACKING_HANDOVER_01"),
            current_state_of_charge=0.18,
            expected_loading_duration_s=30.0,
            expected_handover_duration_s=30.0,
            task_time_buffer_s=15.0,
        )

    def test_returns_authoritative_rmf_response(self) -> None:
        def service(request, timeout_s):
            self.assertEqual(2.0, timeout_s)
            return RmfEstimateResponse(True, 90.0, 165.0, 0.04, 0.14)

        result = RmfEnergyEstimator(service).estimate(self.request)

        self.assertEqual(165.0, result.total_duration_s)
        self.assertEqual(0.14, result.finish_state_of_charge)
        self.assertEqual("open_rmf", result.source)

    def test_records_authoritative_rmf_estimate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            writer = MeasurementLogWriter(
                root=directory, run_id="estimate-test", component="control_tower"
            )
            service = lambda request, timeout_s: RmfEstimateResponse(
                True, 90.0, 165.0, 0.04, 0.14
            )

            RmfEnergyEstimator(service, measurement_writer=writer).estimate(self.request)

            record = json.loads(
                (Path(directory) / "estimate-test" / "rmf_energy_estimates.jsonl")
                .read_text()
                .strip()
            )
            self.assertEqual("PK-01", record["robot_id"])
            self.assertEqual("job-1", record["task_id"])
            self.assertEqual(1, record["attempts"])
            self.assertEqual("open_rmf", record["source"])
            self.assertEqual(0.14, record["finish_state_of_charge"])

    def test_timeout_retries_once(self) -> None:
        calls = 0

        def service(request, timeout_s):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise TimeoutError
            return RmfEstimateResponse(True, 90.0, 165.0, 0.04, 0.14)

        result = RmfEnergyEstimator(service).estimate(self.request)

        self.assertEqual(2, calls)
        self.assertEqual("open_rmf", result.source)

    def test_two_timeouts_are_unavailable_without_fallback(self) -> None:
        def service(request, timeout_s):
            raise TimeoutError

        with self.assertRaisesRegex(EnergyEstimateError, "unavailable"):
            RmfEnergyEstimator(service).estimate(self.request)

    def test_invalid_soc_and_unavailable_route_are_rejected(self) -> None:
        invalid_soc = lambda request, timeout_s: RmfEstimateResponse(True, 1, 76, 0, 1.1)
        unavailable = lambda request, timeout_s: RmfEstimateResponse(False, 0, 0, 0, 0)

        with self.assertRaisesRegex(EnergyEstimateError, "SOC"):
            RmfEnergyEstimator(invalid_soc).estimate(self.request)
        with self.assertRaisesRegex(EnergyEstimateError, "route"):
            RmfEnergyEstimator(unavailable).estimate(self.request)

    def test_server_failure_preserves_reason_code_and_detail(self) -> None:
        response = RmfEstimateResponse(
            False,
            0.0,
            0.0,
            0.0,
            0.0,
            "RMF_FLEET_STATE_STALE",
            "last fleet state exceeded three seconds",
        )

        with self.assertRaises(EnergyEstimateError) as caught:
            RmfEnergyEstimator(lambda request, timeout_s: response).estimate(
                self.request
            )

        self.assertEqual("RMF_FLEET_STATE_STALE", caught.exception.reason_code)
        self.assertIn("three seconds", str(caught.exception))

    def test_explicit_fallback_uses_total_time_consumption(self) -> None:
        def service(request, timeout_s):
            raise TimeoutError

        result = RmfEnergyEstimator(
            service,
            allow_fallback=True,
            consumption_percent_per_minute=2.0,
            safety_margin_percent=1.0,
        ).estimate(self.request, fallback_travel_duration_s=45.0)

        # 전체 120초 = 2분, 2%/분 + 1% margin -> 18%에서 13%.
        self.assertAlmostEqual(120.0, result.total_duration_s)
        self.assertAlmostEqual(0.13, result.finish_state_of_charge)
        self.assertEqual("poc_time_fallback", result.source)

    def test_records_failure_without_hiding_estimation_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            writer = MeasurementLogWriter(
                root=directory, run_id="failure-test", component="control_tower"
            )

            with self.assertRaises(EnergyEstimateError):
                RmfEnergyEstimator(
                    lambda request, timeout_s: (_ for _ in ()).throw(TimeoutError()),
                    measurement_writer=writer,
                ).estimate(self.request)

            record = json.loads(
                (Path(directory) / "failure-test" / "rmf_energy_estimates.jsonl")
                .read_text()
                .strip()
            )
            self.assertEqual(2, record["attempts"])
            self.assertFalse(record["success"])
            self.assertEqual(
                "RMF_ENERGY_ESTIMATE_UNAVAILABLE", record["reason_code"]
            )


if __name__ == "__main__":
    unittest.main()
