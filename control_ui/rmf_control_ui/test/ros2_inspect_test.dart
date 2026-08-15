import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/ros2_inspect.dart';

/// `ros2` 를 부르는 옵션과 출력 파싱.
///
/// 종류마다 받는 옵션이 다르다. 안 받는 옵션을 붙이면 usage 오류로 죽는데,
/// 그 증상은 "액션 목록이 안 나온다" 로만 보여 원인에서 멀다.
void main() {
  group('종류별로 받는 옵션', () {
    test('액션은 조회 옵션을 안 받는다', () {
      // ros2 action list/info 는 -t·-c 만 받는다. --no-daemon 을 붙이면 죽는다.
      expect(Ros2Kind.action.takesProbeOptions, isFalse);
      for (final kind in [Ros2Kind.node, Ros2Kind.topic, Ros2Kind.service]) {
        expect(kind.takesProbeOptions, isTrue, reason: '${kind.command} 는 받는다');
      }
    });

    test('노드 목록에는 형식이 없다', () {
      expect(Ros2Kind.node.listShowsType, isFalse);
      for (final kind in [Ros2Kind.topic, Ros2Kind.service, Ros2Kind.action]) {
        expect(kind.listShowsType, isTrue);
      }
    });

    test('숨은 것 보기 옵션 이름이 종류마다 다르다', () {
      // 실제 --help 로 확인한 이름이다. 노드는 -a 이고 --include-hidden-nodes
      // 같은 것은 없다.
      expect(Ros2Kind.node.includeHiddenFlag, '-a');
      expect(Ros2Kind.topic.includeHiddenFlag, '--include-hidden-topics');
      expect(Ros2Kind.service.includeHiddenFlag, '--include-hidden-services');
      expect(Ros2Kind.action.includeHiddenFlag, isNull);
    });

    test('조회 방식의 깃발', () {
      expect(Ros2Probe.daemon.flag, isNull);
      expect(Ros2Probe.direct.flag, '--no-daemon');
    });
  });

  group('목록 한 줄 가르기', () {
    test('이름과 형식을 가른다', () {
      final item = parseRos2ListLine('/clock [rosgraph_msgs/msg/Clock]')!;
      expect(item.name, '/clock');
      expect(item.type, 'rosgraph_msgs/msg/Clock');
    });

    test('형식이 없으면 이름만', () {
      final item = parseRos2ListLine('/building_map_server')!;
      expect(item.name, '/building_map_server');
      expect(item.type, isNull);
    });

    test('앞뒤 공백과 목록 표시를 견딘다', () {
      final item = parseRos2ListLine('  /rosout [rcl_interfaces/msg/Log]  ')!;
      expect(item.name, '/rosout');
      expect(item.type, 'rcl_interfaces/msg/Log');
    });

    test('이름이 아닌 줄은 버린다', () {
      // `ros2 topic list -v` 는 머리글을 섞어 낸다. 안내문도 온다.
      for (final line in [
        '',
        '   ',
        'Published topics:',
        'Subscribed topics:',
        "WARNING: topic [/x] does not appear to be published yet",
        'Unknown topic',
      ]) {
        expect(parseRos2ListLine(line), isNull, reason: '버려야 한다: $line');
      }
    });

    test('여러 줄을 그대로 훑을 수 있다', () {
      // 실제 `ros2 topic list -t` 출력 모양.
      const output = '''
/bond [bond/msg/Status]
/clock [rosgraph_msgs/msg/Clock]
/door_states [rmf_door_msgs/msg/DoorState]
''';
      final items = [
        for (final line in output.split('\n')) ?parseRos2ListLine(line),
      ];
      expect(items.map((i) => i.name), ['/bond', '/clock', '/door_states']);
      expect(items.last.type, 'rmf_door_msgs/msg/DoorState');
    });
  });

  group('테스트에서는 프로세스를 안 띄운다', () {
    // 진짜 ros2 를 부르면 그 프로세스가 테스트보다 오래 살고, 결과도 그 기계에
    // 무엇이 떠 있는지에 따라 달라져 시험이 안 된다.
    test('목록·자세히·값 셋 다', () async {
      const request = Ros2InspectRequest();
      final list = await ros2List(Ros2Kind.node, request);
      expect(list.success, isFalse);
      expect(list.items, isEmpty);
      final detail = await ros2Detail(Ros2Kind.node, '/x', request);
      expect(detail.success, isFalse);
      final value = await ros2TopicValue('/x', request);
      expect(value.state, Ros2ValueState.failed);
    });

    test('그래도 돌릴 명령은 알려 준다', () async {
      // 화면에 적어 두면 터미널에서 그대로 재현할 수 있다.
      final list = await ros2List(Ros2Kind.topic, const Ros2InspectRequest());
      expect(list.command, contains('ros2 topic list'));
      expect(list.command, contains('-t'));
      expect(list.command, contains('--spin-time'));

      final action = await ros2List(
        Ros2Kind.action,
        const Ros2InspectRequest(probe: Ros2Probe.direct),
      );
      expect(action.command, contains('ros2 action list'));
      expect(
        action.command,
        isNot(contains('--no-daemon')),
        reason: 'ros2 action 은 이 옵션을 안 받는다',
      );
      expect(action.command, isNot(contains('--spin-time')));
    });

    test('직접 탐색을 고르면 깃발이 붙는다', () async {
      final list = await ros2List(
        Ros2Kind.node,
        const Ros2InspectRequest(probe: Ros2Probe.direct, spinSeconds: 7),
      );
      expect(list.command, contains('--no-daemon'));
      expect(list.command, contains('--spin-time 7'));
    });

    test('숨은 것 보기는 종류에 맞는 이름으로 붙는다', () async {
      final node = await ros2List(
        Ros2Kind.node,
        const Ros2InspectRequest(includeHidden: true),
      );
      expect(node.command, contains(' -a'));
      final topic = await ros2List(
        Ros2Kind.topic,
        const Ros2InspectRequest(includeHidden: true),
      );
      expect(topic.command, contains('--include-hidden-topics'));
      final action = await ros2List(
        Ros2Kind.action,
        const Ros2InspectRequest(includeHidden: true),
      );
      expect(action.command, isNot(contains('--include-hidden')));
    });

    test('토픽 값은 --once 로 한 건만, 시간을 끊어서 읽는다', () async {
      final value = await ros2TopicValue(
        '/clock',
        const Ros2InspectRequest(),
        waitSeconds: 4,
      );
      expect(value.command, contains('ros2 topic echo'));
      expect(value.command, contains('--once'));
      expect(value.command, contains('--timeout 4'));
    });

    test('이름은 따옴표로 감싼다', () async {
      final detail = await ros2Detail(
        Ros2Kind.topic,
        '/pinky_01/odom',
        const Ros2InspectRequest(),
      );
      expect(detail.command, contains("'/pinky_01/odom'"));
    });
  });

  group('구현이 갈라져 있다', () {
    test('웹 대체 구현이 있다', () {
      // 조건부 export 가 없으면 웹 빌드가 dart:io 를 끌어와 깨진다.
      final entry = File('lib/ros2_inspect.dart').readAsStringSync();
      expect(entry, contains("export 'ros2_inspect_models.dart';"));
      expect(entry, contains("if (dart.library.io) 'ros2_inspect_io.dart'"));
      expect(File('lib/ros2_inspect_stub.dart').existsSync(), isTrue);
    });
  });
}
