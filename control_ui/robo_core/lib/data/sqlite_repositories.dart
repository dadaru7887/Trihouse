import 'dart:ui' show Offset;

import 'package:sqlite3/sqlite3.dart';

import 'package:robo_core/models/enums.dart';
import 'package:robo_core/models/event.dart';
import 'package:robo_core/models/inventory.dart';
import 'package:robo_core/models/task.dart';
import 'package:robo_core/models/warehouse.dart';
import 'app_database.dart';
import 'repositories.dart';

String _iso(DateTime t) => t.toIso8601String();

DateTime _at(Object? v) => DateTime.parse(v! as String);

DateTime? _atOrNull(Object? v) =>
    v == null ? null : DateTime.parse(v as String);

/// SQLite로 구현한 저장소 묶음.
class SqliteDataStore implements DataStore {
  SqliteDataStore(this._db)
    : robots = _SqliteRobotRepository(_db),
      workers = _SqliteWorkerRepository(_db),
      inventory = _SqliteInventoryRepository(_db),
      orders = _SqliteOrderRepository(_db),
      tasks = _SqliteTaskRepository(_db),
      events = _SqliteEventRepository(_db),
      incidents = _SqliteIncidentRepository(_db),
      counters = _SqliteCounterRepository(_db);

  final AppDatabase _db;

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

  /// 기초 데이터가 아직 없는 신규 DB인지.
  bool get isFresh => _db.isEmpty;

  String get path => _db.path;

  @override
  T transaction<T>(T Function() body) => _db.transaction(body);

  @override
  void close() => _db.close();
}

class _SqliteRobotRepository implements RobotRepository {
  _SqliteRobotRepository(this._db);

  final AppDatabase _db;

  Database get _c => _db.db;

  @override
  List<RobotRegistration> loadActive() {
    final rows = _c.select(
      'SELECT * FROM robots WHERE active = 1 ORDER BY id',
    );
    return rows
        .map(
          (r) => RobotRegistration(
            id: r['id'] as String,
            name: r['name'] as String,
            model: r['model'] as String,
            zoneRating: (r['zone_rating'] as String)
                .split(',')
                .where((s) => s.isNotEmpty)
                .map(TempZone.values.byName)
                .toSet(),
            homeChargerId: r['home_charger_id'] as String,
            reserve: (r['reserve'] as int) == 1,
            registeredAt: _at(r['registered_at']),
          ),
        )
        .toList();
  }

  @override
  RobotSnapshot? loadSnapshot(String robotId) {
    final rows = _c.select(
      'SELECT * FROM robot_telemetry WHERE robot_id = ?',
      <Object?>[robotId],
    );
    if (rows.isEmpty) return null;
    final r = rows.first;
    return RobotSnapshot(
      robotId: r['robot_id'] as String,
      at: _at(r['at']),
      state: RobotState.values.byName(r['state'] as String),
      battery: (r['battery'] as num).toDouble(),
      x: (r['x'] as num).toDouble(),
      y: (r['y'] as num).toDouble(),
      heading: (r['heading'] as num).toDouble(),
      taskId: r['task_id'] as String?,
      progress: (r['progress'] as num).toDouble(),
      activity: r['activity'] as String?,
      odometer: (r['odometer'] as num).toDouble(),
      powerSaving: (r['power_saving'] as int) == 1,
      completed: r['completed'] as int,
      failed: r['failed'] as int,
    );
  }

  @override
  void register(RobotRegistration robot) {
    _c.execute(
      '''
      INSERT INTO robots
        (id, name, model, zone_rating, home_charger_id, reserve, active, registered_at)
      VALUES (?, ?, ?, ?, ?, ?, 1, ?)
      ON CONFLICT(id) DO UPDATE SET
        name = excluded.name, model = excluded.model,
        zone_rating = excluded.zone_rating,
        home_charger_id = excluded.home_charger_id,
        reserve = excluded.reserve, active = 1, retired_at = NULL
      ''',
      <Object?>[
        robot.id,
        robot.name,
        robot.model,
        robot.zoneRating.map((z) => z.name).join(','),
        robot.homeChargerId,
        robot.reserve ? 1 : 0,
        _iso(robot.registeredAt),
      ],
    );
  }

  @override
  void retire(String robotId, DateTime at) {
    _c.execute(
      'UPDATE robots SET active = 0, retired_at = ? WHERE id = ?',
      <Object?>[_iso(at), robotId],
    );
  }

  @override
  void setReserve(String robotId, bool reserve) {
    _c.execute('UPDATE robots SET reserve = ? WHERE id = ?', <Object?>[
      reserve ? 1 : 0,
      robotId,
    ]);
  }

  @override
  void saveSnapshots(List<RobotSnapshot> snapshots) {
    if (snapshots.isEmpty) return;
    final stmt = _c.prepare('''
      INSERT INTO robot_telemetry
        (robot_id, at, state, battery, x, y, heading, task_id, progress,
         activity, odometer, power_saving, completed, failed)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      ON CONFLICT(robot_id) DO UPDATE SET
        at = excluded.at, state = excluded.state, battery = excluded.battery,
        x = excluded.x, y = excluded.y, heading = excluded.heading,
        task_id = excluded.task_id, progress = excluded.progress,
        activity = excluded.activity, odometer = excluded.odometer,
        power_saving = excluded.power_saving,
        completed = excluded.completed, failed = excluded.failed
    ''');
    try {
      _db.transaction(() {
        for (final s in snapshots) {
          stmt.execute(<Object?>[
            s.robotId,
            _iso(s.at),
            s.state.name,
            s.battery,
            s.x,
            s.y,
            s.heading,
            s.taskId,
            s.progress,
            s.activity,
            s.odometer,
            s.powerSaving ? 1 : 0,
            s.completed,
            s.failed,
          ]);
        }
      });
    } finally {
      stmt.close();
    }
  }
}

class _SqliteWorkerRepository implements WorkerRepository {
  _SqliteWorkerRepository(this._db);

  final AppDatabase _db;

  Database get _c => _db.db;

  @override
  List<Worker> loadActive() {
    final rows = _c.select(
      'SELECT * FROM workers WHERE active = 1 ORDER BY id',
    );
    return rows
        .map(
          (r) => Worker(
            id: r['id'] as String,
            name: r['name'] as String,
            role: r['role'] as String,
            zone: TempZone.values.byName(r['zone'] as String),
            pos: Offset.zero,
          ),
        )
        .toList();
  }

  @override
  void register(Worker worker, DateTime at) {
    _c.execute(
      '''
      INSERT INTO workers (id, name, role, zone, active, registered_at)
      VALUES (?, ?, ?, ?, 1, ?)
      ON CONFLICT(id) DO UPDATE SET
        name = excluded.name, role = excluded.role, zone = excluded.zone,
        active = 1, retired_at = NULL
      ''',
      <Object?>[worker.id, worker.name, worker.role, worker.zone.name, _iso(at)],
    );
  }

  @override
  void retire(String workerId, DateTime at) {
    _c.execute(
      'UPDATE workers SET active = 0, retired_at = ? WHERE id = ?',
      <Object?>[_iso(at), workerId],
    );
  }
}

class _SqliteInventoryRepository implements InventoryRepository {
  _SqliteInventoryRepository(this._db);

  final AppDatabase _db;

  Database get _c => _db.db;

  Lot _toLot(Row r) => Lot(
    id: r['id'] as String,
    sku: r['sku'] as String,
    name: r['name'] as String,
    zone: TempZone.values.byName(r['zone'] as String),
    locationId: r['location_id'] as String,
    qty: r['qty'] as int,
    expiry: _at(r['expiry']),
    receivedAt: _at(r['received_at']),
  )..reserved = r['reserved'] as int;

  @override
  List<Lot> loadAll() =>
      _c.select('SELECT * FROM lots ORDER BY expiry').map(_toLot).toList();

  @override
  void insertLot(Lot lot, {required StockMoveReason reason, String? note}) {
    _db.transaction(() {
      _c.execute(
        '''
        INSERT INTO lots
          (id, sku, name, zone, location_id, qty, reserved, expiry, received_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''',
        <Object?>[
          lot.id,
          lot.sku,
          lot.name,
          lot.zone.name,
          lot.locationId,
          lot.qty,
          lot.reserved,
          _iso(lot.expiry),
          _iso(lot.receivedAt),
        ],
      );
      _appendMove(
        lotId: lot.id,
        sku: lot.sku,
        delta: lot.qty,
        qtyAfter: lot.qty,
        reason: reason,
        at: lot.receivedAt,
        note: note,
      );
    });
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
    _db.transaction(() {
      final rows = _c.select(
        'SELECT sku, qty, reserved FROM lots WHERE id = ?',
        <Object?>[lotId],
      );
      if (rows.isEmpty) {
        throw StateError('로트 $lotId 를 찾을 수 없습니다.');
      }
      final sku = rows.first['sku'] as String;
      final qty = rows.first['qty'] as int;
      final reserved = rows.first['reserved'] as int;
      final after = qty + delta;
      if (after < 0) {
        throw StateError('로트 $lotId 재고 부족: 현재 $qty, 요청 $delta');
      }
      if (after < reserved) {
        throw StateError(
          '로트 $lotId 예약 수량($reserved)보다 적게 만들 수 없습니다: 결과 $after',
        );
      }
      _c.execute('UPDATE lots SET qty = ? WHERE id = ?', <Object?>[
        after,
        lotId,
      ]);
      _appendMove(
        lotId: lotId,
        sku: sku,
        delta: delta,
        qtyAfter: after,
        reason: reason,
        at: at,
        taskId: taskId,
        orderId: orderId,
        operator: operator,
        note: note,
      );
    });
  }

  void _appendMove({
    required String lotId,
    required String sku,
    required int delta,
    required int qtyAfter,
    required StockMoveReason reason,
    required DateTime at,
    String? taskId,
    String? orderId,
    String? operator,
    String? note,
  }) {
    _c.execute(
      '''
      INSERT INTO stock_moves
        (at, lot_id, sku, delta, qty_after, reason, task_id, order_id, operator, note)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      ''',
      <Object?>[
        _iso(at),
        lotId,
        sku,
        delta,
        qtyAfter,
        reason.name,
        taskId,
        orderId,
        operator,
        note,
      ],
    );
  }

  @override
  void setReserved(String lotId, int reserved) {
    _c.execute('UPDATE lots SET reserved = ? WHERE id = ?', <Object?>[
      reserved,
      lotId,
    ]);
  }

  @override
  void updateLocation(String lotId, String locationId) {
    _c.execute('UPDATE lots SET location_id = ? WHERE id = ?', <Object?>[
      locationId,
      lotId,
    ]);
  }

  @override
  List<StockMove> recentMoves({int limit = 200, String? lotId}) {
    final rows = lotId == null
        ? _c.select(
            'SELECT * FROM stock_moves ORDER BY id DESC LIMIT ?',
            <Object?>[limit],
          )
        : _c.select(
            'SELECT * FROM stock_moves WHERE lot_id = ? ORDER BY id DESC LIMIT ?',
            <Object?>[lotId, limit],
          );
    return rows
        .map(
          (r) => StockMove(
            id: r['id'] as int,
            at: _at(r['at']),
            lotId: r['lot_id'] as String,
            sku: r['sku'] as String,
            delta: r['delta'] as int,
            qtyAfter: r['qty_after'] as int,
            reason: StockMoveReason.values.byName(r['reason'] as String),
            taskId: r['task_id'] as String?,
            orderId: r['order_id'] as String?,
            operator: r['operator'] as String?,
            note: r['note'] as String?,
          ),
        )
        .toList();
  }
}

class _SqliteOrderRepository implements OrderRepository {
  _SqliteOrderRepository(this._db);

  final AppDatabase _db;

  Database get _c => _db.db;

  @override
  List<SalesOrder> loadRecent({int limit = 200}) {
    final rows = _c.select(
      'SELECT * FROM orders ORDER BY created_at DESC LIMIT ?',
      <Object?>[limit],
    );
    return rows.map((r) {
      final o = SalesOrder(
        id: r['id'] as String,
        customer: r['customer'] as String,
        urgency: Urgency.values.byName(r['urgency'] as String),
        createdAt: _at(r['created_at']),
        dueAt: _at(r['due_at']),
        lineCount: r['line_count'] as int,
      )
        ..state = OrderState.values.byName(r['state'] as String)
        ..doneLines = r['done_lines'] as int
        ..failedLines = r['failed_lines'] as int
        ..closedAt = _atOrNull(r['closed_at']);
      final taskIds = _c.select(
        'SELECT id FROM tasks WHERE order_id = ? ORDER BY created_at',
        <Object?>[o.id],
      );
      o.taskIds.addAll(taskIds.map((t) => t['id'] as String));
      return o;
    }).toList();
  }

  @override
  void insert(
    SalesOrder order, {
    String source = 'auto',
    bool expanded = true,
    List<OrderLine> lines = const <OrderLine>[],
  }) {
    _db.transaction(() {
      _insertOrder(order, source, expanded);
      for (var i = 0; i < lines.length; i++) {
        final l = lines[i];
        _c.execute(
          '''
          INSERT INTO order_lines (order_id, seq, sku, name, qty, lot_id)
          VALUES (?, ?, ?, ?, ?, ?)
          ''',
          <Object?>[order.id, i, l.sku, l.name, l.qty, l.lotId],
        );
      }
    });
  }

  void _insertOrder(SalesOrder order, String source, bool expanded) {
    _c.execute(
      '''
      INSERT INTO orders
        (id, customer, urgency, created_at, due_at, line_count, state,
         done_lines, failed_lines, closed_at, source, expanded)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      ''',
      <Object?>[
        order.id,
        order.customer,
        order.urgency.name,
        _iso(order.createdAt),
        _iso(order.dueAt),
        order.lineCount,
        order.state.name,
        order.doneLines,
        order.failedLines,
        order.closedAt == null ? null : _iso(order.closedAt!),
        source,
        expanded ? 1 : 0,
      ],
    );
  }

  @override
  List<SalesOrder> loadUnexpanded({int limit = 50}) {
    final rows = _c.select(
      'SELECT id FROM orders WHERE expanded = 0 ORDER BY created_at LIMIT ?',
      <Object?>[limit],
    );
    if (rows.isEmpty) return <SalesOrder>[];
    final ids = rows.map((r) => r['id'] as String).toSet();
    return loadRecent(limit: 500).where((o) => ids.contains(o.id)).toList()
      ..sort((a, b) => a.createdAt.compareTo(b.createdAt));
  }

  @override
  List<OrderLine> loadLines(String orderId) => _c
      .select(
        'SELECT * FROM order_lines WHERE order_id = ? ORDER BY seq',
        <Object?>[orderId],
      )
      .map(
        (r) => OrderLine(
          sku: r['sku'] as String,
          name: r['name'] as String,
          qty: r['qty'] as int,
          lotId: r['lot_id'] as String?,
        ),
      )
      .toList();

  @override
  void markExpanded(String orderId) {
    _c.execute('UPDATE orders SET expanded = 1 WHERE id = ?', <Object?>[
      orderId,
    ]);
  }

  @override
  void update(SalesOrder order) {
    _c.execute(
      '''
      UPDATE orders SET state = ?, done_lines = ?, failed_lines = ?, closed_at = ?
      WHERE id = ?
      ''',
      <Object?>[
        order.state.name,
        order.doneLines,
        order.failedLines,
        order.closedAt == null ? null : _iso(order.closedAt!),
        order.id,
      ],
    );
  }
}

class _SqliteTaskRepository implements TaskRepository {
  _SqliteTaskRepository(this._db);

  final AppDatabase _db;

  Database get _c => _db.db;

  @override
  List<WorkTask> loadRecent({int limit = 300}) {
    final rows = _c.select(
      'SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?',
      <Object?>[limit],
    );
    return rows.map((r) {
      final id = r['id'] as String;
      final steps = _c
          .select(
            'SELECT * FROM task_steps WHERE task_id = ? ORDER BY seq',
            <Object?>[id],
          )
          .map(
            (s) => TaskStep(
              kind: StepKind.values.byName(s['kind'] as String),
              label: s['label'] as String,
              target: Offset(
                (s['target_x'] as num).toDouble(),
                (s['target_y'] as num).toDouble(),
              ),
              duration: (s['duration'] as num).toDouble(),
              resourceId: s['resource_id'] as String?,
            ),
          )
          .toList();

      return WorkTask(
        id: id,
        type: TaskType.values.byName(r['type'] as String),
        title: r['title'] as String,
        urgency: Urgency.values.byName(r['urgency'] as String),
        zone: TempZone.values.byName(r['zone'] as String),
        steps: steps,
        createdAt: _at(r['created_at']),
        originLabel: r['origin_label'] as String,
        destLabel: r['dest_label'] as String,
        orderId: r['order_id'] as String?,
        sku: r['sku'] as String?,
        lotId: r['lot_id'] as String?,
        expiry: _atOrNull(r['expiry']),
        qty: r['qty'] as int,
        requestedBy: r['requested_by'] as String?,
      )
        ..state = TaskState.values.byName(r['state'] as String)
        ..robotId = r['robot_id'] as String?
        ..stepIndex = r['step_index'] as int
        ..retries = r['retries'] as int
        ..failReason = r['fail_reason'] as String?
        ..score = (r['score'] as num).toDouble()
        ..assignedAt = _atOrNull(r['assigned_at'])
        ..startedAt = _atOrNull(r['started_at'])
        ..endedAt = _atOrNull(r['ended_at']);
    }).toList();
  }

  @override
  void insert(WorkTask task) {
    _db.transaction(() {
      _c.execute(
        '''
        INSERT INTO tasks
          (id, type, title, urgency, zone, order_id, sku, lot_id, expiry, qty,
           requested_by, origin_label, dest_label, state, robot_id, step_index,
           retries, fail_reason, score, created_at, assigned_at, started_at, ended_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''',
        <Object?>[
          task.id,
          task.type.name,
          task.title,
          task.urgency.name,
          task.zone.name,
          task.orderId,
          task.sku,
          task.lotId,
          task.expiry == null ? null : _iso(task.expiry!),
          task.qty,
          task.requestedBy,
          task.originLabel,
          task.destLabel,
          task.state.name,
          task.robotId,
          task.stepIndex,
          task.retries,
          task.failReason,
          task.score,
          _iso(task.createdAt),
          task.assignedAt == null ? null : _iso(task.assignedAt!),
          task.startedAt == null ? null : _iso(task.startedAt!),
          task.endedAt == null ? null : _iso(task.endedAt!),
        ],
      );
      final stmt = _c.prepare('''
        INSERT INTO task_steps
          (task_id, seq, kind, label, target_x, target_y, duration, resource_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
      ''');
      try {
        for (var i = 0; i < task.steps.length; i++) {
          final s = task.steps[i];
          stmt.execute(<Object?>[
            task.id,
            i,
            s.kind.name,
            s.label,
            s.target.dx,
            s.target.dy,
            s.duration,
            s.resourceId,
          ]);
        }
      } finally {
        stmt.close();
      }
    });
  }

  @override
  void update(WorkTask task) {
    _c.execute(
      '''
      UPDATE tasks SET
        state = ?, robot_id = ?, step_index = ?, retries = ?, fail_reason = ?,
        score = ?, assigned_at = ?, started_at = ?, ended_at = ?
      WHERE id = ?
      ''',
      <Object?>[
        task.state.name,
        task.robotId,
        task.stepIndex,
        task.retries,
        task.failReason,
        task.score,
        task.assignedAt == null ? null : _iso(task.assignedAt!),
        task.startedAt == null ? null : _iso(task.startedAt!),
        task.endedAt == null ? null : _iso(task.endedAt!),
        task.id,
      ],
    );
  }

  @override
  int purgeTerminalBefore(DateTime cutoff) {
    _c.execute(
      '''
      DELETE FROM tasks
      WHERE state IN ('done', 'failed', 'cancelled') AND ended_at < ?
      ''',
      <Object?>[_iso(cutoff)],
    );
    return _c.updatedRows;
  }
}

class _SqliteEventRepository implements EventRepository {
  _SqliteEventRepository(this._db);

  final AppDatabase _db;

  Database get _c => _db.db;

  @override
  List<OpsEvent> loadRecent({
    int limit = 400,
    String? category,
    Severity? severity,
  }) {
    final where = <String>[];
    final args = <Object?>[];
    if (category != null) {
      where.add('category = ?');
      args.add(category);
    }
    if (severity != null) {
      where.add('severity = ?');
      args.add(severity.name);
    }
    final clause = where.isEmpty ? '' : 'WHERE ${where.join(' AND ')}';
    args.add(limit);
    return _c
        .select('SELECT * FROM events $clause ORDER BY id DESC LIMIT ?', args)
        .map(
          (r) => OpsEvent(
            id: (r['id'] as int).toString(),
            at: _at(r['at']),
            severity: Severity.values.byName(r['severity'] as String),
            category: r['category'] as String,
            source: r['source'] as String,
            message: r['message'] as String,
            taskId: r['task_id'] as String?,
            orderId: r['order_id'] as String?,
          ),
        )
        .toList();
  }

  @override
  void append(OpsEvent event) {
    _c.execute(
      '''
      INSERT INTO events (at, severity, category, source, message, task_id, order_id)
      VALUES (?, ?, ?, ?, ?, ?, ?)
      ''',
      <Object?>[
        _iso(event.at),
        event.severity.name,
        event.category,
        event.source,
        event.message,
        event.taskId,
        event.orderId,
      ],
    );
  }

  @override
  int purgeBefore(DateTime cutoff) {
    _c.execute('DELETE FROM events WHERE at < ?', <Object?>[_iso(cutoff)]);
    return _c.updatedRows;
  }
}

class _SqliteIncidentRepository implements IncidentRepository {
  _SqliteIncidentRepository(this._db);

  final AppDatabase _db;

  Database get _c => _db.db;

  @override
  List<Incident> loadRecent({int limit = 100}) {
    return _c
        .select(
          'SELECT * FROM incidents ORDER BY at DESC LIMIT ?',
          <Object?>[limit],
        )
        .map((r) {
          final inc = Incident(
            id: r['id'] as String,
            type: IncidentType.values.byName(r['type'] as String),
            at: _at(r['at']),
            description: r['description'] as String,
            zone: r['zone'] == null
                ? null
                : TempZone.values.byName(r['zone'] as String),
            pos: r['pos_x'] == null
                ? null
                : Offset(
                    (r['pos_x'] as num).toDouble(),
                    (r['pos_y'] as num).toDouble(),
                  ),
            radius: (r['radius'] as num).toDouble(),
          )
            ..active = (r['active'] as int) == 1
            ..clearedAt = _atOrNull(r['cleared_at']);
          final actions = r['actions'] as String;
          if (actions.isNotEmpty) inc.actions.addAll(actions.split(''));
          return inc;
        })
        .toList();
  }

  @override
  void insert(Incident incident) {
    _c.execute(
      '''
      INSERT INTO incidents
        (id, type, at, description, zone, pos_x, pos_y, radius, active, cleared_at, actions)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      ''',
      <Object?>[
        incident.id,
        incident.type.name,
        _iso(incident.at),
        incident.description,
        incident.zone?.name,
        incident.pos?.dx,
        incident.pos?.dy,
        incident.radius,
        incident.active ? 1 : 0,
        incident.clearedAt == null ? null : _iso(incident.clearedAt!),
        incident.actions.join(''),
      ],
    );
  }

  @override
  void update(Incident incident) {
    _c.execute(
      'UPDATE incidents SET active = ?, cleared_at = ? WHERE id = ?',
      <Object?>[
        incident.active ? 1 : 0,
        incident.clearedAt == null ? null : _iso(incident.clearedAt!),
        incident.id,
      ],
    );
  }
}

class _SqliteCounterRepository implements CounterRepository {
  _SqliteCounterRepository(this._db);

  final AppDatabase _db;

  Database get _c => _db.db;

  @override
  int next(String name) {
    return _db.transaction(() {
      _c.execute(
        '''
        INSERT INTO counters (name, value) VALUES (?, 1)
        ON CONFLICT(name) DO UPDATE SET value = value + 1
        ''',
        <Object?>[name],
      );
      return _c.select('SELECT value FROM counters WHERE name = ?', <Object?>[
            name,
          ]).first['value']
          as int;
    });
  }

  @override
  void ensureAtLeast(String name, int value) {
    _c.execute(
      '''
      INSERT INTO counters (name, value) VALUES (?, ?)
      ON CONFLICT(name) DO UPDATE SET value = MAX(value, excluded.value)
      ''',
      <Object?>[name, value],
    );
  }
}
