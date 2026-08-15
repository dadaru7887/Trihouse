/// 고리가 이어져 있는지 실제로 물어보고, 끊긴 고리를 잇는다.
///
/// 앱에 ROS 바인딩이 없으므로 여기서도 `ros2` 를 자식 프로세스로 부른다.
/// 위치를 읽는 다리, 작업을 넣는 다리와 같은 방식이다.
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'workspace_paths_io.dart';

export 'robot_link_check.dart';

String _withRosEnvironment(String command) {
  final rosSetup =
      Platform.environment['ROS_SETUP'] ?? '/opt/ros/jazzy/setup.bash';
  final workspace = bundledRmfWorkspace();
  return 'set +u; '
      '[ -f "$rosSetup" ] && . "$rosSetup"; '
      '[ -f "$workspace/install/setup.bash" ] && . "$workspace/install/setup.bash"; '
      '$command';
}

/// 셸에 넘길 조각 하나. 로봇 ID 도 맵 이름도 사람이 타자로 친다.
String _quote(String value) => "'${value.replaceAll("'", r"'\''")}'";

/// ROS 그래프에서 읽어 온 것.
class RobotLinkProbe {
  const RobotLinkProbe({
    required this.nodesUp,
    required this.topicSeen,
    required this.topicFlowing,
  });

  /// 아무것도 못 물어봤을 때. 모르는 것은 모른다고 한다.
  static const RobotLinkProbe unknown = RobotLinkProbe(
    nodesUp: null,
    topicSeen: null,
    topicFlowing: null,
  );

  final bool? nodesUp;
  final bool? topicSeen;
  final bool? topicFlowing;
}

/// 이 로봇의 고리를 ROS 에 물어본다.
///
/// 세 가지를 따로 본다 — 노드가 떴는지, 토픽 **이름**이 있는지, 그 이름에
/// **값**이 흐르는지. 이름이 있는 것과 값이 오는 것은 다르다. 다리는 월드에
/// 모델이 없어도 토픽을 만들어 놓으므로, 이름만 보고 판단하면 늘 이어져 있는
/// 것처럼 보인다.
Future<RobotLinkProbe> probeRobotLinks({
  required String namespace,
  Duration flowTimeout = const Duration(seconds: 4),
}) async {
  // 위젯 테스트에서는 ROS 에 묻지 않는다. 판정 규칙은 robot_link_check 에서
  // 따로 확인한다.
  if (Platform.environment.containsKey('FLUTTER_TEST')) {
    return RobotLinkProbe.unknown;
  }
  bool? nodesUp;
  bool? topicSeen;
  bool? topicFlowing;
  try {
    final graph = await Process.run('bash', [
      '-lc',
      _withRosEnvironment('ros2 node list; echo "---"; ros2 topic list'),
    ]).timeout(const Duration(seconds: 12));
    final text = '${graph.stdout}';
    if (text.trim().isNotEmpty) {
      final parts = text.split('---');
      final nodes = parts.first;
      final topics = parts.length > 1 ? parts[1] : '';
      // 이 로봇을 **올린** 노드를 찾는다. 네임스페이스만 보면 안 된다 —
      // Nav2 도 같은 네임스페이스에 노드를 둔다(`/pinky_01/amcl` 따위). Nav2 는
      // 따로 뜨는 launch 라 Gazebo 가 죽어도 혼자 살아남으므로, 네임스페이스로
      // 세면 월드에 없는 로봇도 "노드가 떠 있다"가 된다. 실제로 그랬다.
      //
      // robot_state_publisher 는 spawn.launch.xml 이 띄운다. 이동 로봇이든
      // 설치 로봇이든 마찬가지다. 이것이 있으면 그 launch 가 돌았다는 뜻이다.
      nodesUp = nodes
          .split('\n')
          .map((line) => line.trim())
          .contains('/$namespace/robot_state_publisher');
      topicSeen = topics
          .split('\n')
          .map((line) => line.trim())
          .contains('/$namespace/odom');
    }
  } catch (_) {
    // 못 물어봤으면 null 그대로 둔다.
  }
  if (topicSeen != true) {
    return RobotLinkProbe(
      nodesUp: nodesUp,
      topicSeen: topicSeen,
      topicFlowing: topicSeen == false ? false : null,
    );
  }
  try {
    // 한 줄만 받으면 된다. 값이 흐르는지만 보는 것이라 오래 붙들 이유가 없다.
    final seconds = flowTimeout.inMilliseconds / 1000;
    final echo = await Process.run('bash', [
      '-lc',
      _withRosEnvironment(
        'timeout $seconds ros2 topic echo /$namespace/odom '
        '--field pose.pose.position.x --once',
      ),
    ]).timeout(flowTimeout + const Duration(seconds: 3));
    topicFlowing = '${echo.stdout}'.trim().isNotEmpty;
  } catch (_) {
    topicFlowing = null;
  }
  return RobotLinkProbe(
    nodesUp: nodesUp,
    topicSeen: topicSeen,
    topicFlowing: topicFlowing,
  );
}

/// 버튼을 눌렀을 때의 결과.
class RobotLinkFixResult {
  const RobotLinkFixResult({required this.ok, required this.message});

  final bool ok;
  final String message;
}

/// 이 로봇만 월드에 올린다.
///
/// **월드가 이미 떠 있어야 한다.** 없으면 `create` 가 월드 이름을 영영
/// 기다린다 — 오류도 안 내고 그냥 멈춰 있다. 그래서 진단이 Gazebo 고리를
/// 통과했을 때만 이 버튼이 나온다.
Future<RobotLinkFixResult> spawnSingleRobot({
  required String mapDirectory,
  required String robotDirectory,
}) => _launch(
  '$mapDirectory/$robotDirectory/spawn.launch.xml',
  missing:
      '이 로봇의 spawn.launch.xml 이 없습니다.\n'
      '맵 관리에서 RMF 설정 내보내기를 먼저 하세요.',
  started: '이 로봇만 올렸습니다. 잠시 뒤 다시 확인해 주세요.',
);

/// 이 로봇 몫 토픽 다리만 띄운다.
Future<RobotLinkFixResult> startSingleRobotBridge({
  required String mapDirectory,
  required String robotDirectory,
}) async {
  final config = File('$mapDirectory/$robotDirectory/bridge.yaml');
  if (!config.existsSync()) {
    return RobotLinkFixResult(
      ok: false,
      message:
          '${config.path} 가 없습니다.\n'
          '맵 관리에서 RMF 설정 내보내기를 먼저 하세요.',
    );
  }
  return _run(
    'ros2 run ros_gz_bridge parameter_bridge '
    '--ros-args -p config_file:=${_quote(config.path)}',
    started: '이 로봇의 다리를 띄웠습니다. 잠시 뒤 다시 확인해 주세요.',
  );
}

Future<RobotLinkFixResult> _launch(
  String path, {
  required String missing,
  required String started,
}) async {
  if (!File(path).existsSync()) {
    return RobotLinkFixResult(ok: false, message: missing);
  }
  return _run('ros2 launch ${_quote(path)}', started: started);
}

/// 백그라운드로 띄우고 곧바로 돌아온다.
///
/// 이 프로세스들은 앱보다 오래 살아야 한다. 앱을 닫아도 로봇은 떠 있어야
/// 하므로 `setsid` 로 떼어 놓는다. 정리는 프로젝트 중지 스크립트가 한다.
Future<RobotLinkFixResult> _run(
  String command, {
  required String started,
}) async {
  try {
    final process = await Process.start('bash', [
      '-lc',
      _withRosEnvironment(
        'setsid $command > /dev/null 2>&1 < /dev/null & echo \$!',
      ),
    ]);
    final pid = await process.stdout
        .transform(utf8.decoder)
        .transform(const LineSplitter())
        .firstWhere((line) => line.trim().isNotEmpty, orElse: () => '')
        .timeout(const Duration(seconds: 8), onTimeout: () => '');
    if (pid.trim().isEmpty) {
      return const RobotLinkFixResult(
        ok: false,
        message: '띄우지 못했습니다. ROS 환경을 확인하세요.',
      );
    }
    return RobotLinkFixResult(
      ok: true,
      message: '$started (pid ${pid.trim()})',
    );
  } catch (error) {
    return RobotLinkFixResult(ok: false, message: '$error');
  }
}

/// 배포된 bringup 이 로봇을 몇 대 담고 있는가. 파일이 없으면 null.
///
/// 로봇 등록은 앱 안(프로젝트 저장소)에만 남는다. `RMF 설정 내보내기` 를 눌러야
/// 디스크의 launch 파일이 바뀐다. 이 둘이 어긋난 채 백엔드를 띄우면 옛날 로봇
/// 목록으로 월드가 뜬다 — `ros2 launch` 는 띄울 때 한 번만 파일을 읽기 때문이다.
/// 오류는 안 난다. 다리가 토픽 이름은 만들어 두므로 목록에는 나오고 값만 안 온다.
///
/// bringup 이 `<include ... spawn.launch.xml>` 을 몇 줄 담고 있는지 센다. 그것이
/// 곧 지금 월드에 올라갈 로봇 수다.
Future<int?> deployedSpawnCount({
  required String mapDirectory,
  required String mapName,
}) async {
  if (Platform.environment.containsKey('FLUTTER_TEST')) return null;
  final file = File('$mapDirectory/${mapName}_bringup.launch.xml');
  if (!file.existsSync()) return null;
  try {
    return RegExp(
      r'spawn\.launch\.xml',
    ).allMatches(await file.readAsString()).length;
  } catch (_) {
    return null;
  }
}

/// 지금 도는 백엔드가 언제 떴는지, 배포는 언제였는지.
class ProjectBackendAge {
  const ProjectBackendAge({this.startedAt, this.deployedAt});

  /// 백엔드가 뜬 시각. 안 떠 있으면 null.
  final DateTime? startedAt;

  /// 마지막 배포 시각. 산출물이 없으면 null.
  final DateTime? deployedAt;

  /// 배포가 백엔드보다 나중인가.
  ///
  /// `ros2 launch` 는 파일을 띄울 때 한 번만 읽는다. 나중에 배포해도 이미 뜬
  /// 월드에는 안 들어간다. 실제로 로봇 0대이던 시절의 Gazebo 가 34분째 돌고
  /// 있었고, 그동안 토픽 이름만 있고 값은 하나도 안 왔다.
  bool get stale =>
      startedAt != null &&
      deployedAt != null &&
      deployedAt!.isAfter(startedAt!);
}

/// 백엔드가 뜬 시각과 마지막 배포 시각을 견준다.
Future<ProjectBackendAge> readBackendAge({
  required String mapDirectory,
  required String mapName,
}) async {
  if (Platform.environment.containsKey('FLUTTER_TEST')) {
    return const ProjectBackendAge();
  }
  DateTime? deployedAt;
  // bringup 이 로봇 목록을 담는다. 이것이 바뀌었으면 다시 띄워야 한다.
  final bringup = File('$mapDirectory/${mapName}_bringup.launch.xml');
  if (bringup.existsSync()) deployedAt = bringup.lastModifiedSync();

  DateTime? startedAt;
  try {
    // 가장 오래 산 것이 그 판을 띄운 프로세스다.
    final found = await Process.run('bash', [
      '-lc',
      _withRosEnvironment(
        'pgrep -u "\$(id -u)" -f ${_quote(mapDirectory)} '
        "| xargs -r ps -o etimes= -p 2>/dev/null | sort -rn | head -1",
      ),
    ]).timeout(const Duration(seconds: 10));
    final seconds = int.tryParse('${found.stdout}'.trim());
    if (seconds != null && seconds > 0) {
      startedAt = DateTime.now().subtract(Duration(seconds: seconds));
    }
  } catch (_) {
    // 못 물어봤으면 모르는 채로 둔다.
  }
  return ProjectBackendAge(startedAt: startedAt, deployedAt: deployedAt);
}
