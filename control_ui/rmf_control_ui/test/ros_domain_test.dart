/// ROS 도메인을 맵이 정하고, 로봇이 그것을 가져가되 고칠 수 있는지 지킨다.
///
/// 도메인이 어긋나면 **아무 오류도 안 나면서** 아무것도 안 통한다. 실제로 앱은
/// 비대화형 셸로 배포 스크립트를 돌려 `~/.bashrc` 의 `export ROS_DOMAIN_ID=22`
/// 를 못 읽었고, 터미널의 시뮬레이터가 22번에 있는 동안 배포만 0번에서 혼자
/// 돌았다. 지도를 배포해도 시뮬레이터가 못 받았고, 화면에는 "배포가 오래
/// 걸린다" 로만 보였다.
library;

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/main.dart';
import 'package:rmf_control_ui/rmf_project_config.dart';

void main() {
  group('쓸 수 있는 도메인', () {
    test('0 부터 232 까지 받는다', () {
      expect(rosDomainIdError(0), isNull);
      expect(rosDomainIdError(22), isNull);
      expect(rosDomainIdError(maxRosDomainId), isNull);
      expect(rosDomainIdError(-1), isNotNull);
      expect(rosDomainIdError(maxRosDomainId + 1), isNotNull);
      expect(rosDomainIdError(null), isNotNull);
    });

    test('임시 포트와 겹칠 수 있는 번호는 알린다', () {
      expect(rosDomainIdWarning(22), isNull);
      expect(rosDomainIdWarning(safeMaxRosDomainId), isNull);
      expect(rosDomainIdWarning(safeMaxRosDomainId + 1), isNotNull);
    });
  });

  group('실행 스크립트', () {
    test('맵이 정한 도메인을 내보낸다', () {
      final script = buildProjectRunScript(
        mapName: 'gwanghee',
        mapDirectory: '/maps/gwanghee',
        rosDomainId: 22,
      );
      // 앱에서 띄우든 터미널에서 띄우든 같은 망을 써야 한다.
      expect(script, contains('export ROS_DOMAIN_ID="\${ROS_DOMAIN_ID:-22}"'));
      // 무엇으로 떴는지 로그만 봐도 알아야 한다.
      expect(script, contains(r'ROS_DOMAIN_ID: $ROS_DOMAIN_ID'));
    });

    test('환경 변수로 준 값이 이긴다', () {
      // 한 번만 다른 망에서 시험해 보는 길을 막지 않는다.
      final script = buildProjectRunScript(
        mapName: 'gwanghee',
        mapDirectory: '/maps/gwanghee',
      );
      expect(script, contains(r'${ROS_DOMAIN_ID:-0}'));
    });
  });

  group('로봇마다 따로', () {
    const base = RmfProjectRobot(
      robotId: 'PK-01',
      displayName: '핑키 1호',
      model: 'PINKY-GZ',
      gzName: 'pinky_01',
      zones: ['ambient'],
      dataSource: RobotDataSource.gazebo,
    );

    test('안 정한 로봇은 launch 를 건드리지 않는다', () {
      // 빈 값을 넣으면 스크립트가 내보낸 값을 덮어써서, 맵 기본값을 고쳐도
      // 이 로봇만 안 따라온다.
      expect(buildRobotSpawnLaunchXml(base), isNot(contains('ROS_DOMAIN_ID')));
      expect(
        buildRobotNav2LaunchXml(base, 'gwanghee'),
        isNot(contains('ROS_DOMAIN_ID')),
      );
    });

    test('정한 로봇은 제 도메인으로 뜬다', () {
      final robot = RmfProjectRobot(
        robotId: base.robotId,
        displayName: base.displayName,
        model: base.model,
        gzName: base.gzName,
        zones: base.zones,
        dataSource: base.dataSource,
        rosDomainId: 40,
      );
      // 노드가 도메인을 정하는 것은 환경 변수뿐이라 set_env 말고는 길이 없다.
      const expected = '<set_env name="ROS_DOMAIN_ID" value="40"/>';
      expect(buildRobotSpawnLaunchXml(robot), contains(expected));
      expect(buildRobotNav2LaunchXml(robot, 'gwanghee'), contains(expected));
      expect(buildRobotInfoYaml(robot), contains('ros_domain_id: 40'));
    });

    test('프로젝트에 남고 다시 읽힌다', () {
      final robot = RmfProjectRobot(
        robotId: base.robotId,
        displayName: base.displayName,
        model: base.model,
        gzName: base.gzName,
        zones: base.zones,
        rosDomainId: 40,
      );
      expect(RmfProjectRobot.fromJson(robot.toJson()).rosDomainId, 40);
      expect(RmfProjectRobot.fromJson(base.toJson()).rosDomainId, isNull);
      // 자리를 다시 계산해도 도메인은 그대로다.
      expect(robot.withSpawn(spawnX: 1, spawnY: 2).rosDomainId, 40);
    });
  });

  group('배포 스크립트', () {
    late final String script = File(
      '../openrmf/scripts/deploy_map.sh',
    ).readAsStringSync();

    test('어느 도메인에 띄웠는지 로그에 남긴다', () {
      expect(script, contains(r'echo "ROS_DOMAIN_ID: ${ROS_DOMAIN_ID:-0}"'));
    });

    test('기다림을 시계로 자른다', () {
      // `30번 × sleep 0.5` 는 15초로 보이지만, 노드가 수백 개면
      // `ros2 service list` 한 번이 3~5초라 실제로는 100초가 넘었다.
      expect(script, contains('MAP_READY_WAIT'));
      expect(script, contains('DEADLINE=\$((SECONDS + WAIT_SECS))'));
      // 확인 자체가 그 시계 안에서 돌아야 한다. (프로세스가 죽기를 기다리는
      // 다른 반복문은 그대로 둔다 — 그쪽은 횟수로 세는 것이 맞다.)
      // 단계 번호가 아니라 이름으로 찾는다. 번호는 단계가 늘거나 줄면 바뀐다.
      final ready = script.substring(script.indexOf('"새 지도 수신 확인"'));
      expect(ready, contains('while ((SECONDS < DEADLINE)); do'));
      expect(ready, isNot(contains('for _ in {1..30}; do')));
    });

    test('도메인이 비었으면 그것부터 짚는다', () {
      expect(script, contains('노드가 하나도 없습니다'));
      expect(script, contains('맵 관리 · [ROS 도메인] 단추'));
    });

    test('도메인을 바꾼 뒤 이전 ros2 daemon 캐시를 쓰지 않는다', () {
      expect(script, contains('ros2 service list --no-daemon --spin-time 1'));
      expect(script, contains('ros2 node list --no-daemon --spin-time 1'));
    });

    test('맵을 다시 배포해도 등록한 WorkCell policy를 보존한다', () {
      expect(script, contains(r'cp -a "$BACKUP_PATH/policies"'));
      expect(script, contains('WorkCell policy 보존'));
      expect(script, contains(r'cp -a "$BACKUP_PATH/policy_bindings.json"'));
      expect(script, contains('WorkCell policy 연결 보존'));
    });
  });

  group('맵 관리 화면', () {
    testWidgets('단추에 지금 도메인이 적혀 있다', (tester) async {
      // 어긋나면 오류 없이 아무것도 안 통하므로 늘 보여야 한다.
      tester.view.physicalSize = const Size(1600, 1200);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(const RmfControlApp());
      await tester.tap(find.text('맵 관리').first);
      await tester.pumpAndSettle();
      expect(find.text('ROS 도메인 0'), findsOneWidget);
    });

    testWidgets('넣은 도메인이 단추에 남는다', (tester) async {
      tester.view.physicalSize = const Size(1600, 1200);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(const RmfControlApp());
      await tester.tap(find.text('맵 관리').first);
      await tester.pumpAndSettle();
      await tester.tap(find.textContaining('ROS 도메인 '));
      await tester.pumpAndSettle();

      await tester.enterText(
        find.ancestor(
          of: find.text('ROS_DOMAIN_ID'),
          matching: find.byType(TextField),
        ),
        '22',
      );
      await tester.tap(find.text('도메인 저장'));
      await tester.pumpAndSettle();

      expect(find.text('ROS 도메인 22'), findsOneWidget);
    });

    testWidgets('쓸 수 없는 번호는 막는다', (tester) async {
      tester.view.physicalSize = const Size(1600, 1200);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(const RmfControlApp());
      await tester.tap(find.text('맵 관리').first);
      await tester.pumpAndSettle();
      await tester.tap(find.textContaining('ROS 도메인 '));
      await tester.pumpAndSettle();

      await tester.enterText(
        find.ancestor(
          of: find.text('ROS_DOMAIN_ID'),
          matching: find.byType(TextField),
        ),
        '999',
      );
      await tester.tap(find.text('도메인 저장'));
      await tester.pumpAndSettle();

      expect(find.textContaining('사이여야 합니다'), findsOneWidget);
    });
  });
}
