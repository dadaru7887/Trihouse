/// `/fleet_states` 출력에서 로봇 이름을 뽑는 것을 지킨다.
///
/// 이 토픽을 내는 것은 fleet adapter 하나뿐이라, 한 번 읽으면 두 가지를 함께
/// 안다 — 어댑터가 살아 있는가, 어느 로봇이 실제로 붙었는가.
///
/// 함정은 `name` 이 한 항목 안에서 여러 번 나온다는 것이다. 그냥 세면 모델
/// 이름이나 작업 번호까지 로봇으로 잡힌다.
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/rmf_runtime_models.dart';

void main() {
  /// 돌고 있는 시스템에서 그대로 받아 온 것.
  ///
  /// 지어낸 예제로만 시험했더니 **명령 자체가 틀린 것**을 못 잡았다. 앱은
  /// `--field robots` 로 불렀는데 ros2 는 그때 YAML 이 아니라 파이썬 repr 을
  /// 뱉는다. 그래서 로봇 두 대가 멀쩡히 붙어 있는데도 화면은 계속 "안 붙었다"
  /// 였다.
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
    x: 1.6132757663726807
    y: -1.0877513885498047
    yaw: -7.259634516795788e-13
    level_name: L1
    index: 0
  path: []
---
''';

  group('실제 출력', () {
    test('붙은 로봇 두 대를 찾는다', () {
      expect(parseFleetStateRobots(real), {'PK_01', 'PK_02'});
    });

    test('플릿 이름을 로봇으로 세지 않는다', () {
      // 맨 윗줄 `name: project1_pinky` 는 플릿이다. 세면 없는 로봇이 생긴다.
      expect(parseFleetStateRobots(real), isNot(contains('project1_pinky')));
    });

    test('level_name 을 이름으로 세지 않는다', () {
      expect(parseFleetStateRobots(real), isNot(contains('L1')));
    });
  });

  group('로봇 이름만 뽑는다', () {
    test('목록 항목의 첫 줄만 센다', () {
      const output = '''
robots:
- name: PK_01
  model: pinky
  task_id: ''
  location:
    level_name: L1
- name: PK_02
  model: pinky
  task_id: ''
''';
      expect(parseFleetStateRobots(output), {'PK_01', 'PK_02'});
    });

    test('따옴표를 벗긴다', () {
      // ros2 topic echo 는 값에 따라 따옴표를 붙였다 뗐다 한다.
      const output = "robots:\n- name: 'PK_01'\n- name: \"PK_02\"\n";
      expect(parseFleetStateRobots(output), {'PK_01', 'PK_02'});
    });

    test('들여쓴 name 은 로봇이 아니다', () {
      // 항목 안쪽의 다른 name 을 세면 없는 로봇이 붙은 것으로 보인다.
      const output = '''
robots:
- name: PK_01
  model: pinky
  dock:
    name: charger_dock
''';
      expect(parseFleetStateRobots(output), {'PK_01'});
    });

    test('빈 출력이면 빈 목록이다', () {
      expect(parseFleetStateRobots(''), isEmpty);
      expect(
        parseFleetStateRobots('name: project1_pinky\nrobots: []\n'),
        isEmpty,
      );
    });

    test('같은 로봇이 여러 번 나와도 한 번만 센다', () {
      expect(parseFleetStateRobots('robots:\n- name: PK_01\n- name: PK_01\n'), {
        'PK_01',
      });
    });
  });
}
