import 'dart:async';
import 'dart:io';
import 'dart:math' as math;

/// Gazebo 모델을 작업 시작 위치로 즉시 되돌린다.
Future<bool> resetGazeboRobotPose({
  required String modelName,
  required double x,
  required double y,
  required double yaw,
  required int rosDomainId,
}) async {
  final half = yaw / 2;
  final request =
      'name: ${_gzString(modelName)} '
      'position { x: $x y: $y z: 0.1 } '
      'orientation { z: ${math.sin(half)} w: ${math.cos(half)} }';
  try {
    final result = await Process.run('gz', [
      'service',
      '-s',
      '/world/sim_world/set_pose',
      '--reqtype',
      'gz.msgs.Pose',
      '--reptype',
      'gz.msgs.Boolean',
      '--timeout',
      '2000',
      '--req',
      request,
    ]).timeout(const Duration(seconds: 3));
    final moved =
        result.exitCode == 0 && '${result.stdout}'.contains('data: true');
    if (!moved) return false;

    // 운영맵은 Gazebo 모델 좌표가 아니라 AMCL→RMF 위치를 그린다. Gazebo만
    // 순간 이동시키면 AMCL은 취소 전 위치를 계속 내고, 앱의 지도도 곧 그 값으로
    // 되돌아간다. 같은 좌표를 initialpose로 넣어 두 위치 체계를 함께 맞춘다.
    final initialPose =
        '{header: {frame_id: map}, pose: {pose: {'
        'position: {x: $x, y: $y, z: 0.0}, '
        'orientation: {z: ${math.sin(half)}, w: ${math.cos(half)}}'
        '}, covariance: [0.01, 0, 0, 0, 0, 0, '
        '0, 0.01, 0, 0, 0, 0, '
        '0, 0, 0, 0, 0, 0, '
        '0, 0, 0, 0, 0, 0, '
        '0, 0, 0, 0, 0, 0, '
        '0, 0, 0, 0, 0, 0.01]}}';
    final localized = await Process.run(
      'bash',
      [
        '-c',
        'source /opt/ros/jazzy/setup.bash; '
            'exec ros2 topic pub --once "\$1" '
            'geometry_msgs/msg/PoseWithCovarianceStamped "\$2"',
        'reset-gazebo-robot',
        '/$modelName/initialpose',
        initialPose,
      ],
      environment: {...Platform.environment, 'ROS_DOMAIN_ID': '$rosDomainId'},
    ).timeout(const Duration(seconds: 5));
    return localized.exitCode == 0;
  } catch (_) {
    return false;
  }
}

String _gzString(String value) => '"${value.replaceAll('"', r'\"')}"';
