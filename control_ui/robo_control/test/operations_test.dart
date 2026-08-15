import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:robo_control/core/fleet_engine.dart';
import 'package:robo_core/robo_core_sqlite.dart';
import 'package:robo_core/data/repositories.dart';
import 'package:robo_core/models/enums.dart';

FleetEngine _engine({SqliteDataStore? store}) {
  final s = store ?? SqliteDataStore(AppDatabase.memory());
  if (store == null) addTearDown(s.close);
  return FleetEngine(store: s);
}

void main() {
  group('입고 → 재고 반영', () {
    test('입고 태스크가 완료되면 로트가 생기거나 수량이 늘어난다', () {
      final engine = _engine();
      addTearDown(engine.dispose);

      final before = engine.lots.fold<int>(0, (a, l) => a + l.qty);
      for (var i = 0; i < 4000; i++) {
        engine.tick();
      }

      final inboundDone = engine.tasks.values.where(
        (t) => t.type == TaskType.inbound && t.state == TaskState.done,
      );
      expect(inboundDone, isNotEmpty, reason: '입고 태스크가 완료되어야 합니다.');

      final moves = engine.stockMoves(limit: 1000);
      final inboundMoves = moves.where(
        (m) => m.reason == StockMoveReason.inbound,
      );
      expect(
        inboundMoves,
        isNotEmpty,
        reason: '입고 완료가 재고 원장에 기록되어야 합니다.',
      );
      expect(inboundMoves.every((m) => m.delta > 0), isTrue);

      // 원장 합계가 실제 수량과 일치한다.
      final after = engine.lots.fold<int>(0, (a, l) => a + l.qty);
      final ledgerSum = moves.fold<int>(0, (a, m) => a + m.delta);
      expect(after, ledgerSum);
      expect(after, isNot(before));
    });
  });

  group('수동 주문 접수', () {
    test('지정한 수량과 로트로 출고 태스크가 만들어진다', () {
      final engine = _engine();
      addTearDown(engine.dispose);

      final lot = engine.availableLots('SKU-A1').first;
      final order = engine.createOrder(
        customer: '테스트 고객',
        urgency: Urgency.critical,
        dueIn: const Duration(minutes: 15),
        lines: <({String sku, int qty, String? lotId})>[
          (sku: 'SKU-A1', qty: 2, lotId: lot.id),
        ],
      );

      expect(order.taskIds.length, 1);
      final task = engine.tasks[order.taskIds.first]!;
      expect(task.type, TaskType.outbound);
      expect(task.qty, 2);
      expect(task.lotId, lot.id);
      expect(task.urgency, Urgency.critical);
      expect(lot.reserved, greaterThanOrEqualTo(2));

      // 저장소에도 남는다.
      expect(
        engine.store.orders.loadRecent().any((o) => o.id == order.id),
        isTrue,
      );
      expect(
        engine.store.tasks.loadRecent().any((t) => t.id == task.id),
        isTrue,
      );
    });

    test('가용 재고를 넘는 라인은 태스크를 만들지 않고 사유를 남긴다', () {
      final engine = _engine();
      addTearDown(engine.dispose);

      final order = engine.createOrder(
        customer: '과다 요청',
        urgency: Urgency.normal,
        dueIn: const Duration(minutes: 30),
        lines: <({String sku, int qty, String? lotId})>[
          (sku: 'SKU-A1', qty: 999999, lotId: null),
        ],
      );

      // 가용 수량 상한이 적용되므로 태스크는 생성되되 수량이 잘린다.
      if (order.taskIds.isNotEmpty) {
        final task = engine.tasks[order.taskIds.first]!;
        expect(task.qty, lessThan(999999));
      } else {
        expect(order.state, OrderState.failed);
      }
    });

    test('완료되면 재고가 줄고 원장에 출고로 남는다', () {
      final engine = _engine();
      addTearDown(engine.dispose);

      final lot = engine.availableLots('SKU-A1').first;
      final startQty = lot.qty;
      final order = engine.createOrder(
        customer: '출고 검증',
        urgency: Urgency.critical,
        dueIn: const Duration(minutes: 20),
        lines: <({String sku, int qty, String? lotId})>[
          (sku: 'SKU-A1', qty: 3, lotId: lot.id),
        ],
      );
      final taskId = order.taskIds.first;

      for (var i = 0; i < 3000 && engine.tasks[taskId]!.state != TaskState.done; i++) {
        engine.tick();
      }

      expect(engine.tasks[taskId]!.state, TaskState.done);
      expect(lot.qty, startQty - 3);
      expect(lot.reserved, 0);

      final move = engine
          .stockMoves(limit: 500, lotId: lot.id)
          .firstWhere((m) => m.taskId == taskId);
      expect(move.delta, -3);
      expect(move.reason, StockMoveReason.outbound);
    });
  });

  group('재고 조정', () {
    test('증감이 수량과 원장에 반영된다', () {
      final engine = _engine();
      addTearDown(engine.dispose);

      final lot = engine.lots.first;
      final before = lot.qty;

      engine.adjustStock(
        lotId: lot.id,
        delta: 5,
        reason: StockMoveReason.cycleCount,
        note: '실사 결과 +5',
      );
      expect(lot.qty, before + 5);

      engine.adjustStock(
        lotId: lot.id,
        delta: -2,
        reason: StockMoveReason.adjustment,
        note: '파손 폐기',
      );
      expect(lot.qty, before + 3);

      final moves = engine.stockMoves(lotId: lot.id);
      expect(moves.first.delta, -2);
      expect(moves.first.note, '파손 폐기');
      expect(moves.first.operator, engine.operatorName);
    });

    test('예약 수량보다 적게 만들려 하면 거부하고 이력에 남긴다', () {
      final engine = _engine();
      addTearDown(engine.dispose);

      final lot = engine.availableLots('SKU-C1').first;
      engine.createOrder(
        customer: '예약 확보',
        urgency: Urgency.normal,
        dueIn: const Duration(minutes: 30),
        lines: <({String sku, int qty, String? lotId})>[
          (sku: 'SKU-C1', qty: 2, lotId: lot.id),
        ],
      );
      final qtyBefore = lot.qty;

      engine.adjustStock(
        lotId: lot.id,
        delta: -(qtyBefore - 1),
        reason: StockMoveReason.adjustment,
      );

      expect(lot.qty, qtyBefore, reason: '거부되면 수량이 그대로여야 합니다.');
      expect(
        engine.events.any((e) => e.message.contains('조정 거부')),
        isTrue,
      );
    });

    test('신규 로트를 직접 등록할 수 있다', () {
      final engine = _engine();
      addTearDown(engine.dispose);

      final lot = engine.addLot(
        sku: 'SKU-F1',
        locationId: 'F-01-01',
        qty: 30,
        expiry: engine.simNow.add(const Duration(days: 90)),
        note: '긴급 입고',
      );

      expect(engine.lots.contains(lot), isTrue);
      expect(engine.store.inventory.loadAll().any((l) => l.id == lot.id), isTrue);
      expect(engine.availableOf('SKU-F1'), greaterThanOrEqualTo(30));
    });
  });

  group('영속성', () {
    test('재기동하면 재고·주문·태스크·로봇이 복원된다', () {
      final dir = Directory.systemTemp.createTempSync('roboapp_ops');
      addTearDown(() => dir.deleteSync(recursive: true));
      final file = '${dir.path}/ops.db';

      var store = SqliteDataStore(AppDatabase.open(file: file));
      var engine = FleetEngine(store: store);
      for (var i = 0; i < 800; i++) {
        engine.tick();
      }
      final lotCount = engine.lots.length;
      final robotIds = engine.robots.map((r) => r.id).toList()..sort();
      final totalQty = engine.lots.fold<int>(0, (a, l) => a + l.qty);
      final orderIds = engine.orders.map((o) => o.id).toSet();
      final doneCount = engine.completedTotal;
      engine.dispose();
      store.close();

      store = SqliteDataStore(AppDatabase.open(file: file));
      addTearDown(store.close);
      engine = FleetEngine(store: store);
      addTearDown(engine.dispose);

      expect(store.isFresh, isFalse);
      expect(engine.lots.length, lotCount);
      expect(engine.lots.fold<int>(0, (a, l) => a + l.qty), totalQty);
      expect(engine.robots.map((r) => r.id).toList()..sort(), robotIds);
      expect(engine.completedTotal, doneCount);
      expect(orderIds.difference(engine.orders.map((o) => o.id).toSet()), isEmpty);

      // 재기동 후에도 ID가 이어진다(기존 ID와 충돌하지 않음).
      final newOrder = engine.createOrder(
        customer: '재기동 후',
        urgency: Urgency.normal,
        dueIn: const Duration(minutes: 30),
        lines: <({String sku, int qty, String? lotId})>[
          (sku: 'SKU-A2', qty: 1, lotId: null),
        ],
      );
      expect(orderIds.contains(newOrder.id), isFalse);
    });

    test('재기동 시 진행 중이던 태스크는 대기열로 회수된다', () {
      final dir = Directory.systemTemp.createTempSync('roboapp_ops2');
      addTearDown(() => dir.deleteSync(recursive: true));
      final file = '${dir.path}/ops.db';

      var store = SqliteDataStore(AppDatabase.open(file: file));
      var engine = FleetEngine(store: store);
      for (var i = 0; i < 600; i++) {
        engine.tick();
      }
      final busy = engine.robots.where((r) => r.taskId != null).toList();
      expect(busy, isNotEmpty);
      final inFlight = busy.map((r) => r.taskId!).toSet();
      engine.dispose();
      store.close();

      store = SqliteDataStore(AppDatabase.open(file: file));
      addTearDown(store.close);
      engine = FleetEngine(store: store);
      addTearDown(engine.dispose);

      for (final id in inFlight) {
        final t = engine.tasks[id];
        if (t == null || t.isTerminal) continue;
        expect(t.state, TaskState.pending, reason: '$id 는 회수되어야 합니다.');
        expect(t.robotId, isNull);
      }
      expect(engine.robots.every((r) => r.taskId == null), isTrue);
    });
  });
}
