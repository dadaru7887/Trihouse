"""관제 화면이 예약 이상을 읽고 사람이 닫을 수 있는지.

설계 10절이 확인한 공백이다. 이상을 여는 것만으로는 끝나지 않는다 — 목록과 승인
경로가 없으면 열린 이상을 아무도 닫지 못해 job 이 영구히 멈춘다. 지금 job 2·3 이
자원을 붙잡고 있는 것과 같은 종류의 교착을 새로 만드는 셈이다.

이 화면은 DB 를 직접 보지 않는다. FMS Gateway 가 원장의 단일 기록자이므로 UI 서버는
그 HTTP 경계만 지나간다.
"""

import json
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from control_tower.gateway.http_server import OperationsHttpServer
from control_tower.gateway.operations_feed import OperationsFeed, RobotView


class _StubAnomalyClient:
    """Gateway 의 이상 원장을 흉내 낸다. 승인은 열린 목록에서 그것을 지운다."""

    def __init__(self) -> None:
        self.open: list[dict[str, object]] = [
            {
                'correlation_uuid': 'aaaaaaaa-0000-0000-0000-000000000001',
                'job_id': 2,
                'device_id': 'PK_01',
                'occurred_at': '2026-08-18T02:00:00+09:00',
                'message': 'reservation was released while the job still had work left',
                'payload': {'reservation_id': 2},
            },
            {
                'correlation_uuid': 'aaaaaaaa-0000-0000-0000-000000000002',
                'job_id': 3,
                'device_id': 'PK_02',
                'occurred_at': '2026-08-18T02:00:01+09:00',
                'message': 'reservation was released while the job still had work left',
                'payload': {'reservation_id': 5},
            },
        ]
        self.acknowledged: list[tuple[str, str, str]] = []

    def list_open_anomalies(self) -> tuple[dict[str, object], ...]:
        return tuple(self.open)

    def acknowledge_anomaly(
        self, correlation_uuid: str, *, worker_id: str, note: str
    ) -> dict[str, object]:
        remaining = [
            anomaly
            for anomaly in self.open
            if anomaly['correlation_uuid'] != correlation_uuid
        ]
        if len(remaining) == len(self.open):
            raise LookupError(correlation_uuid)
        self.open = remaining
        self.acknowledged.append((correlation_uuid, worker_id, note))
        return {
            'correlation_uuid': correlation_uuid,
            'job_id': 2,
            'acknowledged_by': worker_id,
            'note': note,
        }


def _post(url: str, payload: dict[str, object]) -> tuple[int, dict[str, object]]:
    request = Request(
        url,
        data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    with urlopen(request, timeout=2) as response:
        return response.status, json.loads(response.read())


class OperationsAnomalyUiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.feed = OperationsFeed()
        self.feed.upsert_robot(RobotView('PK_01', 1, 2, 0, 80, 'SAFE', '', 'IDLE', ''))
        self.anomalies = _StubAnomalyClient()
        self.server = OperationsHttpServer(self.feed, anomaly_client=self.anomalies)
        self.server.start()

    def tearDown(self) -> None:
        self.server.stop()

    def test_open_anomalies_are_readable_by_the_control_screen(self) -> None:
        with urlopen(
            f'{self.server.base_url}/api/v1/operations/anomalies?state=open', timeout=2
        ) as response:
            body = json.loads(response.read())

        self.assertEqual(200, response.status)
        self.assertEqual([2, 3], [anomaly['job_id'] for anomaly in body['anomalies']])

    def test_a_person_can_close_an_anomaly_from_the_screen(self) -> None:
        status, body = _post(
            f'{self.server.base_url}/api/v1/operations/anomalies/'
            'aaaaaaaa-0000-0000-0000-000000000001/acknowledge',
            {'worker_id': 'W-OP-01', 'note': 'robot was parked'},
        )

        self.assertEqual(200, status)
        self.assertEqual('W-OP-01', body['acknowledged_by'])
        self.assertEqual(
            [('aaaaaaaa-0000-0000-0000-000000000001', 'W-OP-01', 'robot was parked')],
            self.anomalies.acknowledged,
        )
        with urlopen(
            f'{self.server.base_url}/api/v1/operations/anomalies?state=open', timeout=2
        ) as response:
            remaining = json.loads(response.read())['anomalies']
        self.assertEqual([3], [anomaly['job_id'] for anomaly in remaining])

    def test_closing_something_that_is_not_open_is_not_found(self) -> None:
        with self.assertRaises(HTTPError) as error:
            _post(
                f'{self.server.base_url}/api/v1/operations/anomalies/'
                'ffffffff-0000-0000-0000-000000000000/acknowledge',
                {'worker_id': 'W-OP-01', 'note': 'nothing here'},
            )

        self.assertEqual(404, error.exception.code)

    def test_the_screen_ships_a_button_that_calls_the_acknowledge_route(self) -> None:
        """경로가 있어도 화면에 누를 곳이 없으면 사람은 여전히 닫지 못한다."""
        with urlopen(f'{self.server.base_url}/', timeout=2) as response:
            page = response.read().decode()
        with urlopen(f'{self.server.base_url}/operations.js', timeout=2) as response:
            script = response.read().decode()

        self.assertIn('anomalies', page)
        self.assertIn('/api/v1/operations/anomalies', script)
        self.assertIn('/acknowledge', script)


class OperationsWithoutAnomalyClientTest(unittest.TestCase):
    """Gateway 가 연결되지 않은 배치에서도 기존 화면은 그대로 뜬다."""

    def setUp(self) -> None:
        self.server = OperationsHttpServer(OperationsFeed())
        self.server.start()

    def tearDown(self) -> None:
        self.server.stop()

    def test_the_anomaly_list_is_empty_rather_than_broken(self) -> None:
        with urlopen(
            f'{self.server.base_url}/api/v1/operations/anomalies?state=open', timeout=2
        ) as response:
            body = json.loads(response.read())

        self.assertEqual([], body['anomalies'])

    def test_acknowledging_without_a_gateway_reports_it_is_unavailable(self) -> None:
        with self.assertRaises(HTTPError) as error:
            _post(
                f'{self.server.base_url}/api/v1/operations/anomalies/'
                'aaaaaaaa-0000-0000-0000-000000000001/acknowledge',
                {'worker_id': 'W-OP-01', 'note': 'no gateway here'},
            )

        self.assertEqual(503, error.exception.code)


if __name__ == '__main__':
    unittest.main()
