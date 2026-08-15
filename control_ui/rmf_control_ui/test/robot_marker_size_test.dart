/// RViz 가 로봇을 실제 크기로 그리는지 지킨다.
///
/// `fleet_states_visualizer` 는 로봇을 지름 `2 × <플릿이름>_radius` 짜리
/// SPHERE 로 그린다. 그 값을 **플릿 설정에서 읽지 않는다.** 상류
/// `visualization.launch.xml` 이 rmf_demos 플릿 다섯 개만 적어 두었고 —
///
///   tinyRobot 0.3 · deliveryRobot 0.6 · cleanerBotA 1.0 · caddy 1.5
///
/// 목록에 없는 이름은 노드 기본값 **0.5m** 가 된다. 지름 1m 짜리 공이다.
///
/// 실제로 2.3m 짜리 도면에서 건물 절반을 덮는 자홍색 덩어리가 나왔다. 진짜
/// 핑키의 footprint 는 0.1m 다.
///
/// 실물 노드로 확인한 값 — 걸었을 때 `scale: 0.2`, 안 걸었을 때 `scale: 1.0`.
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/rmf_project_config.dart';

void main() {
  const pinky = RmfProjectRobot(
    robotId: 'PK_01',
    displayName: '핑키 1호',
    model: 'PINKY-GZ',
    gzName: 'pinky_01',
    zones: ['ambient'],
    chargerWaypoint: '충전1',
    dataSource: RobotDataSource.gazebo,
  );

  String launchXml({double footprintRadius = .1}) => buildProjectLaunchXml(
    mapName: 'project1',
    fleetName: 'project1_pinky',
    mapDirectory: '/maps/project1',
    buildingYamlName: 'project1.building.yaml',
    robots: const [pinky],
    footprintRadius: footprintRadius,
  );

  group('로봇 공의 크기', () {
    test('플릿 이름으로 반지름을 건다', () {
      // 이름이 안 맞으면 상류 기본값 0.5m 로 되돌아간다. 조용히.
      expect(launchXml(), contains('name="project1_pinky_radius"'));
    });

    test('플릿의 footprint 를 그대로 쓴다', () {
      expect(launchXml(footprintRadius: .1), contains('value="0.100"'));
      expect(launchXml(footprintRadius: .35), contains('value="0.350"'));
    });

    test('시각화 include 보다 앞에 온다', () {
      // 뒤에 두면 노드가 이미 만들어진 뒤라 안 걸린다.
      final xml = launchXml();
      final param = xml.indexOf('project1_pinky_radius');
      final include = xml.indexOf('visualization.launch.xml');
      expect(param, greaterThan(-1));
      expect(param, lessThan(include));
    });

    test('시각화 group 안에 있다', () {
      // set_parameter 는 범위 안의 모든 노드에 걸린다. group 밖에 두면 이
      // launch 의 다른 노드에까지 번진다.
      final xml = launchXml();
      final param = xml.indexOf('project1_pinky_radius');
      final groupBefore = xml.lastIndexOf('<group>', param);
      final closeBefore = xml.lastIndexOf('</group>', param);
      expect(groupBefore, greaterThan(closeBefore));
      // 그리고 include 와 같은 group 이라야 한다.
      final include = xml.indexOf('visualization.launch.xml');
      expect(xml.indexOf('</group>', param), greaterThan(include));
    });

    test('<param> 이 아니라 <set_parameter> 다', () {
      // <param> 은 남의 launch 안에 있는 노드에 못 붙인다.
      final xml = launchXml();
      final line = xml
          .split('\n')
          .firstWhere((l) => l.contains('project1_pinky_radius'));
      expect(line, contains('<set_parameter'));
    });
  });
}
