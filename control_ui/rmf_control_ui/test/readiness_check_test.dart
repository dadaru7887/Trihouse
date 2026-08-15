/// 작업 준비 확인표의 판단을 지킨다.
///
/// 로봇이 RViz 에 뜨려면 다섯이 줄줄이 되어야 하는데, 하나만 끊겨도 화면은 그냥
/// 빈다. 오류는 어디에도 안 난다 — 어댑터가 SIGSEGV 로 죽었을 때 Gazebo·Nav2·
/// RMF core 는 멀쩡히 살아 있어 겉으로는 정상으로 보였다.
///
/// 가장 조심할 것은 **모른다와 안 됐다를 가르는 것**이다. 뭉뚱그리면 확인 못 한
/// 것이 고장으로 읽혀, 멀쩡한 로봇을 두고 원인을 찾게 된다.
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/nav2_map_alignment.dart';
import 'package:rmf_control_ui/readiness_check.dart';
import 'package:rmf_control_ui/rmf_project_config.dart';

void main() {
  const pinky = RmfProjectRobot(
    robotId: 'PK_01',
    displayName: '핑키 1호',
    model: 'PINKY-GZ',
    gzName: 'pinky_01',
    zones: ['ambient'],
    chargerWaypoint: '충전1',
    dataSource: RobotDataSource.gazebo,
  );
  const pinky2 = RmfProjectRobot(
    robotId: 'PK_02',
    displayName: '핑키 2호',
    model: 'PINKY-GZ',
    gzName: 'pinky_02',
    zones: ['ambient'],
    chargerWaypoint: '충전2',
    dataSource: RobotDataSource.gazebo,
  );
  const arm = RmfProjectRobot(
    robotId: 'OMX_01',
    displayName: '매니퓰레이터',
    model: 'OPENMANIPULATOR-X',
    gzName: 'omx_01',
    kind: RmfRobotKind.workcell,
    zones: ['ambient'],
    dataSource: RobotDataSource.gazebo,
  );
  const mockRobot = RmfProjectRobot(
    robotId: 'MK_01',
    displayName: '가짜 로봇',
    model: 'MOCK',
    gzName: 'mock_01',
    zones: ['ambient'],
  );

  ReadinessReport report({
    List<String> waypoints = const ['충전1', '픽업1'],
    List<RmfProjectRobot> robots = const [pinky],
    bool exported = true,
    bool backendRunning = true,
    bool fleetReachable = true,
    Set<String> attached = const {'PK_01'},
    Nav2MapAlignment? alignment = const Nav2MapAlignment(
      covered: true,
      outsideWaypoints: [],
      marginMeters: 1,
    ),
    int? clockPublishers = 1,
  }) => buildReadinessReport(
    waypointNames: waypoints,
    robots: robots,
    exported: exported,
    backendRunning: backendRunning,
    fleetReachable: fleetReachable,
    attachedRobots: attached,
    alignment: alignment,
    clockPublishers: clockPublishers,
  );

  ReadinessCheck find(ReadinessReport r, String title) =>
      r.checks.firstWhere((check) => check.title == title);

  group('다 됐을 때', () {
    test('여덟 단계가 다 초록이다', () {
      final r = report();
      expect(r.isReady, isTrue);
      expect(r.checks, hasLength(8));
      expect(r.firstBlocked, isNull);
      expect(r.summary, contains('작업을 낼 수 있습니다'));
    });
  });

  group('모른다와 안 됐다를 가른다', () {
    test('백엔드가 없으면 어댑터는 모른다이지 고장이 아니다', () {
      // 빨간불로 보여 주면 멀쩡한 어댑터를 두고 원인을 찾게 된다.
      final r = report(backendRunning: false, fleetReachable: false);
      expect(find(r, 'Open-RMF 실행').state, ReadinessState.blocked);
      expect(find(r, 'RMF↔Nav2 어댑터').state, ReadinessState.unknown);
      expect(find(r, '로봇이 RMF 에 붙음').state, ReadinessState.unknown);
    });

    test('모르는 단계가 있으면 다 됐다고 하지 않는다', () {
      final r = report(backendRunning: false, fleetReachable: false);
      expect(r.isReady, isFalse);
    });

    test('백엔드는 떴는데 토픽이 없으면 어댑터가 죽은 것이다', () {
      // /fleet_states 를 내는 것은 fleet adapter 하나뿐이다.
      final r = report(fleetReachable: false, attached: const {});
      final adapter = find(r, 'RMF↔Nav2 어댑터');
      expect(adapter.state, ReadinessState.blocked);
      expect(adapter.detail, contains('/fleet_states'));
      // RViz 가 왜 비는지도 같이 짚어 준다.
      expect(adapter.detail, contains('RViz'));
    });
  });

  group('막힌 단계', () {
    test('이름 있는 Waypoint 가 없으면 막는다', () {
      final r = report(waypoints: const ['', '   ']);
      final check = find(r, '지도와 Waypoint');
      expect(check.state, ReadinessState.blocked);
      // RMF 가 좌표가 아니라 이름을 본다는 것을 알려 준다.
      expect(check.detail, contains('이름'));
    });

    test('설비 로봇만 있으면 관제할 로봇이 없다', () {
      final r = report(robots: const [arm]);
      expect(find(r, '로봇 등록').state, ReadinessState.blocked);
    });

    test('Mock 로봇은 RMF 가 모른다', () {
      // 앱 안에서만 도는 로봇이다. 세면 등록된 줄 알고 기다리게 된다.
      final r = report(robots: const [mockRobot]);
      final check = find(r, '로봇 등록');
      expect(check.state, ReadinessState.blocked);
      expect(check.detail, contains('Mock'));
    });

    test('내보내기를 안 했으면 막는다', () {
      final r = report(exported: false);
      final check = find(r, 'RMF 설정 내보내기');
      expect(check.state, ReadinessState.blocked);
      // ros2 launch 가 파일을 읽는다는 것이 이 단계가 있는 이유다.
      expect(check.detail, contains('파일'));
    });

    test('안 붙은 로봇을 이름으로 짚어 준다', () {
      final r = report(
        robots: const [pinky, pinky2],
        attached: const {'PK_01'},
      );
      final check = find(r, '로봇이 RMF 에 붙음');
      expect(check.state, ReadinessState.blocked);
      expect(check.detail, contains('PK_02'));
      expect(check.detail, isNot(contains('PK_01')));
    });

    test('두 대 다 붙으면 통과한다', () {
      final r = report(
        robots: const [pinky, pinky2],
        attached: const {'PK_01', 'PK_02'},
      );
      expect(find(r, '로봇이 RMF 에 붙음').state, ReadinessState.ready);
      expect(r.isReady, isTrue);
    });

    test('설비 로봇은 붙기를 기다리지 않는다', () {
      // 설비는 자리를 안 옮기므로 플릿에 붙을 일이 없다. 세면 영영 안 끝난다.
      final r = report(robots: const [pinky, arm], attached: const {'PK_01'});
      expect(find(r, '로봇이 RMF 에 붙음').state, ReadinessState.ready);
    });
  });

  group('지도 정합', () {
    test('그래프가 지도 밖이면 막는다', () {
      // 어긋나면 RMF 는 `픽업1` 로 보내는데 AMCL 은 로봇이 딴 데 있다고 여긴다.
      final r = report(
        alignment: const Nav2MapAlignment(
          covered: false,
          outsideWaypoints: ['대기5', '픽업2'],
          marginMeters: -.441,
        ),
      );
      final check = find(r, '지도 정합');
      expect(check.state, ReadinessState.blocked);
      expect(check.detail, contains('픽업2'));
      // 어떻게 고치는지까지 적는다.
      expect(check.detail, contains('SLAM'));
    });

    test('아직 못 봤으면 모른다이지 고장이 아니다', () {
      final r = report(alignment: null);
      expect(find(r, '지도 정합').state, ReadinessState.unknown);
      expect(r.isReady, isFalse);
    });

    test('내보내기 전에는 볼 수 없다', () {
      // 디스크에 지도도 그래프도 없다. 어긋났다고 말할 근거가 없다.
      final r = report(exported: false, alignment: null);
      expect(find(r, '지도 정합').state, ReadinessState.unknown);
    });
  });

  group('시뮬레이션 시계', () {
    test('하나면 통과한다', () {
      expect(find(report(), '시뮬레이션 시계').state, ReadinessState.ready);
    });

    test('둘이면 막고 정리하는 법을 알려 준다', () {
      // 이전 실행에서 남은 토픽 다리다. 시각이 앞뒤로 튀어 tf2 가 버퍼를
      // 비우고 AMCL 이 위치추정을 잃는다 — 로봇은 멀쩡한데 가만히 선다.
      final check = find(report(clockPublishers: 2), '시뮬레이션 시계');
      expect(check.state, ReadinessState.blocked);
      expect(check.detail, contains('2 곳'));
      expect(check.detail, contains('parameter_bridge'));
    });

    test('없으면 Gazebo 쪽을 짚는다', () {
      final check = find(report(clockPublishers: 0), '시뮬레이션 시계');
      expect(check.state, ReadinessState.blocked);
      expect(check.detail, contains('Gazebo'));
    });

    test('백엔드가 없으면 모른다', () {
      final r = report(
        backendRunning: false,
        fleetReachable: false,
        clockPublishers: null,
      );
      expect(find(r, '시뮬레이션 시계').state, ReadinessState.unknown);
    });
  });

  group('요약 한 줄', () {
    test('처음 막힌 단계를 짚는다', () {
      // 앞이 막히면 뒤는 대개 따라 막힌다. 여섯 줄을 다 읽으라고 하지 않는다.
      final r = report(
        waypoints: const [],
        exported: false,
        backendRunning: false,
        fleetReachable: false,
      );
      expect(r.firstBlocked!.title, '지도와 Waypoint');
      expect(r.summary, startsWith('지도와 Waypoint'));
    });

    test('무엇을 하면 되는지까지 담는다', () {
      // 이유만 있으면 화면을 보고도 다음 손이 안 나간다.
      final r = report(backendRunning: false, fleetReachable: false);
      expect(r.summary, contains('프로젝트 실행'));
    });
  });
}
