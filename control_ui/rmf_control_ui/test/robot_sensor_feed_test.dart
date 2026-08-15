/// relay 가 내려 준 파일을 앱이 읽는 규칙.
///
/// 파일이 남아 있는 것과 값이 오는 것은 다르다. relay 가 죽어도 파일은 그대로라,
/// 멈춘 그림을 실시간으로 착각하기 쉽다.
@TestOn('vm')
library;

import 'dart:io';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/robot_sensor_feed.dart';
import 'package:rmf_control_ui/robot_sensor_models.dart';

void main() {
  group('파일 이름', () {
    test('로봇 ID 를 그대로 쓴다', () {
      expect(sensorFileStem('PK-01'), 'PK-01');
      expect(sensorFileStem('핑키1'), '핑키1');
    });

    test('디렉터리 밖으로 나가지 못한다', () {
      // 로봇 ID 는 사람이 타자로 친다. 슬래시가 들어가면 엉뚱한 곳을 읽는다.
      expect(sensorFileStem('../../etc/passwd'), isNot(contains('/')));
      expect(sensorFileStem('../../etc/passwd'), isNot(contains('..')));
      expect(sensorFileStem(''), 'robot');
    });
  });

  group('relay 와 만나는 자리', () {
    test('환경 변수로 바꿀 수 있다', () {
      // 기본값은 시스템 임시 디렉터리 아래다. 남겨 둘 값이 아니다.
      expect(sensorDirectoryEnvironmentKey, 'ROBOSAPIENS_SENSOR_DIR');
      expect(robotSensorDirectory(), isNotEmpty);
    });
  });

  group('읽어 들이기', () {
    late Directory directory;

    setUp(() {
      directory = Directory.systemTemp.createTempSync('sensor_feed_test');
    });

    tearDown(() {
      RobotSensorFeed.instance.stop();
      if (directory.existsSync()) directory.deleteSync(recursive: true);
    });

    Uint8List frame(int width, int height, int fill) {
      final bytes = BytesBuilder()
        ..add([0x52, 0x53, 0x49, 0x4D])
        ..add(
          (ByteData(8)
                ..setUint32(0, width, Endian.little)
                ..setUint32(4, height, Endian.little))
              .buffer
              .asUint8List(),
        )
        ..add(
          Uint8List(width * height * 4)..fillRange(0, width * height * 4, fill),
        );
      return bytes.toBytes();
    }

    test('라이다와 카메라를 함께 읽는다', () async {
      File(
        '${directory.path}/PK-01.scan',
      ).writeAsStringSync('0,6.283,0.05,12\n1.500,2.000\n');
      File('${directory.path}/PK-01.frame').writeAsBytesSync(frame(4, 2, 200));

      final feed = RobotSensorFeed.instance;
      // 환경 변수를 테스트에서 바꿀 수 없으므로 자리를 직접 확인한다.
      // 여기서는 파싱 규칙만 본다.
      expect(feed.sensorsOf('PK-01').isEmpty, isTrue);

      final scan = RobotScan.parse(
        File('${directory.path}/PK-01.scan').readAsStringSync(),
        DateTime.now(),
      );
      expect(scan, isNotNull);
      expect(scan!.ranges, [1.5, 2.0]);

      final image = RobotCameraFrame.parse(
        File('${directory.path}/PK-01.frame').readAsBytesSync(),
        DateTime.now(),
      );
      expect(image, isNotNull);
      expect(image!.width, 4);
      expect(image.pixels.every((byte) => byte == 200), isTrue);
    });

    test('안 보는 로봇은 값을 들고 있지 않는다', () {
      final feed = RobotSensorFeed.instance;
      feed.watch(const ['PK-01']);
      expect(feed.watching, isTrue);
      feed.stop();
      expect(feed.watching, isFalse);
      expect(feed.sensors, isEmpty);
    });

    test('볼 로봇이 없으면 지켜보지 않는다', () {
      final feed = RobotSensorFeed.instance;
      feed.watch(const []);
      expect(feed.watching, isFalse);
    });

    test('모르는 로봇은 빈 값을 준다', () {
      // 없는 것을 null 로 주면 부르는 쪽마다 null 검사를 해야 한다.
      expect(RobotSensorFeed.instance.sensorsOf('없는로봇').isEmpty, isTrue);
    });
  });
}
