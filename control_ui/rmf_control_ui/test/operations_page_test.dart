import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/trihouse/api/fms_api.dart';
import 'package:rmf_control_ui/trihouse/api/fms_models.dart';
import 'package:rmf_control_ui/trihouse/features/operations/camera_wall.dart';
import 'package:rmf_control_ui/trihouse/features/operations/operations_page.dart';

class FakeOperationsFeed implements FmsApi {
  final _controller = StreamController<OperationsEventDto>.broadcast();
  int _eventId = 0;

  @override
  Stream<OperationsEventDto> operationsEvents() => _controller.stream;

  void _emit(String eventType, Map<String, Object?> payload, {int? incidentId}) {
    _eventId += 1;
    _controller.add(
      OperationsEventDto(
        eventId: _eventId,
        eventUuid: 'evt-$_eventId',
        occurredAt: DateTime.utc(2026, 8, 16),
        actorWorkerId: null,
        deviceId: null,
        jobId: 7,
        jobStepId: 11,
        incidentId: incidentId,
        severity: 'info',
        category: 'operations',
        eventType: eventType,
        message: null,
        payload: payload,
      ),
    );
  }

  void emitPath({
    String robotId = 'PK_01',
    bool mismatch = false,
  }) => _emit(mismatch ? 'PATH_SCHEDULE_MISMATCH' : 'PATH_UPDATED', {
    'robot_id': robotId,
    'map_revision': 'trihouse_test_01:7',
    'nav2_global_path': [
      [0.0, 0.0],
      [4.0, 0.0],
    ],
    'nav2_local_path': [
      [1.0, 0.0],
    ],
    'actual_trail': [
      [0.0, 0.0],
      [1.0, 0.0],
    ],
    'rmf_timed_trajectory': [
      [0.0, 0.0, 0.0],
      [3.0, 4.0, 0.0],
    ],
    'goal_pose': [4.0, 0.0, 0.0],
  });

  void emitRobot({String robotId = 'PK_01'}) => _emit('ROBOT_UPDATED', {
    'robot_id': robotId,
    'x': 1.0,
    'y': 2.0,
    'yaw': 0.5,
    'battery_percent': 91.0,
    'safety_state': 'normal',
    'job_id': 'J-1',
  });

  void emitPinkyFall(String robotId) =>
      _emit('PINKY_FALL', {'robot_id': robotId}, incidentId: 3);

  void emitWarehouseFall(String locationId) =>
      _emit('WAREHOUSE_FALL', {'location_id': locationId}, incidentId: 4);

  void emitOmxLoad({
    String omxId = 'OMX_01',
    String locationId = 'WH-AMB-01',
    String outcome = 'DROP_DETECTED',
  }) => _emit('OMX_LOAD', {
    'omx_id': omxId,
    'location_id': locationId,
    'load_outcome': outcome,
    'qr': 'SKU-MILK',
    'marker_id': 1,
    'act_stage': 'GRASP',
    'act_version': 'fake-act/p0-v1',
    'attempt_no': 1,
    'gripper_state': 'open',
    'safety_gate': 'clear',
  });

  final decisions = <EmergencyDecisionDto>[];

  @override
  Future<void> decideEmergency(
    int incidentId,
    EmergencyDecisionDto request, {
    required String idempotencyKey,
  }) async {
    decisions.add(request);
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

Widget testOperationsPage({FakeOperationsFeed? feed}) => MaterialApp(
  home: Scaffold(body: OperationsPage(api: feed ?? FakeOperationsFeed())),
);

void main() {
  testWidgets('actual Nav2 path is primary and bootstrap graph is absent', (
    tester,
  ) async {
    final feed = FakeOperationsFeed();
    await tester.pumpWidget(testOperationsPage(feed: feed));
    feed.emitPath();
    await tester.pump();

    expect(find.byKey(const Key('nav2-global-path')), findsOneWidget);
    expect(find.byKey(const Key('actual-trail')), findsOneWidget);
    expect(find.byKey(const Key('bootstrap-graph')), findsNothing);
    expect(find.text('RMF 진단'), findsOneWidget);
  });

  testWidgets('the RMF timed trajectory is a diagnostic the operator opts into', (
    tester,
  ) async {
    final feed = FakeOperationsFeed();
    await tester.pumpWidget(testOperationsPage(feed: feed));
    feed.emitPath();
    await tester.pump();

    expect(find.byKey(const Key('rmf-timed-trajectory')), findsNothing);
    await tester.tap(find.byKey(const Key('rmf-diagnostics-toggle')));
    await tester.pump();
    expect(find.byKey(const Key('rmf-timed-trajectory')), findsOneWidget);
  });

  testWidgets('a path schedule mismatch is shown as a hold', (tester) async {
    final feed = FakeOperationsFeed();
    await tester.pumpWidget(testOperationsPage(feed: feed));
    feed.emitPath(mismatch: true);
    await tester.pump();

    expect(find.byKey(const Key('path-hold-badge')), findsOneWidget);
    expect(find.textContaining('PATH_SCHEDULE_MISMATCH'), findsOneWidget);
  });

  testWidgets('six camera fixtures are registered and none decode by default', (
    tester,
  ) async {
    await tester.pumpWidget(testOperationsPage());
    await tester.pump();

    for (final camera in cameraFixtures) {
      expect(find.byKey(Key('${camera.cameraId}-status')), findsOneWidget);
      expect(find.byKey(Key('${camera.cameraId}-live')), findsNothing);
    }
    expect(cameraFixtures.length, 6);
  });

  testWidgets('fall source selects the correct event camera', (tester) async {
    final feed = FakeOperationsFeed();
    await tester.pumpWidget(testOperationsPage(feed: feed));
    feed.emitPinkyFall('PK_01');
    await tester.pump();

    expect(find.byKey(const Key('CAM-PK-01-live')), findsOneWidget);
    expect(find.byKey(const Key('CAM-PK-02-live')), findsNothing);
  });

  testWidgets('a warehouse fall selects the fixed camera instead', (
    tester,
  ) async {
    final feed = FakeOperationsFeed();
    await tester.pumpWidget(testOperationsPage(feed: feed));
    feed.emitWarehouseFall('WH-CHL-01');
    await tester.pump();

    expect(find.byKey(const Key('CAM-FIXED-01-live')), findsOneWidget);
    expect(find.byKey(const Key('CAM-PK-01-live')), findsNothing);
  });

  testWidgets('an OMX load opens the wrist plus fixed camera with overlays', (
    tester,
  ) async {
    final feed = FakeOperationsFeed();
    await tester.pumpWidget(testOperationsPage(feed: feed));
    feed.emitOmxLoad();
    await tester.pump();

    expect(find.byKey(const Key('CAM-OMX-01-WRIST-live')), findsOneWidget);
    expect(find.byKey(const Key('CAM-FIXED-01-live')), findsOneWidget);
    // Pinky video is never opened as OMX load evidence.
    expect(find.byKey(const Key('CAM-PK-01-live')), findsNothing);
    expect(find.textContaining('QR SKU-MILK'), findsWidgets);
    expect(find.textContaining('ACT GRASP fake-act/p0-v1 #1'), findsWidgets);
    expect(find.textContaining('적재 DROP_DETECTED'), findsWidgets);
  });

  testWidgets('a confirmed load auto-closes while a drop stays open', (
    tester,
  ) async {
    final feed = FakeOperationsFeed();
    await tester.pumpWidget(testOperationsPage(feed: feed));

    feed.emitOmxLoad(outcome: 'DROP_DETECTED');
    await tester.pump();
    expect(find.byKey(const Key('CAM-OMX-01-WRIST-live')), findsOneWidget);

    feed.emitOmxLoad(outcome: 'LOAD_CONFIRMED');
    await tester.pump();
    expect(find.byKey(const Key('CAM-OMX-01-WRIST-live')), findsNothing);
  });
}
