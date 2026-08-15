/// 로봇마다 Nav2 를 띄우는 launch.
///
/// 네임스페이스를 두 번 걸면 `/pinky_01/pinky_01/amcl` 이 되어 파라미터가 하나도
/// 안 붙는다. 오류도 안 나고 조용히 기본값으로 돈다 —
/// `docs/MULTI_ROBOT_NAMESPACES.md` 함정 1 과 같은 사고다.
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/rmf_project_config.dart';

void main() {
  const pinky = RmfProjectRobot(
    robotId: 'PK-01',
    displayName: '핑키 1호',
    model: 'PINKY-GZ',
    gzName: 'pinky_01',
    zones: ['ambient'],
    dataSource: RobotDataSource.gazebo,
    chargerWaypoint: '홈1',
    spawnX: 1.7607,
    spawnY: -0.6376,
  );
  const pinkyTwo = RmfProjectRobot(
    robotId: 'PK-02',
    displayName: '핑키 2호',
    model: 'PINKY-GZ',
    gzName: 'pinky_02',
    zones: ['ambient'],
    dataSource: RobotDataSource.gazebo,
    chargerWaypoint: '홈2',
    spawnX: 0.5,
    spawnY: -1.5,
  );
  const omx = RmfProjectRobot(
    robotId: 'OMX-01',
    displayName: '매니퓰레이터 1호',
    model: 'open_manipulator_x',
    kind: RmfRobotKind.workcell,
    gzName: 'omx_01',
    zones: [],
    dataSource: RobotDataSource.gazebo,
    chargerWaypoint: 'OMX1',
  );
  const mockPinky = RmfProjectRobot(
    robotId: 'MK-01',
    displayName: '연습용',
    model: 'PINKY-GZ',
    gzName: 'mock_01',
    zones: ['ambient'],
    chargerWaypoint: '홈3',
  );

  group('로봇 한 대의 Nav2', () {
    final xml = buildRobotNav2LaunchXml(pinky, 'gwanghee');

    test('네임스페이스를 한 번만 건다', () {
      // 두 번 걸면 /pinky_01/pinky_01/amcl 이 되어 파라미터가 안 붙는다.
      expect(RegExp('push-ros-namespace').allMatches(xml).length, 1);
      expect(xml, contains('<push-ros-namespace namespace="pinky_01"/>'));
      // 노드에 이름을 또 걸면 두 겹이 된다.
      expect(xml, isNot(contains('name="pinky_01/amcl"')));
      expect(xml, isNot(contains('ns="pinky_01"')));
    });

    test('AMCL 과 Nav2 서버들을 띄운다', () {
      for (final node in [
        'nav2_amcl',
        'nav2_controller',
        'nav2_planner',
        'nav2_behaviors',
        'nav2_bt_navigator',
        'nav2_smoother',
        'nav2_waypoint_follower',
        'nav2_velocity_smoother',
      ]) {
        expect(xml, contains('pkg="$node"'), reason: '$node 가 없습니다');
      }
    });

    test('map_server 는 없다 — 월드에 하나뿐이다', () {
      expect(xml, isNot(contains('nav2_map_server')));
      expect(xml, contains('map_server 는 여기 없다'));
    });

    test('모든 노드가 이 로봇의 파라미터를 읽는다', () {
      final nodes = RegExp('<node pkg=').allMatches(xml).length;
      final params = RegExp(
        r'<param from="\$\(dirname\)/nav2_params.yaml"/>',
      ).allMatches(xml).length;
      // lifecycle_manager 만 파라미터 파일을 안 읽는다.
      expect(params, nodes - 1);
    });

    test('lifecycle_manager 가 띄운 노드를 전부 관리한다', () {
      final managed = RegExp(
        r'value="\[amcl, ([^\]]+)\]"',
      ).firstMatch(xml)!.group(1)!.split(', ');
      for (final node in managed) {
        expect(xml, contains('name="$node"'), reason: '$node 를 안 띄웁니다');
      }
      expect(managed, contains('controller_server'));
      expect(managed, contains('bt_navigator'));
    });

    test('sim 시간을 쓴다 — Gazebo 와 시계를 맞춰야 한다', () {
      expect(xml, contains('name="use_sim_time"'));
    });

    test('lifecycle_manager 만은 벽시계로 잰다', () {
      // 전이 응답을 기다리는 시간 제한이 sim 시계에 걸리면 `Configuring` 에서
      // 영영 멈춘다. 실제로 map_server 가 거기서 멈춰 있었다.
      final manager = xml.substring(xml.indexOf('nav2_lifecycle_manager'));
      expect(manager, contains('name="use_sim_time" value="false"'));
    });

    test('파일 자리를 arg 로 돌려쓰지 않는다', () {
      // 같은 이름의 <arg> 를 여러 include 가 선언하면 launch 안에서 범위가
      // 겹쳐 먼저 읽은 값이 나머지에 쓰인다. 실제로 pinky_02 가 pinky_01 의
      // URDF 로 올라갔다.
      expect(xml, isNot(contains('robot_dir')));
      expect(xml, contains(r'$(dirname)/nav2_params.yaml'));
    });
  });

  group('프로젝트 전체의 Nav2', () {
    final xml = buildProjectNav2LaunchXml(
      mapName: 'gwanghee',
      robots: const [pinky, pinkyTwo, omx, mockPinky],
    );

    test('건물 지도는 하나만 띄운다', () {
      expect(RegExp('nav2_map_server').allMatches(xml).length, 1);
      expect(xml, contains('value="\$(var map_dir)/nav2_map/gwanghee.yaml"'));
    });

    test('이동 로봇마다 제 Nav2 를 붙인다', () {
      expect(xml, contains('robots/PK-01/nav2.launch.xml'));
      expect(xml, contains('robots/PK-02/nav2.launch.xml'));
    });

    test('설치 로봇은 Nav2 를 안 쓴다 — 한자리에 붙어 있다', () {
      expect(xml, isNot(contains('OMX-01')));
    });

    test('Mock 로봇도 안 쓴다 — 실제로는 없는 로봇이다', () {
      expect(xml, isNot(contains('MK-01')));
    });

    test('띄울 로봇이 없으면 그 사실을 적는다', () {
      final empty = buildProjectNav2LaunchXml(
        mapName: 'gwanghee',
        robots: const [omx, mockPinky],
      );
      expect(empty, contains('이동 로봇이 없다'));
      expect(empty, contains('nav2_map_server'));
    });

    test('RMF 와 Nav2 를 잇는 어댑터를 함께 띄운다', () {
      // 이것이 없으면 RMF 가 배차해도 로봇이 안 움직인다.
      // rmf_demos_fleet_adapter 는 slotcar 전용이라 우리 핑키에게는 상대가 없다.
      final withFleet = buildProjectNav2LaunchXml(
        mapName: 'gwanghee',
        robots: const [pinky],
        fleetName: 'gwanghee_pinky',
      );
      expect(withFleet, contains('gwanghee_nav2_adapter.py'));
      expect(withFleet, contains('gwanghee_pinky_config.yaml'));
      expect(withFleet, contains('nav_graphs/0.yaml'));
      // ROS 패키지에 든 노드가 아니라 우리가 만든 스크립트다.
      expect(withFleet, contains('<executable'));
      // 플릿 이름을 모르면 띄우지 않는다. 설정 파일 자리를 알 수 없다.
      expect(
        buildProjectNav2LaunchXml(mapName: 'gwanghee', robots: const [pinky]),
        isNot(contains('nav2_adapter')),
      );
    });

    test('손대지 못한 것을 파일 맨 위에 적는다', () {
      // 이 launch 가 안 뜰 때 사람이 제일 먼저 여는 파일이다.
      final warned = buildProjectNav2LaunchXml(
        mapName: 'gwanghee',
        robots: const [pinky],
        warnings: const ['벤더 파라미터를 찾지 못했습니다.'],
      );
      expect(warned, contains('확인이 필요한 것'));
      expect(warned, contains('· 벤더 파라미터를 찾지 못했습니다.'));
      // 주석 안에 있어야 launch 가 읽을 수 있다.
      expect(
        warned.indexOf('벤더 파라미터를 찾지 못했습니다.'),
        lessThan(warned.indexOf('-->')),
      );
    });
  });
}
