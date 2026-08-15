/// 맵 프로젝트에서 Open-RMF 설정 파일을 만든다.
///
/// 플릿 설정은 맵을 따라간다. 맵이 다르면 Waypoint 이름도 충전소 위치도 다르므로
/// 전역 fleet.yaml 하나를 돌려 쓰면 프로젝트를 바꾸는 순간 어긋난다.
///
/// 여기서 만든 결과는 `map_project_files` 에 프로젝트별로 보관한다.
library;

import 'dart:math' as math;

import 'nav2_params.dart' show nav2MapTopic, nav2MapTopicName;
import 'rmf_task_request.dart' show rmfArmLoadAction;
import 'workcell_pairing.dart';
import 'workcell_policy.dart';

/// 이 로봇의 값이 어디서 오는가.
///
/// 로봇마다 다를 수 있다. 실물 두 대를 돌리면서 한 대만 Gazebo 로 시험하는 일이
/// 흔하다. 앱 전체에 하나로 두면 그런 구성을 담을 수 없다.
///
/// 무엇을 고르느냐에 따라 실행에 들어가는 자리가 갈린다.
///
/// | | fleet adapter | Gazebo bringup | 토픽 다리 |
/// |---|---|---|---|
/// | mock   | 안 감 | 안 감 | 안 감 |
/// | gazebo | 감 | 감 | 감 |
/// | real   | 감 | 안 감 | 안 감 |
enum RobotDataSource {
  /// 앱이 100ms 마다 직접 계산한 값. ROS 는 아예 관여하지 않는다.
  mock,

  /// Gazebo 가 물리를 돌리고 그 결과가 ROS 토픽으로 온다.
  gazebo,

  /// 실물 로봇에서 온 ROS 토픽.
  real;

  String get label => switch (this) {
    RobotDataSource.mock => '앱 Mock 데이터',
    RobotDataSource.gazebo => 'Gazebo 시뮬레이션',
    RobotDataSource.real => '실제 로봇',
  };

  /// 로봇 화면의 `로봇 실행 방식` 에 쓰는 짧은 이름.
  String get shortLabel => switch (this) {
    RobotDataSource.mock => '앱 Mock',
    RobotDataSource.gazebo => 'Gazebo 시뮬레이션',
    RobotDataSource.real => '실제 로봇',
  };

  /// 이 값이 무엇인지 한 줄로.
  String get summary => switch (this) {
    RobotDataSource.mock => '앱이 계산한 값입니다. 실제 로봇도 Gazebo도 아닙니다.',
    RobotDataSource.gazebo => 'Gazebo가 물리를 돌리고 그 결과를 ROS 토픽으로 주고받습니다.',
    RobotDataSource.real => '실물 로봇이 보내는 ROS 토픽입니다.',
  };

  /// ROS 토픽을 주고받는가. Mock 은 앱 안에서만 돈다.
  bool get usesTopics => this != RobotDataSource.mock;

  static RobotDataSource parse(String? value) => switch (value) {
    'gazebo' => RobotDataSource.gazebo,
    'real' => RobotDataSource.real,
    _ => RobotDataSource.mock,
  };
}

/// 로봇이 돌아다니는지 한자리에 붙어 있는지.
///
/// 둘은 등록 정보도 실행 방법도 다르다. 이동 로봇은 충전소가 있어야 하고
/// fleet adapter 가 배차한다. 설치 로봇은 설비 자리에 고정되고 fleet 에 들어가지
/// 않는다 — Open-RMF 에서 이런 것은 플릿이 아니라 workcell 이다.
enum RmfRobotKind {
  /// 이동 로봇. Pinky 처럼 Lane 을 따라 다닌다.
  mobile,

  /// 설치 로봇. OpenMANIPULATOR 처럼 설비 자리에 고정된다.
  workcell;

  String get label => this == RmfRobotKind.mobile ? '이동 로봇' : '설치 로봇';

  /// 이 로봇이 설 자리를 고를 Waypoint 카테고리.
  String get waypointCategory => this == RmfRobotKind.mobile ? '충전' : '설비';

  static RmfRobotKind parse(String? value) =>
      value == 'workcell' ? RmfRobotKind.workcell : RmfRobotKind.mobile;

  String get storageValue => name;
}

/// ROS 2 는 도메인으로 망을 가른다. 안 정하면 0 이다.
///
/// 같은 도메인에 있는 노드끼리만 서로를 본다. 이것이 어긋나면 **아무 오류도
/// 안 나면서** 아무것도 안 통한다 — 지도를 배포해도 시뮬레이터가 못 받고,
/// 로봇을 띄워도 관제가 못 본다. 그래서 프로젝트가 이 값을 들고 있어야 한다.
const int defaultRosDomainId = 0;

/// 여기까지는 어느 환경에서나 안전하다. 그 위는 OS 의 임시 포트 범위와 겹칠 수
/// 있어 DDS 가 포트를 못 잡는 일이 생긴다.
const int safeMaxRosDomainId = 101;

/// ROS 2 가 받는 가장 큰 도메인 번호.
const int maxRosDomainId = 232;

/// 이 번호를 도메인으로 쓸 수 있나. 쓸 수 있으면 null, 아니면 까닭.
String? rosDomainIdError(int? domainId) {
  if (domainId == null) return '0 부터 $maxRosDomainId 사이의 정수를 넣으세요.';
  if (domainId < 0 || domainId > maxRosDomainId) {
    return '0 부터 $maxRosDomainId 사이여야 합니다.';
  }
  return null;
}

/// 받기는 하지만 알려 줘야 하는 번호인가. 문제없으면 null.
String? rosDomainIdWarning(int domainId) {
  if (domainId <= safeMaxRosDomainId) return null;
  return '$safeMaxRosDomainId 을 넘는 도메인은 OS 의 임시 포트 범위와 겹칠 수 '
      '있습니다. DDS 가 포트를 못 잡으면 노드가 서로를 못 봅니다.';
}

/// 프로젝트에 속한 로봇 한 대.
class RmfProjectRobot {
  const RmfProjectRobot({
    required this.robotId,
    required this.displayName,
    required this.model,
    required this.gzName,
    required this.zones,
    this.kind = RmfRobotKind.mobile,
    this.dataSource = RobotDataSource.mock,
    this.chargerWaypoint,
    this.spawnX,
    this.spawnY,
    this.spawnHeading = 0,
    this.rosDomainId,
  });

  /// 이 로봇만 다른 ROS 도메인을 쓸 때 그 번호. null 이면 프로젝트 기본값.
  ///
  /// 실물 로봇은 제 도메인을 갖고 오는 일이 흔하다. 한 대만 다른 망에 있어도
  /// 나머지를 따라 옮길 이유는 없으므로 대마다 따로 둔다.
  ///
  /// **Gazebo 로봇은 시뮬레이터와 같은 도메인이어야 한다.** 다르면 다리가
  /// 걸어 놓은 토픽에 값이 하나도 안 온다 — 오류는 안 난다.
  final int? rosDomainId;

  final String robotId;
  final String displayName;
  final String model;

  /// 돌아다니는 로봇인지 한자리에 붙은 설비인지.
  final RmfRobotKind kind;

  /// 이 로봇의 값이 어디서 오는가. 실행에 들어가는 자리가 여기서 갈린다.
  final RobotDataSource dataSource;

  /// Gazebo 모델 이름. 토픽 네임스페이스로도 쓰인다(`/<gzName>/odom`).
  final String gzName;

  /// TempZone.name 목록. 관제 배차의 입찰 자격이 된다. 설치 로봇은 배차를 받지
  /// 않으므로 비어 있어도 된다.
  final List<String> zones;

  /// 이 로봇이 서 있는 Waypoint 이름.
  ///
  /// 이동 로봇이면 충전 Waypoint 로, fleet adapter 의 `robots[].charger` 가 된다.
  /// 설치 로봇이면 설비 Waypoint 로, 그 자리에 고정 설치된다.
  final String? chargerWaypoint;
  final double? spawnX;
  final double? spawnY;
  final double spawnHeading;

  /// 올릴 자리만 바꾼 사본.
  ///
  /// spawn 좌표는 늘 자리 Waypoint 에서 나오므로, 지도를 다시 읽었을 때 이름은
  /// 그대로 두고 좌표만 다시 계산해 넣는다.
  RmfProjectRobot withSpawn({
    required double? spawnX,
    required double? spawnY,
    double? spawnHeading,
  }) => RmfProjectRobot(
    robotId: robotId,
    displayName: displayName,
    model: model,
    gzName: gzName,
    zones: zones,
    kind: kind,
    dataSource: dataSource,
    chargerWaypoint: chargerWaypoint,
    spawnX: spawnX,
    spawnY: spawnY,
    spawnHeading: spawnHeading ?? this.spawnHeading,
    rosDomainId: rosDomainId,
  );

  bool get isMobile => kind == RmfRobotKind.mobile;

  /// Gazebo 에 올릴 로봇인가. Mock 은 앱 안에만 있고, 실물은 이미 있다.
  bool get runsInGazebo => dataSource == RobotDataSource.gazebo;

  /// Open-RMF 가 관제하는가. Mock 은 앱이 직접 굴리므로 플릿에 넣지 않는다.
  bool get isManagedByRmf => dataSource != RobotDataSource.mock;

  Map<String, Object?> toJson() => {
    'robotId': robotId,
    'displayName': displayName,
    'model': model,
    'kind': kind.storageValue,
    'dataSource': dataSource.name,
    'gzName': gzName,
    'zones': zones,
    'chargerWaypoint': chargerWaypoint,
    'spawnX': spawnX,
    'spawnY': spawnY,
    'spawnHeading': spawnHeading,
    'rosDomainId': rosDomainId,
  };

  static RmfProjectRobot fromJson(Map<String, dynamic> data) => RmfProjectRobot(
    robotId: data['robotId'] as String,
    displayName: data['displayName'] as String? ?? data['robotId'] as String,
    model: data['model'] as String? ?? 'PINKY',
    kind: RmfRobotKind.parse(data['kind'] as String?),
    dataSource: RobotDataSource.parse(data['dataSource'] as String?),
    gzName: data['gzName'] as String? ?? data['robotId'] as String,
    zones: [
      for (final zone in (data['zones'] as List<dynamic>? ?? const []))
        zone.toString(),
    ],
    chargerWaypoint: data['chargerWaypoint'] as String?,
    spawnX: (data['spawnX'] as num?)?.toDouble(),
    spawnY: (data['spawnY'] as num?)?.toDouble(),
    spawnHeading: (data['spawnHeading'] as num?)?.toDouble() ?? 0,
    rosDomainId: (data['rosDomainId'] as num?)?.toInt(),
  );
}

/// 설치 로봇으로 고를 수 있는 OpenMANIPULATOR 모델과 그 컨트롤러.
///
/// `open_manipulator_description` 의 xacro 가 펼쳐지고 Gazebo 용 컨트롤러 설정이
/// 있는 것만 넣는다. 고를 수 있는데 띄우면 죽는 항목은 없느니만 못하다.
///
/// 뺀 것들:
/// - `omy_f3m` — `realsense2_description` 이 있어야 xacro 가 펼쳐진다
/// - `omx_l`, `omy_l100` — 원격 조종의 leader 쪽이라 설비로 세울 것이 아니다
///
/// 모델마다 컨트롤러가 다르다. `omy_3m` 은 그리퍼가 없어서 있지도 않은
/// `gripper_controller` 를 올리면 spawner 가 기다리다 실패한다.
const Map<String, List<String>> openManipulatorControllers = {
  'open_manipulator_x': [
    'joint_state_broadcaster',
    'arm_controller',
    'gripper_controller',
  ],
  'omx_f': ['joint_state_broadcaster', 'arm_controller', 'gripper_controller'],
  'omy_3m': ['joint_state_broadcaster', 'arm_controller'],
};

/// 설치 로봇으로 고를 수 있는 모델 이름.
List<String> get openManipulatorModels =>
    openManipulatorControllers.keys.toList();

/// 프로젝트의 플릿 설정. Open-RMF fleet adapter 의 `rmf_fleet` 블록과 대응한다.
class RmfFleetSettings {
  const RmfFleetSettings({
    this.fleetName = 'pinky',
    this.linearVelocity = .5,
    this.linearAcceleration = .75,
    this.angularVelocity = .6,
    this.angularAcceleration = 2.0,
    this.footprintRadius = .3,
    this.vicinityRadius = .5,
    this.reversible = false,
    this.batteryVoltage = 12,
    this.batteryCapacity = 24,
    this.chargingCurrent = 5,
    this.mass = 20,
    this.momentOfInertia = 10,
    this.frictionCoefficient = .22,
    this.ambientPower = 20,
    this.toolPower = 0,
    this.rechargeThreshold = .1,
    this.rechargeSoc = 1,
    this.fleetManagerIp = '127.0.0.1',
    this.fleetManagerPort = 22011,
    this.goalToleranceMeters,
    this.manualFootprintRadius,
    this.manualVicinityRadius,
  });

  /// 사람이 직접 넣은 충돌 반경 [m]. null 이면 로봇 폭의 절반으로 계산한다.
  ///
  /// 계산값은 로봇을 원으로 본 어림이다. 적재물이나 범퍼가 튀어나오면 실제
  /// 몸이 그 원보다 크고, RMF 는 그만큼을 모르는 채로 두 로봇을 붙인다.
  /// 재서 넣을 수 있어야 한다.
  final double? manualFootprintRadius;

  /// 사람이 직접 넣은 접근 금지 반경 [m]. null 이면 충돌 반경 + 위치 오차 여유.
  ///
  /// RMF 는 이 원 안에 다른 로봇을 안 들인다. 좁은 통로에서 이 값이 크면 서로
  /// 비켜 주기만 하다 아무도 못 지나가고, 작으면 실제로 닿는다.
  final double? manualVicinityRadius;

  /// Nav2 가 "도착했다" 고 인정하는 반경 [m].
  ///
  /// 비워 두면 맵에서 계산한 값을 쓴다 — [recommendedGoalTolerance].
  /// 벤더 기본값 0.25m 는 사람 다니는 복도를 전제한 것이라, Waypoint 가
  /// 0.33m 간격인 맵에서는 이웃 Waypoint 의 도착 원과 겹친다. 실제로 충전1 로
  /// 돌아오라 했는데 0.246m 어긋난 자리에서 멈추고 도착으로 쳤다.
  final double? goalToleranceMeters;

  final String fleetName;
  final double linearVelocity;
  final double linearAcceleration;
  final double angularVelocity;
  final double angularAcceleration;

  /// 로봇을 원으로 본 반경. 로봇 안전 기준의 폭 절반에서 가져온다.
  final double footprintRadius;

  /// 다른 로봇이 접근하지 않아야 하는 반경. footprint 에 위치 오차 여유를 더한다.
  final double vicinityRadius;
  final bool reversible;
  final double batteryVoltage;
  final double batteryCapacity;
  final double chargingCurrent;
  final double mass;
  final double momentOfInertia;
  final double frictionCoefficient;
  final double ambientPower;
  final double toolPower;
  final double rechargeThreshold;
  final double rechargeSoc;
  final String fleetManagerIp;
  final int fleetManagerPort;

  /// 맵의 로봇 안전 기준에서 프로필 반경을 가져온 설정.
  ///
  /// 사용자가 이미 입력한 값을 다시 묻지 않는다. 두 곳에 따로 적으면 어긋난다.
  ///
  /// 다만 **직접 넣은 값이 있으면 그것이 이긴다.** 로봇을 원으로 보는 계산은
  /// 어림이라, 실제 몸이 원이 아니거나 적재물이 튀어나오면 사람이 재서 넣는
  /// 편이 맞다. 그때 폭을 고쳤다고 넣은 값을 덮어쓰면 안 된다.
  RmfFleetSettings withRobotSafety({
    required double widthMeters,
    required double localizationMarginMeters,
  }) => copyWith(
    footprintRadius: manualFootprintRadius ?? widthMeters / 2,
    vicinityRadius:
        manualVicinityRadius ?? widthMeters / 2 + localizationMarginMeters,
  );

  RmfFleetSettings copyWith({
    String? fleetName,
    double? linearVelocity,
    double? linearAcceleration,
    double? angularVelocity,
    double? angularAcceleration,
    double? footprintRadius,
    double? vicinityRadius,
    double? goalToleranceMeters,
    bool clearGoalTolerance = false,
    double? manualFootprintRadius,
    double? manualVicinityRadius,
    bool clearManualProfile = false,
  }) => RmfFleetSettings(
    goalToleranceMeters: clearGoalTolerance
        ? null
        : goalToleranceMeters ?? this.goalToleranceMeters,
    manualFootprintRadius: clearManualProfile
        ? null
        : manualFootprintRadius ?? this.manualFootprintRadius,
    manualVicinityRadius: clearManualProfile
        ? null
        : manualVicinityRadius ?? this.manualVicinityRadius,
    fleetName: fleetName ?? this.fleetName,
    linearVelocity: linearVelocity ?? this.linearVelocity,
    linearAcceleration: linearAcceleration ?? this.linearAcceleration,
    angularVelocity: angularVelocity ?? this.angularVelocity,
    angularAcceleration: angularAcceleration ?? this.angularAcceleration,
    footprintRadius: footprintRadius ?? this.footprintRadius,
    vicinityRadius: vicinityRadius ?? this.vicinityRadius,
    reversible: reversible,
    batteryVoltage: batteryVoltage,
    batteryCapacity: batteryCapacity,
    chargingCurrent: chargingCurrent,
    mass: mass,
    momentOfInertia: momentOfInertia,
    frictionCoefficient: frictionCoefficient,
    ambientPower: ambientPower,
    toolPower: toolPower,
    rechargeThreshold: rechargeThreshold,
    rechargeSoc: rechargeSoc,
    fleetManagerIp: fleetManagerIp,
    fleetManagerPort: fleetManagerPort,
  );

  Map<String, Object?> toJson() => {
    'fleetName': fleetName,
    'linearVelocity': linearVelocity,
    'linearAcceleration': linearAcceleration,
    'angularVelocity': angularVelocity,
    'angularAcceleration': angularAcceleration,
    'footprintRadius': footprintRadius,
    'vicinityRadius': vicinityRadius,
    'reversible': reversible,
    'batteryVoltage': batteryVoltage,
    'batteryCapacity': batteryCapacity,
    'chargingCurrent': chargingCurrent,
    'mass': mass,
    'momentOfInertia': momentOfInertia,
    'frictionCoefficient': frictionCoefficient,
    'ambientPower': ambientPower,
    'toolPower': toolPower,
    'rechargeThreshold': rechargeThreshold,
    'rechargeSoc': rechargeSoc,
    'fleetManagerIp': fleetManagerIp,
    'fleetManagerPort': fleetManagerPort,
    'goalToleranceMeters': goalToleranceMeters,
    // 비어 있으면 로봇 폭에서 계산한다는 뜻이다. 계산값을 적어 두면 나중에
    // 폭을 고쳐도 옛 값이 남아, 왜 안 따라오는지 알 수 없다.
    'manualFootprintRadius': manualFootprintRadius,
    'manualVicinityRadius': manualVicinityRadius,
  };

  static RmfFleetSettings fromJson(Map<String, dynamic> d) {
    double num_(String key, double fallback) =>
        (d[key] as num?)?.toDouble() ?? fallback;
    const base = RmfFleetSettings();
    return RmfFleetSettings(
      fleetName: d['fleetName'] as String? ?? base.fleetName,
      linearVelocity: num_('linearVelocity', base.linearVelocity),
      linearAcceleration: num_('linearAcceleration', base.linearAcceleration),
      angularVelocity: num_('angularVelocity', base.angularVelocity),
      angularAcceleration: num_(
        'angularAcceleration',
        base.angularAcceleration,
      ),
      footprintRadius: num_('footprintRadius', base.footprintRadius),
      vicinityRadius: num_('vicinityRadius', base.vicinityRadius),
      reversible: d['reversible'] as bool? ?? base.reversible,
      batteryVoltage: num_('batteryVoltage', base.batteryVoltage),
      batteryCapacity: num_('batteryCapacity', base.batteryCapacity),
      chargingCurrent: num_('chargingCurrent', base.chargingCurrent),
      mass: num_('mass', base.mass),
      momentOfInertia: num_('momentOfInertia', base.momentOfInertia),
      frictionCoefficient: num_(
        'frictionCoefficient',
        base.frictionCoefficient,
      ),
      ambientPower: num_('ambientPower', base.ambientPower),
      toolPower: num_('toolPower', base.toolPower),
      rechargeThreshold: num_('rechargeThreshold', base.rechargeThreshold),
      rechargeSoc: num_('rechargeSoc', base.rechargeSoc),
      fleetManagerIp: d['fleetManagerIp'] as String? ?? base.fleetManagerIp,
      fleetManagerPort:
          (d['fleetManagerPort'] as num?)?.toInt() ?? base.fleetManagerPort,
      goalToleranceMeters: (d['goalToleranceMeters'] as num?)?.toDouble(),
      manualFootprintRadius: (d['manualFootprintRadius'] as num?)?.toDouble(),
      manualVicinityRadius: (d['manualVicinityRadius'] as num?)?.toDouble(),
    );
  }
}

String _n(double value) => value.toStringAsFixed(3);

/// 임의의 프로젝트 이름을 유효한 ROS 2 node 이름으로 바꾼다.
/// 파일 이름에는 `-`가 허용되지만 node 이름에는 허용되지 않는다.
String _rosNodeName(String value) {
  var sanitized = value.replaceAll(RegExp(r'[^A-Za-z0-9_]'), '_');
  if (sanitized.isEmpty) return 'robosapiens_node';
  if (RegExp(r'^[0-9]').hasMatch(sanitized)) sanitized = 'n_$sanitized';
  return sanitized;
}

/// Open-RMF fleet adapter 설정(`<fleet>_config.yaml`).
///
/// `rmf_demos` 의 tinyRobot_config.yaml 과 같은 구조다. 이것이 없어서 지금까지
/// office 데모 설정을 빌려 썼고, 로봇 이름·속도·배터리가 전부 맞지 않았다.
String buildFleetAdapterYaml({
  required RmfFleetSettings fleet,
  required List<RmfProjectRobot> robots,
  required String mapName,
}) {
  final buffer = StringBuffer()
    ..writeln('# $mapName 프로젝트의 Open-RMF fleet adapter 설정.')
    ..writeln('# rmf_control_ui 가 맵 프로젝트에서 생성했다. 손으로 고치면')
    ..writeln('# 다음 저장 때 덮어써진다.')
    ..writeln('rmf_fleet:')
    ..writeln('  name: "${fleet.fleetName}"')
    ..writeln('  limits:')
    ..writeln(
      '    linear: [${_n(fleet.linearVelocity)}, '
      '${_n(fleet.linearAcceleration)}] # velocity, acceleration',
    )
    ..writeln(
      '    angular: [${_n(fleet.angularVelocity)}, '
      '${_n(fleet.angularAcceleration)}]',
    )
    ..writeln('  profile: # 로봇을 원으로 본 반경. 맵의 로봇 안전 기준에서 가져왔다.')
    ..writeln('    footprint: ${_n(fleet.footprintRadius)}')
    ..writeln('    vicinity: ${_n(fleet.vicinityRadius)}')
    // Pinky의 Nav2 RPP는 allow_reversing=false다. RMF만 후진 가능으로 두면
    // 대기점에서 반대 방향 자세를 목표로 준 뒤 Nav2가 다시 전진 방향으로
    // 돌리는 왕복 회전이 생긴다. 두 계층을 전진 전용으로 맞춘다.
    ..writeln('  reversible: False')
    ..writeln('  battery_system:')
    ..writeln('    voltage: ${_n(fleet.batteryVoltage)}')
    ..writeln('    capacity: ${_n(fleet.batteryCapacity)}')
    ..writeln('    charging_current: ${_n(fleet.chargingCurrent)}')
    ..writeln('  mechanical_system:')
    ..writeln('    mass: ${_n(fleet.mass)}')
    ..writeln('    moment_of_inertia: ${_n(fleet.momentOfInertia)}')
    ..writeln('    friction_coefficient: ${_n(fleet.frictionCoefficient)}')
    ..writeln('  ambient_system:')
    ..writeln('    power: ${_n(fleet.ambientPower)}')
    ..writeln('  tool_system:')
    ..writeln('    power: ${_n(fleet.toolPower)}')
    ..writeln('  recharge_threshold: ${_n(fleet.rechargeThreshold)}')
    ..writeln('  recharge_soc: ${_n(fleet.rechargeSoc)}')
    ..writeln('  publish_fleet_state: 10.0')
    ..writeln('  account_for_battery_drain: True')
    ..writeln('  task_capabilities:')
    ..writeln('    loop: True')
    ..writeln('    delivery: True')
    // 이 플릿이 맡을 수 있는 별도 동작. 여기 없는 것을 작업에 넣으면 RMF 가
    // `Fleet not configured to perform this action` 이라며 통째로 거절한다.
    // `armLoad` 는 앱의 연속 작업에 있는 매니퓰레이터 적재 단계다.
    ..writeln('  actions: ["teleop", "$rmfArmLoadAction"]')
    // Jazzy easy_full_control은 시작 위치가 주차 지점과 같을 때 자동 park를
    // 즉시 완료하는 경로에서 SIGSEGV가 발생할 수 있다.
    ..writeln('  finishing_request: "nothing"')
    // 대기점 도착 뒤 별도 responsive-wait 자세를 만들지 않는다. 작업의 다음
    // 목적지가 정해졌다면 그 경로를 바로 넘겨 불필요한 대기 회전을 막는다.
    ..writeln('  responsive_wait: False')
    ..writeln('  reassign_task_interval: 120')
    ..writeln('  robots:');
  // 플릿은 돌아다니는 로봇의 모임이다. 한자리에 붙은 설치 로봇을 여기 넣으면
  // fleet adapter 가 배차 대상으로 보고 갈 수 없는 곳으로 보내려 한다.
  // Open-RMF 에서 그런 것은 플릿이 아니라 workcell 로 다룬다.
  //
  // Mock 로봇도 넣지 않는다. 앱이 제 안에서 굴리는 것이라 실제로는 없다.
  // 넣으면 fleet adapter 가 오지 않을 로봇의 상태를 계속 기다린다.
  final mobile = [
    for (final robot in robots)
      if (robot.isMobile && robot.isManagedByRmf) robot,
  ];
  if (mobile.isEmpty) {
    buffer.writeln('    {} # 관제 대상 이동 로봇이 없다.');
  } else {
    for (final robot in mobile) {
      buffer
        ..writeln('    ${robot.robotId}:')
        ..writeln('        charger: "${robot.chargerWaypoint ?? ''}"');
    }
  }
  final workcells = [
    for (final robot in robots)
      if (!robot.isMobile && robot.isManagedByRmf) robot,
  ];
  if (workcells.isNotEmpty) {
    buffer
      ..writeln('')
      ..writeln('# 설치 로봇은 플릿에 넣지 않는다. 배차 대상이 아니다.')
      ..writeln('# 이 프로젝트의 설치 로봇:');
    for (final robot in workcells) {
      buffer.writeln(
        '#   ${robot.robotId} · ${robot.displayName} '
        '(${robot.model}) @ ${robot.chargerWaypoint ?? '자리 미지정'}',
      );
    }
  }
  final appOnly = [
    for (final robot in robots)
      if (!robot.isManagedByRmf) robot,
  ];
  if (appOnly.isNotEmpty) {
    buffer
      ..writeln('')
      ..writeln('# 앱 Mock 로봇은 플릿에 넣지 않는다. 실제로는 없는 로봇이다.')
      ..writeln('# 이 프로젝트의 Mock 로봇:');
    for (final robot in appOnly) {
      buffer.writeln('#   ${robot.robotId} · ${robot.displayName}');
    }
  }
  buffer
    ..writeln('')
    ..writeln('fleet_manager:')
    ..writeln('  ip: "${fleet.fleetManagerIp}"')
    ..writeln('  port: ${fleet.fleetManagerPort}');
  return buffer.toString();
}

/// Gazebo 에 띄울 로봇 목록(`fleet.yaml`).
///
/// spawn 좌표는 맵의 Waypoint 에서 가져온다. 맵이 바뀌면 이 값도 함께 바뀌어야
/// 하므로 프로젝트에 묶어 둔다.
String buildFleetSimYaml({
  required List<RmfProjectRobot> robots,
  required String mapName,
}) {
  final buffer = StringBuffer()
    ..writeln('# $mapName 프로젝트에 띄울 로봇 목록.')
    ..writeln('# rmf_control_ui 가 맵 프로젝트에서 생성했다.')
    ..writeln('#')
    ..writeln('# spawn_x / spawn_y 는 맵 Waypoint 좌표다. zones 는 이 로봇이')
    ..writeln('# 진입 가능한 3온도 구획으로 관제 배차의 입찰 자격이 된다.')
    ..writeln('robots:');
  if (robots.isEmpty) {
    buffer.writeln('  [] # 등록된 로봇이 없다.');
  }
  for (final robot in robots) {
    buffer
      ..writeln('  - id: ${robot.robotId}')
      ..writeln('    name: ${robot.displayName}')
      ..writeln('    kind: ${robot.kind.storageValue} # ${robot.kind.label}')
      ..writeln('    model: ${robot.model}')
      ..writeln('    gz_name: ${robot.gzName}')
      ..writeln('    zones: [${robot.zones.join(', ')}]');
    if (robot.chargerWaypoint != null) {
      buffer.writeln(
        robot.isMobile
            ? '    home_charger: ${robot.chargerWaypoint}'
            : '    station: ${robot.chargerWaypoint}',
      );
    }
    if (robot.spawnX != null && robot.spawnY != null) {
      buffer
        ..writeln('    spawn_x: ${_n(robot.spawnX!)}')
        ..writeln('    spawn_y: ${_n(robot.spawnY!)}');
    }
    buffer.writeln('    spawn_heading: ${_n(robot.spawnHeading)}');
  }
  return buffer.toString();
}

/// 프로젝트를 통째로 띄우는 launch 파일.
///
/// RMF core(schedule·blockade·building map server·supervisor·dispatcher)와 이
/// 프로젝트의 fleet adapter 를 함께 띄운다. 경로는 전부 이 프로젝트 것으로
/// 박아 둔다 — 맵마다 building.yaml 도 nav graph 도 플릿 설정도 다르다.
///
/// [mapDirectory] 는 배포 산출물이 있는 곳(`rmf_maps/<맵이름>`)이다. 설정
/// 파일도 같은 곳에 내보내므로 한 디렉터리만 가리키면 된다.
/// 이 프로젝트를 Nav2 가 모는가.
///
/// `rmf_demos_fleet_adapter` 는 slotcar 전용이다. 그것은 Gazebo 안의 slotcar
/// 플러그인에게 직접 명령하고, 우리 핑키에게는 상대가 없다. 토픽을 쓰는 이동
/// 로봇이 하나라도 있으면 그것 대신 이 프로젝트의 nav2 어댑터를 띄워야 한다.
bool projectUsesNav2(List<RmfProjectRobot> robots) =>
    robots.any((robot) => robot.isMobile && robot.dataSource.usesTopics);

String buildProjectLaunchXml({
  required String mapName,
  required String fleetName,
  required String mapDirectory,
  required String buildingYamlName,
  List<RmfProjectRobot> robots = const [],
  bool useSimTime = true,
  // rmf-web 을 안 띄우면 비운다. 주소를 넘기면 RMF 가 1초마다 영원히 다시
  // 붙으려 하고, 그 여덟 줄이 로그를 채워 정작 볼 것을 덮는다.
  String? serverUri,
  // RViz 가 nav graph 를 그리는 굵기. 맵 크기에 견줘 정한다 — 자세한 것은
  // [navGraphLaneWidth].
  double laneWidth = defaultNavGraphLaneWidth,
  // Waypoint 원과 이름표를 Lane 굵기의 몇 배로 그릴까. 상류 기본값은 1.3·0.7
  // 인데, 작은 도면에서는 Waypoint 원끼리 겹쳐서 1.0·0.6 으로 줄였다.
  double waypointScale = 1.0,
  double textScale = .6,
  // RViz 가 로봇을 그릴 공 반지름(m). 플릿의 footprint 를 그대로 쓴다.
  //
  // 이것을 안 넘기면 상류가 **0.5m 를 쓴다** — 지름 1m 짜리 공이다. 2.3m 짜리
  // 도면에서는 건물 절반을 덮는 자홍색 덩어리가 되어 로봇인지도 모른다.
  double footprintRadius = .3,
}) {
  final usesNav2 = projectUsesNav2(robots);
  final buffer = StringBuffer()
    ..writeln("<?xml version='1.0' ?>")
    ..writeln('<!--')
    ..writeln('  $mapName 프로젝트 실행 launch.')
    ..writeln('  rmf_control_ui 가 맵 프로젝트에서 생성했다. 손으로 고치면')
    ..writeln('  다음 저장 때 덮어써진다.')
    ..writeln('')
    ..writeln('  실행:')
    ..writeln('    source /opt/ros/jazzy/setup.bash')
    ..writeln('    source <robosapiens>/rmf_ws/install/setup.bash')
    ..writeln('    ros2 launch $mapDirectory/$mapName.launch.xml')
    ..writeln('-->')
    ..writeln('<launch>')
    ..writeln('  <arg name="use_sim_time" default="$useSimTime"/>')
    ..writeln('  <arg name="headless" default="true"/>')
    ..writeln(
      serverUri == null || serverUri.isEmpty
          ? '  <!-- rmf-web 을 안 씁니다. 주소를 넘기면 dispatcher 가 1초마다\n'
                '       영원히 다시 붙으려 하고, 그 여덟 줄이 로그를 채웁니다.\n'
                '       띄우실 때 server_uri 를 넣으세요. -->\n'
                '  <arg name="server_uri" default=""/>'
          : '  <arg name="server_uri" default="$serverUri"/>',
    )
    ..writeln('  <arg name="map_dir" default="$mapDirectory"/>')
    ..writeln('')
    ..writeln('  <!--')
    ..writeln('    RMF core. 이것이 먼저 떠야 fleet adapter 가 붙는다.')
    ..writeln('')
    ..writeln('    rmf_demos 의 common.launch.xml 을 `include` 하지 않고 같은')
    ..writeln('    내용을 여기 편다. 그 파일이 시각화에 Lane 굵기·글자 크기를')
    ..writeln('    넘기지 않기 때문이다 — 인자로도, set_parameter 로도 밖에서')
    ..writeln('    못 바꾼다(launch_ros 는 노드에 직접 준 param 이 이기게 한다).')
    ..writeln('    기본값 0.5m 는 창고용이라, 2~3m 짜리 도면에서는 Lane 하나가')
    ..writeln('    건물 폭의 1/5 이 되어 스무 개가 서로 겹쳐 덩어리로 보였다.')
    ..writeln('')
    ..writeln('    RMF 가 올라가면 이 부분을 그쪽과 맞춰야 한다. 원본:')
    ..writeln('    \$(find-pkg-share rmf_demos)/common.launch.xml')
    ..writeln('  -->')
    ..writeln('  <arg name="initial_map" default="L1"/>')
    ..writeln('  <arg name="lane_width" default="${_n(laneWidth)}"/>')
    ..writeln('  <arg name="waypoint_scale" default="${_n(waypointScale)}"/>')
    ..writeln('  <arg name="text_scale" default="${_n(textScale)}"/>')
    ..writeln('')
    ..writeln('  <node pkg="rmf_traffic_ros2" exec="rmf_traffic_schedule"')
    ..writeln('        name="rmf_traffic_schedule_primary" output="both">')
    ..writeln('    <param name="use_sim_time" value="\$(var use_sim_time)"/>')
    ..writeln('  </node>')
    ..writeln('  <node pkg="rmf_traffic_ros2" exec="rmf_traffic_blockade"')
    ..writeln('        output="both">')
    ..writeln('    <param name="use_sim_time" value="\$(var use_sim_time)"/>')
    ..writeln('  </node>')
    ..writeln('  <node pkg="rmf_building_map_tools" exec="building_map_server"')
    ..writeln('        args="\$(var map_dir)/$buildingYamlName">')
    ..writeln('    <param name="use_sim_time" value="\$(var use_sim_time)"/>')
    ..writeln('  </node>')
    ..writeln('')
    ..writeln('  <!-- 지도·nav graph·로봇을 마커로 내는 시각화 노드들.')
    ..writeln('')
    ..writeln('       <group> 으로 감싸야 한다. XML launch 의 <include> 는')
    ..writeln('       스스로 범위를 만들지 않아서, 여기 준 <arg> 가 바깥으로')
    ..writeln('       샌다. 안 감쌌더니 아래 headless 가 true 로 덮여 RViz 가')
    ..writeln('       아예 안 떴다 — 오류는 한 줄도 안 났다. -->')
    ..writeln('  <group>')
    // 로봇을 그릴 공의 크기.
    //
    // fleet_states_visualizer 는 로봇을 지름 `2 × <플릿이름>_radius` 짜리
    // SPHERE 로 그린다. 그 값을 **플릿 설정에서 읽지 않는다.** 상류 launch 가
    // rmf_demos 플릿 다섯 개(tinyRobot 0.3 · deliveryRobot 0.6 · caddy 1.5 …)
    // 만 적어 두었고, 목록에 없는 이름은 노드 기본값 0.5m 가 된다.
    //
    // 그래서 지름 1m 짜리 자홍색 공이 나왔다. 2.3m 짜리 도면에서 건물 절반을
    // 덮어 로봇인지 알아볼 수도 없었다. 실제 핑키는 footprint 0.1m 다.
    //
    // <param> 은 남의 launch 안에 있는 노드에 못 붙인다. <set_parameter> 로
    // 이 <group> 안의 모든 노드에 건다 — 이름이 플릿 전용이라 나머지 노드는
    // 선언하지 않고 그냥 지나친다.
    ..writeln('    <set_parameter name="${fleetName}_radius"')
    ..writeln('                   value="${_n(footprintRadius)}"/>')
    ..writeln(
      '    <include file="\$(find-pkg-share rmf_visualization)'
      '/visualization.launch.xml">',
    )
    ..writeln('      <arg name="use_sim_time" value="\$(var use_sim_time)"/>')
    ..writeln('      <arg name="map_name" value="\$(var initial_map)"/>')
    ..writeln('      <arg name="lane_width" value="\$(var lane_width)"/>')
    ..writeln(
      '      <arg name="waypoint_scale" value="\$(var waypoint_scale)"/>',
    )
    ..writeln('      <arg name="text_scale" value="\$(var text_scale)"/>')
    // 이 include 안의 rviz2 는 띄우지 않는다. 그 설정(rmf.rviz)은 office 데모를
    // 보게 맞춰져 있어 우리 도면이 화면 밖이고, 바닥 그림 토픽 이름도 어긋나
    // 있다 — 그래서 창은 뜨는데 까맣다. 아래에서 우리 설정으로 띄운다.
    ..writeln('      <arg name="headless" value="true"/>')
    ..writeln('    </include>')
    ..writeln('  </group>')
    ..writeln('')
    ..writeln('  <node pkg="rmf_fleet_adapter" exec="door_supervisor">')
    ..writeln('    <param name="use_sim_time" value="\$(var use_sim_time)"/>')
    ..writeln('  </node>')
    ..writeln('  <node pkg="rmf_fleet_adapter" exec="lift_supervisor">')
    ..writeln('    <param name="use_sim_time" value="\$(var use_sim_time)"/>')
    ..writeln('  </node>')
    ..writeln('  <node pkg="rmf_fleet_adapter" exec="mutex_group_supervisor"/>')
    ..writeln('  <node pkg="rmf_task_ros2" exec="rmf_task_dispatcher"')
    ..writeln('        output="screen">')
    ..writeln('    <param name="use_sim_time" value="\$(var use_sim_time)"/>')
    ..writeln('    <param name="bidding_time_window" value="2.0"/>')
    ..writeln('    <param name="use_unique_hex_string_with_task_id"')
    ..writeln('           value="true"/>')
    ..writeln('    <param name="server_uri" value="\$(var server_uri)"/>')
    ..writeln('  </node>')
    ..writeln('')
    ..writeln('  <!--')
    ..writeln('    이 맵을 볼 RViz.')
    ..writeln('')
    ..writeln('    설정은 이 프로젝트의 $mapName.rviz 다 — 카메라가 이 도면을')
    ..writeln('    보고, 바닥 그림은 /floorplan 에서 받는다.')
    ..writeln('')
    ..writeln('    use_sim_time 을 반드시 넘긴다. Gazebo 시간으로 찍힌 라이다와')
    ..writeln('    TF 를 벽시계로 보면 시각이 안 맞아 아무것도 안 그려진다.')
    ..writeln('  -->')
    ..writeln('  <group unless="\$(var headless)">')
    ..writeln('    <node pkg="rviz2" exec="rviz2" name="rviz2" output="both"')
    ..writeln('          args="-d \$(var map_dir)/$mapName.rviz">')
    ..writeln('      <param name="use_sim_time" value="\$(var use_sim_time)"/>')
    ..writeln('    </node>')
    ..writeln('  </group>')
    ..writeln('');
  if (usesNav2) {
    buffer
      ..writeln('  <!--')
      ..writeln('    이 프로젝트의 플릿은 여기 없다.')
      ..writeln('')
      ..writeln('    rmf_demos_fleet_adapter 는 slotcar 전용이다. Gazebo 안의')
      ..writeln('    slotcar 플러그인에게 직접 명령하는 것이라, 토픽으로 도는')
      ..writeln('    우리 핑키에게는 상대가 없다. 붙여 놓으면 설정에')
      ..writeln('    user·password 가 없다며 죽고, 죽은 줄 모르면 배차만')
      ..writeln('    하고 로봇은 가만히 있는다.')
      ..writeln('')
      ..writeln('    플릿은 ${mapName}_nav2.launch.xml 이 띄운다. 거기에')
      ..writeln('    Nav2 와 ${mapName}_nav2_adapter.py 가 함께 있다.')
      ..writeln('    실행 스크립트가 이 launch 다음에 그것을 띄운다 —')
      ..writeln('    RMF core 가 먼저 떠야 어댑터가 schedule node 를 찾는다.')
      ..writeln('  -->')
      ..writeln('</launch>');
    return buffer.toString();
  }
  buffer
    ..writeln('  <!-- 이 프로젝트의 플릿. 설정과 nav graph 모두 이 맵의 것이다.')
    ..writeln('       <group> 으로 감싼다 — include 의 <arg> 는 감싸지 않으면')
    ..writeln('       바깥으로 샌다. -->')
    ..writeln('  <group>')
    ..writeln(
      '    <include file="\$(find-pkg-share rmf_demos_fleet_adapter)'
      '/launch/fleet_adapter.launch.xml">',
    )
    ..writeln('      <arg name="use_sim_time" value="\$(var use_sim_time)"/>')
    ..writeln(
      '      <arg name="config_file" value="\$(var map_dir)'
      '/${fleetName}_config.yaml"/>',
    )
    ..writeln(
      '      <arg name="nav_graph_file" '
      'value="\$(var map_dir)/nav_graphs/0.yaml"/>',
    )
    ..writeln('      <arg name="server_uri" value="\$(var server_uri)"/>')
    ..writeln('    </include>')
    ..writeln('  </group>')
    ..writeln('</launch>');
  return buffer.toString();
}

/// Gazebo 와 ROS 사이의 토픽 다리 설정.
///
/// 벤더의 `pinky_bridge.yaml` 은 이름이 상대 경로(`odom`, `cmd_vel`)라서 로봇이
/// 하나일 때만 맞는다. 여러 대를 띄우면 전부 같은 `/odom` 으로 겹친다.
///
/// 그래서 프로젝트마다 **양쪽 다 절대 이름**으로 새로 만든다. 네임스페이스
/// 해석 규칙에 기대지 않으므로 어긋날 여지가 없다.
///
/// `clock` 과 `tf` 는 월드에 하나뿐이라 로봇별로 나누지 않는다. 프레임 이름은
/// `frame_prefix` 로 이미 갈라져 있어 `/tf` 를 함께 써도 섞이지 않는다.
String buildProjectGzBridgeYaml({
  required String mapName,
  required List<RmfProjectRobot> robots,
  bool includeGlobal = true,
}) {
  void entry(
    StringBuffer out, {
    required String ros,
    required String gz,
    required String rosType,
    required String gzType,
    required String direction,
  }) {
    out
      ..writeln('- ros_topic_name: "$ros"')
      ..writeln('  gz_topic_name: "$gz"')
      ..writeln('  ros_type_name: "$rosType"')
      ..writeln('  gz_type_name: "$gzType"')
      ..writeln('  direction: $direction')
      ..writeln();
  }

  final buffer = StringBuffer()
    ..writeln('# $mapName 프로젝트의 ros_gz_bridge 설정.')
    ..writeln('# rmf_control_ui 가 맵 프로젝트에서 생성했다.')
    ..writeln('#')
    ..writeln('# 이름을 양쪽 다 절대 경로로 적는다. 로봇이 여러 대일 때')
    ..writeln('# 상대 이름을 쓰면 전부 같은 토픽으로 겹친다.')
    ..writeln();
  if (includeGlobal) {
    entry(
      buffer,
      ros: '/clock',
      gz: '/clock',
      rosType: 'rosgraph_msgs/msg/Clock',
      gzType: 'gz.msgs.Clock',
      direction: 'GZ_TO_ROS',
    );
    entry(
      buffer,
      ros: '/tf',
      gz: '/tf',
      rosType: 'tf2_msgs/msg/TFMessage',
      gzType: 'gz.msgs.Pose_V',
      direction: 'GZ_TO_ROS',
    );
  }
  // Gazebo 와 ROS 사이의 다리다. Mock 과 실물은 Gazebo 에 없으므로 놓을 다리도
  // 없다. 넣어 두면 오지 않을 토픽을 기다리는 다리가 조용히 남는다.
  final bridged = [
    for (final robot in robots)
      if (robot.runsInGazebo) robot,
  ];
  if (bridged.isEmpty) {
    buffer.writeln('# Gazebo 로 돌릴 로봇이 없다.');
  }
  for (final robot in bridged) {
    final ns = '/${robot.gzName}';
    buffer.writeln(
      '# ${robot.robotId} · ${robot.displayName} (${robot.kind.label})',
    );
    // 설치 로봇에는 다리를 놓지 않는다.
    //
    // 여기에 `joint_states` 다리를 놓아 두었었는데, 옮길 gz 토픽이 애초에
    // 없었다. 이동 로봇의 URDF 에는 `gz::sim::systems::JointStatePublisher` 가
    // 있어 gz 쪽에 그 이름이 생긴다. OpenMANIPULATOR 의 Gazebo 플러그인은
    // `gz_ros2_control` 하나뿐이라 gz 토픽을 아무것도 내지 않는다.
    //
    // 그 대신 `gz_ros2_control` 이 Gazebo 프로세스 **안에서**
    // controller_manager 를 띄우고 ROS 2 로 직접 말한다 —
    // `joint_state_broadcaster` 가 같은 이름의 ROS 토픽을 내고, 팔은
    // `arm_controller`·`gripper_controller` 의 액션으로 움직인다. 다리를
    // 거치지 않는다.
    //
    // 그래서 다리를 놓으면 값은 영영 오지 않으면서 같은 토픽에 발행자만 둘이
    // 된다 — 조용한 다리 하나와 진짜 값을 내는 broadcaster 하나. "다리는
    // 걸려 있는데 값이 안 온다" 로 보이던 것이 이것이다.
    if (!robot.isMobile) {
      buffer
        ..writeln('#   다리 없음. gz_ros2_control 이 ROS 2 로 직접 주고받는다.')
        ..writeln('#   관절 상태: joint_state_broadcaster 가 $ns/joint_states 로 낸다.')
        ..writeln('#   팔 명령: $ns/arm_controller · $ns/gripper_controller 액션.')
        ..writeln();
      continue;
    }
    entry(
      buffer,
      ros: '$ns/odom',
      gz: '$ns/odom',
      rosType: 'nav_msgs/msg/Odometry',
      gzType: 'gz.msgs.Odometry',
      direction: 'GZ_TO_ROS',
    );
    entry(
      buffer,
      // Nav2 controller/behavior -> cmd_vel -> velocity_smoother ->
      // cmd_vel_smoothed 순서다. 원본 cmd_vel 을 Gazebo 에 바로 연결하면
      // 가속·감속 제한과 timeout 정지가 전부 우회된다.
      ros: '$ns/cmd_vel_smoothed',
      gz: '$ns/cmd_vel',
      rosType: 'geometry_msgs/msg/Twist',
      gzType: 'gz.msgs.Twist',
      direction: 'ROS_TO_GZ',
    );
    entry(
      buffer,
      ros: '$ns/scan',
      gz: '$ns/scan',
      rosType: 'sensor_msgs/msg/LaserScan',
      gzType: 'gz.msgs.LaserScan',
      direction: 'GZ_TO_ROS',
    );
    entry(
      buffer,
      ros: '$ns/joint_states',
      gz: '$ns/joint_states',
      rosType: 'sensor_msgs/msg/JointState',
      gzType: 'gz.msgs.Model',
      direction: 'GZ_TO_ROS',
    );
    entry(
      buffer,
      // 벤더 xacro 가 정한 이름이다. 양쪽을 같게 두어야 다리가 어긋나지 않는다.
      ros: '$ns/imu_raw',
      gz: '$ns/imu_raw',
      rosType: 'sensor_msgs/msg/Imu',
      gzType: 'gz.msgs.IMU',
      direction: 'GZ_TO_ROS',
    );
  }
  return buffer.toString();
}

/// Gazebo 에 이 프로젝트의 월드와 로봇을 올리는 bringup launch.
///
/// 로봇마다 네임스페이스를 나눈다. 그래야 `/pinky_01/odom` 처럼 로봇별 토픽이
/// 갈리고, fleet adapter 가 어느 로봇의 위치인지 구분할 수 있다.
///
/// 네임스페이스는 `upload_robot.launch.py` 의 인자로만 넘긴다. `<group>` 에
/// `push-ros-namespace` 를 함께 걸면 `/pinky_01/pinky_01/...` 로 두 번 겹쳐,
/// `create` 가 기다리는 `robot_description` 이 영영 오지 않는다.
String buildProjectBringupXml({
  required String mapName,
  required List<RmfProjectRobot> robots,
  required String mapDirectory,
}) {
  final buffer = StringBuffer()
    ..writeln("<?xml version='1.0' ?>")
    ..writeln('<!--')
    ..writeln('  $mapName 프로젝트의 Gazebo bringup.')
    ..writeln('  rmf_control_ui 가 맵 프로젝트에서 생성했다.')
    ..writeln('')
    ..writeln('  월드는 배포 산출물을 쓰고, 로봇은 이 프로젝트에 등록된 것만')
    ..writeln('  올린다. 로봇마다 네임스페이스를 나눠 토픽을 구분한다.')
    ..writeln('-->')
    ..writeln('<launch>')
    ..writeln('  <arg name="headless" default="true"/>')
    ..writeln('  <arg name="map_dir" default="$mapDirectory"/>')
    ..writeln('  <arg name="world" default="\$(var map_dir)/$mapName.world"/>')
    ..writeln(
      '  <arg name="bridge_params" '
      'default="\$(var map_dir)/${mapName}_gz_bridge.yaml"/>',
    )
    ..writeln('')
    // 없는 패키지를 가리키면 launch 가 통째로 예외를 내며 멈춘다. 워크셀이
    // 하나도 없는데 open_manipulator 를 찾으면, 그것을 안 쓰는 프로젝트에서도
    // Pinky 까지 못 뜬다.
    ..writeln('  <set_env name="GZ_SIM_RESOURCE_PATH"')
    ..writeln(
      '           value="\$(find-pkg-share pinky_description)/../:'
      '${robots.any((robot) => !robot.isMobile && robot.runsInGazebo) ? '\$(find-pkg-share open_manipulator_description)/../:' : ''}'
      '\$(var map_dir)/generated_models:\$(env HOME)/.gazebo/models"/>',
    )
    ..writeln('')
    // `--headless-rendering` 이 있어야 라이다·카메라가 돈다. gpu_lidar 는 GPU
    // 렌더링으로 거리를 재므로 그릴 자리가 없으면 **아무것도 발행하지 않는다.**
    // 토픽 이름은 보이는데 데이터가 영영 안 오고, 오류도 안 난다. 이것이 없으면
    // AMCL 도 Nav2 도 불가능하다.
    // XML 주석 안에는 붙임표 두 개를 쓸 수 없다. 옵션 이름을 그대로 적으면
    // 파일이 깨져서 bringup 이 통째로 안 뜬다.
    ..writeln('  <!-- 화면이 없는 환경에서는 headless 로 서버만 띄운다.')
    ..writeln('       헤드리스 렌더링이 있어야 라이다·카메라가 돈다.')
    ..writeln('       gpu_lidar 는 GPU 로 거리를 재므로 그릴 자리가 없으면')
    ..writeln('       아무것도 발행하지 않는다. 오류도 나지 않는다. -->')
    // include 의 <arg> 는 <group> 으로 감싸지 않으면 바깥으로 샌다.
    ..writeln('  <group>')
    ..writeln(
      '    <include file="\$(find-pkg-share ros_gz_sim)'
      '/launch/gz_sim.launch.py">',
    )
    ..writeln(
      '      <arg name="gz_args"'
      ' value="-r -s -v2 --headless-rendering \$(var world)"/>',
    )
    ..writeln('      <arg name="on_exit_shutdown" value="true"/>')
    ..writeln('    </include>')
    ..writeln('  </group>')
    ..writeln('  <group unless="\$(var headless)">')
    ..writeln(
      '    <include file="\$(find-pkg-share ros_gz_sim)'
      '/launch/gz_sim.launch.py">',
    )
    ..writeln('      <arg name="gz_args" value="-g -v2"/>')
    ..writeln('    </include>')
    ..writeln('  </group>');
  // Gazebo 로 돌리기로 한 것만 올린다. Mock 은 앱 안에만 있고, 실물은 이미
  // 있으므로 시뮬레이터에 또 띄우면 같은 이름이 두 번 뜬다.
  final spawned = [
    for (final robot in robots)
      if (robot.runsInGazebo) robot,
  ];
  if (spawned.isEmpty) {
    buffer
      ..writeln('')
      ..writeln('  <!-- Gazebo 로 돌릴 로봇이 없다. -->')
      ..writeln('  <!-- 로봇 등록에서 값의 출처를 Gazebo 로 골라야 올라온다. -->');
  }
  // 로봇 하나가 디렉터리 하나다. 여기서는 불러오기만 한다.
  //
  // 로봇마다 설정을 제 자리에 두면 한 대를 빼거나 옮길 때 그 디렉터리만
  // 보면 된다. 이 파일에 다 적어 두면 로봇이 늘수록 어느 줄이 누구 것인지
  // 찾기 어려워진다.
  for (final robot in spawned) {
    buffer
      ..writeln('')
      ..writeln(
        '  <!-- ${robot.robotId} · ${robot.displayName} '
        '· ${robot.kind.label} @ ${robot.chargerWaypoint ?? '자리 미지정'} -->',
      );
    // 자리를 안 고르면 spawn 좌표가 없어 지도 원점(0,0)에 놓인다. 건물 밖일
    // 때가 많고, 그러면 로봇은 올라왔는데 아무 데도 안 보인다. 조용히 넘기지
    // 않고 파일에 적어 둔다.
    if (robot.spawnX == null || robot.spawnY == null) {
      buffer.writeln(
        '  <!-- 주의: 자리를 안 골라 spawn 좌표가 없다. '
        '지도 원점에 놓인다. 로봇 등록에서 '
        '${robot.kind.waypointCategory} Waypoint 를 고르세요. -->',
      );
    }
    buffer.writeln(
      '  <include file="\$(var map_dir)/'
      '${robotDirectoryName(robot)}/spawn.launch.xml"/>',
    );
  }
  buffer
    ..writeln('')
    ..writeln('  <!-- 다리는 하나로 묶는다. 설정에 이름이 절대 경로로 적혀')
    ..writeln('       있어 로봇이 몇 대든 겹치지 않는다. -->')
    ..writeln('  <node pkg="ros_gz_bridge" exec="parameter_bridge"')
    ..writeln('        name="gz_bridge" output="screen"')
    ..writeln(
      '        args="--ros-args -p config_file:=\$(var bridge_params)"/>',
    )
    ..writeln('</launch>');
  return buffer.toString();
}

/// 이 프로젝트의 로봇을 띄우는 데 꼭 있어야 하는 ROS 패키지.
///
/// 없는 것을 launch 가 찾으면 통째로 예외를 내며 멈춘다. 워크셀이 하나도 없는
/// 프로젝트에 open_manipulator 를 요구하면, 그것을 쓰지 않는 사람도 Pinky 를
/// 못 띄운다.
List<String> _requiredPackages(List<RmfProjectRobot> robots) => [
  'rmf_demos',
  'rmf_demos_fleet_adapter',
  // building.yaml 에서 nav_graphs/0.yaml 을 다시 만드는 데 쓴다.
  'rmf_building_map_tools',
  'ros_gz_sim',
  if (robots.any((robot) => robot.runsInGazebo && robot.isMobile)) ...[
    'pinky_description',
    // 벤더 launch 대신 우리가 직접 띄우므로 이 둘이 있어야 한다.
    'robot_state_publisher',
    'joint_state_publisher',
  ],
  if (robots.any((robot) => robot.runsInGazebo && !robot.isMobile))
    'open_manipulator_description',
];

/// Isaac Sim에서 프로젝트 USD stage를 열고 ROS 2 Action Graph를 실행한다.
///
/// USD에는 로봇 articulation과 /clock·odom·scan·joint_states·tf·cmd_vel 그래프가
/// 들어 있어야 한다. 이 실행기는 stage 경로와 GUI/headless 선택을 표준화한다.
String buildIsaacProjectScript({required String mapName}) =>
    '''#!/usr/bin/env python3
import argparse

parser = argparse.ArgumentParser()
parser.add_argument('--stage', required=True)
display = parser.add_mutually_exclusive_group()
display.add_argument('--headless', action='store_true')
display.add_argument('--gui', action='store_true')
args = parser.parse_args()

from isaacsim import SimulationApp

app = SimulationApp({'headless': not args.gui})

import omni.timeline
from isaacsim.core.utils.extensions import enable_extension
from isaacsim.core.utils.stage import open_stage

enable_extension('isaacsim.ros2.bridge')
open_stage(args.stage)
app.update()

timeline = omni.timeline.get_timeline_interface()
timeline.play()
try:
    while app.is_running():
        app.update()
finally:
    timeline.stop()
    app.close()
''';

/// 프로젝트를 통째로 띄우는 셸 스크립트.
///
/// ROS 환경을 읽고 bringup 과 RMF 를 순서대로 띄운다. Gazebo 가 먼저 떠야
/// `/clock` 이 나오고, 그래야 use_sim_time 을 쓰는 RMF 노드가 시간을 맞춘다.
String buildProjectRunScript({
  required String mapName,
  required String mapDirectory,
  List<RmfProjectRobot> robots = const [],
  String rosSetup = '/opt/ros/jazzy/setup.bash',
  String rmfWorkspace = r'$APP_ROOT/rmf_ws',
  String pinkyWorkspace = r'$APP_ROOT/robot_model/pinky_pro',
  String manipulatorWorkspace = r'$APP_ROOT/robot_model/open_manipulator',
  int rosDomainId = defaultRosDomainId,
}) =>
    '''#!/usr/bin/env bash
# $mapName 프로젝트 실행.
# rmf_control_ui 가 맵 프로젝트에서 생성했다. 손으로 고치면 다음 저장 때
# 덮어써진다.
#
# 순서가 중요하다. Gazebo 가 먼저 떠야 /clock 이 나오고, 그래야 use_sim_time 을
# 쓰는 RMF 노드가 시간을 맞춘다. 반대로 하면 RMF 가 시간이 멈춘 줄 알고 멈춰
# 있는다.
set -euo pipefail

# ROS 도메인. 같은 도메인끼리만 서로를 본다.
#
# 이것이 어긋나면 **아무 오류도 안 나면서** 아무것도 안 통한다. 앱이 띄운
# 것과 터미널에서 띄운 것이 서로를 못 보던 일이 그래서 생겼다 — 앱은
# 비대화형 셸로 스크립트를 돌리므로 ~/.bashrc 의 export 를 못 읽는다.
# 그래서 맵 프로젝트가 정한 값을 여기 박아 둔다.
export ROS_DOMAIN_ID="\${ROS_DOMAIN_ID:-$rosDomainId}"

MAP_DIR="\${MAP_DIR:-$mapDirectory}"
APP_ROOT="\${ROBOSAPIENS_ROOT:-\$(cd "\$MAP_DIR/../.." && pwd)}"
ROS_SETUP="\${ROS_SETUP:-$rosSetup}"
RMF_WS="\${RMF_WS:-$rmfWorkspace}"
PINKY_WS="\${PINKY_WS:-$pinkyWorkspace}"
OMX_WS="\${OMX_WS:-$manipulatorWorkspace}"

# 상용 배포 구조는 하나로 고정한다. 환경 변수로 예전 경로를 넘겨 조용히
# 실행하면 개발 PC에서는 되지만 고객 패키지에서는 빠지는 파일이 생긴다.
EXPECTED_RMF_WS="\$APP_ROOT/rmf_ws"
EXPECTED_PINKY_WS="\$APP_ROOT/robot_model/pinky_pro"
EXPECTED_OMX_WS="\$APP_ROOT/robot_model/open_manipulator"
WORKSPACE_ENTRIES=(
  "RMF_WS|\$RMF_WS|\$EXPECTED_RMF_WS"
  "PINKY_WS|\$PINKY_WS|\$EXPECTED_PINKY_WS"
  "OMX_WS|\$OMX_WS|\$EXPECTED_OMX_WS"
)
for entry in "\${WORKSPACE_ENTRIES[@]}"; do
  IFS='|' read -r label actual expected <<< "\$entry"
  if [[ "\$actual" != "\$expected" || -L "\$actual" || ! -d "\$actual" ]]; then
    echo "잘못된 RoboSapiens 파일 구조: \$label=\$actual" >&2
    echo "실제 디렉터리를 다음 위치에 두세요: \$expected" >&2
    echo "심볼릭 링크와 외부 workspace는 지원하지 않습니다." >&2
    exit 1
  fi
done
if [[ ! -f "\$RMF_WS/install/setup.bash" ]]; then
  echo "Open-RMF가 빌드되지 않았습니다: \$RMF_WS/install/setup.bash" >&2
  exit 1
fi

# 이 프로젝트의 로봇이 실제로 쓰는 패키지. 등록된 로봇에서 뽑았다.
REQUIRED_PACKAGES="${_requiredPackages(robots).join(' ')}"

# 창을 띄울지 말지. Gazebo 와 RViz 를 따로 고른다.
#
# 예전에는 HEADLESS 하나가 둘을 함께 껐다 켰다 했다. 그런데 보고 싶은 것이
# 서로 다르다 — 로봇이 물리적으로 어디 있는지는 Gazebo 창에서, 계획한 경로와
# 코스트맵은 RViz 에서 본다. 하나만 보려고 둘을 다 띄우면 이 컴퓨터에서
# 프레임이 떨어져 시뮬레이션까지 느려졌다.
#
# 둘 다 안 띄워도 라이다·카메라는 돈다. Gazebo 서버는 언제나 헤드리스
# 렌더링으로 뜨기 때문이다. 창은 보는 용도일 뿐 데이터와는 무관하다.
#
# 앱이 실행할 때 환경 변수로 넘긴다. 터미널에서 직접 띄울 때는 이렇게 쓴다:
#   GAZEBO_GUI=true RVIZ=true ./run_$mapName.sh
is_true() {
  case "\${1,,}" in
    true|1|yes|on) return 0 ;;
    *) return 1 ;;
  esac
}

# HEADLESS 만 준 예전 방식도 그대로 받는다. 따로 준 값이 있으면 그쪽이 이긴다.
if is_true "\${HEADLESS:-true}"; then
  GUI_DEFAULT=false
else
  GUI_DEFAULT=true
fi
GAZEBO_GUI="\${GAZEBO_GUI:-\$GUI_DEFAULT}"
SIMULATOR_GUI="\${SIMULATOR_GUI:-\$GAZEBO_GUI}"
SIM_BACKEND="\${SIM_BACKEND:-gazebo}"
RVIZ="\${RVIZ:-\$GUI_DEFAULT}"

case "\$SIM_BACKEND" in
  gazebo|isaac_sim|none) ;;
  *)
    echo "지원하지 않는 SIM_BACKEND: \$SIM_BACKEND (gazebo|isaac_sim|none)" >&2
    exit 1
    ;;
esac

# launch 인자는 반대말(headless)이다. 여기서 한 번만 뒤집는다.
if is_true "\$GAZEBO_GUI"; then GAZEBO_HEADLESS=false; else GAZEBO_HEADLESS=true; fi
if is_true "\$RVIZ"; then RVIZ_HEADLESS=false; else RVIZ_HEADLESS=true; fi

BUILDING_YAML="\$MAP_DIR/$mapName.building.yaml"
NAV_GRAPH="\$MAP_DIR/nav_graphs/0.yaml"

if [[ ! -f "\$BUILDING_YAML" ]]; then
  echo "없는 파일: \$BUILDING_YAML" >&2
  echo "앱의 맵 관리에서 배포하기와 RMF 설정 내보내기를 먼저 하세요." >&2
  exit 1
fi

set +u
# shellcheck disable=SC1090
source "\$ROS_SETUP"
[[ -f "\$RMF_WS/install/setup.bash" ]] && source "\$RMF_WS/install/setup.bash"
[[ -f "\$PINKY_WS/install/setup.bash" ]] && source "\$PINKY_WS/install/setup.bash"
[[ -f "\$OMX_WS/install/setup.bash" ]] && source "\$OMX_WS/install/setup.bash"
set -u

# C++ RMF 라이브러리와 Python 바인딩이 다른 설치본에서 섞이면 다중 로봇
# 등록 중 SIGSEGV가 날 수 있으므로 작업공간 설치본만 허용한다.
RMF_ADAPTER_MODULE="\$(python3 -c 'import rmf_adapter; print(rmf_adapter.__file__)' 2>/dev/null || true)"
case "\$RMF_ADAPTER_MODULE" in
  "\$RMF_WS"/install/*) ;;
  *)
    echo "호환되지 않는 rmf_adapter가 선택됐습니다: \${RMF_ADAPTER_MODULE:-찾지 못함}" >&2
    echo "필요한 경로: \$RMF_WS/install 아래" >&2
    echo "RMF↔Nav2 어댑터를 시작하지 않습니다." >&2
    exit 1
    ;;
esac
echo "RMF adapter: \$RMF_ADAPTER_MODULE"

# nav_graphs/0.yaml 은 building.yaml 에서 파생된다. 맵에서 Waypoint 나 Lane 을
# 고쳐도 이 파일이 그대로면 RMF 는 옛날 지도를 본다. 없는 것이 아니라 낡은
# 것이라 오류가 나지 않는다 — 충전 Waypoint 를 방금 이었는데도 RMF 가 "충전
# 지점을 못 찾겠다"고 하는 것이 이 경우다. 그래서 매번 다시 만든다.
if [[ ! -f "\$NAV_GRAPH" || "\$BUILDING_YAML" -nt "\$NAV_GRAPH" ]]; then
  echo "nav_graphs/0.yaml 을 building.yaml 에서 다시 만든다."
  mkdir -p "\$MAP_DIR/nav_graphs"
  if ! ros2 run rmf_building_map_tools building_map_generator nav \\
      "\$BUILDING_YAML" "\$MAP_DIR/nav_graphs"; then
    echo "nav graph 생성 실패. rmf_building_map_tools 가 있는지 보세요." >&2
    exit 1
  fi
fi

if [[ ! -f "\$NAV_GRAPH" ]]; then
  echo "없는 파일: \$NAV_GRAPH" >&2
  exit 1
fi

# 모든 출력을 로그 파일로 보낸다.
#
# 앱이 이 스크립트를 파이프에 물려 띄우면, 그 파이프를 읽는 쪽이 없을 때
# 64KB 가 차는 순간 Gazebo 가 write 에서 영원히 멈춘다. 물리가 돌지 않아
# 모델도 안 올라오고 토픽에 값도 오지 않는다. 파일로 보내면 막힐 일이 없고,
# 무슨 일이 있었는지 나중에 볼 수도 있다.
#
# 다만 그대로 두면 감당이 안 된다. Gazebo 의 ODE 가 메시끼리 닿을 때마다
# 같은 경고 한 줄을 물리 스텝마다 찍어, 시간당 1.8GB 씩 찼다. 그래서 거른다.
#
#   1. launch 접두사만 있고 내용이 없는 줄은 버린다.
#   2. 바로 앞과 똑같은 줄은 세기만 하고, 다른 줄이 오면 "몇 번 더" 로 접는다.
#   3. 그래도 넘치면 한 번 밀어 두고 새로 쓴다 (최대 2 배까지만 남는다).
#
# 에러만 남기지는 않는다. 지금까지 원인을 알려 준 것은 대부분 ERROR 가 아니라
# 뜨는 순서였다 — Gazebo 가 먼저인지, /clock 이 나왔는지, 다리가 어느 토픽을
# 걸었는지. 대신 ERROR·경고·역추적만 따로 모은 파일을 하나 더 쓴다.
LOG_FILE="\$MAP_DIR/$mapName.log"
ERR_FILE="\$MAP_DIR/$mapName.err.log"
LOG_MAX_MB="\${LOG_MAX_MB:-200}"

# UI의 두 실행 경로가 거의 동시에 눌려도 두 번째 스크립트가 기존 로그를
# 비우거나 같은 월드를 한 벌 더 띄우지 못하게 한다. 잠금 FD는 이 셸이 끝날
# 때까지 유지된다.
LOCK_FILE="\$MAP_DIR/.$mapName.run.lock"
exec 9>"\$LOCK_FILE"
if ! flock -n 9; then
  echo "$mapName 프로젝트가 이미 실행 중입니다." >&2
  exit 1
fi
: > "\$ERR_FILE"

# mawk 는 detached 세션의 프로세스 치환 파이프에서 읽기가 멈춘 사례가 있다.
# unbuffered Python 수집기는 시작할 때 파일을 먼저 열고 한 줄씩 즉시 기록한다.
exec > >(exec python3 -u "\$APP_ROOT/openrmf/scripts/log_collector.py" \\
  --out "\$LOG_FILE" --err "\$ERR_FILE" --max-mb "\$LOG_MAX_MB") 2>&1
echo "=== \$(date '+%Y-%m-%d %H:%M:%S') $mapName 실행 ==="
# 창을 띄웠는지 안 띄웠는지 로그만 봐도 알게 한다. "화면이 안 뜬다" 는 물음이
# 실은 안 띄우기로 고른 것이었던 적이 여러 번이다.
echo "Gazebo 창: \$GAZEBO_GUI · RViz: \$RVIZ · ROS_DOMAIN_ID: \$ROS_DOMAIN_ID"
echo "시뮬레이션 백엔드: \$SIM_BACKEND · 시뮬레이터 창: \$SIMULATOR_GUI"

# 자기 프로세스 그룹 번호를 남긴다. 중지 스크립트가 이 그룹을 통째로 끊는다.
# 앱이 detached 로 띄우면 이 셸의 PID 는 그룹 리더가 아니므로, PID 가 아니라
# 실제 PGID 를 적어야 한다.
PGID_FILE="\$MAP_DIR/.$mapName.pgid"
ps -o pgid= -p \$\$ | tr -d ' ' > "\$PGID_FILE"

cleanup() {
  echo "정리 중..."
  kill \$(jobs -p) 2>/dev/null || true
  # PGID 파일은 지우지 않는다.
  #
  # 이 셸이 먼저 끝나고 자식이 살아남는 일이 있다. 그때 파일까지 지우면
  # 그 그룹을 끊을 손잡이가 사라져, 중지 스크립트도 다음 실행의 남은 항목
  # 검사도 그 프로세스를 영영 못 찾는다. 파일은 중지 스크립트가 지운다.
}
trap cleanup EXIT INT TERM

# 필요한 패키지가 없으면 launch 가 통째로 예외를 내며 멈춘다. 그러면 다른
# 로봇까지 안 뜨는데, 화면에는 찾아본 경로 목록만 잔뜩 나와 원인을 알기 어렵다.
missing=()
for pkg in \$REQUIRED_PACKAGES; do
  if [[ "\$SIM_BACKEND" != gazebo && "\$pkg" == ros_gz_sim ]]; then
    continue
  fi
  ros2 pkg prefix "\$pkg" >/dev/null 2>&1 || missing+=("\$pkg")
done
if ((\${#missing[@]} > 0)); then
  echo "없는 ROS 패키지: \${missing[*]}" >&2
  echo "" >&2
  echo "이 프로젝트의 로봇을 띄우려면 아래를 빌드하고 다시 실행하세요." >&2
  for pkg in "\${missing[@]}"; do
    case "\$pkg" in
      pinky_*) echo "  \$pkg  ->  cd \$PINKY_WS && colcon build" >&2 ;;
      open_manipulator_*) echo "  \$pkg  ->  cd \$OMX_WS && colcon build" >&2 ;;
      *) echo "  \$pkg" >&2 ;;
    esac
  done
  exit 1
fi

# 월드에 센서 시스템을 채운다.
#
# 월드는 rmf_building_map_tools 가 제 템플릿(gz_world.sdf)에서 만드는데, 거기에는
# Physics · UserCommands · SceneBroadcaster 셋뿐이다. RMF 의 시범 로봇(slotcar)은
# 라이다를 안 쓰므로 필요가 없었다.
#
# 우리 핑키는 gpu_lidar · camera · imu 를 단다. 센서 시스템이 없으면 이 센서들이
# **하나도 발행하지 않는다.** 토픽 이름은 보이는데 데이터가 영영 안 온다. 라이다가
# 없으면 AMCL 도 Nav2 도 불가능하다.
#
# 배포할 때마다 월드가 다시 만들어지므로 여기서 매번 채운다. 이미 있으면 넘어간다.
ensure_world_sensors() {
  local world="\$1"
  [ -f "\$world" ] || return 0
  python3 - "\$world" <<'PYTHON'
import sys

path = sys.argv[1]
with open(path, encoding='utf-8') as handle:
    world = handle.read()

# 이름으로 찾는다. filename 은 앞에 lib 이 붙기도 하고 안 붙기도 한다.
wanted = [
    ('gz::sim::systems::Sensors',
     '    <plugin filename="gz-sim-sensors-system"\\n'
     '            name="gz::sim::systems::Sensors">\\n'
     '      <render_engine>ogre2</render_engine>\\n'
     '    </plugin>\\n'),
    ('gz::sim::systems::Imu',
     '    <plugin filename="gz-sim-imu-system"\\n'
     '            name="gz::sim::systems::Imu">\\n'
     '    </plugin>\\n'),
]
added = [name for name, _ in wanted if name not in world]
if not added:
    print('월드에 센서 시스템이 이미 있습니다.')
    sys.exit(0)

block = ''.join(snippet for name, snippet in wanted if name not in world)
# <world ...> 바로 다음에 넣는다. 시스템 플러그인은 월드의 자식이어야 한다.
marker = world.index('>', world.index('<world')) + 1
with open(path, 'w', encoding='utf-8') as handle:
    handle.write(world[:marker] + '\\n' + block + world[marker:])
print('월드에 센서 시스템을 넣었습니다: ' + ', '.join(added))
PYTHON
}
ensure_world_sensors "\$MAP_DIR/$mapName.world"

# 월드의 충돌 검출기를 bullet 으로 바꾼다.
#
# 기본값은 ODE 인데, 메시끼리 닿으면 무너진다. 우리 로봇은 충돌 도형이 전부
# 메시(핑키의 base_link.stl 따위)이고, 건물 바닥·벽도 배포가 만든 메시
# (generated_models/<맵>_L1/meshes/floor_1.obj)다. 그래서 로봇이 바닥에 서 있는
# 것만으로도 메시 대 메시다.
#
# 로봇 두 대가 겹쳐 놓이면 접점이 폭발해 여기서 죽는다:
#
#   ODE Message 2: Trimesh-trimesh contact hash table bucket overflow   (103번)
#   ODE INTERNAL ERROR 1: assertion "keyindex < lastkeyindex || ..." failed
#     in UpdateArbitraryContactInNode() [collision_trimesh_trimesh.cpp:285]
#   [ERROR] [gazebo-1]: process has died ... exit code 134
#
# 자리를 안 고른 로봇은 전부 지도 원점에 놓이므로 두 대만 있어도 이렇게 된다.
# 실제로 스폰 4초 만에 Gazebo 가 죽었고, 그 뒤 RMF 와 Nav2 만 살아남아 토픽
# 이름은 있는데 값은 하나도 안 오는 상태로 30분을 돌았다.
#
# bullet 은 같은 조건에서 경고 한 줄 없이 버틴다. 주행 거리도 ODE 와 같다
# (0.2 m/s 로 4초에 ODE 0.811 m · bullet 0.807 m). 자리를 겹쳐 놓는 것 자체는
# 여전히 잘못이지만, 그것 때문에 시뮬레이터가 죽지는 않게 한다.
#
# 배포할 때마다 월드가 다시 만들어지므로 여기서 매번 채운다. 이미 있으면 넘어간다.
ensure_world_collision_detector() {
  local world="\$1"
  [ -f "\$world" ] || return 0
  python3 - "\$world" <<'PYTHON'
import re
import sys

path = sys.argv[1]
with open(path, encoding='utf-8') as handle:
    world = handle.read()

if '<collision_detector>' in world:
    print('월드에 충돌 검출기가 이미 지정돼 있습니다.')
    sys.exit(0)

block = ('      <dart>\\n'
         '        <collision_detector>bullet</collision_detector>\\n'
         '      </dart>\\n')

opening = re.search(r'<physics\\b[^>]*?(/?)>', world)
if opening is None:
    # 월드를 못 고쳐도 실행은 계속한다. 여기서 멈추면 다른 로봇까지 안 뜬다.
    sys.stderr.write('<physics> 가 없어 충돌 검출기를 못 넣었습니다.\\n')
    sys.exit(0)

if opening.group(1):
    # <physics ... /> 처럼 닫혀 있으면 열어서 넣는다.
    head = opening.group(0)[:-2].rstrip() + '>\\n'
    world = (world[:opening.start()] + head + block + '    </physics>'
             + world[opening.end():])
else:
    end = world.find('</physics>', opening.end())
    if end < 0:
        sys.stderr.write('</physics> 가 없어 충돌 검출기를 못 넣었습니다.\\n')
        sys.exit(0)
    # 닫는 태그가 놓인 줄의 맨 앞에서 자른다. 태그 바로 앞에서 자르면 그 줄의
    # 들여쓰기가 우리 블록 앞에 붙고 </physics> 가 1열로 밀린다.
    head = world.rfind('\\n', 0, end) + 1
    if world[head:end].strip():
        head = end
    world = world[:head] + block + world[head:]

with open(path, 'w', encoding='utf-8') as handle:
    handle.write(world)
print('월드의 충돌 검출기를 bullet 으로 바꿨습니다.')
PYTHON
}
ensure_world_collision_detector "\$MAP_DIR/$mapName.world"

# Gazebo 가 실제로 떴는지 보고 다음 단계로 넘어간다.
#
# 예전에는 `&` 로 띄우고 `sleep 12` 만 했다. 뜬 줄 알고 넘어간 것이지 확인한
# 것이 아니었다. 그래서 Gazebo 가 스폰 4초 만에 죽었는데도(ODE 메시 충돌
# 어서션, exit 134) RMF 와 Nav2 가 그 시체 위에 올라갔다. 프로세스는 15개가
# 30분 넘게 살아 있었고 토픽 이름도 다 나왔지만 발행자는 0개였다 — 이름은
# 다리와 구독자가 남긴 것이다. 무엇이 잘못됐는지 어디에도 안 보였다.
#
# 두 가지를 본다. 월드를 물고 있는 `gz sim` 이 있는가, 그리고 /clock 이 나오는가.
# 떠 있는 것과 물리가 도는 것은 다르다. use_sim_time 을 쓰는 RMF 노드는 /clock
# 이 없으면 시간이 멈춘 줄 알고 그대로 멈춰 있는다.
GAZEBO_WAIT="\${GAZEBO_WAIT:-90}"
wait_for_gazebo() {
  local world="\$1"
  local deadline=\$((SECONDS + GAZEBO_WAIT))
  while ((SECONDS < deadline)); do
    if pgrep -u "\$(id -u)" -f "gz sim.*\$world" >/dev/null 2>&1 &&
       timeout 5 ros2 topic echo /clock --once >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  return 1
}

# 선택한 물리 백엔드를 시작한다. 양쪽 모두 같은 ROS 토픽(/clock, odom, scan,
# joint_states, tf, cmd_vel)을 제공해야 이후 Nav2와 RMF를 그대로 쓸 수 있다.
start_simulator() {
  case "\$SIM_BACKEND" in
    gazebo)
      echo "${projectUsesNav2(robots) ? '[1/3]' : '[1/2]'} Gazebo bringup"
      ros2 launch "\$MAP_DIR/${mapName}_bringup.launch.xml" headless:="\$GAZEBO_HEADLESS" &
      if ! wait_for_gazebo "\$MAP_DIR/$mapName.world"; then
        echo "Gazebo 가 \$GAZEBO_WAIT 초 안에 뜨지 않았습니다." >&2
        return 1
      fi
      ;;
    isaac_sim)
      local launcher="\${ISAAC_SIM_PYTHON:-\${ISAAC_SIM_ROOT:-\$HOME/isaacsim}/python.sh}"
      local script="\${ISAAC_PROJECT_SCRIPT:-\$MAP_DIR/isaac/start_$mapName.py}"
      local stage="\${ISAAC_STAGE:-\$MAP_DIR/isaac/$mapName.usd}"
      if [[ ! -x "\$launcher" ]]; then
        echo "Isaac Sim Python 실행기를 찾지 못했습니다: \$launcher" >&2
        echo "ISAAC_SIM_ROOT 또는 ISAAC_SIM_PYTHON을 지정하세요." >&2
        return 1
      fi
      if [[ ! -f "\$script" || ! -f "\$stage" ]]; then
        echo "Isaac Sim 프로젝트 산출물이 없습니다." >&2
        echo "필요한 파일: \$script" >&2
        echo "필요한 파일: \$stage" >&2
        return 1
      fi
      local gui_arg="--headless"
      is_true "\$SIMULATOR_GUI" && gui_arg="--gui"
      echo "Isaac Sim bringup: \$stage"
      "\$launcher" "\$script" --stage "\$stage" "\$gui_arg" &
      local deadline=\$((SECONDS + GAZEBO_WAIT))
      while ((SECONDS < deadline)); do
        timeout 5 ros2 topic echo /clock --once >/dev/null 2>&1 && return 0
        sleep 2
      done
      echo "Isaac Sim이 \$GAZEBO_WAIT 초 안에 /clock을 발행하지 않았습니다." >&2
      return 1
      ;;
    none)
      echo "물리 시뮬레이터 없이 RMF/RViz만 시작합니다."
      ;;
  esac
}

${projectUsesNav2(robots) ? '''
echo "[1/3] 시뮬레이션 백엔드"
if ! start_simulator; then
  echo "" >&2
  echo "시뮬레이션 백엔드가 준비되지 않았습니다." >&2
  echo "RMF 와 Nav2 는 띄우지 않고 여기서 멈춥니다 — 물리가 없으면 그 둘은" >&2
  echo "토픽 이름만 만들어 놓고 값은 하나도 못 받습니다." >&2
  echo "" >&2
  echo "무엇이 있었는지: \$LOG_FILE" >&2
  echo "오류만 모은 것: \$ERR_FILE" >&2
  exit 1
fi

echo "[2/3] Open-RMF"
ros2 launch "\$MAP_DIR/$mapName.launch.xml" headless:="\$RVIZ_HEADLESS" &
sleep 12

# RMF↔Nav2 어댑터가 뜨고 계속 살아 있는지 지켜본다.
#
# 이 어댑터가 죽어도 Gazebo·Nav2·RMF core 는 그대로 남는다. 그래서 토픽은 잘
# 오는데 주문만 안 먹는 상태가 된다. 화면에는 `RMF 가 답하지 않았습니다` 로만
# 보이고 무엇이 죽었는지는 어디에도 안 나왔다.
#
# 실제로 로봇 ID 에 하이픈이 있어(`PK-01`) 어댑터가 로봇을 플릿에 붙이는 순간
# 죽은 일이 있다. RMF 가 `rmf/dynamic_event/begin/<플릿>/<로봇>` 토픽을 만드는데
# ROS 2 토픽 이름에는 하이픈을 못 쓰기 때문이다.
ADAPTER_WAIT="\${ADAPTER_WAIT:-90}"
# launch 의 respawn_delay 보다 넉넉해야 한다. 짧으면 다시 뜨는 중인 것을 두고
# 죽었다고 알린다.
ADAPTER_RESPAWN_WAIT="\${ADAPTER_RESPAWN_WAIT:-30}"
ADAPTER_HEALTH_GRACE="\${ADAPTER_HEALTH_GRACE:-120}"
ADAPTER_HEALTH_INTERVAL="\${ADAPTER_HEALTH_INTERVAL:-30}"
ADAPTER_HEALTH_FAILURES="\${ADAPTER_HEALTH_FAILURES:-3}"
EXPECTED_FLEET_ROBOTS="${robots.where((robot) => robot.isMobile && robot.runsInGazebo).map((robot) => robot.robotId).join(' ')}"
watch_fleet_adapter() {
  local pattern="\$MAP_DIR/${mapName}_nav2_adapter.py"
  local deadline=\$((SECONDS + ADAPTER_WAIT))
  while ((SECONDS < deadline)); do
    pgrep -u "\$(id -u)" -f "\$pattern" >/dev/null 2>&1 && break
    sleep 2
  done
  if ! pgrep -u "\$(id -u)" -f "\$pattern" >/dev/null 2>&1; then
    echo "" >&2
    echo "RMF↔Nav2 어댑터가 \$ADAPTER_WAIT 초 안에 뜨지 않았습니다." >&2
    echo "RMF 는 주문을 받아도 배차할 플릿이 없습니다." >&2
    echo "오류만 모은 것: \$ERR_FILE" >&2
    return
  fi
  echo "RMF↔Nav2 어댑터가 떴습니다."
  local health_after=\$((SECONDS + ADAPTER_HEALTH_GRACE))
  local last_health=0
  local failed_health=0
  # 뜬 다음 죽는 것이 진짜 문제다. 계속 지켜본다.
  #
  # 다만 launch 가 respawn 으로 다시 띄운다. 사라진 그 순간에 죽었다고 알리면
  # 5초 뒤 멀쩡히 살아난 것을 두고 사람을 뛰게 만든다. 돌아오기를 기다렸다가,
  # 정말 안 돌아올 때만 알린다.
  while :; do
    if pgrep -u "\$(id -u)" -f "\$pattern" >/dev/null 2>&1; then
      if ((SECONDS >= health_after && SECONDS - last_health >= ADAPTER_HEALTH_INTERVAL)); then
        last_health=\$SECONDS
        local fleet_state
        fleet_state="\$(timeout 12 ros2 topic echo /fleet_states --once 2>/dev/null || true)"
        local missing=0
        local robot
        for robot in \$EXPECTED_FLEET_ROBOTS; do
          if ! grep -Fq "name: \$robot" <<<"\$fleet_state"; then
            missing=1
            echo "RMF fleet state에 \$robot 등록이 없습니다." >&2
          fi
        done
        if ((missing)); then
          failed_health=\$((failed_health + 1))
          if ((failed_health >= ADAPTER_HEALTH_FAILURES)); then
            echo "fleet 등록 확인이 \$failed_health 회 연속 실패했습니다. 어댑터를 재기동합니다." >&2
            pkill -u "\$(id -u)" -f "\$pattern" || true
            failed_health=0
            health_after=\$((SECONDS + ADAPTER_HEALTH_GRACE))
          fi
        else
          failed_health=0
        fi
      fi
      sleep 5
      continue
    fi
    local back=\$((SECONDS + ADAPTER_RESPAWN_WAIT))
    local revived=0
    while ((SECONDS < back)); do
      sleep 2
      if pgrep -u "\$(id -u)" -f "\$pattern" >/dev/null 2>&1; then
        revived=1
        break
      fi
    done
    if ((revived)); then
      echo "RMF↔Nav2 어댑터가 죽었다가 다시 떴습니다." >&2
      continue
    fi
    break
  done
  echo "" >&2
  echo "RMF↔Nav2 어댑터가 죽었고 다시 뜨지도 않았습니다." >&2
  echo "이제 RMF 는 주문을 받지 못하고, RViz 에서는 경로와 로봇이 사라집니다 —" >&2
  echo "그 둘을 내는 /nav_graphs · /fleet_states 가 이 어댑터에서만 나옵니다." >&2
  echo "Gazebo 와 Nav2 는 그대로 살아 있어 토픽은 계속 옵니다. 그래서 겉으로는" >&2
  echo "멀쩡해 보입니다." >&2
  echo "" >&2
  echo "먼저 위에 출력된 RMF adapter 경로가 rmf_ws/install 아래인지 확인하세요." >&2
  echo "C++ 라이브러리와 Python 바인딩의 설치본이 섞이면 다중 로봇 등록 중" >&2
  echo "SIGSEGV가 날 수 있습니다." >&2
  echo "또 다른 원인은 로봇 ID 입니다. RMF 가 ID 로 토픽을 만드는데" >&2
  echo "(rmf/dynamic_event/begin/<플릿>/<로봇>) 영문·숫자·밑줄만 쓸 수 있습니다." >&2
  echo "하이픈이 들어간 ID 는 로봇을 플릿에 붙이는 순간 어댑터를 죽입니다." >&2
  echo "" >&2
  echo "무엇이 있었는지: \$LOG_FILE" >&2
  echo "오류만 모은 것: \$ERR_FILE" >&2
}

# Nav2 와 RMF↔Nav2 어댑터. 이것이 없으면 RMF 가 배차해도 로봇이 안 움직인다 —
# /<로봇>/cmd_vel 에 발행하는 것이 아무것도 없기 때문이다.
#
# RMF core 다음이라야 한다. 어댑터는 뜨자마자 schedule node 를 찾는다.
echo "[3/3] Nav2 와 RMF 어댑터"
watch_fleet_adapter &
ros2 launch "\$MAP_DIR/${mapName}_nav2.launch.xml"''' : '''
echo "[1/2] 시뮬레이션 백엔드"
if ! start_simulator; then
  echo "" >&2
  echo "시뮬레이션 백엔드가 준비되지 않았습니다." >&2
  echo "Open-RMF 는 띄우지 않고 여기서 멈춥니다 — 월드가 없으면 토픽 이름만" >&2
  echo "만들어 놓고 값은 하나도 못 받습니다." >&2
  echo "" >&2
  echo "무엇이 있었는지: \$LOG_FILE" >&2
  echo "오류만 모은 것: \$ERR_FILE" >&2
  exit 1
fi

echo "[2/2] Open-RMF"
ros2 launch "\$MAP_DIR/$mapName.launch.xml" headless:="\$RVIZ_HEADLESS"'''}
''';

/// 이 프로젝트로 띄운 것을 내리는 셸 스크립트.
String buildProjectStopScript({
  required String mapName,
  required String mapDirectory,
  List<RmfProjectRobot> robots = const [],
}) =>
    '''#!/usr/bin/env bash
# $mapName 프로젝트로 띄운 프로세스를 내린다.
# rmf_control_ui 가 맵 프로젝트에서 생성했다.
#
# 이 프로젝트의 launch 경로로 시작한 것만 고른다. 다른 맵으로 띄운 RMF 나
# 관계없는 Gazebo 는 건드리지 않는다.
set -euo pipefail

MAP_DIR="\${MAP_DIR:-$mapDirectory}"

# 이 프로젝트가 쓰는 로봇 네임스페이스. 인자에 맵 경로가 없는 노드는 이 이름으로
# 찾는다 — robot_state_publisher 같은 것은 URDF 만 들고 있어 경로가 없다.
ROBOT_NAMESPACES="${robots.where((robot) => robot.runsInGazebo).map((robot) => robot.gzName).join(' ')}"
APP_ROOT="\${ROBOSAPIENS_ROOT:-\$(cd "\$MAP_DIR/../.." && pwd)}"
RMF_WS="\${RMF_WS:-\$APP_ROOT/rmf_ws}"
LOCK_FILE="\$MAP_DIR/.$mapName.run.lock"

# INT → TERM → KILL 로 올려 가며 내린다.
#
# rclpy 노드는 TERM 을 받고도 종료 중에 스레드가 서로를 기다리며 굳는 일이
# 있다. 거기서 멈추면 노드가 살아남아 다음 실행에서 이름이 겹친다.
stop_pids() {
  local label="\$1"
  shift
  local pids=("\$@") remaining=() pid
  if ((\${#pids[@]} == 0)); then
    echo "\$label: 실행 중이 아님"
    return
  fi
  echo "\$label 중지: \${pids[*]}"
  local signal
  for signal in INT TERM KILL; do
    remaining=()
    for pid in "\${pids[@]}"; do
      # 좀비는 이미 끝난 것이다. 기다릴 것이 없다.
      if kill -0 "\$pid" 2>/dev/null &&
         [[ "\$(ps -o stat= -p "\$pid" 2>/dev/null)" != *Z* ]]; then
        remaining+=("\$pid")
      fi
    done
    if ((\${#remaining[@]} == 0)); then
      return
    fi
    [[ "\$signal" == "KILL" ]] &&
      echo "  \$label: 응답이 없어 강제 종료합니다 (\${remaining[*]})"
    kill "-\$signal" "\${remaining[@]}" 2>/dev/null || true
    sleep 3
  done
}

stop_matching() {
  local label="\$1" pattern="\$2"
  mapfile -t pids < <(pgrep -u "\$(id -u)" -f "\$pattern" 2>/dev/null || true)
  stop_pids "\$label" "\${pids[@]}"
}

# ros2 launch 가 죽으면 자식이 init 으로 재부모화된다. 그룹도 잃고
# `ros2 launch <경로>` 라는 이름도 잃어서, 이름이나 PGID 로는 잡히지 않는다.
# 이 맵 디렉터리를 인자로 물고 있으면 이 프로젝트가 띄운 것이다.
sweep_map_dir() {
  local label="\$1" pids=() pid args
  while read -r pid; do
    [[ -z "\$pid" || "\$pid" == "\$\$" || "\$pid" == "\$PPID" ]] && continue
    # pgrep 과 여기 사이에 끝난 프로세스가 있을 수 있다. 없으면 조용히 넘긴다.
    [[ -r "/proc/\$pid/cmdline" ]] || continue
    # 2>/dev/null 을 먼저 건다. 뒤에 걸면 입력 리다이렉트가 먼저 실패하면서
    # 셸이 그 오류를 그대로 찍는다 — pgrep 과 여기 사이에 끝난 프로세스가 있다.
    args="\$(tr '\\0' ' ' 2>/dev/null < "/proc/\$pid/cmdline" || true)"
    # 이 스크립트 자신과 이것을 부른 셸은 건드리지 않는다.
    [[ "\$args" == *"stop_$mapName.sh"* ]] && continue
    [[ "\$args" == *"\$MAP_DIR"* ]] || continue
    pids+=("\$pid")
  done < <(pgrep -u "\$(id -u)" -f "\$MAP_DIR" 2>/dev/null || true)
  if ((\${#pids[@]} == 0)); then
    echo "\$label: 남은 것 없음"
    return
  fi
  stop_pids "\$label" "\${pids[@]}"
}

stop_matching "Open-RMF ($mapName)" "ros2 launch \$MAP_DIR/$mapName.launch.xml"
stop_matching "Gazebo bringup ($mapName)" \\
  "ros2 launch \$MAP_DIR/${mapName}_bringup.launch.xml"
stop_matching "Gazebo 서버 ($mapName)" "gz sim.*\$MAP_DIR/$mapName.world"

# 실행 스크립트가 남긴 프로세스 그룹을 통째로 끊는다. 이름으로 못 찾은 자식이
# 있어도 여기서 정리된다.
PGID_FILE="\$MAP_DIR/.$mapName.pgid"
if [[ -f "\$PGID_FILE" ]]; then
  PGID="\$(cat "\$PGID_FILE")"
  if [[ "\$PGID" =~ ^[0-9]+\$ ]] && kill -0 -- "-\$PGID" 2>/dev/null; then
    echo "프로세스 그룹 \$PGID 중지"
    kill -INT -- "-\$PGID" 2>/dev/null || true
    sleep 3
    kill -TERM -- "-\$PGID" 2>/dev/null || true
  fi
  rm -f "\$PGID_FILE"
fi

# 마지막으로 재부모화되어 살아남은 것을 쓸어낸다. fleet_manager 처럼 launch 가
# 죽어도 혼자 도는 것들이 여기서 잡힌다.
sweep_map_dir "이 맵을 물고 남은 노드 ($mapName)"

# 네임스페이스로 한 번 더 쓸어낸다.
#
# robot_state_publisher 같은 노드는 인자에 맵 경로가 없다. 대신 ROS 가 넣어 준
# `__ns:=/<gz 이름>` 을 들고 있다. 이 프로젝트가 쓰는 이름은 우리가 정한
# 것이므로 다른 것과 겹치지 않는다.
sweep_namespaces() {
  local pids=() pid ns
  for ns in \$ROBOT_NAMESPACES; do
    while read -r pid; do
      [[ -z "\$pid" || "\$pid" == "\$\$" || "\$pid" == "\$PPID" ]] && continue
      pids+=("\$pid")
    done < <(pgrep -u "\$(id -u)" -f -- "__ns:=/\$ns\\b" 2>/dev/null || true)
  done
  if ((\${#pids[@]} == 0)); then
    echo "로봇 네임스페이스 ($mapName): 남은 것 없음"
    return
  fi
  stop_pids "로봇 네임스페이스 ($mapName)" "\${pids[@]}"
}

sweep_namespaces

# 마지막으로 RMF core 를 쓸어낸다.
#
# schedule node 나 supervisor 는 인자에 맵 경로도 로봇 네임스페이스도 없다.
# launch 가 죽고 PGID 파일도 없으면 어떤 방법으로도 못 찾는다. RMF core 는
# 한 번에 하나만 뜰 수 있으므로, 백엔드를 내리기로 한 이상 이것이 대상이다.
sweep_rmf_core() {
  mapfile -t pids < <(
    pgrep -u "\$(id -u)" -f "\$RMF_WS/install/rmf_" 2>/dev/null || true
  )
  if ((\${#pids[@]} == 0)); then
    echo "RMF core: 남은 것 없음"
    return
  fi
  stop_pids "RMF core" "\${pids[@]}"
}

sweep_rmf_core

# Gazebo 다리를 쓸어낸다.
#
# `parameter_bridge` 는 인자에 맵 경로가 있는 것도 있지만, `/clock` 하나만 잇는
# 것은 인자가 `/clock@rosgraph_msgs...` 뿐이라 위 그물에 하나도 안 걸린다.
# 부모마저 systemd 로 바뀌면 프로세스 그룹으로도 못 잡는다.
#
# 그러면 다음 실행에서 **/clock 을 두 곳이 낸다.** 두 시계가 번갈아 나오니
# 시각이 앞뒤로 튀고, tf2 가 `Detected jump back in time` 으로 버퍼를 통째로
# 비운다. AMCL 은 위치추정을 잃고 Nav2 는 명령을 멈춘다 — 로봇은 멀쩡한데
# 가만히 서 있고, 그 원인이 한 시간 전에 남은 프로세스라는 것은 어디에도
# 안 보인다. 실제로 그렇게 39번 튀었다.
sweep_bridges() {
  mapfile -t pids < <(
    pgrep -u "\$(id -u)" -f "ros_gz_bridge/parameter_bridge" 2>/dev/null || true
  )
  if ((\${#pids[@]} == 0)); then
    echo "Gazebo 다리: 남은 것 없음"
    return
  fi
  stop_pids "Gazebo 다리" "\${pids[@]}"
}

sweep_bridges

# 실행 셸의 FD 9는 모든 자식에게 상속된다. launch가 죽은 뒤 이름도 경로도 없는
# lifecycle_manager가 고아로 남아도 이 잠금 FD만큼은 그대로 들고 있다. 따라서
# 이름 검색이 모두 실패한 뒤 잠금 파일을 연 PID를 직접 찾아 마지막으로 끊는다.
sweep_lock_holders() {
  local pass fd target pid pids=()
  for pass in 1 2 3; do
    pids=()
    for fd in /proc/[0-9]*/fd/*; do
      target="\$(readlink "\$fd" 2>/dev/null || true)"
      [[ "\$target" == "\$LOCK_FILE" ]] || continue
      pid="\${fd#/proc/}"
      pid="\${pid%%/*}"
      [[ "\$pid" == "\$\$" || "\$pid" == "\$PPID" ]] && continue
      [[ " \${pids[*]} " == *" \$pid "* ]] || pids+=("\$pid")
    done
    ((\${#pids[@]} == 0)) && return
    stop_pids "실행 잠금 보유 프로세스 ($mapName, 확인 \$pass)" "\${pids[@]}"
  done
}

sweep_lock_holders

# 종료 성공은 이름 검색 결과가 아니라 새 실행이 잠금을 잡을 수 있는지로 판정한다.
# 좀비는 FD를 보유하지 않으므로 잠금 검사를 통과하며, 살아 있는 숨은 프로세스는
# 반드시 실패시킨다. 실패를 성공처럼 표시하지 않도록 0이 아닌 코드로 끝낸다.
if ! flock -n "\$LOCK_FILE" true; then
  echo "오류: $mapName 실행 잠금이 아직 사용 중입니다." >&2
  echo "확인: fuser -v \$LOCK_FILE" >&2
  exit 1
fi

remaining_zombies="\$(ps -u "\$(id -u)" -o pid=,ppid=,pgid=,stat=,args= |
  awk -v map="\$MAP_DIR" '\$4 ~ /^Z/ && index(\$0, map) {print}')"
if [[ -n "\$remaining_zombies" ]]; then
  echo "오류: $mapName 관련 좀비 프로세스가 남았습니다:" >&2
  echo "\$remaining_zombies" >&2
  exit 1
fi

echo "$mapName 프로젝트 프로세스를 정리했습니다."
''';

/// 로봇 한 대의 Nav2 를 띄우는 launch.
///
/// **네임스페이스 아래에서만 돈다.** 노드마다 이름을 걸지 않고 그룹에
/// `push-ros-namespace` 를 한 번 건다 — 두 번 걸면 `/pinky_01/pinky_01/amcl` 이
/// 되어 파라미터가 하나도 안 붙는다(`docs/MULTI_ROBOT_NAMESPACES.md` 함정 1).
///
/// `map_server` 는 여기 없다. 같은 건물이므로 **월드에 하나만** 띄운다.
String buildRobotNav2LaunchXml(RmfProjectRobot robot, String mapName) {
  // lifecycle_manager 가 이 차례로 켠다. costmap 을 쓰는 것보다 그것을 만드는
  // 쪽이 먼저 서야 한다.
  const managed = [
    'controller_server',
    'smoother_server',
    'planner_server',
    'behavior_server',
    'bt_navigator',
    'waypoint_follower',
    'velocity_smoother',
  ];
  final buffer = StringBuffer()
    ..writeln("<?xml version='1.0' ?>")
    ..writeln('<!--')
    ..writeln('  ${robot.robotId} · ${robot.displayName} 의 Nav2.')
    ..writeln('  rmf_control_ui 가 맵 프로젝트에서 생성했다.')
    ..writeln('')
    ..writeln('  이 로봇의 라이다로 제 위치를 잡고(AMCL) 길을 만들어 간다.')
    ..writeln('  파라미터는 같은 디렉터리의 nav2_params.yaml 이다 — 벤더의')
    ..writeln('  nav2_params.yaml 을 이 로봇 이름에 맞춰 다시 쓴 것이다.')
    ..writeln('')
    ..writeln('  map_server 는 여기 없다. 같은 건물이므로 월드에 하나만 띄운다.')
    ..writeln('  ${mapName}_nav2.launch.xml 이 그것을 맡는다.')
    ..writeln('')
    ..writeln('  혼자 시험하려면 map_server 를 먼저 띄우고 이것을 돌린다.')
    ..writeln('-->')
    ..writeln('<launch>')
    ..write(_robotDomainEnv(robot))
    ..writeln('  <arg name="use_sim_time" default="true"/>')
    ..writeln('  <group>')
    // 한 번만 건다. 아래 노드에는 네임스페이스를 따로 걸지 않는다.
    ..writeln('    <push-ros-namespace namespace="${robot.gzName}"/>')
    ..writeln('')
    ..writeln('    <!-- 라이다로 제 위치를 잡는다. map → ${robot.gzName}/odom -->')
    ..writeln('    <node pkg="nav2_amcl" exec="amcl" name="amcl"')
    ..writeln('          output="screen">')
    ..writeln('      <param from="\$(dirname)/nav2_params.yaml"/>')
    ..writeln('      <param name="use_sim_time" value="\$(var use_sim_time)"/>')
    // 지도는 로봇마다 가르지 않는다. `/map` 은 RMF 의 building_map_server 가
    // 이미 쓰고 있어서 한 토픽에 형식이 둘 올라간다.
    ..writeln('      <param name="map_topic" value="$nav2MapTopic"/>')
    ..writeln('    </node>');
  for (final node in managed) {
    final package = switch (node) {
      'controller_server' => 'nav2_controller',
      'smoother_server' => 'nav2_smoother',
      'planner_server' => 'nav2_planner',
      'behavior_server' => 'nav2_behaviors',
      'bt_navigator' => 'nav2_bt_navigator',
      'waypoint_follower' => 'nav2_waypoint_follower',
      _ => 'nav2_velocity_smoother',
    };
    buffer
      ..writeln('')
      ..writeln('    <node pkg="$package" exec="$node" name="$node"')
      ..writeln('          output="screen">')
      ..writeln('      <param from="\$(dirname)/nav2_params.yaml"/>')
      ..writeln(
        '      <param name="use_sim_time" value="\$(var use_sim_time)"/>',
      );
    if (node == 'behavior_server') {
      // behavior_server 는 제 이름으로 TF 를 본다. 파라미터로만 주면 늦게
      // 붙는 일이 있어 여기서도 못 박는다.
      buffer.writeln(
        '      <param name="robot_base_frame" '
        'value="${robot.gzName}/base_footprint"/>',
      );
    }
    buffer.writeln('    </node>');
  }
  buffer
    ..writeln('')
    ..writeln('    <!-- 위 노드들을 차례로 켜고 끈다. -->')
    ..writeln('    <node pkg="nav2_lifecycle_manager" exec="lifecycle_manager"')
    ..writeln('          name="lifecycle_manager_navigation" output="screen">')
    // 관리자는 sim 시간을 쓰지 않는다. 전이 응답을 기다리는 시간 제한이 sim
    // 시계에 걸리면 `Configuring` 에서 영영 멈춘다. 관리자가 하는 일은 순서대로
    // 켜고 끄는 것뿐이라 벽시계로 재는 것이 맞다.
    ..writeln('      <param name="use_sim_time" value="false"/>')
    ..writeln('      <param name="autostart" value="true"/>')
    ..writeln('      <param name="node_names"')
    ..writeln('             value="[amcl, ${managed.join(', ')}]"/>')
    ..writeln('    </node>')
    ..writeln('  </group>')
    ..writeln('</launch>');
  return buffer.toString();
}

/// 앱이 만든 작업을 RMF 에 넣어 주는 작은 다리.
///
/// RMF 는 `task_api_requests` 토픽 하나로 작업을 받는다. 그런데 `ros2 topic
/// pub` 으로는 이 일을 제대로 할 수 없다 — 요청과 응답을 `request_id` 로 맞춰야
/// 하고, QoS 가 transient_local 이라 한 번 실은 뒤 잠깐 살아 있어야 한다.
///
/// 그래서 짧은 스크립트를 하나 둔다. 앱이 JSON 파일 하나를 주면 실어 보내고,
/// RMF 의 답을 그대로 찍고 끝난다. 앱은 `ros2 topic echo` 를 띄우는 것과 같은
/// 방식으로 이것을 부른다.
///
/// **실물 로봇에서도 그대로 돈다.** 여기는 RMF 와만 이야기한다.
String buildTaskBridgeScript({
  required String mapName,
  required String fleetName,
}) =>
    '''#!/usr/bin/env python3
"""$mapName 프로젝트의 작업 다리 — 앱이 만든 작업을 RMF 에 넣는다.

rmf_control_ui 가 맵 프로젝트에서 생성했다. 손으로 고치면 다음 저장 때
덮어써진다.

  ${mapName}_task_bridge.py --submit 작업.json

작업.json 은 `robot_task_request` 나 `dispatch_task_request` 한 덩어리다.
성공하면 RMF 의 답을 그대로 찍고 0 으로 끝난다.
"""

import argparse
import json
import sys
import uuid

import rclpy
import rclpy.node
from rclpy.qos import QoSProfile, QoSDurabilityPolicy, QoSHistoryPolicy

from rmf_task_msgs.msg import ApiRequest, ApiResponse

FLEET_NAME = '$fleetName'

# RMF 의 task API 는 transient_local 이다. 늦게 붙는 쪽도 마지막 것을 받는다.
API_QOS = QoSProfile(
    history=QoSHistoryPolicy.KEEP_LAST,
    depth=10,
    durability=QoSDurabilityPolicy.TRANSIENT_LOCAL)


def main(argv=sys.argv):
    parser = argparse.ArgumentParser(prog='$mapName' + '_task_bridge')
    parser.add_argument('--submit', required=True,
                        help='보낼 작업 JSON 파일')
    parser.add_argument('--timeout', type=float, default=15.0,
                        help='답을 기다리는 초')
    args = parser.parse_args(argv[1:])

    with open(args.submit, encoding='utf-8') as handle:
        payload = json.load(handle)

    rclpy.init(args=None)
    node = rclpy.node.Node('$fleetName' + '_task_bridge')
    publisher = node.create_publisher(ApiRequest, 'task_api_requests', API_QOS)

    request = ApiRequest()
    request.request_id = 'rmf_control_ui-' + str(uuid.uuid4())[:8]
    request.json_msg = json.dumps(payload, ensure_ascii=False)

    answer = {}

    def on_response(message):
        # 남의 요청에 대한 답도 같은 토픽으로 온다.
        if message.request_id != request.request_id:
            return
        answer['body'] = json.loads(message.json_msg)

    node.create_subscription(ApiResponse, 'task_api_responses',
                             on_response, API_QOS)

    # 구독이 붙기 전에 실으면 답을 놓친다. 한 바퀴 돌려 놓고 보낸다.
    rclpy.spin_once(node, timeout_sec=0.5)
    publisher.publish(request)

    deadline = node.get_clock().now().nanoseconds + int(args.timeout * 1e9)
    while 'body' not in answer:
        if node.get_clock().now().nanoseconds > deadline:
            print(json.dumps({
                'success': False,
                'errors': [{'code': 0, 'category': 'timeout', 'detail':
                            'RMF 가 답하지 않았습니다. fleet adapter 가 떠 '
                            '있는지 확인하세요.'}],
            }, ensure_ascii=False))
            node.destroy_node()
            if rclpy.ok():
                rclpy.shutdown()
            return 1
        rclpy.spin_once(node, timeout_sec=0.2)

    print(json.dumps(answer['body'], ensure_ascii=False))
    node.destroy_node()
    if rclpy.ok():
        rclpy.shutdown()
    return 0 if answer['body'].get('success') else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
''';

/// 로봇의 센서를 앱이 볼 수 있게 파일로 내려 준다.
///
/// 앱에는 rclpy 바인딩이 없다. 지금까지는 `ros2 topic echo` 를 자식 프로세스로
/// 띄워 읽었는데, **카메라 영상에는 그 방법을 쓸 수 없다** — 1280×720 한 장이
/// YAML 로 2.7MB 다. 초당 서른 장이면 읽기 전에 앱이 멈춘다.
///
/// 그래서 작은 relay 노드를 하나 둔다. 구독해서 줄여 파일로 쓰고, 앱은 그 파일만
/// 읽는다. 로봇마다 프로세스를 띄우지 않으므로 대수가 늘어도 가볍다.
///
/// **실물 로봇에서도 그대로 돈다.** 토픽 이름만 같으면 되고, Gazebo 인지 진짜
/// 카메라인지는 이 노드가 알 필요가 없다.
String buildSensorRelayScript({
  required String mapName,
  required List<RmfProjectRobot> robots,
}) {
  final nodeName = _rosNodeName('${mapName}_sensor_relay');
  final watched = robots
      .where((robot) => robot.isMobile && robot.dataSource.usesTopics)
      .toList();
  final mapping = watched
      .map((robot) => "    ('${robot.robotId}', '${robot.gzName}'),")
      .join('\n');
  return '''#!/usr/bin/env python3
"""$mapName 프로젝트의 센서 relay.

rmf_control_ui 가 맵 프로젝트에서 생성했다. 손으로 고치면 다음 저장 때
덮어써진다.

로봇의 라이다와 카메라를 구독해서 앱이 읽을 수 있는 파일로 내려 준다. 앱에는
rclpy 가 없고, 카메라 영상은 `ros2 topic echo` 로 읽기에 너무 크다.

파일은 --out 디렉터리에 로봇 ID 로 쌓인다.

    <ID>.scan   라이다 한 줄 (텍스트)
    <ID>.frame  카메라 한 장 (RGBA 날바이트, 앞에 작은 머리글)

둘 다 임시 파일에 쓰고 rename 한다. 앱이 반쯤 쓰인 파일을 읽는 일이 없다.
"""

import argparse
import os
import struct
import sys

import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data

from sensor_msgs.msg import Image, LaserScan

# (RMF 가 아는 이름, ROS 네임스페이스)
ROBOTS = [
$mapping
]

# 카메라를 줄여서 보낼 크기. 원본 그대로 두면 한 장에 2.7MB 라 디스크만 먹는다.
# 로봇 상세에서 보기에는 이 정도면 넉넉하다.
FRAME_WIDTH = 320
FRAME_HEIGHT = 180

# 라이다는 이만큼으로 솎는다. 640개를 다 그려도 눈에 보이는 차이가 없다.
SCAN_POINTS = 180

# 카메라를 초당 몇 장까지 내릴까. 앱은 0.2초마다 읽으므로 이보다 많이 내려도
# 보이지 않고 디스크만 먹는다.
FRAME_INTERVAL = 1.0 / 6

# 카메라 파일 머리글. 앱이 이 네 글자로 파일이 맞는지 본다.
FRAME_MAGIC = b'RSIM'


def write_atomic(path, data, binary=True):
    """반쯤 쓰인 파일을 앱이 읽지 않도록 임시 파일에 쓰고 옮긴다."""
    tmp = path + '.tmp'
    with open(tmp, 'wb' if binary else 'w') as handle:
        handle.write(data)
    os.replace(tmp, path)


class SensorRelay(Node):

    def __init__(self, out_dir):
        super().__init__('${nodeName}')
        self.out_dir = out_dir
        self.last_frame = {}
        os.makedirs(out_dir, exist_ok=True)
        for robot_id, namespace in ROBOTS:
            self.create_subscription(
                LaserScan, f'/{namespace}/scan',
                lambda msg, rid=robot_id: self.on_scan(rid, msg),
                qos_profile_sensor_data)
            self.get_logger().info(f'[{robot_id}] /{namespace} 를 봅니다.')

    def on_scan(self, robot_id, msg):
        ranges = list(msg.ranges)
        if not ranges:
            return
        # 고르게 솎는다. 앞쪽만 잘라내면 뒤가 안 보인다.
        step = max(1, len(ranges) // SCAN_POINTS)
        thinned = ranges[::step]
        # 무한대와 NaN 은 텍스트로 옮기면 파서가 걸린다. 잴 수 없었다는 뜻이므로
        # 최대 거리로 적는다.
        cleaned = []
        for value in thinned:
            if value != value or value == float('inf') or value > msg.range_max:
                cleaned.append(msg.range_max)
            else:
                cleaned.append(value)
        head = '{:.6f},{:.6f},{:.3f},{:.3f}'.format(
            msg.angle_min, msg.angle_max, msg.range_min, msg.range_max)
        body = ','.join('{:.3f}'.format(value) for value in cleaned)
        write_atomic(
            os.path.join(self.out_dir, robot_id + '.scan'),
            head + '\\n' + body + '\\n', binary=False)

    def on_image(self, robot_id, msg):
        # 속도를 제한한다. 앱은 0.2초마다 읽으므로 더 자주 내려도 보이지 않는다.
        now = self.get_clock().now().nanoseconds / 1e9
        if now - self.last_frame.get(robot_id, 0.0) < FRAME_INTERVAL:
            return
        self.last_frame[robot_id] = now

        pixels = self.to_rgba(msg)
        if pixels is None:
            return
        header = FRAME_MAGIC + struct.pack('<II', FRAME_WIDTH, FRAME_HEIGHT)
        write_atomic(
            os.path.join(self.out_dir, robot_id + '.frame'), header + pixels)

    def to_rgba(self, msg):
        """영상을 줄여서 RGBA 로 만든다.

        화소를 파이썬 반복문으로 옮기면 안 된다. 320x180 한 장에 5만 7천 번이고,
        두 대가 초당 열두 장이면 코어 하나를 통째로 먹는다 — 실제로 101% 를
        썼다. numpy 는 rclpy 가 이미 쓰고 있으므로 새로 받을 것이 없다.
        """
        if msg.encoding not in ('rgb8', 'bgr8'):
            self.get_logger().warn(
                f'모르는 영상 형식 [{msg.encoding}] 입니다.', once=True)
            return None

        frame = np.frombuffer(msg.data, dtype=np.uint8)
        # step 은 한 줄의 바이트 수다. 폭보다 클 수 있어서 잘라 낸다.
        frame = frame.reshape(msg.height, msg.step)[:, :msg.width * 3]
        frame = frame.reshape(msg.height, msg.width, 3)

        # 가장 가까운 화소를 집는다. 보간은 필요 없다 — 보여 주기용이다.
        rows = (np.arange(FRAME_HEIGHT) * msg.height) // FRAME_HEIGHT
        columns = (np.arange(FRAME_WIDTH) * msg.width) // FRAME_WIDTH
        small = frame[rows][:, columns]
        if msg.encoding == 'bgr8':
            small = small[:, :, ::-1]

        alpha = np.full((FRAME_HEIGHT, FRAME_WIDTH, 1), 255, dtype=np.uint8)
        return np.concatenate([small, alpha], axis=2).tobytes()


def main(argv=sys.argv):
    parser = argparse.ArgumentParser(prog='${mapName}_sensor_relay')
    parser.add_argument('-o', '--out', required=True)
    args = parser.parse_args(rclpy.utilities.remove_ros_args(argv)[1:])

    rclpy.init(args=argv)
    node = SensorRelay(args.out)
    if not ROBOTS:
        node.get_logger().warn('볼 로봇이 없습니다.')
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    node.destroy_node()
    # rclpy 의 신호 처리기가 먼저 context 를 닫아 놓는 일이 있다. 그때 또
    # 부르면 예외가 올라와, 멀쩡히 끝난 것이 죽은 것처럼 보인다.
    if rclpy.ok():
        rclpy.shutdown()


if __name__ == '__main__':
    main(sys.argv)
''';
}

/// RMF 와 Nav2 를 잇는 어댑터.
///
/// 지금까지 이 고리가 끊겨 있었다.
///
/// ```
/// /robot_state          발행자 0 · 구독자 1   ← RMF 가 듣는데 아무도 말 안 함
/// /robot_path_requests  발행자 1 · 구독자 0   ← RMF 가 말하는데 아무도 안 들음
/// ```
///
/// 저 두 토픽은 RMF 시범 로봇(slotcar)의 것이다. 핑키는 slotcar 가 아니라
/// `/cmd_vel` · `/odom` 만 아는 diff drive 라서 상대가 없었다.
///
/// `EasyFullControl` 이 그 사이를 잇는다. RMF 가 주는 목적지를 Nav2 의
/// `NavigateToPose` 로 바꾸고, TF 에서 읽은 위치를 RMF 에 되돌린다.
///
/// **이 노드가 실물에서도 그대로 돈다.** Nav2 가 아래에서 Gazebo 를 몰든 진짜
/// 모터를 몰든 위쪽은 같기 때문이다.
String buildNav2FleetAdapterScript({
  required String mapName,
  required String fleetName,
  required List<RmfProjectRobot> robots,
}) {
  final navigating = robots
      .where((robot) => robot.isMobile && robot.runsInGazebo)
      .toList();
  // RMF 가 아는 이름(로봇 ID)과 ROS 네임스페이스(Gazebo 이름)는 다르다.
  final mapping = navigating
      .map((robot) => "    '${robot.robotId}': '${robot.gzName}',")
      .join('\n');
  return '''#!/usr/bin/env python3
"""$mapName 프로젝트의 RMF ↔ Nav2 어댑터.

rmf_control_ui 가 맵 프로젝트에서 생성했다. 손으로 고치면 다음 저장 때
덮어써진다.

RMF 가 주는 목적지를 Nav2 의 NavigateToPose 로 바꾸고, TF 에서 읽은 위치를 RMF 에
되돌린다. rmf_demos_fleet_adapter 는 slotcar 전용이라 우리 핑키에게는 상대가 없다.

이 노드는 실물에서도 그대로 돈다. Nav2 가 아래에서 Gazebo 를 몰든 진짜 모터를
몰든 위쪽은 같기 때문이다.
"""

import argparse
import json
import math
import sys
import threading
import math
import time
import uuid

import rclpy
import rclpy.node
from rclpy.action import ActionClient
from rclpy.duration import Duration
from rclpy.parameter import Parameter

import rmf_adapter
from rmf_adapter import Adapter
import rmf_adapter.easy_full_control as rmf_easy

from action_msgs.msg import GoalStatus
from nav2_msgs.action import NavigateToPose
from geometry_msgs.msg import PoseStamped
from rmf_dispenser_msgs.msg import DispenserRequest, DispenserRequestItem, DispenserResult
from rclpy.qos import QoSProfile, QoSDurabilityPolicy, QoSReliabilityPolicy
from std_msgs.msg import String as StringMsg
import tf2_ros

# 진행 상황을 내보내는 자리. 앱이 이것을 읽어 단계를 넘긴다.
#
# RMF 의 작업 상태는 rmf-web 의 웹소켓으로만 나간다. 웹서버를 띄우지 않으면
# 어디에서도 볼 수 없다. 그런데 목적지를 하나씩 받는 것은 이 어댑터이므로,
# 여기가 진행을 아는 가장 이른 자리다.
PROGRESS_TOPIC = '$fleetName/task_progress'
_progress = None


def report(**fields):
    """앱에게 지금 무엇을 하는지 알린다. 없으면 조용히 넘어간다."""
    if _progress is None:
        return
    message = StringMsg()
    message.data = json.dumps(fields, ensure_ascii=False)
    _progress.publish(message)

# RMF 가 아는 이름 -> ROS 네임스페이스.
ROBOT_NAMESPACES = {
$mapping
}

# 건물 층 이름. nav graph 의 level 과 같아야 한다.
MAP_NAME = 'L1'


def yaw_of(rotation):
    """사원수에서 yaw 를 푼다. 평면을 도는 로봇이라 이것 하나면 된다."""
    x, y, z, w = rotation.x, rotation.y, rotation.z, rotation.w
    return math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))


class RobotAdapter:
    """로봇 한 대. RMF 쪽과 Nav2 쪽을 양쪽으로 붙인다."""

    next_registration_at = 0.0

    def __init__(self, name, namespace, node, tf_buffer, fleet_handle,
                 fleet_config, registration_delay):
        self.name = name
        self.namespace = namespace
        self.node = node
        self.tf_buffer = tf_buffer
        self.fleet_handle = fleet_handle
        self.fleet_config = fleet_config
        self.update_handle = None
        self.update_ready_at = None
        self.execution = None
        self.goal_handle = None
        # Nav2 액션 결과는 비동기로 늦게 돌아온다. 새 목적지가 옛 목적지를
        # 선점한 뒤 옛 취소 결과가 도착해도 현재 RMF 실행을 끝내면 안 된다.
        self.goal_generation = 0
        self.warned = False
        self.lock = threading.Lock()
        self.nav = ActionClient(
            node, NavigateToPose, f'/{namespace}/navigate_to_pose')
        request_qos = QoSProfile(
            depth=10,
            reliability=QoSReliabilityPolicy.RELIABLE,
            durability=QoSDurabilityPolicy.TRANSIENT_LOCAL,
        )
        self.dispenser_requests = node.create_publisher(
            DispenserRequest, '/dispenser_requests', request_qos)
        self.dispenser_result_subscription = node.create_subscription(
            DispenserResult, '/dispenser_results',
            self.on_dispenser_result, 10)
        self.dispenser_execution = None
        self.dispenser_request_guid = None
        self.dispenser_target_guid = None
        # pybind C++가 콜백을 사용하는 동안 Python 객체가 회수되지 않게 한다.
        self.callbacks = self.make_callbacks()

    # ── RMF 가 부르는 쪽 ────────────────────────────────────────────────

    def make_callbacks(self):
        return rmf_easy.RobotCallbacks(
            lambda destination, execution: self.navigate(destination, execution),
            lambda activity: self.stop(activity),
            lambda category, description, execution: self.execute_action(
                category, description, execution),
        )

    def navigate(self, destination, execution):
        """RMF 가 준 목적지로 Nav2 를 보낸다."""
        with self.lock:
            self.goal_generation += 1
            generation = self.goal_generation
            self.execution = execution
        x, y, yaw = destination.position
        self.node.get_logger().info(
            f'[{self.name}] -> ({x:.3f}, {y:.3f}, {math.degrees(yaw):.0f}도)'
            f' 지도 [{destination.map}]')
        report(robot=self.name, event='navigate_start',
               x=float(x), y=float(y), yaw=float(yaw))

        if not self.nav.wait_for_server(timeout_sec=5.0):
            self.node.get_logger().error(
                f'[{self.name}] Nav2 가 없습니다. '
                f'/{self.namespace}/navigate_to_pose 를 확인하세요.')
            self.finish(generation, execution)
            return

        goal = NavigateToPose.Goal()
        goal.pose = PoseStamped()
        goal.pose.header.frame_id = 'map'
        goal.pose.header.stamp = self.node.get_clock().now().to_msg()
        goal.pose.pose.position.x = float(x)
        goal.pose.pose.position.y = float(y)
        goal.pose.pose.orientation.z = math.sin(yaw / 2)
        goal.pose.pose.orientation.w = math.cos(yaw / 2)

        future = self.nav.send_goal_async(goal)
        future.add_done_callback(
            lambda done: self.on_goal_response(done, generation, execution))

    def on_goal_response(self, future, generation, execution):
        handle = future.result()
        if handle is None or not handle.accepted:
            with self.lock:
                current = generation == self.goal_generation
            if not current:
                return
            self.node.get_logger().error(f'[{self.name}] Nav2 가 거절했습니다.')
            self.finish(generation, execution)
            return
        with self.lock:
            if generation != self.goal_generation:
                handle.cancel_goal_async()
                return
            self.goal_handle = handle
        handle.get_result_async().add_done_callback(
            lambda done: self.on_goal_result(done, generation, execution))

    def on_goal_result(self, future, generation, execution):
        # 결과를 봐야 한다. 안 보고 끝났다고 알리면 RMF 는 그 자리에 닿은 줄
        # 알고 다음 단계로 넘어간다 — 픽업에 가지도 않았는데 드랍오프로 가는
        # 것이 이것 때문이었다.
        status = getattr(future.result(), 'status', None)
        ok = status == GoalStatus.STATUS_SUCCEEDED
        with self.lock:
            # 새 목표가 이 목표를 선점했다. Nav2의 CANCELED/ABORTED는 옛 목표의
            # 결과이지 현재 RMF 실행의 실패가 아니다.
            if generation != self.goal_generation:
                return
            self.goal_handle = None
        if ok:
            self.node.get_logger().info(f'[{self.name}] 도착했습니다.')
            report(robot=self.name, event='navigate_done')
        else:
            self.node.get_logger().error(
                f'[{self.name}] 목적지에 닿지 못했습니다 (Nav2 status '
                f'{status}). 도착 반경이 코스트맵 한 칸보다 촘촘하면 영영 '
                f'못 맞춥니다.')
            report(robot=self.name, event='navigate_failed', status=status)
        self.finish(generation, execution)

    def finish(self, generation, execution):
        """RMF 에 이 명령이 끝났다고 알린다."""
        with self.lock:
            if (generation != self.goal_generation or
                    self.execution is not execution):
                return
            self.execution = None
        execution.finished()

    def stop(self, activity):
        """RMF 가 멈추라고 한다. 지금 가고 있는 것만 멈춘다."""
        with self.lock:
            execution = self.execution
            handle = self.goal_handle
        if execution is None or not execution.identifier.is_same(activity):
            return
        self.node.get_logger().info(f'[{self.name}] 멈춥니다.')
        if handle is not None:
            handle.cancel_goal_async()
        with self.lock:
            self.goal_generation += 1
            self.execution = None
            self.goal_handle = None
            if self.dispenser_execution is execution:
                self.dispenser_execution = None
                self.dispenser_request_guid = None
                self.dispenser_target_guid = None

    def execute_action(self, category, description, execution):
        """armLoad 를 해당 픽업 자리의 RMF 워크셀 요청으로 바꾼다."""
        seconds = 1.0
        target_guid = None
        item_type = 'policy_1'
        quantity = 1
        if isinstance(description, dict):
            target_guid = description.get('target_guid')
            item_type = str(description.get('item_type') or 'policy_1')
            quantity = max(1, int(description.get('quantity') or 1))
            for key, scale in (('seconds', 1.0),
                               ('unix_millis_action_duration_estimate',
                                0.001)):
                value = description.get(key)
                if isinstance(value, (int, float)) and value > 0:
                    seconds = float(value) * scale
                    break
        if category != 'armLoad' or not target_guid:
            self.node.get_logger().error(
                f'[{self.name}] 동작 [{category}]에 워크셀 위치가 없습니다.')
            report(robot=self.name, event='action_failed', category=category)
            execution.finished()
            return

        request_guid = f'{self.name}-{uuid.uuid4()}'
        with self.lock:
            self.execution = execution
            self.dispenser_execution = execution
            self.dispenser_request_guid = request_guid
            self.dispenser_target_guid = str(target_guid)
        self.node.get_logger().info(
            f'[{self.name}] 동작 [{category}] → 워크셀 [{target_guid}] 요청 '
            f'({request_guid})')
        report(robot=self.name, event='action_start',
               category=category, seconds=seconds)
        request = DispenserRequest()
        request.time = self.node.get_clock().now().to_msg()
        request.request_guid = request_guid
        request.target_guid = str(target_guid)
        request.transporter_type = self.name
        item = DispenserRequestItem()
        item.type_guid = item_type
        item.quantity = quantity
        item.compartment_name = 'pinky_tray'
        request.items = [item]
        self.dispenser_requests.publish(request)

    def on_dispenser_result(self, result):
        with self.lock:
            if (result.request_guid != self.dispenser_request_guid or
                    self.dispenser_execution is None):
                return
            if result.status == DispenserResult.ACKNOWLEDGED:
                self.node.get_logger().info(
                    f'[{self.name}] 워크셀 [{self.dispenser_target_guid}]이 '
                    '요청을 받았습니다.')
                return
            if result.status != DispenserResult.SUCCESS:
                self.node.get_logger().error(
                    f'[{self.name}] 워크셀 요청 실패 (status={result.status})')
                return
            execution = self.dispenser_execution
            target = self.dispenser_target_guid
            self.dispenser_execution = None
            self.dispenser_request_guid = None
            self.dispenser_target_guid = None
            if self.execution is execution:
                self.execution = None
        self.node.get_logger().info(
            f'[{self.name}] 워크셀 [{target}] 동작 완료.')
        report(robot=self.name, event='action_done', category='armLoad')
        execution.finished()

    # ── RMF 에 알리는 쪽 ────────────────────────────────────────────────

    def read_state(self):
        """TF 에서 지금 자리를 읽는다. AMCL 이 map -> odom 을 낸다."""
        try:
            tf = self.tf_buffer.lookup_transform(
                'map', f'{self.namespace}/base_footprint',
                rclpy.time.Time(), timeout=Duration(seconds=0.2))
        except Exception:
            return None
        t = tf.transform.translation
        return rmf_easy.RobotState(
            MAP_NAME,
            [t.x, t.y, yaw_of(tf.transform.rotation)],
            # 시뮬레이터에는 배터리가 없다. 실물로 가면 여기에 진짜 값을 넣는다.
            1.0,
        )

    def update(self):
        state = self.read_state()
        if state is None:
            return
        if self.update_handle is None:
            if time.monotonic() < RobotAdapter.next_registration_at:
                return
            # 처음 자리를 알게 된 순간에 RMF 에 등록한다. 자리를 모르는 채로
            # 넣으면 RMF 가 그 로봇을 어디에 둘지 모른다.
            handle = self.fleet_handle.add_robot(
                self.name, state,
                self.fleet_config.get_known_robot_configuration(self.name),
                self.callbacks)
            if handle is None:
                # 자리가 nav graph 에서 너무 멀면 RMF 가 받지 않는다. 다음에 다시
                # 해 본다 — AMCL 이 아직 안 잡혔을 수 있다. 같은 말을 0.1초마다
                # 되풀이하면 로그를 못 읽으므로 한 번만 적는다.
                if not self.warned:
                    self.warned = True
                    x, y, _ = state.position
                    self.node.get_logger().warn(
                        f'[{self.name}] 자리 ({x:.2f}, {y:.2f}) 가 nav graph 에서'
                        f' 멀어 RMF 가 받지 않습니다. AMCL 이 잡히면 다시 붙습니다.')
                return
            self.update_handle = handle
            RobotAdapter.next_registration_at = time.monotonic() + 3.0
            # add_robot의 C++ 측 등록 완료 콜백이 끝나기 전에 update()를 호출하면
            # Jazzy rmf_adapter가 SIGSEGV를 낸다. wall clock으로 여유를 둔다.
            self.update_ready_at = time.monotonic() + 2.0
            self.warned = False
            self.node.get_logger().info(f'[{self.name}] RMF 에 붙었습니다.')
            return
        if (self.update_ready_at is not None and
                time.monotonic() < self.update_ready_at):
            return
        with self.lock:
            activity = (
                self.execution.identifier if self.execution is not None else None)
        self.update_handle.update(state, activity)


def main(argv=sys.argv):
    rclpy.init(args=argv)
    rmf_adapter.init_rclcpp()
    parser = argparse.ArgumentParser(prog='$fleetName' + '_nav2_adapter')
    parser.add_argument('-c', '--config_file', required=True)
    parser.add_argument('-n', '--nav_graph', required=True)
    parser.add_argument('-s', '--use_sim_time', action='store_true')
    args = parser.parse_args(rclpy.utilities.remove_ros_args(argv)[1:])

    fleet_config = rmf_easy.FleetConfiguration.from_config_files(
        args.config_file, args.nav_graph)
    assert fleet_config, f'설정을 읽지 못했습니다: {args.config_file}'

    node = rclpy.node.Node(fleet_config.fleet_name + '_nav2_adapter')
    global _progress
    # 앱이 늦게 붙어도 마지막 소식은 받도록 남겨 둔다.
    _progress = node.create_publisher(StringMsg, PROGRESS_TOPIC, 10)
    adapter = Adapter.make(fleet_config.fleet_name + '_fleet_adapter')
    assert adapter, (
        'fleet adapter 를 만들지 못했습니다. '
        'rmf_traffic_schedule_primary 가 떠 있는지 확인하세요.')

    if args.use_sim_time:
        node.set_parameters(
            [Parameter('use_sim_time', Parameter.Type.BOOL, True)])
        adapter.node.use_sim_time()

    adapter.start()
    time.sleep(1.0)

    tf_buffer = tf2_ros.Buffer()
    tf2_ros.TransformListener(tf_buffer, node)

    fleet_handle = adapter.add_easy_fleet(fleet_config)

    robots = []
    for index, name in enumerate(fleet_config.known_robots):
        namespace = ROBOT_NAMESPACES.get(name)
        if namespace is None:
            node.get_logger().warn(
                f'[{name}] 의 ROS 네임스페이스를 모릅니다. 건너뜁니다.')
            continue
        robots.append(
            RobotAdapter(
                name, namespace, node, tf_buffer, fleet_handle, fleet_config,
                index * 3.0))

    if not robots:
        node.get_logger().error('이을 로봇이 없습니다.')

    period = fleet_config.update_interval.total_seconds()
    node.create_timer(period, lambda: [robot.update() for robot in robots])

    node.get_logger().info(
        f'{fleet_config.fleet_name} 를 Nav2 에 이었습니다. '
        f'로봇 {len(robots)}대, {period:.2f}초마다 알립니다.')

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    node.destroy_node()
    adapter.stop()
    # 신호로 끊길 때 rclpy 가 먼저 context 를 닫아 놓는다. 그때 또 부르면
    # 예외가 올라와, 멀쩡히 끝난 것이 죽은 것처럼 보인다.
    if rclpy.ok():
        rclpy.shutdown()


if __name__ == '__main__':
    main(sys.argv)
''';
}

/// 프로젝트의 Nav2 를 한꺼번에 띄우는 launch.
///
/// 건물 지도(`map_server`)는 **하나만** 띄우고, 이동 로봇마다 제 Nav2 를
/// 붙인다. 로봇들은 `map` 프레임을 함께 쓰고 `<로봇>/odom` 만 서로 다르다.
/// [warnings] 는 파라미터를 다시 쓰면서 손대지 못한 것이다. 여기 주석으로
/// 적어 둔다 — 이 launch 가 안 뜰 때 사람이 제일 먼저 여는 파일이다.
/// [mapYamlName] 은 `nav2_map/` 안에서 `map_server` 가 띄울 파일 이름이다.
///
/// 기본은 도면에서 만든 `<맵>.yaml` 이다. 실물 건물에서 SLAM 으로 뜬 지도를
/// 올려 그것을 쓰기로 골랐으면 `<맵>_slam.yaml` 이 들어온다. 이 값을 못박아
/// 두었더니 SLAM 지도를 올려도 `map_server` 는 계속 도면 지도를 띄웠다.
String buildProjectNav2LaunchXml({
  required String mapName,
  required List<RmfProjectRobot> robots,
  String? fleetName,
  String? mapYamlName,
  List<String> warnings = const [],
}) {
  final mapYaml = (mapYamlName == null || mapYamlName.trim().isEmpty)
      ? '$mapName.yaml'
      : mapYamlName.trim();
  final usingSlam = mapYaml != '$mapName.yaml';
  final navigating = robots
      .where((robot) => robot.isMobile && robot.runsInGazebo)
      .toList();
  final buffer = StringBuffer()
    ..writeln("<?xml version='1.0' ?>")
    ..writeln('<!--')
    ..writeln('  $mapName 프로젝트의 Nav2.')
    ..writeln('  rmf_control_ui 가 맵 프로젝트에서 생성했다.')
    ..writeln('')
    ..writeln('  건물 지도는 하나만 띄우고 이동 로봇마다 제 Nav2 를 붙인다.')
    ..writeln('  로봇들은 map 프레임을 함께 쓰고 <로봇>/odom 만 서로 다르다.')
    ..writeln('  그래서 한 TF 트리에 map → pinky_01/odom, map → pinky_02/odom')
    ..writeln('  이 나란히 선다.')
    ..writeln('')
    ..writeln('  지도는 nav2_map/$mapYaml 이다.');
  if (usingSlam) {
    buffer
      ..writeln('  로봇이 SLAM 으로 뜬 지도다. 원점을 사람이 RMF 월드에 맞춰')
      ..writeln('  두었다 — 그 값이 틀리면 로봇이 엉뚱한 데로 간다.');
  } else {
    buffer.writeln('  도면에서 만든 것이라 원점이 RMF 월드에 정확히 맞는다.');
  }
  buffer
    ..writeln('')
    ..writeln('  아직 RMF 와 이어지지 않았다. 지금은 Nav2 만 따로 돈다.');
  if (warnings.isNotEmpty) {
    buffer
      ..writeln('')
      ..writeln('  ── 확인이 필요한 것 ──────────────────────────────');
    for (final warning in warnings) {
      buffer.writeln('  · $warning');
    }
  }
  buffer
    ..writeln('-->')
    ..writeln('<launch>')
    ..writeln('  <arg name="map_dir" default="\$(dirname)"/>')
    ..writeln('  <arg name="use_sim_time" default="true"/>')
    // relay 와 앱이 만나는 곳. 앱은 ROBOSAPIENS_SENSOR_DIR 환경 변수를 보고
    // 같은 자리를 읽는다.
    ..writeln(
      '  <arg name="sensor_dir"'
      ' default="\$(env ROBOSAPIENS_SENSOR_DIR /tmp/robosapiens_sensors)"/>',
    )
    ..writeln('')
    ..writeln('  <!-- 건물 지도. 로봇들이 함께 본다. -->')
    ..writeln('  <node pkg="nav2_map_server" exec="map_server"')
    ..writeln('        name="map_server" output="screen">')
    ..writeln(
      '    <param name="yaml_filename" '
      'value="\$(var map_dir)/nav2_map/$mapYaml"/>',
    )
    ..writeln('    <param name="use_sim_time" value="\$(var use_sim_time)"/>')
    // `/map` 은 RMF 의 building_map_server 가 이미 쓴다. 같이 쓰면 한 토픽에
    // OccupancyGrid 와 BuildingMap 이 함께 올라가 아무도 제대로 못 읽는다.
    ..writeln('    <param name="topic_name" value="$nav2MapTopicName"/>')
    ..writeln('  </node>')
    ..writeln('  <node pkg="nav2_lifecycle_manager" exec="lifecycle_manager"')
    ..writeln('        name="lifecycle_manager_map" output="screen">')
    // 관리자는 sim 시간을 쓰지 않는다. 위와 같은 이유다.
    ..writeln('    <param name="use_sim_time" value="false"/>')
    ..writeln('    <param name="autostart" value="true"/>')
    ..writeln('    <param name="node_names" value="[map_server]"/>')
    ..writeln('  </node>');
  if (navigating.isEmpty) {
    buffer
      ..writeln('')
      ..writeln('  <!-- Gazebo 로 돌리는 이동 로봇이 없다. 지도만 띄운다. -->');
  }
  for (final robot in navigating) {
    buffer
      ..writeln('')
      ..writeln('  <!-- ${robot.robotId} · ${robot.displayName} -->')
      // include 의 <arg> 는 <group> 으로 감싸지 않으면 바깥으로 샌다.
      ..writeln('  <group>')
      ..writeln(
        '    <include file="\$(var map_dir)/'
        '${robotDirectoryName(robot)}/nav2.launch.xml">',
      )
      ..writeln('      <arg name="use_sim_time" value="\$(var use_sim_time)"/>')
      ..writeln('    </include>')
      ..writeln('  </group>');
  }
  if (navigating.isNotEmpty && fleetName != null) {
    buffer
      ..writeln('')
      ..writeln('  <!-- RMF 와 Nav2 를 잇는다. 이것이 없으면 RMF 가 배차해도')
      ..writeln('       로봇이 안 움직인다.')
      ..writeln('')
      ..writeln('       RViz 도 이것에 매달려 있다. 경로(Lane·Waypoint)를 그리는')
      ..writeln('       /nav_graphs 와 로봇을 그리는 /fleet_states 를 내는 것이')
      ..writeln('       RMF 안에서 이 어댑터(FleetUpdateHandle) 하나뿐이다.')
      ..writeln('       이것이 죽으면 RViz 는 도면만 남고 텅 빈다.')
      ..writeln('')
      ..writeln('       네이티브 RMF 라이브러리 오류나 시작 순서 문제로 종료되더라도')
      ..writeln('       계속 다시 띄운다. 실행 스크립트는 프로세스뿐 아니라')
      ..writeln('       /fleet_states 의 실제 로봇 등록 상태도 별도로 감시한다. -->')
      // ROS 패키지에 든 노드가 아니라 이 프로젝트가 만든 스크립트라 <node> 로는
      // 못 돌린다. <executable> 은 아무 명령이나 그대로 띄운다.
      //
      ..writeln('  <executable output="screen"')
      ..writeln('              respawn="true" respawn_delay="5.0"')
      ..writeln(
        '              cmd="python3 \$(var map_dir)/${mapName}_nav2_adapter.py'
        ' -c \$(var map_dir)/${fleetName}_config.yaml'
        ' -n \$(var map_dir)/nav_graphs/0.yaml'
        ' -s"/>',
      )
      ..writeln('')
      ..writeln('  <!-- 설비 로봇을 RMF 워크셀로 잇는다. 이것이 없으면 로봇이')
      ..writeln('       픽업 자리에 닿아도 RMF 가 답을 못 받아 영원히')
      ..writeln('       기다린다 — 오류는 안 나고 작업만 멈춘다. -->')
      ..writeln('  <executable output="screen"')
      ..writeln(
        '              cmd="python3 \$(var map_dir)/${mapName}_workcell.py"/>',
      )
      ..writeln('')
      ..writeln('  <!-- 라이다·카메라를 앱이 읽을 수 있게 파일로 내려 준다. -->')
      ..writeln('  <executable output="screen"')
      ..writeln(
        '              cmd="python3 \$(var map_dir)/${mapName}_sensor_relay.py'
        ' -o \$(var sensor_dir)"/>',
      );
  }
  buffer.writeln('</launch>');
  return buffer.toString();
}

/// 지도 그림의 픽셀을 RMF 월드 좌표(m)로 옮긴다.
///
/// RMF 지도 생성기(`rmf_building_map_tools`)는 building.yaml 에 적힌 픽셀을
/// 그대로 `(px × 축척, −py × 축척)` 으로 옮긴다. 원점은 **그림의 왼쪽 위**이고
/// y 는 위로 갈수록 커진다. Gazebo 월드도 nav graph 도 이 좌표를 쓰므로,
/// 로봇을 올릴 자리도 반드시 이 좌표로 적어야 한다.
///
/// 화면에 사람이 읽으라고 보여 주는 바닥 좌표는 바닥 왼쪽 **아래**가 원점이라
/// y 부호가 반대다. 그 값을 spawn 좌표로 쓰면 로봇이 건물 밖 허공에 놓여
/// 끝없이 떨어진다.
({double x, double y}) rmfWorldFromPixel(
  double px,
  double py,
  double metersPerPixel,
) => (x: px * metersPerPixel, y: -py * metersPerPixel);

/// [rmfWorldFromPixel] 의 역. 토픽이 준 미터를 화면 픽셀로 되돌린다.
({double dx, double dy}) pixelFromRmfWorld(
  double x,
  double y,
  double metersPerPixel,
) => (dx: x / metersPerPixel, dy: -y / metersPerPixel);

/// 등록된 로봇의 올릴 자리를 지금 지도에서 다시 계산한다.
///
/// spawn 좌표는 언제나 자리 Waypoint 에서 나온다. 예전 판은 화면에 보여 주는
/// 바닥 좌표(바닥 왼쪽 아래가 원점, y 는 위로)를 그대로 넣었는데, RMF 는 그림
/// 왼쪽 위가 원점이고 y 가 아래로 갈수록 음수다. 그렇게 저장된 프로젝트는 로봇을
/// 건물 밖 허공에 올려서 끝없이 떨어뜨렸다. 사람에게 다시 등록하라고 시키는
/// 대신 여기서 고쳐 준다.
///
/// [pixelOf] 는 로봇이 선 Waypoint 의 지도 픽셀을 돌려준다. 자리를 못 찾으면
/// null 을 돌려주고, 그런 로봇은 건드리지 않는다 — 지도가 아직 안 올라왔을 수
/// 있고, 그때 지워 버리면 멀쩡한 등록이 좌표를 잃는다.
///
/// 바꿀 것이 없으면 받은 목록을 그대로 돌려준다. 부르는 쪽이 `identical` 로
/// 달라졌는지 가려서 쓸데없이 다시 그리거나 저장하지 않게 한다.
List<RmfProjectRobot> robotsWithMapSpawnPoints(
  List<RmfProjectRobot> robots,
  ({double dx, double dy})? Function(RmfProjectRobot robot) pixelOf,
  double metersPerPixel,
) {
  if (metersPerPixel <= 0) return robots;
  var changed = false;
  final result = <RmfProjectRobot>[];
  for (final robot in robots) {
    final pixel = pixelOf(robot);
    if (pixel == null) {
      result.add(robot);
      continue;
    }
    final spawn = rmfWorldFromPixel(pixel.dx, pixel.dy, metersPerPixel);
    // 유효한 RMF 좌표가 충전 자리와 다르면 사용자가 별도의 시작 Waypoint를
    // 선택한 것이다. 충전은 작업 후 복귀 지점이고 spawn은 Gazebo 최초 위치라
    // 둘이 같을 필요가 없다. 예전 좌표계 버그는 화면 y를 그대로 저장해 spawnY가
    // 양수였으므로 그 값만 아래에서 현재 지도 기준으로 교정한다.
    final hasExplicitSpawn =
        robot.spawnX != null && robot.spawnY != null && robot.spawnY! <= 0;
    if (hasExplicitSpawn) {
      result.add(robot);
      continue;
    }
    if (robot.spawnX != null &&
        robot.spawnY != null &&
        (spawn.x - robot.spawnX!).abs() < 1e-6 &&
        (spawn.y - robot.spawnY!).abs() < 1e-6) {
      result.add(robot);
      continue;
    }
    changed = true;
    result.add(robot.withSpawn(spawnX: spawn.x, spawnY: spawn.y));
  }
  return changed ? result : robots;
}

/// 로봇 하나가 쓰는 디렉터리 이름. `robots/<로봇 ID>`.
///
/// 로봇마다 제 디렉터리를 두면 한 대를 빼거나 옮길 때 그 디렉터리만 보면 된다.
/// 파일 이름으로 쓸 수 없는 글자는 걷어낸다 — 로봇 ID 에 슬래시가 들어가면
/// 엉뚱한 곳에 디렉터리가 생긴다.
String robotDirectoryName(RmfProjectRobot robot) {
  final safe = robot.robotId.replaceAll(RegExp(r'[^a-zA-Z0-9가-힣_-]'), '_');
  return 'robots/${safe.isEmpty ? robot.gzName : safe}';
}

/// 이 맵이 RMF 월드에서 차지하는 범위(m). RViz 카메라를 여기에 맞춘다.
typedef RmfMapExtent = ({double minX, double maxX, double minY, double maxY});

/// RViz 가 nav graph 를 그리는 굵기의 기본값(m). `visualization.launch.xml` 값.
///
/// RMF 데모(창고 수십 미터)에 맞춘 값이다. 2~3m 짜리 실험실 도면에서는 Lane
/// 하나가 건물 폭의 1/5 이라, 스무 개가 겹쳐 덩어리로 보인다.
const double defaultNavGraphLaneWidth = .5;

/// 시각화 노드가 받는 가장 가는 Lane(m).
///
/// `NavGraphVisualizer.cpp` 가 `std::max(0.1, lane_width)` 로 깎는다. 더 가늘게
/// 적어도 0.1m 로 그려지므로, 화면에서 먼저 알려 준다.
const double minNavGraphLaneWidth = .1;

/// nav graph 를 얼마나 굵게 그릴까(m).
///
/// [manual] 이 있으면 그 값이다. 없으면 **로봇 폭**으로 그린다 — "이 Lane 을 이
/// 로봇이 지난다" 가 그림 그대로 보이는 것이 어림값보다 낫다.
double navGraphLaneWidth({required double robotWidthMeters, double? manual}) {
  final value = manual ?? robotWidthMeters;
  if (!value.isFinite || value <= 0) return defaultNavGraphLaneWidth;
  return value.clamp(minNavGraphLaneWidth, 2.0);
}

/// 바닥 그림이 오는 곳. `rmf_visualization_floorplans` 가 내는 이름이다.
///
/// **밑줄이 없다.** RMF 가 함께 주는 `rmf.rviz` 는 `/floor_plan` 을 보고 있어서
/// 도면이 영영 안 온다. 우리가 설정을 따로 만드는 첫 번째 이유다.
const String rmfFloorplanTopic = '/floorplan';

/// 이 프로젝트를 볼 RViz 설정.
///
/// RMF 가 함께 주는 `rmf_visualization_schedule/config/rmf.rviz` 를 그대로 쓰면
/// **검은 화면**이 된다. 그 파일은 office 데모를 보라고 맞춰 둔 것이다.
///
///   1. 카메라가 (17.7, -20.0) 을 가운데 놓고 폭 27m 를 본다. 우리 도면은
///      원점 둘레 두세 미터라 통째로 화면 밖이다.
///   2. 바닥 그림을 `/floor_plan` 에서 찾는다. 실제로 오는 이름은
///      `/floorplan` 이다(밑줄 없음). 이름이 어긋나 도면이 안 온다.
///   3. Grid 가 꺼져 있다. 그래서 카메라가 엉뚱한 데를 봐도 아무 단서가 없이
///      그냥 까맣다 — 고장 난 것과 구분되지 않는다.
///
/// 그래서 맵마다 우리가 만든다. 카메라는 이 맵의 [extent] 가운데를 보고, 토픽
/// 이름은 실제로 오는 것을 쓰고, Grid 는 켜 둔다.
///
/// [extent] 가 없으면(축척이나 Floor 가 아직 없으면) 원점 둘레를 넓게 본다.
String buildProjectRvizConfig({
  required String mapName,
  List<RmfProjectRobot> robots = const [],
  RmfMapExtent? extent,
}) {
  // 카메라가 볼 창 크기를 이만큼으로 잡고 배율을 정한다. 실제 창이 이보다
  // 크면 더 넓게 보일 뿐이라 지도가 잘리지 않는다.
  const viewportWidth = 1600.0;
  const viewportHeight = 900.0;
  // 도면 둘레를 조금 남긴다. 벽이 화면 가장자리에 딱 붙으면 답답하다.
  const margin = 1.25;

  final centerX = extent == null ? 0.0 : (extent.minX + extent.maxX) / 2;
  final centerY = extent == null ? 0.0 : (extent.minY + extent.maxY) / 2;
  final spanX = extent == null ? 0.0 : (extent.maxX - extent.minX).abs();
  final spanY = extent == null ? 0.0 : (extent.maxY - extent.minY).abs();
  // TopDownOrtho 의 `Scale` 은 1m 가 몇 픽셀인가다. 크면 확대다.
  final scale = spanX <= 0 || spanY <= 0
      ? 50.0
      : math
            .min(
              viewportWidth / (spanX * margin),
              viewportHeight / (spanY * margin),
            )
            .clamp(2.0, 500.0);
  // 격자는 지도를 덮고도 남게 깐다. 배경만 있는 화면과 구분되는 것이 목적이다.
  final gridCells = spanX <= 0 || spanY <= 0
      ? 40
      : (math.max(spanX, spanY).ceil() + 6).clamp(10, 200);

  final buffer = StringBuffer()
    ..writeln('# $mapName 프로젝트 RViz 설정.')
    ..writeln('# rmf_control_ui 가 맵 프로젝트에서 생성했다. 손으로 고치면')
    ..writeln('# 다음 저장 때 덮어써진다.')
    ..writeln('#')
    ..writeln('# 카메라는 이 맵의 가운데(${_n(centerX)}, ${_n(centerY)})를 본다.')
    ..writeln('# RMF 가 주는 rmf.rviz 는 office 데모 자리를 보고 있어 이 도면이')
    ..writeln('# 화면 밖이었다. 바닥 그림 토픽 이름도 거기서는 어긋나 있다.')
    ..writeln('Panels:')
    ..writeln('  - Class: rviz_common/Displays')
    ..writeln('    Name: Displays')
    ..writeln('    Property Tree Widget:')
    ..writeln('      Expanded: ~')
    ..writeln('      Splitter Ratio: 0.5')
    ..writeln('    Tree Height: 600')
    ..writeln('  - Class: rviz_common/Views')
    ..writeln('    Name: Views')
    ..writeln('Visualization Manager:')
    ..writeln('  Class: ""')
    ..writeln('  Displays:');

  // 격자. 아무 데이터가 없어도 이것만은 그려진다 — 화면이 살아 있다는 표시다.
  buffer
    ..writeln('    - Class: rviz_default_plugins/Grid')
    ..writeln('      Name: 격자 (1m)')
    ..writeln('      Enabled: true')
    ..writeln('      Alpha: 0.35')
    ..writeln('      Cell Size: 1')
    ..writeln('      Color: 130; 130; 130')
    ..writeln('      Line Style:')
    ..writeln('        Line Width: 0.03')
    ..writeln('        Value: Lines')
    ..writeln('      Normal Cell Count: 0')
    ..writeln('      Offset:')
    ..writeln('        X: 0')
    ..writeln('        Y: 0')
    ..writeln('        Z: 0')
    ..writeln('      Plane: XY')
    ..writeln('      Plane Cell Count: $gridCells')
    ..writeln('      Reference Frame: <Fixed Frame>')
    ..writeln('      Value: true');

  void mapDisplay({
    required String name,
    required String topic,
    required double alpha,
    required bool enabled,
  }) {
    buffer
      ..writeln('    - Class: rviz_default_plugins/Map')
      ..writeln('      Name: $name')
      ..writeln('      Enabled: $enabled')
      ..writeln('      Alpha: $alpha')
      ..writeln('      Color Scheme: map')
      ..writeln('      Draw Behind: true')
      ..writeln('      Topic:')
      ..writeln('        Depth: 5')
      // 지도는 한 번 내고 만다. Volatile 로 받으면 늦게 붙은 RViz 는 영영
      // 아무것도 못 받는다 — rmf.rviz 가 그렇게 돼 있다.
      ..writeln('        Durability Policy: Transient Local')
      ..writeln('        History Policy: Keep Last')
      ..writeln('        Reliability Policy: Reliable')
      ..writeln('        Value: $topic')
      ..writeln('      Use Timestamp: false')
      ..writeln('      Value: true');
  }

  void markerArray({
    required String name,
    required String topic,
    required bool transientLocal,
    bool enabled = true,
  }) {
    buffer
      ..writeln('    - Class: rviz_default_plugins/MarkerArray')
      ..writeln('      Name: $name')
      ..writeln('      Enabled: $enabled')
      ..writeln('      Namespaces:')
      ..writeln('        {}')
      ..writeln('      Topic:')
      ..writeln('        Depth: 10')
      ..writeln(
        '        Durability Policy: '
        '${transientLocal ? 'Transient Local' : 'Volatile'}',
      )
      ..writeln('        History Policy: Keep Last')
      ..writeln('        Reliability Policy: Reliable')
      ..writeln('        Value: $topic')
      ..writeln('      Value: true');
  }

  mapDisplay(
    name: '도면 (RMF 바닥 그림)',
    topic: rmfFloorplanTopic,
    alpha: 0.9,
    enabled: true,
  );
  if (projectUsesNav2(robots)) {
    // 로봇이 실제로 위치를 맞추는 지도다. 도면과 겹쳐 놓으면 두 장이 포개져
    // 무엇이 무엇인지 알 수 없으므로 꺼 둔다. 도면과 어긋났는지 볼 때 켠다 —
    // 그때는 도면을 끄고 이것만 본다.
    mapDisplay(
      name: 'Nav2 지도 (도면과 견줄 때 켜세요)',
      topic: nav2MapTopic,
      alpha: 0.7,
      enabled: false,
    );
  }
  markerArray(
    name: 'Nav graph (Lane·Waypoint)',
    topic: '/map_markers',
    transientLocal: true,
  );
  // 로봇 자리는 계속 새로 온다. `/fleet_markers` 에는 발행자가 둘인데(하나는
  // transient local, 하나는 volatile), transient local 로 받으면 volatile 쪽과
  // QoS 가 안 맞아 그 발행자의 값이 하나도 안 온다. volatile 로 받으면 둘 다
  // 받는다 — RViz 가 "incompatible QoS" 경고를 내던 것이 이것이다.
  markerArray(
    name: '로봇 (RMF fleet)',
    topic: '/fleet_markers',
    transientLocal: false,
  );
  markerArray(name: '예약 경로', topic: '/schedule_markers', transientLocal: false);
  markerArray(
    name: '문·리프트',
    topic: '/building_systems_markers',
    transientLocal: true,
  );

  // 라이다. 벽 높이를 낮춰 놓고 라이다가 벽을 넘겨다보는지 여기서 확인한다.
  for (final robot in robots.where(
    (robot) => robot.isMobile && robot.runsInGazebo,
  )) {
    buffer
      ..writeln('    - Class: rviz_default_plugins/LaserScan')
      ..writeln('      Name: 라이다 ${robot.robotId}')
      ..writeln('      Enabled: true')
      ..writeln('      Alpha: 1')
      ..writeln('      Color: 255; 85; 0')
      ..writeln('      Color Transformer: FlatColor')
      ..writeln('      Decay Time: 0')
      ..writeln('      Position Transformer: XYZ')
      ..writeln('      Size (m): 0.03')
      ..writeln('      Style: Points')
      ..writeln('      Topic:')
      ..writeln('        Depth: 5')
      ..writeln('        Durability Policy: Volatile')
      ..writeln('        History Policy: Keep Last')
      ..writeln('        Reliability Policy: Best Effort')
      ..writeln('        Value: /${robot.gzName}/scan')
      ..writeln('      Value: true');
  }

  // TF 는 꺼 둔다. 프레임이 로봇 수만큼 늘어나 지도를 덮는다. 위치가 안 맞을
  // 때 켜서 map → odom → base_link 가 이어져 있는지 본다.
  buffer
    ..writeln('    - Class: rviz_default_plugins/TF')
    ..writeln('      Name: TF (필요할 때 켜세요)')
    ..writeln('      Enabled: false')
    ..writeln('      Marker Scale: 0.4')
    ..writeln('      Show Arrows: true')
    ..writeln('      Show Axes: true')
    ..writeln('      Show Names: true')
    ..writeln('      Value: true')
    ..writeln('  Enabled: true')
    ..writeln('  Global Options:')
    ..writeln('    Background Color: 48; 48; 48')
    // RMF 도 Nav2 도 이 프레임을 쓴다. 마커와 지도가 모두 여기 실려 온다.
    ..writeln('    Fixed Frame: map')
    ..writeln('    Frame Rate: 30')
    ..writeln('  Name: root')
    ..writeln('  Tools:')
    ..writeln('    - Class: rviz_default_plugins/MoveCamera')
    ..writeln('    - Class: rviz_default_plugins/Select')
    ..writeln('    - Class: rviz_default_plugins/FocusCamera')
    ..writeln('    - Class: rviz_default_plugins/Measure')
    ..writeln('      Line color: 128; 128; 0')
    ..writeln('  Transformation:')
    ..writeln('    Current:')
    ..writeln('      Class: rviz_default_plugins/TF')
    ..writeln('  Value: true')
    ..writeln('  Views:')
    ..writeln('    Current:')
    ..writeln('      Class: rviz_default_plugins/TopDownOrtho')
    ..writeln('      Name: Current View')
    ..writeln('      Angle: 0')
    ..writeln('      Near Clip Distance: 0.01')
    ..writeln('      Scale: ${_n(scale.toDouble())}')
    ..writeln('      Target Frame: <Fixed Frame>')
    ..writeln('      X: ${_n(centerX)}')
    ..writeln('      Y: ${_n(centerY)}')
    ..writeln('      Value: TopDownOrtho (rviz_default_plugins)')
    ..writeln('    Saved: ~')
    ..writeln('Window Geometry:')
    ..writeln('  Displays:')
    ..writeln('    collapsed: false')
    ..writeln('  Height: ${viewportHeight.round()}')
    ..writeln('  Hide Left Dock: false')
    ..writeln('  Hide Right Dock: true')
    ..writeln('  Views:')
    ..writeln('    collapsed: true')
    ..writeln('  Width: ${viewportWidth.round()}')
    ..writeln('  X: 60')
    ..writeln('  Y: 60');
  return buffer.toString();
}

/// 로봇 한 대의 등록 정보. 사람이 읽고 확인하는 용도다.
String buildRobotInfoYaml(RmfProjectRobot robot) {
  final buffer = StringBuffer()
    ..writeln('# ${robot.robotId} · ${robot.displayName}')
    ..writeln('# rmf_control_ui 가 맵 프로젝트에서 생성했다. 손으로 고치면')
    ..writeln('# 다음 저장 때 덮어써진다. 고치려면 앱의 로봇 등록에서 고친다.')
    ..writeln('id: ${robot.robotId}')
    ..writeln('name: ${robot.displayName}')
    ..writeln('kind: ${robot.kind.storageValue} # ${robot.kind.label}')
    ..writeln(
      'data_source: ${robot.dataSource.name} # ${robot.dataSource.label}',
    )
    ..writeln('model: ${robot.model}')
    ..writeln('gz_name: ${robot.gzName} # 토픽 네임스페이스')
    ..writeln(
      robot.rosDomainId == null
          ? 'ros_domain_id: # 비었으면 프로젝트 기본값을 쓴다'
          : 'ros_domain_id: ${robot.rosDomainId} # 이 로봇만 따로 정했다',
    )
    ..writeln('zones: [${robot.zones.join(', ')}]');
  if (robot.chargerWaypoint != null) {
    buffer.writeln(
      robot.isMobile
          ? 'charger_waypoint: ${robot.chargerWaypoint} # 충전 자리'
          : 'station_waypoint: ${robot.chargerWaypoint} # 설비 자리',
    );
  }
  if (robot.spawnX != null && robot.spawnY != null) {
    buffer
      ..writeln('spawn_x: ${_n(robot.spawnX!)}')
      ..writeln('spawn_y: ${_n(robot.spawnY!)}');
  }
  buffer.writeln('spawn_heading: ${_n(robot.spawnHeading)}');
  return buffer.toString();
}

/// 이 로봇만 다른 도메인을 쓸 때 launch 맨 위에 넣을 줄.
///
/// `set_env` 는 그 뒤에 뜨는 프로세스의 환경을 바꾼다. 노드가 도메인을 정하는
/// 것은 `ROS_DOMAIN_ID` 환경 변수뿐이라, 이 방법 말고는 대마다 가를 수 없다.
///
/// 프로젝트 기본값을 쓰는 로봇은 아무것도 안 쓴다 — 빈 값을 넣으면 스크립트가
/// 내보낸 값을 덮어써서, 기본값을 고쳐도 안 따라온다.
String _robotDomainEnv(RmfProjectRobot robot) {
  final domain = robot.rosDomainId;
  if (domain == null) return '';
  return '  <!-- 이 로봇만 도메인 $domain 을 쓴다. 프로젝트 기본값이 아니다.\n'
      '       Gazebo 로봇이면 시뮬레이터와 같아야 한다 — 다르면 다리가 걸어 둔\n'
      '       토픽에 값이 하나도 안 온다. 오류는 안 난다. -->\n'
      '  <set_env name="ROS_DOMAIN_ID" value="$domain"/>\n';
}

/// 로봇 한 대만 Gazebo 에 올리는 launch.
///
/// 프로젝트 bringup 이 이 파일을 `<include>` 한다. 로봇을 빼려면 등록에서 지우면
/// 되고, 한 대만 따로 시험하려면 이 파일만 돌려 보면 된다.
String buildRobotSpawnLaunchXml(RmfProjectRobot robot) {
  final x = (robot.spawnX ?? 0).toStringAsFixed(3);
  final y = (robot.spawnY ?? 0).toStringAsFixed(3);
  final heading = robot.spawnHeading.toStringAsFixed(3);
  final buffer = StringBuffer()
    ..writeln("<?xml version='1.0' ?>")
    ..writeln('<!--')
    ..writeln('  ${robot.robotId} · ${robot.displayName} (${robot.kind.label})')
    ..writeln('  rmf_control_ui 가 맵 프로젝트에서 생성했다.')
    ..writeln('')
    ..writeln('  이 로봇 한 대만 Gazebo 에 올린다. 월드는 이미 떠 있다고 본다.')
    ..writeln('')
    ..writeln('  값의 출처: ${robot.dataSource.label}');
  if (robot.runsInGazebo) {
    buffer.writeln('  프로젝트 bringup 이 이 파일을 include 한다.');
  } else {
    // 출처가 Gazebo 가 아니면 bringup 이 이 파일을 부르지 않는다. 파일만 보고
    // 왜 안 올라오는지 헤매지 않도록 여기 적어 둔다.
    buffer
      ..writeln('  값의 출처가 Gazebo 가 아니라서 bringup 이 부르지 않는다.')
      ..writeln('  Gazebo 로 돌리려면 로봇 등록에서 출처를 Gazebo 로 바꾼다.');
  }
  buffer
    ..writeln('')
    ..writeln('  혼자 시험하려면:')
    ..writeln('    ros2 launch <이 파일>')
    ..writeln('-->')
    ..writeln('<launch>')
    ..write(_robotDomainEnv(robot));
  if (!robot.isMobile) {
    // 설치 로봇은 설명 파일도 실행 방법도 다르다. pinky_description 이 아니라
    // open_manipulator_description 의 xacro 를 펼치고, 바퀴 대신 ros2_control
    // 컨트롤러를 올린다.
    buffer
      ..writeln('  <group>')
      // 여기서는 push-ros-namespace 를 쓴다. 아래 노드들에 네임스페이스를 따로
      // 걸지 않으므로 두 겹이 되지 않는다. 이동 로봇 쪽은 include 하는 launch 가
      // 이미 namespace 인자를 받으므로 겹쳐 걸면 안 된다.
      ..writeln('    <push-ros-namespace namespace="${robot.gzName}"/>')
      ..writeln('    <node pkg="robot_state_publisher"')
      ..writeln('          exec="robot_state_publisher" output="screen">')
      ..writeln('      <param name="use_sim_time" value="True"/>')
      ..writeln('      <param name="frame_prefix" value="${robot.gzName}/"/>')
      ..writeln('      <param name="robot_description"')
      // 벤더 xacro 의 gz_ros2_control 플러그인에는 네임스페이스가 없다. 그대로
      // 두면 플러그인이 루트 `/robot_description` 을 기다리며 **Gazebo 의 갱신
      // 루프 전체를 막는다.** 시간이 안 흘러 /clock 도 odom 도 나오지 않는다.
      // 그래서 펼친 URDF 에 네임스페이스를 끼워 넣는 스크립트를 거친다.
      ..writeln(
        '             value="\$(command \'\$(dirname)'
        '/robot_description.sh\')"/>',
      )
      ..writeln('    </node>')
      ..writeln('    <node pkg="ros_gz_sim" exec="create" output="screen"')
      ..writeln(
        '          args="-name ${robot.gzName} '
        '-topic robot_description '
        '-x $x -y $y -z 0.0 -Y $heading '
        '-allow_renaming true">',
      )
      ..writeln('      <param name="use_sim_time" value="True"/>')
      ..writeln('    </node>')
      ..writeln('    <!-- 팔은 ros2_control 컨트롤러가 움직인다. -->');
    // 모델마다 컨트롤러가 다르다. 없는 것을 올리면 spawner 가 기다리다
    // 실패한다 — 예를 들어 omy_3m 에는 그리퍼가 없다.
    final controllers =
        openManipulatorControllers[robot.model] ??
        const ['joint_state_broadcaster', 'arm_controller'];
    for (final controller in controllers) {
      buffer
        ..writeln('    <node pkg="controller_manager" exec="spawner"')
        ..writeln('          args="$controller" output="screen"/>');
    }
    buffer
      ..writeln('  </group>')
      ..writeln('</launch>');
    return buffer.toString();
  }
  buffer
    ..writeln('  <group>')
    // 벤더의 upload_robot.launch.py 를 그대로 쓰지 않는다. 그 launch 가 펼치는
    // xacro 는 링크 이름에는 네임스페이스를 안 붙이면서 <gazebo reference> 에는
    // 붙여서, 라이다·카메라·IMU 가 통째로 버려진다. robot_description.sh 가
    // 펼친 뒤 그 접두사를 뗀다. 나머지는 벤더 launch 와 똑같이 맞춘다.
    ..writeln('    <push-ros-namespace namespace="${robot.gzName}"/>')
    ..writeln('    <node pkg="robot_state_publisher"')
    ..writeln('          exec="robot_state_publisher"')
    ..writeln('          name="robot_state_publisher" output="screen">')
    ..writeln('      <param name="use_sim_time" value="True"/>')
    ..writeln('      <param name="ignore_timestamp" value="False"/>')
    // TF 프레임의 접두사는 여기서 붙는다. 링크 이름을 안 건드리는 이유다.
    ..writeln('      <param name="frame_prefix" value="${robot.gzName}/"/>')
    ..writeln(
      '      <param name="robot_description"'
      ' value="\$(command \'\$(dirname)/robot_description.sh\')"/>',
    )
    ..writeln('    </node>')
    ..writeln('    <node pkg="joint_state_publisher"')
    ..writeln('          exec="joint_state_publisher"')
    ..writeln('          name="joint_state_publisher" output="screen">')
    ..writeln('      <param name="use_sim_time" value="True"/>')
    ..writeln('      <param name="rate" value="20.0"/>')
    ..writeln('      <param name="source_list" value="[joint_states]"/>')
    ..writeln('    </node>')
    ..writeln('    <node pkg="ros_gz_sim" exec="create" output="screen"')
    ..writeln(
      '          args="-name ${robot.gzName} '
      '-topic /${robot.gzName}/robot_description '
      '-x $x -y $y -z 0.1 -Y $heading">',
    )
    ..writeln('      <param name="use_sim_time" value="True"/>')
    ..writeln('    </node>')
    ..writeln('  </group>')
    ..writeln('</launch>');
  return buffer.toString();
}

/// 설치 로봇의 URDF 를 만드는 스크립트.
///
/// 벤더 xacro 의 `gz_ros2_control` 플러그인에는 네임스페이스가 없다. 그대로
/// 두면 플러그인이 루트 `/robot_description` 을 기다리는데, 우리는 로봇마다
/// 네임스페이스를 나누므로 그 토픽이 영영 오지 않는다.
///
/// 그냥 못 뜨고 마는 것이 아니다. **플러그인이 Gazebo 의 갱신 루프 안에서
/// 기다리기 때문에 시뮬레이션 전체가 멈춘다.** `/clock` 이 안 나오고, 같은
/// 월드의 Pinky 도 odom 을 못 낸다. 관제 노드 19개가 sim 시간을 기다리며
/// 통째로 굳는다.
///
/// 그래서 펼친 URDF 에 네임스페이스를 끼워 넣는다.
String buildRobotDescriptionScript(RmfProjectRobot robot) => robot.isMobile
    ? _buildMobileDescriptionScript(robot)
    : _buildWorkcellDescriptionScript(robot);

/// 이동 로봇의 URDF 를 만든다.
///
/// 벤더 xacro 는 **링크 이름에는 네임스페이스를 안 붙이는데
/// `<gazebo reference>` 에는 붙인다.**
///
/// ```xml
/// <link name="rplidar_link"/>                  ← 접두사 없음
/// <gazebo reference="pinky_01/rplidar_link">   ← 접두사 있음
///   <sensor name="pinky_01/gpu_lidar" type="gpu_lidar">
/// ```
///
/// 맞는 링크가 없으니 그 `<gazebo>` 블록이 통째로 버려진다. **라이다도 카메라도
/// IMU 도 올라가지 않는다.** 토픽 이름은 다리(bridge)가 만들어서 보이는데 데이터가
/// 영영 안 온다. 오류도 나지 않는다. 바퀴 마찰(`mu1`·`mu2`·`kp`)도 같이 버려진다.
///
/// 링크에 접두사를 붙이지 않는 것은 일부러다 — TF 는 `robot_state_publisher` 의
/// `frame_prefix` 가 붙인다. 그러니 `reference` 쪽 접두사를 떼는 것이 맞다.
///
/// 벤더 파일은 건드리지 않는다. 펼친 뒤에 고친다.
String _buildMobileDescriptionScript(RmfProjectRobot robot) =>
    '''#!/usr/bin/env bash
# ${robot.robotId} 의 URDF 를 만든다.
# rmf_control_ui 가 맵 프로젝트에서 생성했다.
#
# 벤더 xacro 는 링크 이름에는 네임스페이스를 안 붙이면서 <gazebo reference> 에는
# 붙인다. 맞는 링크가 없어 그 블록이 통째로 버려지고, 라이다·카메라·IMU 가
# 하나도 안 올라간다. 토픽 이름은 보이는데 데이터가 영영 안 오고 오류도 안 난다.
#
# 링크에 접두사를 안 붙이는 것은 일부러다 — TF 는 robot_state_publisher 의
# frame_prefix 가 붙인다. 그러니 reference 쪽 접두사를 떼는 것이 맞다.
set -euo pipefail

NAMESPACE="\${NAMESPACE:-${robot.gzName}}"
CAM_TILT_DEG="\${CAM_TILT_DEG:-0}"

XACRO="\$(ros2 pkg prefix pinky_description)"
XACRO="\$XACRO/share/pinky_description/urdf/robot.urdf.xacro"

# 펼친 결과를 파일에 받는다. python 을 heredoc 으로 넘기려면 표준 입력이
# 비어 있어야 한다.
RAW="\$(mktemp)"
trap 'rm -f "\$RAW"' EXIT

# 벤더 launch 와 같은 인자로 펼친다. 네임스페이스 끝의 빗금까지 같아야 한다.
xacro "\$XACRO" \\
  namespace:="\$NAMESPACE/" \\
  is_sim:=true \\
  cam_tilt_deg:="\$CAM_TILT_DEG" > "\$RAW"

python3 - "\$RAW" "\$NAMESPACE" <<'PYTHON'
import re
import sys

path, namespace = sys.argv[1], sys.argv[2]
with open(path, encoding="utf-8") as handle:
    urdf = handle.read()

links = set(re.findall('<link name="([^"]+)"', urdf))
joints = set(re.findall('<joint name="([^"]+)"', urdf))
prefix = namespace + '/'

# 조인트 이름에는 네임스페이스가 붙어 있고 링크 이름에는 안 붙어 있다. 그래서
# 무조건 떼면 조인트 쪽이 깨진다. 가리키는 것이 무엇인지 보고 정한다.
def fix(match):
    name = match.group(1)
    if name in links or name in joints:
        return match.group(0)
    if name.startswith(prefix) and name[len(prefix):] in links:
        return '<gazebo reference="' + name[len(prefix):] + '"'
    sys.stderr.write(
        name + ' 이(가) 없어 그 <gazebo> 블록이 버려집니다.\\n')
    return match.group(0)

urdf, seen = re.subn('<gazebo reference="([^"]+)"', fix, urdf)
if seen == 0:
    sys.stderr.write('<gazebo reference> 가 하나도 없습니다.\\n')

sys.stdout.write(urdf)
PYTHON
''';

String _buildWorkcellDescriptionScript(RmfProjectRobot robot) =>
    '''#!/usr/bin/env bash
# ${robot.robotId} 의 URDF 를 만든다.
# rmf_control_ui 가 맵 프로젝트에서 생성했다.
#
# 벤더 xacro 의 gz_ros2_control 플러그인에 네임스페이스를 끼워 넣는다. 없으면
# 플러그인이 루트 /robot_description 을 기다리며 Gazebo 갱신 루프를 막는다.
set -euo pipefail

MODEL="\${MODEL:-${robot.model}}"
NAMESPACE="\${NAMESPACE:-${robot.gzName}}"

XACRO="\$(ros2 pkg prefix open_manipulator_description)"
XACRO="\$XACRO/share/open_manipulator_description/urdf/\$MODEL/\$MODEL.urdf.xacro"

xacro "\$XACRO" use_sim:=true | python3 -c '
import re
import sys

namespace = sys.argv[1]
urdf = sys.stdin.read()
# 플러그인 여는 태그 바로 뒤에 끼워 넣는다. 벤더 파일을 건드리지 않는다.
urdf = re.sub(
    r"(<plugin[^>]*gz_ros2_control[^>]*>)",
    r"\\1<ros><namespace>/" + namespace + r"</namespace></ros>"
    r"<robot_param_node>robot_state_publisher</robot_param_node>",
    urdf,
    count=1,
)
sys.stdout.write(urdf)
' "\$NAMESPACE"
''';

/// 로봇 한 대의 토픽 다리 설정.
///
/// 실행에는 프로젝트 전체를 묶은 `<맵이름>_gz_bridge.yaml` 을 쓴다. 이 파일은
/// 이 로봇이 무엇을 주고받는지 한자리에서 보기 위한 것이다. 둘 다 같은 등록
/// 정보에서 만들어지므로 어긋나지 않는다.
String buildRobotBridgeYaml(RmfProjectRobot robot) =>
    buildProjectGzBridgeYaml(
          mapName: robot.robotId,
          robots: [robot],
          // clock 과 tf 는 월드에 하나뿐이다. 로봇별 파일에 넣어 두면 이것만
          // 보고 돌렸을 때 같은 토픽에 다리를 두 번 놓게 된다.
          includeGlobal: false,
        )
        .replaceFirst(
          '# ${robot.robotId} 프로젝트의 ros_gz_bridge 설정.',
          '# ${robot.robotId} 한 대의 토픽 목록.',
        )
        .replaceFirst(
          '# rmf_control_ui 가 맵 프로젝트에서 생성했다.',
          '# 실행에는 프로젝트 전체를 묶은 <맵이름>_gz_bridge.yaml 을 쓴다.\n'
              '# clock 과 tf 는 월드에 하나뿐이라 여기 넣지 않았다.',
        );

/// 로봇 디렉터리에 함께 두는 설명.
String buildRobotReadme(RmfProjectRobot robot, String mapName) {
  final station = robot.chargerWaypoint ?? '미지정';
  final buffer = StringBuffer()
    ..writeln('# ${robot.robotId} · ${robot.displayName}')
    ..writeln()
    ..writeln('$mapName 프로젝트의 ${robot.kind.label}입니다.')
    ..writeln('rmf_control_ui 가 로봇 등록에서 만들었습니다.')
    ..writeln()
    ..writeln('| 항목 | 값 |')
    ..writeln('|---|---|')
    ..writeln('| 종류 | ${robot.kind.label} |')
    ..writeln('| 값의 출처 | ${robot.dataSource.label} |')
    ..writeln('| 모델 | ${robot.model} |')
    ..writeln('| Gazebo 이름 | ${robot.gzName} |')
    ..writeln('| 토픽 네임스페이스 | `/${robot.gzName}` |')
    ..writeln('| ${robot.isMobile ? '충전' : '설비'} 자리 | $station |');
  if (robot.isMobile) {
    buffer.writeln('| 구획 자격 | ${robot.zones.join(', ')} |');
  }
  buffer
    ..writeln()
    ..writeln(robot.dataSource.summary)
    ..writeln();
  if (robot.runsInGazebo) {
    buffer.writeln('프로젝트 bringup 이 이 로봇을 Gazebo 에 올립니다.');
  } else if (robot.dataSource == RobotDataSource.real) {
    buffer
      ..writeln('실물이 이미 있으므로 Gazebo 에는 올리지 않습니다.')
      ..writeln('fleet adapter 에는 들어갑니다.');
  } else {
    buffer
      ..writeln('앱 안에서만 도는 로봇입니다.')
      ..writeln('fleet adapter 에도 Gazebo 에도 들어가지 않습니다.');
  }
  buffer
    ..writeln()
    ..writeln('## 파일')
    ..writeln()
    ..writeln('| 파일 | 용도 |')
    ..writeln('|---|---|')
    ..writeln('| `robot.yaml` | 이 로봇의 등록 정보 |')
    ..writeln('| `spawn.launch.xml` | 이 로봇만 Gazebo 에 올리는 launch |')
    ..writeln('| `bridge.yaml` | 이 로봇이 주고받는 토픽 |')
    ..writeln()
    ..writeln('프로젝트 bringup 이 `spawn.launch.xml` 을 include 합니다.')
    ..writeln('이 로봇만 따로 시험하려면 그 파일을 직접 돌리면 됩니다.')
    ..writeln()
    ..writeln('## 고치는 곳')
    ..writeln()
    ..writeln('여기 파일을 손으로 고치지 마세요. 다음 저장 때 덮어써집니다.')
    ..writeln('앱의 `로봇` 메뉴 → `로봇 등록`에서 고칩니다.');
  if (!robot.isMobile) {
    buffer
      ..writeln()
      ..writeln('## 설치 로봇 참고')
      ..writeln()
      ..writeln('한자리에 고정되므로 fleet adapter 에 들어가지 않습니다.')
      ..writeln('배차 대상이 아니라 Open-RMF 에서는 workcell 로 다룹니다.')
      ..writeln()
      ..writeln('올리는 컨트롤러:')
      ..writeln();
    final controllers =
        openManipulatorControllers[robot.model] ??
        const ['joint_state_broadcaster', 'arm_controller'];
    for (final controller in controllers) {
      buffer.writeln('- `$controller`');
    }
  }
  return buffer.toString();
}

/// 설비 로봇을 RMF 의 워크셀(dispenser·ingestor)로 잇는 노드.
///
/// 로봇이 픽업 자리에 닿으면 RMF 가 `/dispenser_requests` 에
/// `target_guid: 픽업2` 를 낸다. **그 이름으로 답하는 노드가 없으면 RMF 는
/// 영원히 기다린다** — 오류는 안 나고 작업만 그 자리에서 멈춘다.
///
/// 이 노드가 그 답을 한다. 요청을 받으면 팔에 관절 궤적을 보내고, 끝나면
/// `/dispenser_results` 에 SUCCESS 를 낸다.
///
/// `/dispenser_states` 를 1초마다 내는 것도 함께 한다. RMF 는 상태가 안 오는
/// 워크셀을 **없는 것으로 본다** — 요청조차 안 보낸다.
String buildWorkcellScript({
  required String mapName,
  required WorkcellPairingResult pairing,
  List<WorkcellPolicy> policies = const [],
}) {
  final nodeName = _rosNodeName('${mapName}_workcell');
  final entries = pairing.pairings
      .map(
        (item) =>
            "    ('${item.robot.robotId}', '${item.robot.gzName}', "
            "'${item.robot.model}', ${_pyList(item.dispensers)}, "
            '${_pyList(item.ingestors)}, '
            '${_pyList([for (final policy in policies)
              if (policy.deployedWorkcells.contains(item.robot.robotId) && policy.robotModel == item.robot.model) policy.id])}),',
      )
      .join('\n');
  return '''#!/usr/bin/env python3
"""$mapName 프로젝트의 RMF 워크셀 어댑터.

rmf_control_ui 가 맵 프로젝트에서 생성했다. 손으로 고치면 다음 저장 때
덮어써진다.

로봇이 픽업 자리에 닿으면 RMF 가 `/dispenser_requests` 로 그 자리 이름을
부른다. 여기서 팔을 움직이고 `/dispenser_results` 로 끝났다고 답한다.

답하지 않으면 RMF 는 영원히 기다린다. 오류는 안 난다 — 작업이 그 자리에서
멈춰 있을 뿐이다.
"""

import sys
import threading

import rclpy
import rclpy.node
from rclpy.qos import QoSProfile, QoSDurabilityPolicy, QoSReliabilityPolicy

from builtin_interfaces.msg import Time
from rmf_dispenser_msgs.msg import DispenserRequest, DispenserResult, DispenserState
from rmf_ingestor_msgs.msg import IngestorRequest, IngestorResult, IngestorState
from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint

# 로봇 ID, ROS 네임스페이스, 모델, 맡은 자리와 배포된 policy.
WORKCELLS = [
$entries
]

# 팔이 한 번 움직이는 데 걸리는 시간 [s].
#
# RMF 는 이 시간을 모른다. 우리가 끝났다고 알릴 때까지 기다릴 뿐이다.
ACTION_SECONDS = 4.0

# 팔 궤적의 마지막 시각과 동시에 RMF에 성공을 알리면 관절 컨트롤러가
# 마지막 자세를 정착시키는 동안 모바일 로봇이 출발할 수 있다. 궤적이 끝난
# 뒤 이 시간만큼 더 기다린 다음 성공을 알려 핑키가 안전하게 출발하게 한다.
ARM_SETTLE_SECONDS = 3.0

# 물품 종류별 가상 모방학습 policy. 모든 OMX가 같은 다섯 policy를 제공한다.
# 각 값은 시간 비율과 joint1~4 자세이며 실제 추론기 연결 전 동작 검증용이다.
JOINT_NAMES = ['joint1', 'joint2', 'joint3', 'joint4']
HOME_POSE = [0.0, -1.0, 0.3, 0.7]
POLICY_MOTIONS = {
    'policy_1': [[0.00, 0.45, -0.30, 0.65], [0.00, 0.75, -0.55, 0.90]],
    'policy_2': [[0.35, 0.35, -0.20, 0.55], [0.55, 0.70, -0.45, 0.80]],
    'policy_3': [[-0.35, 0.35, -0.20, 0.55], [-0.55, 0.70, -0.45, 0.80]],
    'policy_4': [[0.20, 0.15, 0.05, 0.45], [0.35, 0.55, -0.20, 0.70]],
    'policy_5': [[-0.20, 0.15, 0.05, 0.45], [-0.35, 0.55, -0.20, 0.70]],
}

# 학습 policy 실행기를 연결하기 전 controller·RMF 경로를 검증하는 저속 궤적.
# 실제 ACT 추론 결과가 아니며 배포된 policy ID에만 사용한다.
MODEL_TEST_MOTIONS = {
    'open_manipulator_x': {
        'joints': ['joint1', 'joint2', 'joint3', 'joint4'],
        'home': [0.0, -1.0, 0.3, 0.7],
        'poses': [[0.15, -0.85, 0.25, 0.65], [-0.15, -0.85, 0.25, 0.65]],
    },
    'omx_f': {
        'joints': ['joint1', 'joint2', 'joint3', 'joint4', 'joint5', 'gripper_joint_1'],
        'home': [0.0, -1.0, 0.3, 0.7, 0.0, 0.0],
        'poses': [[0.15, -0.85, 0.25, 0.65, 0.10, 0.0],
                  [-0.15, -0.85, 0.25, 0.65, -0.10, 0.0]],
    },
}

# 2usang/trihouse-sandwich episode 0의 성공 시연을 1초 간격으로 추린 값.
# [시각(s), joint1~5(deg), gripper(deg)]이며 controller 전송 때 rad로 바꾼다.
SANDWICH_REPLAY_DEG = [
    [0.0, -0.611, -66.398, 55.018, 47.692, 0.415, 60.147],
    [1.0, -0.611, -66.398, 55.018, 47.692, 0.415, 60.147],
    [2.0, -0.611, -66.398, 55.018, 47.692, 0.415, 60.147],
    [3.0, -0.611, -66.398, 55.018, 47.692, 0.415, 60.147],
    [4.0, -0.611, -66.398, 55.018, 47.692, 0.415, 60.147],
    [5.0, -0.659, -66.398, 55.018, 47.692, 0.415, 60.147],
    [6.0, -0.708, -66.545, 55.018, 43.834, 0.562, 61.001],
    [7.0, -3.053, -66.545, 54.969, 28.547, 0.317, 60.977],
    [8.0, -8.474, -66.545, 54.872, 24.884, 0.708, 59.487],
    [9.0, -18.437, -66.252, 37.729, 25.421, 0.073, 59.219],
    [10.0, -30.696, -49.109, 20.147, 25.079, -7.937, 58.999],
    [11.0, -33.529, -40.757, 10.916, 21.270, -7.253, 58.632],
    [12.0, -33.480, -39.585, 10.183, 17.216, -3.639, 58.657],
    [13.0, -33.431, -34.945, 6.325, 16.044, -3.248, 58.657],
    [14.0, -33.480, -34.212, 6.374, 15.263, -3.492, 58.657],
    [15.0, -33.431, -32.405, 6.716, 14.481, -3.541, 58.681],
    [16.0, -33.431, -32.259, 6.618, 14.432, -3.492, 58.681],
    [17.0, -34.896, -26.593, 6.716, 12.088, -3.394, 58.657],
    [18.0, -34.408, -21.661, -0.659, 12.381, -0.073, 58.388],
    [19.0, -34.164, -17.216, -3.980, 12.234, -0.122, 57.875],
    [20.0, -33.187, -14.286, -5.934, 12.186, -0.073, 57.680],
    [21.0, -32.112, -13.211, -6.032, 11.990, -0.366, 53.187],
    [22.0, -31.233, -14.530, -5.836, 9.499, -0.171, 47.131],
    [23.0, -33.529, -20.684, -5.055, 10.183, -0.122, 46.716],
    [24.0, -45.250, -24.298, -1.245, 13.260, 1.783, 46.716],
    [25.0, -51.013, -24.835, 6.862, 12.772, 1.685, 46.740],
    [26.0, -60.488, -20.488, 7.692, 14.969, 3.932, 46.716],
    [27.0, -65.763, -12.381, 7.839, 20.391, 7.497, 46.716],
    [28.0, -69.035, -3.883, 7.448, 19.365, 7.448, 46.862],
    [29.0, -68.742, -2.711, 6.569, 18.486, 7.497, 59.243],
    [30.0, -65.226, -21.465, 10.574, 18.193, 7.399, 59.341],
    [31.0, -48.767, -56.337, 45.250, 7.106, 7.253, 59.316],
    [32.0, -9.304, -66.447, 55.263, 12.088, 7.448, 59.365],
    [33.0, 1.490, -66.398, 55.263, 42.076, 7.399, 59.365],
    [34.0, 1.050, -66.447, 55.263, 48.620, 7.399, 59.365],
    [34.7, 1.050, -66.447, 55.263, 48.620, 7.350, 59.365],
]


def now_msg(node):
    stamp = node.get_clock().now().to_msg()
    return Time(sec=stamp.sec, nanosec=stamp.nanosec)


class Workcell:
    """설비 한 대. 맡은 자리 이름으로 불린다."""

    def __init__(self, node, robot_id, namespace, model, dispensers, ingestors,
                 deployed_policies):
        self.node = node
        self.robot_id = robot_id
        self.namespace = namespace
        self.model = model
        self.dispensers = dispensers
        self.ingestors = ingestors
        self.deployed_policies = set(deployed_policies)
        self.busy = False
        self.active_request = None
        self.completed_requests = set()
        self.lock = threading.Lock()
        self.arm = node.create_publisher(
            JointTrajectory, f'/{namespace}/arm_controller/joint_trajectory', 10)

    def serves(self, guid):
        return guid in self.dispensers or guid in self.ingestors

    def run_policy(self, policy_id, seconds):
        """선택한 가상 policy의 관절 궤적 전체를 한 번에 보낸다."""
        message = JointTrajectory()
        message.joint_names = list(JOINT_NAMES)
        poses = [*POLICY_MOTIONS[policy_id], HOME_POSE]
        for index, pose in enumerate(poses, start=1):
            point = JointTrajectoryPoint()
            point.positions = list(pose)
            at = seconds * index / len(poses)
            point.time_from_start.sec = int(at)
            point.time_from_start.nanosec = int((at % 1) * 1e9)
            message.points.append(point)
        self.arm.publish(message)

    def run_deployed_policy_test(self, policy_id, seconds):
        """배포 policy의 추론기 연결 전, 모델별 안전 시험 궤적을 보낸다."""
        profile = MODEL_TEST_MOTIONS[self.model]
        message = JointTrajectory()
        message.joint_names = list(profile['joints'])
        poses = [*profile['poses'], profile['home']]
        for index, pose in enumerate(poses, start=1):
            point = JointTrajectoryPoint()
            point.positions = list(pose)
            at = seconds * index / len(poses)
            point.time_from_start.sec = int(at)
            point.time_from_start.nanosec = int((at % 1) * 1e9)
            message.points.append(point)
        self.node.get_logger().warning(
            f'[{self.robot_id}] [{policy_id}] ACT 추론 전 controller 시험 동작')
        self.arm.publish(message)

    def run_sandwich_replay(self, policy_id):
        """학습 episode의 샌드위치 집기 시연을 Gazebo에서 관절 재생한다."""
        message = JointTrajectory()
        message.joint_names = list(MODEL_TEST_MOTIONS['omx_f']['joints'])
        lead_in = 1.0
        for row in SANDWICH_REPLAY_DEG:
            point = JointTrajectoryPoint()
            point.positions = [math.radians(value) for value in row[1:]]
            at = lead_in + row[0]
            point.time_from_start.sec = int(at)
            point.time_from_start.nanosec = int((at % 1) * 1e9)
            message.points.append(point)
        self.node.get_logger().info(
            f'[{self.robot_id}] [{policy_id}] 학습 episode 0 샌드위치 동작 재생')
        self.arm.publish(message)
        return lead_in + SANDWICH_REPLAY_DEG[-1][0]


class WorkcellAdapter(rclpy.node.Node):

    def __init__(self):
        super().__init__('${nodeName}')

        # RMF 는 상태를 **transient local** 로 듣는다. 늦게 뜬 쪽도 마지막
        # 상태를 받아야 워크셀이 있다는 것을 알기 때문이다.
        state_qos = QoSProfile(
            depth=10,
            reliability=QoSReliabilityPolicy.RELIABLE,
            durability=QoSDurabilityPolicy.TRANSIENT_LOCAL,
        )
        self.dispenser_states = self.create_publisher(
            DispenserState, '/dispenser_states', state_qos)
        self.ingestor_states = self.create_publisher(
            IngestorState, '/ingestor_states', state_qos)
        self.dispenser_results = self.create_publisher(
            DispenserResult, '/dispenser_results', 10)
        self.ingestor_results = self.create_publisher(
            IngestorResult, '/ingestor_results', 10)

        self.cells = [
            Workcell(self, robot_id, namespace, model, dispensers, ingestors, policies)
            for robot_id, namespace, model, dispensers, ingestors, policies in WORKCELLS
        ]

        # Fleet adapter의 요청은 transient local이다. 워크셀이 늦게 떠도 이미
        # 보낸 픽업 요청을 받아야 하므로 같은 QoS로 구독한다.
        self.create_subscription(
            DispenserRequest, '/dispenser_requests',
            lambda msg: self.on_request(msg, dispenser=True), state_qos)
        self.create_subscription(
            IngestorRequest, '/ingestor_requests',
            lambda msg: self.on_request(msg, dispenser=False), state_qos)

        # 상태를 안 내면 RMF 가 이 워크셀을 없는 것으로 보고 요청조차 안 한다.
        self.create_timer(1.0, self.publish_states)

        served = sum(len(c.dispensers) + len(c.ingestors) for c in self.cells)
        self.get_logger().info(
            f'워크셀 {len(self.cells)}대, 맡은 자리 {served}곳을 RMF 에 이었습니다.')

    def publish_states(self):
        for cell in self.cells:
            mode = DispenserState.BUSY if cell.busy else DispenserState.IDLE
            for guid in cell.dispensers:
                self.dispenser_states.publish(DispenserState(
                    time=now_msg(self), guid=guid, mode=mode,
                    request_guid_queue=[], seconds_remaining=0.0))
            for guid in cell.ingestors:
                self.ingestor_states.publish(IngestorState(
                    time=now_msg(self), guid=guid, mode=mode,
                    request_guid_queue=[], seconds_remaining=0.0))

    # `handle` 이라고 부르면 안 된다. rclpy 의 Node 가 같은 이름의 속성을
    # 쓰는데, 메서드로 덮으면 Node.__init__ 이 `with self.handle:` 에서
    # TypeError 로 죽는다 — 노드가 아예 안 뜬다.
    def on_request(self, msg, dispenser):
        cell = next((c for c in self.cells if c.serves(msg.target_guid)), None)
        if cell is None:
            # 우리 것이 아니다. 남의 워크셀 요청일 수 있으므로 조용히 넘긴다.
            return

        # 같은 요청은 답을 받을 때까지 반복된다. 같은 GUID로 팔을 두 번
        # 움직이지 않고, 현재 상태만 다시 답한다.
        with cell.lock:
            if msg.request_guid in cell.completed_requests:
                repeated_status = DispenserResult.SUCCESS
            elif cell.active_request == msg.request_guid:
                repeated_status = DispenserResult.ACKNOWLEDGED
            else:
                repeated_status = None
            if repeated_status is not None:
                pass
            elif cell.busy:
                return
            else:
                cell.busy = True
                cell.active_request = msg.request_guid
        if repeated_status is not None:
            self.answer(msg, dispenser, repeated_status)
            return

        self.get_logger().info(
            f'[{cell.robot_id}] {msg.target_guid} 요청 받음 '
            f'({msg.request_guid})')
        self.answer(msg, dispenser, DispenserResult.ACKNOWLEDGED)

        policy_id = msg.items[0].type_guid if msg.items else 'policy_1'
        is_deployed = policy_id in cell.deployed_policies
        if (policy_id != 'armLoad' and policy_id not in POLICY_MOTIONS
                and not is_deployed):
            self.get_logger().error(
                f'[{cell.robot_id}] 알 수 없는 물품 policy [{policy_id}]')
            with cell.lock:
                cell.busy = False
                cell.active_request = None
            self.answer(msg, dispenser, DispenserResult.FAILED)
            return
        execution_seconds = ACTION_SECONDS
        replay_name = policy_id.split('@', 1)[0].lower()
        if (is_deployed and cell.model == 'omx_f'
                and replay_name in ('sandwich', 'sandwitch')):
            execution_seconds = cell.run_sandwich_replay(policy_id)
        elif is_deployed:
            cell.run_deployed_policy_test(policy_id, ACTION_SECONDS)
        elif policy_id == 'armLoad':
            # Mock 또는 별도 policy가 없는 실설비의 기본 적재 동작. RMF 요청은
            # 정상 완료하되 존재하지 않는 관절 policy를 억지로 실행하지 않는다.
            self.get_logger().info(
                f'[{cell.robot_id}] 기본 armLoad 실행 (등록 policy 없음)')
        else:
            self.get_logger().info(
                f'[{cell.robot_id}] 물품 [{policy_id}] 가상 policy 실행')
            cell.run_policy(policy_id, ACTION_SECONDS)

        def finish():
            timer.cancel()
            with cell.lock:
                cell.busy = False
                cell.active_request = None
                cell.completed_requests.add(msg.request_guid)
            self.get_logger().info(f'[{cell.robot_id}] {msg.target_guid} 끝.')
            self.answer(msg, dispenser, DispenserResult.SUCCESS)

        timer = self.create_timer(execution_seconds + ARM_SETTLE_SECONDS, finish)

    def answer(self, msg, dispenser, status):
        if dispenser:
            self.dispenser_results.publish(DispenserResult(
                time=now_msg(self), request_guid=msg.request_guid,
                source_guid=msg.target_guid, status=status))
        else:
            self.ingestor_results.publish(IngestorResult(
                time=now_msg(self), request_guid=msg.request_guid,
                source_guid=msg.target_guid, status=status))


def main(argv=sys.argv):
    rclpy.init(args=argv)
    node = WorkcellAdapter()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    node.destroy_node()
    if rclpy.ok():
        rclpy.shutdown()


if __name__ == '__main__':
    main()
''';
}

/// 파이썬 문자열 목록 리터럴.
String _pyList(List<String> values) =>
    '[${values.map((value) => "'$value'").join(', ')}]';
