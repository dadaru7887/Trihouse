import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:ui' show Offset;

import 'package:flutter/foundation.dart';

import 'package:robo_core/models/enums.dart';

/// 실 장비(Gazebo 시뮬레이션 포함)와 관제센터를 잇는 링크 서버.
///
/// 관제센터가 TCP 서버, 현장 장비가 클라이언트다. 한 줄에 JSON 한 건(NDJSON)을
/// 주고받는다. 두 종류의 장비가 붙는다.
///
///  * **주행 로봇**(`kind: "robot"`, 기본값) — 위치·배터리를 보고하고 경로·정지
///    명령을 받는다.
///  * **적재 로봇팔**(`kind: "arm"`) — 구획 적재 스테이션에 한 대씩 설치되어,
///    관제의 적재 지시를 받아 로봇에 화물을 실어 주고 완료를 보고한다.
///
/// 접속이 끊긴 장비는 관제 화면에서 즉시 `연결 대기` 상태가 된다.
///
/// 프로토콜은 `robo_pinky/src/robo_pinky_agent/robo_pinky_agent/control_link.py`와
/// 짝을 이룬다.
class RobotLinkServer {
  RobotLinkServer({this.host = '127.0.0.1', this.port = 8788});

  static const int proto = 1;

  final String host;
  final int port;

  ServerSocket? _server;
  final Map<String, LinkedRobot> _linked = <String, LinkedRobot>{};

  /// 아직 hello를 보내지 않은 접속.
  final Set<Socket> _pending = <Socket>{};

  /// 신규 로봇이 자기소개를 마쳤을 때. 관제는 여기서 플릿 등록을 처리한다.
  void Function(RobotHello hello)? onHello;

  /// 링크가 끊겼을 때.
  void Function(String robotId)? onDropped;

  /// 로봇이 관제 이력에 남기고 싶은 사건을 보냈을 때.
  void Function(String robotId, String severity, String message)? onLog;

  /// 적재 로봇팔이 자기소개를 마쳤을 때.
  void Function(ArmHello hello)? onArmHello;

  /// 적재 로봇팔 링크가 끊겼을 때.
  void Function(String armId)? onArmDropped;

  /// 적재 완료/실패 보고. [ok]가 false면 [reason]에 사유가 담긴다.
  void Function(String armId, String taskId, bool ok, String? reason)?
  onArmResult;

  bool get listening => _server != null;

  int get linkedCount => _linked.length;

  Iterable<String> get linkedIds => _linked.keys;

  bool isLinked(String robotId) => _linked.containsKey(robotId);

  RobotTelemetry? telemetryOf(String robotId) => _linked[robotId]?.telemetry;

  // ─────────────────────────────────────────────────────── 적재 로봇팔

  final Map<String, LinkedArm> _arms = <String, LinkedArm>{};

  int get armCount => _arms.length;

  Iterable<LinkedArm> get arms => _arms.values;

  LinkedArm? armById(String armId) => _arms[armId];

  /// 이 스테이션에 설치된 로봇팔 ID. 없으면 null(수동 적재로 처리한다).
  String? armAtStation(String stationId) {
    for (final a in _arms.values) {
      if (a.stationId == stationId) return a.id;
    }
    return null;
  }

  String? lastError;

  Future<bool> start() async {
    if (_server != null) return true;
    try {
      _server = await ServerSocket.bind(host, port, shared: false);
      lastError = null;
    } on SocketException catch (e) {
      lastError = '${e.message} (포트 $port)';
      debugPrint('로봇 링크 서버 시작 실패: $lastError');
      return false;
    }
    _server!.listen(_accept, onError: (Object e) => debugPrint('링크 오류: $e'));
    debugPrint('로봇 링크 서버 대기 중 — $host:$port');
    return true;
  }

  Future<void> stop() async {
    // 콜백부터 끊는다. 종료 중에 들어온 단절 통지가 이미 정리된 관제 상태를
    // 건드리지 않도록 하기 위해서다.
    onHello = null;
    onDropped = null;
    onLog = null;
    onArmHello = null;
    onArmDropped = null;
    onArmResult = null;
    for (final l in _linked.values.toList()) {
      l.markDead();
      l.socket.destroy();
    }
    _linked.clear();
    for (final a in _arms.values.toList()) {
      a.markDead();
      a.socket.destroy();
    }
    _arms.clear();
    for (final s in _pending.toList()) {
      await s.close();
    }
    _pending.clear();
    await _server?.close();
    _server = null;
  }

  // ─────────────────────────────────────────────────────── 수신

  void _accept(Socket socket) {
    socket.setOption(SocketOption.tcpNoDelay, true);
    _pending.add(socket);
    String? boundId;

    // 상대가 예고 없이 죽으면 쓰기 쪽에서도 오류가 올라온다. 여기서 삼키지
    // 않으면 처리되지 않은 비동기 오류가 되어 앱 전체로 번진다.
    unawaited(socket.done.then((_) {}, onError: (Object _) {}));

    utf8.decoder
        .bind(socket)
        .transform(const LineSplitter())
        .listen(
          (String line) {
            if (line.trim().isEmpty) return;
            final Object? decoded;
            try {
              decoded = jsonDecode(line);
            } on FormatException {
              return;
            }
            if (decoded is! Map<String, dynamic>) return;
            boundId = _handle(socket, decoded, boundId);
          },
          onError: (Object _) => _close(socket, boundId),
          onDone: () => _close(socket, boundId),
          cancelOnError: true,
        );
  }

  String? _handle(Socket socket, Map<String, dynamic> msg, String? boundId) {
    switch (msg['t']) {
      case 'hello' when msg['kind'] == 'arm':
        final hello = ArmHello.fromJson(msg);
        if (hello == null) return boundId;
        _pending.remove(socket);
        _arms[hello.id]?.socket.destroy();
        final arm = LinkedArm(
          id: hello.id,
          stationId: hello.stationId,
          zone: hello.zone,
          model: hello.model,
          socket: socket,
        );
        _arms[hello.id] = arm;
        arm.send(<String, dynamic>{
          't': 'welcome',
          'proto': proto,
          'scale': 0.1,
          'width': 120.0,
          'height': 72.0,
        });
        onArmHello?.call(hello);
        return hello.id;

      case 'loaded' || 'loadFailed':
        final id = (msg['id'] as String?) ?? boundId;
        final taskId = msg['task'] as String?;
        if (id == null || taskId == null) return boundId;
        final arm = _arms[id];
        if (arm == null) return boundId;
        arm.busyTaskId = null;
        arm.lastResultAt = DateTime.now();
        onArmResult?.call(
          id,
          taskId,
          msg['t'] == 'loaded',
          msg['reason'] as String?,
        );
        return boundId;

      case 'armStatus':
        final id = (msg['id'] as String?) ?? boundId;
        final arm = id == null ? null : _arms[id];
        if (arm == null) return boundId;
        arm.status = (msg['status'] as String?) ?? arm.status;
        arm.loadsCompleted = (msg['done'] as num?)?.toInt() ?? arm.loadsCompleted;
        return boundId;

      case 'hello':
        final hello = RobotHello.fromJson(msg);
        if (hello == null) return boundId;
        _pending.remove(socket);
        _linked[hello.id]?.socket.destroy();
        final link = LinkedRobot(id: hello.id, socket: socket);
        _linked[hello.id] = link;
        link.telemetry = RobotTelemetry(
          x: hello.x,
          y: hello.y,
          heading: hello.heading,
          battery: hello.battery,
          speed: 0,
          odometer: 0,
          waypointsLeft: 0,
          charging: false,
          note: null,
          at: DateTime.now(),
        );
        link.send(<String, dynamic>{
          't': 'welcome',
          'proto': proto,
          'scale': 0.1,
          'width': 120.0,
          'height': 72.0,
        });
        onHello?.call(hello);
        return hello.id;

      case 'telemetry':
        final id = (msg['id'] as String?) ?? boundId;
        final link = id == null ? null : _linked[id];
        if (link == null) return boundId;
        link.telemetry = RobotTelemetry.fromJson(msg);
        return boundId;

      case 'log':
        final id = (msg['id'] as String?) ?? boundId;
        if (id == null) return boundId;
        onLog?.call(
          id,
          (msg['sev'] as String?) ?? 'info',
          (msg['msg'] as String?) ?? '',
        );
        return boundId;
    }
    return boundId;
  }

  void _close(Socket socket, String? boundId) {
    _pending.remove(socket);
    if (boundId != null && _linked[boundId]?.socket == socket) {
      _linked.remove(boundId)!.markDead();
      socket.destroy();
      onDropped?.call(boundId);
      return;
    }
    if (boundId != null && _arms[boundId]?.socket == socket) {
      _arms.remove(boundId)!.markDead();
      socket.destroy();
      onArmDropped?.call(boundId);
      return;
    }
    socket.destroy();
  }

  // ─────────────────────────────────────────────────────── 송신

  /// 주행 경로 하달. 이미 보낸 경로의 남은 부분이면 다시 보내지 않는다.
  ///
  /// [goalTolerance]는 종점 도착 판정 반경(unit)이다. 랙 슬롯 좌표는 선반
  /// 중심선이라 로봇이 그 위에 올라설 수 없다. 실제 현장에서도 로봇은 통로에
  /// 서서 슬롯에 접근하므로, 종점만 넉넉한 반경으로 도착을 판정한다.
  void sendPath(
    String robotId,
    List<Offset> waypoints, {
    String? label,
    double goalTolerance = 5.0,
  }) {
    final link = _linked[robotId];
    if (link == null) return;
    if (link.pathMatches(waypoints)) return;
    link.rememberPath(waypoints);
    link.send(<String, dynamic>{
      't': 'path',
      'seq': link.nextSeq(),
      'goalTol': goalTolerance,
      'label': ?label,
      'waypoints': <List<double>>[
        for (final w in waypoints)
          <double>[
            double.parse(w.dx.toStringAsFixed(3)),
            double.parse(w.dy.toStringAsFixed(3)),
          ],
      ],
    });
  }

  /// 안전 정지 래치. 사유는 관제 화면과 동일한 문구를 그대로 전달한다.
  void sendHold(String robotId, bool on, {String? reason}) {
    final link = _linked[robotId];
    if (link == null) return;
    if (link.hold == on && link.holdReason == reason) return;
    link.hold = on;
    link.holdReason = reason;
    link.send(<String, dynamic>{'t': 'hold', 'on': on, 'reason': reason});
  }

  /// 허용 속도 상한(unit/s). 구획 환경·안전 필드가 반영된 값.
  void sendSpeed(String robotId, double limitUnits) {
    final link = _linked[robotId];
    if (link == null) return;
    if ((link.speedLimit - limitUnits).abs() < 0.05) return;
    link.speedLimit = limitUnits;
    link.send(<String, dynamic>{
      't': 'speed',
      'limit': double.parse(limitUnits.toStringAsFixed(3)),
    });
  }

  void sendCharge(String robotId, bool on) {
    final link = _linked[robotId];
    if (link == null) return;
    if (link.charging == on) return;
    link.charging = on;
    link.send(<String, dynamic>{'t': 'charge', 'on': on});
  }

  /// 적재 스테이션 로봇팔에 적재를 지시한다.
  ///
  /// 팔은 화물을 집어 [robotId] 로봇 위에 올린 뒤 `loaded`(또는 `loadFailed`)로
  /// 응답한다. 같은 팔에 작업이 이미 걸려 있으면 지시하지 않는다.
  void sendLoad(
    String armId, {
    required String robotId,
    required String taskId,
    required String item,
    required int qty,
    required Offset robotPos,
  }) {
    final arm = _arms[armId];
    if (arm == null || arm.busyTaskId != null) return;
    arm.busyTaskId = taskId;
    arm.status = 'loading';
    arm.send(<String, dynamic>{
      't': 'load',
      'seq': arm.nextSeq(),
      'robot': robotId,
      'task': taskId,
      'item': item,
      'qty': qty,
      // 로봇이 실제로 선 자리. 팔은 이 좌표로 역기구학을 풀어 내려놓는다.
      'x': double.parse(robotPos.dx.toStringAsFixed(3)),
      'y': double.parse(robotPos.dy.toStringAsFixed(3)),
    });
  }

  /// 진행 중인 적재 지시를 취소한다(로봇 이탈·타임아웃).
  void sendLoadAbort(String armId, String taskId) {
    final arm = _arms[armId];
    if (arm == null) return;
    if (arm.busyTaskId == taskId) arm.busyTaskId = null;
    arm.status = 'idle';
    arm.send(<String, dynamic>{'t': 'abort', 'task': taskId});
  }
}

/// 접속 중인 적재 로봇팔 하나.
class LinkedArm {
  LinkedArm({
    required this.id,
    required this.stationId,
    required this.zone,
    required this.model,
    required this.socket,
  });

  final String id;

  /// 이 팔이 설치된 스테이션 ID(예: `WS-2`).
  final String stationId;
  final TempZone? zone;
  final String model;
  final Socket socket;

  /// 현재 수행 중인 적재 작업의 태스크 ID.
  String? busyTaskId;

  String status = 'idle';
  int loadsCompleted = 0;
  DateTime? lastResultAt;

  int _seq = 0;
  bool _dead = false;

  int nextSeq() => ++_seq;

  void markDead() => _dead = true;

  void send(Map<String, dynamic> msg) {
    if (_dead) return;
    try {
      socket.write('${jsonEncode(msg)}\n');
    } on SocketException catch (_) {
      _dead = true;
    }
  }
}

/// 적재 로봇팔 자기소개.
class ArmHello {
  ArmHello({
    required this.id,
    required this.stationId,
    required this.zone,
    required this.model,
  });

  static ArmHello? fromJson(Map<String, dynamic> m) {
    final id = m['id'] as String?;
    final station = m['station'] as String?;
    if (id == null || id.isEmpty || station == null || station.isEmpty) {
      return null;
    }
    return ArmHello(
      id: id,
      stationId: station,
      zone: _zoneOf(m['zone'] as String?),
      model: (m['model'] as String?) ?? 'OMX',
    );
  }

  final String id;
  final String stationId;
  final TempZone? zone;
  final String model;
}

TempZone? _zoneOf(String? code) => switch (code?.toLowerCase()) {
  'ambient' || 'a' => TempZone.ambient,
  'chilled' || 'c' => TempZone.chilled,
  'frozen' || 'f' => TempZone.frozen,
  _ => null,
};

/// 접속 중인 로봇 하나.
class LinkedRobot {
  LinkedRobot({required this.id, required this.socket});

  final String id;
  final Socket socket;

  RobotTelemetry? telemetry;

  bool hold = false;
  String? holdReason;
  bool charging = false;
  double speedLimit = -1;

  int _seq = 0;
  List<Offset> _sentPath = <Offset>[];

  int nextSeq() => ++_seq;

  /// 관제가 보유한 경로가 이미 보낸 경로의 남은 구간이면 재전송이 필요 없다.
  /// (로봇이 웨이포인트를 소진하는 동안 관제도 같은 규칙으로 줄이기 때문)
  bool pathMatches(List<Offset> path) {
    if (path.length > _sentPath.length) return false;
    final offset = _sentPath.length - path.length;
    for (var i = 0; i < path.length; i++) {
      if ((_sentPath[offset + i] - path[i]).distance > 0.05) return false;
    }
    return true;
  }

  void rememberPath(List<Offset> path) => _sentPath = List<Offset>.of(path);

  bool _dead = false;

  /// 더 이상 쓰기를 시도하지 않도록 표시한다. 끊긴 소켓에 계속 쓰면
  /// 처리되지 않은 비동기 오류가 쌓인다.
  void markDead() => _dead = true;

  void send(Map<String, dynamic> msg) {
    if (_dead) return;
    try {
      socket.write('${jsonEncode(msg)}\n');
    } on SocketException catch (_) {
      _dead = true;
    }
  }
}

/// 로봇 자기소개(마스터 데이터).
class RobotHello {
  RobotHello({
    required this.id,
    required this.name,
    required this.model,
    required this.zoneCodes,
    required this.homeChargerId,
    required this.x,
    required this.y,
    required this.heading,
    required this.battery,
  });

  static RobotHello? fromJson(Map<String, dynamic> m) {
    final id = m['id'] as String?;
    if (id == null || id.isEmpty) return null;
    return RobotHello(
      id: id,
      name: (m['name'] as String?) ?? id,
      model: (m['model'] as String?) ?? 'PINKY-GZ',
      zoneCodes: <String>[
        for (final z in (m['zones'] as List<dynamic>? ?? const <dynamic>[]))
          z.toString(),
      ],
      homeChargerId: (m['charger'] as String?) ?? 'CHG-1',
      x: _num(m['x']) ?? 50,
      y: _num(m['y']) ?? 22,
      heading: _num(m['heading']) ?? 0,
      battery: _num(m['battery']) ?? 100,
    );
  }

  final String id;
  final String name;
  final String model;
  final List<String> zoneCodes;
  final String homeChargerId;
  final double x;
  final double y;
  final double heading;
  final double battery;

  Offset get pos => Offset(x, y);
}

/// 로봇이 주기 보고하는 실시간 상태. 좌표는 관제 좌표계(unit).
class RobotTelemetry {
  RobotTelemetry({
    required this.x,
    required this.y,
    required this.heading,
    required this.battery,
    required this.speed,
    required this.odometer,
    required this.waypointsLeft,
    required this.charging,
    required this.note,
    required this.at,
  });

  factory RobotTelemetry.fromJson(Map<String, dynamic> m) => RobotTelemetry(
    x: _num(m['x']) ?? 0,
    y: _num(m['y']) ?? 0,
    heading: _num(m['heading']) ?? 0,
    battery: _num(m['battery']) ?? 0,
    speed: _num(m['speed']) ?? 0,
    odometer: _num(m['odom']) ?? 0,
    waypointsLeft: (m['wpLeft'] as num?)?.toInt() ?? 0,
    charging: m['charging'] == true,
    note: m['note'] as String?,
    at: DateTime.now(),
  );

  final double x;
  final double y;
  final double heading;
  final double battery;
  final double speed;
  final double odometer;
  final int waypointsLeft;
  final bool charging;
  final String? note;
  final DateTime at;

  Offset get pos => Offset(x, y);
}

double? _num(Object? v) => v is num ? v.toDouble() : null;
