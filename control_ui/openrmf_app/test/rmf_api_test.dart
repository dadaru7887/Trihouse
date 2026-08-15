import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:openrmf_app/src/models.dart';
import 'package:openrmf_app/src/rmf_api.dart';

void main() {
  test(
    'sends RMF control requests with authentication and expected schema',
    () async {
      final requests = <http.Request>[];
      final client = MockClient((request) async {
        requests.add(request);
        return http.Response('{}', 200);
      });
      final api = RmfApi(
        baseUrl: 'http://rmf.test:8000',
        token: 'operator-token',
        client: client,
      );
      const robot = RmfRobot(
        fleet: 'tinyRobot',
        name: 'tinyRobot1',
        status: 'idle',
        level: 'L1',
        x: 0,
        y: 0,
        yaw: 0,
        battery: 1,
        taskId: null,
        issueCount: 0,
        lockedMutexGroups: ['narrow_hall'],
        requestingMutexGroups: [],
      );

      await api.dispatchTask({
        'category': 'patrol',
        'description': {
          'places': ['coe', 'lounge'],
          'rounds': 1,
        },
      });
      await api.cancelTask('task/1');
      await api.requestDoor('main door', 2);
      await api.requestLift(
        name: 'lift A',
        destination: 'L2',
        requestType: 1,
        doorMode: 2,
      );
      await api.unlockMutex(robot, 'narrow_hall');

      expect(requests, hasLength(5));
      expect(
        requests.every(
          (r) => r.headers['authorization'] == 'Bearer operator-token',
        ),
        isTrue,
      );
      expect(requests[0].url.path, '/tasks/dispatch_task');
      expect(jsonDecode(requests[0].body)['type'], 'dispatch_task_request');
      expect(requests[1].url.path, '/tasks/cancel_task');
      expect(jsonDecode(requests[1].body)['task_id'], 'task/1');
      expect(requests[2].url.path, '/doors/main%20door/request');
      expect(jsonDecode(requests[2].body)['mode'], 2);
      expect(requests[3].url.path, '/lifts/lift%20A/request');
      expect(jsonDecode(requests[3].body)['destination'], 'L2');
      expect(requests[4].url.queryParameters['mutex_group'], 'narrow_hall');
    },
  );

  test('treats optional Jazzy endpoints returning 404 as empty', () async {
    final api = RmfApi(
      baseUrl: 'http://rmf.test:8000',
      token: '',
      client: MockClient((_) async => http.Response('not found', 404)),
    );

    expect(await api.getDoors(), isEmpty);
    expect(await api.getLifts(), isEmpty);
    expect(await api.getWorkcells(), isEmpty);
    expect(await api.getAlerts(), isEmpty);
    expect(await api.getScheduledTasks(), isEmpty);
  });
}
