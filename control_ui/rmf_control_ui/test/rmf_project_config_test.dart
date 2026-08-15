import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/rmf_project_config.dart';

/// 프로젝트마다 새로 만들어지는 Open-RMF 설정 파일의 내용을 확인한다.
///
/// 지금까지는 전역 fleet.yaml 하나와 office 데모의 tinyRobot_config.yaml 을
/// 빌려 썼다. 맵이 바뀌면 spawn 좌표도 charger 이름도 어긋난다.
void main() {
  const robots = [
    RmfProjectRobot(
      robotId: 'PK-01',
      displayName: '핑키 1호',
      model: 'PINKY-GZ-C',
      gzName: 'pinky_01',
      dataSource: RobotDataSource.gazebo,
      zones: ['ambient', 'chilled', 'frozen'],
      chargerWaypoint: '충전1',
      spawnX: 12.5,
      spawnY: 3.25,
    ),
    RmfProjectRobot(
      robotId: 'PK-02',
      displayName: '핑키 2호',
      model: 'PINKY-GZ',
      gzName: 'pinky_02',
      dataSource: RobotDataSource.gazebo,
      zones: ['ambient'],
      chargerWaypoint: '충전2',
      spawnX: 20,
      spawnY: 8.5,
      spawnHeading: 3.14159,
    ),
  ];

  group('fleet adapter 설정', () {
    test('Nav2와 같이 전진 전용이고 대기점에서 별도 회전을 만들지 않는다', () {
      final yaml = buildFleetAdapterYaml(
        fleet: const RmfFleetSettings(reversible: true),
        robots: const [],
        mapName: 'gwanghee',
      );
      // 저장된 옛 설정이 true여도 Pinky Nav2의 allow_reversing=false와 맞춘다.
      expect(yaml, contains('  reversible: False'));
      expect(yaml, contains('  responsive_wait: False'));
      expect(yaml, isNot(contains('  reversible: True')));
      expect(yaml, isNot(contains('  responsive_wait: True')));
    });

    test('로봇마다 charger Waypoint 이름이 들어간다', () {
      final yaml = buildFleetAdapterYaml(
        fleet: const RmfFleetSettings(fleetName: 'gwanghee_pinky'),
        robots: robots,
        mapName: 'gwanghee',
      );
      expect(yaml, contains('name: "gwanghee_pinky"'));
      expect(yaml, contains('    PK-01:'));
      expect(yaml, contains('        charger: "충전1"'));
      expect(yaml, contains('    PK-02:'));
      expect(yaml, contains('        charger: "충전2"'));
    });

    test('프로필 반경을 맵의 로봇 안전 기준에서 가져온다', () {
      // 폭 0.2m · 위치 오차 0.05m 인 작은 로봇.
      // footprint = 0.1, vicinity = 0.15 이어야 한다. 사용자가 이미 넣은 값을
      // 다시 묻지 않는 것이 핵심이다 — 두 곳에 적으면 어긋난다.
      final fleet = const RmfFleetSettings().withRobotSafety(
        widthMeters: .2,
        localizationMarginMeters: .05,
      );
      final yaml = buildFleetAdapterYaml(
        fleet: fleet,
        robots: robots,
        mapName: 'gwanghee',
      );
      expect(yaml, contains('footprint: 0.100'));
      expect(yaml, contains('vicinity: 0.150'));
    });

    test('로봇이 없어도 유효한 YAML 을 만든다', () {
      final yaml = buildFleetAdapterYaml(
        fleet: const RmfFleetSettings(),
        robots: const [],
        mapName: 'gwanghee',
      );
      expect(yaml, contains('  robots:'));
      expect(yaml, contains('{}'), reason: '빈 매핑이라도 있어야 파싱된다');
    });

    test('fleet_manager 접속 정보가 들어간다', () {
      final yaml = buildFleetAdapterYaml(
        fleet: const RmfFleetSettings(),
        robots: robots,
        mapName: 'gwanghee',
      );
      expect(yaml, contains('fleet_manager:'));
      expect(yaml, contains('  ip: "127.0.0.1"'));
      expect(yaml, contains('  port: 22011'));
    });
  });

  group('Gazebo spawn 목록', () {
    test('맵 Waypoint 좌표가 spawn 위치로 들어간다', () {
      final yaml = buildFleetSimYaml(robots: robots, mapName: 'gwanghee');
      expect(yaml, contains('  - id: PK-01'));
      expect(yaml, contains('    gz_name: pinky_01'));
      expect(yaml, contains('    zones: [ambient, chilled, frozen]'));
      expect(yaml, contains('    spawn_x: 12.500'));
      expect(yaml, contains('    spawn_y: 3.250'));
      expect(yaml, contains('    spawn_heading: 3.142'));
    });

    test('로봇이 없으면 빈 목록으로 둔다', () {
      final yaml = buildFleetSimYaml(robots: const [], mapName: 'gwanghee');
      expect(yaml, contains('robots:'));
      expect(yaml, contains('[]'));
    });
  });

  group('설정 저장·복원', () {
    test('플릿 설정이 JSON 을 오가도 값이 유지된다', () {
      final original = const RmfFleetSettings(
        fleetName: 'gwanghee_pinky',
      ).withRobotSafety(widthMeters: .2, localizationMarginMeters: .05);
      final restored = RmfFleetSettings.fromJson(original.toJson());
      expect(restored.fleetName, 'gwanghee_pinky');
      expect(restored.footprintRadius, .1);
      expect(restored.vicinityRadius, closeTo(.15, .0001));
      expect(restored.fleetManagerPort, 22011);
    });

    test('로봇이 JSON 을 오가도 값이 유지된다', () {
      final restored = RmfProjectRobot.fromJson(robots.first.toJson());
      expect(restored.robotId, 'PK-01');
      expect(restored.gzName, 'pinky_01');
      expect(restored.zones, ['ambient', 'chilled', 'frozen']);
      expect(restored.chargerWaypoint, '충전1');
      expect(restored.spawnX, 12.5);
    });

    test('빠진 항목은 기본값으로 채운다', () {
      final restored = RmfFleetSettings.fromJson(const {});
      expect(restored.fleetName, 'pinky');
      expect(restored.linearVelocity, .5);
    });
  });

  group('Gazebo bringup', () {
    test('네임스페이스를 두 번 걸지 않는다', () {
      final xml = buildRobotSpawnLaunchXml(robots.first);
      // 두 번 걸면 노드가 /pinky_01/pinky_01/... 에 뜬다. 그러면 create 가
      // 기다리는 robot_description 이 영영 오지 않아 로봇이 스폰되지 않는다.
      expect(RegExp('push-ros-namespace').allMatches(xml).length, 1);
      expect(xml, contains('<push-ros-namespace namespace="pinky_01"/>'));
      // 그룹에 걸었으니 노드에는 따로 걸지 않는다.
      expect(xml, isNot(contains('<arg name="namespace"')));
      expect(xml, isNot(contains('name="pinky_01/')));
    });

    test('벤더 launch 대신 우리가 손본 URDF 를 쓴다', () {
      // 벤더 xacro 는 링크 이름에는 네임스페이스를 안 붙이면서
      // <gazebo reference> 에는 붙인다. 맞는 링크가 없어 라이다·카메라·IMU 가
      // 통째로 버려진다. 토픽 이름은 보이는데 데이터가 영영 안 온다.
      final xml = buildRobotSpawnLaunchXml(robots.first);
      expect(xml, isNot(contains('upload_robot.launch.py')));
      expect(xml, contains('robot_description.sh'));
      // 벤더 launch 가 하던 일은 그대로 해야 한다.
      expect(xml, contains('frame_prefix" value="pinky_01/"'));
      expect(xml, contains('exec="joint_state_publisher"'));
    });

    test('파일 자리를 arg 로 돌려쓰지 않는다', () {
      // 같은 이름의 <arg> 를 여러 include 가 선언하면 launch 안에서 범위가
      // 겹쳐 먼저 읽은 값이 나머지에 쓰인다. 실제로 pinky_02 가 pinky_01 의
      // URDF 로 올라가서 라이다가 안 돌았다.
      for (final robot in robots) {
        final xml = buildRobotSpawnLaunchXml(robot);
        expect(xml, isNot(contains('robot_dir')));
        expect(xml, contains(r'$(dirname)/robot_description.sh'));
      }
    });

    test('create 가 그 로봇의 robot_description 을 절대 이름으로 가리킨다', () {
      for (final robot in robots) {
        final xml = buildRobotSpawnLaunchXml(robot);
        expect(xml, contains('-topic /${robot.gzName}/robot_description'));
        // 상대 이름이면 루트의 /robot_description 을 기다린다.
        expect(xml, isNot(contains('-topic robot_description')));
      }
    });

    test('로봇마다 제 디렉터리에서 불러온다', () {
      // 로봇 하나가 디렉터리 하나다. 한 대를 빼거나 옮길 때 그 디렉터리만
      // 보면 된다.
      final xml = buildProjectBringupXml(
        mapName: 'gwanghee',
        robots: robots,
        mapDirectory: '/maps/gwanghee',
      );
      expect(robotDirectoryName(robots.first), 'robots/PK-01');
      expect(
        xml,
        contains(
          r'<include file="$(var map_dir)/robots/PK-01'
          '/spawn.launch.xml"/>',
        ),
      );
      expect(
        xml,
        contains(
          r'<include file="$(var map_dir)/robots/PK-02'
          '/spawn.launch.xml"/>',
        ),
      );
      // 로봇 설정이 이 파일에 다시 적히면 두 곳이 어긋날 수 있다.
      expect(xml, isNot(contains('upload_robot.launch.py')));
    });

    test('로봇 ID 에 이상한 글자가 있어도 디렉터리 밖으로 나가지 않는다', () {
      const sneaky = RmfProjectRobot(
        robotId: '../../etc/passwd',
        displayName: 'x',
        model: 'PINKY-GZ',
        gzName: 'pinky_x',
        zones: [],
      );
      expect(robotDirectoryName(sneaky), isNot(contains('..')));
      expect(robotDirectoryName(sneaky), startsWith('robots/'));
    });

    test('Gazebo 플러그인이 켜지도록 is_sim 을 넘긴다', () {
      // is_sim 이 빠지면 diff drive 도 LiDAR 도 없는 껍데기가 스폰된다.
      // 보이기는 하는데 cmd_vel 을 줘도 움직이지 않는다. 이제 xacro 를 우리가
      // 펼치므로 그 인자는 URDF 스크립트에 있다.
      expect(
        buildRobotDescriptionScript(robots.first),
        contains('is_sim:=true'),
      );
    });

    test('이동 로봇의 URDF 스크립트가 reference 접두사를 뗀다', () {
      final script = buildRobotDescriptionScript(robots.first);
      // 네임스페이스 끝의 빗금까지 벤더 launch 와 같아야 한다. 다르면 접두사가
      // 달라져서 떼기 규칙이 안 맞는다.
      expect(script, contains(r'namespace:="$NAMESPACE/"'));
      // 조인트 이름에는 네임스페이스가 붙어 있고 링크에는 안 붙어 있다. 무조건
      // 떼면 조인트 쪽이 깨진다.
      expect(script, contains('if name in links or name in joints:'));
      expect(script, contains("name[len(prefix):] in links"));
      // 셸이 작은따옴표 안에서 작은따옴표를 못 견디므로 heredoc 으로 넘긴다.
      expect(script, contains("<<'PYTHON'"));
      expect(script, isNot(contains("python3 -c '")));
    });

    test('설치 로봇의 URDF 스크립트는 하던 대로 한다', () {
      const workcell = RmfProjectRobot(
        robotId: 'OMX-01',
        displayName: '매니퓰레이터 1호',
        model: 'open_manipulator_x',
        kind: RmfRobotKind.workcell,
        gzName: 'omx_01',
        zones: [],
        dataSource: RobotDataSource.gazebo,
        chargerWaypoint: 'OMX1',
      );
      final script = buildRobotDescriptionScript(workcell);
      expect(script, contains('gz_ros2_control'));
      expect(script, contains('robot_param_node'));
      expect(script, isNot(contains('pinky_description')));
    });

    test('다리는 이 프로젝트 설정으로 한 번만 띄운다', () {
      final xml = buildProjectBringupXml(
        mapName: 'gwanghee',
        robots: robots,
        mapDirectory: '/maps/gwanghee',
      );
      expect(
        'parameter_bridge'.allMatches(xml).length,
        1,
        reason: '로봇마다 띄우면 같은 토픽을 여러 번 다리 놓는다',
      );
      expect(
        xml,
        contains(
          r'<arg name="bridge_params" default="$(var map_dir)'
          '/gwanghee_gz_bridge.yaml"/>',
        ),
      );
      expect(xml, contains('<arg name="map_dir" default="/maps/gwanghee"/>'));
      // 벤더 설정은 이름이 상대 경로라 로봇이 여러 대면 겹친다.
      expect(xml, isNot(contains('pinky_gz_sim)/params/pinky_bridge.yaml')));
    });

    test('로봇이 없어도 유효한 launch 를 만든다', () {
      final xml = buildProjectBringupXml(
        mapName: 'gwanghee',
        robots: const [],
        mapDirectory: '/maps/gwanghee',
      );
      expect(xml, contains('</launch>'));
      expect(xml, contains('Gazebo 로 돌릴 로봇이 없다'));
    });
  });

  group('Gazebo 다리 설정', () {
    test('로봇마다 토픽 이름이 갈린다', () {
      final yaml = buildProjectGzBridgeYaml(
        mapName: 'gwanghee',
        robots: robots,
      );
      for (final topic in [
        'odom',
        'cmd_vel_smoothed',
        'scan',
        'joint_states',
      ]) {
        expect(yaml, contains('ros_topic_name: "/pinky_01/$topic"'));
        expect(yaml, contains('ros_topic_name: "/pinky_02/$topic"'));
      }
      // 상대 이름이 하나라도 남으면 두 로봇이 같은 토픽을 쓴다.
      expect(yaml, isNot(contains('ros_topic_name: "odom"')));
      expect(yaml, isNot(contains('ros_topic_name: "cmd_vel"')));
    });

    test('센서 이름은 같고 속도 명령만 smoother 출력을 Gazebo 입력에 잇는다', () {
      final yaml = buildProjectGzBridgeYaml(
        mapName: 'gwanghee',
        robots: robots,
      );
      final ros = RegExp(
        r'ros_topic_name: "([^"]+)"',
      ).allMatches(yaml).map((m) => m.group(1)).toList();
      final gz = RegExp(
        r'gz_topic_name: "([^"]+)"',
      ).allMatches(yaml).map((m) => m.group(1)).toList();
      expect(ros, isNotEmpty);
      expect(ros.length, gz.length);
      for (var i = 0; i < ros.length; i++) {
        if (ros[i]!.endsWith('/cmd_vel_smoothed')) {
          expect(gz[i], ros[i]!.replaceFirst('/cmd_vel_smoothed', '/cmd_vel'));
        } else {
          expect(gz[i], ros[i]);
        }
      }
    });

    test('clock 과 tf 는 로봇별로 나누지 않는다', () {
      final yaml = buildProjectGzBridgeYaml(
        mapName: 'gwanghee',
        robots: robots,
      );
      // 월드에 하나뿐인 것을 로봇 수만큼 다리 놓으면 시간이 중복 발행된다.
      expect('ros_topic_name: "/clock"'.allMatches(yaml).length, 1);
      expect('ros_topic_name: "/tf"'.allMatches(yaml).length, 1);
    });

    test('cmd_vel 만 ROS 에서 Gazebo 로 간다', () {
      final yaml = buildProjectGzBridgeYaml(
        mapName: 'gwanghee',
        robots: robots,
      );
      final lines = yaml.split('\n');
      for (var i = 0; i < lines.length; i++) {
        if (!lines[i].contains('direction: ROS_TO_GZ')) continue;
        expect(lines[i - 4], contains('cmd_vel'));
      }
      expect('ROS_TO_GZ'.allMatches(yaml).length, robots.length);
      expect(yaml, contains('ros_topic_name: "/pinky_01/cmd_vel_smoothed"'));
      expect(yaml, contains('gz_topic_name: "/pinky_01/cmd_vel"'));
      expect(yaml, isNot(contains('ros_topic_name: "/pinky_01/cmd_vel"')));
    });

    test('핑키 카메라를 ROS로 옮기지 않는다', () {
      final yaml = buildProjectGzBridgeYaml(
        mapName: 'gwanghee',
        robots: robots,
      );
      expect(yaml, isNot(contains('/camera/image_raw')));
      expect(yaml, isNot(contains('/camera/camera_info')));

      final relay = buildSensorRelayScript(mapName: 'gwanghee', robots: robots);
      expect(relay, isNot(contains("Image, f'/{namespace}/camera/image_raw'")));
    });

    test('센서 relay의 ROS node 이름에서 하이픈을 제거한다', () {
      final relay = buildSensorRelayScript(
        mapName: 'project1-ver2',
        robots: robots,
      );
      expect(relay, contains("super().__init__('project1_ver2_sensor_relay')"));
    });
  });

  group('설치 로봇', () {
    const workcell = RmfProjectRobot(
      robotId: 'OMX-01',
      displayName: '매니퓰레이터 1호',
      model: 'open_manipulator_x',
      kind: RmfRobotKind.workcell,
      dataSource: RobotDataSource.gazebo,
      gzName: 'omx_01',
      zones: [],
      chargerWaypoint: 'OMX1',
      spawnX: 5,
      spawnY: 2,
    );
    const mixed = [...robots, workcell];

    test('플릿에 넣지 않는다', () {
      final yaml = buildFleetAdapterYaml(
        fleet: const RmfFleetSettings(),
        robots: mixed,
        mapName: 'gwanghee',
      );
      // 넣으면 fleet adapter 가 배차 대상으로 보고 갈 수 없는 곳으로 보낸다.
      expect(yaml, contains('    PK-01:'));
      expect(yaml, contains('    PK-02:'));
      expect(yaml, isNot(contains('    OMX-01:')));
      // 그래도 어떤 설비가 있는지는 주석으로 남긴다.
      expect(yaml, contains('# 설치 로봇은 플릿에 넣지 않는다'));
      expect(yaml, contains('#   OMX-01 · 매니퓰레이터 1호'));
    });

    test('이동 로봇이 하나도 없으면 빈 플릿이 된다', () {
      final yaml = buildFleetAdapterYaml(
        fleet: const RmfFleetSettings(),
        robots: const [workcell],
        mapName: 'gwanghee',
      );
      expect(yaml, contains('{} # 관제 대상 이동 로봇이 없다.'));
    });

    test('bringup 은 open_manipulator 쪽 설명을 쓴다', () {
      final xml = buildRobotSpawnLaunchXml(workcell);
      // 벤더 xacro 를 직접 부르지 않고 네임스페이스를 끼워 넣는 스크립트를
      // 거친다. 그 스크립트가 open_manipulator 쪽 xacro 를 펼친다.
      expect(xml, contains('robot_description.sh'));
      expect(
        buildRobotDescriptionScript(workcell),
        contains('open_manipulator_description'),
      );
      expect(xml, contains('args="-name omx_01 -topic robot_description'));
      // 팔은 바퀴가 아니라 컨트롤러가 움직인다.
      expect(xml, contains('args="arm_controller"'));
      expect(xml, contains('args="gripper_controller"'));
      expect(xml, contains('args="joint_state_broadcaster"'));
      // 이동 로봇 쪽은 그대로다.
      expect(
        buildRobotSpawnLaunchXml(robots.first),
        contains('-topic /pinky_01/robot_description'),
      );
    });

    test('그리퍼가 없는 모델에는 그리퍼 컨트롤러를 올리지 않는다', () {
      // omy_3m 에는 그리퍼가 없다. 없는 컨트롤러를 올리면 spawner 가 기다리다
      // 실패하고, 팔까지 함께 안 움직이는 것처럼 보인다.
      final xml = buildRobotSpawnLaunchXml(
        const RmfProjectRobot(
          robotId: 'OMY-01',
          displayName: '팔 1호',
          model: 'omy_3m',
          kind: RmfRobotKind.workcell,
          dataSource: RobotDataSource.gazebo,
          gzName: 'omy_01',
          zones: [],
          chargerWaypoint: 'OMX1',
        ),
      );
      expect(xml, contains('args="arm_controller"'));
      expect(xml, contains('args="joint_state_broadcaster"'));
      expect(xml, isNot(contains('args="gripper_controller"')));
    });

    test('고를 수 있는 모델은 모두 컨트롤러가 정의되어 있다', () {
      // 고를 수 있는데 띄우면 죽는 항목은 없느니만 못하다.
      for (final model in openManipulatorModels) {
        expect(
          openManipulatorControllers[model],
          isNotEmpty,
          reason: '$model 의 컨트롤러가 비어 있다',
        );
      }
    });

    test('메시를 찾도록 두 설명 패키지를 모두 경로에 넣는다', () {
      final xml = buildProjectBringupXml(
        mapName: 'gwanghee',
        robots: mixed,
        mapDirectory: '/maps/gwanghee',
      );
      expect(xml, contains(r'$(find-pkg-share pinky_description)/../'));
      expect(
        xml,
        contains(r'$(find-pkg-share open_manipulator_description)/../'),
      );
    });

    test('설치 로봇에는 다리를 아예 놓지 않는다', () {
      // 예전에는 joint_states 다리를 놓았는데, 옮길 gz 토픽이 애초에 없었다.
      // OpenMANIPULATOR 의 Gazebo 플러그인은 gz_ros2_control 하나뿐이라
      // `gz::sim::systems::JointStatePublisher` 가 없다. 그래서 값은 영영
      // 안 오면서 같은 ROS 토픽에 발행자만 둘이 되었다 — 조용한 다리 하나와
      // 진짜 값을 내는 joint_state_broadcaster 하나.
      final yaml = buildProjectGzBridgeYaml(mapName: 'gwanghee', robots: mixed);
      expect(yaml, isNot(contains('ros_topic_name: "/omx_01/joint_states"')));
      // 바퀴도 LiDAR 도 없다. 있지도 않은 토픽에 다리를 놓으면 조용히 놀고 있다.
      expect(yaml, isNot(contains('ros_topic_name: "/omx_01/odom"')));
      expect(yaml, isNot(contains('ros_topic_name: "/omx_01/cmd_vel"')));
      expect(yaml, isNot(contains('ros_topic_name: "/omx_01/scan"')));
      // 대신 어디로 오가는지 파일에 적어 둔다. 다리가 없는 것과 빠뜨린 것은
      // 다르고, 이 파일만 보는 사람이 그 차이를 알 수 있어야 한다.
      expect(yaml, contains('gz_ros2_control'));
      expect(yaml, contains('joint_state_broadcaster'));
      // 이동 로봇은 그대로 다 잇는다.
      expect(yaml, contains('ros_topic_name: "/pinky_01/odom"'));
    });

    test('종류가 JSON 을 오가도 유지된다', () {
      final restored = RmfProjectRobot.fromJson(workcell.toJson());
      expect(restored.kind, RmfRobotKind.workcell);
      expect(restored.isMobile, isFalse);
      expect(restored.chargerWaypoint, 'OMX1');
    });

    test('종류가 없는 옛 기록은 이동 로봇으로 읽는다', () {
      // v8 이전에 저장된 로봇에는 kind 가 없다. 전부 이동 로봇이었다.
      final restored = RmfProjectRobot.fromJson(const {
        'robotId': 'PK-09',
        'model': 'PINKY-GZ',
        'gzName': 'pinky_09',
      });
      expect(restored.kind, RmfRobotKind.mobile);
    });
  });

  group('로봇별 디렉터리', () {
    const workcell = RmfProjectRobot(
      robotId: 'OMX-01',
      displayName: '매니퓰레이터 1호',
      model: 'open_manipulator_x',
      kind: RmfRobotKind.workcell,
      dataSource: RobotDataSource.gazebo,
      gzName: 'omx_01',
      zones: [],
      chargerWaypoint: 'OMX1',
      spawnX: 5,
      spawnY: 2,
    );

    test('등록 정보를 사람이 읽을 수 있게 남긴다', () {
      final yaml = buildRobotInfoYaml(robots.first);
      expect(yaml, contains('id: PK-01'));
      expect(yaml, contains('kind: mobile # 이동 로봇'));
      expect(yaml, contains('gz_name: pinky_01'));
      expect(yaml, contains('charger_waypoint: 충전1'));
      expect(yaml, contains('spawn_x: 12.500'));
    });

    test('설치 로봇은 충전이 아니라 설비 자리라고 적는다', () {
      final yaml = buildRobotInfoYaml(workcell);
      expect(yaml, contains('kind: workcell # 설치 로봇'));
      expect(yaml, contains('station_waypoint: OMX1'));
      expect(yaml, isNot(contains('charger_waypoint')));
    });

    test('한 대만 담긴 다리 설정을 남긴다', () {
      final yaml = buildRobotBridgeYaml(robots.first);
      expect(yaml, contains('/pinky_01/odom'));
      // 다른 로봇 것이 섞이면 이 디렉터리만 봐서는 알 수 없게 된다.
      expect(yaml, isNot(contains('pinky_02')));
      expect(yaml, contains('한 대의 토픽 목록'));
    });

    test('설명이 어디서 고치는지 알려 준다', () {
      final readme = buildRobotReadme(robots.first, 'gwanghee');
      expect(readme, contains('# PK-01 · 핑키 1호'));
      expect(readme, contains('`/pinky_01`'));
      // 여기 파일을 손으로 고치면 다음 저장 때 사라진다.
      expect(readme, contains('손으로 고치지 마세요'));
      expect(readme, contains('로봇 등록'));
    });

    test('설치 로봇 설명에는 올리는 컨트롤러가 적힌다', () {
      final readme = buildRobotReadme(workcell, 'gwanghee');
      expect(readme, contains('workcell'));
      expect(readme, contains('`arm_controller`'));
      expect(readme, contains('`gripper_controller`'));
    });

    test('로봇마다 디렉터리가 갈린다', () {
      final names = {
        for (final robot in [...robots, workcell]) robotDirectoryName(robot),
      };
      expect(names, {'robots/PK-01', 'robots/PK-02', 'robots/OMX-01'});
    });
  });

  group('값의 출처', () {
    const mock = RmfProjectRobot(
      robotId: 'MK-01',
      displayName: '연습용 1호',
      model: 'PINKY-GZ',
      gzName: 'mock_01',
      zones: ['ambient'],
      chargerWaypoint: '충전9',
      spawnX: 1,
      spawnY: 1,
    );
    const real = RmfProjectRobot(
      robotId: 'RP-01',
      displayName: '실물 1호',
      model: 'PINKY-GZ',
      dataSource: RobotDataSource.real,
      gzName: 'real_01',
      zones: ['ambient'],
      chargerWaypoint: '충전8',
      spawnX: 2,
      spawnY: 2,
    );
    // 이동 로봇 둘은 Gazebo, 여기에 Mock 하나와 실물 하나를 더한다.
    const mixed = [...robots, mock, real];

    test('기본값은 Mock 이다', () {
      // 등록만 하고 아무것도 안 고른 로봇을 실행에 밀어 넣으면 안 된다.
      expect(mock.dataSource, RobotDataSource.mock);
      expect(mock.isManagedByRmf, isFalse);
      expect(mock.runsInGazebo, isFalse);
    });

    test('Mock 은 fleet adapter 에 넣지 않는다', () {
      // 앱이 제 안에서 굴리는 것이라 실제로는 없다. 넣으면 fleet adapter 가
      // 오지 않을 로봇의 상태를 계속 기다린다.
      final yaml = buildFleetAdapterYaml(
        fleet: const RmfFleetSettings(),
        robots: mixed,
        mapName: 'gwanghee',
      );
      expect(yaml, contains('    PK-01:'));
      expect(yaml, contains('    RP-01:'), reason: '실물은 관제 대상이다');
      expect(yaml, isNot(contains('    MK-01:')));
      expect(yaml, contains('# 앱 Mock 로봇은 플릿에 넣지 않는다'));
      expect(yaml, contains('#   MK-01 · 연습용 1호'));
    });

    test('Gazebo 로 돌릴 것만 시뮬레이터에 올린다', () {
      // 실물을 시뮬레이터에 또 띄우면 같은 이름이 두 번 뜬다.
      final xml = buildProjectBringupXml(
        mapName: 'gwanghee',
        robots: mixed,
        mapDirectory: '/maps/gwanghee',
      );
      expect(xml, contains('robots/PK-01/spawn.launch.xml'));
      expect(xml, contains('robots/PK-02/spawn.launch.xml'));
      expect(xml, isNot(contains('robots/MK-01/')));
      expect(xml, isNot(contains('robots/RP-01/')));
    });

    test('Gazebo 에 없는 로봇에는 다리를 놓지 않는다', () {
      // 오지 않을 토픽을 기다리는 다리가 조용히 남는다.
      final yaml = buildProjectGzBridgeYaml(mapName: 'gwanghee', robots: mixed);
      expect(yaml, contains('/pinky_01/odom'));
      expect(yaml, isNot(contains('mock_01')));
      expect(yaml, isNot(contains('real_01')));
    });

    test('Gazebo 로 돌릴 것이 하나도 없으면 그렇다고 적는다', () {
      final xml = buildProjectBringupXml(
        mapName: 'gwanghee',
        robots: const [mock, real],
        mapDirectory: '/maps/gwanghee',
      );
      expect(xml, contains('Gazebo 로 돌릴 로봇이 없다'));
      expect(xml, contains('출처를 Gazebo 로 골라야'));
      expect(xml, contains('</launch>'));
    });

    test('로봇 디렉터리에 출처를 적는다', () {
      expect(
        buildRobotInfoYaml(mock),
        contains('data_source: mock # 앱 Mock 데이터'),
      );
      expect(buildRobotInfoYaml(real), contains('data_source: real # 실제 로봇'));
    });

    test('bringup 이 부르지 않는 이유를 그 파일에 적는다', () {
      // 파일만 보고 왜 안 올라오는지 헤매지 않아야 한다.
      final xml = buildRobotSpawnLaunchXml(mock);
      expect(xml, contains('값의 출처: 앱 Mock 데이터'));
      expect(xml, contains('bringup 이 부르지 않는다'));
      // Gazebo 것은 부른다고 적는다.
      expect(
        buildRobotSpawnLaunchXml(robots.first),
        contains('bringup 이 이 파일을 include 한다'),
      );
    });

    test('설명이 어디에 들어가고 안 들어가는지 알려 준다', () {
      expect(
        buildRobotReadme(mock, 'gwanghee'),
        contains('fleet adapter 에도 Gazebo 에도 들어가지 않습니다'),
      );
      expect(
        buildRobotReadme(real, 'gwanghee'),
        contains('실물이 이미 있으므로 Gazebo 에는 올리지 않습니다'),
      );
      expect(
        buildRobotReadme(robots.first, 'gwanghee'),
        contains('Gazebo 에 올립니다'),
      );
    });

    test('출처가 JSON 을 오가도 유지된다', () {
      expect(
        RmfProjectRobot.fromJson(real.toJson()).dataSource,
        RobotDataSource.real,
      );
      // v10 이전 기록에는 출처가 없다. 전부 앱 Mock 으로 보고 있었다.
      expect(
        RmfProjectRobot.fromJson(const {
          'robotId': 'OLD-01',
          'model': 'PINKY-GZ',
          'gzName': 'old_01',
        }).dataSource,
        RobotDataSource.mock,
      );
    });
  });

  group('실행 전 점검', () {
    const pinky = RmfProjectRobot(
      robotId: 'PK-01',
      displayName: '핑키',
      model: 'PINKY-GZ',
      dataSource: RobotDataSource.gazebo,
      gzName: 'pinky_01',
      zones: ['ambient'],
      chargerWaypoint: '충전1',
    );
    const omx = RmfProjectRobot(
      robotId: 'OMX-01',
      displayName: '팔',
      model: 'open_manipulator_x',
      kind: RmfRobotKind.workcell,
      dataSource: RobotDataSource.gazebo,
      gzName: 'omx_01',
      zones: [],
      chargerWaypoint: 'OMX1',
    );

    test('설치 로봇이 있으면 그 workspace 도 읽는다', () {
      // 이것이 빠져 있어 open_manipulator_description 을 못 찾았고, launch 가
      // 통째로 예외를 내며 멈춰 Pinky 까지 안 떴다.
      final script = buildProjectRunScript(
        mapName: 'mixed',
        mapDirectory: '/maps/mixed',
        robots: const [pinky, omx],
      );
      expect(script, contains(r'OMX_WS/install/setup.bash'));
      expect(script, contains('open_manipulator_description'));
    });

    test('필요한 패키지를 등록에서 뽑는다', () {
      final mixed = buildProjectRunScript(
        mapName: 'mixed',
        mapDirectory: '/maps/mixed',
        robots: const [pinky, omx],
      );
      expect(
        mixed,
        contains(
          'REQUIRED_PACKAGES="rmf_demos rmf_demos_fleet_adapter '
          'rmf_building_map_tools ros_gz_sim '
          'pinky_description robot_state_publisher joint_state_publisher '
          'open_manipulator_description"',
        ),
      );
      // 설치 로봇이 없으면 요구하지 않는다. 요구하면 그것을 안 쓰는 사람도
      // 못 띄운다.
      final onlyPinky = buildProjectRunScript(
        mapName: 'pinky',
        mapDirectory: '/maps/pinky',
        robots: const [pinky],
      );
      expect(onlyPinky, isNot(contains('open_manipulator_description')));
    });

    test('Gazebo 창과 RViz 를 따로 고른다', () {
      // 예전에는 HEADLESS 하나가 둘을 함께 껐다 켰다 했다. 보고 싶은 것이
      // 서로 다른데(위치는 Gazebo, 계획한 경로는 RViz) 하나를 보려고 둘을 다
      // 띄우면 그리는 데 자원을 나눠 써 시뮬레이션까지 느려졌다.
      final script = buildProjectRunScript(
        mapName: 'mixed',
        mapDirectory: '/maps/mixed',
        robots: const [pinky],
      );
      expect(script, contains(r'GAZEBO_GUI="${GAZEBO_GUI:-$GUI_DEFAULT}"'));
      expect(script, contains(r'RVIZ="${RVIZ:-$GUI_DEFAULT}"'));
      // 서로 다른 launch 가 서로 다른 값을 받아야 따로 고른 것이 된다.
      expect(
        script,
        contains(
          'ros2 launch "\$MAP_DIR/mixed_bringup.launch.xml" '
          'headless:="\$GAZEBO_HEADLESS"',
        ),
      );
      expect(
        script,
        contains(
          'ros2 launch "\$MAP_DIR/mixed.launch.xml" headless:="\$RVIZ_HEADLESS"',
        ),
      );
      // 하나로 묶여 있던 옛 변수는 launch 로 흘러가지 않는다.
      expect(script, isNot(contains(r'headless:="$HEADLESS"')));
    });

    test('아무것도 안 주면 창을 띄우지 않는다', () async {
      // 기본이 중요하다. 창이 없어도 라이다·카메라는 돌지만(서버는 언제나
      // 헤드리스 렌더링) 창은 자원을 먹는다. 고르지 않은 사람에게 두 개를
      // 띄워 주지 않는다.
      final script = buildProjectRunScript(
        mapName: 'demo',
        mapDirectory: '/maps/demo',
        robots: const [pinky],
      );
      Future<String> resolve(Map<String, String> environment) async {
        // 글자만 보면 뒤집는 자리에서 틀린 것을 못 잡는다. 실제로 bash 에
        // 물려 본다. 실행 부분은 빼고 값을 정하는 데까지만 돌린다.
        const tail = 'RVIZ_HEADLESS=true; fi';
        final start = script.indexOf('is_true() {');
        final end = script.indexOf(tail);
        expect(start, greaterThan(0));
        expect(end, greaterThan(start));
        final block = script.substring(start, end + tail.length);
        final file =
            File(
              '${Directory.systemTemp.createTempSync('rmf_run_flags').path}'
              '/flags.sh',
            )..writeAsStringSync(
              'set -euo pipefail\n$block\n'
              r'echo "$GAZEBO_HEADLESS $RVIZ_HEADLESS"'
              '\n',
            );
        // 셋을 늘 넘긴다. 빈 값은 bash 의 `:-` 가 안 준 것과 똑같이 본다.
        // 부모 환경에 이 이름이 남아 있어도 결과가 흔들리지 않는다.
        final result = await Process.run(
          'bash',
          [file.path],
          environment: {
            'GAZEBO_GUI': environment['GAZEBO_GUI'] ?? '',
            'RVIZ': environment['RVIZ'] ?? '',
            'HEADLESS': environment['HEADLESS'] ?? '',
          },
        );
        expect(result.exitCode, 0, reason: result.stderr.toString());
        return result.stdout.toString().trim();
      }

      // 고르지 않았으면 둘 다 headless.
      expect(await resolve(const {}), 'true true');
      // 고른 것만 뜬다.
      expect(await resolve(const {'GAZEBO_GUI': 'true'}), 'false true');
      expect(await resolve(const {'RVIZ': 'true'}), 'true false');
      expect(
        await resolve(const {'GAZEBO_GUI': 'true', 'RVIZ': 'true'}),
        'false false',
      );
      // 예전 방식(HEADLESS 하나)도 그대로 받는다. 따로 준 값이 이긴다.
      expect(await resolve(const {'HEADLESS': 'false'}), 'false false');
      expect(
        await resolve(const {'HEADLESS': 'false', 'RVIZ': 'false'}),
        'false true',
      );
    }, skip: !Platform.isLinux && !Platform.isMacOS);

    test('월드의 충돌 검출기를 bullet 으로 바꾼다', () {
      // 기본 ODE 는 메시끼리 닿으면 무너진다. 우리 로봇의 충돌 도형도, 배포가
      // 만든 바닥·벽도 전부 메시라 늘 메시 대 메시다. 자리를 안 고른 로봇 두
      // 대가 원점에 겹쳐 놓이자 스폰 4초 만에 Gazebo 가 죽었다
      // (collision_trimesh_trimesh.cpp:285 어서션, exit 134).
      final script = buildProjectRunScript(
        mapName: 'mixed',
        mapDirectory: '/maps/mixed',
        robots: const [pinky, omx],
      );
      expect(
        script,
        contains('<collision_detector>bullet</collision_detector>'),
      );
      expect(
        script,
        contains(r'ensure_world_collision_detector "$MAP_DIR/mixed.world"'),
      );
      // 배포가 월드를 다시 만들므로 띄우기 전에 매번 채워야 한다.
      expect(
        script.indexOf('ensure_world_collision_detector "'),
        lessThan(script.indexOf('Gazebo bringup')),
      );
    });

    test('Gazebo 가 안 뜨면 RMF 도 Nav2 도 띄우지 않는다', () {
      // 예전에는 `&` 로 띄우고 `sleep 12` 만 했다. 뜬 줄 알고 넘어간 것이지
      // 확인한 것이 아니어서, Gazebo 가 4초 만에 죽어도 RMF 와 Nav2 가 그 위에
      // 올라갔다. 프로세스 15개가 30분을 돌았는데 발행자는 0개였다.
      final script = buildProjectRunScript(
        mapName: 'mixed',
        mapDirectory: '/maps/mixed',
        robots: const [pinky, omx],
      );
      expect(script, contains('wait_for_gazebo'));
      // 프로세스가 있는 것과 물리가 도는 것은 다르다. 둘 다 본다.
      expect(script, contains(r'pgrep -u "$(id -u)" -f "gz sim.*$world"'));
      expect(script, contains('ros2 topic echo /clock --once'));
      // 확인은 1단계 뒤, 2단계 앞이라야 뜻이 있다.
      final check = script.indexOf('if ! wait_for_gazebo');
      expect(check, greaterThan(script.indexOf('[1/3] Gazebo bringup')));
      expect(check, lessThan(script.indexOf('[2/3] Open-RMF')));
      // 조용히 넘어가지 않고 멈춘다.
      expect(script, contains('exit 1'));
    });

    test('RMF↔Nav2 어댑터가 죽으면 알린다', () {
      // 어댑터가 죽어도 Gazebo·Nav2·RMF core 는 남는다. 토픽은 오는데 주문만
      // 안 먹는 상태가 되고, 화면에는 `RMF 가 답하지 않았습니다` 로만 보였다.
      // 무엇이 죽었는지는 로그에도 안 남았다.
      final script = buildProjectRunScript(
        mapName: 'mixed',
        mapDirectory: '/maps/mixed',
        robots: const [pinky, omx],
      );
      expect(script, contains('watch_fleet_adapter'));
      // 뜨는 것만 보면 안 된다. 뜬 다음 죽는 것이 진짜 문제다.
      //
      // 다만 이제 launch 가 respawn 으로 다시 띄운다. 사라진 그 순간에 알리면
      // 5초 뒤 살아난 것을 두고 사람을 뛰게 만든다. 정말 안 돌아올 때만 알린다.
      expect(script, contains('다시 뜨지도 않았습니다'));
      // 가장 흔한 원인을 함께 적는다.
      expect(script, contains('rmf/dynamic_event/begin'));
      // 지켜보기는 3단계와 함께 돌아야 한다.
      expect(
        script.indexOf('watch_fleet_adapter &'),
        greaterThan(script.indexOf('[3/3]')),
      );
    });

    test('Nav2 를 안 쓰는 프로젝트도 Gazebo 를 확인한다', () {
      // 단계 수가 2개로 줄 뿐 확인이 빠질 이유는 없다.
      final script = buildProjectRunScript(
        mapName: 'onlymock',
        mapDirectory: '/maps/onlymock',
        robots: const [omx],
      );
      final check = script.indexOf('if ! wait_for_gazebo');
      expect(check, greaterThan(script.indexOf('[1/2] Gazebo bringup')));
      expect(check, lessThan(script.indexOf('[2/2] Open-RMF')));
    });

    test('building.yaml 이 더 새로우면 nav graph 를 다시 만든다', () {
      // 맵에서 충전 Waypoint 에 Lane 을 이어도 nav_graphs/0.yaml 이 그대로면
      // RMF 는 옛날 지도를 본다. 파일이 있으니 오류도 나지 않고, 대신 로봇을
      // 플릿에 넣을 때 "충전 지점을 못 찾겠다"고 한다.
      final script = buildProjectRunScript(
        mapName: 'mixed',
        mapDirectory: '/maps/mixed',
        robots: const [pinky],
      );
      expect(script, contains(r'"$BUILDING_YAML" -nt "$NAV_GRAPH"'));
      expect(
        script,
        contains('ros2 run rmf_building_map_tools building_map_generator nav'),
      );
      // 다시 만드는 일은 ROS 를 읽은 뒤라야 한다.
      expect(
        script.indexOf(r'source "$ROS_SETUP"'),
        lessThan(script.indexOf('building_map_generator nav')),
      );
    });

    test('PGID 파일을 실행 스크립트가 지우지 않는다', () {
      // 이 셸이 먼저 끝나고 자식이 살아남는 일이 있다. 그때 파일까지 지우면
      // 그 그룹을 끊을 손잡이가 사라진다.
      final run = buildProjectRunScript(
        mapName: 'mixed',
        mapDirectory: '/maps/mixed',
        robots: const [pinky],
      );
      final cleanup = run.substring(
        run.indexOf('cleanup() {'),
        run.indexOf('trap cleanup'),
      );
      expect(cleanup, isNot(contains('rm -f')));
      expect(cleanup, contains('kill'));
    });

    test('출력을 파이프가 아니라 파일로 보낸다', () {
      // 앱이 파이프에 물려 띄우면, 읽는 쪽이 없을 때 64KB 가 차는 순간 Gazebo 가
      // write 에서 영원히 멈춘다. 물리가 돌지 않아 모델도 안 올라오고 토픽에
      // 값도 오지 않았다.
      final script = buildProjectRunScript(
        mapName: 'mixed',
        mapDirectory: '/maps/mixed',
        robots: const [pinky],
      );
      expect(script, contains(r'LOG_FILE="$MAP_DIR/mixed.log"'));
      // 거르는 awk 를 거쳐 파일로 간다. 이 awk 가 파이프를 쉬지 않고 읽으므로
      // 교착은 여전히 나지 않는다.
      expect(script, contains('exec > >(exec awk'));
      // 리다이렉트는 로봇을 띄우기 전에 걸려야 한다.
      expect(
        script.indexOf('exec > >(exec awk'),
        lessThan(script.indexOf('Gazebo bringup')),
      );
    });

    test('같은 줄이 반복되면 접어서 쓴다', () {
      // Gazebo 의 ODE 가 물리 스텝마다 같은 경고를 찍어 로그가 시간당 1.8GB 씩
      // 찼다. 실측 3.4GB 짜리가 남아 있었다.
      final script = buildProjectRunScript(
        mapName: 'mixed',
        mapDirectory: '/maps/mixed',
        robots: const [pinky],
      );
      expect(script, contains('if (signature == last_signature) {'));
      expect(
        script,
        contains(r'gsub(/\[[0-9]+\.[0-9]+\]/, "[time]", signature)'),
      );
      expect(script, contains('같은 줄 " dup "번 더'));
      // 넘치면 한 번 밀어 두고 새로 쓴다. 최대 두 배까지만 남는다.
      expect(script, contains(r'LOG_MAX_MB="${LOG_MAX_MB:-200}"'));
      expect(script, contains(r'maxmb * 1048576'));
    });

    test('에러만 따로 모은 파일을 하나 더 쓴다', () {
      // 에러만 남기면 안 된다. 원인을 알려 준 것은 대부분 ERROR 가 아니라
      // 뜨는 순서였다. 그래서 전체는 그대로 두고 요약을 따로 쓴다.
      final script = buildProjectRunScript(
        mapName: 'mixed',
        mapDirectory: '/maps/mixed',
        robots: const [pinky],
      );
      expect(script, contains(r'ERR_FILE="$MAP_DIR/mixed.err.log"'));
      expect(script, contains('Traceback'));
      expect(script, contains(r'print $0 > err'));
    });

    test('없으면 무엇을 빌드해야 하는지 알려 준다', () {
      // 예전에는 찾아본 경로 수십 개가 한 줄로 쏟아져 원인을 알기 어려웠다.
      final script = buildProjectRunScript(
        mapName: 'mixed',
        mapDirectory: '/maps/mixed',
        robots: const [pinky, omx],
      );
      expect(script, contains('없는 ROS 패키지'));
      expect(script, contains('colcon build'));
      expect(script, contains('ros2 pkg prefix'));
    });

    test('Gazebo 경로도 쓰는 것만 가리킨다', () {
      // 없는 패키지를 가리키면 launch 가 통째로 멈춘다.
      final mixed = buildProjectBringupXml(
        mapName: 'mixed',
        robots: const [pinky, omx],
        mapDirectory: '/maps/mixed',
      );
      expect(mixed, contains('open_manipulator_description)/../'));
      final onlyPinky = buildProjectBringupXml(
        mapName: 'pinky',
        robots: const [pinky],
        mapDirectory: '/maps/pinky',
      );
      expect(onlyPinky, contains('pinky_description)/../'));
      expect(onlyPinky, isNot(contains('open_manipulator_description')));
    });

    test('Mock 만 있으면 로봇 패키지를 요구하지 않는다', () {
      final script = buildProjectRunScript(
        mapName: 'mockonly',
        mapDirectory: '/maps/mockonly',
        robots: const [
          RmfProjectRobot(
            robotId: 'MK-01',
            displayName: '연습',
            model: 'PINKY-GZ',
            gzName: 'mock_01',
            zones: [],
          ),
        ],
      );
      expect(script, isNot(contains('pinky_description')));
      expect(script, isNot(contains('open_manipulator_description')));
    });
  });

  group('중지 스크립트', () {
    final script = buildProjectStopScript(
      mapName: 'gwanghee',
      mapDirectory: '/maps/gwanghee',
    );

    test('이 맵을 물고 남은 노드를 쓸어낸다', () {
      // ros2 launch 가 죽으면 자식이 init 으로 재부모화된다. 그룹도 잃고
      // `ros2 launch <경로>` 라는 이름도 잃어서 이름·PGID 로는 못 잡는다.
      // fleet_manager 가 그렇게 남아 `백엔드 중지` 를 눌러도 살아 있었다.
      expect(script, contains('sweep_map_dir'));
      expect(script, contains(r'/proc/$pid/cmdline'));
      expect(script, contains('이 맵을 물고 남은 노드'));
    });

    test('제 자신은 죽이지 않는다', () {
      // 스크립트 경로에도 맵 디렉터리가 들어 있다. 거르지 않으면 자기를 끊는다.
      expect(script, contains('stop_gwanghee.sh'));
      expect(script, contains(r'"$pid" == "$$"'));
      expect(script, contains(r'"$pid" == "$PPID"'));
    });

    test('응답이 없으면 강제 종료까지 올라간다', () {
      // rclpy 노드는 TERM 을 받고도 종료 중에 굳는 일이 있다. 거기서 멈추면
      // 노드가 살아남아 다음 실행에서 이름이 겹친다.
      expect(script, contains('for signal in INT TERM KILL'));
      expect(script, contains('응답이 없어 강제 종료합니다'));
    });

    test('좀비는 기다리지 않는다', () {
      // 이미 끝난 것을 두고 매 단계 3초씩 기다리면 중지가 괜히 느려진다.
      expect(script, contains(r'*Z*'));
    });

    test('네임스페이스로도 쓸어낸다', () {
      // robot_state_publisher 는 인자에 맵 경로가 없다. URDF 만 들고 있어서
      // 경로로는 못 찾는다. 대신 ROS 가 넣어 준 __ns:=/<gz 이름> 을 들고 있다.
      final withRobots = buildProjectStopScript(
        mapName: 'gwanghee',
        mapDirectory: '/maps/gwanghee',
        robots: const [
          RmfProjectRobot(
            robotId: 'PK-01',
            displayName: 'p',
            model: 'PINKY-GZ',
            dataSource: RobotDataSource.gazebo,
            gzName: 'pinky_01',
            zones: [],
          ),
          RmfProjectRobot(
            robotId: 'MK-01',
            displayName: 'm',
            model: 'PINKY-GZ',
            gzName: 'mock_01',
            zones: [],
          ),
        ],
      );
      expect(withRobots, contains('ROBOT_NAMESPACES="pinky_01"'));
      expect(withRobots, contains(r'__ns:=/$ns'));
      // Gazebo 로 돌리지 않는 로봇은 띄운 적이 없으니 내릴 것도 없다.
      expect(withRobots, isNot(contains('mock_01')));
    });

    test('RMF core 도 마지막에 쓸어낸다', () {
      // schedule node 나 supervisor 는 인자에 맵 경로도 로봇 네임스페이스도
      // 없다. launch 가 죽고 PGID 파일까지 없으면 어떤 방법으로도 못 찾는다.
      expect(script, contains('sweep_rmf_core'));
      expect(script, contains('RMF core'));
      expect(script, contains('/install/rmf_'));
    });

    test('이름 없는 고아도 실행 잠금 FD로 찾아 종료한다', () {
      expect(script, contains('sweep_lock_holders'));
      expect(script, contains('/proc/[0-9]*/fd/*'));
      expect(script, contains(r'readlink "$fd"'));
      expect(script, contains('실행 잠금 보유 프로세스'));
    });

    test('마지막에 잠금과 좀비를 다시 검증한다', () {
      expect(script, contains(r'flock -n "$LOCK_FILE" true'));
      expect(script, contains('실행 잠금이 아직 사용 중입니다'));
      expect(script, contains(r'$4 ~ /^Z/'));
      expect(script, contains('관련 좀비 프로세스가 남았습니다'));
    });

    test('없어진 프로세스에 대해 잔소리하지 않는다', () {
      // pgrep 과 /proc 읽기 사이에 끝난 프로세스가 있다. 2>/dev/null 을 입력
      // 리다이렉트보다 먼저 걸어야 셸이 오류를 찍지 않는다.
      final redirect = script.indexOf('< "/proc/');
      final suppress = script.indexOf('2>/dev/null', script.indexOf('args="'));
      expect(suppress, lessThan(redirect));
    });

    test('로봇이 없어도 스크립트가 돈다', () {
      expect(script, contains('ROBOT_NAMESPACES=""'));
      expect(script, contains('sweep_namespaces'));
    });

    test('다른 맵은 건드리지 않는다', () {
      expect(script, contains(r'MAP_DIR="${MAP_DIR:-/maps/gwanghee}"'));
      expect(script, isNot(contains('tinyRobot')));
    });
  });

  group('프로젝트 launch', () {
    test('경로가 전부 이 프로젝트 것으로 박힌다', () {
      final xml = buildProjectLaunchXml(
        mapName: 'gwanghee',
        fleetName: 'gwanghee_pinky',
        mapDirectory: '/home/gyi/robosapiens/rmf_maps/gwanghee',
        buildingYamlName: 'gwanghee.building.yaml',
      );
      // 맵마다 building.yaml 도 nav graph 도 플릿 설정도 다르다. 하나라도
      // 데모 것을 가리키면 지난번처럼 tinyRobot 설정으로 돌아간다.
      expect(
        xml,
        contains(
          '<arg name="map_dir" default='
          '"/home/gyi/robosapiens/rmf_maps/gwanghee"/>',
        ),
      );
      // building_map_server 가 이 맵의 building.yaml 을 물어야 한다.
      expect(xml, contains(r'args="$(var map_dir)/gwanghee.building.yaml"'));
      expect(
        xml,
        contains(
          r'<arg name="config_file" value="$(var map_dir)'
          '/gwanghee_pinky_config.yaml"/>',
        ),
      );
      expect(
        xml,
        contains(
          r'<arg name="nav_graph_file" value="$(var map_dir)'
          '/nav_graphs/0.yaml"/>',
        ),
      );
      expect(xml, isNot(contains('tinyRobot')));
      expect(xml, isNot(contains('office')));
    });

    test('RMF core 와 fleet adapter 를 함께 띄운다', () {
      final xml = buildProjectLaunchXml(
        mapName: 'gwanghee',
        fleetName: 'gwanghee_pinky',
        mapDirectory: '/maps/gwanghee',
        buildingYamlName: 'gwanghee.building.yaml',
      );
      // core 가 먼저 떠야 fleet adapter 가 붙는다. 지난 실패가 그것이었다.
      //
      // core 는 rmf_demos 의 common.launch.xml 을 include 하지 않고 같은
      // 내용을 편 것이다 — 그 파일이 시각화에 Lane 굵기를 넘기지 않는다.
      // 그래서 그 파일이 띄우는 것을 하나도 빠뜨리지 않았는지 여기서 지킨다.
      for (final node in const [
        'rmf_traffic_schedule',
        'rmf_traffic_blockade',
        'building_map_server',
        'visualization.launch.xml',
        'door_supervisor',
        'lift_supervisor',
        'mutex_group_supervisor',
        'rmf_task_dispatcher',
      ]) {
        expect(xml, contains(node), reason: 'RMF core 에 \$node 가 빠졌다');
      }
      expect(xml, contains('rmf_demos_fleet_adapter'));
      expect(
        xml.indexOf('rmf_traffic_schedule'),
        lessThan(xml.indexOf('rmf_demos_fleet_adapter')),
      );
    });

    test('Nav2 로 도는 로봇이 있으면 slotcar 어댑터를 안 붙인다', () {
      // rmf_demos_fleet_adapter 는 Gazebo 안의 slotcar 플러그인에게 직접
      // 명령한다. 토픽으로 도는 핑키에게는 상대가 없다. 그런데도 붙여 놓아
      // 설정에 user 가 없다며 죽었고, 죽은 줄 모른 채 "배차는 됐는데 로봇이
      // 안 움직인다" 로 보였다.
      const pinky = RmfProjectRobot(
        robotId: 'PK-01',
        displayName: '핑키 1호',
        model: 'PINKY-GZ',
        gzName: 'pinky_01',
        zones: ['ambient'],
        chargerWaypoint: '충전1',
        dataSource: RobotDataSource.gazebo,
      );
      final xml = buildProjectLaunchXml(
        mapName: 'gwanghee',
        fleetName: 'gwanghee_pinky',
        mapDirectory: '/maps/gwanghee',
        buildingYamlName: 'gwanghee.building.yaml',
        robots: const [pinky],
      );
      expect(xml, contains('rmf_traffic_schedule'));
      expect(xml, isNot(contains('rmf_demos_fleet_adapter)')));
      // 어디로 갔는지는 파일 안에 적혀 있어야 한다.
      expect(xml, contains('gwanghee_nav2.launch.xml'));

      // Mock 만 있는 프로젝트는 예전 그대로다.
      final mock = buildProjectLaunchXml(
        mapName: 'gwanghee',
        fleetName: 'gwanghee_pinky',
        mapDirectory: '/maps/gwanghee',
        buildingYamlName: 'gwanghee.building.yaml',
        robots: const [
          RmfProjectRobot(
            robotId: 'PK-01',
            displayName: '핑키 1호',
            model: 'PINKY-GZ',
            gzName: 'pinky_01',
            zones: ['ambient'],
          ),
        ],
      );
      expect(mock, contains('rmf_demos_fleet_adapter'));
    });

    test('실행 스크립트가 Nav2 와 어댑터를 RMF 다음에 띄운다', () {
      // 이것이 빠져 있어 /pinky_01/cmd_vel 에 발행하는 것이 하나도 없었다.
      // 실측: Publisher count 0.
      const pinky = RmfProjectRobot(
        robotId: 'PK-01',
        displayName: '핑키 1호',
        model: 'PINKY-GZ',
        gzName: 'pinky_01',
        zones: ['ambient'],
        chargerWaypoint: '충전1',
        dataSource: RobotDataSource.gazebo,
      );
      final script = buildProjectRunScript(
        mapName: 'gwanghee',
        mapDirectory: '/maps/gwanghee',
        robots: const [pinky],
      );
      expect(script, contains('[3/3] Nav2 와 RMF 어댑터'));
      expect(script, contains('gwanghee_nav2.launch.xml'));
      // RMF core 가 먼저라야 어댑터가 schedule node 를 찾는다.
      expect(
        script.indexOf('gwanghee.launch.xml'),
        lessThan(script.indexOf('gwanghee_nav2.launch.xml')),
      );
      expect(script, contains('flock -n 9'));
      expect(script, contains('last_signature'));
      expect(
        script,
        contains(r'gsub(/\[[0-9]+\.[0-9]+\]/, "[time]", signature)'),
      );
    });

    test('기본으로는 rmf-web 주소를 안 넘긴다', () {
      // 주소를 넘기면 dispatcher 가 1초마다 영원히 다시 붙으려 하고, 그 여덟
      // 줄이 로그를 채워 정작 볼 [PK-01] 줄을 덮는다.
      final xml = buildProjectLaunchXml(
        mapName: 'gwanghee',
        fleetName: 'gwanghee_pinky',
        mapDirectory: '/maps/gwanghee',
        buildingYamlName: 'gwanghee.building.yaml',
      );
      expect(xml, contains('<arg name="server_uri" default=""/>'));
      expect(xml, isNot(contains('ws://127.0.0.1:8000')));
      // 왜 비었는지는 파일 안에 적혀 있어야 한다.
      expect(xml, contains('rmf-web 을 안 씁니다'));
    });

    test('띄웠으면 rmf-web 주소를 넘긴다', () {
      final xml = buildProjectLaunchXml(
        mapName: 'gwanghee',
        fleetName: 'f',
        mapDirectory: '/maps/gwanghee',
        buildingYamlName: 'b.yaml',
        serverUri: 'ws://127.0.0.1:8000/_internal',
      );
      expect(xml, contains('ws://127.0.0.1:8000/_internal'));
    });
  });

  group('자리를 안 고른 로봇', () {
    // 자리를 조용히 지우는 버그가 있었다. 창을 열었다 닫기만 해도 충전1 이
    // 사라졌고, 자리가 없으면 spawn 좌표도 없어져 Gazebo 에 로봇이 아예 안
    // 올라갔다 — 토픽이 하나도 안 나온 원인이다.
    const noStation = RmfProjectRobot(
      robotId: 'PK-01',
      displayName: '핑키 1호',
      model: 'PINKY-GZ',
      gzName: 'pinky_01',
      zones: ['ambient'],
      dataSource: RobotDataSource.gazebo,
    );

    test('bringup 이 조용히 넘기지 않는다', () {
      final xml = buildProjectBringupXml(
        mapName: 'gwanghee',
        robots: const [noStation],
        mapDirectory: '/maps/gwanghee',
      );
      expect(xml, contains('spawn 좌표가 없다'));
      expect(xml, contains('지도 원점에 놓인다'));
      // 그래도 올리기는 한다. 안 올리면 왜 없는지 알 데가 없다.
      expect(xml, contains('PK-01/spawn.launch.xml'));
    });

    test('자리가 있으면 그 말은 안 나온다', () {
      const placed = RmfProjectRobot(
        robotId: 'PK-01',
        displayName: '핑키 1호',
        model: 'PINKY-GZ',
        gzName: 'pinky_01',
        zones: ['ambient'],
        dataSource: RobotDataSource.gazebo,
        chargerWaypoint: '충전1',
        spawnX: 1.761,
        spawnY: -1.025,
      );
      final xml = buildProjectBringupXml(
        mapName: 'gwanghee',
        robots: const [placed],
        mapDirectory: '/maps/gwanghee',
      );
      expect(xml, isNot(contains('spawn 좌표가 없다')));
    });
  });

  group('빈 목록으로 덮어쓰지 않는다', () {
    // MySQL 에는 로봇 셋이 있는데 fleet.yaml 은 "등록된 로봇이 없다" 였고,
    // bringup 에 로봇이 하나도 안 실려 Gazebo 에 아무것도 안 올라갔다.
    test('로봇 저장은 지우고 다시 넣는다 — 빈 목록이면 다 사라진다', () {
      final source = File('lib/map_project_store_io.dart').readAsStringSync();
      expect(source, contains('DELETE FROM map_project_robots'));
      // 그래서 설정만 저장하는 길이 따로 있어야 한다.
      expect(source, contains('Future<void> saveMapProjectFleetSettings('));
    });

    test('배포는 저장된 로봇에서 산출물을 만든다', () {
      // 화면이 들고 있는 목록은 지금 열린 프로젝트의 것이다. 다른 화면에서
      // 등록만 해 두고 오면 비어 있다.
      final source = File('lib/main.dart').readAsStringSync();
      expect(source, contains('_fleetRobotsForDeploy(mapName)'));
      expect(source, contains('robots: deployRobots'));
      expect(source, contains('if (_fleetRobots.isNotEmpty) {'));
    });
  });
}
