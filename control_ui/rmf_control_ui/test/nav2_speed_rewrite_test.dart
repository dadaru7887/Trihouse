/// 앱의 속도가 로봇을 실제로 움직이는 값까지 닿는지 지킨다.
///
/// 속도가 두 군데 있었고, 둘이 어긋나 있었다.
///
///   RMF (`project1_pinky_config.yaml`)  linear: [1.00, 0.750]   ← 배차 계산용
///   Nav2 (`robots/PK_01/nav2_params.yaml`)  desired_linear_vel: 0.2  ← 실제 주행
///
/// 로봇은 0.2m/s 로 갔다. 앱에서 속도를 올려도 RMF 쪽 숫자만 바뀌어서 아무것도
/// 안 빨라졌다. 그 위에 RMF 는 5배 빠른 줄 알고 있었으므로, 멀쩡히 가는 로봇을
/// 늦었다고 보고 경로를 다시 짰다.
///
/// 벤더 파일은 그대로 둔다. 로봇마다 만드는 복사본만 고친다 — 어차피 프레임과
/// 토픽도 이미 갈라 놓았다.
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/nav2_params.dart';
import 'package:rmf_control_ui/nav2_speed_limits.dart';

void main() {
  /// 벤더 파일에서 속도에 관한 줄만 추린 것.
  const vendor = '''
controller_server:
  ros__parameters:
    FollowPath:
      desired_linear_vel: 0.2                # [m/s] 목표 기본 직진 속도
      rotate_to_heading_angular_vel: 1.0     # [rad/s] 제자리 회전 속도
velocity_smoother:
  ros__parameters:
    max_velocity: [0.25, 0.0, 1.5]
    max_accel: [2.5, 0.0, 3.2]
''';

  String rewrite({double? speed}) => rewriteNav2Params(
    source: vendor,
    namespace: 'pinky_01',
    linearVelocity: speed,
  ).yaml;

  group('속도를 주면 실제 주행 값을 고친다', () {
    test('목표 직진 속도', () {
      expect(rewrite(speed: 2.0), contains('desired_linear_vel: 2.000'));
      expect(rewrite(speed: 2.0), isNot(contains('desired_linear_vel: 0.2 ')));
    });

    test('스무더 상한도 함께 올린다', () {
      // 여기를 안 올리면 목표만 2.0 이 되고 실제로는 0.25 에서 잘린다. 겉으로는
      // 값을 바꿨는데 로봇은 그대로인 상태가 된다.
      final yaml = rewrite(speed: 2.0);
      expect(yaml, contains('max_velocity: [2.500, 0.0, 1.5]'));
    });

    test('상한은 목표보다 위다', () {
      // 딱 같게 두면 스무더가 목표에 닿기 직전에 늘 걸린다.
      final limits = parseVendorSpeedLimits(rewrite(speed: 0.8));
      expect(limits.linearVelocity, 0.8);
      final ceiling = RegExp(
        r'max_velocity: \[([\d.]+)',
      ).firstMatch(rewrite(speed: 0.8))!.group(1)!;
      expect(double.parse(ceiling), greaterThan(0.8));
    });

    test('회전 속도와 가속도는 벤더 값 그대로 둔다', () {
      // 직진만 요구받았다. 나머지까지 손대면 벤더가 왜 그 값을 골랐는지 모르는
      // 채로 바꾸는 것이 된다.
      final yaml = rewrite(speed: 2.0);
      expect(yaml, contains('rotate_to_heading_angular_vel: 1.0'));
      expect(yaml, contains('max_accel: [2.5, 0.0, 3.2]'));
    });

    test('무엇을 바꿨는지 남긴다', () {
      final result = rewriteNav2Params(
        source: vendor,
        namespace: 'pinky_01',
        linearVelocity: 2.0,
      );
      expect(
        result.changes.any((c) => c.contains('desired_linear_vel')),
        isTrue,
      );
      expect(result.changes.any((c) => c.contains('max_velocity')), isTrue);
    });
  });

  group('속도를 안 주면', () {
    test('벤더 값을 건드리지 않는다', () {
      final yaml = rewrite();
      expect(yaml, contains('desired_linear_vel: 0.2'));
      expect(yaml, contains('max_velocity: [0.25, 0.0, 1.5]'));
    });
  });

  group('벤더 파일이 바뀌었을 때', () {
    test('벡터가 아니면 조용히 넘기지 않고 알린다', () {
      // 상한을 못 고쳤는데 목표만 올리면 로봇은 안 빨라진다. 그것을 모르면
      // 값이 안 먹는다고만 보인다.
      const odd = '''
velocity_smoother:
  ros__parameters:
    max_velocity: 0.25
''';
      final result = rewriteNav2Params(
        source: odd,
        namespace: 'pinky_01',
        linearVelocity: 2.0,
      );
      expect(result.warnings, isNotEmpty);
      expect(result.warnings.first, contains('max_velocity'));
    });
  });

  group('되읽어도 같은 값이 나온다', () {
    test('앱이 보여 주는 벤더 속도와 어긋나지 않는다', () {
      // 로봇 등록 화면이 parseVendorSpeedLimits 로 이 파일을 읽어 보여 준다.
      // 여기서 쓴 값과 저기서 읽는 값이 다르면 화면이 거짓말을 한다.
      final limits = parseVendorSpeedLimits(rewrite(speed: 1.75));
      expect(limits.linearVelocity, 1.75);
    });
  });
}
