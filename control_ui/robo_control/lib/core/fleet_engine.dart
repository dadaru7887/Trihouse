import 'dart:async';
import 'dart:math' as math;
import 'dart:ui' show Offset;

import 'package:flutter/foundation.dart';

import 'package:robo_core/models/enums.dart';
import 'package:robo_core/models/event.dart';
import 'package:robo_core/models/inventory.dart';
import 'package:robo_core/models/robot.dart';
import 'package:robo_core/models/task.dart';
import 'package:robo_core/models/warehouse.dart';
import 'package:robo_core/data/repositories.dart';
import 'coordination.dart';
import 'layout.dart';
import 'robot_link.dart';
import 'scheduler.dart';

/// 로봇 한 대의 진행 정체 감시 상태.
class _StallWatch {
  _StallWatch(this.at);

  /// 마지막으로 유의미하게 움직인 지점.
  Offset at;

  /// 그 뒤로 제자리에 머문 시간(초).
  double seconds = 0;

  /// 이번 정체에서 경로 재계획을 이미 시도했는가.
  bool rerouted = false;

  void reset(Offset pos) {
    at = pos;
    seconds = 0;
    rerouted = false;
  }
}

/// 로봇팔에 지시한 적재 작업 한 건.
class _ArmJob {
  _ArmJob({required this.armId, required this.stationId});

  final String armId;
  final String stationId;

  /// 지시 후 경과 시간(초).
  double waited = 0;
  bool done = false;
  bool failed = false;
  String? reason;
}

/// 처리량 집계 버킷(5분 단위).
class ThroughputBucket {
  ThroughputBucket(this.label, this.completed, this.failed);

  final String label;
  int completed;
  int failed;
}

/// 관제 제어 로직 엔진.
///
/// **원장은 [store]이고, 이 클래스가 들고 있는 컬렉션은 캐시다.** 상태가
/// 바뀔 때마다 저장소에 기록하고(write-through), 기동 시에는 저장소에서
/// 복원한다. 저장소 구현을 PostgreSQL·REST로 바꿔도 이 클래스는 그대로다.
///
/// 로봇 거동(주행·집품)은 기본적으로 이 클래스 안에서 시뮬레이션된다. 다만
/// [link]로 접속한 로봇(Gazebo의 Pinky 등)은 예외로, **위치·배터리는 실장비의
/// 보고값을 그대로 쓰고 관제는 경로·정지·속도 상한만 하달한다.** 배차·안전·
/// 재고 로직은 두 경우 모두 동일하다.
class FleetEngine extends ChangeNotifier {
  FleetEngine({required this.store, DateTime? clock, RobotLinkServer? link})
    : link = link ?? RobotLinkServer() {
    simNow = clock ?? DateTime(2026, 7, 28, 9, 0);
    this.link
      ..onHello = _onLinkHello
      ..onDropped = _onLinkDropped
      ..onLog = _onLinkLog
      ..onArmHello = _onArmHello
      ..onArmDropped = _onArmDropped
      ..onArmResult = _onArmResult;
    _bootstrap();
  }

  /// 영속 저장소(원장).
  final DataStore store;

  /// 실장비(Gazebo Pinky 포함) 링크 서버.
  final RobotLinkServer link;

  /// 조작 주체 표기. 이력·재고 원장에 남는다.
  String operatorName = '관제';

  /// 시뮬레이션 루프 시작. 테스트에서는 호출하지 않고 정적 상태만 검사한다.
  void start() {
    _timer ??= Timer.periodic(
      const Duration(milliseconds: 200),
      (_) => tick(),
    );
    unawaited(_startLink());
  }

  Future<void> _startLink() async {
    final ok = await link.start();
    _log(
      ok ? Severity.info : Severity.warning,
      '운영',
      'LINK',
      ok
          ? '로봇 링크 게이트웨이 개방 — ${link.host}:${link.port}. '
                '현장 로봇(Gazebo Pinky 포함)의 접속을 대기합니다.'
          : '로봇 링크 게이트웨이를 열지 못했습니다(${link.lastError}). '
                '시뮬레이션 로봇만 운영합니다.',
    );
    notifyListeners();
  }

  static const Duration leaseTtl = Duration(seconds: 20);

  final WarehouseLayout layout = WarehouseLayout.build();
  late final Scheduler scheduler = Scheduler(layout);
  final TaskLedger ledger = TaskLedger();
  final math.Random _rng = math.Random(7);

  Timer? _timer;
  late DateTime simNow;

  bool paused = false;
  double speedMultiplier = 4;

  final List<Robot> robots = <Robot>[];
  final Map<String, WorkTask> tasks = <String, WorkTask>{};
  final List<String> taskOrder = <String>[];
  final List<SalesOrder> orders = <SalesOrder>[];
  final List<Lot> lots = <Lot>[];
  final List<Worker> workers = <Worker>[];
  final List<OpsEvent> events = <OpsEvent>[];
  final List<Incident> incidents = <Incident>[];
  final Map<TempZone, ZoneEnvironment> environment =
      <TempZone, ZoneEnvironment>{};
  final List<ThroughputBucket> throughput = <ThroughputBucket>[];

  /// 전체 비상정지 래치.
  bool globalEStop = false;

  String? selectedRobotId;

  int _seq = 0;
  double _orderTimer = 0;
  double _inboundTimer = 0;
  double _requestTimer = 0;
  double _bucketTimer = 0;
  double _beaconTimer = 0;
  double _deployCooldown = 0;

  int completedTotal = 0;
  int failedTotal = 0;
  int fefoPicks = 0;
  int fefoDeviations = 0;
  int safetyStopTotal = 0;
  int reassignedTotal = 0;
  double _cycleSecondsTotal = 0;
  int _cycleCount = 0;

  /// 마지막 상태 브로드캐스트 스냅샷(로봇 ↔ 관제 공유 뷰).
  List<RobotStatusBeacon> beacons = <RobotStatusBeacon>[];

  @override
  void dispose() {
    _timer?.cancel();
    unawaited(link.stop());
    super.dispose();
  }

  static const Map<String, String> _counterOf = <String, String>{
    'TSK': 'task',
    'ORD': 'order',
    'LOT': 'lot',
    'INC': 'incident',
  };

  String _id(String prefix) {
    final counter = _counterOf[prefix];
    if (counter == null) return '$prefix-${(++_seq).toString().padLeft(4, '0')}';
    return '$prefix-${store.counters.next(counter).toString().padLeft(4, '0')}';
  }

  void _persistRegistration(Robot r) {
    store.robots.register(
      RobotRegistration(
        id: r.id,
        name: r.name,
        model: r.model,
        zoneRating: r.zoneRating,
        homeChargerId: r.homeChargerId,
        reserve: r.reserve,
        registeredAt: simNow,
      ),
    );
  }

  void _saveTask(WorkTask t) => store.tasks.update(t);

  void _saveOrder(SalesOrder o) => store.orders.update(o);

  /// 로트 예약 수량을 메모리와 저장소에 함께 반영한다.
  void _setReserved(Lot lot, int value) {
    lot.reserved = math.max(0, math.min(lot.qty, value));
    store.inventory.setReserved(lot.id, lot.reserved);
  }

  Lot? _lotById(String? id) => id == null
      ? null
      : lots.cast<Lot?>().firstWhere((l) => l?.id == id, orElse: () => null);

  // ────────────────────────────────────────────────────────────── 초기화

  void _bootstrap() {
    environment[TempZone.ambient] = ZoneEnvironment(
      zone: TempZone.ambient,
      temperatureC: 20.5,
      lux: 320,
      friction: 0.78,
      slopeDeg: 0.4,
      humidity: 45,
    );
    environment[TempZone.chilled] = ZoneEnvironment(
      zone: TempZone.chilled,
      temperatureC: 2.6,
      lux: 240,
      friction: 0.63,
      slopeDeg: 1.2,
      humidity: 78,
    );
    environment[TempZone.frozen] = ZoneEnvironment(
      zone: TempZone.frozen,
      temperatureC: -21.4,
      lux: 180,
      friction: 0.52,
      slopeDeg: 2.1,
      humidity: 88,
    );

    final fresh = store.inventory.loadAll().isEmpty;
    if (fresh) {
      _seedLots();
      _seedRobots();
      _seedWorkers();
    } else {
      _restore();
    }
    _seedThroughput();

    _log(
      Severity.info,
      '시스템',
      'FMS',
      fresh
          ? '신규 데이터베이스 초기화. 로봇 ${robots.length}대 · 로트 ${lots.length}건 등록.'
          : '데이터베이스에서 복원. 로봇 ${robots.length}대 · 로트 ${lots.length}건 · '
                '미완결 태스크 ${tasks.values.where((t) => !t.isTerminal).length}건.',
    );

    if (fresh) {
      for (var i = 0; i < 4; i++) {
        _spawnOrder();
      }
      _spawnInbound();
    }
  }

  /// 저장소에 남아 있는 운영 상태를 메모리 캐시로 되살린다.
  void _restore() {
    lots.addAll(store.inventory.loadAll());

    for (final reg in store.robots.loadActive()) {
      final robot = Robot(
        id: reg.id,
        name: reg.name,
        model: reg.model,
        pos: layout.stationById[reg.homeChargerId]?.pos ?? const Offset(50, 22),
        homeChargerId: reg.homeChargerId,
        zoneRating: reg.zoneRating,
        reserve: reg.reserve,
        state: reg.reserve ? RobotState.standby : RobotState.idle,
      );
      final snap = store.robots.loadSnapshot(reg.id);
      if (snap != null) {
        robot
          ..pos = Offset(snap.x, snap.y)
          ..heading = snap.heading
          ..battery = snap.battery
          ..odometer = snap.odometer
          ..powerSaving = snap.powerSaving
          ..completedTasks = snap.completed
          ..failedTasks = snap.failed
          // 재기동 직후에는 어떤 로봇도 작업 중이 아니다.
          // 미완결 태스크는 아래에서 대기열로 되돌린다.
          ..state = reg.reserve ? RobotState.standby : RobotState.idle;
      }
      robots.add(robot);
    }

    workers.addAll(
      store.workers.loadActive().map(
        (w) => Worker(
          id: w.id,
          name: w.name,
          role: w.role,
          zone: w.zone,
          pos: _randomCorridorPoint(w.zone),
        ),
      ),
    );

    orders.addAll(store.orders.loadRecent());

    for (final t in store.tasks.loadRecent()) {
      // 진행 중이던 태스크는 담당 로봇 연결이 끊긴 상태이므로 대기열로 되돌린다.
      if (!t.isTerminal &&
          (t.state == TaskState.inProgress ||
              t.state == TaskState.claimed ||
              t.state == TaskState.blocked)) {
        t
          ..state = TaskState.pending
          ..robotId = null
          ..stepIndex = 0
          ..startedAt = null
          ..failReason = '관제 재기동으로 회수';
        for (final step in t.steps) {
          step.elapsed = 0;
        }
        store.tasks.update(t);
      }
      tasks[t.id] = t;
      taskOrder.add(t.id);
    }

    incidents.addAll(store.incidents.loadRecent());
    events.addAll(store.events.loadRecent());

    completedTotal = tasks.values.where((t) => t.state == TaskState.done).length;
    failedTotal = tasks.values.where((t) => t.state == TaskState.failed).length;

    // 예약 수량은 살아 있는 태스크 기준으로 다시 계산한다.
    for (final lot in lots) {
      lot.reserved = 0;
    }
    for (final t in tasks.values) {
      if (t.isTerminal || t.lotId == null) continue;
      final lot = lots.cast<Lot?>().firstWhere(
        (l) => l?.id == t.lotId,
        orElse: () => null,
      );
      if (lot == null) continue;
      lot.reserved = math.min(lot.qty, lot.reserved + t.qty);
    }
    for (final lot in lots) {
      store.inventory.setReserved(lot.id, lot.reserved);
    }
  }

  static const List<List<String>> _catalog = <List<String>>[
    <String>['SKU-A1', '생수 2L 6입', 'ambient'],
    <String>['SKU-A2', '즉석밥 24입', 'ambient'],
    <String>['SKU-A3', '라면 멀티팩', 'ambient'],
    <String>['SKU-A4', '식용유 1.8L', 'ambient'],
    <String>['SKU-C1', '우유 1L 6입', 'chilled'],
    <String>['SKU-C2', '샐러드 팩', 'chilled'],
    <String>['SKU-C3', '숙성 삼겹살', 'chilled'],
    <String>['SKU-C4', '요구르트 12입', 'chilled'],
    <String>['SKU-F1', '냉동만두 1.4kg', 'frozen'],
    <String>['SKU-F2', '아이스크림 벌크', 'frozen'],
    <String>['SKU-F3', '냉동새우 1kg', 'frozen'],
    <String>['SKU-F4', '냉동피자 3입', 'frozen'],
  ];

  TempZone _zoneFromCode(String code) => switch (code) {
    'chilled' => TempZone.chilled,
    'frozen' => TempZone.frozen,
    _ => TempZone.ambient,
  };

  void _seedLots() {
    final byZone = <TempZone, List<StorageLocation>>{
      for (final z in TempZone.values) z: layout.locationsIn(z).toList()..shuffle(_rng),
    };
    final cursor = <TempZone, int>{for (final z in TempZone.values) z: 0};

    for (final item in _catalog) {
      final zone = _zoneFromCode(item[2]);
      // SKU마다 유통기한이 서로 다른 로트 4개를 만든다 → FEFO 판단 대상.
      for (var k = 0; k < 4; k++) {
        final pool = byZone[zone]!;
        final idx = cursor[zone]!;
        if (idx >= pool.length) break;
        cursor[zone] = idx + 1;
        final loc = pool[idx];
        final shelfLife = switch (zone) {
          TempZone.ambient => 40 + _rng.nextInt(180),
          TempZone.chilled => 2 + _rng.nextInt(22),
          TempZone.frozen => 60 + _rng.nextInt(240),
        };
        final lot = Lot(
            id: _id('LOT'),
            sku: item[0],
            name: item[1],
            zone: zone,
            locationId: loc.id,
            qty: 12 + _rng.nextInt(60),
            expiry: simNow.add(Duration(days: shelfLife, hours: _rng.nextInt(24))),
            receivedAt: simNow.subtract(Duration(days: 1 + _rng.nextInt(20))),
        );
        lots.add(lot);
        store.inventory.insertLot(lot, reason: StockMoveReason.initial);
      }
    }
  }

  void _seedRobots() {
    void add(
      String id,
      String name,
      String model,
      Set<TempZone> rating,
      String charger,
      Offset pos,
      double battery, {
      bool reserve = false,
    }) {
      final robot = Robot(
          id: id,
          name: name,
          model: model,
          pos: pos,
          homeChargerId: charger,
          zoneRating: rating,
          battery: battery,
          state: reserve ? RobotState.standby : RobotState.idle,
          reserve: reserve,
      );
      robots.add(robot);
      _persistRegistration(robot);
    }

    const warm = <TempZone>{TempZone.ambient, TempZone.chilled};
    const all = <TempZone>{TempZone.ambient, TempZone.chilled, TempZone.frozen};

    add('RS-01', '알파', 'RSX-200', warm, 'CHG-1', const Offset(20, 22), 96);
    add('RS-02', '브라보', 'RSX-200', warm, 'CHG-1', const Offset(35, 54), 88);
    add('RS-03', '찰리', 'RSX-200', warm, 'CHG-2', const Offset(50, 38), 74);
    add('RS-04', '델타', 'RSX-220', warm, 'CHG-2', const Offset(65, 22), 63);
    add('RS-05', '에코', 'RSX-300C', all, 'CHG-4', const Offset(95, 54), 91);
    add('RS-06', '폭스트롯', 'RSX-300C', all, 'CHG-4', const Offset(110, 38), 45);
    add('RS-07', '골프', 'RSX-220', warm, 'CHG-3', const Offset(65, 68), 100, reserve: true);
    add('RS-08', '호텔', 'RSX-300C', all, 'CHG-3', const Offset(80, 68), 100, reserve: true);
  }

  void _seedWorkers() {
    const defs = <List<String>>[
      <String>['W-01', '김선우', '피킹', 'ambient'],
      <String>['W-02', '이도현', '검수', 'ambient'],
      <String>['W-03', '박서연', '포장', 'ambient'],
      <String>['W-04', '최민재', '냉장 피킹', 'chilled'],
      <String>['W-05', '정하늘', '냉장 검수', 'chilled'],
      <String>['W-06', '한지우', '냉동 피킹', 'frozen'],
    ];
    for (final d in defs) {
      final zone = _zoneFromCode(d[3]);
      final worker = Worker(
        id: d[0],
        name: d[1],
        role: d[2],
        zone: zone,
        pos: _randomCorridorPoint(zone),
      );
      workers.add(worker);
      store.workers.register(worker, simNow);
    }
  }

  void _seedThroughput() {
    var t = simNow.subtract(const Duration(minutes: 55));
    for (var i = 0; i < 11; i++) {
      throughput.add(
        ThroughputBucket(_hhmm(t), 9 + _rng.nextInt(9), _rng.nextInt(2)),
      );
      t = t.add(const Duration(minutes: 5));
    }
    throughput.add(ThroughputBucket(_hhmm(simNow), 0, 0));
  }

  static String _hhmm(DateTime t) =>
      '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';

  Offset _randomCorridorPoint(TempZone zone) {
    final xs = WarehouseLayout.corridorX
        .where((x) => WarehouseLayout.zoneOfX(x) == zone)
        .toList();
    final x = xs.isEmpty
        ? 60.0
        : xs[_rng.nextInt(xs.length)];
    final y = WarehouseLayout
        .corridorY[_rng.nextInt(WarehouseLayout.corridorY.length)];
    return Offset(x, y);
  }

  // ────────────────────────────────────────────────────────────── 메인 루프

  /// 시뮬레이션 1스텝. 타이머가 주기적으로 호출하며, 테스트에서는 직접
  /// 호출해 결정론적으로 진행시킬 수 있다.
  @visibleForTesting
  void tick() {
    if (paused) return;
    final dt = 0.2 * effectiveSpeedMultiplier;
    simNow = simNow.add(Duration(milliseconds: (dt * 1000).round()));

    _pullTelemetry();
    _updateEnvironment(dt);
    _updateWorkers(dt);
    _spawnDemand(dt);
    _reapLeases();
    _intakeCustomerOrders(dt);
    _assign();
    for (final r in robots) {
      _stepRobot(r, dt);
    }
    _pushLinkCommands();
    _fleetScaling(dt);
    _rollBuckets(dt);
    _broadcast(dt);

    notifyListeners();
  }

  // ────────────────────────────────────────────── 실장비 링크(Gazebo Pinky 등)

  /// 실장비가 붙어 있으면 배속을 강제로 1×로 낮춘다.
  ///
  /// 현장 로봇은 실시간으로 움직인다. 관제 시계만 4배로 흐르면 로봇이
  /// 유독 느린 것처럼 보이고 배터리·처리량 지표도 왜곡된다.
  bool get realTimeLocked => link.linkedCount > 0;

  double get effectiveSpeedMultiplier => realTimeLocked ? 1.0 : speedMultiplier;

  /// 이 로봇이 실장비 링크로 제어되는가(현재 접속 중).
  bool isLinked(Robot r) => link.isLinked(r.id);

  /// 링크 전용 로봇인데 접속이 끊긴 상태인가.
  bool isLinkOffline(Robot r) => _linkManaged(r) && !link.isLinked(r.id);

  /// 링크로만 움직이는 기종(자체 시뮬레이션 대상이 아님).
  static bool _linkManaged(Robot r) => r.model.toUpperCase().startsWith('PINKY');

  /// 경유 웨이포인트 소진 반경(unit). 로봇 쪽 값(1.2)보다 조금 넉넉해야
  /// 관제가 영원히 도착을 기다리는 일이 없다.
  static const double _linkReach = 1.3;

  /// 종점 도착 판정 반경(unit = 0.5 m). 랙 슬롯 좌표는 선반 중심선이라
  /// 로봇이 그 위에 설 수 없다. 현장 로봇도 통로에 정지해 슬롯에 접근한다.
  static const double _linkGoalReach = 5.0;

  Robot? _robotById(String id) =>
      robots.cast<Robot?>().firstWhere((r) => r?.id == id, orElse: () => null);

  /// 로봇이 보고한 실제 포즈·배터리를 관제 상태에 반영한다.
  void _pullTelemetry() {
    for (final r in robots) {
      final t = link.telemetryOf(r.id);
      if (t == null) continue;
      r.pos = Offset(
        WarehouseLayout.clampX(t.x),
        WarehouseLayout.clampY(t.y),
      );
      r.heading = t.heading;
      r.battery = t.battery.clamp(0.0, 100.0);
      r.speed = t.speed;
      r.odometer = t.odometer;
      r.pushTrace(r.pos);
    }
  }

  /// 스텝 판정 후 로봇에게 내려보낼 명령을 정리한다.
  void _pushLinkCommands() {
    for (final r in robots) {
      if (!link.isLinked(r.id)) continue;
      final holding = r.state == RobotState.estop;
      link.sendHold(
        r.id,
        holding,
        reason: holding ? (r.safetyNote ?? '관제 정지 명령') : null,
      );
      link.sendCharge(r.id, r.state == RobotState.charging);
      link.sendSpeed(r.id, holding ? 0 : _speedOf(r));
      link.sendPath(
        r.id,
        _linkWaypoints(r),
        label: r.destinationLabel,
        goalTolerance: _linkGoalReach,
      );
    }
  }

  /// 진행 중인 로봇팔 적재 작업(태스크 ID → 작업 상태).
  final Map<String, _ArmJob> _armJobs = <String, _ArmJob>{};

  /// 팔이 응답하지 않을 때 자동 진행으로 넘어가는 한계 시간(초).
  static const double _armTimeout = 45;

  /// 적재 스텝을 진행시켜도 되는지 판단한다.
  ///
  /// 이 구획 적재 스테이션에 **실물 로봇팔이 접속해 있고** 로봇도 실장비라면,
  /// 팔에게 적재를 지시하고 완료 보고를 기다린다. 둘 중 하나라도 시뮬레이션이면
  /// (팔이 없거나 로봇이 Gazebo에 없으면) 다른 스텝과 똑같이 시간으로 진행한다.
  ///
  /// `true`를 돌려주면 호출자가 평소대로 스텝 시간을 누적한다.
  bool _serveLoadStep(Robot r, WorkTask t, TaskStep step, double dt) {
    final stationId = step.resourceId;
    if (stationId == null) return true;

    final armId = link.armAtStation(stationId);
    if (armId == null || !link.isLinked(r.id)) return true;

    final job = _armJobs[t.id];
    if (job == null) {
      _armJobs[t.id] = _ArmJob(armId: armId, stationId: stationId);
      link.sendLoad(
        armId,
        robotId: r.id,
        taskId: t.id,
        item: t.sku == null ? t.title : '${t.sku} ${t.qty}개',
        qty: t.qty,
        robotPos: r.pos,
      );
      _log(
        Severity.info,
        '작업',
        armId,
        '$stationId 로봇팔에 ${r.id}(${r.name}) 적재 지시 — '
            '${t.sku ?? t.title} ${t.qty}개.',
        taskId: t.id,
      );
      r.safetyNote = '로봇팔 적재 지시 전달';
      _drain(r, dt, 0.01);
      return false;
    }

    if (job.failed) {
      _armJobs.remove(t.id);
      link.sendLoadAbort(job.armId, t.id);
      _failStep(r, t, '로봇팔 적재 실패 — ${job.reason ?? "사유 미보고"}');
      return false;
    }

    if (job.done) {
      _armJobs.remove(t.id);
      _log(
        Severity.info,
        '작업',
        job.armId,
        '${job.stationId} 로봇팔 적재 완료 — ${r.id}(${r.name}) 인수.',
        taskId: t.id,
      );
      step.elapsed = step.duration;
      _finishStep(r, t, step);
      return false;
    }

    job.waited += dt;
    if (job.waited > _armTimeout) {
      _armJobs.remove(t.id);
      link.sendLoadAbort(job.armId, t.id);
      _log(
        Severity.warning,
        '작업',
        job.armId,
        '${job.stationId} 로봇팔이 ${_armTimeout.toStringAsFixed(0)}초 내 응답하지 않았습니다. '
            '수동 적재로 전환합니다.',
        taskId: t.id,
      );
      return true; // 자동 진행으로 넘어간다(교착 방지).
    }

    r.safetyNote = '${job.stationId} 로봇팔 적재 중';
    step.elapsed = math.min(job.waited, step.duration * 0.95);
    _drain(r, dt, 0.01);
    return false;
  }

  void _onArmResult(String armId, String taskId, bool ok, String? reason) {
    final job = _armJobs[taskId];
    if (job == null || job.armId != armId) return;
    if (ok) {
      job.done = true;
    } else {
      job.failed = true;
      job.reason = reason;
    }
    notifyListeners();
  }

  void _onArmHello(ArmHello hello) {
    _log(
      Severity.info,
      '가용성',
      hello.id,
      '${hello.id}(${hello.model}) ${hello.stationId} 적재 스테이션 접속. '
          '${hello.zone?.label ?? "구획 미상"} 구획 출고 화물을 로봇에 적재합니다.',
    );
    notifyListeners();
  }

  void _onArmDropped(String armId) {
    // 이 팔을 기다리던 작업은 자동 진행으로 풀어 준다.
    _armJobs.removeWhere((_, job) => job.armId == armId);
    _log(
      Severity.warning,
      '가용성',
      armId,
      '$armId 적재 스테이션 링크 단절. 해당 구획 적재는 수동 처리로 전환합니다.',
    );
    notifyListeners();
  }

  /// 실장비에 내려보낼 웨이포인트 열.
  ///
  /// 관제 경로의 종점은 랙 슬롯 좌표(선반 중심선)다. 통로 교차점에서 거기로
  /// 대각선으로 파고들면 실물 로봇은 선반 모서리에 막혀 슬롯 정면에 서지
  /// 못한다. 그래서 슬롯 바로 앞 통로 지점을 한 점 끼워 넣어 **정면 진입**
  /// 시킨다. 관제가 들고 있는 [Robot.path]는 그대로 두므로 도착 판정과
  /// 시뮬레이션 로봇의 거동은 영향을 받지 않는다.
  List<Offset> _linkWaypoints(Robot r) {
    if (r.path.isEmpty) return r.path;
    final goal = r.path.last;
    final inRack = WarehouseLayout.rackRowY.any(
      (y) => (goal.dy - y).abs() <= 3.2,
    );
    if (!inRack) return r.path;

    // 로봇이 진입하는 쪽 통로를 고른다(랙을 관통하지 않도록).
    final fromY = r.path.length >= 2 ? r.path[r.path.length - 2].dy : r.pos.dy;
    var aisleY = WarehouseLayout.corridorY.first;
    for (final y in WarehouseLayout.corridorY) {
      if ((y - fromY).abs() < (aisleY - fromY).abs()) aisleY = y;
    }

    final approach = Offset(goal.dx, aisleY);
    if ((approach - goal).distance < 1.0) return r.path;
    return <Offset>[...r.path.take(r.path.length - 1), approach, goal];
  }

  /// 실장비는 관제가 위치를 적분하지 않는다. 실제로 지나간 웨이포인트만
  /// 소진해 스텝 완료 판정에 쓴다.
  void _advanceLinked(Robot r, double dt) {
    while (r.path.isNotEmpty) {
      final reach = r.path.length == 1 ? _linkGoalReach : _linkReach;
      if ((r.path.first - r.pos).distance > reach) break;
      r.path.removeAt(0);
    }
    if (r.state == RobotState.moving && r.speed < 0.05) {
      final t = link.telemetryOf(r.id);
      if (t?.note != null) r.safetyNote = t!.note;
    }
    _watchStall(r, dt);
  }

  /// 진행 정체 감시(태스크 ID → 감시 상태).
  final Map<String, _StallWatch> _stalls = <String, _StallWatch>{};

  /// 경로 재계획까지의 정체 한계(초).
  static const double _stallReroute = 25;

  /// 태스크 회수까지의 정체 한계(초).
  static const double _stallRequeue = 55;

  /// 관제는 통로 그래프만 알고 있어서, 현장에만 있는 장애물(적재 스테이션
  /// 받침대·낙하물 등) 앞에 로봇이 갇히면 스스로 빠져나오지 못한다.
  ///
  /// **관제가 이동을 허용했는데도 로봇이 실제로 나아가지 못하면** 먼저 경로를
  /// 다시 깔아 주고, 그래도 풀리지 않으면 태스크를 회수해 다른 로봇에 넘긴다.
  void _watchStall(Robot r, double dt) {
    final watch = _stalls.putIfAbsent(r.id, () => _StallWatch(r.pos));

    // 갈 길이 없거나 관제가 정지시킨 상태면 정체가 아니다.
    if (r.path.isEmpty || _speedOf(r) < 0.05) {
      watch.reset(r.pos);
      return;
    }
    if ((r.pos - watch.at).distance > 0.6) {
      watch.reset(r.pos);
      return;
    }

    watch.seconds += dt;
    if (watch.seconds < _stallReroute) return;

    final t = r.taskId == null ? null : tasks[r.taskId];
    if (watch.seconds >= _stallRequeue && t != null) {
      _stalls.remove(r.id);
      r.path.clear();
      _requeue(t, '경로 정체 — ${watch.seconds.toStringAsFixed(0)}초간 진행 없음');
      _log(
        Severity.serious,
        '작업',
        r.id,
        '${r.name}이(가) (${r.pos.dx.toStringAsFixed(1)}, '
            '${r.pos.dy.toStringAsFixed(1)}) 지점에서 '
            '${watch.seconds.toStringAsFixed(0)}초간 진행하지 못했습니다. '
            '${t.id}를 회수해 재할당합니다. '
            '현장 사유: ${r.safetyNote ?? "미보고"}',
        taskId: t.id,
      );
      return;
    }

    if (!watch.rerouted) {
      watch.rerouted = true;
      final goal = r.path.last;
      r.path = layout.route(r.pos, goal);
      _log(
        Severity.warning,
        '작업',
        r.id,
        '${r.name} 진행 정체 ${watch.seconds.toStringAsFixed(0)}초 — 경로를 다시 계획합니다. '
            '현장 사유: ${r.safetyNote ?? "미보고"}',
        taskId: r.taskId,
      );
    }
  }

  /// 로봇이 자기소개를 보냈다. 신규면 플릿에 등록하고, 기존이면 복귀시킨다.
  void _onLinkHello(RobotHello hello) {
    final zones = <TempZone>{
      for (final code in hello.zoneCodes) ...<TempZone>{
        if (_zoneFromLinkCode(code) case final TempZone z) z,
      },
    };
    if (zones.isEmpty) zones.add(TempZone.ambient);

    final charger = layout.stationById[hello.homeChargerId];
    final homeId = charger != null && charger.kind == StationKind.charger
        ? charger.id
        : layout.stations
              .firstWhere(
                (s) => s.kind == StationKind.charger && zones.contains(s.zone),
                orElse: () => layout.stationById['CHG-1']!,
              )
              .id;

    final existing = _robotById(hello.id);
    if (existing != null) {
      existing
        ..reserve = false
        ..powerSaving = false
        ..state = RobotState.idle
        ..activity = null
        ..safetyNote = null
        ..pos = Offset(
          WarehouseLayout.clampX(hello.pos.dx),
          WarehouseLayout.clampY(hello.pos.dy),
        )
        ..heading = hello.heading
        ..battery = hello.battery.clamp(0.0, 100.0)
        ..path.clear();
      store.robots.setReserve(existing.id, false);
      _log(
        Severity.info,
        '가용성',
        hello.id,
        '${hello.id}(${existing.name}) 현장 링크 재접속. '
            '배터리 ${hello.battery.toStringAsFixed(0)}%로 운영에 복귀합니다.',
      );
    } else {
      final robot = Robot(
        id: hello.id,
        name: hello.name,
        model: hello.model,
        pos: Offset(
          WarehouseLayout.clampX(hello.pos.dx),
          WarehouseLayout.clampY(hello.pos.dy),
        ),
        homeChargerId: homeId,
        zoneRating: zones,
        battery: hello.battery.clamp(0.0, 100.0),
      );
      robot.heading = hello.heading;
      robots.add(robot);
      _persistRegistration(robot);
      _log(
        Severity.info,
        '가용성',
        hello.id,
        '${hello.id}(${hello.name}, ${hello.model}) 현장 링크 접속. '
            '대응 구획 ${zones.map((z) => z.label).join("·")}, 홈 충전소 $homeId. '
            '위치·배터리는 실장비 보고값을 사용합니다.',
      );
    }
    beacons = robots.map((r) => RobotStatusBeacon.of(r, simNow)).toList();
    notifyListeners();
  }

  /// 링크가 끊겼다. 로봇 상태를 신뢰할 수 없으므로 태스크를 회수한다.
  void _onLinkDropped(String robotId) {
    final r = _robotById(robotId);
    if (r == null) return;
    final carried = r.taskId;
    if (carried != null) {
      final t = tasks[carried];
      if (t != null) _requeue(t, '현장 링크 단절');
    }
    ledger.releaseAllOf(r.id);
    for (final s in layout.stations) {
      if (s.occupiedBy == r.id) s.occupiedBy = null;
    }
    r
      ..path.clear()
      ..speed = 0
      ..reserve = true
      ..state = RobotState.standby
      ..activity = '현장 링크 대기';
    _log(
      Severity.serious,
      '가용성',
      robotId,
      '$robotId(${r.name}) 현장 링크 단절. '
          '${carried == null ? "진행 중 태스크 없음" : "$carried 회수 후 재할당 대기열로 반환"}. '
          '재접속 전까지 배차 대상에서 제외합니다.',
      taskId: carried,
    );
    notifyListeners();
  }

  void _onLinkLog(String robotId, String severity, String message) {
    final r = _robotById(robotId);
    if (r == null || message.isEmpty) return;
    _log(
      switch (severity) {
        'critical' => Severity.critical,
        'serious' => Severity.serious,
        'warning' => Severity.warning,
        _ => Severity.info,
      },
      '작업',
      robotId,
      '${r.name}: $message',
    );
    notifyListeners();
  }

  static TempZone? _zoneFromLinkCode(String code) => switch (code.toLowerCase()) {
    'ambient' || 'a' => TempZone.ambient,
    'chilled' || 'c' => TempZone.chilled,
    'frozen' || 'f' => TempZone.frozen,
    _ => null,
  };

  // ─────────────────────────────────────────────────────── 환경(3온도) 변동

  double _envLogTimer = 0;

  void _updateEnvironment(double dt) {
    _envLogTimer -= dt;
    for (final e in environment.values) {
      final setpoint = e.zone.midC;
      e.temperatureC +=
          (setpoint - e.temperatureC) * 0.02 * dt + (_rng.nextDouble() - 0.5) * 0.18;

      // 도크 개방·제상 사이클로 인한 일시적 이탈.
      if (_rng.nextDouble() < 0.0015) {
        e.temperatureC += (e.zone == TempZone.ambient ? 2.5 : 3.4);
        _log(
          Severity.warning,
          '환경',
          'ENV',
          '${e.zone.label} 구역 온도 상승 감지 (${e.temperatureC.toStringAsFixed(1)}℃). 제상/도크 개방 추정.',
        );
      }

      final baseLux = switch (e.zone) {
        TempZone.ambient => 320.0,
        TempZone.chilled => 240.0,
        TempZone.frozen => 180.0,
      };
      final target = e.powerOn ? baseLux : 45.0;
      e.lux += (target - e.lux) * 0.08 * dt + (_rng.nextDouble() - 0.5) * 3;

      final baseFriction = switch (e.zone) {
        TempZone.ambient => 0.78,
        TempZone.chilled => 0.63,
        TempZone.frozen => 0.52,
      };
      e.friction += (baseFriction - e.friction) * 0.03 * dt +
          (_rng.nextDouble() - 0.5) * 0.006;
      e.friction = e.friction.clamp(0.30, 0.90);

      e.slopeDeg += (_rng.nextDouble() - 0.5) * 0.05;
      e.slopeDeg = e.slopeDeg.clamp(0.0, 4.5);
      e.humidity += (_rng.nextDouble() - 0.5) * 0.6;

      if (_envLogTimer <= 0 && e.performanceIndex < 0.62) {
        _log(
          Severity.warning,
          '환경',
          'ENV',
          '${e.zone.label} 구역 주행 성능 지수 ${(e.performanceIndex * 100).toStringAsFixed(0)}%. '
              '해당 구역 최고 속도 자동 하향.',
        );
        _envLogTimer = 45;
      }
    }
  }

  // ────────────────────────────────────────────────────────────── 작업자

  void _updateWorkers(double dt) {
    for (final w in workers) {
      if (w.inDistress) continue;
      final d = (w.target - w.pos).distance;
      if (d < 0.6) {
        w.target = _randomCorridorPoint(w.zone);
        continue;
      }
      final v = 1.1 * dt;
      w.pos = WarehouseLayout.lerp(w.pos, w.target, math.min(1.0, v / d));
    }
  }

  double _nearestWorkerDistance(Offset p) {
    var best = double.infinity;
    for (final w in workers) {
      final d = (w.pos - p).distance;
      if (d < best) best = d;
    }
    return best;
  }

  Robot? _robotAhead(Robot r) {
    if (r.path.isEmpty) return null;
    for (final o in robots) {
      if (identical(o, r) || o.reserve) continue;
      final d = (o.pos - r.pos).distance;
      if (d > 5.0) continue;
      // 진행 방향 앞쪽에 있고, ID 우선순위가 높은 로봇에게 양보한다.
      final toWp = r.path.first - r.pos;
      final toOther = o.pos - r.pos;
      final dot = toWp.dx * toOther.dx + toWp.dy * toOther.dy;
      if (dot > 0 && o.id.compareTo(r.id) < 0) return o;
    }
    return null;
  }

  // ────────────────────────────────────────────────────────────── 수요 생성

  void _spawnDemand(double dt) {
    if (_safetyBlocksScheduling) return;

    // 대기열이 처리 능력을 크게 넘어서면 신규 주문 접수를 잠시 멈춘다.
    // (실제 운영에서 WMS가 무한정 오더를 내리지 않는 것과 같은 제약)
    final backlog = tasks.values
        .where((t) => t.state == TaskState.pending)
        .length;

    _orderTimer -= dt;
    if (_orderTimer <= 0) {
      _orderTimer = 10 + _rng.nextDouble() * 12;
      if (backlog < 40) _spawnOrder();
    }

    _inboundTimer -= dt;
    if (_inboundTimer <= 0) {
      _inboundTimer = 18 + _rng.nextDouble() * 16;
      _spawnInbound();
    }

    _requestTimer -= dt;
    if (_requestTimer <= 0) {
      _requestTimer = 16 + _rng.nextDouble() * 18;
      _spawnWorkerRequest();
    }

    // 유통기한 경과 로트 회수.
    if (_rng.nextDouble() < 0.002) {
      final expired = lots.where((l) => l.expiryPressure(simNow) > 0.985 && l.available > 0);
      if (expired.isNotEmpty) {
        _spawnDisposal(expired.first);
      }
    }
  }

  void _spawnOrder() {
    final urgency = switch (_rng.nextInt(10)) {
      0 => Urgency.critical,
      1 || 2 => Urgency.high,
      9 => Urgency.low,
      _ => Urgency.normal,
    };
    final lines = 1 + _rng.nextInt(3);
    final dueMinutes = switch (urgency) {
      Urgency.critical => 12,
      Urgency.high => 25,
      Urgency.normal => 45,
      Urgency.low => 90,
    };
    final order = SalesOrder(
      id: _id('ORD'),
      customer: _customers[_rng.nextInt(_customers.length)],
      urgency: urgency,
      createdAt: simNow,
      dueAt: simNow.add(Duration(minutes: dueMinutes)),
      lineCount: lines,
    );
    store.orders.insert(order);
    orders.insert(0, order);
    if (orders.length > 80) orders.removeLast();

    for (var i = 0; i < lines; i++) {
      final item = _catalog[_rng.nextInt(_catalog.length)];
      final task = _buildOutboundTask(order, item[0], item[1]);
      if (task != null) order.taskIds.add(task.id);
    }
    if (order.taskIds.isEmpty) {
      order.state = OrderState.failed;
      _log(Severity.warning, '스케줄', 'SCHED', '${order.id} 가용 재고 없음. 주문 보류.',
          orderId: order.id);
    } else {
      _log(
        Severity.info,
        '스케줄',
        'SCHED',
        '${order.id} 접수 (${order.customer}, ${urgency.label}, 납기 ${_hhmm(order.dueAt)}) — '
            '태스크 ${order.taskIds.length}건 생성.',
        orderId: order.id,
      );
    }
  }

  static const List<String> _customers = <String>[
    '강남 스토어',
    '수도권 DC',
    '부산 지점',
    '온라인 새벽배송',
    '대전 허브',
    '광주 지점',
  ];

  /// FEFO 원칙에 따라 유통기한이 가장 임박한 로트를 선택한다.
  /// 1순위 로트가 다른 로봇에 점유되어 있으면 차순위를 쓰고 이탈로 기록한다.
  WorkTask? _buildOutboundTask(
    SalesOrder order,
    String sku,
    String name, {
    int? fixedQty,
    String? preferredLotId,
  }) {
    final candidates = scheduler.fefoOrder(
      lots.where((l) => l.sku == sku && !l.isExpired(simNow)),
      simNow,
    );
    if (candidates.isEmpty) return null;

    Lot? chosen;

    // 관제가 로트를 지정한 경우 FEFO보다 우선한다(사유는 이력에 남는다).
    if (preferredLotId != null) {
      final picked = candidates.cast<Lot?>().firstWhere(
        (l) => l?.id == preferredLotId,
        orElse: () => null,
      );
      if (picked != null) {
        chosen = picked;
        if (picked.id == candidates.first.id) {
          fefoPicks++;
        } else {
          fefoDeviations++;
          _log(
            Severity.warning,
            '스케줄',
            'FEFO',
            '$sku 1순위 로트 ${candidates.first.id} 대신 관제 지정 로트 ${picked.id} 사용. '
                'FEFO 이탈로 기록.',
            orderId: order.id,
          );
        }
      }
    }

    if (chosen == null) {
    for (var i = 0; i < candidates.length; i++) {
      final lot = candidates[i];
      if (ledger.resourceOwner(lot.locationId) != null) continue;
      chosen = lot;
      if (i == 0) {
        fefoPicks++;
      } else {
        fefoDeviations++;
        _log(
          Severity.warning,
          '스케줄',
          'FEFO',
          '$sku 1순위 로트 ${candidates.first.id}(${_dateLabel(candidates.first.expiry)}) '
              '점유 중 → 차순위 ${lot.id} 할당. FEFO 이탈로 기록.',
          orderId: order.id,
        );
      }
      break;
    }
    }
    chosen ??= candidates.first;

    final loc = layout.locationById[chosen.locationId]!;
    final dock = layout.nearest(StationKind.outboundDock, loc.pos);
    final bay = layout.loadingStation(loc.zone);
    // 가용 수량을 넘겨 예약하면 재고가 음수가 되므로 잔량으로 상한을 둔다.
    final qty = math.min(
      fixedQty ?? (1 + _rng.nextInt(4)),
      chosen.available,
    );
    if (qty <= 0) return null;
    _setReserved(chosen, chosen.reserved + qty);

    final task = WorkTask(
      id: _id('TSK'),
      type: TaskType.outbound,
      title: '$name 출고',
      urgency: order.urgency,
      zone: loc.zone,
      createdAt: simNow,
      originLabel: loc.id,
      destLabel: dock.id,
      orderId: order.id,
      sku: sku,
      lotId: chosen.id,
      expiry: chosen.expiry,
      qty: qty,
      steps: <TaskStep>[
        TaskStep(
          kind: StepKind.move,
          label: '${loc.id} 랙으로 이동',
          target: loc.pos,
          duration: 0,
        ),
        TaskStep(
          kind: StepKind.pick,
          label: '${loc.id}에서 $name $qty개 집품',
          target: loc.pos,
          duration: 6,
          resourceId: loc.id,
        ),
        TaskStep(
          kind: StepKind.move,
          label: '${bay.id} 적재 스테이션으로 이동',
          target: bay.pos,
          duration: 0,
        ),
        TaskStep(
          kind: StepKind.load,
          label: '${bay.id} 로봇팔이 $name $qty개 적재',
          target: bay.pos,
          duration: 8,
          resourceId: bay.id,
        ),
        TaskStep(
          kind: StepKind.move,
          label: '${dock.id} 출고 도크로 이동',
          target: dock.pos,
          duration: 0,
        ),
        TaskStep(
          kind: StepKind.place,
          label: '${dock.id}에 하역 및 검수',
          target: dock.pos,
          duration: 7,
          resourceId: dock.id,
        ),
      ],
    );
    _register(task);
    return task;
  }

  void _spawnInbound() {
    final item = _catalog[_rng.nextInt(_catalog.length)];
    final zone = _zoneFromCode(item[2]);
    final dock = layout.stationById[_rng.nextBool() ? 'IN-1' : 'IN-2']!;
    final pool = layout.locationsIn(zone);
    final loc = pool[_rng.nextInt(pool.length)];
    final qty = 8 + _rng.nextInt(24);

    final task = WorkTask(
      id: _id('TSK'),
      type: TaskType.inbound,
      title: '${item[1]} 입고 적치',
      urgency: Urgency.normal,
      zone: zone,
      createdAt: simNow,
      originLabel: dock.id,
      destLabel: loc.id,
      sku: item[0],
      qty: qty,
      steps: <TaskStep>[
        TaskStep(
          kind: StepKind.move,
          label: '${dock.id} 입고 도크로 이동',
          target: dock.pos,
          duration: 0,
        ),
        TaskStep(
          kind: StepKind.scan,
          label: '입하 검수 및 라벨 스캔',
          target: dock.pos,
          duration: 5,
          resourceId: dock.id,
        ),
        TaskStep(
          kind: StepKind.move,
          label: '${loc.id} 로케이션으로 이동',
          target: loc.pos,
          duration: 0,
        ),
        TaskStep(
          kind: StepKind.place,
          label: '${loc.id}에 적치',
          target: loc.pos,
          duration: 6,
          resourceId: loc.id,
        ),
      ],
    );
    _register(task);
  }

  void _spawnWorkerRequest() {
    final w = workers[_rng.nextInt(workers.length)];
    if (w.inDistress) return;
    final relay = _rng.nextInt(10) < 4;
    final ws = layout.nearest(StationKind.workstation, w.pos);

    if (relay) {
      final others = workers.where((o) => o.id != w.id).toList();
      final peer = others[_rng.nextInt(others.length)];
      final peerWs = layout.nearest(StationKind.workstation, peer.pos);
      final task = WorkTask(
        id: _id('TSK'),
        type: TaskType.relay,
        title: '${w.name} → ${peer.name} 물품 전달',
        urgency: Urgency.high,
        zone: layout.zoneAt(ws.pos),
        createdAt: simNow,
        originLabel: ws.id,
        destLabel: peerWs.id,
        requestedBy: '${w.id} ${w.name}',
        steps: <TaskStep>[
          TaskStep(
            kind: StepKind.move,
            label: '${ws.id}(${w.name}) 위치로 이동',
            target: ws.pos,
            duration: 0,
          ),
          TaskStep(
            kind: StepKind.handover,
            label: '${w.name}로부터 물품 수령',
            target: ws.pos,
            duration: 5,
            resourceId: ws.id,
          ),
          TaskStep(
            kind: StepKind.move,
            label: '${peerWs.id}(${peer.name}) 위치로 이동',
            target: peerWs.pos,
            duration: 0,
          ),
          TaskStep(
            kind: StepKind.handover,
            label: '${peer.name}에게 인계',
            target: peerWs.pos,
            duration: 5,
            resourceId: peerWs.id,
          ),
        ],
      );
      _register(task);
      _log(
        Severity.info,
        '작업자 요청',
        w.id,
        '${w.name} → ${peer.name} 물품 전달 요청 접수. 태스크 ${task.id} 생성.',
        taskId: task.id,
      );
    } else {
      final pool = layout.locationsIn(w.zone);
      final loc = pool[_rng.nextInt(pool.length)];
      final item = _catalog.firstWhere(
        (c) => _zoneFromCode(c[2]) == w.zone,
        orElse: () => _catalog.first,
      );
      w.awaitingHandover = true;
      final task = WorkTask(
        id: _id('TSK'),
        type: TaskType.handover,
        title: '${item[1]} ${w.name}에게 전달',
        urgency: Urgency.high,
        zone: w.zone,
        createdAt: simNow,
        originLabel: loc.id,
        destLabel: ws.id,
        sku: item[0],
        requestedBy: '${w.id} ${w.name}',
        steps: <TaskStep>[
          TaskStep(
            kind: StepKind.move,
            label: '${loc.id} 랙으로 이동',
            target: loc.pos,
            duration: 0,
          ),
          TaskStep(
            kind: StepKind.pick,
            label: '${item[1]} 집품',
            target: loc.pos,
            duration: 5,
            resourceId: loc.id,
          ),
          TaskStep(
            kind: StepKind.move,
            label: '${ws.id} 작업 스테이션으로 이동',
            target: ws.pos,
            duration: 0,
          ),
          TaskStep(
            kind: StepKind.handover,
            label: '${w.name}에게 전달(안전 정지 후 인계)',
            target: ws.pos,
            duration: 6,
            resourceId: ws.id,
          ),
        ],
      );
      _register(task);
      _log(
        Severity.info,
        '작업자 요청',
        w.id,
        '${w.name}(${w.role}) 물품 전달 요청. 태스크 ${task.id} 생성.',
        taskId: task.id,
      );
    }
  }

  void _spawnDisposal(Lot lot) {
    final loc = layout.locationById[lot.locationId];
    if (loc == null) return;
    final dock = layout.nearest(StationKind.outboundDock, loc.pos);
    final task = WorkTask(
      id: _id('TSK'),
      type: TaskType.disposal,
      title: '${lot.name} 유통기한 회수',
      urgency: Urgency.critical,
      zone: lot.zone,
      createdAt: simNow,
      originLabel: loc.id,
      destLabel: dock.id,
      sku: lot.sku,
      lotId: lot.id,
      expiry: lot.expiry,
      steps: <TaskStep>[
        TaskStep(
          kind: StepKind.move,
          label: '${loc.id}로 이동',
          target: loc.pos,
          duration: 0,
        ),
        TaskStep(
          kind: StepKind.pick,
          label: '${lot.id} 회수',
          target: loc.pos,
          duration: 5,
          resourceId: loc.id,
        ),
        TaskStep(
          kind: StepKind.move,
          label: '${dock.id} 반출',
          target: dock.pos,
          duration: 0,
        ),
        TaskStep(
          kind: StepKind.place,
          label: '폐기 구역 하역',
          target: dock.pos,
          duration: 5,
          resourceId: dock.id,
        ),
      ],
    );
    _register(task);
    _log(
      Severity.serious,
      '스케줄',
      'FEFO',
      '${lot.id}(${lot.name}) 유통기한 임박/경과. 최우선 회수 태스크 발행.',
      taskId: task.id,
    );
  }

  void _register(WorkTask t) {
    tasks[t.id] = t;
    taskOrder.insert(0, t.id);
    store.tasks.insert(t);
    if (taskOrder.length > 300) {
      final removed = taskOrder.removeLast();
      final rt = tasks[removed];
      if (rt != null && rt.isTerminal) tasks.remove(removed);
    }
  }

  double _intakeTimer = 0;

  /// 소비자 앱이 접수한 주문을 읽어 출고 태스크로 전개한다.
  ///
  /// 소비자 앱은 주문과 라인만 기록하고(`expanded = 0`) 태스크는 만들지
  /// 않는다. 스케줄러·레이아웃을 아는 쪽은 관제이기 때문이다.
  void _intakeCustomerOrders(double dt) {
    _intakeTimer -= dt;
    if (_intakeTimer > 0) return;
    _intakeTimer = 3;

    for (final incoming in store.orders.loadUnexpanded()) {
      final lines = store.orders.loadLines(incoming.id);
      store.orders.markExpanded(incoming.id);

      // 이미 캐시에 있으면 재사용하고, 없으면 새로 담는다.
      final order = orders.cast<SalesOrder?>().firstWhere(
            (o) => o?.id == incoming.id,
            orElse: () => null,
          ) ??
          incoming;
      if (!orders.contains(order)) {
        orders.insert(0, order);
        if (orders.length > 80) orders.removeLast();
      }

      var created = 0;
      for (final line in lines) {
        if (line.qty <= 0) continue;
        final task = _buildOutboundTask(
          order,
          line.sku,
          line.name,
          fixedQty: line.qty,
          preferredLotId: line.lotId,
        );
        if (task != null) {
          order.taskIds.add(task.id);
          created++;
        }
      }

      if (created == 0) {
        order.state = OrderState.failed;
        order.closedAt = simNow;
        _saveOrder(order);
      }

      _log(
        created == 0 ? Severity.serious : Severity.info,
        '주문',
        'APP',
        '${order.id} 소비자 앱 주문 접수 (${order.customer}, ${order.urgency.label}) — '
            '라인 ${lines.length}건 중 $created건 태스크 전개'
            '${created == 0 ? " · 가용 재고 부족" : ""}.',
        orderId: order.id,
      );
    }
  }

  // ────────────────────────────────────────────────────────────── 스케줄링

  bool get _safetyBlocksScheduling =>
      globalEStop ||
      incidents.any((i) => i.active && i.type == IncidentType.fire);

  void _reapLeases() {
    for (final id in ledger.reapExpired(simNow)) {
      final t = tasks[id];
      if (t == null || t.isTerminal) continue;
      if (t.state == TaskState.inProgress || t.state == TaskState.claimed) {
        _log(
          Severity.serious,
          '스케줄',
          'SCHED',
          '${t.id} 리스 만료(로봇 ${t.robotId} 무응답). 태스크를 회수해 재할당합니다.',
          taskId: t.id,
        );
        _requeue(t, '리스 만료 회수');
      }
    }
  }

  void _assign() {
    if (_safetyBlocksScheduling) return;

    final pending = <WorkTask>[];
    for (final id in taskOrder) {
      final t = tasks[id];
      if (t == null) continue;
      if (t.state != TaskState.pending && t.state != TaskState.blocked) continue;
      if (_zoneBlocked(t.zone)) continue;
      final order = t.orderId == null
          ? null
          : orders.cast<SalesOrder?>().firstWhere(
              (o) => o?.id == t.orderId,
              orElse: () => null,
            );
      final lot = t.lotId == null
          ? null
          : lots.cast<Lot?>().firstWhere(
              (l) => l?.id == t.lotId,
              orElse: () => null,
            );
      t.score = scheduler.priority(t, simNow, lot: lot, order: order).total;
      pending.add(t);
    }
    if (pending.isEmpty) return;
    pending.sort((a, b) => b.score.compareTo(a.score));

    final free = robots.where((r) => r.isAvailable).toList();
    if (free.isEmpty) return;

    for (final task in pending) {
      final available = free.where((r) => r.taskId == null).toList();
      if (available.isEmpty) break;
      final bids = scheduler.collectBids(task, available, simNow);
      if (bids.isEmpty) continue;

      // 상위 2개 후보가 동시에 점유를 시도한다. 리스 레지스트리가
      // 단일 소유자만 승인하므로 중복 수행이 발생하지 않는다.
      Robot? winner;
      for (final b in bids.take(2)) {
        if (ledger.claim(task.id, b.robot.id, simNow, leaseTtl)) {
          winner ??= b.robot;
        } else if (winner != null) {
          _log(
            Severity.info,
            '스케줄',
            'LEDGER',
            '${task.id} 동시 점유 시도 차단: ${b.robot.id}는 ${winner.id}가 선점하여 반려됨.',
            taskId: task.id,
          );
        }
      }
      if (winner == null) continue;

      task.state = TaskState.claimed;
      task.robotId = winner.id;
      task.assignedAt = simNow;
      _saveTask(task);
      winner.taskId = task.id;
      winner.state = RobotState.moving;
      winner.taskProgress = 0;
      winner.path = <Offset>[];
      _log(
        Severity.info,
        '스케줄',
        'SCHED',
        '${task.id} → ${winner.id}(${winner.name}) 할당. '
            '우선순위 ${task.score.toStringAsFixed(0)}, ${task.type.label}, ${task.urgency.label}.',
        taskId: task.id,
        orderId: task.orderId,
      );
    }
  }

  bool _zoneBlocked(TempZone zone) => incidents.any(
    (i) => i.active && i.type == IncidentType.powerCut && i.zone == zone,
  );

  // ────────────────────────────────────────────────────────── 로봇 상태 갱신

  void _stepRobot(Robot r, double dt) {
    r.safetyNote = null;

    // 링크 전용 기종은 접속이 살아 있을 때만 운영에 넣는다. 관제가 임의로
    // 위치를 지어내면 실제 장비와 어긋나기 때문이다.
    if (isLinkOffline(r)) {
      r
        ..reserve = true
        ..state = RobotState.standby
        ..activity = '현장 링크 대기'
        ..speed = 0
        ..path.clear();
      r.idleSeconds += dt;
      return;
    }

    if (r.reserve) {
      r.state = RobotState.standby;
      r.idleSeconds += dt;
      return;
    }

    // 1) 안전 정책이 항상 최우선.
    final hold = _safetyHoldReason(r);
    if (hold != null) {
      if (r.state != RobotState.estop) {
        r.safetyStops++;
        safetyStopTotal++;
      }
      r.state = RobotState.estop;
      r.speed = 0;
      r.safetyNote = hold;
      _drain(r, dt, 0.01);
      return;
    }
    if (r.state == RobotState.estop) {
      r.state = r.taskId != null ? RobotState.moving : RobotState.idle;
    }

    // 2) 화재 시 비상 집결지로 대피.
    if (_evacuating) {
      _evacuate(r, dt);
      return;
    }

    // 3) 배터리 정책.
    _batteryPolicy(r, dt);

    switch (r.state) {
      case RobotState.charging:
        // 실장비는 충전 명령을 받아 스스로 회복하고 배터리를 보고한다.
        if (!link.isLinked(r.id)) {
          r.battery = math.min(100, r.battery + 0.55 * dt);
        }
        r.activity = '충전 중 (${r.battery.toStringAsFixed(0)}%)';
        if (r.battery >= 95) {
          final chg = layout.stationById[r.homeChargerId];
          for (final s in layout.stations) {
            if (s.occupiedBy == r.id) s.occupiedBy = null;
          }
          chg?.occupiedBy = null;
          r.powerSaving = false;
          r.state = RobotState.idle;
          r.activity = null;
          _log(Severity.info, '배터리', r.id, '${r.name} 충전 완료(95%). 작업 대기열 복귀.');
        }
        return;
      case RobotState.returning:
        _advance(r, dt);
        r.activity = '충전소 복귀 중';
        _drain(r, dt, 0.05);
        if (r.path.isEmpty) {
          r.state = RobotState.charging;
          _log(Severity.info, '배터리', r.id, '${r.name} 충전소 도킹. 충전을 시작합니다.');
        }
        return;
      case RobotState.error:
        r.activity = r.lastFault;
        if (r.lastFaultAt != null &&
            simNow.difference(r.lastFaultAt!).inSeconds > 8) {
          r.state = RobotState.idle;
          r.activity = null;
          _log(Severity.info, '작업', r.id, '${r.name} 오류 복구 완료. 정상 대기 상태.');
        }
        _drain(r, dt, 0.01);
        return;
      default:
        break;
    }

    if (r.taskId == null) {
      _idleBehaviour(r, dt);
      return;
    }
    _runTask(r, dt);
  }

  String? _safetyHoldReason(Robot r) {
    if (globalEStop) return '전체 비상정지 발령';
    for (final i in incidents.where((e) => e.active)) {
      switch (i.type) {
        case IncidentType.workerEmergency:
          if (i.pos != null && (r.pos - i.pos!).distance <= i.radius) {
            return '작업자 위급 반경 내 정지';
          }
        case IncidentType.powerCut:
          if (i.zone != null && layout.zoneAt(r.pos) == i.zone) {
            return '${i.zone!.label} 구역 전원 차단';
          }
        case IncidentType.eStop:
          return '비상정지 스위치 작동';
        case IncidentType.fire:
        case IncidentType.spill:
          break;
      }
    }
    return null;
  }

  bool get _evacuating =>
      incidents.any((i) => i.active && i.type == IncidentType.fire);

  void _evacuate(Robot r, double dt) {
    if (r.taskId != null) {
      final t = tasks[r.taskId];
      if (t != null) _requeue(t, '화재 대응 안전 종료');
    }
    final asm = layout.nearest(StationKind.assembly, r.pos);
    if (r.path.isEmpty && (r.pos - asm.pos).distance > 1.2) {
      r.path = layout.route(r.pos, asm.pos);
      r.destinationLabel = '${asm.id} 비상 집결지';
    }
    r.activity = '화재 대피 — ${asm.id}로 이동';
    r.state = r.path.isEmpty ? RobotState.idle : RobotState.moving;
    _advance(r, dt);
    _drain(r, dt, 0.04);
  }

  void _idleBehaviour(Robot r, double dt) {
    r.idleSeconds += dt;
    if (r.path.isNotEmpty) {
      r.state = RobotState.moving;
      _advance(r, dt);
      _drain(r, dt, 0.04);
      if (r.path.isEmpty) {
        r.state = r.powerSaving ? RobotState.powerSaving : RobotState.idle;
        r.destinationLabel = null;
      }
      return;
    }
    r.state = r.powerSaving ? RobotState.powerSaving : RobotState.idle;
    r.activity = r.powerSaving ? '절전 대기(최소 동선 이동 완료)' : null;
    r.speed = 0;
    _drain(r, dt, r.powerSaving ? 0.004 : 0.012);
  }

  void _runTask(Robot r, double dt) {
    final t = tasks[r.taskId];
    if (t == null || t.isTerminal) {
      r.taskId = null;
      return;
    }
    ledger.renew(t.id, r.id, simNow, leaseTtl);
    if (t.state == TaskState.claimed) {
      t.state = TaskState.inProgress;
      t.startedAt = simNow;
      _saveTask(t);
    }

    final step = t.currentStep;
    if (step == null) {
      _completeTask(r, t);
      return;
    }

    // 자원(랙 슬롯·도크·스테이션) 단일 점유 확보.
    if (step.resourceId != null && r.reservedResourceId != step.resourceId) {
      if (!ledger.acquireResource(step.resourceId!, r.id)) {
        r.state = RobotState.blocked;
        r.activity = '${step.resourceId} 점유 해제 대기';
        t.state = TaskState.inProgress;
        _drain(r, dt, 0.01);
        return;
      }
      _releaseResource(r);
      r.reservedResourceId = step.resourceId;
    }

    if (step.kind == StepKind.move) {
      if (r.path.isEmpty && (r.pos - step.target).distance > 0.9) {
        r.path = layout.route(r.pos, step.target);
        r.destinationLabel = t.destLabel;
      }
      r.state = RobotState.moving;
      r.activity = step.label;
      _advance(r, dt);
      _drain(r, dt, 0.085);
      if (r.path.isEmpty) _finishStep(r, t, step);
    } else {
      r.state = switch (step.kind) {
        StepKind.pick => RobotState.picking,
        StepKind.place => RobotState.placing,
        StepKind.handover => RobotState.handover,
        StepKind.load => RobotState.loading,
        StepKind.scan => RobotState.picking,
        _ => RobotState.idle,
      };
      r.activity = step.label;
      r.speed = 0;

      // 저온·저조도 환경에서는 매니퓰레이터/스캐너 성능이 떨어진다.
      final e = environment[layout.zoneAt(r.pos)]!;
      final eff = 0.5 + 0.5 * e.performanceIndex;

      // 인계 스텝은 작업자가 도착할 때까지 진행하지 않는다.
      if (step.kind == StepKind.handover &&
          _nearestWorkerDistance(r.pos) > 6.0) {
        r.safetyNote = '작업자 대기 중(인계 보류)';
        _drain(r, dt, 0.01);
        return;
      }

      // 적재 스텝은 실물 로봇팔이 붙어 있으면 팔의 완료 보고를 기다린다.
      if (step.kind == StepKind.load && !_serveLoadStep(r, t, step, dt)) {
        return;
      }

      step.elapsed += dt * eff;
      _drain(r, dt, 0.05);
      if (step.progress >= 1.0) _finishStep(r, t, step);
    }
    r.taskProgress = t.progress;
    r.workingSeconds += dt;
  }

  static const List<String> _faults = <String>[
    '바코드 인식 실패 — 라벨 손상 추정',
    '적재물 감지 센서 이상 — 재시도 필요',
    '팔레트 정렬 오차 초과',
    '저온 결로로 카메라 시야 확보 실패',
    '리프트 과부하 감지',
  ];

  void _finishStep(Robot r, WorkTask t, TaskStep step) {
    // 작업 스텝 완료 시점에 낮은 확률로 오류가 발생한다.
    if (step.kind != StepKind.move && _rng.nextDouble() < 0.012) {
      final reason = _faults[_rng.nextInt(_faults.length)];
      _failStep(r, t, reason);
      return;
    }

    if (step.kind == StepKind.pick || step.kind == StepKind.scan) {
      r.payload = t.sku == null ? t.title : '${t.sku} × ${t.qty}';
    }
    if (step.kind == StepKind.handover) {
      if (t.stepIndex == t.steps.length - 1) {
        r.handovers++;
        r.payload = null;
        for (final w in workers) {
          if ((w.pos - r.pos).distance < 8) w.awaitingHandover = false;
        }
      } else {
        r.payload = t.title;
      }
    }
    if (step.kind == StepKind.place) r.payload = null;

    t.stepIndex++;
    if (t.stepIndex >= t.steps.length) {
      _completeTask(r, t);
    } else {
      final next = t.steps[t.stepIndex];
      if (next.resourceId != r.reservedResourceId) _releaseResource(r);
    }
  }

  void _failStep(Robot r, WorkTask t, String reason) {
    r.lastFault = reason;
    r.lastFaultAt = simNow;
    r.state = RobotState.error;
    r.payload = null;
    _releaseResource(r);

    t.retries++;
    if (t.retries <= 2) {
      _log(
        Severity.warning,
        '작업',
        r.id,
        '${t.id} 스텝 실패: $reason. ${t.retries}차 재시도로 재할당합니다.',
        taskId: t.id,
        orderId: t.orderId,
      );
      _requeue(t, reason);
    } else {
      t.state = TaskState.failed;
      t.failReason = reason;
      t.endedAt = simNow;
      t.robotId = r.id;
      r.failedTasks++;
      failedTotal++;
      if (throughput.isNotEmpty) throughput.last.failed++;
      ledger.release(t.id);
      r.taskId = null;
      r.taskProgress = 0;
      _saveTask(t);
      _closeOrderLine(t, success: false);
      _releaseLotReservation(t);
      _log(
        Severity.serious,
        '작업',
        r.id,
        '${t.id} 최종 실패($reason). 3회 재시도 초과로 주문 라인 실패 처리.',
        taskId: t.id,
        orderId: t.orderId,
      );
    }
  }

  void _completeTask(Robot r, WorkTask t) {
    t.state = TaskState.done;
    t.endedAt = simNow;
    t.robotId = r.id;
    r.completedTasks++;
    completedTotal++;
    r.taskId = null;
    r.taskProgress = 0;
    r.activity = null;
    r.payload = null;
    r.destinationLabel = null;
    _releaseResource(r);
    ledger.release(t.id);
    if (throughput.isNotEmpty) throughput.last.completed++;

    final cycle = t.cycleTime;
    if (cycle != null) {
      _cycleSecondsTotal += cycle.inSeconds;
      _cycleCount++;
    }

    _saveTask(t);
    _applyInventoryEffect(t);
    _closeOrderLine(t, success: true);

    _log(
      Severity.info,
      '작업',
      r.id,
      '${t.id} 완료 (${t.type.label}, ${t.originLabel}→${t.destLabel}, '
          '소요 ${cycle?.inSeconds ?? 0}초).',
      taskId: t.id,
      orderId: t.orderId,
    );
  }

  /// 태스크 완료가 재고에 미치는 영향을 원장에 기록한다.
  ///
  /// 출고·회수는 수량을 줄이고, **입고는 새 로트를 만들거나 동일 로케이션의
  /// 같은 SKU 로트에 합산**한다. 모든 변경은 stock_moves에 남는다.
  void _applyInventoryEffect(WorkTask t) {
    switch (t.type) {
      case TaskType.outbound:
      case TaskType.disposal:
        final lot = _lotById(t.lotId);
        if (lot == null) return;
        _setReserved(lot, lot.reserved - t.qty);
        final delta = -math.min(t.qty, lot.qty);
        if (delta == 0) return;
        store.inventory.applyMove(
          lotId: lot.id,
          delta: delta,
          reason: t.type == TaskType.outbound
              ? StockMoveReason.outbound
              : StockMoveReason.disposal,
          at: simNow,
          taskId: t.id,
          orderId: t.orderId,
          operator: t.robotId,
        );
        lot.qty += delta;
      case TaskType.inbound:
        _receiveInbound(t);
      case TaskType.handover:
      case TaskType.relay:
      case TaskType.replenish:
        break;
    }
  }

  /// 입고 완료 → 재고 반영. 같은 로케이션·SKU·유통기한 로트가 있으면 합산하고,
  /// 없으면 새 로트를 생성한다.
  void _receiveInbound(WorkTask t) {
    if (t.sku == null || t.qty <= 0) return;
    final locationId = t.destLabel;
    final loc = layout.locationById[locationId];
    if (loc == null) return;

    final existing = lots.cast<Lot?>().firstWhere(
      (l) =>
          l != null &&
          l.sku == t.sku &&
          l.locationId == locationId &&
          l.expiry.difference(t.expiry ?? l.expiry).inHours.abs() < 24,
      orElse: () => null,
    );

    if (existing != null) {
      store.inventory.applyMove(
        lotId: existing.id,
        delta: t.qty,
        reason: StockMoveReason.inbound,
        at: simNow,
        taskId: t.id,
        operator: t.robotId,
        note: '$locationId 적치',
      );
      existing.qty += t.qty;
      _log(
        Severity.info,
        '재고',
        'WMS',
        '${t.id} 입고 반영: ${existing.id}에 ${t.qty}개 합산 (잔량 ${existing.qty}).',
        taskId: t.id,
      );
      return;
    }

    final item = _catalog.firstWhere(
      (c) => c[0] == t.sku,
      orElse: () => <String>[t.sku!, t.title, loc.zone.name],
    );
    final lot = Lot(
      id: _id('LOT'),
      sku: t.sku!,
      name: item[1],
      zone: loc.zone,
      locationId: locationId,
      qty: t.qty,
      expiry: t.expiry ?? simNow.add(Duration(days: _shelfLifeDays(loc.zone))),
      receivedAt: simNow,
    );
    lots.add(lot);
    store.inventory.insertLot(lot, reason: StockMoveReason.inbound, note: t.id);
    _log(
      Severity.info,
      '재고',
      'WMS',
      '${t.id} 입고 반영: 신규 로트 ${lot.id} 생성 ($locationId, ${lot.qty}개, '
          '유통기한 ${_dateLabel(lot.expiry)}).',
      taskId: t.id,
    );
  }

  int _shelfLifeDays(TempZone zone) => switch (zone) {
    TempZone.ambient => 40 + _rng.nextInt(180),
    TempZone.chilled => 2 + _rng.nextInt(22),
    TempZone.frozen => 60 + _rng.nextInt(240),
  };

  void _releaseLotReservation(WorkTask t) {
    final lot = _lotById(t.lotId);
    if (lot == null) return;
    _setReserved(lot, lot.reserved - t.qty);
  }

  void _closeOrderLine(WorkTask t, {required bool success}) {
    if (t.orderId == null) return;
    for (final o in orders) {
      if (o.id != t.orderId) continue;
      if (success) {
        o.doneLines++;
      } else {
        o.failedLines++;
      }
      o.state = OrderState.working;
      _saveOrder(o);
      if (o.doneLines + o.failedLines >= o.taskIds.length) {
        o.closedAt = simNow;
        o.state = o.failedLines == 0
            ? OrderState.fulfilled
            : (o.doneLines > 0 ? OrderState.partial : OrderState.failed);
        _log(
          o.state == OrderState.fulfilled ? Severity.info : Severity.warning,
          '주문',
          'WMS',
          '${o.id} ${o.state.label} (성공 ${o.doneLines} / 실패 ${o.failedLines}, '
              '${o.onTime ? "납기 준수" : "납기 초과"}).',
          orderId: o.id,
        );
        _saveOrder(o);
      }
      break;
    }
  }

  /// 진행 중 태스크의 안전 종료 후 대기열 복귀.
  void _requeue(WorkTask t, String reason) {
    final robot = t.robotId == null
        ? null
        : robots.cast<Robot?>().firstWhere(
            (r) => r?.id == t.robotId,
            orElse: () => null,
          );
    if (robot != null) {
      _releaseResource(robot);
      robot.taskId = null;
      robot.taskProgress = 0;
      robot.payload = null;
      robot.path = <Offset>[];
      robot.activity = null;
    }
    ledger.release(t.id);
    for (final s in t.steps) {
      s.elapsed = 0;
    }
    t.stepIndex = 0;
    t.state = TaskState.pending;
    t.robotId = null;
    t.startedAt = null;
    t.failReason = reason;
    _saveTask(t);
    reassignedTotal++;
  }

  void _releaseResource(Robot r) {
    if (r.reservedResourceId != null) {
      ledger.releaseResource(r.reservedResourceId!, r.id);
      r.reservedResourceId = null;
    }
  }

  // ────────────────────────────────────────────────────────────── 주행/배터리

  void _advance(Robot r, double dt) {
    if (link.isLinked(r.id)) {
      _advanceLinked(r, dt);
      return;
    }
    var budget = _speedOf(r) * dt;
    if (budget <= 0) {
      r.speed = 0;
      if (r.state == RobotState.moving) r.state = RobotState.yielding;
      return;
    }
    if (r.state == RobotState.yielding) r.state = RobotState.moving;

    while (budget > 0 && r.path.isNotEmpty) {
      final wp = r.path.first;
      final d = (wp - r.pos).distance;
      if (d <= budget) {
        r.heading = WarehouseLayout.headingOf(r.pos, wp);
        r.pos = wp;
        r.odometer += d;
        budget -= d;
        r.path.removeAt(0);
      } else {
        r.heading = WarehouseLayout.headingOf(r.pos, wp);
        r.pos = WarehouseLayout.lerp(r.pos, wp, budget / d);
        r.odometer += budget;
        budget = 0;
      }
    }
    r.speed = _speedOf(r);
    r.pushTrace(r.pos);
  }

  /// 환경·안전 조건을 모두 반영한 현재 허용 속도(unit/s).
  double _speedOf(Robot r) {
    final e = environment[layout.zoneAt(r.pos)]!;
    var v = 3.4 * e.tractionFactor * e.visibilityFactor * e.slopeFactor;

    r.localizationConfidence =
        (0.55 + 0.45 * e.visibilityFactor * e.tractionFactor).clamp(0.4, 0.99);
    if (r.localizationConfidence < 0.7) v *= 0.8;
    if (r.powerSaving) v *= 0.55;
    if (r.payload != null) v *= 0.92;

    final wd = _nearestWorkerDistance(r.pos);
    if (wd < 3.5) {
      r.safetyNote = '보호 필드(1.7m) — 정지';
      return 0;
    } else if (wd < 8.0) {
      r.safetyNote = '경고 필드(4m) — 감속 주행';
      v *= 0.35;
    }

    final ahead = _robotAhead(r);
    if (ahead != null) {
      r.safetyNote = '${ahead.id} 선행 — 교통 양보';
      v *= 0.22;
    }
    return v;
  }

  void _drain(Robot r, double dt, double rate) {
    // 실장비는 자기 배터리를 스스로 계산해 보고한다.
    if (link.isLinked(r.id)) return;
    final zone = layout.zoneAt(r.pos);
    final cold = switch (zone) {
      TempZone.frozen => 1.35,
      TempZone.chilled => 1.12,
      TempZone.ambient => 1.0,
    };
    final saving = r.powerSaving ? 0.6 : 1.0;
    r.battery = (r.battery - rate * cold * saving * dt).clamp(0.0, 100.0);
  }

  void _batteryPolicy(Robot r, double dt) {
    if (r.state == RobotState.charging || r.state == RobotState.returning) {
      return;
    }

    // 10% 이하 — 충전소 복귀.
    if (r.battery <= 10) {
      if (r.taskId != null) {
        final t = tasks[r.taskId];
        if (t != null) {
          _requeue(t, '배터리 10% 이하 안전 종료');
          _log(
            Severity.serious,
            '배터리',
            r.id,
            '${r.name} 배터리 ${r.battery.toStringAsFixed(0)}%. '
                '${t.id} 안전 종료 후 대기열에 반환하고 충전소로 복귀합니다.',
            taskId: t.id,
          );
        }
      }
      final chg = layout.nearest(StationKind.charger, r.pos, freeOnly: true);
      chg.occupiedBy = r.id;
      r.path = layout.route(r.pos, chg.pos);
      r.destinationLabel = '${chg.id} 충전소';
      r.state = RobotState.returning;
      r.powerSaving = true;
      _requestBackfill(r);
      return;
    }

    // 20% 이하 — 절전 모드 진입 + 최소 동선 이동.
    if (r.battery <= 20 && !r.powerSaving) {
      r.powerSaving = true;
      final t = r.taskId == null ? null : tasks[r.taskId];
      if (t != null && t.progress < 0.65) {
        _requeue(t, '배터리 20% 이하 절전 진입');
        _log(
          Severity.warning,
          '배터리',
          r.id,
          '${r.name} 배터리 20% 이하. 진행률 낮은 ${t.id}를 안전 종료·재할당하고 절전 모드로 전환합니다.',
          taskId: t.id,
        );
      } else if (t != null) {
        _log(
          Severity.warning,
          '배터리',
          r.id,
          '${r.name} 배터리 20% 이하. 진행 중인 ${t.id}(${(t.progress * 100).toStringAsFixed(0)}%)는 '
              '감속 상태로 마무리한 뒤 복귀합니다.',
          taskId: t.id,
        );
      } else {
        _log(Severity.warning, '배터리', r.id, '${r.name} 배터리 20% 이하. 절전 모드 전환.');
      }

      if (r.taskId == null) {
        // 최소 동선: 현재 위치에서 가장 가까운 대기 구역/충전소로만 이동.
        final standby = layout.nearest(StationKind.standby, r.pos);
        final charger = layout.nearest(StationKind.charger, r.pos);
        final target =
            layout.routeLength(r.pos, standby.pos) <=
                layout.routeLength(r.pos, charger.pos)
            ? standby
            : charger;
        r.path = layout.route(r.pos, target.pos);
        r.destinationLabel = '${target.id} (최소 동선)';
      }
      _requestBackfill(r);
    }

    if (r.battery > 35 && r.powerSaving && r.state != RobotState.returning) {
      r.powerSaving = false;
    }
  }

  /// 배터리 저하 로봇을 대체할 예비기를 단계적으로 투입한다.
  void _requestBackfill(Robot low) {
    if (_deployCooldown > 0) return;
    final reserveBot = robots.cast<Robot?>().firstWhere(
      (r) => r!.reserve && !isLinkOffline(r),
      orElse: () => null,
    );
    if (reserveBot == null) return;
    reserveBot.reserve = false;
    reserveBot.state = RobotState.idle;
    _deployCooldown = 25;
    _log(
      Severity.info,
      '가용성',
      'FMS',
      '${low.id} 배터리 저하에 따른 가용 대수 감소. 예비기 ${reserveBot.id}(${reserveBot.name})를 '
          '단계적으로 투입합니다.',
    );
  }

  void _fleetScaling(double dt) {
    _deployCooldown = math.max(0, _deployCooldown - dt);
    if (_deployCooldown > 0) return;

    final pending = tasks.values
        .where((t) => t.state == TaskState.pending)
        .length;
    final active = robots
        .where((r) => !r.reserve && r.isOperational && !r.powerSaving)
        .length;

    if (pending >= 5 && active < robots.length) {
      final reserveBot = robots.cast<Robot?>().firstWhere(
        (r) => r!.reserve && !isLinkOffline(r),
        orElse: () => null,
      );
      if (reserveBot != null) {
        reserveBot.reserve = false;
        reserveBot.state = RobotState.idle;
        _deployCooldown = 30;
        _log(
          Severity.info,
          '가용성',
          'FMS',
          '대기 태스크 $pending건 적체. 예비기 ${reserveBot.id}(${reserveBot.name}) 투입.',
        );
      }
    } else if (pending == 0 && active > 4) {
      final idleBot = robots.cast<Robot?>().firstWhere(
        (r) => !r!.reserve && r.state == RobotState.idle && r.battery > 60,
        orElse: () => null,
      );
      if (idleBot != null) {
        idleBot.reserve = true;
        idleBot.state = RobotState.standby;
        store.robots.setReserve(idleBot.id, true);
        _deployCooldown = 40;
        _log(
          Severity.info,
          '가용성',
          'FMS',
          '대기 태스크 없음. ${idleBot.id}(${idleBot.name})를 예비 대기로 전환해 배터리를 보존합니다.',
        );
      }
    }
  }

  void _rollBuckets(double dt) {
    _bucketTimer += dt;
    if (_bucketTimer < 300) return;
    _bucketTimer = 0;
    throughput.add(ThroughputBucket(_hhmm(simNow), 0, 0));
    while (throughput.length > 12) {
      throughput.removeAt(0);
    }
  }

  void _broadcast(double dt) {
    _beaconTimer -= dt;
    if (_beaconTimer > 0) return;
    _beaconTimer = 2;
    beacons = robots.map((r) => RobotStatusBeacon.of(r, simNow)).toList();
    store.robots.saveSnapshots(
      robots
          .map(
            (r) => RobotSnapshot(
              robotId: r.id,
              at: simNow,
              state: r.state,
              battery: r.battery,
              x: r.pos.dx,
              y: r.pos.dy,
              heading: r.heading,
              taskId: r.taskId,
              progress: r.taskProgress,
              activity: r.activity,
              odometer: r.odometer,
              powerSaving: r.powerSaving,
              completed: r.completedTasks,
              failed: r.failedTasks,
            ),
          )
          .toList(),
    );
  }

  // ────────────────────────────────────────────────────────────── 안전 제어

  Incident raiseIncident(
    IncidentType type, {
    TempZone? zone,
    Offset? pos,
    double radius = 0,
    String? description,
  }) {
    final inc = Incident(
      id: _id('INC'),
      type: type,
      at: simNow,
      description: description ?? type.label,
      zone: zone,
      pos: pos,
      radius: radius,
    );

    switch (type) {
      case IncidentType.fire:
        inc.actions.addAll(<String>[
          '전 로봇 신규 태스크 할당 중단',
          '진행 중 태스크 안전 종료 후 대기열 보류',
          '비상 집결지(ASM-1) 대피 경로 산출 및 이동',
          '해당 구획 전원 차단 요청 및 방화 셔터 연동',
          '작업자 대피 통로 확보(로봇 통로 진입 금지)',
        ]);
      case IncidentType.powerCut:
        environment[zone ?? TempZone.ambient]!.powerOn = false;
        inc.actions.addAll(<String>[
          '${(zone ?? TempZone.ambient).label} 구역 로봇 즉시 안전 정지',
          '비상 조도 전환 — 비전 측위 신뢰도 하향 반영',
          '해당 구역 태스크 할당 중단 및 타 구역 재배치',
          '냉장·냉동 온도 상승 모니터링 강화',
        ]);
      case IncidentType.workerEmergency:
        inc.actions.addAll(<String>[
          '반경 ${radius.toStringAsFixed(0)} unit 내 로봇 즉시 정지',
          '구조 통로 확보를 위한 우회 경로 재계산',
          '관리자/안전 담당 호출 및 이력 기록',
          '해당 구역 신규 태스크 진입 차단',
        ]);
      case IncidentType.eStop:
        globalEStop = true;
        inc.actions.addAll(<String>['전 로봇 동력 차단', '태스크 리스 동결', '수동 해제까지 할당 중단']);
      case IncidentType.spill:
        final e = environment[zone ?? TempZone.frozen]!;
        e.friction = math.max(0.32, e.friction - 0.22);
        inc.actions.addAll(<String>[
          '${(zone ?? TempZone.frozen).label} 구역 마찰계수 하향 반영',
          '해당 구역 최고 속도 제한',
          '청소/제빙 요청 발행',
        ]);
    }

    store.incidents.insert(inc);
    incidents.insert(0, inc);
    _log(
      type.severity,
      '안전',
      'SAFETY',
      '${type.label} 상황 발생 — ${inc.description}. 자동 대응 ${inc.actions.length}건 실행.',
    );
    notifyListeners();
    return inc;
  }

  void raiseWorkerEmergency() {
    final healthy = workers.where((w) => !w.inDistress).toList();
    if (healthy.isEmpty) return;
    final w = healthy[_rng.nextInt(healthy.length)];
    w.inDistress = true;
    raiseIncident(
      IncidentType.workerEmergency,
      pos: w.pos,
      radius: 16,
      zone: w.zone,
      description: '${w.name}(${w.id}, ${w.role}) 작업자 위급 신호 — ${w.zone.label} 구역',
    );
  }

  void clearIncident(String id) {
    for (final inc in incidents) {
      if (inc.id != id || !inc.active) continue;
      inc.active = false;
      inc.clearedAt = simNow;
      store.incidents.update(inc);
      if (inc.type == IncidentType.eStop) globalEStop = false;
      if (inc.type == IncidentType.powerCut && inc.zone != null) {
        environment[inc.zone!]!.powerOn = true;
      }
      if (inc.type == IncidentType.workerEmergency) {
        for (final w in workers) {
          w.inDistress = false;
        }
      }
      _log(
        Severity.info,
        '안전',
        'SAFETY',
        '${inc.type.label} 상황 해제. 보류된 태스크를 재할당하고 정상 운영으로 복귀합니다.',
      );
      break;
    }
    notifyListeners();
  }

  void toggleGlobalEStop() {
    if (globalEStop) {
      final active = incidents
          .cast<Incident?>()
          .firstWhere(
            (i) => i!.active && i.type == IncidentType.eStop,
            orElse: () => null,
          );
      if (active != null) {
        clearIncident(active.id);
      } else {
        globalEStop = false;
        _log(Severity.info, '안전', 'SAFETY', '전체 비상정지 해제. 정상 운영 복귀.');
        notifyListeners();
      }
    } else {
      raiseIncident(IncidentType.eStop, description: '관제 콘솔에서 전체 비상정지 발령');
    }
  }

  // ────────────────────────────────────────────────────────── 수동 운영 제어

  void setPaused(bool value) {
    paused = value;
    notifyListeners();
  }

  void setSpeed(double value) {
    speedMultiplier = value;
    notifyListeners();
  }

  void selectRobot(String? id) {
    selectedRobotId = id;
    notifyListeners();
  }

  Robot? get selectedRobot => selectedRobotId == null
      ? null
      : robots.cast<Robot?>().firstWhere(
          (r) => r?.id == selectedRobotId,
          orElse: () => null,
        );

  // ──────────────────────────────────────────────── 로봇·작업자 등록 / 해제

  /// `RS-09`처럼 기존 ID와 겹치지 않는 다음 번호를 만든다.
  String _nextId(String prefix, Iterable<String> existing) {
    var max = 0;
    for (final id in existing) {
      if (!id.startsWith('$prefix-')) continue;
      final n = int.tryParse(id.substring(prefix.length + 1));
      if (n != null && n > max) max = n;
    }
    return '$prefix-${(max + 1).toString().padLeft(2, '0')}';
  }

  /// 신규 로봇을 플릿에 등록한다.
  ///
  /// 대응 구획에 맞는 충전소를 홈으로 배정하고, 대기 구역에 배치한 뒤
  /// 즉시 스케줄링 대상에 포함시킨다(예비 등록 시에는 대기 상태로 둔다).
  Robot addRobot({
    required String name,
    required String model,
    required Set<TempZone> zoneRating,
    bool reserve = false,
    double battery = 100,
  }) {
    final id = _nextId('RS', robots.map((r) => r.id));
    final standby = layout.nearest(
      StationKind.standby,
      const Offset(50, 22),
    );
    final home = layout.stations.firstWhere(
      (s) => s.kind == StationKind.charger && zoneRating.contains(s.zone),
      orElse: () => layout.stationById['CHG-1']!,
    );

    final robot = Robot(
      id: id,
      name: name,
      model: model,
      pos: standby.pos,
      homeChargerId: home.id,
      zoneRating: zoneRating,
      battery: battery.clamp(0, 100),
      state: reserve ? RobotState.standby : RobotState.idle,
      reserve: reserve,
    );
    robots.add(robot);
    _persistRegistration(robot);
    beacons = robots.map((r) => RobotStatusBeacon.of(r, simNow)).toList();

    _log(
      Severity.info,
      '가용성',
      'FMS',
      '$id($name, $model) 신규 등록. 대응 구획 '
          '${zoneRating.map((z) => z.label).join("·")}, 홈 충전소 ${home.id}, '
          '${reserve ? "예비 대기" : "즉시 투입"}.',
    );
    notifyListeners();
    return robot;
  }

  /// 로봇을 플릿에서 해제한다.
  ///
  /// 진행 중이던 태스크는 안전 종료 후 대기열로 반환하고, 점유 중이던
  /// 리스·자원·충전소를 모두 회수해 다른 로봇이 이어받을 수 있게 한다.
  void removeRobot(Robot r) {
    final carried = r.taskId;
    if (carried != null) {
      final t = tasks[carried];
      if (t != null) _requeue(t, '로봇 등록 해제');
    }
    ledger.releaseAllOf(r.id);
    for (final s in layout.stations) {
      if (s.occupiedBy == r.id) s.occupiedBy = null;
    }

    robots.remove(r);
    store.robots.retire(r.id, simNow);
    beacons = beacons.where((b) => b.robotId != r.id).toList();
    if (selectedRobotId == r.id) selectedRobotId = null;

    _log(
      Severity.warning,
      '가용성',
      'FMS',
      '${r.id}(${r.name}) 등록 해제. '
          '${carried == null ? "진행 중 태스크 없음" : "$carried 안전 종료 후 재할당 대기열로 반환"}. '
          '잔여 로봇 ${robots.length}대.',
      taskId: carried,
    );
    notifyListeners();
  }

  /// 신규 작업자를 등록한다. 등록 즉시 안전 필드 계산에 포함된다.
  Worker addWorker({
    required String name,
    required String role,
    required TempZone zone,
  }) {
    final worker = Worker(
      id: _nextId('W', workers.map((w) => w.id)),
      name: name,
      role: role,
      zone: zone,
      pos: _randomCorridorPoint(zone),
    );
    workers.add(worker);
    store.workers.register(worker, simNow);
    _log(
      Severity.info,
      '안전',
      'SAFETY',
      '${worker.id}($name, $role) ${zone.label} 구역 작업자 등록. '
          '안전 필드 감시 대상에 포함합니다.',
    );
    notifyListeners();
    return worker;
  }

  /// 작업자를 해제한다. 위급 상태였다면 관련 상황도 함께 종료한다.
  void removeWorker(Worker w) {
    workers.remove(w);
    store.workers.retire(w.id, simNow);
    if (w.inDistress) {
      for (final inc in incidents) {
        if (inc.active && inc.type == IncidentType.workerEmergency) {
          inc.active = false;
          inc.clearedAt = simNow;
        }
      }
    }
    _log(
      Severity.warning,
      '안전',
      'SAFETY',
      '${w.id}(${w.name}) 작업자 해제. 잔여 작업자 ${workers.length}명.',
    );
    notifyListeners();
  }

  // ──────────────────────────────────── 수동 주문 접수 · 재고 조정 (운영 조작)

  /// 주문 라인 입력값.
  ///
  /// [lotId]를 지정하면 해당 로트를 강제 지정하고, 비우면 FEFO 규칙으로 고른다.
  /// 사용 가능한 SKU 목록은 [catalogSkus]로 얻는다.
  static List<List<String>> get catalogSkus => _catalog;

  /// SKU별 가용 수량(가용 = 총 수량 − 예약).
  int availableOf(String sku) => lots
      .where((l) => l.sku == sku && !l.isExpired(simNow))
      .fold<int>(0, (sum, l) => sum + l.available);

  /// FEFO 순으로 정렬된 해당 SKU의 가용 로트.
  List<Lot> availableLots(String sku) => scheduler.fefoOrder(
    lots.where((l) => l.sku == sku && !l.isExpired(simNow)),
    simNow,
  );

  /// 관제에서 주문을 직접 접수한다.
  ///
  /// 각 라인은 `(sku, qty, lotId?)`. 라인마다 출고 태스크를 만들며,
  /// 지정 로트가 없으면 FEFO 1순위부터 채운다. 재고가 모자란 라인은
  /// 생성하지 않고 사유를 이력에 남긴다.
  SalesOrder createOrder({
    required String customer,
    required Urgency urgency,
    required Duration dueIn,
    required List<({String sku, int qty, String? lotId})> lines,
  }) {
    final order = SalesOrder(
      id: _id('ORD'),
      customer: customer.trim().isEmpty ? '수동 접수' : customer.trim(),
      urgency: urgency,
      createdAt: simNow,
      dueAt: simNow.add(dueIn),
      lineCount: lines.length,
    );
    store.orders.insert(order, source: 'manual');
    orders.insert(0, order);
    if (orders.length > 80) orders.removeLast();

    var created = 0;
    for (final line in lines) {
      if (line.qty <= 0) continue;
      final item = _catalog.firstWhere(
        (c) => c[0] == line.sku,
        orElse: () => <String>[line.sku, line.sku, 'ambient'],
      );
      final task = _buildOutboundTask(
        order,
        line.sku,
        item[1],
        fixedQty: line.qty,
        preferredLotId: line.lotId,
      );
      if (task != null) {
        order.taskIds.add(task.id);
        created++;
      } else {
        _log(
          Severity.warning,
          '주문',
          operatorName,
          '${order.id} ${line.sku} ${line.qty}개 — 가용 재고 부족으로 태스크를 만들지 못했습니다.',
          orderId: order.id,
        );
      }
    }

    if (created == 0) {
      order.state = OrderState.failed;
      order.closedAt = simNow;
      _saveOrder(order);
    }

    _log(
      created == 0 ? Severity.serious : Severity.info,
      '주문',
      operatorName,
      '${order.id} 수동 접수 (${order.customer}, ${urgency.label}, '
          '납기 ${_hhmm(order.dueAt)}) — 라인 ${lines.length}건 중 $created건 태스크 생성.',
      orderId: order.id,
    );
    notifyListeners();
    return order;
  }

  /// 재고 수량을 조정한다(실사 반영·파손·오차 보정).
  ///
  /// [delta]만큼 증감하며 사유와 메모가 재고 원장에 남는다. 예약 수량보다
  /// 적게 만들 수는 없다.
  void adjustStock({
    required String lotId,
    required int delta,
    required StockMoveReason reason,
    String? note,
  }) {
    final lot = _lotById(lotId);
    if (lot == null || delta == 0) return;
    try {
      store.inventory.applyMove(
        lotId: lotId,
        delta: delta,
        reason: reason,
        at: simNow,
        operator: operatorName,
        note: note,
      );
      lot.qty += delta;
      _log(
        Severity.warning,
        '재고',
        operatorName,
        '$lotId(${lot.name}) ${reason.label} ${delta > 0 ? "+" : ""}$delta '
            '→ 잔량 ${lot.qty}${note == null || note.isEmpty ? "" : " · $note"}.',
      );
    } on StateError catch (e) {
      _log(Severity.serious, '재고', operatorName, '$lotId 조정 거부: ${e.message}');
    }
    notifyListeners();
  }

  /// 로트를 직접 등록한다(기초 재고 입력·긴급 입고).
  Lot addLot({
    required String sku,
    required String locationId,
    required int qty,
    required DateTime expiry,
    String? note,
  }) {
    final loc = layout.locationById[locationId] ?? layout.locations.first;
    final item = _catalog.firstWhere(
      (c) => c[0] == sku,
      orElse: () => <String>[sku, sku, loc.zone.name],
    );
    final lot = Lot(
      id: _id('LOT'),
      sku: sku,
      name: item[1],
      zone: loc.zone,
      locationId: loc.id,
      qty: qty,
      expiry: expiry,
      receivedAt: simNow,
    );
    lots.add(lot);
    store.inventory.insertLot(lot, reason: StockMoveReason.adjustment, note: note);
    _log(
      Severity.info,
      '재고',
      operatorName,
      '${lot.id} 신규 로트 등록 ($sku, ${loc.id}, $qty개, '
          '유통기한 ${_dateLabel(expiry)}).',
    );
    notifyListeners();
    return lot;
  }

  /// 재고 원장 조회(감사 추적).
  List<StockMove> stockMoves({int limit = 200, String? lotId}) =>
      store.inventory.recentMoves(limit: limit, lotId: lotId);

  void recallRobot(Robot r) {
    if (r.taskId != null) {
      final t = tasks[r.taskId];
      if (t != null) _requeue(t, '관제 수동 회수');
    }
    final chg = layout.nearest(StationKind.charger, r.pos, freeOnly: true);
    chg.occupiedBy = r.id;
    r.path = layout.route(r.pos, chg.pos);
    r.destinationLabel = '${chg.id} 충전소';
    r.state = RobotState.returning;
    _log(Severity.info, '운영', 'OP', '${r.id}(${r.name}) 관제 수동 회수 지시.');
    notifyListeners();
  }

  void resumeRobot(Robot r) {
    r.reserve = false;
    r.state = RobotState.idle;
    r.powerSaving = r.battery <= 20;
    _log(Severity.info, '운영', 'OP', '${r.id}(${r.name}) 작업 투입 재개.');
    notifyListeners();
  }

  void cancelTask(WorkTask t) {
    if (t.isTerminal) return;
    _requeue(t, '관제 수동 취소');
    t.state = TaskState.cancelled;
    t.endedAt = simNow;
    _saveTask(t);
    _releaseLotReservation(t);
    _log(Severity.warning, '운영', 'OP', '${t.id} 관제에서 수동 취소.', taskId: t.id);
    notifyListeners();
  }

  void reassignTask(WorkTask t) {
    if (t.isTerminal) return;
    _requeue(t, '관제 수동 재할당');
    _log(Severity.info, '운영', 'OP', '${t.id} 재할당 요청. 대기열 최상단으로 이동.', taskId: t.id);
    notifyListeners();
  }

  // ────────────────────────────────────────────────────────────── 지표

  int get activeRobots => robots
      .where((r) => !r.reserve && r.state != RobotState.estop)
      .length;

  int get workingRobots => robots.where((r) => r.state.isWorking).length;

  double get avgBattery => robots.isEmpty
      ? 0
      : robots.map((r) => r.battery).reduce((a, b) => a + b) / robots.length;

  int get pendingTasks =>
      tasks.values.where((t) => t.state == TaskState.pending).length;

  int get inProgressTasks => tasks.values
      .where((t) => t.state == TaskState.inProgress || t.state == TaskState.claimed)
      .length;

  double get successRate {
    final total = completedTotal + failedTotal;
    return total == 0 ? 1 : completedTotal / total;
  }

  double get avgCycleSeconds =>
      _cycleCount == 0 ? 0 : _cycleSecondsTotal / _cycleCount;

  double get onTimeRate {
    final closed = orders.where((o) => o.closedAt != null).toList();
    if (closed.isEmpty) return 1;
    return closed.where((o) => o.onTime).length / closed.length;
  }

  double get fefoCompliance {
    final total = fefoPicks + fefoDeviations;
    return total == 0 ? 1 : fefoPicks / total;
  }

  List<Incident> get activeIncidents =>
      incidents.where((i) => i.active).toList();

  int get expiringLots =>
      lots.where((l) => l.daysToExpiry(simNow) <= 3 && l.qty > 0).length;

  double get fleetPerformanceIndex {
    final values = environment.values.map((e) => e.performanceIndex).toList();
    return values.reduce((a, b) => a + b) / values.length;
  }

  // ────────────────────────────────────────────────────────────── 이력

  void _log(
    Severity severity,
    String category,
    String source,
    String message, {
    String? taskId,
    String? orderId,
  }) {
    final event = OpsEvent(
        id: _id('EVT'),
        at: simNow,
        severity: severity,
        category: category,
        source: source,
        message: message,
        taskId: taskId,
        orderId: orderId,
    );
    store.events.append(event);
    events.insert(0, event);
    if (events.length > 400) events.removeLast();
  }

  static String _dateLabel(DateTime d) =>
      '${d.year}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

  String dateLabel(DateTime d) => _dateLabel(d);

  String timeLabel(DateTime d) =>
      '${_hhmm(d)}:${d.second.toString().padLeft(2, '0')}';
}
