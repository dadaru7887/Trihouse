import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/rmf_project_config.dart';

void main() {
  test('Spawn에서 고른 위치를 등록 정보에 저장하고 재배포를 요구한다', () {
    final source = File('lib/main.dart').readAsStringSync();
    final spawn = source.indexOf('Future<void> _spawnMockRobot()');
    final end = source.indexOf('void _toggleMockRobot', spawn);
    final body = source.substring(spawn, end);

    expect(body, contains('_rmfMetersFromPixel(result.position)'));
    expect(body, contains('spawnedRegistration.withSpawn('));
    expect(body, contains("label: '로봇 시작 위치'"));
    expect(body, contains('_isDeployed = false'));
    expect(body, contains('다시 배포하고 백엔드를 재시작하세요.'));
  });

  test('충전1로 복귀하더라도 Gazebo는 대기4 좌표에서 시작한다', () {
    const robot = RmfProjectRobot(
      robotId: 'pinky_01',
      displayName: '핑키 1호',
      model: 'PINKY-GZ',
      gzName: 'pinky_01',
      zones: ['ambient'],
      chargerWaypoint: '충전1',
      spawnX: 1.185,
      spawnY: -1.602,
      dataSource: RobotDataSource.gazebo,
    );

    final launch = buildRobotSpawnLaunchXml(robot);
    final info = buildRobotInfoYaml(robot);

    expect(launch, contains('-x 1.185 -y -1.602'));
    expect(info, contains('charger_waypoint: 충전1'));
    expect(info, contains('spawn_x: 1.185'));
    expect(info, contains('spawn_y: -1.602'));
  });
}
