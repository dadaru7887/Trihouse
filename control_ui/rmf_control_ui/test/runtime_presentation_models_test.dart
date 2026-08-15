import 'dart:math' as math;
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/operations_log_models.dart';
import 'package:rmf_control_ui/rmf_runtime_models.dart';
import 'package:rmf_control_ui/robot_sensor_models.dart';
import 'package:rmf_control_ui/robot_telemetry_models.dart';

void main() {
  final at = DateTime(2026, 8, 9, 18);

  test(
    'Team A LiDAR parser and visualization geometry remain browser-safe',
    () {
      final scan = RobotScan.parse(
        '-3.141593,3.141593,0.050,12.000\n1.500,2.000,12.000\n',
        at,
      )!;
      final ahead = scanPointOffset(
        angle: 0,
        range: 1,
        maxRange: 1,
        radius: 100,
      );

      expect(scan.nearest, 1.5);
      expect(scan.hits, 2);
      expect(scan.angleAt(1), closeTo(0, 1e-5));
      expect(ahead.dx, closeTo(0, 1e-9));
      expect(ahead.dy, closeTo(-100, 1e-9));
    },
  );

  test('Team A camera parser rejects incomplete browser event payloads', () {
    final bytes = BytesBuilder()
      ..add([0x52, 0x53, 0x49, 0x4D])
      ..add(
        (ByteData(8)
              ..setUint32(0, 2, Endian.little)
              ..setUint32(4, 2, Endian.little))
            .buffer
            .asUint8List(),
      )
      ..add(Uint8List(16));

    expect(RobotCameraFrame.parse(bytes.toBytes(), at)?.pixels, hasLength(16));
    expect(
      RobotCameraFrame.parse(Uint8List.sublistView(bytes.toBytes(), 0, 15), at),
      isNull,
    );
  });

  test('Team A telemetry pose retains yaw and staleness semantics', () {
    final pose = RobotPose.parseCsv('1,2,0,0,0,0.7071068,0.7071068', at)!;
    final status = RobotTelemetryStatus(
      subscribing: true,
      poses: {'PK_01': pose},
      message: 'Gateway operations stream',
    );

    expect(pose.heading, closeTo(math.pi / 2, .001));
    expect(
      status.isLive('PK_01', now: at.add(const Duration(seconds: 1))),
      isTrue,
    );
    expect(
      status.isLive('PK_01', now: at.add(const Duration(seconds: 5))),
      isFalse,
    );
  });

  test(
    'Team A RMF fleet parser extracts robot map poses without ROS access',
    () {
      final poses = parseFleetStatePoses('''
robots:
- name: PK_01
  location:
    x: 1.25
    y: -0.5
    yaw: 0.75
  path:
  - name: destination
    x: 99
    y: 99
''');

      expect(poses.keys, {'PK_01'});
      expect(poses['PK_01']?.x, 1.25);
      expect(poses['PK_01']?.y, -0.5);
      expect(poses['PK_01']?.yaw, 0.75);
    },
  );

  test('Team A operation labels remain suitable for the Gateway timeline', () {
    expect(OperationLogKind.parse('task'), OperationLogKind.task);
    expect(OperationLogKind.parse('future-kind'), OperationLogKind.event);
    expect(
      formatEntryTitle(OperationLogKind.setting, 'robot\tadded\tPK_01'),
      '로봇 등록 추가 · PK_01',
    );
  });
}
