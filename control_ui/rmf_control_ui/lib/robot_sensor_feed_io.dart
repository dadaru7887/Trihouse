/// relay 가 내려 준 센서 파일을 읽는다.
///
/// 앱에 rclpy 가 없으므로 relay 노드가 파일로 내려 주고 앱은 그것만 읽는다.
/// 카메라 영상은 `ros2 topic echo` 로 읽기에 너무 크다.
library;

import 'dart:async';
import 'dart:io';

import 'robot_sensor_models.dart';

/// relay 와 앱이 만나는 곳.
///
/// 환경 변수로 바꿀 수 있다. 시스템 임시 디렉터리 아래에 두므로 다시 켜면
/// 지워진다 — 남겨 둘 값이 아니다.
const String sensorDirectoryEnvironmentKey = 'ROBOSAPIENS_SENSOR_DIR';

String robotSensorDirectory() {
  final configured = Platform.environment[sensorDirectoryEnvironmentKey];
  if (configured != null && configured.isNotEmpty) return configured;
  return '${Directory.systemTemp.path}/robosapiens_sensors';
}

/// 파일 이름으로 쓸 수 없는 글자를 걷어낸다.
///
/// 로봇 ID 는 사람이 타자로 친다. 슬래시가 들어가면 엉뚱한 곳을 읽는다.
String sensorFileStem(String robotId) {
  final safe = robotId.replaceAll(RegExp(r'[^a-zA-Z0-9가-힣_-]'), '_');
  return safe.isEmpty ? 'robot' : safe;
}

/// 로봇들의 센서 파일을 주기적으로 읽어 둔다.
///
/// 화면 여러 곳이 같은 값을 봐야 하므로 앱에 하나만 둔다.
class RobotSensorFeed {
  RobotSensorFeed._();

  static final RobotSensorFeed instance = RobotSensorFeed._();

  final Map<String, RobotSensors> _sensors = {};
  final Map<String, DateTime> _scanStamp = {};
  final Map<String, DateTime> _frameStamp = {};
  Timer? _timer;
  Set<String> _watched = const {};

  final StreamController<Map<String, RobotSensors>> _controller =
      StreamController<Map<String, RobotSensors>>.broadcast();

  Stream<Map<String, RobotSensors>> get updates => _controller.stream;

  Map<String, RobotSensors> get sensors => Map.unmodifiable(_sensors);

  RobotSensors sensorsOf(String robotId) =>
      _sensors[robotId] ?? const RobotSensors();

  bool get watching => _timer != null;

  /// [robotIds] 의 센서 파일을 지켜본다. 이미 보고 있으면 그대로 둔다.
  ///
  /// 카메라는 320×180 RGBA 한 장이 230KB 다. 너무 자주 읽으면 앱이 무거워지므로
  /// 눈에 자연스러운 정도로만 읽는다.
  void watch(
    Iterable<String> robotIds, {
    Duration interval = const Duration(milliseconds: 200),
  }) {
    final wanted = robotIds.toSet();
    if (wanted.isEmpty) {
      stop();
      return;
    }
    if (_timer != null && _setEquals(wanted, _watched)) return;
    _watched = wanted;
    // 안 보는 로봇의 값은 들고 있을 이유가 없다.
    _sensors.removeWhere((id, _) => !wanted.contains(id));
    _timer?.cancel();
    _timer = Timer.periodic(interval, (_) => _read());
    _read();
  }

  void stop() {
    _timer?.cancel();
    _timer = null;
    _watched = const {};
    _sensors.clear();
    _scanStamp.clear();
    _frameStamp.clear();
    _controller.add(sensors);
  }

  Future<void> _read() async {
    final directory = robotSensorDirectory();
    var changed = false;
    for (final robotId in _watched) {
      final stem = sensorFileStem(robotId);
      final current = _sensors[robotId] ?? const RobotSensors();
      var scan = current.scan;
      var camera = current.camera;

      final scanFile = File('$directory/$stem.scan');
      final scanChanged = await _readIfNewer(scanFile, _scanStamp, robotId, (
        stamp,
      ) async {
        scan = RobotScan.parse(await scanFile.readAsString(), stamp) ?? scan;
      });

      final frameFile = File('$directory/$stem.frame');
      final frameChanged = await _readIfNewer(frameFile, _frameStamp, robotId, (
        stamp,
      ) async {
        camera =
            RobotCameraFrame.parse(await frameFile.readAsBytes(), stamp) ??
            camera;
      });

      if (scanChanged || frameChanged) {
        _sensors[robotId] = RobotSensors(scan: scan, camera: camera);
        changed = true;
      }
    }
    if (changed) _controller.add(sensors);
  }

  /// 파일이 지난번보다 새 것일 때만 읽는다.
  ///
  /// 같은 파일을 되풀이해 읽으면 카메라 한 장이 230KB 라 금세 무거워진다. 그리고
  /// **파일이 남아 있는 것과 값이 오는 것은 다르다** — relay 가 죽어도 파일은
  /// 그대로라, 시각을 갱신하지 않아야 멈춘 것을 알아챈다.
  Future<bool> _readIfNewer(
    File file,
    Map<String, DateTime> stamps,
    String robotId,
    Future<void> Function(DateTime stamp) read,
  ) async {
    try {
      if (!await file.exists()) return false;
      final modified = await file.lastModified();
      if (stamps[robotId] == modified) return false;
      stamps[robotId] = modified;
      await read(modified);
      return true;
    } catch (_) {
      // 쓰는 중이면 읽기가 실패할 수 있다. 다음 차례에 다시 읽는다.
      return false;
    }
  }

  bool _setEquals(Set<String> a, Set<String> b) =>
      a.length == b.length && a.containsAll(b);
}
