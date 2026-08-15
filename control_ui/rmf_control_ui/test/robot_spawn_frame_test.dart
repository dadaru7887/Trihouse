/// 로봇을 올릴 자리가 RMF 월드 좌표와 맞는지.
///
/// 실제로 겪은 일: 홈1 에 스폰했는데 로봇이 지도 원점에 그려졌고, Gazebo 에서는
/// 건물 밖 허공에 놓여 끝없이 떨어졌다(z 가 −600만 m 까지 내려갔다). 원인이 둘
/// 겹쳐 있었다.
///
///   1. 앱이 화면용 바닥 좌표(바닥 왼쪽 아래가 원점, y 는 위로)를 그대로 spawn
///      좌표로 썼다. RMF 는 그림 왼쪽 위가 원점이고 y 가 아래로 갈수록 음수다.
///   2. `/…/odom` 은 월드 좌표가 아니라 올린 자리를 원점으로 잰 값이라, 방금
///      올린 로봇은 언제나 0, 0 을 낸다.
///
/// 아래 숫자는 gwanghee 맵에서 실제로 재서 가져온 것이다.
library;

import 'dart:math' as math;

import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/rmf_project_config.dart';
import 'package:rmf_control_ui/robot_telemetry_models.dart';

void main() {
  // gwanghee.building.yaml 의 measurements: 1842.512px = 2.1100m.
  const metersPerPixel = 2.1100 / 1842.512;

  group('RMF 월드 좌표', () {
    test('홈1 픽셀이 nav graph 가 적은 미터와 같다', () {
      // gwanghee.building.yaml: 홈1 은 픽셀 [1537.532, 556.757].
      // nav_graphs/0.yaml: 같은 홈1 이 (1.760744…, −0.637585…).
      final world = rmfWorldFromPixel(1537.532, 556.757, metersPerPixel);
      expect(world.x, closeTo(1.760744309942079, 1e-9));
      expect(world.y, closeTo(-0.6375845964639578, 1e-9));
    });

    test('y 는 음수다 — 바닥 메시가 음수 y 에만 있다', () {
      // generated_models/gwanghee_L1/meshes/floor_1.obj 의 y 범위는
      // −2.664 ~ −0.107 이다. 양수 y 로 올리면 바닥이 없어 떨어진다.
      final world = rmfWorldFromPixel(1537.532, 556.757, metersPerPixel);
      expect(world.y, lessThan(-0.107));
      expect(world.y, greaterThan(-2.664));
    });

    test('픽셀로 되돌리면 제자리로 온다', () {
      final world = rmfWorldFromPixel(1537.532, 556.757, metersPerPixel);
      final pixel = pixelFromRmfWorld(world.x, world.y, metersPerPixel);
      expect(pixel.dx, closeTo(1537.532, 1e-6));
      expect(pixel.dy, closeTo(556.757, 1e-6));
    });

    test('그림 왼쪽 위가 원점이다', () {
      final world = rmfWorldFromPixel(0, 0, metersPerPixel);
      expect(world.x, 0);
      expect(world.y, 0);
    });
  });

  group('odom 을 월드로 옮기기', () {
    final at = DateTime(2026, 8, 9, 10);

    test('갓 올린 로봇의 0,0 은 올린 자리를 뜻한다', () {
      final odom = RobotPose(x: 0, y: 0, heading: 0, at: at);
      final world = odom.toWorld(
        spawnX: 1.760744309942079,
        spawnY: -0.6375845964639578,
      );
      expect(world.x, closeTo(1.760744309942079, 1e-9));
      expect(world.y, closeTo(-0.6375845964639578, 1e-9));
    });

    test('앞으로 1m 가면 월드에서도 1m 간다', () {
      final odom = RobotPose(x: 1, y: 0, heading: 0, at: at);
      final world = odom.toWorld(spawnX: 1.76, spawnY: -0.64);
      expect(world.x, closeTo(2.76, 1e-9));
      expect(world.y, closeTo(-0.64, 1e-9));
    });

    test('스폰 방향이 90도면 odom 의 앞은 월드의 +y 다', () {
      final odom = RobotPose(x: 1, y: 0, heading: 0, at: at);
      final world = odom.toWorld(
        spawnX: 1.76,
        spawnY: -0.64,
        spawnHeading: math.pi / 2,
      );
      expect(world.x, closeTo(1.76, 1e-9));
      expect(world.y, closeTo(0.36, 1e-9));
      expect(world.heading, closeTo(math.pi / 2, 1e-9));
    });

    test('시각은 그대로 둔다 — 끊김 판정이 흔들리면 안 된다', () {
      final odom = RobotPose(x: 1, y: 2, heading: .5, at: at);
      expect(odom.toWorld(spawnX: 0, spawnY: 0).at, at);
    });

    test('스폰 자리를 모르면 받은 값을 그대로 둔다', () {
      final odom = RobotPose(x: 1, y: 2, heading: .5, at: at);
      final world = odom.toWorld(spawnY: -0.64);
      expect(world.x, 1);
      expect(world.y, 2);
    });
  });

  group('저장해 둔 자리 고치기', () {
    const pinky = RmfProjectRobot(
      robotId: 'PK-01',
      displayName: '핑키 1호',
      model: 'PINKY-GZ',
      gzName: 'pinky_01',
      zones: ['ambient'],
      chargerWaypoint: '홈1',
      // 예전 판이 남긴 값. y 부호가 반대라 건물 밖이다.
      spawnX: 1.642,
      spawnY: 1.595,
    );

    test('잘못된 좌표계로 저장된 자리를 지금 지도 기준으로 고친다', () {
      final fixed = robotsWithMapSpawnPoints(
        [pinky],
        (_) => (dx: 1537.532, dy: 556.757),
        metersPerPixel,
      );
      expect(fixed.single.spawnX, closeTo(1.760744309942079, 1e-9));
      expect(fixed.single.spawnY, closeTo(-0.6375845964639578, 1e-9));
    });

    test('이름과 구획 자격은 건드리지 않는다', () {
      final fixed = robotsWithMapSpawnPoints(
        [pinky],
        (_) => (dx: 1537.532, dy: 556.757),
        metersPerPixel,
      ).single;
      expect(fixed.robotId, 'PK-01');
      expect(fixed.displayName, '핑키 1호');
      expect(fixed.gzName, 'pinky_01');
      expect(fixed.zones, ['ambient']);
      expect(fixed.chargerWaypoint, '홈1');
    });

    test('자리를 못 찾은 로봇은 좌표를 잃지 않는다', () {
      // 지도가 아직 안 올라온 사이에 불릴 수 있다. 그때 지워 버리면 멀쩡한
      // 등록이 자리를 잃는다.
      final kept = robotsWithMapSpawnPoints([pinky], (_) => null, 0.001);
      expect(identical(kept, [pinky]), isFalse);
      expect(kept.single.spawnX, 1.642);
      expect(kept.single.spawnY, 1.595);
    });

    test('이미 맞으면 받은 목록을 그대로 돌려준다', () {
      final good = [
        pinky.withSpawn(spawnX: 1.760744309942079, spawnY: -0.6375845964639578),
      ];
      expect(
        identical(
          robotsWithMapSpawnPoints(
            good,
            (_) => (dx: 1537.532, dy: 556.757),
            metersPerPixel,
          ),
          good,
        ),
        isTrue,
      );
    });

    test('충전소와 다른 유효한 시작 좌표는 다시 열어도 유지한다', () {
      final waiting4 = [pinky.withSpawn(spawnX: 1.185, spawnY: -1.602)];
      final kept = robotsWithMapSpawnPoints(
        waiting4,
        (_) => (dx: 1537.532, dy: 556.757),
        metersPerPixel,
      );

      expect(identical(kept, waiting4), isTrue);
      expect(kept.single.chargerWaypoint, '홈1');
      expect(kept.single.spawnX, 1.185);
      expect(kept.single.spawnY, -1.602);
    });

    test('자리는 있는데 좌표가 없던 로봇도 채워 준다', () {
      const noSpawn = RmfProjectRobot(
        robotId: 'PK-02',
        displayName: '핑키 2호',
        model: 'PINKY-GZ',
        gzName: 'pinky_02',
        zones: [],
        chargerWaypoint: '홈1',
      );
      final fixed = robotsWithMapSpawnPoints(
        [noSpawn],
        (_) => (dx: 1537.532, dy: 556.757),
        metersPerPixel,
      ).single;
      expect(fixed.spawnX, closeTo(1.760744309942079, 1e-9));
      expect(fixed.spawnY, closeTo(-0.6375845964639578, 1e-9));
    });

    test('축척을 모르면 아무것도 바꾸지 않는다', () {
      final robots = [pinky];
      expect(
        identical(
          robotsWithMapSpawnPoints(
            robots,
            (_) => (dx: 1537.532, dy: 556.757),
            0,
          ),
          robots,
        ),
        isTrue,
      );
    });
  });
}
