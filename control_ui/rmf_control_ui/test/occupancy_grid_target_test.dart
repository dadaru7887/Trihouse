import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/occupancy_grid.dart';

/// 격자를 정해진 칸 수 상자에 맞추는 계산.
///
/// 기본을 800×600 으로 두었다. 칸 수를 고정하면 파일 크기가 예측 가능해지지만
/// **해상도가 건물 크기에 따라 정해진다** — 큰 창고에서는 한 칸이 로봇만 해져
/// 좁은 통로가 통째로 막힌 것으로 보인다. 그래서 거친지 판정하는 함수를 함께
/// 두고, 화면이 그것을 보고 경고한다.
void main() {
  group('상자에 맞추는 해상도', () {
    test('두 축 중 빡빡한 쪽에 맞춘다', () {
      // 세로가 더 긴 건물. 정사각 칸을 지키려면 세로가 기준이 된다.
      final res = occupancyResolutionForTarget(
        widthMeters: 3.267,
        heightMeters: 3.657,
        targetWidth: 800,
        targetHeight: 600,
      );
      expect(res, closeTo(3.657 / 600, 1e-9));
      // 상자를 넘지 않는다.
      expect((3.267 / res).ceil(), lessThanOrEqualTo(800));
      expect((3.657 / res).ceil(), lessThanOrEqualTo(600));
    });

    test('가로가 더 긴 건물은 가로가 기준이 된다', () {
      final res = occupancyResolutionForTarget(
        widthMeters: 101.1,
        heightMeters: 61.1,
        targetWidth: 800,
        targetHeight: 600,
      );
      expect(res, closeTo(101.1 / 800, 1e-9));
      expect((61.1 / res).ceil(), lessThanOrEqualTo(600));
    });

    test('0 이나 음수가 오면 0 을 돌려준다', () {
      // buildOccupancyGrid 가 resolution <= 0 이면 null 을 내므로 조용히 멈춘다.
      for (final bad in [
        occupancyResolutionForTarget(
          widthMeters: 0,
          heightMeters: 3,
          targetWidth: 800,
          targetHeight: 600,
        ),
        occupancyResolutionForTarget(
          widthMeters: 3,
          heightMeters: 3,
          targetWidth: 0,
          targetHeight: 600,
        ),
      ]) {
        expect(bad, 0);
      }
    });
  });

  group('거친지 판정', () {
    test('로봇 몸이 6칸 미만이면 거칠다', () {
      // 100×60m 창고를 800×600 에 넣으면 0.126 m/칸 — 로봇 몸이 4.7칸.
      expect(
        occupancyResolutionTooCoarse(resolution: .126, robotWidth: .6),
        isTrue,
      );
      // 로봇 조건만 떼어 본다. costmap 조건은 크게 열어 둔다.
      expect(
        occupancyResolutionTooCoarse(
          resolution: .1,
          robotWidth: .6,
          costmapResolution: 1,
        ),
        isFalse,
        reason: '0.6/6 = 0.1 은 딱 경계라 통과',
      );
      expect(
        occupancyResolutionTooCoarse(
          resolution: .11,
          robotWidth: .6,
          costmapResolution: 1,
        ),
        isTrue,
      );
    });

    test('두 조건 중 하나만 걸려도 거칠다', () {
      // 0.1 은 로봇(0.6m) 기준으로는 딱 통과하지만 costmap 0.05 보다 거칠다.
      expect(
        occupancyResolutionTooCoarse(resolution: .1, robotWidth: .6),
        isTrue,
        reason: 'costmap 조건에서 걸려야 한다',
      );
    });

    test('costmap 보다 거칠면 거칠다', () {
      // 큰 로봇이면 0.1 도 몸 기준으로는 통과하지만, costmap 0.05 보다 거칠다.
      expect(
        occupancyResolutionTooCoarse(resolution: .1, robotWidth: 3),
        isTrue,
      );
      expect(
        occupancyResolutionTooCoarse(resolution: .05, robotWidth: 3),
        isFalse,
      );
    });

    test('gwanghee·project1 의 800×600 은 통과한다', () {
      for (final size in [
        (3.267, 3.657), // gwanghee
        (3.300, 3.683), // project1
      ]) {
        final res = occupancyResolutionForTarget(
          widthMeters: size.$1,
          heightMeters: size.$2,
          targetWidth: 800,
          targetHeight: 600,
        );
        expect(
          occupancyResolutionTooCoarse(resolution: res, robotWidth: .6),
          isFalse,
          reason: '$size 에서 800×600 은 좋은 선택이어야 한다',
        );
        // costmap 0.05 보다 촘촘해야 한다.
        expect(res, lessThan(.05));
      }
    });
  });

  group('상자를 정확히 채우기', () {
    // 2m × 3m 바닥. 여백 0.55 가 사방에 붙어 3.1 × 4.1 m 가 된다.
    final floor = <GridPoint>[
      (x: 0, y: 0),
      (x: 2, y: 0),
      (x: 2, y: -3),
      (x: 0, y: -3),
    ];

    test('채우지 않으면 필요한 만큼만 만든다', () {
      final grid = buildOccupancyGrid(
        floorOutline: floor,
        walls: const [],
        resolution: .05,
      )!;
      expect(grid.width, (3.1 / .05).ceil());
      expect(grid.height, (4.1 / .05).ceil());
    });

    test('채우면 정확히 그 칸 수가 된다', () {
      final grid = buildOccupancyGrid(
        floorOutline: floor,
        walls: const [],
        resolution: .05,
        padToWidth: 800,
        padToHeight: 600,
      )!;
      expect(grid.width, 800);
      expect(grid.height, 600);
    });

    test('채운 자리는 모름이고 기하는 그대로다', () {
      const resolution = .05;
      final plain = buildOccupancyGrid(
        floorOutline: floor,
        walls: const [],
        resolution: resolution,
      )!;
      final padded = buildOccupancyGrid(
        floorOutline: floor,
        walls: const [],
        resolution: resolution,
        padToWidth: 800,
        padToHeight: 600,
      )!;

      // 다닐 수 있는 칸 수가 같아야 한다 — 채운 자리는 모름이므로.
      expect(padded.freeCells, plain.freeCells);
      // 한 칸 크기도 그대로다.
      expect(padded.resolution, resolution);
      // 건물이 가운데 온다 — 원점이 양쪽으로 반씩 밀린다.
      final grewX = (800 - plain.width) * resolution / 2;
      final grewY = (600 - plain.height) * resolution / 2;
      expect(padded.originX, closeTo(plain.originX - grewX, 1e-9));
      expect(padded.originY, closeTo(plain.originY - grewY, 1e-9));
    });

    test('바닥의 같은 자리가 양쪽에서 다닐 수 있다', () {
      // 원점이 밀렸어도 월드 좌표로 같은 점을 짚으면 같은 판정이 나와야 한다.
      const resolution = .05;
      const probe = (x: 1.0, y: -1.5); // 바닥 가운데
      for (final grid in [
        buildOccupancyGrid(
          floorOutline: floor,
          walls: const [],
          resolution: resolution,
        )!,
        buildOccupancyGrid(
          floorOutline: floor,
          walls: const [],
          resolution: resolution,
          padToWidth: 800,
          padToHeight: 600,
        )!,
      ]) {
        final col = ((probe.x - grid.originX) / resolution).floor();
        final row =
            grid.height - 1 - ((probe.y - grid.originY) / resolution).floor();
        expect(
          grid.at(col, row),
          OccupancyGrid.free,
          reason: '${grid.width}×${grid.height} 에서 바닥 가운데가 막혀 있다',
        );
      }
    });

    test('필요한 칸 수보다 작게 주면 무시한다', () {
      // 기하를 잘라 내면 벽이 사라진다. 그것보다는 상자를 넘기는 편이 낫다.
      final grid = buildOccupancyGrid(
        floorOutline: floor,
        walls: const [],
        resolution: .05,
        padToWidth: 3,
        padToHeight: 3,
      )!;
      expect(grid.width, (3.1 / .05).ceil());
      expect(grid.height, (4.1 / .05).ceil());
    });
  });
}
