import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

import 'package:robo_control/core/fleet_engine.dart';
import 'package:robo_control/core/robot_link.dart';
import 'package:robo_core/models/enums.dart';
import 'package:robo_core/robo_core_sqlite.dart';

/// 현장 로봇(Gazebo Pinky) 역할을 하는 테스트용 가짜 에이전트.
///
/// 실제 `robo_pinky_agent`와 같은 NDJSON 프로토콜을 쓴다.
class FakeAgent {
  FakeAgent._(this._socket, this.received);

  static Future<FakeAgent> connect(int port) async {
    final socket = await Socket.connect('127.0.0.1', port);
    final received = <Map<String, dynamic>>[];
    utf8.decoder
        .bind(socket)
        .transform(const LineSplitter())
        .listen((String line) {
          if (line.trim().isEmpty) return;
          received.add(jsonDecode(line) as Map<String, dynamic>);
        });
    return FakeAgent._(socket, received);
  }

  final Socket _socket;
  final List<Map<String, dynamic>> received;

  void send(Map<String, dynamic> msg) => _socket.write('${jsonEncode(msg)}\n');

  Map<String, dynamic>? last(String type) =>
      received.lastWhereOrNull((m) => m['t'] == type);

  Future<void> close() async {
    _socket.destroy();
  }
}

extension _LastWhereOrNull<T> on List<T> {
  T? lastWhereOrNull(bool Function(T) test) {
    for (var i = length - 1; i >= 0; i--) {
      if (test(this[i])) return this[i];
    }
    return null;
  }
}

/// 조건이 만족될 때까지 짧게 대기한다(TCP는 비동기라 즉시 반영되지 않는다).
Future<void> until(
  bool Function() condition, {
  Duration timeout = const Duration(seconds: 5),
}) async {
  final deadline = DateTime.now().add(timeout);
  while (!condition()) {
    if (DateTime.now().isAfter(deadline)) {
      fail('조건이 $timeout 안에 만족되지 않았습니다.');
    }
    await Future<void>.delayed(const Duration(milliseconds: 20));
  }
}

void main() {
  late FleetEngine engine;
  late int port;

  setUp(() async {
    // 테스트마다 다른 포트를 써서 이전 소켓 잔류의 영향을 받지 않게 한다.
    final probe = await ServerSocket.bind('127.0.0.1', 0);
    port = probe.port;
    await probe.close();

    final store = SqliteDataStore(AppDatabase.memory());
    addTearDown(store.close);
    engine = FleetEngine(
      store: store,
      link: RobotLinkServer(port: port),
    );
    addTearDown(engine.dispose);
    expect(await engine.link.start(), isTrue);
  });

  test('hello를 보내면 플릿에 등록되고 좌표계 파라미터를 회신받는다', () async {
    final agent = await FakeAgent.connect(port);
    addTearDown(agent.close);

    agent.send(<String, dynamic>{
      't': 'hello',
      'proto': 1,
      'id': 'PK-01',
      'name': '핑키 1호',
      'model': 'PINKY-GZ-C',
      'zones': <String>['ambient', 'chilled', 'frozen'],
      'charger': 'CHG-1',
      'x': 50.0,
      'y': 22.0,
      'heading': 0.0,
      'battery': 92.0,
    });

    await until(() => engine.link.isLinked('PK-01'));
    await until(() => agent.last('welcome') != null);

    final welcome = agent.last('welcome')!;
    expect(welcome['scale'], 0.1);
    expect(welcome['width'], 120.0);
    expect(welcome['height'], 72.0);
  });

  test('접속한 로봇은 관제가 위치를 지어내지 않고 보고값을 그대로 쓴다', () async {
    final agent = await FakeAgent.connect(port);
    addTearDown(agent.close);
    agent.send(_hello());
    await until(() => engine.link.isLinked('PK-01'));

    // 엔진이 hello를 처리해 플릿에 넣을 때까지 tick을 돌린다.
    await until(() {
      engine.tick();
      return engine.robots.any((r) => r.id == 'PK-01');
    });

    agent.send(<String, dynamic>{
      't': 'telemetry',
      'id': 'PK-01',
      'x': 61.5,
      'y': 37.25,
      'heading': 1.2,
      'battery': 77.5,
      'speed': 2.1,
      'odom': 33.0,
      'wpLeft': 2,
      'charging': false,
      'note': null,
    });

    final robot = engine.robots.firstWhere((r) => r.id == 'PK-01');
    await until(() {
      engine.tick();
      return (robot.pos.dx - 61.5).abs() < 0.01;
    });

    expect(robot.pos.dy, closeTo(37.25, 0.01));
    expect(robot.heading, closeTo(1.2, 0.001));
    expect(robot.battery, closeTo(77.5, 0.01));
    expect(robot.speed, closeTo(2.1, 0.01));
  });

  test('배차된 경로가 웨이포인트 명령으로 하달된다', () async {
    final agent = await FakeAgent.connect(port);
    addTearDown(agent.close);
    agent.send(_hello());
    await until(() => engine.link.isLinked('PK-01'));
    await until(() {
      engine.tick();
      return engine.robots.any((r) => r.id == 'PK-01');
    });

    // 태스크가 배정되면 경로가 생기고, 그 경로가 로봇에게 내려간다.
    await until(() {
      engine.tick();
      return agent.last('path') != null &&
          (agent.last('path')!['waypoints'] as List<dynamic>).isNotEmpty;
    }, timeout: const Duration(seconds: 20));

    final path = agent.last('path')!;
    final waypoints = path['waypoints'] as List<dynamic>;
    for (final wp in waypoints) {
      final p = wp as List<dynamic>;
      expect(p[0] as num, inInclusiveRange(0, 120));
      expect(p[1] as num, inInclusiveRange(0, 72));
    }
  });

  test('전체 비상정지는 hold 명령으로 전달되고 해제되면 풀린다', () async {
    final agent = await FakeAgent.connect(port);
    addTearDown(agent.close);
    agent.send(_hello());
    await until(() => engine.link.isLinked('PK-01'));
    await until(() {
      engine.tick();
      return engine.robots.any((r) => r.id == 'PK-01');
    });

    engine.toggleGlobalEStop();
    await until(() {
      engine.tick();
      return agent.last('hold')?['on'] == true;
    });
    expect(agent.last('hold')!['reason'], isNotNull);

    engine.toggleGlobalEStop();
    await until(() {
      engine.tick();
      return agent.last('hold')?['on'] == false;
    });
  });

  test('링크가 끊기면 태스크를 회수하고 배차 대상에서 제외한다', () async {
    final agent = await FakeAgent.connect(port);
    agent.send(_hello());
    await until(() => engine.link.isLinked('PK-01'));
    await until(() {
      engine.tick();
      return engine.robots.any((r) => r.id == 'PK-01');
    });

    await agent.close();
    await until(() => !engine.link.isLinked('PK-01'));

    final robot = engine.robots.firstWhere((r) => r.id == 'PK-01');
    engine.tick();
    expect(robot.state, RobotState.standby);
    expect(robot.reserve, isTrue);
    expect(robot.taskId, isNull);
    expect(engine.isLinkOffline(robot), isTrue);

    // 끊긴 상태에서 계속 tick을 돌려도 관제가 위치를 지어내지 않는다.
    final before = robot.pos;
    for (var i = 0; i < 20; i++) {
      engine.tick();
    }
    expect(robot.pos, before);
  });

  test('실장비가 붙어 있는 동안 배속은 1×로 고정된다', () async {
    engine.setSpeed(8);
    expect(engine.effectiveSpeedMultiplier, 8);

    final agent = await FakeAgent.connect(port);
    addTearDown(agent.close);
    agent.send(_hello());
    await until(() => engine.link.isLinked('PK-01'));

    expect(engine.realTimeLocked, isTrue);
    expect(engine.effectiveSpeedMultiplier, 1.0);
  });
}

Map<String, dynamic> _hello() => <String, dynamic>{
  't': 'hello',
  'proto': 1,
  'id': 'PK-01',
  'name': '핑키 1호',
  'model': 'PINKY-GZ-C',
  'zones': <String>['ambient', 'chilled', 'frozen'],
  'charger': 'CHG-1',
  'x': 50.0,
  'y': 22.0,
  'heading': 0.0,
  'battery': 92.0,
};
