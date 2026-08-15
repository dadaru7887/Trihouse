import 'package:robo_core/models/enums.dart';
import 'package:robo_core/models/event.dart';
import 'package:robo_core/models/inventory.dart';
import 'package:robo_core/models/task.dart';
import 'package:robo_core/models/warehouse.dart';

import 'repositories.dart';

/// 인메모리 [DataStore] 구현 — **플랫폼 중립**.
///
/// `dart:ffi`를 쓰지 않으므로 웹에서도 동작한다. 용도는 두 가지다.
///
/// * 웹 클라이언트의 데모/오프라인 모드 (서버 API 구현이 붙기 전까지)
/// * 저장소 계약을 검증하는 테스트
///
/// 프로세스가 끝나면 사라지므로 운영 원장으로는 쓰지 않는다.
class MemoryDataStore implements DataStore {
  MemoryDataStore()
    : robots = _MemRobots(),
      workers = _MemWorkers(),
      inventory = _MemInventory(),
      orders = _MemOrders(),
      tasks = _MemTasks(),
      events = _MemEvents(),
      incidents = _MemIncidents(),
      counters = _MemCounters();

  @override
  final RobotRepository robots;
  @override
  final WorkerRepository workers;
  @override
  final InventoryRepository inventory;
  @override
  final OrderRepository orders;
  @override
  final TaskRepository tasks;
  @override
  final EventRepository events;
  @override
  final IncidentRepository incidents;
  @override
  final CounterRepository counters;

  @override
  T transaction<T>(T Function() body) => body();

  @override
  void close() {}
}

class _MemRobots implements RobotRepository {
  final Map<String, RobotRegistration> _regs = <String, RobotRegistration>{};
  final Map<String, RobotSnapshot> _snaps = <String, RobotSnapshot>{};

  @override
  List<RobotRegistration> loadActive() => _regs.values.toList();

  @override
  RobotSnapshot? loadSnapshot(String robotId) => _snaps[robotId];

  @override
  void register(RobotRegistration robot) => _regs[robot.id] = robot;

  @override
  void retire(String robotId, DateTime at) => _regs.remove(robotId);

  @override
  void setReserve(String robotId, bool reserve) {}

  @override
  void saveSnapshots(List<RobotSnapshot> snapshots) {
    for (final s in snapshots) {
      _snaps[s.robotId] = s;
    }
  }
}

class _MemWorkers implements WorkerRepository {
  final Map<String, Worker> _workers = <String, Worker>{};

  @override
  List<Worker> loadActive() => _workers.values.toList();

  @override
  void register(Worker worker, DateTime at) => _workers[worker.id] = worker;

  @override
  void retire(String workerId, DateTime at) => _workers.remove(workerId);
}

class _MemInventory implements InventoryRepository {
  final Map<String, Lot> _lots = <String, Lot>{};
  final List<StockMove> _moves = <StockMove>[];
  int _seq = 0;

  @override
  List<Lot> loadAll() => _lots.values.toList();

  @override
  void insertLot(Lot lot, {required StockMoveReason reason, String? note}) {
    _lots[lot.id] = lot;
    _push(lot.id, lot.sku, lot.qty, lot.qty, reason, lot.receivedAt, note: note);
  }

  @override
  void applyMove({
    required String lotId,
    required int delta,
    required StockMoveReason reason,
    required DateTime at,
    String? taskId,
    String? orderId,
    String? operator,
    String? note,
  }) {
    final lot = _lots[lotId];
    if (lot == null) throw StateError('로트 $lotId 를 찾을 수 없습니다.');
    final after = lot.qty + delta;
    if (after < 0) {
      throw StateError('로트 $lotId 재고 부족: 현재 ${lot.qty}, 요청 $delta');
    }
    if (after < lot.reserved) {
      throw StateError('로트 $lotId 예약 수량(${lot.reserved})보다 적게 만들 수 없습니다.');
    }
    lot.qty = after;
    _push(
      lotId,
      lot.sku,
      delta,
      after,
      reason,
      at,
      taskId: taskId,
      orderId: orderId,
      operator: operator,
      note: note,
    );
  }

  void _push(
    String lotId,
    String sku,
    int delta,
    int after,
    StockMoveReason reason,
    DateTime at, {
    String? taskId,
    String? orderId,
    String? operator,
    String? note,
  }) => _moves.insert(
    0,
    StockMove(
      id: ++_seq,
      at: at,
      lotId: lotId,
      sku: sku,
      delta: delta,
      qtyAfter: after,
      reason: reason,
      taskId: taskId,
      orderId: orderId,
      operator: operator,
      note: note,
    ),
  );

  @override
  void setReserved(String lotId, int reserved) =>
      _lots[lotId]?.reserved = reserved;

  @override
  void updateLocation(String lotId, String locationId) =>
      _lots[lotId]?.locationId = locationId;

  @override
  List<StockMove> recentMoves({int limit = 200, String? lotId}) => _moves
      .where((m) => lotId == null || m.lotId == lotId)
      .take(limit)
      .toList();
}

class _MemOrders implements OrderRepository {
  final List<SalesOrder> _orders = <SalesOrder>[];
  final Map<String, List<OrderLine>> _lines = <String, List<OrderLine>>{};
  final Set<String> _unexpanded = <String>{};

  @override
  List<SalesOrder> loadRecent({int limit = 200}) => _orders.take(limit).toList();

  @override
  void insert(
    SalesOrder order, {
    String source = 'auto',
    bool expanded = true,
    List<OrderLine> lines = const <OrderLine>[],
  }) {
    _orders.insert(0, order);
    _lines[order.id] = List<OrderLine>.of(lines);
    if (!expanded) _unexpanded.add(order.id);
  }

  @override
  void update(SalesOrder order) {}

  @override
  List<SalesOrder> loadUnexpanded({int limit = 50}) => _orders
      .where((o) => _unexpanded.contains(o.id))
      .toList()
      .reversed
      .take(limit)
      .toList();

  @override
  List<OrderLine> loadLines(String orderId) =>
      _lines[orderId] ?? const <OrderLine>[];

  @override
  void markExpanded(String orderId) => _unexpanded.remove(orderId);
}

class _MemTasks implements TaskRepository {
  final List<WorkTask> _tasks = <WorkTask>[];

  @override
  List<WorkTask> loadRecent({int limit = 300}) => _tasks.take(limit).toList();

  @override
  void insert(WorkTask task) => _tasks.insert(0, task);

  @override
  void update(WorkTask task) {}

  @override
  int purgeTerminalBefore(DateTime cutoff) => 0;
}

class _MemEvents implements EventRepository {
  final List<OpsEvent> _events = <OpsEvent>[];

  @override
  List<OpsEvent> loadRecent({
    int limit = 400,
    String? category,
    Severity? severity,
  }) => _events
      .where(
        (e) =>
            (category == null || e.category == category) &&
            (severity == null || e.severity == severity),
      )
      .take(limit)
      .toList();

  @override
  void append(OpsEvent event) => _events.insert(0, event);

  @override
  int purgeBefore(DateTime cutoff) => 0;
}

class _MemIncidents implements IncidentRepository {
  final List<Incident> _incidents = <Incident>[];

  @override
  List<Incident> loadRecent({int limit = 100}) =>
      _incidents.take(limit).toList();

  @override
  void insert(Incident incident) => _incidents.insert(0, incident);

  @override
  void update(Incident incident) {}
}

class _MemCounters implements CounterRepository {
  final Map<String, int> _values = <String, int>{};

  @override
  int next(String name) => _values[name] = (_values[name] ?? 0) + 1;

  @override
  void ensureAtLeast(String name, int value) =>
      _values[name] = (_values[name] ?? 0) < value ? value : _values[name]!;
}
