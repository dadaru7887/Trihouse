import 'package:robo_core/models/enums.dart';
import 'package:robo_core/models/event.dart';
import 'package:robo_core/models/inventory.dart';
import 'package:robo_core/models/task.dart';
import 'package:robo_core/models/warehouse.dart';

/// 재고 수량이 변한 사유. 재고 원장(stock_moves)의 분류축이다.
enum StockMoveReason {
  inbound('입고'),
  outbound('출고'),
  disposal('폐기·회수'),
  adjustment('재고 조정'),
  cycleCount('실사 반영'),
  initial('기초 재고');

  const StockMoveReason(this.label);

  final String label;
}

/// 재고 원장 한 줄.
class StockMove {
  StockMove({
    required this.id,
    required this.at,
    required this.lotId,
    required this.sku,
    required this.delta,
    required this.qtyAfter,
    required this.reason,
    this.taskId,
    this.orderId,
    this.operator,
    this.note,
  });

  final int id;
  final DateTime at;
  final String lotId;
  final String sku;
  final int delta;
  final int qtyAfter;
  final StockMoveReason reason;
  final String? taskId;
  final String? orderId;
  final String? operator;
  final String? note;
}

/// 로봇 등록 정보(텔레메트리와 분리된 마스터 데이터).
class RobotRegistration {
  RobotRegistration({
    required this.id,
    required this.name,
    required this.model,
    required this.zoneRating,
    required this.homeChargerId,
    required this.reserve,
    required this.registeredAt,
  });

  final String id;
  final String name;
  final String model;
  final Set<TempZone> zoneRating;
  final String homeChargerId;
  final bool reserve;
  final DateTime registeredAt;
}

/// 로봇의 최신 상태 스냅샷(주기 저장).
class RobotSnapshot {
  RobotSnapshot({
    required this.robotId,
    required this.at,
    required this.state,
    required this.battery,
    required this.x,
    required this.y,
    required this.heading,
    required this.progress,
    required this.odometer,
    required this.powerSaving,
    required this.completed,
    required this.failed,
    this.taskId,
    this.activity,
  });

  final String robotId;
  final DateTime at;
  final RobotState state;
  final double battery;
  final double x;
  final double y;
  final double heading;
  final String? taskId;
  final double progress;
  final String? activity;
  final double odometer;
  final bool powerSaving;
  final int completed;
  final int failed;
}

/// 로봇 마스터 + 텔레메트리 저장소.
abstract class RobotRepository {
  List<RobotRegistration> loadActive();

  RobotSnapshot? loadSnapshot(String robotId);

  void register(RobotRegistration robot);

  /// 등록 해제. 이력 보존을 위해 삭제가 아닌 비활성 처리한다.
  void retire(String robotId, DateTime at);

  void setReserve(String robotId, bool reserve);

  /// 다건 스냅샷을 한 트랜잭션으로 upsert한다.
  void saveSnapshots(List<RobotSnapshot> snapshots);
}

/// 작업자 저장소.
abstract class WorkerRepository {
  List<Worker> loadActive();

  void register(Worker worker, DateTime at);

  void retire(String workerId, DateTime at);
}

/// 재고 저장소. 수량 변경은 반드시 원장을 함께 남긴다.
abstract class InventoryRepository {
  List<Lot> loadAll();

  void insertLot(Lot lot, {required StockMoveReason reason, String? note});

  /// 수량 변경 + 원장 기록을 한 트랜잭션으로 처리한다.
  ///
  /// [delta]가 음수면 출고·폐기, 양수면 입고·조정 증가.
  /// 결과 수량이 음수가 되거나 예약 수량을 밑돌면 [StateError]를 던진다.
  void applyMove({
    required String lotId,
    required int delta,
    required StockMoveReason reason,
    required DateTime at,
    String? taskId,
    String? orderId,
    String? operator,
    String? note,
  });

  /// 예약 수량만 변경한다(가용 수량 계산용, 실물 이동 없음).
  void setReserved(String lotId, int reserved);

  void updateLocation(String lotId, String locationId);

  List<StockMove> recentMoves({int limit = 200, String? lotId});
}

/// 주문 라인 — 주문이 담고 있는 품목·수량.
class OrderLine {
  OrderLine({
    required this.sku,
    required this.name,
    required this.qty,
    this.lotId,
  });

  final String sku;
  final String name;
  final int qty;

  /// 로트를 지정한 경우. 비우면 FEFO 규칙으로 관제가 고른다.
  final String? lotId;
}

/// 주문 저장소.
abstract class OrderRepository {
  List<SalesOrder> loadRecent({int limit = 200});

  /// [expanded]가 false면 관제가 아직 태스크로 전개하지 않은 주문이다.
  /// 소비자 앱이 넣는 주문이 여기 해당한다.
  void insert(
    SalesOrder order, {
    String source = 'auto',
    bool expanded = true,
    List<OrderLine> lines = const <OrderLine>[],
  });

  void update(SalesOrder order);

  /// 아직 전개되지 않은 주문(소비자 앱 접수분)을 오래된 순으로 돌려준다.
  List<SalesOrder> loadUnexpanded({int limit = 50});

  List<OrderLine> loadLines(String orderId);

  void markExpanded(String orderId);
}

/// 태스크 저장소.
abstract class TaskRepository {
  /// 미완결 태스크 + 최근 완결 태스크를 함께 돌려준다(재기동 복원용).
  List<WorkTask> loadRecent({int limit = 300});

  void insert(WorkTask task);

  void update(WorkTask task);

  /// 오래된 완결 태스크를 정리한다.
  int purgeTerminalBefore(DateTime cutoff);
}

/// 운행 이력 저장소.
abstract class EventRepository {
  List<OpsEvent> loadRecent({int limit = 400, String? category, Severity? severity});

  void append(OpsEvent event);

  int purgeBefore(DateTime cutoff);
}

/// 안전 상황 저장소.
abstract class IncidentRepository {
  List<Incident> loadRecent({int limit = 100});

  void insert(Incident incident);

  void update(Incident incident);
}

/// ID 시퀀스 저장소. 재기동해도 번호가 이어지도록 한다.
abstract class CounterRepository {
  int next(String name);

  void ensureAtLeast(String name, int value);
}

/// 저장소 묶음. 엔진은 이 인터페이스에만 의존한다.
///
/// SQLite 구현을 PostgreSQL·REST 구현으로 갈아끼울 때 바뀌는 지점은 여기뿐이다.
abstract class DataStore {
  RobotRepository get robots;

  WorkerRepository get workers;

  InventoryRepository get inventory;

  OrderRepository get orders;

  TaskRepository get tasks;

  EventRepository get events;

  IncidentRepository get incidents;

  CounterRepository get counters;

  /// 여러 저장소에 걸친 변경을 원자적으로 묶는다.
  T transaction<T>(T Function() body);

  void close();
}
