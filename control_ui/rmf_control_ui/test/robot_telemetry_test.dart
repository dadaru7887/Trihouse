import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/robot_telemetry_models.dart';

/// Gazebo 가 내는 위치 토픽을 앱이 어떻게 읽는지.
///
/// 출처를 Gazebo 로 골라도 화면 숫자는 앱이 계산한 것이었다. 실제로 토픽을
/// 받아와야 그 숫자가 진짜가 된다.
void main() {
  final at = DateTime(2026, 8, 9, 12);

  group('CSV 파싱', () {
    test('위치와 방향을 푼다', () {
      // `ros2 topic echo <토픽> --field pose.pose --csv` 가 내는 모양.
      // z=0.3827 w=0.9239 는 45도다.
      final pose = RobotPose.parseCsv(
        '3.25,1.75,0.0,0.0,0.0,0.3826834,0.9238795',
        at,
      );
      expect(pose, isNotNull);
      expect(pose!.x, closeTo(3.25, 1e-9));
      expect(pose.y, closeTo(1.75, 1e-9));
      expect(pose.heading * 180 / 3.14159265358979, closeTo(45, .01));
    });

    test('돌지 않은 로봇은 방향이 0이다', () {
      final pose = RobotPose.parseCsv('1,2,0,0,0,0,1', at);
      expect(pose!.heading, closeTo(0, 1e-9));
    });

    test('반대로 돈 것도 푼다', () {
      // z=-0.7071 w=0.7071 은 -90도.
      final pose = RobotPose.parseCsv('0,0,0,0,0,-0.7071068,0.7071068', at);
      expect(pose!.heading * 180 / 3.14159265358979, closeTo(-90, .01));
    });

    test('모양이 다르면 값을 지어내지 않는다', () {
      // 숫자가 모자라거나 섞이면 null 이어야 한다. 0 으로 채우면 로봇이
      // 원점으로 순간이동한 것처럼 보인다.
      expect(RobotPose.parseCsv('1,2,3', at), isNull);
      expect(RobotPose.parseCsv('', at), isNull);
      expect(RobotPose.parseCsv('a,b,c,d,e,f,g', at), isNull);
      expect(RobotPose.parseCsv('1,2,0,0,0,0,--', at), isNull);
    });

    test('여분의 열이 있어도 앞 일곱 개만 본다', () {
      final pose = RobotPose.parseCsv('1,2,0,0,0,0,1,999,888', at);
      expect(pose, isNotNull);
      expect(pose!.x, 1);
    });
  });

  group('살아 있는가', () {
    test('방금 온 값은 살아 있다', () {
      final status = RobotTelemetryStatus(
        subscribing: true,
        poses: {'PK-01': RobotPose(x: 0, y: 0, heading: 0, at: at)},
        message: '',
      );
      expect(
        status.isLive('PK-01', now: at.add(const Duration(seconds: 1))),
        isTrue,
      );
    });

    test('오래된 값은 죽은 것으로 본다', () {
      // 값이 멈춘 것을 실시간으로 착각하면 로봇이 서 있는지 통신이 끊긴 건지
      // 구별할 수 없다.
      final status = RobotTelemetryStatus(
        subscribing: true,
        poses: {'PK-01': RobotPose(x: 0, y: 0, heading: 0, at: at)},
        message: '',
      );
      expect(
        status.isLive('PK-01', now: at.add(const Duration(seconds: 5))),
        isFalse,
      );
    });

    test('구독만 걸고 값이 안 오면 살아 있지 않다', () {
      const status = RobotTelemetryStatus(
        subscribing: true,
        poses: {},
        message: '',
      );
      expect(status.isLive('PK-01'), isFalse);
    });

    test('모르는 로봇은 살아 있지 않다', () {
      final status = RobotTelemetryStatus(
        subscribing: true,
        poses: {'PK-01': RobotPose(x: 0, y: 0, heading: 0, at: at)},
        message: '',
      );
      expect(status.isLive('없는로봇', now: at), isFalse);
    });
  });

  group('백엔드가 오르내려도 다시 붙는다', () {
    // 백엔드를 내렸다 올리면 `ros2 topic echo` 도 함께 죽는다. 죽은 것을 살아
    // 있는 것으로 알고 넘기면 앱은 영영 아무 값도 못 받는다 — 등록도 토픽도
    // 멀쩡한데 화면만 조용했다.
    test('로봇별 프로세스 대신 fleet_states 하나만 읽는다', () {
      final source = File(
        'lib/robot_telemetry_bridge_io.dart',
      ).readAsStringSync();
      expect(source, contains('exec ros2 topic echo /fleet_states'));
      expect(source, contains('await _openFleetStates()'));
      expect(source, isNot(contains('Future<void> _open(String robotId')));
    });

    test('사람이 다시 붙여 주기를 기다리지 않는다', () {
      // 5초마다 스스로 다시 띄운다. 붙을 것이 없으면 시계도 멈춘다.
      final source = File(
        'lib/robot_telemetry_bridge_io.dart',
      ).readAsStringSync();
      expect(source, contains('void _startHealer()'));
      expect(source, contains('Timer.periodic(const Duration(seconds: 5)'));
      expect(source, contains('_healer?.cancel()'));
    });
  });
}
