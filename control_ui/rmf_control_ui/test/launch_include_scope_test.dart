/// `<include>` 에 준 `<arg>` 가 바깥으로 새지 않는지 지킨다.
///
/// XML launch 의 `<include>` 는 **스스로 범위를 만들지 않는다.** 그래서 안에
/// 적은 `<arg>` 가 그 뒤의 형제들에게도 그대로 남는다. `rmf_demos` 가 include
/// 마다 `<group>` 을 씌우는 이유가 이것이다.
///
/// 실제로 이것 때문에 RViz 가 안 떴다. 시각화 include 에 `headless=true` 를
/// 넘겼더니 그 값이 바깥까지 덮어써서, 뒤에 있는
/// `<group unless="$(var headless)">` 가 통째로 건너뛰어졌다. Gazebo 는 멀쩡히
/// 뜨고 RViz 만 안 떴는데 **오류는 한 줄도 안 났다.**
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/rmf_project_config.dart';

/// `<arg>` 를 넘기면서 `<group>` 밖에 있는 include 를 찾는다.
///
/// 줄 단위로 훑는다. XML 파서를 들이지 않는 이유는 우리가 만든 파일이라 모양이
/// 정해져 있고, 여는 태그와 닫는 태그가 늘 제 줄에 있기 때문이다.
List<String> _leakingIncludes(String xml) {
  final leaking = <String>[];
  var groupDepth = 0;
  String? openInclude;
  var includeGroupDepth = 0;
  var includeHasArgs = false;

  for (final raw in xml.split('\n')) {
    final line = raw.trim();
    // 주석 줄에 든 태그는 세지 않는다.
    if (line.startsWith('<!--') || line.startsWith('*') || line.isEmpty) {
      continue;
    }
    if (line.startsWith('<group')) groupDepth++;
    if (line.startsWith('</group>')) groupDepth--;

    if (line.startsWith('<include')) {
      // 한 줄로 닫는 include 는 넘길 <arg> 가 없다.
      if (line.endsWith('/>')) continue;
      openInclude = line;
      includeGroupDepth = groupDepth;
      includeHasArgs = false;
      continue;
    }
    if (openInclude != null) {
      if (line.startsWith('<arg')) includeHasArgs = true;
      if (line.startsWith('</include>')) {
        if (includeHasArgs && includeGroupDepth == 0) {
          leaking.add(openInclude);
        }
        openInclude = null;
      }
    }
  }
  return leaking;
}

void main() {
  const pinky = RmfProjectRobot(
    robotId: 'PK-01',
    displayName: '핑키 1호',
    model: 'PINKY-GZ',
    gzName: 'pinky_01',
    zones: ['ambient'],
    chargerWaypoint: '충전1',
    dataSource: RobotDataSource.gazebo,
  );
  const slotcar = RmfProjectRobot(
    robotId: 'TR-01',
    displayName: '데모 로봇',
    model: 'tinyRobot',
    gzName: 'tiny_01',
    zones: ['ambient'],
  );

  String projectLaunch(List<RmfProjectRobot> robots) => buildProjectLaunchXml(
    mapName: 'gwanghee',
    fleetName: 'gwanghee_pinky',
    mapDirectory: '/maps/gwanghee',
    buildingYamlName: 'gwanghee.building.yaml',
    robots: robots,
  );

  group('include 의 <arg> 가 새지 않는다', () {
    test('프로젝트 launch (Nav2 로봇)', () {
      expect(_leakingIncludes(projectLaunch(const [pinky])), isEmpty);
    });

    test('프로젝트 launch (slotcar 플릿)', () {
      expect(_leakingIncludes(projectLaunch(const [slotcar])), isEmpty);
    });

    test('Gazebo bringup', () {
      final xml = buildProjectBringupXml(
        mapName: 'gwanghee',
        mapDirectory: '/maps/gwanghee',
        robots: const [pinky],
      );
      expect(_leakingIncludes(xml), isEmpty);
    });

    test('Nav2 launch', () {
      final xml = buildProjectNav2LaunchXml(
        mapName: 'gwanghee',
        robots: const [pinky],
        fleetName: 'gwanghee_pinky',
      );
      expect(_leakingIncludes(xml), isEmpty);
    });
  });

  group('RViz 를 띄우는 조건', () {
    test('시각화 include 가 group 안에 있다', () {
      // 이것을 감싸지 않아 headless 가 덮여 RViz 가 안 떴다.
      final xml = projectLaunch(const [pinky]);
      final viz = xml.indexOf('visualization.launch.xml');
      final groupBefore = xml.lastIndexOf('<group>', viz);
      final closeBefore = xml.lastIndexOf('</group>', viz);
      expect(groupBefore, greaterThan(-1));
      expect(
        groupBefore,
        greaterThan(closeBefore),
        reason: '시각화 include 가 열린 group 안에 있어야 한다',
      );
    });

    test('rviz 는 headless 가 아닐 때만 뜬다', () {
      final xml = projectLaunch(const [pinky]);
      final group = xml.indexOf(r'<group unless="$(var headless)">');
      expect(group, greaterThan(-1));
      expect(xml.indexOf('exec="rviz2"'), greaterThan(group));
      // 그 조건은 시각화 include 뒤에 온다. 그래서 새면 덮인다.
      expect(group, greaterThan(xml.indexOf('visualization.launch.xml')));
    });
  });

  /// 이 검사가 실제로 새는 것을 잡는지 확인한다. 안 그러면 늘 통과만 한다.
  group('검사 자체', () {
    test('group 밖의 include 를 잡아낸다', () {
      const leaky = '''
<launch>
  <include file="x.launch.xml">
    <arg name="headless" value="true"/>
  </include>
</launch>
''';
      expect(_leakingIncludes(leaky), hasLength(1));
    });

    test('group 안이면 통과시킨다', () {
      const scoped = '''
<launch>
  <group>
    <include file="x.launch.xml">
      <arg name="headless" value="true"/>
    </include>
  </group>
</launch>
''';
      expect(_leakingIncludes(scoped), isEmpty);
    });
  });
}
