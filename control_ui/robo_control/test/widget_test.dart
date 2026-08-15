import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:robo_control/core/fleet_engine.dart';
import 'package:robo_core/robo_core_sqlite.dart';
import 'package:robo_control/core/layout.dart';
import 'package:robo_core/models/enums.dart';
import 'package:robo_control/ui/app_shell.dart';
import 'package:robo_control/ui/theme.dart';

/// 기본 테스트 폰트는 모든 글리프 폭이 같아 실제 한글 문자열의 폭을 반영하지
/// 못한다. 시스템에 한글 폰트가 있으면 로드해 실제 텍스트 폭으로 레이아웃을
/// 검증한다(없으면 기본 폰트로 진행).
Future<void> _loadKoreanFontIfAvailable() async {
  const candidates = <String>[
    '/usr/share/fonts/truetype/nanum/NanumGothic.ttf',
    '/usr/share/fonts/truetype/nanum/NanumBarunGothic.ttf',
    '/System/Library/Fonts/AppleSDGothicNeo.ttc',
    'C:/Windows/Fonts/malgun.ttf',
  ];
  final path = candidates.where((p) => File(p).existsSync()).firstOrNull;
  if (path == null) return;
  final loader = FontLoader('Roboto')
    ..addFont(
      Future<ByteData>.value(
        ByteData.sublistView(File(path).readAsBytesSync()),
      ),
    );
  await loader.load();
}

/// 테스트마다 독립된 인메모리 DB 위에서 엔진을 만든다.
FleetEngine _newEngine() {
  final store = SqliteDataStore(AppDatabase.memory());
  addTearDown(store.close);
  return FleetEngine(store: store);
}

void main() {
  setUpAll(_loadKoreanFontIfAvailable);

  testWidgets('관제센터 셸이 렌더링되고 핵심 지표를 표시한다', (WidgetTester tester) async {
    tester.view.physicalSize = const Size(1600, 1000);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);

    final engine = _newEngine();
    addTearDown(engine.dispose);

    await tester.pumpWidget(
      MaterialApp(
        theme: buildControlRoomTheme(),
        home: EngineScope(engine: engine, child: const ControlCenterShell()),
      ),
    );
    await tester.pump();

    expect(find.text('종합 현황'), findsWidgets);
    expect(find.text('가동 로봇'), findsOneWidget);
    expect(find.text('전체 비상정지'), findsOneWidget);
  });

  // 폭이 좁으면 사이드바가 아이콘만 표시하므로 아이콘으로 탭을 전환한다.
  // 사이드바는 트리에서 본문보다 앞에 있으므로 first가 내비게이션 항목이다.
  const tabs = <(String, IconData)>[
    ('실시간 맵', Icons.map_outlined),
    ('로봇 관제', Icons.smart_toy_outlined),
    ('태스크·주문', Icons.assignment_outlined),
    ('재고 · FEFO', Icons.inventory_2_outlined),
    ('안전 관리', Icons.health_and_safety_outlined),
    ('운행 이력', Icons.receipt_long_outlined),
    ('종합 현황', Icons.dashboard_outlined),
  ];

  // 관제실 대형 모니터부터 노트북 창까지 잘림 없이 표시되어야 한다.
  for (final size in <Size>[
    const Size(1920, 1080),
    const Size(1600, 1000),
    const Size(1280, 720),
    const Size(1024, 700),
  ]) {
    testWidgets(
      '${size.width.toInt()}×${size.height.toInt()}에서 모든 탭이 오버플로 없이 렌더링된다',
      (WidgetTester tester) async {
        tester.view.physicalSize = size;
        tester.view.devicePixelRatio = 1.0;
        addTearDown(tester.view.resetPhysicalSize);

        final engine = _newEngine();
        addTearDown(engine.dispose);
        for (var i = 0; i < 400; i++) {
          engine.tick();
        }

        await tester.pumpWidget(
          MaterialApp(
            theme: buildControlRoomTheme(),
            home: EngineScope(engine: engine, child: const ControlCenterShell()),
          ),
        );
        expect(tester.takeException(), isNull, reason: '초기 렌더링 오류');

        for (final (label, icon) in tabs) {
          await tester.tap(find.byIcon(icon).first, warnIfMissed: false);
          await tester.pump();
          expect(tester.takeException(), isNull, reason: '$label 탭 렌더링 오류');
        }
      },
    );
  }

  test('통로 그래프 경로 탐색이 양 끝점을 연결한다', () {
    final layout = WarehouseLayout.build();
    const from = Offset(10, 10);
    const to = Offset(110, 60);
    final path = layout.route(from, to);

    expect(path, isNotEmpty);
    expect(path.last, to);
    expect(layout.routeLength(from, to), greaterThan((to - from).distance));
  });

  test('태스크 리스는 단일 소유자만 허용한다', () {
    final engine = _newEngine();
    addTearDown(engine.dispose);

    final now = engine.simNow;
    expect(engine.ledger.claim('T-1', 'RS-01', now, FleetEngine.leaseTtl), isTrue);
    expect(engine.ledger.claim('T-1', 'RS-02', now, FleetEngine.leaseTtl), isFalse);
    expect(engine.ledger.conflictsPrevented, greaterThanOrEqualTo(1));

    engine.ledger.release('T-1');
    expect(engine.ledger.claim('T-1', 'RS-02', now, FleetEngine.leaseTtl), isTrue);
  });

  test('비상정지를 발령하면 상황이 활성화되고 해제하면 복구된다', () {
    final engine = _newEngine();
    addTearDown(engine.dispose);

    engine.toggleGlobalEStop();
    expect(engine.globalEStop, isTrue);
    expect(engine.activeIncidents.any((i) => i.type == IncidentType.eStop), isTrue);

    engine.toggleGlobalEStop();
    expect(engine.globalEStop, isFalse);
    expect(engine.activeIncidents.any((i) => i.type == IncidentType.eStop), isFalse);
  });

  test('시뮬레이션을 진행하면 태스크가 할당·완료되고 중복 소유자가 없다', () {
    final engine = _newEngine();
    addTearDown(engine.dispose);

    for (var i = 0; i < 1200; i++) {
      engine.tick();
    }

    expect(engine.completedTotal, greaterThan(0), reason: '완료된 태스크가 있어야 합니다.');
    expect(engine.events.length, greaterThan(5));

    // 한 로봇이 동시에 두 태스크를 수행하지 않는다.
    final owned = engine.robots
        .where((r) => r.taskId != null)
        .map((r) => r.taskId)
        .toList();
    expect(owned.toSet().length, owned.length, reason: '태스크가 중복 할당되면 안 됩니다.');

    // 진행 중인 태스크의 담당 로봇 표기가 서로 일치한다.
    for (final r in engine.robots) {
      if (r.taskId == null) continue;
      expect(engine.tasks[r.taskId]?.robotId, r.id);
    }
  });

  test('로봇을 등록하면 ID가 중복 없이 부여되고 스케줄링 대상이 된다', () {
    final engine = _newEngine();
    addTearDown(engine.dispose);

    final before = engine.robots.length;
    final added = engine.addRobot(
      name: '인디아',
      model: 'RSX-300C',
      zoneRating: const <TempZone>{
        TempZone.ambient,
        TempZone.chilled,
        TempZone.frozen,
      },
    );

    expect(engine.robots.length, before + 1);
    expect(engine.robots.map((r) => r.id).toSet().length, engine.robots.length);
    expect(added.battery, 100);
    expect(added.reserve, isFalse);
    expect(engine.beacons.any((b) => b.robotId == added.id), isTrue);

    // 등록된 로봇이 실제로 태스크를 받아 움직이는지 확인한다.
    for (var i = 0; i < 1500; i++) {
      engine.tick();
    }
    expect(added.odometer, greaterThan(0));
  });

  test('진행 중 로봇을 해제하면 태스크가 회수되어 재할당된다', () {
    final engine = _newEngine();
    addTearDown(engine.dispose);

    for (var i = 0; i < 600; i++) {
      engine.tick();
    }
    final busy = engine.robots.firstWhere((r) => r.taskId != null);
    final taskId = busy.taskId!;
    engine.selectRobot(busy.id);

    engine.removeRobot(busy);

    expect(engine.robots.contains(busy), isFalse);
    expect(engine.selectedRobotId, isNull);
    expect(engine.beacons.any((b) => b.robotId == busy.id), isFalse);
    expect(engine.ledger.ownerOf(taskId, engine.simNow), isNull);
    expect(engine.tasks[taskId]!.state, TaskState.pending);
    expect(engine.tasks[taskId]!.robotId, isNull);

    // 남은 로봇이 이어받는다.
    for (var i = 0; i < 600; i++) {
      engine.tick();
    }
    final task = engine.tasks[taskId]!;
    expect(
      task.robotId != null || task.state == TaskState.done,
      isTrue,
      reason: '회수된 태스크가 다른 로봇에 재할당되어야 합니다.',
    );
  });

  test('작업자를 등록·해제하면 안전 필드 대상이 갱신된다', () {
    final engine = _newEngine();
    addTearDown(engine.dispose);

    final before = engine.workers.length;
    final w = engine.addWorker(
      name: '오지훈',
      role: '지게차',
      zone: TempZone.frozen,
    );
    expect(engine.workers.length, before + 1);
    expect(engine.workers.map((e) => e.id).toSet().length, engine.workers.length);
    expect(w.zone, TempZone.frozen);

    engine.removeWorker(w);
    expect(engine.workers.length, before);
    expect(engine.workers.contains(w), isFalse);
  });

  test('위급 상태 작업자를 해제하면 관련 안전 상황도 종료된다', () {
    final engine = _newEngine();
    addTearDown(engine.dispose);

    engine.raiseWorkerEmergency();
    expect(
      engine.activeIncidents.any((i) => i.type == IncidentType.workerEmergency),
      isTrue,
    );

    final hurt = engine.workers.firstWhere((w) => w.inDistress);
    engine.removeWorker(hurt);

    expect(
      engine.activeIncidents.any((i) => i.type == IncidentType.workerEmergency),
      isFalse,
    );
  });

  test('로봇을 모두 해제해도 엔진이 계속 동작한다', () {
    final engine = _newEngine();
    addTearDown(engine.dispose);

    for (var i = 0; i < 300; i++) {
      engine.tick();
    }
    for (final r in engine.robots.toList()) {
      engine.removeRobot(r);
    }
    expect(engine.robots, isEmpty);

    for (var i = 0; i < 300; i++) {
      engine.tick();
    }
    expect(engine.avgBattery, 0);
    expect(engine.pendingTasks, greaterThan(0));
  });

  test('재고 예약이 가용 수량을 넘지 않는다', () {
    final engine = _newEngine();
    addTearDown(engine.dispose);

    for (var i = 0; i < 2500; i++) {
      engine.tick();
      for (final lot in engine.lots) {
        expect(
          lot.available,
          greaterThanOrEqualTo(0),
          reason: '${lot.id} 가용 수량이 음수가 되었습니다(예약 ${lot.reserved} / 총 ${lot.qty}).',
        );
        expect(lot.qty, greaterThanOrEqualTo(0));
      }
    }
  });

  test('전체 비상정지 중에는 로봇이 이동하지 않는다', () {
    final engine = _newEngine();
    addTearDown(engine.dispose);

    for (var i = 0; i < 200; i++) {
      engine.tick();
    }
    engine.toggleGlobalEStop();

    final before = engine.robots.map((r) => r.pos).toList();
    for (var i = 0; i < 60; i++) {
      engine.tick();
    }
    for (var i = 0; i < engine.robots.length; i++) {
      expect(engine.robots[i].pos, before[i]);
    }
  });

  test('FEFO 정렬은 유통기한이 이른 로트를 먼저 반환한다', () {
    final engine = _newEngine();
    addTearDown(engine.dispose);

    final ordered = engine.scheduler.fefoOrder(engine.lots, engine.simNow);
    for (var i = 1; i < ordered.length; i++) {
      expect(
        ordered[i - 1].expiry.isAfter(ordered[i].expiry),
        isFalse,
        reason: 'FEFO 정렬이 유통기한 오름차순이어야 합니다.',
      );
    }
  });
}
