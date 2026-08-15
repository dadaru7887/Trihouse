/// RMF 와 Nav2 를 잇는 어댑터 스크립트.
///
/// 지금까지 이 고리가 끊겨 있었다 — /robot_state 는 발행자가 0명이고
/// /robot_path_requests 는 구독자가 0명이었다. 저 두 토픽은 RMF 시범
/// 로봇(slotcar)의 것이라 우리 핑키에게는 상대가 없다.
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
    chargerWaypoint: '충전1',
    spawnX: 1.76,
    spawnY: -0.64,
  );
  const pinkyTwo = RmfProjectRobot(
    robotId: 'PK-02',
    displayName: '핑키 2호',
    model: 'PINKY-GZ',
    gzName: 'pinky_02',
    zones: ['ambient'],
    dataSource: RobotDataSource.gazebo,
    chargerWaypoint: '충전2',
  );
  const omx = RmfProjectRobot(
    robotId: 'OMX-01',
    displayName: '매니퓰레이터 1호',
    model: 'open_manipulator_x',
    kind: RmfRobotKind.workcell,
    gzName: 'omx_01',
    zones: [],
    dataSource: RobotDataSource.gazebo,
  );
  const mock = RmfProjectRobot(
    robotId: 'MK-01',
    displayName: '연습용',
    model: 'PINKY-GZ',
    gzName: 'mock_01',
    zones: ['ambient'],
  );

  final script = buildNav2FleetAdapterScript(
    mapName: 'gwanghee',
    fleetName: 'gwanghee_pinky',
    robots: const [pinky, pinkyTwo, omx, mock],
  );

  group('이름 짝짓기', () {
    test('RMF 가 아는 이름과 ROS 네임스페이스를 이어 준다', () {
      // 둘이 다르다. RMF 는 PK-01 을 알고 ROS 는 pinky_01 을 안다.
      expect(script, contains("'PK-01': 'pinky_01',"));
      expect(script, contains("'PK-02': 'pinky_02',"));
    });

    test('설치 로봇과 Mock 은 넣지 않는다', () {
      // 설치 로봇은 배차 대상이 아니고 Mock 은 실제로 없는 로봇이다.
      expect(script, isNot(contains('OMX-01')));
      expect(script, isNot(contains('MK-01')));
    });
  });

  group('무엇을 잇는가', () {
    test('RMF 의 목적지를 Nav2 의 NavigateToPose 로 바꾼다', () {
      expect(script, contains('from nav2_msgs.action import NavigateToPose'));
      expect(script, contains("f'/{namespace}/navigate_to_pose'"));
    });

    test('위치는 TF 에서 읽는다 — AMCL 이 map -> odom 을 낸다', () {
      expect(script, contains("f'{self.namespace}/base_footprint'"));
    });

    test('slotcar 토픽은 쓰지 않는다', () {
      // 그 둘이 이번 문제의 원인이었다.
      expect(script, isNot(contains('robot_path_requests')));
      expect(script, isNot(contains('robot_state_msgs')));
    });
  });

  group('끝났다고 알리기', () {
    test('도착하면 RMF 에 알린다', () {
      expect(script, contains('execution.finished()'));
    });

    test('Nav2 가 없거나 거절해도 붙잡고 있지 않는다', () {
      // 안 알리면 그 작업이 영영 안 끝난다.
      expect(script, contains('Nav2 가 없습니다'));
      expect(script, contains('Nav2 가 거절했습니다'));
    });

    test('선점된 예전 목표의 취소 결과가 현재 실행을 끝내지 않는다', () {
      expect(script, contains('self.goal_generation += 1'));
      expect(script, contains('generation != self.goal_generation'));
      expect(script, contains('self.execution is not execution'));
      expect(
        script,
        contains(
          'lambda done: self.on_goal_result(done, generation, execution)',
        ),
      );
    });

    test('armLoad를 워크셀 요청으로 보내고 성공 뒤 끝낸다', () {
      expect(script, contains('def execute_action'));
      expect(script, contains('execution.finished()'));
      expect(script, contains("DispenserRequest, '/dispenser_requests'"));
      expect(script, contains("DispenserResult, '/dispenser_results'"));
      expect(script, contains("target_guid = description.get('target_guid')"));
      expect(script, contains("item_type = str(description.get('item_type')"));
      expect(script, contains('DispenserRequestItem()'));
      expect(script, contains('request.items = [item]'));
      expect(script, contains('result.status != DispenserResult.SUCCESS'));
    });

    test('진행 상황을 앱이 읽을 수 있게 낸다', () {
      // RMF 의 작업 상태는 rmf-web 웹소켓으로만 나간다. 웹서버를 안 띄우면
      // 어디에서도 볼 수 없다. 목적지를 하나씩 받는 것은 이 어댑터다.
      expect(
        script,
        contains("PROGRESS_TOPIC = 'gwanghee_pinky/task_progress'"),
      );
      expect(script, contains("event='navigate_start'"));
      expect(script, contains("event='navigate_done'"));
      expect(script, contains("event='action_start'"));
      expect(script, contains("event='action_done'"));
    });
  });

  group('붙지 못할 때', () {
    test('자리가 nav graph 에서 멀면 다시 해 보고 한 번만 알린다', () {
      // 0.1초마다 같은 말을 되풀이하면 로그를 읽을 수 없다.
      expect(script, contains('if not self.warned:'));
      expect(script, contains('nav graph 에서'));
    });
  });

  group('실패를 도착이라고 하지 않는다', () {
    test('Nav2 결과를 보고 가른다', () {
      // 안 보고 끝났다고 알리면 RMF 는 그 자리에 닿은 줄 알고 다음 단계로
      // 넘어간다. 픽업에 가지도 않았는데 드랍오프로 가는 것이 이것이었다.
      expect(script, contains('from action_msgs.msg import GoalStatus'));
      expect(script, contains('GoalStatus.STATUS_SUCCEEDED'));
      expect(script, contains("event='navigate_failed'"));
      expect(script, contains('목적지에 닿지 못했습니다'));
    });

    test('실패해도 붙잡고 있지 않는다', () {
      // 안 알리면 그 작업이 영영 안 끝난다.
      final tail = script.substring(script.indexOf('def on_goal_result'));
      expect(
        tail.substring(0, 1400),
        contains('self.finish(generation, execution)'),
      );
    });
  });
}
