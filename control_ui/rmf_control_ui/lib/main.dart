import 'dart:async';
import 'dart:convert';
import 'dart:io' show Platform, ProcessSignal, exit;
import 'dart:math' as math;
import 'dart:ui' as ui;

import 'package:file_picker/file_picker.dart';
import 'package:flutter/foundation.dart' show listEquals;
import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'deployment_service.dart';
import 'database_migration.dart';
import 'deployed_map_service.dart';
import 'gazebo_robot_reset.dart';
import 'map_ai_service.dart';
import 'map_geometry.dart';
import 'map_project_store.dart';
import 'movable_dialog.dart';
import 'nav2_map_alignment.dart';
import 'nav2_map_reader.dart';
import 'nav2_params.dart';
import 'nav2_progress_checker.dart';
import 'nav2_speed_limits.dart';
import 'nav2_vendor_params.dart';
import 'occupancy_grid.dart';
import 'project_log.dart';
import 'project_file_store.dart';
import 'occupancy_grid_export.dart';
import 'rmf_config_export.dart';
import 'rmf_project_config.dart';
import 'operations_log.dart';
import 'operations_log_models.dart';
import 'robot_data_source.dart';
import 'grid_map_settings.dart';
import 'readiness_check.dart';
import 'robot_link_probe.dart';
import 'robot_move_command.dart';
import 'robot_model_store.dart';
import 'robot_sensor_feed.dart';
import 'robot_sensor_models.dart';
import 'robot_spawn_check.dart';
import 'robot_telemetry_bridge.dart';
import 'robot_telemetry_models.dart';
import 'ros2_inspect_page.dart';
import 'slam_map.dart';
import 'slam_map_store.dart';
import 'rmf_project_runner.dart';
import 'rmf_task_bridge.dart';
import 'rmf_task_request.dart';
import 'rmf_runtime_service.dart';
import 'robot_id_rule.dart';
import 'robot_station_rule.dart';
import 'scenario_route_planner.dart';
import 'task_dispatch.dart';
import 'task_store.dart';
import 'wall_height.dart';
import 'workcell_pairing.dart';
import 'workcell_policy_page.dart';
import 'workcell_policy_store.dart';
import 'workspace_layout.dart';

void main() => runApp(const RmfControlApp());

class RmfControlApp extends StatelessWidget {
  const RmfControlApp({super.key});

  @override
  Widget build(BuildContext context) {
    const navy = Color(0xFF111827);
    const blue = Color(0xFF2563EB);
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      title: 'RoboSapiens Control',
      theme: ThemeData(
        useMaterial3: true,
        fontFamily: 'sans-serif',
        scaffoldBackgroundColor: const Color(0xFFF5F7FA),
        colorScheme: ColorScheme.fromSeed(
          seedColor: blue,
          brightness: Brightness.light,
          surface: Colors.white,
        ),
        textTheme: const TextTheme(
          headlineMedium: TextStyle(
            color: navy,
            fontWeight: FontWeight.w800,
            letterSpacing: -0.8,
          ),
          titleMedium: TextStyle(color: navy, fontWeight: FontWeight.w700),
          bodyMedium: TextStyle(color: Color(0xFF64748B)),
        ),
      ),
      home: const ControlDashboard(),
    );
  }
}

enum MapStage { upload, measurement, walls, floor, lanes, stations, deploy }

class _MapMeasurement {
  const _MapMeasurement({
    required this.start,
    required this.end,
    required this.length,
    required this.unit,
  });

  final Offset start;
  final Offset end;
  final double length;
  final String unit;
}

class UploadedDrawing {
  const UploadedDrawing({
    required this.name,
    required this.extension,
    required this.size,
    this.bytes,
    this.pixelWidth,
    this.pixelHeight,
  });

  final String name;
  final String extension;
  final int size;
  final Uint8List? bytes;
  final int? pixelWidth;
  final int? pixelHeight;

  bool get isImage => ['png', 'jpg', 'jpeg'].contains(extension);
  String get readableSize => size < 1024 * 1024
      ? '${(size / 1024).toStringAsFixed(1)} KB'
      : '${(size / 1024 / 1024).toStringAsFixed(1)} MB';
}

class _EditorSnapshot {
  const _EditorSnapshot({
    required this.drawing,
    required this.stage,
    required this.measurement,
    required this.wallMask,
    required this.floorMask,
    required this.previousWallMask,
    required this.wallsDetected,
    required this.floorGenerated,
    required this.manualWalls,
    required this.wallVertexOverrides,
    required this.frozenAutoWalls,
    required this.recommendedLanes,
    required this.laneDirections,
    required this.laneSpeedLimits,
    required this.laneOrientations,
    required this.laneMutexGroups,
    required this.robotWidthMeters,
    required this.turningRadiusMeters,
    required this.localizationMarginMeters,
    required this.mapScenarioSummary,
    required this.laneWaypoints,
    required this.waypointTypes,
    required this.waypointNames,
    required this.activeLaneEndpoint,
  });

  final UploadedDrawing? drawing;
  final MapStage stage;
  final _MapMeasurement? measurement;
  final _WallMask? wallMask;
  final _WallMask? floorMask;
  final _WallMask? previousWallMask;
  final bool wallsDetected;
  final bool floorGenerated;
  final List<(Offset, Offset)> manualWalls;
  final Map<Offset, Offset> wallVertexOverrides;
  final List<(Offset, Offset)> frozenAutoWalls;
  final List<(Offset, Offset)> recommendedLanes;
  final Map<(Offset, Offset), String> laneDirections;
  final Map<(Offset, Offset), double> laneSpeedLimits;
  final Map<(Offset, Offset), String> laneOrientations;
  final Map<(Offset, Offset), String> laneMutexGroups;
  final double robotWidthMeters;
  final double turningRadiusMeters;
  final double localizationMarginMeters;
  final String? mapScenarioSummary;
  final List<Offset> laneWaypoints;
  final Map<Offset, String> waypointTypes;
  final Map<Offset, String> waypointNames;
  final Offset? activeLaneEndpoint;
}

class _LaneRecommendation {
  const _LaneRecommendation({
    required this.title,
    required this.description,
    required this.start,
    required this.end,
  });

  final String title;
  final String description;
  final Offset start;
  final Offset end;
}

class _MapScenarioConfig {
  const _MapScenarioConfig({
    required this.robotCount,
    required this.homeCount,
    required this.chargerCount,
    required this.ambientPickupCount,
    required this.chilledPickupCount,
    required this.frozenPickupCount,
    required this.dropoffCount,
    required this.returnHome,
    required this.singleLoadPerTrip,
  });

  final int robotCount;
  final int homeCount;
  final int chargerCount;
  final int ambientPickupCount;
  final int chilledPickupCount;
  final int frozenPickupCount;
  final int dropoffCount;
  final bool returnHome;
  final bool singleLoadPerTrip;

  int get requiredWaypointCount =>
      homeCount +
      homeCount +
      chargerCount +
      ambientPickupCount +
      chilledPickupCount +
      frozenPickupCount +
      dropoffCount;
}

class _ScenarioWaypointAssignment {
  const _ScenarioWaypointAssignment({
    required this.point,
    required this.category,
    required this.name,
  });

  final Offset point;
  final String category;
  final String name;
}

/// 출처를 화면에 어떻게 그릴지. 색과 아이콘은 화면 쪽 개념이라 규칙 라이브러리에
/// 두지 않는다.
extension _RobotDataSourceStyle on RobotDataSource {
  Color get color => switch (this) {
    // Mock 을 실물로 착각하는 것이 가장 위험하다. 붉게 세운다.
    RobotDataSource.mock => const Color(0xFFDC2626),
    RobotDataSource.gazebo => const Color(0xFFEA580C),
    RobotDataSource.real => const Color(0xFF15803D),
  };

  IconData get icon => switch (this) {
    RobotDataSource.mock => Icons.science_outlined,
    RobotDataSource.gazebo => Icons.view_in_ar_outlined,
    RobotDataSource.real => Icons.smart_toy,
  };
}

enum _RobotKind { mockMobile, pinky, omxManipulator, mockHumanoid, human }

/// Spawn 창에서 `등록 없이 배치`를 고른 것. 관제 대상이 아닌 사람·휴머노이드만
/// 이 길로 올린다. 로봇은 등록해야 Gazebo 와 fleet adapter 가 함께 안다.
const String _unregisteredSpawn = '__unregistered__';

extension on _RobotKind {
  String get label => switch (this) {
    _RobotKind.mockMobile => 'Mock 주행로봇',
    _RobotKind.pinky => 'Pinky',
    _RobotKind.omxManipulator => 'OMX Manipulator',
    _RobotKind.mockHumanoid => 'Mock 휴머노이드',
    _RobotKind.human => 'Human',
  };

  bool get isMobile => this != _RobotKind.omxManipulator;
  bool get canCarry =>
      this == _RobotKind.mockMobile || this == _RobotKind.pinky;
}

class _MockRobot {
  _MockRobot({
    required this.id,
    required this.position,
    required this.color,
    required this.kind,
    Offset? spawnPosition,
    this.imageBytes,
    this.image,
  }) : spawnPosition = spawnPosition ?? position;

  /// 등록된 로봇의 ID 와 같아야 한다.
  ///
  /// 지도에 올린 로봇은 등록에서 온다. 등록에서 ID 를 고치면 이 값도 함께
  /// 바뀌어야 서로를 찾는다 — 어긋나면 작업이 RMF 로 안 가고 앱 안에서만 돈다.
  /// 그래서 final 이 아니다.
  String id;
  Offset position;

  /// Spawn 할 때 고른 Waypoint. `로봇 원위치`가 되돌려 놓는 자리다.
  final Offset spawnPosition;
  final Color color;
  final _RobotKind kind;
  final Uint8List? imageBytes;
  final ui.Image? image;
  Offset? previousWaypoint;
  Offset? targetWaypoint;
  bool moving = false;

  /// 최초 위치로 돌아가는 중. 작업 없이 움직이는 로봇은 평소 Lane을 따라
  /// 배회하는데, 원위치 이동은 도착하면 멈춰야 하므로 구분한다.
  bool returningToSpawn = false;
  double battery = 100;
  final List<Offset> assignedRoute = [];
  String? activeTaskId;

  /// 지금 작업을 RMF 가 몰고 있다.
  ///
  /// 이때 앱은 좌표를 밀지도 않고 단계를 세지도 않는다. 둘 다 하면 화면의
  /// 진행률이 실제 로봇과 어긋난다 — 로봇이 안 움직여도 3초마다 다음 단계로
  /// 넘어가던 것이 그것이었다.
  bool rmfDriven = false;

  /// RMF 가 이 작업에 붙인 번호. 앱의 작업 번호와 다르다.
  String? rmfTaskId;

  /// RMF 가 마지막으로 지시한 목적지(월드 좌표). 도착 소식이 왔을 때 그것이
  /// 우리 단계의 목적지인지 가리는 데 쓴다. RMF 는 Lane 을 따라 중간
  /// Waypoint 를 스스로 끼워 넣으므로, 도착 횟수와 단계 수가 다르다.
  double? rmfGoalX;
  double? rmfGoalY;
}

class _RobotSpawnSelection {
  const _RobotSpawnSelection({
    required this.name,
    required this.position,
    required this.kind,
    this.imageBytes,
    this.image,
  });

  final String name;
  final Offset position;
  final _RobotKind kind;
  final Uint8List? imageBytes;
  final ui.Image? image;
}

enum _MockTaskStatus { queued, active, completed, cancelled, failed }

/// 로봇을 최초 위치로 돌려보낸 결과. 사람에게 무슨 일이 있었는지 적을 때 쓴다.
enum _ReturnOutcome {
  /// Lane 을 따라 돌아가는 중.
  routed,

  /// 갈 길이 없어 그 자리에 놓았다.
  teleported,

  /// 이미 최초 위치였다.
  already,
}

enum _TaskStepType { navigate, returnHome, armLoad, wait }

extension on _TaskStepType {
  bool get isMovement =>
      this == _TaskStepType.navigate || this == _TaskStepType.returnHome;
}

enum _OrderTrigger { manual, any, ambient, chilled, frozen }

extension on _OrderTrigger {
  String get label => switch (this) {
    _OrderTrigger.manual => '수동 실행',
    _OrderTrigger.any => '모든 주문',
    _OrderTrigger.ambient => '상온 주문',
    _OrderTrigger.chilled => '냉장 주문',
    _OrderTrigger.frozen => '냉동 주문',
  };
}

enum _TaskStepStatus { pending, active, completed, failed, cancelled }

class _MockTaskStep {
  _MockTaskStep({
    required this.type,
    this.destination,
    this.destinationName,
    this.durationSeconds = 0,
    this.policyId = 'policy_1',
  });

  final _TaskStepType type;
  Offset? destination;
  String? destinationName;
  final double durationSeconds;
  final String policyId;
  _TaskStepStatus status = _TaskStepStatus.pending;
  double remainingSeconds = 0;
  String? failureReason;

  String get label => switch (type) {
    _TaskStepType.navigate => 'Pinky 이동 · $destinationName',
    _TaskStepType.returnHome => '홈 복귀(자동) · ${destinationName ?? '배정 대기'}',
    _TaskStepType.armLoad => 'OMX-AI 픽업/적재 · $policyId',
    _TaskStepType.wait => '대기 · ${durationSeconds.toStringAsFixed(0)}초',
  };
}

/// 주문 긴급도. robo_core 의 Urgency enum 과 이름·가중치를 맞춘다.
enum _TaskUrgency {
  critical('긴급', 3),
  high('높음', 2),
  normal('보통', 1),
  low('낮음', 0);

  const _TaskUrgency(this.label, this.weight);

  final String label;
  final int weight;

  static _TaskUrgency parse(String? name) => switch (name) {
    'critical' => critical,
    'high' => high,
    'low' => low,
    _ => normal,
  };
}

class _MockTask {
  _MockTask({
    required this.id,
    required this.name,
    required this.description,
    required this.type,
    required this.robotId,
    required this.steps,
    this.trigger = _OrderTrigger.manual,
    this.orderId,
    this.urgency = _TaskUrgency.normal,
    DateTime? createdAt,
  }) : createdAt = createdAt ?? DateTime.now();

  final String id;
  String name;
  String description;
  final String type;
  String robotId;
  final List<_MockTaskStep> steps;
  _OrderTrigger trigger;
  final String? orderId;

  /// 주문에서 넘어온 긴급도. 대기가 쌓였을 때 배차 순서를 가른다.
  _TaskUrgency urgency;
  int currentStepIndex = 0;
  _MockTaskStatus status = _MockTaskStatus.queued;
  final DateTime createdAt;
  DateTime? completedAt;
  Offset? initialRobotPosition;
  double? initialRobotHeading;

  _MockTaskStep? get currentStep =>
      currentStepIndex < steps.length ? steps[currentStepIndex] : null;
}

class _TaskStepDraft {
  _TaskStepDraft(
    this.type, {
    this.destination,
    this.durationSeconds = 3,
    this.policyId = 'policy_1',
  });

  _TaskStepType type;
  Offset? destination;
  double durationSeconds;
  String policyId;
}

class _TaskEditorResult {
  const _TaskEditorResult({
    required this.name,
    required this.description,
    required this.robotId,
    required this.steps,
    required this.startImmediately,
    required this.trigger,
  });

  final String name;
  final String description;
  final String robotId;
  final List<_TaskStepDraft> steps;
  final bool startImmediately;
  final _OrderTrigger trigger;
}

class ControlDashboard extends StatefulWidget {
  const ControlDashboard({super.key});

  @override
  State<ControlDashboard> createState() => _ControlDashboardState();
}

/// 격자 한 칸을 무엇으로 정할지.
enum _GridResolutionMode {
  /// 로봇 몸 6칸·바닥 짧은 쪽 120칸으로 앱이 정한다.
  auto,

  /// 정해진 칸 수 상자에 맞춘다. 기본이다.
  target,

  /// 사람이 미터로 직접 넣는다.
  manual,
}

class _ControlDashboardState extends State<ControlDashboard> {
  final TransformationController _mapTransform = TransformationController();
  UploadedDrawing? _drawing;

  /// 그리드맵을 굽고 있는 중인가. 커서와 단추가 이걸 보고 바뀐다.
  bool _isGeneratingGrid = false;

  /// 격자 한 칸을 무엇으로 정할지.
  ///
  /// 기본은 `target` — 800×600 칸 상자에 맞춘다. 파일 크기가 예측 가능해지고,
  /// gwanghee·project1 규모에서는 자동 계산식보다 13배 촘촘해진다.
  ///
  /// 다만 칸 수를 고정하면 **해상도가 건물 크기에 따라 정해진다.** 큰 창고에서는
  /// 한 칸이 로봇만 해질 수 있어서 화면이 그때 경고한다.
  _GridResolutionMode _gridResolutionMode = _GridResolutionMode.target;
  int _gridTargetWidth = 800;
  int _gridTargetHeight = 600;

  /// 상자를 `모름` 으로 채워 정확히 그 칸 수를 만들지.
  ///
  /// 정사각 칸을 지키면 건물 비율 때문에 상자를 꽉 채울 수 없다. 800×600 이라는
  /// 숫자를 그대로 얻으려면 남는 쪽을 채워야 한다.
  bool _gridPadToTarget = true;

  /// `manual` 모드에서 쓸 한 칸 크기(m).
  double _gridManualResolution = .02;

  /// 마지막으로 저장된(또는 열면서 읽은) 그리드맵 설정.
  ///
  /// 지금 값과 견줘 저장할 것이 남았는지 본다. 시작할 때는 기본값이 기준이라,
  /// **프로젝트가 없어도** 고치면 알린다 — 저장할 곳이 없으면 그 사실까지
  /// 함께 적는다. 프로젝트 없이 고친 값은 그냥 사라지는데, 그것을 조용히 두면
  /// 맞춰 놓은 격자 크기가 어디로 갔는지 알 수 없다.
  late GridMapSettings _savedGridSettings = _currentGridSettings;

  /// Nav2 가 도면 지도 대신 SLAM 지도를 띄울지.
  ///
  /// launch 가 지도 경로를 못박고 있어서, 이 선택이 없으면 SLAM 지도를 올려도
  /// `map_server` 는 계속 도면 지도를 띄운다.
  bool _useSlamMap = false;

  /// 이 프로젝트에 넣어 둔 SLAM 지도. 없으면 아직 안 올렸다.
  SlamMap? _slamMap;
  ui.Image? _slamPreview;
  bool _isReadingSlamMap = false;

  /// 마지막으로 구운 그리드맵. 화면에 그림으로 보여 준다.
  ui.Image? _gridPreview;
  OccupancyGrid? _gridPreviewGrid;
  String? _gridPreviewDirectory;

  /// 이 그림이 **저장돼 있던 것**이면 그 파일을 쓴 때. 방금 구운 것이면 null.
  ///
  /// 프로젝트를 열면서 올린 격자는 도면보다 오래됐을 수 있다. 언제 만든
  /// 것인지 같이 보여 주지 않으면, 도면을 고친 뒤에도 지도가 최신인 줄 안다.
  DateTime? _gridPreviewSavedAt;

  /// 사람이 정한 프로젝트 이름. 정해져 있으면 도면 파일 이름을 이기고, 도면을
  /// 갈아 끼워도 그대로다.
  ///
  /// 예전에는 이 값이 없으면 도면 파일 이름이 곧 프로젝트 이름이었고, 도면을
  /// 올릴 때마다 여기를 null 로 되돌렸다. 그래서 같은 `warehouse.png` 로는
  /// 늘 `warehouse` 프로젝트가 되어, 같은 도면으로 다른 버전을 만들려면 저장
  /// 단계에서 이름 충돌 팝업을 거쳐야 했다. 이름을 먼저 정하는 길(`새
  /// 프로젝트`)을 두고, 도면 올리기가 이 값을 건드리지 않게 했다.
  String? _projectName;
  String? _projectFileName;
  MapStage _stage = MapStage.upload;
  bool _isPicking = false;
  bool _isDeployed = false;
  bool _isDetectingWalls = false;
  bool _isGeneratingFloor = false;
  bool _wallsDetected = false;
  bool _floorGenerated = false;
  _WallMask? _wallMask;
  _WallMask? _floorMask;
  _WallMask? _previousWallMask;
  Color _wallColor = const Color(0xFF2563EB);
  Color _floorColor = const Color(0xFF22C55E);
  bool _isWallEraseMode = false;
  bool _isMeasurementMode = false;
  _MapMeasurement? _measurement;
  bool _isMeasurementSelected = false;
  bool _showDrawingInfo = true;
  bool _isWallConnectMode = false;
  Offset? _pendingWallVertex;
  final List<(Offset, Offset)> _manualWalls = [];
  bool _isWallEndpointEditMode = false;
  final Map<Offset, Offset> _wallVertexOverrides = {};
  List<(Offset, Offset)> _frozenAutoWalls = [];
  List<(Offset, Offset)> _recommendedLanes = [];
  final Map<(Offset, Offset), String> _laneDirections = {};
  final Map<(Offset, Offset), double> _laneSpeedLimits = {};
  final Map<(Offset, Offset), String> _laneOrientations = {};
  final Map<(Offset, Offset), String> _laneMutexGroups = {};
  double _robotWidthMeters = .6;
  double _turningRadiusMeters = .3;
  double _localizationMarginMeters = .1;

  /// Gazebo 월드에서 벽을 얼마나 높게 세울까(m).
  ///
  /// 도면에는 높이가 없다. 길이는 Measurement 로 재지만 높이는 잴 데가 없어
  /// 사람이 넣어야 한다. 자세한 것은 `wall_height.dart`.
  double _wallHeightMeters = defaultWallHeight;

  /// 이 프로젝트가 쓸 ROS 도메인. 로봇마다 따로 정하지 않으면 이 값이다.
  ///
  /// 같은 도메인에 있는 노드끼리만 서로를 본다. 어긋나면 **아무 오류도 안
  /// 나면서** 아무것도 안 통한다 — 앱이 배포한 지도를 터미널에서 띄운
  /// 시뮬레이터가 못 받던 일이 그것이었다. 앱은 비대화형 셸로 스크립트를
  /// 돌리므로 `~/.bashrc` 의 `export ROS_DOMAIN_ID` 를 못 읽는다.
  int _rosDomainId = defaultRosDomainId;

  /// 사람이 직접 넣은 Lane 표시 폭(m). null 이면 로봇 폭으로 그린다.
  ///
  /// 화면에 그리는 굵기일 뿐 주행에는 안 쓴다. 그런데도 받는 이유는, RMF 의
  /// 기본값 0.5m 가 창고용이라 2~3m 짜리 실험실 도면에서는 Lane 하나가 건물
  /// 폭의 1/5 이 되어 스무 개가 서로 겹쳐 덩어리로 보이기 때문이다.
  double? _manualLaneDisplayWidth;

  /// RViz 가 nav graph 를 그릴 굵기(m).
  double get _laneDisplayWidth => navGraphLaneWidth(
    robotWidthMeters: _robotWidthMeters,
    manual: _manualLaneDisplayWidth,
  );

  /// 플릿의 프로필 반경을 지금 안전 기준으로 다시 맞춘다.
  ///
  /// 직접 넣은 값이 있으면 그것이 이긴다 — [RmfFleetSettings.withRobotSafety].
  void _syncFleetProfileToSafety() {
    setState(() {
      _fleetSettings = _fleetSettings.withRobotSafety(
        widthMeters: _robotWidthMeters,
        localizationMarginMeters: _localizationMarginMeters,
      );
    });
  }

  String? _mapScenarioSummary;
  bool _scenarioUsesSeparateRoutes = true;
  List<Offset> _scenarioHoldingAnchors = const [];
  final List<Offset> _laneWaypoints = [];
  final Map<Offset, String> _waypointTypes = {};
  final Map<Offset, String> _waypointNames = {};
  Offset? _activeLaneEndpoint;
  bool _isWaypointMode = false;
  int _vertexLabelRevision = 0;
  bool _showVertexLabels = true;
  final List<_EditorSnapshot> _undoHistory = [];
  String? _processingWarning;

  /// 왼쪽 메뉴에서 지금 보고 있는 화면.
  ///
  /// 자리마다 이름을 둔다. 숫자를 그냥 흩어 두면 메뉴를 가운데 하나 끼울 때
  /// 뒤의 숫자를 전부 같이 밀어야 하고, 한 군데만 놓치면 엉뚱한 화면이 열린다.
  /// 순서는 일하는 차례다 — 맵을 만들고, 그 도면에서 지도를 굽고, 로봇을
  /// 올리고, 작업을 관리하고, ROS2 상태를 확인한 뒤 설정 파일을 다룬다.
  static const _menuDashboard = 0;
  static const _menuMap = 1;
  static const _menuGrid = 2;
  static const _menuRobots = 3;
  static const _menuPolicies = 4;
  static const _menuTasks = 5;
  static const _menuRobotModels = 6;
  static const _menuRos2 = 7;
  static const _menuFiles = 8;
  static const _menuLog = 9;
  static const _menuAnalytics = 10;
  static const _menuProjectAnalytics = 11;

  int _selectedMenu = _menuDashboard;

  AppLifecycleListener? _exitListener;
  StreamSubscription<ProcessSignal>? _interruptSubscription;
  bool _isExiting = false;

  /// 열린 프로젝트의 RMF 플릿 설정. 맵이 다르면 충전소 위치도 다르므로
  /// 프로젝트를 따라간다.
  RmfFleetSettings _fleetSettings = const RmfFleetSettings();

  /// 열린 프로젝트에 등록된 로봇. Gazebo spawn 과 fleet adapter 의 robots
  /// 항목을 함께 만든다.
  List<RmfProjectRobot> _fleetRobots = const [];
  List<WorkcellPolicy> _workcellPolicyModels = const [];

  List<String> get _availableWorkcellPolicies {
    final deployed = deployedPolicyIds(_workcellPolicyModels);
    return deployed.isNotEmpty ? deployed : workcellPoliciesFor(_fleetRobots);
  }

  /// Gazebo 에서 실제로 받아온 위치.
  ///
  /// 값이 들어오면 그 로봇은 앱 계산을 멈추고 이것을 쓴다. 출처를 Gazebo 로
  /// 골라 놓고 앱이 계산한 숫자를 보여 주는 것이 지금까지의 문제였다.
  RobotTelemetryStatus _telemetry = RobotTelemetryStatus.idle;
  StreamSubscription<RobotTelemetryStatus>? _telemetrySubscription;

  /// MySQL에 저장된 채로 지금 열려 있는 맵 프로젝트의 지도 이름.
  ///
  /// 대시보드의 작업은 이 프로젝트에 속한다. 프로젝트를 저장하거나 열기 전에는
  /// null 이며, 그동안에는 작업을 읽지도 쓰지도 않고 주문 자동 분류도 돌지
  /// 않는다 — 작업 단계가 그 맵의 Waypoint 좌표를 들고 있어서, 맵이 정해지지
  /// 않은 상태에서 만들면 아무 데도 가리키지 않는 작업이 되기 때문이다.
  /// 파일에서 연 맵도 MySQL에 저장하기 전까지는 null 이다.
  String? _openProjectName;
  final List<_MockRobot> _mockRobots = [];
  final List<_MockTask> _mockTasks = [];
  final Map<Offset, String> _homeReservations = {};
  Future<void> _taskSaveChain = Future<void>.value();
  Timer? _mockRobotTimer;
  Timer? _orderDispatchTimer;
  bool _isPollingOrders = false;
  bool _databaseReady = false;
  DeployedMapData? _robotDeployedMap;

  @override
  void initState() {
    super.initState();
    // 시작 시점에는 열린 프로젝트가 없다. 작업도 주문 분류도 프로젝트가 정해진
    // 뒤에야 의미가 있으므로 타이머만 걸어 두고 실제 처리는 그때 시작한다.
    _orderDispatchTimer = Timer.periodic(
      const Duration(seconds: 5),
      (_) => unawaited(_pollPendingOrders()),
    );
    // 창을 닫을 때 앱이 띄운 프로젝트를 정리한다. 강제 종료(kill·전원)까지는
    // 막을 수 없으므로, 그때 남은 것을 시작하면서 알아챈다.
    _exitListener = AppLifecycleListener(onExitRequested: _handleExitRequest);
    // 터미널 Ctrl+C는 SIGINT다. 화면의 복사 단축키는 건드리지 않고 OS 신호만
    // 받아 창 X와 Ctrl+X가 쓰는 것과 같은 백엔드 정리를 수행한다.
    if (Platform.isLinux || Platform.isMacOS) {
      _interruptSubscription = ProcessSignal.sigint.watch().listen(
        (_) => unawaited(_handleInterruptSignal()),
      );
    }
    WidgetsBinding.instance.addPostFrameCallback(
      (_) => unawaited(_initializeApplication()),
    );
  }

  Future<void> _initializeApplication() async {
    final layoutWarnings = await workspaceLayoutWarnings();
    if (layoutWarnings.isNotEmpty && mounted) {
      await showWaypointErrorDialog(
        context,
        title: 'RoboSapiens 파일 구조를 확인해주세요',
        message: [
          '상업 배포를 위해 모든 실행 파일은 ~/robosapiens 아래의 실제 디렉터리에 있어야 합니다.',
          '',
          ...layoutWarnings.map((warning) => '• $warning'),
          '',
          '필수 구조:',
          '~/robosapiens/rmf_ws',
          '~/robosapiens/robot_model/pinky_pro',
          '~/robosapiens/robot_model/open_manipulator',
        ].join('\n'),
      );
    }
    try {
      final migration = await migrateDatabaseSchema();
      _databaseReady = true;
      if (migration.changed && mounted) {
        await showWaypointErrorDialog(
          context,
          title: migration.fromVersion == null
              ? 'DB 스키마를 생성했습니다'
              : 'DB 스키마를 자동 업데이트했습니다',
          message: [
            if (migration.fromVersion != null)
              'v${migration.fromVersion} → v${migration.toVersion}',
            '적용: ${migration.applied.join(', ')}',
            if (migration.backupPath != null) '백업: ${migration.backupPath}',
          ].join('\n'),
        );
      }
    } catch (error) {
      _databaseReady = false;
      if (mounted) {
        await showWaypointErrorDialog(
          context,
          title: 'DB 스키마 준비에 실패했습니다',
          message: '$error\n\n데이터 보호를 위해 DB 작업 기능을 시작하지 않았습니다.',
        );
      }
      return;
    }
    await _checkOrphanedProjects();
  }

  /// 지난 실행에서 정리되지 않고 남은 프로젝트를 알린다.
  ///
  /// 강제 종료되면 종료 훅이 돌지 않아 ros2 launch 가 그대로 남는다. 모르고 새로
  /// 띄우면 schedule node 가 부딪혀 엉뚱한 오류로 나타난다.
  Future<void> _checkOrphanedProjects() async {
    List<OrphanedProject> orphans;
    try {
      orphans = await findOrphanedProjects();
    } catch (_) {
      return;
    }
    if (!mounted || orphans.isEmpty) return;
    final cleanUp = await showMovableDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        icon: const Icon(Icons.running_with_errors, size: 34),
        title: const Text('정리되지 않은 프로젝트가 있습니다'),
        content: SizedBox(
          width: 460,
          child: Text(
            '지난 실행이 정상적으로 끝나지 않아 아직 돌고 있는 프로젝트가 있습니다.\n\n'
            '${orphans.map((o) => '· ${o.mapName} (프로세스 그룹 ${o.pgid})').join('\n')}\n\n'
            '그대로 두고 새로 띄우면 schedule node 가 부딪혀 엉뚱한 오류로 나타납니다.',
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('그대로 두기'),
          ),
          FilledButton.icon(
            onPressed: () => Navigator.pop(dialogContext, true),
            icon: const Icon(Icons.cleaning_services_outlined, size: 18),
            label: const Text('정리'),
            style: FilledButton.styleFrom(
              backgroundColor: const Color(0xFFDC2626),
            ),
          ),
        ],
      ),
    );
    if (cleanUp != true || !mounted) return;
    final report = StringBuffer();
    for (final orphan in orphans) {
      final result = await stopProject(orphan.mapName);
      report
        ..writeln('[${orphan.mapName}]')
        ..writeln(result.message)
        ..writeln();
    }
    if (!mounted) return;
    await showWaypointErrorDialog(
      context,
      title: '정리 결과',
      message: report.toString().trim(),
    );
  }

  /// 창을 닫을 때 실행 중인 백엔드를 모두 내린다.
  ///
  /// 기억값 하나만 보면 앱 재시작 뒤 이어서 보고 있던 백엔드를 놓칠 수 있다.
  /// 종료 요청은 사용자가 운영 프로그램과 백엔드를 함께 끝내겠다는 뜻이므로
  /// 실제 PGID 파일을 다시 읽어 현재 실행 중인 프로젝트까지 정리한다.
  Future<ui.AppExitResponse> _handleExitRequest() async {
    if (_isExiting) return ui.AppExitResponse.cancel;
    _isExiting = true;
    try {
      await RobotTelemetryBridge.instance.stop();
      RobotSensorFeed.instance.stop();
      await RmfTaskBridge.instance.stop();
      final projects = <String>{
        if (runningProjectName case final String name) name,
        for (final project in await findRunningProjects()) project.mapName,
      };
      for (final mapName in projects) {
        await stopProject(mapName);
      }
    } finally {
      _isExiting = false;
    }
    return ui.AppExitResponse.exit;
  }

  Future<void> _handleInterruptSignal() async {
    if (_isExiting) return;
    await _handleExitRequest();
    // SIGINT를 구독하면 기본 즉시 종료가 억제되므로 정리가 끝난 뒤 종료한다.
    exit(0);
  }

  /// Ctrl+X도 창의 X 버튼과 같은 종료 요청을 보낸다.
  void _requestAppExit() {
    unawaited(
      ServicesBinding.instance.exitApplication(ui.AppExitType.cancelable),
    );
  }

  /// 열린 프로젝트가 바뀌었을 때 대시보드를 그 프로젝트 상태로 갈아 끼운다.
  Future<void> _switchOpenProject(String? mapName) async {
    setState(() {
      _openProjectName = mapName;
      // 이전 프로젝트의 작업은 이 맵의 Waypoint를 가리키지 않는다. 남겨 두면
      // 갈 곳 없는 목적지를 들고 있는 작업이 화면에 남는다.
      _mockTasks.clear();
      _homeReservations.clear();
      // SLAM 지도도 프로젝트에 딸린다. 앞 프로젝트의 지도를 남겨 두면 다른
      // 창고의 지도를 보며 원점을 맞추게 된다.
      _slamPreview?.dispose();
      _slamPreview = null;
      _slamMap = null;
      // 그리드맵도 마찬가지다. 앞 프로젝트에서 구운 격자가 남아 있으면, 새로
      // 연 프로젝트의 지도가 이미 있는 것으로 보인다.
      _gridPreview?.dispose();
      _gridPreview = null;
      _gridPreviewGrid = null;
      _gridPreviewDirectory = null;
      _gridPreviewSavedAt = null;
      _workcellPolicyModels = const [];
    });
    if (mapName == null) return;
    try {
      final policies = await loadWorkcellPolicies(mapName);
      if (mounted) setState(() => _workcellPolicyModels = policies);
    } catch (_) {
      // Policy 저장소가 아직 없거나 배포 디렉터리가 없는 옛 프로젝트다.
    }
    // 넣어 둔 SLAM 지도가 있으면 올려 준다. 없으면 조용히 지나간다.
    unawaited(_loadStoredSlam(mapName));
    // 구워 둔 그리드맵도 같이 올린다. 프로젝트에 딸린 산출물이므로 열면 그때
    // 만든 것이 그대로 보여야 한다.
    unawaited(_loadStoredGrid(mapName));
    await _loadMockTasks();
    if (!mounted) return;
    await _pollPendingOrders();
  }

  bool _triggerMatches(_OrderTrigger trigger, Set<String> zones) =>
      trigger == _OrderTrigger.any || zones.contains(trigger.name);

  Future<void> _pollPendingOrders() async {
    // 주문을 태스크로 전개하려면 목적지로 삼을 맵이 있어야 한다. 열린 프로젝트가
    // 없으면 주문은 미처리 상태로 그냥 둔다(주문 자체는 창고 공통 원장이다).
    if (!_databaseReady || _openProjectName == null) return;
    if (_isPollingOrders || !mounted) return;
    _isPollingOrders = true;
    try {
      final raw = jsonDecode(await loadPendingOrders());
      if (raw is! List) return;
      for (final value in raw) {
        if (value is! Map<String, dynamic>) continue;
        final orderId = value['id'] as String?;
        if (orderId == null || orderId.isEmpty) continue;
        final existing = _mockTasks
            .where((task) => task.orderId == orderId)
            .firstOrNull;
        if (existing != null) {
          await markOrderDispatched(orderId, existing.id);
          continue;
        }
        final zones = (value['zones'] as List<dynamic>? ?? const ['ambient'])
            .whereType<String>()
            .toSet();
        final template = _mockTasks
            .where(
              (task) =>
                  task.orderId == null &&
                  task.trigger != _OrderTrigger.manual &&
                  _triggerMatches(task.trigger, zones),
            )
            .firstOrNull;
        if (template == null) continue;
        final available =
            _mockRobots
                .where(
                  (robot) => robot.kind.canCarry && robot.activeTaskId == null,
                )
                .toList()
              ..sort((a, b) => b.battery.compareTo(a.battery));
        final robot = available.firstOrNull;
        final task = _MockTask(
          id: _nextTaskId(),
          name: '${template.name} · 주문 $orderId',
          description:
              '${template.description}${template.description.isEmpty ? '' : '\n'}'
              '자동 생성 주문: $orderId · 고객: ${value['customer'] ?? '-'}',
          type: template.type,
          robotId: robot?.id ?? '__auto__',
          orderId: orderId,
          urgency: _TaskUrgency.parse(value['urgency'] as String?),
          steps: [
            for (final step in template.steps)
              _MockTaskStep(
                type: step.type,
                destination: step.destination,
                destinationName: step.destinationName,
                durationSeconds: step.durationSeconds,
                policyId: step.policyId,
              ),
          ],
        );
        setState(() {
          task.status = robot == null
              ? _MockTaskStatus.queued
              : _MockTaskStatus.active;
          _mockTasks.insert(0, task);
          if (robot != null) {
            robot.activeTaskId = task.id;
            _startTaskStep(robot, task);
          }
        });
        await _saveMockTasks();
        await markOrderDispatched(orderId, task.id);
      }
      _startQueuedOrderTasks();
      if (_processingWarning?.startsWith('[주문 자동 분류]') == true && mounted) {
        setState(() => _processingWarning = null);
      }
    } catch (error) {
      if (!mounted) return;
      setState(() => _processingWarning = '[주문 자동 분류] MySQL 주문 처리 실패: $error');
    } finally {
      _isPollingOrders = false;
    }
  }

  void _startQueuedOrderTasks() {
    final available =
        _mockRobots
            .where((robot) => robot.kind.canCarry && robot.activeTaskId == null)
            .toList()
          ..sort((a, b) => b.battery.compareTo(a.battery));
    // 목록은 새 작업이 위로 오게 정렬돼 있다. 그대로 꺼내 쓰면 나중에 들어온
    // 주문이 먼저 나가고 기다리던 주문이 뒤로 밀린다.
    final queued = dispatchOrder(
      _mockTasks.where(
        (task) => task.orderId != null && task.status == _MockTaskStatus.queued,
      ),
      (task) => task.createdAt,
      priority: (task) => task.urgency.weight,
    );
    var changed = false;
    while (available.isNotEmpty && queued.isNotEmpty) {
      final robot = available.removeAt(0);
      final task = queued.removeAt(0);
      task
        ..robotId = robot.id
        ..status = _MockTaskStatus.active;
      robot.activeTaskId = task.id;
      _startTaskStep(robot, task);
      changed = true;
    }
    if (changed) {
      setState(() {});
      unawaited(_saveMockTasks());
      _startMockRobotTimer();
    }
  }

  Map<String, Object?> _encodeTask(_MockTask task) => {
    'id': task.id,
    'name': task.name,
    'description': task.description,
    'type': task.type,
    'robotId': task.robotId,
    'status': task.status.name,
    'trigger': task.trigger.name,
    'orderId': task.orderId,
    'urgency': task.urgency.name,
    'currentStepIndex': task.currentStepIndex,
    'createdAt': task.createdAt.toIso8601String(),
    'completedAt': task.completedAt?.toIso8601String(),
    'initialRobotPosition': task.initialRobotPosition == null
        ? null
        : {
            'x': task.initialRobotPosition!.dx,
            'y': task.initialRobotPosition!.dy,
          },
    'initialRobotHeading': task.initialRobotHeading,
    'steps': [
      for (final step in task.steps)
        {
          'type': step.type.name,
          'destination': step.destination == null
              ? null
              : {'x': step.destination!.dx, 'y': step.destination!.dy},
          'destinationName': step.destinationName,
          'durationSeconds': step.durationSeconds,
          'policyId': step.policyId,
          'status': step.status.name,
          'remainingSeconds': step.remainingSeconds,
          'failureReason': step.failureReason,
        },
    ],
  };

  _MockTask _decodeTask(Map<String, dynamic> data) {
    final savedStatus = _MockTaskStatus.values.byName(
      data['status'] as String? ?? _MockTaskStatus.queued.name,
    );
    final task = _MockTask(
      id: data['id'] as String,
      name: data['name'] as String? ?? '저장된 작업',
      description: data['description'] as String? ?? '',
      type: data['type'] as String? ?? '연속 작업',
      robotId: data['robotId'] as String? ?? '__auto__',
      trigger: _OrderTrigger.values.byName(
        data['trigger'] as String? ?? _OrderTrigger.manual.name,
      ),
      orderId: data['orderId'] as String?,
      urgency: _TaskUrgency.parse(data['urgency'] as String?),
      createdAt:
          DateTime.tryParse(data['createdAt'] as String? ?? '') ??
          DateTime.now(),
      steps: [
        for (final raw in data['steps'] as List<dynamic>? ?? const [])
          if (raw is Map<String, dynamic>)
            _MockTaskStep(
                type: _TaskStepType.values.byName(raw['type'] as String),
                destination: switch (raw['destination']) {
                  {'x': final num x, 'y': final num y} => Offset(
                    x.toDouble(),
                    y.toDouble(),
                  ),
                  _ => null,
                },
                destinationName: raw['destinationName'] as String?,
                durationSeconds:
                    (raw['durationSeconds'] as num?)?.toDouble() ?? 0,
                policyId: raw['policyId'] as String? ?? 'policy_1',
              )
              ..status = _TaskStepStatus.values.byName(
                raw['status'] as String? ?? _TaskStepStatus.pending.name,
              )
              ..remainingSeconds =
                  (raw['remainingSeconds'] as num?)?.toDouble() ?? 0
              ..failureReason = raw['failureReason'] as String?,
      ],
    );
    task.status = savedStatus == _MockTaskStatus.active
        ? _MockTaskStatus.queued
        : savedStatus;
    task.currentStepIndex = (data['currentStepIndex'] as num?)?.toInt() ?? 0;
    if (savedStatus == _MockTaskStatus.active ||
        savedStatus == _MockTaskStatus.queued) {
      task.currentStepIndex = 0;
      for (final step in task.steps) {
        step
          ..status = _TaskStepStatus.pending
          ..remainingSeconds = 0
          ..failureReason = null;
      }
    }
    task.completedAt = DateTime.tryParse(data['completedAt'] as String? ?? '');
    task.initialRobotPosition = switch (data['initialRobotPosition']) {
      {'x': final num x, 'y': final num y} => Offset(
        x.toDouble(),
        y.toDouble(),
      ),
      _ => null,
    };
    task.initialRobotHeading = (data['initialRobotHeading'] as num?)
        ?.toDouble();
    return task;
  }

  Future<void> _loadMockTasks() async {
    final project = _openProjectName;
    if (project == null) return;
    try {
      final contents = await loadSavedTasks(project);
      if (contents == null || contents.trim().isEmpty) return;
      final data = jsonDecode(contents);
      if (data is! List) return;
      final loaded = <_MockTask>[];
      for (final raw in data) {
        if (raw is! Map<String, dynamic>) continue;
        try {
          loaded.add(_decodeTask(raw));
        } catch (_) {
          // 손상된 단일 작업은 건너뛰고 나머지 목록을 복원한다.
        }
      }
      if (!mounted) return;
      setState(() {
        final currentIds = _mockTasks.map((task) => task.id).toSet();
        _mockTasks.addAll(
          loaded.where((task) => !currentIds.contains(task.id)),
        );
      });
    } catch (error) {
      if (!mounted) return;
      setState(() => _processingWarning = '[작업 불러오기] 저장된 작업을 읽지 못했습니다: $error');
    }
  }

  Future<void> _saveMockTasks() {
    // 작업은 맵 프로젝트에 속한다. 저장할 프로젝트가 정해지지 않았으면 쓸 곳이
    // 없다. 이 경로는 화면에서 작업을 만들 수 없게 막아 두어 실제로는 오지
    // 않지만, 어느 맵의 것인지 모르는 작업이 DB에 들어가는 일은 없어야 한다.
    final project = _openProjectName;
    if (project == null) return _taskSaveChain;
    final contents = const JsonEncoder.withIndent(
      '  ',
    ).convert(_mockTasks.map(_encodeTask).toList());
    _taskSaveChain = _taskSaveChain
        .then((_) => saveTasks(project, contents))
        .catchError((Object error) {
          if (!mounted) return;
          setState(
            () => _processingWarning = '[작업 저장] 작업 목록을 저장하지 못했습니다: $error',
          );
        });
    return _taskSaveChain;
  }

  String _nextTaskId() {
    var highest = 0;
    for (final task in _mockTasks) {
      final number = int.tryParse(task.id.replaceFirst('TASK-', ''));
      if (number != null) highest = math.max(highest, number);
    }
    return 'TASK-${(highest + 1).toString().padLeft(3, '0')}';
  }

  void _showProcessingWarning(String operation, Object error) {
    if (!mounted) return;
    final message = [
      '[$operation] 처리 중 문제가 발생했습니다.',
      '원인: $error',
      '입력값과 설정을 확인한 뒤 다시 시도해 주세요.',
    ].join('\n');
    setState(() => _processingWarning = message);
  }

  void _clearProcessingWarning() {
    if (_processingWarning != null) {
      setState(() => _processingWarning = null);
    }
  }

  String _laneLabel((Offset, Offset) lane) =>
      '${_waypointLabel(lane.$1)} ↔ ${_waypointLabel(lane.$2)}';

  /// 목록이 길면 앞쪽만 보이고 나머지는 수로 줄인다. 수십 개를 다 나열하면
  /// 정작 무엇을 고쳐야 하는지 묻히기 때문이다.
  static String _summarize(Iterable<String> items, {int limit = 8}) {
    final list = items.toList();
    if (list.length <= limit) return list.join(', ');
    return '${list.take(limit).join(', ')} 외 ${list.length - limit}개';
  }

  /// 레인 위에 얹혀 있으면서 그 레인에 연결되지 않은 Waypoint.
  ///
  /// 눈으로는 선 위에 있으니 이어진 줄 알지만 그래프상 연결이 없어, 로봇이 그
  /// 지점을 지나갈 수 없다. 작업 순서대로 가다가 엉뚱한 곳으로 되돌아가는 원인이
  /// 된다. 이제 Waypoint 를 놓을 때 레인에 스냅되지만, 그 전에 만든 맵에는
  /// 남아 있다.
  Map<Offset, List<(Offset, Offset)>> _laneDetachedWaypoints() {
    final tolerance = _waypointLaneSnapTolerance;
    final result = <Offset, List<(Offset, Offset)>>{};
    for (final point in _laneWaypoints) {
      if (_waypointTypes[point] == '설비') continue;
      final lanes = [
        for (final lane in _recommendedLanes)
          if ((lane.$1 - point).distance > .01 &&
              (lane.$2 - point).distance > .01 &&
              pointSegmentDistance(point, lane.$1, lane.$2) <= tolerance)
            lane,
      ];
      if (lanes.isNotEmpty) result[point] = lanes;
    }
    return result;
  }

  /// 레인 위에 얹힌 Waypoint들을 그 레인에 끼워 넣는다.
  ///
  /// 스냅이 없던 때 만든 맵을 고치는 용도다. 실행 취소로 되돌릴 수 있다.
  Future<void> _spliceDetachedWaypoints() async {
    final detached = _laneDetachedWaypoints();
    if (detached.isEmpty) return;
    final tolerance = _waypointLaneSnapTolerance;
    _recordUndo();
    var splicedLanes = 0;
    setState(() {
      for (final point in detached.keys) {
        splicedLanes += _spliceWaypointIntoLanes(point, tolerance);
      }
      _isDeployed = false;
      _vertexLabelRevision++;
    });
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          'Waypoint ${detached.length}개를 레인에 끼워 넣었습니다 '
          '(레인 $splicedLanes개를 나눠 이음). 실행 취소로 되돌릴 수 있습니다.',
        ),
        duration: const Duration(seconds: 6),
        showCloseIcon: true,
      ),
    );
    await _saveSettingToOpenProject(
      label: '레인 연결',
      detail: 'Waypoint ${detached.length}개를 레인에 끼워 넣음',
    );
  }

  List<String> _validateMap() {
    final warnings = <String>[];
    final detached = _laneDetachedWaypoints();
    if (detached.isNotEmpty) {
      warnings.add(
        '레인 위에 있으나 그 레인에 연결되지 않은 Waypoint가 ${detached.length}개 있습니다: '
        '${_summarize(detached.entries.map((entry) => '${_waypointLabel(entry.key)}'
            '(${entry.value.map(_laneLabel).join(', ')} 위)'))}. '
        '로봇이 이 지점을 지나갈 수 없어 먼 길로 돌아갑니다. '
        '`레인에 끼워 넣기`를 누르면 해당 레인을 이 지점에서 나눠 잇습니다.',
      );
    }
    if (_measurement == null) {
      warnings.add('기준 길이(Measurement)가 없어 실제 축척을 계산할 수 없습니다.');
    }
    if (_floorOutline().length < 3) {
      warnings.add('Floor 경계를 구성할 정점이 3개보다 적습니다.');
    }
    if (_recommendedLanes.isEmpty) {
      warnings.add('Lane이 하나도 없습니다.');
    } else {
      final zeroLengthLanes = _recommendedLanes
          .where((lane) => (lane.$1 - lane.$2).distance <= .01)
          .toList();
      if (zeroLengthLanes.isNotEmpty) {
        warnings.add(
          '시작점과 끝점이 같은 Lane이 ${zeroLengthLanes.length}개 있습니다: '
          '${_summarize(zeroLengthLanes.map(_laneLabel))}.',
        );
      }
      final duplicateLanes = <String>{};
      for (var i = 0; i < _recommendedLanes.length; i++) {
        for (var j = i + 1; j < _recommendedLanes.length; j++) {
          final first = _recommendedLanes[i];
          final second = _recommendedLanes[j];
          final sameDirection =
              (first.$1 - second.$1).distance <= .01 &&
              (first.$2 - second.$2).distance <= .01;
          final reverseDirection =
              (first.$1 - second.$2).distance <= .01 &&
              (first.$2 - second.$1).distance <= .01;
          if (sameDirection || reverseDirection) {
            duplicateLanes.add(_laneLabel(first));
          }
        }
      }
      if (duplicateLanes.isNotEmpty) {
        warnings.add(
          '같은 Waypoint 쌍을 잇는 Lane이 겹쳐 있습니다: '
          '${_summarize(duplicateLanes)}.',
        );
      }
      final wallCrossingLanes = _recommendedLanes
          .where((lane) => _crossesWall(lane.$1, lane.$2))
          .toList();
      if (wallCrossingLanes.isNotEmpty) {
        warnings.add(
          '벽을 통과하는 Lane이 ${wallCrossingLanes.length}개 있습니다: '
          '${_summarize(wallCrossingLanes.map(_laneLabel))}.',
        );
      }
      final metersPerPixel = _metersPerPixel;
      if (metersPerPixel != null) {
        final minimumLaneLengthMeters = math.max(.3, _turningRadiusMeters * 2);
        final minimumWallClearanceMeters =
            _robotWidthMeters / 2 + _localizationMarginMeters;
        final shortLanes = _recommendedLanes
            .where(
              (lane) =>
                  (lane.$1 - lane.$2).distance * metersPerPixel <
                  minimumLaneLengthMeters,
            )
            .toList();
        if (shortLanes.isNotEmpty) {
          final labels = shortLanes.map((lane) {
            final meters = (lane.$1 - lane.$2).distance * metersPerPixel;
            return '${_laneLabel(lane)} (${meters.toStringAsFixed(2)}m)';
          });
          warnings.add(
            '길이가 ${minimumLaneLengthMeters}m보다 짧아 회전·정지 여유가 부족한 Lane이 '
            '${shortLanes.length}개 있습니다: ${_summarize(labels)}.',
          );
        }
        final walls = _visibleWallSegments();
        // 여유가 얼마나 모자란지 함께 보여 준다. 로봇 폭이 잘못 잡혀서 전부
        // 걸리는 것인지, 특정 Lane 하나만 벽에 붙은 것인지 구분되어야 한다.
        final narrowLanes = <(Offset, Offset), double>{};
        for (final lane in _recommendedLanes) {
          if (walls.isEmpty) break;
          final clearanceMeters =
              walls
                  .map(
                    (wall) =>
                        _segmentDistance(lane.$1, lane.$2, wall.$1, wall.$2),
                  )
                  .reduce(math.min) *
              metersPerPixel;
          if (clearanceMeters < minimumWallClearanceMeters) {
            narrowLanes[lane] = clearanceMeters;
          }
        }
        if (narrowLanes.isNotEmpty) {
          warnings.add(
            '벽과의 중심선 여유가 ${minimumWallClearanceMeters}m보다 작은 Lane이 '
            '${narrowLanes.length}개 있습니다: '
            '${_summarize(narrowLanes.entries.map((entry) => '${_laneLabel(entry.key)} (${entry.value.toStringAsFixed(2)}m)'))}. '
            '로봇 폭을 확인하세요.',
          );
        }
      }
      final adjacency = <Offset, Set<Offset>>{};
      for (final lane in _recommendedLanes) {
        adjacency.putIfAbsent(lane.$1, () => <Offset>{}).add(lane.$2);
        adjacency.putIfAbsent(lane.$2, () => <Offset>{}).add(lane.$1);
      }
      final visited = <Offset>{};
      final queue = <Offset>[adjacency.keys.first];
      while (queue.isNotEmpty) {
        final point = queue.removeLast();
        if (!visited.add(point)) continue;
        queue.addAll(
          adjacency[point]!.where((next) => !visited.contains(next)),
        );
      }
      final disconnected = adjacency.keys.where(
        (point) => !visited.contains(point),
      );
      if (disconnected.isNotEmpty) {
        warnings.add(
          'Lane 네트워크가 분리되어 접근할 수 없는 Waypoint가 '
          '${disconnected.length}개 있습니다: '
          '${_summarize(disconnected.map(_waypointLabel))}.',
        );
      }
      final directed = <Offset, Set<Offset>>{
        for (final point in _laneWaypoints)
          if (_waypointTypes[point] != '설비') point: <Offset>{},
      };
      final reversed = <Offset, Set<Offset>>{
        for (final point in _laneWaypoints)
          if (_waypointTypes[point] != '설비') point: <Offset>{},
      };
      void addDirected(Offset from, Offset to) {
        directed.putIfAbsent(from, () => <Offset>{}).add(to);
        directed.putIfAbsent(to, () => <Offset>{});
        reversed.putIfAbsent(to, () => <Offset>{}).add(from);
        reversed.putIfAbsent(from, () => <Offset>{});
      }

      for (final lane in _recommendedLanes) {
        final direction = _laneDirections[lane] ?? '양방향';
        if (direction != '역방향') addDirected(lane.$1, lane.$2);
        if (direction != '정방향') addDirected(lane.$2, lane.$1);
      }
      Set<Offset> reachable(Map<Offset, Set<Offset>> graph, Offset start) {
        final visited = <Offset>{};
        final pending = <Offset>[start];
        while (pending.isNotEmpty) {
          final point = pending.removeLast();
          if (!visited.add(point)) continue;
          pending.addAll(
            (graph[point] ?? const <Offset>{}).where(
              (next) => !visited.contains(next),
            ),
          );
        }
        return visited;
      }

      if (directed.isNotEmpty) {
        final root = directed.keys.first;
        final unreachable = directed.keys.toSet()
          ..removeAll(reachable(directed, root));
        final noReturnPath = reversed.keys.toSet()
          ..removeAll(reachable(reversed, root));
        if (unreachable.isNotEmpty || noReturnPath.isNotEmpty) {
          warnings.add(
            '단방향 규칙 때문에 모든 Waypoint를 왕복할 수 없습니다. '
            '${_waypointLabel(root)}에서 갈 수 없는 곳: '
            '${unreachable.isEmpty ? '없음' : _summarize(unreachable.map(_waypointLabel))}. '
            '거기서 ${_waypointLabel(root)}로 돌아올 수 없는 곳: '
            '${noReturnPath.isEmpty ? '없음' : _summarize(noReturnPath.map(_waypointLabel))}.',
          );
        }
      }
    }
    final connectedPoints = <Offset>{
      for (final lane in _recommendedLanes) ...[lane.$1, lane.$2],
    };
    final orphans = _laneWaypoints
        .where(
          (point) =>
              _waypointTypes[point] != '설비' &&
              !connectedPoints.any(
                (connected) => (connected - point).distance <= .01,
              ),
        )
        .toList();
    if (orphans.isNotEmpty) {
      warnings.add(
        '어떤 Lane에도 연결되지 않은 Waypoint가 ${orphans.length}개 있습니다: '
        '${_summarize(orphans.map(_waypointLabel))}.',
      );
    }
    final connectedEquipment = _laneWaypoints
        .where(
          (point) =>
              _waypointTypes[point] == '설비' &&
              connectedPoints.any(
                (connected) => (connected - point).distance <= .01,
              ),
        )
        .toList();
    if (connectedEquipment.isNotEmpty) {
      warnings.add(
        '고정 설비 Waypoint가 Lane에 연결되어 있습니다: '
        '${_summarize(connectedEquipment.map(_waypointLabel))}. '
        '이동 로봇용 픽업 Waypoint를 별도로 만드세요.',
      );
    }
    final names = _waypointNames.values
        .map((name) => name.trim())
        .where((name) => name.isNotEmpty);
    final seenNames = <String>{};
    final duplicateNames = <String>{};
    for (final name in names) {
      if (!seenNames.add(name)) duplicateNames.add(name);
    }
    if (duplicateNames.isNotEmpty) {
      warnings.add('중복된 Waypoint 이름이 있습니다: ${duplicateNames.join(', ')}.');
    }
    return warnings;
  }

  Future<void> _showRobotSafetySettings() async {
    final widthController = TextEditingController(
      text: _robotWidthMeters.toStringAsFixed(2),
    );
    final radiusController = TextEditingController(
      text: _turningRadiusMeters.toStringAsFixed(2),
    );
    final marginController = TextEditingController(
      text: _localizationMarginMeters.toStringAsFixed(2),
    );
    // 비워 두면 맵에서 계산한 값을 쓴다. 지금 쓰는 값을 미리 채워 둔다.
    final toleranceController = TextEditingController(
      text: _goalTolerance.toStringAsFixed(3),
    );
    // 아래 셋은 비우면 자동이다. 직접 넣은 값이 있을 때만 채워 둔다 — 계산값을
    // 미리 적어 두면 폭을 고쳐도 그 값이 남아, 왜 안 따라오는지 알 수 없다.
    final footprintController = TextEditingController(
      text: _fleetSettings.manualFootprintRadius?.toStringAsFixed(3) ?? '',
    );
    final vicinityController = TextEditingController(
      text: _fleetSettings.manualVicinityRadius?.toStringAsFixed(3) ?? '',
    );
    final laneWidthController = TextEditingController(
      text: _manualLaneDisplayWidth?.toStringAsFixed(2) ?? '',
    );
    // 주행 한계. 예전에는 로봇 등록 창에 있었다. 값은 플릿 하나인데 로봇 창에
    // 있으니 로봇마다 정하는 것처럼 보였고, 정작 찾을 때는 여기부터 뒤지게
    // 됐다 — footprint·vicinity 같은 다른 플릿 값이 여기 있기 때문이다.
    //
    // 벤더 Nav2 파일의 값을 곁들여 보여 준다. 이 숫자의 근거가 거기라서,
    // 아무 데서도 못 보면 무엇을 기준으로 정할지 알 수 없다.
    final vendorSource = readVendorNav2Params();
    final vendorLimits = vendorSource == null
        ? const VendorSpeedLimits()
        : parseVendorSpeedLimits(vendorSource);
    final linearVelocityController = TextEditingController(
      text: _fleetSettings.linearVelocity.toStringAsFixed(2),
    );
    final linearAccelerationController = TextEditingController(
      text: _fleetSettings.linearAcceleration.toStringAsFixed(2),
    );
    final angularVelocityController = TextEditingController(
      text: _fleetSettings.angularVelocity.toStringAsFixed(2),
    );
    final angularAccelerationController = TextEditingController(
      text: _fleetSettings.angularAcceleration.toStringAsFixed(2),
    );
    String? footprintError;
    String? vicinityError;
    String? laneWidthError;
    final floor = minimumGoalTolerance();
    final recommended = _recommendedGoalTolerance;
    final spacing = _minLaneSpacing;
    String? widthError;
    String? radiusError;
    String? marginError;
    String? toleranceError;
    String? toleranceWarning;
    // 최소보다 작은 값을 한 번 되물은 뒤, 같은 값으로 다시 누르면 넣는다.
    double? toleranceForced;
    final values =
        await showMovableDialog<
          ({
            double width,
            double radius,
            double margin,
            double? tolerance,
            double? footprint,
            double? vicinity,
            double? laneWidth,
            double? linearVelocity,
            double? linearAcceleration,
            double? angularVelocity,
            double? angularAcceleration,
          })
        >(
          context: context,
          builder: (dialogContext) => StatefulBuilder(
            builder: (context, setDialogState) {
              // 지금 적힌 속도로 Nav2 의 "끼었나" 판정을 벗어날 수 있는지.
              // 타자를 칠 때마다 다시 본다.
              final speed = double.tryParse(
                linearVelocityController.text.trim(),
              );
              final progressWarning =
                  speed == null ||
                      vendorLimits.progressAllowanceSeconds == null ||
                      vendorLimits.progressRadiusMeters == null
                  ? null
                  : progressCheckerWarning(
                      linearVelocity: speed,
                      allowanceSeconds: vendorLimits.progressAllowanceSeconds!,
                      vendorRadius: vendorLimits.progressRadiusMeters!,
                    );
              return AlertDialog(
                icon: const Icon(
                  Icons.precision_manufacturing_outlined,
                  size: 34,
                ),
                title: const Text('로봇 주행 안전 기준'),
                content: SizedBox(
                  width: 390,
                  child: SingleChildScrollView(
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        TextField(
                          controller: widthController,
                          keyboardType: const TextInputType.numberWithOptions(
                            decimal: true,
                          ),
                          decoration: InputDecoration(
                            labelText: '로봇 최대 폭 (m)',
                            helperText:
                                '좌우로 가장 넓은 실제 폭입니다. 적재물·돌출 센서·보호 범퍼를 포함한 최대값을 입력하세요.',
                            helperMaxLines: 2,
                            errorText: widthError,
                            border: const OutlineInputBorder(),
                          ),
                        ),
                        const SizedBox(height: 12),
                        TextField(
                          controller: radiusController,
                          keyboardType: const TextInputType.numberWithOptions(
                            decimal: true,
                          ),
                          decoration: InputDecoration(
                            labelText: '최소 회전 반경 (m)',
                            helperText:
                                '로봇이 주행하며 회전할 때 필요한 최소 반경입니다. 제자리 회전이 가능하면 0을 입력할 수 있습니다.',
                            helperMaxLines: 2,
                            errorText: radiusError,
                            border: const OutlineInputBorder(),
                          ),
                        ),
                        const SizedBox(height: 12),
                        TextField(
                          controller: marginController,
                          keyboardType: const TextInputType.numberWithOptions(
                            decimal: true,
                          ),
                          decoration: InputDecoration(
                            labelText: '위치 오차·안전 여유 (m)',
                            helperText:
                                'Localization 오차, 제어 편차와 벽 충돌 방지를 위해 로봇 외곽에 추가할 거리입니다.',
                            helperMaxLines: 2,
                            errorText: marginError,
                            border: const OutlineInputBorder(),
                          ),
                        ),
                        const SizedBox(height: 12),
                        TextField(
                          controller: toleranceController,
                          keyboardType: const TextInputType.numberWithOptions(
                            decimal: true,
                          ),
                          decoration: InputDecoration(
                            labelText: '도착 인정 반경 (m)',
                            helperText:
                                '최소 ${floor.toStringAsFixed(3)} · '
                                '이 맵 권장 ${recommended.toStringAsFixed(3)}'
                                '${spacing == null ? '' : ' (레인 최소 간격 ${spacing.toStringAsFixed(3)}m ÷ 4)'}'
                                '\n비우면 권장값을 씁니다. 벤더 기본값은 '
                                '${vendorGoalTolerance.toStringAsFixed(2)}m 입니다.',
                            helperMaxLines: 3,
                            errorText: toleranceError,
                            border: const OutlineInputBorder(),
                          ),
                          onChanged: (_) => setDialogState(() {
                            toleranceError = null;
                            // 값을 고치면 되묻기를 처음부터 다시 한다.
                            toleranceForced = null;
                            final value = _parseMeters(
                              toleranceController.text,
                            );
                            toleranceWarning =
                                value != null && value > 0 && value < floor
                                ? '코스트맵 한 칸이 ${nav2CostmapResolution.toStringAsFixed(2)}m 입니다. '
                                      '이보다 촘촘히 요구하면 Nav2 가 목표를 못 맞추고 '
                                      '주변을 맴돌다 포기합니다. 실제로 0.080 을 넣었다가 '
                                      '픽업 지점에 닿지 못했습니다.'
                                : null;
                          }),
                        ),
                        if (toleranceWarning != null) ...[
                          const SizedBox(height: 6),
                          Row(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              const Icon(
                                Icons.warning_amber_rounded,
                                size: 16,
                                color: Color(0xFFD97706),
                              ),
                              const SizedBox(width: 6),
                              Expanded(
                                child: Text(
                                  toleranceWarning!,
                                  style: const TextStyle(
                                    fontSize: 12,
                                    color: Color(0xFF92400E),
                                  ),
                                ),
                              ),
                            ],
                          ),
                        ],
                        const SizedBox(height: 18),
                        const Divider(height: 1),
                        const SizedBox(height: 14),
                        const Align(
                          alignment: Alignment.centerLeft,
                          child: Text(
                            '직접 지정 (비우면 위 값에서 계산)',
                            style: TextStyle(fontWeight: FontWeight.w800),
                          ),
                        ),
                        const SizedBox(height: 4),
                        const Align(
                          alignment: Alignment.centerLeft,
                          child: Text(
                            '로봇을 원으로 보는 계산은 어림입니다. 적재물이나 범퍼가 튀어나오면 '
                            '실제로 재서 넣는 편이 맞습니다.',
                            style: TextStyle(
                              color: Color(0xFF64748B),
                              fontSize: 12,
                            ),
                          ),
                        ),
                        const SizedBox(height: 12),
                        TextField(
                          controller: footprintController,
                          keyboardType: const TextInputType.numberWithOptions(
                            decimal: true,
                          ),
                          decoration: InputDecoration(
                            labelText: '충돌 반경 footprint (m)',
                            helperText:
                                'RMF 가 로봇을 이 반경의 원으로 봅니다. '
                                '자동 ${(_parseMeters(widthController.text) ?? _robotWidthMeters) / 2 <= 0 ? '-' : ((_parseMeters(widthController.text) ?? _robotWidthMeters) / 2).toStringAsFixed(3)} '
                                '(로봇 폭 ÷ 2)',
                            helperMaxLines: 2,
                            errorText: footprintError,
                            border: const OutlineInputBorder(),
                          ),
                          onChanged: (_) =>
                              setDialogState(() => footprintError = null),
                        ),
                        const SizedBox(height: 12),
                        TextField(
                          controller: vicinityController,
                          keyboardType: const TextInputType.numberWithOptions(
                            decimal: true,
                          ),
                          decoration: InputDecoration(
                            labelText: '접근 금지 반경 vicinity (m)',
                            helperText:
                                '이 원 안에 다른 로봇을 들이지 않습니다. 크면 좁은 통로에서 '
                                '서로 비켜 주기만 하다 아무도 못 지나갑니다.',
                            helperMaxLines: 2,
                            errorText: vicinityError,
                            border: const OutlineInputBorder(),
                          ),
                          onChanged: (_) =>
                              setDialogState(() => vicinityError = null),
                        ),
                        const SizedBox(height: 12),
                        TextField(
                          controller: laneWidthController,
                          keyboardType: const TextInputType.numberWithOptions(
                            decimal: true,
                          ),
                          decoration: InputDecoration(
                            labelText: 'Lane 표시 폭 · RViz (m)',
                            helperText:
                                '화면에 그리는 굵기일 뿐 주행에는 안 씁니다. 비우면 로봇 폭 '
                                '(${_robotWidthMeters.toStringAsFixed(2)}m)으로 그립니다. '
                                '최소 ${minNavGraphLaneWidth.toStringAsFixed(2)}m — 시각화 노드가 그 아래를 안 받습니다.',
                            helperMaxLines: 3,
                            errorText: laneWidthError,
                            border: const OutlineInputBorder(),
                          ),
                          onChanged: (_) =>
                              setDialogState(() => laneWidthError = null),
                        ),
                        const SizedBox(height: 10),
                        const Text(
                          '필요한 벽 여유는 로봇 폭의 절반과 안전 여유를 합산하고, 최소 Lane 길이는 회전 반경의 2배로 검사합니다.',
                          style: TextStyle(
                            color: Color(0xFF64748B),
                            fontSize: 12,
                          ),
                        ),
                        const SizedBox(height: 18),
                        const Divider(height: 1),
                        const SizedBox(height: 12),
                        Row(
                          children: [
                            const Expanded(
                              child: Text(
                                '주행 한계',
                                style: TextStyle(
                                  fontSize: 13,
                                  fontWeight: FontWeight.w600,
                                ),
                              ),
                            ),
                            TextButton.icon(
                              onPressed: vendorLimits.isEmpty
                                  ? null
                                  : () => setDialogState(() {
                                      void fill(
                                        TextEditingController controller,
                                        double? value,
                                      ) {
                                        if (value == null) return;
                                        controller.text = value.toStringAsFixed(
                                          2,
                                        );
                                      }

                                      fill(
                                        linearVelocityController,
                                        vendorLimits.linearVelocity,
                                      );
                                      fill(
                                        linearAccelerationController,
                                        vendorLimits.linearAcceleration,
                                      );
                                      fill(
                                        angularVelocityController,
                                        vendorLimits.angularVelocity,
                                      );
                                      fill(
                                        angularAccelerationController,
                                        vendorLimits.angularAcceleration,
                                      );
                                    }),
                              icon: const Icon(
                                Icons.download_outlined,
                                size: 18,
                              ),
                              label: const Text('벤더 값 불러오기'),
                            ),
                          ],
                        ),
                        Text(
                          vendorLimits.isEmpty
                              ? '벤더 Nav2 파일을 찾지 못해 불러올 값이 없습니다. '
                                    '$nav2ParamsEnvironmentKey 환경 변수로 자리를 알려 주세요.'
                              : '로봇을 실제로 움직이는 속도이자, RMF 가 도착 시각을 계산할 '
                                    '때 쓰는 값입니다. 내보내기가 이 값을 로봇별 '
                                    'nav2_params.yaml 에도 함께 씁니다. 플릿 전체에 '
                                    '적용됩니다.',
                          style: TextStyle(
                            fontSize: 12,
                            color: vendorLimits.isEmpty
                                ? const Color(0xFFB45309)
                                : const Color(0xFF64748B),
                          ),
                        ),
                        const SizedBox(height: 12),
                        Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Expanded(
                              child: _limitField(
                                controller: linearVelocityController,
                                label: '직진 속도',
                                unit: 'm/s',
                                vendor: vendorLimits.linearVelocity,
                                onChanged: (_) => setDialogState(() {}),
                              ),
                            ),
                            const SizedBox(width: 12),
                            Expanded(
                              child: _limitField(
                                controller: linearAccelerationController,
                                label: '직진 가속도',
                                unit: 'm/s²',
                                vendor: vendorLimits.linearAcceleration,
                              ),
                            ),
                          ],
                        ),
                        const SizedBox(height: 12),
                        Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Expanded(
                              child: _limitField(
                                controller: angularVelocityController,
                                label: '회전 속도',
                                unit: 'rad/s',
                                vendor: vendorLimits.angularVelocity,
                              ),
                            ),
                            const SizedBox(width: 12),
                            Expanded(
                              child: _limitField(
                                controller: angularAccelerationController,
                                label: '회전 가속도',
                                unit: 'rad/s²',
                                vendor: vendorLimits.angularAcceleration,
                              ),
                            ),
                          ],
                        ),
                        // 너무 느리면 Nav2 가 정상 주행을 "끼었다" 로 판정한다.
                        // 요구 거리는 내보낼 때 속도에 맞춰 낮춰 주지만 바닥이
                        // 있어서, 그 아래로 내려가면 값을 맞춰도 소용이 없다.
                        if (progressWarning != null) ...[
                          const SizedBox(height: 12),
                          Container(
                            width: double.infinity,
                            padding: const EdgeInsets.all(12),
                            decoration: BoxDecoration(
                              color: const Color(0xFFFEF2F2),
                              borderRadius: BorderRadius.circular(9),
                              border: Border.all(
                                color: const Color(0xFFFECACA),
                              ),
                            ),
                            child: Row(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                const Icon(
                                  Icons.warning_amber_rounded,
                                  size: 18,
                                  color: Color(0xFFDC2626),
                                ),
                                const SizedBox(width: 8),
                                Expanded(
                                  child: Text(
                                    progressWarning,
                                    style: const TextStyle(
                                      fontSize: 12,
                                      height: 1.5,
                                      color: Color(0xFF7F1D1D),
                                    ),
                                  ),
                                ),
                              ],
                            ),
                          ),
                        ],
                      ],
                    ),
                  ),
                ),
                actions: [
                  TextButton(
                    onPressed: () => Navigator.pop(dialogContext),
                    child: const Text('취소'),
                  ),
                  FilledButton(
                    onPressed: () {
                      final width = _parseMeters(widthController.text);
                      final radius = _parseMeters(radiusController.text);
                      final margin = _parseMeters(marginController.text);
                      final nextWidthError = width == null
                          ? '숫자로 입력하세요. 예: 0.20'
                          : width <= 0
                          ? '0보다 커야 합니다.'
                          : null;
                      final nextRadiusError = radius == null
                          ? '숫자로 입력하세요. 예: 0.15'
                          : radius < 0
                          ? '0 이상이어야 합니다.'
                          : null;
                      final nextMarginError = margin == null
                          ? '숫자로 입력하세요. 예: 0.05'
                          : margin < 0
                          ? '0 이상이어야 합니다.'
                          : null;
                      // 예전에는 여기서 그냥 return 했다. 버튼을 눌러도 아무 일이
                      // 일어나지 않아 값이 저장되지 않는 것처럼 보였다.
                      // 비우면 맵에서 계산한 값을 쓴다는 뜻이다.
                      final rawTolerance = toleranceController.text.trim();
                      final tolerance = rawTolerance.isEmpty
                          ? null
                          : _parseMeters(rawTolerance);
                      final nextToleranceError =
                          rawTolerance.isNotEmpty && tolerance == null
                          ? '숫자로 입력하세요. 예: ${recommended.toStringAsFixed(3)}'
                          : tolerance != null && tolerance <= 0
                          ? '0보다 커야 합니다.'
                          : null;
                      // 비우면 자동이라는 뜻이다. 적었으면 숫자여야 하고 0보다 커야
                      // 한다 — 0 인 충돌 반경은 로봇이 점이라는 말이 된다.
                      (double?, String?) optional(
                        TextEditingController controller, {
                        double? minimum,
                        String? belowMinimum,
                      }) {
                        final raw = controller.text.trim();
                        if (raw.isEmpty) return (null, null);
                        final value = _parseMeters(raw);
                        if (value == null) {
                          return (null, '숫자로 입력하세요. 비우면 자동입니다.');
                        }
                        if (value <= 0) return (null, '0보다 커야 합니다.');
                        if (minimum != null && value < minimum) {
                          return (null, belowMinimum);
                        }
                        return (value, null);
                      }

                      final footprint = optional(footprintController);
                      final vicinity = optional(vicinityController);
                      final laneWidth = optional(
                        laneWidthController,
                        minimum: minNavGraphLaneWidth,
                        belowMinimum:
                            '${minNavGraphLaneWidth.toStringAsFixed(2)}m 보다 가늘게는 '
                            '그리지 못합니다. 시각화 노드가 그 값으로 깎습니다.',
                      );
                      if (nextWidthError != null ||
                          nextRadiusError != null ||
                          nextMarginError != null ||
                          nextToleranceError != null ||
                          footprint.$2 != null ||
                          vicinity.$2 != null ||
                          laneWidth.$2 != null) {
                        setDialogState(() {
                          widthError = nextWidthError;
                          radiusError = nextRadiusError;
                          marginError = nextMarginError;
                          toleranceError = nextToleranceError;
                          footprintError = footprint.$2;
                          vicinityError = vicinity.$2;
                          laneWidthError = laneWidth.$2;
                        });
                        return;
                      }
                      // 접근 금지 반경은 충돌 반경보다 작을 수 없다. 작으면 다른
                      // 로봇이 몸 안까지 들어와도 된다는 말이 된다.
                      final effectiveFootprint = footprint.$1 ?? width! / 2;
                      if (vicinity.$1 != null &&
                          vicinity.$1! < effectiveFootprint) {
                        setDialogState(
                          () => vicinityError =
                              '충돌 반경(${effectiveFootprint.toStringAsFixed(3)}m)보다 '
                              '작을 수 없습니다.',
                        );
                        return;
                      }
                      // 최소보다 작으면 저장 전에 한 번 더 묻는다. 입력 중에만
                      // 알리면 그냥 지나치기 쉽다 — 실제로 0.080 이 저장돼 나갔고,
                      // Nav2 가 목표를 못 맞추고 맴돌다 포기했다.
                      if (tolerance != null && tolerance < floor) {
                        setDialogState(() {
                          widthError = null;
                          radiusError = null;
                          marginError = null;
                          toleranceError =
                              '최소 ${floor.toStringAsFixed(3)} 보다 작습니다. '
                              '그래도 쓰시려면 한 번 더 누르세요.';
                        });
                        // 같은 값으로 다시 누르면 그때는 넣는다.
                        if (toleranceForced != tolerance) {
                          toleranceForced = tolerance;
                          return;
                        }
                      }
                      // 주행 한계는 빈 칸이나 못 읽는 값이면 지금 값을 그대로
                      // 둔다. 0 으로 떨어지면 RMF 가 로봇을 멈춰 있는 것으로 보고
                      // 배차를 안 한다.
                      double? limit(TextEditingController controller) {
                        final value = double.tryParse(controller.text.trim());
                        return value != null && value > 0 ? value : null;
                      }

                      Navigator.pop(dialogContext, (
                        width: width!,
                        radius: radius!,
                        margin: margin!,
                        tolerance: tolerance,
                        footprint: footprint.$1,
                        vicinity: vicinity.$1,
                        laneWidth: laneWidth.$1,
                        linearVelocity: limit(linearVelocityController),
                        linearAcceleration: limit(linearAccelerationController),
                        angularVelocity: limit(angularVelocityController),
                        angularAcceleration: limit(
                          angularAccelerationController,
                        ),
                      ));
                    },
                    child: const Text('기준 저장'),
                  ),
                ],
              );
            },
          ),
        );
    // 창이 닫히는 애니메이션이 끝나기 전에 컨트롤러를 버리면, 사라지는 중인
    // TextField 가 이미 버려진 컨트롤러를 다시 읽어 예외가 난다. 애니메이션이
    // 끝난 뒤에 버리되, 그동안 사용자를 기다리게 하지는 않는다.
    unawaited(
      Future<void>.delayed(const Duration(milliseconds: 350)).then((_) {
        widthController.dispose();
        radiusController.dispose();
        marginController.dispose();
        toleranceController.dispose();
        footprintController.dispose();
        vicinityController.dispose();
        laneWidthController.dispose();
        linearVelocityController.dispose();
        linearAccelerationController.dispose();
        angularVelocityController.dispose();
        angularAccelerationController.dispose();
      }),
    );
    if (values == null || !mounted) return;
    _recordUndo();
    setState(() {
      _robotWidthMeters = values.width;
      _turningRadiusMeters = values.radius;
      _localizationMarginMeters = values.margin;
      _manualLaneDisplayWidth = values.laneWidth;
      _fleetSettings = _fleetSettings.copyWith(
        goalToleranceMeters: values.tolerance,
        clearGoalTolerance: values.tolerance == null,
        manualFootprintRadius: values.footprint,
        manualVicinityRadius: values.vicinity,
        // 이 넷이 RMF 의 배차 계산과 로봇별 Nav2 파라미터를 함께 쓴다.
        linearVelocity: values.linearVelocity,
        linearAcceleration: values.linearAcceleration,
        angularVelocity: values.angularVelocity,
        angularAcceleration: values.angularAcceleration,
        // 둘 다 비웠으면 직접 지정을 그만두겠다는 뜻이다. copyWith 의 null 은
        // "안 바꿈" 이라 이 깃발이 없으면 지운 값이 되살아난다.
        clearManualProfile: values.footprint == null && values.vicinity == null,
      );
      _isDeployed = false;
    });
    // 프로필 반경은 폭에서 다시 계산된다. 직접 넣은 값이 있으면 그것이 이긴다.
    _syncFleetProfileToSafety();
    await _saveSettingToOpenProject(
      label: '로봇 안전 기준',
      detail:
          '폭 ${values.width.toStringAsFixed(2)}m · '
          '회전 반경 ${values.radius.toStringAsFixed(2)}m · '
          '여유 ${values.margin.toStringAsFixed(2)}m · '
          '도착 반경 '
          '${values.tolerance == null ? '자동 ${_recommendedGoalTolerance.toStringAsFixed(3)}' : values.tolerance!.toStringAsFixed(3)}m · '
          '충돌 ${_fleetSettings.footprintRadius.toStringAsFixed(3)}m'
          '${values.footprint == null ? ' (자동)' : ''} · '
          '접근 금지 ${_fleetSettings.vicinityRadius.toStringAsFixed(3)}m'
          '${values.vicinity == null ? ' (자동)' : ''} · '
          'Lane 표시 ${_laneDisplayWidth.toStringAsFixed(2)}m'
          '${values.laneWidth == null ? ' (자동)' : ''}',
    );
    if (!mounted) return;
    await _showValidationDialog();
  }

  /// Gazebo 월드에서 벽을 얼마나 높게 세울지 받는다.
  ///
  /// 도면에는 높이가 없다. 길이는 Measurement 로 재지만 높이는 잴 데가 없어서
  /// 여기서 받는다. 안 받으면 traffic_editor 기본값 2.5m 로 서는데, 실험실
  /// 세트는 0.3m 라 시뮬레이터가 실제와 딴판이 된다.
  Future<void> _showWallHeightSettings() async {
    final controller = TextEditingController(
      text: _wallHeightMeters.toStringAsFixed(2),
    );
    String? error;
    String? warning = wallHeightWarning(_wallHeightMeters);
    final height = await showMovableDialog<double>(
      context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (context, setDialogState) => AlertDialog(
          icon: const Icon(Icons.height, size: 34),
          title: const Text('벽 높이'),
          content: SizedBox(
            width: 400,
            child: SingleChildScrollView(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    '도면은 위에서 내려다본 그림이라 높이가 없습니다. 길이는 '
                    'Measurement 로 재지만 높이는 잴 데가 없어 여기서 받습니다.',
                    style: TextStyle(color: Color(0xFF475569), fontSize: 12.5),
                  ),
                  const SizedBox(height: 14),
                  TextField(
                    controller: controller,
                    autofocus: true,
                    keyboardType: const TextInputType.numberWithOptions(
                      decimal: true,
                    ),
                    decoration: InputDecoration(
                      labelText: '벽 높이 (m)',
                      helperText:
                          '실험실 책상 세트는 0.3m 안팎, 건물 벽은 2.5m 쯤입니다. '
                          '기본값은 ${defaultWallHeight.toStringAsFixed(1)}m 입니다.',
                      helperMaxLines: 2,
                      errorText: error,
                      border: const OutlineInputBorder(),
                    ),
                    onChanged: (_) => setDialogState(() {
                      error = null;
                      final value = _parseMeters(controller.text);
                      warning = value == null || wallHeightError(value) != null
                          ? null
                          : wallHeightWarning(value);
                    }),
                  ),
                  if (warning != null) ...[
                    const SizedBox(height: 12),
                    Container(
                      padding: const EdgeInsets.all(11),
                      decoration: BoxDecoration(
                        color: const Color(0xFFFEF3C7),
                        borderRadius: BorderRadius.circular(9),
                        border: Border.all(color: const Color(0xFFFCD34D)),
                      ),
                      child: Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const Icon(
                            Icons.warning_amber_rounded,
                            size: 18,
                            color: Color(0xFFB45309),
                          ),
                          const SizedBox(width: 7),
                          Expanded(
                            child: SelectableText(
                              warning!,
                              style: const TextStyle(
                                fontSize: 12,
                                color: Color(0xFF92400E),
                              ),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ],
                  const SizedBox(height: 12),
                  const Text(
                    '$wallHeightGridNote\n'
                    '바꾼 뒤에는 배포해야 Gazebo 월드에 들어갑니다.',
                    style: TextStyle(color: Color(0xFF64748B), fontSize: 12),
                  ),
                ],
              ),
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext),
              child: const Text('취소'),
            ),
            FilledButton(
              onPressed: () {
                final value = _parseMeters(controller.text);
                final nextError = wallHeightError(value);
                if (nextError != null) {
                  setDialogState(() => error = nextError);
                  return;
                }
                Navigator.pop(dialogContext, value);
              },
              child: const Text('높이 저장'),
            ),
          ],
        ),
      ),
    );
    // 창이 닫히는 애니메이션이 끝나기 전에 버리면, 사라지는 중인 TextField 가
    // 이미 버려진 컨트롤러를 다시 읽어 예외가 난다.
    unawaited(
      Future<void>.delayed(
        const Duration(milliseconds: 350),
      ).then((_) => controller.dispose()),
    );
    if (height == null || !mounted) return;
    _recordUndo();
    setState(() {
      _wallHeightMeters = height;
      // 벽 높이는 월드 파일에 들어간다. 다시 배포하기 전에는 떠 있는 Gazebo 가
      // 아직 옛 높이의 벽을 들고 있다.
      _isDeployed = false;
    });
    await _saveSettingToOpenProject(
      label: '벽 높이',
      detail: '${height.toStringAsFixed(2)}m · 배포해야 Gazebo 에 반영됩니다',
    );
  }

  /// 이 프로젝트가 쓸 ROS 도메인을 받는다.
  ///
  /// 로봇을 등록할 때 이 값을 기본으로 가져간다. 대마다 고칠 수 있다.
  Future<void> _showRosDomainSettings() async {
    final controller = TextEditingController(text: '$_rosDomainId');
    String? error;
    String? warning = rosDomainIdWarning(_rosDomainId);
    final domain = await showMovableDialog<int>(
      context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (context, setDialogState) => AlertDialog(
          icon: const Icon(Icons.lan_outlined, size: 34),
          title: const Text('ROS 도메인'),
          content: SizedBox(
            width: 430,
            child: SingleChildScrollView(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    '같은 도메인에 있는 노드끼리만 서로를 봅니다. 이 값이 어긋나면 '
                    '오류는 하나도 안 나면서 아무것도 안 통합니다 — 지도를 배포해도 '
                    '시뮬레이터가 못 받고, 로봇을 띄워도 관제가 못 봅니다.',
                    style: TextStyle(color: Color(0xFF475569), fontSize: 12.5),
                  ),
                  const SizedBox(height: 14),
                  TextField(
                    controller: controller,
                    autofocus: true,
                    keyboardType: TextInputType.number,
                    decoration: InputDecoration(
                      labelText: 'ROS_DOMAIN_ID',
                      helperText:
                          '0 ~ $maxRosDomainId. 터미널에서 `echo \$ROS_DOMAIN_ID` 로 '
                          '지금 쓰는 값을 볼 수 있습니다.',
                      helperMaxLines: 2,
                      errorText: error,
                      border: const OutlineInputBorder(),
                    ),
                    onChanged: (_) => setDialogState(() {
                      error = null;
                      final value = int.tryParse(controller.text.trim());
                      warning = value == null || rosDomainIdError(value) != null
                          ? null
                          : rosDomainIdWarning(value);
                    }),
                  ),
                  if (warning != null) ...[
                    const SizedBox(height: 12),
                    Container(
                      padding: const EdgeInsets.all(11),
                      decoration: BoxDecoration(
                        color: const Color(0xFFFEF3C7),
                        borderRadius: BorderRadius.circular(9),
                        border: Border.all(color: const Color(0xFFFCD34D)),
                      ),
                      child: SelectableText(
                        warning!,
                        style: const TextStyle(
                          fontSize: 12,
                          color: Color(0xFF92400E),
                        ),
                      ),
                    ),
                  ],
                  const SizedBox(height: 12),
                  const Text(
                    '로봇을 등록할 때 이 값을 기본으로 가져갑니다. 실물 로봇처럼 제 '
                    '도메인을 갖고 오는 대는 등록 창에서 따로 고칠 수 있습니다.\n'
                    '바꾼 뒤에는 RMF 설정 내보내기와 배포를 다시 하세요 — 실행 '
                    '스크립트에 이 값이 박혀 나갑니다.',
                    style: TextStyle(color: Color(0xFF64748B), fontSize: 12),
                  ),
                ],
              ),
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext),
              child: const Text('취소'),
            ),
            FilledButton(
              onPressed: () {
                final value = int.tryParse(controller.text.trim());
                final nextError = rosDomainIdError(value);
                if (nextError != null) {
                  setDialogState(() => error = nextError);
                  return;
                }
                Navigator.pop(dialogContext, value);
              },
              child: const Text('도메인 저장'),
            ),
          ],
        ),
      ),
    );
    unawaited(
      Future<void>.delayed(
        const Duration(milliseconds: 350),
      ).then((_) => controller.dispose()),
    );
    if (domain == null || !mounted) return;
    _recordUndo();
    setState(() {
      _rosDomainId = domain;
      // 실행 스크립트에 박혀 나가는 값이다. 다시 내보내기 전에는 떠 있는 것도
      // 디스크의 스크립트도 예전 도메인을 쓴다.
      _isDeployed = false;
    });
    await _saveSettingToOpenProject(
      label: 'ROS 도메인',
      detail: '$domain · 내보내기와 배포를 다시 해야 반영됩니다',
    );
  }

  /// 미터 값을 읽는다. `0,2` 처럼 쉼표를 소수점으로 쓴 입력도 받는다 —
  /// 숫자 자판과 붙여넣기에서 흔하고, 거절해 봐야 사용자가 알 방법이 없다.
  static double? _parseMeters(String raw) =>
      double.tryParse(raw.trim().replaceAll(',', '.'));

  List<_ScenarioWaypointAssignment>? _buildScenarioAssignments(
    _MapScenarioConfig config,
  ) {
    final connected = <Offset>{
      for (final lane in _recommendedLanes) ...[lane.$1, lane.$2],
    };
    final candidates = _laneWaypoints
        .where(
          (point) =>
              connected.contains(point) &&
              _isInsideFloor(point) &&
              (_waypointTypes[point] ?? '대기') == '대기' &&
              (_waypointNames[point] ?? '').trim().isEmpty,
        )
        .toList();
    int existingCount(String category, {String? namePrefix}) =>
        _laneWaypoints.where((point) {
          if (_waypointTypes[point] != category) return false;
          if (namePrefix == null) return true;
          return (_waypointNames[point] ?? '').trim().startsWith(namePrefix);
        }).length;
    final homeNeeded = math.max(0, config.homeCount - existingCount('홈'));
    final chargerNeeded = math.max(
      0,
      config.chargerCount - existingCount('충전'),
    );
    final holdingNeeded = math.max(0, config.homeCount - existingCount('주차'));
    final ambientNeeded = math.max(
      0,
      config.ambientPickupCount - existingCount('픽업', namePrefix: '상온'),
    );
    final chilledNeeded = math.max(
      0,
      config.chilledPickupCount - existingCount('픽업', namePrefix: '냉장'),
    );
    final frozenNeeded = math.max(
      0,
      config.frozenPickupCount - existingCount('픽업', namePrefix: '냉동'),
    );
    final dropoffNeeded = math.max(
      0,
      config.dropoffCount - existingCount('드랍오프'),
    );
    final neededCount =
        homeNeeded +
        holdingNeeded +
        chargerNeeded +
        ambientNeeded +
        chilledNeeded +
        frozenNeeded +
        dropoffNeeded;
    if (candidates.length < neededCount) return null;

    final occupied = _laneWaypoints
        .where((point) => (_waypointTypes[point] ?? '대기') != '대기')
        .toList();
    final selected = <Offset>[];
    Offset takeSpreadPoint() {
      if (selected.isEmpty && occupied.isEmpty) {
        candidates.sort((a, b) {
          final horizontal = a.dx.compareTo(b.dx);
          return horizontal != 0 ? horizontal : a.dy.compareTo(b.dy);
        });
        return candidates.removeAt(0);
      }
      final anchors = [...occupied, ...selected];
      var best = candidates.first;
      var bestDistance = -1.0;
      for (final candidate in candidates) {
        final nearest = anchors
            .map((anchor) => (candidate - anchor).distance)
            .reduce(math.min);
        if (nearest > bestDistance) {
          best = candidate;
          bestDistance = nearest;
        }
      }
      candidates.remove(best);
      return best;
    }

    Offset takeNearestPoint(List<Offset> anchors) {
      if (anchors.isEmpty) return takeSpreadPoint();
      var best = candidates.first;
      var bestDistance = double.infinity;
      for (final candidate in candidates) {
        final distance = anchors
            .map((anchor) => (candidate - anchor).distance)
            .reduce(math.min);
        if (distance < bestDistance) {
          best = candidate;
          bestDistance = distance;
        }
      }
      candidates.remove(best);
      return best;
    }

    final usedNames = _waypointNames.values
        .map((name) => name.trim())
        .where((name) => name.isNotEmpty)
        .toSet();
    String nextName(String prefix) {
      var number = 1;
      while (usedNames.contains('$prefix$number')) {
        number++;
      }
      final name = '$prefix$number';
      usedNames.add(name);
      return name;
    }

    final assignments = <_ScenarioWaypointAssignment>[];
    void assign(
      int count,
      String category,
      String prefix, {
      List<Offset> near = const [],
    }) {
      for (var index = 0; index < count; index++) {
        final point = near.isEmpty
            ? takeSpreadPoint()
            : takeNearestPoint([near[index % near.length]]);
        selected.add(point);
        assignments.add(
          _ScenarioWaypointAssignment(
            point: point,
            category: category,
            name: nextName(prefix),
          ),
        );
      }
    }

    assign(dropoffNeeded, '드랍오프', '드랍오프');
    final dropoffAnchors = <Offset>[
      ..._laneWaypoints.where((point) => _waypointTypes[point] == '드랍오프'),
      ...assignments
          .where((assignment) => assignment.category == '드랍오프')
          .map((assignment) => assignment.point),
    ];
    assign(homeNeeded, '홈', '홈', near: dropoffAnchors);
    // 이름 붙이기 규칙이 Waypoint 추가 창(주차 → 홈N)과 다르다. 여기서는 이
    // 자동 배치가 예전부터 내보내던 이름(주차N)을 그대로 둔다. 변수명이
    // holdingNeeded 인데 카테고리가 '주차'인 것도 이름 정리 이전부터의 상태다
    // — 실제로 내보내는 속성(is_parking_spot)은 예전과 같다.
    assign(
      holdingNeeded,
      '주차',
      '주차',
      near: _scenarioUsesSeparateRoutes ? const [] : _scenarioHoldingAnchors,
    );
    assign(chargerNeeded, '충전', '충전');
    assign(ambientNeeded, '픽업', '상온픽업');
    assign(chilledNeeded, '픽업', '냉장픽업');
    assign(frozenNeeded, '픽업', '냉동픽업');
    return assignments;
  }

  String? _categoryInferredFromName(String name) {
    final normalized = name.trim().toLowerCase().replaceAll(
      RegExp(r'[ _-]'),
      '',
    );
    if (normalized.isEmpty) return null;
    if (RegExp(r'(충전|charger|charging|charge|dock)').hasMatch(normalized)) {
      return '충전';
    }
    if (RegExp(r'(홈|home)').hasMatch(normalized)) return '홈';
    if (RegExp(r'(드랍|하차|dropoff|drop)').hasMatch(normalized)) {
      return '드랍오프';
    }
    if (RegExp(r'(픽업|상차|pickup|pick)').hasMatch(normalized)) return '픽업';
    if (RegExp(r'(주차|parking|park)').hasMatch(normalized)) return '주차';
    if (RegExp(r'(대기|holding|hold|wait)').hasMatch(normalized)) return '대기';
    return null;
  }

  int _inferWaypointTypesFromNames() {
    final updates = <Offset, String>{};
    for (final point in _laneWaypoints) {
      // 설비는 Lane에 연결하지 않으므로 제외한다. 주차는 이름이 홈N이라
      // 이름만 보면 '홈'으로 추론돼 is_parking_spot 이 조용히 떨어져 나간다.
      if (_waypointTypes[point] == '설비' || _waypointTypes[point] == '주차') {
        continue;
      }
      final inferred = _categoryInferredFromName(_waypointNames[point] ?? '');
      if (inferred != null && inferred != _waypointTypes[point]) {
        updates[point] = inferred;
      }
    }
    if (updates.isEmpty) return 0;
    _recordUndo();
    setState(() {
      _waypointTypes.addAll(updates);
      _isDeployed = false;
      _vertexLabelRevision++;
    });
    return updates.length;
  }

  bool _isInsideFloor(Offset point) => insidePolygon(point, _floorOutline());

  bool _floorSupportsTwoRobotRoutes() {
    final outline = _floorOutline();
    if (outline.length < 3) return false;
    final bounds = _pointsBounds(outline);
    final metersPerPixel = _metersPerPixel;
    final clearancePixels = metersPerPixel == null || metersPerPixel <= 0
        ? math.min(bounds.width, bounds.height) * .08
        : (_robotWidthMeters / 2 + _localizationMarginMeters) / metersPerPixel;
    return bounds.height >= math.max(clearancePixels * 4, 48);
  }

  ({
    int waypointCount,
    int laneCount,
    int doubledCorridors,
    List<String> unlinked,
  })
  _ensureScenarioDraftNetwork(_MapScenarioConfig config) {
    const empty = (
      waypointCount: 0,
      laneCount: 0,
      doubledCorridors: 0,
      unlinked: <String>[],
    );
    final connected = <Offset>{
      for (final lane in _recommendedLanes) ...[lane.$1, lane.$2],
    };
    final availableCount = _laneWaypoints.where((point) {
      return connected.contains(point) &&
          (_waypointTypes[point] ?? '대기') == '대기' &&
          (_waypointNames[point] ?? '').trim().isEmpty;
    }).length;
    final deficit = math.max(0, config.requiredWaypointCount - availableCount);

    final floorOutline = _floorOutline();
    if (floorOutline.length < 3) return empty;
    final bounds = _pointsBounds(floorOutline);
    final metersPerPixel = _metersPerPixel;
    final requiredClearanceMeters =
        _robotWidthMeters / 2 + _localizationMarginMeters;
    final clearancePixels = metersPerPixel == null || metersPerPixel <= 0
        ? math.min(bounds.width, bounds.height) * .08
        : requiredClearanceMeters / metersPerPixel;
    final draftClearancePixels = math.max(
      math.max(clearancePixels, _laneWallClearancePixels),
      12.0,
    );
    final pointCount = math.max(
      math.max(deficit, config.requiredWaypointCount),
      8,
    );

    // Routes are planned on a clearance-aware raster of the floor rather than
    // inset from the Floor outline. The outline is the convex hull of the Wall
    // vertices, so a row inset from it can still end up closer to a wall than
    // the robot may pass, which used to abort the whole draft.
    final planner = ScenarioRoutePlanner(
      walls: _visibleWallSegments(),
      floorOutline: floorOutline,
      floorMaskPoints: _floorMask?.points ?? const [],
      clearancePixels: draftClearancePixels,
    );
    final plan = planner.planRoutes(waypointTarget: pointCount);
    if (plan == null || plan.outbound.length < 2) {
      _showProcessingWarning(
        '시나리오 맵 자동 완성',
        '벽에서 ${draftClearancePixels.toStringAsFixed(1)}px'
            '${metersPerPixel == null || metersPerPixel <= 0 ? '' : '(로봇 폭 절반 + 안전 여유 ${requiredClearanceMeters.toStringAsFixed(2)}m)'}'
            ' 이상 떨어져 지나갈 수 있는 통로를 도면에서 찾지 못했습니다.\n'
            '도면에서 가장 여유가 큰 지점도 벽까지 '
            '${planner.bestClearancePixels.toStringAsFixed(1)}px 입니다.\n'
            '${metersPerPixel == null || metersPerPixel <= 0 ? '길이 기준(축척)을 먼저 측정하면 실제 로봇 크기로 통로를 판단합니다.' : '로봇 폭과 안전 여유를 줄이거나 길이 기준(축척) 측정을 다시 확인해 주세요.'}',
      );
      return empty;
    }

    final generated = <Offset>[];
    final generatedLanes = <(Offset, Offset)>[];
    final draftDirections = <(Offset, Offset), String>{};

    Offset canonical(Offset point) {
      for (final existing in generated) {
        if ((existing - point).distance <= .01) return existing;
      }
      return point;
    }

    void addLaneChain(
      List<Offset> chain,
      String direction,
      List<Offset> anchors,
    ) {
      final resolved = <Offset>[];
      for (final raw in chain) {
        Offset? anchor;
        for (final candidate in anchors) {
          if ((candidate - raw).distance <= .01) anchor = candidate;
        }
        final point = anchor ?? canonical(raw);
        if (resolved.isNotEmpty && (resolved.last - point).distance <= .01) {
          continue;
        }
        resolved.add(point);
        if (anchor == null &&
            !generated.any((existing) => (existing - point).distance <= .01)) {
          generated.add(point);
        }
      }
      for (var index = 0; index < resolved.length - 1; index++) {
        final lane = (resolved[index], resolved[index + 1]);
        if (generatedLanes.any(
          (existing) =>
              ((existing.$1 - lane.$1).distance <= .01 &&
                  (existing.$2 - lane.$2).distance <= .01) ||
              ((existing.$1 - lane.$2).distance <= .01 &&
                  (existing.$2 - lane.$1).distance <= .01),
        )) {
          continue;
        }
        generatedLanes.add(lane);
        draftDirections[lane] = direction;
      }
    }

    // Wherever a corridor is wide enough for two robots to keep their safety
    // distance side by side, it is drawn as a separate outbound and return
    // one-way lane so robots never meet head-on. Narrow stretches stay a
    // single shared lane.
    var doubledCorridors = 0;
    bool addDraftPath(
      Offset start,
      Offset end,
      String direction, {
      List<Offset> existingAnchors = const [],
      double? waypointSpacing,
    }) {
      final path = planner.planPath(start, end);
      if (path == null) return false;
      final route = [start, ...path.sublist(1, path.length - 1), end];
      for (final section in planner.splitCorridor(route)) {
        if (section.isDoubled) doubledCorridors++;
        for (final chain in section.chains) {
          addLaneChain(
            waypointSpacing == null
                ? chain
                : planner.densify(chain, waypointSpacing),
            section.isDoubled ? '정방향' : direction,
            existingAnchors,
          );
        }
      }
      return true;
    }

    // Each row is drafted as one corridor so a wide row can be split over its
    // whole length instead of merging in and out at every waypoint.
    double rowSpacing(List<Offset> row) =>
        (row.last - row.first).distance / math.max(1, row.length - 1);
    final routeDirection = plan.separateRoutes ? '정방향' : '양방향';
    final corridors = <(Offset, Offset, double?)>[
      (plan.outbound.first, plan.outbound.last, rowSpacing(plan.outbound)),
      if (plan.separateRoutes) ...[
        (plan.outbound.last, plan.returnRoute.first, null),
        (
          plan.returnRoute.first,
          plan.returnRoute.last,
          rowSpacing(plan.returnRoute),
        ),
        (plan.returnRoute.last, plan.outbound.first, null),
      ],
    ];
    for (final (start, end, spacing) in corridors) {
      if (addDraftPath(start, end, routeDirection, waypointSpacing: spacing)) {
        continue;
      }
      _showProcessingWarning(
        '시나리오 맵 자동 완성',
        '벽과 로봇 안전거리를 지키는 연속 경로를 만들 수 없어 초안을 적용하지 않았습니다.\n'
            '실패 지점: '
            '(${start.dx.toStringAsFixed(1)}, ${start.dy.toStringAsFixed(1)}) → '
            '(${end.dx.toStringAsFixed(1)}, ${end.dy.toStringAsFixed(1)}) · '
            '필요 ${draftClearancePixels.toStringAsFixed(1)}px',
      );
      return empty;
    }

    // A doubled corridor already carries traffic both ways, so the entrance
    // holding points a shared corridor needs are only placed without one.
    _scenarioUsesSeparateRoutes = plan.separateRoutes || doubledCorridors > 0;
    _scenarioHoldingAnchors = _scenarioUsesSeparateRoutes
        ? const []
        : [plan.outbound.first, plan.outbound.last];

    // Existing waypoints join the draft only when they can be reached without
    // giving up the clearance; the ones that cannot are reported instead of
    // failing the whole draft.
    final baseRoutePoints = [...generated];
    final unlinked = <String>[];
    String label(Offset point) {
      final name = (_waypointNames[point] ?? '').trim();
      return name.isEmpty
          ? '(${point.dx.toStringAsFixed(0)}, ${point.dy.toStringAsFixed(0)})'
          : name;
    }

    Offset nearestRoutePoint(Offset point) => baseRoutePoints.reduce(
      (a, b) => (a - point).distance <= (b - point).distance ? a : b,
    );
    double routeDistance(Offset point) =>
        (nearestRoutePoint(point) - point).distance;

    final existingNetworkPoints = connected.where(_isInsideFloor).toList()
      ..sort((a, b) => routeDistance(a).compareTo(routeDistance(b)));
    if (existingNetworkPoints.isNotEmpty &&
        !existingNetworkPoints.any(
          (point) => addDraftPath(
            point,
            nearestRoutePoint(point),
            '양방향',
            existingAnchors: [point],
          ),
        )) {
      unlinked.add('기존 Lane 네트워크');
    }
    final operationalAnchors = _laneWaypoints.where((point) {
      final type = _waypointTypes[point] ?? '대기';
      return _isInsideFloor(point) &&
          (type == '홈' ||
              type == '주차' ||
              type == '충전' ||
              type == '픽업' ||
              type == '드랍오프');
    });
    for (final anchor in operationalAnchors) {
      if (connected.contains(anchor)) continue;
      if (addDraftPath(
        anchor,
        nearestRoutePoint(anchor),
        '양방향',
        existingAnchors: [anchor],
      )) {
        continue;
      }
      unlinked.add(label(anchor));
    }

    if (generatedLanes.isEmpty ||
        generatedLanes.any(
          (lane) => _touchesWall(
            lane.$1,
            lane.$2,
            clearancePixels: draftClearancePixels,
          ),
        )) {
      _showProcessingWarning(
        '시나리오 맵 자동 완성',
        '벽과 로봇 안전거리를 지키는 연속 경로를 만들 수 없어 초안을 적용하지 않았습니다.\n'
            '필요 안전거리: ${draftClearancePixels.toStringAsFixed(1)}px',
      );
      return empty;
    }

    _recordUndo();
    setState(() {
      for (final point in generated) {
        if (!_laneWaypoints.any(
          (existing) => (existing - point).distance <= .01,
        )) {
          _laneWaypoints.add(point);
          _waypointTypes[point] = '대기';
          _waypointNames[point] = ' ';
        }
      }
      for (final lane in generatedLanes) {
        if (_hasLane(lane.$1, lane.$2)) continue;
        _recommendedLanes.add(lane);
        _laneDirections[lane] = draftDirections[lane] ?? '정방향';
      }
      _stage = MapStage.lanes;
      _mapScenarioSummary =
          '자동 경로 초안 · Waypoint ${generated.length} · '
          'Lane ${generatedLanes.length} · Floor 내부 · '
          '${_scenarioUsesSeparateRoutes ? '왕복 2경로' : '협로 1경로+입구 대기'}'
          '${doubledCorridors == 0 ? '' : ' · 넓은 통로 왕복 분리 $doubledCorridors곳'} · 역할 적용 전'
          '${unlinked.isEmpty ? '' : ' · 미연결 ${unlinked.length}곳'}';
      _isDeployed = false;
      _vertexLabelRevision++;
    });
    return (
      waypointCount: generated.length,
      laneCount: generatedLanes.length,
      doubledCorridors: doubledCorridors,
      unlinked: unlinked,
    );
  }

  Future<bool> _tryCodexScenarioMap(_MapScenarioConfig config) async {
    if (!isMapAiConfigured) return false;
    final drawing = _drawing;
    if (drawing == null) return false;
    final existingIds = <Offset, String>{
      for (var i = 0; i < _laneWaypoints.length; i++)
        _laneWaypoints[i]: 'existing_$i',
    };
    final request = <String, dynamic>{
      'schemaVersion': 1,
      'task': 'open_rmf_waypoint_lane_design',
      'coordinateSystem': 'drawing_pixels_top_left_origin',
      'drawing': {
        'width': drawing.pixelWidth,
        'height': drawing.pixelHeight,
        'name': drawing.name,
      },
      'robotSafety': {
        'widthMeters': _robotWidthMeters,
        'turningRadiusMeters': _turningRadiusMeters,
        'localizationMarginMeters': _localizationMarginMeters,
        'pixelsPerMeter': _metersPerPixel == null ? null : 1 / _metersPerPixel!,
      },
      'scenario': {
        'robotCount': config.robotCount,
        'homeCount': config.homeCount,
        'holdingCount': config.homeCount,
        'chargerCount': config.chargerCount,
        'ambientPickupCount': config.ambientPickupCount,
        'chilledPickupCount': config.chilledPickupCount,
        'frozenPickupCount': config.frozenPickupCount,
        'dropoffCount': config.dropoffCount,
        'returnHome': config.returnHome,
        'singleLoadPerTrip': config.singleLoadPerTrip,
        'routeMode': _floorSupportsTwoRobotRoutes()
            ? 'separate_outbound_return'
            : 'shared_narrow_lane_with_holding',
      },
      'walls': [
        for (final wall in _visibleWallSegments())
          {
            'start': {'x': wall.$1.dx, 'y': wall.$1.dy},
            'end': {'x': wall.$2.dx, 'y': wall.$2.dy},
          },
      ],
      'floorPolygon': [
        for (final point in _floorOutline()) {'x': point.dx, 'y': point.dy},
      ],
      'waypoints': [
        for (final entry in existingIds.entries)
          {
            'id': entry.value,
            'x': entry.key.dx,
            'y': entry.key.dy,
            'name': (_waypointNames[entry.key] ?? '').trim(),
            'category': _waypointTypes[entry.key] ?? '대기',
          },
      ],
      'lanes': [
        for (final lane in _recommendedLanes)
          {
            'startId': existingIds[lane.$1],
            'endId': existingIds[lane.$2],
            'direction': _laneDirections[lane] ?? '양방향',
          },
      ],
      'requirements': {
        'preserveExistingOperationalWaypoints': true,
        'placeEveryNewWaypointInsideFloorPolygon': true,
        'avoidWallCrossings': true,
        'produceSeparateOutboundAndReturnRoutes':
            _floorSupportsTwoRobotRoutes(),
        'placeHomesNearDropoffWaypoints': true,
        'useSeparateRoutesOnlyWhenTwoRobotsFitSafely': true,
        'createHoldingAtNarrowPassageEntrances': true,
        'chargerWaypointsMustUseChargerCategory': true,
        'minimumHoldingWaypointCount': config.homeCount,
        'connectEveryMobileWaypoint': true,
        'allowedCategories': ['대기', '주차', '홈', '충전', '픽업', '드랍오프'],
        'allowedDirections': ['양방향', '정방향', '역방향'],
      },
    };
    MapAiProposal? proposal;
    try {
      proposal = await requestMapAiProposal(request);
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Codex 연결에 실패해 로컬 맵 분석으로 전환합니다.')),
        );
      }
      return false;
    }
    if (proposal == null || !mounted) return false;

    final pointsById = <String, Offset>{
      ...{for (final entry in existingIds.entries) entry.value: entry.key},
    };
    final newPoints = <Offset>[];
    final names = <Offset, String>{};
    final categories = <Offset, String>{};
    final allowedCategories = {'대기', '주차', '홈', '충전', '픽업', '드랍오프'};
    final width = (drawing.pixelWidth ?? 0).toDouble();
    final height = (drawing.pixelHeight ?? 0).toDouble();
    try {
      for (final item in proposal.waypoints) {
        final id = item['id'] as String;
        final existingPoint = existingIds.entries
            .where((entry) => entry.value == id)
            .firstOrNull
            ?.key;
        final point =
            existingPoint ??
            Offset(
              (item['x'] as num).toDouble(),
              (item['y'] as num).toDouble(),
            );
        if (!point.dx.isFinite ||
            !point.dy.isFinite ||
            point.dx < 0 ||
            point.dy < 0 ||
            (width > 0 && point.dx > width) ||
            (height > 0 && point.dy > height)) {
          throw const FormatException('Waypoint가 도면 범위를 벗어났습니다.');
        }
        if (existingPoint == null && !_isInsideFloor(point)) {
          throw const FormatException('Codex Waypoint가 Floor 영역 밖에 있습니다.');
        }
        final category = item['category'] as String? ?? '대기';
        if (!allowedCategories.contains(category)) {
          throw FormatException('지원하지 않는 Waypoint 종류: $category');
        }
        if (!id.startsWith('existing_')) newPoints.add(point);
        pointsById[id] = point;
        names[point] = (item['name'] as String? ?? '').trim();
        categories[point] = category;
      }
      final lanes = <(Offset, Offset)>[];
      final directions = <(Offset, Offset), String>{};
      for (final item in proposal.lanes) {
        final start = pointsById[item['startId'] as String];
        final end = pointsById[item['endId'] as String];
        if (start == null || end == null || (start - end).distance <= .01) {
          throw const FormatException('Lane 연결 ID가 잘못되었습니다.');
        }
        if (_crossesWall(start, end)) {
          throw const FormatException('Codex Lane이 벽 또는 로봇 안전거리를 침범합니다.');
        }
        final lane = (start, end);
        lanes.add(lane);
        final direction = item['direction'] as String? ?? '양방향';
        directions[lane] = {'양방향', '정방향', '역방향'}.contains(direction)
            ? direction
            : '양방향';
      }
      if (newPoints.isEmpty || lanes.isEmpty) {
        throw const FormatException('Codex 제안이 비어 있습니다.');
      }
      int finalCategoryCount(String category) {
        final existing = _laneWaypoints.where((point) {
          final proposed = categories[point];
          return (proposed ?? _waypointTypes[point] ?? '대기') == category;
        }).length;
        final added = newPoints
            .where((point) => categories[point] == category)
            .length;
        return existing + added;
      }

      if (finalCategoryCount('홈') < config.homeCount ||
          finalCategoryCount('주차') < config.homeCount ||
          finalCategoryCount('충전') < config.chargerCount) {
        throw const FormatException('Codex 제안에 Home·대기·충전 Waypoint가 부족합니다.');
      }
      final apply = await showMovableDialog<bool>(
        context: context,
        builder: (dialogContext) => AlertDialog(
          icon: const Icon(Icons.psychology_alt_outlined, size: 36),
          title: Text('${proposal!.provider} 맵 분석 결과'),
          content: SizedBox(
            width: 520,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  proposal.summary.isEmpty ? '맵 구조를 분석했습니다.' : proposal.summary,
                ),
                const SizedBox(height: 10),
                Text(
                  '신규 Waypoint ${newPoints.length}개 · Lane ${lanes.length}개',
                ),
                if (proposal.warnings.isNotEmpty) ...[
                  const SizedBox(height: 10),
                  for (final warning in proposal.warnings.take(4))
                    Text('• $warning', style: const TextStyle(fontSize: 12)),
                ],
                const SizedBox(height: 10),
                const Text(
                  '응답은 좌표 범위와 벽 교차를 로컬에서 재검증했습니다.',
                  style: TextStyle(color: Color(0xFF64748B), fontSize: 12),
                ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext, false),
              child: const Text('취소'),
            ),
            FilledButton.icon(
              onPressed: () => Navigator.pop(dialogContext, true),
              icon: const Icon(Icons.auto_fix_high, size: 18),
              label: const Text('Codex 제안 적용'),
            ),
          ],
        ),
      );
      if (apply == true && mounted) {
        _recordUndo();
        setState(() {
          for (final point in newPoints) {
            if (!_laneWaypoints.any(
              (value) => (value - point).distance <= .01,
            )) {
              _laneWaypoints.add(point);
            }
          }
          for (final entry in names.entries) {
            _waypointNames[entry.key] = entry.value;
            _waypointTypes[entry.key] = categories[entry.key] ?? '대기';
          }
          for (final lane in lanes) {
            if (_hasLane(lane.$1, lane.$2)) continue;
            _recommendedLanes.add(lane);
            _laneDirections[lane] = directions[lane] ?? '양방향';
          }
          _stage = MapStage.lanes;
          _mapScenarioSummary =
              'Codex 혼합 분석 · Waypoint ${newPoints.length} · Lane ${lanes.length}';
          _isDeployed = false;
          _vertexLabelRevision++;
        });
      }
      return true;
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Codex 제안이 맵 안전 검증을 통과하지 못해 로컬 분석으로 전환합니다.'),
          ),
        );
      }
      return false;
    }
  }

  Future<void> _showScenarioMapAssistant() async {
    if (_drawing == null) {
      _showProcessingWarning('시나리오 맵 자동 완성', '자동 경로를 배치할 도면을 먼저 올려주세요.');
      return;
    }
    if (_floorOutline().length < 3) {
      _showProcessingWarning(
        '시나리오 맵 자동 완성',
        'Waypoint를 Floor 내부에만 배치하려면 Floor 영역을 먼저 생성해야 합니다.',
      );
      return;
    }
    final robotController = TextEditingController(text: '4');
    final homeController = TextEditingController(text: '4');
    final chargerController = TextEditingController(text: '2');
    final ambientController = TextEditingController(text: '0');
    final chilledController = TextEditingController(text: '0');
    final frozenController = TextEditingController(text: '1');
    final dropoffController = TextEditingController(text: '1');
    var returnHome = true;
    var singleLoad = true;
    final config = await showMovableDialog<_MapScenarioConfig>(
      context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (context, setDialogState) {
          Widget countField(String label, TextEditingController controller) =>
              TextField(
                controller: controller,
                keyboardType: TextInputType.number,
                onChanged: (_) => setDialogState(() {}),
                decoration: InputDecoration(
                  labelText: label,
                  border: const OutlineInputBorder(),
                  isDense: true,
                ),
              );
          int count(TextEditingController controller) =>
              int.tryParse(controller.text.trim()) ?? -1;
          final counts = [
            robotController,
            homeController,
            chargerController,
            ambientController,
            chilledController,
            frozenController,
            dropoffController,
          ].map(count).toList();
          final valid =
              counts.every((value) => value >= 0) &&
              counts.first > 0 &&
              (!returnHome || counts[1] >= counts[0]);
          return AlertDialog(
            icon: const Icon(Icons.auto_awesome_outlined, size: 36),
            title: const Text('시나리오 맵 자동 완성'),
            content: SizedBox(
              width: 520,
              child: SingleChildScrollView(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      '기존 Lane에 연결된 이름 없는 대기 Waypoint를 운영 목적에 맞게 자동 배치합니다.',
                    ),
                    const SizedBox(height: 16),
                    Row(
                      children: [
                        Expanded(child: countField('이동 로봇 수', robotController)),
                        const SizedBox(width: 10),
                        Expanded(child: countField('Home 수', homeController)),
                        const SizedBox(width: 10),
                        Expanded(child: countField('충전소 수', chargerController)),
                      ],
                    ),
                    const SizedBox(height: 12),
                    Row(
                      children: [
                        Expanded(child: countField('상온 픽업', ambientController)),
                        const SizedBox(width: 10),
                        Expanded(child: countField('냉장 픽업', chilledController)),
                        const SizedBox(width: 10),
                        Expanded(child: countField('냉동 픽업', frozenController)),
                        const SizedBox(width: 10),
                        Expanded(child: countField('드랍오프', dropoffController)),
                      ],
                    ),
                    const SizedBox(height: 10),
                    CheckboxListTile(
                      value: returnHome,
                      contentPadding: EdgeInsets.zero,
                      title: const Text('작업 완료 후 빈 Home으로 복귀'),
                      onChanged: (value) =>
                          setDialogState(() => returnHome = value ?? true),
                    ),
                    if (returnHome && counts[1] < counts[0])
                      const Padding(
                        padding: EdgeInsets.only(bottom: 8),
                        child: Text(
                          '각 로봇이 동시에 복귀하려면 Home 수가 이동 로봇 수 이상이어야 합니다.',
                          style: TextStyle(
                            color: Color(0xFFDC2626),
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                      ),
                    CheckboxListTile(
                      value: singleLoad,
                      contentPadding: EdgeInsets.zero,
                      title: const Text('한 운행에서 상품을 한 번만 적재'),
                      onChanged: (value) =>
                          setDialogState(() => singleLoad = value ?? true),
                    ),
                    const Text(
                      '모든 신규 Waypoint를 Floor 내부에만 배치합니다. Home 수만큼 대기 지점을 만들고, 충전은 충전 지점으로 지정하며, 가는 길과 오는 길을 서로 다른 두 줄의 단방향 Lane으로 생성합니다.',
                      style: TextStyle(color: Color(0xFF64748B), fontSize: 12),
                    ),
                  ],
                ),
              ),
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(dialogContext),
                child: const Text('취소'),
              ),
              FilledButton.icon(
                onPressed: valid
                    ? () => Navigator.pop(
                        dialogContext,
                        _MapScenarioConfig(
                          robotCount: counts[0],
                          homeCount: counts[1],
                          chargerCount: counts[2],
                          ambientPickupCount: counts[3],
                          chilledPickupCount: counts[4],
                          frozenPickupCount: counts[5],
                          dropoffCount: counts[6],
                          returnHome: returnHome,
                          singleLoadPerTrip: singleLoad,
                        ),
                      )
                    : null,
                icon: const Icon(Icons.route_outlined, size: 18),
                label: const Text('추천 배치 만들기'),
              ),
            ],
          );
        },
      ),
    );
    for (final controller in [
      robotController,
      homeController,
      chargerController,
      ambientController,
      chilledController,
      frozenController,
      dropoffController,
    ]) {
      controller.dispose();
    }
    if (config == null || !mounted) return;
    final inferredWaypointCount = _inferWaypointTypesFromNames();
    if (await _tryCodexScenarioMap(config)) return;
    if (!mounted) return;
    final generatedDraft = _ensureScenarioDraftNetwork(config);
    if (generatedDraft.laneCount == 0) return;
    final assignments = _buildScenarioAssignments(config);
    if (assignments == null) {
      final connectedGeneralCount = _laneWaypoints.where((point) {
        if ((_waypointTypes[point] ?? '대기') != '대기') return false;
        if ((_waypointNames[point] ?? '').trim().isNotEmpty) return false;
        return _recommendedLanes.any(
          (lane) =>
              (lane.$1 - point).distance <= .01 ||
              (lane.$2 - point).distance <= .01,
        );
      }).length;
      _showProcessingWarning(
        '시나리오 맵 자동 완성',
        '기존 픽업·드랍오프·충전·Home을 제외한 부족한 역할을 배치할 '
            'Lane 연결 대기 Waypoint(이름 없음)가 부족합니다. '
            '현재 사용 가능: $connectedGeneralCount개',
      );
      return;
    }
    final apply = await showMovableDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        icon: const Icon(Icons.map_outlined, size: 36),
        title: const Text('추천 배치를 적용할까요?'),
        content: SizedBox(
          width: 500,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                '로봇 ${config.robotCount}대 · 목표 운영 지점 '
                '${config.requiredWaypointCount}개 · 새 역할 배치 ${assignments.length}개',
                style: const TextStyle(fontWeight: FontWeight.w800),
              ),
              if (inferredWaypointCount > 0) ...[
                const SizedBox(height: 6),
                Text('이름으로 인식한 운영 지점 $inferredWaypointCount개'),
              ],
              if (generatedDraft.waypointCount > 0) ...[
                const SizedBox(height: 6),
                Text(
                  '자동 경로 초안 · Waypoint ${generatedDraft.waypointCount}개 · '
                  'Lane ${generatedDraft.laneCount}개 '
                  '(${_scenarioUsesSeparateRoutes ? '2대 통행 가능: 가는 길·오는 길' : '협로: 공용 1경로+입구 대기'})'
                  '${generatedDraft.doubledCorridors == 0 ? '' : '\n넓은 통로 ${generatedDraft.doubledCorridors}곳은 가는 길·오는 길 단방향 2차선으로 분리했습니다.'}',
                  style: const TextStyle(
                    color: Color(0xFF7C3AED),
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ],
              if (generatedDraft.unlinked.isNotEmpty) ...[
                const SizedBox(height: 6),
                Text(
                  '안전거리를 지키며 연결하지 못한 지점 '
                  '${generatedDraft.unlinked.length}곳: '
                  '${generatedDraft.unlinked.join(', ')} · '
                  '벽에 너무 가까워 Lane을 잇지 않았습니다.',
                  style: const TextStyle(
                    color: Color(0xFFB45309),
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ],
              const SizedBox(height: 12),
              Container(
                constraints: const BoxConstraints(maxHeight: 300),
                child: ListView(
                  shrinkWrap: true,
                  children: [
                    for (final assignment in assignments)
                      ListTile(
                        dense: true,
                        leading: const Icon(Icons.place_outlined, size: 19),
                        title: Text(assignment.name),
                        subtitle: Text(
                          '${assignment.category} · X ${assignment.point.dx.toStringAsFixed(1)}, Y ${assignment.point.dy.toStringAsFixed(1)}',
                        ),
                      ),
                  ],
                ),
              ),
              const SizedBox(height: 8),
              Text(
                '${config.singleLoadPerTrip ? '운행당 1회 적재' : '운행당 복수 적재 허용'} · '
                '${config.returnHome ? '작업 후 Home 자동 복귀' : '최종 작업 지점 대기'}',
              ),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('초안만 유지'),
          ),
          FilledButton.icon(
            onPressed: () => Navigator.pop(dialogContext, true),
            icon: const Icon(Icons.auto_fix_high, size: 18),
            label: const Text('추천 맵 적용'),
          ),
        ],
      ),
    );
    if (apply != true || !mounted) return;
    _recordUndo();
    setState(() {
      for (final assignment in assignments) {
        _waypointTypes[assignment.point] = assignment.category;
        _waypointNames[assignment.point] = assignment.name;
      }
      _mapScenarioSummary =
          '로봇 ${config.robotCount}대 · Home ${config.homeCount} · 충전 ${config.chargerCount} · '
          '상온 ${config.ambientPickupCount} · 냉장 ${config.chilledPickupCount} · '
          '냉동 ${config.frozenPickupCount} · 드랍오프 ${config.dropoffCount} · '
          '${config.singleLoadPerTrip ? '1회 적재' : '복수 적재'} · '
          '${config.returnHome ? 'Home 복귀' : '현장 대기'}';
      if (generatedDraft.waypointCount > 0) {
        _mapScenarioSummary =
            '$_mapScenarioSummary · 자동 초안 Waypoint ${generatedDraft.waypointCount} / Lane ${generatedDraft.laneCount}';
      }
      _isDeployed = false;
      _vertexLabelRevision++;
    });
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text('운영 Waypoint ${assignments.length}개를 자동 배치했습니다.')),
    );
  }

  Future<void> _showValidationDialog() async {
    if (_drawing == null) return;
    final warnings = _validateMap();
    final report = [
      'YAML 오류 검증 결과',
      '파일: $_yamlFileName',
      '',
      if (warnings.isEmpty)
        '검증된 문제점이 없습니다.'
      else ...[
        'Warning ${warnings.length}건',
        for (var i = 0; i < warnings.length; i++) '${i + 1}. ${warnings[i]}',
      ],
    ].join('\n');
    if (!mounted) return;
    await showMovableDialog<void>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        icon: Icon(
          warnings.isEmpty
              ? Icons.verified_outlined
              : Icons.warning_amber_rounded,
          color: warnings.isEmpty
              ? const Color(0xFF15803D)
              : const Color(0xFFD97706),
          size: 36,
        ),
        title: const Text('YAML 오류 검증'),
        content: SizedBox(
          width: 560,
          child: Container(
            constraints: const BoxConstraints(maxHeight: 420),
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: warnings.isEmpty
                  ? const Color(0xFFF0FDF4)
                  : const Color(0xFFFFFBEB),
              borderRadius: BorderRadius.circular(10),
              border: Border.all(
                color: warnings.isEmpty
                    ? const Color(0xFF86EFAC)
                    : const Color(0xFFFCD34D),
              ),
            ),
            child: SingleChildScrollView(child: SelectableText(report)),
          ),
        ),
        actions: [
          if (_laneDetachedWaypoints().isNotEmpty)
            TextButton.icon(
              onPressed: () {
                Navigator.pop(dialogContext);
                unawaited(_spliceDetachedWaypoints());
              },
              icon: const Icon(Icons.link, size: 18),
              label: const Text('레인에 끼워 넣기'),
            ),
          TextButton.icon(
            onPressed: () {
              Navigator.pop(dialogContext);
              unawaited(_showRobotSafetySettings());
            },
            icon: const Icon(Icons.tune, size: 18),
            label: const Text('로봇 안전 기준'),
          ),
          TextButton.icon(
            onPressed: () async {
              await Clipboard.setData(ClipboardData(text: report));
              if (!dialogContext.mounted) return;
              ScaffoldMessenger.of(
                dialogContext,
              ).showSnackBar(const SnackBar(content: Text('검증 결과를 복사했습니다.')));
            },
            icon: const Icon(Icons.copy_outlined, size: 18),
            label: const Text('결과 복사'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(dialogContext),
            child: const Text('확인'),
          ),
        ],
      ),
    );
  }

  /// 메시지에서 Waypoint를 가리키는 이름.
  ///
  /// 이름이 없으면 순번과 함께 Floor 좌표를 붙인다. 오류 검증이 어느 지점을
  /// 두고 하는 말인지 알 수 없으면 고칠 수가 없다.
  String _waypointLabel(Offset point) {
    final name = (_waypointNames[point] ?? '').trim();
    if (name.isNotEmpty) return name;
    final index = _laneWaypoints.indexOf(point);
    final floor = _floorCoordinate(point);
    final position =
        '${floor.dx.toStringAsFixed(0)}, ${floor.dy.toStringAsFixed(0)}';
    return index < 0 ? '이름없음($position)' : '이름없는 ${index + 1}번($position)';
  }

  bool _hasLane(Offset start, Offset end) => _recommendedLanes.any(
    (lane) =>
        ((lane.$1 - start).distance <= .01 &&
            (lane.$2 - end).distance <= .01) ||
        ((lane.$1 - end).distance <= .01 && (lane.$2 - start).distance <= .01),
  );

  double _segmentDistance(
    Offset firstStart,
    Offset firstEnd,
    Offset secondStart,
    Offset secondEnd,
  ) => segmentDistance(firstStart, firstEnd, secondStart, secondEnd);

  double? get _metersPerPixel {
    final measurement = _measurement;
    if (measurement == null) return null;
    final pixels = (measurement.start - measurement.end).distance;
    if (pixels <= .01 || measurement.length <= 0) return null;
    final meters = measurement.unit == 'ft'
        ? measurement.length * .3048
        : measurement.length;
    return meters / pixels;
  }

  double get _laneWallClearancePixels {
    final metersPerPixel = _metersPerPixel;
    if (metersPerPixel == null || metersPerPixel <= 0) return 2;
    return math.max(
      2,
      (_robotWidthMeters / 2 + _localizationMarginMeters) / metersPerPixel,
    );
  }

  bool _touchesWall(Offset start, Offset end, {double? clearancePixels}) {
    final clearance = clearancePixels ?? _laneWallClearancePixels;
    return _visibleWallSegments().any(
      (wall) =>
          _segmentDistance(start, end, wall.$1, wall.$2) < clearance - .01,
    );
  }

  bool _crossesWall(Offset start, Offset end) => _touchesWall(start, end);

  /// 벽 여유가 모자랄 때 실제 수치를 담은 문장을 만든다.
  ///
  /// 어느 값이 잘못됐는지는 단정하지 않는다. 2m대 실험 공간에서 작은 로봇을
  /// 쓰는 것도 정상이라, 도면이 작다는 이유로 축척을 의심하면 헛경고가 된다.
  /// 판정에 쓰인 값을 그대로 보여 주고 판단은 사용자에게 맡긴다.
  String _wallClearanceIssue(double nearestPixels, double clearancePixels) {
    final metersPerPixel = _metersPerPixel;
    if (metersPerPixel == null || metersPerPixel <= 0) {
      return '벽에 너무 가까워 Lane을 만들 수 없습니다. '
          '필요 여유 ${clearancePixels.toStringAsFixed(0)}px, '
          '실제 ${nearestPixels.toStringAsFixed(0)}px입니다. '
          'Measurement를 지정하면 실제 치수로 확인할 수 있습니다.';
    }
    return '벽에 너무 가까워 Lane을 만들 수 없습니다. '
        '필요 여유 ${clearancePixels.toStringAsFixed(0)}px'
        '(${(clearancePixels * metersPerPixel).toStringAsFixed(2)}m), '
        '실제 ${nearestPixels.toStringAsFixed(0)}px'
        '(${(nearestPixels * metersPerPixel).toStringAsFixed(2)}m). '
        '로봇 폭 ${_robotWidthMeters.toStringAsFixed(2)}m · '
        '위치 오차 여유 ${_localizationMarginMeters.toStringAsFixed(2)}m · '
        '축척 ${(1 / metersPerPixel).toStringAsFixed(0)}px/m 기준입니다. '
        '값이 실제와 다르면 로봇 안전 기준이나 Measurement를 확인하세요.';
  }

  /// Lane을 만들 수 없는 이유. 만들 수 있으면 null.
  String? _laneCreationIssue(Offset start, Offset end) {
    if ((start - end).distance <= .01) return '시작점과 끝점이 같은 Lane은 만들 수 없습니다.';
    if (_hasLane(start, end)) return '두 Waypoint 사이에 Lane이 이미 있습니다.';
    final clearance = _laneWallClearancePixels;
    var nearest = double.infinity;
    for (final wall in _visibleWallSegments()) {
      final distance = _segmentDistance(start, end, wall.$1, wall.$2);
      if (distance < nearest) nearest = distance;
    }
    if (nearest.isFinite && nearest < clearance - .01) {
      return _wallClearanceIssue(nearest, clearance);
    }
    return null;
  }

  /// Waypoint를 찍다 생긴 오류를 팝업으로 알린다.
  ///
  /// 스낵바를 쓰다 팝업으로 옮겼다. 진단 문구에 수치가 들어가 길어졌는데
  /// 스낵바는 읽기 전에 사라지고, 값을 옮겨 적을 수도 없었다. 팝업은 닫을
  /// 때까지 남고, 본문을 끌어 선택하거나 복사 버튼으로 통째로 가져갈 수 있다.
  void _showLaneCreationIssue(String issue) {
    unawaited(
      showWaypointErrorDialog(
        context,
        title: 'Waypoint · Lane 오류',
        message: issue,
      ),
    );
  }

  List<_LaneRecommendation> _buildLaneRecommendations() {
    if (_recommendedLanes.isEmpty) return const [];
    final adjacency = <Offset, Set<Offset>>{};
    for (final lane in _recommendedLanes) {
      adjacency.putIfAbsent(lane.$1, () => <Offset>{}).add(lane.$2);
      adjacency.putIfAbsent(lane.$2, () => <Offset>{}).add(lane.$1);
    }
    final components = <Set<Offset>>[];
    final unvisited = adjacency.keys.toSet();
    while (unvisited.isNotEmpty) {
      final component = <Offset>{};
      final queue = <Offset>[unvisited.first];
      while (queue.isNotEmpty) {
        final point = queue.removeLast();
        if (!component.add(point)) continue;
        unvisited.remove(point);
        queue.addAll(
          adjacency[point]!.where((next) => !component.contains(next)),
        );
      }
      components.add(component);
    }

    final recommendations = <_LaneRecommendation>[];
    components.sort((a, b) => b.length.compareTo(a.length));
    final mainComponent = components.first;
    for (final component in components.skip(1)) {
      Offset? bestStart;
      Offset? bestEnd;
      var bestDistance = double.infinity;
      for (final start in mainComponent) {
        for (final end in component) {
          final distance = (start - end).distance;
          if (distance < bestDistance && !_crossesWall(start, end)) {
            bestDistance = distance;
            bestStart = start;
            bestEnd = end;
          }
        }
      }
      if (bestStart != null && bestEnd != null) {
        recommendations.add(
          _LaneRecommendation(
            title: '분리된 구역 연결',
            description:
                '${_waypointLabel(bestStart)} ↔ ${_waypointLabel(bestEnd)}를 연결하면 접근 불가능한 구역이 해소됩니다.',
            start: bestStart,
            end: bestEnd,
          ),
        );
      }
    }

    for (final entry in adjacency.entries) {
      if (recommendations.length >= 8) break;
      if (entry.value.length != 1) continue;
      final category = _waypointTypes[entry.key] ?? '대기';
      if (category == '충전' || category == '주차') continue;
      Offset? nearest;
      var nearestDistance = double.infinity;
      for (final candidate in adjacency.keys) {
        if (candidate == entry.key || entry.value.contains(candidate)) continue;
        if (_hasLane(entry.key, candidate)) continue;
        if (_crossesWall(entry.key, candidate)) continue;
        final distance = (entry.key - candidate).distance;
        if (distance < nearestDistance) {
          nearest = candidate;
          nearestDistance = distance;
        }
      }
      if (nearest == null) continue;
      final duplicate = recommendations.any(
        (item) =>
            (item.start == entry.key && item.end == nearest) ||
            (item.start == nearest && item.end == entry.key),
      );
      if (duplicate) continue;
      recommendations.add(
        _LaneRecommendation(
          title: '막다른 경로에 우회로 추가',
          description:
              '${_waypointLabel(entry.key)} ↔ ${_waypointLabel(nearest)}를 연결하면 단일 경로 의존도를 줄일 수 있습니다.',
          start: entry.key,
          end: nearest,
        ),
      );
    }
    return recommendations;
  }

  Future<void> _showLaneRecommendationsDialog() async {
    final recommendations = _buildLaneRecommendations();
    if (!mounted) return;
    if (recommendations.isEmpty) {
      await showMovableDialog<void>(
        context: context,
        builder: (dialogContext) => AlertDialog(
          icon: const Icon(
            Icons.route_outlined,
            color: Color(0xFF15803D),
            size: 36,
          ),
          title: const Text('경로 추천'),
          content: const Text('현재 Lane 구성에서 바로 적용할 추가 경로를 찾지 못했습니다.'),
          actions: [
            FilledButton(
              onPressed: () => Navigator.pop(dialogContext),
              child: const Text('확인'),
            ),
          ],
        ),
      );
      return;
    }

    final selected = <int>{};
    final directions = <int, String>{
      for (var i = 0; i < recommendations.length; i++) i: '양방향',
    };
    final result =
        await showMovableDialog<
          ({Set<int> selected, Map<int, String> directions})
        >(
          context: context,
          builder: (dialogContext) => StatefulBuilder(
            builder: (context, setDialogState) => AlertDialog(
              icon: const Icon(
                Icons.auto_awesome_outlined,
                color: Color(0xFF2563EB),
                size: 36,
              ),
              title: const Text('효율적인 경로 추천'),
              content: SizedBox(
                width: 650,
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text('적용할 추천을 선택하고 각 Lane의 이동 방향을 수정할 수 있습니다.'),
                    const SizedBox(height: 14),
                    Flexible(
                      child: ListView.separated(
                        shrinkWrap: true,
                        itemCount: recommendations.length,
                        separatorBuilder: (_, _) => const Divider(height: 1),
                        itemBuilder: (context, index) {
                          final item = recommendations[index];
                          return CheckboxListTile(
                            value: selected.contains(index),
                            onChanged: (checked) => setDialogState(() {
                              checked == true
                                  ? selected.add(index)
                                  : selected.remove(index);
                            }),
                            title: Text(item.title),
                            subtitle: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                const SizedBox(height: 4),
                                Text(item.description),
                                const SizedBox(height: 8),
                                DropdownButton<String>(
                                  value: directions[index],
                                  items: const [
                                    DropdownMenuItem(
                                      value: '양방향',
                                      child: Text('양방향'),
                                    ),
                                    DropdownMenuItem(
                                      value: '정방향',
                                      child: Text('정방향'),
                                    ),
                                    DropdownMenuItem(
                                      value: '역방향',
                                      child: Text('역방향'),
                                    ),
                                  ],
                                  onChanged: (value) {
                                    if (value != null) {
                                      setDialogState(
                                        () => directions[index] = value,
                                      );
                                    }
                                  },
                                ),
                              ],
                            ),
                            controlAffinity: ListTileControlAffinity.leading,
                          );
                        },
                      ),
                    ),
                  ],
                ),
              ),
              actions: [
                TextButton(
                  onPressed: () => Navigator.pop(dialogContext),
                  child: const Text('취소'),
                ),
                FilledButton.icon(
                  onPressed: selected.isEmpty
                      ? null
                      : () => Navigator.pop(dialogContext, (
                          selected: {...selected},
                          directions: {...directions},
                        )),
                  icon: const Icon(Icons.auto_fix_high, size: 18),
                  label: Text('선택 적용 (${selected.length})'),
                ),
              ],
            ),
          ),
        );
    if (result == null || !mounted) return;
    _recordUndo();
    setState(() {
      for (final index in result.selected) {
        final recommendation = recommendations[index];
        if (_hasLane(recommendation.start, recommendation.end)) continue;
        final lane = (recommendation.start, recommendation.end);
        _recommendedLanes.add(lane);
        _laneDirections[lane] = result.directions[index] ?? '양방향';
      }
      _stage = MapStage.lanes;
      _isDeployed = false;
      _vertexLabelRevision++;
    });
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text('추천 Lane ${result.selected.length}개를 적용했습니다.')),
    );
  }

  bool _showMapValidationWarnings() {
    final warnings = _validateMap();
    if (warnings.isEmpty) return false;
    setState(() {
      _processingWarning = [
        '[맵 검증] 배포 전에 확인이 필요합니다.',
        for (var i = 0; i < warnings.length; i++) '${i + 1}. ${warnings[i]}',
      ].join('\n');
    });
    return true;
  }

  _EditorSnapshot _captureSnapshot() => _EditorSnapshot(
    drawing: _drawing,
    stage: _stage,
    measurement: _measurement,
    wallMask: _wallMask,
    floorMask: _floorMask,
    previousWallMask: _previousWallMask,
    wallsDetected: _wallsDetected,
    floorGenerated: _floorGenerated,
    manualWalls: [..._manualWalls],
    wallVertexOverrides: {..._wallVertexOverrides},
    frozenAutoWalls: [..._frozenAutoWalls],
    recommendedLanes: [..._recommendedLanes],
    laneDirections: {..._laneDirections},
    laneSpeedLimits: {..._laneSpeedLimits},
    laneOrientations: {..._laneOrientations},
    laneMutexGroups: {..._laneMutexGroups},
    robotWidthMeters: _robotWidthMeters,
    turningRadiusMeters: _turningRadiusMeters,
    localizationMarginMeters: _localizationMarginMeters,
    mapScenarioSummary: _mapScenarioSummary,
    laneWaypoints: [..._laneWaypoints],
    waypointTypes: {..._waypointTypes},
    waypointNames: {..._waypointNames},
    activeLaneEndpoint: _activeLaneEndpoint,
  );

  void _recordUndo() {
    _undoHistory.add(_captureSnapshot());
    if (_undoHistory.length > 10) _undoHistory.removeAt(0);
  }

  void _undo() {
    if (_undoHistory.isEmpty) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('되돌릴 작업이 없습니다.')));
      return;
    }
    final snapshot = _undoHistory.removeLast();
    setState(() {
      _drawing = snapshot.drawing;
      _stage = snapshot.stage;
      _measurement = snapshot.measurement;
      _wallMask = snapshot.wallMask;
      _floorMask = snapshot.floorMask;
      _previousWallMask = snapshot.previousWallMask;
      _wallsDetected = snapshot.wallsDetected;
      _floorGenerated = snapshot.floorGenerated;
      _manualWalls
        ..clear()
        ..addAll(snapshot.manualWalls);
      _wallVertexOverrides
        ..clear()
        ..addAll(snapshot.wallVertexOverrides);
      _frozenAutoWalls = [...snapshot.frozenAutoWalls];
      _recommendedLanes = [...snapshot.recommendedLanes];
      _laneDirections
        ..clear()
        ..addAll(snapshot.laneDirections);
      _laneSpeedLimits
        ..clear()
        ..addAll(snapshot.laneSpeedLimits);
      _laneOrientations
        ..clear()
        ..addAll(snapshot.laneOrientations);
      _laneMutexGroups
        ..clear()
        ..addAll(snapshot.laneMutexGroups);
      _robotWidthMeters = snapshot.robotWidthMeters;
      _turningRadiusMeters = snapshot.turningRadiusMeters;
      _localizationMarginMeters = snapshot.localizationMarginMeters;
      _mapScenarioSummary = snapshot.mapScenarioSummary;
      _laneWaypoints
        ..clear()
        ..addAll(snapshot.laneWaypoints);
      _waypointTypes
        ..clear()
        ..addAll(snapshot.waypointTypes);
      _waypointNames
        ..clear()
        ..addAll(snapshot.waypointNames);
      _activeLaneEndpoint = snapshot.activeLaneEndpoint;
      _isWaypointMode = false;
      _isMeasurementMode = false;
      _isWallEraseMode = false;
      _isWallConnectMode = false;
      _isWallEndpointEditMode = false;
      _pendingWallVertex = null;
      _isDeployed = false;
      _vertexLabelRevision++;
    });
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text('이전 작업으로 되돌렸습니다. (${_undoHistory.length}단계 남음)')),
    );
  }

  Future<void> _pickDrawing() async {
    if (_isPicking) return;
    setState(() => _isPicking = true);
    try {
      final result = await FilePicker.platform.pickFiles(
        type: FileType.custom,
        allowedExtensions: const ['png', 'jpg', 'jpeg', 'pdf', 'dxf', 'dwg'],
        withData: true,
      );
      if (result == null || result.files.isEmpty) return;
      final file = result.files.single;
      final extension = (file.extension ?? '').toLowerCase();
      int? pixelWidth;
      int? pixelHeight;
      if (['png', 'jpg', 'jpeg'].contains(extension) && file.bytes != null) {
        final codec = await ui.instantiateImageCodec(file.bytes!);
        final frame = await codec.getNextFrame();
        pixelWidth = frame.image.width;
        pixelHeight = frame.image.height;
        frame.image.dispose();
        codec.dispose();
      }
      if (!mounted) return;
      _fitMapToScreen();
      _recordUndo();
      setState(() {
        // 도면을 갈아 끼워도 프로젝트는 그대로다. 예전에는 여기서
        // 이름을 지워 도면 파일 이름으로 되돌렸다.
        _projectFileName = null;
        _mapScenarioSummary = null;
        _drawing = UploadedDrawing(
          name: file.name,
          extension: extension,
          size: file.size,
          bytes: file.bytes,
          pixelWidth: pixelWidth,
          pixelHeight: pixelHeight,
        );
        _stage = MapStage.upload;
        _isDeployed = false;
        _wallMask = null;
        _floorMask = null;
        _wallsDetected = false;
        _floorGenerated = false;
        _previousWallMask = null;
        _isWallEraseMode = false;
        _isMeasurementMode = false;
        _measurement = null;
        _isMeasurementSelected = false;
        _showDrawingInfo = true;
        _isWallConnectMode = false;
        _pendingWallVertex = null;
        _manualWalls.clear();
        _isWallEndpointEditMode = false;
        _wallVertexOverrides.clear();
        _frozenAutoWalls = [];
        _recommendedLanes = [];
        _laneDirections.clear();
        _laneSpeedLimits.clear();
        _laneOrientations.clear();
        _laneMutexGroups.clear();
        _laneWaypoints.clear();
        _waypointTypes.clear();
        _waypointNames.clear();
        _activeLaneEndpoint = null;
        _isWaypointMode = false;
      });
      // 열린 프로젝트가 있으면 도면을 그 프로젝트에 바로 넣는다. 저장을
      // 미루면 앱이 죽었을 때 어떤 도면으로 시작했는지가 사라지고, 무엇보다
      // 프로젝트 목록에 도면 이름이 안 떠서 어느 창고인지 알 수 없다.
      final project = _openProjectName;
      var stored = false;
      if (project != null) {
        try {
          await _writeMapProject(project);
          stored = true;
        } catch (error) {
          if (!mounted) return;
          // 도면은 화면에 이미 올라와 있다. 저장만 못 했으니 그것만 알린다.
          _showProcessingWarning('도면을 프로젝트에 저장', error);
        }
      }
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            stored
                ? '${file.name} 도면을 `$project` 프로젝트에 저장했습니다.'
                : '${file.name} 도면을 불러왔습니다.',
          ),
        ),
      );
    } catch (error) {
      if (!mounted) return;
      _showProcessingWarning('도면 불러오기', error);
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text('파일을 불러오지 못했습니다: $error')));
    } finally {
      if (mounted) setState(() => _isPicking = false);
    }
  }

  void _removeDrawing() {
    if (_drawing == null) return;
    _recordUndo();
    _fitMapToScreen();
    _clearMapWorkspace();
  }

  /// 도면과 그 도면에서 나온 것을 전부 비운다.
  ///
  /// 프로젝트 이름은 건드리지 않는다. 도면을 지우는 것과 프로젝트에서 나가는
  /// 것은 다른 일이다. `새 프로젝트` 도 이 초기화를 쓴다 — 이름만 새로 받고
  /// 화면은 같은 백지에서 시작해야 하므로.
  void _clearMapWorkspace() {
    setState(() {
      _projectFileName = null;
      _mapScenarioSummary = null;
      _drawing = null;
      _stage = MapStage.upload;
      _isDeployed = false;
      _wallMask = null;
      _floorMask = null;
      _wallsDetected = false;
      _floorGenerated = false;
      _previousWallMask = null;
      _isWallEraseMode = false;
      _isMeasurementMode = false;
      _measurement = null;
      _isMeasurementSelected = false;
      _showDrawingInfo = false;
      _isWallConnectMode = false;
      _pendingWallVertex = null;
      _manualWalls.clear();
      _isWallEndpointEditMode = false;
      _wallVertexOverrides.clear();
      _frozenAutoWalls = [];
      _recommendedLanes = [];
      _laneDirections.clear();
      _laneSpeedLimits.clear();
      _laneOrientations.clear();
      _laneMutexGroups.clear();
      _laneWaypoints.clear();
      _waypointTypes.clear();
      _waypointNames.clear();
      _activeLaneEndpoint = null;
      _isWaypointMode = false;
    });
  }

  void _zoomMap(double factor) {
    final current = _mapTransform.value.getMaxScaleOnAxis();
    final next = (current * factor).clamp(.4, 5.0);
    _mapTransform.value = Matrix4.diagonal3Values(next, next, 1);
  }

  void _fitMapToScreen() {
    _mapTransform.value = Matrix4.identity();
  }

  Future<void> _renumberVertices() async {
    final count = _visibleMapVertices().length;
    setState(() {
      _pendingWallVertex = null;
      _isMeasurementSelected = false;
      _showVertexLabels = false;
    });
    await WidgetsBinding.instance.endOfFrame;
    if (!mounted) return;
    setState(() {
      _vertexLabelRevision++;
      _showVertexLabels = true;
    });
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text('정점 $count개를 왼쪽 시작 시계방향으로 재넘버링했습니다.')),
    );
  }

  void _toggleWaypointMode() {
    if (_drawing == null) return;
    if (!_floorGenerated) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('Floor를 먼저 생성해주세요.')));
      return;
    }
    setState(() {
      _isWaypointMode = !_isWaypointMode;
      if (!_isWaypointMode) _activeLaneEndpoint = null;
      _isWallEraseMode = false;
      _isMeasurementMode = false;
      _isWallConnectMode = false;
      _isWallEndpointEditMode = false;
    });
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          _isWaypointMode
              ? '도면을 눌러 Waypoint를 순서대로 입력하세요.'
              : 'Waypoint 입력을 완료했습니다.',
        ),
      ),
    );
  }

  void _finishCurrentLane() {
    if (!_isWaypointMode || _activeLaneEndpoint == null) return;
    setState(() => _activeLaneEndpoint = null);
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('현재 레인을 종료했습니다. 새 시작점을 선택하세요.')),
    );
  }

  Offset? _firstCrossedWaypoint(Offset start, Offset end, double tolerance) {
    final lane = end - start;
    final lengthSquared = lane.distanceSquared;
    if (lengthSquared <= .01) return null;
    Offset? crossed;
    var firstT = 1.0;
    for (final waypoint in _laneWaypoints) {
      if ((waypoint - start).distance <= tolerance) continue;
      final relative = waypoint - start;
      final t = (relative.dx * lane.dx + relative.dy * lane.dy) / lengthSquared;
      if (t <= .02 || t >= .98 || t >= firstT) continue;
      final nearest = start + lane * t;
      if ((waypoint - nearest).distance <= tolerance) {
        crossed = waypoint;
        firstT = t;
      }
    }
    return crossed;
  }

  Future<String?> _chooseWaypointAction(Offset waypoint) =>
      showMovableDialog<String>(
        context: context,
        builder: (dialogContext) => AlertDialog(
          title: Text(
            (_waypointNames[waypoint] ?? '').trim().isEmpty
                ? 'Waypoint 선택'
                : _waypointNames[waypoint]!,
          ),
          // 레인을 그리는 중(시작점이 잡힌 상태)에는 이 창을 띄우지 않는다. 그때
          // 찍는 Waypoint는 끝점이므로 바로 잇는다.
          content: Text(
            '카테고리: ${_waypointTypes[waypoint] ?? '대기'}\n'
            '시작점으로 잡으면 다음에 찍는 Waypoint까지 Lane이 자동으로 연결됩니다.',
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext),
              child: const Text('취소'),
            ),
            TextButton.icon(
              onPressed: () => Navigator.pop(dialogContext, 'delete'),
              icon: const Icon(Icons.delete_outline),
              label: const Text('Waypoint 삭제'),
              style: TextButton.styleFrom(
                foregroundColor: const Color(0xFFDC2626),
              ),
            ),
            FilledButton.icon(
              onPressed: () => Navigator.pop(dialogContext, 'connect'),
              icon: const Icon(Icons.route, size: 18),
              label: const Text('레인 시작점으로 사용'),
            ),
          ],
        ),
      );

  /// [tolerance] 안에 레인이 있으면 그 선 위의 가장 가까운 점을 돌려준다.
  ///
  /// Waypoint 를 레인 근처에 놓으면 그 선 위에 얹으려는 뜻으로 본다. 몇 픽셀
  /// 어긋난 채로 두면 눈에는 선 위인데 연결되지 않아, 로봇이 지나갈 수 없는
  /// 외딴 지점이 된다.
  Offset? _snapToLane(Offset point, double tolerance, {Offset? ignore}) {
    Offset? best;
    var bestDistance = tolerance;
    for (final lane in _recommendedLanes) {
      if (ignore != null &&
          ((lane.$1 - ignore).distance <= .01 ||
              (lane.$2 - ignore).distance <= .01)) {
        continue;
      }
      final distance = pointSegmentDistance(point, lane.$1, lane.$2);
      if (distance <= bestDistance) {
        bestDistance = distance;
        best = closestPointOnSegment(point, lane.$1, lane.$2);
      }
    }
    return best;
  }

  /// 레인 위에 놓인 [point] 를 그 레인에 끼워 넣는다. 끼운 레인 수를 돌려준다.
  ///
  /// 레인을 그 지점에서 둘로 나눠 잇는다. 방향·속도 제한·자세 제약·Mutex 는
  /// 원래 레인의 값을 두 조각이 그대로 물려받는다 — 일방통행이던 통로가 나뉘면서
  /// 양방향으로 풀리면 로봇이 역주행한다.
  ///
  /// setState 안에서 부른다.
  int _spliceWaypointIntoLanes(Offset point, double tolerance) {
    final targets = [
      for (final lane in _recommendedLanes)
        if ((lane.$1 - point).distance > .01 &&
            (lane.$2 - point).distance > .01 &&
            pointSegmentDistance(point, lane.$1, lane.$2) <= tolerance)
          lane,
    ];
    for (final lane in targets) {
      final direction = _laneDirections[lane] ?? '양방향';
      final speed = _laneSpeedLimits[lane];
      final orientation = _laneOrientations[lane];
      final mutex = _laneMutexGroups[lane];
      _recommendedLanes.remove(lane);
      _removeLaneProperties(lane);
      for (final piece in [(lane.$1, point), (point, lane.$2)]) {
        if ((piece.$1 - piece.$2).distance <= .01) continue;
        if (_hasLane(piece.$1, piece.$2)) continue;
        _recommendedLanes.add(piece);
        _laneDirections[piece] = direction;
        if (speed != null) _laneSpeedLimits[piece] = speed;
        if (orientation != null) _laneOrientations[piece] = orientation;
        if (mutex != null) _laneMutexGroups[piece] = mutex;
      }
    }
    return targets.length;
  }

  void _removeLaneProperties((Offset, Offset) lane) {
    _laneDirections.remove(lane);
    _laneSpeedLimits.remove(lane);
    _laneOrientations.remove(lane);
    _laneMutexGroups.remove(lane);
  }

  void _deleteWaypoint(Offset waypoint) {
    _recordUndo();
    var removedLaneCount = 0;
    setState(() {
      for (var i = _recommendedLanes.length - 1; i >= 0; i--) {
        final lane = _recommendedLanes[i];
        if ((lane.$1 - waypoint).distance <= .01 ||
            (lane.$2 - waypoint).distance <= .01) {
          _removeLaneProperties(lane);
          _recommendedLanes.removeAt(i);
          removedLaneCount++;
        }
      }
      _laneWaypoints.removeWhere((point) => (point - waypoint).distance <= .01);
      _waypointTypes.remove(waypoint);
      _waypointNames.remove(waypoint);
      if (_activeLaneEndpoint != null &&
          (_activeLaneEndpoint! - waypoint).distance <= .01) {
        _activeLaneEndpoint = null;
      }
      _isDeployed = false;
      _vertexLabelRevision++;
    });
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          removedLaneCount > 0
              ? 'Waypoint와 연결된 레인 $removedLaneCount개를 삭제했습니다.'
              : 'Waypoint를 삭제했습니다.',
        ),
      ),
    );
  }

  /// Why [updated] is not a valid drop point for the Waypoint at [original],
  /// or null when the move is allowed. Shared with the drag preview so the
  /// canvas shows the same verdict before the button is released.
  WaypointMoveIssue? _waypointDropIssue(Offset original, Offset updated) =>
      waypointMoveIssue(
        original: original,
        updated: updated,
        waypoints: _laneWaypoints,
        lanes: _recommendedLanes,
        walls: _visibleWallSegments(),
        floorOutline: _floorOutline(),
        laneWallClearance: _laneWallClearancePixels,
      );

  String _waypointDropMessage(WaypointMoveIssue issue) => switch (issue) {
    WaypointMoveIssue.outsideFloor => 'Waypoint는 Floor 내부로만 이동할 수 있습니다.',
    WaypointMoveIssue.waypointTooClose => '다른 Waypoint와 너무 가깝습니다.',
    WaypointMoveIssue.laneTouchesWall =>
      '이동하면 연결된 Lane이 벽 안전거리'
          '(${_laneWallClearancePixels.toStringAsFixed(1)}px)를 침범하므로 '
          '원래 위치를 유지합니다.',
  };

  void _moveWaypoint(Offset original, Offset rawUpdated) {
    final index = _laneWaypoints.indexWhere(
      (point) => (point - original).distance <= .01,
    );
    if (index < 0) return;
    // 끌어다 놓은 자리가 레인 근처면 그 선 위로 맞춘다. 자기에게 붙어 있는
    // 레인은 함께 움직이므로 스냅 대상에서 뺀다.
    final updated =
        _snapToLane(rawUpdated, _waypointLaneSnapTolerance, ignore: original) ??
        rawUpdated;
    if ((original - updated).distance <= .01) return;
    final issue = _waypointDropIssue(original, updated);
    if (issue != null) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(_waypointDropMessage(issue))));
      return;
    }
    final movedLanes = <(Offset, Offset)>[
      for (final lane in _recommendedLanes)
        (
          (lane.$1 - original).distance <= .01 ? updated : lane.$1,
          (lane.$2 - original).distance <= .01 ? updated : lane.$2,
        ),
    ];
    _recordUndo();
    final oldLanes = [..._recommendedLanes];
    final oldDirections = {..._laneDirections};
    final oldSpeeds = {..._laneSpeedLimits};
    final oldOrientations = {..._laneOrientations};
    final oldMutexGroups = {..._laneMutexGroups};
    final type = _waypointTypes[original];
    final name = _waypointNames[original];
    var spliced = 0;
    setState(() {
      _laneWaypoints[index] = updated;
      _waypointTypes.remove(original);
      _waypointNames.remove(original);
      if (type != null) _waypointTypes[updated] = type;
      if (name != null) _waypointNames[updated] = name;
      _recommendedLanes = movedLanes;
      _laneDirections.clear();
      _laneSpeedLimits.clear();
      _laneOrientations.clear();
      _laneMutexGroups.clear();
      for (var laneIndex = 0; laneIndex < oldLanes.length; laneIndex++) {
        final oldLane = oldLanes[laneIndex];
        final newLane = movedLanes[laneIndex];
        if (oldDirections[oldLane] case final value?) {
          _laneDirections[newLane] = value;
        }
        if (oldSpeeds[oldLane] case final value?) {
          _laneSpeedLimits[newLane] = value;
        }
        if (oldOrientations[oldLane] case final value?) {
          _laneOrientations[newLane] = value;
        }
        if (oldMutexGroups[oldLane] case final value?) {
          _laneMutexGroups[newLane] = value;
        }
      }
      if (_activeLaneEndpoint != null &&
          (_activeLaneEndpoint! - original).distance <= .01) {
        _activeLaneEndpoint = updated;
      }
      if (_waypointTypes[updated] != '설비') {
        spliced = _spliceWaypointIntoLanes(updated, _waypointLaneSnapTolerance);
      }
      _isDeployed = false;
      _vertexLabelRevision++;
    });
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          spliced > 0
              ? 'Waypoint를 레인 위에 놓아 레인 $spliced개를 나눠 이었습니다.'
              : 'Waypoint와 연결된 Lane을 함께 이동했습니다.',
        ),
      ),
    );
  }

  /// Waypoint 를 끌어 놓을 때 레인에 붙는 거리.
  ///
  /// Waypoint 추가와 같은 기준(도면 짧은 변의 2%)을 쓴다. 도면이 없으면 화면
  /// 기준으로 16px.
  double get _waypointLaneSnapTolerance {
    final drawing = _drawing;
    final width = drawing?.pixelWidth;
    final height = drawing?.pixelHeight;
    if (width == null || height == null) return 16;
    return math.min(width, height) * .02;
  }

  Future<void> _confirmDeleteWaypoint(Offset waypoint) async {
    final name = (_waypointNames[waypoint] ?? '').trim();
    final confirmed = await showMovableDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        icon: const Icon(Icons.delete_outline, color: Color(0xFFDC2626)),
        title: const Text('Waypoint를 삭제할까요?'),
        content: Text(
          '${name.isEmpty ? '선택한 Waypoint' : name}와 연결된 모든 레인도 함께 삭제됩니다.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('취소'),
          ),
          FilledButton.icon(
            onPressed: () => Navigator.pop(dialogContext, true),
            icon: const Icon(Icons.delete_outline),
            label: const Text('삭제'),
            style: FilledButton.styleFrom(
              backgroundColor: const Color(0xFFDC2626),
            ),
          ),
        ],
      ),
    );
    if (confirmed == true && mounted) _deleteWaypoint(waypoint);
  }

  String _waypointTypeDescription(String type) => switch (type) {
    '대기' => '경로 연결과 잠시 정지할 수 있는 지점입니다. RMF에서는 holding point로 내보냅니다.',
    '주차' =>
      '작업이 없을 때 로봇을 장시간 세워 두는 전용 자리입니다. 이름을 홈N으로 붙여 로봇 복귀 지점으로도 씁니다. RMF에서는 parking spot으로 내보냅니다.',
    '홈' => '홈 풀 자동 할당에서 복귀 위치로 사용하는 지점입니다.',
    '충전' => '로봇 충전 위치로 사용하는 지점입니다.',
    '픽업' => '상품이나 화물을 싣는 작업 위치입니다.',
    '드랍오프' => '상품이나 화물을 내려놓는 작업 위치입니다.',
    '설비' => '고정 로봇팔·컨베이어 등의 설치 좌표입니다. 이동 Lane에 연결하지 않습니다.',
    _ => '',
  };

  /// 자동 이름의 접두사가 카테고리명과 다른 경우. 주차 지점은 로봇이 복귀해
  /// 서 있는 자리이므로 `_homeWaypoints`(이름이 '홈'으로 시작하는 Waypoint를
  /// 복귀 지점으로 잡는다)가 집어갈 수 있도록 홈N으로 붙인다.
  static const Map<String, String> _waypointNamePrefixes = {'주차': '홈'};

  String _nextWaypointName(String category) {
    final prefix = _waypointNamePrefixes[category] ?? category;
    var maxNumber = 0;
    final pattern = RegExp('^${RegExp.escape(prefix)}([0-9]+)\$');
    // 카테고리가 아니라 이름 전체를 훑는다. '주차'와 '홈'이 같은 홈N 접두사를
    // 공유하므로, 카테고리별로 세면 양쪽에서 홈1이 생겨 중복 이름 검사에 걸린다.
    for (final name in _waypointNames.values) {
      final match = pattern.firstMatch(name.trim());
      final number = match == null ? null : int.tryParse(match.group(1)!);
      if (number != null) maxNumber = math.max(maxNumber, number);
    }
    return '$prefix${maxNumber + 1}';
  }

  Future<void> _editWaypoint(Offset waypoint) async {
    final nameController = TextEditingController(
      text: _waypointNames[waypoint] ?? '',
    );
    var selectedType = _waypointTypes[waypoint] == '드롭오프'
        ? '드랍오프'
        : _waypointTypes[waypoint] ?? '대기';
    final action = await showMovableDialog<String>(
      context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (context, setDialogState) => AlertDialog(
          title: const Text('Waypoint 수정'),
          content: SizedBox(
            width: 360,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                TextField(
                  controller: nameController,
                  autofocus: true,
                  decoration: InputDecoration(
                    labelText: 'Waypoint 이름',
                    border: OutlineInputBorder(),
                  ),
                  onChanged: (_) => setDialogState(() {}),
                ),
                const SizedBox(height: 14),
                DropdownButtonFormField<String>(
                  initialValue: selectedType,
                  decoration: const InputDecoration(
                    labelText: 'Waypoint 카테고리',
                    border: OutlineInputBorder(),
                  ),
                  items: const ['대기', '주차', '홈', '충전', '픽업', '드랍오프', '설비']
                      .map(
                        (type) =>
                            DropdownMenuItem(value: type, child: Text(type)),
                      )
                      .toList(),
                  onChanged: (value) {
                    if (value != null) {
                      setDialogState(() => selectedType = value);
                    }
                  },
                ),
                const SizedBox(height: 10),
                Align(
                  alignment: Alignment.centerLeft,
                  child: Text(
                    _waypointTypeDescription(selectedType),
                    style: const TextStyle(
                      color: Color(0xFF64748B),
                      fontSize: 12,
                    ),
                  ),
                ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext),
              child: const Text('취소'),
            ),
            TextButton.icon(
              onPressed: () => Navigator.pop(dialogContext, 'delete'),
              icon: const Icon(Icons.delete_outline),
              label: const Text('Waypoint 삭제'),
              style: TextButton.styleFrom(
                foregroundColor: const Color(0xFFDC2626),
              ),
            ),
            FilledButton(
              onPressed:
                  selectedType != '대기' && nameController.text.trim().isEmpty
                  ? null
                  : () => Navigator.pop(dialogContext, 'save'),
              child: const Text('저장'),
            ),
          ],
        ),
      ),
    );
    // 대기 지점은 이름 없이 둘 수 있다(시나리오 자동 배치가 이름 없는 대기
    // Waypoint를 후보로 쓴다). 다만 입력한 이름이 있으면 그대로 살린다.
    final enteredName = nameController.text.trim();
    final name = enteredName.isEmpty ? ' ' : enteredName;
    await Future<void>.delayed(const Duration(milliseconds: 350));
    nameController.dispose();
    if (!mounted) return;
    if (action == 'delete') {
      await _confirmDeleteWaypoint(waypoint);
      return;
    }
    if (action != 'save' || name.isEmpty) return;
    _recordUndo();
    setState(() {
      _waypointNames[waypoint] = name;
      _waypointTypes[waypoint] = selectedType;
      _isDeployed = false;
    });
    ScaffoldMessenger.of(
      context,
    ).showSnackBar(const SnackBar(content: Text('Waypoint 정보를 수정했습니다.')));
  }

  Future<void> _selectLaneForDeletion((Offset, Offset) lane) async {
    var selectedDirection = _laneDirections[lane] ?? '양방향';
    var selectedOrientation = _laneOrientations[lane] ?? '제약 없음';
    final speedController = TextEditingController(
      text: _laneSpeedLimits[lane]?.toStringAsFixed(2) ?? '',
    );
    final mutexController = TextEditingController(
      text: _laneMutexGroups[lane] ?? '',
    );
    final result =
        await showMovableDialog<
          ({
            String action,
            String direction,
            double? speed,
            String orientation,
            String mutex,
          })
        >(
          context: context,
          builder: (dialogContext) => StatefulBuilder(
            builder: (context, setDialogState) => AlertDialog(
              icon: const Icon(Icons.route_outlined, color: Color(0xFF2563EB)),
              title: const Text('레인 설정'),
              content: SizedBox(
                width: 390,
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    DropdownButtonFormField<String>(
                      initialValue: selectedDirection,
                      decoration: const InputDecoration(
                        labelText: 'Lane 이동 방향',
                        border: OutlineInputBorder(),
                      ),
                      items: const [
                        DropdownMenuItem(
                          value: '정방향',
                          child: Text('단방향 · 정방향 (시작 → 끝)'),
                        ),
                        DropdownMenuItem(
                          value: '양방향',
                          child: Text('양방향 (시작 ↔ 끝)'),
                        ),
                        DropdownMenuItem(
                          value: '역방향',
                          child: Text('단방향 · 역방향 (끝 → 시작)'),
                        ),
                      ],
                      onChanged: (value) {
                        if (value != null) {
                          setDialogState(() => selectedDirection = value);
                        }
                      },
                    ),
                    const SizedBox(height: 12),
                    DropdownButtonFormField<String>(
                      initialValue: selectedOrientation,
                      decoration: const InputDecoration(
                        labelText: '로봇 진행 자세',
                        border: OutlineInputBorder(),
                      ),
                      items: const [
                        DropdownMenuItem(value: '제약 없음', child: Text('제약 없음')),
                        DropdownMenuItem(
                          value: 'forward',
                          child: Text('정면 주행'),
                        ),
                        DropdownMenuItem(
                          value: 'backward',
                          child: Text('후진 주행'),
                        ),
                      ],
                      onChanged: (value) {
                        if (value != null) {
                          setDialogState(() => selectedOrientation = value);
                        }
                      },
                    ),
                    const SizedBox(height: 12),
                    TextField(
                      controller: speedController,
                      keyboardType: const TextInputType.numberWithOptions(
                        decimal: true,
                      ),
                      decoration: const InputDecoration(
                        labelText: '속도 제한 (m/s, 선택)',
                        border: OutlineInputBorder(),
                      ),
                    ),
                    const SizedBox(height: 12),
                    TextField(
                      controller: mutexController,
                      decoration: const InputDecoration(
                        labelText: 'Mutex 그룹 (선택)',
                        helperText: '좁은 통로를 동시에 한 대만 사용하게 할 그룹명',
                        border: OutlineInputBorder(),
                      ),
                    ),
                  ],
                ),
              ),
              actions: [
                TextButton(
                  onPressed: () => Navigator.pop(dialogContext),
                  child: const Text('취소'),
                ),
                TextButton.icon(
                  onPressed: () => Navigator.pop(dialogContext, (
                    action: 'delete',
                    direction: selectedDirection,
                    speed: null,
                    orientation: selectedOrientation,
                    mutex: mutexController.text.trim(),
                  )),
                  icon: const Icon(Icons.delete_outline),
                  label: const Text('레인 삭제'),
                  style: TextButton.styleFrom(
                    foregroundColor: const Color(0xFFDC2626),
                  ),
                ),
                FilledButton(
                  onPressed: () {
                    final speedText = speedController.text.trim();
                    final speed = speedText.isEmpty
                        ? null
                        : double.tryParse(speedText);
                    if (speedText.isNotEmpty && (speed == null || speed <= 0)) {
                      return;
                    }
                    Navigator.pop(dialogContext, (
                      action: 'save',
                      direction: selectedDirection,
                      speed: speed,
                      orientation: selectedOrientation,
                      mutex: mutexController.text.trim(),
                    ));
                  },
                  child: const Text('Lane 설정 저장'),
                ),
              ],
            ),
          ),
        );
    speedController.dispose();
    mutexController.dispose();
    if (result == null || !mounted) return;
    final index = _recommendedLanes.indexWhere(
      (candidate) =>
          (candidate.$1 - lane.$1).distance <= .01 &&
          (candidate.$2 - lane.$2).distance <= .01,
    );
    if (index < 0) return;
    _recordUndo();
    setState(() {
      if (result.action == 'delete') {
        final removed = _recommendedLanes.removeAt(index);
        _removeLaneProperties(removed);
      } else {
        final target = _recommendedLanes[index];
        _laneDirections[target] = result.direction;
        if (result.speed == null) {
          _laneSpeedLimits.remove(target);
        } else {
          _laneSpeedLimits[target] = result.speed!;
        }
        if (result.orientation == '제약 없음') {
          _laneOrientations.remove(target);
        } else {
          _laneOrientations[target] = result.orientation;
        }
        if (result.mutex.isEmpty) {
          _laneMutexGroups.remove(target);
        } else {
          _laneMutexGroups[target] = result.mutex;
        }
      }
      _isDeployed = false;
    });
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          result.action == 'delete'
              ? '선택한 레인을 삭제했습니다.'
              : '${result.direction}과 Open-RMF Lane 속성을 저장했습니다.',
        ),
      ),
    );
  }

  Future<void> _addLaneWaypoint(Offset rawPoint) async {
    var point = rawPoint;
    final drawing = _drawing;
    final snapTolerance =
        drawing?.pixelWidth != null && drawing?.pixelHeight != null
        ? math.min(drawing!.pixelWidth!, drawing.pixelHeight!) * .02
        : 16.0;
    Offset? snappedWaypoint;
    var nearestDistance = snapTolerance;
    for (final waypoint in _laneWaypoints) {
      final distance = (waypoint - point).distance;
      if (distance <= nearestDistance) {
        snappedWaypoint = waypoint;
        nearestDistance = distance;
      }
    }
    if (snappedWaypoint != null) {
      final snapped = snappedWaypoint;
      final start = _activeLaneEndpoint;
      // 시작점이 정해져 있고 다른 Waypoint를 찍었다면 그건 끝점이다. 무엇을
      // 할지 되묻지 않고 바로 잇는다 — 레인을 그리는 중에 원하는 동작은 그것
      // 하나뿐이다. 삭제처럼 다른 일을 하려면 Esc로 레인을 끝낸 뒤 누른다.
      if (start == null || (start - snapped).distance <= .01) {
        final action = await _chooseWaypointAction(snapped);
        if (!mounted || action == null) return;
        if (action == 'delete') {
          await _confirmDeleteWaypoint(snapped);
          return;
        }
        _recordUndo();
        setState(() {
          _activeLaneEndpoint = snapped;
          _stage = MapStage.lanes;
        });
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text(
              '이 Waypoint를 레인 시작점으로 잡았습니다. 다음 Waypoint를 찍으면 이어집니다.',
            ),
          ),
        );
        return;
      }
      final crossed = _firstCrossedWaypoint(start, snapped, snapTolerance);
      final laneStart = crossed ?? start;
      // Lane을 잇지 못해도 사용자가 고른 지점은 새 시작점으로 삼는다. 예전에는
      // 여기서 그냥 되돌아가 클릭이 통째로 무시된 것처럼 보였다.
      final laneIssue = _laneCreationIssue(laneStart, snapped);
      _recordUndo();
      setState(() {
        if (laneIssue == null) {
          final lane = (laneStart, snapped);
          _recommendedLanes.add(lane);
          _laneDirections[lane] = '양방향';
        }
        // 이어 그릴 수 있도록 방금 찍은 지점이 다음 구간의 시작점이 된다.
        _activeLaneEndpoint = snapped;
        _stage = MapStage.lanes;
        _isDeployed = false;
      });
      if (laneIssue != null) {
        _showLaneCreationIssue('$laneIssue 이 지점을 새 레인 시작점으로 잡았습니다.');
        return;
      }
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            crossed != null
                ? '중간 Waypoint를 통과하여 해당 지점부터 레인을 연결했습니다.'
                : '기존 Waypoint까지 레인을 연결했습니다.',
          ),
        ),
      );
      return;
    }
    // 기존 Waypoint에 붙지 않았다면, 레인 위에 얹으려는 것인지 본다. Waypoint
    // 끼리는 예전부터 스냅됐지만 레인에는 붙지 않아서, 선 위에 놓은 지점이
    // 연결되지 않은 채 남았다.
    final laneSnap = _snapToLane(point, snapTolerance);
    final snappedToLane = laneSnap != null;
    if (laneSnap != null) point = laneSnap;
    final floorPoint = _floorCoordinate(point);
    final activeEndpoint = _activeLaneEndpoint;
    final crossedWaypoint = activeEndpoint == null
        ? null
        : _firstCrossedWaypoint(activeEndpoint, point, snapTolerance);
    var selectedType = '주차';
    final nameController = TextEditingController(
      text: _nextWaypointName(selectedType),
    );
    final confirmed = await showMovableDialog<bool>(
      context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (context, setDialogState) => AlertDialog(
          title: const Text('Waypoint 추가'),
          content: SizedBox(
            width: 360,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '좌표  X ${floorPoint.dx.toStringAsFixed(1)}  ·  Y ${floorPoint.dy.toStringAsFixed(1)}'
                  '${snappedToLane ? '  ·  레인 위에 스냅 (레인을 이 지점에서 나눠 잇습니다)' : ''}',
                  style: const TextStyle(
                    color: Color(0xFF475569),
                    fontWeight: FontWeight.w600,
                  ),
                ),
                const SizedBox(height: 18),
                TextField(
                  controller: nameController,
                  decoration: InputDecoration(
                    labelText: 'Waypoint 이름',
                    hintText: selectedType == '대기' ? '(이름 없음)' : null,
                    helperText: '유형에 맞는 이름을 자동 제안합니다. 원하는 이름으로 수정할 수 있습니다.',
                    helperMaxLines: 2,
                    errorText:
                        nameController.text.trim().isNotEmpty &&
                            _waypointNames.values.any(
                              (name) =>
                                  name.trim() == nameController.text.trim(),
                            )
                        ? '이미 사용 중인 Waypoint 이름입니다.'
                        : null,
                    border: OutlineInputBorder(),
                  ),
                  onChanged: (_) => setDialogState(() {}),
                ),
                const SizedBox(height: 14),
                DropdownButtonFormField<String>(
                  initialValue: selectedType,
                  decoration: const InputDecoration(
                    labelText: 'Waypoint 카테고리',
                    border: OutlineInputBorder(),
                  ),
                  items: const ['대기', '주차', '홈', '충전', '픽업', '드랍오프', '설비']
                      .map(
                        (type) =>
                            DropdownMenuItem(value: type, child: Text(type)),
                      )
                      .toList(),
                  onChanged: (value) {
                    if (value != null) {
                      setDialogState(() {
                        selectedType = value;
                        nameController.text = _nextWaypointName(value);
                      });
                    }
                  },
                ),
                const SizedBox(height: 10),
                Text(
                  _waypointTypeDescription(selectedType),
                  style: const TextStyle(
                    color: Color(0xFF64748B),
                    fontSize: 12,
                  ),
                ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext, false),
              child: const Text('취소'),
            ),
            FilledButton(
              onPressed:
                  (selectedType != '대기' &&
                          nameController.text.trim().isEmpty) ||
                      (nameController.text.trim().isNotEmpty &&
                          _waypointNames.values.any(
                            (name) => name.trim() == nameController.text.trim(),
                          ))
                  ? null
                  : () => Navigator.pop(dialogContext, true),
              child: const Text('추가'),
            ),
          ],
        ),
      ),
    );
    final enteredName = nameController.text.trim();
    final waypointName = enteredName.isEmpty ? ' ' : enteredName;
    nameController.dispose();
    if (confirmed != true || !mounted) return;
    final laneStart = selectedType == '설비'
        ? null
        : crossedWaypoint ?? _activeLaneEndpoint;
    // Lane을 잇지 못하는 것과 Waypoint를 못 놓는 것은 다른 일이다. 예전에는
    // 여기서 되돌아가 Waypoint까지 버렸고, 그래서 스낵바를 놓치면 클릭이 그냥
    // 먹히지 않는 것처럼 보였다.
    final laneIssue = laneStart == null
        ? null
        : _laneCreationIssue(laneStart, point);
    _recordUndo();
    var splicedLanes = 0;
    setState(() {
      if (laneStart != null && laneIssue == null) {
        final lane = (laneStart, point);
        _recommendedLanes.add(lane);
        _laneDirections[lane] = '양방향';
      }
      _laneWaypoints.add(point);
      _waypointTypes[point] = selectedType;
      _waypointNames[point] = waypointName;
      // 설비는 이동 Lane에 끼우지 않는다. 나머지는 얹혀 있는 레인을 이 지점에서
      // 나눠 이어 로봇이 지나갈 수 있게 한다.
      if (selectedType != '설비') {
        splicedLanes = _spliceWaypointIntoLanes(point, snapTolerance);
      }
      _activeLaneEndpoint = selectedType == '설비' ? null : point;
      _stage = MapStage.lanes;
      _isDeployed = false;
      _vertexLabelRevision++;
    });
    if (splicedLanes > 0) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('레인 $splicedLanes개를 이 Waypoint에서 나눠 이었습니다.')),
      );
    }
    if (laneIssue != null) {
      _showLaneCreationIssue('Waypoint는 추가했지만 Lane은 잇지 못했습니다. $laneIssue');
      return;
    }
    if (crossedWaypoint != null) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('통과한 Waypoint부터 새 레인을 시작했습니다.')),
      );
    }
  }

  /// 지도 픽셀을 RMF 월드 좌표(m)로 옮긴다.
  ///
  /// RMF 지도 생성기는 building.yaml 에 적힌 픽셀을 그대로
  /// `(px × 축척, −py × 축척)` 으로 옮긴다. 원점은 **그림의 왼쪽 위**이고 y 는
  /// 위로 갈수록 커진다. 그래서 Gazebo 월드도 nav graph 도 이 좌표를 쓴다.
  ///
  /// 사람에게 보여 주는 [_floorCoordinate] 와는 다르다. 그쪽은 바닥 왼쪽
  /// **아래**가 원점이라 읽기 좋지만, 그 값을 그대로 spawn 좌표로 쓰면 로봇이
  /// 바닥 밖에 놓인다 — y 부호가 반대라서 건물 바깥 허공에 떨어진다.
  Offset? _rmfMetersFromPixel(Offset point) {
    final scale = _metersPerPixel;
    if (scale == null || scale <= 0) return null;
    final world = rmfWorldFromPixel(point.dx, point.dy, scale);
    return Offset(world.x, world.y);
  }

  /// RMF 월드 좌표(m)를 지도 픽셀로 되돌린다. [_rmfMetersFromPixel] 의 역이다.
  ///
  /// 토픽은 미터로 오고 화면은 픽셀로 그린다.
  Offset? _pixelFromMeters(double xMeters, double yMeters) {
    final scale = _metersPerPixel;
    if (scale == null || scale <= 0) return null;
    final pixel = pixelFromRmfWorld(xMeters, yMeters, scale);
    return Offset(pixel.dx, pixel.dy);
  }

  /// 등록된 로봇의 올릴 자리를 지금 지도에서 다시 계산한다.
  ///
  /// spawn 좌표는 언제나 자리 Waypoint 에서 나온다. 예전 판은 화면에 보여 주는
  /// 바닥 좌표를 그대로 넣었고, 그 좌표는 원점도 y 방향도 RMF 와 달랐다. 그렇게
  /// 저장된 프로젝트는 로봇을 건물 밖 허공에 올려서 끝없이 떨어뜨린다. 사람에게
  /// 다시 등록하라고 시키는 대신 여기서 고쳐 준다.
  ///
  /// 자리를 못 찾은 로봇은 그대로 둔다 — 지도가 아직 안 올라왔을 수 있고, 그때
  /// 지워 버리면 멀쩡한 등록이 좌표를 잃는다.
  List<RmfProjectRobot> _withMapSpawnPoints(List<RmfProjectRobot> robots) {
    final scale = _metersPerPixel;
    if (scale == null) return robots;
    return robotsWithMapSpawnPoints(robots, (robot) {
      final station = _stationPixelFor(robot);
      return station == null ? null : (dx: station.dx, dy: station.dy);
    }, scale);
  }

  /// 로봇이 선 자리 Waypoint 의 지도 픽셀.
  ///
  /// 자리는 종류에 맞는 카테고리에서만 찾는다. 이동 로봇이 설비 자리를, 설치
  /// 로봇이 충전 자리를 잡으면 실행에서 어긋난다.
  Offset? _stationPixelFor(RmfProjectRobot robot) {
    final station = robot.chargerWaypoint?.trim();
    if (station == null || station.isEmpty) return null;
    final types = _waypointTypes.isNotEmpty
        ? _waypointTypes
        : (_robotDeployedMap?.waypointCategories ?? const <Offset, String>{});
    final names = _waypointTypes.isNotEmpty
        ? _waypointNames
        : (_robotDeployedMap?.waypointNames ?? const <Offset, String>{});
    return types.entries
        .where(
          (entry) =>
              entry.value == robot.kind.waypointCategory &&
              (names[entry.key] ?? '').trim() == station,
        )
        .map((entry) => entry.key)
        .firstOrNull;
  }

  /// 등록된 로봇의 자리가 지도와 맞는지 살핀다.
  List<SpawnCheck> get _spawnChecks => checkRobotSpawns(
    robots: _fleetRobots,
    pixelOf: (robot) {
      final station = _stationPixelFor(robot);
      return station == null ? null : (dx: station.dx, dy: station.dy);
    },
    insideFloor: (dx, dy) => _isInsideFloor(Offset(dx, dy)),
    metersPerPixel: _metersPerPixel,
  );

  /// 바닥이 있는 범위. RMF 월드 좌표(m).
  ///
  /// 자리가 이 밖이면 이동 로봇은 올라가자마자 허공에서 떨어진다.
  ({double minX, double maxX, double minY, double maxY})? get _floorBounds {
    final points = _floorMask?.points;
    final scale = _metersPerPixel;
    if (points == null || points.isEmpty || scale == null || scale <= 0) {
      return null;
    }
    final pixels = _pointsBounds(points);
    // y 는 뒤집히므로 아래쪽 픽셀이 더 작은 미터가 된다.
    final topLeft = rmfWorldFromPixel(pixels.left, pixels.top, scale);
    final bottomRight = rmfWorldFromPixel(pixels.right, pixels.bottom, scale);
    return (
      minX: topLeft.x,
      maxX: bottomRight.x,
      minY: bottomRight.y,
      maxY: topLeft.y,
    );
  }

  /// 벤더 Nav2 파라미터를 이동 로봇마다 다시 쓴다. 로봇 ID → 내용.
  ///
  /// 벤더 파일은 로봇 한 대를 전제로 쓰였다. 두 대를 같은 월드에 올리면 서로의
  /// 라이다를 보고 TF 가 충돌한다. 벤더 파일은 **고치지 않고** 읽어서 로봇마다
  /// 다시 쓴다.
  ///
  /// 바꾼 것과 손대지 못한 것은 [_nav2Warnings] 에 남는다. 벤더 파일이 바뀌면
  /// 여기 걸리므로 조용히 어긋나지 않는다.
  ({Map<String, String> params, List<String> warnings})
  _rewriteNav2ParamsForRobots() {
    final source = readVendorNav2Params();
    final navigating = _fleetRobots.where(
      (robot) => robot.isMobile && robot.runsInGazebo,
    );
    if (source == null) {
      return (
        params: const {},
        warnings: navigating.isEmpty
            ? const []
            : [
                '벤더 Nav2 파라미터를 찾지 못해 로봇별 nav2_params.yaml 을 '
                    '만들지 못했습니다. $nav2ParamsEnvironmentKey 환경 변수로 '
                    '자리를 알려 주세요.',
              ],
      );
    }
    final params = <String, String>{};
    final warnings = <String>[];
    for (final robot in navigating) {
      final rewritten = rewriteNav2Params(
        source: source,
        goalTolerance: _goalTolerance,
        namespace: robot.gzName,
        // AMCL 이 처음 찍는 자리. 로봇을 올린 자리를 그대로 쓴다.
        initialX: robot.spawnX,
        initialY: robot.spawnY,
        initialYaw: robot.spawnHeading,
        // 로봇을 실제로 움직이는 속도. RMF 쪽 한계와 같은 값을 넣는다 —
        // 벤더 파일(0.2m/s)에 맡겨 두면 RMF 가 아는 속도와 어긋나, 멀쩡히
        // 가는 로봇을 늦었다고 보고 경로를 다시 짠다.
        linearVelocity: _fleetSettings.linearVelocity,
      );
      params[robot.robotId] = rewritten.yaml;
      for (final warning in rewritten.warnings) {
        warnings.add('${robot.robotId}: $warning');
      }
    }
    return (params: params, warnings: warnings);
  }

  /// Nav2 가 쓸 점유격자를 지금 도면에서 만든다.
  ///
  /// RMF 는 nav graph 만으로 길을 찾으므로 이 격자가 필요 없다. 필요한 것은
  /// **로봇 쪽**이다 — AMCL 이 라이다로 제 위치를 잡고 Nav2 가 장애물을 피할 때
  /// 쓴다. building.yaml 에 나가는 것과 **같은 원본**(바닥 다각형과 벽 선분)을
  /// 쓰므로 Gazebo 에서 라이다가 보는 벽과 격자의 벽이 어긋나지 않는다.
  OccupancyGrid? _buildOccupancyGrid() {
    final scale = _metersPerPixel;
    if (scale == null || scale <= 0) return null;
    GridPoint toWorld(Offset point) {
      final world = rmfWorldFromPixel(point.dx, point.dy, scale);
      return (x: world.x, y: world.y);
    }

    final padToTarget =
        _gridResolutionMode == _GridResolutionMode.target && _gridPadToTarget;
    return buildOccupancyGrid(
      floorOutline: [for (final point in _floorOutline()) toWorld(point)],
      walls: [
        for (final wall in _visibleWallSegments())
          (toWorld(wall.$1), toWorld(wall.$2)),
      ],
      resolution: _occupancyResolution(),
      // 정사각 칸을 지키면 건물 비율 때문에 상자를 꽉 채울 수 없다. 800×600
      // 이라는 숫자를 그대로 얻으려면 남는 쪽을 `모름` 으로 채운다.
      padToWidth: padToTarget ? _gridTargetWidth : null,
      padToHeight: padToTarget ? _gridTargetHeight : null,
    );
  }

  /// 격자가 덮을 범위(m). 바닥 바깥 여백까지 더한 값이다.
  ///
  /// `buildOccupancyGrid` 이 같은 여백을 붙이므로 여기서도 같이 붙여야 상자에
  /// 맞춘 칸 수가 실제와 맞는다.
  ({double width, double height})? _occupancyExtent() {
    final bounds = _floorBounds;
    if (bounds == null) return null;
    final scale = _metersPerPixel;
    if (scale == null || scale <= 0) return null;
    // 벽은 선분 한가운데를 지나므로 두께의 절반이 바깥으로 나간다.
    const pad = .5 + rmfWallThickness / 2;
    return (
      width: (bounds.maxX - bounds.minX) + 2 * pad,
      height: (bounds.maxY - bounds.minY) + 2 * pad,
    );
  }

  double _occupancyResolution() {
    final bounds = _floorBounds;
    switch (_gridResolutionMode) {
      case _GridResolutionMode.manual:
        // 0 이면 격자를 못 만든다. 사람이 지우다 만 값을 그대로 쓰지 않는다.
        return _gridManualResolution > 0 ? _gridManualResolution : .02;
      case _GridResolutionMode.target:
        final extent = _occupancyExtent();
        if (extent == null) break; // 바닥이 없으면 자동으로 떨어진다
        final byTarget = occupancyResolutionForTarget(
          widthMeters: extent.width,
          heightMeters: extent.height,
          targetWidth: _gridTargetWidth,
          targetHeight: _gridTargetHeight,
        );
        if (byTarget > 0) return byTarget;
      case _GridResolutionMode.auto:
        break;
    }
    return occupancyResolutionFor(
      robotWidth: _robotWidthMeters,
      floorShorterSide: bounds == null
          ? null
          : math.min(bounds.maxX - bounds.minX, bounds.maxY - bounds.minY),
    );
  }

  /// 격자를 화면에 보여 줄 그림으로 만든다.
  ///
  /// 셀 값이 그대로 회색조다 — 벽 0(검정), 바닥 254(흰), 모름 205(회색). 그래서
  /// 값 하나를 R·G·B 에 그대로 넣으면 `map_server` 가 읽는 PGM 과 같은 그림이
  /// 된다. 사람이 보는 것과 로봇이 보는 것이 어긋나면 안 된다.
  Future<ui.Image> _occupancyGridImage(OccupancyGrid grid) {
    final rgba = Uint8List(grid.width * grid.height * 4);
    for (var i = 0; i < grid.cells.length; i++) {
      final value = grid.cells[i];
      final at = i * 4;
      rgba[at] = value;
      rgba[at + 1] = value;
      rgba[at + 2] = value;
      rgba[at + 3] = 0xFF;
    }
    final completer = Completer<ui.Image>();
    ui.decodeImageFromPixels(
      rgba,
      grid.width,
      grid.height,
      ui.PixelFormat.rgba8888,
      completer.complete,
    );
    return completer.future;
  }

  /// 만든 격자를 맵 디렉터리에 쓴다. 조용히 한다.
  ///
  /// 도면에서 파생되는 산출물이라 `.world` 처럼 프로젝트를 내보낼 때마다 다시
  /// 만든다. 실패해도 하려던 일(띄우기·내리기)은 계속한다.
  ///
  /// [prebuilt] 를 주면 격자를 다시 만들지 않는다. 그리드맵 화면은 만든 격자를
  /// 그림으로도 보여 주므로, 같은 것을 두 번 굽지 않기 위해서다.
  Future<OccupancyGridExportResult?> _exportOccupancyGrid(
    String mapName, {
    OccupancyGrid? prebuilt,
  }) async {
    final grid = prebuilt ?? _buildOccupancyGrid();
    if (grid == null) {
      // 축척이 없으면 격자를 만들 수 없다. 예전에는 여기서 조용히 돌아섰는데,
      // 그러면 nav2_map 이 없는 채로 배포가 끝난다. 그 결과가 한참 뒤에
      // 엉뚱한 얼굴로 나타났다 — map_server 가 unconfigured 로 멈추고, AMCL 이
      // "Waiting for map" 만 되풀이하고, 위치를 모르니 fleet adapter 가 로봇을
      // 등록하지 못해, 결국 "RMF 가 답하지 않습니다" 로 보였다.
      return const OccupancyGridExportResult(
        success: false,
        directory: '',
        written: [],
        message:
            '축척이 없어 Nav2 지도를 만들지 못했습니다. '
            '맵의 로봇 안전 기준에서 축척을 먼저 정하세요.',
      );
    }
    try {
      return await exportOccupancyGrid(
        mapName: mapName,
        grid: grid,
        note:
            'rmf_control_ui 가 $mapName 도면에서 만들었다. 손으로 고치면 다음 '
            '내보내기 때 덮어써진다.\n'
            '좌표는 RMF 월드 — 원점은 도면 왼쪽 위, 건물 안은 y 가 음수다.\n'
            '벽 두께는 RMF 와 같은 ${rmfWallThickness}m 다.',
      );
    } catch (error) {
      return OccupancyGridExportResult(
        success: false,
        directory: '',
        written: const [],
        message: 'Nav2 지도를 쓰지 못했습니다: $error',
      );
    }
  }

  /// 그리드맵 화면이 건드리는 값 한 벌.
  GridMapSettings get _currentGridSettings => GridMapSettings(
    mode: _gridResolutionMode.name,
    targetWidth: _gridTargetWidth,
    targetHeight: _gridTargetHeight,
    padToTarget: _gridPadToTarget,
    manualResolution: _gridManualResolution,
    useSlamMap: _useSlamMap,
  );

  /// 그리드맵 화면에서 아직 저장 안 한 것들. 없으면 빈 목록.
  List<String> get _gridSettingChanges => gridSettingChanges(
    saved: _savedGridSettings,
    current: _currentGridSettings,
  );

  /// 그리드맵 설정을 열린 프로젝트에 바로 저장한다.
  ///
  /// 예전에는 이 화면에 저장하는 자리가 없어서, 격자 크기를 맞춰 놓고 다른
  /// 화면으로 옮겨 가 `프로젝트 저장` 을 눌러야 남았다. 그것을 모르면 프로젝트를
  /// 다시 열었을 때 옛 값으로 돌아가 있는데 아무 말도 없었다.
  Future<void> _saveGridSettings() async {
    final changes = _gridSettingChanges;
    if (changes.isEmpty) return;
    await _saveSettingToOpenProject(
      label: '그리드맵 설정',
      detail: changes.join(' · '),
    );
    if (!mounted) return;
    // 저장이 실패해도 여기까지 온다. 그때 기준을 옮기면 고친 것이 사라진 것으로
    // 보이므로, 프로젝트가 실제로 있을 때만 옮긴다.
    if (_openProjectName != null && _drawing != null) {
      setState(() => _savedGridSettings = _currentGridSettings);
    }
  }

  /// 지금 도면에서 Nav2 그리드맵(점유격자)을 만든다.
  ///
  /// 배포하기 안에도 같은 일이 들어 있다. 그런데도 따로 부를 수 있어야 하는
  /// 이유는, 이것만 없어도 로봇이 아예 못 움직이는데 그 사실이 화면에
  /// 드러나지 않기 때문이다. 지도가 없으면 `map_server` 가 unconfigured 에서
  /// 멈추고, AMCL 은 "Waiting for map" 만 되풀이하고, 위치를 모르니 fleet
  /// adapter 가 로봇을 등록하지 못한다. 그때 사람이 보는 말은 "RMF 가 답하지
  /// 않습니다. fleet adapter 가 떠 있는지 확인하세요" 라서 원인에서 네 단계
  /// 떨어져 있다. 도면을 고친 뒤 이 단추 하나로 지도만 다시 만들 수 있어야
  /// 한다.
  Future<void> _generateGridMap() async {
    final project = _openProjectName;
    if (project == null) {
      await showWaypointErrorDialog(
        context,
        title: '그리드맵 작성',
        message:
            '열린 맵 프로젝트가 없습니다.\n\n'
            '그리드맵은 도면에서 만들어지므로 맵 프로젝트가 있어야 합니다. '
            '맵 관리에서 `프로젝트 열기` 로 불러오거나 `프로젝트 저장` 으로 '
            '먼저 등록하세요.',
      );
      return;
    }
    if (_isGeneratingGrid) return;
    setState(() {
      _isGeneratingGrid = true;
      // 이전 그림은 지운다. 남겨 두면 새로 굽는 동안 옛 지도를 보며
      // 다 됐다고 여긴다.
      _gridPreview?.dispose();
      _gridPreview = null;
      _gridPreviewGrid = null;
      _gridPreviewDirectory = null;
      _gridPreviewSavedAt = null;
    });
    // 격자 굽기는 UI 스레드에서 돈다. 한 프레임 내주지 않으면 `작성 중` 커서와
    // 글자가 그려지기 전에 화면이 멈춰 버려, 정작 기다리는 동안 아무 표시가
    // 없다.
    await WidgetsBinding.instance.endOfFrame;
    if (!mounted) return;

    OccupancyGridExportResult? result;
    OccupancyGrid? grid;
    ui.Image? image;
    try {
      grid = _buildOccupancyGrid();
      result = await _exportOccupancyGrid(project, prebuilt: grid);
      if (grid != null && result != null && result.success) {
        image = await _occupancyGridImage(grid);
      }
    } finally {
      if (mounted) {
        setState(() {
          _isGeneratingGrid = false;
          _gridPreview = image;
          _gridPreviewGrid = image == null ? null : grid;
          _gridPreviewDirectory = image == null ? null : result?.directory;
          // 방금 구운 것이다. 저장된 것을 올린 때와 구분한다.
          _gridPreviewSavedAt = null;
        });
      } else {
        image?.dispose();
      }
    }
    if (!mounted) return;
    if (result == null || !result.success) {
      await showWaypointErrorDialog(
        context,
        title: '그리드맵 작성 실패',
        message:
            '${result?.message ?? '그리드맵을 만들지 못했습니다.'}\n\n'
            '이 지도가 없으면 map_server 가 뜨지 못하고, AMCL 이 위치를 잡지 '
            '못해 로봇이 배차를 받지 못합니다.',
      );
      return;
    }
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          '그리드맵을 만들었습니다 · ${result.written.join(', ')}\n'
          '${result.directory}',
        ),
        duration: const Duration(seconds: 6),
        showCloseIcon: true,
      ),
    );
  }

  /// 회색조 셀을 화면에 보여 줄 그림으로 만든다.
  Future<ui.Image> _grayCellsImage(Uint8List cells, int width, int height) {
    final rgba = Uint8List(width * height * 4);
    for (var i = 0; i < cells.length; i++) {
      final value = cells[i];
      final at = i * 4;
      rgba[at] = value;
      rgba[at + 1] = value;
      rgba[at + 2] = value;
      rgba[at + 3] = 0xFF;
    }
    final completer = Completer<ui.Image>();
    ui.decodeImageFromPixels(
      rgba,
      width,
      height,
      ui.PixelFormat.rgba8888,
      completer.complete,
    );
    return completer.future;
  }

  /// 이 프로젝트에 구워 둔 그리드맵을 읽어 화면에 올린다.
  ///
  /// 격자는 `rmf_maps/<맵>/nav2_map/` 에 파일로 남아 있다. 그것을 다시 읽어
  /// 올리므로, 프로젝트를 열면 지난번에 만든 지도가 그대로 보인다. 없으면
  /// 조용히 지나간다 — 아직 안 만든 프로젝트가 정상이다.
  Future<void> _loadStoredGrid(String mapName) async {
    // 굽는 중이면 손대지 않는다. 다 구운 그림을 옛 파일로 덮으면 방금 한 일이
    // 없던 것이 된다.
    if (_isGeneratingGrid) return;
    final stored = await loadStoredOccupancyGrid(mapName);
    if (stored == null || !mounted) return;
    // 여는 사이에 다른 프로젝트로 넘어갔거나 사람이 새로 구웠으면 버린다.
    if (_openProjectName != mapName || _isGeneratingGrid) return;
    final image = await _occupancyGridImage(stored.grid);
    if (!mounted || _openProjectName != mapName || _isGeneratingGrid) {
      image.dispose();
      return;
    }
    setState(() {
      _gridPreview?.dispose();
      _gridPreview = image;
      _gridPreviewGrid = stored.grid;
      _gridPreviewDirectory = stored.directory;
      _gridPreviewSavedAt = stored.savedAt;
    });
  }

  /// 이 프로젝트에 넣어 둔 SLAM 지도를 읽어 화면에 올린다.
  Future<void> _loadStoredSlam(String mapName) async {
    final stored = await loadStoredSlamMap(mapName);
    if (!mounted) return;
    if (stored == null) {
      setState(() {
        _slamPreview?.dispose();
        _slamPreview = null;
        _slamMap = null;
      });
      return;
    }
    final image = await _grayCellsImage(
      stored.cells,
      stored.width,
      stored.height,
    );
    if (!mounted) {
      image.dispose();
      return;
    }
    setState(() {
      _slamPreview?.dispose();
      _slamPreview = image;
      _slamMap = stored;
    });
  }

  /// 로봇이 SLAM 으로 뜬 지도를 골라 이 프로젝트에 넣는다.
  ///
  /// `map_saver` 는 `.yaml` 과 `.pgm` 을 함께 낸다. yaml 을 고르게 하고 그 옆의
  /// 그림을 따라간다 — 사람이 둘을 각각 고르게 하면 짝이 안 맞는 조합이 들어온다.
  ///
  /// **원점은 여기서 손대지 않는다.** 올린 그대로 넣고, 화면에서 도면 격자와
  /// 겹쳐 보며 맞추게 한다. SLAM 지도의 원점은 로봇이 SLAM 을 시작한 자리여서
  /// RMF 원점과 아무 관계가 없다.
  Future<void> _uploadSlamMap() async {
    final project = _openProjectName;
    if (project == null) {
      await showWaypointErrorDialog(
        context,
        title: 'SLAM 지도 올리기',
        message:
            '열린 맵 프로젝트가 없습니다.\n\n'
            'SLAM 지도는 프로젝트에 딸립니다. `새 프로젝트` 로 만들거나 '
            '`프로젝트 열기` 로 먼저 여세요.',
      );
      return;
    }
    if (_isReadingSlamMap) return;
    final picked = await FilePicker.platform.pickFiles(
      dialogTitle: '① .yaml 을 먼저 고르세요 — .pgm 은 따라 읽습니다',
      type: FileType.custom,
      allowedExtensions: const ['yaml', 'yml'],
    );
    final path = picked?.files.singleOrNull?.path;
    if (path == null || !mounted) return;

    // 확장자를 한 번 더 본다. 걸러 두었어도 플랫폼에 따라 다른 파일이 넘어오는
    // 경우가 있고, 그때 `.pgm` 을 골랐다면 원인을 짚어 줘야 한다 — 그냥
    // `읽지 못했습니다` 로 끝나면 무엇을 잘못했는지 알 수 없다.
    final lower = path.toLowerCase();
    if (!lower.endsWith('.yaml') && !lower.endsWith('.yml')) {
      await showWaypointErrorDialog(
        context,
        title: '.yaml 을 먼저 고르세요',
        message:
            '고른 파일: ${path.split(RegExp(r'[/\\]')).last}\n\n'
            '`map_saver` 는 yaml 과 그림(`.pgm` 또는 `.png`)을 함께 냅니다. '
            '**`.yaml` 을 고르면 그림은 앱이 따라 읽습니다.** '
            '그림만 골라서는 한 칸이 몇 미터인지, 원점이 어디인지 알 수 '
            '없어 지도를 앉힐 수 없습니다.\n\n'
            '두 파일은 같은 디렉터리에 함께 두세요.',
      );
      return;
    }

    setState(() => _isReadingSlamMap = true);
    try {
      final read = await readSlamMapFrom(path);
      if (!mounted) return;
      final map = read.map;
      if (!read.success || map == null) {
        await showWaypointErrorDialog(
          context,
          title: 'SLAM 지도를 읽지 못했습니다',
          message: read.message,
        );
        return;
      }
      final written = await writeSlamMap(
        mapName: project,
        map: map,
        note:
            'rmf_control_ui 가 넣은 SLAM 지도. 로봇이 뜬 것이다.\n'
            '원점은 아직 SLAM 을 시작한 자리 기준이다 — 그리드맵 화면에서 '
            'RMF 월드에 맞춰야 한다.',
      );
      if (!mounted) return;
      if (!written.success) {
        await showWaypointErrorDialog(
          context,
          title: 'SLAM 지도를 넣지 못했습니다',
          message: written.message,
        );
        return;
      }
      await _loadStoredSlam(project);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            'SLAM 지도를 넣었습니다 · ${written.written.join(', ')}\n'
            '원점을 RMF 월드에 맞춰 주세요.',
          ),
          duration: const Duration(seconds: 6),
          showCloseIcon: true,
        ),
      );
    } finally {
      if (mounted) setState(() => _isReadingSlamMap = false);
    }
  }

  /// 도면 축척을 SLAM 지도로 견준 결과. 둘 중 하나가 없으면 null.
  ///
  /// 도면의 축척은 사람이 두 점 사이 실제 거리를 재서 넣은 값이라 오차가 있다.
  /// SLAM 은 로봇이 실제로 굴러 잰 값이라 그걸로 검증할 수 있다. 축척이 틀리면
  /// building.yaml · nav graph · 격자 · Gazebo 메시가 한꺼번에 틀어진다.
  WallExtentComparison? _slamScaleComparison() {
    final slam = _slamMap;
    final grid = _gridPreviewGrid;
    if (slam == null || grid == null) return null;
    return compareWallExtents(
      drawing: occupiedExtent(
        cells: grid.cells,
        width: grid.width,
        height: grid.height,
        resolution: grid.resolution,
        occupiedThreshold: OccupancyGrid.occupiedThreshold,
      ),
      slam: occupiedExtent(
        cells: slam.cells,
        width: slam.width,
        height: slam.height,
        resolution: slam.resolution,
        occupiedThreshold: slam.occupiedThreshold,
        negate: slam.negate,
      ),
    );
  }

  /// 견준 비를 도면 축척에 넣는다.
  ///
  /// 축척은 `meters / pixels` 이므로 measurement 의 길이에 비를 곱하면 축척도
  /// 같은 비로 바뀐다. Waypoint 는 픽셀로 저장돼 있어 **다시 찍을 필요가 없다** —
  /// 월드 좌표가 자동으로 다시 계산된다.
  Future<void> _applySlamScale(double ratio) async {
    final measurement = _measurement;
    if (measurement == null || ratio <= 0) return;
    final before = _metersPerPixel;
    final ok = await showMovableDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        icon: const Icon(Icons.straighten, size: 32),
        title: const Text('도면 축척을 보정할까요'),
        content: SizedBox(
          width: 460,
          child: SelectableText(
            '축척을 ${((ratio - 1) * 100).toStringAsFixed(2)}% '
            '${ratio > 1 ? '키웁니다' : '줄입니다'}.\n\n'
            '지금  ${before?.toStringAsFixed(8) ?? '-'} m/px\n'
            '뒤    ${((before ?? 0) * ratio).toStringAsFixed(8)} m/px\n\n'
            '이 값에서 building.yaml · nav graph · 그리드맵 · Gazebo 월드가 '
            '전부 다시 나옵니다. Waypoint 는 픽셀로 저장돼 있어 다시 찍지 '
            '않아도 됩니다 — 월드 좌표만 다시 계산됩니다.\n\n'
            '보정한 뒤 그리드맵을 다시 만들고 배포하세요. 이미 배포된 지도와 '
            '떠 있는 로봇은 예전 축척을 쓰고 있습니다.',
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('취소'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(dialogContext, true),
            child: const Text('축척 보정'),
          ),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    _recordUndo();
    setState(() {
      _measurement = _MapMeasurement(
        start: measurement.start,
        end: measurement.end,
        length: measurement.length * ratio,
        unit: measurement.unit,
      );
      // 축척이 바뀌면 격자도 다시 만들어야 한다. 예전 그림을 남겨 두면
      // 보정이 반영된 것으로 오해한다.
      _gridPreview?.dispose();
      _gridPreview = null;
      _gridPreviewGrid = null;
      _gridPreviewDirectory = null;
      _gridPreviewSavedAt = null;
    });
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          '축척을 ${_metersPerPixel?.toStringAsFixed(8)} m/px 로 보정했습니다. '
          '그리드맵을 다시 만드세요.',
        ),
        duration: const Duration(seconds: 6),
        showCloseIcon: true,
      ),
    );
  }

  /// 사람이 맞춘 원점을 SLAM 지도 yaml 에 쓴다.
  Future<void> _saveSlamOrigin(double x, double y) async {
    final project = _openProjectName;
    final map = _slamMap;
    if (project == null || map == null) return;
    final written = await writeSlamMap(
      mapName: project,
      map: map.withOrigin(x, y),
      note:
          'rmf_control_ui 가 넣은 SLAM 지도. 원점을 사람이 RMF 월드에 맞췄다.\n'
          '틀리면 로봇이 `픽업1로 가라`는 명령을 받고 엉뚱한 데로 간다.',
    );
    if (!mounted) return;
    if (!written.success) {
      await showWaypointErrorDialog(
        context,
        title: '원점을 저장하지 못했습니다',
        message: written.message,
      );
      return;
    }
    await _loadStoredSlam(project);
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          '원점을 ${x.toStringAsFixed(6)}, ${y.toStringAsFixed(6)} 으로 '
          '맞췄습니다.',
        ),
      ),
    );
  }

  /// 자리 맞추기 창을 연다.
  Future<void> _showSpawnCheck() => showMovableDialog<void>(
    context: context,
    builder: (_) => _SpawnCheckDialog(
      checksOf: () => _spawnChecks,
      metersPerPixel: _metersPerPixel,
      floorBounds: _floorBounds,
      onRefit: _refitSpawnPoints,
      onHeading: _setSpawnHeading,
    ),
  );

  /// 등록된 자리를 지금 지도 기준으로 다시 맞춘다. 바뀐 대수를 돌려준다.
  Future<int> _refitSpawnPoints() async {
    final before = _fleetRobots;
    final after = _withMapSpawnPoints(before);
    if (identical(after, before)) return 0;
    var changed = 0;
    for (var i = 0; i < after.length; i++) {
      if (after[i].spawnX != before[i].spawnX ||
          after[i].spawnY != before[i].spawnY) {
        changed++;
      }
    }
    setState(() => _fleetRobots = after);
    await _syncTelemetry();
    await _saveSettingToOpenProject(
      label: '로봇 자리',
      detail: '$changed대의 자리를 지도 기준으로 맞췄습니다.',
    );
    return changed;
  }

  /// 로봇이 그 자리에서 볼 방향을 정한다.
  Future<void> _setSpawnHeading(RmfProjectRobot robot, double heading) async {
    final index = _fleetRobots.indexWhere(
      (item) => item.robotId == robot.robotId,
    );
    if (index < 0) return;
    final updated = [..._fleetRobots];
    updated[index] = robot.withSpawn(
      spawnX: robot.spawnX,
      spawnY: robot.spawnY,
      spawnHeading: heading,
    );
    setState(() => _fleetRobots = updated);
    await _syncTelemetry();
    await _saveSettingToOpenProject(
      label: '로봇 방향',
      detail:
          '${robot.robotId} 를 '
          '${(heading * 180 / math.pi).toStringAsFixed(0)}° 로 돌렸습니다.',
    );
  }

  /// 등록된 Gazebo 로봇의 위치 토픽을 구독한다.
  ///
  /// 등록이 바뀔 때마다 부른다. 이미 붙어 있는 것은 그대로 두므로 자주 불러도
  /// 값이 끊기지 않는다.
  StreamSubscription<Map<String, RobotSensors>>? _sensorSubscription;

  /// 어댑터가 내는 작업 진행 소식. RMF 가 모는 작업의 단계를 이것이 넘긴다.
  StreamSubscription<RmfTaskProgress>? _rmfProgressSubscription;

  Future<void> _syncTelemetry() async {
    _telemetrySubscription ??= RobotTelemetryBridge.instance.updates.listen((
      status,
    ) {
      if (!mounted) return;
      setState(() => _telemetry = status);
    });
    // 라이다는 relay 노드가 파일로 내려 준다. 볼 로봇만 지켜본다.
    RobotSensorFeed.instance.watch([
      for (final robot in _fleetRobots)
        if (robot.isMobile && robot.dataSource.usesTopics) robot.robotId,
    ]);
    _sensorSubscription ??= RobotSensorFeed.instance.updates.listen((_) {
      if (mounted) setState(() {});
    });
    // RMF 가 모는 작업의 단계는 어댑터가 알린다. 이것을 안 들으면 로봇은
    // 움직이는데 화면의 진행률이 첫 단계에 멈춰 있는다.
    _rmfProgressSubscription ??= RmfTaskBridge.instance.progress.listen(
      _handleRmfProgress,
    );
    if (_fleetRobots.any(
      (robot) => robot.isMobile && robot.dataSource.usesTopics,
    )) {
      final mapName = _robotDeployedMap?.summary.name ?? _mapName;
      if (mapName.trim().isNotEmpty) {
        await RmfTaskBridge.instance.watch(
          _fleetSettingsFor(mapName).fleetName,
        );
      }
    }
    try {
      await RobotTelemetryBridge.instance.sync(_fleetRobots);
    } catch (_) {
      // 토픽을 못 붙어도 앱은 계속 돌아야 한다. 못 받으면 앱 계산으로 돈다.
    }
    // 로봇 상세의 진단이 이 값을 본다. 창을 열 때마다 프로세스를 뒤지면
    // 창이 늦게 뜬다.
    //
    // 여기서 묻는 것은 "Gazebo 가 도는가" 지 "이 프로젝트의 프로세스가 있는가"
    // 가 아니다. 진단의 `Gazebo` 고리가 이 값을 그대로 쓰기 때문이다. 예전에는
    // 뒤엣것을 물어서, Gazebo 가 죽고 RMF·Nav2 만 남은 상태를 초록으로 보여
    // 줬다.
    try {
      final running = await gazeboRunningProjects();
      if (mounted) setState(() => _backendRunning = running.isNotEmpty);
    } catch (_) {}
  }

  Offset _floorCoordinate(Offset point) {
    final floorPoints = _floorMask?.points;
    if (floorPoints == null || floorPoints.isEmpty) return point;
    final bounds = _pointsBounds(floorPoints);
    return Offset(point.dx - bounds.left, bounds.bottom - point.dy);
  }

  List<Offset> _outgoingWaypoints(Offset point) {
    final result = <Offset>{};
    final loadedMap = _robotDeployedMap;
    final lanes = loadedMap?.lanes ?? _recommendedLanes;
    for (final lane in lanes) {
      // 배포 맵도 일방통행 정보를 들고 온다. 예전에는 무조건 양방향으로 봐서
      // 로봇이 일방통행 레인을 거슬러 올라갔다.
      final direction = loadedMap == null
          ? _laneDirections[lane] ?? '양방향'
          : loadedMap.laneDirections[lane] ?? '양방향';
      if ((lane.$1 - point).distance <= .01 && direction != '역방향') {
        result.add(lane.$2);
      }
      if ((lane.$2 - point).distance <= .01 && direction != '정방향') {
        result.add(lane.$1);
      }
    }
    return result.toList();
  }

  List<Offset>? _shortestRobotPath(Offset start, Offset destination) {
    const mergeTolerance = .1;
    final canonicalPoints = <Offset>[];
    Offset canonical(Offset point) {
      for (final existing in canonicalPoints) {
        if ((existing - point).distance <= mergeTolerance) return existing;
      }
      canonicalPoints.add(point);
      return point;
    }

    final edges = <Offset, List<(Offset, double)>>{};
    final loadedMap = _robotDeployedMap;
    final lanes = loadedMap?.lanes ?? _recommendedLanes;
    for (final lane in lanes) {
      final from = canonical(lane.$1);
      final to = canonical(lane.$2);
      // 배포 맵도 일방통행 정보를 들고 온다. 예전에는 무조건 양방향으로 봐서
      // 로봇이 일방통행 레인을 거슬러 올라갔다.
      final direction = loadedMap == null
          ? _laneDirections[lane] ?? '양방향'
          : loadedMap.laneDirections[lane] ?? '양방향';
      final distance = (from - to).distance;
      if (direction != '역방향') {
        edges.putIfAbsent(from, () => []).add((to, distance));
      }
      if (direction != '정방향') {
        edges.putIfAbsent(to, () => []).add((from, distance));
      }
    }
    final routeStart = canonical(start);
    final routeDestination = canonical(destination);
    final points = canonicalPoints.toSet();
    final distances = {for (final point in points) point: double.infinity};
    final previous = <Offset, Offset>{};
    final unvisited = points.toSet();
    distances[routeStart] = 0;
    while (unvisited.isNotEmpty) {
      Offset? current;
      var best = double.infinity;
      for (final point in unvisited) {
        final distance = distances[point]!;
        if (distance < best) {
          best = distance;
          current = point;
        }
      }
      if (current == null || best == double.infinity) break;
      unvisited.remove(current);
      if (current == routeDestination) break;
      for (final edge in edges[current] ?? const []) {
        final candidate = best + edge.$2;
        if (candidate < distances[edge.$1]!) {
          distances[edge.$1] = candidate;
          previous[edge.$1] = current;
        }
      }
    }
    if (routeStart != routeDestination &&
        !previous.containsKey(routeDestination)) {
      return null;
    }
    final path = <Offset>[routeDestination];
    while (path.last != routeStart) {
      final parent = previous[path.last];
      if (parent == null) return null;
      path.add(parent);
    }
    return path.reversed.toList();
  }

  void _finishRobotTask(_MockRobot robot) {
    final taskId = robot.activeTaskId;
    if (taskId == null) return;
    final task = _mockTasks.where((item) => item.id == taskId).firstOrNull;
    if (task != null && task.status == _MockTaskStatus.active) {
      task.status = _MockTaskStatus.completed;
      task.completedAt = DateTime.now();
      unawaited(_saveMockTasks());
    }
    robot
      ..activeTaskId = null
      ..moving = false
      ..rmfDriven = false
      ..rmfTaskId = null
      ..rmfGoalX = null
      ..rmfGoalY = null;
    _homeReservations.removeWhere((_, robotId) => robotId == robot.id);
  }

  void _failRobotTask(_MockRobot robot, _MockTask task, String reason) {
    final step = task.currentStep;
    if (step != null) {
      step.status = _TaskStepStatus.failed;
      step.failureReason = reason;
    }
    task.status = _MockTaskStatus.failed;
    task.completedAt = DateTime.now();
    robot
      ..activeTaskId = null
      ..moving = false
      ..targetWaypoint = null
      ..rmfDriven = false
      ..rmfTaskId = null
      ..rmfGoalX = null
      ..rmfGoalY = null
      ..assignedRoute.clear();
    _homeReservations.removeWhere((_, robotId) => robotId == robot.id);
    unawaited(_saveMockTasks());
  }

  /// 작업과 담당 로봇의 상태를 실시간으로 보여 준다.
  ///
  /// 로봇 상태는 앱 안의 Mock 주행에서 나온다. 실제 ROS 토픽 구독은 아직
  /// 없으므로, 여기 보이는 값은 앱이 계산한 위치다. 실제 로봇을 붙이면 같은
  /// 자리에 토픽 값이 들어오도록 필드를 맞춰 두었다.
  /// 레인으로 이어진 Waypoint 사이의 최소 거리 [m].
  ///
  /// 도착 반경을 여기서 뽑는다. 이 맵은 0.33m 인데 벤더 도착 반경은 0.25m 라,
  /// 이웃 Waypoint 의 도착 원과 겹쳐 어느 지점에 섰는지 구별이 안 됐다.
  double? get _minLaneSpacing {
    final scale = _metersPerPixel;
    if (scale == null) return null;
    final lanes = _robotDeployedMap?.lanes ?? _recommendedLanes;
    double? shortest;
    for (final lane in lanes) {
      final meters = (lane.$1 - lane.$2).distance * scale;
      if (meters <= 0) continue;
      if (shortest == null || meters < shortest) shortest = meters;
    }
    return shortest;
  }

  /// 이 맵에서 권하는 도착 반경 [m].
  double get _recommendedGoalTolerance =>
      recommendedGoalTolerance(minLaneSpacing: _minLaneSpacing);

  /// 실제로 쓸 도착 반경 [m]. 사람이 넣은 값이 있으면 그것을 쓴다.
  double get _goalTolerance =>
      _fleetSettings.goalToleranceMeters ?? _recommendedGoalTolerance;

  /// 배포 산출물을 만들 때 쓸 로봇 목록.
  ///
  /// 화면이 들고 있는 `_fleetRobots` 는 지금 열린 프로젝트의 것이다. 다른
  /// 화면에서 등록만 해 두고 이 화면으로 오면 비어 있을 수 있고, 그대로
  /// 배포하면 로봇이 하나도 안 실린 산출물이 나간다. 실제로 MySQL 에는
  /// 로봇 셋이 있는데 fleet.yaml 은 "등록된 로봇이 없다" 였다.
  ///
  /// 그래서 배포는 **저장된 것**을 본다. 저장이 진실이다.
  Future<List<RmfProjectRobot>> _fleetRobotsForDeploy(String mapName) async {
    try {
      final stored = await loadMapProjectFleet(mapName);
      final rows =
          (stored?['robots'] as List<dynamic>? ?? const [])
              .cast<Map<String, dynamic>>()
              .toList()
            ..sort(
              (a, b) =>
                  ((a['seq'] as num?) ?? 0).compareTo((b['seq'] as num?) ?? 0),
            );
      if (rows.isEmpty) return _fleetRobots;
      return _withMapSpawnPoints([
        for (final row in rows)
          RmfProjectRobot.fromJson({
            ...row,
            'zones': (row['zonesText'] as String? ?? '')
                .split(',')
                .map((zone) => zone.trim())
                .where((zone) => zone.isNotEmpty)
                .toList(),
          }),
      ]);
    } catch (_) {
      // 못 읽으면 화면이 들고 있는 것으로라도 만든다.
      return _fleetRobots;
    }
  }

  /// 배포 산출물이 있는 곳. 불러온 배포 맵 기준이다.
  String? get _deployedMapDirectory {
    final name = _robotDeployedMap?.summary.name ?? _mapName;
    return name.trim().isEmpty ? null : _mapDirectoryFor(name);
  }

  /// 이 프로젝트의 백엔드가 떠 있는가.
  ///
  /// 로봇 상세를 열 때마다 프로세스를 뒤지면 창이 늦게 뜬다. 화면이 이미
  /// 주기적으로 읽어 둔 값을 쓴다.
  bool _backendRunning = false;

  Future<void> _startBackendFromDetail() async {
    final name = _robotDeployedMap?.summary.name ?? _mapName;
    if (name.trim().isEmpty) return;
    // 여기서도 어떤 창을 볼지 묻는다. 설정 파일 메뉴에서 띄울 때와 다르게
    // 굴면, 같은 일을 어디서 시작했느냐에 따라 결과가 달라진다.
    final windows = await _askRunWindows(name);
    if (windows == null || !mounted) return;
    await startProject(
      name,
      backend: windows.backend,
      gazeboGui: windows.gazeboGui,
      rviz: windows.rviz,
    );
    final running = await gazeboRunningProjects();
    if (!mounted) return;
    setState(() => _backendRunning = running.isNotEmpty);
  }

  /// `/fleet_states` 를 마지막으로 읽은 결과. 아직 안 읽었으면 null.
  RmfFleetSnapshot? _fleetSnapshot;

  /// 위치추정 지도와 주행 그래프의 정합. 아직 안 봤으면 null.
  Nav2MapAlignment? _mapAlignment;

  /// `/clock` 을 내는 곳의 수. 아직 안 셌으면 null.
  int? _clockPublishers;

  /// 작업 화면에 늘 띄우는 준비 확인표.
  ///
  /// 값은 여기서 모으고 판단은 [buildReadinessReport] 가 한다 — 그래야 판단을
  /// 화면 없이 시험할 수 있다.
  ReadinessReport get _readiness {
    final mapName = _robotDeployedMap?.summary.name ?? _mapName;
    final snapshot = _fleetSnapshot;
    return buildReadinessReport(
      waypointNames: movableWaypointNames(
        _robotDeployedMap?.waypointNames ?? _waypointNames,
      ),
      robots: _fleetRobots,
      // ros2 launch 는 앱이 아니라 파일을 읽는다. 실행 스크립트가 디스크에
      // 있어야 띄울 수 있다.
      exported:
          mapName.trim().isNotEmpty &&
          projectRunScriptExists(_mapDirectoryFor(mapName), mapName),
      backendRunning: _backendRunning,
      fleetReachable: snapshot?.reachable ?? false,
      attachedRobots: snapshot?.robots ?? const {},
      alignment: _mapAlignment,
      clockPublishers: _clockPublishers,
    );
  }

  /// 배포된 위치추정 지도와 주행 그래프가 같은 자리에 있는지 본다.
  ///
  /// 앱이 들고 있는 값이 아니라 **디스크의 파일**을 읽는다. 어긋난 채로 도는
  /// 것은 디스크 쪽이고, 내보내기를 안 했으면 둘이 다르다.
  Nav2MapAlignment? _readMapAlignment(String mapName) {
    if (mapName.trim().isEmpty) return null;
    final dir = _mapDirectoryFor(mapName);
    final graph = readNavGraphWaypoints('$dir/nav_graphs/0.yaml');
    if (graph.isEmpty) return null;
    // 실행에 실제로 들어가는 지도를 본다. SLAM 을 쓰기로 했으면 그것이다 —
    // 도면에서 구운 격자만 보면 늘 맞다고 나온다.
    final yaml = _useSlamMap
        ? '$dir/nav2_map/${mapName}_slam.yaml'
        : '$dir/nav2_map/$mapName.yaml';
    final map = readNav2MapExtent(yaml);
    if (map == null) return null;
    return checkNav2MapAlignment(map: map, waypoints: graph);
  }

  /// 확인표의 재료를 다시 모은다. 작업 화면이 10초마다 부른다.
  Future<void> _refreshReadiness() async {
    // 백엔드가 없으면 읽을 토픽도 없다. 그때마다 ros2 를 띄우면 8초씩 기다렸다
    // 실패하는 일만 되풀이한다.
    final running = await gazeboRunningProjects();
    if (!mounted) return;
    final backendRunning = running.isNotEmpty;
    // RobotTelemetryBridge가 이미 /fleet_states를 계속 읽고 있다. 준비 확인마다
    // 별도 `ros2 topic echo --once`를 띄우면 같은 DDS 데이터를 중복 구독하며
    // 순간적으로 CPU 한 코어를 대부분 사용한다.
    final attached = RobotTelemetryBridge.instance.attachedRobotIds;
    final snapshot = backendRunning
        ? RmfFleetSnapshot(
            reachable: attached.isNotEmpty,
            robots: attached,
            message: attached.isEmpty ? '/fleet_states를 아직 받지 못했습니다.' : null,
          )
        : null;
    final clocks = backendRunning
        ? await probeClockPublishers(rosDomainId: _rosDomainId)
        : null;
    final alignment = _readMapAlignment(
      _robotDeployedMap?.summary.name ?? _mapName,
    );
    if (!mounted) return;
    setState(() {
      _backendRunning = backendRunning;
      _fleetSnapshot = snapshot;
      _mapAlignment = alignment;
      _clockPublishers = clocks;
    });
  }

  /// 로봇 하나를 Waypoint 하나로 바로 보낸다.
  ///
  /// 작업을 만들지 않는다. 작업 목록에도 안 남는다 — 자리 확인이나 충전대
  /// 복귀처럼 한 번 시키고 끝나는 일에 단계를 엮고 저장하는 것은 과하다.
  ///
  /// RMF 에게는 `robot_task_request` 로 간다. 고른 로봇이 그대로 간다는 뜻이다.
  /// 그래도 **경로는 RMF 가 만든다** — Nav2 에 좌표를 바로 던지면 traffic
  /// schedule 밖에서 도는 로봇이 생겨, 다른 로봇이 그 자리를 비었다고 여긴다.
  Future<void> _sendRobotToWaypoint(RmfProjectRobot robot) async {
    final mapName = _robotDeployedMap?.summary.name ?? _mapName;
    final waypoints = movableWaypointNames(
      _robotDeployedMap?.waypointNames ?? _waypointNames,
    );
    final blocker = robotMoveBlocker(
      robot: robot,
      backendRunning: _backendRunning,
      waypoints: waypoints,
      mapName: mapName,
    );
    if (blocker != null) {
      await showWaypointErrorDialog(
        context,
        title: '보낼 수 없습니다',
        message: blocker,
      );
      return;
    }
    // 지금 서 있는 자리는 기본값에서 뺀다. 있는 자리로 보내는 것은 아무 일도
    // 안 하는 것과 같은데, RMF 는 그것도 작업으로 받아 성공이라고 답한다.
    final here = robot.chargerWaypoint?.trim();
    final destination = await showMovableDialog<String>(
      context: context,
      builder: (dialogContext) => _RobotMoveDialog(
        robot: robot,
        waypoints: waypoints,
        currentWaypoint: here,
      ),
    );
    if (destination == null || !mounted) return;

    final request = buildRobotMoveRequest(
      fleetName: _fleetSettingsFor(mapName).fleetName,
      robotId: robot.robotId,
      waypoint: destination,
    );
    final result = await RmfTaskBridge.instance.submit(
      mapDirectory: _mapDirectoryFor(mapName),
      mapName: mapName,
      requestJson: request.json,
    );
    if (!mounted) return;
    await showWaypointErrorDialog(
      context,
      title: result.accepted ? '보냈습니다' : '보내지 못했습니다',
      message: result.accepted
          ? '${robot.displayName} 을(를) $destination 으로 보냈습니다.'
                '${result.taskId == null ? '' : '\nRMF 작업 번호: ${result.taskId}'}\n\n'
                '경로는 RMF 가 Lane 을 따라 만듭니다. 도중에 다른 로봇과 겹치면 '
                '알아서 기다립니다.'
          : result.message,
    );
  }

  /// 앱이 로봇 토픽을 다시 구독하게 한다.
  Future<void> _resubscribeRobots() async {
    await RobotTelemetryBridge.instance.stop();
    await _syncTelemetry();
  }

  /// 로봇 하나의 상세를 연다.
  ///
  /// 등록된 로봇이든 지도에만 올라온 것이든 같은 창으로 본다. 둘 중 하나만
  /// 있어도 열린다 — 등록만 하고 아직 안 올렸거나, 등록 없이 올린 사람·
  /// 휴머노이드일 수 있다.
  Future<void> _showRobotDetail(String robotId) => showMovableDialog<void>(
    context: context,
    builder: (_) => _RobotDetailDialog(
      robotId: robotId,
      registered: _fleetRobots
          .where((robot) => robot.robotId == robotId)
          .firstOrNull,
      robotOf: () =>
          _mockRobots.where((robot) => robot.id == robotId).firstOrNull,
      tasksOf: () => [
        for (final task in _mockTasks)
          if (task.robotId == robotId) task,
      ],
      telemetry: () => _telemetry,
      sensorsOf: () => RobotSensorFeed.instance.sensorsOf(robotId),
      toFloor: _floorCoordinate,
      metersPerPixel: _metersPerPixel,
      waypointLabel: _waypointLabel,
      mapDirectory: _deployedMapDirectory,
      mapName: _robotDeployedMap?.summary.name ?? _mapName,
      backendRunning: () => _backendRunning,
      onStartBackend: _startBackendFromDetail,
      onResubscribe: _resubscribeRobots,
    ),
  );

  Future<void> _showTaskDetail(_MockTask task) {
    final registered = _fleetRobots
        .where((robot) => robot.robotId == task.robotId)
        .firstOrNull;
    return showMovableDialog<void>(
      context: context,
      builder: (_) => _TaskDetailDialog(
        task: task,
        robotOf: (id) =>
            _mockRobots.where((robot) => robot.id == id).firstOrNull,
        toFloor: _floorCoordinate,
        metersPerPixel: _metersPerPixel,
        waypointLabel: _waypointLabel,
        // 출처는 로봇마다 다르다. 등록에 적힌 것을 그대로 쓴다.
        dataSource: registered?.dataSource ?? RobotDataSource.mock,
        // 실제로 값이 들어오고 있을 때만 참이다. 구독을 걸어 두기만 하고 값이
        // 안 오는 것과 오는 것은 다르다.
        topicsConnected:
            registered != null && _telemetry.isLive(registered.robotId),
        registeredRobot: registered,
      ),
    );
  }

  /// 로봇을 최초 위치까지 데려갈 Lane 경로. 갈 길이 없으면 null.
  List<Offset>? _routeToSpawn(_MockRobot robot) {
    final waypoints = _robotDeployedMap?.waypoints ?? _laneWaypoints;
    if (waypoints.isEmpty) return null;
    final start = waypoints.reduce(
      (a, b) => (a - robot.position).distance <= (b - robot.position).distance
          ? a
          : b,
    );
    final path = _shortestRobotPath(start, robot.spawnPosition);
    if (path == null) return null;
    return path.skip(1).toList();
  }

  /// 이동 로봇을 Spawn 할 때 고른 Waypoint로 되돌린다.
  ///
  /// 진행 중이던 작업은 대기로 되돌린다. 로봇만 치우고 작업을 진행 중으로 두면
  /// 아무도 손대지 않는 작업이 남는다.
  /// 로봇 하나를 Spawn 할 때 고른 자리로 돌려보낸다.
  ///
  /// `setState` 안에서 부른다. 돌아간 방식을 돌려주므로 부르는 쪽이 사람에게
  /// 무슨 일이 있었는지 적을 수 있다.
  ///
  /// Lane 으로 갈 길이 없으면 그 자리에 놓아 둔다. 못 돌아간 채로 두면 버튼을
  /// 눌러도 아무 일이 없는 것처럼 보인다.
  _ReturnOutcome _sendRobotHome(_MockRobot robot) {
    robot
      ..activeTaskId = null
      ..targetWaypoint = null
      ..previousWaypoint = null
      ..assignedRoute.clear();
    _homeReservations.removeWhere((_, robotId) => robotId == robot.id);
    if ((robot.position - robot.spawnPosition).distance <= .01) {
      robot
        ..moving = false
        ..returningToSpawn = false;
      return _ReturnOutcome.already;
    }
    final path = _routeToSpawn(robot);
    if (path == null || path.isEmpty) {
      robot
        ..position = robot.spawnPosition
        ..moving = false
        ..returningToSpawn = false;
      return _ReturnOutcome.teleported;
    }
    robot
      ..assignedRoute.addAll(path)
      ..moving = true
      ..returningToSpawn = true;
    return _ReturnOutcome.routed;
  }

  /// 돌고 있는 작업 하나를 취소하고, 그 로봇을 최초 위치로 돌려보낸다.
  ///
  /// RMF 가 몰고 있던 작업이면 RMF 에도 취소를 넣는다. 앱에서만 지우면 RMF 는
  /// 계속 그 작업을 들고 있어, 로봇이 돌아가는 도중에 다시 목적지로 끌려간다.
  Future<void> _cancelMockTask(_MockTask task) async {
    // 대기 중인 것도 취소할 수 있다. 배차를 기다리는 작업을 못 지우면 목록에
    // 계속 남아 다음 로봇이 그것을 물어 간다.
    if (task.status != _MockTaskStatus.active &&
        task.status != _MockTaskStatus.queued) {
      _showProcessingWarning('작업 취소', '${task.name} 작업은 이미 끝났습니다.');
      return;
    }
    // 그 작업을 실제로 들고 있는 로봇을 본다. `task.robotId` 는 `__auto__` 일
    // 수도 있고, 배차가 바뀌었으면 옛 로봇을 가리킬 수도 있다.
    final robot = _mockRobots
        .where((item) => item.activeTaskId == task.id)
        .firstOrNull;
    final rmfTaskId = robot?.rmfTaskId;
    final confirmed = await showMovableDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        icon: const Icon(Icons.cancel_outlined, size: 32),
        title: const Text('작업 취소'),
        content: SizedBox(
          width: 430,
          child: Text(
            '${task.name} 을 취소합니다.\n\n'
            '${robot == null ? '맡은 로봇이 없습니다.' : '${robot.id} 는 Spawn 할 때 고른 자리로 돌아갑니다.'}'
            '${rmfTaskId == null ? '' : '\n\nRMF 에도 취소를 넣습니다 (작업 $rmfTaskId).'}',
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('닫기'),
          ),
          FilledButton.icon(
            onPressed: () => Navigator.pop(dialogContext, true),
            style: FilledButton.styleFrom(
              backgroundColor: const Color(0xFFDC2626),
            ),
            icon: const Icon(Icons.cancel_outlined, size: 18),
            label: const Text('작업 취소'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;

    final registered = robot == null
        ? null
        : _fleetRobots.where((item) => item.robotId == robot.id).firstOrNull;
    final immediateSimulation =
        registered?.dataSource == RobotDataSource.gazebo ||
        registered?.dataSource == RobotDataSource.mock;
    if (immediateSimulation) {
      final initial = task.initialRobotPosition ?? robot?.spawnPosition;
      setState(() {
        task
          ..status = _MockTaskStatus.cancelled
          ..completedAt = DateTime.now();
        for (final step in task.steps.where(
          (step) =>
              step.status == _TaskStepStatus.pending ||
              step.status == _TaskStepStatus.active,
        )) {
          step
            ..status = _TaskStepStatus.cancelled
            ..remainingSeconds = 0;
        }
        if (robot != null) {
          robot
            ..activeTaskId = null
            ..moving = false
            ..returningToSpawn = false
            ..rmfDriven = false
            ..rmfTaskId = null
            ..rmfGoalX = null
            ..rmfGoalY = null
            ..targetWaypoint = null
            ..previousWaypoint = null
            ..assignedRoute.clear();
          if (initial != null) robot.position = initial;
          _homeReservations.removeWhere((_, robotId) => robotId == robot.id);
        }
      });
      await _saveMockTasks();
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            '${task.name} 을 즉시 취소했습니다 — '
            '${robot?.id ?? '로봇'}을 작업 최초 위치로 되돌렸습니다.',
          ),
        ),
      );

      // 화면은 위에서 즉시 끝낸다. ROS 응답을 기다리느라 취소 버튼이 멈춰
      // 보이지 않도록 RMF와 Gazebo 정리는 뒤에서 수행한다.
      final mapName = _robotDeployedMap?.summary.name ?? _mapName;
      if (rmfTaskId != null) {
        unawaited(
          RmfTaskBridge.instance.submit(
            mapDirectory: _mapDirectoryFor(mapName),
            mapName: mapName,
            requestJson: buildCancelTaskRequest(rmfTaskId),
          ),
        );
      }
      if (registered?.dataSource == RobotDataSource.gazebo && initial != null) {
        final world = _rmfMetersFromPixel(initial);
        if (world != null) {
          unawaited(
            resetGazeboRobotPose(
              modelName: registered!.gzName,
              x: world.dx,
              y: world.dy,
              yaw: task.initialRobotHeading ?? 0,
              rosDomainId: _rosDomainId,
            ),
          );
        }
      }
      _startQueuedOrderTasks();
      return;
    }

    // RMF 를 먼저 세운다. 앱 상태를 먼저 지우면 그 사이에 RMF 가 로봇을 계속
    // 몰아, 돌아가는 로봇과 RMF 의 명령이 서로 당긴다.
    final mapName = _robotDeployedMap?.summary.name ?? _mapName;
    final directory = _mapDirectoryFor(mapName);
    final problems = <String>[];
    if (rmfTaskId != null) {
      final result = await RmfTaskBridge.instance.submit(
        mapDirectory: directory,
        mapName: mapName,
        requestJson: buildCancelTaskRequest(rmfTaskId),
      );
      if (!result.accepted) problems.add('RMF 취소 실패: ${result.message}');
    }
    if (!mounted) return;

    // 되돌아가는 길은 누가 모느냐에 따라 다르다.
    //
    // RMF 가 몰던 로봇을 앱 애니메이션으로 되돌리면 **화면만 집에 가고 실제
    // 로봇은 그 자리에 선다.** 이동 타이머는 `rmfDriven` 로봇을 건너뛰기
    // 때문이다 — 위치는 토픽에서 온다. 그러니 RMF 에게 자리로 가라고 새 작업을
    // 넣어야 진짜로 돌아간다.
    final charger = registered?.chargerWaypoint?.trim();
    final byRmf = robot != null && robot.rmfDriven;
    var sentHomeByRmf = false;
    if (byRmf) {
      if (charger == null || charger.isEmpty) {
        problems.add('${robot.id} 의 자리 Waypoint 가 없어 복귀를 못 시켰습니다.');
      } else {
        final request = buildRmfTaskRequest(
          fleetName: _fleetSettingsFor(mapName).fleetName,
          robotId: robot.id,
          category: '복귀',
          activities: [RmfTaskActivity.goToPlace(charger)],
        );
        final result = await RmfTaskBridge.instance.submit(
          mapDirectory: directory,
          mapName: mapName,
          requestJson: request.json,
        );
        sentHomeByRmf = result.accepted;
        if (!result.accepted) {
          problems.add('복귀 작업을 RMF 가 받지 않았습니다: ${result.message}');
        }
      }
    }
    if (!mounted) return;

    var outcome = _ReturnOutcome.already;
    setState(() {
      task
        ..status = _MockTaskStatus.cancelled
        ..completedAt = DateTime.now();
      // 못 끝낸 단계는 취소로 남긴다. 대기로 되돌리면 이력에서 이 작업이
      // 어디까지 갔었는지 알 수 없다.
      for (final step in task.steps.where(
        (step) =>
            step.status == _TaskStepStatus.pending ||
            step.status == _TaskStepStatus.active,
      )) {
        step
          ..status = _TaskStepStatus.cancelled
          ..remainingSeconds = 0;
      }
      if (robot != null) {
        robot
          ..activeTaskId = null
          ..rmfTaskId = null
          ..rmfGoalX = null
          ..rmfGoalY = null;
        if (byRmf) {
          // 계속 RMF 가 몬다. 여기서 `rmfDriven` 을 내리면 앱이 좌표를 직접
          // 옮기기 시작해 토픽으로 오는 진짜 위치와 싸운다.
          robot
            ..targetWaypoint = null
            ..previousWaypoint = null
            ..assignedRoute.clear()
            ..moving = sentHomeByRmf;
          _homeReservations.removeWhere((_, robotId) => robotId == robot.id);
        } else {
          outcome = _sendRobotHome(robot);
        }
      }
    });
    _startMockRobotTimer();
    await _saveMockTasks();
    if (!mounted) return;
    final detail = robot == null
        ? '맡은 로봇이 없었습니다'
        : byRmf
        ? (sentHomeByRmf
              ? '${robot.id} 복귀를 RMF 에 넘겼습니다'
              : '${robot.id} 는 그 자리에 섰습니다')
        : switch (outcome) {
            _ReturnOutcome.routed => '${robot.id} 복귀 중',
            _ReturnOutcome.teleported => '${robot.id} 는 경로가 없어 즉시 이동',
            _ReturnOutcome.already => '${robot.id} 는 이미 최초 위치',
          };
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          problems.isEmpty
              ? '${task.name} 을 취소했습니다 — $detail'
              : '${task.name} 을 취소했습니다 — $detail\n${problems.join('\n')}',
        ),
        duration: const Duration(seconds: 7),
        showCloseIcon: true,
      ),
    );
  }

  Future<void> _returnRobotsToSpawn() async {
    final movable = _mockRobots.where((robot) => robot.kind.isMobile).toList();
    if (movable.isEmpty) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('되돌릴 이동 로봇이 없습니다.')));
      return;
    }
    final stoppable = _mockTasks
        .where(
          (task) =>
              task.status == _MockTaskStatus.active ||
              task.status == _MockTaskStatus.queued,
        )
        .length;
    final confirmed = await showMovableDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        icon: const Icon(Icons.replay, size: 34),
        title: const Text('로봇을 최초 위치로'),
        content: SizedBox(
          width: 420,
          child: Text(
            '이동 로봇 ${movable.length}대를 Spawn 할 때 고른 Waypoint로 되돌립니다.'
            '\n\n진행 중이거나 대기 중인 작업 $stoppable건을 모두 중지합니다.'
            '\nGazebo와 작업맵의 위치도 함께 원위치로 맞춥니다.',
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('취소'),
          ),
          FilledButton.icon(
            onPressed: () => Navigator.pop(dialogContext, true),
            icon: const Icon(Icons.replay, size: 18),
            label: const Text('원위치'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;

    final mapName = _robotDeployedMap?.summary.name ?? _mapName;
    final rmfTaskIds = movable
        .map((robot) => robot.rmfTaskId)
        .whereType<String>()
        .toSet();
    final registrations = {
      for (final robot in _fleetRobots) robot.robotId: robot,
    };
    var moved = 0;
    var already = 0;
    setState(() {
      // 원위치는 비상 정리 성격의 명령이다. 대기 작업을 남기면 로봇을 되돌린
      // 직후 주문 타이머가 다시 배차하므로 활성·대기 작업을 모두 끝낸다.
      for (final task in _mockTasks.where(
        (task) =>
            task.status == _MockTaskStatus.active ||
            task.status == _MockTaskStatus.queued,
      )) {
        task
          ..status = _MockTaskStatus.cancelled
          ..completedAt = DateTime.now();
        for (final step in task.steps.where(
          (step) =>
              step.status == _TaskStepStatus.pending ||
              step.status == _TaskStepStatus.active,
        )) {
          step
            ..status = _TaskStepStatus.cancelled
            ..remainingSeconds = 0;
        }
      }
      for (final robot in movable) {
        if ((robot.position - robot.spawnPosition).distance <= .01) {
          already++;
        } else {
          moved++;
        }
        // 작업맵은 즉시 원위치로 맞춘다. Gazebo/AMCL도 아래에서 같은 좌표로
        // 맞추므로 다음 텔레메트리 갱신 때 이전 위치로 되돌아가지 않는다.
        robot
          ..position = robot.spawnPosition
          ..activeTaskId = null
          ..moving = false
          ..returningToSpawn = false
          ..rmfDriven = false
          ..rmfTaskId = null
          ..rmfGoalX = null
          ..rmfGoalY = null
          ..targetWaypoint = null
          ..previousWaypoint = null
          ..assignedRoute.clear();
      }
      _homeReservations.clear();
    });
    await _saveMockTasks();
    if (!mounted) return;

    // 화면은 즉시 멈추되 RMF에도 취소를 보내 이전 목적지가 로봇을 다시 끌고
    // 가지 않게 한다.
    for (final taskId in rmfTaskIds) {
      unawaited(
        RmfTaskBridge.instance.submit(
          mapDirectory: _mapDirectoryFor(mapName),
          mapName: mapName,
          requestJson: buildCancelTaskRequest(taskId),
        ),
      );
    }
    for (final robot in movable) {
      final registered = registrations[robot.id];
      if (registered?.dataSource != RobotDataSource.gazebo) continue;
      final world = _rmfMetersFromPixel(robot.spawnPosition);
      if (world == null) continue;
      unawaited(
        resetGazeboRobotPose(
          modelName: registered!.gzName,
          x: world.dx,
          y: world.dy,
          yaw: registered.spawnHeading,
          rosDomainId: _rosDomainId,
        ),
      );
    }
    final detail = [
      if (stoppable > 0) '작업 $stoppable건 중지',
      if (moved > 0) '$moved대 원위치 이동',
      if (already > 0) '$already대는 이미 최초 위치',
    ].join(' · ');
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text('로봇 원위치 — $detail'),
        duration: const Duration(seconds: 5),
        showCloseIcon: true,
      ),
    );
  }

  Map<Offset, String> get _homeWaypoints {
    final names = _robotDeployedMap?.waypointNames ?? _waypointNames;
    return {
      for (final entry in names.entries)
        if (entry.value.trim().toLowerCase().startsWith('홈') ||
            entry.value.trim().toLowerCase().startsWith('home'))
          entry.key: entry.value.trim(),
    };
  }

  List<Offset> get _mobileRuntimeWaypoints {
    final waypoints = _robotDeployedMap?.waypoints ?? _laneWaypoints;
    final lanes = _robotDeployedMap?.lanes ?? _recommendedLanes;
    return waypoints
        .where(
          (point) => lanes.any(
            (lane) =>
                (lane.$1 - point).distance <= .01 ||
                (lane.$2 - point).distance <= .01,
          ),
        )
        .toSet()
        .toList();
  }

  bool _assignHome(_MockRobot robot, _MockTaskStep step) {
    final homes = _homeWaypoints;
    if (homes.isEmpty) return false;
    final waypoints = _robotDeployedMap?.waypoints ?? _laneWaypoints;
    if (waypoints.isEmpty) return false;
    final start = waypoints.reduce(
      (a, b) => (a - robot.position).distance <= (b - robot.position).distance
          ? a
          : b,
    );
    Offset? selected;
    List<Offset>? selectedPath;
    var selectedDistance = double.infinity;
    for (final home in homes.keys) {
      final reservedBy = _homeReservations[home];
      if (reservedBy != null && reservedBy != robot.id) continue;
      final occupied = _mockRobots.any(
        (other) =>
            other.id != robot.id && (other.position - home).distance <= 18,
      );
      if (occupied) continue;
      final path = _shortestRobotPath(start, home);
      if (path == null) continue;
      var distance = 0.0;
      for (var index = 1; index < path.length; index++) {
        distance += (path[index] - path[index - 1]).distance;
      }
      if (distance < selectedDistance) {
        selected = home;
        selectedPath = path;
        selectedDistance = distance;
      }
    }
    if (selected == null || selectedPath == null) return false;
    _homeReservations.removeWhere((_, robotId) => robotId == robot.id);
    _homeReservations[selected] = robot.id;
    step
      ..destination = selected
      ..destinationName = homes[selected]
      ..status = _TaskStepStatus.active;
    robot
      ..targetWaypoint = null
      ..assignedRoute.clear()
      ..assignedRoute.addAll(selectedPath.skip(1))
      ..moving = true;
    unawaited(_saveMockTasks());
    return true;
  }

  /// 이 로봇의 작업을 RMF 가 몰아야 하는가.
  ///
  /// 등록에서 값의 출처를 Gazebo 나 실물로 고른 로봇이다. Mock 로봇은 ROS 를
  /// 아예 안 쓰므로 예전처럼 앱이 굴린다.
  bool _isRmfDriven(String robotId) {
    final registered = _fleetRobots
        .where((item) => item.robotId == robotId)
        .firstOrNull;
    return registered != null &&
        registered.isMobile &&
        registered.dataSource.usesTopics;
  }

  /// 앱 작업 하나를 RMF 에 넘긴다.
  ///
  /// 넘기고 나면 경로도 단계 진행도 RMF 가 정한다. 앱은 무엇을 할지만 정하고
  /// 언제 끝났는지는 어댑터가 내는 진행 토픽으로 듣는다.
  Future<RmfTaskSubmission> _submitTaskToRmf(
    _MockRobot robot,
    _MockTask task,
  ) async {
    // 배포 산출물이 있는 맵이라야 한다. 로봇 화면에서 불러온 것이 그것이다.
    final mapName = _robotDeployedMap?.summary.name ?? _mapName;
    if (mapName.trim().isEmpty) {
      return const RmfTaskSubmission(
        accepted: false,
        message: '어느 맵인지 모릅니다. 로봇 화면에서 배포 맵 불러오기를 먼저 하세요.',
      );
    }
    final registered = _fleetRobots
        .where((item) => item.robotId == robot.id)
        .firstOrNull;
    final converted = convertTaskSteps([
      for (final step in task.steps)
        RmfTaskStepInput(
          kind: step.type.name,
          placeName: step.destinationName,
          durationSeconds: step.durationSeconds,
          policyId: step.policyId,
        ),
    ], homePlaceName: registered?.chargerWaypoint);
    if (converted.isEmpty) {
      return RmfTaskSubmission(
        accepted: false,
        message: ['RMF 에 넘길 단계가 하나도 없습니다.', ...converted.skipped].join('\n'),
      );
    }
    final request = buildRmfTaskRequest(
      fleetName: _fleetSettingsFor(mapName).fleetName,
      robotId: robot.id,
      activities: converted.activities,
      category: task.name,
    );
    final result = await RmfTaskBridge.instance.submit(
      mapDirectory: _mapDirectoryFor(mapName),
      mapName: mapName,
      requestJson: request.json,
    );
    if (result.accepted && converted.skipped.isNotEmpty) {
      // 넘긴 것과 화면에 보이는 것이 다르면 밝혀야 한다.
      _processingWarning =
          '[RMF] ${task.name}: 넘기지 못한 단계가 있습니다 — '
          '${converted.skipped.join(' · ')}';
    }
    return result;
  }

  /// 어댑터가 낸 진행 소식 하나를 화면에 반영한다.
  ///
  /// RMF 는 Lane 을 따라 중간 Waypoint 를 스스로 끼워 넣는다. 도착 소식이
  /// 올 때마다 단계를 넘기면 화면이 실제보다 앞서간다. 그래서 마지막 목적지가
  /// **우리 단계의 목적지와 같을 때만** 넘긴다.
  void _handleRmfProgress(RmfTaskProgress event) {
    if (!mounted) return;
    final robot = _mockRobots
        .where((item) => item.id == event.robotId)
        .firstOrNull;
    if (robot == null || !robot.rmfDriven) return;
    final task = robot.activeTaskId == null
        ? null
        : _mockTasks.where((item) => item.id == robot.activeTaskId).firstOrNull;
    if (task == null) return;
    final step = task.currentStep;
    if (step == null) return;

    if (event.event == 'navigate_start') {
      setState(() {
        robot
          ..rmfGoalX = event.x
          ..rmfGoalY = event.y
          ..moving = true;
      });
      return;
    }
    if (event.event == 'action_start') {
      setState(() => robot.moving = true);
      return;
    }
    if (event.event == 'action_done') {
      if (step.type != _TaskStepType.armLoad) return;
      setState(() => _completeCurrentTaskStep(robot, task));
      return;
    }
    if (event.event != 'navigate_done') return;
    if (!step.type.isMovement) return;
    final goalX = robot.rmfGoalX;
    final goalY = robot.rmfGoalY;
    final destination = step.destination;
    if (goalX == null || goalY == null || destination == null) return;
    final expected = _rmfMetersFromPixel(destination);
    if (expected == null) return;
    // RMF 가 준 좌표는 nav graph 의 Waypoint 값 그대로다. 우리가 도면에서
    // 계산한 값과 소수점 아래까지 같아야 정상이다.
    final gap = math.sqrt(
      math.pow(goalX - expected.dx, 2) + math.pow(goalY - expected.dy, 2),
    );
    if (gap > 0.02) return;
    setState(() => _completeCurrentTaskStep(robot, task));
  }

  void _startTaskStep(_MockRobot robot, _MockTask task) {
    // 취소하면 Spawn 지점이 아니라 이 작업을 시작한 자리로 돌아간다. 다음
    // 단계로 넘어갈 때 기준점이 바뀌지 않도록 최초 한 번만 기록한다.
    task.initialRobotPosition ??= robot.position;
    task.initialRobotHeading ??= _telemetry.poses[robot.id]?.heading;
    // RMF 가 모는 작업은 통째로 한 번 넘긴다. 단계마다 앱이 경로를 만들면
    // RMF 가 고른 경로와 둘이 된다.
    if (robot.rmfDriven) {
      task.currentStep?.status = _TaskStepStatus.active;
      robot.moving = true;
      return;
    }
    final step = task.currentStep;
    if (step == null) {
      _finishRobotTask(robot);
      return;
    }
    step.status = _TaskStepStatus.active;
    step.remainingSeconds = step.durationSeconds;
    if (step.type == _TaskStepType.returnHome) {
      if (_homeWaypoints.isEmpty) {
        _failRobotTask(robot, task, '홈 Waypoint가 없습니다. 홈1, 홈2처럼 이름을 지정해 주세요.');
      } else if (!_assignHome(robot, step)) {
        step.status = _TaskStepStatus.pending;
        robot.moving = false;
      }
      return;
    }
    if (!step.type.isMovement) {
      robot.moving = true;
      return;
    }
    final waypoints = _robotDeployedMap?.waypoints ?? _laneWaypoints;
    final destination = step.destination;
    if (destination == null || waypoints.isEmpty) {
      _failRobotTask(robot, task, '이동 목적지가 없습니다.');
      return;
    }
    final start =
        robot.targetWaypoint ??
        waypoints.reduce(
          (a, b) =>
              (a - robot.position).distance <= (b - robot.position).distance
              ? a
              : b,
        );
    final path = _shortestRobotPath(start, destination);
    if (path == null) {
      _failRobotTask(robot, task, '${step.destinationName}까지 Lane 경로가 없습니다.');
      return;
    }
    robot
      ..targetWaypoint = null
      ..assignedRoute.clear()
      ..assignedRoute.addAll(path.skip(1))
      ..moving = true;
  }

  void _completeCurrentTaskStep(_MockRobot robot, _MockTask task) {
    task.currentStep?.status = _TaskStepStatus.completed;
    task.currentStepIndex++;
    if (task.currentStep == null) {
      _finishRobotTask(robot);
    } else {
      _startTaskStep(robot, task);
    }
    unawaited(_saveMockTasks());
  }

  void _startMockRobotTimer() {
    _mockRobotTimer ??= Timer.periodic(const Duration(milliseconds: 100), (_) {
      if (!mounted || _mockRobots.isEmpty) return;
      final baseSpeed = math.max(
        18.0,
        math.min(
              _drawing?.pixelWidth?.toDouble() ?? 1200,
              _drawing?.pixelHeight?.toDouble() ?? 800,
            ) /
            18,
      );
      var changed = false;
      final now = DateTime.now();
      for (final robot in _mockRobots) {
        // Gazebo 에서 값이 들어오는 로봇은 앱이 위치를 계산하지 않는다.
        // 계산한 값을 덮어써 버리면 실제로 어디 있는지 알 수 없게 된다.
        final live = _telemetry.isLive(robot.id, now: now);
        if (live) {
          final pose = _telemetry.poses[robot.id]!;
          final pixel = _pixelFromMeters(pose.x, pose.y);
          if (pixel != null && (pixel - robot.position).distance > .5) {
            robot.position = pixel;
            changed = true;
          }
        }
        // RMF 가 모는 로봇은 여기서 아무것도 하지 않는다. 위치는 위에서 토픽
        // 으로 받았고, 단계는 어댑터의 진행 소식이 넘긴다. 여기서 또 세면
        // 로봇이 아직 가는 중인데 화면만 다음 단계로 넘어간다.
        if (robot.rmfDriven) {
          robot.battery = math.max(0, robot.battery - .003);
          continue;
        }
        final task = robot.activeTaskId == null
            ? null
            : _mockTasks
                  .where((item) => item.id == robot.activeTaskId)
                  .firstOrNull;
        final activeStep = task?.currentStep;
        if (!robot.moving) {
          if (task != null &&
              activeStep?.type == _TaskStepType.returnHome &&
              activeStep?.status == _TaskStepStatus.pending) {
            _startTaskStep(robot, task);
            changed = robot.moving || changed;
          }
          continue;
        }
        if (task != null && activeStep != null && !activeStep.type.isMovement) {
          activeStep.remainingSeconds = math.max(
            0,
            activeStep.remainingSeconds - .1,
          );
          if (activeStep.remainingSeconds <= 0) {
            _completeCurrentTaskStep(robot, task);
          }
          changed = true;
          continue;
        }
        var target = robot.targetWaypoint;
        if (target == null) {
          if (robot.assignedRoute.isNotEmpty) {
            target = robot.assignedRoute.removeAt(0);
          } else if (robot.returningToSpawn) {
            // 최초 위치에 닿았다. 여기서 멈추지 않으면 아래의 배회 경로를 타고
            // 다시 떠돌기 시작한다.
            robot
              ..position = robot.spawnPosition
              ..returningToSpawn = false
              ..moving = false
              ..previousWaypoint = null;
            changed = true;
            continue;
          } else if (task != null) {
            _completeCurrentTaskStep(robot, task);
            changed = true;
            continue;
          } else {
            final options = _outgoingWaypoints(robot.position);
            if (options.isEmpty) continue;
            target = options.firstWhere(
              (candidate) => candidate != robot.previousWaypoint,
              orElse: () => options.first,
            );
          }
          robot.previousWaypoint = robot.position;
          robot.targetWaypoint = target;
        }
        final delta = target - robot.position;
        // 실제 로봇은 앱이 밀어 주지 않는다. 도착했는지만 본다.
        final step = live
            ? math.max(6.0, .2 / (_metersPerPixel ?? .05))
            : baseSpeed * .1;
        if (delta.distance <= step) {
          // 실제 위치로 도착을 판정할 때는 좌표를 Waypoint 로 끌어당기지
          // 않는다. 그러면 토픽 값을 덮어써 버린다.
          if (!live) robot.position = target;
          robot.targetWaypoint = null;
        } else if (!live) {
          robot.position += delta / delta.distance * step;
        }
        robot.battery = math.max(0, robot.battery - .003);
        changed = true;
      }
      if (changed) setState(() {});
    });
  }

  /// 등록 정보에서 지도에 그릴 종류를 고른다.
  ///
  /// 등록은 Open-RMF 쪽 정보(종류·모델·gz 이름·자리)를 담고, 지도 표시는 앱 쪽
  /// 개념이다. 둘을 따로 물으면 같은 것을 두 번 적게 된다.
  ///
  /// 설치 로봇은 그대로 매니퓰레이터로 그린다. 이동 로봇은 모델 이름으로 Pinky
  /// 인지만 가른다 — 어느 쪽이든 Lane 을 따라 다니는 것은 같다.
  static _RobotKind _kindForRobot(RmfProjectRobot robot) {
    if (!robot.isMobile) return _RobotKind.omxManipulator;
    return robot.model.toUpperCase().contains('PINKY')
        ? _RobotKind.pinky
        : _RobotKind.mockMobile;
  }

  Future<void> _spawnMockRobot() async {
    final runtimeWaypoints = (_robotDeployedMap?.waypoints ?? _laneWaypoints)
        .toSet()
        .toList();
    final runtimeLanes = _robotDeployedMap?.lanes ?? _recommendedLanes;
    final runtimeNames = _robotDeployedMap?.waypointNames ?? _waypointNames;
    // 스폰은 등록된 로봇을 지도에 올리는 일이다. 무엇이 있는지 먼저 정해야
    // Gazebo bringup 과 fleet adapter 가 같은 로봇을 본다.
    //
    // 여기서 막힐 때는 팝업으로 알린다. `_processingWarning` 은 대시보드에만
    // 보여서, 로봇 메뉴에서 누르면 아무 일도 없는 것처럼 보인다.
    if (_fleetRobots.isEmpty) {
      await showWaypointErrorDialog(
        context,
        title: '로봇 Spawn',
        message:
            '등록된 로봇이 없습니다.\n\n'
            '`로봇 등록`에서 먼저 등록해 주세요.\n'
            '맵에 충전 카테고리 Waypoint가 있다면 '
            '`충전 Waypoint에서 만들기`로 한 번에 채울 수 있습니다.',
      );
      return;
    }
    if (runtimeWaypoints.isEmpty) {
      await showWaypointErrorDialog(
        context,
        title: '로봇 Spawn',
        message:
            '로봇을 올릴 Waypoint가 없습니다.\n\n'
            '맵 관리에서 도면을 올리고 Waypoint와 Lane을 만든 뒤, '
            '`배포 맵 불러오기`로 이 화면에 불러오세요.',
      );
      return;
    }
    final unspawned = [
      for (final robot in _fleetRobots)
        if (!_mockRobots.any((mock) => mock.id == robot.robotId)) robot,
    ];
    RmfProjectRobot? registered = unspawned.firstOrNull;
    var kind = registered == null
        ? _RobotKind.mockHumanoid
        : _kindForRobot(registered);
    bool isLaneConnected(Offset point) => runtimeLanes.any(
      (lane) =>
          (lane.$1 - point).distance <= .01 ||
          (lane.$2 - point).distance <= .01,
    );
    List<Offset> candidatesFor(_RobotKind robotKind) {
      if (robotKind == _RobotKind.omxManipulator) {
        final equipment = runtimeWaypoints
            .where(
              (point) => _robotDeployedMap == null
                  ? _waypointTypes[point] == '설비'
                  : !isLaneConnected(point),
            )
            .toList();
        return equipment.isEmpty ? runtimeWaypoints : equipment;
      }
      return runtimeWaypoints.where(isLaneConnected).toList();
    }

    /// 등록된 로봇의 충전 Waypoint 를 지도에서 찾는다. 등록할 때 고른 자리가
    /// 그대로 출발점이 되어야 spawn 좌표와 어긋나지 않는다.
    Offset? chargerPoint(RmfProjectRobot? robot) {
      final name = robot?.chargerWaypoint?.trim();
      if (name == null || name.isEmpty) return null;
      return runtimeWaypoints
          .where((point) => (runtimeNames[point] ?? '').trim() == name)
          .firstOrNull;
    }

    /// 고를 수 있는 출발 Waypoint. 등록된 충전 자리는 Lane 에 붙어 있지 않더라도
    /// 반드시 목록에 넣는다. 그러지 않으면 골라 둔 자리가 목록에 없어 빈칸으로
    /// 보인다.
    List<Offset> startCandidates(_RobotKind robotKind) {
      final charger = chargerPoint(registered);
      final base = candidatesFor(robotKind);
      if (charger == null || base.contains(charger)) return base;
      return [charger, ...base];
    }

    final controller = TextEditingController(
      text: registered?.robotId ?? '사람-${_mockRobots.length + 1}',
    );
    var start =
        chargerPoint(registered) ??
        candidatesFor(kind).firstOrNull ??
        runtimeWaypoints.first;
    Uint8List? selectedImageBytes;
    ui.Image? selectedImage;
    String? selectedImageName;
    final result = await showMovableDialog<_RobotSpawnSelection>(
      context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (context, setDialogState) => AlertDialog(
          icon: const Icon(Icons.smart_toy_outlined, size: 36),
          title: const Text('로봇 Spawn'),
          content: SizedBox(
            width: 420,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                DropdownButtonFormField<String>(
                  initialValue: registered?.robotId ?? _unregisteredSpawn,
                  isExpanded: true,
                  decoration: InputDecoration(
                    labelText: '등록된 로봇',
                    helperText: unspawned.isEmpty
                        ? '등록된 로봇이 모두 배치되어 있습니다.'
                        : '로봇 등록에서 정한 ID·모델·충전 자리를 그대로 씁니다.',
                    border: const OutlineInputBorder(),
                  ),
                  items: [
                    for (final robot in unspawned)
                      DropdownMenuItem(
                        value: robot.robotId,
                        child: Text(
                          '${robot.robotId} · ${robot.displayName}'
                          ' (${robot.model})',
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                    const DropdownMenuItem(
                      value: _unregisteredSpawn,
                      child: Text('등록 없이 배치 — 사람 · 휴머노이드'),
                    ),
                  ],
                  onChanged: (value) {
                    setDialogState(() {
                      registered = value == _unregisteredSpawn
                          ? null
                          : unspawned
                                .where((robot) => robot.robotId == value)
                                .firstOrNull;
                      // 등록된 로봇은 무엇인지 이미 정해져 있다. 등록 없이
                      // 배치하는 것은 관제 대상이 아닌 사람·휴머노이드뿐이다.
                      kind = registered == null
                          ? _RobotKind.mockHumanoid
                          : _kindForRobot(registered!);
                      controller.text =
                          registered?.robotId ?? '사람-${_mockRobots.length + 1}';
                      start =
                          chargerPoint(registered) ??
                          candidatesFor(kind).firstOrNull ??
                          start;
                    });
                  },
                ),
                const SizedBox(height: 14),
                if (registered == null) ...[
                  DropdownButtonFormField<_RobotKind>(
                    initialValue: kind,
                    decoration: const InputDecoration(
                      labelText: '유형',
                      helperText: '관제 대상 로봇은 등록해야 스폰할 수 있습니다.',
                      border: OutlineInputBorder(),
                    ),
                    items: const [
                      DropdownMenuItem(
                        value: _RobotKind.mockHumanoid,
                        child: Text('휴머노이드'),
                      ),
                      DropdownMenuItem(
                        value: _RobotKind.human,
                        child: Text('사람'),
                      ),
                    ],
                    onChanged: (value) {
                      if (value == null) return;
                      setDialogState(() {
                        kind = value;
                        final prefix = value == _RobotKind.human
                            ? '사람'
                            : '휴머노이드';
                        controller.text = '$prefix-${_mockRobots.length + 1}';
                        final candidates = candidatesFor(value);
                        if (candidates.isNotEmpty) start = candidates.first;
                      });
                    },
                  ),
                  const SizedBox(height: 14),
                  TextField(
                    controller: controller,
                    decoration: const InputDecoration(
                      labelText: '이름',
                      border: OutlineInputBorder(),
                    ),
                  ),
                ] else
                  InputDecorator(
                    decoration: const InputDecoration(
                      labelText: '배치할 로봇',
                      border: OutlineInputBorder(),
                    ),
                    child: Text(
                      '${registered!.robotId} · ${kind.label}'
                      ' · ${registered!.gzName}',
                      style: const TextStyle(fontWeight: FontWeight.w600),
                    ),
                  ),
                const SizedBox(height: 14),
                Row(
                  children: [
                    Container(
                      width: 54,
                      height: 54,
                      clipBehavior: Clip.antiAlias,
                      decoration: BoxDecoration(
                        color: const Color(0xFFF1F5F9),
                        borderRadius: BorderRadius.circular(12),
                        border: Border.all(color: const Color(0xFFCBD5E1)),
                      ),
                      child: selectedImageBytes == null
                          ? Icon(
                              kind == _RobotKind.human
                                  ? Icons.person
                                  : kind == _RobotKind.mockHumanoid
                                  ? Icons.accessibility_new
                                  : Icons.smart_toy_outlined,
                              color: const Color(0xFF475569),
                              size: 30,
                            )
                          : Image.memory(
                              selectedImageBytes!,
                              fit: BoxFit.cover,
                            ),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          OutlinedButton.icon(
                            onPressed: () async {
                              final picked = await FilePicker.platform
                                  .pickFiles(
                                    type: FileType.custom,
                                    allowedExtensions: const [
                                      'png',
                                      'jpg',
                                      'jpeg',
                                      'webp',
                                    ],
                                    withData: true,
                                  );
                              if (picked == null || picked.files.isEmpty) {
                                return;
                              }
                              final file = picked.files.single;
                              if (file.bytes == null) return;
                              try {
                                final codec = await ui.instantiateImageCodec(
                                  file.bytes!,
                                );
                                final frame = await codec.getNextFrame();
                                codec.dispose();
                                if (!dialogContext.mounted) {
                                  frame.image.dispose();
                                  return;
                                }
                                selectedImage?.dispose();
                                setDialogState(() {
                                  selectedImageBytes = file.bytes;
                                  selectedImage = frame.image;
                                  selectedImageName = file.name;
                                });
                              } catch (_) {
                                if (!dialogContext.mounted) return;
                                ScaffoldMessenger.of(
                                  dialogContext,
                                ).showSnackBar(
                                  const SnackBar(
                                    content: Text('선택한 이미지를 읽을 수 없습니다.'),
                                  ),
                                );
                              }
                            },
                            icon: const Icon(Icons.image_outlined),
                            label: const Text('캐릭터 이미지 선택'),
                          ),
                          Text(
                            selectedImageName ?? '선택하지 않으면 기본 아이콘을 사용합니다.',
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: Theme.of(context).textTheme.bodySmall,
                          ),
                        ],
                      ),
                    ),
                    if (selectedImageBytes != null)
                      IconButton(
                        onPressed: () {
                          selectedImage?.dispose();
                          setDialogState(() {
                            selectedImageBytes = null;
                            selectedImage = null;
                            selectedImageName = null;
                          });
                        },
                        tooltip: '기본 아이콘 사용',
                        icon: const Icon(Icons.close),
                      ),
                  ],
                ),
                const SizedBox(height: 14),
                DropdownButtonFormField<Offset>(
                  key: ValueKey('$kind${registered?.robotId}'),
                  initialValue: startCandidates(kind).contains(start)
                      ? start
                      : null,
                  decoration: InputDecoration(
                    labelText: kind.isMobile ? '시작 Waypoint' : '고정 설치 Waypoint',
                    helperText: startCandidates(kind).isEmpty
                        ? kind.isMobile
                              ? 'Lane에 연결된 이동 Waypoint가 없습니다.'
                              : '설비 Waypoint가 없습니다.'
                        : registered?.chargerWaypoint != null
                        ? '등록된 충전 자리 ${registered!.chargerWaypoint} 로 맞춰 두었습니다.'
                        : kind == _RobotKind.omxManipulator
                        ? 'Lane이 없는 설비 Waypoint를 우선 표시합니다.'
                        : null,
                    border: OutlineInputBorder(),
                  ),
                  items: [
                    for (final point in startCandidates(kind))
                      DropdownMenuItem(
                        value: point,
                        child: Text(
                          (runtimeNames[point] ?? '').trim().isEmpty
                              ? 'Waypoint ${runtimeWaypoints.indexOf(point) + 1}'
                              : '${runtimeNames[point]!}${kind == _RobotKind.omxManipulator ? ' · 설비' : ''}',
                        ),
                      ),
                  ],
                  onChanged: (value) {
                    if (value != null) setDialogState(() => start = value);
                  },
                ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext),
              child: const Text('취소'),
            ),
            FilledButton.icon(
              onPressed: () {
                final name = controller.text.trim();
                // 등록된 로봇의 충전 자리는 Lane 에 붙어 있지 않을 수도 있다.
                // 그때도 지도 위의 Waypoint 이기만 하면 올려 준다. 예전처럼
                // 아무 말 없이 버튼이 먹지 않으면 왜인지 알 길이 없다.
                if (name.isEmpty) {
                  ScaffoldMessenger.of(
                    dialogContext,
                  ).showSnackBar(const SnackBar(content: Text('이름을 입력해 주세요.')));
                  return;
                }
                if (!runtimeWaypoints.contains(start)) {
                  ScaffoldMessenger.of(dialogContext).showSnackBar(
                    const SnackBar(content: Text('올릴 Waypoint를 골라 주세요.')),
                  );
                  return;
                }
                Navigator.pop(
                  dialogContext,
                  _RobotSpawnSelection(
                    name: name,
                    position: start,
                    kind: kind,
                    imageBytes: selectedImageBytes,
                    image: selectedImage,
                  ),
                );
              },
              icon: const Icon(Icons.add, size: 18),
              label: const Text('Spawn'),
            ),
          ],
        ),
      ),
    );
    controller.dispose();
    if (result == null || !mounted) {
      selectedImage?.dispose();
      return;
    }
    if (_mockRobots.any((robot) => robot.id == result.name)) {
      result.image?.dispose();
      _showProcessingWarning(
        'Mock 로봇 Spawn',
        '같은 이름의 로봇이 이미 있습니다: ${result.name}',
      );
      return;
    }
    const colors = [
      Color(0xFFDC2626),
      Color(0xFF7C3AED),
      Color(0xFF0891B2),
      Color(0xFFEA580C),
      Color(0xFF16A34A),
    ];
    setState(() {
      _mockRobots.add(
        _MockRobot(
          id: result.name,
          position: result.position,
          spawnPosition: result.position,
          color: colors[_mockRobots.length % colors.length],
          kind: result.kind,
          imageBytes: result.imageBytes,
          image: result.image,
        ),
      );
    });
    // 화면의 Spawn 위치와 Gazebo 의 시작 위치가 같은 값을 보게 한다. 예전에는
    // 지도 마커만 옮기고 등록 정보의 spawn_x/spawn_y 는 그대로여서, 다시
    // 실행하면 늘 충전 Waypoint 좌표로 돌아갔다. 충전 복귀 지점은 유지하고
    // 최초 시작 좌표만 이번 선택으로 저장한다.
    final spawnedRegistration = registered;
    final spawnWorld = _rmfMetersFromPixel(result.position);
    if (spawnedRegistration != null && spawnWorld != null) {
      final updated = spawnedRegistration.withSpawn(
        spawnX: spawnWorld.dx,
        spawnY: spawnWorld.dy,
      );
      setState(() {
        _fleetRobots = [
          for (final robot in _fleetRobots)
            if (robot.robotId == spawnedRegistration.robotId)
              updated
            else
              robot,
        ];
        // 이미 만들어진 Gazebo launch 는 옛 좌표를 담고 있다.
        _isDeployed = false;
      });
      final waypoint = (runtimeNames[result.position] ?? '').trim();
      await _saveSettingToOpenProject(
        label: '로봇 시작 위치',
        detail:
            '${spawnedRegistration.robotId} · '
            '${waypoint.isEmpty ? '선택한 Waypoint' : waypoint} '
            '(${spawnWorld.dx.toStringAsFixed(3)}, '
            '${spawnWorld.dy.toStringAsFixed(3)}) · 다시 배포하고 백엔드를 재시작하세요.',
      );
    }
    _startMockRobotTimer();
  }

  void _toggleMockRobot(_MockRobot robot) {
    if (!robot.kind.isMobile) return;
    setState(() => robot.moving = !robot.moving);
  }

  void _removeMockRobot(_MockRobot robot) {
    setState(() {
      for (final task in _mockTasks.where(
        (task) =>
            task.robotId == robot.id &&
            (task.status == _MockTaskStatus.active ||
                task.status == _MockTaskStatus.queued),
      )) {
        task.status = _MockTaskStatus.failed;
      }
      _mockRobots.remove(robot);
    });
    robot.image?.dispose();
    _homeReservations.removeWhere((_, robotId) => robotId == robot.id);
    unawaited(_saveMockTasks());
  }

  Future<void> _createMockTask() async {
    // 작업은 맵 프로젝트에 속한다. 저장할 프로젝트가 없으면 만들 수 없다.
    if (_openProjectName == null) {
      await showMovableDialog<void>(
        context: context,
        builder: (dialogContext) => AlertDialog(
          icon: const Icon(Icons.info_outline, color: Color(0xFF2563EB)),
          title: const Text('먼저 맵 프로젝트를 저장하세요'),
          content: const SizedBox(
            width: 420,
            child: Text(
              '작업은 맵 프로젝트에 속합니다. 작업 단계가 그 맵의 Waypoint 좌표와 이름을 '
              '그대로 담기 때문에, 어느 맵의 작업인지 정해지지 않으면 목적지가 아무 곳도 '
              '가리키지 않습니다.\n\n'
              '맵 관리에서 `프로젝트 저장`으로 지도 이름을 정해 저장하거나, '
              '`프로젝트 열기`로 저장된 맵을 여세요.',
            ),
          ),
          actions: [
            FilledButton(
              onPressed: () => Navigator.pop(dialogContext),
              child: const Text('확인'),
            ),
          ],
        ),
      );
      return;
    }
    // Waypoint 는 편집 중인 프로젝트에도 있으므로, 그것만 확인하면 새 프로젝트를
    // 저장한 직후 배포하지 않고도 작업 편집기로 들어갈 수 있다. 작업은 RMF 가
    // 읽을 운영 산출물을 전제로 하므로 현재 프로젝트의 배포가 먼저다.
    final loadedOperationalMap =
        _robotDeployedMap != null &&
        !_robotDeployedMap!.summary.yamlPath.endsWith('.rmfproject') &&
        _robotDeployedMap!.summary.name == _openProjectName;
    if (!_isDeployed && !loadedOperationalMap) {
      final action = await showMovableDialog<String>(
        context: context,
        builder: (dialogContext) => AlertDialog(
          icon: const Icon(
            Icons.rocket_launch_outlined,
            color: Color(0xFFD97706),
            size: 36,
          ),
          title: const Text('먼저 맵을 배포하세요'),
          content: const SizedBox(
            width: 420,
            child: Text(
              '현재 프로젝트가 아직 배포되지 않았습니다. 로봇 작업을 만들기 전에 '
              '맵 관리에서 `배포하기`를 완료하세요.',
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext),
              child: const Text('닫기'),
            ),
            FilledButton.icon(
              onPressed: () => Navigator.pop(dialogContext, 'map'),
              icon: const Icon(Icons.map_outlined, size: 18),
              label: const Text('맵 관리로 이동'),
            ),
          ],
        ),
      );
      if (action == 'map' && mounted) {
        setState(() => _selectedMenu = _menuMap);
      }
      return;
    }
    final waypoints = _mobileRuntimeWaypoints;
    final names = _robotDeployedMap?.waypointNames ?? _waypointNames;
    final taskRobots = _mockRobots
        .where((robot) => robot.kind.canCarry)
        .toList();
    if (waypoints.isEmpty) {
      final action = await showMovableDialog<String>(
        context: context,
        builder: (dialogContext) => AlertDialog(
          icon: const Icon(
            Icons.info_outline,
            color: Color(0xFF2563EB),
            size: 36,
          ),
          title: const Text('작업 준비가 필요합니다'),
          content: Text(
            waypoints.isEmpty
                ? '작업을 생성하려면 먼저 배포된 맵을 불러와야 합니다.\n'
                      '그 다음 로봇 메뉴에서 시작 Waypoint를 선택해 로봇을 Spawn하세요.'
                : '운영 맵은 준비되었습니다. 로봇 메뉴에서 Pinky 또는 Mock 주행로봇을 Spawn한 뒤 작업을 생성하세요.',
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext),
              child: const Text('닫기'),
            ),
            if (waypoints.isEmpty)
              OutlinedButton.icon(
                onPressed: () => Navigator.pop(dialogContext, 'map'),
                icon: const Icon(Icons.folder_open_outlined, size: 18),
                label: const Text('배포 맵 불러오기'),
              ),
            FilledButton.icon(
              onPressed: () => Navigator.pop(dialogContext, 'robots'),
              icon: const Icon(Icons.smart_toy_outlined, size: 18),
              label: const Text('로봇 메뉴'),
            ),
          ],
        ),
      );
      if (action == 'map') await _loadMapForRobots();
      if (action == 'robots' && mounted) {
        setState(() => _selectedMenu = _menuRobots);
      }
      return;
    }
    final result = await showMovableDialog<_TaskEditorResult>(
      context: context,
      builder: (_) => _SequentialTaskEditorDialog(
        initialName: '연속 작업 ${_mockTasks.length + 1}',
        robots: taskRobots,
        workcellPolicies: _availableWorkcellPolicies,
        drawing: _robotRuntimeDrawing,
        lanes: _robotDeployedMap?.lanes ?? _recommendedLanes,
        waypoints: waypoints,
        waypointNames: names,
      ),
    );
    if (result == null || !mounted) return;
    final available = taskRobots
        .where((robot) => robot.activeTaskId == null)
        .toList();
    final robot = !result.startImmediately
        ? null
        : result.robotId == '__auto__'
        ? (available..sort((a, b) => b.battery.compareTo(a.battery)))
              .firstOrNull
        : available.where((item) => item.id == result.robotId).firstOrNull;
    if (result.startImmediately && robot == null) {
      _showProcessingWarning('작업 생성', '현재 작업을 수행할 수 있는 로봇이 없습니다.');
      return;
    }
    final steps = result.steps.map((draft) {
      final destination = draft.destination;
      final destinationName = destination == null
          ? null
          : (names[destination] ?? '').trim().isEmpty
          ? 'Waypoint ${waypoints.indexOf(destination) + 1}'
          : names[destination]!;
      return _MockTaskStep(
        type: draft.type,
        destination: destination,
        destinationName: destinationName,
        durationSeconds: draft.type == _TaskStepType.armLoad
            ? 9.6
            : draft.durationSeconds,
        policyId: draft.policyId,
      );
    }).toList();
    final task = _MockTask(
      id: _nextTaskId(),
      name: result.name,
      description: result.description,
      type: '연속 작업',
      robotId: robot?.id ?? result.robotId,
      steps: steps,
      trigger: result.trigger,
    );
    setState(() {
      task.status = result.startImmediately
          ? _MockTaskStatus.active
          : _MockTaskStatus.queued;
      _mockTasks.insert(0, task);
      if (robot != null) {
        robot.activeTaskId = task.id;
        _startTaskStep(robot, task);
      }
    });
    await _saveMockTasks();
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          result.startImmediately
              ? '${task.name} 작업을 MySQL에 저장하고 시작했습니다.'
              : '${task.name} 작업을 MySQL에 저장했습니다.',
        ),
      ),
    );
    _startMockRobotTimer();
  }

  Future<void> _editMockTask(_MockTask task) async {
    final waypoints = _mobileRuntimeWaypoints;
    final names = _robotDeployedMap?.waypointNames ?? _waypointNames;
    final taskRobots = _mockRobots
        .where((robot) => robot.kind.canCarry)
        .toList();
    if (waypoints.isEmpty) {
      _showProcessingWarning('작업 수정', '운영 맵을 먼저 준비해 주세요.');
      return;
    }
    final result = await showMovableDialog<_TaskEditorResult>(
      context: context,
      builder: (_) => _SequentialTaskEditorDialog(
        initialName: task.name,
        initialDescription: task.description,
        initialRobotId: task.robotId,
        initialSteps: task.steps
            .map(
              (step) => _TaskStepDraft(
                step.type,
                destination: step.destination,
                durationSeconds: step.durationSeconds,
                policyId: step.policyId,
              ),
            )
            .toList(),
        initialTrigger: task.trigger,
        editing: true,
        robots: taskRobots,
        workcellPolicies: _availableWorkcellPolicies,
        drawing: _robotRuntimeDrawing,
        lanes: _robotDeployedMap?.lanes ?? _recommendedLanes,
        waypoints: waypoints,
        waypointNames: names,
      ),
    );
    if (result == null || !mounted) return;
    final available = taskRobots
        .where(
          (robot) =>
              robot.activeTaskId == null || robot.activeTaskId == task.id,
        )
        .toList();
    final nextRobot = !result.startImmediately
        ? null
        : result.robotId == '__auto__'
        ? (available..sort((a, b) => b.battery.compareTo(a.battery)))
              .firstOrNull
        : available.where((robot) => robot.id == result.robotId).firstOrNull;
    if (result.startImmediately && nextRobot == null) {
      _showProcessingWarning('작업 수정', '선택한 로봇이 다른 작업을 수행 중입니다.');
      return;
    }
    final nextSteps = result.steps.map((draft) {
      final destination = draft.destination;
      final destinationName = destination == null
          ? null
          : (names[destination] ?? '').trim().isEmpty
          ? 'Waypoint ${waypoints.indexOf(destination) + 1}'
          : names[destination]!;
      return _MockTaskStep(
        type: draft.type,
        destination: destination,
        destinationName: destinationName,
        durationSeconds: draft.type == _TaskStepType.armLoad
            ? 9.6
            : draft.durationSeconds,
        policyId: draft.policyId,
      );
    }).toList();
    final previousRobot = _mockRobots
        .where((robot) => robot.activeTaskId == task.id)
        .firstOrNull;
    setState(() {
      if (previousRobot != null) {
        previousRobot
          ..activeTaskId = null
          ..moving = false
          ..targetWaypoint = null
          ..assignedRoute.clear();
        _homeReservations.removeWhere(
          (_, robotId) => robotId == previousRobot.id,
        );
      }
      task
        ..name = result.name
        ..description = result.description
        ..trigger = result.trigger
        ..robotId = nextRobot?.id ?? result.robotId
        ..currentStepIndex = 0
        ..status = result.startImmediately
            ? _MockTaskStatus.active
            : _MockTaskStatus.queued
        ..completedAt = null
        ..steps.clear()
        ..steps.addAll(nextSteps);
      if (nextRobot != null) {
        nextRobot.activeTaskId = task.id;
        _startTaskStep(nextRobot, task);
      }
    });
    await _saveMockTasks();
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          result.startImmediately
              ? '${task.name} 작업을 수정하고 다시 시작했습니다.'
              : '${task.name} 작업 수정 내용을 MySQL에 저장했습니다.',
        ),
      ),
    );
    _startMockRobotTimer();
  }

  Future<void> _runMockTask(_MockTask task) async {
    if (task.status == _MockTaskStatus.active) {
      _showProcessingWarning('작업 실행', '${task.name} 작업은 이미 실행 중입니다.');
      return;
    }
    final waypoints = _mobileRuntimeWaypoints;
    if (waypoints.isEmpty || task.steps.isEmpty) {
      _showProcessingWarning('작업 실행', '운영 맵과 실행 단계를 먼저 준비해 주세요.');
      return;
    }
    final available = _mockRobots
        .where((robot) => robot.kind.canCarry && robot.activeTaskId == null)
        .toList();
    final robot = task.robotId == '__auto__'
        ? (available..sort((a, b) => b.battery.compareTo(a.battery)))
              .firstOrNull
        : available.where((robot) => robot.id == task.robotId).firstOrNull;
    if (robot == null) {
      _showProcessingWarning(
        '작업 실행',
        task.robotId == '__auto__'
            ? '현재 작업 가능한 로봇이 없습니다.'
            : '${task.robotId} 로봇이 없거나 다른 작업을 수행 중입니다.',
      );
      return;
    }
    // 이 로봇의 ID 가 등록에 있는지 먼저 본다.
    //
    // 없으면 `_isRmfDriven` 이 조용히 거짓을 돌려주고, 앱은 RMF 에 넘기지 않은
    // 채 저 혼자 단계를 센다. 화면에서는 일하는 것처럼 보이는데 로봇은 가만히
    // 있는다 — 앱이 단계를 세는 것과 로봇이 실제로 가는 것이 따로 노는 그
    // 상태다. 조용히 넘기지 않고 멈춰 세운다.
    final unregistered = unregisteredRobotMessage(_fleetRobots, robot.id);
    if (unregistered != null) {
      await showWaypointErrorDialog(
        context,
        title: '작업 실행',
        message: unregistered,
      );
      return;
    }
    // 값의 출처가 Gazebo·실물인 로봇은 RMF 가 몬다. 앱이 단계를 세는 것과
    // 로봇이 실제로 가는 것이 따로 놀면 화면이 거짓말을 한다.
    final rmfDriven = _isRmfDriven(robot.id);
    setState(() {
      task
        ..robotId = robot.id
        ..status = _MockTaskStatus.active
        ..currentStepIndex = 0
        ..completedAt = null;
      for (final step in task.steps) {
        step
          ..status = _TaskStepStatus.pending
          ..remainingSeconds = 0
          ..failureReason = null;
      }
      robot
        ..activeTaskId = task.id
        ..rmfDriven = rmfDriven
        ..rmfTaskId = null
        ..rmfGoalX = null
        ..rmfGoalY = null;
      _startTaskStep(robot, task);
    });
    if (rmfDriven) {
      final result = await _submitTaskToRmf(robot, task);
      if (!mounted) return;
      if (!result.accepted) {
        setState(() => _failRobotTask(robot, task, 'RMF: ${result.message}'));
        await _saveMockTasks();
        if (!mounted) return;
        await showWaypointErrorDialog(
          context,
          title: '작업 실행',
          message:
              '${task.name} 을 RMF 가 받지 않았습니다.\n\n'
              '${result.message}',
        );
        return;
      }
      setState(() => robot.rmfTaskId = result.taskId);
      await RmfTaskBridge.instance.watch(
        _fleetSettingsFor(
          _robotDeployedMap?.summary.name ?? _mapName,
        ).fleetName,
      );
    }
    await _saveMockTasks();
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          rmfDriven
              ? '${task.name} 을 RMF 에 넘겼습니다. ${robot.id} 가 수행합니다.'
              : '${task.name} 작업을 ${robot.id}에 배정해 실행했습니다.',
        ),
      ),
    );
    _startMockRobotTimer();
  }

  Future<void> _deleteMockTask(_MockTask task) async {
    final confirmed = await showMovableDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        icon: const Icon(
          Icons.delete_outline,
          color: Color(0xFFDC2626),
          size: 36,
        ),
        title: const Text('작업 삭제'),
        content: Text('${task.name} 작업을 목록과 저장소에서 삭제할까요?'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('취소'),
          ),
          FilledButton.icon(
            style: FilledButton.styleFrom(
              backgroundColor: const Color(0xFFDC2626),
            ),
            onPressed: () => Navigator.pop(dialogContext, true),
            icon: const Icon(Icons.delete_outline, size: 18),
            label: const Text('삭제'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    final robot = _mockRobots
        .where((item) => item.activeTaskId == task.id)
        .firstOrNull;
    setState(() {
      if (robot != null) {
        robot
          ..activeTaskId = null
          ..moving = false
          ..targetWaypoint = null
          ..assignedRoute.clear();
        _homeReservations.removeWhere((_, robotId) => robotId == robot.id);
      }
      _mockTasks.remove(task);
    });
    await _saveMockTasks();
  }

  Future<void> _loadMapForRobots() async {
    try {
      final mapsFuture = listDeployedMaps();
      final selected = await showMovableDialog<DeployedMapSummary>(
        context: context,
        builder: (dialogContext) => AlertDialog(
          icon: const Icon(Icons.map_outlined, size: 36),
          title: const Text('배포된 맵 불러오기'),
          content: SizedBox(
            width: 560,
            height: 380,
            child: FutureBuilder<List<DeployedMapSummary>>(
              future: mapsFuture,
              builder: (context, snapshot) {
                if (snapshot.connectionState != ConnectionState.done) {
                  return const Center(
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        CircularProgressIndicator(),
                        SizedBox(height: 14),
                        Text('프로젝트의 배포 맵을 검색하고 있습니다…'),
                      ],
                    ),
                  );
                }
                if (snapshot.hasError) {
                  return Center(
                    child: SelectableText(
                      '맵 목록을 읽지 못했습니다.\n${snapshot.error}',
                      textAlign: TextAlign.center,
                    ),
                  );
                }
                final maps = snapshot.data ?? const [];
                if (maps.isEmpty) {
                  return const Center(
                    child: Text(
                      'rmf_maps에서 building.yaml 또는 rmfproject를 찾지 못했습니다.',
                      textAlign: TextAlign.center,
                    ),
                  );
                }
                return ListView.separated(
                  itemCount: maps.length,
                  separatorBuilder: (_, _) => const Divider(height: 1),
                  itemBuilder: (context, index) {
                    final map = maps[index];
                    final isProject = map.yamlPath.endsWith('.rmfproject');
                    return ListTile(
                      leading: Icon(
                        isProject
                            ? Icons.edit_document
                            : map.hasNavGraph
                            ? Icons.check_circle_outline
                            : Icons.warning_amber_outlined,
                        color: isProject
                            ? const Color(0xFF2563EB)
                            : map.hasNavGraph
                            ? const Color(0xFF15803D)
                            : const Color(0xFFD97706),
                      ),
                      title: Text(map.name),
                      subtitle: Text(
                        '${isProject
                            ? '저장된 RMF 프로젝트'
                            : map.hasNavGraph
                            ? 'nav graph 확인됨'
                            : 'nav graph 없음'}\n${map.yamlPath}',
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                      ),
                      onTap: () => Navigator.pop(dialogContext, map),
                    );
                  },
                );
              },
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext),
              child: const Text('취소'),
            ),
          ],
        ),
      );
      if (selected == null) return;
      final loaded = await loadDeployedMap(selected);
      if (!mounted) return;
      for (final robot in _mockRobots) {
        robot.image?.dispose();
      }
      setState(() {
        _robotDeployedMap = loaded;
        _mockRobots.clear();
        _homeReservations.clear();
        for (final task in _mockTasks.where(
          (task) =>
              task.status == _MockTaskStatus.active ||
              task.status == _MockTaskStatus.queued,
        )) {
          task
            ..status = _MockTaskStatus.queued
            ..currentStepIndex = 0
            ..completedAt = null;
          for (final step in task.steps) {
            step
              ..status = _TaskStepStatus.pending
              ..remainingSeconds = 0
              ..failureReason = null;
          }
        }
      });
      unawaited(_saveMockTasks());
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('${loaded.summary.name} 배포 맵을 불러왔습니다.')),
      );
    } catch (error) {
      _showProcessingWarning('배포 맵 불러오기', error);
      if (!mounted) return;
      await showMovableDialog<void>(
        context: context,
        builder: (dialogContext) => AlertDialog(
          icon: const Icon(Icons.error_outline, color: Color(0xFFDC2626)),
          title: const Text('배포 맵을 불러오지 못했습니다'),
          content: SelectableText('$error'),
          actions: [
            TextButton.icon(
              onPressed: () =>
                  Clipboard.setData(ClipboardData(text: error.toString())),
              icon: const Icon(Icons.copy_outlined, size: 18),
              label: const Text('오류 복사'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(dialogContext),
              child: const Text('확인'),
            ),
          ],
        ),
      );
    }
  }

  UploadedDrawing? get _robotRuntimeDrawing {
    final loaded = _robotDeployedMap;
    if (loaded == null) return _drawing;
    return UploadedDrawing(
      name: loaded.imageName,
      extension: loaded.imageName.split('.').last.toLowerCase(),
      size: loaded.imageBytes.length,
      bytes: loaded.imageBytes,
      pixelWidth: loaded.imageSize.width.round(),
      pixelHeight: loaded.imageSize.height.round(),
    );
  }

  @override
  void dispose() {
    _exitListener?.dispose();
    unawaited(_interruptSubscription?.cancel());
    _mockRobotTimer?.cancel();
    _orderDispatchTimer?.cancel();
    // 그리드맵·SLAM 미리보기는 GPU 쪽 자원이라 놔두면 안 돌아온다.
    _gridPreview?.dispose();
    _slamPreview?.dispose();
    // 구독을 남기면 `ros2 topic echo` 가 앱보다 오래 산다.
    unawaited(_telemetrySubscription?.cancel());
    unawaited(RobotTelemetryBridge.instance.stop());
    // 센서 파일을 읽는 타이머도 함께 멈춘다. 남겨 두면 앱이 사라진 뒤에도
    // 0.2초마다 디스크를 읽는다.
    unawaited(_sensorSubscription?.cancel());
    RobotSensorFeed.instance.stop();
    // RMF 진행 소식을 읽는 `ros2 topic echo` 도 함께 끊는다.
    unawaited(_rmfProgressSubscription?.cancel());
    unawaited(RmfTaskBridge.instance.stop());
    for (final robot in _mockRobots) {
      robot.image?.dispose();
    }
    _mapTransform.dispose();
    super.dispose();
  }

  void _toggleMeasurementMode() {
    if (_drawing?.isImage != true) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('이미지 도면에서 기준 길이를 선택할 수 있습니다.')),
      );
      return;
    }
    setState(() {
      _isMeasurementMode = !_isMeasurementMode;
      _isWallEraseMode = false;
      _isMeasurementSelected = false;
    });
  }

  void _selectMeasurement() {
    if (_measurement == null) return;
    setState(() => _isMeasurementSelected = true);
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Measurement 선을 선택했습니다. 휴지통으로 제거할 수 있습니다.')),
    );
  }

  void _removeMeasurement() {
    if (_measurement == null) return;
    _recordUndo();
    setState(() {
      _measurement = null;
      _isMeasurementSelected = false;
      _isMeasurementMode = false;
      _stage = MapStage.upload;
      _isDeployed = false;
    });
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: const Text('Measurement를 제거했습니다. 새 기준선을 선택할 수 있습니다.'),
        action: SnackBarAction(
          label: '새로 측정',
          textColor: Colors.white,
          onPressed: _toggleMeasurementMode,
        ),
      ),
    );
  }

  Future<void> _askMeasurement(Offset start, Offset end) async {
    final controller = TextEditingController(
      text: _measurement?.length.toString() ?? '',
    );
    var unit = _measurement?.unit ?? 'm';
    final result = await showMovableDialog<(double, String)>(
      context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (context, setDialogState) => AlertDialog(
          icon: const Icon(
            Icons.straighten,
            color: Color(0xFF2563EB),
            size: 34,
          ),
          title: Row(
            children: [
              const Expanded(child: Text('가로나 세로의 실제 길이는?')),
              IconButton(
                onPressed: () => Navigator.pop(dialogContext),
                icon: const Icon(Icons.close),
                tooltip: '닫기',
              ),
            ],
          ),
          content: SizedBox(
            width: 390,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  '선택한 기준선의 실제 길이와 단위를 입력하세요.',
                  style: TextStyle(color: Color(0xFF64748B)),
                ),
                const SizedBox(height: 20),
                const Text(
                  '길이 단위',
                  style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700),
                ),
                const SizedBox(height: 8),
                SegmentedButton<String>(
                  segments: const [
                    ButtonSegment(value: 'm', label: Text('미터 (m)')),
                    ButtonSegment(value: 'ft', label: Text('피트 (ft)')),
                  ],
                  selected: {unit},
                  onSelectionChanged: (value) =>
                      setDialogState(() => unit = value.first),
                ),
                const SizedBox(height: 18),
                TextField(
                  controller: controller,
                  autofocus: true,
                  keyboardType: const TextInputType.numberWithOptions(
                    decimal: true,
                  ),
                  decoration: InputDecoration(
                    labelText: '실제 길이',
                    hintText: unit == 'm' ? '예: 12.5' : '예: 40',
                    suffixText: unit,
                    border: const OutlineInputBorder(),
                  ),
                  onSubmitted: (_) {
                    final value = double.tryParse(controller.text.trim());
                    if (value != null && value > 0) {
                      Navigator.pop(dialogContext, (value, unit));
                    }
                  },
                ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext),
              child: const Text('다시 선택'),
            ),
            FilledButton(
              onPressed: () {
                final value = double.tryParse(controller.text.trim());
                if (value == null || value <= 0) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(content: Text('0보다 큰 실제 길이를 입력해주세요.')),
                  );
                  return;
                }
                Navigator.pop(dialogContext, (value, unit));
              },
              child: const Text('Measurement 저장'),
            ),
          ],
        ),
      ),
    );
    // showDialog completes when pop starts, while the route can still be
    // rebuilding during its reverse animation. Disposing immediately causes
    // "TextEditingController was used after being disposed" on registration.
    await Future<void>.delayed(const Duration(milliseconds: 350));
    controller.dispose();
    if (result == null || !mounted) return;
    _recordUndo();
    setState(() {
      _measurement = _MapMeasurement(
        start: start,
        end: end,
        length: result.$1,
        unit: result.$2,
      );
      _isMeasurementMode = false;
      _isMeasurementSelected = false;
      _stage = MapStage.measurement;
      _isDeployed = false;
    });
    await _saveSettingToOpenProject(
      label: 'Measurement',
      detail: '기준 길이 ${result.$1} ${result.$2}',
    );
  }

  void _eraseWalls(Rect imageArea) {
    final mask = _wallMask;
    if (mask == null) return;
    final remaining = mask.points
        .where((point) => !imageArea.contains(point))
        .toList();
    final removed = mask.points.length - remaining.length;
    if (removed == 0) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('선택한 영역에 제거할 벽이 없습니다.')));
      return;
    }
    _recordUndo();
    setState(() {
      _previousWallMask = mask;
      _wallMask = _WallMask(
        width: mask.width,
        height: mask.height,
        sampleSize: mask.sampleSize,
        points: remaining,
      );
      _isDeployed = false;
    });
    setState(() => _frozenAutoWalls = _wallSegments());
    ScaffoldMessenger.of(
      context,
    ).showSnackBar(SnackBar(content: Text('선택 영역에서 벽 후보 $removed개를 제거했습니다.')));
  }

  void _undoWallErase() {
    final previous = _previousWallMask;
    if (previous == null) return;
    _recordUndo();
    setState(() {
      _wallMask = previous;
      _previousWallMask = null;
    });
    ScaffoldMessenger.of(
      context,
    ).showSnackBar(const SnackBar(content: Text('마지막 벽 제거 작업을 되돌렸습니다.')));
  }

  void _toggleWallConnectMode() {
    setState(() {
      _isWallConnectMode = !_isWallConnectMode;
      _pendingWallVertex = null;
      _isWallEraseMode = false;
      _isMeasurementMode = false;
      _isWallEndpointEditMode = false;
    });
  }

  void _toggleWallEndpointEditMode() {
    setState(() {
      _isWallEndpointEditMode = !_isWallEndpointEditMode;
      _isWallConnectMode = false;
      _pendingWallVertex = null;
      _isWallEraseMode = false;
      _isMeasurementMode = false;
    });
  }

  void _moveWallEndpoint(Offset original, Offset updated) {
    _recordUndo();
    setState(() {
      Offset? source;
      for (final entry in _wallVertexOverrides.entries) {
        if ((entry.value - original).distance <= .01) {
          source = entry.key;
          break;
        }
      }
      _wallVertexOverrides[source ?? original] = updated;
      _isWallEndpointEditMode = false;
      _isDeployed = false;
    });
    ScaffoldMessenger.of(
      context,
    ).showSnackBar(const SnackBar(content: Text('Wall의 마지막 정점 위치를 수정했습니다.')));
  }

  Offset _overriddenVertex(Offset point) =>
      _wallVertexOverrides[point] ?? point;

  List<(Offset, Offset)> _applyWallVertexOverrides(
    List<(Offset, Offset)> walls,
  ) => [
    for (final wall in walls)
      (_overriddenVertex(wall.$1), _overriddenVertex(wall.$2)),
  ];

  double get _floorVertexSnapTolerance {
    final sampleTolerance = (_wallMask?.sampleSize ?? 2) * 9;
    final width = _drawing?.pixelWidth?.toDouble() ?? 0;
    final height = _drawing?.pixelHeight?.toDouble() ?? 0;
    final imageTolerance = width > 0 && height > 0
        ? math.min(width, height) * .025
        : 0.0;
    return math.max(sampleTolerance, imageTolerance);
  }

  void _selectWallConnectionVertex(Offset vertex) {
    final first = _pendingWallVertex;
    if (first == null) {
      setState(() => _pendingWallVertex = vertex);
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('연결할 두 번째 정점을 선택하세요.')));
      return;
    }
    if ((first - vertex).distance <= .01) return;
    final alreadyExists = _manualWalls.any(
      (wall) =>
          ((wall.$1 - first).distance <= .01 &&
              (wall.$2 - vertex).distance <= .01) ||
          ((wall.$2 - first).distance <= .01 &&
              (wall.$1 - vertex).distance <= .01),
    );
    if (!alreadyExists) _recordUndo();
    setState(() {
      if (!alreadyExists) _manualWalls.add((first, vertex));
      _pendingWallVertex = null;
      _isWallConnectMode = false;
      _isDeployed = false;
    });
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          alreadyExists ? '이미 연결된 Wall입니다.' : '두 정점을 Wall로 연결했습니다.',
        ),
      ),
    );
  }

  Future<void> _detectWalls() async {
    final drawing = _drawing;
    if (drawing == null || _isDetectingWalls) return;
    if (_wallsDetected) {
      _recordUndo();
      setState(() {
        _wallMask = null;
        _previousWallMask = null;
        _wallsDetected = false;
        _isWallEraseMode = false;
        _isWallConnectMode = false;
        _pendingWallVertex = null;
        _manualWalls.clear();
        _frozenAutoWalls = [];
        _isWallEndpointEditMode = false;
        _wallVertexOverrides.clear();
        _isDeployed = false;
        _stage = _floorGenerated
            ? MapStage.floor
            : _measurement != null
            ? MapStage.measurement
            : MapStage.upload;
      });
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('자동 인식된 벽을 제거했습니다.')));
      return;
    }
    if (!drawing.isImage || drawing.bytes == null) {
      _showProcessingWarning(
        '벽 자동 인식',
        'PDF와 CAD 도면은 직접 처리할 수 없습니다. PNG 또는 JPG로 변환해 주세요.',
      );
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('PDF와 CAD 도면은 이미지 변환 후 벽을 인식할 수 있습니다.')),
      );
      return;
    }

    setState(() {
      _isDetectingWalls = true;
      _isDeployed = false;
    });
    try {
      final codec = await ui.instantiateImageCodec(drawing.bytes!);
      final frame = await codec.getNextFrame();
      final image = frame.image;
      final data = await image.toByteData(format: ui.ImageByteFormat.rawRgba);
      if (data == null) throw StateError('이미지 픽셀을 읽을 수 없습니다.');

      final pixels = data.buffer.asUint8List();
      final width = image.width;
      final height = image.height;
      final stride = math.sqrt(width * height / 45000).ceil().clamp(2, 16);
      final points = <Offset>[];
      for (var y = 0; y < height; y += stride) {
        for (var x = 0; x < width; x += stride) {
          final index = (y * width + x) * 4;
          final red = pixels[index];
          final green = pixels[index + 1];
          final blue = pixels[index + 2];
          final alpha = pixels[index + 3];
          final luminance = red * .2126 + green * .7152 + blue * .0722;
          if (alpha > 80 && luminance < 105) {
            points.add(Offset(x.toDouble(), y.toDouble()));
          }
        }
      }
      image.dispose();
      codec.dispose();
      if (!mounted) return;
      _recordUndo();
      setState(() {
        _wallMask = _WallMask(
          width: width,
          height: height,
          sampleSize: stride.toDouble(),
          points: points,
        );
        _previousWallMask = null;
        _isWallEraseMode = false;
        _wallsDetected = true;
        _stage = MapStage.walls;
      });
      setState(() => _frozenAutoWalls = _wallSegments());
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('벽 후보 ${points.length}개 영역을 도면 위에 표시했습니다.')),
      );
    } catch (error) {
      if (!mounted) return;
      _showProcessingWarning('벽 자동 인식', error);
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text('벽 자동 인식에 실패했습니다: $error')));
    } finally {
      if (mounted) setState(() => _isDetectingWalls = false);
    }
  }

  Future<void> _generateFloor() async {
    final drawing = _drawing;
    if (drawing == null || _isGeneratingFloor) return;
    if (!drawing.isImage || drawing.bytes == null) {
      _showProcessingWarning(
        'Floor 생성',
        'PDF와 CAD 도면은 직접 처리할 수 없습니다. PNG 또는 JPG로 변환해 주세요.',
      );
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('PDF와 CAD 도면은 이미지 변환 후 Floor를 생성할 수 있습니다.'),
        ),
      );
      return;
    }

    setState(() {
      _isGeneratingFloor = true;
      _isDeployed = false;
    });
    try {
      final codec = await ui.instantiateImageCodec(drawing.bytes!);
      final frame = await codec.getNextFrame();
      final image = frame.image;
      final data = await image.toByteData(format: ui.ImageByteFormat.rawRgba);
      if (data == null) throw StateError('이미지 픽셀을 읽을 수 없습니다.');
      final pixels = data.buffer.asUint8List();
      final width = image.width;
      final height = image.height;
      final stride = math.sqrt(width * height / 32000).ceil().clamp(3, 18);
      final wallPoints = _wallMask?.points;
      final bounds = wallPoints == null || wallPoints.isEmpty
          ? Rect.fromLTWH(width * .04, height * .04, width * .92, height * .92)
          : _pointsBounds(wallPoints)
                .inflate(stride * 2)
                .intersect(
                  Rect.fromLTWH(0, 0, width.toDouble(), height.toDouble()),
                );
      final points = <Offset>[];
      for (var y = 0; y < height; y += stride) {
        for (var x = 0; x < width; x += stride) {
          final point = Offset(x.toDouble(), y.toDouble());
          if (!bounds.contains(point)) continue;
          final index = (y * width + x) * 4;
          final red = pixels[index];
          final green = pixels[index + 1];
          final blue = pixels[index + 2];
          final alpha = pixels[index + 3];
          final luminance = red * .2126 + green * .7152 + blue * .0722;
          if (alpha > 80 && luminance > 150) points.add(point);
        }
      }
      image.dispose();
      codec.dispose();
      if (!mounted) return;
      _recordUndo();
      setState(() {
        _floorMask = _WallMask(
          width: width,
          height: height,
          sampleSize: stride.toDouble(),
          points: points,
        );
        _floorGenerated = true;
        _stage = MapStage.floor;
      });
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('선택한 색상으로 Floor 영역을 생성했습니다.')),
      );
    } catch (error) {
      if (!mounted) return;
      _showProcessingWarning('Floor 생성', error);
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text('Floor 생성에 실패했습니다: $error')));
    } finally {
      if (mounted) setState(() => _isGeneratingFloor = false);
    }
  }

  Rect _pointsBounds(List<Offset> points) {
    var left = points.first.dx;
    var top = points.first.dy;
    var right = left;
    var bottom = top;
    for (final point in points.skip(1)) {
      left = math.min(left, point.dx);
      top = math.min(top, point.dy);
      right = math.max(right, point.dx);
      bottom = math.max(bottom, point.dy);
    }
    return Rect.fromLTRB(left, top, right, bottom);
  }

  /// 지금 프로젝트의 이름. 맵 디렉터리·building.yaml·플릿 이름이 다 여기서 나온다.
  ///
  /// 사람이 정한 이름이 있으면 그것이다. 없을 때만 도면 파일 이름으로 흘러가는데,
  /// 그건 `새 프로젝트` 없이 도면부터 올린 경우의 임시 이름이다 — 저장할 때
  /// 이름을 물으므로 그대로 굳지 않는다.
  String get _mapName {
    final chosen = _projectName?.trim();
    if (chosen != null && chosen.isNotEmpty) return chosen;
    final name = _drawing?.name.split('.').first.trim() ?? 'warehouse';
    return name.isEmpty ? 'warehouse' : name;
  }

  String get _yamlFileName => _yamlFileNameFor(_mapName);

  String _yamlFileNameFor(String mapName) {
    final safeName = mapName.replaceAll(RegExp(r'[^a-zA-Z0-9가-힣_-]'), '_');
    return '$safeName.building.yaml';
  }

  String get _deploymentMapName =>
      _mapName.replaceAll(RegExp(r'[^a-zA-Z0-9가-힣_-]'), '_');

  String _fileNameFromPath(String path) => path.split(RegExp(r'[/\\]')).last;

  String get _activeBuildingYamlName {
    final loaded = _robotDeployedMap?.summary;
    if (loaded != null && loaded.yamlPath.endsWith('.building.yaml')) {
      return _fileNameFromPath(loaded.yamlPath);
    }
    final name = loaded?.name ?? _mapName;
    final safeName = name.replaceAll(RegExp(r'[^a-zA-Z0-9가-힣_-]'), '_');
    return '$safeName.building.yaml';
  }

  String get _activeMapSourceName {
    final loaded = _robotDeployedMap?.summary;
    if (loaded != null) return _fileNameFromPath(loaded.yamlPath);
    return _projectFileName ?? '저장 전 편집 작업';
  }

  String _yamlEscape(String value) =>
      value.replaceAll(r'\', r'\\').replaceAll('"', r'\"');

  List<double> _encodeOffset(Offset point) => [point.dx, point.dy];

  Offset _decodeOffset(dynamic value) {
    final values = value as List<dynamic>;
    return Offset((values[0] as num).toDouble(), (values[1] as num).toDouble());
  }

  Map<String, dynamic>? _encodeMask(_WallMask? mask) => mask == null
      ? null
      : {
          'width': mask.width,
          'height': mask.height,
          'sampleSize': mask.sampleSize,
          'points': mask.points.map(_encodeOffset).toList(),
        };

  _WallMask? _decodeMask(dynamic value) {
    if (value == null) return null;
    final data = value as Map<String, dynamic>;
    return _WallMask(
      width: data['width'] as int,
      height: data['height'] as int,
      sampleSize: (data['sampleSize'] as num).toDouble(),
      points: (data['points'] as List<dynamic>).map(_decodeOffset).toList(),
    );
  }

  List<List<List<double>>> _encodeLines(List<(Offset, Offset)> lines) => [
    for (final line in lines) [_encodeOffset(line.$1), _encodeOffset(line.$2)],
  ];

  List<(Offset, Offset)> _decodeLines(dynamic value) => [
    for (final line in value as List<dynamic>)
      (_decodeOffset((line as List<dynamic>)[0]), _decodeOffset(line[1])),
  ];

  Map<String, dynamic> _encodeLaneProjectData((Offset, Offset) lane) {
    final data = <String, dynamic>{
      'start': _encodeOffset(lane.$1),
      'end': _encodeOffset(lane.$2),
      'direction': _laneDirections[lane] ?? '양방향',
    };
    final speed = _laneSpeedLimits[lane];
    final orientation = _laneOrientations[lane];
    final mutex = _laneMutexGroups[lane];
    if (speed != null) data['speedLimit'] = speed;
    if (orientation != null) data['orientation'] = orientation;
    if (mutex != null) data['mutex'] = mutex;
    return data;
  }

  Map<String, dynamic> _buildProjectData({String? mapName}) {
    final drawing = _drawing;
    return {
      'format': 'robosapiens-map-project',
      // v2: Waypoint 카테고리 이름이 바뀌었다. v1 의 '일반'(holding point)이
      // '대기'가 되고, v1 의 '대기'(parking spot)가 '주차'가 된다. '대기'가
      // 양쪽 버전에 다른 뜻으로 존재하므로 이 번호로만 구분할 수 있다.
      'version': 2,
      'mapName': mapName ?? _mapName,
      'mapScenarioSummary': _mapScenarioSummary,
      // Nav2 가 도면 지도 대신 SLAM 지도를 띄울지. 프로젝트에 딸린 선택이다 —
      // 같은 창고라도 시뮬레이션은 도면 지도로, 실물은 SLAM 지도로 돈다.
      'useSlamMap': _useSlamMap,
      // 격자 해상도를 무엇으로 정했는지도 프로젝트에 딸린다. 작은 아레나와 큰
      // 창고가 같은 설정을 쓸 수 없다.
      'gridResolution': {
        'mode': _gridResolutionMode.name,
        'targetWidth': _gridTargetWidth,
        'targetHeight': _gridTargetHeight,
        'padToTarget': _gridPadToTarget,
        'manualMeters': _gridManualResolution,
      },
      'robotSafety': {
        'widthMeters': _robotWidthMeters,
        'turningRadiusMeters': _turningRadiusMeters,
        'localizationMarginMeters': _localizationMarginMeters,
      },
      // 도면에 없는 값이라 프로젝트가 들고 있어야 한다. 안 남기면 열 때마다
      // 2.5m 로 돌아가고, 배포한 월드의 벽 높이가 조용히 바뀐다.
      'wallHeightMeters': _wallHeightMeters,
      // 비어 있으면 로봇 폭으로 그린다는 뜻이다.
      'manualLaneDisplayWidth': _manualLaneDisplayWidth,
      // 도메인이 어긋나면 아무 오류 없이 아무것도 안 통한다. 프로젝트가 들고
      // 있어야 앱에서 띄우든 터미널에서 띄우든 같은 망을 쓴다.
      'rosDomainId': _rosDomainId,
      'drawing': drawing == null
          ? null
          : {
              'name': drawing.name,
              'extension': drawing.extension,
              'size': drawing.size,
              'bytes': drawing.bytes == null
                  ? null
                  : base64Encode(drawing.bytes!),
              'pixelWidth': drawing.pixelWidth,
              'pixelHeight': drawing.pixelHeight,
            },
      'stage': _stage.index,
      'measurement': _measurement == null
          ? null
          : {
              'start': _encodeOffset(_measurement!.start),
              'end': _encodeOffset(_measurement!.end),
              'length': _measurement!.length,
              'unit': _measurement!.unit,
            },
      'wallMask': _encodeMask(_wallMask),
      'floorMask': _encodeMask(_floorMask),
      'previousWallMask': _encodeMask(_previousWallMask),
      'wallsDetected': _wallsDetected,
      'floorGenerated': _floorGenerated,
      'wallColor': _wallColor.toARGB32(),
      'floorColor': _floorColor.toARGB32(),
      'manualWalls': _encodeLines(_manualWalls),
      'wallVertexOverrides': [
        for (final entry in _wallVertexOverrides.entries)
          {'from': _encodeOffset(entry.key), 'to': _encodeOffset(entry.value)},
      ],
      'frozenAutoWalls': _encodeLines(_frozenAutoWalls),
      'recommendedLanes': _encodeLines(_recommendedLanes),
      'laneDirections': [
        for (final lane in _recommendedLanes) _encodeLaneProjectData(lane),
      ],
      'waypoints': [
        for (final point in _laneWaypoints)
          {
            'point': _encodeOffset(point),
            'name': _waypointNames[point] ?? '',
            'category': _waypointTypes[point] ?? '대기',
          },
      ],
      'activeLaneEndpoint': _activeLaneEndpoint == null
          ? null
          : _encodeOffset(_activeLaneEndpoint!),
    };
  }

  Future<bool> _writeProject({required String mapName}) async {
    if (_drawing == null) return false;
    try {
      final fileName = projectFileName(mapName);
      final bytes = Uint8List.fromList(
        utf8.encode(jsonEncode(_buildProjectData(mapName: mapName))),
      );
      final path = await saveProjectFile(mapName, bytes);
      if (!mounted) return false;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('$fileName 작업을 project 디렉터리에 저장했습니다.\n$path')),
      );
      setState(() => _projectFileName = fileName);
      return true;
    } catch (error) {
      if (!mounted) return false;
      _showProcessingWarning('작업 저장', error);
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text('작업을 저장하지 못했습니다: $error')));
      return false;
    }
  }

  Future<void> _saveProject() async {
    if (_drawing == null) return;
    await _writeProject(mapName: _mapName);
  }

  Future<void> _saveProjectAs() async {
    if (_drawing == null) return;
    final controller = TextEditingController(text: '$_mapName 복사본');
    final newName = await showMovableDialog<String>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        icon: const Icon(Icons.drive_file_rename_outline, size: 36),
        title: const Text('다른 이름으로 저장'),
        content: SizedBox(
          width: 390,
          child: TextField(
            controller: controller,
            autofocus: true,
            decoration: const InputDecoration(
              labelText: '새 맵 이름',
              helperText: '프로젝트 내부 이름과 파일명에 함께 적용됩니다.',
              border: OutlineInputBorder(),
            ),
            onSubmitted: (value) {
              final name = value.trim();
              if (name.isNotEmpty) Navigator.pop(dialogContext, name);
            },
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext),
            child: const Text('취소'),
          ),
          FilledButton.icon(
            onPressed: () {
              final name = controller.text.trim();
              if (name.isNotEmpty) Navigator.pop(dialogContext, name);
            },
            icon: const Icon(Icons.save_as_outlined, size: 18),
            label: const Text('project에 저장'),
          ),
        ],
      ),
    );
    controller.dispose();
    if (newName == null || !mounted) return;
    final saved = await _writeProject(mapName: newName);
    if (!saved || !mounted) return;
    setState(() {
      _projectName = newName;
      _isDeployed = false;
    });
  }

  /// 지금 편집 상태를 [mapName] 프로젝트로 MySQL에 쓴다.
  ///
  /// 배포 쪽이 앱을 거치지 않고 바로 집어갈 수 있도록 YAML도 같이 넣는다.
  /// 아직 YAML로 만들 수 없는 단계(벽·Floor 미완성 등)여도 저장 자체는 막지
  /// 않는다 — 작업 중인 맵을 못 저장하게 하는 게 더 나쁘다.
  /// 이 프로젝트에 쓸 플릿 설정. 프로필 반경은 맵의 로봇 안전 기준에서 온다.
  ///
  /// 같은 값을 두 곳에 적으면 어긋나므로, 사용자가 이미 넣은 로봇 폭과 위치
  /// 오차 여유를 그대로 가져다 쓴다.
  RmfFleetSettings _fleetSettingsFor(String mapName) {
    final named = _fleetSettings.fleetName.trim().isEmpty
        ? _fleetSettings.copyWith(fleetName: _fleetNameFor(mapName))
        : _fleetSettings;
    return named.withRobotSafety(
      widthMeters: _robotWidthMeters,
      localizationMarginMeters: _localizationMarginMeters,
    );
  }

  /// 이 프로젝트의 배포 디렉터리. launch 가 가리킬 경로다.
  ///
  /// 맵마다 따로이므로 프로젝트를 바꿔도 서로 덮어쓰지 않는다.
  String _mapDirectoryFor(String mapName) {
    final root =
        Platform.environment['RMF_ROOT'] ??
        '${Platform.environment['HOME'] ?? '~'}/robosapiens';
    return '$root/rmf_maps/${safeMapDirectoryName(mapName)}';
  }

  /// 지도 이름에서 만든 기본 플릿 이름. YAML 식별자로 쓸 수 있게 다듬는다.
  String _fleetNameFor(String mapName) {
    final safe = mapName.replaceAll(RegExp(r'[^a-zA-Z0-9가-힣_-]'), '_');
    return safe.isEmpty ? 'pinky' : '${safe}_pinky';
  }

  /// 이번 저장에서 무엇이 달라졌는지 알아낸다.
  ///
  /// map_project_files 는 덮어쓰기라 지금 모습만 남는다. 언제 무엇을 바꿨는지
  /// 따로 적어 두지 않으면, 어제까지 되던 것이 오늘 안 될 때 그 사이에 무엇이
  /// 달라졌는지 알 길이 없다.
  ///
  /// 바뀐 것이 없으면 빈 목록을 준다. 저장을 누를 때마다 줄이 늘면 무엇이
  /// 실제로 달라졌는지 오히려 안 보인다.
  Future<List<MapProjectChange>> _diffMapProject(
    String mapName,
    RmfFleetSettings fleet,
    List<MapProjectFile> files,
  ) async {
    Map<String, dynamic>? storedFleet;
    var storedFiles = <MapProjectFile>[];
    var isNew = false;
    try {
      storedFleet = await loadMapProjectFleet(mapName);
      storedFiles = await loadMapProjectFiles(mapName);
      isNew = storedFleet == null && storedFiles.isEmpty;
    } catch (_) {
      // 읽지 못하면 비교할 것이 없다. 기록을 남기지 못해도 저장은 막지 않는다.
      return const [];
    }
    final changes = <MapProjectChange>[];
    if (isNew) {
      changes.add(
        MapProjectChange(
          category: 'project',
          action: 'added',
          target: mapName,
          summary: '프로젝트를 처음 저장했습니다.',
        ),
      );
    }

    // 로봇 등록
    final before = <String, RmfProjectRobot>{
      for (final row
          in ((storedFleet?['robots'] as List<dynamic>?) ?? const [])
              .cast<Map<String, dynamic>>())
        row['robotId'] as String: RmfProjectRobot.fromJson({
          ...row,
          'zones': (row['zonesText'] as String? ?? '')
              .split(',')
              .map((zone) => zone.trim())
              .where((zone) => zone.isNotEmpty)
              .toList(),
        }),
    };
    final after = {for (final robot in _fleetRobots) robot.robotId: robot};
    for (final id in after.keys) {
      final now = after[id]!;
      final old = before[id];
      if (old == null) {
        changes.add(
          MapProjectChange(
            category: 'robot',
            action: 'added',
            target: id,
            summary:
                '${now.displayName} · ${now.kind.label} · ${now.model} · '
                '자리 ${now.chargerWaypoint ?? '미지정'}',
          ),
        );
        continue;
      }
      final diffs = <String>[
        if (old.displayName != now.displayName)
          '이름 ${old.displayName} → ${now.displayName}',
        if (old.kind != now.kind) '종류 ${old.kind.label} → ${now.kind.label}',
        if (old.model != now.model) '모델 ${old.model} → ${now.model}',
        if (old.gzName != now.gzName) 'gz 이름 ${old.gzName} → ${now.gzName}',
        if (old.chargerWaypoint != now.chargerWaypoint)
          '자리 ${old.chargerWaypoint ?? '미지정'} → '
              '${now.chargerWaypoint ?? '미지정'}',
        if (old.zones.join(',') != now.zones.join(','))
          '구획 ${old.zones.join('·')} → ${now.zones.join('·')}',
      ];
      if (diffs.isNotEmpty) {
        changes.add(
          MapProjectChange(
            category: 'robot',
            action: 'changed',
            target: id,
            summary: diffs.join(' · '),
          ),
        );
      }
    }
    for (final id in before.keys) {
      if (after.containsKey(id)) continue;
      changes.add(
        MapProjectChange(
          category: 'robot',
          action: 'removed',
          target: id,
          summary: '${before[id]!.displayName} 등록을 해제했습니다.',
        ),
      );
    }

    // 플릿 설정 — 값이 바뀐 항목만 적는다.
    final oldFleet = storedFleet == null
        ? null
        : RmfFleetSettings.fromJson(
            storedFleet['settings'] as Map<String, dynamic>,
          );
    if (oldFleet != null) {
      final oldJson = oldFleet.toJson();
      final newJson = fleet.toJson();
      final fields = <String>[
        for (final key in newJson.keys)
          if ('${oldJson[key]}' != '${newJson[key]}')
            '$key ${oldJson[key]} → ${newJson[key]}',
      ];
      if (fields.isNotEmpty) {
        changes.add(
          MapProjectChange(
            category: 'fleet',
            action: 'changed',
            target: fleet.fleetName,
            summary: fields.join(' · '),
          ),
        );
      }
    }

    // 생성 파일 — 내용이 달라진 것만.
    final oldContents = {
      for (final file in storedFiles) file.fileName: file.content,
    };
    for (final file in files) {
      final old = oldContents[file.fileName];
      if (old == null) {
        if (!isNew) {
          changes.add(
            MapProjectChange(
              category: 'file',
              action: 'added',
              target: file.fileName,
              summary: file.description,
            ),
          );
        }
      } else if (old != file.content) {
        changes.add(
          MapProjectChange(
            category: 'file',
            action: 'changed',
            target: file.fileName,
            summary: '내용이 달라졌습니다.',
          ),
        );
      }
    }
    final newNames = {for (final file in files) file.fileName};
    for (final name in oldContents.keys) {
      if (newNames.contains(name)) continue;
      changes.add(
        MapProjectChange(
          category: 'file',
          action: 'removed',
          target: name,
          summary: '더 이상 만들어지지 않습니다.',
        ),
      );
    }
    return changes;
  }

  /// 설비 로봇과 그 로봇이 맡을 픽업·드랍오프 자리를 짝지운다.
  ///
  /// 등록에는 이 짝이 없다 — 설비 로봇에는 `station: 설비2` 만 적혀 있고 그것은
  /// nav graph 에 없는 이름이다. 그래서 **자리로** 짝을 짓는다. 설비를 그
  /// Waypoint 옆에 세워 두는 것이 애초에 그 일을 시키려는 뜻이다.
  ///
  /// 맡을 설비가 없는 자리는 [_nav2Warnings] 로 알린다. 조용히 넘기면 그 자리로
  /// 보내는 작업이 RMF 안에서 영원히 멈춘다.
  WorkcellPairingResult _workcellPairing(
    String mapName,
    List<RmfProjectRobot> robots,
  ) {
    final scale = _metersPerPixel;
    if (scale == null || scale <= 0) {
      // 축척이 없으면 자리를 미터로 옮길 수 없다. 짝을 못 짓는 것과 자리가
      // 없는 것은 다르므로 빈 결과를 준다.
      return const WorkcellPairingResult(
        pairings: [],
        unservedWaypoints: [],
        idleWorkcells: [],
      );
    }
    final types = _waypointTypes.isNotEmpty
        ? _waypointTypes
        : (_robotDeployedMap?.waypointCategories ?? const <Offset, String>{});
    final names = _waypointTypes.isNotEmpty
        ? _waypointNames
        : (_robotDeployedMap?.waypointNames ?? const <Offset, String>{});
    final stations = <WorkcellStation>[];
    for (final entry in names.entries) {
      final name = entry.value.trim();
      if (name.isEmpty) continue;
      final category = types[entry.key];
      final isPickup = category == '픽업';
      final isDropoff = category == '드랍오프';
      if (!isPickup && !isDropoff) continue;
      // 로봇 spawn 과 같은 자로 재야 한다. 화면 좌표는 원점도 y 방향도 RMF 와
      // 다르다 — 섞으면 짝이 통째로 어긋난다.
      final world = rmfWorldFromPixel(entry.key.dx, entry.key.dy, scale);
      stations.add(
        WorkcellStation(
          name: name,
          x: world.x,
          y: world.y,
          isDispenser: isPickup,
        ),
      );
    }
    return pairWorkcells(robots: robots, stations: stations);
  }

  Future<void> _writeMapProject(String mapName) async {
    // 어느 경로로 저장하든 그리드맵 설정도 함께 나간다(`_buildProjectData`).
    // 그러니 기준도 함께 옮긴다 — 안 그러면 다른 화면에서 저장한 뒤에도
    // 그리드맵 화면이 계속 "저장할 것 있음" 으로 남는다.
    final gridSnapshot = _currentGridSettings;
    String? buildingYaml;
    try {
      buildingYaml = _buildBuildingYaml(mapName: mapName);
    } catch (_) {
      buildingYaml = null;
    }
    await saveMapProject(
      mapName: mapName,
      payloadJson: jsonEncode(_buildProjectData(mapName: mapName)),
      buildingYaml: buildingYaml,
      buildingYamlName: buildingYaml == null ? null : _yamlFileNameFor(mapName),
    );

    // 도면을 이 프로젝트 디렉터리에도 한 장 남긴다. 원장은 MySQL 이지만
    // 배포 스크립트와 building.yaml 의 `drawing.filename` 은 파일을 본다.
    // 실패해도 저장 자체는 이어 간다 — 원장은 이미 들어갔다.
    final drawing = _drawing;
    if (drawing != null && drawing.bytes != null) {
      try {
        await exportProjectDrawing(
          mapName: mapName,
          fileName: drawing.name,
          bytes: drawing.bytes!,
        );
      } catch (_) {
        // 디스크가 막혔을 뿐이다. 다음 배포에서 다시 쓴다.
      }
    }

    // 플릿 설정과 그로부터 만든 설정 파일을 함께 남긴다. 프로젝트 하나만 열면
    // 배포와 실행에 필요한 것이 다 있어야 한다.
    final fleet = _fleetSettingsFor(mapName);
    // 화면이 로봇을 안 들고 있으면 로봇은 건드리지 않는다. 빈 목록으로
    // 덮어쓰면 다른 화면에서 등록해 둔 로봇이 통째로 지워진다.
    if (_fleetRobots.isNotEmpty) {
      await saveMapProjectFleet(
        mapName,
        settings: fleet.toJson(),
        robots: [
          for (final robot in _fleetRobots)
            {...robot.toJson(), 'zonesText': robot.zones.join(',')},
        ],
      );
    } else {
      await saveMapProjectFleetSettings(mapName, fleet.toJson());
    }
    // 산출물은 **이 맵에 저장된 로봇**에서 만든다. 화면이 들고 있는 목록을
    // 그대로 쓰면, 다른 화면에서 등록해 둔 로봇이 빠진 채로 배포된다. 실제로
    // MySQL 에는 로봇 셋이 있는데 fleet.yaml 은 "등록된 로봇이 없다" 였고,
    // bringup 에 로봇이 하나도 안 실려 Gazebo 에 아무것도 안 올라갔다.
    final deployRobots = await _fleetRobotsForDeploy(mapName);
    final mapDirectory = _mapDirectoryFor(mapName);
    final now = DateTime.now();
    // 벤더 파라미터를 로봇마다 다시 쓴다. 벤더 패키지가 없으면 이 파일만
    // 빠지고 나머지는 그대로 만들어진다.
    final nav2 = _rewriteNav2ParamsForRobots();
    final files = <MapProjectFile>[
      if (buildingYaml != null)
        MapProjectFile(
          fileName: _yamlFileNameFor(mapName),
          kind: 'building',
          description:
              'Open-RMF 건물 맵. 벽·바닥·Waypoint·Lane 을 담는다. '
              '배포 스크립트가 이 파일에서 nav_graphs/0.yaml 을 만든다.',
          content: buildingYaml,
          generatedAt: now,
        ),
      MapProjectFile(
        fileName: '${fleet.fleetName}_config.yaml',
        kind: 'fleet_adapter',
        description:
            'Fleet adapter 설정. 로봇 속도·회전 한계, 프로필 반경(맵의 로봇 안전 '
            '기준에서 계산), 배터리, 로봇별 충전 Waypoint 를 담는다. '
            'ros2 launch 의 config_file 로 들어간다.',
        content: buildFleetAdapterYaml(
          fleet: fleet,
          robots: deployRobots,
          mapName: mapName,
        ),
        generatedAt: now,
      ),
      MapProjectFile(
        fileName: 'fleet.yaml',
        kind: 'fleet_sim',
        description:
            'Gazebo 에 띄울 로봇 목록. spawn 좌표는 이 맵의 충전 Waypoint 에서 '
            '가져왔다. 관제 배차의 입찰 자격이 되는 3온도 구획도 여기 있다.',
        content: buildFleetSimYaml(robots: deployRobots, mapName: mapName),
        generatedAt: now,
      ),
      MapProjectFile(
        fileName: '$mapName.launch.xml',
        kind: 'launch',
        description:
            'Open-RMF 실행. schedule node·building map server·supervisor·'
            'dispatcher 를 띄운다. 플릿은 '
            '${projectUsesNav2(_fleetRobots) ? '${mapName}_nav2.launch.xml 이 띄운다 — rmf_demos_fleet_adapter 는 slotcar 전용이라 토픽으로 도는 로봇에게는 상대가 없다.' : '이 launch 가 함께 붙인다.'} '
            '순서가 뒤집히면 fleet adapter 가 schedule node 를 못 찾는다.',
        content: buildProjectLaunchXml(
          mapName: mapName,
          fleetName: fleet.fleetName,
          mapDirectory: mapDirectory,
          buildingYamlName: _yamlFileNameFor(mapName),
          robots: deployRobots,
          laneWidth: _laneDisplayWidth,
          // RViz 가 로봇을 그릴 공 크기. 안 넘기면 상류 기본값 0.5m 가 되어
          // 지름 1m 짜리 덩어리가 도면을 덮는다.
          footprintRadius: fleet.footprintRadius,
        ),
        generatedAt: now,
      ),
      MapProjectFile(
        fileName: '$mapName.rviz',
        kind: 'rviz',
        description:
            'RViz 설정. 카메라가 이 도면을 보고, 바닥 그림을 /floorplan 에서 '
            '받는다. RMF 가 딸려 주는 rmf.rviz 는 office 데모 자리를 보고 있고 '
            '토픽 이름도 /floor_plan 이라 창은 뜨는데 까맣다.',
        content: buildProjectRvizConfig(
          mapName: mapName,
          robots: deployRobots,
          extent: _floorBounds,
        ),
        generatedAt: now,
      ),
      MapProjectFile(
        fileName: '${mapName}_bringup.launch.xml',
        kind: 'bringup',
        description:
            'Gazebo 에 이 맵의 월드와 로봇을 올린다. 로봇마다 네임스페이스를 '
            '나눠 /<로봇>/odom 처럼 토픽을 구분한다.',
        content: buildProjectBringupXml(
          mapName: mapName,
          robots: deployRobots,
          mapDirectory: mapDirectory,
        ),
        generatedAt: now,
      ),
      MapProjectFile(
        fileName: '${mapName}_nav2.launch.xml',
        kind: 'nav2',
        description:
            '이 프로젝트의 Nav2. 건물 지도(map_server)는 하나만 띄우고 이동 '
            '로봇마다 제 Nav2 를 붙인다. 로봇들은 map 프레임을 함께 쓰고 '
            '<로봇>/odom 만 서로 다르다. 아직 RMF 와 이어지지 않아 따로 돈다.',
        content: buildProjectNav2LaunchXml(
          mapName: mapName,
          robots: deployRobots,
          fleetName: fleet.fleetName,
          // SLAM 지도를 쓰기로 골랐으면 map_server 가 그것을 띄운다. 이걸
          // 넘기지 않으면 지도를 올려도 계속 도면 지도가 뜬다.
          mapYamlName: _useSlamMap ? slamYamlName(mapName) : null,
          warnings: nav2.warnings,
        ),
        generatedAt: now,
      ),
      MapProjectFile(
        fileName: '${mapName}_workcell.py',
        kind: 'nav2',
        description:
            '설비 로봇을 RMF 의 워크셀로 잇는다. 로봇이 픽업 자리에 닿으면 '
            'RMF 가 그 자리 이름으로 부르는데, 답하는 노드가 없으면 RMF 는 '
            '영원히 기다린다 — 오류는 안 나고 작업만 멈춘다.',
        executable: true,
        content: buildWorkcellScript(
          mapName: mapName,
          pairing: _workcellPairing(mapName, deployRobots),
          policies: _workcellPolicyModels,
        ),
        generatedAt: now,
      ),
      MapProjectFile(
        fileName: '${mapName}_sensor_relay.py',
        kind: 'nav2',
        description:
            '로봇의 라이다와 카메라를 앱이 읽을 수 있게 파일로 내려 준다. '
            '앱에는 rclpy 가 없고 카메라 영상은 ros2 topic echo 로 읽기에 '
            '너무 크다 — 1280×720 한 장이 YAML 로 2.7MB 다.',
        executable: true,
        content: buildSensorRelayScript(mapName: mapName, robots: deployRobots),
        generatedAt: now,
      ),
      MapProjectFile(
        fileName: '${mapName}_nav2_adapter.py',
        kind: 'nav2',
        description:
            'RMF 와 Nav2 를 잇는다. RMF 가 주는 목적지를 NavigateToPose 로 '
            '바꾸고 TF 에서 읽은 위치를 RMF 에 되돌린다. 이것이 없으면 RMF 가 '
            '배차해도 로봇이 안 움직인다 — rmf_demos_fleet_adapter 는 slotcar '
            '전용이라 우리 핑키에게는 상대가 없다.',
        executable: true,
        content: buildNav2FleetAdapterScript(
          mapName: mapName,
          fleetName: fleet.fleetName,
          robots: deployRobots,
        ),
        generatedAt: now,
      ),
      MapProjectFile(
        fileName: '${mapName}_task_bridge.py',
        kind: 'nav2',
        description:
            '앱이 만든 연속 작업을 RMF 에 넣어 준다. RMF 는 task_api_requests '
            '토픽 하나로 작업을 받는데, 요청과 답을 request_id 로 맞춰야 해서 '
            'ros2 topic pub 으로는 안 된다. 이것이 없으면 작업이 앱 안에서만 '
            '돌고 로봇은 가만히 있는다.',
        executable: true,
        content: buildTaskBridgeScript(
          mapName: mapName,
          fleetName: fleet.fleetName,
        ),
        generatedAt: now,
      ),
      MapProjectFile(
        fileName: '${mapName}_gz_bridge.yaml',
        kind: 'bridge',
        description:
            'Gazebo 와 ROS 사이의 토픽 다리. 로봇마다 /<로봇>/odom · cmd_vel · '
            'scan 을 절대 이름으로 적어 여러 대를 띄워도 겹치지 않는다. '
            'clock 과 tf 는 월드에 하나뿐이라 로봇별로 나누지 않는다.',
        content: buildProjectGzBridgeYaml(
          mapName: mapName,
          robots: deployRobots,
        ),
        generatedAt: now,
      ),
      MapProjectFile(
        fileName: 'isaac/start_$mapName.py',
        kind: 'isaac',
        description:
            'Isaac Sim에서 isaac/$mapName.usd를 열고 ROS 2 Bridge와 stage의 '
            'Action Graph를 실행한다. USD에는 clock·odom·scan·TF·cmd_vel '
            '인터페이스가 구성돼 있어야 한다.',
        executable: true,
        content: buildIsaacProjectScript(mapName: mapName),
        generatedAt: now,
      ),
      // 로봇 하나가 디렉터리 하나다. 한 대를 빼거나 옮길 때 그 디렉터리만
      // 보면 되고, 파일이 늘어도 어느 것이 누구 것인지 헷갈리지 않는다.
      for (final robot in deployRobots) ...[
        MapProjectFile(
          fileName: '${robotDirectoryName(robot)}/robot.yaml',
          kind: 'robot',
          description:
              '${robot.robotId} · ${robot.displayName} 의 등록 정보. '
              '${robot.kind.label} · ${robot.model} · '
              '${robot.isMobile ? '충전' : '설비'} 자리 '
              '${robot.chargerWaypoint ?? '미지정'}.',
          content: buildRobotInfoYaml(robot),
          generatedAt: now,
        ),
        MapProjectFile(
          fileName: '${robotDirectoryName(robot)}/spawn.launch.xml',
          kind: 'robot',
          description:
              '${robot.robotId} 한 대만 Gazebo 에 올리는 launch. '
              '프로젝트 bringup 이 이 파일을 include 한다. '
              '이 로봇만 따로 시험할 때는 이것만 돌리면 된다.',
          content: buildRobotSpawnLaunchXml(robot),
          generatedAt: now,
        ),
        if (robot.runsInGazebo)
          MapProjectFile(
            fileName: '${robotDirectoryName(robot)}/robot_description.sh',
            kind: 'robot',
            description: robot.isMobile
                ? '${robot.robotId} 의 URDF 를 만든다. 벤더 xacro 가 '
                      '<gazebo reference> 에만 네임스페이스를 붙여 라이다·'
                      '카메라·IMU 가 통째로 버려지는 것을 고친다.'
                : '${robot.robotId} 의 URDF 를 만든다. 벤더 xacro 의 '
                      'gz_ros2_control 플러그인에 네임스페이스를 끼워 넣는다. '
                      '없으면 플러그인이 루트 /robot_description 을 기다리며 '
                      'Gazebo 갱신 루프 전체를 막는다.',
            executable: true,
            content: buildRobotDescriptionScript(robot),
            generatedAt: now,
          ),
        MapProjectFile(
          fileName: '${robotDirectoryName(robot)}/bridge.yaml',
          kind: 'robot',
          description:
              '${robot.robotId} 가 주고받는 토픽. 실행에는 프로젝트 전체를 묶은 '
              '${mapName}_gz_bridge.yaml 을 쓴다. 이 파일은 이 로봇 몫만 '
              '따로 보기 위한 것이다.',
          content: buildRobotBridgeYaml(robot),
          generatedAt: now,
        ),
        // Nav2 는 이동 로봇만 쓴다. 설치 로봇은 한자리에 붙어 있어 길을 찾을
        // 일이 없다.
        if (robot.isMobile && robot.runsInGazebo) ...[
          MapProjectFile(
            fileName: '${robotDirectoryName(robot)}/nav2.launch.xml',
            kind: 'nav2',
            description:
                '${robot.robotId} 의 Nav2. 이 로봇의 라이다로 제 위치를 잡고'
                ' 길을 만들어 간다. map_server 는 월드에 하나뿐이라 여기 없다.',
            content: buildRobotNav2LaunchXml(robot, mapName),
            generatedAt: now,
          ),
          if (nav2.params[robot.robotId] != null)
            MapProjectFile(
              fileName: '${robotDirectoryName(robot)}/nav2_params.yaml',
              kind: 'nav2',
              description:
                  '${robot.robotId} 의 Nav2 파라미터. 벤더의 nav2_params.yaml 을'
                  ' 이 로봇 이름에 맞춰 다시 쓴 것이다. TF 프레임과 라이다·'
                  '오도메트리 토픽은 가르고, map 프레임은 함께 쓴다.',
              content: nav2.params[robot.robotId]!,
              generatedAt: now,
            ),
        ],
        MapProjectFile(
          fileName: '${robotDirectoryName(robot)}/README.md',
          kind: 'robot',
          description: '${robot.robotId} 디렉터리 설명. 무엇이고 어디서 고치는지.',
          content: buildRobotReadme(robot, mapName),
          generatedAt: now,
        ),
      ],
      MapProjectFile(
        fileName: 'run_$mapName.sh',
        kind: 'script',
        description:
            '전체 실행. 선택한 Gazebo/Isaac Sim 백엔드를 먼저 띄운 뒤 '
            'Open-RMF를 올린다. 물리 백엔드가 먼저 /clock을 내야 '
            'use_sim_time을 쓰는 RMF 노드가 시간을 맞춘다.',
        executable: true,
        content: buildProjectRunScript(
          mapName: mapName,
          mapDirectory: mapDirectory,
          robots: deployRobots,
          rosDomainId: _rosDomainId,
        ),
        generatedAt: now,
      ),
      MapProjectFile(
        fileName: 'stop_$mapName.sh',
        kind: 'script',
        description:
            '이 프로젝트로 띄운 프로세스만 내린다. 다른 맵으로 띄운 RMF 나 '
            '관계없는 Gazebo 는 건드리지 않는다.',
        executable: true,
        content: buildProjectStopScript(
          mapName: mapName,
          mapDirectory: mapDirectory,
          robots: deployRobots,
        ),
        generatedAt: now,
      ),
    ];
    // 저장하기 전에 견줘 봐야 무엇이 달라졌는지 알 수 있다.
    final changes = await _diffMapProject(mapName, fleet, files);
    await saveMapProjectFiles(mapName, files);
    // 무엇이 달라졌는지 남긴다. 실패해도 저장 자체는 이미 끝났으므로 막지
    // 않는다 — 기록이 없다고 프로젝트를 못 쓰게 만들 일은 아니다.
    try {
      await recordMapProjectChanges(mapName, changes);
    } catch (_) {}
    if (mounted) {
      setState(() {
        _fleetSettings = fleet;
        // 저장이 끝났으니 그리드맵 화면의 기준도 여기로 옮긴다. 저장을 시작할
        // 때 찍어 둔 것을 쓴다 — 그 사이에 사람이 값을 더 고쳤을 수 있고,
        // 그것은 아직 저장되지 않았다.
        _savedGridSettings = gridSnapshot;
      });
    }
  }

  /// 열린 프로젝트의 플릿 설정을 읽어 온다. 없으면 맵 이름에서 기본값을 만든다.
  Future<void> _loadFleetForProject(String mapName) async {
    Map<String, dynamic>? stored;
    try {
      stored = await loadMapProjectFleet(mapName);
    } catch (_) {
      stored = null;
    }
    if (!mounted) return;
    setState(() {
      if (stored == null) {
        _fleetSettings = RmfFleetSettings(fleetName: _fleetNameFor(mapName));
        _fleetRobots = const [];
        return;
      }
      _fleetSettings = RmfFleetSettings.fromJson(
        stored['settings'] as Map<String, dynamic>,
      );
      // JSON_ARRAYAGG 는 순서를 보장하지 않는다. 저장할 때 매긴 seq 로 되돌려
      // 놓지 않으면 프로젝트를 다시 열 때마다 목록 차례가 뒤바뀐다.
      final rows =
          (stored['robots'] as List<dynamic>? ?? const [])
              .cast<Map<String, dynamic>>()
              .toList()
            ..sort(
              (a, b) =>
                  ((a['seq'] as num?) ?? 0).compareTo((b['seq'] as num?) ?? 0),
            );
      // 예전 판이 잘못된 좌표계로 저장해 둔 자리를 지금 지도 기준으로 고친다.
      _fleetRobots = _withMapSpawnPoints([
        for (final row in rows)
          RmfProjectRobot.fromJson({
            ...row,
            'zones': (row['zonesText'] as String? ?? '')
                .split(',')
                .map((zone) => zone.trim())
                .where((zone) => zone.isNotEmpty)
                .toList(),
          }),
      ]);
    });
    await _syncTelemetry();
  }

  /// 창에서 `저장`을 눌러 확정한 중간 설정을 곧바로 프로젝트에 남긴다.
  ///
  /// 로봇 안전 기준이나 축척처럼 그 자리에서 확정하는 값은, `프로젝트 저장`을
  /// 따로 눌러야만 남는다면 저장했는데 왜 되돌아왔느냐는 혼란이 반복된다.
  /// 열린 프로젝트가 없으면 남길 곳이 없으므로 그 사실을 함께 알린다.
  ///
  /// [label] 은 무엇을 저장했는지(예: `로봇 안전 기준`), [detail] 은 적용된
  /// 값의 요약이다.
  Future<void> _saveSettingToOpenProject({
    required String label,
    required String detail,
  }) async {
    final project = _openProjectName;
    if (project != null && _drawing != null) {
      try {
        await _writeMapProject(project);
        if (!mounted) return;
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('$label 적용 · $detail\n`$project` 프로젝트에 바로 저장했습니다.'),
            duration: const Duration(seconds: 5),
            showCloseIcon: true,
          ),
        );
        return;
      } catch (error) {
        if (!mounted) return;
        _showProcessingWarning('$label 저장', error);
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('$label 적용 · $detail\n프로젝트에 저장하지 못했습니다: $error'),
            backgroundColor: const Color(0xFFDC2626),
            duration: const Duration(seconds: 8),
            showCloseIcon: true,
          ),
        );
        return;
      }
    }
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          '$label 적용 · $detail\n'
          '아직 맵 프로젝트가 없습니다. `프로젝트 저장`으로 만들면 이후 변경은 바로 저장됩니다.',
        ),
        duration: const Duration(seconds: 6),
        showCloseIcon: true,
      ),
    );
  }

  /// 로봇이 설 자리로 고를 수 있는 Waypoint 이름 목록.
  ///
  /// 이동 로봇은 충전 Waypoint 에, 설치 로봇은 설비 Waypoint 에 선다. 맵에 있는
  /// 것 중에서 고르므로 이름을 잘못 적을 일이 없다.
  /// 로봇이 설 수 있는 자리 Waypoint 이름.
  ///
  /// 편집기에 맵이 열려 있지 않으면 `_waypointTypes` 가 비어 있다. 그때는
  /// 로봇 화면에서 불러온 배포 맵을 본다 — 그러지 않으면 자리 목록이 통째로
  /// 비어, 이미 골라 둔 자리가 저장할 때 지워졌다.
  List<String> _stationWaypointNames(RmfRobotKind kind) {
    final types = _waypointTypes.isNotEmpty
        ? _waypointTypes
        : (_robotDeployedMap?.waypointCategories ?? const <Offset, String>{});
    final names = _waypointTypes.isNotEmpty
        ? _waypointNames
        : (_robotDeployedMap?.waypointNames ?? const <Offset, String>{});
    return [
      for (final entry in types.entries)
        if (entry.value == kind.waypointCategory)
          (names[entry.key] ?? '').trim()
        else
          '',
    ].where((name) => name.isNotEmpty).toList()..sort();
  }

  /// 자리 Waypoint 이름에서 spawn 좌표(RMF 월드, m)를 푼다.
  ///
  /// 자리는 종류에 맞는 카테고리에서만 찾는다. 이동 로봇이 설비 자리에 서거나
  /// 그 반대가 되면 실행에서 어긋난다.
  ///
  /// 화면에 보여 주는 바닥 좌표가 아니라 RMF 월드 좌표를 낸다. 바닥 좌표를
  /// 그대로 넣으면 y 부호가 반대라 로봇이 건물 밖에 떨어진다.
  ///
  /// 등록 창의 저장 단추도, 실제로 저장되는 값도 이 함수 하나만 본다. 두 곳에서
  /// 따로 풀면 "저장은 되는데 좌표는 없는" 로봇이 다시 생긴다.
  Offset? _spawnFromStation({
    required RmfRobotKind kind,
    required String? station,
  }) {
    final name = (station ?? '').trim();
    if (name.isEmpty) return null;
    final source = _waypointTypes.entries
        .where(
          (entry) =>
              entry.value == kind.waypointCategory &&
              (_waypointNames[entry.key] ?? '').trim() == name,
        )
        .map((entry) => entry.key)
        .firstOrNull;
    if (source == null) return null;
    return _rmfMetersFromPixel(source);
  }

  /// 자리 Waypoint 하나마다 로봇 한 대를 만든다.
  ///
  /// 로봇을 손으로 하나씩 넣는 대신 맵에서 끌어온다. 충전 Waypoint 는 이동
  /// 로봇의 자리이고 설비 Waypoint 는 설치 로봇의 자리이므로, spawn 좌표와
  /// 자리를 한꺼번에 채울 수 있다.
  List<RmfProjectRobot> _robotsFromChargers() {
    final robots = <RmfProjectRobot>[];
    for (final kind in RmfRobotKind.values) {
      final stations = <Offset, String>{
        for (final entry in _waypointTypes.entries)
          if (entry.value == kind.waypointCategory &&
              (_waypointNames[entry.key] ?? '').trim().isNotEmpty)
            entry.key: _waypointNames[entry.key]!.trim(),
      };
      var index = 0;
      for (final entry in stations.entries) {
        index++;
        final serial = index.toString().padLeft(2, '0');
        // Gazebo 도 nav graph 도 RMF 월드 좌표를 쓴다. 화면에 보여 주는 바닥
        // 좌표를 그대로 넣으면 로봇이 건물 밖 허공에 놓여 끝없이 떨어진다.
        final spawn = _rmfMetersFromPixel(entry.key);
        robots.add(
          kind == RmfRobotKind.mobile
              ? RmfProjectRobot(
                  robotId: 'pinky_$serial',
                  displayName: 'PK-$serial',
                  model: 'PINKY-GZ',
                  gzName: 'pinky_$serial',
                  zones: const ['ambient', 'chilled', 'frozen'],
                  chargerWaypoint: entry.value,
                  spawnX: spawn?.dx,
                  spawnY: spawn?.dy,
                )
              : RmfProjectRobot(
                  robotId: 'omx_$serial',
                  displayName: 'OMX-$serial',
                  model: openManipulatorModels.first,
                  kind: RmfRobotKind.workcell,
                  gzName: 'omx_$serial',
                  // 설치 로봇은 배차를 받지 않으므로 구획 자격이 필요 없다.
                  zones: const [],
                  chargerWaypoint: entry.value,
                  spawnX: spawn?.dx,
                  spawnY: spawn?.dy,
                ),
        );
      }
    }
    return robots;
  }

  /// 속도 한계 입력 칸 하나.
  ///
  /// 벤더 값을 helperText 로 늘 보여 준다. 불러오기 단추를 누르지 않아도 지금
  /// 값이 로봇의 실제 성능과 얼마나 다른지 눈에 보여야 한다 — 이 두 값이 조용히
  /// 어긋나 있던 것이 이 칸을 만든 이유다.
  Widget _limitField({
    required TextEditingController controller,
    required String label,
    required String unit,
    required double? vendor,
    // 값이 바뀔 때마다 창을 다시 그려야 하는 칸이 있다. 직진 속도가 그렇다 —
    // 너무 느리면 Nav2 가 정상 주행을 끼었다고 판정하는데, 저장하고 나서
    // 알려 주면 이미 늦다.
    ValueChanged<String>? onChanged,
  }) => TextField(
    controller: controller,
    onChanged: onChanged,
    keyboardType: const TextInputType.numberWithOptions(decimal: true),
    decoration: InputDecoration(
      labelText: label,
      suffixText: unit,
      helperText: vendor == null
          ? '벤더 값 없음'
          : '벤더 ${vendor.toStringAsFixed(2)}',
      helperMaxLines: 2,
      isDense: true,
      border: const OutlineInputBorder(),
    ),
  );

  /// 로봇 한 대를 추가하거나 고친다. 취소하면 null.
  Future<RmfProjectRobot?> _editFleetRobot(RmfProjectRobot? existing) async {
    final index = _fleetRobots.length + 1;
    final serial = index.toString().padLeft(2, '0');
    // 기본 ID 에 하이픈을 쓰지 않는다. RMF 가 이 이름으로 토픽을 만드는데
    // (`rmf/dynamic_event/begin/<플릿>/<로봇>`) 하이픈은 ROS 2 토픽 이름에 못
    // 들어간다. 예전 기본값 `PK-01` 로 만든 이동 로봇은 플릿에 붙는 순간
    // fleet adapter 를 죽였다.
    //
    // Gazebo/ROS에서 실제 사용하던 이름을 표준 system ID로 삼는다. 예전 등록을
    // 저장하면 아래의 기존 rename 경로가 지도와 작업 참조도 함께 옮긴다.
    final idController = TextEditingController(
      text: existing?.gzName ?? 'pinky_$serial',
    );
    final nameController = TextEditingController(
      text: existing?.displayName ?? 'PK-$serial',
    );
    final modelController = TextEditingController(
      text: existing?.model ?? 'PINKY-GZ',
    );
    // 맵의 기본 도메인을 가져와 채워 둔다. 대개는 그대로 두고, 실물 로봇처럼
    // 제 도메인을 갖고 오는 대만 고친다. 비우면 기본값을 따라간다 — 그러면
    // 나중에 맵에서 기본값을 바꿔도 이 로봇이 같이 따라온다.
    final domainController = TextEditingController(
      text: '${existing?.rosDomainId ?? _rosDomainId}',
    );
    String? domainError;
    var kind = existing?.kind ?? RmfRobotKind.mobile;
    var dataSource = existing?.dataSource ?? RobotDataSource.mock;
    var charger = existing?.chargerWaypoint;
    var zones = {...?existing?.zones};
    if (zones.isEmpty && kind == RmfRobotKind.mobile) {
      zones = {'ambient', 'chilled', 'frozen'};
    }
    // 골라 둔 자리를 조용히 지우지 않는다. 맵을 열지 않은 채로 로봇을 한 번
    // 열어 보기만 해도 자리가 사라졌고, 자리가 없으면 spawn 좌표도 없어져
    // Gazebo 에 로봇이 아예 안 올라갔다 — 토픽이 하나도 안 나온 원인이다.
    final missingStation =
        charger != null && !_stationWaypointNames(kind).contains(charger);

    final saved = await showMovableDialog<RmfProjectRobot>(
      context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (context, setDialogState) {
          final stations = _stationWaypointNames(kind);
          final isMobile = kind == RmfRobotKind.mobile;
          final spawn = _spawnFromStation(kind: kind, station: charger);
          // 자리를 고르게 하는 규칙. 판정은 robot_station_rule 에 있다.
          //
          // 좌표가 아니라 **자리 이름**을 본다. 좌표는 자리 이름에서 계산되는데,
          // 그 계산에는 지도 축척이 있어야 한다. 그런데 배포 맵을 불러오는
          // 것만으로는 축척이 따라오지 않는다(맵 관리에서 재는 값이다). 좌표로
          // 막으면 자리를 멀쩡히 골라도 저장이 안 되고, 사람은 무엇이 잘못인지
          // 알 수 없다.
          //
          // 이름만 있으면 좌표는 나중에 채워진다 — 맵을 열면
          // `_syncRobotSpawnsToMap` 이 등록된 로봇의 자리를 지금 지도에서 다시
          // 계산한다. 이름이 없으면 그때도 채울 것이 없다.
          // 플릿에 들어가는 로봇만 ID 가 토픽 이름이 된다. 설치 로봇은 플릿에
          // 안 들어가므로 예전 이름을 그대로 두어도 된다 — 멀쩡한 등록에 이름을
          // 바꾸라고 시킬 이유가 없다.
          final idMattersForTopics = isMobile && dataSource.usesTopics;
          final idProblem = idMattersForTopics
              ? robotIdProblem(idController.text)
              : null;
          final stationRule = checkStationRequirement(
            usesTopics: dataSource.usesTopics,
            station: charger,
            stationsAvailable: stations.isNotEmpty || missingStation,
          );
          final needsStation = dataSource.usesTopics;
          final canSave = canSaveRobot(stationRule);
          final stationMessage = stationRequirementMessage(
            stationRule,
            kind.waypointCategory,
          );
          return AlertDialog(
            icon: Icon(
              isMobile
                  ? Icons.smart_toy_outlined
                  : Icons.precision_manufacturing,
              size: 32,
            ),
            title: Text(existing == null ? '로봇 등록' : '로봇 수정'),
            content: SizedBox(
              width: 460,
              child: SingleChildScrollView(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    // 종류를 먼저 정한다. 자리를 고를 Waypoint 카테고리도,
                    // 실행할 때 쓰는 설명 파일도, 플릿에 들어가는지 여부도
                    // 여기서 갈린다.
                    SegmentedButton<RmfRobotKind>(
                      segments: const [
                        ButtonSegment(
                          value: RmfRobotKind.mobile,
                          icon: Icon(Icons.smart_toy_outlined, size: 18),
                          label: Text('이동 로봇'),
                        ),
                        ButtonSegment(
                          value: RmfRobotKind.workcell,
                          icon: Icon(Icons.precision_manufacturing, size: 18),
                          label: Text('설치 로봇'),
                        ),
                      ],
                      selected: {kind},
                      onSelectionChanged: (selected) => setDialogState(() {
                        kind = selected.first;
                        charger = null;
                        if (kind == RmfRobotKind.mobile) {
                          zones = {'ambient', 'chilled', 'frozen'};
                          if (existing == null) {
                            idController.text = 'pinky_$serial';
                            nameController.text = 'PK-$serial';
                            modelController.text = 'PINKY-GZ';
                          }
                        } else {
                          // 설치 로봇은 배차를 받지 않으므로 구획 자격이 없다.
                          zones = {};
                          if (existing == null) {
                            idController.text = 'omx_$serial';
                            nameController.text = 'OMX-$serial';
                            modelController.text = openManipulatorModels.first;
                          }
                        }
                      }),
                    ),
                    const SizedBox(height: 8),
                    Text(
                      isMobile
                          ? 'Lane 을 따라 다닙니다. fleet adapter 가 배차합니다.'
                          : '설비 자리에 고정됩니다. 배차 대상이 아니라서 '
                                'fleet adapter 에 들어가지 않습니다.',
                      style: const TextStyle(
                        fontSize: 12,
                        color: Color(0xFF64748B),
                      ),
                    ),
                    const SizedBox(height: 16),
                    // 값이 어디서 오는가. 무엇을 고르느냐에 따라 실행에
                    // 들어가는 자리가 갈린다.
                    DropdownButtonFormField<RobotDataSource>(
                      initialValue: dataSource,
                      isExpanded: true,
                      decoration: InputDecoration(
                        labelText: '값의 출처',
                        helperText: switch (dataSource) {
                          RobotDataSource.mock =>
                            '앱 안에서만 돕니다. fleet adapter 에도 Gazebo 에도 '
                                '들어가지 않습니다.',
                          RobotDataSource.gazebo =>
                            'Gazebo 가 물리를 돌리고 토픽으로 주고받습니다. '
                                'bringup 과 토픽 다리에 들어갑니다.',
                          RobotDataSource.real =>
                            '실물이 이미 있습니다. fleet adapter 에는 들어가고 '
                                'Gazebo 에는 올리지 않습니다.',
                        },
                        helperMaxLines: 3,
                        border: const OutlineInputBorder(),
                      ),
                      items: [
                        for (final value in RobotDataSource.values)
                          DropdownMenuItem(
                            value: value,
                            child: Text(value.label),
                          ),
                      ],
                      onChanged: (value) => setDialogState(
                        () => dataSource = value ?? RobotDataSource.mock,
                      ),
                    ),
                    const SizedBox(height: 14),
                    TextField(
                      controller: idController,
                      // 못 쓰는 글자는 치는 즉시 고친다. 막기만 하면 사람이
                      // 무엇을 쳐야 하는지 알아내야 한다 — `PK-01` 을 치면
                      // `PK_01` 이 된다.
                      inputFormatters: [_RobotIdFormatter()],
                      onChanged: (_) => setDialogState(() {}),
                      decoration: InputDecoration(
                        labelText: '로봇 ID',
                        helperText: isMobile
                            ? 'Gazebo 모델명·ROS namespace·RMF 로봇 이름으로 함께 '
                                  '씁니다. 예: pinky_01'
                            : 'Gazebo 모델명·ROS namespace와 함께 씁니다. 예: omx_01',
                        helperMaxLines: 3,
                        // 예전에 하이픈으로 저장된 로봇을 열었을 때를 위해 남긴다.
                        // 새로 치는 것은 위 formatter 가 이미 막는다.
                        errorText: idProblem,
                        errorMaxLines: 3,
                        border: const OutlineInputBorder(),
                      ),
                    ),
                    const SizedBox(height: 12),
                    TextField(
                      controller: nameController,
                      decoration: const InputDecoration(
                        labelText: '표시 이름',
                        border: OutlineInputBorder(),
                      ),
                    ),
                    const SizedBox(height: 12),
                    if (isMobile)
                      TextField(
                        controller: modelController,
                        decoration: const InputDecoration(
                          labelText: '모델',
                          border: OutlineInputBorder(),
                        ),
                      )
                    else
                      DropdownButtonFormField<String>(
                        initialValue:
                            openManipulatorModels.contains(modelController.text)
                            ? modelController.text
                            : openManipulatorModels.first,
                        isExpanded: true,
                        decoration: const InputDecoration(
                          labelText: '모델',
                          helperText:
                              'open_manipulator_description 의 xacro 이름입니다.',
                          border: OutlineInputBorder(),
                        ),
                        items: [
                          for (final model in openManipulatorModels)
                            DropdownMenuItem(value: model, child: Text(model)),
                        ],
                        onChanged: (value) => setDialogState(
                          () => modelController.text = value ?? '',
                        ),
                      ),
                    const SizedBox(height: 8),
                    const Align(
                      alignment: Alignment.centerLeft,
                      child: Text(
                        'Gazebo 모델명과 ROS namespace도 위 시스템 ID를 사용합니다.',
                        style: TextStyle(
                          fontSize: 12,
                          color: Color(0xFF64748B),
                        ),
                      ),
                    ),
                    const SizedBox(height: 12),
                    TextField(
                      controller: domainController,
                      keyboardType: TextInputType.number,
                      decoration: InputDecoration(
                        labelText: 'ROS_DOMAIN_ID',
                        helperText: dataSource == RobotDataSource.gazebo
                            ? '맵 기본값 $_rosDomainId 을 가져왔습니다. Gazebo 로봇은 '
                                  '시뮬레이터와 같아야 합니다 — 다르면 오류 없이 값만 '
                                  '안 옵니다.'
                            : '맵 기본값 $_rosDomainId 을 가져왔습니다. 이 로봇이 다른 '
                                  '망에 있으면 여기서 고치세요. 비우면 기본값을 따라갑니다.',
                        helperMaxLines: 3,
                        errorText: domainError,
                        border: const OutlineInputBorder(),
                      ),
                      onChanged: (_) =>
                          setDialogState(() => domainError = null),
                    ),
                    const SizedBox(height: 12),
                    DropdownButtonFormField<String>(
                      key: ValueKey(kind),
                      initialValue: charger,
                      isExpanded: true,
                      decoration: InputDecoration(
                        // 필수인 것만 별표를 단다. Mock 로봇에까지 달면
                        // 안 골라도 되는 칸을 골라야 하는 것으로 읽는다.
                        labelText:
                            '${isMobile ? '충전' : '설비'} Waypoint'
                            '${needsStation ? ' *' : ''}',
                        // 목록이 빈 이유를 밝힌다. 예전에는 맵을 안 열었을
                        // 뿐인데 "Waypoint 가 없습니다" 라고만 해서, 지도에
                        // 멀쩡히 있는 자리를 없는 것으로 알게 했다.
                        helperText: stations.isEmpty
                            ? '맵이 열려 있지 않거나 '
                                  '${kind.waypointCategory} 카테고리 Waypoint가 '
                                  '없습니다. 로봇 화면에서 배포 맵을 먼저 '
                                  '불러오세요.'
                            : missingStation
                            ? '$charger 를 지금 맵에서 찾지 못했습니다. '
                                  '그대로 두면 값은 지워지지 않습니다.'
                            : isMobile
                            ? '작업 후 복귀할 충전소입니다. 새 로봇은 처음에 이 '
                                  '위치를 Spawn 기본값으로 쓰지만, 이후 로봇 '
                                  'Spawn에서 다른 시작 Waypoint를 고를 수 있습니다.'
                            : '이 자리에 고정 설치됩니다. 반드시 골라야 합니다.',
                        helperMaxLines: 3,
                        border: const OutlineInputBorder(),
                      ),
                      items: [
                        // 지금 맵에서 못 찾은 자리도 목록에 남겨 둔다. 빼면
                        // 창을 열었다 닫기만 해도 값이 사라진다.
                        if (missingStation)
                          DropdownMenuItem(
                            value: charger,
                            child: Text('$charger  (지금 맵에서 못 찾음)'),
                          ),
                        for (final name in stations)
                          DropdownMenuItem(value: name, child: Text(name)),
                      ],
                      onChanged: (value) =>
                          setDialogState(() => charger = value),
                    ),
                    // 단추가 왜 안 눌리는지, 또는 지금 저장하면 무엇이 빈 채로
                    // 남는지 그 자리에서 밝힌다. 흐린 단추만 두면 사람이 다른
                    // 칸을 뒤진다.
                    if (stationMessage != null)
                      Padding(
                        padding: const EdgeInsets.only(top: 8),
                        child: Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Icon(
                              canSave
                                  ? Icons.warning_amber_outlined
                                  : Icons.error_outline,
                              size: 16,
                              // 막는 것과 알리는 것은 색이 달라야 한다. 둘 다
                              // 빨간색이면 저장되는데도 막힌 줄 안다.
                              color: canSave
                                  ? const Color(0xFFB45309)
                                  : const Color(0xFFDC2626),
                            ),
                            const SizedBox(width: 6),
                            Expanded(
                              child: Text(
                                stationMessage,
                                style: TextStyle(
                                  fontSize: 12,
                                  color: canSave
                                      ? const Color(0xFFB45309)
                                      : const Color(0xFFDC2626),
                                  height: 1.4,
                                ),
                              ),
                            ),
                          ],
                        ),
                      ),
                    const SizedBox(height: 12),
                    if (isMobile)
                      Align(
                        alignment: Alignment.centerLeft,
                        child: Wrap(
                          spacing: 8,
                          children: [
                            for (final zone in const [
                              'ambient',
                              'chilled',
                              'frozen',
                            ])
                              FilterChip(
                                label: Text(zone),
                                selected: zones.contains(zone),
                                onSelected: (on) => setDialogState(() {
                                  if (on) {
                                    zones.add(zone);
                                  } else {
                                    zones.remove(zone);
                                  }
                                }),
                              ),
                          ],
                        ),
                      ),
                    if (isMobile)
                      const Align(
                        alignment: Alignment.centerLeft,
                        child: Padding(
                          padding: EdgeInsets.only(top: 6),
                          child: Text(
                            '진입 가능한 3온도 구획입니다. 관제 배차의 입찰 자격이 됩니다.',
                            style: TextStyle(
                              fontSize: 12,
                              color: Color(0xFF64748B),
                            ),
                          ),
                        ),
                      ),
                    // 주행 한계(속도·가속도)는 여기 없다. 플릿 하나에 걸리는
                    // 값이라 로봇 창에 두면 PK_01 에서 고친 것이 PK_02 에도
                    // 걸리는데, 로봇마다 정하는 것처럼 보인다. 실제로 그렇게
                    // 오해를 샀다. 맵 관리의 `로봇 안전 기준` 으로 옮겼다 —
                    // footprint·vicinity 같은 다른 플릿 값이 이미 거기 있다.
                  ],
                ),
              ),
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(dialogContext),
                child: const Text('취소'),
              ),
              FilledButton(
                // 자리를 안 고른 로봇은 만들지 않는다. spawn 좌표가 없으면
                // 지도 원점에 놓이고, 그 상태로도 등록·배포·스폰이 전부
                // 성공한 것처럼 보인다.
                onPressed: !canSave || idProblem != null
                    ? null
                    : () {
                        final id = idController.text.trim();
                        if (id.isEmpty) return;
                        final stationChanged =
                            existing == null ||
                            charger != existing.chargerWaypoint ||
                            kind != existing.kind;
                        // 비우면 맵 기본값을 따라간다는 뜻이라 저장할 것이
                        // 없다. 적었으면 쓸 수 있는 번호여야 한다.
                        final rawDomain = domainController.text.trim();
                        final domain = rawDomain.isEmpty
                            ? null
                            : int.tryParse(rawDomain);
                        if (rawDomain.isNotEmpty) {
                          final domainProblem = rosDomainIdError(domain);
                          if (domainProblem != null) {
                            setDialogState(() => domainError = domainProblem);
                            return;
                          }
                        }
                        Navigator.pop(
                          dialogContext,
                          RmfProjectRobot(
                            robotId: id,
                            displayName: nameController.text.trim().isEmpty
                                ? id
                                : nameController.text.trim(),
                            model: modelController.text.trim().isEmpty
                                ? (isMobile
                                      ? 'PINKY-GZ'
                                      : openManipulatorModels.first)
                                : modelController.text.trim(),
                            kind: kind,
                            dataSource: dataSource,
                            // 맵 기본값과 같으면 따로 들고 있지 않는다.
                            // 그래야 나중에 기본값을 바꿨을 때 같이 따라온다.
                            rosDomainId: domain == _rosDomainId ? null : domain,
                            gzName: id,
                            zones: zones.toList()..sort(),
                            chargerWaypoint: charger,
                            // 충전소는 복귀점이고 Spawn은 최초 시작 위치다. 등록
                            // 창을 열어 저장했다는 이유만으로 대기4 Spawn을
                            // 충전1 좌표로 덮어쓰지 않는다. 복귀점을 실제로
                            // 바꾼 경우에만 새 로봇의 기본 시작점도 함께 맞춘다.
                            spawnX: stationChanged
                                ? spawn?.dx
                                : existing?.spawnX ?? spawn?.dx,
                            spawnY: stationChanged
                                ? spawn?.dy
                                : existing?.spawnY ?? spawn?.dy,
                            spawnHeading: existing?.spawnHeading ?? 0,
                          ),
                        );
                      },
                child: const Text('저장'),
              ),
            ],
          );
        },
      ),
    );
    unawaited(
      Future<void>.delayed(const Duration(milliseconds: 350)).then((_) {
        idController.dispose();
        nameController.dispose();
        modelController.dispose();
        domainController.dispose();
      }),
    );
    return saved;
  }

  /// 로봇을 프로젝트에 등록한다. 등록해야 Gazebo 에 스폰되고 fleet adapter 가
  /// 그 로봇을 안다.
  ///
  /// 등록은 맵 관리의 RMF 설정 창에도 있지만, 로봇을 다루러 온 사람이 먼저 찾는
  /// 곳은 로봇 메뉴다. 두 곳이 같은 [_fleetRobots] 를 본다.
  Future<void> _registerFleetRobot() async {
    final robot = await _editFleetRobot(null);
    if (robot == null) return;
    setState(
      () => _fleetRobots = [
        ..._fleetRobots.where((r) => r.robotId != robot.robotId),
        robot,
      ],
    );
    await _saveSettingToOpenProject(
      label: '로봇 등록',
      detail: '${robot.robotId} · ${robot.displayName}',
    );
    await _syncTelemetry();
  }

  /// 등록된 로봇 하나를 고친다.
  Future<void> _updateFleetRobot(RmfProjectRobot existing) async {
    final updated = await _editFleetRobot(existing);
    if (updated == null) return;
    setState(() {
      _fleetRobots = [
        for (final robot in _fleetRobots)
          if (robot.robotId == existing.robotId) updated else robot,
      ];
      // ID 를 바꿨으면 그 ID 를 들고 있는 것을 여기서 전부 함께 바꾼다.
      //
      // 지도에 올린 로봇도 작업도 등록에서 온 ID 를 들고 있다. 등록만 고치면
      // 옛 ID 가 그대로 남아 서로를 못 찾는다. 그러면 작업이 RMF 로 안 가고
      // 앱 안에서만 돌아, 화면에서는 일하는 것처럼 보이는데 로봇은 가만히
      // 있는다. 고치는 자리에서 맞춰 두면 어긋날 일이 없다.
      if (updated.robotId != existing.robotId) {
        _renameRobotEverywhere(existing.robotId, updated.robotId);
      }
    });
    await _saveSettingToOpenProject(
      label: '로봇 수정',
      detail: '${updated.robotId} · ${updated.displayName}',
    );
    // 작업이 들고 있던 ID 도 바뀌었으므로 함께 남긴다.
    await _saveMockTasks();
    await _syncTelemetry();
  }

  /// 지도·작업·자리 예약이 들고 있는 로봇 ID 를 한꺼번에 바꾼다.
  ///
  /// `setState` 안에서 부른다 — 화면이 한 번에 새 ID 로 그려져야 중간 상태가
  /// 안 보인다.
  void _renameRobotEverywhere(String from, String to) {
    for (final robot in _mockRobots) {
      if (robot.id == from) robot.id = to;
    }
    for (final task in _mockTasks) {
      if (task.robotId == from) task.robotId = to;
    }
    // 자리 예약은 값이 로봇 ID 다. 안 바꾸면 그 자리가 영영 잠긴다.
    for (final entry in _homeReservations.entries.toList()) {
      if (entry.value == from) _homeReservations[entry.key] = to;
    }
  }

  /// 등록을 지운다. 이미 스폰해 둔 로봇이 있으면 함께 사라진다는 것을 먼저
  /// 알린다. 등록이 없어지면 다음 실행에서 그 로봇은 올라오지 않는다.
  Future<void> _unregisterFleetRobot(RmfProjectRobot robot) async {
    final spawned = _mockRobots.where((m) => m.id == robot.robotId).toList();
    final confirmed = await showMovableDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        icon: const Icon(Icons.delete_outline, size: 32),
        title: const Text('로봇 등록 해제'),
        content: SizedBox(
          width: 420,
          child: Text(
            '${robot.robotId} · ${robot.displayName} 의 등록을 지웁니다.\n\n'
            '이 로봇은 Gazebo 에 올라오지 않고 fleet adapter 에서도 빠집니다.'
            '${spawned.isEmpty ? '' : '\n\n지금 배치되어 있는 이 로봇도 함께 내립니다.'}',
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('취소'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(dialogContext, true),
            style: FilledButton.styleFrom(
              backgroundColor: const Color(0xFFDC2626),
            ),
            child: const Text('등록 해제'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    for (final mock in spawned) {
      _removeMockRobot(mock);
    }
    setState(
      () => _fleetRobots = [
        for (final r in _fleetRobots)
          if (r.robotId != robot.robotId) r,
      ],
    );
    await _saveSettingToOpenProject(
      label: '로봇 등록 해제',
      detail: '${robot.robotId} · ${robot.displayName}',
    );
    await _syncTelemetry();
  }

  /// 충전 Waypoint 마다 로봇을 한 대씩 만들어 등록한다. spawn 좌표와 charger 가
  /// 한꺼번에 채워지므로 손으로 넣다 어긋날 일이 없다.
  Future<void> _registerRobotsFromChargers() async {
    final generated = _robotsFromChargers();
    if (generated.isEmpty) {
      // 팝업으로 알린다. 대시보드에만 뜨는 경고로 두면 로봇 메뉴에서는 눌러도
      // 아무 일이 없는 것처럼 보인다.
      await showWaypointErrorDialog(
        context,
        title: '충전 Waypoint에서 만들기',
        message:
            '이름이 있는 충전 카테고리 Waypoint가 없습니다.\n\n'
            '맵 관리에서 Waypoint를 찍고 카테고리를 `충전`으로 바꾼 뒤 '
            '이름을 넣어 주세요. 그 자리가 로봇의 충전소이자 '
            'Gazebo spawn 좌표가 됩니다.',
      );
      return;
    }
    setState(() => _fleetRobots = generated);
    await _saveSettingToOpenProject(
      label: '로봇 등록',
      detail: '충전 Waypoint에서 ${generated.length}대',
    );
    await _syncTelemetry();
  }

  /// RMF 설정 창 — 로봇 목록과 생성된 설정 파일을 한자리에서 본다.
  Future<void> _showRmfConfigDialog() async {
    final project = _openProjectName;
    var files = <MapProjectFile>[];
    if (project != null) {
      try {
        files = await loadMapProjectFiles(project);
      } catch (_) {
        files = [];
      }
    }
    if (!mounted) return;
    await showMovableDialog<void>(
      context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (context, setDialogState) => AlertDialog(
          icon: const Icon(Icons.settings_ethernet, size: 32),
          title: Text('RMF 설정 · ${project ?? _mapName}'),
          content: SizedBox(
            width: 640,
            height: 480,
            child: DefaultTabController(
              length: 2,
              child: Column(
                children: [
                  const TabBar(
                    tabs: [
                      Tab(text: '로봇'),
                      Tab(text: '설정 파일'),
                    ],
                  ),
                  Expanded(
                    child: TabBarView(
                      children: [
                        _fleetRobotsTab(setDialogState),
                        _fleetFilesTab(files, project),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ),
          actions: [
            FilledButton(
              onPressed: () => Navigator.pop(dialogContext),
              child: const Text('닫기'),
            ),
          ],
        ),
      ),
    );
  }

  Widget _fleetRobotsTab(void Function(void Function()) setDialogState) =>
      Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const SizedBox(height: 10),
          Row(
            children: [
              Expanded(
                child: Text(
                  '플릿 ${_fleetSettings.fleetName} · 로봇 ${_fleetRobots.length}대',
                  style: const TextStyle(fontWeight: FontWeight.w800),
                ),
              ),
              TextButton.icon(
                onPressed: () async {
                  await _registerRobotsFromChargers();
                  setDialogState(() {});
                },
                icon: const Icon(Icons.auto_awesome, size: 18),
                label: const Text('충전 Waypoint에서 만들기'),
              ),
              const SizedBox(width: 6),
              FilledButton.icon(
                onPressed: () async {
                  await _registerFleetRobot();
                  setDialogState(() {});
                },
                icon: const Icon(Icons.add, size: 18),
                label: const Text('로봇 등록'),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Expanded(
            child: _fleetRobots.isEmpty
                ? const Center(
                    child: Padding(
                      padding: EdgeInsets.all(24),
                      child: Text(
                        '등록된 로봇이 없습니다.\n'
                        '맵에 충전 Waypoint를 만들고 `충전 Waypoint에서 만들기`를 누르면\n'
                        'spawn 위치와 charger가 한꺼번에 채워집니다.',
                        textAlign: TextAlign.center,
                        style: TextStyle(color: Color(0xFF64748B)),
                      ),
                    ),
                  )
                : ListView.separated(
                    itemCount: _fleetRobots.length,
                    separatorBuilder: (_, _) => const Divider(height: 1),
                    itemBuilder: (_, index) {
                      final robot = _fleetRobots[index];
                      return ListTile(
                        leading: const Icon(Icons.smart_toy_outlined),
                        title: Text('${robot.robotId} · ${robot.displayName}'),
                        subtitle: Text(
                          '${robot.model} · ${robot.gzName} · '
                          '${robot.zones.join(', ')}\n'
                          '충전 ${robot.chargerWaypoint ?? '미지정'}'
                          '${robot.spawnX == null ? '' : ' · spawn '
                                    '${robot.spawnX!.toStringAsFixed(2)}, '
                                    '${robot.spawnY!.toStringAsFixed(2)}'}',
                        ),
                        isThreeLine: true,
                        trailing: Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            IconButton(
                              tooltip: '수정',
                              onPressed: () async {
                                await _updateFleetRobot(robot);
                                setDialogState(() {});
                              },
                              icon: const Icon(Icons.edit_outlined, size: 18),
                            ),
                            IconButton(
                              tooltip: '등록 해제',
                              onPressed: () async {
                                await _unregisterFleetRobot(robot);
                                setDialogState(() {});
                              },
                              icon: const Icon(
                                Icons.delete_outline,
                                size: 18,
                                color: Color(0xFFDC2626),
                              ),
                            ),
                          ],
                        ),
                      );
                    },
                  ),
          ),
          const Padding(
            padding: EdgeInsets.symmetric(vertical: 8),
            child: Text(
              '`프로젝트 저장`을 누르면 이 목록으로 설정 파일이 다시 만들어집니다.',
              style: TextStyle(fontSize: 12, color: Color(0xFF64748B)),
            ),
          ),
        ],
      );

  Widget _fleetFilesTab(List<MapProjectFile> files, String? project) {
    if (project == null) {
      return const Center(
        child: Padding(
          padding: EdgeInsets.all(24),
          child: Text(
            '열린 맵 프로젝트가 없습니다.\n`프로젝트 저장`으로 등록하면 설정 파일이 만들어집니다.',
            textAlign: TextAlign.center,
            style: TextStyle(color: Color(0xFF64748B)),
          ),
        ),
      );
    }
    if (files.isEmpty) {
      return const Center(
        child: Padding(
          padding: EdgeInsets.all(24),
          child: Text(
            '아직 만들어진 설정 파일이 없습니다.\n`프로젝트 저장`을 한 번 누르세요.',
            textAlign: TextAlign.center,
            style: TextStyle(color: Color(0xFF64748B)),
          ),
        ),
      );
    }
    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 8),
          child: Row(
            children: [
              Expanded(
                child: Text(
                  '${files.length}개 · MySQL 보관',
                  style: const TextStyle(fontWeight: FontWeight.w800),
                ),
              ),
              FilledButton.icon(
                onPressed: () => unawaited(_exportRmfConfig(project, files)),
                icon: const Icon(Icons.drive_file_move_outline, size: 18),
                label: const Text('디스크로 내보내기'),
              ),
            ],
          ),
        ),
        const Padding(
          padding: EdgeInsets.only(bottom: 8),
          child: Align(
            alignment: Alignment.centerLeft,
            child: Text(
              'ros2 launch 는 파일만 읽습니다. 실행하기 전에 한 번 내보내세요.',
              style: TextStyle(fontSize: 12, color: Color(0xFF64748B)),
            ),
          ),
        ),
        Expanded(child: _fleetFileList(files)),
      ],
    );
  }

  /// 지난번에 고른 실행 창 설정. 한 번 정하면 대개 그대로 여러 번 띄운다.
  bool _runWithGazeboGui = false;
  bool _runWithRviz = false;
  SimulationBackend _runBackend = SimulationBackend.gazebo;

  /// 띄우기 전에 어떤 창을 볼지 고르게 한다. 취소하면 null.
  ///
  /// 기본은 둘 다 끈 것이다. 창이 없어도 시뮬레이션은 그대로 돌고 라이다·
  /// 카메라도 발행한다 — Gazebo 서버는 언제나 헤드리스 렌더링으로 뜬다.
  /// 창은 사람이 보기 위한 것일 뿐이고, 두 개를 함께 띄우면 이 컴퓨터에서는
  /// 프레임이 떨어져 시뮬레이션까지 느려진다.
  Future<({SimulationBackend backend, bool gazeboGui, bool rviz})?>
  _askRunWindows(String mapName) async {
    var backend = _runBackend;
    var gazeboGui = _runWithGazeboGui;
    var rviz = _runWithRviz;
    var savedSettings = const ProjectSimulationSettings();
    try {
      final saved = await loadProjectSimulationSettings(mapName);
      savedSettings = saved;
      backend = saved.backend;
      gazeboGui = saved.simulatorGui;
      rviz = saved.rviz;
    } catch (_) {
      // v12 설정이 없는 기존 프로젝트는 이 실행 중 기억을 사용한다.
    }
    if (!mounted) return null;
    final chosen =
        await showMovableDialog<
          ({SimulationBackend backend, bool gazeboGui, bool rviz})
        >(
          context: context,
          builder: (dialogContext) => StatefulBuilder(
            builder: (context, setDialogState) => AlertDialog(
              icon: const Icon(Icons.play_circle_outline, size: 32),
              title: Text('$mapName 실행'),
              content: SizedBox(
                width: 460,
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      '설정 저장과 디스크 내보내기는 완료되었습니다.',
                      style: TextStyle(
                        color: Color(0xFF15803D),
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                    const SizedBox(height: 14),
                    const Text('물리 시뮬레이션 백엔드를 고르세요.'),
                    const SizedBox(height: 10),
                    DropdownButtonFormField<SimulationBackend>(
                      initialValue: backend,
                      decoration: const InputDecoration(
                        labelText: '시뮬레이션 백엔드',
                        border: OutlineInputBorder(),
                      ),
                      items: [
                        for (final value in SimulationBackend.values)
                          DropdownMenuItem(
                            value: value,
                            child: Text(value.label),
                          ),
                      ],
                      onChanged: (selected) =>
                          setDialogState(() => backend = selected ?? backend),
                    ),
                    const SizedBox(height: 8),
                    Text(switch (backend) {
                      SimulationBackend.gazebo =>
                        '기존 Gazebo Harmonic 월드와 ROS 다리를 사용합니다.',
                      SimulationBackend.isaacSim =>
                        'USD stage와 Isaac Sim ROS 2 Bridge를 사용합니다.',
                      SimulationBackend.none =>
                        '물리·센서 없이 RMF와 선택한 RViz만 실행합니다.',
                    }, style: const TextStyle(fontSize: 12)),
                    const Divider(height: 24),
                    const Text('표시 화면'),
                    CheckboxListTile(
                      value: gazeboGui,
                      enabled: backend != SimulationBackend.none,
                      contentPadding: EdgeInsets.zero,
                      title: Text('${backend.label} 3D 창'),
                      subtitle: const Text(
                        '선택한 시뮬레이터의 로봇과 건물을 3D로 봅니다.',
                        style: TextStyle(fontSize: 12),
                      ),
                      onChanged: (value) =>
                          setDialogState(() => gazeboGui = value ?? false),
                    ),
                    CheckboxListTile(
                      value: rviz,
                      contentPadding: EdgeInsets.zero,
                      title: const Text('RViz'),
                      subtitle: const Text(
                        'RMF 가 계획한 경로와 교통 정리를 봅니다.',
                        style: TextStyle(fontSize: 12),
                      ),
                      onChanged: (value) =>
                          setDialogState(() => rviz = value ?? false),
                    ),
                    const SizedBox(height: 6),
                    Text(
                      gazeboGui || rviz
                          ? '창을 띄우면 그리는 데 자원을 나눠 써 시뮬레이션이 느려질 수 있습니다.'
                          : '창 없이 띄웁니다. 시뮬레이션은 그대로 돌고 라이다·카메라도 '
                                '발행합니다 — 앱의 로봇 화면에서 위치와 센서를 볼 수 있습니다.',
                      style: const TextStyle(
                        color: Color(0xFF64748B),
                        fontSize: 12,
                      ),
                    ),
                  ],
                ),
              ),
              actions: [
                TextButton(
                  onPressed: () => Navigator.pop(dialogContext),
                  child: const Text('취소'),
                ),
                FilledButton.icon(
                  onPressed: () => Navigator.pop(dialogContext, (
                    backend: backend,
                    gazeboGui: backend == SimulationBackend.none
                        ? false
                        : gazeboGui,
                    rviz: rviz,
                  )),
                  icon: const Icon(Icons.play_arrow, size: 18),
                  label: const Text('백엔드 실행'),
                ),
              ],
            ),
          ),
        );
    if (chosen == null) return null;
    // 고른 것을 다음 실행의 기본값으로 남긴다.
    setState(() {
      _runBackend = chosen.backend;
      _runWithGazeboGui = chosen.gazeboGui;
      _runWithRviz = chosen.rviz;
    });
    try {
      await saveProjectSimulationSettings(
        mapName,
        ProjectSimulationSettings(
          backend: chosen.backend,
          simulatorGui: chosen.gazeboGui,
          rviz: chosen.rviz,
          gazeboSettings: savedSettings.gazeboSettings,
          isaacSettings: savedSettings.isaacSettings,
          coordinateTransform: savedSettings.coordinateTransform,
        ),
      );
    } catch (error) {
      if (mounted) _showProcessingWarning('시뮬레이션 실행 설정 저장', error);
    }
    return chosen;
  }

  Future<bool> _saveSettingsBeforeBackend(String mapName) async {
    try {
      await _writeMapProject(mapName);
      return true;
    } catch (error) {
      if (mounted) _showProcessingWarning('설정 내용 저장', error);
      return false;
    }
  }

  /// 앱에서 프로젝트를 띄운다.
  ///
  /// 앱이 띄운 것만 앱이 내린다. 창을 닫을 때 자동으로 정리되지만, 강제 종료
  /// (kill·전원)는 막을 수 없다 — 그때는 남은 것을 다음 실행에서 알아채고
  /// `로봇 운영` 화면에서 정리한다.
  Future<void> _runProjectScript(String mapName) async {
    final windows = await _askRunWindows(mapName);
    if (windows == null || !mounted) return;
    final result = await startProject(
      mapName,
      backend: windows.backend,
      gazeboGui: windows.gazeboGui,
      rviz: windows.rviz,
    );
    if (!mounted) return;
    await showWaypointErrorDialog(
      context,
      title: result.success ? '프로젝트 실행' : '실행하지 못했습니다',
      message: result.success
          ? '${result.message}\n\n'
                '선택한 백엔드를 준비한 뒤 Open-RMF 를 올립니다.\n'
                '창을 닫으면 자동으로 정리됩니다. 강제 종료하면 남을 수 있으니 '
                '그때는 로봇 운영 화면에서 확인하세요.'
          : result.message,
    );
  }

  /// 로봇 화면에서 곧바로 백엔드를 띄운다.
  ///
  /// 설정 파일 메뉴의 `프로젝트 실행` 과 같은 일을 한다. 백엔드가 없다는 것을
  /// 알게 된 자리에서 바로 띄울 수 있어야지, 다른 메뉴로 찾아가라고 하면
  /// 무엇을 눌러야 하는지 또 헤맨다.
  ///
  /// `ros2 launch` 는 파일만 읽으므로 띄우기 전에 설정을 디스크로 풀어 놓는다.
  /// 내보내기를 깜빡해 `파일이 없습니다` 로 막히는 것이 잦다.
  /// 설정 파일을 지금 코드로 다시 만들어 디스크까지 맞춘다.
  ///
  /// 다시 만드는 것이 핵심이다. `map_project_files` 에 든 내용은 **저장할 당시의
  /// 코드가 만든 것**이라, 앱을 고쳐도 저장된 글자는 예전 그대로다. 내보내기만
  /// 하면 예전 스크립트를 디스크에 다시 쓰는 셈이 된다.
  ///
  /// 조용히 한다. 실패해도 하려던 일(띄우기·내리기)은 계속 시도한다 — 예전
  /// 스크립트라도 없는 것보다는 낫다.
  Future<void> _refreshProjectScripts() async {
    final project = _openProjectName;
    if (project == null) return;
    try {
      // 올릴 자리도 같이 맞춘다. 예전 판이 잘못된 좌표계로 저장해 둔 채로
      // 스크립트를 다시 만들면 로봇이 또 건물 밖에 놓인다.
      final corrected = _withMapSpawnPoints(_fleetRobots);
      if (!identical(corrected, _fleetRobots)) {
        setState(() => _fleetRobots = corrected);
        await _syncTelemetry();
      }
      if (_drawing != null) await _writeMapProject(project);
      // Nav2 지도도 도면에서 파생되는 산출물이다. 도면이 바뀌었는데 예전 격자를
      // 그대로 두면 AMCL 이 없는 벽을 보고 헤맨다.
      //
      // 실패를 삼키지 않는다. 지도가 없으면 로봇은 배차를 아예 못 받는데,
      // 그때 화면에 뜨는 말은 "fleet adapter 가 떠 있는지 확인하세요" 라서
      // 원인에서 한참 떨어져 있다. 여기서 바로 말해 주는 편이 낫다.
      final gridExport = await _exportOccupancyGrid(project);
      if (gridExport != null && !gridExport.success) {
        _showProcessingWarning('Nav2 지도 내보내기', gridExport.message);
      }
      final files = await loadMapProjectFiles(project);
      if (files.isEmpty) return;
      await exportProjectConfigFiles(mapName: project, files: files);
    } catch (_) {}
  }

  Future<void> _startBackendForOpenProject() async {
    final project = _openProjectName;
    if (project == null) {
      await showWaypointErrorDialog(
        context,
        title: 'Open-RMF 백엔드 띄우기',
        message:
            '열린 맵 프로젝트가 없습니다.\n\n'
            '맵 관리에서 `프로젝트 열기` 로 불러오거나 `프로젝트 저장` 으로 '
            '만든 뒤 다시 눌러 주세요.',
      );
      return;
    }
    // 버튼 한 번으로 저장 → 생성 → 내보내기까지 끝낸다. 어느 단계든 실패하면
    // 예전 파일로 백엔드를 띄우지 않는다.
    final saved = await _saveSettingsBeforeBackend(project);
    if (!saved || !mounted) return;
    final gridExport = await _exportOccupancyGrid(project);
    if (gridExport != null && !gridExport.success) {
      if (!mounted) return;
      await showWaypointErrorDialog(
        context,
        title: 'Nav2 지도 내보내기 실패',
        message: gridExport.message,
      );
      return;
    }
    if (!mounted) return;
    List<MapProjectFile> files;
    try {
      files = await loadMapProjectFiles(project);
    } catch (error) {
      if (!mounted) return;
      await showWaypointErrorDialog(
        context,
        title: 'Open-RMF 백엔드 띄우기',
        message: '설정 파일을 읽지 못했습니다.\n$error',
      );
      return;
    }
    if (files.isEmpty) {
      if (!mounted) return;
      await showWaypointErrorDialog(
        context,
        title: 'Open-RMF 백엔드 띄우기',
        message:
            '`$project` 프로젝트에 만들어진 설정 파일이 없습니다.\n\n'
            '맵 관리에서 `프로젝트 저장` 을 한 번 눌러 주세요.',
      );
      return;
    }
    final exported = await exportProjectConfigFiles(
      mapName: project,
      files: files,
    );
    if (!mounted) return;
    if (!exported.success) {
      await showWaypointErrorDialog(
        context,
        title: '설정을 디스크에 풀지 못했습니다',
        message: exported.message,
      );
      return;
    }
    await _runProjectScript(project);
  }

  Future<void> _stopProjectScript() async {
    final result = await stopProject();
    if (!mounted) return;
    await showWaypointErrorDialog(
      context,
      title: result.success ? '프로젝트 중지 결과' : '중지 실패',
      message: result.message.isEmpty ? '출력이 없습니다.' : result.message,
    );
  }

  /// MySQL 에 있는 설정을 배포 디렉터리로 풀어 놓는다.
  ///
  /// 설정의 원장은 MySQL 이지만 `ros2 launch` 는 파일만 읽는다. 실행 직전에
  /// 이 프로젝트의 파일을 디스크에 내려 두어야 한다.
  Future<void> _exportRmfConfig(
    String mapName,
    List<MapProjectFile> files,
  ) async {
    // 자리 없는 로봇이 있으면 파일을 만들지 않는다.
    //
    // 등록 창은 고를 자리가 하나도 없을 때는 막지 않는다 — 맵을 그리기 전에도
    // 로봇 목록은 짤 수 있어야 하기 때문이다. 그래서 자리 없는 로봇이 남을 수
    // 있고, 예전에 그렇게 저장된 것도 있다. 배포는 여기까지 왔으면 맵이 이미
    // 있으므로, 좌표가 파일에 박히기 전 마지막으로 여기서 막는다.
    //
    // 화면의 목록(_fleetRobots)이 아니라 산출물을 만든 그 목록을 본다. 저장된
    // 프로젝트에서 읽어 오므로 둘이 다를 수 있고, 다르면 검사와 파일이 어긋난다.
    final deployRobots = await _fleetRobotsForDeploy(mapName);
    // ID 를 먼저 본다. 자리를 다 골라도 ID 가 틀리면 fleet adapter 가 죽어서
    // 어차피 주문이 안 먹는다. 예전에 하이픈으로 저장된 로봇이 여기서 걸린다.
    final blocked =
        deployBlockedByRobotId(deployRobots) ??
        deployBlockedMessage(deployRobots);
    if (blocked != null) {
      if (!mounted) return;
      await showWaypointErrorDialog(
        context,
        title: '설정 내보내기 실패',
        message: blocked,
      );
      return;
    }
    final result = await exportProjectConfigFiles(
      mapName: mapName,
      files: files,
    );
    if (!mounted) return;
    await showWaypointErrorDialog(
      context,
      title: result.success ? '설정 내보내기 완료' : '설정 내보내기 실패',
      message: result.success
          ? '${result.message}\n\n'
                '${result.written.join('\n')}\n\n'
                '실행:\n'
                '  source /opt/ros/jazzy/setup.bash\n'
                '  source <robosapiens>/rmf_ws/install/setup.bash\n'
                '  ros2 launch ${result.directory}/$mapName.launch.xml'
          : result.message,
    );
  }

  Widget _fleetFileList(List<MapProjectFile> files) {
    return ListView.separated(
      itemCount: files.length,
      separatorBuilder: (_, _) => const Divider(height: 1),
      itemBuilder: (_, index) {
        final file = files[index];
        return ExpansionTile(
          leading: const Icon(Icons.description_outlined),
          title: Text(file.fileName),
          subtitle: Text('${file.kind} · ${file.content.length}자'),
          children: [
            Container(
              width: double.infinity,
              constraints: const BoxConstraints(maxHeight: 240),
              margin: const EdgeInsets.fromLTRB(16, 0, 16, 12),
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: const Color(0xFFF8FAFC),
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: const Color(0xFFE2E8F0)),
              ),
              child: Scrollbar(
                child: SingleChildScrollView(
                  child: SelectableText(
                    file.content,
                    style: const TextStyle(fontSize: 12, height: 1.4),
                  ),
                ),
              ),
            ),
            Align(
              alignment: Alignment.centerRight,
              child: Padding(
                padding: const EdgeInsets.only(right: 16, bottom: 8),
                child: TextButton.icon(
                  onPressed: () async {
                    await Clipboard.setData(ClipboardData(text: file.content));
                    if (!mounted) return;
                    ScaffoldMessenger.of(context).showSnackBar(
                      SnackBar(content: Text('${file.fileName} 내용을 복사했습니다.')),
                    );
                  },
                  icon: const Icon(Icons.content_copy_outlined, size: 16),
                  label: const Text('복사'),
                ),
              ),
            ),
          ],
        );
      },
    );
  }

  /// 맵 프로젝트 이름을 입력받는다. 취소하면 null.
  Future<String?> _askMapProjectName({
    required String title,
    required String initialName,
    required String confirmLabel,
    String? helperText,
  }) async {
    return showMovableDialog<String>(
      context: context,
      builder: (dialogContext) => _ProjectNameDialog(
        title: title,
        initialName: initialName,
        confirmLabel: confirmLabel,
        helperText: helperText,
      ),
    );
  }

  /// 같은 지도 이름의 프로젝트가 이미 있을 때 어떻게 할지 묻는다.
  Future<MapProjectNameConflictChoice> _askMapProjectNameConflict(
    String mapName,
    MapProjectSummary? existing,
  ) async {
    final saved = existing == null
        ? ''
        : '\n\n저장된 내용: Waypoint ${existing.waypointCount}개 · '
              'Lane ${existing.laneCount}개'
              '${existing.drawingName == null ? '' : ' · 도면 ${existing.drawingName}'}'
              '\n마지막 저장: ${_projectTimestamp(existing.updatedAt)}';
    final choice = await showMovableDialog<MapProjectNameConflictChoice>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        icon: const Icon(Icons.help_outline, size: 36),
        title: const Text('같은 이름의 프로젝트가 있습니다'),
        content: SizedBox(
          width: 420,
          child: Text(
            '`$mapName` 프로젝트가 이미 저장되어 있습니다. '
            '덮어쓰면 그 프로젝트의 Waypoint와 Lane이 지금 작업 내용으로 '
            '완전히 교체되며 되돌릴 수 없습니다.$saved',
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(
              dialogContext,
              MapProjectNameConflictChoice.cancel,
            ),
            child: const Text('취소'),
          ),
          TextButton.icon(
            onPressed: () => Navigator.pop(
              dialogContext,
              MapProjectNameConflictChoice.rename,
            ),
            icon: const Icon(Icons.drive_file_rename_outline, size: 18),
            label: const Text('다른 이름으로 저장'),
          ),
          FilledButton.icon(
            onPressed: () => Navigator.pop(
              dialogContext,
              MapProjectNameConflictChoice.overwrite,
            ),
            icon: const Icon(Icons.save_outlined, size: 18),
            label: Text('`$mapName` 덮어쓰기'),
            style: FilledButton.styleFrom(
              backgroundColor: const Color(0xFFDC2626),
            ),
          ),
        ],
      ),
    );
    return choice ?? MapProjectNameConflictChoice.cancel;
  }

  static String _projectTimestamp(DateTime at) =>
      '${at.year}-${at.month.toString().padLeft(2, '0')}-'
      '${at.day.toString().padLeft(2, '0')} '
      '${at.hour.toString().padLeft(2, '0')}:'
      '${at.minute.toString().padLeft(2, '0')}';

  /// 이름을 먼저 받아 빈 프로젝트를 만든다.
  ///
  /// 이름이 프로젝트의 정체다. 도면 파일 이름이 아니다. 그래서 같은
  /// `warehouse.png` 로도 `2층창고_v2`, `2층창고_v3` 처럼 서로 다른 프로젝트를
  /// 만들 수 있고, 각자 제 디렉터리에 제 데이터를 담는다.
  ///
  /// 만든 즉시 저장소에 쓴다. 이름만 화면에 들고 있으면, 다른 데서 같은 이름을
  /// 저장해 버려도 알 수 없고, 작업하다 앱이 죽으면 이름부터 다시 정해야 한다.
  Future<void> _createNewProject() async {
    final name = await _askMapProjectName(
      title: '새 프로젝트',
      initialName: '',
      confirmLabel: '만들기',
      helperText: '같은 도면으로도 이름이 다르면 별개의 프로젝트가 됩니다.',
    );
    if (name == null || !mounted) return;
    try {
      if (await mapProjectExists(name)) {
        if (!mounted) return;
        await showWaypointErrorDialog(
          context,
          title: '이미 있는 이름입니다',
          message:
              '`$name` 프로젝트가 이미 있습니다.\n\n'
              '그 프로젝트를 이어서 작업하려면 `프로젝트 열기` 로 여세요. '
              '새로 만들려면 다른 이름을 쓰세요 — 뒤에 버전을 붙이는 것이 '
              '나중에 구분하기 쉽습니다(`$name v2`).',
        );
        return;
      }
      // 백지에서 시작한다. 앞 프로젝트의 벽·Waypoint 가 남아 있으면 새
      // 프로젝트에 그대로 저장돼 버린다.
      _recordUndo();
      _fitMapToScreen();
      _clearMapWorkspace();
      if (!mounted) return;
      setState(() {
        _projectName = name;
        _isDeployed = false;
        // 로봇도 프로젝트에 딸린다. 앞 프로젝트의 로봇을 물려받으면 없는
        // 충전소를 가리킨다.
        //
        // `clear()` 를 부르면 안 된다. 이 리스트는 `const []` 로 시작해서 늘
        // 통째로 갈아 끼우는 방식이고, 손대면 `Cannot clear an unmodifiable
        // list` 로 죽는다.
        _fleetRobots = const [];
        _fleetSettings = RmfFleetSettings(fleetName: _fleetNameFor(name));
      });
      await _writeMapProject(name);
      if (!mounted) return;
      await _switchOpenProject(name);
      if (!mounted) return;
      setState(() => _projectFileName = name);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('`$name` 프로젝트를 만들었습니다. 도면을 올리세요.')),
      );
    } catch (error) {
      if (!mounted) return;
      _showProcessingWarning('새 프로젝트', error);
    }
  }

  /// 지금 작업을 MySQL 맵 프로젝트 저장소에 저장한다.
  ///
  /// 지도 이름이 곧 프로젝트 구분자다. 같은 이름이 이미 있으면 덮어쓸지 다른
  /// 이름으로 갈지 먼저 묻는다. 다른 이름을 골랐는데 그 이름도 이미 있으면
  /// 다시 묻는다 — 그래서 반복문이다.
  Future<void> _saveProjectToDatabase() async {
    if (_drawing == null) return;
    try {
      var mapName = _mapName.trim();
      while (true) {
        if (mapName.isEmpty) {
          final asked = await _askMapProjectName(
            title: '맵 프로젝트 저장',
            initialName: '',
            confirmLabel: '저장',
          );
          if (asked == null || !mounted) return;
          mapName = asked;
          continue;
        }
        // 지금 열려 있는 프로젝트에 저장하는 것은 덮어쓰기가 아니라 그냥
        // 저장이다. 여기서 묻지 않아야 한다 — `새 프로젝트` 는 이름을 받는
        // 즉시 레코드를 만들므로, 묻게 두면 첫 저장부터 "이미 있는
        // 이름입니다" 가 떠서 제 프로젝트를 덮어쓸지 고르게 된다.
        if (mapName == _openProjectName) break;
        if (!await mapProjectExists(mapName)) break;
        if (!mounted) return;
        final existing = (await listMapProjects())
            .where((project) => project.mapName == mapName)
            .firstOrNull;
        if (!mounted) return;
        final choice = await _askMapProjectNameConflict(mapName, existing);
        if (!mounted) return;
        if (choice == MapProjectNameConflictChoice.cancel) return;
        if (choice == MapProjectNameConflictChoice.overwrite) break;
        final renamed = await _askMapProjectName(
          title: '다른 이름으로 저장',
          initialName: '$mapName 사본',
          confirmLabel: '저장',
          helperText: '이미 쓰고 있는 이름이면 다시 확인합니다.',
        );
        if (renamed == null || !mounted) return;
        mapName = renamed;
      }
      await _writeMapProject(mapName);
      if (!mounted) return;
      setState(() {
        _projectName = mapName;
        _projectFileName = mapName;
      });
      // 저장한 프로젝트가 곧 열린 프로젝트가 된다. 다른 이름으로 저장했다면
      // 작업 목록도 그 프로젝트의 것으로 갈아 끼운다.
      if (_openProjectName != mapName) {
        await _switchOpenProject(mapName);
        if (!mounted) return;
      }
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('`$mapName` 프로젝트를 MySQL에 저장했습니다.')),
      );
    } catch (error) {
      if (!mounted) return;
      _showProcessingWarning('맵 프로젝트 저장', error);
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text('프로젝트를 저장하지 못했습니다: $error')));
    }
  }

  /// MySQL에 저장된 프로젝트 목록에서 골라 연다.
  Future<void> _openProjectFromDatabase() async {
    try {
      final projects = await listMapProjects();
      if (!mounted) return;
      if (projects.isEmpty) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('MySQL에 저장된 맵 프로젝트가 없습니다.')),
        );
        return;
      }
      final picked = await showMovableDialog<String>(
        context: context,
        builder: (dialogContext) => AlertDialog(
          icon: const Icon(Icons.storage_outlined, size: 36),
          title: const Text('맵 프로젝트 열기'),
          content: SizedBox(
            width: 460,
            height: 360,
            child: ListView.separated(
              itemCount: projects.length,
              separatorBuilder: (_, _) => const Divider(height: 1),
              itemBuilder: (_, index) {
                final project = projects[index];
                return ListTile(
                  leading: const Icon(Icons.map_outlined),
                  title: Text(project.mapName),
                  subtitle: Text(
                    'Waypoint ${project.waypointCount}개 · '
                    'Lane ${project.laneCount}개 · '
                    '${project.hasBuildingYaml ? 'YAML 보관됨' : 'YAML 없음'}\n'
                    '${_projectTimestamp(project.updatedAt)}'
                    '${project.drawingName == null ? '' : ' · ${project.drawingName}'}',
                  ),
                  isThreeLine: true,
                  onTap: () => Navigator.pop(dialogContext, project.mapName),
                );
              },
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext),
              child: const Text('취소'),
            ),
          ],
        ),
      );
      if (picked == null || !mounted) return;
      final payload = await loadMapProject(picked);
      if (!mounted) return;
      if (payload == null) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('`$picked` 프로젝트를 찾지 못했습니다.')));
        return;
      }
      _applyProjectData(
        jsonDecode(payload) as Map<String, dynamic>,
        sourceName: picked,
        fallbackMapName: picked,
      );
      await _loadFleetForProject(picked);
      if (!mounted) return;
      await _switchOpenProject(picked);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('`$picked` 프로젝트를 MySQL에서 불러왔습니다.')),
      );
    } catch (error) {
      if (!mounted) return;
      _showProcessingWarning('맵 프로젝트 열기', error);
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text('프로젝트를 열지 못했습니다: $error')));
    }
  }

  /// 저장된 카테고리 문자열을 현재 이름 체계로 옮긴다.
  ///
  /// v1 은 holding point 를 '일반', parking spot 을 '대기'라고 불렀다. v2 부터
  /// 각각 '대기', '주차'다. '대기'가 두 버전에서 서로 다른 뜻이므로 버전을
  /// 보지 않으면 구분할 수 없다 — 그냥 두면 예전 파일의 주차 자리가 단순
  /// 정지 지점으로 바뀌어 is_parking_spot 이 사라진다.
  static String _migrateWaypointCategory(String category, Object? version) {
    final normalized = category == '드롭오프' ? '드랍오프' : category;
    if (version != 1) return normalized;
    return switch (normalized) {
      '대기' => '주차',
      '일반' => '대기',
      _ => normalized,
    };
  }

  /// `.rmfproject` 파일에서 프로젝트를 연다.
  Future<void> _loadProject() async {
    try {
      final projects = await listProjectFiles();
      if (!mounted) return;
      if (projects.isEmpty) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('project 디렉터리에 저장된 프로젝트가 없습니다.')),
        );
        return;
      }
      final selected = await showMovableDialog<StoredProjectFile>(
        context: context,
        builder: (dialogContext) => AlertDialog(
          icon: const Icon(Icons.folder_copy_outlined, size: 34),
          title: const Text('project 디렉터리에서 불러오기'),
          content: SizedBox(
            width: 460,
            height: 360,
            child: ListView.separated(
              itemCount: projects.length,
              separatorBuilder: (_, _) => const Divider(height: 1),
              itemBuilder: (_, index) {
                final project = projects[index];
                return ListTile(
                  leading: const Icon(Icons.description_outlined),
                  title: Text(project.projectName),
                  subtitle: Text(
                    '${project.fileName}\n'
                    '${_projectTimestamp(project.modifiedAt)} · '
                    '${(project.size / 1024).toStringAsFixed(1)} KB',
                  ),
                  isThreeLine: true,
                  onTap: () => Navigator.pop(dialogContext, project),
                );
              },
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext),
              child: const Text('취소'),
            ),
          ],
        ),
      );
      if (selected == null) return;
      final fileName = selected.fileName;
      final bytes = await readProjectFile(fileName);
      final data = jsonDecode(utf8.decode(bytes)) as Map<String, dynamic>;
      if (!mounted) return;
      _applyProjectData(
        data,
        sourceName: fileName,
        fallbackMapName: fileName.replaceFirst(RegExp(r'\.rmfproject$'), ''),
      );
      // 파일에서 연 맵은 아직 MySQL의 프로젝트가 아니다. `프로젝트 저장`으로
      // 등록하기 전까지는 작업을 붙일 곳이 없으므로 열린 프로젝트를 비운다.
      await _switchOpenProject(null);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('$fileName 작업을 불러왔습니다. 작업을 만들려면 프로젝트로 저장하세요.')),
      );
    } catch (error) {
      if (!mounted) return;
      _showProcessingWarning('작업 불러오기', error);
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text('작업을 불러오지 못했습니다: $error')));
    }
  }

  /// 파싱한 프로젝트 JSON 을 편집 화면에 적용한다. 파일에서 왔든 MySQL 맵
  /// 프로젝트 저장소에서 왔든 같은 경로를 탄다.
  void _applyProjectData(
    Map<String, dynamic> data, {
    required String sourceName,
    required String fallbackMapName,
  }) {
    {
      final projectVersion = data['version'];
      if (data['format'] != 'robosapiens-map-project' ||
          (projectVersion != 1 && projectVersion != 2)) {
        throw const FormatException('지원하지 않는 프로젝트 파일입니다.');
      }
      final drawingData = data['drawing'] as Map<String, dynamic>?;
      final measurementData = data['measurement'] as Map<String, dynamic>?;
      final safetyData = data['robotSafety'] as Map<String, dynamic>?;
      final waypointData = data['waypoints'] as List<dynamic>;
      final loadedWaypoints = <Offset>[];
      final loadedNames = <Offset, String>{};
      final loadedTypes = <Offset, String>{};
      for (final item in waypointData) {
        final waypoint = item as Map<String, dynamic>;
        final point = _decodeOffset(waypoint['point']);
        loadedWaypoints.add(point);
        loadedNames[point] = waypoint['name'] as String? ?? '';
        final category = waypoint['category'] as String? ?? '대기';
        loadedTypes[point] = _migrateWaypointCategory(category, projectVersion);
      }
      final loadedOverrides = <Offset, Offset>{};
      for (final item in data['wallVertexOverrides'] as List<dynamic>) {
        final entry = item as Map<String, dynamic>;
        loadedOverrides[_decodeOffset(entry['from'])] = _decodeOffset(
          entry['to'],
        );
      }
      final loadedLanes = _decodeLines(data['recommendedLanes']);
      final loadedDirections = <(Offset, Offset), String>{};
      final loadedSpeedLimits = <(Offset, Offset), double>{};
      final loadedOrientations = <(Offset, Offset), String>{};
      final loadedMutexGroups = <(Offset, Offset), String>{};
      for (final item
          in (data['laneDirections'] as List<dynamic>?) ?? const []) {
        final entry = item as Map<String, dynamic>;
        final lane = (
          _decodeOffset(entry['start']),
          _decodeOffset(entry['end']),
        );
        loadedDirections[lane] = entry['direction'] as String? ?? '양방향';
        if (entry['speedLimit'] case final num speed) {
          loadedSpeedLimits[lane] = speed.toDouble();
        }
        if (entry['orientation'] case final String orientation) {
          loadedOrientations[lane] = orientation;
        }
        if (entry['mutex'] case final String mutex when mutex.isNotEmpty) {
          loadedMutexGroups[lane] = mutex;
        }
      }
      for (final lane in loadedLanes) {
        loadedDirections.putIfAbsent(lane, () => '양방향');
      }
      final loadedMapName = (data['mapName'] as String?)?.trim();
      _recordUndo();
      _fitMapToScreen();
      setState(() {
        _projectName = loadedMapName?.isNotEmpty == true
            ? loadedMapName
            : fallbackMapName;
        _projectFileName = sourceName;
        _mapScenarioSummary = data['mapScenarioSummary'] as String?;
        // 어느 지도를 쓰기로 했는지도 프로젝트에 딸린다. 안 되살리면 다음
        // 저장에서 도면 지도로 조용히 돌아간다.
        _useSlamMap = data['useSlamMap'] as bool? ?? false;
        final gridSettings = data['gridResolution'] as Map<String, dynamic>?;
        if (gridSettings != null) {
          _gridResolutionMode =
              _GridResolutionMode.values
                  .where((mode) => mode.name == gridSettings['mode'])
                  .firstOrNull ??
              _GridResolutionMode.target;
          _gridTargetWidth =
              (gridSettings['targetWidth'] as num?)?.toInt() ?? 800;
          _gridTargetHeight =
              (gridSettings['targetHeight'] as num?)?.toInt() ?? 600;
          _gridPadToTarget = gridSettings['padToTarget'] as bool? ?? true;
          _gridManualResolution =
              (gridSettings['manualMeters'] as num?)?.toDouble() ?? .02;
        }
        // 방금 읽은 것이 곧 저장된 상태다. 여기서 기준을 잡아야 그리드맵
        // 화면이 "저장할 것 없음" 으로 시작한다.
        _savedGridSettings = GridMapSettings(
          mode: _gridResolutionMode.name,
          targetWidth: _gridTargetWidth,
          targetHeight: _gridTargetHeight,
          padToTarget: _gridPadToTarget,
          manualResolution: _gridManualResolution,
          useSlamMap: _useSlamMap,
        );
        _robotWidthMeters =
            (safetyData?['widthMeters'] as num?)?.toDouble() ?? .6;
        _turningRadiusMeters =
            (safetyData?['turningRadiusMeters'] as num?)?.toDouble() ?? .3;
        _localizationMarginMeters =
            (safetyData?['localizationMarginMeters'] as num?)?.toDouble() ?? .1;
        // 예전 프로젝트에는 이 값이 없다. 그때 배포한 월드가 2.5m 였으므로
        // 없으면 2.5m 다 — 열었다고 벽 높이가 달라지면 안 된다.
        _wallHeightMeters =
            (data['wallHeightMeters'] as num?)?.toDouble() ?? defaultWallHeight;
        _manualLaneDisplayWidth = (data['manualLaneDisplayWidth'] as num?)
            ?.toDouble();
        _rosDomainId =
            (data['rosDomainId'] as num?)?.toInt() ?? defaultRosDomainId;
        _drawing = drawingData == null
            ? null
            : UploadedDrawing(
                name: drawingData['name'] as String,
                extension: drawingData['extension'] as String,
                size: drawingData['size'] as int,
                bytes: drawingData['bytes'] == null
                    ? null
                    : base64Decode(drawingData['bytes'] as String),
                pixelWidth: drawingData['pixelWidth'] as int?,
                pixelHeight: drawingData['pixelHeight'] as int?,
              );
        _stage =
            MapStage.values[(data['stage'] as int).clamp(
              0,
              MapStage.values.length - 1,
            )];
        _measurement = measurementData == null
            ? null
            : _MapMeasurement(
                start: _decodeOffset(measurementData['start']),
                end: _decodeOffset(measurementData['end']),
                length: (measurementData['length'] as num).toDouble(),
                unit: measurementData['unit'] as String,
              );
        _wallMask = _decodeMask(data['wallMask']);
        _floorMask = _decodeMask(data['floorMask']);
        _previousWallMask = _decodeMask(data['previousWallMask']);
        _wallsDetected = data['wallsDetected'] as bool;
        _floorGenerated = data['floorGenerated'] as bool;
        _wallColor = Color(data['wallColor'] as int);
        _floorColor = Color(data['floorColor'] as int);
        _manualWalls
          ..clear()
          ..addAll(_decodeLines(data['manualWalls']));
        _wallVertexOverrides
          ..clear()
          ..addAll(loadedOverrides);
        _frozenAutoWalls = _decodeLines(data['frozenAutoWalls']);
        _recommendedLanes = loadedLanes;
        _laneDirections
          ..clear()
          ..addAll(loadedDirections);
        _laneSpeedLimits
          ..clear()
          ..addAll(loadedSpeedLimits);
        _laneOrientations
          ..clear()
          ..addAll(loadedOrientations);
        _laneMutexGroups
          ..clear()
          ..addAll(loadedMutexGroups);
        _laneWaypoints
          ..clear()
          ..addAll(loadedWaypoints);
        _waypointNames
          ..clear()
          ..addAll(loadedNames);
        _waypointTypes
          ..clear()
          ..addAll(loadedTypes);
        _activeLaneEndpoint = data['activeLaneEndpoint'] == null
            ? null
            : _decodeOffset(data['activeLaneEndpoint']);
        _isWaypointMode = false;
        _isMeasurementMode = false;
        _isWallEraseMode = false;
        _isWallConnectMode = false;
        _isWallEndpointEditMode = false;
        _pendingWallVertex = null;
        _isDeployed = false;
        _vertexLabelRevision++;
      });
    }
  }

  List<Offset> _floorOutline() {
    // A generated Floor must not introduce a second set of vertices beside
    // an existing Wall outline. Reuse the structural Wall vertices so Floor
    // generation cannot move, duplicate, or renumber the Wall geometry.
    final wallVertices = _uniqueVertices([
      for (final wall in _visibleWallSegments()) ...[wall.$1, wall.$2],
    ]);
    if (wallVertices.length >= 3) return _convexHull(wallVertices);

    final points = _floorMask?.points;
    if (points == null || points.length < 3) return const [];
    final step = math.max(1, points.length ~/ 6000);
    return _convexHull([
      for (var i = 0; i < points.length; i += step) points[i],
    ]);
  }

  List<Offset> _convexHull(Iterable<Offset> points) {
    final sorted = _uniqueVertices(points)
      ..sort((a, b) {
        final x = a.dx.compareTo(b.dx);
        return x != 0 ? x : a.dy.compareTo(b.dy);
      });
    if (sorted.length < 3) return sorted;
    double cross(Offset origin, Offset a, Offset b) =>
        (a.dx - origin.dx) * (b.dy - origin.dy) -
        (a.dy - origin.dy) * (b.dx - origin.dx);
    final lower = <Offset>[];
    for (final point in sorted) {
      while (lower.length >= 2 &&
          cross(lower[lower.length - 2], lower.last, point) <= 0) {
        lower.removeLast();
      }
      lower.add(point);
    }
    final upper = <Offset>[];
    for (final point in sorted.reversed) {
      while (upper.length >= 2 &&
          cross(upper[upper.length - 2], upper.last, point) <= 0) {
        upper.removeLast();
      }
      upper.add(point);
    }
    lower.removeLast();
    upper.removeLast();
    return [...lower, ...upper];
  }

  List<(Offset, Offset)> _wallSegments() {
    final mask = _wallMask;
    if (mask == null || mask.points.isEmpty) return const [];
    final stride = mask.sampleSize;
    final rows = <int, Set<int>>{};
    final columns = <int, Set<int>>{};
    for (final point in mask.points) {
      final x = (point.dx / stride).round();
      final y = (point.dy / stride).round();
      rows.putIfAbsent(y, () => <int>{}).add(x);
      columns.putIfAbsent(x, () => <int>{}).add(y);
    }
    final candidates = <_AxisWall>[];
    final minimumLength = math.max(
      stride * 6,
      math.min(mask.width, mask.height) * .025,
    );
    void addRuns(Map<int, Set<int>> groups, bool horizontal) {
      final keys = groups.keys.toList()..sort();
      for (final key in keys) {
        final values = groups[key]!.toList()..sort();
        if (values.isEmpty) continue;
        var start = values.first;
        var previous = start;
        void finishRun() {
          final runLength = (previous - start) * stride;
          if (runLength < minimumLength) return;
          candidates.add(
            _AxisWall(
              horizontal: horizontal,
              axis: key * stride,
              start: start * stride,
              end: previous * stride,
            ),
          );
        }

        for (final value in values.skip(1)) {
          if (value > previous + 1) {
            finishRun();
            start = value;
          }
          previous = value;
        }
        finishRun();
      }
    }

    addRuns(rows, true);
    addRuns(columns, false);

    // Collapse the many parallel scan-lines produced by one thick wall into
    // one structural center-line.
    final merged = <_AxisWall>[];
    final thicknessTolerance = stride * 5;
    for (final candidate in candidates) {
      _AxisWall? match;
      for (final existing in merged) {
        if (existing.horizontal != candidate.horizontal ||
            (existing.axis - candidate.axis).abs() > thicknessTolerance) {
          continue;
        }
        final overlap =
            math.min(existing.end, candidate.end) -
            math.max(existing.start, candidate.start);
        if (overlap >= math.min(existing.length, candidate.length) * .55) {
          match = existing;
          break;
        }
      }
      if (match == null) {
        merged.add(candidate.copy());
      } else {
        match.absorb(candidate);
      }
    }

    // Join collinear fragments separated only by small raster gaps.
    merged.sort((a, b) {
      final direction = a.horizontal == b.horizontal
          ? 0
          : (a.horizontal ? -1 : 1);
      if (direction != 0) return direction;
      final axis = a.axis.compareTo(b.axis);
      return axis != 0 ? axis : a.start.compareTo(b.start);
    });
    final simplified = <_AxisWall>[];
    for (final segment in merged) {
      final previous = simplified.isEmpty ? null : simplified.last;
      if (previous != null &&
          previous.horizontal == segment.horizontal &&
          (previous.axis - segment.axis).abs() <= stride * 2 &&
          segment.start <= previous.end + stride * 5) {
        previous.absorb(segment);
      } else {
        simplified.add(segment.copy());
      }
    }

    simplified.removeWhere((wall) => wall.length < minimumLength);
    final floorPoints = _floorMask?.points;
    if (floorPoints != null && floorPoints.isNotEmpty) {
      for (final wall in simplified) {
        wall.chooseFloorBoundary(floorPoints, stride);
      }
    }
    simplified.sort((a, b) => b.length.compareTo(a.length));
    final result = [for (final wall in simplified.take(48)) wall.offsets];
    return _snapWallCorners(result, stride * 4);
  }

  List<(Offset, Offset)> _effectiveAutoWalls() =>
      _wallsDetected ? _frozenAutoWalls : const [];

  List<(Offset, Offset)> _snapWallCorners(
    List<(Offset, Offset)> walls,
    double tolerance,
  ) {
    final result = [...walls];
    bool horizontal((Offset, Offset) wall) =>
        (wall.$1.dy - wall.$2.dy).abs() <= .01;
    int nearestEndpoint((Offset, Offset) wall, Offset point) =>
        (wall.$1 - point).distance <= (wall.$2 - point).distance ? 0 : 1;
    double endpointDistance((Offset, Offset) wall, Offset point) =>
        math.min((wall.$1 - point).distance, (wall.$2 - point).distance);
    (Offset, Offset) replaceEndpoint(
      (Offset, Offset) wall,
      int endpoint,
      Offset point,
    ) => endpoint == 0 ? (point, wall.$2) : (wall.$1, point);

    for (var i = 0; i < result.length; i++) {
      for (var j = i + 1; j < result.length; j++) {
        if (horizontal(result[i]) == horizontal(result[j])) continue;
        final horizontalIndex = horizontal(result[i]) ? i : j;
        final verticalIndex = horizontal(result[i]) ? j : i;
        final horizontalWall = result[horizontalIndex];
        final verticalWall = result[verticalIndex];
        final intersection = Offset(verticalWall.$1.dx, horizontalWall.$1.dy);
        if (endpointDistance(horizontalWall, intersection) > tolerance ||
            endpointDistance(verticalWall, intersection) > tolerance) {
          continue;
        }
        result[horizontalIndex] = replaceEndpoint(
          horizontalWall,
          nearestEndpoint(horizontalWall, intersection),
          intersection,
        );
        result[verticalIndex] = replaceEndpoint(
          verticalWall,
          nearestEndpoint(verticalWall, intersection),
          intersection,
        );
      }
    }
    return result;
  }

  List<Offset> _uniqueVertices(Iterable<Offset> points) {
    final result = <Offset>[];
    for (final point in points) {
      if (!result.any((existing) => (existing - point).distance <= .01)) {
        result.add(point);
      }
    }
    return result;
  }

  List<Offset> _clockwiseFromLeft(Iterable<Offset> points) {
    final result = _uniqueVertices(points);
    if (result.length < 2) return result;
    final center = Offset(
      result.map((point) => point.dx).reduce((a, b) => a + b) / result.length,
      result.map((point) => point.dy).reduce((a, b) => a + b) / result.length,
    );
    final first = result.reduce((a, b) {
      if (a.dx != b.dx) return a.dx < b.dx ? a : b;
      return a.dy < b.dy ? a : b;
    });
    final startAngle = math.atan2(first.dy - center.dy, first.dx - center.dx);
    double order(Offset point) {
      final angle = math.atan2(point.dy - center.dy, point.dx - center.dx);
      return (angle - startAngle + math.pi * 2) % (math.pi * 2);
    }

    result.sort((a, b) {
      final angle = order(a).compareTo(order(b));
      if (angle != 0) return angle;
      return (a - center).distance.compareTo((b - center).distance);
    });
    return result;
  }

  List<Offset> _visibleMapVertices() {
    final measurement = _measurement;
    final vertices = <Offset>[
      if (measurement != null) measurement.start,
      if (measurement != null) measurement.end,
    ];
    final walls = _visibleWallSegments();
    final wallVertices = _clockwiseFromLeft([
      for (final wall in walls) ...[wall.$1, wall.$2],
    ]);
    vertices.addAll(wallVertices);

    final floorOnly = <Offset>[];
    for (final point in _floorOutline()) {
      final sharesWall = wallVertices.any(
        (wallVertex) =>
            (wallVertex - point).distance <= _floorVertexSnapTolerance,
      );
      if (!sharesWall) floorOnly.add(point);
    }
    vertices.addAll(_clockwiseFromLeft(floorOnly));
    vertices.addAll(
      _uniqueVertices([..._laneWaypoints]).where(
        (point) =>
            !vertices.any((existing) => (existing - point).distance <= .01),
      ),
    );
    return vertices;
  }

  List<(Offset, Offset)> _visibleWallSegments() {
    if (!_wallsDetected) return const [];
    final walls = _applyWallVertexOverrides(_effectiveAutoWalls());
    walls.addAll(_applyWallVertexOverrides(_manualWalls));
    return walls;
  }

  /// [mapName] 을 주면 그 이름으로 YAML을 만든다. 다른 이름으로 프로젝트를
  /// 저장할 때, 아직 화면에 반영되지 않은 새 이름을 쓰기 위한 통로다.
  String _buildBuildingYaml({String? mapName}) {
    final yamlMapName = mapName ?? _mapName;
    final drawing = _drawing;
    final measurement = _measurement;
    final vertices = _visibleMapVertices();
    final measurementIndices = measurement == null ? <int>[] : <int>[0, 1];
    final floorOutline = _floorOutline();
    int vertexIndex(Offset point) {
      for (var i = 0; i < vertices.length; i++) {
        if ((vertices[i] - point).distance <= .01) return i;
      }
      vertices.add(point);
      return vertices.length - 1;
    }

    final floorSnapTolerance = _floorVertexSnapTolerance;
    int floorVertexIndex(Offset point) {
      final structuralStart = measurement == null ? 0 : 2;
      for (var i = structuralStart; i < vertices.length; i++) {
        if ((vertices[i] - point).distance <= floorSnapTolerance) return i;
      }
      return vertexIndex(point);
    }

    final floorIndices = [
      for (final point in floorOutline) floorVertexIndex(point),
    ];
    final wallIndices = <(int, int)>[];
    final wallKeys = <String>{};
    bool addWallIndex(int start, int end) {
      if (start == end) return false;
      final low = math.min(start, end);
      final high = math.max(start, end);
      final key = '$low:$high';
      if (!wallKeys.add(key)) return false;
      wallIndices.add((start, end));
      return true;
    }

    for (final wall in _visibleWallSegments()) {
      addWallIndex(vertexIndex(wall.$1), vertexIndex(wall.$2));
    }
    final laneIndices = <(int, int, String)>[
      for (final lane in _recommendedLanes)
        (
          vertexIndex(lane.$1),
          vertexIndex(lane.$2),
          _laneDirections[lane] ?? '양방향',
        ),
    ];
    final buffer = StringBuffer()
      ..writeln('coordinate_system: reference_image')
      ..writeln('graphs: {}')
      ..writeln('reference_level_name: L1')
      ..writeln('levels:')
      ..writeln('  L1:')
      ..writeln('    drawing:')
      ..writeln('      filename: "${_yamlEscape(drawing?.name ?? '')}"')
      ..writeln('    elevation: 0.0')
      ..writeln('    floors:');
    if (floorIndices.length < 3) {
      buffer.writeln('      []');
    } else {
      buffer
        ..writeln(
          '      - parameters: {ceiling_scale: [3, 1], ceiling_texture: [1, blue_linoleum], indoor: [2, 0], texture_name: [1, blue_linoleum], texture_rotation: [3, 0], texture_scale: [3, 1]}',
        )
        ..writeln('        vertices: [${floorIndices.join(', ')}]');
    }
    buffer
      ..writeln('    layers: {}')
      ..writeln('    lanes:');
    if (laneIndices.isEmpty) {
      buffer.writeln('      []');
    } else {
      for (final lane in laneIndices) {
        final sourceLane = _recommendedLanes[laneIndices.indexOf(lane)];
        final reverse = lane.$3 == '역방향';
        final start = reverse ? lane.$2 : lane.$1;
        final end = reverse ? lane.$1 : lane.$2;
        final bidirectional = lane.$3 == '양방향';
        final properties = <String>[
          'bidirectional: [4, $bidirectional]',
          'graph_idx: [2, 0]',
          if (_laneSpeedLimits[sourceLane] case final speed?)
            'speed_limit: [3, ${speed.toStringAsFixed(3)}]',
          if (_laneOrientations[sourceLane] case final orientation?)
            'orientation: [1, $orientation]',
          if (_laneMutexGroups[sourceLane] case final mutex?)
            'mutex: [1, "${_yamlEscape(mutex)}"]',
        ];
        buffer.writeln('      - [$start, $end, {${properties.join(', ')}}]');
      }
    }
    buffer.writeln('    measurements:');
    if (measurement == null) {
      buffer.writeln('      []');
    } else {
      final meters = measurement.unit == 'ft'
          ? measurement.length * 0.3048
          : measurement.length;
      buffer.writeln(
        '      - [${measurementIndices[0]}, ${measurementIndices[1]}, {distance: [3, ${meters.toStringAsFixed(4)}]}]',
      );
    }
    buffer.writeln('    vertices:');
    if (vertices.isEmpty) {
      buffer.writeln('      []');
    } else {
      for (var i = 0; i < vertices.length; i++) {
        final point = vertices[i];
        final waypointType = _waypointTypes[point];
        final waypointName = _waypointNames[point];
        final name = measurement != null && i == measurementIndices.first
            ? 'measurement_start'
            : measurement != null && i == measurementIndices.last
            ? 'measurement_end'
            : waypointName ?? (waypointType != null ? 'waypoint_$i' : '');
        final trafficEditorProperty = switch (waypointType) {
          '충전' => 'is_charger',
          '주차' => 'is_parking_spot',
          '대기' => 'is_holding_point',
          _ => null,
        };
        final waypointProperties = <String>[
          if (trafficEditorProperty != null)
            '$trafficEditorProperty: [4, true]',
          if (waypointType == '픽업' && waypointName?.trim().isNotEmpty == true)
            'pickup_dispenser: [1, "${_yamlEscape(waypointName!.trim())}"]',
          if (waypointType == '드랍오프' && waypointName?.trim().isNotEmpty == true)
            'dropoff_ingestor: [1, "${_yamlEscape(waypointName!.trim())}"]',
          if (waypointType == '설비') 'robosapiens_equipment: [4, true]',
        ];
        final properties = waypointProperties.isEmpty
            ? ''
            : ', {${waypointProperties.join(', ')}}';
        buffer.writeln(
          '      - [${point.dx.toStringAsFixed(3)}, ${point.dy.toStringAsFixed(3)}, 0.0, "${_yamlEscape(name)}"$properties]',
        );
      }
    }
    buffer.writeln('    walls:');
    if (wallIndices.isEmpty) {
      buffer.writeln('      []');
    } else {
      // `texture_height` 가 벽 높이다. traffic_editor 에서는 벽 한 장에
      // 텍스처를 한 번 입히는 높이라, 벽 높이와 같은 값을 쓴다(기본 2.5m).
      // 배포 스크립트가 이 값을 읽어 Gazebo 벽 모델의 높이로 세운다.
      final height = _wallHeightMeters.toStringAsFixed(3);
      for (final wall in wallIndices) {
        buffer.writeln(
          '      - [${wall.$1}, ${wall.$2}, {alpha: [3, 1], texture_height: [3, $height], texture_name: [1, default], texture_scale: [3, 1], texture_width: [3, 1]}]',
        );
      }
    }
    buffer
      ..writeln('lifts: {}')
      ..writeln('name: "${_yamlEscape(yamlMapName)}"');
    return buffer.toString();
  }

  Future<void> _downloadBuildingYaml() async {
    if (_drawing == null) return;
    if (_showMapValidationWarnings()) return;
    try {
      final yaml = _buildBuildingYaml();
      final path = await FilePicker.platform.saveFile(
        dialogTitle: 'Open-RMF 맵 저장',
        fileName: _yamlFileName,
        type: FileType.custom,
        allowedExtensions: const ['yaml'],
        bytes: Uint8List.fromList(utf8.encode(yaml)),
      );
      if (!mounted) return;
      if (path != null) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('$_yamlFileName 파일을 저장했습니다.')));
      }
    } catch (error) {
      if (!mounted) return;
      _showProcessingWarning('YAML 저장', error);
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text('YAML 파일을 저장하지 못했습니다: $error')));
    }
  }

  Future<void> _copyBuildingYaml() async {
    if (_drawing == null) return;
    if (_showMapValidationWarnings()) return;
    try {
      await Clipboard.setData(ClipboardData(text: _buildBuildingYaml()));
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('$_yamlFileName 내용을 클립보드에 복사했습니다.')),
      );
    } catch (error) {
      _showProcessingWarning('YAML 복사', error);
    }
  }

  Future<void> _deployMap() async {
    final drawing = _drawing;
    if (drawing == null) return;
    if (!drawing.isImage || drawing.bytes == null) {
      _showProcessingWarning(
        'Open-RMF 맵 배포',
        'PNG 또는 JPG 원본 이미지가 포함된 맵만 배포할 수 있습니다.',
      );
      return;
    }
    if (_showMapValidationWarnings()) return;

    final shouldDeploy = await showMovableDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        icon: const Icon(
          Icons.rocket_launch_outlined,
          color: Color(0xFF2563EB),
          size: 34,
        ),
        title: Row(
          children: [
            const Expanded(child: Text('맵을 배포할까요?')),
            IconButton(
              onPressed: () => Navigator.pop(dialogContext, false),
              icon: const Icon(Icons.close),
              tooltip: '닫기',
            ),
          ],
        ),
        content: SizedBox(
          width: 390,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text('다음 도면을 Open-RMF 운영 맵으로 배포합니다.'),
              const SizedBox(height: 18),
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(14),
                decoration: BoxDecoration(
                  color: const Color(0xFFF8FAFC),
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(color: const Color(0xFFE2E8F0)),
                ),
                child: Row(
                  children: [
                    const Icon(Icons.map_outlined, color: Color(0xFF2563EB)),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            drawing.name.split('.').first,
                            style: const TextStyle(
                              fontWeight: FontWeight.w700,
                              color: Color(0xFF1E293B),
                            ),
                          ),
                          const SizedBox(height: 3),
                          Text(
                            '${drawing.extension.toUpperCase()} · ${drawing.readableSize}',
                            style: const TextStyle(
                              fontSize: 12,
                              color: Color(0xFF64748B),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 14),
              const Text(
                '오류 검증 → YAML/이미지 저장 → nav graph/world 생성 → '
                'RMF 맵 설치 → Map Server/Fleet Adapter 재시작 → 지도 수신 확인',
                style: TextStyle(
                  fontSize: 12,
                  color: Color(0xFF64748B),
                  height: 1.5,
                ),
              ),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('취소'),
          ),
          FilledButton.icon(
            onPressed: () => Navigator.pop(dialogContext, true),
            icon: const Icon(Icons.rocket_launch, size: 17),
            label: const Text('배포하기'),
          ),
        ],
      ),
    );

    if (shouldDeploy != true || !mounted) return;
    showMovableDialog<void>(
      context: context,
      barrierDismissible: false,
      builder: (dialogContext) => const PopScope(
        canPop: false,
        child: AlertDialog(
          content: SizedBox(
            width: 430,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                CircularProgressIndicator(),
                SizedBox(height: 20),
                Text(
                  'Open-RMF 맵을 배포하고 있습니다…',
                  style: TextStyle(fontWeight: FontWeight.w700),
                ),
                SizedBox(height: 8),
                Text('생성 및 서비스 재시작에는 시간이 걸릴 수 있습니다.'),
              ],
            ),
          ),
        ),
      ),
    );
    final result = await deployMapProject(
      mapName: _deploymentMapName,
      yaml: _buildBuildingYaml(),
      imageName: drawing.name,
      imageBytes: drawing.bytes!,
      rosDomainId: _rosDomainId,
    );
    if (!mounted) return;
    Navigator.of(context, rootNavigator: true).pop();
    if (!result.success) {
      _showProcessingWarning('Open-RMF 맵 배포', result.output);
      await _showDeploymentResultDialog(success: false, output: result.output);
      return;
    }
    setState(() {
      _stage = MapStage.deploy;
      _isDeployed = true;
      _processingWarning = null;
    });
    await _showDeploymentResultDialog(success: true, output: result.output);
  }

  Future<void> _showDeploymentResultDialog({
    required bool success,
    required String output,
  }) => showMovableDialog<void>(
    context: context,
    builder: (dialogContext) => AlertDialog(
      icon: Icon(
        success ? Icons.check_circle_outline : Icons.error_outline,
        color: success ? const Color(0xFF15803D) : const Color(0xFFDC2626),
        size: 38,
      ),
      title: Text(success ? '맵 배포 완료' : '맵 배포 실패'),
      content: SizedBox(
        width: 620,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(success ? '새 지도 수신까지 확인했습니다.' : '아래 로그를 복사해 원인을 확인해 주세요.'),
            const SizedBox(height: 14),
            Container(
              constraints: const BoxConstraints(maxHeight: 360),
              width: double.infinity,
              padding: const EdgeInsets.all(12),
              color: const Color(0xFF0F172A),
              child: SingleChildScrollView(
                child: SelectableText(
                  output,
                  style: const TextStyle(
                    color: Color(0xFFE2E8F0),
                    fontFamily: 'monospace',
                    fontSize: 12,
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
      actions: [
        TextButton.icon(
          onPressed: () async {
            await Clipboard.setData(ClipboardData(text: output));
            if (!dialogContext.mounted) return;
            ScaffoldMessenger.of(
              dialogContext,
            ).showSnackBar(const SnackBar(content: Text('배포 로그를 복사했습니다.')));
          },
          icon: const Icon(Icons.copy_outlined, size: 18),
          label: const Text('로그 복사'),
        ),
        FilledButton(
          onPressed: () => Navigator.pop(dialogContext),
          child: const Text('확인'),
        ),
      ],
    ),
  );

  @override
  Widget build(BuildContext context) {
    return CallbackShortcuts(
      bindings: {
        const SingleActivator(LogicalKeyboardKey.keyZ, control: true): _undo,
        const SingleActivator(LogicalKeyboardKey.keyX, control: true):
            _requestAppExit,
        const SingleActivator(LogicalKeyboardKey.escape): _finishCurrentLane,
      },
      child: Focus(
        autofocus: true,
        child: Scaffold(
          body: Row(
            children: [
              _NavigationRail(
                selectedIndex: _selectedMenu,
                onSelected: (index) => setState(() => _selectedMenu = index),
              ),
              Expanded(
                child: Column(
                  children: [
                    _TopBar(
                      title: const [
                        '대시보드',
                        '맵 관리',
                        '그리드맵',
                        '로봇 관리',
                        'WorkCell 관리',
                        '작업 관리',
                        '로봇 모델 관리',
                        'ROS2 확인',
                        '설정 파일',
                        '로그 분석',
                        '운영 분석',
                        '프로젝트 분석',
                      ][_selectedMenu],
                    ),
                    Expanded(
                      child: _selectedMenu == _menuDashboard
                          ? _MainDashboard(
                              drawing: _robotRuntimeDrawing,
                              mapName:
                                  _robotDeployedMap?.summary.name ?? _mapName,
                              openProjectName: _openProjectName,
                              mapReady:
                                  (_robotDeployedMap?.waypoints ??
                                          _laneWaypoints)
                                      .isNotEmpty,
                              deployed:
                                  _isDeployed || _robotDeployedMap != null,
                              lanes:
                                  _robotDeployedMap?.lanes ?? _recommendedLanes,
                              waypoints:
                                  _robotDeployedMap?.waypoints ??
                                  _laneWaypoints,
                              waypointNames:
                                  _robotDeployedMap?.waypointNames ??
                                  _waypointNames,
                              robots: _mockRobots,
                              tasks: _mockTasks,
                              warning: _processingWarning,
                              onOpenMap: () =>
                                  setState(() => _selectedMenu = _menuMap),
                              onOpenRobots: () =>
                                  setState(() => _selectedMenu = _menuRobots),
                              onOpenTasks: () =>
                                  setState(() => _selectedMenu = _menuTasks),
                              onLoadMap: _loadMapForRobots,
                              onSpawn: _spawnMockRobot,
                              onCreateTask: _createMockTask,
                            )
                          : _selectedMenu == _menuMap
                          ? SingleChildScrollView(
                              padding: const EdgeInsets.fromLTRB(
                                32,
                                30,
                                32,
                                40,
                              ),
                              child: Center(
                                child: ConstrainedBox(
                                  constraints: const BoxConstraints(
                                    maxWidth: 1767,
                                  ),
                                  child: Column(
                                    crossAxisAlignment:
                                        CrossAxisAlignment.start,
                                    children: [
                                      _PageHeading(
                                        onHelp: () => _showUsageGuide(
                                          context,
                                          _UsageGuideTopic.map,
                                        ),
                                        onUpload: _pickDrawing,
                                        exportEnabled: _drawing != null,
                                        onValidate: _showValidationDialog,
                                        onRecommend:
                                            _showLaneRecommendationsDialog,
                                        onDownload: _downloadBuildingYaml,
                                        onCopy: _copyBuildingYaml,
                                        onSaveProject: _saveProject,
                                        onSaveProjectAs: _saveProjectAs,
                                        onLoadProject: _loadProject,
                                        onSaveToDatabase:
                                            _saveProjectToDatabase,
                                        onOpenFromDatabase:
                                            _openProjectFromDatabase,
                                        onNewProject: _createNewProject,
                                        onRmfConfig: _showRmfConfigDialog,
                                      ),
                                      const SizedBox(height: 14),
                                      _MapFileStatus(
                                        sourceLabel: '현재 작업',
                                        sourceName:
                                            _projectFileName ?? '저장 전 편집 작업',
                                        buildingYamlName: _yamlFileName,
                                        pendingDeployment: !_isDeployed,
                                      ),
                                      const SizedBox(height: 8),
                                      Align(
                                        alignment: Alignment.centerRight,
                                        child: Wrap(
                                          spacing: 8,
                                          runSpacing: 8,
                                          children: [
                                            OutlinedButton.icon(
                                              onPressed:
                                                  _showScenarioMapAssistant,
                                              icon: const Icon(
                                                Icons.auto_awesome_outlined,
                                                size: 18,
                                              ),
                                              label: const Text('시나리오 맵 자동 완성'),
                                            ),
                                            OutlinedButton.icon(
                                              onPressed:
                                                  _showRobotSafetySettings,
                                              icon: const Icon(
                                                Icons
                                                    .health_and_safety_outlined,
                                                size: 18,
                                              ),
                                              label: const Text('로봇 안전 기준'),
                                            ),
                                            // 지금 높이를 단추에 적는다. 도면
                                            // 어디에도 안 보이는 값이라, 열어
                                            // 보지 않으면 2.5m 인 줄 모른다.
                                            OutlinedButton.icon(
                                              onPressed:
                                                  _showWallHeightSettings,
                                              icon: const Icon(
                                                Icons.height,
                                                size: 18,
                                              ),
                                              label: Text(
                                                '벽 높이 '
                                                '${_wallHeightMeters.toStringAsFixed(2)}m',
                                              ),
                                            ),
                                            // 도메인도 단추에 적는다. 어긋나면
                                            // 오류 없이 아무것도 안 통하므로,
                                            // 지금 값이 늘 보여야 한다.
                                            OutlinedButton.icon(
                                              onPressed: _showRosDomainSettings,
                                              icon: const Icon(
                                                Icons.lan_outlined,
                                                size: 18,
                                              ),
                                              label: Text(
                                                'ROS 도메인 $_rosDomainId',
                                              ),
                                            ),
                                          ],
                                        ),
                                      ),
                                      if (_mapScenarioSummary != null) ...[
                                        const SizedBox(height: 8),
                                        Container(
                                          width: double.infinity,
                                          padding: const EdgeInsets.symmetric(
                                            horizontal: 13,
                                            vertical: 10,
                                          ),
                                          decoration: BoxDecoration(
                                            color: const Color(0xFFF5F3FF),
                                            borderRadius: BorderRadius.circular(
                                              9,
                                            ),
                                            border: Border.all(
                                              color: const Color(0xFFDDD6FE),
                                            ),
                                          ),
                                          child: Text(
                                            '적용된 운영 시나리오 · $_mapScenarioSummary',
                                            style: const TextStyle(
                                              color: Color(0xFF5B21B6),
                                              fontWeight: FontWeight.w700,
                                            ),
                                          ),
                                        ),
                                      ],
                                      const SizedBox(height: 24),
                                      _StageBar(activeStage: _stage),
                                      const SizedBox(height: 24),
                                      LayoutBuilder(
                                        builder: (context, constraints) {
                                          if (constraints.maxWidth < 980) {
                                            return Column(
                                              children: [
                                                _MapWorkspace(
                                                  drawing: _drawing,
                                                  transformController:
                                                      _mapTransform,
                                                  onZoomIn: () =>
                                                      _zoomMap(1.25),
                                                  onZoomOut: () => _zoomMap(.8),
                                                  onFitScreen: _fitMapToScreen,
                                                  onRenumberVertices:
                                                      _renumberVertices,
                                                  wallMask: _wallMask,
                                                  wallColor: _wallColor,
                                                  floorMask: _floorMask,
                                                  floorColor: _floorColor,
                                                  mapVertices: _showVertexLabels
                                                      ? _visibleMapVertices()
                                                      : const [],
                                                  vertexLabelRevision:
                                                      _vertexLabelRevision,
                                                  optimizedWalls:
                                                      _visibleWallSegments(),
                                                  recommendedLanes:
                                                      _recommendedLanes,
                                                  laneDirections:
                                                      _laneDirections,
                                                  laneWaypoints: _laneWaypoints,
                                                  waypointNames: _waypointNames,
                                                  waypointTypes: _waypointTypes,
                                                  activeLaneEndpoint:
                                                      _activeLaneEndpoint,
                                                  waypointMode: _isWaypointMode,
                                                  onAddWaypoint:
                                                      _addLaneWaypoint,
                                                  onEditWaypoint: _editWaypoint,
                                                  onMoveWaypoint: _moveWaypoint,
                                                  waypointDropIssue:
                                                      _waypointDropIssue,
                                                  onSelectLane:
                                                      _selectLaneForDeletion,
                                                  isWallConnectMode:
                                                      _isWallConnectMode,
                                                  pendingWallVertex:
                                                      _pendingWallVertex,
                                                  onToggleWallConnect:
                                                      _toggleWallConnectMode,
                                                  onSelectWallVertex:
                                                      _selectWallConnectionVertex,
                                                  isWallEndpointEditMode:
                                                      _isWallEndpointEditMode,
                                                  onToggleWallEndpointEdit:
                                                      _toggleWallEndpointEditMode,
                                                  onMoveWallEndpoint:
                                                      _moveWallEndpoint,
                                                  measurement: _measurement,
                                                  showDrawingInfo:
                                                      _showDrawingInfo,
                                                  onCloseDrawingInfo: () =>
                                                      setState(
                                                        () => _showDrawingInfo =
                                                            false,
                                                      ),
                                                  isMeasurementSelected:
                                                      _isMeasurementSelected,
                                                  onSelectMeasurement:
                                                      _selectMeasurement,
                                                  onRemoveMeasurement:
                                                      _removeMeasurement,
                                                  isMeasurementMode:
                                                      _isMeasurementMode,
                                                  onMeasurementSelected:
                                                      _askMeasurement,
                                                  onCloseMeasurementMode: () =>
                                                      setState(
                                                        () =>
                                                            _isMeasurementMode =
                                                                false,
                                                      ),
                                                  isWallEraseMode:
                                                      _isWallEraseMode,
                                                  canUndoWallErase:
                                                      _previousWallMask != null,
                                                  onToggleWallErase: () =>
                                                      setState(
                                                        () => _isWallEraseMode =
                                                            !_isWallEraseMode,
                                                      ),
                                                  onEraseWalls: _eraseWalls,
                                                  onUndoWallErase:
                                                      _undoWallErase,
                                                  isPicking: _isPicking,
                                                  onPick: _pickDrawing,
                                                  onRemove: _removeDrawing,
                                                ),
                                                const SizedBox(height: 20),
                                                _SetupPanel(
                                                  drawing: _drawing,
                                                  stage: _stage,
                                                  measurement: _measurement,
                                                  isMeasurementMode:
                                                      _isMeasurementMode,
                                                  onToggleMeasurement:
                                                      _toggleMeasurementMode,
                                                  wallColor: _wallColor,
                                                  floorColor: _floorColor,
                                                  wallsDetected: _wallsDetected,
                                                  floorGenerated:
                                                      _floorGenerated,
                                                  isDetectingWalls:
                                                      _isDetectingWalls,
                                                  isGeneratingFloor:
                                                      _isGeneratingFloor,
                                                  onDetectWalls: _detectWalls,
                                                  onGenerateFloor:
                                                      _generateFloor,
                                                  lanesGenerated:
                                                      _laneWaypoints.isNotEmpty,
                                                  waypointMode: _isWaypointMode,
                                                  onToggleWaypoint:
                                                      _toggleWaypointMode,
                                                  onWallColorChanged: (color) =>
                                                      setState(
                                                        () =>
                                                            _wallColor = color,
                                                      ),
                                                  onFloorColorChanged:
                                                      (color) => setState(
                                                        () =>
                                                            _floorColor = color,
                                                      ),
                                                  isDeployed: _isDeployed,
                                                  onDeploy: _deployMap,
                                                  onGenerateGrid:
                                                      _generateGridMap,
                                                  onStageChanged: (value) =>
                                                      setState(
                                                        () => _stage = value,
                                                      ),
                                                ),
                                              ],
                                            );
                                          }
                                          return Row(
                                            crossAxisAlignment:
                                                CrossAxisAlignment.start,
                                            children: [
                                              Expanded(
                                                child: _MapWorkspace(
                                                  drawing: _drawing,
                                                  transformController:
                                                      _mapTransform,
                                                  onZoomIn: () =>
                                                      _zoomMap(1.25),
                                                  onZoomOut: () => _zoomMap(.8),
                                                  onFitScreen: _fitMapToScreen,
                                                  onRenumberVertices:
                                                      _renumberVertices,
                                                  wallMask: _wallMask,
                                                  wallColor: _wallColor,
                                                  floorMask: _floorMask,
                                                  floorColor: _floorColor,
                                                  mapVertices: _showVertexLabels
                                                      ? _visibleMapVertices()
                                                      : const [],
                                                  vertexLabelRevision:
                                                      _vertexLabelRevision,
                                                  optimizedWalls:
                                                      _visibleWallSegments(),
                                                  recommendedLanes:
                                                      _recommendedLanes,
                                                  laneDirections:
                                                      _laneDirections,
                                                  laneWaypoints: _laneWaypoints,
                                                  waypointNames: _waypointNames,
                                                  waypointTypes: _waypointTypes,
                                                  activeLaneEndpoint:
                                                      _activeLaneEndpoint,
                                                  waypointMode: _isWaypointMode,
                                                  onAddWaypoint:
                                                      _addLaneWaypoint,
                                                  onEditWaypoint: _editWaypoint,
                                                  onMoveWaypoint: _moveWaypoint,
                                                  waypointDropIssue:
                                                      _waypointDropIssue,
                                                  onSelectLane:
                                                      _selectLaneForDeletion,
                                                  isWallConnectMode:
                                                      _isWallConnectMode,
                                                  pendingWallVertex:
                                                      _pendingWallVertex,
                                                  onToggleWallConnect:
                                                      _toggleWallConnectMode,
                                                  onSelectWallVertex:
                                                      _selectWallConnectionVertex,
                                                  isWallEndpointEditMode:
                                                      _isWallEndpointEditMode,
                                                  onToggleWallEndpointEdit:
                                                      _toggleWallEndpointEditMode,
                                                  onMoveWallEndpoint:
                                                      _moveWallEndpoint,
                                                  measurement: _measurement,
                                                  showDrawingInfo:
                                                      _showDrawingInfo,
                                                  onCloseDrawingInfo: () =>
                                                      setState(
                                                        () => _showDrawingInfo =
                                                            false,
                                                      ),
                                                  isMeasurementSelected:
                                                      _isMeasurementSelected,
                                                  onSelectMeasurement:
                                                      _selectMeasurement,
                                                  onRemoveMeasurement:
                                                      _removeMeasurement,
                                                  isMeasurementMode:
                                                      _isMeasurementMode,
                                                  onMeasurementSelected:
                                                      _askMeasurement,
                                                  onCloseMeasurementMode: () =>
                                                      setState(
                                                        () =>
                                                            _isMeasurementMode =
                                                                false,
                                                      ),
                                                  isWallEraseMode:
                                                      _isWallEraseMode,
                                                  canUndoWallErase:
                                                      _previousWallMask != null,
                                                  onToggleWallErase: () =>
                                                      setState(
                                                        () => _isWallEraseMode =
                                                            !_isWallEraseMode,
                                                      ),
                                                  onEraseWalls: _eraseWalls,
                                                  onUndoWallErase:
                                                      _undoWallErase,
                                                  isPicking: _isPicking,
                                                  onPick: _pickDrawing,
                                                  onRemove: _removeDrawing,
                                                ),
                                              ),
                                              const SizedBox(width: 20),
                                              SizedBox(
                                                width: 330,
                                                child: _SetupPanel(
                                                  drawing: _drawing,
                                                  stage: _stage,
                                                  measurement: _measurement,
                                                  isMeasurementMode:
                                                      _isMeasurementMode,
                                                  onToggleMeasurement:
                                                      _toggleMeasurementMode,
                                                  wallColor: _wallColor,
                                                  floorColor: _floorColor,
                                                  wallsDetected: _wallsDetected,
                                                  floorGenerated:
                                                      _floorGenerated,
                                                  isDetectingWalls:
                                                      _isDetectingWalls,
                                                  isGeneratingFloor:
                                                      _isGeneratingFloor,
                                                  onDetectWalls: _detectWalls,
                                                  onGenerateFloor:
                                                      _generateFloor,
                                                  lanesGenerated:
                                                      _laneWaypoints.isNotEmpty,
                                                  waypointMode: _isWaypointMode,
                                                  onToggleWaypoint:
                                                      _toggleWaypointMode,
                                                  onWallColorChanged: (color) =>
                                                      setState(
                                                        () =>
                                                            _wallColor = color,
                                                      ),
                                                  onFloorColorChanged:
                                                      (color) => setState(
                                                        () =>
                                                            _floorColor = color,
                                                      ),
                                                  isDeployed: _isDeployed,
                                                  onDeploy: _deployMap,
                                                  onGenerateGrid:
                                                      _generateGridMap,
                                                  onStageChanged: (value) =>
                                                      setState(
                                                        () => _stage = value,
                                                      ),
                                                ),
                                              ),
                                            ],
                                          );
                                        },
                                      ),
                                      if (_processingWarning != null) ...[
                                        const SizedBox(height: 20),
                                        _ProcessingWarningPanel(
                                          message: _processingWarning!,
                                          onDismiss: _clearProcessingWarning,
                                        ),
                                      ],
                                    ],
                                  ),
                                ),
                              ),
                            )
                          : _selectedMenu == _menuGrid
                          ? _GridMapPage(
                              projectName: _openProjectName,
                              mapName: _mapName,
                              hasDrawing: _drawing != null,
                              calibrated: _metersPerPixel != null,
                              floorGenerated: _floorGenerated,
                              resolution: _occupancyResolution(),
                              mapDirectory: _mapDirectoryFor(
                                _openProjectName ?? _mapName,
                              ),
                              onGenerate: _generateGridMap,
                              onOpenMap: () =>
                                  setState(() => _selectedMenu = _menuMap),
                              generating: _isGeneratingGrid,
                              preview: _gridPreview,
                              previewGrid: _gridPreviewGrid,
                              previewDirectory: _gridPreviewDirectory,
                              previewSavedAt: _gridPreviewSavedAt,
                              slamMap: _slamMap,
                              slamPreview: _slamPreview,
                              readingSlam: _isReadingSlamMap,
                              useSlamMap: _useSlamMap,
                              onUploadSlam: _uploadSlamMap,
                              onSaveSlamOrigin: _saveSlamOrigin,
                              onUseSlamMapChanged: (value) =>
                                  setState(() => _useSlamMap = value),
                              slamScale: _slamScaleComparison(),
                              onApplySlamScale: (ratio) =>
                                  unawaited(_applySlamScale(ratio)),
                              resolutionMode: _gridResolutionMode,
                              targetWidth: _gridTargetWidth,
                              targetHeight: _gridTargetHeight,
                              padToTarget: _gridPadToTarget,
                              manualResolution: _gridManualResolution,
                              extent: _occupancyExtent(),
                              robotWidth: _robotWidthMeters,
                              drawingScale: _metersPerPixel,
                              onResolutionChanged:
                                  (mode, width, height, pad, manual) =>
                                      setState(() {
                                        _gridResolutionMode = mode;
                                        // 0 이나 음수가 들어오면 격자를 못
                                        // 만든다. 앞 값을 지킨다.
                                        if (width > 0) _gridTargetWidth = width;
                                        if (height > 0) {
                                          _gridTargetHeight = height;
                                        }
                                        _gridPadToTarget = pad;
                                        if (manual > 0) {
                                          _gridManualResolution = manual;
                                        }
                                      }),
                              unsavedChanges: _gridSettingChanges,
                              onSaveSettings: () =>
                                  unawaited(_saveGridSettings()),
                            )
                          : _selectedMenu == _menuRobots
                          ? _RobotManagementPage(
                              drawing: _robotRuntimeDrawing,
                              activeMapSourceName: _activeMapSourceName,
                              activeBuildingYamlName: _activeBuildingYamlName,
                              pendingDeployment:
                                  _robotDeployedMap?.summary.yamlPath.endsWith(
                                    '.rmfproject',
                                  ) ??
                                  !_isDeployed,
                              lanes:
                                  _robotDeployedMap?.lanes ?? _recommendedLanes,
                              waypoints:
                                  _robotDeployedMap?.waypoints ??
                                  _laneWaypoints,
                              waypointNames:
                                  _robotDeployedMap?.waypointNames ??
                                  _waypointNames,
                              robots: _mockRobots,
                              projectName: _openProjectName,
                              // 차례의 `RMF 설정 내보내기` 칸이 이 둘로 배포
                              // 산출물을 읽는다. 맵 이름은 산출물 파일 이름과
                              // 같은 것이라야 한다 — 열린 프로젝트 이름과 다를
                              // 수 있다.
                              mapDirectory: _deployedMapDirectory,
                              deployMapName:
                                  _robotDeployedMap?.summary.name ?? _mapName,
                              fleetName: _fleetSettings.fleetName,
                              registeredRobots: _fleetRobots,
                              onLoadMap: _loadMapForRobots,
                              onSpawn: _spawnMockRobot,
                              onToggle: _toggleMockRobot,
                              onRemove: _removeMockRobot,
                              onRegisterRobot: () =>
                                  unawaited(_registerFleetRobot()),
                              onOpenRobot: (id) =>
                                  unawaited(_showRobotDetail(id)),
                              onEditRegisteredRobot: (robot) =>
                                  unawaited(_updateFleetRobot(robot)),
                              onUnregisterRobot: (robot) =>
                                  unawaited(_unregisterFleetRobot(robot)),
                              onSendRobot: (robot) =>
                                  unawaited(_sendRobotToWaypoint(robot)),
                              onRegisterFromChargers: () =>
                                  unawaited(_registerRobotsFromChargers()),
                              onCheckSpawns: () => unawaited(_showSpawnCheck()),
                              spawnChecks: _spawnChecks,
                              onStartBackend: _startBackendForOpenProject,
                              onRefreshScripts: _refreshProjectScripts,
                              telemetry: _telemetry,
                            )
                          : _selectedMenu == _menuTasks
                          ? _TaskManagementPage(
                              tasks: _mockTasks,
                              robots: _mockRobots,
                              drawing: _robotRuntimeDrawing,
                              lanes:
                                  _robotDeployedMap?.lanes ?? _recommendedLanes,
                              waypoints:
                                  _robotDeployedMap?.waypoints ??
                                  _laneWaypoints,
                              waypointNames:
                                  _robotDeployedMap?.waypointNames ??
                                  _waypointNames,
                              activeMapName:
                                  _robotDeployedMap?.summary.name ?? _mapName,
                              activeMapSourceName: _activeMapSourceName,
                              activeBuildingYamlName: _activeBuildingYamlName,
                              pendingDeployment:
                                  _robotDeployedMap?.summary.yamlPath.endsWith(
                                    '.rmfproject',
                                  ) ??
                                  !_isDeployed,
                              mapReady:
                                  (_robotDeployedMap?.waypoints ??
                                          _laneWaypoints)
                                      .isNotEmpty,
                              onLoadMap: _loadMapForRobots,
                              onOpenRobots: () =>
                                  setState(() => _selectedMenu = _menuRobots),
                              onCreate: _createMockTask,
                              onReturnRobots: _returnRobotsToSpawn,
                              onShowDetail: _showTaskDetail,
                              onRun: _runMockTask,
                              onEdit: _editMockTask,
                              onDelete: _deleteMockTask,
                              onCancel: _cancelMockTask,
                              readiness: _readiness,
                              onRefreshReadiness: _refreshReadiness,
                            )
                          : _selectedMenu == _menuRobotModels
                          ? const _RobotModelManagementPage()
                          : _selectedMenu == _menuFiles
                          ? _ProjectFilesPage(
                              projectName: _openProjectName,
                              mapName: _mapName,
                              fleetName: _fleetSettings.fleetName,
                              robotCount: _fleetRobots.length,
                              mapDirectory: _mapDirectoryFor(
                                _openProjectName ?? _mapName,
                              ),
                              onOpenMap: () =>
                                  setState(() => _selectedMenu = _menuMap),
                              onExport: _exportRmfConfig,
                              onRun: _runProjectScript,
                              onStop: _stopProjectScript,
                            )
                          : _selectedMenu == _menuPolicies
                          ? WorkcellPolicyPage(
                              projectName: _openProjectName,
                              robots: _fleetRobots,
                              onChanged: (policies) {
                                if (!listEquals(
                                  _workcellPolicyModels,
                                  policies,
                                )) {
                                  setState(
                                    () => _workcellPolicyModels = policies,
                                  );
                                }
                              },
                            )
                          : _selectedMenu == _menuRos2
                          ? const Ros2InspectPage()
                          : _selectedMenu == _menuLog
                          ? _ProjectLogPage(
                              mapDirectory: _deployedMapDirectory,
                              mapName:
                                  _robotDeployedMap?.summary.name ?? _mapName,
                            )
                          : _selectedMenu == _menuAnalytics
                          ? const _OperationsAnalyticsPage()
                          : _selectedMenu == _menuProjectAnalytics
                          ? const _ProjectAnalyticsPage()
                          // 여기까지 왔으면 아직 안 만든 화면이다. 예전에는
                          // 항목 수가 메뉴보다 적고 순서도 달라, 메뉴를 하나
                          // 늘리면 범위 넘침으로 터졌다. 메뉴 이름을 그대로
                          // 쓴다.
                          : const _ComingSoonPage(title: '준비 중'),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// 프로젝트 이름을 받는 팝업.
///
/// 컨트롤러를 이 위젯이 들고 있어야 한다. 부르는 쪽에서 만들고 `await` 뒤에
/// dispose 하면, 팝업이 닫히는 애니메이션이 남아 있는 동안 이미 버린 컨트롤러로
/// 다시 그리게 되어 `A TextEditingController was used after being disposed` 로
/// 터진다. `showMovableDialog` 는 라우트가 pop 되는 순간 돌아오고, 사라지는
/// 그림은 그 뒤에 몇 프레임 더 그려진다.
class _ProjectNameDialog extends StatefulWidget {
  const _ProjectNameDialog({
    required this.title,
    required this.initialName,
    required this.confirmLabel,
    this.helperText,
  });

  final String title;
  final String initialName;
  final String confirmLabel;
  final String? helperText;

  @override
  State<_ProjectNameDialog> createState() => _ProjectNameDialogState();
}

class _ProjectNameDialogState extends State<_ProjectNameDialog> {
  late final TextEditingController _controller = TextEditingController(
    text: widget.initialName,
  );

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  void _submit() {
    final trimmed = _controller.text.trim();
    if (trimmed.isNotEmpty) Navigator.pop(context, trimmed);
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
    icon: const Icon(Icons.drive_file_rename_outline, size: 36),
    title: Text(widget.title),
    content: SizedBox(
      width: 390,
      child: TextField(
        controller: _controller,
        autofocus: true,
        decoration: InputDecoration(
          // 도면 이름이 아니라 프로젝트 이름이다. 같은 도면으로도 이름이
          // 다르면 별개의 프로젝트가 된다.
          labelText: '프로젝트 이름',
          helperText: widget.helperText ?? '이 이름이 프로젝트 구분자가 됩니다.',
          helperMaxLines: 3,
          border: const OutlineInputBorder(),
        ),
        onSubmitted: (_) => _submit(),
      ),
    ),
    actions: [
      TextButton(
        onPressed: () => Navigator.pop(context),
        child: const Text('취소'),
      ),
      FilledButton(onPressed: _submit, child: Text(widget.confirmLabel)),
    ],
  );
}

class _SequentialTaskEditorDialog extends StatefulWidget {
  const _SequentialTaskEditorDialog({
    required this.initialName,
    this.initialDescription = '',
    this.initialRobotId = '__auto__',
    this.initialSteps,
    this.initialTrigger = _OrderTrigger.manual,
    this.editing = false,
    required this.robots,
    required this.workcellPolicies,
    required this.drawing,
    required this.lanes,
    required this.waypoints,
    required this.waypointNames,
  });

  final String initialName;
  final String initialDescription;
  final String initialRobotId;
  final List<_TaskStepDraft>? initialSteps;
  final _OrderTrigger initialTrigger;
  final bool editing;
  final List<_MockRobot> robots;
  final List<String> workcellPolicies;
  final UploadedDrawing? drawing;
  final List<(Offset, Offset)> lanes;
  final List<Offset> waypoints;
  final Map<Offset, String> waypointNames;

  @override
  State<_SequentialTaskEditorDialog> createState() =>
      _SequentialTaskEditorDialogState();
}

class _SequentialTaskEditorDialogState
    extends State<_SequentialTaskEditorDialog> {
  late final TextEditingController _name;
  final _description = TextEditingController();
  String _robotId = '__auto__';
  late _OrderTrigger _trigger;
  late final List<_TaskStepDraft> _steps;
  int _selectedStepIndex = 0;

  Offset? _normalizedDestination(Offset? destination) {
    if (destination == null || widget.waypoints.isEmpty) return null;
    return widget.waypoints.reduce(
      (a, b) =>
          (a - destination).distance <= (b - destination).distance ? a : b,
    );
  }

  @override
  void initState() {
    super.initState();
    _name = TextEditingController(text: widget.initialName);
    _description.text = widget.initialDescription;
    _robotId = widget.initialRobotId;
    _trigger = widget.initialTrigger;
    final defaultArmAction = widget.workcellPolicies.firstOrNull ?? 'armLoad';
    _steps = widget.initialSteps?.isNotEmpty == true
        ? widget.initialSteps!
              .map(
                (step) => _TaskStepDraft(
                  step.type,
                  destination: _normalizedDestination(step.destination),
                  durationSeconds: step.durationSeconds,
                  policyId: step.policyId,
                ),
              )
              .toList()
        : [
            _TaskStepDraft(
              _TaskStepType.navigate,
              destination: widget.waypoints.first,
            ),
            _TaskStepDraft(_TaskStepType.armLoad, policyId: defaultArmAction),
            _TaskStepDraft(
              _TaskStepType.navigate,
              destination: widget.waypoints.first,
            ),
          ];
  }

  @override
  void dispose() {
    _name.dispose();
    _description.dispose();
    super.dispose();
  }

  String _waypointLabel(Offset point) {
    final name = widget.waypointNames[point]?.trim() ?? '';
    return name.isEmpty
        ? 'Waypoint ${widget.waypoints.indexOf(point) + 1}'
        : name;
  }

  bool get _valid =>
      _name.text.trim().isNotEmpty &&
      _steps.isNotEmpty &&
      _steps.every(
        (step) =>
            step.type != _TaskStepType.navigate || step.destination != null,
      );

  void _submit({required bool startImmediately}) {
    Navigator.pop(
      context,
      _TaskEditorResult(
        name: _name.text.trim(),
        description: _description.text.trim(),
        robotId: _robotId,
        steps: _steps,
        startImmediately: startImmediately,
        trigger: _trigger,
      ),
    );
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
    icon: const Icon(Icons.account_tree_outlined, size: 36),
    title: const Text('연속 작업 편집기'),
    content: SizedBox(
      width: 1100,
      height: 650,
      child: Row(
        children: [
          Expanded(
            flex: 3,
            child: Column(
              children: [
                Row(
                  children: [
                    Expanded(
                      child: TextField(
                        controller: _name,
                        decoration: const InputDecoration(
                          labelText: '작업 이름 *',
                          border: OutlineInputBorder(),
                        ),
                        onChanged: (_) => setState(() {}),
                      ),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: DropdownButtonFormField<String>(
                        initialValue: _robotId,
                        decoration: const InputDecoration(
                          labelText: 'Pinky 배정',
                          border: OutlineInputBorder(),
                        ),
                        items: [
                          const DropdownMenuItem(
                            value: '__auto__',
                            child: Text('자동 배정'),
                          ),
                          if (_robotId != '__auto__' &&
                              !widget.robots.any(
                                (robot) => robot.id == _robotId,
                              ))
                            DropdownMenuItem(
                              value: _robotId,
                              child: Text('$_robotId (미접속)'),
                            ),
                          for (final robot in widget.robots)
                            DropdownMenuItem(
                              value: robot.id,
                              child: Text(robot.id),
                            ),
                        ],
                        onChanged: (value) => setState(() => _robotId = value!),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _description,
                  maxLines: 2,
                  decoration: const InputDecoration(
                    labelText: '상세 지시',
                    border: OutlineInputBorder(),
                  ),
                ),
                const SizedBox(height: 12),
                DropdownButtonFormField<_OrderTrigger>(
                  initialValue: _trigger,
                  decoration: const InputDecoration(
                    labelText: '주문 자동 분류 규칙',
                    helperText: '일치하는 MySQL 주문이 들어오면 이 작업을 자동 생성합니다.',
                    border: OutlineInputBorder(),
                  ),
                  items: [
                    for (final trigger in _OrderTrigger.values)
                      DropdownMenuItem(
                        value: trigger,
                        child: Text(trigger.label),
                      ),
                  ],
                  onChanged: (value) => setState(() => _trigger = value!),
                ),
                const SizedBox(height: 12),
                Row(
                  children: [
                    const Expanded(
                      child: Text(
                        '실행 단계',
                        style: TextStyle(fontWeight: FontWeight.w800),
                      ),
                    ),
                    OutlinedButton.icon(
                      onPressed: () => setState(() {
                        _steps.add(
                          _TaskStepDraft(
                            _TaskStepType.navigate,
                            destination: widget.waypoints.first,
                          ),
                        );
                        _selectedStepIndex = _steps.length - 1;
                      }),
                      icon: const Icon(Icons.add, size: 18),
                      label: const Text('단계 추가'),
                    ),
                  ],
                ),
                const SizedBox(height: 8),
                Expanded(
                  child: ReorderableListView.builder(
                    itemCount: _steps.length,
                    onReorderItem: (oldIndex, newIndex) => setState(() {
                      final selectedStep = _steps[_selectedStepIndex];
                      _steps.insert(newIndex, _steps.removeAt(oldIndex));
                      _selectedStepIndex = _steps.indexOf(selectedStep);
                    }),
                    itemBuilder: (context, index) {
                      final step = _steps[index];
                      return Card(
                        key: ObjectKey(step),
                        color:
                            index == _selectedStepIndex &&
                                step.type == _TaskStepType.navigate
                            ? const Color(0xFFEFF6FF)
                            : null,
                        child: Padding(
                          padding: const EdgeInsets.all(10),
                          child: Row(
                            children: [
                              CircleAvatar(
                                radius: 15,
                                child: Text('${index + 1}'),
                              ),
                              const SizedBox(width: 10),
                              SizedBox(
                                width: 165,
                                child: DropdownButtonFormField<_TaskStepType>(
                                  initialValue: step.type,
                                  decoration: const InputDecoration(
                                    labelText: '동작',
                                    isDense: true,
                                    border: OutlineInputBorder(),
                                  ),
                                  items: const [
                                    DropdownMenuItem(
                                      value: _TaskStepType.navigate,
                                      child: Text('Pinky 이동'),
                                    ),
                                    DropdownMenuItem(
                                      value: _TaskStepType.returnHome,
                                      child: Text('홈 복귀(자동)'),
                                    ),
                                    DropdownMenuItem(
                                      value: _TaskStepType.armLoad,
                                      child: Text('OMX-AI 픽업'),
                                    ),
                                    DropdownMenuItem(
                                      value: _TaskStepType.wait,
                                      child: Text('대기'),
                                    ),
                                  ],
                                  onChanged: (value) => setState(() {
                                    _selectedStepIndex = index;
                                    step.type = value!;
                                    if (value == _TaskStepType.navigate) {
                                      step.destination ??=
                                          widget.waypoints.first;
                                    } else if (value ==
                                        _TaskStepType.returnHome) {
                                      step.destination = null;
                                    } else if (value == _TaskStepType.armLoad) {
                                      step.policyId =
                                          widget.workcellPolicies.firstOrNull ??
                                          'armLoad';
                                    }
                                  }),
                                ),
                              ),
                              const SizedBox(width: 10),
                              Expanded(
                                child: step.type == _TaskStepType.navigate
                                    ? DropdownButtonFormField<Offset>(
                                        initialValue: step.destination,
                                        decoration: const InputDecoration(
                                          labelText: '목적지 Waypoint',
                                          isDense: true,
                                          border: OutlineInputBorder(),
                                        ),
                                        items: [
                                          for (final point in widget.waypoints)
                                            DropdownMenuItem(
                                              value: point,
                                              child: Text(
                                                _waypointLabel(point),
                                              ),
                                            ),
                                        ],
                                        onChanged: (value) => setState(() {
                                          _selectedStepIndex = index;
                                          step.destination = value;
                                        }),
                                      )
                                    : step.type == _TaskStepType.wait
                                    ? DropdownButtonFormField<double>(
                                        initialValue: step.durationSeconds,
                                        decoration: const InputDecoration(
                                          labelText: '대기 시간',
                                          isDense: true,
                                          border: OutlineInputBorder(),
                                        ),
                                        items: const [3, 5, 10, 30, 60]
                                            .map(
                                              (seconds) => DropdownMenuItem(
                                                value: seconds.toDouble(),
                                                child: Text('$seconds초'),
                                              ),
                                            )
                                            .toList(),
                                        onChanged: (value) => setState(
                                          () => step.durationSeconds = value!,
                                        ),
                                      )
                                    : step.type == _TaskStepType.returnHome
                                    ? const Text(
                                        '비어 있고 도달 가능한 가장 가까운 홈을 자동 예약',
                                        style: TextStyle(
                                          color: Color(0xFF0F766E),
                                          fontWeight: FontWeight.w700,
                                        ),
                                      )
                                    : DropdownButtonFormField<String>(
                                        initialValue: step.policyId,
                                        decoration: InputDecoration(
                                          labelText:
                                              widget.workcellPolicies.isEmpty
                                              ? '픽업 동작'
                                              : '픽업 Policy',
                                          helperText:
                                              widget.workcellPolicies.isEmpty
                                              ? 'Policy가 없어 기본 armLoad를 사용합니다.'
                                              : 'Gazebo 설비에 자동 생성된 Policy 중 선택',
                                          isDense: true,
                                          border: const OutlineInputBorder(),
                                        ),
                                        items: [
                                          if (widget.workcellPolicies.isEmpty)
                                            const DropdownMenuItem(
                                              value: 'armLoad',
                                              child: Text('기본 armLoad'),
                                            ),
                                          for (final policy
                                              in widget.workcellPolicies)
                                            DropdownMenuItem(
                                              value: policy,
                                              child: Text(policy),
                                            ),
                                          if (step.policyId != 'armLoad' &&
                                              !widget.workcellPolicies.contains(
                                                step.policyId,
                                              ))
                                            DropdownMenuItem(
                                              value: step.policyId,
                                              child: Text(
                                                '${step.policyId} · 기존 설정',
                                              ),
                                            ),
                                        ],
                                        onChanged: (value) => setState(
                                          () => step.policyId = value!,
                                        ),
                                      ),
                              ),
                              if (step.type == _TaskStepType.navigate)
                                IconButton(
                                  tooltip: '지도에서 이 단계 목적지 지정',
                                  onPressed: () => setState(
                                    () => _selectedStepIndex = index,
                                  ),
                                  icon: Icon(
                                    Icons.add_location_alt_outlined,
                                    color: index == _selectedStepIndex
                                        ? const Color(0xFF2563EB)
                                        : null,
                                  ),
                                ),
                              IconButton(
                                tooltip: '단계 삭제',
                                onPressed: () => setState(() {
                                  _steps.remove(step);
                                  if (_steps.isEmpty) {
                                    _selectedStepIndex = 0;
                                  } else {
                                    _selectedStepIndex = _selectedStepIndex
                                        .clamp(0, _steps.length - 1);
                                  }
                                }),
                                icon: const Icon(Icons.delete_outline),
                              ),
                              const Icon(Icons.drag_handle),
                            ],
                          ),
                        ),
                      );
                    },
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(width: 18),
          Expanded(
            flex: 2,
            child: _TaskWaypointSelector(
              drawing: widget.drawing,
              lanes: widget.lanes,
              waypoints: widget.waypoints,
              waypointNames: widget.waypointNames,
              steps: _steps,
              selectedStepIndex: _selectedStepIndex,
              onWaypointSelected: (point) => setState(() {
                var targetIndex = _selectedStepIndex;
                if (targetIndex >= _steps.length ||
                    _steps[targetIndex].type != _TaskStepType.navigate) {
                  targetIndex = _steps.indexWhere(
                    (step) => step.type == _TaskStepType.navigate,
                  );
                }
                if (targetIndex < 0) return;
                _selectedStepIndex = targetIndex;
                _steps[targetIndex].destination = point;
              }),
            ),
          ),
        ],
      ),
    ),
    actions: [
      TextButton(
        onPressed: () => Navigator.pop(context),
        child: const Text('취소'),
      ),
      OutlinedButton.icon(
        onPressed: !_valid ? null : () => _submit(startImmediately: false),
        icon: const Icon(Icons.save_outlined, size: 18),
        label: const Text('저장'),
      ),
      FilledButton.icon(
        onPressed: !_valid ? null : () => _submit(startImmediately: true),
        icon: const Icon(Icons.play_arrow, size: 18),
        label: Text(widget.editing ? '저장 후 재시작' : '저장 후 시작'),
      ),
    ],
  );
}

class _TaskWaypointSelector extends StatelessWidget {
  const _TaskWaypointSelector({
    required this.drawing,
    required this.lanes,
    required this.waypoints,
    required this.waypointNames,
    required this.steps,
    required this.selectedStepIndex,
    required this.onWaypointSelected,
  });

  final UploadedDrawing? drawing;
  final List<(Offset, Offset)> lanes;
  final List<Offset> waypoints;
  final Map<Offset, String> waypointNames;
  final List<_TaskStepDraft> steps;
  final int selectedStepIndex;
  final ValueChanged<Offset> onWaypointSelected;

  Size get _sourceSize {
    final width = drawing?.pixelWidth;
    final height = drawing?.pixelHeight;
    if (width != null && height != null && width > 0 && height > 0) {
      return Size(width.toDouble(), height.toDouble());
    }
    final maxX = waypoints.fold<double>(1, (value, p) => math.max(value, p.dx));
    final maxY = waypoints.fold<double>(1, (value, p) => math.max(value, p.dy));
    return Size(maxX + 24, maxY + 24);
  }

  Offset _toCanvas(Offset point, Size canvasSize) {
    final fitted = applyBoxFit(
      BoxFit.contain,
      _sourceSize,
      canvasSize,
    ).destination;
    final target = Alignment.center.inscribe(fitted, Offset.zero & canvasSize);
    return Offset(
      target.left + point.dx * target.width / _sourceSize.width,
      target.top + point.dy * target.height / _sourceSize.height,
    );
  }

  void _selectNearest(TapDownDetails details, Size canvasSize) {
    Offset? nearest;
    var distance = 24.0;
    for (final waypoint in waypoints) {
      final candidateDistance =
          (_toCanvas(waypoint, canvasSize) - details.localPosition).distance;
      if (candidateDistance <= distance) {
        nearest = waypoint;
        distance = candidateDistance;
      }
    }
    if (nearest != null) onWaypointSelected(nearest);
  }

  @override
  Widget build(BuildContext context) {
    final activeStep =
        selectedStepIndex >= 0 && selectedStepIndex < steps.length
        ? steps[selectedStepIndex]
        : null;
    final canSelect = activeStep?.type == _TaskStepType.navigate;
    return Container(
      clipBehavior: Clip.antiAlias,
      decoration: BoxDecoration(
        color: const Color(0xFFF8FAFC),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: const Color(0xFFCBD5E1)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(14, 12, 14, 10),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    const Icon(
                      Icons.map_outlined,
                      size: 19,
                      color: Color(0xFF2563EB),
                    ),
                    const SizedBox(width: 7),
                    const Expanded(
                      child: Text(
                        '지도에서 Waypoint 지정',
                        style: TextStyle(fontWeight: FontWeight.w800),
                      ),
                    ),
                    if (canSelect)
                      Chip(
                        visualDensity: VisualDensity.compact,
                        label: Text('${selectedStepIndex + 1}단계'),
                      ),
                  ],
                ),
                const SizedBox(height: 4),
                Text(
                  canSelect
                      ? '목적지 Waypoint를 지도에서 직접 누르세요.'
                      : '왼쪽에서 이동 단계의 지도 핀 버튼을 선택하세요.',
                  style: const TextStyle(fontSize: 12),
                ),
              ],
            ),
          ),
          const Divider(height: 1),
          Expanded(
            child: LayoutBuilder(
              builder: (context, constraints) {
                final canvasSize = constraints.biggest;
                return GestureDetector(
                  behavior: HitTestBehavior.opaque,
                  onTapDown: canSelect
                      ? (details) => _selectNearest(details, canvasSize)
                      : null,
                  child: Stack(
                    fit: StackFit.expand,
                    children: [
                      if (drawing?.isImage == true && drawing!.bytes != null)
                        Image.memory(drawing!.bytes!, fit: BoxFit.contain),
                      CustomPaint(
                        painter: _TaskWaypointPainter(
                          sourceSize: _sourceSize,
                          lanes: lanes,
                          waypoints: waypoints,
                          waypointNames: waypointNames,
                          steps: steps,
                          selectedStepIndex: selectedStepIndex,
                        ),
                      ),
                    ],
                  ),
                );
              },
            ),
          ),
          const Padding(
            padding: EdgeInsets.all(10),
            child: Row(
              children: [
                Icon(Icons.touch_app_outlined, size: 17),
                SizedBox(width: 6),
                Expanded(child: Text('파란 원: 선택 단계 · 숫자: 이동 단계 순서')),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _TaskWaypointPainter extends CustomPainter {
  const _TaskWaypointPainter({
    required this.sourceSize,
    required this.lanes,
    required this.waypoints,
    required this.waypointNames,
    required this.steps,
    required this.selectedStepIndex,
  });

  final Size sourceSize;
  final List<(Offset, Offset)> lanes;
  final List<Offset> waypoints;
  final Map<Offset, String> waypointNames;
  final List<_TaskStepDraft> steps;
  final int selectedStepIndex;

  @override
  void paint(Canvas canvas, Size size) {
    final fitted = applyBoxFit(BoxFit.contain, sourceSize, size).destination;
    final target = Alignment.center.inscribe(fitted, Offset.zero & size);
    Offset convert(Offset point) => Offset(
      target.left + point.dx * target.width / sourceSize.width,
      target.top + point.dy * target.height / sourceSize.height,
    );
    final lanePaint = Paint()
      ..color = const Color(0xCC0891B2)
      ..strokeWidth = 3
      ..strokeCap = StrokeCap.round;
    for (final lane in lanes) {
      canvas.drawLine(convert(lane.$1), convert(lane.$2), lanePaint);
    }
    for (final waypoint in waypoints) {
      final center = convert(waypoint);
      canvas.drawCircle(center, 7, Paint()..color = Colors.white);
      canvas.drawCircle(center, 4, Paint()..color = const Color(0xFF0F766E));
      final name = waypointNames[waypoint]?.trim() ?? '';
      if (name.isNotEmpty) {
        final label = TextPainter(
          text: TextSpan(
            text: name,
            style: const TextStyle(
              color: Color(0xFF0F172A),
              fontSize: 10,
              fontWeight: FontWeight.w700,
              backgroundColor: Color(0xDDFFFFFF),
            ),
          ),
          textDirection: TextDirection.ltr,
          maxLines: 1,
          ellipsis: '…',
        )..layout(maxWidth: 100);
        label.paint(canvas, center + const Offset(7, -18));
      }
    }
    for (var index = 0; index < steps.length; index++) {
      final step = steps[index];
      if (step.type != _TaskStepType.navigate || step.destination == null) {
        continue;
      }
      final center = convert(step.destination!);
      final active = index == selectedStepIndex;
      canvas.drawCircle(
        center,
        active ? 14 : 11,
        Paint()
          ..color = active ? const Color(0xFF2563EB) : const Color(0xFF7C3AED),
      );
      final number = TextPainter(
        text: TextSpan(
          text: '${index + 1}',
          style: const TextStyle(
            color: Colors.white,
            fontSize: 11,
            fontWeight: FontWeight.w900,
          ),
        ),
        textDirection: TextDirection.ltr,
      )..layout();
      number.paint(
        canvas,
        center - Offset(number.width / 2, number.height / 2),
      );
    }
  }

  @override
  bool shouldRepaint(covariant _TaskWaypointPainter oldDelegate) => true;
}

/// 작업을 낼 수 있는 상태인지 늘 보여 주는 칸.
///
/// 로봇이 RViz 에 안 뜨면 무엇이 끊긴 것인지 알려면 로그를 뒤지고 토픽을 하나씩
/// 쳐 봐야 했다. 그 확인을 화면이 대신한다.
///
/// 스스로 새로 고친다. 사람이 눌러야만 갱신되면, 고친 뒤에도 빨간불이 남아
/// 아직 안 됐다고 여긴다.
class _ReadinessPanel extends StatefulWidget {
  const _ReadinessPanel({required this.report, required this.onRefresh});

  final ReadinessReport report;
  final Future<void> Function() onRefresh;

  @override
  State<_ReadinessPanel> createState() => _ReadinessPanelState();
}

class _ReadinessPanelState extends State<_ReadinessPanel> {
  Timer? _timer;
  bool _expanded = false;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    unawaited(_refresh());
    // 10초. 확인 한 번에 `ros2 topic echo` 를 한 번 띄우므로 더 잦으면 값이
    // 싸지 않다. 백엔드가 뜨고 로봇이 붙는 데도 그 정도는 걸린다.
    _timer = Timer.periodic(
      const Duration(seconds: 10),
      (_) => unawaited(_refresh()),
    );
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _refresh() async {
    // 앞의 확인이 아직 안 끝났으면 겹쳐 띄우지 않는다.
    if (_busy) return;
    _busy = true;
    try {
      await widget.onRefresh();
    } finally {
      _busy = false;
    }
  }

  static const Map<ReadinessState, (IconData, Color)> _marks = {
    ReadinessState.ready: (Icons.check_circle, Color(0xFF15803D)),
    ReadinessState.blocked: (Icons.cancel, Color(0xFFDC2626)),
    ReadinessState.unknown: (Icons.help_outline, Color(0xFF94A3B8)),
  };

  @override
  Widget build(BuildContext context) {
    final report = widget.report;
    final ready = report.isReady;
    final done = report.checks.where((check) => check.isReady).length;
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: ready ? const Color(0xFFF0FDF4) : const Color(0xFFFEF2F2),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(
          color: ready ? const Color(0xFFBBF7D0) : const Color(0xFFFECACA),
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(
                ready ? Icons.task_alt : Icons.error_outline,
                size: 20,
                color: ready
                    ? const Color(0xFF15803D)
                    : const Color(0xFFDC2626),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  // 다 됐으면 한 줄이면 된다. 아니면 어디를 손대야 하는지를
                  // 맨 앞에 둔다 — 여섯 줄을 다 읽으라고 하지 않는다.
                  ready ? '작업 준비 완료' : report.summary,
                  style: const TextStyle(
                    fontWeight: FontWeight.w600,
                    height: 1.4,
                  ),
                ),
              ),
              const SizedBox(width: 8),
              Text(
                '$done/${report.checks.length}',
                style: const TextStyle(fontSize: 12, color: Color(0xFF64748B)),
              ),
              IconButton(
                tooltip: '지금 다시 확인',
                visualDensity: VisualDensity.compact,
                onPressed: () => unawaited(_refresh()),
                icon: const Icon(Icons.refresh, size: 18),
              ),
              IconButton(
                tooltip: _expanded ? '접기' : '단계별로 보기',
                visualDensity: VisualDensity.compact,
                onPressed: () => setState(() => _expanded = !_expanded),
                icon: Icon(
                  _expanded ? Icons.expand_less : Icons.expand_more,
                  size: 20,
                ),
              ),
            ],
          ),
          // 다 됐을 때는 접어 둔다. 초록 줄 여섯 개는 읽을 것이 없다.
          if (_expanded || !ready) ...[
            const SizedBox(height: 10),
            for (final check in report.checks)
              Padding(
                padding: const EdgeInsets.only(bottom: 6),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Icon(
                      _marks[check.state]!.$1,
                      size: 16,
                      color: _marks[check.state]!.$2,
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      // RichText 가 아니라 Text.rich 다. 위젯 테스트의
                      // find.textContaining 이 RichText 안은 못 본다.
                      child: Text.rich(
                        TextSpan(
                          style: const TextStyle(
                            fontSize: 12.5,
                            height: 1.45,
                            color: Color(0xFF0F172A),
                          ),
                          children: [
                            TextSpan(
                              text: '${check.title} — ',
                              style: const TextStyle(
                                fontWeight: FontWeight.w600,
                              ),
                            ),
                            TextSpan(
                              text: check.detail,
                              style: const TextStyle(color: Color(0xFF475569)),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ],
                ),
              ),
          ],
        ],
      ),
    );
  }
}

class _TaskManagementPage extends StatelessWidget {
  const _TaskManagementPage({
    required this.tasks,
    required this.robots,
    required this.drawing,
    required this.lanes,
    required this.waypoints,
    required this.waypointNames,
    required this.activeMapName,
    required this.activeMapSourceName,
    required this.activeBuildingYamlName,
    required this.pendingDeployment,
    required this.mapReady,
    required this.onLoadMap,
    required this.onOpenRobots,
    required this.onCreate,
    required this.onReturnRobots,
    required this.onShowDetail,
    required this.onRun,
    required this.onEdit,
    required this.onDelete,
    required this.onCancel,
    required this.readiness,
    required this.onRefreshReadiness,
  });

  /// 작업을 낼 수 있는 상태인지 단계별로 확인한 것.
  final ReadinessReport readiness;

  /// 그 확인을 다시 한다. 이 화면이 떠 있는 동안 스스로 부른다.
  final Future<void> Function() onRefreshReadiness;

  final List<_MockTask> tasks;
  final List<_MockRobot> robots;
  final UploadedDrawing? drawing;
  final List<(Offset, Offset)> lanes;
  final List<Offset> waypoints;
  final Map<Offset, String> waypointNames;
  final String activeMapName;
  final String activeMapSourceName;
  final String activeBuildingYamlName;
  final bool pendingDeployment;
  final bool mapReady;
  final VoidCallback onLoadMap;
  final VoidCallback onOpenRobots;
  final VoidCallback onCreate;

  /// 이동 로봇을 Spawn 위치로 되돌린다.
  final VoidCallback onReturnRobots;

  /// 작업과 담당 로봇의 실시간 상태를 보여 준다.
  final ValueChanged<_MockTask> onShowDetail;
  final ValueChanged<_MockTask> onRun;
  final ValueChanged<_MockTask> onEdit;
  final ValueChanged<_MockTask> onDelete;
  final ValueChanged<_MockTask> onCancel;

  String _statusLabel(_MockTaskStatus status) => switch (status) {
    _MockTaskStatus.queued => '대기',
    _MockTaskStatus.active => '진행 중',
    _MockTaskStatus.completed => '완료',
    _MockTaskStatus.cancelled => '취소',
    _MockTaskStatus.failed => '실패',
  };

  Color _statusColor(_MockTaskStatus status) => switch (status) {
    _MockTaskStatus.queued => const Color(0xFFD97706),
    _MockTaskStatus.active => const Color(0xFF2563EB),
    _MockTaskStatus.completed => const Color(0xFF15803D),
    _MockTaskStatus.cancelled => const Color(0xFF64748B),
    _MockTaskStatus.failed => const Color(0xFFDC2626),
  };

  String _time(DateTime value) =>
      '${value.hour.toString().padLeft(2, '0')}:${value.minute.toString().padLeft(2, '0')}:${value.second.toString().padLeft(2, '0')}';

  @override
  Widget build(BuildContext context) {
    final active = tasks
        .where(
          (task) =>
              task.status == _MockTaskStatus.active ||
              task.status == _MockTaskStatus.queued,
        )
        .length;
    final completed = tasks
        .where((task) => task.status == _MockTaskStatus.completed)
        .length;
    return Padding(
      padding: const EdgeInsets.all(28),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '작업 관리',
                      style: Theme.of(context).textTheme.headlineMedium,
                    ),
                    const SizedBox(height: 6),
                    const Text('Pinky 이동과 OMX-AI 픽업을 순서대로 편집하고 실행 상태를 확인합니다.'),
                  ],
                ),
              ),
              const Chip(
                avatar: Icon(Icons.sync, size: 17),
                label: Text('MySQL 주문 자동화 · 5초'),
              ),
              const SizedBox(width: 10),
              OutlinedButton.icon(
                onPressed: () =>
                    _showUsageGuide(context, _UsageGuideTopic.task),
                icon: const Icon(Icons.help_outline),
                label: const Text('사용법'),
              ),
              const SizedBox(width: 10),
              OutlinedButton.icon(
                onPressed: onLoadMap,
                icon: const Icon(Icons.folder_open_outlined),
                label: const Text('배포 맵 불러오기'),
              ),
              const SizedBox(width: 10),
              OutlinedButton.icon(
                onPressed: robots.any((robot) => robot.kind.isMobile)
                    ? onReturnRobots
                    : null,
                icon: const Icon(Icons.replay),
                label: const Text('로봇 원위치'),
              ),
              const SizedBox(width: 10),
              FilledButton.icon(
                onPressed: onCreate,
                icon: const Icon(Icons.add_task),
                label: const Text('새 작업'),
              ),
            ],
          ),
          const SizedBox(height: 14),
          _ReadinessPanel(report: readiness, onRefresh: onRefreshReadiness),
          const SizedBox(height: 14),
          _MapFileStatus(
            sourceLabel: '불러온 맵',
            sourceName: activeMapSourceName,
            buildingYamlName: activeBuildingYamlName,
            pendingDeployment: pendingDeployment,
          ),
          const SizedBox(height: 12),
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(13),
            decoration: BoxDecoration(
              color: mapReady && robots.any((robot) => robot.kind.canCarry)
                  ? const Color(0xFFF0FDF4)
                  : const Color(0xFFFFFBEB),
              borderRadius: BorderRadius.circular(10),
              border: Border.all(
                color: mapReady && robots.any((robot) => robot.kind.canCarry)
                    ? const Color(0xFF86EFAC)
                    : const Color(0xFFFCD34D),
              ),
            ),
            child: Row(
              children: [
                Icon(
                  mapReady && robots.any((robot) => robot.kind.canCarry)
                      ? Icons.check_circle_outline
                      : Icons.info_outline,
                  color: mapReady && robots.any((robot) => robot.kind.canCarry)
                      ? const Color(0xFF15803D)
                      : const Color(0xFFD97706),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    !mapReady
                        ? '1단계: 배포 맵을 불러오세요.'
                        : !robots.any((robot) => robot.kind.canCarry)
                        ? '현재 맵: $activeMapName · 2단계: Pinky 또는 Mock 주행로봇을 Spawn하세요.'
                        : '작업 준비 완료 · 맵: $activeMapName · 로봇 ${robots.length}대',
                    style: const TextStyle(fontWeight: FontWeight.w700),
                  ),
                ),
                if (!mapReady)
                  TextButton(onPressed: onLoadMap, child: const Text('맵 불러오기'))
                else if (!robots.any((robot) => robot.kind.canCarry))
                  TextButton(
                    onPressed: onOpenRobots,
                    child: const Text('로봇 메뉴로 이동'),
                  ),
              ],
            ),
          ),
          const SizedBox(height: 20),
          Row(
            children: [
              _TaskSummaryCard(
                label: '전체 작업',
                value: tasks.length,
                color: const Color(0xFF334155),
              ),
              const SizedBox(width: 12),
              _TaskSummaryCard(
                label: '진행 중',
                value: active,
                color: const Color(0xFF2563EB),
              ),
              const SizedBox(width: 12),
              _TaskSummaryCard(
                label: '완료',
                value: completed,
                color: const Color(0xFF15803D),
              ),
              const SizedBox(width: 12),
              _TaskSummaryCard(
                label: '가용 로봇',
                value: robots
                    .where(
                      (robot) =>
                          robot.kind.canCarry && robot.activeTaskId == null,
                    )
                    .length,
                color: const Color(0xFF7C3AED),
              ),
            ],
          ),
          const SizedBox(height: 18),
          Expanded(
            child: Row(
              children: [
                Expanded(
                  flex: 2,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Row(
                        children: [
                          Icon(
                            Icons.map_outlined,
                            size: 19,
                            color: Color(0xFF2563EB),
                          ),
                          SizedBox(width: 7),
                          Text(
                            '현재 운영 맵',
                            style: TextStyle(fontWeight: FontWeight.w800),
                          ),
                        ],
                      ),
                      const SizedBox(height: 8),
                      Expanded(
                        child: _RobotMapCard(
                          drawing: drawing,
                          lanes: lanes,
                          waypoints: waypoints,
                          waypointNames: waypointNames,
                          robots: robots,
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(width: 18),
                Expanded(
                  flex: 3,
                  child: Container(
                    decoration: BoxDecoration(
                      color: Colors.white,
                      borderRadius: BorderRadius.circular(14),
                      border: Border.all(color: const Color(0xFFE2E8F0)),
                    ),
                    child: tasks.isEmpty
                        ? const Center(
                            child: Column(
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                Icon(
                                  Icons.assignment_outlined,
                                  size: 52,
                                  color: Color(0xFF94A3B8),
                                ),
                                SizedBox(height: 12),
                                Text('생성된 작업이 없습니다.'),
                              ],
                            ),
                          )
                        : ListView.separated(
                            itemCount: tasks.length,
                            separatorBuilder: (_, _) =>
                                const Divider(height: 1),
                            itemBuilder: (context, index) {
                              final task = tasks[index];
                              final color = _statusColor(task.status);
                              return ListTile(
                                contentPadding: const EdgeInsets.symmetric(
                                  horizontal: 20,
                                  vertical: 9,
                                ),
                                leading: Container(
                                  width: 44,
                                  height: 44,
                                  decoration: BoxDecoration(
                                    color: color.withValues(alpha: .12),
                                    borderRadius: BorderRadius.circular(10),
                                  ),
                                  child: Icon(
                                    Icons.route_outlined,
                                    color: color,
                                  ),
                                ),
                                title: Row(
                                  children: [
                                    Expanded(
                                      child: Text(
                                        task.name,
                                        maxLines: 1,
                                        overflow: TextOverflow.ellipsis,
                                        style: const TextStyle(
                                          fontWeight: FontWeight.w800,
                                        ),
                                      ),
                                    ),
                                    TextButton.icon(
                                      onPressed: () => onShowDetail(task),
                                      icon: const Icon(
                                        Icons.monitor_heart_outlined,
                                        size: 17,
                                      ),
                                      label: const Text('상세내용'),
                                      style: TextButton.styleFrom(
                                        visualDensity: VisualDensity.compact,
                                        padding: const EdgeInsets.symmetric(
                                          horizontal: 8,
                                        ),
                                      ),
                                    ),
                                    IconButton(
                                      onPressed:
                                          task.status == _MockTaskStatus.active
                                          ? null
                                          : () => onRun(task),
                                      tooltip:
                                          task.status == _MockTaskStatus.active
                                          ? '현재 실행 중'
                                          : '작업 실행',
                                      visualDensity: VisualDensity.compact,
                                      icon: const Icon(
                                        Icons.play_circle_outline,
                                        size: 19,
                                        color: Color(0xFF15803D),
                                      ),
                                    ),
                                    // 돌고 있는 작업에만 나온다. 멈출 수 없는
                                    // 작업 옆에 흐린 단추를 두면 무엇이 지금
                                    // 누를 수 있는 것인지 흐려진다.
                                    if (task.status == _MockTaskStatus.active)
                                      IconButton(
                                        onPressed: () => onCancel(task),
                                        tooltip: '작업 취소 · 로봇은 최초 위치로',
                                        visualDensity: VisualDensity.compact,
                                        icon: const Icon(
                                          Icons.cancel_outlined,
                                          size: 19,
                                          color: Color(0xFFB45309),
                                        ),
                                      ),
                                    IconButton(
                                      onPressed: () => onEdit(task),
                                      tooltip: '작업 수정',
                                      visualDensity: VisualDensity.compact,
                                      icon: const Icon(
                                        Icons.edit_outlined,
                                        size: 18,
                                        color: Color(0xFF2563EB),
                                      ),
                                    ),
                                    IconButton(
                                      onPressed: () => onDelete(task),
                                      tooltip: '작업 삭제',
                                      visualDensity: VisualDensity.compact,
                                      icon: const Icon(
                                        Icons.delete_outline,
                                        size: 18,
                                        color: Color(0xFFDC2626),
                                      ),
                                    ),
                                    const SizedBox(width: 8),
                                    Text(
                                      task.id,
                                      style: const TextStyle(
                                        color: Color(0xFF64748B),
                                        fontSize: 12,
                                      ),
                                    ),
                                    const SizedBox(width: 10),
                                    Container(
                                      padding: const EdgeInsets.symmetric(
                                        horizontal: 8,
                                        vertical: 3,
                                      ),
                                      decoration: BoxDecoration(
                                        color: color.withValues(alpha: .12),
                                        borderRadius: BorderRadius.circular(20),
                                      ),
                                      child: Text(
                                        _statusLabel(task.status),
                                        style: TextStyle(
                                          color: color,
                                          fontSize: 12,
                                          fontWeight: FontWeight.w700,
                                        ),
                                      ),
                                    ),
                                  ],
                                ),
                                subtitle: Padding(
                                  padding: const EdgeInsets.only(top: 5),
                                  child: Text(
                                    '${task.orderId != null
                                        ? '주문 ${task.orderId} · '
                                        : task.trigger != _OrderTrigger.manual
                                        ? '자동화 ${task.trigger.label} · '
                                        : ''}'
                                    '${task.type} · ${task.robotId} · '
                                    '${task.orderId == null ? '' : '긴급도 ${task.urgency.label} · '}'
                                    '${task.currentStepIndex}/${task.steps.length}단계 완료 · 생성 ${_time(task.createdAt)}'
                                    '\n${task.steps.map((step) => step.label).join(' → ')}'
                                    '${task.description.isEmpty ? '' : '\n${task.description}'}',
                                    maxLines: 3,
                                    overflow: TextOverflow.ellipsis,
                                  ),
                                ),
                                trailing: task.status == _MockTaskStatus.active
                                    ? OutlinedButton.icon(
                                        onPressed: () => onCancel(task),
                                        icon: const Icon(
                                          Icons.cancel_outlined,
                                          size: 17,
                                        ),
                                        label: const Text('취소'),
                                      )
                                    : task.completedAt == null
                                    ? null
                                    : Text(
                                        _time(task.completedAt!),
                                        style: const TextStyle(
                                          color: Color(0xFF64748B),
                                        ),
                                      ),
                              );
                            },
                          ),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _TaskSummaryCard extends StatelessWidget {
  const _TaskSummaryCard({
    required this.label,
    required this.value,
    required this.color,
  });
  final String label;
  final int value;
  final Color color;

  @override
  Widget build(BuildContext context) => Expanded(
    child: Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0xFFE2E8F0)),
      ),
      child: Row(
        children: [
          Container(
            width: 5,
            height: 34,
            decoration: BoxDecoration(
              color: color,
              borderRadius: BorderRadius.circular(4),
            ),
          ),
          const SizedBox(width: 12),
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                '$value',
                style: TextStyle(
                  fontSize: 22,
                  fontWeight: FontWeight.w800,
                  color: color,
                ),
              ),
              Text(
                label,
                style: const TextStyle(color: Color(0xFF64748B), fontSize: 12),
              ),
            ],
          ),
        ],
      ),
    ),
  );
}

class _MainDashboard extends StatelessWidget {
  const _MainDashboard({
    required this.drawing,
    required this.mapName,
    required this.openProjectName,
    required this.mapReady,
    required this.deployed,
    required this.lanes,
    required this.waypoints,
    required this.waypointNames,
    required this.robots,
    required this.tasks,
    required this.warning,
    required this.onOpenMap,
    required this.onOpenRobots,
    required this.onOpenTasks,
    required this.onLoadMap,
    required this.onSpawn,
    required this.onCreateTask,
  });

  final UploadedDrawing? drawing;
  final String mapName;

  /// 열려 있는 맵 프로젝트 이름. null 이면 프로젝트가 없다는 뜻이고, 그때는
  /// 작업 목록이 비어 있는 것이 정상이다.
  final String? openProjectName;
  final bool mapReady;
  final bool deployed;
  final List<(Offset, Offset)> lanes;
  final List<Offset> waypoints;
  final Map<Offset, String> waypointNames;
  final List<_MockRobot> robots;
  final List<_MockTask> tasks;
  final String? warning;
  final VoidCallback onOpenMap;
  final VoidCallback onOpenRobots;
  final VoidCallback onOpenTasks;
  final VoidCallback onLoadMap;
  final VoidCallback onSpawn;
  final VoidCallback onCreateTask;

  String _taskStatus(_MockTaskStatus status) => switch (status) {
    _MockTaskStatus.queued => '대기',
    _MockTaskStatus.active => '진행 중',
    _MockTaskStatus.completed => '완료',
    _MockTaskStatus.cancelled => '취소',
    _MockTaskStatus.failed => '실패',
  };

  String _clock(DateTime value) =>
      '${value.hour.toString().padLeft(2, '0')}:${value.minute.toString().padLeft(2, '0')}';

  @override
  Widget build(BuildContext context) {
    final moving = robots.where((robot) => robot.moving).length;
    final robotErrors = robots.where((robot) => robot.battery <= 10).length;
    final activeTasks = tasks
        .where(
          (task) =>
              task.status == _MockTaskStatus.active ||
              task.status == _MockTaskStatus.queued,
        )
        .length;
    final failedTasks = tasks
        .where((task) => task.status == _MockTaskStatus.failed)
        .length;
    final completedTasks = tasks
        .where((task) => task.status == _MockTaskStatus.completed)
        .length;
    final hasIssue = warning != null || failedTasks > 0 || robotErrors > 0;
    final arms = robots
        .where((robot) => robot.kind == _RobotKind.omxManipulator)
        .toList();

    return SingleChildScrollView(
      padding: const EdgeInsets.all(28),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '운영 대시보드',
                      style: Theme.of(context).textTheme.headlineMedium,
                    ),
                    const SizedBox(height: 6),
                    const Text('맵, 로봇과 작업 상태를 한 화면에서 확인합니다.'),
                  ],
                ),
              ),
              // 일하는 차례대로 둔다 — 맵을 불러오고 → 로봇을 올리고 →
              // 작업을 시킨다. 차례가 뒤집혀 있으면 처음 쓰는 사람이 스폰부터
              // 눌러 보고 아무 일도 안 일어나는 것을 겪는다.
              OutlinedButton.icon(
                onPressed: onLoadMap,
                icon: const Icon(Icons.folder_open_outlined),
                label: const Text('운영 맵 불러오기'),
              ),
              const SizedBox(width: 10),
              OutlinedButton.icon(
                onPressed: onSpawn,
                icon: const Icon(Icons.add_circle_outline),
                label: const Text('로봇 Spawn'),
              ),
              const SizedBox(width: 10),
              FilledButton.icon(
                onPressed: onCreateTask,
                icon: const Icon(Icons.add_task),
                label: const Text('새 작업'),
              ),
            ],
          ),
          const SizedBox(height: 18),
          // 프로젝트가 없으면 대시보드는 비어 있는 게 맞다. 다만 왜 비었는지는
          // 알려 준다 — 데이터가 사라진 것으로 오해할 수 있다.
          if (openProjectName == null) ...[
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                color: const Color(0xFFEFF6FF),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: const Color(0xFF93C5FD)),
              ),
              child: const Row(
                children: [
                  Icon(Icons.folder_off_outlined, color: Color(0xFF2563EB)),
                  SizedBox(width: 10),
                  Expanded(
                    child: Text(
                      '열린 맵 프로젝트가 없습니다. 작업과 주문 자동 분류는 맵 프로젝트에 속하므로 '
                      '지금은 아무 데이터도 표시하지 않습니다.\n'
                      '맵 관리에서 `프로젝트 열기`로 저장된 맵을 열거나, 작성 중인 맵을 '
                      '`프로젝트 저장`으로 등록하세요.',
                      style: TextStyle(fontWeight: FontWeight.w700),
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 12),
          ],
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: hasIssue
                  ? const Color(0xFFFFFBEB)
                  : const Color(0xFFF0FDF4),
              borderRadius: BorderRadius.circular(12),
              border: Border.all(
                color: hasIssue
                    ? const Color(0xFFFCD34D)
                    : const Color(0xFF86EFAC),
              ),
            ),
            child: Row(
              children: [
                Icon(
                  hasIssue ? Icons.warning_amber_rounded : Icons.check_circle,
                  color: hasIssue
                      ? const Color(0xFFD97706)
                      : const Color(0xFF15803D),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    hasIssue
                        ? '운영 주의 · Warning 또는 실패 작업을 확인하세요.'
                        : mapReady
                        ? '운영 준비 정상 · 현재 맵 $mapName'
                        : '운영 준비 필요 · 먼저 맵을 작성하거나 배포 맵을 불러오세요.',
                    style: const TextStyle(fontWeight: FontWeight.w800),
                  ),
                ),
                _DashboardStatusChip(
                  label: deployed ? '맵 배포됨' : '맵 미배포',
                  ok: deployed,
                ),
                const SizedBox(width: 8),
                _DashboardStatusChip(
                  label: mapReady ? 'Nav graph 준비' : 'Nav graph 없음',
                  ok: mapReady,
                ),
              ],
            ),
          ),
          const SizedBox(height: 16),
          LayoutBuilder(
            builder: (context, constraints) {
              final width = constraints.maxWidth;
              final columns = width >= 1100
                  ? 4
                  : width >= 620
                  ? 2
                  : 1;
              final cardWidth = (width - (columns - 1) * 12) / columns;
              return Wrap(
                spacing: 12,
                runSpacing: 12,
                children: [
                  SizedBox(
                    width: cardWidth,
                    child: _DashboardMetricCard(
                      icon: Icons.smart_toy_outlined,
                      label: '등록 로봇',
                      value: '${robots.length}대',
                      detail: '이동 $moving · 정지 ${robots.length - moving}',
                      color: const Color(0xFF2563EB),
                      onTap: onOpenRobots,
                    ),
                  ),
                  SizedBox(
                    width: cardWidth,
                    child: _DashboardMetricCard(
                      icon: Icons.pending_actions_outlined,
                      label: '진행 작업',
                      value: '$activeTasks건',
                      detail: '완료 $completedTasks건',
                      color: const Color(0xFF7C3AED),
                      onTap: onOpenTasks,
                    ),
                  ),
                  SizedBox(
                    width: cardWidth,
                    child: _DashboardMetricCard(
                      icon: Icons.error_outline,
                      label: '확인 필요',
                      value: '${failedTasks + robotErrors}건',
                      detail: '실패 작업 $failedTasks · 저전압 $robotErrors',
                      color: const Color(0xFFDC2626),
                      onTap: onOpenTasks,
                    ),
                  ),
                  SizedBox(
                    width: cardWidth,
                    child: _DashboardMetricCard(
                      icon: Icons.precision_manufacturing_outlined,
                      label: 'OMX 스테이션',
                      value: '${arms.length}대',
                      detail: arms.isEmpty ? '등록 필요' : '고정 장비 등록됨',
                      color: const Color(0xFF0891B2),
                      onTap: onOpenRobots,
                    ),
                  ),
                ],
              );
            },
          ),
          const SizedBox(height: 18),
          LayoutBuilder(
            builder: (context, constraints) {
              final compact = constraints.maxWidth < 1050;
              final map = _DashboardPanel(
                title: '실시간 운영 맵',
                icon: Icons.map_outlined,
                trailing: TextButton(
                  onPressed: onOpenRobots,
                  child: const Text('로봇 화면 열기'),
                ),
                child: SizedBox(
                  height: 430,
                  child: _RobotMapCard(
                    drawing: drawing,
                    lanes: lanes,
                    waypoints: waypoints,
                    waypointNames: waypointNames,
                    robots: robots,
                  ),
                ),
              );
              final side = Column(
                children: [
                  _DashboardPanel(
                    title: 'Warning',
                    icon: Icons.warning_amber_outlined,
                    child: warning == null && failedTasks == 0
                        ? const _DashboardEmpty(
                            icon: Icons.check_circle_outline,
                            text: '현재 확인할 Warning이 없습니다.',
                          )
                        : Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              if (warning != null)
                                SelectableText(
                                  warning!,
                                  style: const TextStyle(
                                    color: Color(0xFFB45309),
                                    height: 1.45,
                                  ),
                                ),
                              if (failedTasks > 0)
                                ListTile(
                                  contentPadding: EdgeInsets.zero,
                                  leading: const Icon(
                                    Icons.error_outline,
                                    color: Color(0xFFDC2626),
                                  ),
                                  title: Text('실패 작업 $failedTasks건'),
                                  trailing: TextButton(
                                    onPressed: onOpenTasks,
                                    child: const Text('확인'),
                                  ),
                                ),
                            ],
                          ),
                  ),
                  const SizedBox(height: 14),
                  _DashboardPanel(
                    title: 'OMX 스테이션',
                    icon: Icons.precision_manufacturing_outlined,
                    child: arms.isEmpty
                        ? const _DashboardEmpty(
                            icon: Icons.add_location_alt_outlined,
                            text: 'OMX Manipulator를 설치 Waypoint에 Spawn하세요.',
                          )
                        : Column(
                            children: [
                              for (final arm in arms)
                                ListTile(
                                  dense: true,
                                  contentPadding: EdgeInsets.zero,
                                  leading: CircleAvatar(
                                    backgroundColor: arm.color,
                                    child: const Icon(
                                      Icons.precision_manufacturing,
                                      color: Colors.white,
                                      size: 18,
                                    ),
                                  ),
                                  title: Text(arm.id),
                                  subtitle: const Text('고정 설치 · 대기'),
                                ),
                            ],
                          ),
                  ),
                ],
              );
              if (compact) {
                return Column(
                  children: [map, const SizedBox(height: 14), side],
                );
              }
              return Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(flex: 2, child: map),
                  const SizedBox(width: 16),
                  Expanded(child: side),
                ],
              );
            },
          ),
          const SizedBox(height: 18),
          _DashboardPanel(
            title: '최근 작업 활동',
            icon: Icons.history,
            trailing: TextButton(
              onPressed: onOpenTasks,
              child: const Text('전체 작업 보기'),
            ),
            child: tasks.isEmpty
                ? const _DashboardEmpty(
                    icon: Icons.inbox_outlined,
                    text: '아직 생성된 작업이 없습니다.',
                  )
                : Column(
                    children: [
                      for (final task in tasks.take(5))
                        ListTile(
                          contentPadding: EdgeInsets.zero,
                          leading: Icon(
                            task.status == _MockTaskStatus.failed
                                ? Icons.error_outline
                                : task.status == _MockTaskStatus.completed
                                ? Icons.check_circle_outline
                                : Icons.route_outlined,
                          ),
                          title: Text('${task.id} · ${task.name}'),
                          subtitle: Text(
                            '${task.robotId} · ${task.currentStepIndex}/${task.steps.length}단계',
                          ),
                          trailing: Text(
                            '${_taskStatus(task.status)} · ${_clock(task.createdAt)}',
                          ),
                        ),
                    ],
                  ),
          ),
          const SizedBox(height: 18),
          _DashboardPanel(
            title: '빠른 실행',
            icon: Icons.bolt_outlined,
            child: Wrap(
              spacing: 10,
              runSpacing: 10,
              children: [
                OutlinedButton.icon(
                  onPressed: onOpenMap,
                  icon: const Icon(Icons.map_outlined),
                  label: const Text('맵 관리'),
                ),
                OutlinedButton.icon(
                  onPressed: onOpenRobots,
                  icon: const Icon(Icons.smart_toy_outlined),
                  label: const Text('로봇 관리'),
                ),
                OutlinedButton.icon(
                  onPressed: onLoadMap,
                  icon: const Icon(Icons.folder_open_outlined),
                  label: const Text('배포 맵 불러오기'),
                ),
                OutlinedButton.icon(
                  onPressed: onOpenTasks,
                  icon: const Icon(Icons.assignment_outlined),
                  label: const Text('작업 관리'),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _DashboardStatusChip extends StatelessWidget {
  const _DashboardStatusChip({required this.label, required this.ok});
  final String label;
  final bool ok;

  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
    decoration: BoxDecoration(
      color: ok ? const Color(0xFFDCFCE7) : const Color(0xFFFFEDD5),
      borderRadius: BorderRadius.circular(20),
    ),
    child: Text(
      label,
      style: TextStyle(
        color: ok ? const Color(0xFF15803D) : const Color(0xFFC2410C),
        fontSize: 12,
        fontWeight: FontWeight.w800,
      ),
    ),
  );
}

class _DashboardMetricCard extends StatelessWidget {
  const _DashboardMetricCard({
    required this.icon,
    required this.label,
    required this.value,
    required this.detail,
    required this.color,
    required this.onTap,
  });
  final IconData icon;
  final String label;
  final String value;
  final String detail;
  final Color color;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => Material(
    color: Colors.white,
    borderRadius: BorderRadius.circular(12),
    child: InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(12),
      child: Container(
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          border: Border.all(color: const Color(0xFFE2E8F0)),
          borderRadius: BorderRadius.circular(12),
        ),
        child: Row(
          children: [
            Container(
              width: 44,
              height: 44,
              decoration: BoxDecoration(
                color: color.withValues(alpha: .12),
                borderRadius: BorderRadius.circular(10),
              ),
              child: Icon(icon, color: color),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(label, style: const TextStyle(color: Color(0xFF64748B))),
                  Text(
                    value,
                    style: const TextStyle(
                      fontSize: 22,
                      fontWeight: FontWeight.w900,
                    ),
                  ),
                  Text(detail, style: const TextStyle(fontSize: 12)),
                ],
              ),
            ),
            const Icon(Icons.chevron_right, color: Color(0xFF94A3B8)),
          ],
        ),
      ),
    ),
  );
}

class _DashboardPanel extends StatelessWidget {
  const _DashboardPanel({
    required this.title,
    required this.icon,
    required this.child,
    this.trailing,
  });
  final String title;
  final IconData icon;
  final Widget child;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) => Container(
    width: double.infinity,
    padding: const EdgeInsets.all(16),
    decoration: BoxDecoration(
      color: Colors.white,
      border: Border.all(color: const Color(0xFFE2E8F0)),
      borderRadius: BorderRadius.circular(14),
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Icon(icon, size: 20, color: const Color(0xFF334155)),
            const SizedBox(width: 8),
            Text(
              title,
              style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w800),
            ),
            const Spacer(),
            trailing ?? const SizedBox.shrink(),
          ],
        ),
        const SizedBox(height: 12),
        child,
      ],
    ),
  );
}

class _DashboardEmpty extends StatelessWidget {
  const _DashboardEmpty({required this.icon, required this.text});
  final IconData icon;
  final String text;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 22),
    child: Center(
      child: Column(
        children: [
          Icon(icon, color: const Color(0xFF94A3B8), size: 32),
          const SizedBox(height: 8),
          Text(text, style: const TextStyle(color: Color(0xFF64748B))),
        ],
      ),
    ),
  );
}

class _ComingSoonPage extends StatelessWidget {
  const _ComingSoonPage({required this.title});
  final String title;

  @override
  Widget build(BuildContext context) =>
      Center(child: Text('$title 화면은 준비 중입니다.'));
}

/// Nav2 그리드맵(점유격자)을 굽는 화면.
///
/// 맵 관리 패널 안에도 같은 단추가 있다. 그런데도 왼쪽 메뉴로 꺼내 둔 이유는,
/// 이 지도가 없을 때 사람이 보는 증상이 원인에서 네 단계나 떨어져 있기
/// 때문이다 — `map_server` 가 unconfigured 에서 멈추고, AMCL 은 "Waiting for
/// map" 만 되풀이하고, 위치를 모르니 fleet adapter 가 로봇을 등록하지 못하고,
/// 화면에는 "RMF 가 답하지 않습니다" 가 뜬다. 도면을 고친 뒤 지도만 다시 굽는
/// 일이 잦으므로 찾아 들어가지 않아도 되게 한다.
///
/// **못 만드는 경우에는 이유를 먼저 보여 준다.** 흐린 단추만 두면 왜 안 되는지
/// 알 수 없어, 사람이 배포를 처음부터 다시 돌리게 된다.
class _GridMapPage extends StatelessWidget {
  const _GridMapPage({
    required this.projectName,
    required this.mapName,
    required this.hasDrawing,
    required this.calibrated,
    required this.floorGenerated,
    required this.resolution,
    required this.mapDirectory,
    required this.onGenerate,
    required this.onOpenMap,
    required this.generating,
    required this.preview,
    required this.previewGrid,
    required this.previewDirectory,
    required this.previewSavedAt,
    required this.slamMap,
    required this.slamPreview,
    required this.readingSlam,
    required this.useSlamMap,
    required this.onUploadSlam,
    required this.onSaveSlamOrigin,
    required this.onUseSlamMapChanged,
    required this.slamScale,
    required this.onApplySlamScale,
    required this.resolutionMode,
    required this.targetWidth,
    required this.targetHeight,
    required this.padToTarget,
    required this.manualResolution,
    required this.extent,
    required this.robotWidth,
    required this.drawingScale,
    required this.onResolutionChanged,
    required this.unsavedChanges,
    required this.onSaveSettings,
  });

  /// 이 화면에서 고쳤지만 아직 프로젝트에 안 남긴 것들. 비어 있으면 저장 칸이
  /// 아예 안 나온다.
  final List<String> unsavedChanges;

  /// 그것들을 열린 프로젝트에 바로 저장한다.
  final VoidCallback onSaveSettings;

  final String? projectName;
  final String mapName;

  /// 도면이 올라와 있나.
  final bool hasDrawing;

  /// 축척(Measurement)이 잡혀 있나. 없으면 격자를 만들 수 없다.
  final bool calibrated;
  final bool floorGenerated;

  /// 격자 한 칸이 몇 미터인가.
  final double resolution;
  final String mapDirectory;
  final VoidCallback onGenerate;
  final VoidCallback onOpenMap;

  /// 지금 굽고 있는가. 커서와 단추가 이걸 보고 바뀐다.
  final bool generating;

  /// 다 구운 그림. 없으면 아직 안 구웠거나 실패했다.
  final ui.Image? preview;
  final OccupancyGrid? previewGrid;
  final String? previewDirectory;

  /// 이 그림이 프로젝트에 저장돼 있던 것이면 그 파일을 쓴 때. 방금 구웠으면 null.
  final DateTime? previewSavedAt;

  /// 이 프로젝트에 넣어 둔 SLAM 지도. 없으면 아직 안 올렸다.
  final SlamMap? slamMap;
  final ui.Image? slamPreview;
  final bool readingSlam;

  /// Nav2 가 SLAM 지도를 띄울지.
  final bool useSlamMap;
  final VoidCallback onUploadSlam;
  final void Function(double x, double y) onSaveSlamOrigin;
  final ValueChanged<bool> onUseSlamMapChanged;

  /// 도면 축척과 SLAM 을 견준 결과. 둘 중 하나가 없으면 null.
  final WallExtentComparison? slamScale;
  final void Function(double ratio) onApplySlamScale;

  /// 격자 한 칸을 무엇으로 정할지.
  final _GridResolutionMode resolutionMode;
  final int targetWidth;
  final int targetHeight;
  final bool padToTarget;
  final double manualResolution;

  /// 격자가 덮을 범위(m). 바닥이 없으면 null.
  final ({double width, double height})? extent;
  final double robotWidth;

  /// 도면 해상도(m/px). 참고로 보여 준다.
  final double? drawingScale;
  final void Function(
    _GridResolutionMode mode,
    int targetWidth,
    int targetHeight,
    bool padToTarget,
    double manualResolution,
  )
  onResolutionChanged;

  /// 지금 설정으로 나올 칸 수. 바닥이 없으면 null.
  ({int width, int height})? get gridCells {
    final size = extent;
    if (size == null || resolution <= 0) return null;
    var width = (size.width / resolution).ceil();
    var height = (size.height / resolution).ceil();
    if (resolutionMode == _GridResolutionMode.target && padToTarget) {
      width = math.max(width, targetWidth);
      height = math.max(height, targetHeight);
    }
    return (width: width, height: height);
  }

  /// 아직 안 된 것들. 비어 있으면 구울 수 있다.
  List<String> get _missing => [
    if (projectName == null) '맵 프로젝트를 열거나 저장하세요',
    if (!hasDrawing) '도면을 올리세요',
    if (!calibrated) 'Measurement 로 축척을 잡으세요',
    if (!floorGenerated) 'Floor 자동 생성을 하세요',
  ];

  @override
  Widget build(BuildContext context) {
    final missing = _missing;
    final ready = missing.isEmpty;
    final body = SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(32, 26, 32, 28),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            '그리드맵 작성',
            style: TextStyle(fontSize: 18, fontWeight: FontWeight.w800),
          ),
          const SizedBox(height: 7),
          const Text(
            'AMCL·Nav2 가 쓰는 점유격자를 지금 도면에서 만듭니다. '
            'RMF 는 nav graph 만으로 길을 찾지만, 로봇이 제 위치를 알고 '
            '장애물을 피하려면 이 격자가 있어야 합니다.',
            style: TextStyle(
              fontSize: 13,
              height: 1.6,
              color: Color(0xFF475569),
            ),
          ),
          const SizedBox(height: 22),
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(18),
            decoration: BoxDecoration(
              color: Colors.white,
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: const Color(0xFFE2E8F0)),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _GridMapFact(
                  label: '맵 프로젝트',
                  value: projectName ?? '열린 프로젝트 없음',
                  dim: projectName == null,
                ),
                _GridMapFact(label: '맵 이름', value: mapName),
                _GridMapFact(
                  label: '격자 한 칸',
                  value:
                      '${resolution.toStringAsFixed(6)} m'
                      '${gridCells == null ? '' : ' · ${gridCells!.width} × '
                                '${gridCells!.height} 칸'}',
                ),
                _GridMapFact(label: '나갈 곳', value: '$mapDirectory/nav2_map/'),
              ],
            ),
          ),
          const SizedBox(height: 18),
          _GridResolutionSettings(
            mode: resolutionMode,
            targetWidth: targetWidth,
            targetHeight: targetHeight,
            padToTarget: padToTarget,
            manualResolution: manualResolution,
            resolution: resolution,
            extent: extent,
            robotWidth: robotWidth,
            drawingScale: drawingScale,
            onChanged: onResolutionChanged,
          ),
          // 고친 것이 있을 때만 나온다. 늘 켜 두면 눌러야 하는지 아닌지를
          // 화면에서 알 수 없다.
          if (unsavedChanges.isNotEmpty) ...[
            const SizedBox(height: 14),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.fromLTRB(16, 14, 16, 14),
              decoration: BoxDecoration(
                color: const Color(0xFFFFFBEB),
                borderRadius: BorderRadius.circular(11),
                border: Border.all(color: const Color(0xFFFCD34D)),
              ),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Icon(
                    Icons.edit_note,
                    size: 20,
                    color: Color(0xFFB45309),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text(
                          '저장하지 않은 설정이 있습니다',
                          style: TextStyle(
                            fontWeight: FontWeight.w700,
                            fontSize: 13,
                          ),
                        ),
                        const SizedBox(height: 4),
                        // 무엇을 저장하는지 적는다. 단추만 켜 두면 무엇이
                        // 바뀌었는지 모르는 채로 누르게 된다.
                        Text(
                          unsavedChanges.join('\n'),
                          style: const TextStyle(
                            fontSize: 12.5,
                            height: 1.5,
                            color: Color(0xFF78350F),
                          ),
                        ),
                        if (projectName == null) ...[
                          const SizedBox(height: 6),
                          const Text(
                            '아직 맵 프로젝트가 없어 저장할 곳이 없습니다. '
                            '맵 관리에서 `프로젝트 저장`으로 먼저 만드세요.',
                            style: TextStyle(
                              fontSize: 12,
                              color: Color(0xFF92400E),
                            ),
                          ),
                        ],
                      ],
                    ),
                  ),
                  const SizedBox(width: 12),
                  FilledButton.icon(
                    onPressed: projectName == null ? null : onSaveSettings,
                    icon: const Icon(Icons.save_outlined, size: 18),
                    label: const Text('설정 저장'),
                  ),
                ],
              ),
            ),
          ],
          const SizedBox(height: 18),
          if (!ready)
            Container(
              width: double.infinity,
              padding: const EdgeInsets.fromLTRB(16, 14, 16, 15),
              decoration: BoxDecoration(
                color: const Color(0xFFFFFBEB),
                borderRadius: BorderRadius.circular(11),
                border: Border.all(color: const Color(0xFFFCD34D)),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    '아직 만들 수 없습니다',
                    style: TextStyle(
                      fontSize: 13.5,
                      fontWeight: FontWeight.w800,
                      color: Color(0xFF92400E),
                    ),
                  ),
                  const SizedBox(height: 9),
                  for (final step in missing)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 5),
                      child: Text(
                        '· $step',
                        style: const TextStyle(
                          fontSize: 12.5,
                          height: 1.5,
                          color: Color(0xFF92400E),
                        ),
                      ),
                    ),
                  const SizedBox(height: 4),
                  TextButton.icon(
                    onPressed: onOpenMap,
                    icon: const Icon(Icons.map_outlined, size: 17),
                    label: const Text('맵 관리로 가기'),
                    style: TextButton.styleFrom(
                      padding: EdgeInsets.zero,
                      minimumSize: const Size(0, 32),
                      tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                    ),
                  ),
                ],
              ),
            ),
          if (ready)
            const Text(
              '도면과 축척, Floor 가 모두 준비되었습니다. 도면의 벽을 고쳤다면 '
              '다시 구워야 로봇이 새 벽을 봅니다.',
              style: TextStyle(
                fontSize: 12.5,
                height: 1.6,
                color: Color(0xFF475569),
              ),
            ),
          const SizedBox(height: 20),
          Row(
            children: [
              FilledButton.icon(
                onPressed: ready && !generating ? onGenerate : null,
                icon: generating
                    ? const SizedBox(
                        width: 18,
                        height: 18,
                        child: CircularProgressIndicator(strokeWidth: 2.2),
                      )
                    : const Icon(Icons.grid_on_outlined, size: 18),
                label: Text(generating ? '그리드 이미지 작성 중…' : '그리드맵 만들기'),
                style: FilledButton.styleFrom(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 22,
                    vertical: 16,
                  ),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(9),
                  ),
                ),
              ),
              if (generating) ...[
                const SizedBox(width: 16),
                const Expanded(
                  child: Text(
                    '도면의 벽과 바닥을 칸으로 옮기고 있습니다. 맵이 넓으면 '
                    '몇 초 걸립니다.',
                    style: TextStyle(fontSize: 12.5, color: Color(0xFF64748B)),
                  ),
                ),
              ],
            ],
          ),
          if (preview != null) ...[
            const SizedBox(height: 26),
            _GridMapPreview(
              image: preview!,
              grid: previewGrid,
              directory: previewDirectory,
              savedAt: previewSavedAt,
            ),
          ],

          // ── 로봇이 뜬 지도 ────────────────────────────────────
          const SizedBox(height: 30),
          const Divider(height: 1, color: Color(0xFFE2E8F0)),
          const SizedBox(height: 22),
          const Text(
            '로봇이 뜬 지도 (SLAM)',
            style: TextStyle(fontSize: 16, fontWeight: FontWeight.w800),
          ),
          const SizedBox(height: 7),
          const Text(
            '실제 건물에서는 도면이 아니라 로봇이 돌아다니며 지도를 뜹니다'
            '(`map_saver`). 그 지도의 원점은 로봇이 SLAM 을 시작한 자리라서 '
            'RMF 원점(도면 왼쪽 위)과 아무 관계가 없습니다. 그래서 올린 뒤에 '
            '원점을 맞춰 주어야 합니다.',
            style: TextStyle(
              fontSize: 13,
              height: 1.6,
              color: Color(0xFF475569),
            ),
          ),
          const SizedBox(height: 14),
          // `map_saver` 는 두 파일을 낸다. 무엇을 먼저 고르는지가 분명해야
          // 한다 — `.pgm` 만 골라서는 한 칸 크기도 원점도 알 수 없다.
          Container(
            padding: const EdgeInsets.fromLTRB(15, 12, 15, 13),
            decoration: BoxDecoration(
              color: const Color(0xFFEFF6FF),
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: const Color(0xFFBFDBFE)),
            ),
            child: const Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '.yaml 을 먼저 고르세요',
                  style: TextStyle(
                    fontSize: 13,
                    fontWeight: FontWeight.w800,
                    color: Color(0xFF1E40AF),
                  ),
                ),
                SizedBox(height: 6),
                Text(
                  '`map_saver` 는 yaml 과 그림 두 파일을 냅니다. `.yaml` 을 '
                  '고르면 옆의 그림은 앱이 따라 읽으므로 따로 고르지 않아도 '
                  '됩니다. 그림은 PGM·PNG 어느 쪽이어도 됩니다'
                  '(`--fmt` 에 따라 다릅니다). 두 파일은 같은 디렉터리에 함께 '
                  '두세요.',
                  style: TextStyle(
                    fontSize: 12.5,
                    height: 1.55,
                    color: Color(0xFF1E3A8A),
                  ),
                ),
                SizedBox(height: 8),
                Text(
                  'ros2 run nav2_map_server map_saver_cli -f my_map',
                  style: TextStyle(
                    fontSize: 11.5,
                    fontFamily: 'monospace',
                    color: Color(0xFF3B5BA9),
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 14),
          OutlinedButton.icon(
            onPressed: readingSlam ? null : onUploadSlam,
            icon: readingSlam
                ? const SizedBox(
                    width: 18,
                    height: 18,
                    child: CircularProgressIndicator(strokeWidth: 2.2),
                  )
                : const Icon(Icons.upload_file_outlined, size: 18),
            label: Text(readingSlam ? '읽는 중…' : 'SLAM 지도 올리기 — .yaml 고르기'),
            style: OutlinedButton.styleFrom(
              padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 15),
            ),
          ),
          if (slamMap != null) ...[
            const SizedBox(height: 22),
            _SlamMapPanel(
              map: slamMap!,
              image: slamPreview,
              referenceGrid: previewGrid,
              useSlamMap: useSlamMap,
              onSaveOrigin: onSaveSlamOrigin,
              onUseSlamMapChanged: onUseSlamMapChanged,
              scale: slamScale,
              onApplyScale: onApplySlamScale,
            ),
          ],
        ],
      ),
    );
    // 굽는 동안은 커서로도 알린다. 화면이 멈춘 것과 일하고 있는 것을 사람이
    // 구분할 수 있어야 한다.
    return generating
        ? MouseRegion(
            cursor: SystemMouseCursors.progress,
            child: AbsorbPointer(child: body),
          )
        : body;
  }
}

/// 격자 한 칸을 무엇으로 정할지 고르는 칸.
///
/// 기본은 800×600 상자에 맞추기다. 파일 크기가 예측 가능해지고, 작은 아레나에서는
/// 자동 계산식보다 훨씬 촘촘해진다.
///
/// **칸 수를 고정하면 해상도가 건물 크기에 따라 정해진다.** 100×60m 창고를
/// 800×600 에 넣으면 한 칸이 0.126m 가 되어 로봇 몸이 4.7칸밖에 안 걸친다. 그러면
/// 좁은 통로가 통째로 막힌 것으로 보인다. 그래서 그 자리에서 경고한다.
class _GridResolutionSettings extends StatefulWidget {
  const _GridResolutionSettings({
    required this.mode,
    required this.targetWidth,
    required this.targetHeight,
    required this.padToTarget,
    required this.manualResolution,
    required this.resolution,
    required this.extent,
    required this.robotWidth,
    required this.drawingScale,
    required this.onChanged,
  });

  final _GridResolutionMode mode;
  final int targetWidth;
  final int targetHeight;
  final bool padToTarget;
  final double manualResolution;

  /// 지금 설정으로 나온 한 칸 크기.
  final double resolution;
  final ({double width, double height})? extent;
  final double robotWidth;
  final double? drawingScale;
  final void Function(
    _GridResolutionMode mode,
    int targetWidth,
    int targetHeight,
    bool padToTarget,
    double manualResolution,
  )
  onChanged;

  @override
  State<_GridResolutionSettings> createState() =>
      _GridResolutionSettingsState();
}

class _GridResolutionSettingsState extends State<_GridResolutionSettings> {
  late final TextEditingController _width = TextEditingController(
    text: '${widget.targetWidth}',
  );
  late final TextEditingController _height = TextEditingController(
    text: '${widget.targetHeight}',
  );
  late final TextEditingController _manual = TextEditingController(
    text: widget.manualResolution.toStringAsFixed(4),
  );

  @override
  void dispose() {
    _width.dispose();
    _height.dispose();
    _manual.dispose();
    super.dispose();
  }

  void _push(_GridResolutionMode mode, {bool? pad}) {
    widget.onChanged(
      mode,
      int.tryParse(_width.text.trim()) ?? widget.targetWidth,
      int.tryParse(_height.text.trim()) ?? widget.targetHeight,
      pad ?? widget.padToTarget,
      double.tryParse(_manual.text.trim()) ?? widget.manualResolution,
    );
  }

  @override
  Widget build(BuildContext context) {
    final cells = widget.extent == null
        ? null
        : (
            width: (widget.extent!.width / widget.resolution).ceil(),
            height: (widget.extent!.height / widget.resolution).ceil(),
          );
    final coarse = occupancyResolutionTooCoarse(
      resolution: widget.resolution,
      robotWidth: widget.robotWidth,
    );
    final span = widget.resolution <= 0
        ? 0.0
        : widget.robotWidth / widget.resolution;
    // ListTile 류는 가장 가까운 Material 에 배경과 잉크를 그린다. 배경색 있는
    // Container 안에 그냥 두면 그 효과가 가려져 프레임워크가 경고한다.
    return Material(
      color: const Color(0xFFF8FAFC),
      borderRadius: BorderRadius.circular(11),
      child: Container(
        padding: const EdgeInsets.fromLTRB(18, 15, 18, 16),
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(11),
          border: Border.all(color: const Color(0xFFE2E8F0)),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              '격자 한 칸을 무엇으로 정할까',
              style: TextStyle(fontSize: 13.5, fontWeight: FontWeight.w800),
            ),
            const SizedBox(height: 8),
            RadioGroup<_GridResolutionMode>(
              groupValue: widget.mode,
              onChanged: (value) {
                if (value != null) _push(value);
              },
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const RadioListTile<_GridResolutionMode>(
                    value: _GridResolutionMode.target,
                    dense: true,
                    contentPadding: EdgeInsets.zero,
                    title: Text('크기 맞추기 (기본)'),
                  ),
                  Padding(
                    padding: const EdgeInsets.only(left: 34, bottom: 8),
                    child: Wrap(
                      spacing: 10,
                      runSpacing: 8,
                      crossAxisAlignment: WrapCrossAlignment.center,
                      children: [
                        _numberField(_width, '가로 칸'),
                        const Text('×'),
                        _numberField(_height, '세로 칸'),
                        FilledButton.tonal(
                          onPressed: () => _push(_GridResolutionMode.target),
                          child: const Text('적용'),
                        ),
                        SizedBox(
                          width: 300,
                          child: CheckboxListTile(
                            value: widget.padToTarget,
                            dense: true,
                            contentPadding: EdgeInsets.zero,
                            controlAffinity: ListTileControlAffinity.leading,
                            title: const Text(
                              '남는 쪽을 `모름` 으로 채워 정확히 맞추기',
                              style: TextStyle(fontSize: 12.5),
                            ),
                            onChanged: (value) => _push(
                              _GridResolutionMode.target,
                              pad: value ?? false,
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                  const RadioListTile<_GridResolutionMode>(
                    value: _GridResolutionMode.auto,
                    dense: true,
                    contentPadding: EdgeInsets.zero,
                    title: Text('자동'),
                    subtitle: Text('로봇 몸 6칸 · 바닥 짧은 쪽 120칸으로 앱이 정합니다.'),
                  ),
                  const RadioListTile<_GridResolutionMode>(
                    value: _GridResolutionMode.manual,
                    dense: true,
                    contentPadding: EdgeInsets.zero,
                    title: Text('직접 지정'),
                  ),
                  Padding(
                    padding: const EdgeInsets.only(left: 34),
                    child: Wrap(
                      spacing: 10,
                      crossAxisAlignment: WrapCrossAlignment.center,
                      children: [
                        _numberField(_manual, 'm/칸', width: 110),
                        FilledButton.tonal(
                          onPressed: () => _push(_GridResolutionMode.manual),
                          child: const Text('적용'),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 12),
            const Divider(height: 1, color: Color(0xFFE2E8F0)),
            const SizedBox(height: 10),
            Text(
              '지금 설정  ${widget.resolution.toStringAsFixed(6)} m/칸'
              '${cells == null ? '' : '  →  ${cells.width} × ${cells.height} 칸'}'
              '${span <= 0 ? '' : '  ·  로봇 몸이 ${span.toStringAsFixed(1)}칸'}',
              style: const TextStyle(
                fontSize: 12.5,
                fontWeight: FontWeight.w700,
                color: Color(0xFF334155),
              ),
            ),
            const SizedBox(height: 5),
            Text(
              '참고  costmap 0.050000 m/칸'
              '${widget.drawingScale == null ? '' : '  ·  도면 해상도 '
                        '${widget.drawingScale!.toStringAsFixed(6)} m/px'}',
              style: const TextStyle(fontSize: 11.5, color: Color(0xFF94A3B8)),
            ),
            if (coarse) ...[
              const SizedBox(height: 10),
              Container(
                width: double.infinity,
                padding: const EdgeInsets.fromLTRB(13, 10, 13, 11),
                decoration: BoxDecoration(
                  color: const Color(0xFFFEF2F2),
                  borderRadius: BorderRadius.circular(9),
                  border: Border.all(color: const Color(0xFFFCA5A5)),
                ),
                child: Text(
                  '한 칸이 너무 큽니다. 로봇 몸(${widget.robotWidth}m)이 '
                  '${span.toStringAsFixed(1)}칸에 걸치는데, 여섯 칸은 되어야 좁은 '
                  '통로가 통째로 막힌 것으로 보이지 않습니다. costmap 이 쓰는 '
                  '0.05 m/칸보다 거칠면 벽이 뭉개진 채로 계획에 들어갑니다.\n'
                  '칸 수를 늘리거나 `자동` 으로 두세요.',
                  style: TextStyle(
                    fontSize: 12,
                    height: 1.55,
                    color: Color(0xFF991B1B),
                  ),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }

  Widget _numberField(
    TextEditingController controller,
    String label, {
    double width = 92,
  }) => SizedBox(
    width: width,
    child: TextField(
      controller: controller,
      decoration: InputDecoration(
        labelText: label,
        isDense: true,
        border: const OutlineInputBorder(),
      ),
    ),
  );
}

/// 구운 그리드맵을 그림으로 보여 준다.
///
/// `map_server` 가 읽는 PGM 과 같은 픽셀이다. 벽은 검고 바닥은 희고 모르는 곳은
/// 회색이다. 눈으로 벽이 끊긴 데가 보이면 그게 AMCL 이 헷갈리는 자리다.
class _GridMapPreview extends StatelessWidget {
  const _GridMapPreview({
    required this.image,
    required this.grid,
    required this.directory,
    this.savedAt,
  });

  final ui.Image image;
  final OccupancyGrid? grid;
  final String? directory;

  /// 프로젝트에 저장돼 있던 것을 올렸으면 그 파일을 쓴 때. 방금 구웠으면 null.
  final DateTime? savedAt;

  @override
  Widget build(BuildContext context) {
    final g = grid;
    final stored = savedAt;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            const Icon(Icons.check_circle, size: 18, color: Color(0xFF16A34A)),
            const SizedBox(width: 8),
            Text(
              stored == null ? '만든 그리드맵' : '프로젝트에 저장된 그리드맵',
              style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w800),
            ),
            if (stored != null) ...[
              const SizedBox(width: 10),
              Text(
                // 도면을 이 뒤에 고쳤으면 지도가 옛것이다. 언제 만든 것인지
                // 보이지 않으면 최신인 줄 알고 그대로 배포한다.
                '${_ControlDashboardState._projectTimestamp(stored)} 작성',
                style: const TextStyle(
                  fontSize: 12.5,
                  color: Color(0xFF64748B),
                ),
              ),
            ],
            if (g != null) ...[
              const SizedBox(width: 12),
              Text(
                '${g.width} × ${g.height} 칸 · 한 칸 '
                '${g.resolution.toStringAsFixed(3)} m',
                style: const TextStyle(
                  fontSize: 12.5,
                  color: Color(0xFF64748B),
                ),
              ),
            ],
          ],
        ),
        const SizedBox(height: 10),
        Container(
          padding: const EdgeInsets.all(10),
          decoration: BoxDecoration(
            // 바닥이 흰색이라 흰 카드 위에 놓으면 지도의 범위가 안 보인다.
            color: const Color(0xFFE2E8F0),
            borderRadius: BorderRadius.circular(10),
            border: Border.all(color: const Color(0xFFCBD5E1)),
          ),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxHeight: 420, maxWidth: 720),
            child: FittedBox(
              child: RawImage(
                image: image,
                // 칸이 뭉개지면 벽이 이어져 보인다. 있는 그대로 키운다.
                filterQuality: FilterQuality.none,
              ),
            ),
          ),
        ),
        if (g != null) ...[
          const SizedBox(height: 12),
          Wrap(
            spacing: 20,
            runSpacing: 6,
            children: [
              _GridLegend(
                color: const Color(0xFF000000),
                label: '벽 ${g.occupiedCells}칸',
              ),
              _GridLegend(
                color: const Color(0xFFFEFEFE),
                label: '바닥 ${g.freeCells}칸',
              ),
              _GridLegend(
                color: const Color(0xFFCDCDCD),
                label: '모름 ${g.unknownCells}칸',
              ),
            ],
          ),
        ],
        if (directory != null && directory!.isNotEmpty) ...[
          const SizedBox(height: 10),
          SelectableText(
            // 이미 `nav2_map` 까지 들어 있는 경로다. 뒤에 또 붙이면 없는
            // 디렉터리를 알려 주게 된다.
            '$directory/',
            style: const TextStyle(fontSize: 12, color: Color(0xFF64748B)),
          ),
        ],
      ],
    );
  }
}

/// 올린 SLAM 지도 — 그림, 원점 맞추기, 어느 지도를 쓸지.
///
/// 원점을 손으로 넣게 하는 이유는, 자동으로 맞출 방법이 아직 없기 때문이다.
/// 로봇을 아는 자리에 세우고 그 포즈로 계산하는 방법이 있지만 실물 로봇이
/// 있어야 한다. 그때까지는 **범위를 맞춘 제안값**에서 시작해 사람이 겹쳐 보며
/// 잡는 것이 가장 빠르다.
class _SlamMapPanel extends StatefulWidget {
  const _SlamMapPanel({
    required this.map,
    required this.image,
    required this.referenceGrid,
    required this.useSlamMap,
    required this.onSaveOrigin,
    required this.onUseSlamMapChanged,
    required this.scale,
    required this.onApplyScale,
  });

  final SlamMap map;
  final ui.Image? image;

  /// 도면에서 만든 격자. 제안값을 계산할 기준이다.
  final OccupancyGrid? referenceGrid;
  final bool useSlamMap;
  final void Function(double x, double y) onSaveOrigin;
  final ValueChanged<bool> onUseSlamMapChanged;

  /// 도면 축척과 견준 결과. 격자를 아직 안 구웠으면 null.
  final WallExtentComparison? scale;
  final void Function(double ratio) onApplyScale;

  @override
  State<_SlamMapPanel> createState() => _SlamMapPanelState();
}

class _SlamMapPanelState extends State<_SlamMapPanel> {
  late final TextEditingController _x = TextEditingController(
    text: widget.map.originX.toStringAsFixed(6),
  );
  late final TextEditingController _y = TextEditingController(
    text: widget.map.originY.toStringAsFixed(6),
  );

  @override
  void didUpdateWidget(_SlamMapPanel old) {
    super.didUpdateWidget(old);
    // 저장하고 다시 읽어 오면 칸을 새 값으로 맞춘다.
    if (old.map.originX != widget.map.originX) {
      _x.text = widget.map.originX.toStringAsFixed(6);
    }
    if (old.map.originY != widget.map.originY) {
      _y.text = widget.map.originY.toStringAsFixed(6);
    }
  }

  @override
  void dispose() {
    _x.dispose();
    _y.dispose();
    super.dispose();
  }

  /// 도면 격자와 덮는 범위의 가운데를 맞춘 제안값.
  ({double x, double y})? get _suggestion {
    final reference = widget.referenceGrid;
    if (reference == null) return null;
    final bounds = reference.bounds;
    return suggestSlamOrigin(
      slamWidth: widget.map.width,
      slamHeight: widget.map.height,
      slamResolution: widget.map.resolution,
      referenceMinX: bounds.minX,
      referenceMinY: bounds.minY,
      referenceWidthMeters: bounds.maxX - bounds.minX,
      referenceHeightMeters: bounds.maxY - bounds.minY,
    );
  }

  void _save() {
    final x = double.tryParse(_x.text.trim());
    final y = double.tryParse(_y.text.trim());
    if (x == null || y == null) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('원점은 숫자여야 합니다.')));
      return;
    }
    widget.onSaveOrigin(x, y);
  }

  @override
  Widget build(BuildContext context) {
    final map = widget.map;
    final bounds = map.bounds;
    final suggestion = _suggestion;
    // RadioListTile 이 들어 있다. 배경색 있는 Container 안에 그냥 두면 잉크가
    // 가려져 프레임워크가 경고한다.
    return Material(
      color: Colors.white,
      borderRadius: BorderRadius.circular(12),
      child: Container(
        padding: const EdgeInsets.all(18),
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: const Color(0xFFE2E8F0)),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              '${map.width} × ${map.height} 칸 · 한 칸 '
              '${map.resolution.toStringAsFixed(3)} m',
              style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w700),
            ),
            const SizedBox(height: 4),
            Text(
              '덮는 범위  x ${bounds.minX.toStringAsFixed(3)} ~ '
              '${bounds.maxX.toStringAsFixed(3)} m · '
              'y ${bounds.minY.toStringAsFixed(3)} ~ '
              '${bounds.maxY.toStringAsFixed(3)} m',
              style: const TextStyle(fontSize: 12, color: Color(0xFF64748B)),
            ),
            if (widget.image != null) ...[
              const SizedBox(height: 12),
              Container(
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: const Color(0xFFE2E8F0),
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(color: const Color(0xFFCBD5E1)),
                ),
                child: ConstrainedBox(
                  constraints: const BoxConstraints(
                    maxHeight: 300,
                    maxWidth: 520,
                  ),
                  child: FittedBox(
                    child: RawImage(
                      image: widget.image,
                      filterQuality: FilterQuality.none,
                    ),
                  ),
                ),
              ),
            ],
            if (widget.scale != null) ...[
              const SizedBox(height: 18),
              _SlamScalePanel(
                comparison: widget.scale!,
                onApply: widget.onApplyScale,
              ),
            ],
            const SizedBox(height: 18),
            const Text(
              '원점 맞추기',
              style: TextStyle(fontSize: 13.5, fontWeight: FontWeight.w800),
            ),
            const SizedBox(height: 4),
            const Text(
              '그림의 왼쪽 아래 모서리가 RMF 월드에서 어디인가입니다. '
              '두 지도를 겹쳐 보고 벽이 맞으면 맞은 것입니다.',
              style: TextStyle(
                fontSize: 12,
                height: 1.5,
                color: Color(0xFF64748B),
              ),
            ),
            const SizedBox(height: 12),
            Row(
              children: [
                SizedBox(
                  width: 150,
                  child: TextField(
                    controller: _x,
                    decoration: const InputDecoration(
                      labelText: 'origin x (m)',
                      isDense: true,
                      border: OutlineInputBorder(),
                    ),
                  ),
                ),
                const SizedBox(width: 10),
                SizedBox(
                  width: 150,
                  child: TextField(
                    controller: _y,
                    decoration: const InputDecoration(
                      labelText: 'origin y (m)',
                      isDense: true,
                      border: OutlineInputBorder(),
                    ),
                  ),
                ),
                const SizedBox(width: 12),
                FilledButton(onPressed: _save, child: const Text('원점 저장')),
              ],
            ),
            if (suggestion != null) ...[
              const SizedBox(height: 12),
              Wrap(
                spacing: 12,
                runSpacing: 8,
                crossAxisAlignment: WrapCrossAlignment.center,
                children: [
                  Text(
                    '제안 ${suggestion.x.toStringAsFixed(6)}, '
                    '${suggestion.y.toStringAsFixed(6)}',
                    style: const TextStyle(
                      fontSize: 12.5,
                      color: Color(0xFF475569),
                    ),
                  ),
                  TextButton.icon(
                    onPressed: () {
                      _x.text = suggestion.x.toStringAsFixed(6);
                      _y.text = suggestion.y.toStringAsFixed(6);
                    },
                    icon: const Icon(Icons.auto_fix_high_outlined, size: 16),
                    label: const Text('제안값 넣기'),
                    style: TextButton.styleFrom(
                      padding: const EdgeInsets.symmetric(horizontal: 8),
                      minimumSize: const Size(0, 32),
                      tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                    ),
                  ),
                  const Text(
                    '— 도면 지도와 덮는 범위의 가운데를 맞춘 값입니다. '
                    '정답이 아니라 출발점입니다.',
                    style: TextStyle(fontSize: 11.5, color: Color(0xFF94A3B8)),
                  ),
                ],
              ),
            ],
            const SizedBox(height: 20),
            const Divider(height: 1, color: Color(0xFFE2E8F0)),
            const SizedBox(height: 14),
            const Text(
              'Nav2 가 띄울 지도',
              style: TextStyle(fontSize: 13.5, fontWeight: FontWeight.w800),
            ),
            const SizedBox(height: 6),
            RadioGroup<bool>(
              groupValue: widget.useSlamMap,
              onChanged: (value) {
                if (value != null) widget.onUseSlamMapChanged(value);
              },
              child: const Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  RadioListTile<bool>(
                    value: false,
                    dense: true,
                    contentPadding: EdgeInsets.zero,
                    title: Text('도면에서 만든 지도'),
                    subtitle: Text('원점이 계산으로 맞습니다. 시뮬레이션에 씁니다.'),
                  ),
                  RadioListTile<bool>(
                    value: true,
                    dense: true,
                    contentPadding: EdgeInsets.zero,
                    title: Text('SLAM 지도'),
                    subtitle: Text('실제 건물에 씁니다. 원점을 맞춘 뒤에 고르세요.'),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 4),
            const Text(
              '고른 지도는 프로젝트에 저장됩니다. `프로젝트 저장` 을 누르면 '
              'Nav2 launch 가 그 지도를 가리키게 다시 만들어집니다.',
              style: TextStyle(
                fontSize: 11.5,
                height: 1.5,
                color: Color(0xFF94A3B8),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// 도면 축척을 SLAM 지도로 견준 결과.
///
/// **정합(alignment)의 첫 단계다.** 도면의 축척은 사람이 두 점 사이 실제 거리를
/// 재서 넣은 값이라 오차가 있고, SLAM 은 로봇이 실제로 굴러 잰 값이다. 두 지도의
/// 벽 테두리를 견주면 그 오차가 몇 %인지 나온다.
///
/// **정답이 아니라 근거다.** 테두리만 보므로 회전은 못 잡고, SLAM 이 한쪽 복도를
/// 덜 돌았으면 그만큼 작게 나온다. 그래서 두 축의 비가 서로 어긋나면 믿지 말라고
/// 말하고, 마지막 판단은 사람이 겹쳐 보고 한다.
class _SlamScalePanel extends StatelessWidget {
  const _SlamScalePanel({required this.comparison, required this.onApply});

  final WallExtentComparison comparison;
  final void Function(double ratio) onApply;

  @override
  Widget build(BuildContext context) {
    final trust = comparison.trustworthy;
    final percent = comparison.percent;
    // 0.5% 안쪽이면 손댈 것이 없다. 측정 오차 범위다.
    final matched = percent.abs() < .5;
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(15, 13, 15, 14),
      decoration: BoxDecoration(
        color: matched
            ? const Color(0xFFF0FDF4)
            : (trust ? const Color(0xFFFFFBEB) : const Color(0xFFF8FAFC)),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(
          color: matched
              ? const Color(0xFF86EFAC)
              : (trust ? const Color(0xFFFCD34D) : const Color(0xFFE2E8F0)),
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(
                matched ? Icons.check_circle : Icons.straighten,
                size: 17,
                color: matched
                    ? const Color(0xFF16A34A)
                    : const Color(0xFF92400E),
              ),
              const SizedBox(width: 8),
              const Text(
                '축척 검증',
                style: TextStyle(fontSize: 13.5, fontWeight: FontWeight.w800),
              ),
            ],
          ),
          const SizedBox(height: 9),
          Text(
            '도면  ${comparison.drawingWidth.toStringAsFixed(3)} × '
            '${comparison.drawingHeight.toStringAsFixed(3)} m\n'
            'SLAM  ${comparison.slamWidth.toStringAsFixed(3)} × '
            '${comparison.slamHeight.toStringAsFixed(3)} m\n'
            '가로 ${comparison.ratioX.toStringAsFixed(4)}배 · '
            '세로 ${comparison.ratioY.toStringAsFixed(4)}배',
            style: const TextStyle(
              fontSize: 12.5,
              height: 1.6,
              color: Color(0xFF334155),
            ),
          ),
          const SizedBox(height: 9),
          if (matched)
            const Text(
              '두 지도의 벽 테두리가 맞습니다. 도면 축척을 손댈 것이 없습니다.',
              style: TextStyle(
                fontSize: 12.5,
                height: 1.55,
                color: Color(0xFF15803D),
              ),
            )
          else ...[
            Text(
              '도면 축척이 SLAM 대비 ${percent.abs().toStringAsFixed(2)}% '
              '${percent > 0 ? '작게' : '크게'} 잡혀 있습니다.',
              style: const TextStyle(
                fontSize: 13,
                fontWeight: FontWeight.w700,
                color: Color(0xFF92400E),
              ),
            ),
            const SizedBox(height: 7),
            if (!trust)
              const Text(
                '다만 가로와 세로의 비가 서로 5% 넘게 어긋납니다. 같은 건물이 '
                '아니거나, 지도가 돌아가 있거나, SLAM 이 한쪽을 덜 돌아본 '
                '것입니다. 이 숫자를 그대로 넣지 마세요 — 두 그림을 겹쳐 보고 '
                '벽이 맞는지 먼저 확인하세요.',
                style: TextStyle(
                  fontSize: 12,
                  height: 1.55,
                  color: Color(0xFF991B1B),
                ),
              )
            else
              const Text(
                '가로·세로의 비가 서로 맞으므로 축척 오차로 볼 수 있습니다. '
                '보정하면 building.yaml · nav graph · 그리드맵 · Gazebo 월드가 '
                '전부 다시 나옵니다. Waypoint 는 다시 찍지 않아도 됩니다.',
                style: TextStyle(
                  fontSize: 12,
                  height: 1.55,
                  color: Color(0xFF78350F),
                ),
              ),
            const SizedBox(height: 10),
            FilledButton.tonalIcon(
              onPressed: () => onApply(comparison.ratio),
              icon: const Icon(Icons.straighten, size: 17),
              label: Text(
                '도면 축척 ${percent > 0 ? '키우기' : '줄이기'} '
                '(${comparison.ratio.toStringAsFixed(4)}배)',
              ),
            ),
          ],
          const SizedBox(height: 8),
          const Text(
            '벽으로 읽히는 칸의 테두리만 견줍니다. 회전은 못 잡습니다.',
            style: TextStyle(fontSize: 11.5, color: Color(0xFF94A3B8)),
          ),
        ],
      ),
    );
  }
}

class _GridLegend extends StatelessWidget {
  const _GridLegend({required this.color, required this.label});

  final Color color;
  final String label;

  @override
  Widget build(BuildContext context) => Row(
    mainAxisSize: MainAxisSize.min,
    children: [
      Container(
        width: 13,
        height: 13,
        decoration: BoxDecoration(
          color: color,
          border: Border.all(color: const Color(0xFF94A3B8)),
          borderRadius: BorderRadius.circular(3),
        ),
      ),
      const SizedBox(width: 7),
      Text(
        label,
        style: const TextStyle(fontSize: 12.5, color: Color(0xFF475569)),
      ),
    ],
  );
}

class _GridMapFact extends StatelessWidget {
  const _GridMapFact({
    required this.label,
    required this.value,
    this.dim = false,
  });

  final String label;
  final String value;
  final bool dim;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(bottom: 11),
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(
          width: 108,
          child: Text(
            label,
            style: const TextStyle(fontSize: 12.5, color: Color(0xFF64748B)),
          ),
        ),
        Expanded(
          child: SelectableText(
            value,
            style: TextStyle(
              fontSize: 12.5,
              fontWeight: dim ? FontWeight.w400 : FontWeight.w700,
              color: dim ? const Color(0xFF94A3B8) : const Color(0xFF0F172A),
            ),
          ),
        ),
      ],
    ),
  );
}

class _MapFileStatus extends StatelessWidget {
  const _MapFileStatus({
    required this.sourceLabel,
    required this.sourceName,
    required this.buildingYamlName,
    required this.pendingDeployment,
  });

  final String sourceLabel;
  final String sourceName;
  final String buildingYamlName;
  final bool pendingDeployment;

  @override
  Widget build(BuildContext context) => Container(
    width: double.infinity,
    padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 11),
    decoration: BoxDecoration(
      color: pendingDeployment
          ? const Color(0xFFFFFBEB)
          : const Color(0xFFEFF6FF),
      borderRadius: BorderRadius.circular(10),
      border: Border.all(
        color: pendingDeployment
            ? const Color(0xFFFCD34D)
            : const Color(0xFFBFDBFE),
      ),
    ),
    child: Wrap(
      spacing: 20,
      runSpacing: 7,
      crossAxisAlignment: WrapCrossAlignment.center,
      children: [
        _MapFileStatusItem(
          icon: Icons.edit_document,
          label: sourceLabel,
          value: sourceName,
        ),
        _MapFileStatusItem(
          icon: Icons.description_outlined,
          label: 'building.yaml',
          value: buildingYamlName,
        ),
        if (pendingDeployment)
          const Chip(
            visualDensity: VisualDensity.compact,
            avatar: Icon(Icons.info_outline, size: 16),
            label: Text('배포 전'),
          ),
      ],
    ),
  );
}

class _MapFileStatusItem extends StatelessWidget {
  const _MapFileStatusItem({
    required this.icon,
    required this.label,
    required this.value,
  });

  final IconData icon;
  final String label;
  final String value;

  @override
  Widget build(BuildContext context) => Row(
    mainAxisSize: MainAxisSize.min,
    children: [
      Icon(icon, size: 18, color: const Color(0xFF2563EB)),
      const SizedBox(width: 7),
      Text('$label: ', style: const TextStyle(color: Color(0xFF64748B))),
      Text(value, style: const TextStyle(fontWeight: FontWeight.w800)),
    ],
  );
}

/// 등록된 로봇이 지금 지도에 올라와 있는지 한눈에 보여 준다.
class _RegistrationBadge extends StatelessWidget {
  const _RegistrationBadge({required this.label, required this.color});

  final String label;
  final Color color;

  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2),
    decoration: BoxDecoration(
      color: color.withValues(alpha: .12),
      borderRadius: BorderRadius.circular(6),
    ),
    child: Text(
      label,
      style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: color),
    ),
  );
}

/// 로봇 모델 저장소를 독립적으로 관리한다.
class _RobotModelManagementPage extends StatefulWidget {
  const _RobotModelManagementPage();

  @override
  State<_RobotModelManagementPage> createState() =>
      _RobotModelManagementPageState();
}

class _RobotModelManagementPageState extends State<_RobotModelManagementPage> {
  List<RobotModelInfo> _models = const [];
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    unawaited(_reload());
  }

  Future<void> _reload() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final models = await listRobotModels();
      if (!mounted) return;
      setState(() {
        _models = models;
        _loading = false;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _error = '$error';
        _loading = false;
      });
    }
  }

  Future<void> _importZip() async {
    final chosen = await FilePicker.platform.pickFiles(
      dialogTitle: '로봇 모델 ZIP 선택',
      type: FileType.custom,
      allowedExtensions: const ['zip'],
    );
    final path = chosen?.files.single.path;
    if (path == null) return;
    await _runImport(() => importRobotModelFromZip(path));
  }

  Future<void> _importGit() async {
    final answer = await showMovableDialog<({String url, String name})>(
      context: context,
      builder: (dialogContext) => _GitRobotModelDialog(
        onSubmit: (url, name) =>
            Navigator.pop(dialogContext, (url: url, name: name)),
      ),
    );
    if (answer == null) return;
    await _runImport(
      () => importRobotModelFromGit(
        answer.url,
        name: answer.name.trim().isEmpty ? null : answer.name.trim(),
      ),
    );
  }

  Future<void> _runImport(Future<RobotModelInfo> Function() action) async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      await action();
      await _reload();
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _error = '$error';
        _loading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.all(28),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    '로봇 모델 관리',
                    style: Theme.of(context).textTheme.headlineMedium,
                  ),
                  const SizedBox(height: 6),
                  const Text('Gazebo·ROS 2에서 사용할 로봇 모델 패키지를 등록하고 확인합니다.'),
                ],
              ),
            ),
            OutlinedButton.icon(
              onPressed: _loading ? null : _importGit,
              icon: const Icon(Icons.account_tree_outlined),
              label: const Text('Git에서 추가'),
            ),
            const SizedBox(width: 10),
            FilledButton.icon(
              onPressed: _loading ? null : _importZip,
              icon: const Icon(Icons.folder_zip_outlined),
              label: const Text('ZIP으로 추가'),
            ),
          ],
        ),
        const SizedBox(height: 18),
        Container(
          width: double.infinity,
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(
            color: const Color(0xFFEFF6FF),
            borderRadius: BorderRadius.circular(10),
            border: Border.all(color: const Color(0xFFBFDBFE)),
          ),
          child: const Text(
            '모델은 robot_model/<모델명>에 보관됩니다. ROS 2 작업공간, '
            'URDF·SDF 또는 여러 패키지가 포함된 저장소를 등록할 수 있습니다.',
          ),
        ),
        if (_error != null) ...[
          const SizedBox(height: 12),
          SelectableText(
            _error!,
            style: const TextStyle(color: Color(0xFFB91C1C)),
          ),
        ],
        const SizedBox(height: 14),
        Expanded(
          child: _loading
              ? const Center(child: CircularProgressIndicator())
              : _models.isEmpty
              ? const Center(child: Text('등록된 로봇 모델이 없습니다.'))
              : ListView.separated(
                  itemCount: _models.length,
                  separatorBuilder: (_, _) => const SizedBox(height: 8),
                  itemBuilder: (_, index) {
                    final model = _models[index];
                    return Card(
                      child: ListTile(
                        leading: CircleAvatar(
                          child: Icon(
                            model.isGitRepository
                                ? Icons.account_tree_outlined
                                : Icons.view_in_ar_outlined,
                          ),
                        ),
                        title: Text(
                          model.name,
                          style: const TextStyle(fontWeight: FontWeight.w800),
                        ),
                        subtitle: SelectableText(
                          '${model.packageCount}개 ROS 패키지\n${model.path}',
                        ),
                        isThreeLine: true,
                      ),
                    );
                  },
                ),
        ),
      ],
    ),
  );
}

class _GitRobotModelDialog extends StatefulWidget {
  const _GitRobotModelDialog({required this.onSubmit});
  final void Function(String url, String name) onSubmit;

  @override
  State<_GitRobotModelDialog> createState() => _GitRobotModelDialogState();
}

class _GitRobotModelDialogState extends State<_GitRobotModelDialog> {
  final _url = TextEditingController();
  final _name = TextEditingController();

  @override
  void dispose() {
    _url.dispose();
    _name.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
    icon: const Icon(Icons.account_tree_outlined),
    title: const Text('Git에서 로봇 모델 추가'),
    content: SizedBox(
      width: 520,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          TextField(
            controller: _url,
            autofocus: true,
            onChanged: (_) => setState(() {}),
            decoration: const InputDecoration(
              labelText: 'Git 저장소 주소 *',
              hintText: 'https://github.com/owner/robot.git',
              border: OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _name,
            decoration: const InputDecoration(
              labelText: '폴더 이름 (선택)',
              helperText: '비우면 저장소 이름을 사용합니다.',
              border: OutlineInputBorder(),
            ),
          ),
        ],
      ),
    ),
    actions: [
      TextButton(
        onPressed: () => Navigator.pop(context),
        child: const Text('취소'),
      ),
      FilledButton(
        onPressed: _url.text.trim().isEmpty
            ? null
            : () => widget.onSubmit(_url.text.trim(), _name.text.trim()),
        child: const Text('가져오기'),
      ),
    ],
  );
}

class _RobotManagementPage extends StatefulWidget {
  const _RobotManagementPage({
    required this.drawing,
    required this.activeMapSourceName,
    required this.activeBuildingYamlName,
    required this.pendingDeployment,
    required this.lanes,
    required this.waypoints,
    required this.waypointNames,
    required this.robots,
    required this.projectName,
    required this.fleetName,
    required this.registeredRobots,
    required this.onLoadMap,
    required this.onSpawn,
    required this.onToggle,
    required this.onRemove,
    required this.onRegisterRobot,
    required this.onOpenRobot,
    required this.onEditRegisteredRobot,
    required this.onUnregisterRobot,
    required this.onSendRobot,
    required this.onRegisterFromChargers,
    required this.onCheckSpawns,
    required this.spawnChecks,
    required this.onStartBackend,
    required this.onRefreshScripts,
    required this.telemetry,
    this.mapDirectory,
    this.deployMapName,
  });

  /// 이 프로젝트의 배포 산출물이 있는 곳. 없으면 내보내기 여부를 볼 수 없다.
  final String? mapDirectory;

  /// 산출물 파일 이름에 쓰이는 맵 이름(`<이름>_bringup.launch.xml`).
  final String? deployMapName;

  final UploadedDrawing? drawing;
  final String activeMapSourceName;
  final String activeBuildingYamlName;
  final bool pendingDeployment;
  final List<(Offset, Offset)> lanes;
  final List<Offset> waypoints;
  final Map<Offset, String> waypointNames;
  final List<_MockRobot> robots;

  /// 열린 맵 프로젝트. 없으면 등록해도 남길 곳이 없다.
  final String? projectName;
  final String fleetName;

  /// 프로젝트에 등록된 로봇. 스폰과 Gazebo bringup 이 이것을 본다.
  final List<RmfProjectRobot> registeredRobots;

  final VoidCallback onLoadMap;
  final VoidCallback onSpawn;
  final ValueChanged<_MockRobot> onToggle;
  final ValueChanged<_MockRobot> onRemove;
  final VoidCallback onRegisterRobot;

  /// 로봇 하나의 상세를 연다.
  final ValueChanged<String> onOpenRobot;
  final ValueChanged<RmfProjectRobot> onEditRegisteredRobot;
  final ValueChanged<RmfProjectRobot> onUnregisterRobot;

  /// 로봇 하나를 Waypoint 하나로 바로 보낸다. 작업 목록을 거치지 않는다.
  final ValueChanged<RmfProjectRobot> onSendRobot;
  final VoidCallback onRegisterFromChargers;

  /// 등록된 로봇이 설 자리가 지도와 맞는지 살피는 창을 연다.
  final VoidCallback onCheckSpawns;

  /// 자리 점검 결과. 버튼에 경고를 띄울지 여기서 가린다.
  final List<SpawnCheck> spawnChecks;

  /// 열린 프로젝트로 Gazebo 와 Open-RMF 를 함께 띄운다.
  final Future<void> Function() onStartBackend;

  /// 디스크의 실행·중지 스크립트를 MySQL 의 최신 내용으로 맞춘다.
  final Future<void> Function() onRefreshScripts;

  /// Gazebo 에서 실제로 값을 받고 있는지.
  final RobotTelemetryStatus telemetry;

  @override
  State<_RobotManagementPage> createState() => _RobotManagementPageState();
}

class _RobotManagementPageState extends State<_RobotManagementPage> {
  RmfRuntimeStatus _rmfStatus = RmfRuntimeStatus.unknown;
  bool _rmfBusy = false;

  Future<List<String>?> _askGitModel() async {
    var url = '';
    var name = '';
    return showMovableDialog<List<String>>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        icon: const Icon(Icons.account_tree_outlined),
        title: const Text('Git에서 로봇 모델 추가'),
        content: SizedBox(
          width: 520,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextFormField(
                autofocus: true,
                decoration: const InputDecoration(
                  labelText: 'Git 저장소 주소',
                  hintText: 'https://github.com/owner/robot.git',
                  border: OutlineInputBorder(),
                ),
                onChanged: (value) => url = value,
              ),
              const SizedBox(height: 12),
              TextFormField(
                decoration: const InputDecoration(
                  labelText: '폴더 이름 (선택)',
                  helperText: '비우면 저장소 이름을 사용합니다.',
                  border: OutlineInputBorder(),
                ),
                onChanged: (value) => name = value,
              ),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext),
            child: const Text('취소'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(dialogContext, [url, name]),
            child: const Text('가져오기'),
          ),
        ],
      ),
    );
  }

  Future<void> _showRobotModelManager() async {
    var models = await listRobotModels();
    if (!mounted) return;
    var busy = false;
    String? error;
    await showMovableDialog<void>(
      context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (context, setDialogState) {
          Future<void> runImport(
            Future<RobotModelInfo> Function() action,
          ) async {
            setDialogState(() {
              busy = true;
              error = null;
            });
            try {
              await action();
              models = await listRobotModels();
            } catch (caught) {
              error = '$caught';
            }
            if (dialogContext.mounted) {
              setDialogState(() => busy = false);
            }
          }

          return AlertDialog(
            icon: const Icon(Icons.smart_toy_outlined),
            title: const Text('로봇 모델 관리'),
            content: SizedBox(
              width: 720,
              height: 520,
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    '모든 모델은 robot_model/<모델명>에 보관됩니다. ROS 2 작업공간, '
                    'URDF·SDF 모델 또는 여러 패키지가 든 저장소를 추가할 수 있습니다.',
                    style: TextStyle(color: Color(0xFF64748B), height: 1.45),
                  ),
                  const SizedBox(height: 14),
                  if (error != null)
                    Container(
                      width: double.infinity,
                      margin: const EdgeInsets.only(bottom: 12),
                      padding: const EdgeInsets.all(10),
                      color: const Color(0xFFFEF2F2),
                      child: SelectableText(
                        error!,
                        style: const TextStyle(color: Color(0xFFB91C1C)),
                      ),
                    ),
                  Flexible(
                    child: models.isEmpty
                        ? const Padding(
                            padding: EdgeInsets.symmetric(vertical: 28),
                            child: Text('등록된 로봇 모델이 없습니다.'),
                          )
                        : ListView.separated(
                            shrinkWrap: true,
                            itemCount: models.length,
                            separatorBuilder: (_, _) =>
                                const Divider(height: 1),
                            itemBuilder: (_, index) {
                              final model = models[index];
                              return ListTile(
                                contentPadding: EdgeInsets.zero,
                                leading: Icon(
                                  model.isGitRepository
                                      ? Icons.account_tree_outlined
                                      : Icons.folder_outlined,
                                ),
                                title: Text(model.name),
                                subtitle: SelectableText(
                                  '${model.packageCount}개 ROS 패키지 · ${model.path}',
                                ),
                              );
                            },
                          ),
                  ),
                  if (busy) const LinearProgressIndicator(),
                ],
              ),
            ),
            actions: [
              OutlinedButton.icon(
                onPressed: busy
                    ? null
                    : () async {
                        final chosen = await FilePicker.platform.pickFiles(
                          dialogTitle: '로봇 모델 ZIP 선택',
                          type: FileType.custom,
                          allowedExtensions: const ['zip'],
                        );
                        final path = chosen?.files.single.path;
                        if (path != null) {
                          await runImport(() => importRobotModelFromZip(path));
                        }
                      },
                icon: const Icon(Icons.folder_zip_outlined),
                label: const Text('ZIP 추가'),
              ),
              OutlinedButton.icon(
                onPressed: busy
                    ? null
                    : () async {
                        final answer = await _askGitModel();
                        if (answer == null) return;
                        await runImport(
                          () => importRobotModelFromGit(
                            answer[0],
                            name: answer[1].trim().isEmpty ? null : answer[1],
                          ),
                        );
                      },
                icon: const Icon(Icons.cloud_download_outlined),
                label: const Text('Git 추가'),
              ),
              FilledButton(
                onPressed: busy ? null : () => Navigator.pop(dialogContext),
                child: const Text('닫기'),
              ),
            ],
          );
        },
      ),
    );
  }

  /// 노드 목록 스크롤. Scrollbar 와 스크롤 뷰가 같은 것을 잡아야 손잡이가
  /// 제자리에 붙는다.
  final ScrollController _nodeListScroll = ScrollController();

  @override
  void dispose() {
    _nodeListScroll.dispose();
    super.dispose();
  }

  @override
  void initState() {
    super.initState();
    // 이미 떠 있는 백엔드를 모르고 새로 띄우면 schedule node 와 fleet adapter 가
    // 부딪혀 엉뚱한 오류로 나타난다. 화면에 들어올 때 먼저 확인한다.
    unawaited(_refreshRmfStatus());
    unawaited(_refreshDeployedCount());
  }

  @override
  void didUpdateWidget(_RobotManagementPage oldWidget) {
    super.didUpdateWidget(oldWidget);
    // 로봇을 등록·해제하면 `내보내기` 칸의 판정이 달라진다. 등록만 하고 안
    // 내보낸 상태를 그 자리에서 보여 줘야 뜻이 있다.
    if (oldWidget.registeredRobots.length != widget.registeredRobots.length ||
        oldWidget.deployMapName != widget.deployMapName ||
        oldWidget.mapDirectory != widget.mapDirectory) {
      unawaited(_refreshDeployedCount());
    }
  }

  Future<void> _refreshRmfStatus() async {
    setState(() {
      _rmfBusy = true;
      _ghostNodes = false;
    });
    final status = await probeRmfRuntime();
    if (!mounted) return;
    setState(() {
      _rmfStatus = status;
      _rmfBusy = false;
    });
  }

  /// 백엔드를 띄우고, 올라올 때쯤 스스로 다시 확인한다.
  ///
  /// 실행 스크립트는 Gazebo 를 먼저 띄우고 12초 뒤 Open-RMF 를 올린다. 바로
  /// 확인하면 아직 아무것도 없어서 실패한 것처럼 보인다.
  Future<void> _startBackend() async {
    if (_rmfBusy || widget.projectName == null) return;
    setState(() => _rmfBusy = true);
    await widget.onStartBackend();
    if (!mounted) return;
    await Future<void>.delayed(const Duration(seconds: 16));
    if (!mounted) return;
    await _refreshUntilClear();
  }

  /// 배포된 bringup 이 담고 있는 로봇 수. 안 봤거나 파일이 없으면 null.
  ///
  /// 등록은 앱 안에만 남는다. 이 수가 지금 등록된 수와 다르면 `RMF 설정
  /// 내보내기` 를 아직 안 누른 것이다 — 그대로 띄우면 옛날 로봇 목록으로 뜬다.
  int? _deployedRobots;

  Future<void> _refreshDeployedCount() async {
    final directory = widget.mapDirectory;
    final name = widget.deployMapName;
    if (directory == null || name == null || name.trim().isEmpty) return;
    final count = await deployedSpawnCount(
      mapDirectory: directory,
      mapName: name,
    );
    if (!mounted) return;
    setState(() => _deployedRobots = count);
  }

  /// 로봇을 띄우기까지의 차례. 각 칸이 됐는지도 함께 본다.
  List<_WorkflowStep> get _workflowSteps {
    final gazeboRobots = widget.registeredRobots
        .where((robot) => robot.runsInGazebo)
        .length;
    final mapReady = widget.waypoints.isNotEmpty;
    final registered = widget.registeredRobots.isNotEmpty;
    // 내보낸 로봇 수가 지금 등록된 수와 같아야 한다. 파일만 있으면 옛날 것일 수
    // 있다 — 로봇을 한 대 더 등록하고 안 내보낸 경우가 그렇다.
    final exported = _deployedRobots != null && _deployedRobots == gazeboRobots;
    final backendUp = _rmfStatus.isRunning && !_ghostNodes;
    return [
      _WorkflowStep(
        title: '맵 불러오기',
        detail: mapReady
            ? 'Waypoint ${widget.waypoints.length}개'
            : '자리를 고르려면 맵이 먼저 있어야 합니다',
        done: mapReady,
      ),
      _WorkflowStep(
        // 아래 `로봇 등록` 단추와 같은 글자를 쓰지 않는다. 화면에 같은 말이 두
        // 번 나오면 어느 것을 누르라는 말인지 헷갈린다.
        title: '로봇 등록하기',
        detail: registered
            ? '${widget.registeredRobots.length}대 (Gazebo $gazeboRobots대)'
            : '자리 Waypoint 를 함께 고릅니다',
        done: registered,
      ),
      _WorkflowStep(
        title: 'RMF 설정 내보내기',
        detail: exported
            ? '$gazeboRobots대가 launch 에 들어갔습니다'
            : _deployedRobots == null
            ? '아직 안 내보냈습니다'
            : '내보낸 것은 $_deployedRobots대 · 등록은 $gazeboRobots대',
        done: exported,
      ),
      _WorkflowStep(
        title: '백엔드 실행',
        detail: backendUp ? '떠 있습니다' : '마지막에 띄웁니다',
        done: backendUp,
      ),
    ];
  }

  /// 지금 내릴 대상 프로젝트. 확인 창에 그대로 보여 준다.
  List<String> _stopTargets = const [];

  /// 프로세스는 없는데 노드 목록에만 남아 있는 상태.
  ///
  /// 강제 종료된 노드는 DDS 에 떠난다고 알리지 못해 `ros2 node list` 에 십수 초
  /// 남는다(실측 약 16초). 그것을 "떠 있습니다"로 보여 주면 정리가 안 된 줄 안다.
  bool _ghostNodes = false;

  /// 중지한 뒤 실제로 내려갔는지 확인한다.
  ///
  /// **프로세스 목록이 진실이다.** `ros2 node list` 는 강제 종료된 노드를 십수 초
  /// 더 들고 있다(실측 약 16초). DDS 에 떠난다고 알리지 못했기 때문이다. 그것을
  /// 그대로 "떠 있습니다"로 보여 주면 정리가 안 된 줄 안다.
  ///
  /// 그래서 판정은 프로세스로 하고, 노드 목록은 뒤에서 조용히 다시 읽어 화면이
  /// 스스로 맞춰지게 둔다.
  Future<void> _refreshUntilClear() async {
    setState(() {
      _rmfBusy = true;
      _ghostNodes = false;
    });
    final running = await runningBackendProjects();
    if (!mounted) return;
    final processesGone = running.isEmpty;
    var status = await probeRmfRuntime();
    if (!mounted) return;
    setState(() {
      _rmfStatus = status;
      _ghostNodes = processesGone && status.isRunning;
      _rmfBusy = false;
    });
    // 유령이 사라질 때까지 뒤에서 다시 읽는다. 버튼을 막지 않는다.
    for (var attempt = 0; attempt < 12 && status.isRunning; attempt++) {
      await Future<void>.delayed(const Duration(seconds: 3));
      if (!mounted) return;
      status = await probeRmfRuntime();
      if (!mounted) return;
      setState(() {
        _rmfStatus = status;
        _ghostNodes = processesGone && status.isRunning;
      });
    }
  }

  Future<void> _stopRmfBackend() async {
    final running = await runningBackendProjects();
    if (!mounted) return;
    setState(() {
      _stopTargets = {
        if (widget.projectName != null) widget.projectName!,
        ...running,
      }.toList()..sort();
    });
    final confirmed = await showMovableDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        icon: const Icon(Icons.stop_circle_outlined, size: 34),
        title: const Text('Open-RMF 백엔드 중지'),
        content: SizedBox(
          width: 430,
          child: Text(
            '${_stopTargets.isEmpty ? '내릴 프로젝트를 찾지 못했습니다.' : '${_stopTargets.join(', ')} 프로젝트를 내립니다.'}\n\n'
            '떠 있는 노드: ${_rmfStatus.nodes.join(', ')}\n\n'
            '진행 중인 작업이 있으면 함께 끊깁니다.',
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('취소'),
          ),
          FilledButton.icon(
            onPressed: () => Navigator.pop(dialogContext, true),
            icon: const Icon(Icons.stop_circle_outlined, size: 18),
            label: const Text('중지'),
            style: FilledButton.styleFrom(
              backgroundColor: const Color(0xFFDC2626),
            ),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    setState(() => _rmfBusy = true);
    // 디스크의 중지 스크립트를 최신으로 맞춘 뒤 돌린다.
    //
    // 원장은 MySQL 이지만 실제로 도는 것은 디스크의 파일이다. 앱을 고쳐도
    // 내보내기를 안 하면 예전 스크립트가 계속 돌아, 고친 것이 반영되지 않는다.
    await widget.onRefreshScripts();
    if (!mounted) return;
    // 무엇을 띄웠느냐에 따라 내리는 스크립트가 다르다. 예전에는 무조건 office
    // 데모 스크립트만 돌려서, 맵 프로젝트로 띄운 fleet_manager 가 그대로
    // 남았다.
    final result = await stopRmfBackend(mapName: widget.projectName);
    if (!mounted) return;
    setState(() => _rmfBusy = false);
    // 스크립트가 무엇을 내렸는지 그대로 보여 준다. '중지했습니다'만으로는 실제로
    // 정리됐는지 알 수 없다.
    await showWaypointErrorDialog(
      context,
      title: result.success ? 'Open-RMF 백엔드 중지 결과' : '중지 실패',
      message: result.output.isEmpty ? '출력이 없습니다.' : result.output,
    );
    if (!mounted) return;
    await _refreshRmfStatus();
  }

  Widget _rmfStatusCard() {
    final running = _rmfStatus.isRunning;
    final color = running
        ? const Color(0xFFFFFBEB)
        : _rmfStatus.available
        ? const Color(0xFFF0FDF4)
        : const Color(0xFFF1F5F9);
    final border = running
        ? const Color(0xFFFCD34D)
        : _rmfStatus.available
        ? const Color(0xFF86EFAC)
        : const Color(0xFFCBD5E1);
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: color,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: border),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(
            running && !_ghostNodes
                ? Icons.warning_amber_rounded
                : _rmfStatus.available
                ? Icons.check_circle
                : Icons.help_outline,
            color: running && !_ghostNodes
                ? const Color(0xFFD97706)
                : _rmfStatus.available
                ? const Color(0xFF15803D)
                : const Color(0xFF64748B),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  _ghostNodes
                      ? 'Open-RMF 백엔드 · 정리했습니다.'
                      : 'Open-RMF 백엔드 · ${_rmfStatus.message}',
                  style: const TextStyle(fontWeight: FontWeight.w800),
                ),
                if (!running && _rmfStatus.available) ...[
                  const SizedBox(height: 4),
                  Text(
                    widget.projectName == null
                        ? '관제·경로계획을 맡는 ROS 노드입니다. 띄우려면 먼저 '
                              '맵 프로젝트를 열거나 저장하세요.'
                        : '관제·경로계획을 맡는 ROS 노드(schedule · building map '
                              'server · dispatcher)입니다. `${widget.projectName}` '
                              '프로젝트로 띄우면 Gazebo 와 함께 올라옵니다.',
                    style: const TextStyle(
                      fontSize: 12,
                      color: Color(0xFF64748B),
                      height: 1.45,
                    ),
                  ),
                ],
                if (running && _ghostNodes) ...[
                  const SizedBox(height: 4),
                  const Text(
                    '프로세스는 모두 내려갔습니다. 목록에 남은 것은 DDS 가 아직 '
                    '떠난 것을 알아채지 못한 흔적이며 곧 사라집니다.',
                    style: TextStyle(fontSize: 12, color: Color(0xFF15803D)),
                  ),
                ],
                if (running) ...[
                  const SizedBox(height: 6),
                  Text(
                    '떠 있는 노드 ${_rmfStatus.nodes.length}개',
                    style: const TextStyle(
                      fontSize: 12,
                      fontWeight: FontWeight.w700,
                      color: Color(0xFF7C2D12),
                    ),
                  ),
                  const SizedBox(height: 4),
                  // 노드가 서른 개를 넘는다. 그대로 늘어놓으면 카드가 화면을
                  // 넘어가 아래 버튼이 안 보인다. 여기서만 굴린다.
                  ConstrainedBox(
                    constraints: const BoxConstraints(maxHeight: 168),
                    child: Scrollbar(
                      controller: _nodeListScroll,
                      thumbVisibility: true,
                      child: SingleChildScrollView(
                        controller: _nodeListScroll,
                        primary: false,
                        padding: const EdgeInsets.only(right: 12),
                        child: SelectableText(
                          _rmfStatus.nodes.join('\n'),
                          style: const TextStyle(
                            fontSize: 12,
                            height: 1.5,
                            fontFamily: 'monospace',
                            color: Color(0xFF7C2D12),
                          ),
                        ),
                      ),
                    ),
                  ),
                  const SizedBox(height: 4),
                  if (!_ghostNodes)
                    const Text(
                      '실제 로봇·Gazebo 모드로 새로 띄우기 전에 정리하세요.',
                      style: TextStyle(fontSize: 12, color: Color(0xFF92400E)),
                    ),
                ],
              ],
            ),
          ),
          const SizedBox(width: 10),
          if (_rmfBusy)
            const Padding(
              padding: EdgeInsets.symmetric(horizontal: 12, vertical: 8),
              child: SizedBox(
                width: 18,
                height: 18,
                child: CircularProgressIndicator(strokeWidth: 2),
              ),
            )
          else ...[
            OutlinedButton.icon(
              onPressed: _refreshRmfStatus,
              icon: const Icon(Icons.refresh, size: 18),
              label: const Text('다시 확인'),
            ),
            const SizedBox(width: 8),
            // 내리는 버튼만 있고 띄우는 버튼이 없으면, 없다는 것만 알려주고
            // 어떻게 하라는 말은 없는 셈이 된다.
            if (running && !_ghostNodes)
              FilledButton.icon(
                onPressed: _stopRmfBackend,
                icon: const Icon(Icons.stop_circle_outlined, size: 18),
                label: const Text('백엔드 중지'),
                style: FilledButton.styleFrom(
                  backgroundColor: const Color(0xFFDC2626),
                ),
              )
            else
              Column(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  const Text(
                    '버튼을 누르면 설정 저장과 내보내기 후 백엔드를 실행합니다.',
                    style: TextStyle(fontSize: 11, color: Color(0xFF92400E)),
                  ),
                  const SizedBox(height: 5),
                  Tooltip(
                    message: widget.projectName == null
                        ? '먼저 맵 프로젝트를 열거나 저장하세요.'
                        : '설정 저장 → 디스크 내보내기 → 백엔드 실행을 한 번에 수행합니다.',
                    child: FilledButton.icon(
                      onPressed: widget.projectName == null || _rmfBusy
                          ? null
                          : () => unawaited(_startBackend()),
                      icon: const Icon(Icons.play_arrow_rounded, size: 18),
                      label: const Text('백엔드 띄우기'),
                    ),
                  ),
                ],
              ),
          ],
        ],
      ),
    );
  }

  /// 로봇 등록 카드.
  ///
  /// 스폰은 등록된 로봇을 지도에 올리는 일이다. 무엇이 있는지 정하는 곳이 먼저
  /// 있어야 한다. 여기 등록한 로봇이 Gazebo 에 올라가고 fleet adapter 의
  /// `robots` 항목이 된다 — 맵 관리의 RMF 설정 창과 같은 목록이다.
  Widget _registrationCard() {
    final robots = widget.registeredRobots;
    final spawnedIds = {for (final robot in widget.robots) robot.id};
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(16, 14, 16, 14),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0xFFE2E8F0)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.app_registration, size: 20),
              const SizedBox(width: 8),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '로봇 등록 · ${robots.length}대',
                      style: const TextStyle(
                        fontWeight: FontWeight.w800,
                        fontSize: 15,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      widget.projectName == null
                          ? '열린 프로젝트가 없습니다. 등록해도 지금은 앱 안에만 남습니다.'
                          : '`${widget.projectName}` 프로젝트 · 플릿 ${widget.fleetName}'
                                ' — 여기 등록한 로봇이 Gazebo에 올라가고'
                                ' fleet adapter에 들어갑니다.',
                      style: const TextStyle(
                        fontSize: 12,
                        color: Color(0xFF64748B),
                      ),
                    ),
                  ],
                ),
              ),
              // 좌표가 틀려도 화면에서는 티가 안 난다. 문제가 있으면 버튼
              // 자체가 붉어져서 누르기 전에 보이게 한다.
              _SpawnCheckButton(
                checks: widget.spawnChecks,
                onPressed: widget.onCheckSpawns,
              ),
              const SizedBox(width: 6),
              TextButton.icon(
                onPressed: widget.onRegisterFromChargers,
                icon: const Icon(Icons.auto_awesome, size: 18),
                label: const Text('충전 Waypoint에서 만들기'),
              ),
              const SizedBox(width: 6),
              FilledButton.icon(
                onPressed: widget.onRegisterRobot,
                icon: const Icon(Icons.add, size: 18),
                label: const Text('로봇 등록'),
              ),
            ],
          ),
          const SizedBox(height: 10),
          if (robots.isEmpty)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 14),
              child: Text(
                '등록된 로봇이 없습니다. 등록해야 스폰할 수 있습니다.\n'
                '맵에 충전 카테고리 Waypoint를 만들어 두었다면 '
                '`충전 Waypoint에서 만들기`로 한 번에 채울 수 있습니다.',
                style: TextStyle(color: Color(0xFF64748B), height: 1.5),
              ),
            )
          else
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final robot in robots)
                  // 카드를 누르면 그 로봇의 상세가 열린다. 로봇을 눌렀는데
                  // 작업 이야기가 나오면 찾던 것이 아니다.
                  InkWell(
                    onTap: () => widget.onOpenRobot(robot.robotId),
                    borderRadius: BorderRadius.circular(10),
                    child: Container(
                      width: 320,
                      padding: const EdgeInsets.fromLTRB(12, 10, 6, 10),
                      decoration: BoxDecoration(
                        color: const Color(0xFFF8FAFC),
                        borderRadius: BorderRadius.circular(10),
                        border: Border.all(color: const Color(0xFFE2E8F0)),
                      ),
                      child: Row(
                        children: [
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Row(
                                  children: [
                                    Flexible(
                                      child: Text(
                                        '${robot.robotId} · ${robot.displayName}',
                                        overflow: TextOverflow.ellipsis,
                                        style: const TextStyle(
                                          fontWeight: FontWeight.w700,
                                        ),
                                      ),
                                    ),
                                    const SizedBox(width: 6),
                                    // 토픽이 실제로 들어오는지가 배치 여부보다
                                    // 중요하다. 출처를 Gazebo 로 골라 놓고 값이
                                    // 안 오면 화면 숫자는 앱이 계산한 것이다.
                                    if (widget.telemetry.isLive(robot.robotId))
                                      const _RegistrationBadge(
                                        label: '토픽 수신',
                                        color: Color(0xFFEA580C),
                                      )
                                    else if (robot.runsInGazebo)
                                      const _RegistrationBadge(
                                        label: '토픽 없음',
                                        color: Color(0xFFDC2626),
                                      )
                                    else if (spawnedIds.contains(robot.robotId))
                                      const _RegistrationBadge(
                                        label: '배치됨',
                                        color: Color(0xFF16A34A),
                                      )
                                    else
                                      const _RegistrationBadge(
                                        label: '대기',
                                        color: Color(0xFF94A3B8),
                                      ),
                                  ],
                                ),
                                const SizedBox(height: 3),
                                Text(
                                  '${robot.dataSource.label} · '
                                  '${robot.kind.label} · ${robot.model}\n'
                                  '${robot.isMobile ? '충전' : '설비'} '
                                  '${robot.chargerWaypoint ?? '미지정'}'
                                  '${robot.spawnX == null ? '' : ' · spawn '
                                            '${robot.spawnX!.toStringAsFixed(2)}, '
                                            '${robot.spawnY!.toStringAsFixed(2)}'}',
                                  style: const TextStyle(
                                    fontSize: 12,
                                    color: Color(0xFF64748B),
                                    height: 1.4,
                                  ),
                                ),
                              ],
                            ),
                          ),
                          // 이동 로봇만 보낼 수 있다. 설비 로봇에게 보내기를
                          // 내밀면 눌러 보고서야 안 된다는 것을 알게 된다.
                          if (robot.isMobile)
                            IconButton(
                              tooltip: 'Waypoint 로 보내기',
                              visualDensity: VisualDensity.compact,
                              onPressed: () => widget.onSendRobot(robot),
                              icon: const Icon(
                                Icons.near_me_outlined,
                                size: 17,
                                color: Color(0xFF15803D),
                              ),
                            ),
                          IconButton(
                            tooltip: '수정',
                            visualDensity: VisualDensity.compact,
                            onPressed: () =>
                                widget.onEditRegisteredRobot(robot),
                            icon: const Icon(Icons.edit_outlined, size: 17),
                          ),
                          IconButton(
                            tooltip: '등록 해제',
                            visualDensity: VisualDensity.compact,
                            onPressed: () => widget.onUnregisterRobot(robot),
                            icon: const Icon(
                              Icons.delete_outline,
                              size: 17,
                              color: Color(0xFFDC2626),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
              ],
            ),
        ],
      ),
    );
  }

  @override
  // 맵 관리와 같이 화면을 스크롤한다. 예전에는 창에 든 만큼만 쓰고 지도가
  // 남는 자리를 가져갔다. 위쪽 카드(차례·등록·백엔드 상태)가 자리를 다 먹어
  // 지도는 띠처럼 눌렸고, 로봇이 어느 Waypoint 에 서 있는지 알아볼 수 없었다.
  Widget build(BuildContext context) => SingleChildScrollView(
    padding: const EdgeInsets.all(28),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    '로봇 운영',
                    style: Theme.of(context).textTheme.headlineMedium,
                  ),
                  const SizedBox(height: 6),
                  const Text('Gazebo나 RViz 창 없이 앱 지도에서 로봇을 확인할 수 있습니다.'),
                ],
              ),
            ),
            OutlinedButton.icon(
              onPressed: () => _showUsageGuide(context, _UsageGuideTopic.robot),
              icon: const Icon(Icons.help_outline),
              label: const Text('사용법'),
            ),
            const SizedBox(width: 10),
            // 출처는 이제 로봇마다 다르다. 여기서는 지금 어떤 구성인지만
            // 보여 준다. 화면 전체에 하나로 두면 실물 두 대에 Gazebo 한 대
            // 같은 구성을 담을 수 없다.
            for (final source in RobotDataSource.values)
              if (widget.registeredRobots.any((r) => r.dataSource == source))
                Padding(
                  padding: const EdgeInsets.only(right: 6),
                  child: Chip(
                    visualDensity: VisualDensity.compact,
                    label: Text(
                      '${source.shortLabel} '
                      '${widget.registeredRobots.where((r) => r.dataSource == source).length}',
                      style: const TextStyle(fontSize: 12),
                    ),
                  ),
                ),
            const SizedBox(width: 6),
            OutlinedButton.icon(
              onPressed: widget.onLoadMap,
              icon: const Icon(Icons.folder_open_outlined),
              label: const Text('배포 맵 불러오기'),
            ),
            const SizedBox(width: 10),
            Tooltip(
              message: widget.registeredRobots.isEmpty
                  ? '먼저 아래에서 로봇을 등록하세요.'
                  : '등록된 로봇을 앱 지도에 올려 봅니다.',
              child: FilledButton.icon(
                onPressed: widget.registeredRobots.isNotEmpty
                    ? widget.onSpawn
                    : null,
                icon: const Icon(Icons.add_circle_outline),
                label: const Text('로봇 Spawn'),
              ),
            ),
          ],
        ),
        const SizedBox(height: 12),
        // 차례가 맨 위다. 아래 단추들은 이 차례의 각 칸을 누르는 것이다.
        _WorkflowStrip(steps: _workflowSteps),
        const SizedBox(height: 12),
        _registrationCard(),
        const SizedBox(height: 12),
        _rmfStatusCard(),
        const SizedBox(height: 12),
        _MapFileStatus(
          sourceLabel: '불러온 맵',
          sourceName: widget.activeMapSourceName,
          buildingYamlName: widget.activeBuildingYamlName,
          pendingDeployment: widget.pendingDeployment,
        ),
        const SizedBox(height: 18),
        // 지도는 맵 관리와 같은 크기다. 같은 도면을 두 화면에서 보는데 여기서만
        // 작으면 다른 지도처럼 보인다. Spawn 목록도 같이 커져 로봇이 여러 대일
        // 때 스크롤 없이 보인다.
        SizedBox(
          height: mapWorkspaceHeight,
          child: LayoutBuilder(
            builder: (context, constraints) {
              final map = _RobotMapCard(
                drawing: widget.drawing,
                lanes: widget.lanes,
                waypoints: widget.waypoints,
                waypointNames: widget.waypointNames,
                robots: widget.robots,
              );
              final list = _RobotListCard(
                robots: widget.robots,
                onToggle: widget.onToggle,
                onRemove: widget.onRemove,
                onOpenRobot: widget.onOpenRobot,
              );
              if (constraints.maxWidth < 960) {
                return Column(
                  children: [
                    Expanded(child: map),
                    const SizedBox(height: 14),
                    SizedBox(height: 230, child: list),
                  ],
                );
              }
              return Row(
                children: [
                  Expanded(child: map),
                  const SizedBox(width: 18),
                  SizedBox(width: 340, child: list),
                ],
              );
            },
          ),
        ),
      ],
    ),
  );
}

/// 로봇 ID 칸에 못 쓰는 글자가 들어오면 그 자리에서 고친다.
///
/// RMF 는 플릿 로봇마다 `rmf/dynamic_event/begin/<플릿>/<로봇>` 토픽을 만든다.
/// ROS 2 토픽 이름에는 영문·숫자·밑줄만 쓸 수 있어서, 하이픈이 들어가면 로봇을
/// 플릿에 붙이는 순간 fleet adapter 가 죽는다. 다 치고 나서 빨간 글씨로 알리는
/// 것보다 치는 동안 바로잡는 편이 낫다.
class _RobotIdFormatter extends TextInputFormatter {
  @override
  TextEditingValue formatEditUpdate(
    TextEditingValue oldValue,
    TextEditingValue newValue,
  ) {
    final fixed = normalizeRobotId(newValue.text);
    if (fixed == newValue.text) return newValue;
    // 글자 수가 그대로라(한 글자가 한 글자로 바뀐다) 커서를 그 자리에 둔다.
    // 다시 계산하면 하이픈을 칠 때마다 커서가 끝으로 튄다.
    final offset =
        newValue.selection.baseOffset + (fixed.length - newValue.text.length);
    return TextEditingValue(
      text: fixed,
      selection: TextSelection.collapsed(offset: offset.clamp(0, fixed.length)),
    );
  }
}

/// 로봇을 띄우기까지의 차례. 로봇 운영 화면 맨 위에 둔다.
///
/// 순서가 있는 일이다. `ros2 launch` 는 띄울 때 파일을 한 번만 읽으므로, 백엔드를
/// 먼저 띄우면 나중에 등록한 로봇은 그 월드에 없다. 오류도 안 난다 — 다리가
/// 토픽 이름은 만들어 두어서 목록에는 나오고 값만 안 온다. 로봇 0대이던 시절의
/// Gazebo 가 34분째 돌고 있던 일이 그래서 생겼다.
///
/// 그런데 그 차례가 화면 어디에도 없었다. 사람은 눈에 보이는 단추부터 누른다.
class _WorkflowStrip extends StatelessWidget {
  const _WorkflowStrip({required this.steps});

  final List<_WorkflowStep> steps;

  @override
  Widget build(BuildContext context) {
    // 아직 못 한 것 중 가장 앞. 지금 할 일 하나만 짚어 준다.
    final current = steps.indexWhere((step) => !step.done);
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(16, 14, 16, 14),
      decoration: BoxDecoration(
        color: const Color(0xFFF8FAFC),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0xFFCBD5E1)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(
                Icons.format_list_numbered,
                size: 17,
                color: Color(0xFF334155),
              ),
              const SizedBox(width: 6),
              const Text(
                '로봇을 띄우는 차례',
                style: TextStyle(fontWeight: FontWeight.w800, fontSize: 13),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  current < 0 ? '다 되었습니다.' : '지금 할 일 — ${steps[current].title}',
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w700,
                    color: current < 0
                        ? const Color(0xFF15803D)
                        : const Color(0xFFB45309),
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          LayoutBuilder(
            builder: (context, constraints) {
              // 좁으면 세로로 쌓는다. 가로로 밀어 넣으면 글자가 잘려서 정작
              // 무슨 차례인지 안 보인다.
              final vertical = constraints.maxWidth < 900;
              final tiles = [
                for (var i = 0; i < steps.length; i++)
                  _WorkflowTile(
                    index: i + 1,
                    step: steps[i],
                    isCurrent: i == current,
                    expand: !vertical,
                  ),
              ];
              if (vertical) {
                return Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    for (final tile in tiles)
                      Padding(
                        padding: const EdgeInsets.only(bottom: 6),
                        child: tile,
                      ),
                  ],
                );
              }
              return Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  for (var i = 0; i < tiles.length; i++) ...[
                    if (i > 0)
                      const Padding(
                        padding: EdgeInsets.only(top: 6, left: 4, right: 4),
                        child: Icon(
                          Icons.chevron_right,
                          size: 16,
                          color: Color(0xFF94A3B8),
                        ),
                      ),
                    tiles[i],
                  ],
                ],
              );
            },
          ),
          const SizedBox(height: 8),
          const Text(
            '차례를 지켜야 합니다. `ros2 launch` 는 띄울 때 파일을 한 번만 '
            '읽습니다 — 백엔드를 먼저 띄우면 그 뒤에 등록한 로봇은 월드에 '
            '없습니다. 오류도 안 나고 토픽 이름만 보입니다.',
            style: TextStyle(
              fontSize: 11.5,
              color: Color(0xFF64748B),
              height: 1.45,
            ),
          ),
        ],
      ),
    );
  }
}

/// 차례 한 칸.
class _WorkflowStep {
  const _WorkflowStep({
    required this.title,
    required this.detail,
    required this.done,
  });

  final String title;

  /// 지금 어떤 상태인지. 값이 있으면 값을 적는다.
  final String detail;
  final bool done;
}

class _WorkflowTile extends StatelessWidget {
  const _WorkflowTile({
    required this.index,
    required this.step,
    required this.isCurrent,
    required this.expand,
  });

  final int index;
  final _WorkflowStep step;
  final bool isCurrent;
  final bool expand;

  @override
  Widget build(BuildContext context) {
    final color = step.done
        ? const Color(0xFF15803D)
        : isCurrent
        ? const Color(0xFFB45309)
        : const Color(0xFF94A3B8);
    final tile = Row(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Container(
          width: 20,
          height: 20,
          alignment: Alignment.center,
          decoration: BoxDecoration(
            color: step.done ? color : Colors.transparent,
            shape: BoxShape.circle,
            border: Border.all(color: color, width: 1.5),
          ),
          child: step.done
              ? const Icon(Icons.check, size: 13, color: Colors.white)
              : Text(
                  '$index',
                  style: TextStyle(
                    fontSize: 11,
                    fontWeight: FontWeight.w800,
                    color: color,
                  ),
                ),
        ),
        const SizedBox(width: 7),
        Flexible(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                step.title,
                style: TextStyle(
                  fontSize: 12.5,
                  fontWeight: isCurrent ? FontWeight.w800 : FontWeight.w700,
                  color: const Color(0xFF0F172A),
                ),
              ),
              const SizedBox(height: 2),
              Text(
                step.detail,
                style: TextStyle(fontSize: 11.5, color: color, height: 1.35),
              ),
            ],
          ),
        ),
      ],
    );
    return expand ? Expanded(child: tile) : tile;
  }
}

class _RobotMapCard extends StatelessWidget {
  const _RobotMapCard({
    required this.drawing,
    required this.lanes,
    required this.waypoints,
    required this.waypointNames,
    required this.robots,
  });

  final UploadedDrawing? drawing;
  final List<(Offset, Offset)> lanes;
  final List<Offset> waypoints;
  final Map<Offset, String> waypointNames;
  final List<_MockRobot> robots;

  @override
  Widget build(BuildContext context) {
    final current = drawing;
    return Container(
      clipBehavior: Clip.antiAlias,
      decoration: BoxDecoration(
        color: Colors.white,
        border: Border.all(color: const Color(0xFFE2E8F0)),
        borderRadius: BorderRadius.circular(14),
      ),
      child: current?.isImage == true && current!.bytes != null
          ? Stack(
              fit: StackFit.expand,
              children: [
                Padding(
                  padding: const EdgeInsets.all(18),
                  child: Image.memory(current.bytes!, fit: BoxFit.contain),
                ),
                Padding(
                  padding: const EdgeInsets.all(18),
                  child: CustomPaint(
                    painter: _RobotOperationsPainter(
                      sourceSize: Size(
                        current.pixelWidth!.toDouble(),
                        current.pixelHeight!.toDouble(),
                      ),
                      lanes: lanes,
                      waypoints: waypoints,
                      waypointNames: waypointNames,
                      robots: robots,
                    ),
                  ),
                ),
              ],
            )
          : const Center(child: Text('맵 관리에서 이미지 도면과 Lane을 먼저 작성하세요.')),
    );
  }
}

class _RobotListCard extends StatelessWidget {
  const _RobotListCard({
    required this.robots,
    required this.onToggle,
    required this.onRemove,
    required this.onOpenRobot,
  });
  final List<_MockRobot> robots;
  final ValueChanged<_MockRobot> onToggle;
  final ValueChanged<_MockRobot> onRemove;

  /// 로봇 하나의 상세를 연다.
  final ValueChanged<String> onOpenRobot;

  @override
  Widget build(BuildContext context) => Container(
    decoration: BoxDecoration(
      color: Colors.white,
      border: Border.all(color: const Color(0xFFE2E8F0)),
      borderRadius: BorderRadius.circular(14),
    ),
    child: Column(
      children: [
        Padding(
          padding: const EdgeInsets.all(16),
          child: Row(
            children: [
              const Text(
                'Spawn 로봇',
                style: TextStyle(fontWeight: FontWeight.w800),
              ),
              const Spacer(),
              Text('${robots.length}대'),
            ],
          ),
        ),
        const Divider(height: 1),
        Expanded(
          child: robots.isEmpty
              ? const Center(child: Text('Spawn된 로봇이 없습니다.'))
              : ListView.separated(
                  itemCount: robots.length,
                  separatorBuilder: (_, _) => const Divider(height: 1),
                  itemBuilder: (context, index) {
                    final robot = robots[index];
                    return ListTile(
                      // 목록에서 눌러도 그 로봇의 상세가 열린다.
                      onTap: () => onOpenRobot(robot.id),
                      leading: CircleAvatar(
                        backgroundColor: robot.color,
                        foregroundImage: robot.imageBytes == null
                            ? null
                            : MemoryImage(robot.imageBytes!),
                        child: Icon(
                          switch (robot.kind) {
                            _RobotKind.mockMobile => Icons.smart_toy,
                            _RobotKind.pinky => Icons.agriculture,
                            _RobotKind.omxManipulator =>
                              Icons.precision_manufacturing,
                            _RobotKind.mockHumanoid => Icons.accessibility_new,
                            _RobotKind.human => Icons.person,
                          },
                          color: Colors.white,
                          size: 19,
                        ),
                      ),
                      title: Text(
                        robot.id,
                        style: const TextStyle(fontWeight: FontWeight.w700),
                      ),
                      subtitle: Text(
                        '${robot.kind.label} · ${robot.activeTaskId ?? (robot.kind.isMobile ? (robot.moving ? '자율 이동' : '정지') : '고정 설치')}'
                        '${robot.kind.isMobile ? ' · 배터리 ${robot.battery.toStringAsFixed(1)}%' : ''}',
                      ),
                      trailing: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          if (robot.kind.isMobile)
                            IconButton(
                              onPressed: () => onToggle(robot),
                              tooltip: robot.moving ? '정지' : '재개',
                              icon: Icon(
                                robot.moving
                                    ? Icons.pause_circle_outline
                                    : Icons.play_circle_outline,
                              ),
                            ),
                          IconButton(
                            onPressed: () => onRemove(robot),
                            tooltip: '삭제',
                            icon: const Icon(
                              Icons.delete_outline,
                              color: Color(0xFFDC2626),
                            ),
                          ),
                        ],
                      ),
                    );
                  },
                ),
        ),
      ],
    ),
  );
}

class _RobotOperationsPainter extends CustomPainter {
  const _RobotOperationsPainter({
    required this.sourceSize,
    required this.lanes,
    required this.waypoints,
    required this.waypointNames,
    required this.robots,
  });
  final Size sourceSize;
  final List<(Offset, Offset)> lanes;
  final List<Offset> waypoints;
  final Map<Offset, String> waypointNames;
  final List<_MockRobot> robots;

  @override
  void paint(Canvas canvas, Size size) {
    final fitted = applyBoxFit(BoxFit.contain, sourceSize, size).destination;
    final target = Alignment.center.inscribe(fitted, Offset.zero & size);
    Offset convert(Offset point) => Offset(
      target.left + point.dx * target.width / sourceSize.width,
      target.top + point.dy * target.height / sourceSize.height,
    );
    final lanePaint = Paint()
      ..color = const Color(0xAA0891B2)
      ..strokeWidth = 3
      ..strokeCap = StrokeCap.round;
    for (final lane in lanes) {
      canvas.drawLine(convert(lane.$1), convert(lane.$2), lanePaint);
    }
    for (final waypoint in waypoints) {
      canvas.drawCircle(convert(waypoint), 5, Paint()..color = Colors.white);
      canvas.drawCircle(
        convert(waypoint),
        3,
        Paint()..color = const Color(0xFF0891B2),
      );
    }
    final waypointObstacles = [
      for (final waypoint in waypoints)
        Rect.fromCircle(center: convert(waypoint), radius: 9),
      for (final robot in robots)
        Rect.fromCircle(center: convert(robot.position), radius: 18),
    ];
    final occupiedLabels = <Rect>[];
    final canvasBounds = Offset.zero & size;
    for (final waypoint in waypoints) {
      final name = (waypointNames[waypoint] ?? '').trim();
      if (name.isEmpty) continue;
      final center = convert(waypoint);
      final label = TextPainter(
        text: TextSpan(
          text: name,
          style: const TextStyle(
            color: Color(0xFF0F172A),
            fontSize: 10,
            fontWeight: FontWeight.w700,
          ),
        ),
        textDirection: TextDirection.ltr,
        maxLines: 1,
        ellipsis: '…',
      )..layout(maxWidth: 140);
      final labelSize = Size(label.width + 10, label.height + 6);
      final candidates = [
        Rect.fromLTWH(
          center.dx + 11,
          center.dy - labelSize.height / 2,
          labelSize.width,
          labelSize.height,
        ),
        Rect.fromLTWH(
          center.dx - 11 - labelSize.width,
          center.dy - labelSize.height / 2,
          labelSize.width,
          labelSize.height,
        ),
        Rect.fromLTWH(
          center.dx - labelSize.width / 2,
          center.dy - 11 - labelSize.height,
          labelSize.width,
          labelSize.height,
        ),
        Rect.fromLTWH(
          center.dx - labelSize.width / 2,
          center.dy + 11,
          labelSize.width,
          labelSize.height,
        ),
      ];
      bool available(Rect candidate) =>
          canvasBounds.contains(candidate.topLeft) &&
          canvasBounds.contains(candidate.bottomRight) &&
          !occupiedLabels.any((rect) => rect.inflate(3).overlaps(candidate)) &&
          !waypointObstacles.any((rect) => rect.overlaps(candidate));
      int overlapCount(Rect candidate) =>
          occupiedLabels.where((rect) => rect.overlaps(candidate)).length +
          waypointObstacles.where((rect) => rect.overlaps(candidate)).length;
      final labelRect = candidates.firstWhere(
        available,
        orElse: () => candidates.reduce(
          (best, candidate) =>
              overlapCount(candidate) < overlapCount(best) ? candidate : best,
        ),
      );
      occupiedLabels.add(labelRect);
      canvas.drawRRect(
        RRect.fromRectAndRadius(labelRect, const Radius.circular(4)),
        Paint()..color = const Color(0xEFFFFFFF),
      );
      canvas.drawRRect(
        RRect.fromRectAndRadius(labelRect, const Radius.circular(4)),
        Paint()
          ..color = const Color(0x330F172A)
          ..style = PaintingStyle.stroke,
      );
      label.paint(canvas, Offset(labelRect.left + 5, labelRect.top + 3));
    }
    for (final robot in robots) {
      final center = convert(robot.position);
      canvas.drawCircle(center, 16, Paint()..color = const Color(0xCCFFFFFF));
      final robotPaint = Paint()
        ..color = robot.color
        ..strokeWidth = 3
        ..strokeCap = StrokeCap.round;
      if (robot.image != null) {
        final avatarRect = Rect.fromCircle(center: center, radius: 14);
        canvas.save();
        canvas.clipPath(Path()..addOval(avatarRect));
        final image = robot.image!;
        final side = math.min(image.width, image.height).toDouble();
        final sourceRect = Rect.fromCenter(
          center: Offset(image.width / 2, image.height / 2),
          width: side,
          height: side,
        );
        canvas.drawImageRect(image, sourceRect, avatarRect, Paint());
        canvas.restore();
        canvas.drawCircle(
          center,
          14,
          Paint()
            ..color = robot.color
            ..style = PaintingStyle.stroke
            ..strokeWidth = 2,
        );
      } else {
        switch (robot.kind) {
          case _RobotKind.omxManipulator:
            canvas.drawRRect(
              RRect.fromRectAndRadius(
                Rect.fromCenter(center: center, width: 22, height: 22),
                const Radius.circular(4),
              ),
              robotPaint,
            );
            canvas.drawLine(
              center,
              center + const Offset(7, -8),
              Paint()
                ..color = Colors.white
                ..strokeWidth = 3,
            );
          case _RobotKind.mockHumanoid:
            canvas.drawCircle(center - const Offset(0, 7), 5, robotPaint);
            canvas.drawLine(
              center - const Offset(0, 1),
              center + const Offset(0, 8),
              robotPaint,
            );
            canvas.drawLine(
              center + const Offset(0, 2),
              center + const Offset(-7, 5),
              robotPaint,
            );
            canvas.drawLine(
              center + const Offset(0, 2),
              center + const Offset(7, 5),
              robotPaint,
            );
          case _RobotKind.human:
            canvas.drawCircle(
              center - const Offset(0, 7),
              5,
              Paint()..color = const Color(0xFFF6C7A5),
            );
            canvas.drawRRect(
              RRect.fromRectAndRadius(
                Rect.fromCenter(
                  center: center + const Offset(0, 3),
                  width: 13,
                  height: 17,
                ),
                const Radius.circular(5),
              ),
              robotPaint,
            );
            canvas.drawCircle(
              center - const Offset(0, 9),
              5,
              Paint()
                ..color = const Color(0xFF334155)
                ..style = PaintingStyle.stroke
                ..strokeWidth = 2,
            );
          case _RobotKind.pinky:
            canvas.drawRRect(
              RRect.fromRectAndRadius(
                Rect.fromCenter(center: center, width: 25, height: 18),
                const Radius.circular(7),
              ),
              robotPaint,
            );
          case _RobotKind.mockMobile:
            canvas.drawCircle(center, 12, robotPaint);
        }
      }
      final label = TextPainter(
        text: TextSpan(
          text: robot.id,
          style: const TextStyle(
            color: Color(0xFF0F172A),
            fontSize: 11,
            fontWeight: FontWeight.w800,
          ),
        ),
        textDirection: TextDirection.ltr,
      )..layout();
      final rect = Rect.fromLTWH(
        center.dx + 16,
        center.dy - label.height / 2 - 3,
        label.width + 10,
        label.height + 6,
      );
      canvas.drawRRect(
        RRect.fromRectAndRadius(rect, const Radius.circular(5)),
        Paint()..color = const Color(0xEFFFFFFF),
      );
      label.paint(canvas, Offset(rect.left + 5, rect.top + 3));
    }
  }

  @override
  bool shouldRepaint(covariant _RobotOperationsPainter oldDelegate) => true;
}

class _ProcessingWarningPanel extends StatelessWidget {
  const _ProcessingWarningPanel({
    required this.message,
    required this.onDismiss,
  });

  final String message;
  final VoidCallback onDismiss;

  @override
  Widget build(BuildContext context) => Container(
    width: double.infinity,
    padding: const EdgeInsets.all(16),
    decoration: BoxDecoration(
      color: const Color(0xFFFFFBEB),
      border: Border.all(color: const Color(0xFFF59E0B)),
      borderRadius: BorderRadius.circular(12),
    ),
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Icon(Icons.warning_amber_rounded, color: Color(0xFFB45309)),
        const SizedBox(width: 12),
        Expanded(
          child: SelectableText(
            message,
            style: const TextStyle(
              color: Color(0xFF78350F),
              height: 1.5,
              fontWeight: FontWeight.w600,
            ),
          ),
        ),
        const SizedBox(width: 12),
        TextButton.icon(
          onPressed: () async {
            await Clipboard.setData(ClipboardData(text: message));
            if (!context.mounted) return;
            ScaffoldMessenger.of(context).showSnackBar(
              const SnackBar(content: Text('Warning 메시지를 복사했습니다.')),
            );
          },
          icon: const Icon(Icons.copy_rounded, size: 18),
          label: const Text('복사'),
        ),
        IconButton(
          onPressed: onDismiss,
          icon: const Icon(Icons.close_rounded),
          tooltip: 'Warning 닫기',
          color: const Color(0xFF92400E),
        ),
      ],
    ),
  );
}

class _NavigationRail extends StatelessWidget {
  const _NavigationRail({
    required this.selectedIndex,
    required this.onSelected,
  });

  final int selectedIndex;
  final ValueChanged<int> onSelected;

  @override
  Widget build(BuildContext context) {
    // 주요 운영 메뉴는 로봇 등록 → 작업 관리 → ROS2 확인 → 설정 파일
    // 순서로 둔다.
    // 그리드맵은 맵 바로 뒤에 둔다. 도면에서 파생되는 산출물이고, 이것이
    // 없으면 뒤의 로봇·작업이 아예 돌지 않는다.
    const items = [
      (Icons.grid_view_rounded, '대시보드'),
      (Icons.map_outlined, '맵 관리'),
      (Icons.grid_on_outlined, '그리드맵'),
      (Icons.smart_toy_outlined, '로봇 관리'),
      (Icons.model_training_outlined, 'WorkCell 관리'),
      (Icons.assignment_outlined, '작업 관리'),
      (Icons.view_in_ar_outlined, '로봇 모델'),
      (Icons.hub_outlined, 'ROS2 확인'),
      (Icons.description_outlined, '설정 파일'),
      (Icons.receipt_long_outlined, '로그 분석'),
      (Icons.analytics_outlined, '운영 분석'),
      (Icons.difference_outlined, '프로젝트 분석'),
    ];
    return Container(
      width: 224,
      color: const Color(0xFF111827),
      child: SafeArea(
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Padding(
                padding: EdgeInsets.symmetric(horizontal: 10),
                child: Row(
                  children: [
                    _Logo(),
                    SizedBox(width: 12),
                    Expanded(
                      child: FittedBox(
                        fit: BoxFit.scaleDown,
                        alignment: Alignment.centerLeft,
                        child: Text(
                          'ROBOSAPIENS',
                          style: TextStyle(
                            color: Colors.white,
                            fontSize: 16,
                            fontWeight: FontWeight.w800,
                            letterSpacing: 0.8,
                          ),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 24),
              Expanded(
                child: ListView.builder(
                  itemCount: items.length,
                  itemBuilder: (_, i) => InkWell(
                    onTap: () => onSelected(i),
                    borderRadius: BorderRadius.circular(9),
                    child: Padding(
                      padding: const EdgeInsets.only(bottom: 7),
                      child: _NavItem(
                        icon: items[i].$1,
                        label: items[i].$2,
                        selected: i == selectedIndex,
                      ),
                    ),
                  ),
                ),
              ),
              const Divider(color: Color(0xFF273449)),
              const SizedBox(height: 8),
              const _NavItem(icon: Icons.settings_outlined, label: '설정'),
              const SizedBox(height: 16),
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: const Color(0xFF1B2638),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: const Row(
                  children: [
                    CircleAvatar(
                      radius: 17,
                      backgroundColor: Color(0xFF334155),
                      child: Icon(
                        Icons.person,
                        size: 20,
                        color: Colors.white70,
                      ),
                    ),
                    SizedBox(width: 10),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            '관리자',
                            style: TextStyle(
                              color: Colors.white,
                              fontWeight: FontWeight.w600,
                            ),
                          ),
                          Text(
                            'admin@robo.ai',
                            style: TextStyle(
                              color: Color(0xFF94A3B8),
                              fontSize: 11,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _Logo extends StatelessWidget {
  const _Logo();
  @override
  Widget build(BuildContext context) => Container(
    width: 34,
    height: 34,
    decoration: BoxDecoration(
      color: const Color(0xFF2563EB),
      borderRadius: BorderRadius.circular(9),
    ),
    child: const Icon(
      Icons.precision_manufacturing,
      color: Colors.white,
      size: 21,
    ),
  );
}

class _NavItem extends StatelessWidget {
  const _NavItem({
    required this.icon,
    required this.label,
    this.selected = false,
  });
  final IconData icon;
  final String label;
  final bool selected;
  @override
  Widget build(BuildContext context) => Container(
    height: 46,
    padding: const EdgeInsets.symmetric(horizontal: 13),
    decoration: BoxDecoration(
      color: selected ? const Color(0xFF2563EB) : Colors.transparent,
      borderRadius: BorderRadius.circular(9),
    ),
    child: Row(
      children: [
        Icon(
          icon,
          color: selected ? Colors.white : const Color(0xFF94A3B8),
          size: 21,
        ),
        const SizedBox(width: 12),
        Text(
          label,
          style: TextStyle(
            color: selected ? Colors.white : const Color(0xFFCBD5E1),
            fontWeight: FontWeight.w600,
          ),
        ),
      ],
    ),
  );
}

class _TopBar extends StatelessWidget {
  const _TopBar({required this.title});
  final String title;
  @override
  Widget build(BuildContext context) => Container(
    height: 68,
    padding: const EdgeInsets.symmetric(horizontal: 30),
    decoration: const BoxDecoration(
      color: Colors.white,
      border: Border(bottom: BorderSide(color: Color(0xFFE5EAF0))),
    ),
    child: Row(
      children: [
        Text(
          title,
          style: const TextStyle(
            fontWeight: FontWeight.w700,
            color: Color(0xFF334155),
          ),
        ),
        const Spacer(),
        const _StatusDot(),
        const SizedBox(width: 20),
        const Icon(Icons.notifications_none_rounded, color: Color(0xFF64748B)),
        const SizedBox(width: 18),
        const Icon(Icons.help_outline_rounded, color: Color(0xFF64748B)),
      ],
    ),
  );
}

class _StatusDot extends StatelessWidget {
  const _StatusDot();
  @override
  Widget build(BuildContext context) => Row(
    children: [
      Container(
        width: 8,
        height: 8,
        decoration: const BoxDecoration(
          color: Color(0xFF22C55E),
          shape: BoxShape.circle,
        ),
      ),
      const SizedBox(width: 7),
      const Text(
        '시스템 정상',
        style: TextStyle(
          color: Color(0xFF64748B),
          fontSize: 13,
          fontWeight: FontWeight.w600,
        ),
      ),
    ],
  );
}

enum _UsageGuideTopic { map, robot, task }

class _UsageGuideStep {
  const _UsageGuideStep({
    required this.title,
    required this.why,
    required this.actions,
    required this.doneWhen,
    this.caution,
  });

  final String title;
  final String why;
  final List<String> actions;
  final String doneWhen;
  final String? caution;
}

Future<void> _showUsageGuide(
  BuildContext context,
  _UsageGuideTopic topic,
) async {
  final (title, introduction, steps) = switch (topic) {
    _UsageGuideTopic.map => (
      '맵 관리 사용법',
      '맵은 단순한 배경 그림이 아닙니다. 로봇이 이동할 수 있는 공간, 정지할 위치와 '
          '이동 방향을 관제 시스템이 이해할 수 있는 데이터로 만드는 과정입니다. 아래 '
          '순서를 바꾸지 말고 도면부터 배포까지 진행하세요.',
      const [
        _UsageGuideStep(
          title: '도면 업로드와 축척 확인',
          why: '실제 거리와 이미지 픽셀의 관계가 틀리면 로봇 속도, 위치와 안전거리가 모두 틀어집니다.',
          actions: [
            '도면 업로드를 눌러 창고 PNG/JPG/PDF를 선택합니다.',
            '도면 방향과 잘린 영역이 없는지 확인합니다.',
            '측정 도구로 실제 길이를 아는 벽이나 통로를 지정하고 실제 길이를 입력합니다.',
          ],
          doneWhen: '화면의 측정값과 현장 도면의 실제 길이가 일치하면 완료입니다.',
          caution: '사진처럼 기울어진 이미지나 축척을 모르는 도면은 바로 Lane 작성에 사용하지 마세요.',
        ),
        _UsageGuideStep(
          title: 'Wall 검출과 Floor 생성',
          why: 'Wall은 진입하면 안 되는 경계이고 Floor는 이동 가능한 영역입니다. 이후 경로 검증의 기준이 됩니다.',
          actions: [
            'Wall 검출을 실행하고 누락된 벽이나 잘못 검출된 선을 확인합니다.',
            '지우기와 벽 연결 도구로 출입구를 막는 선이나 끊어진 외벽을 수정합니다.',
            'Floor 생성을 눌러 실제 이동 가능한 바닥 영역이 채워지는지 확인합니다.',
          ],
          doneWhen: '벽 바깥이나 선반 내부가 Floor로 잡히지 않고, 실제 통로가 연결되어 있으면 완료입니다.',
          caution: '출입문을 Wall로 막으면 Lane이 있어도 로봇이 통과할 수 없습니다.',
        ),
        _UsageGuideStep(
          title: 'Lane과 Waypoint 작성',
          why: 'Lane은 로봇이 주행할 중심선이고 Waypoint는 출발·도착·대기·충전·픽업 위치입니다.',
          actions: [
            'Lane 만들기를 켜고 통로 중앙에 Waypoint를 순서대로 놓습니다.',
            '교차로, 회전 전후, 픽업 위치와 하차 위치에는 별도 Waypoint를 만듭니다.',
            '시작점을 잡은 뒤 다음 Waypoint를 찍으면 그 지점이 끝점이 되어 Lane이 이어집니다. 계속 찍으면 계속 이어집니다.',
            'Esc를 누르면 현재 레인을 끝냅니다. Waypoint 삭제처럼 다른 작업은 레인을 끝낸 뒤 그 지점을 눌러 선택합니다.',
            'Waypoint 입력 모드를 끄면 기존 Waypoint를 끌어 옮길 수 있습니다. Shift를 누른 채 끌면 가로 또는 세로 한 방향으로만 움직입니다.',
            '대기는 경로상의 정지·통과 지점(holding point), 주차는 작업이 없을 때 로봇을 세워 두는 전용 위치(parking spot)입니다.',
            'Lane을 양방향·정방향·역방향 중 실제 운영 규칙에 맞게 지정합니다.',
            'Lane 설정에서 속도 제한, 정면·후진 자세 제약과 좁은 통로 Mutex 그룹을 필요에 따라 지정합니다.',
            '주차, 충전, 픽업, 드랍오프 Waypoint에 알아보기 쉬운 이름을 부여합니다. 주차는 홈1·홈2처럼 붙이면 로봇 복귀 지점으로 잡힙니다.',
            '고정 로봇팔이나 컨베이어 위치는 설비 Waypoint로 만들고 Lane에는 연결하지 않습니다.',
            '시나리오 맵 자동 완성에서 로봇·Home·충전소·온도대별 픽업·드랍오프 수를 입력하면 기존 Lane 위에 운영 지점을 추천 배치할 수 있습니다.',
          ],
          doneWhen: '모든 운영 위치가 Lane으로 연결되고 이름만 보고 목적을 알 수 있으면 완료입니다.',
          caution: 'Waypoint끼리 Lane 없이 가깝게 놓아도 연결된 것으로 처리되지 않습니다.',
        ),
        _UsageGuideStep(
          title: '오류 검증과 경로 추천 확인',
          why: '화면상으로 자연스러워 보여도 단방향 설정이나 끊어진 Lane 때문에 도달할 수 없는 지점이 생길 수 있습니다.',
          actions: [
            '오류 검증을 눌러 고립된 Waypoint, 이름과 Lane 문제를 확인합니다.',
            '검증은 단방향 왕복 가능성, 중복·벽 교차 Lane과 설정한 로봇 폭·회전 반경 기준도 확인합니다.',
            'Warning의 Waypoint를 찾아 실제로 왕복 가능한 경로가 있는지 확인합니다.',
            '경로 추천은 참고자료로 사용하고 벽, 회전 반경과 일방통행 규칙에 맞게 수정합니다.',
            '수정 후 오류 검증을 다시 실행합니다.',
          ],
          doneWhen: '설명 가능한 Warning만 남고 모든 필수 지점에 도달 가능하면 완료입니다.',
        ),
        _UsageGuideStep(
          title: '저장과 배포',
          why: '작업 저장은 편집을 보존하고, 배포는 RMF와 로봇이 사용할 운영 파일을 생성·설치하는 과정입니다.',
          actions: [
            '작업 저장으로 편집 가능한 프로젝트 파일을 먼저 보존합니다.',
            '다른 이름으로 저장을 사용하면 현재 편집본을 새 맵 이름으로 복제하고 이후 내보내기와 배포에도 그 이름을 사용합니다.',
            '배포를 실행해 building.yaml, 이미지, nav graph와 world를 생성합니다.',
            '배포 로그에서 Map Server와 Fleet Adapter 재시작 및 새 지도 수신을 확인합니다.',
            '로봇 메뉴에서 배포 맵을 다시 불러와 Waypoint와 Lane이 보이는지 확인합니다.',
          ],
          doneWhen: '배포 로그가 성공이고 로봇 메뉴에서 같은 맵을 불러올 수 있으면 완료입니다.',
          caution: '작업 저장과 배포는 다릅니다. 저장만 해서는 실제 관제 맵이 변경되지 않습니다.',
        ),
      ],
    ),
    _UsageGuideTopic.robot => (
      '로봇 운영 사용법',
      '로봇 화면은 운영 맵 위에 장비를 등록하고 현재 위치와 상태를 확인하는 곳입니다. '
          'Spawn은 출발 명령이 아니라 지정 Waypoint에 로봇을 배치하고 관제 대상으로 '
          '등록하는 동작입니다.',
      const [
        _UsageGuideStep(
          title: '배포 맵 불러오기',
          why:
              '로봇과 작업은 동일한 Waypoint 좌표계를 사용해야 합니다. 맵 없이 Spawn하면 위치와 경로를 해석할 수 없습니다.',
          actions: [
            '배포 맵 불러오기를 누릅니다.',
            'nav graph 확인됨 상태인 운영 맵을 선택합니다.',
            '도면, Lane, Waypoint 이름과 현재 운영 맵 이름을 확인합니다.',
          ],
          doneWhen: '로봇 화면에 도면과 Lane, 이름이 표시되면 완료입니다.',
          caution: '운영 중 맵을 교체하면 기존 로봇과 작업의 좌표가 맞지 않을 수 있으므로 다시 등록해야 합니다.',
        ),
        _UsageGuideStep(
          title: '실행 방식 선택',
          why: '앱 Mock, Headless Gazebo와 실제 로봇은 위치를 만드는 주체와 안전 책임이 다릅니다.',
          actions: [
            'UI 확인은 앱 Mock을 선택합니다.',
            '물리 시뮬레이션은 Headless Gazebo와 외부 백엔드를 사용합니다.',
            '실장비는 로컬 Linux Edge Agent와 Fleet Adapter 연결 상태를 먼저 확인합니다.',
          ],
          doneWhen: '시험 목적에 맞는 실행 방식과 백엔드가 준비되면 완료입니다.',
          caution:
              '현재 앱의 직접 Spawn은 Mock 표현입니다. 실제 장비는 전원을 켜고 Edge Agent로 등록해야 합니다.',
        ),
        _UsageGuideStep(
          title: '로봇 유형과 Spawn 위치 선택',
          why: '장비 종류에 따라 이동 가능 여부와 수행할 수 있는 작업이 다르기 때문입니다.',
          actions: [
            'Mock 주행로봇, Pinky, OMX Manipulator 또는 Mock 휴머노이드를 선택합니다.',
            'Human도 작업자 유형으로 선택할 수 있습니다.',
            '캐릭터 이미지 선택으로 각 로봇이나 Human에 표시할 PNG, JPG 또는 WebP 이미지를 지정합니다.',
            '중복되지 않는 이름을 입력합니다.',
            '이동 로봇은 시작 Waypoint, OMX는 고정 설치 Waypoint를 선택합니다.',
            'OMX의 고정 설치 위치에는 Lane이 없는 설비 Waypoint가 우선 표시됩니다.',
            'Spawn 후 선택한 위치에서 정지 상태인지 확인합니다.',
          ],
          doneWhen: '지도와 목록에 올바른 유형·이름·위치로 표시되고 정지 상태이면 완료입니다.',
          caution: 'OMX Manipulator는 고정 장비이므로 Lane을 따라 이동하지 않습니다.',
        ),
        _UsageGuideStep(
          title: '상태 확인과 이동 시작',
          why: '등록 직후 예상하지 않은 이동을 방지하고 작업 전 장비 상태를 확인해야 합니다.',
          actions: [
            '목록에서 연결 상태, 정지 여부, 배터리와 활성 작업을 확인합니다.',
            '수동 확인이 필요할 때만 재개를 눌러 자율 이동을 시작합니다.',
            '업무 이동은 수동 재개보다 작업 메뉴에서 목적지를 배정해 시작합니다.',
            '이상 동작이 있으면 정지를 누르고 작업과 경로를 확인합니다.',
          ],
          doneWhen: '의도한 명령을 받은 로봇만 움직이고 나머지는 정지해 있으면 정상입니다.',
        ),
        _UsageGuideStep(
          title: '실장비 운영 전 확인',
          why: '화면의 아이콘이 정상이어도 실제 센서, 비상정지와 네트워크가 준비되지 않으면 안전하게 운행할 수 없습니다.',
          actions: [
            'Pinky의 비상정지, 라이다, odometry와 배터리를 확인합니다.',
            'OMX-AI의 원점 복귀, 그리퍼와 작업 범위를 확인합니다.',
            'Edge Agent 및 게이트웨이 연결과 연결 끊김 시 안전 정지를 시험합니다.',
            '저속 단일 로봇 시험 후 여러 로봇 작업을 시작합니다.',
          ],
          doneWhen: '통신 단절과 비상정지 시험까지 통과하면 실작업 준비 완료입니다.',
        ),
      ],
    ),
    _UsageGuideTopic.task => (
      '작업 관리 사용법',
      '작업은 단순 목적지 지정이 아니라 Pinky 이동, OMX-AI 적재와 하차를 정해진 '
          '순서로 실행하는 절차입니다. 앞 단계의 성공이 검증되어야 다음 단계가 시작됩니다.',
      const [
        _UsageGuideStep(
          title: '맵과 로봇 준비',
          why: '작업은 맵의 Waypoint와 실제 수행 로봇을 참조하므로 두 항목이 먼저 준비되어야 합니다.',
          actions: [
            '화면의 준비 안내에서 운영 맵이 선택되었는지 확인합니다.',
            'Pinky 또는 Mock 주행로봇이 Spawn되어 정지 중인지 확인합니다.',
            '실제 적재 작업이면 담당 OMX-AI와 픽업 스테이션의 연결 상태를 확인합니다.',
            '로봇이 엉뚱한 곳에 흩어져 있으면 상단 `로봇 원위치`로 Spawn 할 때 고른 Waypoint로 되돌립니다. 진행 중이던 작업은 대기로 돌아가 다시 배차됩니다.',
            '작업 이름 옆 `상세내용`을 누르면 담당 로봇의 현재 위치·주행 여부·배터리와 단계 진행을 실시간으로 볼 수 있습니다. `복사`로 지금 상태를 그대로 가져갈 수 있습니다.',
          ],
          doneWhen: '상단에 작업 준비 완료와 가용 로봇 수가 표시되면 완료입니다.',
        ),
        _UsageGuideStep(
          title: '연속 작업 생성',
          why:
              '이동과 팔 동작을 한 작업에 묶어야 잘못된 위치에서 팔이 움직이거나 적재 전에 로봇이 출발하는 일을 막을 수 있습니다.',
          actions: [
            '새 작업을 누르고 작업자가 구분할 수 있는 이름을 입력합니다.',
            '자동 배정 또는 특정 Pinky를 선택합니다.',
            '단계 추가로 Pinky 이동, OMX-AI 픽업과 대기를 구성합니다.',
            '이동 단계의 지도 핀 버튼을 누른 뒤 오른쪽 운영 맵에서 목적지 Waypoint를 직접 선택합니다.',
            '기존 작업 이름 옆 수정 버튼을 누르면 이름, 로봇과 실행 단계를 변경할 수 있습니다.',
            '작업 이름 옆 삭제 버튼으로 필요 없는 저장 작업을 확인 후 삭제합니다.',
            '작업 이름 옆 실행 버튼을 누르면 저장된 작업을 가용 로봇에 즉시 배정합니다.',
            '생성·수정한 작업은 MySQL에 보존되며 앱을 다시 열어도 목록과 변경 이력을 확인할 수 있습니다.',
            '편집기의 저장은 실행하지 않고 대기 작업으로 보존하며, 저장 후 시작은 즉시 로봇에 배정합니다.',
            '카드를 끌어 실제 실행 순서대로 배치하고 필요 없는 단계는 삭제합니다.',
          ],
          doneWhen: '작업 이름, 수행 로봇과 모든 단계의 목적지가 지정되면 시작할 수 있습니다.',
        ),
        _UsageGuideStep(
          title: '권장 주문 작업 순서',
          why: '로봇 도착과 적재 성공을 각각 확인해야 상품 누락과 빈 차 출발을 방지할 수 있습니다.',
          actions: [
            '1단계: Pinky를 주문 온도에 맞는 픽업 Waypoint로 이동시킵니다.',
            '2단계: Pinky가 정지한 뒤 OMX-AI 픽업/적재를 실행합니다.',
            '3단계: 적재 성공 후 Pinky를 하차 Waypoint로 이동시킵니다.',
            '필요하면 작업자 확인이나 설비 동작을 위한 대기 단계를 추가합니다.',
          ],
          doneWhen: '픽업 이동 → 적재 → 하차 이동 순서가 명확하면 완료입니다.',
          caution: 'OMX-AI 성공 전에 하차 이동을 시작하도록 순서를 만들지 마세요.',
        ),
        _UsageGuideStep(
          title: '실행 상태와 오류 확인',
          why: '진행 중인 단계와 실패 위치를 알아야 재시도 여부와 현장 조치를 안전하게 결정할 수 있습니다.',
          actions: [
            '목록에서 완료 단계 수와 현재 활성 단계를 확인합니다.',
            '경로 없음은 맵의 Lane 연결과 방향을 먼저 확인합니다.',
            '적재 실패는 상품, 로봇 ID, 정지 위치, OMX 그리퍼 상태를 확인합니다.',
            '원인을 모르는 상태에서는 반복 시작하지 말고 작업을 취소한 뒤 현장을 확인합니다.',
          ],
          doneWhen: '모든 단계가 완료되고 로봇이 최종 Waypoint에서 정지하면 운반 단계가 완료된 것입니다.',
        ),
        _UsageGuideStep(
          title: '실제 주문 완료 판단',
          why: '로봇이 하차 지점에 도착한 것과 주문 상품이 실제 인계된 것은 서로 다른 사건입니다.',
          actions: [
            '작업자 확인, 자동 하차 설비 응답 또는 데크 센서로 상품 인수를 확인합니다.',
            '인수 완료 후 주문 상태와 재고 이력을 완료 처리합니다.',
            '취소·실패 작업은 적재된 상품과 예약 재고 상태를 반드시 대조합니다.',
          ],
          doneWhen: '상품 인수와 재고 반영까지 확인되어야 주문 전체가 완료입니다.',
          caution: '현재 앱 Mock 엔진의 완료 표시는 실제 상품 인수 증명이 아닙니다.',
        ),
      ],
    ),
  };

  await showMovableDialog<void>(
    context: context,
    builder: (dialogContext) => AlertDialog(
      icon: const Icon(Icons.menu_book_outlined, size: 38),
      title: Text(title),
      content: SizedBox(
        width: 780,
        height: 650,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(
                color: const Color(0xFFEFF6FF),
                borderRadius: BorderRadius.circular(10),
                border: Border.all(color: const Color(0xFFBFDBFE)),
              ),
              child: Text(
                introduction,
                style: const TextStyle(height: 1.55, color: Color(0xFF1E3A8A)),
              ),
            ),
            const SizedBox(height: 14),
            Expanded(
              child: ListView.separated(
                itemCount: steps.length,
                separatorBuilder: (_, _) => const SizedBox(height: 12),
                itemBuilder: (context, index) {
                  final step = steps[index];
                  return Container(
                    padding: const EdgeInsets.all(16),
                    decoration: BoxDecoration(
                      color: Colors.white,
                      borderRadius: BorderRadius.circular(12),
                      border: Border.all(color: const Color(0xFFE2E8F0)),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            CircleAvatar(
                              radius: 15,
                              backgroundColor: const Color(0xFF2563EB),
                              foregroundColor: Colors.white,
                              child: Text('${index + 1}'),
                            ),
                            const SizedBox(width: 10),
                            Expanded(
                              child: Text(
                                step.title,
                                style: const TextStyle(
                                  fontSize: 16,
                                  fontWeight: FontWeight.w800,
                                ),
                              ),
                            ),
                          ],
                        ),
                        const SizedBox(height: 10),
                        Text(
                          '왜 필요한가: ${step.why}',
                          style: const TextStyle(height: 1.45),
                        ),
                        const SizedBox(height: 9),
                        for (
                          var actionIndex = 0;
                          actionIndex < step.actions.length;
                          actionIndex++
                        )
                          Padding(
                            padding: const EdgeInsets.only(bottom: 5),
                            child: Text(
                              '${actionIndex + 1}) ${step.actions[actionIndex]}',
                              style: const TextStyle(height: 1.4),
                            ),
                          ),
                        const SizedBox(height: 6),
                        Text(
                          '완료 기준: ${step.doneWhen}',
                          style: const TextStyle(
                            color: Color(0xFF15803D),
                            fontWeight: FontWeight.w700,
                            height: 1.4,
                          ),
                        ),
                        if (step.caution != null) ...[
                          const SizedBox(height: 7),
                          Text(
                            '주의: ${step.caution}',
                            style: const TextStyle(
                              color: Color(0xFFB45309),
                              fontWeight: FontWeight.w700,
                              height: 1.4,
                            ),
                          ),
                        ],
                      ],
                    ),
                  );
                },
              ),
            ),
          ],
        ),
      ),
      actions: [
        TextButton.icon(
          onPressed: () async {
            final plainText = StringBuffer('$title\n\n$introduction\n');
            for (var index = 0; index < steps.length; index++) {
              final step = steps[index];
              plainText
                ..writeln('\n${index + 1}. ${step.title}')
                ..writeln('왜 필요한가: ${step.why}');
              for (
                var actionIndex = 0;
                actionIndex < step.actions.length;
                actionIndex++
              ) {
                plainText.writeln(
                  '  ${actionIndex + 1}) ${step.actions[actionIndex]}',
                );
              }
              plainText.writeln('완료 기준: ${step.doneWhen}');
              if (step.caution != null) {
                plainText.writeln('주의: ${step.caution}');
              }
            }
            await Clipboard.setData(ClipboardData(text: plainText.toString()));
            if (!dialogContext.mounted) return;
            ScaffoldMessenger.of(
              dialogContext,
            ).showSnackBar(const SnackBar(content: Text('사용법 전체 내용을 복사했습니다.')));
          },
          icon: const Icon(Icons.copy_outlined),
          label: const Text('전체 복사'),
        ),
        FilledButton(
          onPressed: () => Navigator.pop(dialogContext),
          child: const Text('확인'),
        ),
      ],
    ),
  );
}

enum _ExportAction { download, copy }

class _PageHeading extends StatelessWidget {
  const _PageHeading({
    required this.onHelp,
    required this.onUpload,
    required this.exportEnabled,
    required this.onValidate,
    required this.onRecommend,
    required this.onDownload,
    required this.onCopy,
    required this.onSaveProject,
    required this.onSaveProjectAs,
    required this.onLoadProject,
    required this.onSaveToDatabase,
    required this.onOpenFromDatabase,
    required this.onNewProject,
    required this.onRmfConfig,
  });
  final VoidCallback onHelp;
  final VoidCallback onUpload;
  final bool exportEnabled;
  final VoidCallback onValidate;
  final VoidCallback onRecommend;
  final VoidCallback onDownload;
  final VoidCallback onCopy;
  final VoidCallback onSaveProject;
  final VoidCallback onSaveProjectAs;
  final VoidCallback onLoadProject;
  final VoidCallback onSaveToDatabase;
  final VoidCallback onOpenFromDatabase;

  /// 이름을 먼저 받아 빈 프로젝트를 만든다.
  final VoidCallback onNewProject;

  /// 프로젝트별 RMF 플릿 설정과 생성된 설정 파일을 본다.
  final VoidCallback onRmfConfig;
  @override
  Widget build(BuildContext context) => Row(
    crossAxisAlignment: CrossAxisAlignment.center,
    children: [
      Expanded(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              '새 창고 맵 만들기',
              style: Theme.of(context).textTheme.headlineMedium,
            ),
            const SizedBox(height: 7),
            const Text('도면을 불러오면 이동 경로와 로봇 운영 지점을 빠르게 설정할 수 있습니다.'),
          ],
        ),
      ),
      // 버튼이 열 개에 가까워 좁은 창에서는 한 줄에 들어가지 않는다. Row 에
      // 그대로 늘어놓으면 폭이 모자란 순간 오른쪽이 잘려 나가므로, 모자라면
      // 다음 줄로 접히도록 Wrap 에 담는다.
      Flexible(
        child: Wrap(
          alignment: WrapAlignment.end,
          crossAxisAlignment: WrapCrossAlignment.center,
          spacing: 8,
          runSpacing: 8,
          children: [
            OutlinedButton.icon(
              onPressed: onHelp,
              icon: const Icon(Icons.help_outline, size: 18),
              label: const Text('사용법'),
              style: OutlinedButton.styleFrom(
                padding: const EdgeInsets.symmetric(
                  horizontal: 15,
                  vertical: 16,
                ),
              ),
            ),
            // 맵 프로젝트의 원장은 MySQL이다. 프로젝트 이름으로 구분해 담으므로
            // 이 세 버튼이 여러 창고를 오가는 기본 경로다. 파일 저장·불러오기는
            // rmf_control_ui/project 한 곳에서만 하는 보조 수단이다. 사용자가
            // 폴더를 고르게 하면 같은 이름의 파일이 여러 곳에 흩어진다.
            //
            // `새 프로젝트` 가 맨 앞이다. 이름을 먼저 정하고 도면을 올리는 것이
            // 제 차례다 — 도면부터 올리면 그 파일 이름이 프로젝트 이름으로
            // 굳어 버리는 것이 예전 문제였다.
            OutlinedButton.icon(
              onPressed: onNewProject,
              icon: const Icon(Icons.create_new_folder_outlined, size: 18),
              label: const Text('새 프로젝트'),
              style: OutlinedButton.styleFrom(
                padding: const EdgeInsets.symmetric(
                  horizontal: 15,
                  vertical: 16,
                ),
              ),
            ),
            FilledButton.icon(
              onPressed: onOpenFromDatabase,
              icon: const Icon(Icons.storage_outlined, size: 18),
              label: const Text('프로젝트 열기'),
              style: FilledButton.styleFrom(
                padding: const EdgeInsets.symmetric(
                  horizontal: 15,
                  vertical: 16,
                ),
              ),
            ),
            OutlinedButton.icon(
              onPressed: onRmfConfig,
              icon: const Icon(Icons.settings_ethernet, size: 18),
              label: const Text('RMF 설정'),
              style: OutlinedButton.styleFrom(
                padding: const EdgeInsets.symmetric(
                  horizontal: 15,
                  vertical: 16,
                ),
              ),
            ),
            FilledButton.icon(
              onPressed: exportEnabled ? onSaveToDatabase : null,
              icon: const Icon(Icons.cloud_upload_outlined, size: 18),
              label: const Text('프로젝트 저장'),
              style: FilledButton.styleFrom(
                padding: const EdgeInsets.symmetric(
                  horizontal: 15,
                  vertical: 16,
                ),
              ),
            ),
            OutlinedButton.icon(
              onPressed: onLoadProject,
              icon: const Icon(Icons.folder_open_outlined, size: 18),
              label: const Text('project에서 열기'),
              style: OutlinedButton.styleFrom(
                padding: const EdgeInsets.symmetric(
                  horizontal: 15,
                  vertical: 16,
                ),
              ),
            ),
            OutlinedButton.icon(
              onPressed: exportEnabled ? onSaveProject : null,
              icon: const Icon(Icons.save_outlined, size: 18),
              label: const Text('project에 저장'),
              style: OutlinedButton.styleFrom(
                padding: const EdgeInsets.symmetric(
                  horizontal: 15,
                  vertical: 16,
                ),
              ),
            ),
            OutlinedButton.icon(
              onPressed: exportEnabled ? onSaveProjectAs : null,
              icon: const Icon(Icons.save_as_outlined, size: 18),
              label: const Text('다른 이름으로 저장'),
              style: OutlinedButton.styleFrom(
                padding: const EdgeInsets.symmetric(
                  horizontal: 15,
                  vertical: 16,
                ),
              ),
            ),
            OutlinedButton.icon(
              onPressed: exportEnabled ? onValidate : null,
              icon: const Icon(Icons.fact_check_outlined, size: 18),
              label: const Text('오류 검증'),
              style: OutlinedButton.styleFrom(
                padding: const EdgeInsets.symmetric(
                  horizontal: 15,
                  vertical: 16,
                ),
              ),
            ),
            OutlinedButton.icon(
              onPressed: exportEnabled ? onRecommend : null,
              icon: const Icon(Icons.auto_awesome_outlined, size: 18),
              label: const Text('경로 추천'),
              style: OutlinedButton.styleFrom(
                padding: const EdgeInsets.symmetric(
                  horizontal: 15,
                  vertical: 16,
                ),
              ),
            ),
            PopupMenuButton<_ExportAction>(
              enabled: exportEnabled,
              onSelected: (action) {
                if (action == _ExportAction.download) {
                  onDownload();
                } else {
                  onCopy();
                }
              },
              itemBuilder: (context) => const [
                PopupMenuItem(
                  value: _ExportAction.download,
                  child: ListTile(
                    contentPadding: EdgeInsets.zero,
                    leading: Icon(Icons.download_outlined),
                    title: Text('파일 다운로드'),
                    subtitle: Text('.building.yaml로 저장'),
                  ),
                ),
                PopupMenuItem(
                  value: _ExportAction.copy,
                  child: ListTile(
                    contentPadding: EdgeInsets.zero,
                    leading: Icon(Icons.content_copy_outlined),
                    title: Text('YAML 복사'),
                    subtitle: Text('클립보드에 내용 복사'),
                  ),
                ),
              ],
              child: Container(
                padding: const EdgeInsets.symmetric(
                  horizontal: 17,
                  vertical: 14,
                ),
                decoration: BoxDecoration(
                  color: exportEnabled ? Colors.white : const Color(0xFFF1F5F9),
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(color: const Color(0xFFCBD5E1)),
                ),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(
                      Icons.download_outlined,
                      size: 19,
                      color: exportEnabled
                          ? const Color(0xFF334155)
                          : const Color(0xFF94A3B8),
                    ),
                    const SizedBox(width: 8),
                    Text(
                      '맵 다운로드',
                      style: TextStyle(
                        color: exportEnabled
                            ? const Color(0xFF334155)
                            : const Color(0xFF94A3B8),
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    const SizedBox(width: 5),
                    const Icon(Icons.arrow_drop_down, size: 18),
                  ],
                ),
              ),
            ),
            FilledButton.icon(
              onPressed: onUpload,
              icon: const Icon(Icons.upload_file_rounded, size: 19),
              label: const Text('도면 올리기'),
              style: FilledButton.styleFrom(
                padding: const EdgeInsets.symmetric(
                  horizontal: 20,
                  vertical: 17,
                ),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(10),
                ),
              ),
            ),
          ],
        ),
      ),
    ],
  );
}

/// 작업과 담당 로봇의 상태를 실시간으로 보여 주는 팝업.
///
/// 부모 화면이 다시 그려져도 팝업은 따라 그려지지 않으므로 자기 타이머로
/// 갱신한다. 작업·로봇 객체는 제자리에서 값이 바뀌므로 매번 읽으면 최신이다.
class _TaskDetailDialog extends StatefulWidget {
  const _TaskDetailDialog({
    required this.task,
    required this.robotOf,
    required this.toFloor,
    required this.metersPerPixel,
    required this.waypointLabel,
    required this.dataSource,
    required this.topicsConnected,
    required this.registeredRobot,
  });

  final _MockTask task;
  final _MockRobot? Function(String robotId) robotOf;
  final Offset Function(Offset point) toFloor;
  final double? metersPerPixel;
  final String Function(Offset point) waypointLabel;

  /// 고른 실행 방식. 이것을 모르면 Mock 을 실물로 착각한다.
  final RobotDataSource dataSource;

  /// 그 방식의 토픽을 실제로 구독하고 있는가.
  ///
  /// 방식을 고르는 것과 값이 실제로 들어오는 것은 다르다. Gazebo 를 골라 놓고
  /// 구독은 아직 없으면, 화면의 숫자는 여전히 앱이 계산한 값이다. 그 사실을
  /// 감추면 이 띠가 거짓말을 하게 된다.
  final bool topicsConnected;

  /// 이 작업을 맡은 로봇의 등록 정보. 토픽 이름을 여기서 가져온다.
  final RmfProjectRobot? registeredRobot;

  @override
  State<_TaskDetailDialog> createState() => _TaskDetailDialogState();
}

class _TaskDetailDialogState extends State<_TaskDetailDialog> {
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    // 로봇 주행은 100ms 주기로 움직인다. 그보다 조금 느리게 읽어도 흐름을
    // 보는 데는 충분하고 다시 그리는 비용이 줄어든다.
    _timer = Timer.periodic(
      const Duration(milliseconds: 200),
      (_) => setState(() {}),
    );
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  String _point(Offset point) {
    final floor = widget.toFloor(point);
    final pixels =
        'X ${floor.dx.toStringAsFixed(1)} · Y ${floor.dy.toStringAsFixed(1)} px';
    final scale = widget.metersPerPixel;
    if (scale == null || scale <= 0) return pixels;
    return '$pixels  ('
        '${(floor.dx * scale).toStringAsFixed(2)} · '
        '${(floor.dy * scale).toStringAsFixed(2)} m)';
  }

  String _stepLabel(_MockTaskStep step) => switch (step.type) {
    _TaskStepType.navigate => '이동',
    _TaskStepType.returnHome => '홈 복귀',
    _TaskStepType.armLoad => '로봇팔 적재',
    _TaskStepType.wait => '대기',
  };

  String _stepStatus(_TaskStepStatus status) => switch (status) {
    _TaskStepStatus.pending => '대기',
    _TaskStepStatus.active => '진행 중',
    _TaskStepStatus.completed => '완료',
    _TaskStepStatus.failed => '실패',
    _TaskStepStatus.cancelled => '취소',
  };

  /// 화면에 뿌리는 것과 같은 내용을 글로 만든다. 복사해서 붙일 수 있어야 한다.
  String _asText(_MockRobot? robot) {
    final task = widget.task;
    final topics = robotTopics(widget.registeredRobot);
    final source = _effectiveSource;
    final lines = <String>[
      '[출처] ${source.label} — ${source.summary}',
      if (source.usesTopics && topics.incoming.isNotEmpty)
        '  받기 ${topics.incoming.join(', ')}',
      if (source.usesTopics && topics.outgoing.isNotEmpty)
        '  보내기 ${topics.outgoing.join(', ')}',
      if (_sourceMismatch)
        '  주의 실행 방식은 ${widget.dataSource.label}로 골랐지만 아직 그 토픽을 '
            '구독하지 않습니다. 아래 값은 앱이 계산한 것입니다.',
      '',
      '작업 ${task.name} (${task.id})',
      '상태 ${task.status.name} · 긴급도 ${task.urgency.label} · '
          '단계 ${task.currentStepIndex}/${task.steps.length}',
      '담당 로봇 ${task.robotId}',
      if (robot == null)
        '로봇 상태를 읽을 수 없습니다 (Spawn 되지 않았거나 이름이 다릅니다).'
      else ...[
        '위치 ${_point(robot.position)}',
        '이동 ${robot.moving ? '주행 중' : '정지'} · 배터리 '
            '${robot.battery.toStringAsFixed(1)}%',
        '목표 ${robot.targetWaypoint == null ? '없음' : widget.waypointLabel(robot.targetWaypoint!)}',
        '남은 경로 ${robot.assignedRoute.length}개 지점',
      ],
      '',
      for (var i = 0; i < task.steps.length; i++)
        '${i + 1}. ${_stepLabel(task.steps[i])} '
            '${task.steps[i].destinationName ?? '-'} · '
            '${_stepStatus(task.steps[i].status)}'
            '${task.steps[i].type.isMovement ? '' : ' · 남은 ${task.steps[i].remainingSeconds.toStringAsFixed(1)}s'}'
            '${task.steps[i].failureReason == null ? '' : ' · ${task.steps[i].failureReason}'}',
    ];
    return lines.join('\n');
  }

  /// 아래 숫자를 실제로 만들어 낸 곳.
  ///
  /// 방식을 Gazebo 로 골라도 구독이 없으면 값은 여전히 앱이 계산한 것이다.
  RobotDataSource get _effectiveSource => effectiveDataSource(
    selected: widget.dataSource,
    topicsConnected: widget.topicsConnected,
  );

  /// 고른 방식과 실제 값의 출처가 어긋나 있는가.
  bool get _sourceMismatch => dataSourceMismatch(
    selected: widget.dataSource,
    topicsConnected: widget.topicsConnected,
  );

  /// 값의 출처를 크게 세운 띠.
  ///
  /// 앱이 계산한 값과 실물에서 온 값이 같은 자리에 같은 모양으로 보인다.
  /// 어느 쪽인지 한눈에 들어오지 않으면 Mock 주행을 실제 상태로 착각한다.
  Widget _sourceBanner() {
    final source = _effectiveSource;
    final topics = robotTopics(widget.registeredRobot);
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
      decoration: BoxDecoration(
        color: source.color.withValues(alpha: .10),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: source.color, width: 2),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(source.icon, color: source.color, size: 30),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  source.label,
                  style: TextStyle(
                    color: source.color,
                    fontSize: 22,
                    fontWeight: FontWeight.w900,
                    letterSpacing: -.5,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 6),
          Text(
            source.summary,
            style: TextStyle(
              color: source.color,
              fontSize: 13,
              fontWeight: FontWeight.w600,
              height: 1.4,
            ),
          ),
          if (source.usesTopics) ...[
            const SizedBox(height: 8),
            if (widget.registeredRobot == null)
              Text(
                '이 로봇의 등록 정보가 없어 토픽 이름을 알 수 없습니다.',
                style: TextStyle(color: source.color, fontSize: 12),
              )
            else ...[
              _topicLine('받기', topics.incoming, source.color),
              if (topics.outgoing.isNotEmpty)
                _topicLine('보내기', topics.outgoing, source.color),
            ],
          ],
          // 고른 방식과 실제 출처가 다르면 반드시 밝힌다. 감추면 이 띠가
          // 거짓말이 된다.
          if (_sourceMismatch) ...[
            const SizedBox(height: 8),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(8),
              decoration: BoxDecoration(
                color: source.color.withValues(alpha: .14),
                borderRadius: BorderRadius.circular(6),
              ),
              child: Text(
                '실행 방식은 `${widget.dataSource.label}`로 골라 두었지만 '
                '앱이 아직 그 토픽을 구독하지 않습니다.\n'
                '지금 보이는 값은 앱이 계산한 것입니다.',
                style: TextStyle(
                  color: source.color,
                  fontSize: 12,
                  fontWeight: FontWeight.w700,
                  height: 1.4,
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }

  Widget _topicLine(String label, List<String> topics, Color color) => Padding(
    padding: const EdgeInsets.only(top: 2),
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(
          width: 46,
          child: Text(
            label,
            style: TextStyle(
              color: color,
              fontSize: 12,
              fontWeight: FontWeight.w800,
            ),
          ),
        ),
        Expanded(
          child: SelectableText(
            topics.join('  ·  '),
            style: TextStyle(
              color: color,
              fontSize: 12,
              fontFamily: 'monospace',
            ),
          ),
        ),
      ],
    ),
  );

  Widget _row(String label, String value) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 3),
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(
          width: 92,
          child: Text(
            label,
            style: const TextStyle(
              color: Color(0xFF64748B),
              fontWeight: FontWeight.w700,
            ),
          ),
        ),
        Expanded(child: SelectableText(value)),
      ],
    ),
  );

  @override
  Widget build(BuildContext context) {
    final task = widget.task;
    final robot = widget.robotOf(task.robotId);
    final step = task.currentStep;
    return AlertDialog(
      title: Row(
        children: [
          const Icon(Icons.monitor_heart_outlined, color: Color(0xFF2563EB)),
          const SizedBox(width: 10),
          Expanded(child: Text('${task.name} 상세')),
        ],
      ),
      content: SizedBox(
        width: 560,
        height: 520,
        child: SingleChildScrollView(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _sourceBanner(),
              const SizedBox(height: 14),
              _row('작업 상태', '${task.status.name} · 긴급도 ${task.urgency.label}'),
              _row('진행', '${task.currentStepIndex}/${task.steps.length} 단계'),
              _row(
                '현재 단계',
                step == null
                    ? '없음'
                    : '${_stepLabel(step)} ${step.destinationName ?? ''} · '
                          '${_stepStatus(step.status)}'
                          '${step.type.isMovement ? '' : ' · 남은 ${step.remainingSeconds.toStringAsFixed(1)}s'}',
              ),
              const Divider(height: 22),
              _row('로봇', task.robotId),
              if (robot == null)
                _row('상태', 'Spawn 되지 않았거나 이름이 다릅니다.')
              else ...[
                _row('현재 위치', _point(robot.position)),
                _row('주행', robot.moving ? '주행 중' : '정지'),
                _row('배터리', '${robot.battery.toStringAsFixed(1)}%'),
                _row(
                  '목표 지점',
                  robot.targetWaypoint == null
                      ? '없음'
                      : widget.waypointLabel(robot.targetWaypoint!),
                ),
                _row('남은 경로', '${robot.assignedRoute.length}개 지점'),
              ],
              const Divider(height: 22),
              const Align(
                alignment: Alignment.centerLeft,
                child: Text(
                  '단계 진행',
                  style: TextStyle(fontWeight: FontWeight.w800),
                ),
              ),
              const SizedBox(height: 6),
              for (var i = 0; i < task.steps.length; i++)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 2),
                  child: Row(
                    children: [
                      Icon(
                        switch (task.steps[i].status) {
                          _TaskStepStatus.completed => Icons.check_circle,
                          _TaskStepStatus.active => Icons.play_circle_fill,
                          _TaskStepStatus.failed => Icons.error,
                          _ => Icons.radio_button_unchecked,
                        },
                        size: 16,
                        color: switch (task.steps[i].status) {
                          _TaskStepStatus.completed => const Color(0xFF15803D),
                          _TaskStepStatus.active => const Color(0xFF2563EB),
                          _TaskStepStatus.failed => const Color(0xFFDC2626),
                          _ => const Color(0xFF94A3B8),
                        },
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text(
                          '${i + 1}. ${_stepLabel(task.steps[i])} '
                          '${task.steps[i].destinationName ?? '-'}'
                          '${task.steps[i].failureReason == null ? '' : ' · ${task.steps[i].failureReason}'}',
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                    ],
                  ),
                ),
              const SizedBox(height: 12),
              Text(
                widget.dataSource == RobotDataSource.mock
                    ? '앱 Mock 주행이 계산한 값입니다. 실제 로봇의 ROS 토픽은 아직 '
                          '연결되지 않았습니다.'
                    : '${_effectiveSource.label}에서 오는 값입니다. '
                          '토픽이 끊기면 값이 멈춘 채로 남습니다.',
                style: const TextStyle(color: Color(0xFF64748B), fontSize: 12),
              ),
            ],
          ),
        ),
      ),
      actions: [
        TextButton.icon(
          onPressed: () async {
            await Clipboard.setData(ClipboardData(text: _asText(robot)));
            if (!context.mounted) return;
            ScaffoldMessenger.of(context).showSnackBar(
              const SnackBar(content: Text('현재 상태를 클립보드에 복사했습니다.')),
            );
          },
          icon: const Icon(Icons.content_copy_outlined, size: 18),
          label: const Text('복사'),
        ),
        FilledButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('닫기'),
        ),
      ],
    );
  }
}

/// Waypoint를 찍다 생긴 오류를 복사·크기 조절이 되는 팝업으로 보여 준다.
Future<void> showWaypointErrorDialog(
  BuildContext context, {
  required String title,
  required String message,
}) => showMovableDialog<void>(
  context: context,
  builder: (_) => _CopyableErrorDialog(title: title, message: message),
);

/// 본문을 복사할 수 있고 크기를 조절할 수 있는 오류 팝업.
///
/// 오류 문구에 좌표·거리·축척 같은 수치가 들어가면 길어진다. 스낵바로는 다
/// 읽기 전에 사라지고 옮겨 적을 수도 없어서, 닫을 때까지 남고 통째로 복사할 수
/// 있는 팝업으로 보여 준다. 문구가 길면 오른쪽 아래 모서리를 끌어 넓힌다.
class _CopyableErrorDialog extends StatefulWidget {
  const _CopyableErrorDialog({required this.title, required this.message});

  final String title;
  final String message;

  @override
  State<_CopyableErrorDialog> createState() => _CopyableErrorDialogState();
}

class _CopyableErrorDialogState extends State<_CopyableErrorDialog> {
  static const double _minWidth = 320;
  static const double _minHeight = 140;

  double _width = 520;
  double _height = 240;

  @override
  Widget build(BuildContext context) {
    final screen = MediaQuery.of(context).size;
    // 팝업이 화면을 넘어가면 끌어서 되돌릴 수도 없게 된다.
    final maxWidth = math.max(_minWidth, screen.width - 120);
    final maxHeight = math.max(_minHeight, screen.height - 220);
    final width = _width.clamp(_minWidth, maxWidth);
    final height = _height.clamp(_minHeight, maxHeight);

    return AlertDialog(
      title: Row(
        children: [
          const Icon(Icons.error_outline, color: Color(0xFFDC2626)),
          const SizedBox(width: 10),
          Expanded(child: Text(widget.title)),
        ],
      ),
      content: SizedBox(
        width: width,
        height: height,
        child: Stack(
          children: [
            Positioned.fill(
              child: Container(
                decoration: BoxDecoration(
                  color: const Color(0xFFFEF2F2),
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(color: const Color(0xFFFECACA)),
                ),
                child: Scrollbar(
                  child: SingleChildScrollView(
                    padding: const EdgeInsets.fromLTRB(14, 14, 14, 26),
                    child: SelectableText(
                      widget.message,
                      style: const TextStyle(
                        color: Color(0xFF7F1D1D),
                        height: 1.5,
                      ),
                    ),
                  ),
                ),
              ),
            ),
            Positioned(
              right: 0,
              bottom: 0,
              child: MouseRegion(
                cursor: SystemMouseCursors.resizeDownRight,
                child: GestureDetector(
                  behavior: HitTestBehavior.opaque,
                  onPanUpdate: (details) => setState(() {
                    _width = (width + details.delta.dx).clamp(
                      _minWidth,
                      maxWidth,
                    );
                    _height = (height + details.delta.dy).clamp(
                      _minHeight,
                      maxHeight,
                    );
                  }),
                  child: const Padding(
                    padding: EdgeInsets.all(6),
                    child: Icon(
                      Icons.open_in_full,
                      size: 15,
                      color: Color(0xFFB91C1C),
                    ),
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
      actions: [
        TextButton.icon(
          onPressed: () async {
            await Clipboard.setData(ClipboardData(text: widget.message));
            if (!context.mounted) return;
            ScaffoldMessenger.of(context).showSnackBar(
              const SnackBar(content: Text('오류 내용을 클립보드에 복사했습니다.')),
            );
          },
          icon: const Icon(Icons.content_copy_outlined, size: 18),
          label: const Text('복사'),
        ),
        FilledButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('닫기'),
        ),
      ],
    );
  }
}

class _StageBar extends StatelessWidget {
  const _StageBar({required this.activeStage});
  final MapStage activeStage;
  static const labels = [
    '도면 업로드',
    'Measurement',
    '벽 인식',
    'Floor 생성',
    'Lane 만들기',
    '위치 지정',
    '배포',
  ];
  @override
  Widget build(BuildContext context) {
    final active = MapStage.values.indexOf(activeStage);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 18),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(13),
        border: Border.all(color: const Color(0xFFE5EAF0)),
      ),
      child: Row(
        children: [
          for (var i = 0; i < labels.length; i++) ...[
            _StageItem(
              index: i,
              label: labels[i],
              active: i == active,
              done: i < active,
            ),
            if (i < labels.length - 1)
              Expanded(
                child: Container(
                  height: 1,
                  color: i < active
                      ? const Color(0xFF2563EB)
                      : const Color(0xFFE2E8F0),
                ),
              ),
          ],
        ],
      ),
    );
  }
}

class _StageItem extends StatelessWidget {
  const _StageItem({
    required this.index,
    required this.label,
    required this.active,
    required this.done,
  });
  final int index;
  final String label;
  final bool active;
  final bool done;
  @override
  Widget build(BuildContext context) => Row(
    mainAxisSize: MainAxisSize.min,
    children: [
      Container(
        width: 28,
        height: 28,
        alignment: Alignment.center,
        decoration: BoxDecoration(
          color: active || done
              ? const Color(0xFF2563EB)
              : const Color(0xFFF1F5F9),
          shape: BoxShape.circle,
        ),
        child: done
            ? const Icon(Icons.check, size: 16, color: Colors.white)
            : Text(
                '${index + 1}',
                style: TextStyle(
                  color: active ? Colors.white : const Color(0xFF94A3B8),
                  fontSize: 12,
                  fontWeight: FontWeight.w800,
                ),
              ),
      ),
      const SizedBox(width: 8),
      Text(
        label,
        style: TextStyle(
          color: active ? const Color(0xFF1E293B) : const Color(0xFF94A3B8),
          fontSize: 12,
          fontWeight: active ? FontWeight.w700 : FontWeight.w500,
        ),
      ),
    ],
  );
}

/// 지도를 보여 주는 칸의 높이(px).
///
/// 맵 관리와 로봇 운영이 같은 값을 쓴다. 같은 도면인데 화면마다 크기가 다르면
/// 다른 지도처럼 보이고, 로봇 화면에서는 작아서 어느 Waypoint 에 서 있는지
/// 눈으로 짚기 어려웠다. 한 곳에서 고쳐 둘이 함께 움직이게 한다.
///
/// 창 높이에 맞춰 줄이지 않는다 — 도면은 위아래로 넓어서, 남는 자리에
/// 맞추면 낮은 창에서 지도가 띠처럼 눌린다. 모자라면 화면을 스크롤한다.
const double mapWorkspaceHeight = 936;

class _MapWorkspace extends StatelessWidget {
  const _MapWorkspace({
    required this.drawing,
    required this.transformController,
    required this.onZoomIn,
    required this.onZoomOut,
    required this.onFitScreen,
    required this.onRenumberVertices,
    required this.wallMask,
    required this.wallColor,
    required this.floorMask,
    required this.floorColor,
    required this.mapVertices,
    required this.vertexLabelRevision,
    required this.optimizedWalls,
    required this.recommendedLanes,
    required this.laneDirections,
    required this.laneWaypoints,
    required this.waypointNames,
    required this.waypointTypes,
    required this.activeLaneEndpoint,
    required this.waypointMode,
    required this.onAddWaypoint,
    required this.onEditWaypoint,
    required this.onMoveWaypoint,
    required this.waypointDropIssue,
    required this.onSelectLane,
    required this.isWallConnectMode,
    required this.pendingWallVertex,
    required this.onToggleWallConnect,
    required this.onSelectWallVertex,
    required this.isWallEndpointEditMode,
    required this.onToggleWallEndpointEdit,
    required this.onMoveWallEndpoint,
    required this.measurement,
    required this.showDrawingInfo,
    required this.onCloseDrawingInfo,
    required this.isMeasurementSelected,
    required this.onSelectMeasurement,
    required this.onRemoveMeasurement,
    required this.isMeasurementMode,
    required this.onMeasurementSelected,
    required this.onCloseMeasurementMode,
    required this.isWallEraseMode,
    required this.canUndoWallErase,
    required this.onToggleWallErase,
    required this.onEraseWalls,
    required this.onUndoWallErase,
    required this.isPicking,
    required this.onPick,
    required this.onRemove,
  });
  final UploadedDrawing? drawing;
  final TransformationController transformController;
  final VoidCallback onZoomIn;
  final VoidCallback onZoomOut;
  final VoidCallback onFitScreen;
  final VoidCallback onRenumberVertices;
  final _WallMask? wallMask;
  final Color wallColor;
  final _WallMask? floorMask;
  final Color floorColor;
  final List<Offset> mapVertices;
  final int vertexLabelRevision;
  final List<(Offset, Offset)> optimizedWalls;
  final List<(Offset, Offset)> recommendedLanes;
  final Map<(Offset, Offset), String> laneDirections;
  final List<Offset> laneWaypoints;
  final Map<Offset, String> waypointNames;
  final Map<Offset, String> waypointTypes;
  final Offset? activeLaneEndpoint;
  final bool waypointMode;
  final ValueChanged<Offset> onAddWaypoint;
  final ValueChanged<Offset> onEditWaypoint;
  final void Function(Offset original, Offset updated) onMoveWaypoint;
  final WaypointMoveIssue? Function(Offset original, Offset updated)
  waypointDropIssue;
  final ValueChanged<(Offset, Offset)> onSelectLane;
  final bool isWallConnectMode;
  final Offset? pendingWallVertex;
  final VoidCallback onToggleWallConnect;
  final ValueChanged<Offset> onSelectWallVertex;
  final bool isWallEndpointEditMode;
  final VoidCallback onToggleWallEndpointEdit;
  final void Function(Offset original, Offset updated) onMoveWallEndpoint;
  final _MapMeasurement? measurement;
  final bool showDrawingInfo;
  final VoidCallback onCloseDrawingInfo;
  final bool isMeasurementSelected;
  final VoidCallback onSelectMeasurement;
  final VoidCallback onRemoveMeasurement;
  final bool isMeasurementMode;
  final void Function(Offset start, Offset end) onMeasurementSelected;
  final VoidCallback onCloseMeasurementMode;
  final bool isWallEraseMode;
  final bool canUndoWallErase;
  final VoidCallback onToggleWallErase;
  final ValueChanged<Rect> onEraseWalls;
  final VoidCallback onUndoWallErase;
  final bool isPicking;
  final VoidCallback onPick;
  final VoidCallback onRemove;
  @override
  Widget build(BuildContext context) => Container(
    height: mapWorkspaceHeight,
    clipBehavior: Clip.antiAlias,
    decoration: BoxDecoration(
      color: Colors.white,
      borderRadius: BorderRadius.circular(14),
      border: Border.all(color: const Color(0xFFE2E8F0)),
    ),
    child: Column(
      children: [
        Container(
          height: 58,
          padding: const EdgeInsets.symmetric(horizontal: 18),
          decoration: const BoxDecoration(
            border: Border(bottom: BorderSide(color: Color(0xFFE5EAF0))),
          ),
          child: Row(
            children: [
              const Text(
                '도면 작업 영역',
                style: TextStyle(
                  fontWeight: FontWeight.w700,
                  color: Color(0xFF1E293B),
                ),
              ),
              const Spacer(),
              if (drawing != null) ...[
                if (measurement != null && isMeasurementSelected) ...[
                  IconButton(
                    onPressed: onRemoveMeasurement,
                    icon: const Icon(Icons.delete_outline),
                    color: const Color(0xFFEF4444),
                    tooltip: 'Measurement 제거',
                    style: IconButton.styleFrom(
                      backgroundColor: const Color(0xFFFEF2F2),
                    ),
                  ),
                  const SizedBox(width: 5),
                ],
                if (wallMask != null) ...[
                  IconButton(
                    onPressed: onToggleWallConnect,
                    icon: Icon(
                      Icons.add_link,
                      color: isWallConnectMode
                          ? const Color(0xFF2563EB)
                          : const Color(0xFF64748B),
                    ),
                    tooltip: isWallConnectMode ? '벽 연결 종료' : '끊어진 벽 연결',
                    style: IconButton.styleFrom(
                      backgroundColor: isWallConnectMode
                          ? const Color(0xFFEFF6FF)
                          : Colors.transparent,
                    ),
                  ),
                  IconButton(
                    onPressed: onToggleWallEndpointEdit,
                    icon: Icon(
                      Icons.open_with,
                      color: isWallEndpointEditMode
                          ? const Color(0xFF2563EB)
                          : const Color(0xFF64748B),
                    ),
                    tooltip: isWallEndpointEditMode ? '끝점 이동 종료' : '마지막 정점 이동',
                    style: IconButton.styleFrom(
                      backgroundColor: isWallEndpointEditMode
                          ? const Color(0xFFEFF6FF)
                          : Colors.transparent,
                    ),
                  ),
                  IconButton(
                    onPressed: onToggleWallErase,
                    icon: Icon(
                      Icons.cleaning_services_outlined,
                      color: isWallEraseMode
                          ? const Color(0xFF2563EB)
                          : const Color(0xFF64748B),
                    ),
                    tooltip: isWallEraseMode ? '벽 지우기 종료' : '잘못 인식된 벽 선택 제거',
                    style: IconButton.styleFrom(
                      backgroundColor: isWallEraseMode
                          ? const Color(0xFFEFF6FF)
                          : Colors.transparent,
                    ),
                  ),
                  IconButton(
                    onPressed: canUndoWallErase ? onUndoWallErase : null,
                    icon: const Icon(Icons.undo, size: 20),
                    tooltip: '벽 제거 실행 취소',
                  ),
                  const SizedBox(width: 5),
                ],
                _ToolButton(
                  icon: Icons.zoom_out,
                  tooltip: '축소',
                  onPressed: onZoomOut,
                ),
                _ToolButton(
                  icon: Icons.zoom_in,
                  tooltip: '확대',
                  onPressed: onZoomIn,
                ),
                _ToolButton(
                  icon: Icons.fit_screen,
                  tooltip: '화면 맞춤',
                  onPressed: onFitScreen,
                ),
                _ToolButton(
                  icon: Icons.format_list_numbered,
                  tooltip: '정점 재넘버링',
                  onPressed: onRenumberVertices,
                ),
                const SizedBox(width: 8),
                IconButton(
                  onPressed: onRemove,
                  icon: const Icon(
                    Icons.delete_outline,
                    color: Color(0xFFEF4444),
                  ),
                  tooltip: '도면 제거',
                ),
              ],
            ],
          ),
        ),
        Expanded(
          child: drawing == null
              ? _UploadEmpty(isPicking: isPicking, onPick: onPick)
              : _DrawingPreview(
                  drawing: drawing!,
                  transformController: transformController,
                  wallMask: wallMask,
                  wallColor: wallColor,
                  floorMask: floorMask,
                  floorColor: floorColor,
                  mapVertices: mapVertices,
                  vertexLabelRevision: vertexLabelRevision,
                  optimizedWalls: optimizedWalls,
                  recommendedLanes: recommendedLanes,
                  laneDirections: laneDirections,
                  laneWaypoints: laneWaypoints,
                  waypointNames: waypointNames,
                  waypointTypes: waypointTypes,
                  activeLaneEndpoint: activeLaneEndpoint,
                  waypointMode: waypointMode,
                  onAddWaypoint: onAddWaypoint,
                  onEditWaypoint: onEditWaypoint,
                  onMoveWaypoint: onMoveWaypoint,
                  waypointDropIssue: waypointDropIssue,
                  onSelectLane: onSelectLane,
                  wallConnectMode: isWallConnectMode,
                  pendingWallVertex: pendingWallVertex,
                  onSelectWallVertex: onSelectWallVertex,
                  wallEndpointEditMode: isWallEndpointEditMode,
                  onMoveWallEndpoint: onMoveWallEndpoint,
                  measurement: measurement,
                  showDrawingInfo: showDrawingInfo,
                  onCloseDrawingInfo: onCloseDrawingInfo,
                  measurementSelected: isMeasurementSelected,
                  onSelectMeasurement: onSelectMeasurement,
                  measurementMode: isMeasurementMode,
                  onMeasurementSelected: onMeasurementSelected,
                  onCloseMeasurementMode: onCloseMeasurementMode,
                  isWallEraseMode: isWallEraseMode,
                  onEraseWalls: onEraseWalls,
                ),
        ),
      ],
    ),
  );
}

class _ToolButton extends StatelessWidget {
  const _ToolButton({
    required this.icon,
    required this.tooltip,
    required this.onPressed,
  });
  final IconData icon;
  final String tooltip;
  final VoidCallback onPressed;
  @override
  Widget build(BuildContext context) => IconButton(
    onPressed: onPressed,
    icon: Icon(icon, size: 20),
    tooltip: tooltip,
    color: const Color(0xFF64748B),
  );
}

class _UploadEmpty extends StatelessWidget {
  const _UploadEmpty({required this.isPicking, required this.onPick});
  final bool isPicking;
  final VoidCallback onPick;
  @override
  Widget build(BuildContext context) => Container(
    margin: const EdgeInsets.all(22),
    decoration: BoxDecoration(
      color: const Color(0xFFF8FAFC),
      borderRadius: BorderRadius.circular(12),
      border: Border.all(color: const Color(0xFFCBD5E1), width: 1.4),
    ),
    child: Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 430),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Container(
              width: 76,
              height: 76,
              decoration: const BoxDecoration(
                color: Color(0xFFEFF6FF),
                shape: BoxShape.circle,
              ),
              child: const Icon(
                Icons.cloud_upload_outlined,
                color: Color(0xFF2563EB),
                size: 36,
              ),
            ),
            const SizedBox(height: 22),
            const Text(
              '창고 도면을 올려주세요',
              style: TextStyle(
                fontSize: 20,
                fontWeight: FontWeight.w800,
                color: Color(0xFF1E293B),
              ),
            ),
            const SizedBox(height: 9),
            const Text(
              '파일을 선택하면 맵 생성 준비를 시작합니다.\nPNG, JPG, PDF, DXF, DWG 형식을 지원합니다.',
              textAlign: TextAlign.center,
              style: TextStyle(height: 1.6, color: Color(0xFF64748B)),
            ),
            const SizedBox(height: 22),
            OutlinedButton.icon(
              onPressed: isPicking ? null : onPick,
              icon: isPicking
                  ? const SizedBox(
                      width: 17,
                      height: 17,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.folder_open_outlined),
              label: Text(isPicking ? '불러오는 중...' : '내 컴퓨터에서 선택'),
              style: OutlinedButton.styleFrom(
                padding: const EdgeInsets.symmetric(
                  horizontal: 20,
                  vertical: 15,
                ),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(9),
                ),
              ),
            ),
            const SizedBox(height: 13),
            const Text(
              '최대 파일 크기 50MB',
              style: TextStyle(fontSize: 12, color: Color(0xFF94A3B8)),
            ),
          ],
        ),
      ),
    ),
  );
}

class _DrawingPreview extends StatelessWidget {
  const _DrawingPreview({
    required this.drawing,
    required this.transformController,
    required this.wallMask,
    required this.wallColor,
    required this.floorMask,
    required this.floorColor,
    required this.mapVertices,
    required this.vertexLabelRevision,
    required this.optimizedWalls,
    required this.recommendedLanes,
    required this.laneDirections,
    required this.laneWaypoints,
    required this.waypointNames,
    required this.waypointTypes,
    required this.activeLaneEndpoint,
    required this.waypointMode,
    required this.onAddWaypoint,
    required this.onEditWaypoint,
    required this.onMoveWaypoint,
    required this.waypointDropIssue,
    required this.onSelectLane,
    required this.wallConnectMode,
    required this.pendingWallVertex,
    required this.onSelectWallVertex,
    required this.wallEndpointEditMode,
    required this.onMoveWallEndpoint,
    required this.measurement,
    required this.showDrawingInfo,
    required this.onCloseDrawingInfo,
    required this.measurementSelected,
    required this.onSelectMeasurement,
    required this.measurementMode,
    required this.onMeasurementSelected,
    required this.onCloseMeasurementMode,
    required this.isWallEraseMode,
    required this.onEraseWalls,
  });
  final UploadedDrawing drawing;
  final TransformationController transformController;
  final _WallMask? wallMask;
  final Color wallColor;
  final _WallMask? floorMask;
  final Color floorColor;
  final List<Offset> mapVertices;
  final int vertexLabelRevision;
  final List<(Offset, Offset)> optimizedWalls;
  final List<(Offset, Offset)> recommendedLanes;
  final Map<(Offset, Offset), String> laneDirections;
  final List<Offset> laneWaypoints;
  final Map<Offset, String> waypointNames;
  final Map<Offset, String> waypointTypes;
  final Offset? activeLaneEndpoint;
  final bool waypointMode;
  final ValueChanged<Offset> onAddWaypoint;
  final ValueChanged<Offset> onEditWaypoint;
  final void Function(Offset original, Offset updated) onMoveWaypoint;
  final WaypointMoveIssue? Function(Offset original, Offset updated)
  waypointDropIssue;
  final ValueChanged<(Offset, Offset)> onSelectLane;
  final bool wallConnectMode;
  final Offset? pendingWallVertex;
  final ValueChanged<Offset> onSelectWallVertex;
  final bool wallEndpointEditMode;
  final void Function(Offset original, Offset updated) onMoveWallEndpoint;
  final _MapMeasurement? measurement;
  final bool showDrawingInfo;
  final VoidCallback onCloseDrawingInfo;
  final bool measurementSelected;
  final VoidCallback onSelectMeasurement;
  final bool measurementMode;
  final void Function(Offset start, Offset end) onMeasurementSelected;
  final VoidCallback onCloseMeasurementMode;
  final bool isWallEraseMode;
  final ValueChanged<Rect> onEraseWalls;
  @override
  Widget build(BuildContext context) => Stack(
    children: [
      Positioned.fill(
        child: Container(
          color: const Color(0xFFF1F5F9),
          padding: const EdgeInsets.symmetric(horizontal: 28, vertical: 33.6),
          child: drawing.isImage && drawing.bytes != null
              ? InteractiveViewer(
                  transformationController: transformController,
                  minScale: 0.4,
                  maxScale: 5,
                  panEnabled:
                      !isWallEraseMode &&
                      !measurementMode &&
                      !wallConnectMode &&
                      !wallEndpointEditMode &&
                      !waypointMode,
                  scaleEnabled:
                      !isWallEraseMode &&
                      !measurementMode &&
                      !wallConnectMode &&
                      !wallEndpointEditMode &&
                      !waypointMode,
                  child: _WallEditorCanvas(
                    bytes: drawing.bytes!,
                    sourceSize: Size(
                      drawing.pixelWidth!.toDouble(),
                      drawing.pixelHeight!.toDouble(),
                    ),
                    mask: wallMask,
                    color: wallColor,
                    floorMask: floorMask,
                    floorColor: floorColor,
                    mapVertices: mapVertices,
                    vertexLabelRevision: vertexLabelRevision,
                    optimizedWalls: optimizedWalls,
                    recommendedLanes: recommendedLanes,
                    laneDirections: laneDirections,
                    laneWaypoints: laneWaypoints,
                    waypointNames: waypointNames,
                    waypointTypes: waypointTypes,
                    activeLaneEndpoint: activeLaneEndpoint,
                    waypointMode: waypointMode,
                    onAddWaypoint: onAddWaypoint,
                    onEditWaypoint: onEditWaypoint,
                    onMoveWaypoint: onMoveWaypoint,
                    waypointDropIssue: waypointDropIssue,
                    onSelectLane: onSelectLane,
                    wallConnectMode: wallConnectMode,
                    pendingWallVertex: pendingWallVertex,
                    onSelectWallVertex: onSelectWallVertex,
                    wallEndpointEditMode: wallEndpointEditMode,
                    onMoveWallEndpoint: onMoveWallEndpoint,
                    measurement: measurement,
                    measurementSelected: measurementSelected,
                    onSelectMeasurement: onSelectMeasurement,
                    measurementMode: measurementMode,
                    onMeasurementSelected: onMeasurementSelected,
                    onCloseMeasurementMode: onCloseMeasurementMode,
                    eraseMode: isWallEraseMode,
                    onErase: onEraseWalls,
                  ),
                )
              : _NonImagePreview(extension: drawing.extension),
        ),
      ),
      if (showDrawingInfo)
        Positioned(
          left: 16,
          bottom: 16,
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 13, vertical: 10),
            decoration: BoxDecoration(
              color: Colors.white.withValues(alpha: .94),
              borderRadius: BorderRadius.circular(9),
              boxShadow: const [
                BoxShadow(color: Color(0x18000000), blurRadius: 12),
              ],
            ),
            child: Row(
              children: [
                const Icon(
                  Icons.description_outlined,
                  size: 18,
                  color: Color(0xFF2563EB),
                ),
                const SizedBox(width: 8),
                Text(
                  drawing.name,
                  style: const TextStyle(
                    fontWeight: FontWeight.w700,
                    color: Color(0xFF334155),
                  ),
                ),
                const SizedBox(width: 10),
                Text(
                  drawing.readableSize,
                  style: const TextStyle(
                    fontSize: 12,
                    color: Color(0xFF94A3B8),
                  ),
                ),
                const SizedBox(width: 6),
                InkWell(
                  onTap: onCloseDrawingInfo,
                  customBorder: const CircleBorder(),
                  child: const Padding(
                    padding: EdgeInsets.all(3),
                    child: Icon(
                      Icons.close,
                      size: 16,
                      color: Color(0xFF64748B),
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
    ],
  );
}

class _WallEditorCanvas extends StatefulWidget {
  const _WallEditorCanvas({
    required this.bytes,
    required this.sourceSize,
    required this.mask,
    required this.color,
    required this.floorMask,
    required this.floorColor,
    required this.mapVertices,
    required this.vertexLabelRevision,
    required this.optimizedWalls,
    required this.recommendedLanes,
    required this.laneDirections,
    required this.laneWaypoints,
    required this.waypointNames,
    required this.waypointTypes,
    required this.activeLaneEndpoint,
    required this.waypointMode,
    required this.onAddWaypoint,
    required this.onEditWaypoint,
    required this.onMoveWaypoint,
    required this.waypointDropIssue,
    required this.onSelectLane,
    required this.wallConnectMode,
    required this.pendingWallVertex,
    required this.onSelectWallVertex,
    required this.wallEndpointEditMode,
    required this.onMoveWallEndpoint,
    required this.measurement,
    required this.measurementSelected,
    required this.onSelectMeasurement,
    required this.measurementMode,
    required this.onMeasurementSelected,
    required this.onCloseMeasurementMode,
    required this.eraseMode,
    required this.onErase,
  });

  final Uint8List bytes;
  final Size sourceSize;
  final _WallMask? mask;
  final Color color;
  final _WallMask? floorMask;
  final Color floorColor;
  final List<Offset> mapVertices;
  final int vertexLabelRevision;
  final List<(Offset, Offset)> optimizedWalls;
  final List<(Offset, Offset)> recommendedLanes;
  final Map<(Offset, Offset), String> laneDirections;
  final List<Offset> laneWaypoints;
  final Map<Offset, String> waypointNames;
  final Map<Offset, String> waypointTypes;
  final Offset? activeLaneEndpoint;
  final bool waypointMode;
  final ValueChanged<Offset> onAddWaypoint;
  final ValueChanged<Offset> onEditWaypoint;
  final void Function(Offset original, Offset updated) onMoveWaypoint;
  final WaypointMoveIssue? Function(Offset original, Offset updated)
  waypointDropIssue;
  final ValueChanged<(Offset, Offset)> onSelectLane;
  final bool wallConnectMode;
  final Offset? pendingWallVertex;
  final ValueChanged<Offset> onSelectWallVertex;
  final bool wallEndpointEditMode;
  final void Function(Offset original, Offset updated) onMoveWallEndpoint;
  final _MapMeasurement? measurement;
  final bool measurementSelected;
  final VoidCallback onSelectMeasurement;
  final bool measurementMode;
  final void Function(Offset start, Offset end) onMeasurementSelected;
  final VoidCallback onCloseMeasurementMode;
  final bool eraseMode;
  final ValueChanged<Rect> onErase;

  @override
  State<_WallEditorCanvas> createState() => _WallEditorCanvasState();
}

class _WallEditorCanvasState extends State<_WallEditorCanvas> {
  Offset? _start;
  Offset? _current;
  Offset _measurementBadgeOffset = const Offset(12, 12);
  Offset? _movingWallVertex;
  Offset? _movingWallScreenPoint;
  Offset? _movingWaypoint;

  /// 드래그를 시작한 순간의 Waypoint 화면 좌표. Shift 직선 이동의 기준이다.
  Offset? _movingWaypointOrigin;

  /// 제약 없이 커서를 따라간 좌표. 화면에 그리고 실제로 놓는 자리는
  /// [_movingWaypointScreenPoint] 가 정한다.
  Offset? _movingWaypointRawPoint;
  Offset? _waypointCursor;
  Offset? _hoveredWaypoint;
  Offset? _waypointHoverPosition;
  bool _movingWallHorizontally = true;

  /// Shift를 누르고 있으면 시작점에서 가로 또는 세로 한 방향으로만 움직인다.
  ///
  /// 더 많이 끈 축을 남기고 다른 축은 시작값으로 묶는다. 통로를 따라 일직선으로
  /// 늘어놓을 때 눈대중으로 맞추지 않아도 된다. 끌던 도중에 Shift를 눌렀다
  /// 떼도 원래 좌표가 남아 있으므로 그대로 되돌아온다.
  Offset? get _movingWaypointScreenPoint {
    final raw = _movingWaypointRawPoint;
    final origin = _movingWaypointOrigin;
    if (raw == null || origin == null) return raw;
    if (!HardwareKeyboard.instance.isShiftPressed) return raw;
    return constrainToAxis(origin, raw);
  }

  /// Shift를 누르거나 떼는 순간 미리보기가 따라오게 한다. 마우스를 움직이지
  /// 않으면 다시 그릴 일이 없어 눌러도 반응이 없는 것처럼 보인다.
  bool _handleKeyEvent(KeyEvent event) {
    if (_movingWaypoint == null) return false;
    if (event.logicalKey != LogicalKeyboardKey.shiftLeft &&
        event.logicalKey != LogicalKeyboardKey.shiftRight) {
      return false;
    }
    setState(() {});
    return false;
  }

  @override
  void initState() {
    super.initState();
    HardwareKeyboard.instance.addHandler(_handleKeyEvent);
  }

  @override
  void dispose() {
    HardwareKeyboard.instance.removeHandler(_handleKeyEvent);
    super.dispose();
  }

  Rect? get _selection => _start == null || _current == null
      ? null
      : Rect.fromPoints(_start!, _current!);

  (Offset, Offset) _measurementScreenPoints(Size canvasSize) {
    final measurement = widget.measurement!;
    final fitted = applyBoxFit(
      BoxFit.contain,
      widget.sourceSize,
      canvasSize,
    ).destination;
    final target = Alignment.center.inscribe(fitted, Offset.zero & canvasSize);
    Offset convert(Offset point) => Offset(
      target.left + point.dx * target.width / widget.sourceSize.width,
      target.top + point.dy * target.height / widget.sourceSize.height,
    );
    return (convert(measurement.start), convert(measurement.end));
  }

  void _trySelectMeasurement(Offset position, Size canvasSize) {
    if (widget.measurement == null) return;
    final points = _measurementScreenPoints(canvasSize);
    final line = points.$2 - points.$1;
    final lengthSquared = line.distanceSquared;
    if (lengthSquared == 0) return;
    final relative = position - points.$1;
    final t = ((relative.dx * line.dx + relative.dy * line.dy) / lengthSquared)
        .clamp(0.0, 1.0);
    final nearest = points.$1 + line * t;
    if ((position - nearest).distance <= 14) widget.onSelectMeasurement();
  }

  bool _tryEditWaypoint(Offset position, Size canvasSize) {
    final nearest = _findWaypointAt(position, canvasSize);
    if (nearest == null) return false;
    widget.onEditWaypoint(nearest);
    return true;
  }

  Offset? _findWaypointAt(Offset position, Size canvasSize) {
    Offset? nearest;
    var nearestDistance = 18.0;
    for (final waypoint in widget.laneWaypoints) {
      final distance =
          (_vertexToScreen(waypoint, canvasSize) - position).distance;
      if (distance <= nearestDistance) {
        nearest = waypoint;
        nearestDistance = distance;
      }
    }
    return nearest;
  }

  bool _trySelectLane(Offset position, Size canvasSize) {
    (Offset, Offset)? nearestLane;
    var nearestDistance = 12.0;
    for (final lane in widget.recommendedLanes) {
      final start = _vertexToScreen(lane.$1, canvasSize);
      final end = _vertexToScreen(lane.$2, canvasSize);
      final direction = end - start;
      if (direction.distanceSquared <= .01) continue;
      final relative = position - start;
      final t =
          ((relative.dx * direction.dx + relative.dy * direction.dy) /
                  direction.distanceSquared)
              .clamp(0.0, 1.0);
      final distance = (position - (start + direction * t)).distance;
      if (distance <= nearestDistance) {
        nearestLane = lane;
        nearestDistance = distance;
      }
    }
    if (nearestLane == null) return false;
    widget.onSelectLane(nearestLane);
    return true;
  }

  void _trySelectWallVertex(Offset position, Size canvasSize) {
    final fitted = applyBoxFit(
      BoxFit.contain,
      widget.sourceSize,
      canvasSize,
    ).destination;
    final target = Alignment.center.inscribe(fitted, Offset.zero & canvasSize);
    Offset convert(Offset point) => Offset(
      target.left + point.dx * target.width / widget.sourceSize.width,
      target.top + point.dy * target.height / widget.sourceSize.height,
    );
    Offset? nearest;
    var nearestDistance = 16.0;
    for (final vertex in widget.mapVertices) {
      final distance = (convert(vertex) - position).distance;
      if (distance < nearestDistance) {
        nearest = vertex;
        nearestDistance = distance;
      }
    }
    if (nearest != null) widget.onSelectWallVertex(nearest);
  }

  Rect _imageTarget(Size canvasSize) {
    final fitted = applyBoxFit(
      BoxFit.contain,
      widget.sourceSize,
      canvasSize,
    ).destination;
    return Alignment.center.inscribe(fitted, Offset.zero & canvasSize);
  }

  Offset _vertexToScreen(Offset point, Size canvasSize) {
    final target = _imageTarget(canvasSize);
    return Offset(
      target.left + point.dx * target.width / widget.sourceSize.width,
      target.top + point.dy * target.height / widget.sourceSize.height,
    );
  }

  Offset? _screenToImage(Offset position, Size canvasSize) {
    final target = _imageTarget(canvasSize);
    if (!target.contains(position)) return null;
    return Offset(
      (position.dx - target.left) * widget.sourceSize.width / target.width,
      (position.dy - target.top) * widget.sourceSize.height / target.height,
    );
  }

  Rect _floorBounds() {
    final points = widget.floorMask?.points;
    if (points == null || points.isEmpty) {
      return Offset.zero & widget.sourceSize;
    }
    var left = points.first.dx;
    var top = points.first.dy;
    var right = left;
    var bottom = top;
    for (final point in points.skip(1)) {
      left = math.min(left, point.dx);
      top = math.min(top, point.dy);
      right = math.max(right, point.dx);
      bottom = math.max(bottom, point.dy);
    }
    return Rect.fromLTRB(left, top, right, bottom);
  }

  Offset _imageToFloor(Offset point) {
    final bounds = _floorBounds();
    return Offset(point.dx - bounds.left, bounds.bottom - point.dy);
  }

  ({double left, double right, double top, double bottom}) _wallSpan(
    Offset point,
  ) {
    final floor = _floorBounds();
    var left = floor.left;
    var right = floor.right;
    var top = floor.top;
    var bottom = floor.bottom;
    for (final wall in widget.optimizedWalls) {
      final a = wall.$1;
      final b = wall.$2;
      final vertical = (a.dx - b.dx).abs() <= 2;
      final horizontal = (a.dy - b.dy).abs() <= 2;
      if (vertical &&
          point.dy >= math.min(a.dy, b.dy) - 2 &&
          point.dy <= math.max(a.dy, b.dy) + 2) {
        final x = (a.dx + b.dx) / 2;
        if (x <= point.dx && x > left) left = x;
        if (x >= point.dx && x < right) right = x;
      }
      if (horizontal &&
          point.dx >= math.min(a.dx, b.dx) - 2 &&
          point.dx <= math.max(a.dx, b.dx) + 2) {
        final y = (a.dy + b.dy) / 2;
        if (y <= point.dy && y > top) top = y;
        if (y >= point.dy && y < bottom) bottom = y;
      }
    }
    return (left: left, right: right, top: top, bottom: bottom);
  }

  void _addWaypointAt(Offset position, Size canvasSize) {
    final point = _screenToImage(position, canvasSize);
    if (point != null) widget.onAddWaypoint(point);
  }

  void _startEndpointMove(Offset position, Size canvasSize) {
    Offset? vertex;
    var distance = 16.0;
    for (final candidate in widget.mapVertices) {
      final candidateDistance =
          (_vertexToScreen(candidate, canvasSize) - position).distance;
      if (candidateDistance < distance) {
        vertex = candidate;
        distance = candidateDistance;
      }
    }
    if (vertex == null) return;
    final incident = widget.optimizedWalls
        .where(
          (wall) =>
              (wall.$1 - vertex!).distance <= .01 ||
              (wall.$2 - vertex).distance <= .01,
        )
        .toList();
    if (incident.length != 1) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('여러 Wall이 만나는 공유 정점은 이동할 수 없습니다.')),
      );
      return;
    }
    final wall = incident.single;
    setState(() {
      _movingWallVertex = vertex;
      _movingWallScreenPoint = _vertexToScreen(vertex!, canvasSize);
      _movingWallHorizontally = (wall.$1.dy - wall.$2.dy).abs() <= .01;
    });
  }

  void _updateEndpointMove(Offset position, Size canvasSize) {
    final original = _movingWallVertex;
    if (original == null) return;
    final start = _vertexToScreen(original, canvasSize);
    setState(() {
      _movingWallScreenPoint = _movingWallHorizontally
          ? Offset(position.dx, start.dy)
          : Offset(start.dx, position.dy);
    });
  }

  void _finishEndpointMove(Size canvasSize) {
    final original = _movingWallVertex;
    final screenPoint = _movingWallScreenPoint;
    if (original == null || screenPoint == null) return;
    final target = _imageTarget(canvasSize);
    final updated = Offset(
      ((screenPoint.dx - target.left) * widget.sourceSize.width / target.width)
          .clamp(0, widget.sourceSize.width),
      ((screenPoint.dy - target.top) * widget.sourceSize.height / target.height)
          .clamp(0, widget.sourceSize.height),
    );
    widget.onMoveWallEndpoint(original, updated);
    setState(() {
      _movingWallVertex = null;
      _movingWallScreenPoint = null;
    });
  }

  /// Whether the Waypoint being dragged could be dropped where it is now.
  bool _waypointDropAllowed(Size canvasSize) {
    final original = _movingWaypoint;
    final screenPoint = _movingWaypointScreenPoint;
    if (original == null || screenPoint == null) return true;
    final updated = _screenToImage(screenPoint, canvasSize);
    if (updated == null) return false;
    return widget.waypointDropIssue(original, updated) == null;
  }

  void _finishWaypointMove(Size canvasSize) {
    final original = _movingWaypoint;
    final screenPoint = _movingWaypointScreenPoint;
    if (original == null || screenPoint == null) return;
    final updated = _screenToImage(screenPoint, canvasSize);
    setState(() {
      _movingWaypoint = null;
      _movingWaypointOrigin = null;
      _movingWaypointRawPoint = null;
      _hoveredWaypoint = null;
      _waypointHoverPosition = null;
    });
    if (updated != null) widget.onMoveWaypoint(original, updated);
  }

  void _finishSelection(Size canvasSize) {
    final selection = _selection;
    final mask = widget.mask;
    if (selection == null || mask == null) return;
    final source = Size(mask.width.toDouble(), mask.height.toDouble());
    final fitted = applyBoxFit(BoxFit.contain, source, canvasSize).destination;
    final imageRect = Alignment.center.inscribe(
      fitted,
      Offset.zero & canvasSize,
    );
    final selectedImageArea = selection.intersect(imageRect);
    if (selectedImageArea.width < 3 || selectedImageArea.height < 3) {
      setState(() {
        _start = null;
        _current = null;
      });
      return;
    }

    final scale = source.width / imageRect.width;
    widget.onErase(
      Rect.fromLTRB(
        (selectedImageArea.left - imageRect.left) * scale,
        (selectedImageArea.top - imageRect.top) * scale,
        (selectedImageArea.right - imageRect.left) * scale,
        (selectedImageArea.bottom - imageRect.top) * scale,
      ),
    );
    setState(() {
      _start = null;
      _current = null;
    });
  }

  void _finishMeasurement(Size canvasSize) {
    final start = _start;
    final end = _current;
    if (start == null || end == null || (end - start).distance < 8) return;
    final source = widget.sourceSize;
    final fitted = applyBoxFit(BoxFit.contain, source, canvasSize).destination;
    final imageRect = Alignment.center.inscribe(
      fitted,
      Offset.zero & canvasSize,
    );
    Offset toImage(Offset point) => Offset(
      ((point.dx - imageRect.left) * source.width / imageRect.width).clamp(
        0,
        source.width,
      ),
      ((point.dy - imageRect.top) * source.height / imageRect.height).clamp(
        0,
        source.height,
      ),
    );
    widget.onMeasurementSelected(toImage(start), toImage(end));
    setState(() {
      _start = null;
      _current = null;
    });
  }

  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (context, constraints) {
      final size = Size(constraints.maxWidth, constraints.maxHeight);
      return Stack(
        fit: StackFit.expand,
        children: [
          Image.memory(
            widget.bytes,
            fit: BoxFit.contain,
            gaplessPlayback: true,
          ),
          if (widget.floorMask != null)
            IgnorePointer(
              child: CustomPaint(
                painter: _WallOverlayPainter(
                  mask: widget.floorMask!,
                  color: widget.floorColor,
                  opacity: .28,
                ),
              ),
            ),
          if (widget.optimizedWalls.isNotEmpty)
            IgnorePointer(
              child: CustomPaint(
                painter: _VectorWallPainter(
                  walls: widget.optimizedWalls,
                  sourceSize: widget.sourceSize,
                  color: widget.color,
                ),
              ),
            ),
          if (widget.measurement != null)
            IgnorePointer(
              child: CustomPaint(
                painter: _MeasurementPainter(
                  measurement: widget.measurement!,
                  sourceSize: widget.sourceSize,
                  selected: widget.measurementSelected,
                ),
              ),
            ),
          if (widget.laneWaypoints.isNotEmpty)
            IgnorePointer(
              child: CustomPaint(
                painter: _LanePainter(
                  lanes: widget.recommendedLanes,
                  directions: widget.laneDirections,
                  waypoints: widget.laneWaypoints,
                  waypointNames: widget.waypointNames,
                  waypointTypes: widget.waypointTypes,
                  activeEndpoint: widget.activeLaneEndpoint,
                  sourceSize: widget.sourceSize,
                ),
              ),
            ),
          if (widget.mapVertices.isNotEmpty)
            IgnorePointer(
              child: CustomPaint(
                key: ValueKey(widget.vertexLabelRevision),
                painter: _VertexLabelPainter(
                  vertices: widget.mapVertices,
                  sourceSize: widget.sourceSize,
                  revision: widget.vertexLabelRevision,
                ),
              ),
            ),
          if (widget.waypointMode)
            MouseRegion(
              cursor: SystemMouseCursors.precise,
              onHover: (event) => setState(() {
                _waypointCursor =
                    _screenToImage(event.localPosition, size) == null
                    ? null
                    : event.localPosition;
              }),
              onExit: (_) => setState(() => _waypointCursor = null),
              child: GestureDetector(
                behavior: HitTestBehavior.opaque,
                onTapUp: (details) =>
                    _addWaypointAt(details.localPosition, size),
              ),
            ),
          if (widget.waypointMode && _waypointCursor != null)
            IgnorePointer(
              child: CustomPaint(
                painter: _WaypointWallDistancePainter(
                  point: _screenToImage(_waypointCursor!, size)!,
                  span: _wallSpan(_screenToImage(_waypointCursor!, size)!),
                  sourceSize: widget.sourceSize,
                  waypoints: widget.laneWaypoints,
                ),
              ),
            ),
          if (widget.waypointMode && _waypointCursor != null)
            Positioned(
              left: _waypointCursor!.dx + 250 <= size.width
                  ? _waypointCursor!.dx + 18
                  : math.max(0, _waypointCursor!.dx - 242),
              top: _waypointCursor!.dy + 126 <= size.height
                  ? _waypointCursor!.dy + 18
                  : math.max(0, _waypointCursor!.dy - 118),
              child: IgnorePointer(
                child: _WaypointCoordinateBadge(
                  point: _imageToFloor(_screenToImage(_waypointCursor!, size)!),
                  imagePoint: _screenToImage(_waypointCursor!, size)!,
                  span: _wallSpan(_screenToImage(_waypointCursor!, size)!),
                ),
              ),
            ),
          if (widget.wallConnectMode)
            GestureDetector(
              behavior: HitTestBehavior.opaque,
              onTapUp: (details) =>
                  _trySelectWallVertex(details.localPosition, size),
              child: CustomPaint(
                painter: _PendingVertexPainter(
                  vertex: widget.pendingWallVertex,
                  sourceSize: widget.sourceSize,
                ),
              ),
            ),
          if (widget.wallEndpointEditMode)
            GestureDetector(
              behavior: HitTestBehavior.opaque,
              onPanStart: (details) =>
                  _startEndpointMove(details.localPosition, size),
              onPanUpdate: (details) =>
                  _updateEndpointMove(details.localPosition, size),
              onPanEnd: (_) => _finishEndpointMove(size),
              child: CustomPaint(
                painter: _EndpointMovePainter(
                  original: _movingWallVertex == null
                      ? null
                      : _vertexToScreen(_movingWallVertex!, size),
                  current: _movingWallScreenPoint,
                ),
              ),
            ),
          if (!widget.measurementMode &&
              !widget.eraseMode &&
              !widget.waypointMode &&
              !widget.wallConnectMode &&
              !widget.wallEndpointEditMode)
            MouseRegion(
              cursor: _hoveredWaypoint == null
                  ? MouseCursor.defer
                  : SystemMouseCursors.click,
              onHover: (event) {
                final waypoint = _findWaypointAt(event.localPosition, size);
                if (waypoint != _hoveredWaypoint ||
                    event.localPosition != _waypointHoverPosition) {
                  setState(() {
                    _hoveredWaypoint = waypoint;
                    _waypointHoverPosition = waypoint == null
                        ? null
                        : event.localPosition;
                  });
                }
              },
              onExit: (_) => setState(() {
                _hoveredWaypoint = null;
                _waypointHoverPosition = null;
              }),
              child: GestureDetector(
                behavior: HitTestBehavior.translucent,
                onTapUp: (details) {
                  if (_tryEditWaypoint(details.localPosition, size)) return;
                  if (_trySelectLane(details.localPosition, size)) return;
                  if (widget.measurement != null) {
                    _trySelectMeasurement(details.localPosition, size);
                  }
                },
              ),
            ),
          if (!widget.measurementMode &&
              !widget.eraseMode &&
              !widget.waypointMode &&
              !widget.wallConnectMode &&
              !widget.wallEndpointEditMode)
            for (final waypoint in widget.laneWaypoints)
              Positioned(
                left: _vertexToScreen(waypoint, size).dx - 18,
                top: _vertexToScreen(waypoint, size).dy - 18,
                width: 36,
                height: 36,
                child: MouseRegion(
                  cursor: _movingWaypoint == null
                      ? SystemMouseCursors.grab
                      : SystemMouseCursors.grabbing,
                  child: GestureDetector(
                    behavior: HitTestBehavior.opaque,
                    // Keeps the Waypoint under the cursor: with the default
                    // behaviour the distance travelled before the drag is
                    // recognised is never reported, so it lands short.
                    dragStartBehavior: DragStartBehavior.down,
                    onTap: () => widget.onEditWaypoint(waypoint),
                    onPanStart: (_) => setState(() {
                      final origin = _vertexToScreen(waypoint, size);
                      _movingWaypoint = waypoint;
                      _movingWaypointOrigin = origin;
                      _movingWaypointRawPoint = origin;
                    }),
                    onPanUpdate: (details) => setState(() {
                      final current = _movingWaypointRawPoint;
                      if (current != null) {
                        _movingWaypointRawPoint = current + details.delta;
                      }
                    }),
                    onPanEnd: (_) => _finishWaypointMove(size),
                    onPanCancel: () => setState(() {
                      _movingWaypoint = null;
                      _movingWaypointOrigin = null;
                      _movingWaypointRawPoint = null;
                    }),
                  ),
                ),
              ),
          if (_movingWaypoint != null)
            IgnorePointer(
              child: CustomPaint(
                painter: _WaypointDragPainter(
                  original: _vertexToScreen(_movingWaypoint!, size),
                  current: _movingWaypointScreenPoint,
                  neighbors: [
                    for (final lane in widget.recommendedLanes)
                      if ((lane.$1 - _movingWaypoint!).distance <= .01)
                        _vertexToScreen(lane.$2, size)
                      else if ((lane.$2 - _movingWaypoint!).distance <= .01)
                        _vertexToScreen(lane.$1, size),
                  ],
                  allowed: _waypointDropAllowed(size),
                ),
              ),
            ),
          if (!widget.waypointMode &&
              _hoveredWaypoint != null &&
              _waypointHoverPosition != null &&
              _movingWaypoint == null)
            Positioned(
              left: _waypointHoverPosition!.dx + 210 <= size.width
                  ? _waypointHoverPosition!.dx + 16
                  : math.max(0, _waypointHoverPosition!.dx - 202),
              top: _waypointHoverPosition!.dy + 82 <= size.height
                  ? _waypointHoverPosition!.dy + 16
                  : math.max(0, _waypointHoverPosition!.dy - 76),
              child: IgnorePointer(
                child: _WaypointHoverBadge(
                  name: widget.waypointNames[_hoveredWaypoint!] ?? '',
                  category: widget.waypointTypes[_hoveredWaypoint!] ?? '대기',
                ),
              ),
            ),
          if ((widget.eraseMode && widget.mask != null) ||
              widget.measurementMode)
            MouseRegion(
              cursor: SystemMouseCursors.precise,
              child: GestureDetector(
                behavior: HitTestBehavior.opaque,
                onPanStart: (details) => setState(() {
                  _start = details.localPosition;
                  _current = details.localPosition;
                }),
                onPanUpdate: (details) => setState(() {
                  final position = details.localPosition;
                  final start = _start;
                  if (widget.measurementMode && start != null) {
                    final delta = position - start;
                    _current = delta.dx.abs() >= delta.dy.abs()
                        ? Offset(position.dx, start.dy)
                        : Offset(start.dx, position.dy);
                  } else {
                    _current = position;
                  }
                }),
                onPanEnd: (_) => widget.measurementMode
                    ? _finishMeasurement(size)
                    : _finishSelection(size),
                onPanCancel: () => setState(() {
                  _start = null;
                  _current = null;
                }),
                child: CustomPaint(
                  painter: widget.measurementMode
                      ? _MeasurementDraftPainter(start: _start, end: _current)
                      : _WallSelectionPainter(selection: _selection),
                ),
              ),
            ),
          if (widget.measurementMode)
            Positioned(
              top: _measurementBadgeOffset.dy.clamp(
                0,
                math.max(0, size.height - 44),
              ),
              left: _measurementBadgeOffset.dx.clamp(
                0,
                math.max(0, size.width - 360),
              ),
              child: GestureDetector(
                behavior: HitTestBehavior.opaque,
                onPanUpdate: (details) => setState(() {
                  _measurementBadgeOffset = Offset(
                    (_measurementBadgeOffset.dx + details.delta.dx).clamp(
                      0,
                      math.max(0, size.width - 360),
                    ),
                    (_measurementBadgeOffset.dy + details.delta.dy).clamp(
                      0,
                      math.max(0, size.height - 44),
                    ),
                  );
                }),
                child: _MeasurementModeBadge(
                  onClose: widget.onCloseMeasurementMode,
                ),
              ),
            ),
          if (widget.eraseMode)
            const Positioned(
              top: 12,
              left: 12,
              child: IgnorePointer(child: _EraseModeBadge()),
            ),
        ],
      );
    },
  );
}

class _EraseModeBadge extends StatelessWidget {
  const _EraseModeBadge();

  @override
  Widget build(BuildContext context) => DecoratedBox(
    decoration: BoxDecoration(
      color: const Color(0xEFFFFFFF),
      borderRadius: BorderRadius.circular(8),
      boxShadow: const [BoxShadow(color: Color(0x18000000), blurRadius: 8)],
    ),
    child: Padding(
      padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 8),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.select_all, size: 16, color: Color(0xFFEF4444)),
          SizedBox(width: 6),
          Text(
            '지울 글자 영역을 드래그하세요',
            style: TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w700,
              color: Color(0xFF334155),
            ),
          ),
        ],
      ),
    ),
  );
}

class _WaypointCoordinateBadge extends StatelessWidget {
  const _WaypointCoordinateBadge({
    required this.point,
    required this.imagePoint,
    required this.span,
  });

  final Offset point;
  final Offset imagePoint;
  final ({double left, double right, double top, double bottom}) span;

  @override
  Widget build(BuildContext context) => DecoratedBox(
    decoration: BoxDecoration(
      color: const Color(0xEFFFFFFF),
      borderRadius: BorderRadius.circular(7),
      border: Border.all(color: const Color(0xFFCBD5E1)),
      boxShadow: const [BoxShadow(color: Color(0x18000000), blurRadius: 8)],
    ),
    child: Padding(
      padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 9),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'X ${point.dx.toStringAsFixed(1)}  ·  Y ${point.dy.toStringAsFixed(1)}',
            style: const TextStyle(
              color: Color(0xFF0F172A),
              fontSize: 12,
              fontWeight: FontWeight.w800,
            ),
          ),
          const SizedBox(height: 6),
          Text(
            '← 왼쪽 ${(imagePoint.dx - span.left).toStringAsFixed(1)}   오른쪽 ${(span.right - imagePoint.dx).toStringAsFixed(1)} →',
            style: const TextStyle(
              color: Color(0xFF9A3412),
              fontSize: 11,
              fontWeight: FontWeight.w700,
            ),
          ),
          const SizedBox(height: 3),
          Text(
            '↑ 위 ${(imagePoint.dy - span.top).toStringAsFixed(1)}   아래 ${(span.bottom - imagePoint.dy).toStringAsFixed(1)} ↓',
            style: const TextStyle(
              color: Color(0xFF9A3412),
              fontSize: 11,
              fontWeight: FontWeight.w700,
            ),
          ),
        ],
      ),
    ),
  );
}

class _WaypointHoverBadge extends StatelessWidget {
  const _WaypointHoverBadge({required this.name, required this.category});

  final String name;
  final String category;

  @override
  Widget build(BuildContext context) => DecoratedBox(
    decoration: BoxDecoration(
      color: const Color(0xF7FFFFFF),
      borderRadius: BorderRadius.circular(8),
      border: Border.all(color: const Color(0xFFCBD5E1)),
      boxShadow: const [BoxShadow(color: Color(0x22000000), blurRadius: 10)],
    ),
    child: Padding(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            name.trim().isEmpty ? '(이름 없음)' : name,
            style: const TextStyle(
              color: Color(0xFF0F172A),
              fontSize: 13,
              fontWeight: FontWeight.w800,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            '카테고리 · $category',
            style: const TextStyle(
              color: Color(0xFF64748B),
              fontSize: 11,
              fontWeight: FontWeight.w600,
            ),
          ),
        ],
      ),
    ),
  );
}

class _WaypointWallDistancePainter extends CustomPainter {
  const _WaypointWallDistancePainter({
    required this.point,
    required this.span,
    required this.sourceSize,
    required this.waypoints,
  });

  final Offset point;
  final ({double left, double right, double top, double bottom}) span;
  final Size sourceSize;
  final List<Offset> waypoints;

  @override
  void paint(Canvas canvas, Size size) {
    final fitted = applyBoxFit(BoxFit.contain, sourceSize, size).destination;
    final target = Alignment.center.inscribe(fitted, Offset.zero & size);
    Offset convert(Offset value) => Offset(
      target.left + value.dx * target.width / sourceSize.width,
      target.top + value.dy * target.height / sourceSize.height,
    );

    final center = convert(point);
    final left = convert(Offset(span.left, point.dy));
    final right = convert(Offset(span.right, point.dy));
    final top = convert(Offset(point.dx, span.top));
    final bottom = convert(Offset(point.dx, span.bottom));
    final paint = Paint()
      ..color = const Color(0xFFEA580C)
      ..strokeWidth = 1.6
      ..style = PaintingStyle.stroke;

    void arrow(Offset start, Offset end) {
      canvas.drawLine(start, end, paint);
      final direction = (end - start) / (end - start).distance;
      final normal = Offset(-direction.dy, direction.dx);
      const head = 7.0;
      const wing = 4.0;
      canvas.drawLine(start, start + direction * head + normal * wing, paint);
      canvas.drawLine(start, start + direction * head - normal * wing, paint);
      canvas.drawLine(end, end - direction * head + normal * wing, paint);
      canvas.drawLine(end, end - direction * head - normal * wing, paint);
    }

    void label(String text, Offset position) {
      final painter = TextPainter(
        text: TextSpan(
          text: text,
          style: const TextStyle(
            color: Color(0xFF9A3412),
            fontSize: 11,
            fontWeight: FontWeight.w800,
            backgroundColor: Color(0xEFFFFFFF),
          ),
        ),
        textDirection: TextDirection.ltr,
      )..layout();
      painter.paint(
        canvas,
        position - Offset(painter.width / 2, painter.height / 2),
      );
    }

    final sourceTolerance = 10 * sourceSize.width / target.width;
    final horizontalCrossings = waypoints
        .where(
          (waypoint) =>
              (waypoint.dy - point.dy).abs() <= sourceTolerance &&
              waypoint.dx > span.left &&
              waypoint.dx < span.right,
        )
        .toList();
    final verticalCrossings = waypoints
        .where(
          (waypoint) =>
              (waypoint.dx - point.dx).abs() <= sourceTolerance &&
              waypoint.dy > span.top &&
              waypoint.dy < span.bottom,
        )
        .toList();

    if (horizontalCrossings.isEmpty) {
      if ((center - left).distance > 14) {
        arrow(left, center);
        label(
          '좌 ${(point.dx - span.left).toStringAsFixed(1)}',
          Offset((left.dx + center.dx) / 2, center.dy - 12),
        );
      }
      if ((right - center).distance > 14) {
        arrow(center, right);
        label(
          '우 ${(span.right - point.dx).toStringAsFixed(1)}',
          Offset((center.dx + right.dx) / 2, center.dy - 12),
        );
      }
    } else {
      final stops = <double>[
        span.left,
        point.dx,
        ...horizontalCrossings.map((waypoint) => waypoint.dx),
        span.right,
      ]..sort();
      for (var i = 0; i < stops.length - 1; i++) {
        final start = Offset(stops[i], point.dy);
        final end = Offset(stops[i + 1], point.dy);
        final screenStart = convert(start);
        final screenEnd = convert(end);
        if ((screenEnd - screenStart).distance <= 14) continue;
        arrow(screenStart, screenEnd);
        label(
          '길이 ${(stops[i + 1] - stops[i]).toStringAsFixed(1)}',
          Offset((screenStart.dx + screenEnd.dx) / 2, center.dy - 12),
        );
      }
    }

    if (verticalCrossings.isEmpty) {
      if ((center - top).distance > 14) {
        arrow(top, center);
        label(
          '위 ${(point.dy - span.top).toStringAsFixed(1)}',
          Offset(center.dx + 30, (top.dy + center.dy) / 2),
        );
      }
      if ((bottom - center).distance > 14) {
        arrow(center, bottom);
        label(
          '아래 ${(span.bottom - point.dy).toStringAsFixed(1)}',
          Offset(center.dx + 34, (center.dy + bottom.dy) / 2),
        );
      }
    } else {
      final stops = <double>[
        span.top,
        point.dy,
        ...verticalCrossings.map((waypoint) => waypoint.dy),
        span.bottom,
      ]..sort();
      for (var i = 0; i < stops.length - 1; i++) {
        final start = Offset(point.dx, stops[i]);
        final end = Offset(point.dx, stops[i + 1]);
        final screenStart = convert(start);
        final screenEnd = convert(end);
        if ((screenEnd - screenStart).distance <= 14) continue;
        arrow(screenStart, screenEnd);
        label(
          '길이 ${(stops[i + 1] - stops[i]).toStringAsFixed(1)}',
          Offset(center.dx + 38, (screenStart.dy + screenEnd.dy) / 2),
        );
      }
    }
    for (final waypoint in {...horizontalCrossings, ...verticalCrossings}) {
      final screenPoint = convert(waypoint);
      canvas.drawCircle(
        screenPoint,
        5,
        Paint()..color = const Color(0xFF2563EB),
      );
      canvas.drawCircle(
        screenPoint,
        7,
        Paint()
          ..color = Colors.white
          ..style = PaintingStyle.stroke
          ..strokeWidth = 2,
      );
    }
    canvas.drawCircle(center, 3, Paint()..color = const Color(0xFFEA580C));
  }

  @override
  bool shouldRepaint(covariant _WaypointWallDistancePainter oldDelegate) =>
      oldDelegate.point != point ||
      oldDelegate.span != span ||
      oldDelegate.sourceSize != sourceSize ||
      oldDelegate.waypoints != waypoints;
}

class _MeasurementModeBadge extends StatelessWidget {
  const _MeasurementModeBadge({required this.onClose});
  final VoidCallback onClose;

  @override
  Widget build(BuildContext context) => DecoratedBox(
    decoration: BoxDecoration(
      color: const Color(0xEFFFFFFF),
      borderRadius: BorderRadius.circular(8),
      boxShadow: const [BoxShadow(color: Color(0x18000000), blurRadius: 8)],
    ),
    child: Padding(
      padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 8),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.drag_indicator, size: 17, color: Color(0xFF94A3B8)),
          SizedBox(width: 4),
          Icon(Icons.straighten, size: 16, color: Color(0xFF2563EB)),
          SizedBox(width: 6),
          const Text(
            '실제 길이를 아는 가로/세로 라인을 드래그하세요',
            style: TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w700,
              color: Color(0xFF334155),
            ),
          ),
          const SizedBox(width: 8),
          const Text(
            '이동 가능',
            style: TextStyle(fontSize: 10, color: Color(0xFF94A3B8)),
          ),
          const SizedBox(width: 5),
          InkWell(
            onTap: onClose,
            customBorder: const CircleBorder(),
            child: const Padding(
              padding: EdgeInsets.all(3),
              child: Icon(Icons.close, size: 16, color: Color(0xFF64748B)),
            ),
          ),
        ],
      ),
    ),
  );
}

class _MeasurementDraftPainter extends CustomPainter {
  const _MeasurementDraftPainter({required this.start, required this.end});
  final Offset? start;
  final Offset? end;

  @override
  void paint(Canvas canvas, Size size) {
    if (start == null || end == null) return;
    final paint = Paint()
      ..color = const Color(0xFF2563EB)
      ..strokeWidth = 3
      ..strokeCap = StrokeCap.round;
    canvas.drawLine(start!, end!, paint);
    canvas.drawCircle(start!, 5, Paint()..color = Colors.white);
    canvas.drawCircle(start!, 5, paint..style = PaintingStyle.stroke);
    canvas.drawCircle(end!, 5, Paint()..color = Colors.white);
    canvas.drawCircle(end!, 5, paint);
  }

  @override
  bool shouldRepaint(covariant _MeasurementDraftPainter oldDelegate) =>
      oldDelegate.start != start || oldDelegate.end != end;
}

class _MeasurementPainter extends CustomPainter {
  const _MeasurementPainter({
    required this.measurement,
    required this.sourceSize,
    required this.selected,
  });
  final _MapMeasurement measurement;
  final Size sourceSize;
  final bool selected;

  @override
  void paint(Canvas canvas, Size size) {
    final fitted = applyBoxFit(BoxFit.contain, sourceSize, size).destination;
    final target = Alignment.center.inscribe(fitted, Offset.zero & size);
    Offset convert(Offset point) => Offset(
      target.left + point.dx * target.width / sourceSize.width,
      target.top + point.dy * target.height / sourceSize.height,
    );
    final start = convert(measurement.start);
    final end = convert(measurement.end);
    final paint = Paint()
      ..color = selected ? const Color(0xFFEF4444) : const Color(0xFF0EA5E9)
      ..strokeWidth = selected ? 4 : 3
      ..strokeCap = StrokeCap.round;
    canvas.drawLine(start, end, paint);
    canvas.drawCircle(start, 5, Paint()..color = Colors.white);
    canvas.drawCircle(start, 5, paint..style = PaintingStyle.stroke);
    canvas.drawCircle(end, 5, Paint()..color = Colors.white);
    canvas.drawCircle(end, 5, paint);

    final label = TextPainter(
      text: TextSpan(
        text: '${measurement.length} ${measurement.unit}',
        style: const TextStyle(
          color: Colors.white,
          fontSize: 12,
          fontWeight: FontWeight.w700,
        ),
      ),
      textDirection: TextDirection.ltr,
    )..layout();
    final center = Offset((start.dx + end.dx) / 2, (start.dy + end.dy) / 2);
    final labelRect = Rect.fromCenter(
      center: center,
      width: label.width + 16,
      height: label.height + 10,
    );
    canvas.drawRRect(
      RRect.fromRectAndRadius(labelRect, const Radius.circular(6)),
      Paint()
        ..color = selected ? const Color(0xFFDC2626) : const Color(0xFF0284C7),
    );
    label.paint(canvas, Offset(labelRect.left + 8, labelRect.top + 5));
  }

  @override
  bool shouldRepaint(covariant _MeasurementPainter oldDelegate) =>
      oldDelegate.measurement != measurement ||
      oldDelegate.sourceSize != sourceSize ||
      oldDelegate.selected != selected;
}

class _LanePainter extends CustomPainter {
  const _LanePainter({
    required this.lanes,
    required this.directions,
    required this.waypoints,
    required this.waypointNames,
    required this.waypointTypes,
    required this.activeEndpoint,
    required this.sourceSize,
  });

  final List<(Offset, Offset)> lanes;
  final Map<(Offset, Offset), String> directions;
  final List<Offset> waypoints;
  final Map<Offset, String> waypointNames;
  final Map<Offset, String> waypointTypes;
  final Offset? activeEndpoint;
  final Size sourceSize;

  @override
  void paint(Canvas canvas, Size size) {
    final fitted = applyBoxFit(BoxFit.contain, sourceSize, size).destination;
    final target = Alignment.center.inscribe(fitted, Offset.zero & size);
    Offset convert(Offset point) => Offset(
      target.left + point.dx * target.width / sourceSize.width,
      target.top + point.dy * target.height / sourceSize.height,
    );
    final paint = Paint()
      ..color = const Color(0xFF06B6D4)
      ..strokeWidth = 3
      ..strokeCap = StrokeCap.round;
    void drawArrow(Offset from, Offset to, double fraction) {
      final direction = to - from;
      if (direction.distance <= 1) return;
      final unit = direction / direction.distance;
      final normal = Offset(-unit.dy, unit.dx);
      const arrowLength = 9.0;
      const arrowWidth = 5.0;
      final tip = Offset.lerp(from, to, fraction)!;
      final base = tip - unit * arrowLength;
      final path = Path()
        ..moveTo(tip.dx, tip.dy)
        ..lineTo(
          (base + normal * arrowWidth).dx,
          (base + normal * arrowWidth).dy,
        )
        ..lineTo(
          (base - normal * arrowWidth).dx,
          (base - normal * arrowWidth).dy,
        )
        ..close();
      canvas.drawPath(path, paint);
    }

    for (final lane in lanes) {
      final start = convert(lane.$1);
      final end = convert(lane.$2);
      canvas.drawLine(start, end, paint);
      final laneDirection = directions[lane] ?? '양방향';
      if (laneDirection == '정방향') {
        drawArrow(start, end, .62);
      } else if (laneDirection == '역방향') {
        drawArrow(end, start, .62);
      } else {
        drawArrow(start, end, .38);
        drawArrow(end, start, .38);
      }
    }
    for (var i = 0; i < waypoints.length; i++) {
      final point = convert(waypoints[i]);
      if (waypointTypes[waypoints[i]] == '설비') {
        final equipmentRect = Rect.fromCenter(
          center: point,
          width: 22,
          height: 22,
        );
        canvas.drawRRect(
          RRect.fromRectAndRadius(
            equipmentRect.inflate(2),
            const Radius.circular(6),
          ),
          Paint()..color = const Color(0xFFFFFFFF),
        );
        canvas.drawRRect(
          RRect.fromRectAndRadius(equipmentRect, const Radius.circular(5)),
          Paint()..color = const Color(0xFF7C3AED),
        );
        canvas.drawCircle(point, 4, Paint()..color = const Color(0xFFFFFFFF));
      } else {
        canvas.drawCircle(point, 12, Paint()..color = const Color(0xFFFFFFFF));
        canvas.drawCircle(point, 10, paint);
      }
    }
    final waypointObstacles = [
      for (final waypoint in waypoints)
        Rect.fromCircle(center: convert(waypoint), radius: 14),
    ];
    final occupiedLabels = <Rect>[];
    for (final waypoint in waypoints) {
      final name = (waypointNames[waypoint] ?? '').trim();
      if (name.isEmpty) continue;
      final center = convert(waypoint);
      final label = TextPainter(
        text: TextSpan(
          text: name,
          style: const TextStyle(
            color: Color(0xFF0F172A),
            fontSize: 11,
            fontWeight: FontWeight.w700,
          ),
        ),
        textDirection: TextDirection.ltr,
        maxLines: 1,
        ellipsis: '…',
      )..layout(maxWidth: 160);
      final labelSize = Size(label.width + 12, label.height + 6);
      final candidates = <Rect>[
        Rect.fromLTWH(
          center.dx + 16,
          center.dy - labelSize.height / 2,
          labelSize.width,
          labelSize.height,
        ),
        Rect.fromLTWH(
          center.dx - 16 - labelSize.width,
          center.dy - labelSize.height / 2,
          labelSize.width,
          labelSize.height,
        ),
        Rect.fromLTWH(
          center.dx - labelSize.width / 2,
          center.dy - 16 - labelSize.height,
          labelSize.width,
          labelSize.height,
        ),
        Rect.fromLTWH(
          center.dx - labelSize.width / 2,
          center.dy + 16,
          labelSize.width,
          labelSize.height,
        ),
      ];
      final canvasBounds = Offset.zero & size;
      bool isAvailable(Rect candidate) =>
          canvasBounds.contains(candidate.topLeft) &&
          canvasBounds.contains(candidate.bottomRight) &&
          !occupiedLabels.any((rect) => rect.inflate(3).overlaps(candidate)) &&
          !waypointObstacles.any((rect) => rect.overlaps(candidate));
      final labelRect = candidates.firstWhere(
        isAvailable,
        orElse: () => candidates.reduce((best, candidate) {
          int overlapCount(Rect rect) =>
              occupiedLabels.where((used) => used.overlaps(rect)).length +
              waypointObstacles.where((point) => point.overlaps(rect)).length;
          return overlapCount(candidate) < overlapCount(best)
              ? candidate
              : best;
        }),
      );
      occupiedLabels.add(labelRect);
      canvas.drawRRect(
        RRect.fromRectAndRadius(labelRect, const Radius.circular(5)),
        Paint()..color = const Color(0xEFFFFFFF),
      );
      canvas.drawRRect(
        RRect.fromRectAndRadius(labelRect, const Radius.circular(5)),
        Paint()
          ..color = const Color(0x330F172A)
          ..style = PaintingStyle.stroke,
      );
      label.paint(canvas, Offset(labelRect.left + 6, labelRect.top + 3));
    }
    if (activeEndpoint != null) {
      final point = convert(activeEndpoint!);
      canvas.drawCircle(
        point,
        17,
        Paint()
          ..color = const Color(0xFFF59E0B)
          ..style = PaintingStyle.stroke
          ..strokeWidth = 4,
      );
      canvas.drawCircle(
        point,
        13,
        Paint()
          ..color = const Color(0x66FDE68A)
          ..style = PaintingStyle.fill,
      );
    }
  }

  @override
  bool shouldRepaint(covariant _LanePainter oldDelegate) =>
      oldDelegate.lanes != lanes ||
      oldDelegate.directions != directions ||
      oldDelegate.waypoints != waypoints ||
      oldDelegate.waypointNames != waypointNames ||
      oldDelegate.waypointTypes != waypointTypes ||
      oldDelegate.activeEndpoint != activeEndpoint ||
      oldDelegate.sourceSize != sourceSize;
}

class _VertexLabelPainter extends CustomPainter {
  const _VertexLabelPainter({
    required this.vertices,
    required this.sourceSize,
    required this.revision,
  });

  final List<Offset> vertices;
  final Size sourceSize;
  final int revision;

  @override
  void paint(Canvas canvas, Size size) {
    final fitted = applyBoxFit(BoxFit.contain, sourceSize, size).destination;
    final target = Alignment.center.inscribe(fitted, Offset.zero & size);
    Offset convert(Offset point) => Offset(
      target.left + point.dx * target.width / sourceSize.width,
      target.top + point.dy * target.height / sourceSize.height,
    );

    for (var i = 0; i < vertices.length; i++) {
      final center = convert(vertices[i]);
      canvas.drawCircle(center, 7, Paint()..color = const Color(0xEFFFFFFF));
      canvas.drawCircle(
        center,
        7,
        Paint()
          ..color = const Color(0xFF0F172A)
          ..style = PaintingStyle.stroke
          ..strokeWidth = 1,
      );
      final label = TextPainter(
        text: TextSpan(
          text: '$i',
          style: const TextStyle(
            color: Color(0xFF0F172A),
            fontSize: 8,
            fontWeight: FontWeight.w800,
          ),
        ),
        textDirection: TextDirection.ltr,
      )..layout();
      label.paint(canvas, center - Offset(label.width / 2, label.height / 2));
    }
  }

  @override
  bool shouldRepaint(covariant _VertexLabelPainter oldDelegate) =>
      oldDelegate.revision != revision ||
      oldDelegate.vertices != vertices ||
      oldDelegate.sourceSize != sourceSize;
}

class _PendingVertexPainter extends CustomPainter {
  const _PendingVertexPainter({required this.vertex, required this.sourceSize});
  final Offset? vertex;
  final Size sourceSize;

  @override
  void paint(Canvas canvas, Size size) {
    final point = vertex;
    if (point == null) return;
    final fitted = applyBoxFit(BoxFit.contain, sourceSize, size).destination;
    final target = Alignment.center.inscribe(fitted, Offset.zero & size);
    final center = Offset(
      target.left + point.dx * target.width / sourceSize.width,
      target.top + point.dy * target.height / sourceSize.height,
    );
    canvas.drawCircle(
      center,
      11,
      Paint()
        ..color = const Color(0xFFEF4444)
        ..style = PaintingStyle.stroke
        ..strokeWidth = 3,
    );
  }

  @override
  bool shouldRepaint(covariant _PendingVertexPainter oldDelegate) =>
      oldDelegate.vertex != vertex || oldDelegate.sourceSize != sourceSize;
}

class _EndpointMovePainter extends CustomPainter {
  const _EndpointMovePainter({required this.original, required this.current});
  final Offset? original;
  final Offset? current;

  @override
  void paint(Canvas canvas, Size size) {
    if (original == null || current == null) return;
    canvas.drawLine(
      original!,
      current!,
      Paint()
        ..color = const Color(0xFFEF4444)
        ..strokeWidth = 2
        ..strokeCap = StrokeCap.round,
    );
    canvas.drawCircle(
      current!,
      9,
      Paint()
        ..color = const Color(0xFFEF4444)
        ..style = PaintingStyle.stroke
        ..strokeWidth = 3,
    );
  }

  @override
  bool shouldRepaint(covariant _EndpointMovePainter oldDelegate) =>
      oldDelegate.original != original || oldDelegate.current != current;
}

/// Preview drawn while a Waypoint is being dragged: the Lanes that follow it
/// rubber-band to the pointer, and the marker turns red as soon as the drop
/// would be refused, so the verdict is visible before the button is released.
class _WaypointDragPainter extends CustomPainter {
  const _WaypointDragPainter({
    required this.original,
    required this.current,
    required this.neighbors,
    required this.allowed,
  });

  final Offset original;
  final Offset? current;
  final List<Offset> neighbors;
  final bool allowed;

  @override
  void paint(Canvas canvas, Size size) {
    final target = current;
    if (target == null) return;
    final color = allowed ? const Color(0xFF16A34A) : const Color(0xFFEF4444);
    for (final neighbor in neighbors) {
      canvas.drawLine(
        neighbor,
        target,
        Paint()
          ..color = color.withValues(alpha: .75)
          ..strokeWidth = 2.4
          ..strokeCap = StrokeCap.round,
      );
    }
    canvas.drawCircle(original, 6, Paint()..color = const Color(0x33475569));
    canvas.drawLine(
      original,
      target,
      Paint()
        ..color = const Color(0x66475569)
        ..strokeWidth = 1.4,
    );
    canvas.drawCircle(target, 11, Paint()..color = color.withValues(alpha: .2));
    canvas.drawCircle(
      target,
      11,
      Paint()
        ..color = color
        ..style = PaintingStyle.stroke
        ..strokeWidth = 3,
    );
  }

  @override
  bool shouldRepaint(covariant _WaypointDragPainter oldDelegate) =>
      oldDelegate.original != original ||
      oldDelegate.current != current ||
      oldDelegate.allowed != allowed ||
      oldDelegate.neighbors.length != neighbors.length;
}

class _WallSelectionPainter extends CustomPainter {
  const _WallSelectionPainter({required this.selection});
  final Rect? selection;

  @override
  void paint(Canvas canvas, Size size) {
    final rect = selection;
    if (rect == null) return;
    canvas.drawRect(rect, Paint()..color = const Color(0x33EF4444));
    canvas.drawRect(
      rect,
      Paint()
        ..color = const Color(0xFFEF4444)
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2,
    );
  }

  @override
  bool shouldRepaint(covariant _WallSelectionPainter oldDelegate) =>
      oldDelegate.selection != selection;
}

class _NonImagePreview extends StatelessWidget {
  const _NonImagePreview({required this.extension});
  final String extension;
  @override
  Widget build(BuildContext context) => Center(
    child: Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(
          extension == 'pdf'
              ? Icons.picture_as_pdf_outlined
              : Icons.architecture_outlined,
          size: 62,
          color: const Color(0xFF64748B),
        ),
        const SizedBox(height: 16),
        Text(
          '${extension.toUpperCase()} 도면을 불러왔습니다',
          style: const TextStyle(
            fontSize: 17,
            fontWeight: FontWeight.w700,
            color: Color(0xFF334155),
          ),
        ),
        const SizedBox(height: 8),
        const Text(
          '서버 변환이 연결되면 이 영역에 도면 미리보기가 표시됩니다.',
          style: TextStyle(color: Color(0xFF64748B)),
        ),
      ],
    ),
  );
}

class _SetupPanel extends StatelessWidget {
  const _SetupPanel({
    required this.drawing,
    required this.stage,
    required this.measurement,
    required this.isMeasurementMode,
    required this.onToggleMeasurement,
    required this.wallColor,
    required this.floorColor,
    required this.wallsDetected,
    required this.floorGenerated,
    required this.isDetectingWalls,
    required this.isGeneratingFloor,
    required this.onDetectWalls,
    required this.onGenerateFloor,
    required this.lanesGenerated,
    required this.waypointMode,
    required this.onToggleWaypoint,
    required this.onWallColorChanged,
    required this.onFloorColorChanged,
    required this.isDeployed,
    required this.onDeploy,
    required this.onGenerateGrid,
    required this.onStageChanged,
  });
  final UploadedDrawing? drawing;
  final MapStage stage;
  final _MapMeasurement? measurement;
  final bool isMeasurementMode;
  final VoidCallback onToggleMeasurement;
  final Color wallColor;
  final Color floorColor;
  final bool wallsDetected;
  final bool floorGenerated;
  final bool isDetectingWalls;
  final bool isGeneratingFloor;
  final VoidCallback onDetectWalls;
  final VoidCallback onGenerateFloor;
  final bool lanesGenerated;
  final bool waypointMode;
  final VoidCallback onToggleWaypoint;
  final ValueChanged<Color> onWallColorChanged;
  final ValueChanged<Color> onFloorColorChanged;
  final bool isDeployed;
  final VoidCallback onDeploy;

  /// 그리드맵만 다시 만든다. 배포 전체를 돌리지 않고 지도만 고칠 때 쓴다.
  final VoidCallback onGenerateGrid;
  final ValueChanged<MapStage> onStageChanged;
  @override
  Widget build(BuildContext context) {
    final enabled = drawing != null;
    final calibrated = measurement != null;
    return Container(
      padding: const EdgeInsets.all(22),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: const Color(0xFFE2E8F0)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            '맵 생성 설정',
            style: TextStyle(
              fontSize: 17,
              fontWeight: FontWeight.w800,
              color: Color(0xFF1E293B),
            ),
          ),
          const SizedBox(height: 7),
          const Text(
            '도면 분석 후 필요한 항목을 확인하세요.',
            style: TextStyle(fontSize: 13, color: Color(0xFF64748B)),
          ),
          const SizedBox(height: 22),
          _InfoField(
            label: '맵 이름',
            value: drawing == null
                ? '도면을 먼저 올려주세요'
                : drawing!.name.split('.').first,
            enabled: enabled,
          ),
          const SizedBox(height: 17),
          const Text(
            '자동 생성 항목',
            style: TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w700,
              color: Color(0xFF64748B),
            ),
          ),
          const SizedBox(height: 10),
          _SettingTile(
            icon: Icons.straighten_outlined,
            title: isMeasurementMode ? '라인을 선택해주세요' : 'Measurement',
            subtitle: measurement == null
                ? '가로 또는 세로의 실제 길이 설정'
                : '${measurement!.length} ${measurement!.unit} 기준 저장됨',
            enabled: enabled,
            checked: measurement != null,
            onTap: onToggleMeasurement,
          ),
          _SettingTile(
            icon: Icons.polyline_outlined,
            title: isDetectingWalls
                ? '벽을 인식하는 중...'
                : wallsDetected
                ? '벽 자동인식 제거하기'
                : '벽 자동 인식',
            subtitle: isDetectingWalls
                ? '이미지 픽셀을 분석하고 있습니다'
                : wallsDetected
                ? '누르면 인식된 벽을 모두 제거합니다'
                : '도면의 외곽선과 장애물 추출',
            enabled: enabled && calibrated,
            checked: wallsDetected,
            onTap: onDetectWalls,
          ),
          AnimatedOpacity(
            duration: const Duration(milliseconds: 180),
            opacity: enabled && calibrated ? 1 : .45,
            child: Padding(
              padding: const EdgeInsets.fromLTRB(47, 0, 0, 10),
              child: Row(
                children: [
                  const Text(
                    '벽 색상',
                    style: TextStyle(
                      fontSize: 11,
                      fontWeight: FontWeight.w700,
                      color: Color(0xFF64748B),
                    ),
                  ),
                  const Spacer(),
                  for (final color in const [
                    Color(0xFF2563EB),
                    Color(0xFFEF4444),
                    Color(0xFFF97316),
                    Color(0xFF16A34A),
                    Color(0xFF9333EA),
                  ])
                    _WallColorButton(
                      color: color,
                      selected: wallColor == color,
                      onTap: enabled && calibrated
                          ? () => onWallColorChanged(color)
                          : null,
                    ),
                ],
              ),
            ),
          ),
          _SettingTile(
            icon: Icons.layers_outlined,
            title: isGeneratingFloor ? 'Floor를 생성하는 중...' : 'Floor 자동 생성',
            subtitle: isGeneratingFloor ? '주행 가능 영역을 분석하고 있습니다' : '주행 가능 영역 생성',
            enabled: enabled && calibrated,
            checked: floorGenerated,
            onTap: onGenerateFloor,
          ),
          AnimatedOpacity(
            duration: const Duration(milliseconds: 180),
            opacity: enabled && calibrated ? 1 : .45,
            child: Padding(
              padding: const EdgeInsets.fromLTRB(47, 0, 0, 10),
              child: Row(
                children: [
                  const Text(
                    'Floor 색상',
                    style: TextStyle(
                      fontSize: 11,
                      fontWeight: FontWeight.w700,
                      color: Color(0xFF64748B),
                    ),
                  ),
                  const Spacer(),
                  for (final color in const [
                    Color(0xFF22C55E),
                    Color(0xFF38BDF8),
                    Color(0xFFFACC15),
                    Color(0xFFF97316),
                    Color(0xFFA855F7),
                  ])
                    _WallColorButton(
                      color: color,
                      selected: floorColor == color,
                      onTap: enabled && calibrated
                          ? () => onFloorColorChanged(color)
                          : null,
                    ),
                ],
              ),
            ),
          ),
          _SettingTile(
            icon: Icons.route_outlined,
            title: waypointMode ? 'Waypoint 입력 완료' : 'Waypoint 입력',
            subtitle: waypointMode ? '도면을 눌러 경로점을 추가하세요' : '경로점을 순서대로 직접 지정',
            enabled: enabled && floorGenerated,
            checked: lanesGenerated,
            onTap: onToggleWaypoint,
          ),
          _SettingTile(
            icon: Icons.pin_drop_outlined,
            title: '로봇·작업 위치',
            subtitle: 'Pinky와 OMX 위치 지정',
            enabled: enabled,
            checked: stage.index >= MapStage.stations.index,
            onTap: () => onStageChanged(MapStage.stations),
          ),
          // 배포하기 안에도 들어 있지만 따로 둔다. 도면의 벽을 고친 뒤 지도만
          // 다시 만들고 싶을 때가 잦고, 이것이 빠지면 로봇이 아예 안 움직인다.
          _SettingTile(
            icon: Icons.grid_on_outlined,
            title: '그리드맵 작성',
            subtitle: 'AMCL·Nav2 가 쓰는 점유격자를 도면에서 만듭니다',
            enabled: enabled && floorGenerated,
            checked: false,
            onTap: onGenerateGrid,
          ),
          const SizedBox(height: 20),
          SizedBox(
            width: double.infinity,
            child: FilledButton.icon(
              onPressed: enabled ? onDeploy : null,
              icon: Icon(
                isDeployed ? Icons.check_circle : Icons.rocket_launch_outlined,
                size: 18,
              ),
              label: Text(isDeployed ? '배포 완료' : '배포 준비 완료'),
              style: FilledButton.styleFrom(
                padding: const EdgeInsets.symmetric(vertical: 16),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(9),
                ),
              ),
            ),
          ),
          const SizedBox(height: 12),
          const Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(Icons.lock_outline, size: 13, color: Color(0xFF94A3B8)),
              SizedBox(width: 5),
              Text(
                '원본 파일은 안전하게 보관됩니다',
                style: TextStyle(fontSize: 11, color: Color(0xFF94A3B8)),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _InfoField extends StatelessWidget {
  const _InfoField({
    required this.label,
    required this.value,
    required this.enabled,
  });
  final String label;
  final String value;
  final bool enabled;
  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Text(
        label,
        style: const TextStyle(
          fontSize: 12,
          fontWeight: FontWeight.w700,
          color: Color(0xFF64748B),
        ),
      ),
      const SizedBox(height: 7),
      Container(
        width: double.infinity,
        padding: const EdgeInsets.symmetric(horizontal: 13, vertical: 13),
        decoration: BoxDecoration(
          color: const Color(0xFFF8FAFC),
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: const Color(0xFFE2E8F0)),
        ),
        child: Text(
          value,
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: TextStyle(
            fontSize: 13,
            color: enabled ? const Color(0xFF334155) : const Color(0xFF94A3B8),
            fontWeight: FontWeight.w600,
          ),
        ),
      ),
    ],
  );
}

class _WallColorButton extends StatelessWidget {
  const _WallColorButton({
    required this.color,
    required this.selected,
    required this.onTap,
  });

  final Color color;
  final bool selected;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(left: 4),
    child: Tooltip(
      message: '벽 오버레이 색상',
      child: InkWell(
        onTap: onTap,
        customBorder: const CircleBorder(),
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 150),
          width: 22,
          height: 22,
          padding: const EdgeInsets.all(3),
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            border: Border.all(
              color: selected ? color : Colors.transparent,
              width: 2,
            ),
          ),
          child: DecoratedBox(
            decoration: BoxDecoration(color: color, shape: BoxShape.circle),
            child: selected
                ? const Icon(Icons.check, size: 12, color: Colors.white)
                : null,
          ),
        ),
      ),
    ),
  );
}

class _WallMask {
  const _WallMask({
    required this.width,
    required this.height,
    required this.sampleSize,
    required this.points,
  });

  final int width;
  final int height;
  final double sampleSize;
  final List<Offset> points;
}

class _AxisWall {
  _AxisWall({
    required this.horizontal,
    required this.axis,
    required this.start,
    required this.end,
  }) : minAxis = axis,
       maxAxis = axis;

  final bool horizontal;
  double axis;
  double minAxis;
  double maxAxis;
  double start;
  double end;
  int _samples = 1;

  double get length => end - start;
  (Offset, Offset) get offsets => horizontal
      ? (Offset(start, axis), Offset(end, axis))
      : (Offset(axis, start), Offset(axis, end));

  _AxisWall copy() =>
      _AxisWall(horizontal: horizontal, axis: axis, start: start, end: end)
        ..minAxis = minAxis
        ..maxAxis = maxAxis
        .._samples = _samples;

  void absorb(_AxisWall other) {
    axis =
        (axis * _samples + other.axis * other._samples) /
        (_samples + other._samples);
    _samples += other._samples;
    minAxis = math.min(minAxis, other.minAxis);
    maxAxis = math.max(maxAxis, other.maxAxis);
    start = math.min(start, other.start);
    end = math.max(end, other.end);
  }

  void chooseFloorBoundary(List<Offset> floorPoints, double sampleSize) {
    final searchBand = sampleSize * 10;
    var minusSide = 0;
    var plusSide = 0;
    for (final point in floorPoints) {
      final along = horizontal ? point.dx : point.dy;
      if (along < start - sampleSize || along > end + sampleSize) continue;
      final across = horizontal ? point.dy : point.dx;
      if (across < minAxis && minAxis - across <= searchBand) {
        minusSide++;
      } else if (across > maxAxis && across - maxAxis <= searchBand) {
        plusSide++;
      }
    }
    // Pick exactly one black-wall/white-floor interface. For walls with floor
    // on both sides, the more exposed side wins; ties use the upper/left edge
    // consistently so the opposite boundary is never duplicated.
    axis = plusSide > minusSide ? maxAxis : minAxis;
  }
}

class _WallOverlayPainter extends CustomPainter {
  const _WallOverlayPainter({
    required this.mask,
    required this.color,
    this.opacity = .72,
  });

  final _WallMask mask;
  final Color color;
  final double opacity;

  @override
  void paint(Canvas canvas, Size size) {
    final source = Size(mask.width.toDouble(), mask.height.toDouble());
    final fitted = applyBoxFit(BoxFit.contain, source, size).destination;
    final target = Alignment.center.inscribe(fitted, Offset.zero & size);
    final scale = target.width / source.width;

    canvas.save();
    canvas.clipRect(target);
    canvas.translate(target.left, target.top);
    canvas.scale(scale);
    canvas.drawPoints(
      ui.PointMode.points,
      mask.points,
      Paint()
        ..color = color.withValues(alpha: opacity)
        ..strokeWidth = mask.sampleSize * 1.55
        ..strokeCap = StrokeCap.square
        ..blendMode = BlendMode.srcOver,
    );
    canvas.restore();
  }

  @override
  bool shouldRepaint(covariant _WallOverlayPainter oldDelegate) =>
      oldDelegate.mask != mask ||
      oldDelegate.color != color ||
      oldDelegate.opacity != opacity;
}

class _VectorWallPainter extends CustomPainter {
  const _VectorWallPainter({
    required this.walls,
    required this.sourceSize,
    required this.color,
  });

  final List<(Offset, Offset)> walls;
  final Size sourceSize;
  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    final fitted = applyBoxFit(BoxFit.contain, sourceSize, size).destination;
    final target = Alignment.center.inscribe(fitted, Offset.zero & size);
    Offset convert(Offset point) => Offset(
      target.left + point.dx * target.width / sourceSize.width,
      target.top + point.dy * target.height / sourceSize.height,
    );
    final paint = Paint()
      ..color = color.withValues(alpha: .9)
      ..strokeWidth = 2.2
      ..strokeCap = StrokeCap.round;
    for (final wall in walls) {
      canvas.drawLine(convert(wall.$1), convert(wall.$2), paint);
    }
  }

  @override
  bool shouldRepaint(covariant _VectorWallPainter oldDelegate) =>
      oldDelegate.walls != walls ||
      oldDelegate.sourceSize != sourceSize ||
      oldDelegate.color != color;
}

class _SettingTile extends StatelessWidget {
  const _SettingTile({
    required this.icon,
    required this.title,
    required this.subtitle,
    required this.enabled,
    required this.checked,
    required this.onTap,
  });
  final IconData icon;
  final String title;
  final String subtitle;
  final bool enabled;
  final bool checked;
  final VoidCallback onTap;
  @override
  Widget build(BuildContext context) => InkWell(
    onTap: enabled ? onTap : null,
    borderRadius: BorderRadius.circular(9),
    child: Padding(
      padding: const EdgeInsets.symmetric(vertical: 10),
      child: Row(
        children: [
          Container(
            width: 36,
            height: 36,
            decoration: BoxDecoration(
              color: enabled
                  ? const Color(0xFFEFF6FF)
                  : const Color(0xFFF1F5F9),
              borderRadius: BorderRadius.circular(8),
            ),
            child: Icon(
              icon,
              size: 19,
              color: enabled
                  ? const Color(0xFF2563EB)
                  : const Color(0xFF94A3B8),
            ),
          ),
          const SizedBox(width: 11),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: TextStyle(
                    fontSize: 13,
                    fontWeight: FontWeight.w700,
                    color: enabled
                        ? const Color(0xFF334155)
                        : const Color(0xFF94A3B8),
                  ),
                ),
                const SizedBox(height: 3),
                Text(
                  subtitle,
                  style: const TextStyle(
                    fontSize: 11,
                    color: Color(0xFF94A3B8),
                  ),
                ),
              ],
            ),
          ),
          Icon(
            checked ? Icons.check_circle : Icons.radio_button_unchecked,
            size: 20,
            color: checked ? const Color(0xFF22C55E) : const Color(0xFFCBD5E1),
          ),
        ],
      ),
    ),
  );
}

/// 프로젝트마다 만들어지는 설정 파일을 설명과 함께 보는 화면.
///
/// 파일 이름만으로는 building.yaml 과 fleet.yaml 이 각각 무엇을 하는지,
/// run_*.sh 를 언제 쓰는지 알 수 없다. 무엇이고 어디에 쓰이는지 함께 보여 준다.
class _ProjectFilesPage extends StatefulWidget {
  const _ProjectFilesPage({
    required this.projectName,
    required this.mapName,
    required this.fleetName,
    required this.robotCount,
    required this.mapDirectory,
    required this.onOpenMap,
    required this.onExport,
    required this.onRun,
    required this.onStop,
  });

  /// 열려 있는 맵 프로젝트. null 이면 아직 저장 전이다.
  final String? projectName;
  final String mapName;
  final String fleetName;
  final int robotCount;
  final String mapDirectory;
  final VoidCallback onOpenMap;
  final Future<void> Function(String mapName, List<MapProjectFile> files)
  onExport;

  /// 앱에서 프로젝트를 띄우고 내린다.
  final Future<void> Function(String mapName) onRun;
  final Future<void> Function() onStop;

  @override
  State<_ProjectFilesPage> createState() => _ProjectFilesPageState();
}

class _ProjectFilesPageState extends State<_ProjectFilesPage> {
  List<MapProjectFile> _files = const [];
  bool _loading = false;
  String? _error;

  static const Map<String, (String, IconData, Color)> _kinds = {
    'building': ('건물 맵', Icons.apartment_outlined, Color(0xFF2563EB)),
    'fleet_adapter': (
      'Fleet Adapter',
      Icons.settings_input_component,
      Color(0xFF7C3AED),
    ),
    'fleet_sim': ('시뮬레이션 로봇', Icons.smart_toy_outlined, Color(0xFF0891B2)),
    'launch': (
      '실행 (Open-RMF)',
      Icons.rocket_launch_outlined,
      Color(0xFF15803D),
    ),
    'bringup': ('실행 (Gazebo)', Icons.view_in_ar_outlined, Color(0xFFEA580C)),
    'bridge': ('토픽 다리', Icons.swap_horiz, Color(0xFF0D9488)),
    'robot': ('로봇별 설정', Icons.folder_outlined, Color(0xFF9333EA)),
    'script': ('셸 스크립트', Icons.terminal, Color(0xFF334155)),
  };

  /// 실행 여부를 실제 프로세스와 맞춰 주는 타이머.
  ///
  /// 프로젝트는 앱 밖에서도 내려간다 — 터미널에서 `stop_<맵>.sh` 를 돌리거나
  /// 프로세스가 죽는다. 그때 앱의 기억을 그대로 두면 `실행` 자리에 `중지` 버튼이
  /// 굳어, 다시 띄울 길이 화면에서 사라진다. 앱을 껐다 켜야만 풀렸다.
  ///
  /// 이 화면이 떠 있는 동안만 돈다. 한 번에 `kill -0` 한 번이라 값이 싸다.
  Timer? _runStateTimer;

  @override
  void initState() {
    super.initState();
    unawaited(_reload());
    unawaited(_syncRunState());
    _runStateTimer = Timer.periodic(
      const Duration(seconds: 3),
      (_) => unawaited(_syncRunState()),
    );
  }

  @override
  void dispose() {
    _runStateTimer?.cancel();
    super.dispose();
  }

  @override
  void didUpdateWidget(_ProjectFilesPage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.projectName != widget.projectName) unawaited(_reload());
  }

  /// 바뀐 때만 다시 그린다. 3초마다 setState 를 부르면 이 화면의 스크롤과
  /// 펼친 항목이 계속 흔들린다.
  Future<void> _syncRunState() async {
    final before = runningProjectName;
    final after = await refreshRunningProject();
    if (!mounted || before == after) return;
    setState(() {});
  }

  Future<void> _reload() async {
    final project = widget.projectName;
    if (project == null) {
      setState(() {
        _files = const [];
        _error = null;
      });
      return;
    }
    setState(() => _loading = true);
    try {
      final files = await loadMapProjectFiles(project);
      if (!mounted) return;
      setState(() {
        _files = files;
        _error = null;
        _loading = false;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _error = '$error';
        _loading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final project = widget.projectName;
    return SingleChildScrollView(
      padding: const EdgeInsets.all(28),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '프로젝트 설정 파일',
                      style: Theme.of(context).textTheme.headlineMedium,
                    ),
                    const SizedBox(height: 6),
                    const Text('맵 프로젝트마다 같은 형식으로 만들어지며 MySQL에 보관됩니다.'),
                  ],
                ),
              ),
              OutlinedButton.icon(
                onPressed: _loading ? null : _reload,
                icon: const Icon(Icons.refresh, size: 18),
                label: const Text('다시 읽기'),
              ),
              const SizedBox(width: 10),
              FilledButton.icon(
                onPressed: project == null || _files.isEmpty
                    ? null
                    : () => unawaited(widget.onExport(project, _files)),
                icon: const Icon(Icons.drive_file_move_outline, size: 18),
                label: const Text('디스크로 내보내기'),
              ),
              const SizedBox(width: 10),
              if (runningProjectName == null)
                FilledButton.icon(
                  onPressed: project == null
                      ? null
                      : () async {
                          await widget.onRun(project);
                          if (mounted) setState(() {});
                        },
                  icon: const Icon(Icons.play_arrow, size: 18),
                  label: const Text('프로젝트 실행'),
                  style: FilledButton.styleFrom(
                    backgroundColor: const Color(0xFF15803D),
                  ),
                )
              else
                FilledButton.icon(
                  onPressed: () async {
                    await widget.onStop();
                    if (mounted) setState(() {});
                  },
                  icon: const Icon(Icons.stop, size: 18),
                  label: Text('$runningProjectName 중지'),
                  style: FilledButton.styleFrom(
                    backgroundColor: const Color(0xFFDC2626),
                  ),
                ),
            ],
          ),
          const SizedBox(height: 16),
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: project == null
                  ? const Color(0xFFEFF6FF)
                  : const Color(0xFFF8FAFC),
              borderRadius: BorderRadius.circular(12),
              border: Border.all(
                color: project == null
                    ? const Color(0xFF93C5FD)
                    : const Color(0xFFE2E8F0),
              ),
            ),
            child: project == null
                ? Row(
                    children: [
                      const Icon(
                        Icons.folder_off_outlined,
                        color: Color(0xFF2563EB),
                      ),
                      const SizedBox(width: 10),
                      const Expanded(
                        child: Text(
                          '열린 맵 프로젝트가 없습니다. 설정 파일은 프로젝트마다 만들어지므로 '
                          '먼저 맵 관리에서 `프로젝트 저장`으로 등록하세요.',
                          style: TextStyle(fontWeight: FontWeight.w700),
                        ),
                      ),
                      TextButton.icon(
                        onPressed: widget.onOpenMap,
                        icon: const Icon(Icons.map_outlined, size: 18),
                        label: const Text('맵 관리로'),
                      ),
                    ],
                  )
                : Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        '$project · 플릿 ${widget.fleetName} · '
                        '로봇 ${widget.robotCount}대 · 파일 ${_files.length}개',
                        style: const TextStyle(fontWeight: FontWeight.w800),
                      ),
                      const SizedBox(height: 6),
                      SelectableText(
                        '내보내는 곳: ${widget.mapDirectory}',
                        style: const TextStyle(
                          fontSize: 12,
                          color: Color(0xFF64748B),
                        ),
                      ),
                      const SizedBox(height: 4),
                      const Text(
                        'ros2 launch 는 파일만 읽습니다. 실행하기 전에 한 번 내보내세요.',
                        style: TextStyle(
                          fontSize: 12,
                          color: Color(0xFF64748B),
                        ),
                      ),
                    ],
                  ),
          ),
          if (_error != null) ...[
            const SizedBox(height: 12),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(
                color: const Color(0xFFFEF2F2),
                borderRadius: BorderRadius.circular(10),
                border: Border.all(color: const Color(0xFFFECACA)),
              ),
              child: SelectableText(
                '설정 파일을 읽지 못했습니다: $_error',
                style: const TextStyle(color: Color(0xFF7F1D1D)),
              ),
            ),
          ],
          const SizedBox(height: 16),
          if (_loading)
            const Padding(
              padding: EdgeInsets.all(40),
              child: Center(child: CircularProgressIndicator()),
            )
          else if (project != null && _files.isEmpty)
            const Padding(
              padding: EdgeInsets.all(40),
              child: Center(
                child: Text(
                  '아직 만들어진 설정 파일이 없습니다.\n'
                  '맵 관리에서 `프로젝트 저장`을 한 번 누르면 만들어집니다.',
                  textAlign: TextAlign.center,
                  style: TextStyle(color: Color(0xFF64748B)),
                ),
              ),
            )
          else
            for (final file in _files) _fileCard(file),
        ],
      ),
    );
  }

  Widget _fileCard(MapProjectFile file) {
    final (label, icon, color) =
        _kinds[file.kind] ??
        ('기타', Icons.insert_drive_file_outlined, const Color(0xFF64748B));
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0xFFE2E8F0)),
      ),
      child: ExpansionTile(
        shape: const Border(),
        collapsedShape: const Border(),
        leading: CircleAvatar(
          backgroundColor: color.withValues(alpha: .12),
          child: Icon(icon, color: color, size: 20),
        ),
        title: Row(
          children: [
            Expanded(
              child: Text(
                file.fileName,
                style: const TextStyle(fontWeight: FontWeight.w800),
              ),
            ),
            Chip(
              label: Text(label),
              labelStyle: TextStyle(fontSize: 11, color: color),
              backgroundColor: color.withValues(alpha: .1),
              side: BorderSide.none,
              visualDensity: VisualDensity.compact,
            ),
            if (file.executable) ...[
              const SizedBox(width: 6),
              const Chip(
                label: Text('실행 가능'),
                labelStyle: TextStyle(fontSize: 11),
                visualDensity: VisualDensity.compact,
                side: BorderSide.none,
              ),
            ],
          ],
        ),
        subtitle: Padding(
          padding: const EdgeInsets.only(top: 6, right: 12),
          child: Text(
            file.description.isEmpty ? '설명이 없습니다.' : file.description,
            style: const TextStyle(fontSize: 12, color: Color(0xFF475569)),
          ),
        ),
        children: [
          Container(
            width: double.infinity,
            constraints: const BoxConstraints(maxHeight: 320),
            margin: const EdgeInsets.fromLTRB(16, 0, 16, 8),
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: const Color(0xFFF8FAFC),
              borderRadius: BorderRadius.circular(8),
              border: Border.all(color: const Color(0xFFE2E8F0)),
            ),
            child: Scrollbar(
              child: SingleChildScrollView(
                child: SelectableText(
                  file.content,
                  style: const TextStyle(
                    fontSize: 12,
                    height: 1.45,
                    fontFamily: 'monospace',
                  ),
                ),
              ),
            ),
          ),
          Padding(
            padding: const EdgeInsets.only(right: 16, bottom: 10),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.end,
              children: [
                Text(
                  '${file.content.length}자 · '
                  '${file.generatedAt.year}-'
                  '${file.generatedAt.month.toString().padLeft(2, '0')}-'
                  '${file.generatedAt.day.toString().padLeft(2, '0')} '
                  '${file.generatedAt.hour.toString().padLeft(2, '0')}:'
                  '${file.generatedAt.minute.toString().padLeft(2, '0')}',
                  style: const TextStyle(
                    fontSize: 12,
                    color: Color(0xFF94A3B8),
                  ),
                ),
                const SizedBox(width: 12),
                TextButton.icon(
                  onPressed: () async {
                    await Clipboard.setData(ClipboardData(text: file.content));
                    if (!mounted) return;
                    ScaffoldMessenger.of(context).showSnackBar(
                      SnackBar(content: Text('${file.fileName} 내용을 복사했습니다.')),
                    );
                  },
                  icon: const Icon(Icons.content_copy_outlined, size: 16),
                  label: const Text('복사'),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

/// 운영 분석 — 설정 기록과 운영 기록을 같은 시간축에서 본다.
///
/// 어제까지 되던 것이 오늘 안 되면 그 사이에 무엇을 바꿨는지 함께 봐야 한다.
/// 설정만 따로, 운영만 따로 보면 "설정을 바꾼 직후에 작업이 실패했다" 같은 것이
/// 눈에 띄지 않는다.
class _OperationsAnalyticsPage extends StatefulWidget {
  const _OperationsAnalyticsPage();

  @override
  State<_OperationsAnalyticsPage> createState() =>
      _OperationsAnalyticsPageState();
}

class _OperationsAnalyticsPageState extends State<_OperationsAnalyticsPage> {
  List<OperationMonth> _months = const [];
  List<OperationDay> _days = const [];
  List<OperationEntry> _entries = const [];
  OperationMonth? _month;
  DateTime? _day;
  final Set<OperationLogKind> _hidden = {};
  bool _loading = false;
  String? _error;

  static const Map<OperationLogKind, Color> _colors = {
    OperationLogKind.setting: Color(0xFF7C3AED),
    OperationLogKind.task: Color(0xFF2563EB),
    OperationLogKind.order: Color(0xFF0891B2),
    OperationLogKind.event: Color(0xFF64748B),
    OperationLogKind.incident: Color(0xFFDC2626),
    OperationLogKind.stock: Color(0xFF15803D),
  };

  static const Map<OperationLogKind, IconData> _icons = {
    OperationLogKind.setting: Icons.tune,
    OperationLogKind.task: Icons.assignment_outlined,
    OperationLogKind.order: Icons.receipt_long_outlined,
    OperationLogKind.event: Icons.article_outlined,
    OperationLogKind.incident: Icons.warning_amber_rounded,
    OperationLogKind.stock: Icons.inventory_2_outlined,
  };

  @override
  void initState() {
    super.initState();
    unawaited(_loadMonths());
  }

  Future<void> _loadMonths() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final months = await loadOperationMonths();
      if (!mounted) return;
      setState(() {
        _months = months;
        _loading = false;
      });
      if (months.isNotEmpty) await _selectMonth(months.first);
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _error = '$error';
        _loading = false;
      });
    }
  }

  Future<void> _selectMonth(OperationMonth month) async {
    setState(() {
      _month = month;
      _loading = true;
      _day = null;
      _entries = const [];
    });
    try {
      final days = await loadOperationDays(month.year, month.month);
      if (!mounted) return;
      setState(() {
        _days = days;
        _loading = false;
      });
      // 기록이 있는 마지막 날을 먼저 보여 준다. 빈 화면으로 시작하면 무엇을
      // 눌러야 하는지 알기 어렵다.
      if (days.isNotEmpty) await _selectDay(days.last.date);
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _error = '$error';
        _loading = false;
      });
    }
  }

  Future<void> _selectDay(DateTime day) async {
    setState(() {
      _day = day;
      _loading = true;
    });
    try {
      final entries = await loadOperationEntries(day);
      if (!mounted) return;
      setState(() {
        _entries = entries;
        _loading = false;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _error = '$error';
        _loading = false;
      });
    }
  }

  List<OperationEntry> get _visible => [
    for (final entry in _entries)
      if (!_hidden.contains(entry.kind)) entry,
  ];

  /// 화면에 보이는 것과 같은 내용을 글로 만든다. 복사해서 붙일 수 있어야 한다.
  String _asText() {
    final day = _day;
    if (day == null) return '';
    final lines = <String>[
      '${day.year}-${day.month.toString().padLeft(2, '0')}-'
          '${day.day.toString().padLeft(2, '0')} 운영 기록',
      '',
    ];
    for (final entry in _visible) {
      lines.add(
        '${entry.timeLabel}  [${entry.kind.label}] ${entry.title}'
        '${entry.detail.isEmpty ? '' : '\n            ${entry.detail}'}'
        '${entry.project == null ? '' : '\n            프로젝트 ${entry.project}'}',
      );
    }
    return lines.join('\n');
  }

  Widget _monthStrip() => SizedBox(
    height: 74,
    child: ListView.separated(
      scrollDirection: Axis.horizontal,
      itemCount: _months.length,
      separatorBuilder: (_, _) => const SizedBox(width: 8),
      itemBuilder: (_, index) {
        final month = _months[index];
        final selected = _month?.key == month.key;
        return InkWell(
          onTap: () => unawaited(_selectMonth(month)),
          borderRadius: BorderRadius.circular(10),
          child: Container(
            width: 132,
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
            decoration: BoxDecoration(
              color: selected ? const Color(0xFF1E293B) : Colors.white,
              borderRadius: BorderRadius.circular(10),
              border: Border.all(
                color: selected
                    ? const Color(0xFF1E293B)
                    : const Color(0xFFE2E8F0),
              ),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Text(
                  month.label,
                  style: TextStyle(
                    fontWeight: FontWeight.w800,
                    fontSize: 15,
                    color: selected ? Colors.white : const Color(0xFF0F172A),
                  ),
                ),
                const SizedBox(height: 3),
                Text(
                  '기록 ${month.total}건',
                  style: TextStyle(
                    fontSize: 12,
                    color: selected
                        ? const Color(0xFFCBD5E1)
                        : const Color(0xFF64748B),
                  ),
                ),
              ],
            ),
          ),
        );
      },
    ),
  );

  /// 날짜별 막대. 높이가 그날의 기록 수, 색이 갈래다.
  Widget _dayChart() {
    if (_days.isEmpty) {
      return const Padding(
        padding: EdgeInsets.symmetric(vertical: 26),
        child: Text(
          '이 달에는 기록이 없습니다.',
          style: TextStyle(color: Color(0xFF64748B)),
        ),
      );
    }
    final peak = _days
        .map((day) => day.total)
        .reduce((a, b) => a > b ? a : b)
        .toDouble();
    return SizedBox(
      height: 152,
      child: SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.end,
          children: [
            for (final day in _days)
              Builder(
                builder: (context) {
                  final selected =
                      _day != null &&
                      _day!.year == day.date.year &&
                      _day!.month == day.date.month &&
                      _day!.day == day.date.day;
                  return Padding(
                    padding: const EdgeInsets.only(right: 6),
                    child: InkWell(
                      onTap: () => unawaited(_selectDay(day.date)),
                      borderRadius: BorderRadius.circular(6),
                      child: Tooltip(
                        message: [
                          '${day.date.month}월 ${day.date.day}일 · ${day.total}건',
                          for (final kind in OperationLogKind.values)
                            if ((day.counts[kind] ?? 0) > 0)
                              '${kind.label} ${day.counts[kind]}',
                        ].join('\n'),
                        child: Column(
                          mainAxisAlignment: MainAxisAlignment.end,
                          children: [
                            Text(
                              '${day.total}',
                              style: const TextStyle(
                                fontSize: 11,
                                fontWeight: FontWeight.w700,
                                color: Color(0xFF475569),
                              ),
                            ),
                            const SizedBox(height: 3),
                            // 갈래별로 쌓아 올린다. 그날 무엇이 많았는지 색으로
                            // 바로 보인다.
                            SizedBox(
                              width: 26,
                              height: 96,
                              child: Column(
                                mainAxisAlignment: MainAxisAlignment.end,
                                children: [
                                  for (final kind in OperationLogKind.values)
                                    if ((day.counts[kind] ?? 0) > 0)
                                      Container(
                                        width: 26,
                                        height:
                                            96 *
                                            (day.counts[kind]! / peak).clamp(
                                              .04,
                                              1,
                                            ),
                                        color: _colors[kind],
                                      ),
                                ],
                              ),
                            ),
                            const SizedBox(height: 5),
                            Container(
                              width: 26,
                              padding: const EdgeInsets.symmetric(vertical: 2),
                              decoration: BoxDecoration(
                                color: selected
                                    ? const Color(0xFF1E293B)
                                    : Colors.transparent,
                                borderRadius: BorderRadius.circular(4),
                              ),
                              child: Text(
                                '${day.date.day}',
                                textAlign: TextAlign.center,
                                style: TextStyle(
                                  fontSize: 11,
                                  fontWeight: selected
                                      ? FontWeight.w800
                                      : FontWeight.w500,
                                  color: selected
                                      ? Colors.white
                                      : const Color(0xFF64748B),
                                ),
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                  );
                },
              ),
          ],
        ),
      ),
    );
  }

  Widget _legend() {
    final month = _month;
    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: [
        for (final kind in OperationLogKind.values)
          FilterChip(
            selected: !_hidden.contains(kind),
            showCheckmark: false,
            avatar: Icon(_icons[kind], size: 16, color: _colors[kind]),
            label: Text(
              '${kind.label} ${month?.counts[kind] ?? 0}',
              style: const TextStyle(fontSize: 13),
            ),
            selectedColor: _colors[kind]!.withValues(alpha: .12),
            side: BorderSide(
              color: _hidden.contains(kind)
                  ? const Color(0xFFE2E8F0)
                  : _colors[kind]!.withValues(alpha: .5),
            ),
            onSelected: (on) => setState(() {
              if (on) {
                _hidden.remove(kind);
              } else {
                _hidden.add(kind);
              }
            }),
          ),
      ],
    );
  }

  Widget _timeline() {
    final day = _day;
    if (day == null) {
      return const Padding(
        padding: EdgeInsets.symmetric(vertical: 26),
        child: Text(
          '날짜를 고르면 그날의 기록이 나옵니다.',
          style: TextStyle(color: Color(0xFF64748B)),
        ),
      );
    }
    final entries = _visible;
    if (entries.isEmpty) {
      return Padding(
        padding: const EdgeInsets.symmetric(vertical: 26),
        child: Text(
          _entries.isEmpty
              ? '이 날에는 기록이 없습니다.'
              : '고른 갈래에 해당하는 기록이 없습니다. 위에서 갈래를 켜 보세요.',
          style: const TextStyle(color: Color(0xFF64748B)),
        ),
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        for (final entry in entries)
          Container(
            margin: const EdgeInsets.only(bottom: 8),
            padding: const EdgeInsets.fromLTRB(14, 11, 14, 11),
            decoration: BoxDecoration(
              color: Colors.white,
              borderRadius: BorderRadius.circular(9),
              border: Border.all(color: const Color(0xFFE2E8F0)),
            ),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                SizedBox(
                  width: 48,
                  child: Text(
                    entry.timeLabel,
                    style: const TextStyle(
                      fontFeatures: [FontFeature.tabularFigures()],
                      fontWeight: FontWeight.w700,
                      color: Color(0xFF475569),
                    ),
                  ),
                ),
                Container(
                  width: 3,
                  height: 34,
                  margin: const EdgeInsets.only(right: 12),
                  decoration: BoxDecoration(
                    color: _colors[entry.kind],
                    borderRadius: BorderRadius.circular(2),
                  ),
                ),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Icon(
                            _icons[entry.kind],
                            size: 15,
                            color: _colors[entry.kind],
                          ),
                          const SizedBox(width: 6),
                          Flexible(
                            child: SelectableText(
                              entry.title,
                              style: const TextStyle(
                                fontWeight: FontWeight.w700,
                              ),
                            ),
                          ),
                          if (entry.severity != null) ...[
                            const SizedBox(width: 8),
                            _RegistrationBadge(
                              label: entry.severity!,
                              color: _colors[entry.kind]!,
                            ),
                          ],
                          if (entry.project != null) ...[
                            const SizedBox(width: 6),
                            _RegistrationBadge(
                              label: entry.project!,
                              color: const Color(0xFF64748B),
                            ),
                          ],
                        ],
                      ),
                      if (entry.detail.isNotEmpty) ...[
                        const SizedBox(height: 3),
                        SelectableText(
                          entry.detail,
                          style: const TextStyle(
                            fontSize: 13,
                            color: Color(0xFF64748B),
                            height: 1.45,
                          ),
                        ),
                      ],
                    ],
                  ),
                ),
              ],
            ),
          ),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    final day = _day;
    return SingleChildScrollView(
      padding: const EdgeInsets.all(28),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '운영 분석',
                      style: Theme.of(context).textTheme.headlineMedium,
                    ),
                    const SizedBox(height: 6),
                    const Text(
                      '설정을 언제 바꿨는지와 그날 무슨 일이 있었는지를 같은 '
                      '시간축에서 봅니다.',
                    ),
                  ],
                ),
              ),
              if (day != null)
                OutlinedButton.icon(
                  onPressed: () async {
                    await Clipboard.setData(ClipboardData(text: _asText()));
                    if (!context.mounted) return;
                    ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(content: Text('이 날의 기록을 복사했습니다.')),
                    );
                  },
                  icon: const Icon(Icons.copy_outlined, size: 18),
                  label: const Text('복사'),
                ),
              const SizedBox(width: 10),
              OutlinedButton.icon(
                onPressed: _loading ? null : () => unawaited(_loadMonths()),
                icon: const Icon(Icons.refresh, size: 18),
                label: const Text('다시 읽기'),
              ),
            ],
          ),
          const SizedBox(height: 18),
          if (_error != null)
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: const Color(0xFFFEF2F2),
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: const Color(0xFFFECACA)),
              ),
              child: SelectableText(
                '기록을 읽지 못했습니다.\n$_error',
                style: const TextStyle(color: Color(0xFFB91C1C)),
              ),
            )
          else if (_months.isEmpty && !_loading)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 40),
              child: Text(
                '아직 남은 기록이 없습니다.\n'
                '프로젝트를 저장하거나 작업을 실행하면 여기에 쌓입니다.',
                style: TextStyle(color: Color(0xFF64748B), height: 1.6),
              ),
            )
          else ...[
            _monthStrip(),
            const SizedBox(height: 18),
            _legend(),
            const SizedBox(height: 14),
            _dayChart(),
            const SizedBox(height: 20),
            if (day != null)
              Text(
                '${day.year}년 ${day.month}월 ${day.day}일 · '
                '${_visible.length}건',
                style: const TextStyle(
                  fontWeight: FontWeight.w800,
                  fontSize: 16,
                ),
              ),
            const SizedBox(height: 10),
            if (_loading)
              const Padding(
                padding: EdgeInsets.symmetric(vertical: 26),
                child: Center(child: CircularProgressIndicator()),
              )
            else
              _timeline(),
          ],
        ],
      ),
    );
  }
}

/// MySQL에 저장된 프로젝트 설정 스냅샷을 나란히 비교한다.
///
/// 값의 원장은 map_projects / map_project_fleets / map_project_robots /
/// map_project_files다. 도면 bytes와 마스크 점 목록처럼 사람이 비교할 수 없는
/// 큰 값은 크기와 개수로 요약한다.
class _ProjectAnalyticsPage extends StatefulWidget {
  const _ProjectAnalyticsPage();

  @override
  State<_ProjectAnalyticsPage> createState() => _ProjectAnalyticsPageState();
}

class _ProjectAnalyticsSnapshot {
  const _ProjectAnalyticsSnapshot({
    required this.summary,
    required this.values,
    required this.files,
  });

  final MapProjectSummary summary;
  final Map<String, String> values;
  final List<MapProjectFile> files;
}

class _ProjectAnalyticsPageState extends State<_ProjectAnalyticsPage> {
  static const _comparisonSlots = 4;
  static const _rowsPerPage = 50;
  List<MapProjectSummary> _projects = const [];
  final List<String?> _selectedNames = List<String?>.filled(
    _comparisonSlots,
    null,
  );
  final List<_ProjectAnalyticsSnapshot?> _snapshots =
      List<_ProjectAnalyticsSnapshot?>.filled(_comparisonSlots, null);
  bool _loading = false;
  bool _differencesOnly = true;
  int _rowPage = 0;
  String? _error;

  @override
  void initState() {
    super.initState();
    unawaited(_loadProjects());
  }

  Future<void> _loadProjects() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final projects = await listMapProjects();
      if (!mounted) return;
      _projects = projects;
      for (var slot = 0; slot < _comparisonSlots; slot++) {
        _selectedNames[slot] = slot < projects.length
            ? projects[slot].mapName
            : null;
      }
      await _reloadSnapshots();
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = '$error';
      });
    }
  }

  Future<_ProjectAnalyticsSnapshot?> _loadSnapshot(String? name) async {
    if (name == null) return null;
    final summary = _projects.firstWhere((item) => item.mapName == name);
    final payloadText = await loadMapProject(name);
    final fleet = await loadMapProjectFleet(name);
    // 원문까지 네 프로젝트치를 동시에 읽으면 수십 MB 문자열과 렌더 객체가 한
    // 번에 생긴다. 목록에서는 메타데이터만 읽고 원문은 펼칠 때 한 파일만 읽는다.
    final files = await loadMapProjectFileSummaries(name);
    final values = <String, String>{
      '기본.프로젝트명': summary.mapName,
      '기본.도면': summary.drawingName ?? '없음',
      '기본.Waypoint 수': '${summary.waypointCount}',
      '기본.Lane 수': '${summary.laneCount}',
      '기본.building.yaml': summary.hasBuildingYaml ? '있음' : '없음',
      '기본.설정 파일 수': '${files.length}',
    };
    if (payloadText != null && payloadText.isNotEmpty) {
      final payload = jsonDecode(payloadText) as Map<String, dynamic>;
      _flattenProjectValues(values, '맵', payload);
    }
    if (fleet != null) _flattenProjectValues(values, '플릿', fleet);
    return _ProjectAnalyticsSnapshot(
      summary: summary,
      values: values,
      files: files,
    );
  }

  Future<void> _reloadSnapshots() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final snapshots = <_ProjectAnalyticsSnapshot?>[];
      // MySQL 결과와 JSON decode 네 벌의 최고 메모리가 겹치지 않게 순차 로드한다.
      for (final name in _selectedNames) {
        snapshots.add(await _loadSnapshot(name));
      }
      if (!mounted) return;
      setState(() {
        for (var slot = 0; slot < _comparisonSlots; slot++) {
          _snapshots[slot] = snapshots[slot];
        }
        _rowPage = 0;
        _loading = false;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = '$error';
      });
    }
  }

  static final RegExp _secretKey = RegExp(
    r'(password|passwd|secret|token|api[_-]?key|credential)',
    caseSensitive: false,
  );

  static void _flattenProjectValues(
    Map<String, String> output,
    String path,
    dynamic value,
  ) {
    if (path.endsWith('.bytes')) {
      output[path] = value is String ? '바이너리 ${value.length} 문자' : '없음';
      return;
    }
    if (_secretKey.hasMatch(path)) {
      output[path] = value == null ? '없음' : '••••••';
      return;
    }
    if (value is Map) {
      final entries = value.entries.toList()
        ..sort((a, b) => '${a.key}'.compareTo('${b.key}'));
      for (final entry in entries) {
        _flattenProjectValues(output, '$path.${entry.key}', entry.value);
      }
      return;
    }
    if (value is List) {
      // 좌표/마스크/로봇 배열은 전체 원문 대신 개수와, 작은 구조만 펼친다.
      output['$path.개수'] = '${value.length}';
      if (value.length <= 20 && value.every((item) => item is Map)) {
        for (var i = 0; i < value.length; i++) {
          final item = value[i] as Map;
          final identity =
              item['robotId'] ?? item['name'] ?? item['fileName'] ?? i;
          _flattenProjectValues(output, '$path[$identity]', item);
        }
      }
      return;
    }
    output[path] = value == null ? '없음' : '$value';
  }

  List<String> get _keys {
    final keys = <String>{
      for (final snapshot in _snapshots) ...?snapshot?.values.keys,
    }.toList()..sort();
    final selectedCount = _snapshots
        .whereType<_ProjectAnalyticsSnapshot>()
        .length;
    if (!_differencesOnly || selectedCount < 2) return keys;
    return keys.where(_isChanged).toList();
  }

  bool _isChanged(String key) {
    final values = <String?>{
      for (final snapshot in _snapshots)
        if (snapshot != null) snapshot.values[key],
    };
    return values.length > 1;
  }

  Widget _selector(int slot) {
    final value = _selectedNames[slot];
    return DropdownButtonFormField<String>(
      key: ValueKey('project-comparison-$slot:$value'),
      initialValue: value,
      decoration: InputDecoration(
        labelText: slot == 0 ? '기준 프로젝트' : '비교 프로젝트 ${slot + 1}',
        border: const OutlineInputBorder(),
        isDense: true,
      ),
      items: [
        if (slot > 0)
          const DropdownMenuItem(value: null, child: Text('비교 안 함')),
        for (final project in _projects)
          DropdownMenuItem(
            value: project.mapName,
            child: Text(project.mapName, overflow: TextOverflow.ellipsis),
          ),
      ],
      onChanged: (name) {
        if (slot == 0 && name == null) return;
        setState(() {
          _selectedNames[slot] = name;
          _rowPage = 0;
        });
        unawaited(_reloadSnapshots());
      },
    );
  }

  Widget _valueCell(String? value, {required bool changed}) => Container(
    width: double.infinity,
    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 9),
    color: changed ? const Color(0xFFFFF7ED) : Colors.transparent,
    child: SelectableText(
      value ?? '—',
      style: TextStyle(
        fontFamily: value != null && value.length > 30 ? 'monospace' : null,
        fontSize: 13,
        color: value == null
            ? const Color(0xFF94A3B8)
            : const Color(0xFF334155),
      ),
    ),
  );

  Widget _comparisonTable() {
    final keys = _keys;
    if (keys.isEmpty) {
      return const Padding(
        padding: EdgeInsets.symmetric(vertical: 32),
        child: Text('선택한 프로젝트들의 설정 차이가 없습니다.'),
      );
    }
    final pageCount = math.max(1, (keys.length / _rowsPerPage).ceil());
    if (_rowPage >= pageCount) _rowPage = pageCount - 1;
    final start = _rowPage * _rowsPerPage;
    final visibleKeys = keys.skip(start).take(_rowsPerPage).toList();
    return Column(
      children: [
        Row(
          children: [
            Text(
              '${start + 1}–${start + visibleKeys.length} / ${keys.length}개 항목',
            ),
            const Spacer(),
            IconButton(
              tooltip: '이전 페이지',
              onPressed: _rowPage == 0
                  ? null
                  : () => setState(() => _rowPage--),
              icon: const Icon(Icons.chevron_left),
            ),
            Text('${_rowPage + 1} / $pageCount'),
            IconButton(
              tooltip: '다음 페이지',
              onPressed: _rowPage + 1 >= pageCount
                  ? null
                  : () => setState(() => _rowPage++),
              icon: const Icon(Icons.chevron_right),
            ),
          ],
        ),
        const SizedBox(height: 8),
        SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          child: SizedBox(
            width: 1420,
            child: Table(
              columnWidths: const {
                0: FixedColumnWidth(300),
                1: FixedColumnWidth(280),
                2: FixedColumnWidth(280),
                3: FixedColumnWidth(280),
                4: FixedColumnWidth(280),
              },
              border: TableBorder.all(color: const Color(0xFFE2E8F0)),
              children: [
                TableRow(
                  decoration: const BoxDecoration(color: Color(0xFFF8FAFC)),
                  children: [
                    const Padding(
                      padding: EdgeInsets.all(10),
                      child: Text(
                        '설정 항목',
                        style: TextStyle(fontWeight: FontWeight.w800),
                      ),
                    ),
                    for (var slot = 0; slot < _comparisonSlots; slot++)
                      Padding(
                        padding: const EdgeInsets.all(10),
                        child: Text(
                          _selectedNames[slot] ?? '비교 없음',
                          style: const TextStyle(fontWeight: FontWeight.w800),
                        ),
                      ),
                  ],
                ),
                for (final key in visibleKeys)
                  TableRow(
                    children: [
                      Padding(
                        padding: const EdgeInsets.all(10),
                        child: SelectableText(
                          key,
                          style: const TextStyle(
                            fontWeight: FontWeight.w600,
                            fontSize: 13,
                          ),
                        ),
                      ),
                      for (final snapshot in _snapshots)
                        _valueCell(
                          snapshot?.values[key],
                          changed: _isChanged(key),
                        ),
                    ],
                  ),
              ],
            ),
          ),
        ),
      ],
    );
  }

  Widget _fileList(_ProjectAnalyticsSnapshot? snapshot) {
    if (snapshot == null) return const Text('프로젝트를 고르세요.');
    if (snapshot.files.isEmpty) return const Text('보관된 설정 파일이 없습니다.');
    return Column(
      children: [
        for (final file in snapshot.files)
          _LazyProjectFile(mapName: snapshot.summary.mapName, file: file),
      ],
    );
  }

  @override
  Widget build(BuildContext context) => SingleChildScrollView(
    padding: const EdgeInsets.all(28),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    '프로젝트 분석',
                    style: Theme.of(context).textTheme.headlineMedium,
                  ),
                  const SizedBox(height: 6),
                  const Text(
                    'MySQL에 보관된 도면·로봇·안전·RMF·Gazebo·Nav2 설정을 프로젝트별로 비교합니다.',
                  ),
                ],
              ),
            ),
            OutlinedButton.icon(
              onPressed: _loading ? null : () => unawaited(_loadProjects()),
              icon: const Icon(Icons.refresh, size: 18),
              label: const Text('다시 읽기'),
            ),
          ],
        ),
        const SizedBox(height: 18),
        if (_error != null)
          SelectableText(
            '프로젝트 설정을 읽지 못했습니다.\n$_error',
            style: const TextStyle(color: Color(0xFFB91C1C)),
          )
        else if (_projects.isEmpty && !_loading)
          const Text('MySQL에 저장된 프로젝트가 없습니다.')
        else ...[
          Wrap(
            spacing: 12,
            runSpacing: 12,
            children: [
              for (var slot = 0; slot < _comparisonSlots; slot++)
                SizedBox(width: 270, child: _selector(slot)),
            ],
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              FilterChip(
                selected: _differencesOnly,
                label: const Text('다른 항목만'),
                onSelected: (value) => setState(() {
                  _differencesOnly = value;
                  _rowPage = 0;
                }),
              ),
              const SizedBox(width: 12),
              const Expanded(
                child: Text(
                  'SLAM PGM 원본은 현재 프로젝트 파일로 보관되며, MySQL에서는 SLAM 사용 여부와 생성 설정을 비교합니다.',
                  style: TextStyle(fontSize: 12, color: Color(0xFF64748B)),
                ),
              ),
            ],
          ),
          const SizedBox(height: 14),
          if (_loading)
            const Center(
              child: Padding(
                padding: EdgeInsets.all(36),
                child: CircularProgressIndicator(),
              ),
            )
          else ...[
            _comparisonTable(),
            const SizedBox(height: 26),
            Text('설정 파일 원문', style: Theme.of(context).textTheme.titleLarge),
            const SizedBox(height: 6),
            const Text(
              '네 프로젝트의 파일을 가로로 비교할 수 있습니다. 파일을 펼치면 MySQL에 보관된 실제 산출물이 표시됩니다.',
              style: TextStyle(color: Color(0xFF64748B)),
            ),
            const SizedBox(height: 12),
            SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  for (var slot = 0; slot < _comparisonSlots; slot++) ...[
                    SizedBox(
                      width: 330,
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            _selectedNames[slot] ?? '비교 없음',
                            style: const TextStyle(fontWeight: FontWeight.w800),
                          ),
                          const SizedBox(height: 8),
                          _fileList(_snapshots[slot]),
                        ],
                      ),
                    ),
                    if (slot < _comparisonSlots - 1) const SizedBox(width: 24),
                  ],
                ],
              ),
            ),
          ],
        ],
      ],
    ),
  );
}

/// 프로젝트 설정 파일 원문은 사용자가 펼친 한 건만 읽는다.
class _LazyProjectFile extends StatefulWidget {
  const _LazyProjectFile({required this.mapName, required this.file});
  final String mapName;
  final MapProjectFile file;

  @override
  State<_LazyProjectFile> createState() => _LazyProjectFileState();
}

class _LazyProjectFileState extends State<_LazyProjectFile> {
  String? _content;
  String? _error;
  bool _loading = false;

  Future<void> _load(bool expanded) async {
    if (!expanded || _content != null || _loading) return;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final content = await loadMapProjectFileContent(
        widget.mapName,
        widget.file.fileName,
      );
      if (!mounted) return;
      setState(() {
        _content = content ?? '파일 원문이 없습니다.';
        _loading = false;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _error = '$error';
        _loading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) => ExpansionTile(
    tilePadding: EdgeInsets.zero,
    leading: const Icon(Icons.description_outlined),
    title: Text(widget.file.fileName),
    subtitle: Text(
      '${widget.file.kind}'
      '${widget.file.description.isEmpty ? '' : ' · ${widget.file.description}'}',
    ),
    onExpansionChanged: (expanded) => unawaited(_load(expanded)),
    children: [
      Container(
        width: double.infinity,
        constraints: const BoxConstraints(maxHeight: 360),
        padding: const EdgeInsets.all(12),
        color: const Color(0xFF0F172A),
        child: _loading
            ? const Center(child: CircularProgressIndicator())
            : _error != null
            ? SelectableText(
                _error!,
                style: const TextStyle(color: Color(0xFFFCA5A5)),
              )
            : SingleChildScrollView(
                child: SelectableText(
                  _content ?? '펼치면 원문을 읽습니다.',
                  style: const TextStyle(
                    color: Color(0xFFE2E8F0),
                    fontFamily: 'monospace',
                    fontSize: 12,
                  ),
                ),
              ),
      ),
    ],
  );
}

/// 로봇 한 대의 상세. 등록 정보와 지금 상태를 한자리에서 본다.
///
/// 작업 상세는 "이 작업이 어떻게 되고 있나"를 본다. 이것은 "이 로봇이 어떤
/// 로봇이고 지금 어떤가"를 본다. 로봇을 눌렀을 때 작업 이야기가 나오면 찾던
/// 것이 아니다.
/// `자리 맞추기` 버튼. 문제가 있으면 눌러 보기 전에 버튼이 알린다.
class _SpawnCheckButton extends StatelessWidget {
  const _SpawnCheckButton({required this.checks, required this.onPressed});

  final List<SpawnCheck> checks;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    final bad = checks.where((check) => !check.isOk).length;
    final outside = checks
        .where((check) => check.issue == SpawnIssue.outsideFloor)
        .length;
    // 바닥 밖은 이동 로봇을 허공에서 떨어뜨리므로 가장 세게 알린다.
    final color = outside > 0
        ? const Color(0xFFDC2626)
        : bad > 0
        ? const Color(0xFFEA580C)
        : null;
    return Tooltip(
      message: checks.isEmpty
          ? '축척과 등록된 로봇이 있어야 자리를 살필 수 있습니다.'
          : spawnCheckSummary(checks),
      child: TextButton.icon(
        onPressed: onPressed,
        style: color == null
            ? null
            : TextButton.styleFrom(
                foregroundColor: color,
                backgroundColor: color.withValues(alpha: .10),
              ),
        icon: Icon(
          bad > 0 ? Icons.warning_amber_rounded : Icons.my_location,
          size: 18,
        ),
        label: Text(bad > 0 ? '자리 맞추기 · $bad대' : '자리 맞추기'),
      ),
    );
  }
}

/// 등록된 로봇이 설 자리가 지도와 맞는지 살피고 맞춘다.
///
/// 좌표는 눈에 안 보이는 값이라 틀려도 티가 안 난다. 홈1 에 올린 로봇이 건물
/// 밖 허공에서 끝없이 떨어지고 있어도 화면은 멀쩡했다 — 바퀴는 허공에서도
/// 돌아서 odom 이 정상으로 보였기 때문이다. 그래서 사람이 눌러서 확인할 수
/// 있어야 한다.
class _SpawnCheckDialog extends StatefulWidget {
  const _SpawnCheckDialog({
    required this.checksOf,
    required this.metersPerPixel,
    required this.floorBounds,
    required this.onRefit,
    required this.onHeading,
  });

  /// 지금 결과. 맞춘 뒤 다시 부른다.
  final List<SpawnCheck> Function() checksOf;

  final double? metersPerPixel;

  /// 바닥이 있는 범위(m). 자리가 이 밖이면 로봇이 떨어진다.
  final ({double minX, double maxX, double minY, double maxY})? floorBounds;

  /// 지도 기준으로 다시 맞춘다. 몇 대가 바뀌었는지 돌려준다.
  final Future<int> Function() onRefit;

  /// 이 로봇이 그 자리에서 볼 방향을 정한다. 라디안.
  final Future<void> Function(RmfProjectRobot robot, double heading) onHeading;

  @override
  State<_SpawnCheckDialog> createState() => _SpawnCheckDialogState();
}

class _SpawnCheckDialogState extends State<_SpawnCheckDialog> {
  bool _working = false;

  static const Map<SpawnIssue, Color> _colors = {
    SpawnIssue.ok: Color(0xFF16A34A),
    SpawnIssue.outsideFloor: Color(0xFFDC2626),
    SpawnIssue.stale: Color(0xFFEA580C),
    SpawnIssue.noStation: Color(0xFFEA580C),
    SpawnIssue.noCoordinate: Color(0xFF64748B),
  };

  /// 방향은 8방위면 충분하다. 자리에 세우는 것이지 정밀 정렬이 아니다.
  static const List<(double, String)> _headings = [
    (0, '0° 오른쪽'),
    (45, '45°'),
    (90, '90° 위'),
    (135, '135°'),
    (180, '180° 왼쪽'),
    (225, '225°'),
    (270, '270° 아래'),
    (315, '315°'),
  ];

  String _meters(({double x, double y})? point) => point == null
      ? '없음'
      : '${point.x.toStringAsFixed(3)}, ${point.y.toStringAsFixed(3)} m';

  Future<void> _refit() async {
    setState(() => _working = true);
    try {
      final changed = await widget.onRefit();
      if (!mounted) return;
      setState(() {});
      final message = changed == 0
          ? '바꿀 자리가 없었습니다.'
          : '$changed대의 자리를 지도 기준으로 맞췄습니다.';
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            changed == 0
                ? message
                : '$message 이미 Gazebo에 올라간 로봇은 그대로입니다 — '
                      '백엔드를 내렸다가 다시 띄워 주세요.',
          ),
        ),
      );
    } finally {
      if (mounted) setState(() => _working = false);
    }
  }

  String _asText(List<SpawnCheck> checks) {
    final buffer = StringBuffer()
      ..writeln('자리 맞추기')
      ..writeln(spawnCheckSummary(checks))
      ..writeln();
    final scale = widget.metersPerPixel;
    buffer.writeln(
      scale == null
          ? '축척: 없음 (맵 관리에서 길이 기준을 먼저 재야 합니다)'
          : '축척: ${scale.toStringAsFixed(6)} m/px '
                '(${(1 / scale).toStringAsFixed(0)} px/m)',
    );
    final bounds = widget.floorBounds;
    if (bounds != null) {
      buffer.writeln(
        '바닥: x ${bounds.minX.toStringAsFixed(2)} ~ '
        '${bounds.maxX.toStringAsFixed(2)} m · '
        'y ${bounds.minY.toStringAsFixed(2)} ~ '
        '${bounds.maxY.toStringAsFixed(2)} m',
      );
    }
    for (final check in checks) {
      buffer
        ..writeln()
        ..writeln(
          '${check.robot.robotId} · ${check.robot.displayName} '
          '(${check.robot.chargerWaypoint ?? '자리 없음'}) — '
          '${check.issue.label}',
        )
        ..writeln('  저장된 자리: ${_meters(check.stored)}')
        ..writeln('  지도 기준  : ${_meters(check.fromMap)}')
        ..writeln(
          '  방향       : '
          '${(check.robot.spawnHeading * 180 / math.pi).toStringAsFixed(0)}°',
        )
        ..writeln('  ${check.issue.detail}');
    }
    return buffer.toString();
  }

  Widget _summaryLine(String label, String value) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 2),
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(
          width: 52,
          child: Text(
            label,
            style: const TextStyle(
              color: Color(0xFF64748B),
              fontWeight: FontWeight.w700,
            ),
          ),
        ),
        Expanded(child: SelectableText(value)),
      ],
    ),
  );

  Widget _card(SpawnCheck check) {
    final color = _colors[check.issue]!;
    final robot = check.robot;
    final degrees = (robot.spawnHeading * 180 / math.pi) % 360;
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
      decoration: BoxDecoration(
        color: color.withValues(alpha: check.isOk ? .05 : .10),
        borderRadius: BorderRadius.circular(9),
        border: Border.all(color: color, width: check.isOk ? 1 : 2),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(
                check.isOk
                    ? Icons.check_circle_outline
                    : Icons.warning_amber_rounded,
                color: color,
                size: 20,
              ),
              const SizedBox(width: 8),
              Expanded(
                child: SelectableText(
                  '${robot.robotId} · ${robot.displayName}',
                  style: const TextStyle(fontWeight: FontWeight.w800),
                ),
              ),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                decoration: BoxDecoration(
                  color: color,
                  borderRadius: BorderRadius.circular(20),
                ),
                child: Text(
                  check.issue.label,
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 11,
                    fontWeight: FontWeight.w800,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 6),
          _summaryLine(
            '자리',
            '${robot.chargerWaypoint ?? '고르지 않았습니다'}'
                ' (${robot.kind.waypointCategory})',
          ),
          _summaryLine('저장', _meters(check.stored)),
          if (check.fromMap != null &&
              (check.stored == null || check.issue != SpawnIssue.ok))
            _summaryLine('지도', '${_meters(check.fromMap)}  ← 맞추면 이 값이 됩니다'),
          const SizedBox(height: 4),
          SelectableText(
            check.issue.detail,
            style: TextStyle(color: color, fontSize: 12, height: 1.4),
          ),
          // 자리를 못 찾으면 `맞추기` 로도 못 고친다. 눌러도 안 바뀌는 이유를
          // 여기서 알려 준다.
          if (check.fromMap == null && check.issue != SpawnIssue.noStation)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: SelectableText(
                '자리 Waypoint `${robot.chargerWaypoint ?? ''}` 를 지도에서 '
                '못 찾아서 `맞추기` 로는 고칠 수 없습니다. '
                '로봇 등록에서 자리를 다시 골라 주세요.',
                style: TextStyle(color: color, fontSize: 12, height: 1.4),
              ),
            ),
          const SizedBox(height: 8),
          Row(
            children: [
              const SizedBox(
                width: 52,
                child: Text(
                  '방향',
                  style: TextStyle(
                    color: Color(0xFF64748B),
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
              DropdownButton<double>(
                value: _headings
                    .map((item) => item.$1)
                    .firstWhere(
                      (value) => (value - degrees).abs() < .5,
                      orElse: () => 0,
                    ),
                isDense: true,
                underline: const SizedBox.shrink(),
                items: [
                  for (final item in _headings)
                    DropdownMenuItem(value: item.$1, child: Text(item.$2)),
                ],
                onChanged: _working
                    ? null
                    : (value) async {
                        if (value == null) return;
                        await widget.onHeading(robot, value * math.pi / 180);
                        if (mounted) setState(() {});
                      },
              ),
              const SizedBox(width: 10),
              const Expanded(
                child: Text(
                  '이 자리에서 로봇이 볼 방향입니다.',
                  style: TextStyle(color: Color(0xFF64748B), fontSize: 12),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final checks = widget.checksOf();
    final scale = widget.metersPerPixel;
    final bounds = widget.floorBounds;
    final fixable = checks.where((check) => check.willChange).length;
    return AlertDialog(
      title: const Row(
        children: [
          Icon(Icons.my_location, size: 22),
          SizedBox(width: 8),
          Text('자리 맞추기'),
        ],
      ),
      content: SizedBox(
        width: 720,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(11),
              decoration: BoxDecoration(
                color: const Color(0xFFF1F5F9),
                borderRadius: BorderRadius.circular(9),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  _summaryLine(
                    '축척',
                    scale == null
                        ? '없습니다 — 맵 관리에서 길이 기준을 먼저 재 주세요.'
                        : '${scale.toStringAsFixed(6)} m/px '
                              '(${(1 / scale).toStringAsFixed(0)} px/m)',
                  ),
                  _summaryLine(
                    '바닥',
                    bounds == null
                        ? '바닥 영역이 없습니다 — 맵 관리에서 바닥을 먼저 그려 주세요.'
                        : 'x ${bounds.minX.toStringAsFixed(2)} ~ '
                              '${bounds.maxX.toStringAsFixed(2)} m · '
                              'y ${bounds.minY.toStringAsFixed(2)} ~ '
                              '${bounds.maxY.toStringAsFixed(2)} m',
                  ),
                  _summaryLine('결과', spawnCheckSummary(checks)),
                ],
              ),
            ),
            const SizedBox(height: 12),
            Flexible(
              child: checks.isEmpty
                  ? const Padding(
                      padding: EdgeInsets.symmetric(vertical: 24),
                      child: Text(
                        '살펴볼 것이 없습니다.\n\n'
                        '축척(길이 기준)을 재고 로봇을 등록하면 여기서 '
                        '자리가 지도와 맞는지 확인할 수 있습니다.',
                        style: TextStyle(color: Color(0xFF64748B), height: 1.6),
                      ),
                    )
                  : SingleChildScrollView(
                      child: Column(
                        children: [for (final check in checks) _card(check)],
                      ),
                    ),
            ),
          ],
        ),
      ),
      actions: [
        TextButton.icon(
          onPressed: () async {
            await Clipboard.setData(ClipboardData(text: _asText(checks)));
            if (!context.mounted) return;
            ScaffoldMessenger.of(
              context,
            ).showSnackBar(const SnackBar(content: Text('내용을 복사했습니다.')));
          },
          icon: const Icon(Icons.copy_all_outlined, size: 18),
          label: const Text('복사'),
        ),
        FilledButton.icon(
          onPressed: _working || fixable == 0 ? null : _refit,
          icon: _working
              ? const SizedBox(
                  width: 16,
                  height: 16,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const Icon(Icons.auto_fix_high, size: 18),
          label: Text(fixable == 0 ? '맞출 것이 없습니다' : '지도 기준으로 맞추기 · $fixable대'),
        ),
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('닫기'),
        ),
      ],
    );
  }
}

/// 라이다를 로봇 기준으로 그린다.
///
/// 가운데가 로봇이고 위쪽이 로봇의 앞이다. 점 하나가 라이다가 맞힌 곳이다.
class _ScanPainter extends CustomPainter {
  const _ScanPainter({required this.scan, required this.live});

  final RobotScan scan;
  final bool live;

  @override
  void paint(Canvas canvas, Size size) {
    final center = Offset(size.width / 2, size.height / 2);
    final radius = math.min(size.width, size.height) / 2 - 8;

    // 거리를 가늠할 눈금. 최대 거리의 1/3 씩 세 겹.
    final grid = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1
      ..color = const Color(0xFF334155);
    for (var i = 1; i <= 3; i++) {
      canvas.drawCircle(center, radius * i / 3, grid);
    }

    // 로봇의 앞을 가리키는 표. 이것이 없으면 어느 쪽이 앞인지 알 수 없다.
    canvas.drawLine(
      center,
      center + Offset(0, -radius),
      Paint()
        ..strokeWidth = 1
        ..color = const Color(0xFF475569),
    );

    final dot = Paint()
      ..color = live ? const Color(0xFF38BDF8) : const Color(0xFF64748B);
    for (var i = 0; i < scan.ranges.length; i++) {
      final range = scan.ranges[i];
      // 못 잰 값은 그리지 않는다. 최대 거리로 채워 두면 없는 벽이 둘러선다.
      if (range <= scan.rangeMin || range >= scan.rangeMax) continue;
      final point = scanPointOffset(
        angle: scan.angleAt(i),
        range: range,
        maxRange: scan.rangeMax,
        radius: radius,
      );
      canvas.drawCircle(center + Offset(point.dx, point.dy), 1.6, dot);
    }

    // 로봇 자신.
    canvas.drawCircle(center, 3, Paint()..color = const Color(0xFFF97316));
  }

  @override
  bool shouldRepaint(_ScanPainter oldDelegate) =>
      oldDelegate.scan != scan || oldDelegate.live != live;
}

/// 테스트에서 보내기 창만 따로 띄운다.
///
/// 창을 앱 전체로 몰아 열려면 프로젝트를 띄우고 지도를 붙여야 하는데, 그러면
/// 창이 아니라 그 준비 과정을 시험하게 된다. 막는 조건은 `robot_move_command`
/// 쪽에서 따로 본다.
@visibleForTesting
Widget debugRobotMoveDialog({
  required RmfProjectRobot robot,
  required List<String> waypoints,
  String? currentWaypoint,
}) => _RobotMoveDialog(
  robot: robot,
  waypoints: waypoints,
  currentWaypoint: currentWaypoint,
);

/// 로봇 하나를 어느 Waypoint 로 보낼지 고른다.
///
/// 목록만 준다. 지도에서 찍게 하지 않는 것은, RMF 가 **이름**으로 자리를 찾기
/// 때문이다. 지도에서 찍으면 이름 없는 자리도 고를 수 있게 되어, 보낸 뒤에야
/// 갈 수 없다는 답을 받는다.
class _RobotMoveDialog extends StatefulWidget {
  const _RobotMoveDialog({
    required this.robot,
    required this.waypoints,
    this.currentWaypoint,
  });

  final RmfProjectRobot robot;
  final List<String> waypoints;

  /// 지금 서 있다고 아는 자리. 목록에서 표시만 하고 고르지는 못하게 한다.
  final String? currentWaypoint;

  @override
  State<_RobotMoveDialog> createState() => _RobotMoveDialogState();
}

class _RobotMoveDialogState extends State<_RobotMoveDialog> {
  String? _selected;
  String _filter = '';

  /// 이름이 한글이면 RViz 라벨에서는 숫자만 보인다. 여기서는 온전히 보인다 —
  /// 두 화면이 달라 보이는 이유를 한 줄로 밝혀 둔다.
  bool get _hasNonAscii =>
      widget.waypoints.any((name) => name.codeUnits.any((c) => c > 127));

  List<String> get _visible {
    final query = _filter.trim();
    if (query.isEmpty) return widget.waypoints;
    return widget.waypoints
        .where((name) => name.toLowerCase().contains(query.toLowerCase()))
        .toList(growable: false);
  }

  @override
  Widget build(BuildContext context) {
    final visible = _visible;
    return AlertDialog(
      icon: const Icon(Icons.near_me_outlined, size: 30),
      title: Text('${widget.robot.displayName} 보내기'),
      content: SizedBox(
        width: 440,
        height: 460,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              '${widget.robot.robotId} · ${widget.robot.model}',
              style: const TextStyle(fontSize: 12, color: Color(0xFF64748B)),
            ),
            const SizedBox(height: 10),
            // 이 창이 작업 목록과 무엇이 다른지 밝힌다. 작업으로 남는 줄 알고
            // 여기서 여러 번 누르면, 아무 데도 안 쌓이는 것을 보고 안 먹었다고
            // 여긴다.
            Container(
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                color: const Color(0xFFEFF6FF),
                borderRadius: BorderRadius.circular(8),
              ),
              child: const Text(
                '이 지시는 작업 목록에 남지 않습니다. 고른 로봇이 그대로 갑니다 '
                '(입찰 없음).\n경로는 RMF 가 Lane 을 따라 만듭니다.',
                style: TextStyle(fontSize: 12, height: 1.5),
              ),
            ),
            const SizedBox(height: 12),
            if (widget.waypoints.length > 8)
              Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: TextField(
                  decoration: const InputDecoration(
                    isDense: true,
                    prefixIcon: Icon(Icons.search, size: 18),
                    hintText: 'Waypoint 이름으로 찾기',
                    border: OutlineInputBorder(),
                  ),
                  onChanged: (value) => setState(() => _filter = value),
                ),
              ),
            Expanded(
              child: visible.isEmpty
                  ? const Center(
                      child: Text(
                        '찾는 이름이 없습니다.',
                        style: TextStyle(color: Color(0xFF64748B)),
                      ),
                    )
                  : Scrollbar(
                      child: ListView.builder(
                        itemCount: visible.length,
                        itemBuilder: (_, index) {
                          final name = visible[index];
                          final isHere = name == widget.currentWaypoint;
                          final isPicked = name == _selected;
                          return ListTile(
                            dense: true,
                            selected: isPicked,
                            enabled: !isHere,
                            leading: Icon(
                              isPicked
                                  ? Icons.radio_button_checked
                                  : Icons.radio_button_unchecked,
                              size: 18,
                            ),
                            // 있는 자리로 보내는 것은 아무 일도 아닌데, RMF 는
                            // 그것도 받아 성공이라고 답한다.
                            onTap: isHere
                                ? null
                                : () => setState(() => _selected = name),
                            title: Text(name),
                            subtitle: isHere ? const Text('지금 이 자리입니다') : null,
                          );
                        },
                      ),
                    ),
            ),
            if (_hasNonAscii)
              const Padding(
                padding: EdgeInsets.only(top: 8),
                child: Text(
                  'RViz 라벨에는 한글이 빠지고 숫자만 보입니다. 이름 자체는 '
                  '여기 보이는 그대로입니다.',
                  style: TextStyle(fontSize: 11, color: Color(0xFF94A3B8)),
                ),
              ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('취소'),
        ),
        FilledButton.icon(
          onPressed: _selected == null
              ? null
              : () => Navigator.pop(context, _selected),
          icon: const Icon(Icons.send, size: 18),
          label: const Text('보내기'),
        ),
      ],
    );
  }
}

class _RobotDetailDialog extends StatefulWidget {
  const _RobotDetailDialog({
    required this.robotId,
    required this.registered,
    required this.robotOf,
    required this.tasksOf,
    required this.telemetry,
    required this.sensorsOf,
    required this.toFloor,
    required this.metersPerPixel,
    required this.waypointLabel,
    required this.mapDirectory,
    required this.mapName,
    required this.backendRunning,
    required this.onStartBackend,
    required this.onResubscribe,
  });

  final String robotId;

  /// 프로젝트 등록 정보. 등록되지 않은 것(사람·휴머노이드)이면 null.
  final RmfProjectRobot? registered;

  /// 지도에 올라와 있는 로봇. 아직 배치하지 않았으면 null.
  final _MockRobot? Function() robotOf;

  /// 이 로봇이 맡은 작업.
  final List<_MockTask> Function() tasksOf;
  final RobotTelemetryStatus Function() telemetry;

  /// 이 로봇의 라이다·카메라. relay 노드가 파일로 내려 준 것을 읽는다.
  final RobotSensors Function() sensorsOf;

  final Offset Function(Offset point) toFloor;
  final double? metersPerPixel;
  final String Function(Offset point) waypointLabel;

  /// 배포 산출물이 있는 곳. 이 로봇만 올리는 launch 가 그 안에 있다.
  final String? mapDirectory;

  /// 지금 프로젝트의 맵 이름. 배포 시각을 볼 때 쓴다.
  final String mapName;

  /// 이 프로젝트의 백엔드가 떠 있는가.
  final bool Function() backendRunning;

  /// 백엔드를 띄운다. 로봇 화면의 그 버튼과 같은 것을 부른다.
  final Future<void> Function() onStartBackend;

  /// 앱이 이 로봇의 토픽을 다시 구독하게 한다.
  final Future<void> Function() onResubscribe;

  @override
  State<_RobotDetailDialog> createState() => _RobotDetailDialogState();
}

class _RobotDetailDialogState extends State<_RobotDetailDialog> {
  Timer? _timer;

  /// ROS 에 물어본 결과. 아직 안 물어봤으면 모른다.
  RobotLinkProbe _probe = RobotLinkProbe.unknown;
  ProjectBackendAge _age = const ProjectBackendAge();
  bool _probing = false;
  String? _fixMessage;
  bool _fixOk = true;

  @override
  void initState() {
    super.initState();
    // 위치와 배터리가 계속 바뀐다. 작업 상세와 같은 주기로 읽는다.
    _timer = Timer.periodic(
      const Duration(milliseconds: 200),
      (_) => setState(() {}),
    );
    // 창을 열면 한 번 물어본다. 사람이 버튼을 찾아 누르기 전에 무엇이 끊겼는지
    // 보여야 한다.
    if (_registered?.dataSource.usesTopics ?? false) {
      unawaited(_runProbe());
    }
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  /// 이 로봇의 고리를 ROS 에 물어본다.
  Future<void> _runProbe() async {
    final namespace = _registered?.gzName;
    if (namespace == null || namespace.isEmpty) return;
    setState(() => _probing = true);
    RobotLinkProbe probe;
    try {
      probe = await probeRobotLinks(namespace: namespace);
    } catch (_) {
      probe = RobotLinkProbe.unknown;
    }
    // 떠 있는 백엔드가 지금 배포본으로 뜬 것인지도 함께 본다.
    var age = const ProjectBackendAge();
    final directory = widget.mapDirectory;
    if (directory != null) {
      try {
        age = await readBackendAge(
          mapDirectory: directory,
          mapName: widget.mapName,
        );
      } catch (_) {}
    }
    if (!mounted) return;
    setState(() {
      _probe = probe;
      _age = age;
      _probing = false;
    });
  }

  /// 지금 아는 것을 모아 고리를 판정한다.
  List<RobotLink> get _links {
    final registered = _registered;
    final telemetry = widget.telemetry();
    final pose = telemetry.poses[widget.robotId];
    return checkRobotLinks(
      RobotLinkFacts(
        usesTopics: registered?.dataSource.usesTopics ?? false,
        hasStation: (registered?.chargerWaypoint ?? '').trim().isNotEmpty,
        stationName: registered?.chargerWaypoint,
        spawnX: registered?.spawnX,
        spawnY: registered?.spawnY,
        backendRunning: widget.backendRunning(),
        staleBackendDetail: _age.stale
            ? '${_hhmm(_age.startedAt!)} 에 뜬 월드입니다. '
                  '배포는 ${_hhmm(_age.deployedAt!)} — 다시 띄우세요. '
                  '`ros2 launch` 는 띄울 때 한 번만 파일을 읽습니다.'
            : null,
        nodesUp: _probe.nodesUp,
        topicSeen: _probe.topicSeen,
        topicFlowing: _probe.topicFlowing,
        receiving: _live,
        lastPoseAgeSeconds: pose == null
            ? null
            : DateTime.now().difference(pose.at).inMilliseconds / 1000,
      ),
    );
  }

  static String _hhmm(DateTime at) =>
      '${at.hour.toString().padLeft(2, '0')}:'
      '${at.minute.toString().padLeft(2, '0')}';

  Future<void> _applyFix(RobotLinkAction action) async {
    final registered = _registered;
    final directory = widget.mapDirectory;
    setState(() {
      _probing = true;
      _fixMessage = null;
    });
    RobotLinkFixResult result;
    switch (action) {
      case RobotLinkAction.chooseStation:
        result = const RobotLinkFixResult(
          ok: false,
          message: '로봇 등록에서 자리 Waypoint 를 골라 주세요.',
        );
      case RobotLinkAction.startBackend:
        await widget.onStartBackend();
        result = const RobotLinkFixResult(
          ok: true,
          message: '백엔드를 띄웠습니다. 잠시 뒤 다시 확인해 주세요.',
        );
      case RobotLinkAction.spawnRobot:
        result = registered == null || directory == null
            ? const RobotLinkFixResult(
                ok: false,
                message: '등록 정보나 배포 위치를 찾지 못했습니다.',
              )
            : await spawnSingleRobot(
                mapDirectory: directory,
                robotDirectory: robotDirectoryName(registered),
              );
      case RobotLinkAction.startBridge:
        result = registered == null || directory == null
            ? const RobotLinkFixResult(
                ok: false,
                message: '등록 정보나 배포 위치를 찾지 못했습니다.',
              )
            : await startSingleRobotBridge(
                mapDirectory: directory,
                robotDirectory: robotDirectoryName(registered),
              );
      case RobotLinkAction.resubscribe:
        await widget.onResubscribe();
        result = const RobotLinkFixResult(
          ok: true,
          message: '다시 구독했습니다. 잠시 뒤 다시 확인해 주세요.',
        );
    }
    if (!mounted) return;
    setState(() {
      _fixMessage = result.message;
      _fixOk = result.ok;
      _probing = false;
    });
    // 눌렀으면 결과가 바뀌었을 것이다. 사람이 또 누르게 하지 않는다.
    if (result.ok) {
      await Future<void>.delayed(const Duration(seconds: 3));
      if (mounted) await _runProbe();
    }
  }

  RmfProjectRobot? get _registered => widget.registered;

  bool get _live => widget.telemetry().isLive(widget.robotId);

  /// 이 로봇의 값이 실제로 어디서 오는가.
  ///
  /// 등록에서 Gazebo 를 골랐어도 토픽이 안 오면 화면 숫자는 앱이 계산한 것이다.
  RobotDataSource get _source => effectiveDataSource(
    selected: _registered?.dataSource ?? RobotDataSource.mock,
    topicsConnected: _live,
  );

  bool get _mismatch => dataSourceMismatch(
    selected: _registered?.dataSource ?? RobotDataSource.mock,
    topicsConnected: _live,
  );

  static const Map<RobotDataSource, Color> _sourceColors = {
    RobotDataSource.mock: Color(0xFFDC2626),
    RobotDataSource.gazebo: Color(0xFFEA580C),
    RobotDataSource.real: Color(0xFF15803D),
  };

  String _point(Offset point) {
    final floor = widget.toFloor(point);
    final pixels =
        'X ${floor.dx.toStringAsFixed(1)} · Y ${floor.dy.toStringAsFixed(1)} px';
    final scale = widget.metersPerPixel;
    if (scale == null || scale <= 0) return pixels;
    return '$pixels  ('
        '${(floor.dx * scale).toStringAsFixed(2)} · '
        '${(floor.dy * scale).toStringAsFixed(2)} m)';
  }

  Widget _row(String label, String value, {Color? color}) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 3),
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(
          width: 96,
          child: Text(
            label,
            style: const TextStyle(
              color: Color(0xFF64748B),
              fontWeight: FontWeight.w700,
            ),
          ),
        ),
        Expanded(
          child: SelectableText(
            value,
            style: color == null
                ? null
                : TextStyle(color: color, fontWeight: FontWeight.w600),
          ),
        ),
      ],
    ),
  );

  Widget _heading(String text) => Padding(
    padding: const EdgeInsets.only(top: 18, bottom: 6),
    child: Text(text, style: const TextStyle(fontWeight: FontWeight.w800)),
  );

  /// 이 로봇이 주고받는 토픽과, 실제로 들어온 라이다·카메라.
  ///
  /// 작업 상세는 `무엇을 하고 있나`를 보여 주고, 여기는 `무엇을 보고 있나`를
  /// 보여 준다. 같은 화면에 둘 다 두면 어느 쪽이 어느 쪽인지 헷갈린다.
  /// 값이 안 올 때 어디서 끊겼는지, 무엇을 누르면 되는지.
  ///
  /// 다 이어져 있으면 접어 둔다. 잘 도는 로봇에까지 진단표를 펼쳐 두면
  /// 정작 봐야 할 때 눈에 안 들어온다.
  List<Widget> _diagnosisSection() {
    final registered = _registered;
    if (registered == null || !registered.dataSource.usesTopics) {
      return const [];
    }
    final links = _links;
    final broken = firstBrokenLink(links);
    if (broken == null && !_mismatch && _fixMessage == null) {
      return [
        const SizedBox(height: 14),
        Row(
          children: [
            const Icon(Icons.link, size: 16, color: Color(0xFF15803D)),
            const SizedBox(width: 6),
            Expanded(
              child: Text(
                robotLinkSummary(links),
                style: const TextStyle(fontSize: 12, color: Color(0xFF15803D)),
              ),
            ),
            TextButton(
              onPressed: _probing ? null : _runProbe,
              child: const Text('다시 확인'),
            ),
          ],
        ),
      ];
    }
    return [
      const SizedBox(height: 16),
      Row(
        children: [
          const Text(
            '어디서 끊겼나',
            style: TextStyle(fontWeight: FontWeight.w800, fontSize: 13),
          ),
          const Spacer(),
          if (_probing)
            const SizedBox(
              width: 14,
              height: 14,
              child: CircularProgressIndicator(strokeWidth: 2),
            )
          else
            TextButton(onPressed: _runProbe, child: const Text('다시 확인')),
        ],
      ),
      const SizedBox(height: 4),
      for (final link in links) _linkRow(link),
      if (_fixMessage != null) ...[
        const SizedBox(height: 8),
        SelectableText(
          _fixMessage!,
          style: TextStyle(
            fontSize: 12,
            color: _fixOk ? const Color(0xFF15803D) : const Color(0xFFB91C1C),
          ),
        ),
      ],
    ];
  }

  Widget _linkRow(RobotLink link) {
    final (icon, color) = switch (link.state) {
      RobotLinkState.ok => (Icons.check_circle, const Color(0xFF15803D)),
      RobotLinkState.broken => (Icons.cancel, const Color(0xFFB91C1C)),
      RobotLinkState.unknown => (
        Icons.remove_circle_outline,
        const Color(0xFF94A3B8),
      ),
    };
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, size: 15, color: color),
          const SizedBox(width: 7),
          SizedBox(
            width: 74,
            child: Text(
              link.title,
              style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w700),
            ),
          ),
          Expanded(
            child: Text(
              link.detail,
              style: TextStyle(
                fontSize: 12,
                height: 1.4,
                color: link.state == RobotLinkState.unknown
                    ? const Color(0xFF94A3B8)
                    : const Color(0xFF475569),
              ),
            ),
          ),
          // 버튼은 처음 끊긴 고리에만 붙는다. 순서가 있는 일이라 아래를 먼저
          // 눌러 봐야 소용이 없다 — 월드가 없는데 로봇을 올리면 create 가
          // 월드 이름을 영영 기다린다.
          if (link.action case final action?) ...[
            const SizedBox(width: 8),
            Tooltip(
              message: action.detail,
              child: FilledButton.tonal(
                onPressed: _probing ? null : () => _applyFix(action),
                style: FilledButton.styleFrom(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 12,
                    vertical: 4,
                  ),
                  minimumSize: const Size(0, 32),
                  textStyle: const TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                child: Text(action.label),
              ),
            ),
          ],
        ],
      ),
    );
  }

  List<Widget> _sensorSections() {
    final robot = _registered;
    final topics = robotTopicDetails(robot);
    if (topics.isEmpty) {
      // Mock 은 주고받는 상대가 없다. 빈 자리를 두는 대신 왜 없는지 적는다.
      return [
        _heading('주고받는 토픽'),
        const Padding(
          padding: EdgeInsets.symmetric(vertical: 4),
          child: Text(
            '앱 Mock 로봇은 토픽을 쓰지 않습니다.\n'
            '앱이 제 안에서 굴리는 로봇이라 주고받을 상대가 없습니다.',
            style: TextStyle(color: Color(0xFF64748B), height: 1.5),
          ),
        ),
      ];
    }
    final sensors = widget.sensorsOf();
    final now = DateTime.now();
    return [
      _heading('주고받는 토픽'),
      // 출처가 Gazebo 든 실물이든 이름과 형식은 같다. 그래야 위쪽(Nav2·RMF·앱)이
      // 그대로 돈다.
      for (final topic in topics) _topicRow(topic),
      if (sensors.scan != null) ...[
        _heading('보고 있는 것'),
        _scanView(sensors, now),
      ] else ...[
        _heading('보고 있는 것'),
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 4),
          child: Text(
            robot!.dataSource == RobotDataSource.gazebo
                ? '아직 라이다가 들어오지 않았습니다.\n'
                      '백엔드를 띄웠는지, 센서 relay 가 도는지 확인해 주세요.'
                : '아직 라이다가 들어오지 않았습니다.\n'
                      '로봇이 켜져 있고 토픽이 나오는지 확인해 주세요.',
            style: const TextStyle(color: Color(0xFF64748B), height: 1.5),
          ),
        ),
      ],
    ];
  }

  Widget _topicRow(RobotTopic topic) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 2),
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // 오는 것과 가는 것을 화살표로 가른다. cmd_vel 만 로봇에게 간다.
        SizedBox(
          width: 22,
          child: Text(
            topic.incoming ? '←' : '→',
            style: TextStyle(
              color: topic.incoming
                  ? const Color(0xFF2563EB)
                  : const Color(0xFFEA580C),
              fontWeight: FontWeight.w900,
            ),
          ),
        ),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              SelectableText(
                topic.name,
                style: const TextStyle(
                  fontFamily: 'monospace',
                  fontWeight: FontWeight.w600,
                ),
              ),
              Text(
                '${topic.type} · ${topic.what}',
                style: const TextStyle(color: Color(0xFF64748B), fontSize: 12),
              ),
            ],
          ),
        ),
      ],
    ),
  );

  /// 라이다를 로봇 기준으로 그린다. 가운데가 로봇, 위쪽이 로봇의 앞이다.
  Widget _scanView(RobotSensors sensors, DateTime now) {
    final scan = sensors.scan;
    final live = sensors.scanIsLive(now: now);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          scan == null
              ? '라이다 · 없음'
              : live
              ? '라이다 · ${scan.hits}/${scan.ranges.length}점'
              : '라이다 · 멈춤',
          style: TextStyle(
            fontWeight: FontWeight.w700,
            fontSize: 12,
            color: live ? const Color(0xFF0F172A) : const Color(0xFF94A3B8),
          ),
        ),
        const SizedBox(height: 4),
        Container(
          width: 180,
          height: 180,
          decoration: BoxDecoration(
            color: const Color(0xFF0F172A),
            borderRadius: BorderRadius.circular(8),
          ),
          child: scan == null
              ? const Center(
                  child: Text(
                    '값 없음',
                    style: TextStyle(color: Color(0xFF64748B), fontSize: 12),
                  ),
                )
              : CustomPaint(
                  painter: _ScanPainter(scan: scan, live: live),
                ),
        ),
        if (scan != null) ...[
          const SizedBox(height: 4),
          Text(
            scan.nearest == null
                ? '둘레에 아무것도 없습니다'
                : '제일 가까운 것 ${scan.nearest!.toStringAsFixed(2)}m',
            style: const TextStyle(color: Color(0xFF64748B), fontSize: 12),
          ),
        ],
      ],
    );
  }

  /// 값의 출처를 크게 세운 띠. 작업 상세와 같은 규칙을 쓴다.
  Widget _sourceBanner() {
    final source = _source;
    final color = _sourceColors[source]!;
    final topics = robotTopics(_registered);
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
      decoration: BoxDecoration(
        color: color.withValues(alpha: .10),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: color, width: 2),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(
                switch (source) {
                  RobotDataSource.mock => Icons.science_outlined,
                  RobotDataSource.gazebo => Icons.view_in_ar_outlined,
                  RobotDataSource.real => Icons.smart_toy,
                },
                color: color,
                size: 28,
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  source.label,
                  style: TextStyle(
                    color: color,
                    fontSize: 21,
                    fontWeight: FontWeight.w900,
                    letterSpacing: -.5,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 5),
          Text(
            source.summary,
            style: TextStyle(
              color: color,
              fontSize: 13,
              fontWeight: FontWeight.w600,
              height: 1.4,
            ),
          ),
          if (source.usesTopics && _registered != null) ...[
            const SizedBox(height: 8),
            _topicLine('받기', topics.incoming, color),
            if (topics.outgoing.isNotEmpty)
              _topicLine('보내기', topics.outgoing, color),
          ],
          if (_mismatch) ...[
            const SizedBox(height: 8),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(8),
              decoration: BoxDecoration(
                color: color.withValues(alpha: .14),
                borderRadius: BorderRadius.circular(6),
              ),
              child: Text(
                '등록은 `${_registered!.dataSource.label}` 인데 앱이 아직 그 '
                '토픽을 받지 못하고 있습니다.\n'
                '아래 위치는 앱이 계산한 것입니다.',
                style: TextStyle(
                  color: color,
                  fontSize: 12,
                  fontWeight: FontWeight.w700,
                  height: 1.4,
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }

  Widget _topicLine(String label, List<String> topics, Color color) => Padding(
    padding: const EdgeInsets.only(top: 2),
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(
          width: 46,
          child: Text(
            label,
            style: TextStyle(
              color: color,
              fontSize: 12,
              fontWeight: FontWeight.w800,
            ),
          ),
        ),
        Expanded(
          child: SelectableText(
            topics.join('  ·  '),
            style: TextStyle(
              color: color,
              fontSize: 12,
              fontFamily: 'monospace',
            ),
          ),
        ),
      ],
    ),
  );

  /// 화면에 뿌리는 것과 같은 내용을 글로 만든다.
  String _asText() {
    final robot = widget.robotOf();
    final registered = _registered;
    final pose = widget.telemetry().poses[widget.robotId];
    final tasks = widget.tasksOf();
    return [
      '[로봇] ${widget.robotId}'
          '${registered == null ? '' : ' · ${registered.displayName}'}',
      '[출처] ${_source.label} — ${_source.summary}',
      if (_mismatch) '  주의 등록은 ${registered!.dataSource.label} 인데 토픽이 오지 않습니다.',
      '',
      if (registered != null) ...[
        '종류 ${registered.kind.label}',
        '모델 ${registered.model}',
        'Gazebo 이름 ${registered.gzName}',
        '${registered.isMobile ? '충전' : '설비'} 자리 '
            '${registered.chargerWaypoint ?? '미지정'}',
        if (registered.isMobile) '구획 ${registered.zones.join(', ')}',
      ] else
        '등록되지 않은 로봇입니다 (사람·휴머노이드).',
      '',
      if (robot == null)
        '지도에 배치되지 않았습니다.'
      else ...[
        '위치 ${_point(robot.position)}',
        '주행 ${robot.moving ? '주행 중' : '정지'} · 배터리 '
            '${robot.battery.toStringAsFixed(1)}%',
        '목표 ${robot.targetWaypoint == null ? '없음' : widget.waypointLabel(robot.targetWaypoint!)}',
        '남은 경로 ${robot.assignedRoute.length}개 지점',
      ],
      if (pose != null)
        '토픽 위치 ${pose.x.toStringAsFixed(3)}, ${pose.y.toStringAsFixed(3)} m · '
            '방향 ${(pose.heading * 180 / math.pi).toStringAsFixed(1)}°',
      '',
      if (tasks.isEmpty)
        '맡은 작업이 없습니다.'
      else
        for (final task in tasks)
          '작업 ${task.id} ${task.name} · ${task.status.name} · '
              '${task.currentStepIndex}/${task.steps.length} 단계',
    ].join('\n');
  }

  @override
  Widget build(BuildContext context) {
    final robot = widget.robotOf();
    final registered = _registered;
    final pose = widget.telemetry().poses[widget.robotId];
    final tasks = widget.tasksOf();
    return AlertDialog(
      title: Row(
        children: [
          Icon(
            registered == null
                ? Icons.person
                : registered.isMobile
                ? Icons.smart_toy_outlined
                : Icons.precision_manufacturing,
            color: const Color(0xFF2563EB),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              registered == null
                  ? widget.robotId
                  : '${widget.robotId} · ${registered.displayName}',
            ),
          ),
        ],
      ),
      content: SizedBox(
        width: 560,
        height: 520,
        child: SingleChildScrollView(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _sourceBanner(),
              _heading('등록 정보'),
              if (registered == null)
                _row('등록', '등록되지 않은 로봇입니다 (사람·휴머노이드).')
              else ...[
                _row('종류', registered.kind.label),
                _row('모델', registered.model),
                _row('Gazebo 이름', registered.gzName),
                _row(
                  '${registered.isMobile ? '충전' : '설비'} 자리',
                  registered.chargerWaypoint ?? '미지정',
                ),
                if (registered.isMobile)
                  _row(
                    '구획 자격',
                    registered.zones.isEmpty
                        ? '없음'
                        : registered.zones.join(', '),
                  ),
                _row(
                  'RMF 관제',
                  registered.isManagedByRmf
                      ? 'fleet adapter 에 들어감'
                      : '들어가지 않음 (앱이 직접 굴림)',
                ),
                _row('Gazebo', registered.runsInGazebo ? '올라감' : '올리지 않음'),
              ],
              _heading('지금 상태'),
              if (robot == null)
                _row('배치', '지도에 배치되지 않았습니다.')
              else ...[
                _row('위치', _point(robot.position)),
                if (registered?.isMobile ?? true) ...[
                  _row('주행', robot.moving ? '주행 중' : '정지'),
                  _row('배터리', '${robot.battery.toStringAsFixed(1)}%'),
                  _row(
                    '목표 지점',
                    robot.targetWaypoint == null
                        ? '없음'
                        : widget.waypointLabel(robot.targetWaypoint!),
                  ),
                  _row('남은 경로', '${robot.assignedRoute.length}개 지점'),
                ],
              ],
              if (pose != null)
                _row(
                  '토픽 위치',
                  '${pose.x.toStringAsFixed(3)}, ${pose.y.toStringAsFixed(3)} m'
                      ' · 방향 ${(pose.heading * 180 / math.pi).toStringAsFixed(1)}°',
                  color: _sourceColors[_source],
                ),
              ..._diagnosisSection(),
              ..._sensorSections(),
              _heading('맡은 작업'),
              if (tasks.isEmpty)
                const Padding(
                  padding: EdgeInsets.symmetric(vertical: 4),
                  child: Text(
                    '맡은 작업이 없습니다.',
                    style: TextStyle(color: Color(0xFF64748B)),
                  ),
                )
              else
                for (final task in tasks)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 3),
                    child: Row(
                      children: [
                        Icon(
                          switch (task.status) {
                            _MockTaskStatus.completed => Icons.check_circle,
                            _MockTaskStatus.active => Icons.play_circle_fill,
                            _MockTaskStatus.failed => Icons.error,
                            _ => Icons.radio_button_unchecked,
                          },
                          size: 16,
                          color: switch (task.status) {
                            _MockTaskStatus.completed => const Color(
                              0xFF15803D,
                            ),
                            _MockTaskStatus.active => const Color(0xFF2563EB),
                            _MockTaskStatus.failed => const Color(0xFFDC2626),
                            _ => const Color(0xFF94A3B8),
                          },
                        ),
                        const SizedBox(width: 8),
                        Expanded(
                          child: Text(
                            '${task.name} · ${task.currentStepIndex}/'
                            '${task.steps.length} 단계'
                            '${task.currentStep == null ? '' : ' · ${task.currentStep!.destinationName ?? ''}'}',
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                          ),
                        ),
                      ],
                    ),
                  ),
            ],
          ),
        ),
      ),
      actions: [
        TextButton.icon(
          onPressed: () async {
            await Clipboard.setData(ClipboardData(text: _asText()));
            if (!context.mounted) return;
            ScaffoldMessenger.of(
              context,
            ).showSnackBar(const SnackBar(content: Text('로봇 상세를 복사했습니다.')));
          },
          icon: const Icon(Icons.copy_outlined, size: 18),
          label: const Text('복사'),
        ),
        FilledButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('닫기'),
        ),
      ],
    );
  }
}

/// 프로젝트 로그의 마지막 50줄.
///
/// 지금까지 무엇이 잘못됐는지 알려면 터미널에서 로그를 뒤져야 했다. 오류만
/// 모은 파일을 함께 보여 준다 — 원인을 알려 준 것은 대부분 ERROR 가 아니라
/// 뜨는 순서였지만, 한눈에 볼 때는 오류 쪽이 빠르다.
class _ProjectLogPage extends StatefulWidget {
  const _ProjectLogPage({required this.mapDirectory, required this.mapName});

  final String? mapDirectory;
  final String mapName;

  @override
  State<_ProjectLogPage> createState() => _ProjectLogPageState();
}

class _ProjectLogPageState extends State<_ProjectLogPage> {
  static const int _count = 30;
  bool _errorsOnly = false;
  ({ProjectLogTail run, ProjectLogTail errors})? _logs;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _reload();
    // 백엔드가 도는 동안 계속 쌓인다. 화면을 열어 둔 채로 따라가게 한다.
    _timer = Timer.periodic(const Duration(seconds: 3), (_) => _reload());
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  void _reload() {
    final directory = widget.mapDirectory;
    if (directory == null || widget.mapName.trim().isEmpty) return;
    final logs = readProjectLogs(
      mapDirectory: directory,
      mapName: widget.mapName,
      count: _count,
    );
    if (mounted) setState(() => _logs = logs);
  }

  /// 로그를 비운다. 되돌릴 수 없으니 한 번 묻는다.
  Future<void> _confirmClear() async {
    final logs = _logs;
    if (logs == null) return;
    final ok = await showMovableDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        icon: const Icon(Icons.delete_sweep_outlined, size: 32),
        title: const Text('로그 비우기'),
        content: SizedBox(
          width: 420,
          child: SelectableText(
            '실행 로그와 오류 로그를 비웁니다. 되돌릴 수 없습니다.\n\n'
            '${logs.run.path}  ${_size(logs.run.sizeBytes)}\n'
            '${logs.errors.path}  ${_size(logs.errors.sizeBytes)}\n\n'
            '백엔드가 돌고 있어도 괜찮습니다. 지우는 것이 아니라 길이를 0으로 '
            '만드는 것이라, 열려 있는 채로 디스크 자리가 돌아옵니다.',
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('취소'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(dialogContext, true),
            style: FilledButton.styleFrom(
              backgroundColor: const Color(0xFFDC2626),
            ),
            child: const Text('비우기'),
          ),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    final failed = [
      for (final path in [logs.run.path, logs.errors.path])
        if (truncateLog(path) case final error?) '$path — $error',
    ];
    _reload();
    if (!mounted) return;
    if (failed.isEmpty) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('로그를 비웠습니다.')));
      return;
    }
    await showWaypointErrorDialog(
      context,
      title: '로그 비우기',
      message: '비우지 못한 파일이 있습니다.\n\n${failed.join('\n')}',
    );
  }

  String _size(int bytes) => bytes >= 1 << 30
      ? '${(bytes / (1 << 30)).toStringAsFixed(1)}GB'
      : bytes >= 1 << 20
      ? '${(bytes / (1 << 20)).toStringAsFixed(1)}MB'
      : '${(bytes / 1024).toStringAsFixed(0)}KB';

  @override
  Widget build(BuildContext context) {
    final logs = _logs;
    final tail = _errorsOnly ? logs?.errors : logs?.run;
    return Padding(
      padding: const EdgeInsets.fromLTRB(28, 22, 28, 24),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Row(
            children: [
              const Text(
                '마지막 30줄',
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.w800),
              ),
              const SizedBox(width: 14),
              SegmentedButton<bool>(
                segments: const [
                  ButtonSegment(value: false, label: Text('전체')),
                  ButtonSegment(value: true, label: Text('오류·경고만')),
                ],
                selected: {_errorsOnly},
                onSelectionChanged: (value) =>
                    setState(() => _errorsOnly = value.first),
              ),
              const Spacer(),
              if (tail != null && tail.sizeBytes > 0)
                Text(
                  '${_size(tail.sizeBytes)}'
                  '${tail.modifiedAt == null ? '' : ' · ${_clock(tail.modifiedAt!)}'}',
                  style: const TextStyle(
                    fontSize: 12,
                    color: Color(0xFF64748B),
                  ),
                ),
              const SizedBox(width: 10),
              OutlinedButton.icon(
                onPressed: _reload,
                icon: const Icon(Icons.refresh, size: 18),
                label: const Text('다시 읽기'),
              ),
              const SizedBox(width: 8),
              OutlinedButton.icon(
                onPressed: tail == null || tail.sizeBytes == 0
                    ? null
                    : _confirmClear,
                icon: const Icon(Icons.delete_sweep_outlined, size: 18),
                label: const Text('로그 비우기'),
                style: OutlinedButton.styleFrom(
                  foregroundColor: const Color(0xFFB91C1C),
                ),
              ),
              const SizedBox(width: 8),
              OutlinedButton.icon(
                onPressed: tail == null || tail.isEmpty
                    ? null
                    : () {
                        Clipboard.setData(
                          ClipboardData(
                            text: tail.lines.map((l) => l.text).join('\n'),
                          ),
                        );
                        ScaffoldMessenger.of(context).showSnackBar(
                          const SnackBar(content: Text('로그를 복사했습니다.')),
                        );
                      },
                icon: const Icon(Icons.copy_all_outlined, size: 18),
                label: const Text('전체 복사'),
              ),
            ],
          ),
          if (tail != null) ...[
            const SizedBox(height: 6),
            Row(
              children: [
                Expanded(
                  child: SelectableText(
                    tail.path,
                    style: const TextStyle(
                      fontSize: 11,
                      color: Color(0xFF94A3B8),
                    ),
                  ),
                ),
                const Text(
                  '마우스로 끌어 몇 줄만 고른 뒤 Ctrl+C 로도 복사됩니다.',
                  style: TextStyle(fontSize: 11, color: Color(0xFF94A3B8)),
                ),
              ],
            ),
          ],
          const SizedBox(height: 12),
          // 화면을 다 먹지 않게 높이를 묶어 둔다. 30줄이면 이만큼이면 되고,
          // 아래에 다른 것을 놓을 자리도 남는다.
          ConstrainedBox(
            constraints: const BoxConstraints(maxHeight: 360),
            child: Container(
              width: double.infinity,
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(
                color: const Color(0xFF0F172A),
                borderRadius: BorderRadius.circular(10),
              ),
              child: tail == null
                  ? const Center(
                      child: Text(
                        '프로젝트를 열거나 배포 맵을 불러오면 로그를 읽습니다.',
                        style: TextStyle(color: Color(0xFF94A3B8)),
                      ),
                    )
                  : tail.isEmpty
                  ? Center(
                      child: Text(
                        tail.message ??
                            (_errorsOnly ? '오류나 경고가 없습니다.' : '아직 아무것도 없습니다.'),
                        textAlign: TextAlign.center,
                        style: const TextStyle(
                          color: Color(0xFF94A3B8),
                          height: 1.6,
                        ),
                      ),
                    )
                  // 마우스로 여러 줄을 끌어 고를 수 있어야 한다. 줄마다
                  // SelectableText 를 두면 그 줄 안에서만 골라진다.
                  // SelectionArea 로 감싸고 안은 보통 Text 로 둔다.
                  //
                  // ListView.builder 는 화면 밖 줄을 만들지 않아 스크롤한
                  // 부분이 선택에서 빠진다. 50줄뿐이니 통째로 둔다.
                  : SelectionArea(
                      child: Scrollbar(
                        thumbVisibility: true,
                        child: SingleChildScrollView(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              for (final line in tail.lines)
                                Padding(
                                  padding: const EdgeInsets.only(bottom: 2),
                                  child: Text(
                                    line.text,
                                    style: TextStyle(
                                      fontFamily: 'monospace',
                                      fontSize: 12,
                                      height: 1.5,
                                      color: line.isError
                                          ? const Color(0xFFFCA5A5)
                                          : line.isWarning
                                          ? const Color(0xFFFCD34D)
                                          : const Color(0xFFCBD5E1),
                                    ),
                                  ),
                                ),
                            ],
                          ),
                        ),
                      ),
                    ),
            ),
          ),
        ],
      ),
    );
  }

  static String _clock(DateTime at) =>
      '${at.hour.toString().padLeft(2, '0')}:'
      '${at.minute.toString().padLeft(2, '0')}:'
      '${at.second.toString().padLeft(2, '0')}';
}
