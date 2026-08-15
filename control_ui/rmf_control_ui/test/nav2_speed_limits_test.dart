import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/nav2_speed_limits.dart';

/// 벤더 파일에서 실제로 뽑아 온 모양. 주석과 들여쓰기까지 같게 두었다 —
/// 주석을 안 떼면 숫자를 못 읽는 것이 이 파서의 주된 실패 방식이다.
const String _vendorSample = '''
controller_server:
  ros__parameters:
    FollowPath:
      plugin: nav2_regulated_pure_pursuit_controller::RegulatedPurePursuitController
      desired_linear_vel: 0.2                # [m/s] 목표 기본 직진 속도
      max_angular_accel: 3.2                 # [rad/s^2] 최대 각가속도
      use_rotate_to_heading: true            # 제자리 회전 먼저 하기
      rotate_to_heading_angular_vel: 1.0     # [rad/s] 제자리 회전 속도

velocity_smoother:
  ros__parameters:
    max_velocity: [0.25, 0.0, 1.5]
    min_velocity: [-0.25, 0.0, -1.5]
    max_accel: [2.5, 0.0, 3.2]
    max_decel: [-2.5, 0.0, -3.2]
''';

void main() {
  group('parseVendorSpeedLimits', () {
    test('벤더 파일에서 네 값을 뽑는다', () {
      final limits = parseVendorSpeedLimits(_vendorSample);

      expect(limits.linearVelocity, 0.2);
      expect(limits.linearAcceleration, 2.5);
      expect(limits.angularVelocity, 1.0);
      expect(limits.angularAcceleration, 3.2);
      expect(limits.isComplete, isTrue);
      expect(limits.isEmpty, isFalse);
    });

    test('가속도는 목록의 첫 항만 쓴다', () {
      // `[x, y, theta]` 에서 직진은 x 다. theta 를 집어 오면 회전 가속도가
      // 직진 가속도 자리에 들어가 RMF 가 엉뚱한 시간을 계산한다.
      final limits = parseVendorSpeedLimits('    max_accel: [2.5, 0.0, 3.2]');
      expect(limits.linearAcceleration, 2.5);
    });

    test('주석을 값으로 읽지 않는다', () {
      final limits = parseVendorSpeedLimits(
        '      desired_linear_vel: 0.35   # [m/s] 설명이 붙어 있다',
      );
      expect(limits.linearVelocity, 0.35);
    });

    test('같은 이름이 여러 번 나오면 처음 것을 쓴다', () {
      final limits = parseVendorSpeedLimits('''
      desired_linear_vel: 0.2
      desired_linear_vel: 9.9
''');
      expect(limits.linearVelocity, 0.2);
    });

    test('찾지 못한 값은 null 로 두고 0 으로 채우지 않는다', () {
      // 0 으로 채우면 "벤더가 정지를 원한다" 는 뜻이 되어 버린다.
      final limits = parseVendorSpeedLimits('some_other_key: 1.0');
      expect(limits.linearVelocity, isNull);
      expect(limits.linearAcceleration, isNull);
      expect(limits.angularVelocity, isNull);
      expect(limits.angularAcceleration, isNull);
      expect(limits.isEmpty, isTrue);
      expect(limits.isComplete, isFalse);
    });

    test('빈 문자열도 견딘다', () {
      expect(parseVendorSpeedLimits('').isEmpty, isTrue);
    });

    test('목록이 아닌 max_accel 은 무시한다', () {
      expect(
        parseVendorSpeedLimits('    max_accel: 2.5').linearAcceleration,
        isNull,
      );
    });
  });
}
