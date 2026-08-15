/// RMF↔Nav2 어댑터가 죽으면 다시 띄우는지 지킨다.
///
/// 이 어댑터는 로봇을 움직이는 일만 하는 것이 아니다. RMF 안에서
/// `/nav_graphs`(경로 Lane·Waypoint)와 `/fleet_states`(로봇)를 내는 것이
/// **FleetUpdateHandle 하나뿐**이라, 이것이 죽으면 RViz 는 도면만 남고 텅 빈다.
///
/// 실제로 이렇게 됐다. Nav2 20여 개 노드와 같이 뜨는 중에 어댑터가
/// `add_easy_fleet` 안에서 SIGSEGV(-11) 로 죽었다 —
///
///   [ERROR] [python3-21]: process has died [pid 229066, exit code -11]
///
/// Gazebo·Nav2·RMF core 는 그대로 살아 있어 토픽은 계속 왔고, 화면에는 오류가
/// 한 줄도 안 났다. 한가할 때 같은 명령을 손으로 돌리니 멀쩡히 떴다 — 부하가
/// 걸린 순간에만 나는 rmf_adapter 쪽 경합이라 우리가 고칠 수 없다.
library;

import 'package:flutter_test/flutter_test.dart';
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

  String nav2Launch() => buildProjectNav2LaunchXml(
    mapName: 'project1',
    robots: const [pinky],
    fleetName: 'project1_pinky',
  );

  /// 어댑터를 띄우는 `<executable>` 한 덩어리만 떼어 본다. 파일 전체에서 찾으면
  /// 옆에 있는 센서 릴레이의 속성에 걸린다.
  String adapterBlock(String xml) {
    final cmd = xml.indexOf('nav2_adapter.py');
    expect(cmd, greaterThan(-1), reason: '어댑터를 띄우는 곳이 없다');
    final open = xml.lastIndexOf('<executable', cmd);
    final close = xml.indexOf('/>', cmd);
    return xml.substring(open, close);
  }

  group('어댑터가 죽으면 다시 띄운다', () {
    test('respawn 을 켠다', () {
      final block = adapterBlock(nav2Launch());
      expect(block, contains('respawn="true"'));
    });

    test('바로 다시 띄우지 않는다', () {
      // 죽자마자 다시 띄우면 같은 부하 속에서 같은 자리를 또 밟는다.
      final block = adapterBlock(nav2Launch());
      final delay = RegExp(r'respawn_delay="([\d.]+)"').firstMatch(block);
      expect(delay, isNotNull, reason: 'respawn_delay 가 없다');
      expect(double.parse(delay!.group(1)!), greaterThanOrEqualTo(1.0));
    });

    test('무한히 되살리지는 않는다', () {
      // 설정이 잘못돼 늘 죽는 경우, 끝없이 되살리면 로그가 같은 역추적으로
      // 덮여 진짜 원인이 묻힌다.
      final block = adapterBlock(nav2Launch());
      final retries = RegExp(
        r'respawn_max_retries="(-?\d+)"',
      ).firstMatch(block);
      expect(retries, isNotNull, reason: 'respawn_max_retries 가 없다');
      final value = int.parse(retries!.group(1)!);
      expect(value, greaterThan(0));
    });

    test('센서 릴레이가 아니라 어댑터에 붙였다', () {
      final block = adapterBlock(nav2Launch());
      expect(block, contains('nav2_adapter.py'));
      expect(block, isNot(contains('sensor_relay')));
    });
  });

  group('실행 스크립트의 감시', () {
    // 감시자가 사라진 그 순간에 죽었다고 알리면, 5초 뒤 살아난 것을 두고 사람을
    // 뛰게 만든다.
    final script = buildProjectRunScript(
      mapName: 'project1',
      mapDirectory: '/maps/project1',
      robots: const [pinky],
      rosDomainId: 22,
    );

    test('다시 뜨기를 기다린다', () {
      expect(script, contains('ADAPTER_RESPAWN_WAIT'));
      expect(script, contains('죽었다가 다시 떴습니다'));
    });

    test('정말 안 돌아올 때만 알린다', () {
      expect(script, contains('다시 뜨지도 않았습니다'));
    });

    test('RViz 가 왜 비는지 알려 준다', () {
      // 어댑터가 죽었을 때 눈에 먼저 띄는 것이 빈 RViz 다. 그 둘을 이어 준다.
      expect(script, contains('/nav_graphs'));
      expect(script, contains('/fleet_states'));
    });
  });
}
