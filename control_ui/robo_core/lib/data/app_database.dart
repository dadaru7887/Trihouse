import 'dart:io';

import 'package:path/path.dart' as p;
import 'package:sqlite3/sqlite3.dart';

/// SQLite 연결과 스키마 마이그레이션을 담당한다.
///
/// 이 시스템의 **원장(system of record)은 이 데이터베이스**이며, 화면과
/// 제어 루프가 들고 있는 메모리 상태는 캐시다. 재기동하면 여기 남은 내용으로
/// 복원된다.
class AppDatabase {
  AppDatabase._(this.db, this.path);

  final Database db;

  /// 인메모리 DB인 경우 `:memory:`.
  final String path;

  /// 현재 스키마 버전. 올릴 때마다 [_migrations]에 단계를 추가한다.
  static const int schemaVersion = 2;

  /// 파일 기반 DB를 연다. 경로를 주지 않으면 사용자 데이터 디렉터리를 쓴다.
  factory AppDatabase.open({String? file}) {
    final target = file ?? defaultPath();
    Directory(p.dirname(target)).createSync(recursive: true);
    final db = sqlite3.open(target);
    _configure(db);
    _migrate(db);
    return AppDatabase._(db, target);
  }

  /// 테스트용 인메모리 DB.
  factory AppDatabase.memory() {
    final db = sqlite3.openInMemory();
    _configure(db);
    _migrate(db);
    return AppDatabase._(db, ':memory:');
  }

  /// `$XDG_DATA_HOME/robo_control/robo_control.db` (없으면 `~/.local/share/...`).
  static String defaultPath() {
    final env = Platform.environment;
    final base =
        env['ROBOAPP_DB_DIR'] ??
        env['XDG_DATA_HOME'] ??
        (env['HOME'] != null
            ? p.join(env['HOME']!, '.local', 'share')
            : Directory.systemTemp.path);
    return p.join(base, 'robo_control', 'robo_control.db');
  }

  static void _configure(Database db) {
    // WAL: 읽기(화면 갱신)와 쓰기(제어 루프)가 서로를 막지 않도록.
    db.execute('PRAGMA journal_mode = WAL');
    db.execute('PRAGMA foreign_keys = ON');
    db.execute('PRAGMA busy_timeout = 3000');
  }

  static void _migrate(Database db) {
    final current = db.userVersion;
    for (var v = current; v < schemaVersion; v++) {
      db.execute('BEGIN');
      try {
        _migrations[v](db);
        db.userVersion = v + 1;
        db.execute('COMMIT');
      } catch (_) {
        db.execute('ROLLBACK');
        rethrow;
      }
    }
  }

  static final List<void Function(Database)> _migrations =
      <void Function(Database)>[_v1, _v2];

  /// 트랜잭션 헬퍼. 예외가 나면 롤백한다.
  T transaction<T>(T Function() body) {
    db.execute('BEGIN');
    try {
      final result = body();
      db.execute('COMMIT');
      return result;
    } catch (_) {
      db.execute('ROLLBACK');
      rethrow;
    }
  }

  bool get isEmpty =>
      db.select('SELECT COUNT(*) AS n FROM lots').first['n'] as int == 0;

  void close() => db.close();
}

void _v1(Database db) {
  db.execute('''
    CREATE TABLE robots (
      id              TEXT PRIMARY KEY,
      name            TEXT NOT NULL,
      model           TEXT NOT NULL,
      zone_rating     TEXT NOT NULL,
      home_charger_id TEXT NOT NULL,
      reserve         INTEGER NOT NULL DEFAULT 0,
      active          INTEGER NOT NULL DEFAULT 1,
      registered_at   TEXT NOT NULL,
      retired_at      TEXT
    );
  ''');

  // 로봇당 최신 스냅샷 1행. 고빈도 위치 갱신은 여기에만 반영한다.
  db.execute('''
    CREATE TABLE robot_telemetry (
      robot_id     TEXT PRIMARY KEY REFERENCES robots(id) ON DELETE CASCADE,
      at           TEXT NOT NULL,
      state        TEXT NOT NULL,
      battery      REAL NOT NULL,
      x            REAL NOT NULL,
      y            REAL NOT NULL,
      heading      REAL NOT NULL,
      task_id      TEXT,
      progress     REAL NOT NULL DEFAULT 0,
      activity     TEXT,
      odometer     REAL NOT NULL DEFAULT 0,
      power_saving INTEGER NOT NULL DEFAULT 0,
      completed    INTEGER NOT NULL DEFAULT 0,
      failed       INTEGER NOT NULL DEFAULT 0
    );
  ''');

  db.execute('''
    CREATE TABLE workers (
      id            TEXT PRIMARY KEY,
      name          TEXT NOT NULL,
      role          TEXT NOT NULL,
      zone          TEXT NOT NULL,
      active        INTEGER NOT NULL DEFAULT 1,
      registered_at TEXT NOT NULL,
      retired_at    TEXT
    );
  ''');

  db.execute('''
    CREATE TABLE lots (
      id          TEXT PRIMARY KEY,
      sku         TEXT NOT NULL,
      name        TEXT NOT NULL,
      zone        TEXT NOT NULL,
      location_id TEXT NOT NULL,
      qty         INTEGER NOT NULL,
      reserved    INTEGER NOT NULL DEFAULT 0,
      expiry      TEXT NOT NULL,
      received_at TEXT NOT NULL,
      CHECK (qty >= 0),
      CHECK (reserved >= 0),
      CHECK (reserved <= qty)
    );
  ''');
  db.execute('CREATE INDEX idx_lots_sku_expiry ON lots(sku, expiry)');
  db.execute('CREATE INDEX idx_lots_location ON lots(location_id)');

  // 재고 원장 — 수량이 바뀐 모든 사건을 append-only로 남긴다.
  db.execute('''
    CREATE TABLE stock_moves (
      id       INTEGER PRIMARY KEY AUTOINCREMENT,
      at       TEXT NOT NULL,
      lot_id   TEXT NOT NULL,
      sku      TEXT NOT NULL,
      delta    INTEGER NOT NULL,
      qty_after INTEGER NOT NULL,
      reason   TEXT NOT NULL,
      task_id  TEXT,
      order_id TEXT,
      operator TEXT,
      note     TEXT
    );
  ''');
  db.execute('CREATE INDEX idx_moves_at ON stock_moves(at DESC)');
  db.execute('CREATE INDEX idx_moves_lot ON stock_moves(lot_id)');

  db.execute('''
    CREATE TABLE orders (
      id           TEXT PRIMARY KEY,
      customer     TEXT NOT NULL,
      urgency      TEXT NOT NULL,
      created_at   TEXT NOT NULL,
      due_at       TEXT NOT NULL,
      line_count   INTEGER NOT NULL,
      state        TEXT NOT NULL,
      done_lines   INTEGER NOT NULL DEFAULT 0,
      failed_lines INTEGER NOT NULL DEFAULT 0,
      closed_at    TEXT,
      source       TEXT NOT NULL DEFAULT 'auto'
    );
  ''');
  db.execute('CREATE INDEX idx_orders_created ON orders(created_at DESC)');

  db.execute('''
    CREATE TABLE tasks (
      id           TEXT PRIMARY KEY,
      type         TEXT NOT NULL,
      title        TEXT NOT NULL,
      urgency      TEXT NOT NULL,
      zone         TEXT NOT NULL,
      order_id     TEXT,
      sku          TEXT,
      lot_id       TEXT,
      expiry       TEXT,
      qty          INTEGER NOT NULL DEFAULT 1,
      requested_by TEXT,
      origin_label TEXT NOT NULL,
      dest_label   TEXT NOT NULL,
      state        TEXT NOT NULL,
      robot_id     TEXT,
      step_index   INTEGER NOT NULL DEFAULT 0,
      retries      INTEGER NOT NULL DEFAULT 0,
      fail_reason  TEXT,
      score        REAL NOT NULL DEFAULT 0,
      created_at   TEXT NOT NULL,
      assigned_at  TEXT,
      started_at   TEXT,
      ended_at     TEXT
    );
  ''');
  db.execute('CREATE INDEX idx_tasks_state ON tasks(state)');
  db.execute('CREATE INDEX idx_tasks_created ON tasks(created_at DESC)');
  db.execute('CREATE INDEX idx_tasks_order ON tasks(order_id)');

  db.execute('''
    CREATE TABLE task_steps (
      task_id     TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
      seq         INTEGER NOT NULL,
      kind        TEXT NOT NULL,
      label       TEXT NOT NULL,
      target_x    REAL NOT NULL,
      target_y    REAL NOT NULL,
      duration    REAL NOT NULL,
      resource_id TEXT,
      PRIMARY KEY (task_id, seq)
    );
  ''');

  db.execute('''
    CREATE TABLE events (
      id       INTEGER PRIMARY KEY AUTOINCREMENT,
      at       TEXT NOT NULL,
      severity TEXT NOT NULL,
      category TEXT NOT NULL,
      source   TEXT NOT NULL,
      message  TEXT NOT NULL,
      task_id  TEXT,
      order_id TEXT
    );
  ''');
  db.execute('CREATE INDEX idx_events_at ON events(at DESC)');
  db.execute('CREATE INDEX idx_events_category ON events(category)');

  db.execute('''
    CREATE TABLE incidents (
      id          TEXT PRIMARY KEY,
      type        TEXT NOT NULL,
      at          TEXT NOT NULL,
      description TEXT NOT NULL,
      zone        TEXT,
      pos_x       REAL,
      pos_y       REAL,
      radius      REAL NOT NULL DEFAULT 0,
      active      INTEGER NOT NULL DEFAULT 1,
      cleared_at  TEXT,
      actions     TEXT NOT NULL DEFAULT ''
    );
  ''');
  db.execute('CREATE INDEX idx_incidents_at ON incidents(at DESC)');

  // 재기동 시에도 ID가 이어지도록 시퀀스를 저장한다.
  db.execute('''
    CREATE TABLE counters (
      name  TEXT PRIMARY KEY,
      value INTEGER NOT NULL
    );
  ''');
}

/// v2 — 주문 라인.
///
/// v1에서는 주문의 구성 품목이 태스크로만 표현됐다. 소비자 앱이 주문을 넣는
/// 순간에는 아직 태스크가 없으므로, 주문 자체가 품목·수량을 들고 있어야 한다.
/// 관제는 이 라인을 읽어 출고 태스크로 전개한다.
void _v2(Database db) {
  db.execute('''
    CREATE TABLE order_lines (
      order_id TEXT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
      seq      INTEGER NOT NULL,
      sku      TEXT NOT NULL,
      name     TEXT NOT NULL,
      qty      INTEGER NOT NULL,
      lot_id   TEXT,
      PRIMARY KEY (order_id, seq)
    );
  ''');
  db.execute('CREATE INDEX idx_order_lines_order ON order_lines(order_id)');

  // 관제가 아직 전개하지 않은 주문을 찾기 위한 표시.
  db.execute("ALTER TABLE orders ADD COLUMN expanded INTEGER NOT NULL DEFAULT 1");
}
