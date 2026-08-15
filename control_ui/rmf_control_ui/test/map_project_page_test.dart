import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/trihouse/api/fms_api.dart';
import 'package:rmf_control_ui/trihouse/api/fms_models.dart';
import 'package:rmf_control_ui/trihouse/features/maps/map_project_page.dart';


List<JsonObject> _waypoints() => [
  for (final value in const [
    ('ambient_storage_loading_dock_01', 1.234, 0.743, 2.255),
    ('chilled_storage_loading_dock_01', 1.260, 0.193, -2.258),
    ('frozen_storage_loading_dock_01', 1.201, -0.799, -1.408),
    ('packing_station_loading_dock_01', 0.351, -0.490, 0.231),
    ('packing_station_loading_dock_02', 0.351, -1.017, 0.231),
    ('safety_zone_01', 0.613, -1.249, 0.0),
    ('charging_station_01', 0.065, 0.227, -0.005),
    ('charging_station_02', 0.076, -0.013, 0.239),
  ])
    {
      'code': value.$1,
      'display_name': value.$1,
      'x': value.$2,
      'y': value.$3,
      'yaw': value.$4,
      'origin': 'physical_features_import',
    },
];

List<JsonObject> _features() => const [
  {
    'type': 'bottleneck',
    'code': 'bottleneck_zone_01',
    'display_name': 'Bottleneck Zone 01',
    'feature_code': 'TRIHOUSE-TEST-01-BOTTLENECK-01',
    'mutex_group': 'bottleneck_01',
    'x': 0.841,
    'y': -0.111,
    'radius_m': 0.1,
    'source_diameter_m': 0.2,
    'origin': 'physical_features_import',
  },
  {
    'type': 'bottleneck',
    'code': 'bottleneck_zone_02',
    'display_name': 'Bottleneck Zone 02',
    'feature_code': 'TRIHOUSE-TEST-01-BOTTLENECK-02',
    'mutex_group': 'bottleneck_02',
    'x': 0.367,
    'y': -0.762,
    'radius_m': 0.1,
    'source_diameter_m': 0.2,
    'origin': 'physical_features_import',
  },
  {
    'type': 'fiducial_binding',
    'code': 'aruco_marker_2',
    'marker_id': 2,
    'dictionary': 'DICT_5X5_50',
    'target_location_code': 'WH-AMB-01-DOCK-01',
    'x': 1.234,
    'y': 0.743,
    'yaw': 2.255,
    'pixel_size': 41.8,
    'origin': 'physical_features_import',
  },
  {
    'type': 'fiducial_binding',
    'code': 'aruco_marker_1',
    'marker_id': 1,
    'dictionary': 'DICT_5X5_50',
    'target_location_code': 'WH-CHL-01-DOCK-01',
    'x': 1.260,
    'y': 0.193,
    'yaw': -2.258,
    'pixel_size': 37.0,
    'origin': 'physical_features_import',
  },
  {
    'type': 'fiducial_binding',
    'code': 'aruco_marker_0',
    'marker_id': 0,
    'dictionary': 'DICT_5X5_50',
    'target_location_code': 'WH-FRZ-01-DOCK-01',
    'x': 1.370,
    'y': -0.233,
    'yaw': 1.772,
    'pixel_size': 24.6,
    'origin': 'physical_features_import',
  },
];

class _MapApi implements FmsApi {
  var saved = 0;
  var deleted = 0;

  MapProjectDraftDto get draft => MapProjectDraftDto(
    mapName: 'trihouse_test_01',
    formatVersion: 1,
    draftRevision: 4,
    sourceUuids: const {
      'slam_yaml': 'source-yaml',
      'slam_image': 'source-image',
      'physical_features_import': 'source-physical',
    },
    stagedSourceTokens: const {},
    waypoints: _waypoints(),
    features: _features(),
    runtimeProfileHash: 'a' * 64,
  );

  @override
  Future<List<MapProjectSummaryDto>> listMapProjects() async => [
    MapProjectSummaryDto(
      mapName: 'trihouse_test_01',
      drawingName: 'map.pgm',
      formatVersion: 1,
      waypointCount: 8,
      laneCount: 0,
      draftRevision: 4,
      hasBuildingYaml: false,
      updatedAt: DateTime(2026, 8, 16),
    ),
  ];

  @override
  Future<MapProjectOpenDto> openMapProject(String mapName) async =>
      MapProjectOpenDto(
        draft: draft,
        openExisting: true,
        activeRevision: 'trihouse_test_01:active',
      );

  @override
  Future<RuntimeProfileDto> getRuntimeProfile() async => RuntimeProfileDto.fromJson({
    'profile_name': 'pinky_pro simulation profile',
    'profile_hash': 'a' * 64,
    'source_files': [
      'pinky_pro/pinky_navigation/params/nav2_params.yaml',
      'pinky_pro/pinky_bringup/config/pinky_params.yaml',
    ],
    'controller': {
      'plugin': 'RegulatedPurePursuitController',
      'desired_linear_velocity_mps': 0.2,
    },
    'planner': {'plugin': 'NavfnPlanner', 'tolerance_m': 0.5},
    'local_costmap': {'resolution': 0.05, 'inflation_radius_m': 0.15},
    'global_costmap': {'resolution': 0.05, 'inflation_radius_m': 0.15},
    'robot': {
      'footprint': [
        [0.06, 0.06],
        [0.06, -0.06],
        [-0.06, -0.06],
        [-0.06, 0.06],
      ],
      'dimensions_m': {'length': 0.12, 'width': 0.12},
      'robot_radius_m': null,
    },
    'max_speeds': {'linear_mps': 0.25, 'angular_radps': 1.5},
    'goal_tolerances': {'xy_m': 0.25, 'yaw_rad': 0.25},
    'progress_tolerances': {
      'required_movement_radius_m': 0.5,
      'movement_time_allowance_s': 10.0,
    },
    'wheel_parameters': {
      'wheel_radius_m': 0.027,
      'wheel_separation_m': 0.0961,
    },
  });

  @override
  Future<MapProjectDraftDto> saveMapDraft(
    MapProjectDraftDto draft, {
    int? expectedRevision,
  }) async {
    saved += 1;
    return draft;
  }

  @override
  Future<void> deleteMapDraft(String mapName) async {
    deleted += 1;
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

Future<_MapApi> _pumpPage(WidgetTester tester) async {
  tester.view.physicalSize = const Size(1440, 1000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  final api = _MapApi();
  await tester.pumpWidget(
    MaterialApp(home: Scaffold(body: MapProjectPage(api: api))),
  );
  await tester.pumpAndSettle();
  await tester.tap(find.text('trihouse_test_01').first);
  await tester.pumpAndSettle();
  return api;
}

void main() {
  testWidgets('P0 map page has save delete publish uploads and no lane tools', (
    tester,
  ) async {
    await _pumpPage(tester);

    expect(find.text('저장'), findsOneWidget);
    expect(find.text('삭제'), findsOneWidget);
    expect(find.text('배포'), findsOneWidget);
    expect(find.text('SLAM YAML 업로드'), findsOneWidget);
    expect(find.text('SLAM 이미지 업로드'), findsOneWidget);
    expect(find.text('실측 JSONL 업로드'), findsOneWidget);
    expect(find.text('Waypoint 추가'), findsOneWidget);
    expect(find.textContaining('Lane'), findsNothing);
    expect(find.textContaining('Transit'), findsNothing);
    expect(find.text('Polygon 추가'), findsNothing);
    expect(find.textContaining('Floor measurement'), findsNothing);
    expect(find.textContaining('수동 배차'), findsNothing);
    expect(find.textContaining('기존 프로젝트를 열었습니다'), findsOneWidget);
  });

  testWidgets('physical tab shows exact P0 counts radii and recognition poses', (
    tester,
  ) async {
    await _pumpPage(tester);
    await tester.tap(find.text('실측 Feature'));
    await tester.pumpAndSettle();

    expect(find.text('Waypoint 8'), findsOneWidget);
    expect(find.text('Bottleneck 2'), findsOneWidget);
    expect(find.text('Marker pose 3'), findsOneWidget);
    expect(find.textContaining('radius 0.10 m'), findsNWidgets(2));
    expect(find.textContaining('marker 2 · (1.234, 0.743, 2.255)'), findsOneWidget);
    expect(find.textContaining('marker 1 · (1.260, 0.193, -2.258)'), findsOneWidget);
    expect(find.textContaining('marker 0 · (1.370, -0.233, 1.772)'), findsOneWidget);
  });

  testWidgets('configuration tab is read-only in P0 and names pinned sources', (
    tester,
  ) async {
    await _pumpPage(tester);
    await tester.tap(find.text('설정 파일'));
    await tester.pumpAndSettle();

    expect(find.text('pinky_pro simulation profile'), findsOneWidget);
    expect(find.textContaining('RegulatedPurePursuitController'), findsOneWidget);
    expect(find.textContaining('NavfnPlanner'), findsOneWidget);
    expect(find.textContaining('robot_radius_m: unavailable'), findsOneWidget);
    expect(find.textContaining('wheel_radius_m: 0.027'), findsOneWidget);
    expect(find.textContaining('nav2_params.yaml'), findsOneWidget);
    expect(find.textContaining('pinky_params.yaml'), findsOneWidget);
    expect(find.byType(TextField), findsNothing);
  });

  testWidgets('manual point+yaw marks unsaved and explicit Save clears it', (
    tester,
  ) async {
    final api = await _pumpPage(tester);
    await tester.tap(find.text('Waypoint 추가'));
    await tester.pumpAndSettle();
    await tester.enterText(find.widgetWithText(TextField, '코드'), 'manual-1');
    await tester.enterText(find.widgetWithText(TextField, 'x (m)'), '0');
    await tester.enterText(find.widgetWithText(TextField, 'y (m)'), '0');
    await tester.enterText(find.widgetWithText(TextField, 'yaw (rad)'), '1.57');
    await tester.tap(find.text('추가'));
    await tester.pumpAndSettle();
    expect(find.text('저장되지 않은 변경'), findsOneWidget);
    expect(find.byKey(const Key('waypoint-manual-1')), findsOneWidget);

    await tester.tap(find.text('저장'));
    await tester.pumpAndSettle();
    expect(api.saved, 1);
    expect(find.text('저장되지 않은 변경'), findsNothing);
  });
}
