import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('시뮬레이션 작업 취소는 UI를 먼저 끝내고 최초 위치로 되돌린다', () {
    final source = File('lib/main.dart').readAsStringSync();
    final cancel = source.indexOf('Future<void> _cancelMockTask');
    final realRobotPath = source.indexOf('// RMF 를 먼저 세운다.', cancel);
    final immediate = source.substring(cancel, realRobotPath);

    expect(immediate, contains('immediateSimulation'));
    expect(immediate, contains('_MockTaskStatus.cancelled'));
    expect(immediate, contains('robot.position = initial'));
    expect(immediate, contains('resetGazeboRobotPose('));
    expect(immediate, contains('rosDomainId: _rosDomainId'));
    expect(immediate, contains('unawaited('));
    expect(immediate, contains('작업 최초 위치로 되돌렸습니다'));
  });

  test('Gazebo 복귀와 함께 AMCL initialpose도 갱신한다', () {
    final source = File('lib/gazebo_robot_reset_io.dart').readAsStringSync();

    expect(source, contains(r"'/$modelName/initialpose'"));
    expect(source, contains('PoseWithCovarianceStamped'));
    expect(source, contains(r"'ROS_DOMAIN_ID': '$rosDomainId'"));
    expect(source, contains('if (!moved) return false'));
  });

  test('상단 원위치는 모든 작업을 중지하고 작업맵과 Gazebo를 함께 되돌린다', () {
    final source = File('lib/main.dart').readAsStringSync();
    final start = source.indexOf('Future<void> _returnRobotsToSpawn()');
    final end = source.indexOf('Map<Offset, String> get _homeWaypoints', start);
    final method = source.substring(start, end);

    expect(method, contains('_MockTaskStatus.active'));
    expect(method, contains('_MockTaskStatus.queued'));
    expect(method, contains('_MockTaskStatus.cancelled'));
    expect(method, contains('buildCancelTaskRequest(taskId)'));
    expect(method, contains('..position = robot.spawnPosition'));
    expect(method, contains('resetGazeboRobotPose('));
    expect(method, contains('yaw: registered.spawnHeading'));
    expect(method, isNot(contains('_startQueuedOrderTasks()')));
  });
}
