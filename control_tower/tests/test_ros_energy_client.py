import unittest

from control_tower.rmf_adapter.energy_estimator import EstimateRequest
from control_tower.rmf_adapter.ros_energy_client import RosEstimateService
from trihouse_interfaces.srv import EstimateTaskEnergy


class CompletedFuture:
    def __init__(self, result):
        self._result = result

    def done(self):
        return True

    def result(self):
        return self._result


class RecordingClient:
    def __init__(self, response):
        self.response = response
        self.last_request = None

    def call_async(self, request):
        self.last_request = request
        return CompletedFuture(self.response)


class RecordingNode:
    def __init__(self, response):
        self.client = RecordingClient(response)

    def create_client(self, service_type, service_name):
        assert service_type is EstimateTaskEnergy
        assert service_name == "/trihouse/rmf/estimate_task_energy"
        return self.client


class RosEnergyClientTest(unittest.TestCase):
    def test_maps_request_and_response_fields(self):
        response = EstimateTaskEnergy.Response()
        response.success = True
        response.travel_duration_s = 90.0
        response.total_duration_s = 165.0
        response.change_in_charge = 0.04
        response.finish_state_of_charge = 0.76
        response.reason_code = "OK"
        response.detail = "estimated"
        node = RecordingNode(response)
        service = RosEstimateService(
            node,
            spin_until_future_complete=lambda node, future, timeout_sec: None,
        )
        request = EstimateRequest(
            robot_id="tinyRobot1",
            task_id="job-1",
            map_revision="office",
            waypoint_ids=("pantry", "hardware_2"),
            current_state_of_charge=0.8,
            expected_loading_duration_s=30.0,
            expected_handover_duration_s=20.0,
            task_time_buffer_s=10.0,
        )

        result = service(request, 2.0)

        sent = node.client.last_request
        self.assertEqual("tinyRobot1", sent.robot_id)
        self.assertEqual(["pantry", "hardware_2"], sent.waypoint_ids)
        self.assertEqual(30.0, sent.expected_loading_duration_s)
        self.assertEqual("OK", result.reason_code)
        self.assertEqual("estimated", result.detail)


if __name__ == "__main__":
    unittest.main()
