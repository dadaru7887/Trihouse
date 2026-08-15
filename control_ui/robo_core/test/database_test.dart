import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:robo_core/data/app_database.dart';
import 'package:robo_core/data/repositories.dart';
import 'package:robo_core/data/sqlite_repositories.dart';
import 'package:robo_core/models/enums.dart';
import 'package:robo_core/models/inventory.dart';

SqliteDataStore _memoryStore() => SqliteDataStore(AppDatabase.memory());

Lot _lot(String id, {int qty = 10, String sku = 'SKU-A1'}) => Lot(
  id: id,
  sku: sku,
  name: '테스트 품목',
  zone: TempZone.ambient,
  locationId: 'A-01-01',
  qty: qty,
  expiry: DateTime(2026, 12, 31),
  receivedAt: DateTime(2026, 7, 28),
);

void main() {
  test('스키마가 생성되고 버전이 기록된다', () {
    final db = AppDatabase.memory();
    addTearDown(db.close);

    expect(db.db.userVersion, AppDatabase.schemaVersion);
    final tables = db.db
        .select("SELECT name FROM sqlite_master WHERE type = 'table'")
        .map((r) => r['name'] as String)
        .toSet();
    expect(
      tables,
      containsAll(<String>[
        'robots',
        'robot_telemetry',
        'workers',
        'lots',
        'stock_moves',
        'orders',
        'tasks',
        'task_steps',
        'events',
        'incidents',
        'counters',
      ]),
    );
  });

  test('재고 이동이 수량과 원장에 함께 반영된다', () {
    final store = _memoryStore();
    addTearDown(store.close);
    final now = DateTime(2026, 7, 28, 9);

    store.inventory.insertLot(_lot('LOT-1'), reason: StockMoveReason.initial);
    store.inventory.applyMove(
      lotId: 'LOT-1',
      delta: -3,
      reason: StockMoveReason.outbound,
      at: now,
      taskId: 'TSK-1',
    );
    store.inventory.applyMove(
      lotId: 'LOT-1',
      delta: 5,
      reason: StockMoveReason.inbound,
      at: now,
    );

    expect(store.inventory.loadAll().single.qty, 12);

    final moves = store.inventory.recentMoves();
    expect(moves.length, 3);
    expect(moves.first.delta, 5);
    expect(moves.first.qtyAfter, 12);
    expect(moves.map((m) => m.reason), <StockMoveReason>[
      StockMoveReason.inbound,
      StockMoveReason.outbound,
      StockMoveReason.initial,
    ]);
  });

  test('재고를 음수로 만들거나 예약분보다 줄일 수 없다', () {
    final store = _memoryStore();
    addTearDown(store.close);
    final now = DateTime(2026, 7, 28, 9);

    store.inventory.insertLot(
      _lot('LOT-1', qty: 5),
      reason: StockMoveReason.initial,
    );

    expect(
      () => store.inventory.applyMove(
        lotId: 'LOT-1',
        delta: -6,
        reason: StockMoveReason.outbound,
        at: now,
      ),
      throwsStateError,
    );

    store.inventory.setReserved('LOT-1', 4);
    expect(
      () => store.inventory.applyMove(
        lotId: 'LOT-1',
        delta: -2,
        reason: StockMoveReason.adjustment,
        at: now,
      ),
      throwsStateError,
    );

    // 실패한 이동은 수량도 원장도 남기지 않는다(롤백 확인).
    expect(store.inventory.loadAll().single.qty, 5);
    expect(store.inventory.recentMoves().length, 1);
  });

  test('카운터는 이어지는 번호를 준다', () {
    final store = _memoryStore();
    addTearDown(store.close);

    expect(store.counters.next('task'), 1);
    expect(store.counters.next('task'), 2);
    store.counters.ensureAtLeast('task', 10);
    expect(store.counters.next('task'), 11);
    expect(store.counters.next('order'), 1);
  });

  test('파일 DB는 재기동 후에도 내용이 남는다', () {
    final dir = Directory.systemTemp.createTempSync('robocontrol_db_test');
    addTearDown(() => dir.deleteSync(recursive: true));
    final file = '${dir.path}/test.db';

    var store = SqliteDataStore(AppDatabase.open(file: file));
    store.inventory.insertLot(
      _lot('LOT-P', qty: 7),
      reason: StockMoveReason.initial,
    );
    store.counters.next('task');
    store.close();

    store = SqliteDataStore(AppDatabase.open(file: file));
    addTearDown(store.close);

    expect(store.isFresh, isFalse);
    expect(store.inventory.loadAll().single.qty, 7);
    expect(store.counters.next('task'), 2);
  });
}
