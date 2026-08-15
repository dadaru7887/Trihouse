/// 웹 빌드용 대체 구현. 브라우저에서는 파일을 읽을 수 없다.
library;

import 'dart:async';

import 'robot_sensor_models.dart';

const String sensorDirectoryEnvironmentKey = 'ROBOSAPIENS_SENSOR_DIR';

String robotSensorDirectory() => '';

String sensorFileStem(String robotId) => robotId;

class RobotSensorFeed {
  RobotSensorFeed._();

  static final RobotSensorFeed instance = RobotSensorFeed._();

  Stream<Map<String, RobotSensors>> get updates =>
      const Stream<Map<String, RobotSensors>>.empty();

  Map<String, RobotSensors> get sensors => const {};

  RobotSensors sensorsOf(String robotId) => const RobotSensors();

  bool get watching => false;

  void watch(Iterable<String> robotIds, {Duration? interval}) {}

  void stop() {}
}
