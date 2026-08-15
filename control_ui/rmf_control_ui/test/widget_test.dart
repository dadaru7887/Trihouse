import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/main.dart';
import 'package:rmf_control_ui/trihouse/api/fms_api.dart';
import 'package:rmf_control_ui/trihouse/api/fms_models.dart';

class _TeamAApi implements FmsApi {
  @override
  Future<List<InventoryLotDto>> listInventory() async => [
    InventoryLotDto(
      lotId: 7,
      lotCode: 'LOT-0007',
      productCode: 'MILK-1L',
      itemName: 'Milk',
      temperatureZone: 'chilled',
      locationCode: 'CHILL-A-01',
      expiryDate: DateTime(2026, 8, 20),
      availableQty: 12,
      reservedQty: 3,
      state: 'available',
    ),
  ];

  @override
  Future<List<MapProjectSummaryDto>> listMapProjects() async => [
    MapProjectSummaryDto(
      mapName: 'trihouse_test_01',
      drawingName: 'warehouse-map.pgm',
      formatVersion: 1,
      waypointCount: 1,
      laneCount: 0,
      draftRevision: 4,
      hasBuildingYaml: true,
      updatedAt: DateTime(2026, 8, 16, 3),
    ),
  ];

  @override
  Future<MapProjectOpenDto> openMapProject(String mapName) async =>
      MapProjectOpenDto(
        draft: MapProjectDraftDto(
          mapName: mapName,
          formatVersion: 1,
          draftRevision: 4,
          sourceUuids: const {'slam_image': 'source-1'},
          stagedSourceTokens: const {},
          waypoints: const [
            {
              'code': 'PACKING-01-DOCK-01',
              'x': 0.351,
              'y': -0.490,
              'yaw': 1.57,
            },
          ],
          features: const [],
          runtimeProfileHash: 'profile-sha',
        ),
        openExisting: true,
        activeRevision: 'map-sha',
      );

  @override
  Future<JobDetailDto> getJob(int jobId) async => JobDetailDto.fromJson({
    'job_id': jobId,
    'job_code': 'OUT-$jobId',
    'operation_type': 'outbound',
    'priority': 'high',
    'state': 'waiting_worker',
    'requested_by': 'W-OP-01',
    'external_reference': 'ORDER-$jobId',
    'source_location_id': null,
    'destination_location_id': 12,
    'due_at': null,
    'context': {'product_code': 'MILK-1L'},
    'created_at': '2026-08-16T03:00:00+09:00',
    'steps': [
      {'job_step_id': 9, 'step_no': 10, 'state': 'waiting_worker'},
    ],
  });

  @override
  Stream<OperationsEventDto> operationsEvents() => Stream.value(
    OperationsEventDto.fromJson({
      'event_id': 8,
      'event_uuid': 'event-8',
      'occurred_at': '2026-08-16T03:00:00+09:00',
      'actor_worker_id': null,
      'device_id': 'PK_01',
      'job_id': 42,
      'job_step_id': 9,
      'incident_id': null,
      'severity': 'info',
      'category': 'robot',
      'event_type': 'robot.pose',
      'message': 'Pinky 위치 갱신',
      'payload': {'x': 1.2, 'y': 0.4, 'yaw': 0.2},
    }),
  );

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

void main() {
  testWidgets('Team A shell renders dashboard map robot task and operations', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1280, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(RmfControlApp(api: _TeamAApi()));
    await tester.pumpAndSettle();

    expect(find.text('운영 대시보드'), findsOneWidget);
    expect(find.text('실시간 운영 맵'), findsOneWidget);
    expect(find.text('최근 작업 활동'), findsOneWidget);
    expect(find.text('빠른 실행'), findsOneWidget);
    expect(find.text('재고'), findsOneWidget);
    expect(find.text('MILK-1L'), findsOneWidget);
    expect(find.text('가용 12 · 예약 3'), findsOneWidget);

    await tester.tap(find.text('맵 관리'));
    await tester.pumpAndSettle();
    expect(find.text('맵 프로젝트'), findsOneWidget);
    expect(find.text('도면 작업 영역'), findsOneWidget);
    expect(find.text('Waypoint 편집'), findsOneWidget);
    expect(find.text('trihouse_test_01'), findsWidgets);
    expect(find.textContaining('Lane'), findsNothing);
    expect(find.textContaining('수동 배차'), findsNothing);

    await tester.tap(find.text('로봇'));
    await tester.pumpAndSettle();
    expect(find.text('로봇 운영'), findsOneWidget);
    expect(find.text('실시간 로봇 맵'), findsOneWidget);
    expect(find.text('PK_01'), findsWidgets);
    expect(find.text('브라우저 진단 모델'), findsOneWidget);

    await tester.tap(find.text('작업'));
    await tester.pumpAndSettle();
    expect(find.text('작업 관리'), findsOneWidget);
    expect(find.text('Gateway 작업 조회'), findsOneWidget);
    await tester.enterText(find.byKey(const Key('job-id-field')), '42');
    await tester.tap(find.text('작업 조회'));
    await tester.pumpAndSettle();
    expect(find.text('OUT-42'), findsOneWidget);
    expect(find.text('waiting_worker'), findsWidgets);

    await tester.tap(find.text('운영 분석'));
    await tester.pumpAndSettle();
    expect(find.text('운영 분석'), findsWidgets);
    expect(find.text('운영 이벤트 타임라인'), findsOneWidget);
    expect(find.text('Pinky 위치 갱신'), findsOneWidget);
  });
}
