/// 웹 빌드용 대체 구현. 브라우저에서는 `ros2` 를 실행할 수 없다.
library;

import 'dart:async';

import 'rmf_project_config.dart';
import 'robot_telemetry_models.dart';

class RobotTelemetryBridge {
  RobotTelemetryBridge._();

  static final RobotTelemetryBridge instance = RobotTelemetryBridge._();

  Stream<RobotTelemetryStatus> get updates => const Stream.empty();

  Set<String> get attachedRobotIds => const {};

  bool get subscribing => false;

  Map<String, RobotPose> get poses => const {};

  RobotTelemetryStatus get status => RobotTelemetryStatus.idle;

  Future<void> sync(Iterable<RmfProjectRobot> robots) async {}

  Future<void> stop() async {}
}
