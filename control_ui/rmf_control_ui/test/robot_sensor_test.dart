/// relay 가 내려 준 센서 파일을 푸는 규칙.
///
/// 카메라 영상은 `ros2 topic echo` 로 읽을 수 없다 — 1280×720 한 장이 YAML 로
/// 2.7MB 다. 그래서 relay 노드가 줄여서 파일로 내려 주고 앱은 그것만 읽는다.
library;

import 'dart:math' as math;
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/robot_sensor_models.dart';

void main() {
  final at = DateTime(2026, 8, 9, 18);

  group('라이다', () {
    test('relay 가 쓴 두 줄을 푼다', () {
      final scan = RobotScan.parse(
        '-3.141593,3.141593,0.050,12.000\n1.500,2.000,12.000\n',
        at,
      )!;
      expect(scan.angleMin, closeTo(-math.pi, 1e-5));
      expect(scan.angleMax, closeTo(math.pi, 1e-5));
      expect(scan.rangeMin, 0.05);
      expect(scan.rangeMax, 12.0);
      expect(scan.ranges, [1.5, 2.0, 12.0]);
      expect(scan.at, at);
    });

    test('제일 가까운 것을 찾는다 — 못 잰 값은 빼고', () {
      // 최대 거리는 `아무것도 없다` 는 뜻이다. 그것을 가장 가까운 것으로 세면
      // 벽이 코앞에 있다고 잘못 알린다.
      final scan = RobotScan.parse(
        '0,6.283,0.050,12.000\n12.000,0.400,12.000,0.900\n',
        at,
      )!;
      expect(scan.nearest, 0.4);
      expect(scan.hits, 2);
    });

    test('아무것도 못 맞히면 가장 가까운 것이 없다', () {
      final scan = RobotScan.parse(
        '0,6.283,0.050,12.000\n12.000,12.000\n',
        at,
      )!;
      expect(scan.nearest, isNull);
      expect(scan.hits, 0);
    });

    test('점의 방향을 고르게 나눈다', () {
      final scan = RobotScan.parse('0,3.141593,0.05,12\n1,2,3\n', at)!;
      expect(scan.angleAt(0), 0);
      expect(scan.angleAt(1), closeTo(math.pi / 2, 1e-5));
      expect(scan.angleAt(2), closeTo(math.pi, 1e-5));
    });

    test('모양이 다르면 푸는 대신 null 을 준다', () {
      expect(RobotScan.parse('', at), isNull);
      expect(RobotScan.parse('0,1,2,3\n', at), isNull);
      expect(RobotScan.parse('0,1\n1,2\n', at), isNull);
      expect(RobotScan.parse('0,1,2,3\n\n', at), isNull);
    });
  });

  group('카메라', () {
    Uint8List frame(int width, int height) {
      final header = BytesBuilder()
        ..add([0x52, 0x53, 0x49, 0x4D]) // RSIM
        ..add(
          (ByteData(8)
                ..setUint32(0, width, Endian.little)
                ..setUint32(4, height, Endian.little))
              .buffer
              .asUint8List(),
        )
        ..add(Uint8List(width * height * 4));
      return header.toBytes();
    }

    test('머리글과 화소를 푼다', () {
      final image = RobotCameraFrame.parse(frame(320, 180), at)!;
      expect(image.width, 320);
      expect(image.height, 180);
      expect(image.pixels.length, 320 * 180 * 4);
      expect(image.at, at);
    });

    test('머리글이 아니면 안 받는다', () {
      final wrong = Uint8List.fromList([1, 2, 3, 4, 0, 0, 0, 0, 0, 0, 0, 0]);
      expect(RobotCameraFrame.parse(wrong, at), isNull);
    });

    test('화소가 모자라면 안 받는다', () {
      // relay 가 쓰는 중일 수 있다. 그대로 그리면 깨진 그림이 나온다.
      final short = Uint8List.sublistView(frame(320, 180), 0, 5000);
      expect(RobotCameraFrame.parse(short, at), isNull);
    });

    test('터무니없는 크기는 안 받는다', () {
      // 그대로 믿고 자리를 잡으면 앱이 죽는다.
      expect(RobotCameraFrame.parse(frame(0, 180), at), isNull);
      final huge = BytesBuilder()
        ..add([0x52, 0x53, 0x49, 0x4D])
        ..add(
          (ByteData(8)
                ..setUint32(0, 99999, Endian.little)
                ..setUint32(4, 99999, Endian.little))
              .buffer
              .asUint8List(),
        );
      expect(RobotCameraFrame.parse(huge.toBytes(), at), isNull);
    });

    test('너무 짧으면 안 받는다', () {
      expect(RobotCameraFrame.parse(Uint8List(3), at), isNull);
    });
  });

  group('값이 오고 있는가', () {
    test('파일이 남아 있는 것과 값이 오는 것은 다르다', () {
      // relay 가 죽어도 파일은 그대로다. 시각을 안 보면 멈춘 그림을 실시간으로
      // 착각한다.
      final old = RobotScan.parse('0,1,0.05,12\n1,2\n', at)!;
      final sensors = RobotSensors(scan: old);
      expect(
        sensors.scanIsLive(now: at.add(const Duration(seconds: 1))),
        isTrue,
      );
      expect(
        sensors.scanIsLive(now: at.add(const Duration(seconds: 9))),
        isFalse,
      );
    });

    test('없으면 오고 있지 않다', () {
      const empty = RobotSensors();
      expect(empty.isEmpty, isTrue);
      expect(empty.scanIsLive(now: at), isFalse);
      expect(empty.cameraIsLive(now: at), isFalse);
    });
  });

  group('라이다를 그리는 자리', () {
    test('앞(0도)이 위로 간다', () {
      // 화면은 y 가 아래로 간다. 돌려 그리지 않으면 앞뒤가 뒤집힌다.
      final point = scanPointOffset(
        angle: 0,
        range: 1,
        maxRange: 1,
        radius: 100,
      );
      expect(point.dx, closeTo(0, 1e-9));
      expect(point.dy, closeTo(-100, 1e-9));
    });

    test('왼쪽(90도)이 왼쪽으로 간다', () {
      final point = scanPointOffset(
        angle: math.pi / 2,
        range: 1,
        maxRange: 1,
        radius: 100,
      );
      expect(point.dx, closeTo(100, 1e-9));
      expect(point.dy, closeTo(0, 1e-9));
    });

    test('먼 것일수록 바깥에 그린다', () {
      final near = scanPointOffset(
        angle: 0,
        range: 1,
        maxRange: 10,
        radius: 100,
      );
      final far = scanPointOffset(
        angle: 0,
        range: 9,
        maxRange: 10,
        radius: 100,
      );
      expect(near.dy.abs(), lessThan(far.dy.abs()));
    });

    test('최대 거리를 넘어도 그림 밖으로 나가지 않는다', () {
      final point = scanPointOffset(
        angle: 0,
        range: 999,
        maxRange: 10,
        radius: 100,
      );
      expect(point.dy.abs(), lessThanOrEqualTo(100));
    });
  });
}
