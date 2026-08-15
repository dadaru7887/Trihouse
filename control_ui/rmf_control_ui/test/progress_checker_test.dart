/// 속도를 낮출 때 "끼었나" 판정도 함께 낮추는지 지킨다.
///
/// `SimpleProgressChecker` 는 정해진 시간 안에 정해진 거리를 못 벗어나면 로봇이
/// 끼었다고 보고 제자리 회전·후진을 시킨다. 벤더 값 10초·0.5m 는 **0.05m/s
/// 이상**을 전제한다.
///
/// 속도만 낮추고 이것을 그대로 두면 정상 주행이 실패로 판정된다. 실제로 직진
/// 속도를 0.02m/s 로 내렸더니 10초에 0.2m 밖에 못 가는데 0.5m 를 요구받아 —
///
///   [pinky_02.controller_server] ERROR: Failed to make progress
///
/// 로봇이 목적지로 가다 말고 되돌아오기를 되풀이했다. 픽업 지점에 영영 못 닿았고,
/// 그 헛회전이 odom 에 쌓여 AMCL 보정이 46도까지 벌어졌다. 그래서 앱 화면과
/// RViz 의 로봇 위치가 1m 넘게 어긋나 보였다.
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/nav2_params.dart';
import 'package:rmf_control_ui/nav2_progress_checker.dart';
import 'package:rmf_control_ui/nav2_speed_limits.dart';

void main() {
  double radius(double speed, {double allowance = 10, double vendor = .5}) =>
      progressCheckerRadius(
        linearVelocity: speed,
        allowanceSeconds: allowance,
        vendorRadius: vendor,
      );

  group('요구 거리를 속도에 맞춘다', () {
    test('벤더 속도에서는 벤더 값 그대로다', () {
      // 0.2m/s 는 10초에 2m 를 간다. 0.5m 요구는 넉넉하다 — 벤더가 고른 짝이
      // 이미 맞으므로 건드릴 이유가 없다.
      expect(radius(.2), .5);
    });

    test('속도를 올려도 더 깐깐해지지 않는다', () {
      expect(radius(2), .5);
    });

    test('느리면 낮춘다', () {
      // 0.02m/s 는 10초에 0.2m. 그 3할인 0.06m 를 요구한다.
      expect(radius(.02), closeTo(.06, 1e-9));
    });

    test('최고 속도를 다 요구하지 않는다', () {
      // 로봇은 늘 최고 속도로 안 간다 — 방향을 틀 때 멈추고, 목적지 가까이서
      // 줄인다. 그 모두가 정상인데 끼었다고 판정되면 안 된다.
      expect(radius(.1), lessThan(.1 * 10));
      expect(radius(.1), closeTo(.3, 1e-9));
    });

    test('바닥이 있다', () {
      // 더 작게 잡으면 진짜로 끼었을 때도 안 걸린다. AMCL 이 떠는 폭이 몇 cm 다.
      expect(radius(.001), minProgressRadius);
    });

    test('속도를 모르면 벤더 값을 둔다', () {
      expect(radius(0), .5);
      expect(radius(.2, allowance: 0), .5);
    });
  });

  group('값을 맞춰도 안 되는 속도는 알린다', () {
    String? warn(double speed) => progressCheckerWarning(
      linearVelocity: speed,
      allowanceSeconds: 10,
      vendorRadius: .5,
    );

    test('쓸 만한 속도에서는 조용하다', () {
      expect(warn(.2), isNull);
      expect(warn(.02), isNull);
    });

    test('바닥 아래로 내려가면 알린다', () {
      // 0.004m/s 는 10초에 0.04m — 바닥인 0.05m 도 못 벗어난다. 값을 맞춰 주는
      // 것으로 해결되지 않으므로 사람에게 알려야 한다.
      final message = warn(.004);
      expect(message, isNotNull);
      expect(message, contains('끼었다고'));
      // 얼마면 되는지까지 적는다.
      expect(message, contains('m/s 이상'));
    });
  });

  group('생성되는 파라미터', () {
    const vendor = '''
controller_server:
  ros__parameters:
    FollowPath:
      desired_linear_vel: 0.2
    progress_checker:
      plugin: "nav2_controller::SimpleProgressChecker"
      movement_time_allowance: 10.0
      required_movement_radius: 0.5
velocity_smoother:
  ros__parameters:
    max_velocity: [0.25, 0.0, 1.5]
''';

    String rewrite(double speed) => rewriteNav2Params(
      source: vendor,
      namespace: 'pinky_01',
      linearVelocity: speed,
    ).yaml;

    test('속도를 낮추면 요구 거리도 낮춘다', () {
      final yaml = rewrite(.02);
      expect(yaml, contains('desired_linear_vel: 0.020'));
      expect(yaml, contains('required_movement_radius: 0.060'));
    });

    test('벤더 속도면 요구 거리를 안 건드린다', () {
      expect(rewrite(.2), contains('required_movement_radius: 0.500'));
    });

    test('여유 시간은 그대로 둔다', () {
      // 우리가 요구받은 것은 속도다. 시간까지 손대면 벤더가 왜 10초를 골랐는지
      // 모르는 채로 바꾸는 것이 된다.
      expect(rewrite(.02), contains('movement_time_allowance: 10.0'));
    });

    test('무엇을 바꿨는지 남긴다', () {
      final result = rewriteNav2Params(
        source: vendor,
        namespace: 'pinky_01',
        linearVelocity: .02,
      );
      expect(
        result.changes.any((c) => c.contains('required_movement_radius')),
        isTrue,
      );
    });

    test('너무 느리면 경고까지 남긴다', () {
      final result = rewriteNav2Params(
        source: vendor,
        namespace: 'pinky_01',
        linearVelocity: .004,
      );
      expect(result.warnings.any((w) => w.contains('끼었다고')), isTrue);
    });

    test('속도를 안 주면 아무것도 안 건드린다', () {
      final yaml = rewriteNav2Params(
        source: vendor,
        namespace: 'pinky_01',
      ).yaml;
      expect(yaml, contains('required_movement_radius: 0.5'));
      expect(yaml, contains('desired_linear_vel: 0.2'));
    });
  });

  group('벤더 파일에서 판정 값을 읽는다', () {
    test('여유 시간과 요구 거리', () {
      const yaml = '''
      movement_time_allowance: 10.0              # [s] 끼었는지 보는 시간
      required_movement_radius: 0.5              # [m] 그동안 벗어나야 하는 거리
''';
      final limits = parseVendorSpeedLimits(yaml);
      expect(limits.progressAllowanceSeconds, 10.0);
      expect(limits.progressRadiusMeters, .5);
    });
  });
}
