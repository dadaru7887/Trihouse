/// 설비 로봇이 RMF 워크셀로 이어지는지 지킨다.
///
/// 로봇이 픽업 자리에 닿으면 RMF 가 `/dispenser_requests` 에 그 자리 이름을
/// `target_guid` 로 낸다. **그 이름으로 답하는 노드가 없으면 RMF 는 영원히
/// 기다린다** — 오류는 안 나고 작업만 그 자리에서 멈춘다.
///
/// 등록에는 그 짝이 없다. 설비 로봇에는 `station: 설비2` 만 적혀 있고 그것은
/// nav graph 에 없는 이름이다. 그래서 자리로 짝을 짓는다.
///
/// 살아 있는 RMF 에 대고 돌려 확인한 값 —
///
///   [OMX_02] 픽업2 요청 받음 (test-1)
///   /dispenser_results  status 0 (ACKNOWLEDGED) → 1 (SUCCESS)
///   /omx_02/arm_controller/joint_trajectory 로 궤적 2건
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/rmf_project_config.dart';
import 'package:rmf_control_ui/workcell_pairing.dart';
import 'package:rmf_control_ui/workcell_policy.dart';

void main() {
  /// 이 맵의 실제 등록. 자리도 nav graph 에서 그대로 가져왔다.
  const omx1 = RmfProjectRobot(
    robotId: 'OMX_01',
    displayName: '매니퓰레이터 1호',
    model: 'open_manipulator_x',
    gzName: 'omx_01',
    zones: [],
    kind: RmfRobotKind.workcell,
    dataSource: RobotDataSource.gazebo,
    spawnX: .448,
    spawnY: -1.138,
  );
  const omx2 = RmfProjectRobot(
    robotId: 'OMX_02',
    displayName: '매니퓰레이터 2호',
    model: 'open_manipulator_x',
    gzName: 'omx_02',
    zones: [],
    kind: RmfRobotKind.workcell,
    dataSource: RobotDataSource.gazebo,
    spawnX: .409,
    spawnY: -2.187,
  );
  const omxFollower = RmfProjectRobot(
    robotId: 'OMX_F',
    displayName: 'OMX follower',
    model: 'omx_f',
    gzName: 'omx_f',
    zones: [],
    kind: RmfRobotKind.workcell,
    dataSource: RobotDataSource.gazebo,
    spawnX: .448,
    spawnY: -1.138,
  );
  const pinky = RmfProjectRobot(
    robotId: 'PK_02',
    displayName: '핑키 2호',
    model: 'PINKY-GZ',
    gzName: 'pinky_02',
    zones: ['ambient'],
    dataSource: RobotDataSource.gazebo,
    spawnX: 1.613,
    spawnY: -1.088,
  );

  const pickup1 = WorkcellStation(
    name: '픽업1',
    x: .454,
    y: -.869,
    isDispenser: true,
  );
  const pickup2 = WorkcellStation(
    name: '픽업2',
    x: .405,
    y: -1.964,
    isDispenser: true,
  );
  const dropoff1 = WorkcellStation(
    name: '드랍오프1',
    x: 1.924,
    y: -.286,
    isDispenser: false,
  );

  group('자리로 짝을 짓는다', () {
    test('가장 가까운 설비가 맡는다', () {
      final result = pairWorkcells(
        robots: const [omx1, omx2, pinky],
        stations: const [pickup1, pickup2],
      );
      expect(result.pairings, hasLength(2));
      final byId = {for (final p in result.pairings) p.robot.robotId: p};
      expect(byId['OMX_01']!.dispensers, ['픽업1']);
      expect(byId['OMX_02']!.dispensers, ['픽업2']);
    });

    test('이동 로봇은 워크셀이 아니다', () {
      // 핑키가 픽업 자리에 제일 가까이 서 있어도 그것을 맡을 수는 없다.
      final result = pairWorkcells(
        robots: const [pinky],
        stations: const [pickup2],
      );
      expect(result.pairings, isEmpty);
      expect(result.unservedWaypoints, ['픽업2']);
    });

    test('팔이 닿지 않는 자리는 맡기지 않는다', () {
      // 드랍오프1 은 가장 가까운 설비에서 1.7m 다. 억지로 맡기면 오지도 않을
      // 팔을 RMF 가 기다린다.
      final result = pairWorkcells(
        robots: const [omx1, omx2],
        stations: const [dropoff1],
      );
      expect(result.unservedWaypoints, ['드랍오프1']);
      expect(result.pairings, isEmpty);
    });

    test('맡을 설비가 없는 자리를 알린다', () {
      // 조용히 넘기면 그 자리로 보내는 작업이 RMF 안에서 영원히 멈춘다.
      final result = pairWorkcells(
        robots: const [omx2],
        stations: const [pickup1, pickup2],
      );
      expect(result.unservedWaypoints, ['픽업1']);
      expect(result.pairings.single.dispensers, ['픽업2']);
    });

    test('맡은 자리가 없는 설비를 알린다', () {
      final result = pairWorkcells(
        robots: const [omx1, omx2],
        stations: const [pickup2],
      );
      expect(result.idleWorkcells, ['OMX_01']);
    });

    test('한 설비가 픽업과 드랍오프를 함께 맡을 수 있다', () {
      const nearDropoff = WorkcellStation(
        name: '드랍오프2',
        x: .45,
        y: -2.1,
        isDispenser: false,
      );
      final result = pairWorkcells(
        robots: const [omx2],
        stations: const [pickup2, nearDropoff],
      );
      expect(result.pairings.single.dispensers, ['픽업2']);
      expect(result.pairings.single.ingestors, ['드랍오프2']);
    });
  });

  group('만들어지는 워크셀 노드', () {
    String script() => buildWorkcellScript(
      mapName: 'project1',
      pairing: pairWorkcells(
        robots: const [omx1, omx2],
        stations: const [pickup1, pickup2],
      ),
    );

    test('맡은 자리를 이름으로 적는다', () {
      final code = script();
      expect(
        code,
        contains("('OMX_02', 'omx_02', 'open_manipulator_x', ['픽업2'], [], [])"),
      );
      expect(
        code,
        contains("('OMX_01', 'omx_01', 'open_manipulator_x', ['픽업1'], [], [])"),
      );
    });

    test('상태를 낸다', () {
      // 상태가 안 오면 RMF 는 이 워크셀을 없는 것으로 보고 요청조차 안 한다.
      final code = script();
      expect(code, contains('/dispenser_states'));
      expect(code, contains('TRANSIENT_LOCAL'));
    });

    test('요청을 받고 결과를 낸다', () {
      final code = script();
      expect(code, contains('/dispenser_requests'));
      expect(code, contains('/dispenser_results'));
      expect(code, contains('DispenserResult.SUCCESS'));
    });

    test('같은 RMF 요청으로 팔을 두 번 움직이지 않는다', () {
      final code = script();
      expect(code, contains('self.completed_requests = set()'));
      expect(code, contains('msg.request_guid in cell.completed_requests'));
      expect(code, contains('cell.active_request == msg.request_guid'));
      expect(code, contains('cell.completed_requests.add(msg.request_guid)'));
    });

    test('느게 뜨어도 이미 보낸 픽업 요청을 받는다', () {
      final code = script();
      expect(
        code,
        contains(
          "DispenserRequest, '/dispenser_requests',\n"
          '            lambda msg: self.on_request(msg, dispenser=True), state_qos',
        ),
      );
    });

    test('팔에 궤적을 보낸다', () {
      final code = script();
      expect(code, contains('arm_controller/joint_trajectory'));
      expect(code, contains("'policy_1':"));
      expect(code, contains("'policy_5':"));
      expect(code, contains('msg.items[0].type_guid'));
      expect(code, contains('cell.run_policy(policy_id, ACTION_SECONDS)'));
      expect(code, contains('ARM_SETTLE_SECONDS = 3.0'));
      expect(
        code,
        contains(
          'self.create_timer(execution_seconds + ARM_SETTLE_SECONDS, finish)',
        ),
      );
      expect(code, contains('DispenserResult.FAILED'));
      expect(code, contains("policy_id == 'armLoad'"));
    });

    test('omx_f에 배포한 policy는 6축 controller 시험 동작으로 잇는다', () {
      final code = buildWorkcellScript(
        mapName: 'project1',
        pairing: pairWorkcells(
          robots: const [omxFollower],
          stations: const [pickup1],
        ),
        policies: [
          WorkcellPolicy(
            name: 'sandwich',
            version: '1.0.0',
            objectType: 'sandwich',
            robotModel: 'omx_f',
            archiveName: 'policy.zip',
            archiveBytes: 10,
            deployedWorkcells: const ['OMX_F'],
            createdAt: DateTime(2026),
          ),
        ],
      );
      expect(code, contains("'omx_f', ['픽업1'], [], ['sandwich@1.0.0']"));
      expect(
        code,
        contains(
          "['joint1', 'joint2', 'joint3', 'joint4', 'joint5', 'gripper_joint_1']",
        ),
      );
      expect(code, contains('cell.run_deployed_policy_test(policy_id'));
      expect(code, contains('ACT 추론 전 controller 시험 동작'));
      expect(code, contains('SANDWICH_REPLAY_DEG'));
      expect(code, contains('math.radians(value)'));
      expect(code, contains('cell.run_sandwich_replay(policy_id)'));
      expect(code, contains("replay_name in ('sandwich', 'sandwitch')"));
      expect(code, contains('학습 episode 0 샌드위치 동작 재생'));
    });

    test('하이픈이 든 프로젝트 이름도 유효한 ROS node 이름을 만든다', () {
      final code = buildWorkcellScript(
        mapName: 'project1-ver2',
        pairing: pairWorkcells(robots: const [omx2], stations: const [pickup2]),
      );
      expect(code, contains("super().__init__('project1_ver2_workcell')"));
      expect(
        code,
        isNot(contains("super().__init__('project1-ver2_workcell')")),
      );
    });

    test('handle 이라는 이름을 쓰지 않는다', () {
      // rclpy 의 Node 가 같은 이름의 속성을 쓴다. 메서드로 덮으면
      // Node.__init__ 이 `with self.handle:` 에서 TypeError 로 죽어 노드가
      // 아예 안 뜬다. 실제로 그렇게 죽었다.
      final code = script();
      expect(code, isNot(contains('def handle(')));
      expect(code, contains('def on_request('));
    });
  });

  group('실행 launch', () {
    test('워크셀 노드를 띄운다', () {
      final xml = buildProjectNav2LaunchXml(
        mapName: 'project1',
        robots: const [pinky, omx2],
        fleetName: 'project1_pinky',
      );
      expect(xml, contains('project1_workcell.py'));
    });
  });

  group('작업 policy 자동 구성', () {
    test('Gazebo 설비가 있으면 생성되는 다섯 policy를 고를 수 있다', () {
      expect(workcellPoliciesFor(const [pinky, omx2]), gazeboWorkcellPolicies);
    });

    test('policy가 없는 실제 설비는 기본 armLoad를 사용한다', () {
      const real = RmfProjectRobot(
        robotId: 'OMX_REAL',
        displayName: '실설비',
        model: 'open_manipulator_x',
        gzName: 'omx_real',
        zones: [],
        kind: RmfRobotKind.workcell,
        dataSource: RobotDataSource.real,
      );
      expect(workcellPoliciesFor(const [real]), isEmpty);
    });
  });
}
