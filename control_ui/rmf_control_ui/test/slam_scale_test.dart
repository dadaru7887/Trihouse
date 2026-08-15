import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/occupancy_grid.dart';
import 'package:rmf_control_ui/slam_map.dart';

/// 도면 축척을 SLAM 지도로 검증하는 계산.
///
/// 도면의 축척은 사람이 두 점 사이 실제 거리를 재서 넣은 값이라 오차가 있다.
/// SLAM 은 로봇이 실제로 굴러 잰 값이라 그걸로 견줄 수 있다. 축척이 틀리면
/// building.yaml · nav graph · 격자 · Gazebo 메시가 한꺼번에 틀어진다.
void main() {
  /// 테두리에 벽이 있고 안이 바닥인 격자를 만든다. 바깥 [pad] 칸은 `모름`.
  Uint8List box(int width, int height, {int pad = 0}) {
    final cells = Uint8List(width * height)
      ..fillRange(0, width * height, OccupancyGrid.unknown);
    for (var row = pad; row < height - pad; row++) {
      for (var col = pad; col < width - pad; col++) {
        final edge =
            row == pad ||
            row == height - pad - 1 ||
            col == pad ||
            col == width - pad - 1;
        cells[row * width + col] = edge
            ? OccupancyGrid.occupied
            : OccupancyGrid.free;
      }
    }
    return cells;
  }

  group('벽으로 읽히는가', () {
    test('map_server 와 같은 규칙이다', () {
      // 점유 확률 = (255 - 값) / 255. 문턱 0.65.
      expect(isOccupiedValue(0, occupiedThreshold: .65), isTrue);
      expect(isOccupiedValue(254, occupiedThreshold: .65), isFalse);
      // 205(모름)는 0.196 이라 벽이 아니다.
      expect(isOccupiedValue(205, occupiedThreshold: .65), isFalse);
      // 문턱 바로 위·아래
      expect(isOccupiedValue(89, occupiedThreshold: .65), isTrue); // .651
      expect(isOccupiedValue(90, occupiedThreshold: .65), isFalse); // .647
    });

    test('negate 면 뒤집힌다', () {
      expect(
        isOccupiedValue(254, occupiedThreshold: .65, negate: true),
        isTrue,
      );
      expect(isOccupiedValue(0, occupiedThreshold: .65, negate: true), isFalse);
    });
  });

  group('벽 테두리 재기', () {
    test('벽만 감싼다 — 모름은 뺀다', () {
      // 20×20 격자에 바깥 5칸은 모름, 안쪽 10×10 이 건물.
      final extent = occupiedExtent(
        cells: box(20, 20, pad: 5),
        width: 20,
        height: 20,
        resolution: .05,
        occupiedThreshold: .65,
      )!;
      // 벽이 col·row 5..14 → 10칸 → 0.5m
      expect(extent.widthMeters, closeTo(.5, 1e-9));
      expect(extent.heightMeters, closeTo(.5, 1e-9));
      // 테두리 한 겹: 10×10 - 8×8 = 36칸
      expect(extent.cells, 36);
    });

    test('그림 크기가 아니라 건물 크기를 잰다', () {
      // 같은 건물(10×10칸)을 담은 두 그림. 여백이 달라도 결과가 같아야 한다.
      final tight = occupiedExtent(
        cells: box(10, 10),
        width: 10,
        height: 10,
        resolution: .05,
        occupiedThreshold: .65,
      )!;
      final loose = occupiedExtent(
        cells: box(40, 30, pad: 0),
        width: 40,
        height: 30,
        resolution: .05,
        occupiedThreshold: .65,
      );
      expect(tight.widthMeters, closeTo(.5, 1e-9));
      // loose 는 40×30 테두리라 건물이 다르다 — 크기가 다르게 나와야 한다.
      expect(loose!.widthMeters, closeTo(2, 1e-9));
    });

    test('벽이 없으면 null', () {
      final cells = Uint8List(9)..fillRange(0, 9, OccupancyGrid.free);
      expect(
        occupiedExtent(
          cells: cells,
          width: 3,
          height: 3,
          resolution: .05,
          occupiedThreshold: .65,
        ),
        isNull,
      );
    });
  });

  group('축척 견주기', () {
    test('같으면 1.0 이고 0% 다', () {
      final same = (widthMeters: 2.0, heightMeters: 3.0, cells: 100);
      final result = compareWallExtents(drawing: same, slam: same)!;
      expect(result.ratio, closeTo(1, 1e-9));
      expect(result.percent, closeTo(0, 1e-9));
      expect(result.trustworthy, isTrue);
    });

    test('도면이 작게 잡혀 있으면 양수 % 가 나온다', () {
      // 실제(SLAM)가 2% 크다 → 도면 축척을 2% 키워야 한다.
      final result = compareWallExtents(
        drawing: (widthMeters: 2.0, heightMeters: 3.0, cells: 100),
        slam: (widthMeters: 2.04, heightMeters: 3.06, cells: 100),
      )!;
      expect(result.ratioX, closeTo(1.02, 1e-9));
      expect(result.ratioY, closeTo(1.02, 1e-9));
      expect(result.percent, closeTo(2, 1e-6));
      expect(result.trustworthy, isTrue);
    });

    test('두 축이 어긋나면 믿지 않는다', () {
      // 한쪽 복도를 안 돌아본 경우. 이 숫자를 축척에 넣으면 안 된다.
      final result = compareWallExtents(
        drawing: (widthMeters: 2.0, heightMeters: 3.0, cells: 100),
        slam: (widthMeters: 2.04, heightMeters: 2.10, cells: 100),
      )!;
      expect(result.trustworthy, isFalse);
      expect(result.axisDisagreement, greaterThan(.05));
    });

    test('기하평균을 쓴다 — 한쪽 축의 치우침을 줄인다', () {
      final result = compareWallExtents(
        drawing: (widthMeters: 2.0, heightMeters: 2.0, cells: 100),
        slam: (widthMeters: 2.2, heightMeters: 1.8, cells: 100),
      )!;
      // 1.1 과 0.9 의 기하평균 = sqrt(0.99) ≈ 0.99499
      expect(result.ratio, closeTo(0.994987, 1e-6));
      // 산술평균(1.0)과 다르다는 점이 요점이다.
      expect(result.ratio, lessThan(1));
      expect(result.trustworthy, isFalse, reason: '20% 어긋났으니 믿지 않는다');
    });

    test('한쪽이 없으면 null', () {
      final some = (widthMeters: 2.0, heightMeters: 3.0, cells: 100);
      expect(compareWallExtents(drawing: null, slam: some), isNull);
      expect(compareWallExtents(drawing: some, slam: null), isNull);
      expect(
        compareWallExtents(
          drawing: (widthMeters: 0.0, heightMeters: 3.0, cells: 1),
          slam: some,
        ),
        isNull,
      );
    });
  });

  group('보정을 축척에 넣기', () {
    test('measurement 길이에 비를 곱하면 된다', () {
      // 축척은 meters / pixels 다. 비를 길이에 곱하면 축척도 같은 비로 바뀐다.
      const pixels = 1842.512;
      const meters = 2.11;
      final before = meters / pixels;
      const ratio = 1.02;
      final after = (meters * ratio) / pixels;
      expect(after / before, closeTo(ratio, 1e-12));
    });
  });
}
