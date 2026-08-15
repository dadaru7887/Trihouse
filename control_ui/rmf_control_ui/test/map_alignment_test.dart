/// 지도 정합 — 위치추정 지도와 주행 그래프가 같은 자리에 있는지 지킨다.
///
/// 로봇이 길을 찾는 데는 두 가지가 함께 쓰인다.
///
///   위치추정 지도 (`nav2_map/*.yaml`)  — AMCL 이 라이다 스캔을 맞출 점유격자
///   주행 그래프  (`nav_graphs/0.yaml`) — RMF 가 길을 고를 Waypoint 와 Lane
///
/// 어긋나면 RMF 는 `픽업1` 로 보내는데 AMCL 은 로봇이 딴 데 있다고 여긴다.
/// **오류는 안 난다.** 로봇이 엉뚱한 데로 갈 뿐이다.
///
/// 실제로 이랬다 — SLAM 지도가 건물이 없는 위쪽을 덮고, 건물 아래 0.44m 는
/// 지도 밖이었다. 도면에서 구운 격자는 그래프와 같은 도면에서 나와 맞았다.
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/nav2_map_alignment.dart';

void main() {
  /// 실제 배포에서 읽은 값.
  final slam = MapExtentMeters.fromOrigin(
    originX: -0.214,
    originY: -1.523,
    resolution: .05,
    widthCells: 43,
    heightCells: 53,
  );
  final fromDrawing = MapExtentMeters.fromOrigin(
    originX: -1.238644,
    originY: -3.241447,
    resolution: 0.005994,
    widthCells: 800,
    heightCells: 615,
  );

  /// 이 맵의 Waypoint 11곳. `nav_graphs/0.yaml` 에서 그대로 가져왔다.
  const graph = <String, ({double x, double y})>{
    '드랍오프1': (x: 1.924, y: -0.286),
    '대기1': (x: 1.236, y: -0.282),
    '대기2': (x: 0.450, y: -0.286),
    '픽업1': (x: 0.454, y: -0.869),
    '충전1': (x: 1.612, y: -0.717),
    '충전2': (x: 1.613, y: -1.088),
    '대기3': (x: 1.185, y: -1.091),
    '대기4': (x: 1.185, y: -1.602),
    '대기5': (x: 0.409, y: -1.602),
    '픽업2': (x: 0.405, y: -1.964),
    '드랍오프2': (x: 1.919, y: -1.096),
  };

  group('원점은 왼쪽 아래다', () {
    test('위로 세지 않는다', () {
      // 여기를 뒤집으면 y 가 통째로 반대편으로 가서, 맞는 지도를 어긋났다고
      // 판정한다.
      expect(slam.minY, closeTo(-1.523, 1e-9));
      expect(slam.maxY, closeTo(-1.523 + 53 * .05, 1e-9));
      expect(slam.maxY, greaterThan(slam.minY));
    });
  });

  group('실제 배포', () {
    test('SLAM 지도는 어긋나 있었다', () {
      final result = checkNav2MapAlignment(map: slam, waypoints: graph);
      expect(result.isAligned, isFalse);
      expect(result.covered, isFalse);
      // 건물 아래쪽 Waypoint 셋이 지도 밖이었다.
      expect(result.outsideWaypoints, ['대기4', '대기5', '픽업2']);
      expect(result.marginMeters, lessThan(0));
    });

    test('도면에서 구운 격자는 맞는다', () {
      // 주행 그래프와 같은 도면에서 나오므로 어긋날 수가 없다.
      final result = checkNav2MapAlignment(map: fromDrawing, waypoints: graph);
      expect(result.isAligned, isTrue);
      expect(result.outsideWaypoints, isEmpty);
      expect(result.marginMeters, greaterThan(minAlignmentMargin));
    });
  });

  group('가장자리에 붙은 것도 잡는다', () {
    test('안에 있어도 여유가 없으면 통과시키지 않는다', () {
      // 자리 자체는 지도 안이어도 가장자리에 바짝 붙으면 라이다 절반이 미지
      // 영역을 향한다. 위치추정이 거기서 흔들린다.
      const tight = MapExtentMeters(minX: 0, maxX: 2, minY: -2, maxY: 0);
      final result = checkNav2MapAlignment(
        map: tight,
        waypoints: const {'끝자리': (x: 0.05, y: -1)},
      );
      expect(result.covered, isTrue, reason: '지도 안에는 있다');
      expect(result.isAligned, isFalse, reason: '그래도 통과시키면 안 된다');
      expect(result.marginMeters, closeTo(.05, 1e-9));
    });

    test('여유가 넉넉하면 통과한다', () {
      const room = MapExtentMeters(minX: 0, maxX: 2, minY: -2, maxY: 0);
      final result = checkNav2MapAlignment(
        map: room,
        waypoints: const {'가운데': (x: 1, y: -1)},
      );
      expect(result.isAligned, isTrue);
      expect(result.marginMeters, closeTo(1, 1e-9));
    });
  });

  group('견줄 것이 없을 때', () {
    test('Waypoint 가 없으면 어긋났다고 하지 않는다', () {
      // 근거가 없는 것과 어긋난 것은 다르다.
      final result = checkNav2MapAlignment(map: slam, waypoints: const {});
      expect(result.covered, isTrue);
      expect(result.outsideWaypoints, isEmpty);
    });
  });
}
