/// 도면에서 만든 점유격자가 Gazebo 월드와 같은 자리에 놓이는지.
///
/// 이 격자로 AMCL 이 라이다를 맞춘다. 원점이 한 칸만 어긋나도 로봇은 `픽업1로
/// 가라`는 명령을 받고 엉뚱한 데로 간다. 좌표계는 어제 한 번 크게 데인 곳이라
/// 숫자를 못 박아 둔다.
library;

import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/occupancy_grid.dart';

void main() {
  // 4m × 3m 짜리 방. 왼쪽 위가 (0, 0), 건물 안은 y 가 음수다.
  const room = <GridPoint>[
    (x: 0, y: 0),
    (x: 4, y: 0),
    (x: 4, y: -3),
    (x: 0, y: -3),
  ];
  const roomWalls = <GridWall>[
    ((x: 0, y: 0), (x: 4, y: 0)),
    ((x: 4, y: 0), (x: 4, y: -3)),
    ((x: 4, y: -3), (x: 0, y: -3)),
    ((x: 0, y: -3), (x: 0, y: 0)),
  ];

  OccupancyGrid build({
    double resolution = .1,
    double margin = .5,
    List<GridPoint> floor = room,
    List<GridWall> walls = roomWalls,
  }) => buildOccupancyGrid(
    floorOutline: floor,
    walls: walls,
    resolution: resolution,
    margin: margin,
  )!;

  group('격자가 놓이는 자리', () {
    test('원점은 담을 범위의 왼쪽 아래다', () {
      final grid = build();
      // 방은 x 0~4, y −3~0. 여백 0.5 에 벽 두께 절반 0.05 가 더 붙는다.
      expect(grid.originX, closeTo(-0.55, 1e-9));
      expect(grid.originY, closeTo(-3.55, 1e-9));
    });

    test('격자가 방 전체와 여백을 덮는다', () {
      final grid = build();
      expect(grid.bounds.minX, lessThan(0));
      expect(grid.bounds.maxX, greaterThan(4));
      expect(grid.bounds.minY, lessThan(-3));
      expect(grid.bounds.maxY, greaterThan(0));
    });

    test('첫 줄이 위쪽이다 — PGM 과 같은 차례', () {
      final grid = build();
      final top = grid.centerOf(0, 0);
      final bottom = grid.centerOf(0, grid.height - 1);
      expect(top.y, greaterThan(bottom.y));
      // 맨 아랫줄의 가운데는 원점에서 셀 반 칸 위다.
      expect(bottom.y, closeTo(grid.originY + grid.resolution / 2, 1e-9));
    });

    test('셀 가운데가 Nav2 가 읽는 자리와 같다', () {
      final grid = build();
      // Nav2: worldY = origin + (height − 1 − row + 0.5) × res
      for (final row in [0, 7, grid.height - 1]) {
        expect(
          grid.centerOf(3, row).y,
          closeTo(
            grid.originY + (grid.height - 1 - row + .5) * grid.resolution,
            1e-9,
          ),
        );
      }
    });
  });

  group('무엇이 벽이고 무엇이 바닥인가', () {
    test('방 한가운데는 다닐 수 있다', () {
      final grid = build();
      final col = ((2.0 - grid.originX) / grid.resolution).floor();
      final row =
          grid.height - 1 - ((-1.5 - grid.originY) / grid.resolution).floor();
      expect(grid.at(col, row), OccupancyGrid.free);
    });

    test('벽 위는 막혀 있다', () {
      final grid = build();
      // 위쪽 벽은 y = 0 을 지난다.
      final col = ((2.0 - grid.originX) / grid.resolution).floor();
      final row =
          grid.height - 1 - ((0.0 - grid.originY) / grid.resolution).floor();
      expect(grid.at(col, row), OccupancyGrid.occupied);
    });

    test('방 밖은 모르는 곳이다', () {
      final grid = build();
      // 벽에서 충분히 떨어진 바깥.
      final col = ((-0.4 - grid.originX) / grid.resolution).floor();
      final row =
          grid.height - 1 - ((-1.5 - grid.originY) / grid.resolution).floor();
      expect(grid.at(col, row), OccupancyGrid.unknown);
    });

    test('벽이 바닥을 덮는다 — 칠하는 차례가 맞다', () {
      // 벽은 바닥 다각형 안을 지난다. 바닥을 나중에 칠하면 벽이 지워진다.
      final grid = build(walls: const [((x: 2, y: -0.5), (x: 2, y: -2.5))]);
      final col = ((2.0 - grid.originX) / grid.resolution).floor();
      final row =
          grid.height - 1 - ((-1.5 - grid.originY) / grid.resolution).floor();
      expect(grid.at(col, row), OccupancyGrid.occupied);
    });

    test('벽 두께는 RMF 와 같은 0.1m 다', () {
      // 이 값이 다르면 라이다가 보는 벽과 지도의 벽이 어긋나 AMCL 이 못 붙는다.
      expect(rmfWallThickness, 0.1);
      final grid = build(
        resolution: .01,
        walls: const [((x: 1, y: -1), (x: 3, y: -1))],
        floor: room,
      );
      int cellAt(double x, double y) => grid.at(
        ((x - grid.originX) / grid.resolution).floor(),
        grid.height - 1 - ((y - grid.originY) / grid.resolution).floor(),
      );
      // 선분에서 0.04m 는 안, 0.06m 는 바깥.
      expect(cellAt(2, -1.04), OccupancyGrid.occupied);
      expect(cellAt(2, -0.94), OccupancyGrid.free);
    });
  });

  group('만들 수 없을 때', () {
    test('바닥도 벽도 없으면 만들지 않는다', () {
      expect(
        buildOccupancyGrid(
          floorOutline: const [],
          walls: const [],
          resolution: .05,
        ),
        isNull,
      );
    });

    test('축척이 0 이면 만들지 않는다', () {
      expect(
        buildOccupancyGrid(floorOutline: room, walls: roomWalls, resolution: 0),
        isNull,
      );
    });

    test('격자가 터무니없이 크면 만들지 않는다', () {
      // 축척이 틀리면 셀이 수억 개가 되어 앱이 멈춘다.
      expect(
        buildOccupancyGrid(
          floorOutline: room,
          walls: roomWalls,
          resolution: .00001,
        ),
        isNull,
      );
    });

    test('벽만 있어도 만든다', () {
      final grid = buildOccupancyGrid(
        floorOutline: const [],
        walls: roomWalls,
        resolution: .1,
      );
      expect(grid, isNotNull);
      expect(grid!.freeCells, 0);
      expect(grid.occupiedCells, greaterThan(0));
    });
  });

  group('map_server 가 읽는 파일', () {
    test('PGM 머리글과 그림 길이가 맞다', () {
      final grid = build();
      final pgm = grid.toPgm();
      final header = ascii.decode(
        pgm.sublist(0, pgm.indexOf(0x35) + 1 + 20).toList(),
        allowInvalid: true,
      );
      expect(header, startsWith('P5\n${grid.width} ${grid.height}\n255\n'));
      final headerLength = 'P5\n${grid.width} ${grid.height}\n255\n'.length;
      expect(pgm.length, headerLength + grid.width * grid.height);
    });

    test('yaml 의 origin 이 격자의 원점과 같다', () {
      final grid = build();
      final yaml = grid.toYaml(imageName: 'gwanghee.pgm');
      expect(yaml, contains('image: gwanghee.pgm'));
      expect(
        yaml,
        contains(
          'origin: [${grid.originX.toStringAsFixed(6)}, '
          '${grid.originY.toStringAsFixed(6)}, 0.000000]',
        ),
      );
      expect(yaml, contains('mode: trinary'));
      expect(yaml, contains('negate: 0'));
    });

    test('회색이 바닥으로 읽히지 않는다', () {
      // map_server 는 (255 − 값) / 255 로 어둡기를 잰다. 회색 205 는
      // 0.196078… 이라 free_thresh 0.196 보다 아주 조금 크다. 그래서 `모름` 이다.
      // 한쪽만 바꾸면 모르는 곳이 전부 다닐 수 있는 바닥이 된다.
      const grey = (255 - OccupancyGrid.unknown) / 255;
      expect(grey, greaterThan(OccupancyGrid.freeThreshold));
      expect(grey, lessThan(OccupancyGrid.occupiedThreshold));

      const white = (255 - OccupancyGrid.free) / 255;
      expect(white, lessThan(OccupancyGrid.freeThreshold));

      const black = (255 - OccupancyGrid.occupied) / 255;
      expect(black, greaterThan(OccupancyGrid.occupiedThreshold));
    });

    test('설명을 주석으로 얹을 수 있다', () {
      final yaml = build().toYaml(
        imageName: 'gwanghee.pgm',
        note: 'rmf_control_ui 가 도면에서 만들었다.',
      );
      expect(yaml, contains('# rmf_control_ui 가 도면에서 만들었다.'));
      // 주석이 image: 앞에 와야 파서가 읽는 데 지장이 없다.
      expect(yaml.indexOf('#'), lessThan(yaml.indexOf('image:')));
    });
  });

  group('한 칸을 몇 미터로 할까', () {
    test('작은 아레나는 잘게 뜬다', () {
      // gwanghee 는 짧은 쪽이 2.557m 다. 0.05m 로 뜨면 방이 쉰 칸밖에 안 되어
      // AMCL 이 맞출 무늬가 없다.
      final resolution = occupancyResolutionFor(
        robotWidth: .6,
        floorShorterSide: 2.557,
      );
      expect(resolution, closeTo(2.557 / 120, 1e-9));
      expect(2.557 / resolution, greaterThan(100));
    });

    test('큰 건물은 ROS 관례인 0.05m 를 넘지 않는다', () {
      expect(occupancyResolutionFor(robotWidth: .6, floorShorterSide: 50), .05);
    });

    test('로봇 몸이 여섯 칸은 되게 한다', () {
      // 한 칸이 로봇만 하면 좁은 통로가 통째로 막힌 것으로 보인다.
      const width = .15;
      final resolution = occupancyResolutionFor(
        robotWidth: width,
        floorShorterSide: 50,
      );
      expect(width / resolution, greaterThanOrEqualTo(6));
    });

    test('아무리 잘아도 0.01m 아래로는 안 간다', () {
      expect(
        occupancyResolutionFor(robotWidth: .01, floorShorterSide: .1),
        .01,
      );
    });

    test('바닥을 모르면 로봇 몸만 본다', () {
      expect(occupancyResolutionFor(robotWidth: .6), .05);
      expect(occupancyResolutionFor(robotWidth: .15), closeTo(.025, 1e-9));
      expect(occupancyResolutionFor(robotWidth: .6, floorShorterSide: 0), .05);
    });
  });

  group('gwanghee 맵 실측', () {
    test('바닥 범위가 Gazebo 의 floor_1.obj 와 겹친다', () {
      // generated_models/gwanghee_L1/meshes/floor_1.obj 를 재 보면
      //   x 0.063 ~ 2.230 · y −2.664 ~ −0.107
      const floor = <GridPoint>[
        (x: 0.063, y: -0.107),
        (x: 2.230, y: -0.107),
        (x: 2.230, y: -2.664),
        (x: 0.063, y: -2.664),
      ];
      final grid = buildOccupancyGrid(
        floorOutline: floor,
        walls: const [],
        resolution: .025,
        margin: .3,
      )!;
      // 홈1 (1.7607, −0.6376) 은 바닥 안이어야 한다.
      final col = ((1.7607 - grid.originX) / grid.resolution).floor();
      final row =
          grid.height -
          1 -
          ((-0.6376 - grid.originY) / grid.resolution).floor();
      expect(grid.at(col, row), OccupancyGrid.free);

      // 예전 판이 로봇을 올리던 자리(1.642, +1.595)는 격자 밖이다.
      expect(grid.bounds.maxY, lessThan(1.595));
    });
  });
}
