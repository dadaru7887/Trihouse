/// Gazebo·실물에서 받아온 로봇의 실제 위치.
///
/// 지금까지 화면의 숫자는 전부 앱이 계산한 것이었다. 출처를 Gazebo 로 골라도
/// 값은 여전히 앱 것이어서, 작업 상세의 띠가 그 사실을 경고로 알렸다. 실제로
/// 토픽을 받아오면 그 경고가 사라진다.
library;

import 'dart:math' as math;

/// 토픽에서 받은 한 순간의 자세.
class RobotPose {
  const RobotPose({
    required this.x,
    required this.y,
    required this.heading,
    required this.at,
  });

  /// 미터. `/…/odom` 의 `pose.pose.position`.
  final double x;
  final double y;

  /// 라디안. 사원수에서 푼 yaw.
  final double heading;

  /// 이 값을 받은 시각. 오래되면 끊긴 것으로 본다.
  final DateTime at;

  /// `x,y,z,qx,qy,qz,qw` 일곱 개짜리 CSV 한 줄을 푼다. 모양이 다르면 null.
  ///
  /// `ros2 topic echo <토픽> --field pose.pose --csv` 가 내는 모양이다.
  static RobotPose? parseCsv(String line, DateTime at) {
    final parts = line.trim().split(',');
    if (parts.length < 7) return null;
    final values = <double>[];
    for (final part in parts.take(7)) {
      final value = double.tryParse(part.trim());
      if (value == null) return null;
      values.add(value);
    }
    final qx = values[3];
    final qy = values[4];
    final qz = values[5];
    final qw = values[6];
    // 평면을 도는 로봇이라 yaw 하나면 된다.
    final heading = math.atan2(
      2 * (qw * qz + qx * qy),
      1 - 2 * (qy * qy + qz * qz),
    );
    return RobotPose(x: values[0], y: values[1], heading: heading, at: at);
  }

  /// odom 원점을 스폰 자리로 옮겨 월드 좌표를 만든다.
  ///
  /// Gazebo 의 바퀴 플러그인이 내는 `/…/odom` 은 월드 좌표가 아니라 **로봇을
  /// 올린 자리에서부터** 잰 값이다. 홈1 에 세워 두어도 방금 올린 로봇은 0, 0
  /// 을 낸다. 실제 로봇도 마찬가지로 odom 은 켠 자리가 원점이고, 지도 좌표는
  /// 측위(AMCL 등)가 따로 얹어 준다.
  ///
  /// 스폰 자세를 모르면 옮길 수 없으므로 받은 값을 그대로 돌려준다.
  RobotPose toWorld({double? spawnX, double? spawnY, double spawnHeading = 0}) {
    if (spawnX == null || spawnY == null) return this;
    final cos = math.cos(spawnHeading);
    final sin = math.sin(spawnHeading);
    return RobotPose(
      x: spawnX + x * cos - y * sin,
      y: spawnY + x * sin + y * cos,
      heading: heading + spawnHeading,
      at: at,
    );
  }
}

/// 토픽을 받고 있는지.
class RobotTelemetryStatus {
  const RobotTelemetryStatus({
    required this.subscribing,
    required this.poses,
    required this.message,
  });

  /// 구독을 걸어 둔 상태인지. 값이 아직 안 왔어도 true 일 수 있다.
  final bool subscribing;

  /// 로봇 ID 별 마지막 자세.
  final Map<String, RobotPose> poses;

  /// 사람에게 보여 줄 한 줄.
  final String message;

  static const RobotTelemetryStatus idle = RobotTelemetryStatus(
    subscribing: false,
    poses: {},
    message: '토픽을 구독하지 않습니다.',
  );

  /// 이 로봇의 값이 지금 들어오고 있는가.
  ///
  /// 구독만 걸어 두고 값이 안 오는 것과 실제로 오는 것은 다르다. 안 오는데
  /// 온다고 표시하면 멈춘 숫자를 실시간으로 착각한다.
  bool isLive(
    String robotId, {
    DateTime? now,
    Duration stale = const Duration(seconds: 3),
  }) {
    final pose = poses[robotId];
    if (pose == null) return false;
    return (now ?? DateTime.now()).difference(pose.at) <= stale;
  }
}
