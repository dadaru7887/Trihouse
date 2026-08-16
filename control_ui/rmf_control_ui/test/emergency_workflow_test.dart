import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/trihouse/api/fms_models.dart';
import 'package:rmf_control_ui/trihouse/features/operations/camera_wall.dart';

import 'operations_page_test.dart' show FakeOperationsFeed, testOperationsPage;

void main() {
  testWidgets('both operator decisions are offered when an incident opens', (
    tester,
  ) async {
    final feed = FakeOperationsFeed();
    await tester.pumpWidget(testOperationsPage(feed: feed));

    expect(find.byKey(const Key('emergency-decision')), findsNothing);
    feed.emitPinkyFall('PK_01');
    await tester.pump();

    expect(find.byKey(const Key('emergency-decision')), findsOneWidget);
    expect(find.text('비상경보 발령'), findsOneWidget);
    expect(find.text('작업 계속 진행'), findsOneWidget);
  });

  testWidgets('raising the alarm sends RAISE_ALARM with the worker', (
    tester,
  ) async {
    final feed = FakeOperationsFeed();
    await tester.pumpWidget(testOperationsPage(feed: feed));
    feed.emitPinkyFall('PK_01');
    await tester.pump();

    await tester.tap(find.byKey(const Key('raise-alarm')));
    await tester.pumpAndSettle();

    expect(feed.decisions, hasLength(1));
    expect(feed.decisions.single.decision, EmergencyDecision.raiseAlarm);
    expect(feed.decisions.single.workerId, 'W-1');
  });

  testWidgets('continuing work sends CONTINUE_WORK for the same incident', (
    tester,
  ) async {
    final feed = FakeOperationsFeed();
    await tester.pumpWidget(testOperationsPage(feed: feed));
    feed.emitWarehouseFall('WH-CHL-01');
    await tester.pump();

    await tester.tap(find.byKey(const Key('continue-work')));
    await tester.pumpAndSettle();

    expect(feed.decisions, hasLength(1));
    expect(feed.decisions.single.decision, EmergencyDecision.continueWork);
  });

  testWidgets('closing the dialog records no decision', (tester) async {
    final feed = FakeOperationsFeed();
    await tester.pumpWidget(testOperationsPage(feed: feed));
    feed.emitPinkyFall('PK_01');
    await tester.pump();

    await tester.tap(find.byKey(const Key('dismiss-emergency')));
    await tester.pumpAndSettle();

    expect(feed.decisions, isEmpty);
    expect(find.byKey(const Key('emergency-decision')), findsNothing);
  });

  testWidgets('the incident camera stays open through the decision', (
    tester,
  ) async {
    final feed = FakeOperationsFeed();
    await tester.pumpWidget(testOperationsPage(feed: feed));
    feed.emitPinkyFall('PK_02');
    await tester.pump();

    expect(find.byKey(const Key('CAM-PK-02-live')), findsOneWidget);
    await tester.tap(find.byKey(const Key('raise-alarm')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('CAM-PK-02-live')), findsOneWidget);
  });

  test('the UI selects the same cameras as the Control Tower rule', () {
    expect(
      selectEventCameras(kind: 'PINKY_FALL', robotId: 'PK_01').cameraIds,
      ['CAM-PK-01'],
    );
    expect(
      selectEventCameras(kind: 'WAREHOUSE_FALL', locationId: 'WH-FRZ-01')
          .cameraIds,
      ['CAM-FIXED-02'],
    );
    expect(
      selectEventCameras(
        kind: 'OMX_LOAD',
        omxId: 'OMX_02',
        locationId: 'PACKING-01',
      ).cameraIds,
      ['CAM-OMX-02-WRIST', 'CAM-FIXED-02'],
    );
    expect(selectEventCameras(kind: 'UNKNOWN').cameraIds, isEmpty);
  });
}
