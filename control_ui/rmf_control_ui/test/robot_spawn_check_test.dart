/// 등록된 로봇의 자리가 지도와 맞는지 살피는 판정.
///
/// 좌표는 눈에 안 보이는 값이라 틀려도 티가 안 난다. 홈1 에 올린 핑키가 건물 밖
/// 허공에서 끝없이 떨어지고 있어도 화면은 멀쩡했다 — 바퀴는 허공에서도 돌아서
/// odom 이 정상으로 보였기 때문이다. 그래서 사람이 눌러서 확인할 수 있어야 한다.
///
/// 아래 숫자는 gwanghee 맵에서 실제로 재서 가져온 것이다.
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/rmf_project_config.dart';
import 'package:rmf_control_ui/robot_spawn_check.dart';

void main() {
  // gwanghee.building.yaml 의 measurements: 1842.512px = 2.1100m.
  const metersPerPixel = 2.1100 / 1842.512;

  // 홈1 의 지도 픽셀. RMF 월드로는 (1.760744, −0.637585).
  const homePixel = (dx: 1537.532, dy: 556.757);
  const homeX = 1.760744309942079;
  const homeY = -0.6375845964639578;

  // 바닥 메시가 있는 픽셀 범위. 미터로는 y 가 −2.664 ~ −0.107 이다.
  bool insideFloor(double dx, double dy) =>
      dx >= 55 && dx <= 1947 && dy >= 93 && dy <= 2327;

  RmfProjectRobot pinky({double? spawnX, double? spawnY, String? station}) =>
      RmfProjectRobot(
        robotId: 'PK-01',
        displayName: '핑키 1호',
        model: 'PINKY-GZ',
        gzName: 'pinky_01',
        zones: const ['ambient'],
        chargerWaypoint: station,
        spawnX: spawnX,
        spawnY: spawnY,
      );

  List<SpawnCheck> check(
    List<RmfProjectRobot> robots, {
    ({double dx, double dy})? station = homePixel,
    double? scale = metersPerPixel,
  }) => checkRobotSpawns(
    robots: robots,
    pixelOf: (_) => station,
    insideFloor: insideFloor,
    metersPerPixel: scale,
  );

  group('자리 판정', () {
    test('저장된 자리가 지도와 같고 바닥 안이면 맞다', () {
      final result = check([
        pinky(spawnX: homeX, spawnY: homeY, station: '홈1'),
      ]).single;
      expect(result.issue, SpawnIssue.ok);
      expect(result.isOk, isTrue);
      expect(result.willChange, isFalse);
    });

    test('y 부호가 뒤집힌 예전 값은 바닥 밖으로 잡힌다', () {
      // 예전 판이 저장하던 값. 이대로 올리면 로봇이 끝없이 떨어진다.
      final result = check([
        pinky(spawnX: 1.642, spawnY: 1.595, station: '홈1'),
      ]).single;
      expect(result.issue, SpawnIssue.outsideFloor);
      expect(result.storedInsideFloor, isFalse);
      expect(result.willChange, isTrue);
      expect(result.fromMap?.x, closeTo(homeX, 1e-9));
      expect(result.fromMap?.y, closeTo(homeY, 1e-9));
    });

    test('충전소와 Spawn 위치가 달라도 바닥 안이면 정상이다', () {
      // 충전1은 복귀점이고 이 좌표는 대기4의 시작 위치다.
      final result = check([
        pinky(spawnX: 1.0, spawnY: -1.0, station: '홈1'),
      ]).single;
      expect(result.issue, SpawnIssue.ok);
      expect(result.storedInsideFloor, isTrue);
      expect(result.willChange, isFalse);
    });

    test('자리를 안 고른 로봇은 좌표 없음이다', () {
      final result = check([pinky(station: '홈1')]).single;
      expect(result.issue, SpawnIssue.noCoordinate);
      expect(result.willChange, isTrue);
    });

    test('자리 Waypoint 를 못 찾으면 맞추기로 고칠 수 없다', () {
      final result = check([
        pinky(spawnX: homeX, spawnY: homeY, station: '없어진자리'),
      ], station: null).single;
      expect(result.issue, SpawnIssue.noStation);
      expect(result.issue.fixableByRefit, isFalse);
      expect(result.willChange, isFalse);
    });

    test('축척이 없으면 아무것도 판정하지 않는다', () {
      // 미터로 옮길 수가 없다. 틀렸다고 단정하면 헛경고가 된다.
      expect(check([pinky(station: '홈1')], scale: null), isEmpty);
      expect(check([pinky(station: '홈1')], scale: 0), isEmpty);
    });

    test('판정은 지도 기준이 아니라 저장된 값을 본다', () {
      // 실행에 실제로 나가는 것은 저장된 값이다. 지도에서 다시 계산한 값만
      // 보면 정작 틀린 좌표가 나가는 것을 놓친다.
      final result = check([
        pinky(spawnX: 1.642, spawnY: 1.595, station: '홈1'),
      ]).single;
      expect(result.stored?.y, 1.595);
      expect(result.storedInsideFloor, isFalse);
    });
  });

  group('요약 한 줄', () {
    test('모두 맞으면 그렇게 말한다', () {
      final checks = check([
        pinky(spawnX: homeX, spawnY: homeY, station: '홈1'),
      ]);
      expect(spawnCheckSummary(checks), '1대 모두 시작 위치가 유효합니다.');
    });

    test('바닥 밖은 몇 대인지 세어서 알린다', () {
      final checks = check([
        pinky(spawnX: 1.642, spawnY: 1.595, station: '홈1'),
        pinky(spawnX: 2.0, spawnY: 3.0, station: '홈1'),
      ]);
      expect(spawnCheckSummary(checks), contains('2대가 바닥 밖에 있습니다'));
    });

    test('살펴볼 로봇이 없으면 그렇게 말한다', () {
      expect(spawnCheckSummary(const []), '살펴볼 로봇이 없습니다.');
    });
  });

  group('무엇을 해야 하는지 알린다', () {
    test('바닥 밖은 왜 위험한지 밝힌다', () {
      expect(SpawnIssue.outsideFloor.detail, contains('떨어집니다'));
      expect(SpawnIssue.outsideFloor.detail, contains('설치 로봇'));
    });

    test('자리를 못 찾으면 어디서 고치는지 알린다', () {
      expect(SpawnIssue.noStation.detail, contains('로봇 등록'));
    });

    test('맞추기로 풀리는 것과 아닌 것을 가린다', () {
      expect(SpawnIssue.outsideFloor.fixableByRefit, isTrue);
      expect(SpawnIssue.stale.fixableByRefit, isTrue);
      expect(SpawnIssue.noCoordinate.fixableByRefit, isTrue);
      expect(SpawnIssue.noStation.fixableByRefit, isFalse);
      expect(SpawnIssue.ok.fixableByRefit, isFalse);
    });
  });
}
