import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/wall_height.dart';

void main() {
  group('wall height validation', () {
    test('rejects non-finite, non-positive, and out-of-range values', () {
      expect(wallHeightError(null), isNotNull);
      expect(wallHeightError(double.nan), isNotNull);
      expect(wallHeightError(double.infinity), isNotNull);
      expect(wallHeightError(0), isNotNull);
      expect(wallHeightError(-.3), isNotNull);
      expect(wallHeightError(minWallHeight - .01), isNotNull);
      expect(wallHeightError(maxWallHeight + .01), isNotNull);
    });

    test('accepts the inclusive supported range', () {
      expect(wallHeightError(minWallHeight), isNull);
      expect(wallHeightError(.3), isNull);
      expect(wallHeightError(defaultWallHeight), isNull);
      expect(wallHeightError(maxWallHeight), isNull);
    });
  });

  group('laser clearance warning', () {
    test('warns when a wall is below the laser plane', () {
      expect(wallHeightWarning(.08), contains('라이다'));
      expect(wallHeightWarning(.3, laserHeight: .5), isNotNull);
    });

    test('does not warn at or above the laser plane', () {
      expect(wallHeightWarning(.3), isNull);
      expect(wallHeightWarning(laserHeightPinky), isNull);
    });

    test('keeps the Pinky laser height aligned with the robot model', () {
      expect(laserHeightPinky, closeTo(.102, 1e-9));
    });
  });
}
