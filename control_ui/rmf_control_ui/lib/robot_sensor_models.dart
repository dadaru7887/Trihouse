/// 로봇이 실제로 보내오는 센서 값.
///
/// 위치(odom)는 `robot_telemetry_models.dart` 가 맡는다. 이 파일은 사람이 눈으로
/// 보는 것 — 라이다와 카메라 — 을 맡는다.
///
/// 값은 relay 노드가 파일로 내려 준다. 앱에 rclpy 가 없고, 카메라 영상은
/// `ros2 topic echo` 로 읽기에 너무 크기 때문이다(1280×720 한 장이 YAML 로
/// 2.7MB).
library;

import 'dart:math' as math;
import 'dart:typed_data';

/// 라이다 한 번 훑은 값.
class RobotScan {
  const RobotScan({
    required this.angleMin,
    required this.angleMax,
    required this.rangeMin,
    required this.rangeMax,
    required this.ranges,
    required this.at,
  });

  /// 라디안. 첫 점과 마지막 점의 방향.
  final double angleMin;
  final double angleMax;

  /// 미터. 이 밖은 못 잰다.
  final double rangeMin;
  final double rangeMax;

  /// 미터. 로봇 기준 거리.
  final List<double> ranges;

  final DateTime at;

  bool get isEmpty => ranges.isEmpty;

  /// 점 하나의 방향(라디안).
  double angleAt(int index) {
    if (ranges.length <= 1) return angleMin;
    return angleMin + (angleMax - angleMin) * index / (ranges.length - 1);
  }

  /// 제일 가까운 것까지의 거리. 못 잰 값은 빼고 본다.
  double? get nearest {
    double? best;
    for (final value in ranges) {
      if (value <= rangeMin || value >= rangeMax) continue;
      if (best == null || value < best) best = value;
    }
    return best;
  }

  /// 실제로 무언가를 맞힌 점의 수. 전부 최대 거리면 아무것도 안 보이는 것이다.
  int get hits =>
      ranges.where((value) => value > rangeMin && value < rangeMax).length;

  /// relay 가 쓴 한 줄짜리 파일을 푼다. 모양이 다르면 null.
  ///
  /// ```
  /// angleMin,angleMax,rangeMin,rangeMax
  /// r0,r1,r2,...
  /// ```
  static RobotScan? parse(String text, DateTime at) {
    final lines = text.trim().split('\n');
    if (lines.length < 2) return null;
    final head = lines[0].split(',');
    if (head.length < 4) return null;
    final values = <double>[];
    for (final part in head) {
      final value = double.tryParse(part.trim());
      if (value == null) return null;
      values.add(value);
    }
    final ranges = <double>[];
    for (final part in lines[1].split(',')) {
      final value = double.tryParse(part.trim());
      if (value == null) continue;
      ranges.add(value);
    }
    if (ranges.isEmpty) return null;
    return RobotScan(
      angleMin: values[0],
      angleMax: values[1],
      rangeMin: values[2],
      rangeMax: values[3],
      ranges: ranges,
      at: at,
    );
  }
}

/// 카메라 한 장.
class RobotCameraFrame {
  const RobotCameraFrame({
    required this.width,
    required this.height,
    required this.pixels,
    required this.at,
  });

  final int width;
  final int height;

  /// RGBA 날바이트. `ui.decodeImageFromPixels` 에 그대로 넣는다.
  final Uint8List pixels;

  final DateTime at;

  /// relay 가 쓴 파일을 푼다. 머리글이 안 맞거나 길이가 모자라면 null.
  ///
  /// ```
  /// 'RSIM' + uint32 너비 + uint32 높이 + RGBA 바이트
  /// ```
  static RobotCameraFrame? parse(Uint8List bytes, DateTime at) {
    const magic = [0x52, 0x53, 0x49, 0x4D]; // RSIM
    if (bytes.length < 12) return null;
    for (var i = 0; i < 4; i++) {
      if (bytes[i] != magic[i]) return null;
    }
    final view = ByteData.sublistView(bytes, 4, 12);
    final width = view.getUint32(0, Endian.little);
    final height = view.getUint32(4, Endian.little);
    // 터무니없는 크기면 파일이 깨진 것이다. 그대로 믿고 할당하면 앱이 죽는다.
    if (width <= 0 || height <= 0 || width > 4096 || height > 4096) return null;
    final needed = width * height * 4;
    if (bytes.length < 12 + needed) return null;
    return RobotCameraFrame(
      width: width,
      height: height,
      pixels: Uint8List.sublistView(bytes, 12, 12 + needed),
      at: at,
    );
  }
}

/// 로봇 한 대의 센서 값. 없으면 그 항목이 null 이다.
class RobotSensors {
  const RobotSensors({this.scan, this.camera});

  final RobotScan? scan;
  final RobotCameraFrame? camera;

  bool get isEmpty => scan == null && camera == null;

  /// 이 값이 지금 들어오고 있는가.
  ///
  /// 파일이 남아 있는 것과 값이 오는 것은 다르다. relay 가 죽어도 파일은
  /// 그대로라, 멈춘 그림을 실시간으로 착각하기 쉽다.
  bool scanIsLive({
    DateTime? now,
    Duration stale = const Duration(seconds: 3),
  }) => scan != null && (now ?? DateTime.now()).difference(scan!.at) <= stale;

  bool cameraIsLive({
    DateTime? now,
    Duration stale = const Duration(seconds: 3),
  }) =>
      camera != null && (now ?? DateTime.now()).difference(camera!.at) <= stale;
}

/// 로봇이 주고받는 토픽 하나.
class RobotTopic {
  const RobotTopic({
    required this.name,
    required this.type,
    required this.incoming,
    required this.what,
  });

  final String name;
  final String type;

  /// 로봇에게서 오는가(true), 로봇에게 가는가(false).
  final bool incoming;

  /// 사람 말로 무엇인지.
  final String what;
}

/// 각도와 거리를 화면 좌표로 옮긴다. 라이다를 그릴 때 쓴다.
///
/// 로봇이 가운데이고 위쪽이 로봇의 앞이다. [radius] 는 그림의 반지름(px).
({double dx, double dy}) scanPointOffset({
  required double angle,
  required double range,
  required double maxRange,
  required double radius,
}) {
  final scaled = maxRange <= 0 ? 0.0 : (range / maxRange).clamp(0.0, 1.0);
  final length = scaled * radius;
  // 라이다의 0도는 로봇의 앞이고 반시계가 +다. 화면은 y 가 아래로 가므로
  // 앞(0도)이 위로 가도록 돌려서 그린다.
  return (dx: length * math.sin(angle), dy: -length * math.cos(angle));
}
