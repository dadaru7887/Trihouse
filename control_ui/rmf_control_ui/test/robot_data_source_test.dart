import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/rmf_project_config.dart';
import 'package:rmf_control_ui/robot_data_source.dart';

/// 작업 상세에 보이는 숫자가 어디서 온 것인지 가리는 규칙.
///
/// 앱이 계산한 값과 실물에서 온 값이 같은 자리에 같은 모양으로 보인다. 어느
/// 쪽인지 틀리게 알리면 Mock 주행을 실제 상태로 착각한다.
void main() {
  const pinky = RmfProjectRobot(
    robotId: 'PK-01',
    displayName: '핑키 1호',
    model: 'PINKY-GZ',
    gzName: 'pinky_01',
    dataSource: RobotDataSource.gazebo,
    zones: ['ambient'],
    chargerWaypoint: '충전1',
  );
  const omx = RmfProjectRobot(
    robotId: 'OMX-01',
    displayName: '매니퓰레이터 1호',
    model: 'open_manipulator_x',
    kind: RmfRobotKind.workcell,
    dataSource: RobotDataSource.gazebo,
    gzName: 'omx_01',
    zones: [],
    chargerWaypoint: 'OMX1',
  );

  group('출처 구분', () {
    test('Mock 만 토픽을 쓰지 않는다', () {
      expect(RobotDataSource.mock.usesTopics, isFalse);
      expect(RobotDataSource.gazebo.usesTopics, isTrue);
      expect(RobotDataSource.real.usesTopics, isTrue);
    });

    test('셋 다 서로 다른 이름을 가진다', () {
      final labels = RobotDataSource.values.map((s) => s.label).toSet();
      expect(labels.length, RobotDataSource.values.length);
    });
  });

  group('고른 방식과 실제 출처', () {
    test('구독이 없으면 무엇을 골랐든 값은 Mock 이다', () {
      // 이것이 핵심이다. Gazebo 를 골랐다는 이유로 Gazebo 값이라고 표시하면
      // 앱이 계산한 숫자를 실물로 착각하게 만든다.
      for (final selected in RobotDataSource.values) {
        expect(
          effectiveDataSource(selected: selected, topicsConnected: false),
          RobotDataSource.mock,
          reason: '$selected 를 골라도 구독이 없으면 Mock 이다',
        );
      }
    });

    test('구독이 붙으면 고른 방식이 그대로 출처가 된다', () {
      expect(
        effectiveDataSource(
          selected: RobotDataSource.gazebo,
          topicsConnected: true,
        ),
        RobotDataSource.gazebo,
      );
      expect(
        effectiveDataSource(
          selected: RobotDataSource.real,
          topicsConnected: true,
        ),
        RobotDataSource.real,
      );
    });

    test('어긋난 경우에만 경고한다', () {
      expect(
        dataSourceMismatch(
          selected: RobotDataSource.gazebo,
          topicsConnected: false,
        ),
        isTrue,
      );
      expect(
        dataSourceMismatch(
          selected: RobotDataSource.gazebo,
          topicsConnected: true,
        ),
        isFalse,
      );
      // Mock 을 골라 Mock 이 나오는 것은 어긋난 것이 아니다.
      expect(
        dataSourceMismatch(
          selected: RobotDataSource.mock,
          topicsConnected: false,
        ),
        isFalse,
      );
    });
  });

  group('토픽 이름', () {
    test('이동 로봇은 주행에 필요한 것을 모두 주고받는다', () {
      final topics = robotTopics(pinky);
      expect(topics.incoming, [
        '/pinky_01/odom',
        '/pinky_01/scan',
        '/pinky_01/imu_raw',
        '/pinky_01/joint_states',
      ]);
      expect(topics.outgoing, ['/pinky_01/cmd_vel']);
    });

    test('토픽마다 무엇인지 사람 말로 적어 둔다', () {
      // 이름만 보고 무엇인지 알 수 있는 사람은 많지 않다.
      final detail = robotTopicDetails(pinky);
      expect(detail, isNotEmpty);
      for (final topic in detail) {
        expect(topic.what, isNotEmpty, reason: '${topic.name} 설명이 없습니다');
        expect(topic.type, contains('/'), reason: '${topic.name} 형식이 없습니다');
      }
      final scan = detail.firstWhere((t) => t.name.endsWith('/scan'));
      expect(scan.incoming, isTrue);
      final cmd = detail.firstWhere((t) => t.name.endsWith('/cmd_vel'));
      expect(cmd.incoming, isFalse, reason: 'cmd_vel 은 로봇에게 가는 것이다');
    });

    test('Mock 로봇은 토픽이 하나도 없다', () {
      // 앱 안에만 있는 로봇이라 주고받을 상대가 없다. 적어 두면 오지 않을 것을
      // 기다리는 것처럼 보인다.
      const mock = RmfProjectRobot(
        robotId: 'MK-01',
        displayName: '연습용',
        model: 'PINKY-GZ',
        gzName: 'mock_01',
        zones: ['ambient'],
      );
      expect(robotTopicDetails(mock), isEmpty);
      expect(robotTopics(mock).incoming, isEmpty);
      expect(robotTopics(mock).outgoing, isEmpty);
    });

    test('실물과 Gazebo 는 토픽이 같다', () {
      // 같은 이름으로 같은 형식을 주고받아야 위쪽이 그대로 돈다.
      const real = RmfProjectRobot(
        robotId: 'PK-01',
        displayName: '핑키 1호',
        model: 'PINKY-GZ',
        gzName: 'pinky_01',
        zones: ['ambient'],
        dataSource: RobotDataSource.real,
      );
      expect(
        robotTopicDetails(real).map((t) => t.name),
        robotTopicDetails(pinky).map((t) => t.name),
      );
    });

    test('설치 로봇은 관절 상태만 온다', () {
      // 바퀴도 LiDAR 도 없다. 있지도 않은 토픽을 알려주면 없는 것을 찾게 된다.
      final topics = robotTopics(omx);
      expect(topics.incoming, ['/omx_01/joint_states']);
      expect(topics.outgoing, isEmpty);
    });

    test('등록 정보가 없으면 아무 이름도 지어내지 않는다', () {
      final topics = robotTopics(null);
      expect(topics.incoming, isEmpty);
      expect(topics.outgoing, isEmpty);
    });

    test('이동 로봇이 알려 주는 이름은 다리 설정에 다 있다', () {
      // 화면과 <맵이름>_gz_bridge.yaml 이 다르면, 있는 줄 알고 찾다가 못 찾는다.
      //
      // 설치 로봇은 견주지 않는다. 그 토픽은 다리를 거치지 않기 때문이다 —
      // gz_ros2_control 이 Gazebo 안에서 controller_manager 를 띄우고
      // joint_state_broadcaster 가 ROS 로 직접 낸다. 다리 설정에 없는 것이
      // 맞고, 그래도 화면에는 나와야 한다.
      final bridge = buildProjectGzBridgeYaml(
        mapName: 'gwanghee',
        robots: const [pinky, omx],
      );
      final topics = robotTopics(pinky);
      for (final topic in [...topics.incoming, ...topics.outgoing]) {
        // 화면에는 Nav2가 내는 원본 명령을 보여 준다. Gazebo 다리는 그 명령을
        // 직접 받지 않고 velocity_smoother의 최종 출력만 받아야 한다.
        final bridgedTopic = topic.endsWith('/cmd_vel')
            ? '${topic}_smoothed'
            : topic;
        expect(
          bridge,
          contains('ros_topic_name: "$bridgedTopic"'),
          reason: '$bridgedTopic 이 다리 설정에 없다',
        );
      }
    });

    test('설치 로봇 토픽은 다리에 없어도 화면에는 나온다', () {
      // ros2_control 이 직접 내는 것이라 다리 설정에서는 찾을 수 없다.
      final bridge = buildProjectGzBridgeYaml(
        mapName: 'gwanghee',
        robots: const [pinky, omx],
      );
      expect(robotTopics(omx).incoming, ['/omx_01/joint_states']);
      expect(bridge, isNot(contains('ros_topic_name: "/omx_01/joint_states"')));
    });
  });
}
