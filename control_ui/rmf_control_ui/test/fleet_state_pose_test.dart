/// 앱이 그리는 로봇 위치가 RViz 와 같은 값인지 지킨다.
///
/// 앱은 `/<로봇>/odom` 을 읽어 spawn 을 더해 월드 좌표를 만들었다. 그것은 AMCL 이
/// 보정하지 않을 때만 맞다. 로봇이 미끄러지거나 복구 회전을 돌면 `map→odom` 이
/// 틀어지는데 앱은 그것을 모른다.
///
/// 실제로 이렇게 됐다 —
///
///   map → pinky_02/odom :  이동 (0.938, -0.229),  회전 -46.07°
///   RViz(/fleet_states)  :  (0.718, -0.311)
///   앱(spawn + odom)     :  약 (1.46, -1.13)
///
/// 2.3m 짜리 도면에서 1m 넘게 어긋났다. `/fleet_states` 는 RMF 가 내는 map
/// 좌표라 RViz 가 그리는 것과 같은 값이다.
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/rmf_runtime_models.dart';

void main() {
  group('실제 출력', () {
    /// 돌고 있는 시스템에서 받아 온 것.
    const real = '''
name: project1_pinky
robots:
- name: PK_01
  model: project1_pinky
  task_id: ''
  seq: 0
  mode:
    mode: 0
    mode_request_id: 0
    performing_action: ''
  battery_percent: 100.0
  location:
    t:
      sec: 18
      nanosec: 700000000
    x: 1.6117591857910156
    y: -0.7171659469604492
    yaw: 4.845038961503144e-14
    level_name: L1
    index: 0
  path: []
- name: PK_02
  model: project1_pinky
  task_id: ''
  seq: 0
  mode:
    mode: 0
    mode_request_id: 0
    performing_action: ''
  battery_percent: 100.0
  location:
    t:
      sec: 18
      nanosec: 700000000
    x: 0.7177459597587585
    y: -0.3109061121940613
    yaw: -0.1962117999792099
    level_name: L1
    index: 0
  path: []
---
''';

    test('로봇마다 map 좌표를 준다', () {
      final poses = parseFleetStatePoses(real);
      expect(poses.keys.toSet(), {'PK_01', 'PK_02'});
      expect(poses['PK_02']!.x, closeTo(0.7177, 1e-4));
      expect(poses['PK_02']!.y, closeTo(-0.3109, 1e-4));
      expect(poses['PK_02']!.yaw, closeTo(-0.1962, 1e-4));
    });

    test('시각(t) 의 sec 을 좌표로 오해하지 않는다', () {
      // location 바로 아래가 아니라 t: 안쪽이다. 들여쓰기로 갈라야 한다.
      final poses = parseFleetStatePoses(real);
      expect(poses['PK_01']!.x, closeTo(1.6118, 1e-4));
      expect(poses['PK_01']!.x, isNot(closeTo(18, 1)));
    });
  });

  group('가려는 곳을 위치로 그리지 않는다', () {
    test('path 안의 좌표는 무시한다', () {
      // 주행 중에는 path 가 채워진다. 그것을 세면 로봇이 아직 안 간 자리에
      // 그려진다 — 화면에서는 로봇이 순간이동한 것으로 보인다.
      const moving = '''
name: project1_pinky
robots:
- name: PK_02
  battery_percent: 100.0
  location:
    t:
      sec: 30
      nanosec: 0
    x: 0.5
    y: -0.5
    yaw: 0.0
    level_name: L1
    index: 0
  path:
  - t:
      sec: 40
      nanosec: 0
    x: 9.9
    y: -9.9
    yaw: 1.5
    level_name: L1
    index: 0
---
''';
      final poses = parseFleetStatePoses(moving);
      expect(poses, hasLength(1));
      expect(poses['PK_02']!.x, 0.5);
      expect(poses['PK_02']!.y, -0.5);
    });
  });

  group('덜 온 것', () {
    test('빈 목록이면 아무것도 안 준다', () {
      expect(parseFleetStatePoses('name: f\nrobots: []\n---\n'), isEmpty);
    });

    test('좌표가 없는 항목은 건너뛴다', () {
      // 자리를 모르는 로봇을 (0,0) 으로 그리면 지도 원점에 유령이 선다.
      const partial = '''
robots:
- name: PK_01
  battery_percent: 100.0
---
''';
      expect(parseFleetStatePoses(partial), isEmpty);
    });
  });
}
