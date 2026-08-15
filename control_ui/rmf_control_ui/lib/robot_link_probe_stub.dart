/// 웹 빌드용 대체 구현. 브라우저에서는 `ros2` 를 실행할 수 없다.
library;

export 'robot_link_check.dart';

class RobotLinkProbe {
  const RobotLinkProbe({
    required this.nodesUp,
    required this.topicSeen,
    required this.topicFlowing,
  });

  static const RobotLinkProbe unknown = RobotLinkProbe(
    nodesUp: null,
    topicSeen: null,
    topicFlowing: null,
  );

  final bool? nodesUp;
  final bool? topicSeen;
  final bool? topicFlowing;
}

Future<RobotLinkProbe> probeRobotLinks({
  required String namespace,
  Duration flowTimeout = const Duration(seconds: 4),
}) async => RobotLinkProbe.unknown;

class RobotLinkFixResult {
  const RobotLinkFixResult({required this.ok, required this.message});

  final bool ok;
  final String message;
}

Future<RobotLinkFixResult> spawnSingleRobot({
  required String mapDirectory,
  required String robotDirectory,
}) async => const RobotLinkFixResult(ok: false, message: '웹에서는 로봇을 띄울 수 없습니다.');

Future<RobotLinkFixResult> startSingleRobotBridge({
  required String mapDirectory,
  required String robotDirectory,
}) async => const RobotLinkFixResult(ok: false, message: '웹에서는 다리를 띄울 수 없습니다.');

Future<int?> deployedSpawnCount({
  required String mapDirectory,
  required String mapName,
}) async => null;

class ProjectBackendAge {
  const ProjectBackendAge({this.startedAt, this.deployedAt});

  final DateTime? startedAt;
  final DateTime? deployedAt;

  bool get stale => false;
}

Future<ProjectBackendAge> readBackendAge({
  required String mapDirectory,
  required String mapName,
}) async => const ProjectBackendAge();
