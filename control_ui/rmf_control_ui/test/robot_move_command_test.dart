/// 로봇 하나를 Waypoint 하나로 바로 보내는 명령을 지킨다.
///
/// 작업 목록과 다른 길이다. 작업은 단계를 엮고 저장하고 진행을 좇는 물건인데,
/// "저 로봇 저기로" 하나에 그것을 다 만드는 것은 과하다.
///
/// 가장 중요한 것은 **입찰이 아니라는 것**이다. 사람이 로봇을 이미 골랐는데
/// RMF 가 다른 로봇을 뽑으면 시킨 것과 다른 일이 벌어진다.
library;

import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/rmf_project_config.dart';
import 'package:rmf_control_ui/robot_move_command.dart';

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
  const arm = RmfProjectRobot(
    robotId: 'OMX_01',
    displayName: '매니퓰레이터 1호',
    model: 'OPENMANIPULATOR-X',
    gzName: 'omx_01',
    kind: RmfRobotKind.workcell,
    zones: ['ambient'],
    dataSource: RobotDataSource.gazebo,
  );

  group('고를 수 있는 Waypoint', () {
    test('이름 없는 자리는 뺀다', () {
      // RMF 는 좌표가 아니라 이름으로 자리를 찾는다. 이름이 없으면 보낼 수단이
      // 없는데, 목록에 넣으면 고른 뒤에야 그것을 알게 된다.
      final names = movableWaypointNames({
        const Offset(0, 0): '충전1',
        const Offset(1, 0): '',
        const Offset(2, 0): '   ',
        const Offset(3, 0): '픽업1',
      });
      expect(names, ['충전1', '픽업1']);
    });

    test('같은 이름은 한 번만 준다', () {
      final names = movableWaypointNames({
        const Offset(0, 0): '충전1',
        const Offset(1, 0): '충전1',
      });
      expect(names, ['충전1']);
    });

    test('가나다순으로 준다', () {
      // 지도에 놓인 순서는 사람에게 아무 뜻이 없다.
      final names = movableWaypointNames({
        const Offset(0, 0): '픽업1',
        const Offset(1, 0): '대기1',
        const Offset(2, 0): '충전1',
      });
      expect(names, ['대기1', '충전1', '픽업1']);
    });

    test('앞뒤 공백은 턴다', () {
      expect(movableWaypointNames({const Offset(0, 0): '  충전1 '}), ['충전1']);
    });
  });

  group('보낼 수 없는 경우를 미리 막는다', () {
    const places = ['충전1', '픽업1'];

    String? blocker({
      RmfProjectRobot? robot = pinky,
      bool backendRunning = true,
      List<String> waypoints = places,
      String? mapName = 'project1',
    }) => robotMoveBlocker(
      robot: robot,
      backendRunning: backendRunning,
      waypoints: waypoints,
      mapName: mapName,
    );

    test('갖출 것을 다 갖추면 막지 않는다', () {
      expect(blocker(), isNull);
    });

    test('등록되지 않은 로봇', () {
      // RMF 는 등록된 로봇만 안다. 그냥 보내면 조용히 무시당한다.
      expect(blocker(robot: null), contains('등록되어 있지 않습니다'));
    });

    test('설비 로봇은 자리를 못 옮긴다', () {
      expect(blocker(robot: arm), contains('설비 로봇'));
    });

    test('맵을 모르면', () {
      expect(blocker(mapName: ''), contains('어느 맵인지'));
      expect(blocker(mapName: null), contains('어느 맵인지'));
    });

    test('갈 곳이 없으면', () {
      expect(blocker(waypoints: const []), contains('Waypoint 가 없습니다'));
    });

    test('Open-RMF 가 안 떠 있으면', () {
      // 받을 쪽이 없으면 보내도 아무 일도 안 일어난다.
      expect(blocker(backendRunning: false), contains('떠 있지 않습니다'));
    });
  });

  group('만들어지는 요청', () {
    Map<String, Object?> decode() =>
        jsonDecode(
              buildRobotMoveRequest(
                fleetName: 'project1_pinky',
                robotId: 'PK_01',
                waypoint: '픽업1',
              ).json,
            )
            as Map<String, Object?>;

    test('입찰이 아니라 그 로봇에게 바로 간다', () {
      // dispatch_task_request 였다면 RMF 가 플릿에서 다른 로봇을 뽑을 수 있다.
      final json = decode();
      expect(json['type'], 'robot_task_request');
      expect(json['robot'], 'PK_01');
      expect(json['fleet'], 'project1_pinky');
    });

    test('동작은 go_to_place 하나뿐이다', () {
      final json = decode();
      final request = json['request']! as Map<String, Object?>;
      final description = request['description']! as Map<String, Object?>;
      final phases = description['phases']! as List<Object?>;
      final activity =
          (phases.single as Map<String, Object?>)['activity']!
              as Map<String, Object?>;
      final activities =
          (activity['description']! as Map<String, Object?>)['activities']!
              as List<Object?>;
      expect(activities, hasLength(1));
      final only = activities.single as Map<String, Object?>;
      expect(only['category'], 'go_to_place');
      // 좌표가 아니라 이름이라야 한다.
      expect(only['description'], '픽업1');
    });

    test('화면에 보일 이름을 붙인다', () {
      final request = decode()['request']! as Map<String, Object?>;
      final description = request['description']! as Map<String, Object?>;
      expect(description['category'], robotMoveCategory);
    });

    test('로봇을 안 주면 만들지 않는다', () {
      // 비우면 buildRmfTaskRequest 가 조용히 입찰 요청을 만든다. 사람이 고른
      // 로봇이 아닌 다른 로봇이 가는 것은 시킨 것과 다른 일이다.
      expect(
        () => buildRobotMoveRequest(
          fleetName: 'project1_pinky',
          robotId: '  ',
          waypoint: '픽업1',
        ),
        throwsArgumentError,
      );
    });

    test('목적지를 안 주면 만들지 않는다', () {
      expect(
        () => buildRobotMoveRequest(
          fleetName: 'project1_pinky',
          robotId: 'PK_01',
          waypoint: '   ',
        ),
        throwsArgumentError,
      );
    });
  });
}
