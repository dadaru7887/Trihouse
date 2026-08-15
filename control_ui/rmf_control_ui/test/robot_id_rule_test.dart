/// 로봇 ID 는 ROS 2 이름 규칙을 지켜야 한다.
///
/// RMF 는 플릿 로봇마다 `rmf/dynamic_event/begin/<플릿>/<로봇>` 토픽을 만든다.
/// 토픽 이름에 하이픈을 못 쓰므로 `PK-01` 은 fleet adapter 를 죽인다:
///
///   terminate called after throwing an instance of
///     'rclcpp::exceptions::InvalidTopicNameError'
///   what():  Invalid topic name: ... 'rmf/dynamic_event/begin/project1_pinky/PK-02'
///
/// 죽는 것은 adapter 하나뿐이라 Gazebo·Nav2·RMF core 는 남는다. 그래서 토픽은
/// 오는데 주문만 안 먹었다.
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/rmf_project_config.dart';
import 'package:rmf_control_ui/robot_id_rule.dart';

void main() {
  RmfProjectRobot robot({
    required String id,
    RmfRobotKind kind = RmfRobotKind.mobile,
    RobotDataSource source = RobotDataSource.gazebo,
  }) => RmfProjectRobot(
    robotId: id,
    displayName: id,
    model: 'PINKY-GZ',
    kind: kind,
    dataSource: source,
    gzName: 'pinky_01',
    zones: const [],
    chargerWaypoint: '충전1',
  );

  group('ID 규칙', () {
    test('하이픈은 못 쓴다', () {
      expect(isValidRobotId('PK-01'), isFalse);
      expect(robotIdProblem('PK-01'), contains('영문·숫자·밑줄'));
      // 왜 안 되는지 함께 적는다. 규칙만 적으면 앱이 까다로운 줄 안다.
      expect(robotIdProblem('PK-01'), contains('fleet adapter'));
    });

    test('밑줄은 쓸 수 있다', () {
      expect(isValidRobotId('PK_01'), isTrue);
      expect(isValidRobotId('OMX_01'), isTrue);
      expect(robotIdProblem('PK_01'), isNull);
    });

    test('숫자로 시작할 수 없다', () {
      expect(isValidRobotId('01PK'), isFalse);
      expect(robotIdProblem('01PK'), contains('숫자로 시작'));
    });

    test('한글도 토픽 이름에 못 들어간다', () {
      expect(isValidRobotId('핑키1'), isFalse);
    });

    test('빈 값은 이유를 따로 말한다', () {
      expect(robotIdProblem('   '), contains('적어야'));
    });
  });

  group('고쳐 주기', () {
    test('하이픈을 밑줄로 바꾼다', () {
      expect(normalizeRobotId('PK-01'), 'PK_01');
      expect(normalizeRobotId('OMX-01'), 'OMX_01');
    });

    test('빈칸과 점도 바꾼다', () {
      expect(normalizeRobotId('PK 01'), 'PK_01');
      expect(normalizeRobotId('pk.01'), 'pk_01');
    });

    test('숫자로 시작하면 앞에 R 을 붙여 살린다', () {
      // 지워 버리면 사람이 친 것이 사라진다. 쓸 수 있는 이름으로 바꿔 준다.
      expect(normalizeRobotId('01'), 'R01');
    });

    test('멀쩡한 것은 그대로 둔다', () {
      expect(normalizeRobotId('PK_01'), 'PK_01');
      // 치는 도중의 빈 값도 그대로. 여기서 R 을 붙이면 칸을 비울 수 없다.
      expect(normalizeRobotId(''), '');
    });
  });

  group('등록에 없는 ID', () {
    test('없으면 무엇이 없는지와 지금 있는 것을 함께 알린다', () {
      // 등록을 지웠거나 ID 를 고치면 지도와 작업에는 옛 ID 가 남는다. 하이픈을
      // 밑줄로 바꾸게 되면서 이 어긋남이 반드시 생긴다.
      final message = unregisteredRobotMessage([
        robot(id: 'PK_01'),
        robot(id: 'PK_02'),
      ], 'PK-01');
      expect(message, contains('등록된 로봇 ID 가 없습니다: PK-01'));
      // 지금 무엇이 있는지 보여 줘야 무엇으로 바뀌었는지 안다.
      expect(message, contains('PK_01, PK_02'));
      // 그냥 두면 어떻게 되는지도 적는다. 조용히 Mock 으로 도는 것이 가장 나쁘다.
      expect(message, contains('앱 안에서만'));
    });

    test('하나도 없으면 그렇게 말한다', () {
      final message = unregisteredRobotMessage(const [], 'PK_01');
      expect(message, contains('등록된 로봇이 하나도 없습니다'));
    });

    test('등록에 있으면 아무 말도 하지 않는다', () {
      expect(unregisteredRobotMessage([robot(id: 'PK_01')], 'PK_01'), isNull);
    });
  });

  group('배포 검사', () {
    test('플릿 로봇의 하이픈 ID 는 배포를 막는다', () {
      final robots = [robot(id: 'PK-01'), robot(id: 'PK_02')];
      expect(robotsWithInvalidId(robots).map((r) => r.robotId), ['PK-01']);
      final message = deployBlockedByRobotId(robots);
      expect(message, contains('PK-01'));
      // 무엇으로 바꾸면 되는지까지 적는다.
      expect(message, contains('PK_01 로 바꾸세요'));
    });

    test('설치 로봇은 막지 않는다', () {
      // 플릿에 안 들어가므로 dynamic event 토픽도 안 만들어진다. gwanghee 의
      // OMX-01 이 하이픈인데도 멀쩡했던 이유다.
      final robots = [robot(id: 'OMX-01', kind: RmfRobotKind.workcell)];
      expect(robotsWithInvalidId(robots), isEmpty);
      expect(deployBlockedByRobotId(robots), isNull);
    });

    test('Mock 로봇도 막지 않는다', () {
      final robots = [robot(id: 'PK-01', source: RobotDataSource.mock)];
      expect(robotsWithInvalidId(robots), isEmpty);
    });

    test('다 멀쩡하면 통과한다', () {
      expect(deployBlockedByRobotId([robot(id: 'PK_01')]), isNull);
      expect(deployBlockedByRobotId(const []), isNull);
    });
  });
}
