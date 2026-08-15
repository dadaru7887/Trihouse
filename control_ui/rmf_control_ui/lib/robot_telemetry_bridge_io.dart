/// Gazebo 가 내는 위치 토픽을 앱으로 끌어온다.
///
/// 지금까지 화면의 숫자는 전부 앱이 계산한 것이었다. 출처를 Gazebo 로 골라도
/// 값은 여전히 앱 것이어서 작업 상세의 띠가 그 사실을 경고로 알렸다.
///
/// 앱에 rclpy·rclcpp 바인딩이 없으므로 `ros2 topic echo` 를 자식 프로세스로
/// 띄워 읽는다. MySQL 도 `mysql` 클라이언트를 부르고 노드 확인도 `ros2 node
/// list` 를 부르는 것과 같은 방식이다.
///
/// `--field pose.pose --csv` 는 `x,y,z,qx,qy,qz,qw` 일곱 개만 한 줄로 낸다.
/// 전체 Odometry 를 YAML 로 받아 파싱하는 것보다 훨씬 싸다.
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'rmf_project_config.dart';
import 'rmf_runtime_models.dart';
import 'robot_telemetry_models.dart';
import 'workspace_paths_io.dart';

/// ROS 환경을 읽어 들인 뒤 [command] 를 실행하는 셸 한 줄.
///
/// 앱은 보통 ROS 를 source 하지 않은 셸에서 실행된다. 그대로 `ros2` 를 부르면
/// 명령을 찾지 못한다.
String _withRosEnvironment(String command) {
  final rosSetup =
      Platform.environment['ROS_SETUP'] ?? '/opt/ros/jazzy/setup.bash';
  final workspace = bundledRmfWorkspace();
  return 'set +u; '
      '[ -f "$rosSetup" ] && . "$rosSetup"; '
      '[ -f "$workspace/install/setup.bash" ] && . "$workspace/install/setup.bash"; '
      '$command';
}

/// 이 로봇에서 살아 있는지 확인할 토픽.
///
/// 이동 로봇은 `/odom` 이다. 설치 로봇은 바퀴가 없어 `/odom` 이 아예 없다 —
/// 그런데도 `/odom` 을 읽으러 가서, 등록도 Gazebo 도 멀쩡한 OpenMANIPULATOR 가
/// 앱에서는 영영 Mock 으로만 보였다. 팔이 내는 것은 관절 상태다.
String _liveTopicFor(RmfProjectRobot robot) =>
    robot.isMobile ? '/${robot.gzName}/odom' : '/${robot.gzName}/joint_states';

/// 로봇 한 대의 위치 토픽을 읽는 자식 프로세스.
class _RobotFeed {
  _RobotFeed({
    required this.robotId,
    required this.topic,
    this.spawnX,
    this.spawnY,
    this.spawnHeading = 0,
  });

  final String robotId;
  final String topic;

  /// 로봇을 올린 자리. odom 의 원점이라서 월드 좌표로 옮길 때 필요하다.
  final double? spawnX;
  final double? spawnY;
  final double spawnHeading;
  Process? process;
  StreamSubscription<String>? lines;
  RobotPose? pose;

  /// 프로세스가 낸 마지막 오류. 토픽이 없으면 여기 남는다.
  String? error;

  Future<void> close() async {
    await lines?.cancel();
    lines = null;
    // 셸을 `exec` 로 띄웠으므로 이 pid 가 곧 `ros2` 프로세스다. 그룹을 따로
    // 끊을 것이 없다.
    final target = process;
    process = null;
    if (target == null) return;
    target.kill(ProcessSignal.sigint);
    // 곧바로 안 죽으면 한 번 더. 남겨 두면 다음 실행에서 같은 토픽을 두 번
    // 읽는다.
    unawaited(
      target.exitCode.timeout(
        const Duration(seconds: 3),
        onTimeout: () {
          target.kill(ProcessSignal.sigterm);
          return -1;
        },
      ),
    );
  }
}

/// 등록된 Gazebo 로봇의 위치를 계속 받아 둔다.
///
/// 화면 여러 곳이 같은 값을 봐야 하므로 앱에 하나만 둔다.
class RobotTelemetryBridge {
  RobotTelemetryBridge._();

  static final RobotTelemetryBridge instance = RobotTelemetryBridge._();

  final Map<String, _RobotFeed> _feeds = {};

  /// 죽은 구독을 다시 띄우는 시계.
  ///
  /// 백엔드는 앱과 따로 오르내린다. 사람이 다시 붙여 주기를 기다리면 그동안
  /// 화면은 조용한데 왜 조용한지 알 수 없다.
  Timer? _healer;

  /// 다시 붙일 로봇. 마지막으로 [sync] 에 들어온 것을 기억해 둔다.
  final Map<String, RmfProjectRobot> _wanted = {};
  final StreamController<RobotTelemetryStatus> _controller =
      StreamController<RobotTelemetryStatus>.broadcast();

  /// 값이 바뀔 때마다 흘러나온다. 화면이 이것을 듣고 다시 그린다.
  Stream<RobotTelemetryStatus> get updates => _controller.stream;

  bool get subscribing => _wanted.isNotEmpty;

  /// `/fleet_states` 를 읽는 프로세스. RMF 가 아는 map 좌표가 여기서 온다.
  Process? _fleetProcess;
  StreamSubscription<String>? _fleetLines;

  /// RMF 가 알려 준 로봇 자세. odom 으로 계산한 것보다 이쪽이 옳다.
  final Map<String, RobotPose> _fleetPoses = {};

  /// 지금까지 받은 자세.
  ///
  /// **RMF 가 아는 자리를 먼저 쓴다.** odom 은 로봇을 올린 자리를 원점으로
  /// 삼고 거기서 바퀴 회전을 더해 나가는 값이라, AMCL 이 보정을 시작하면
  /// 실제와 벌어진다. 실제로 복구 회전이 되풀이되며 `map→odom` 이 46도까지
  /// 틀어져, 앱 화면과 RViz 의 로봇 위치가 1m 넘게 달랐다.
  ///
  /// RMF 에 안 붙은 로봇은 여전히 odom 으로 그린다 — 틀릴 수 있어도 아무것도
  /// 안 그리는 것보다는 낫다.
  Map<String, RobotPose> get poses => {
    for (final feed in _feeds.values)
      if (feed.pose != null) feed.robotId: feed.pose!,
    ..._fleetPoses,
  };

  /// 마지막 `/fleet_states` 메시지에 실제로 들어 있던 RMF 로봇 ID.
  Set<String> get attachedRobotIds => _fleetPoses.keys.toSet();

  RobotTelemetryStatus get status {
    if (_wanted.isEmpty) return RobotTelemetryStatus.idle;
    final live = _wanted.keys.where(poses.containsKey).length;
    return RobotTelemetryStatus(
      subscribing: true,
      poses: poses,
      message: '$live/${_wanted.length}대에서 위치를 받고 있습니다.',
    );
  }

  /// [robots] 중 Gazebo 로 돌리는 것만 구독한다.
  ///
  /// 이미 붙어 있는 것은 그대로 두고, 빠진 것만 끊고 새로 생긴 것만 붙인다.
  /// 매번 전부 다시 띄우면 화면이 잠깐씩 빈다.
  Future<void> sync(Iterable<RmfProjectRobot> robots) async {
    final wanted = {
      for (final robot in robots)
        if (robot.runsInGazebo) robot.robotId: robot,
    };
    // 위치는 플릿 전체가 담긴 /fleet_states 하나에서 읽는다. 예전에는 로봇마다
    // `ros2 topic echo`를 하나씩 띄워 DDS 그래프를 N번 돌렸고, 등록 대수만큼
    // CPU 사용량이 늘었다. 설치 로봇은 움직이지 않으므로 등록된 자리를 쓴다.
    for (final feed in _feeds.values.toList()) {
      await feed.close();
    }
    _feeds.clear();
    for (final entry in wanted.entries) {
      final robot = entry.value;
      if (robot.isMobile) continue;
      _feeds[entry.key] =
          _RobotFeed(
              robotId: entry.key,
              topic: _liveTopicFor(robot),
              spawnX: robot.spawnX,
              spawnY: robot.spawnY,
              spawnHeading: robot.spawnHeading,
            )
            ..pose = RobotPose(
              x: robot.spawnX ?? 0,
              y: robot.spawnY ?? 0,
              heading: robot.spawnHeading,
              at: DateTime.now(),
            );
    }
    _wanted
      ..clear()
      ..addAll(wanted);
    await _openFleetStates();
    _startHealer();
    _controller.add(status);
  }

  /// RMF 가 내는 `/fleet_states` 를 읽기 시작한다. 이미 읽고 있으면 둔다.
  ///
  /// 로봇마다 하나씩이 아니라 **하나만** 띄운다. 한 토픽에 플릿 전체가 담겨
  /// 있어서 그것으로 충분하다.
  Future<void> _openFleetStates() async {
    if (_fleetProcess != null) return;
    if (_wanted.isEmpty) return;
    if (Platform.environment.containsKey('FLUTTER_TEST')) return;
    try {
      final process = await Process.start('bash', [
        '-lc',
        _withRosEnvironment('exec ros2 topic echo /fleet_states'),
      ]);
      _fleetProcess = process;
      // 메시지 하나가 여러 줄이다. `---` 가 나올 때까지 모았다가 한 번에 푼다.
      final block = StringBuffer();
      _fleetLines = process.stdout
          .transform(utf8.decoder)
          .transform(const LineSplitter())
          .listen((line) {
            if (!line.startsWith('---')) {
              block.writeln(line);
              return;
            }
            final parsed = parseFleetStatePoses(block.toString());
            block.clear();
            if (parsed.isEmpty) return;
            final at = DateTime.now();
            for (final entry in parsed.entries) {
              _fleetPoses[entry.key] = RobotPose(
                x: entry.value.x,
                y: entry.value.y,
                heading: entry.value.yaw,
                at: at,
              );
            }
            _controller.add(status);
          });
      unawaited(
        process.exitCode.then((_) {
          if (_fleetProcess != process) return;
          _fleetProcess = null;
          // 값을 지운다. 남겨 두면 백엔드가 내려간 뒤에도 마지막 자리에
          // 로봇이 서 있는 것처럼 보인다.
          _fleetPoses.clear();
          _controller.add(status);
        }),
      );
    } catch (_) {
      // 토픽이 아직 없을 수 있다. 다음 sync 나 healer 가 다시 부른다.
      _fleetProcess = null;
    }
  }

  /// 5초마다 죽은 구독을 다시 띄운다.
  ///
  /// 붙을 것이 없으면 시계도 멈춘다. 살려 둘 이유가 없다.
  void _startHealer() {
    if (_wanted.isEmpty) {
      _healer?.cancel();
      _healer = null;
      return;
    }
    _healer ??= Timer.periodic(const Duration(seconds: 5), (_) async {
      // RMF 쪽 읽기도 함께 되살린다. 이것이 끊기면 화면의 위치가 조용히
      // odom 으로 되돌아가, 맞던 자리가 다시 어긋나기 시작한다.
      await _openFleetStates();
      _controller.add(status);
    });
  }

  /// 전부 끊는다. 앱을 닫거나 프로젝트를 바꿀 때 부른다.
  Future<void> stop() async {
    _healer?.cancel();
    _healer = null;
    _wanted.clear();
    await _fleetLines?.cancel();
    _fleetLines = null;
    _fleetProcess?.kill(ProcessSignal.sigint);
    _fleetProcess = null;
    _fleetPoses.clear();
    for (final feed in _feeds.values.toList()) {
      await feed.close();
    }
    _feeds.clear();
    _controller.add(RobotTelemetryStatus.idle);
  }
}
