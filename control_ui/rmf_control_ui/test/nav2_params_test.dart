/// 벤더 Nav2 파라미터를 로봇 한 대에 맞춰 다시 쓰는 규칙.
///
/// 두 대를 같은 월드에 올리면 서로의 라이다를 보고 TF 가 충돌한다. 무엇을
/// 가르고 무엇을 함께 쓰는지가 이 파일에 못 박혀 있다.
library;

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/nav2_params.dart';

void main() {
  // pinky_navigation/params/nav2_params.yaml 에서 그대로 따온 조각.
  const vendor = '''
amcl:
  ros__parameters:
    base_frame_id: "base_footprint"
    global_frame_id: "map"
    odom_frame_id: "odom"
    scan_topic: scan
    set_initial_pose: true
    initial_pose: [0, 0, 0]

bt_navigator:
  ros__parameters:
    global_frame: map
    robot_base_frame: base_link
    odom_topic: odom

controller_server:
  ros__parameters:
    speed_limit_topic: "speed_limit"             # 속도 제한 구역
    odom_topic: "odom"                           # 현재 속도를 읽어올 토픽

local_costmap:
  local_costmap:
    ros__parameters:
      global_frame: odom
      robot_base_frame: base_footprint
      observation_sources: scan
      scan:
        topic: /scan

global_costmap:
  global_costmap:
    ros__parameters:
      global_frame: map
      robot_base_frame: base_footprint
      scan:
        topic: /scan

behavior_server:
  ros__parameters:
    local_costmap_topic: local_costmap/costmap_raw
    local_frame: odom
    global_frame: map
    robot_base_frame: base_footprint
''';

  Nav2ParamsRewrite rewrite({
    String source = vendor,
    String namespace = 'pinky_01',
    double? x = 1.7607,
    double? y = -0.6376,
    double? yaw = 0,
  }) => rewriteNav2Params(
    source: source,
    namespace: namespace,
    initialX: x,
    initialY: y,
    initialYaw: yaw,
  );

  group('노드 이름', () {
    test('맨 위 칸에 네임스페이스를 붙인다', () {
      // `amcl:` 은 `/amcl` 을 뜻한다. 그대로 두면 `/pinky_01/amcl` 에는 하나도
      // 안 붙고 조용히 기본값으로 돈다.
      final result = rewrite();
      expect(result.yaml, contains('/pinky_01/amcl:'));
      expect(result.yaml, contains('/pinky_01/bt_navigator:'));
      expect(result.yaml, contains('/pinky_01/controller_server:'));
      expect(result.yaml, isNot(contains('\namcl:')));
    });

    test('costmap 의 안쪽 칸은 건드리지 않는다', () {
      // 노드 이름이 /pinky_01/local_costmap/local_costmap 이라 바깥 칸만 바꾼다.
      final result = rewrite();
      expect(result.yaml, contains('/pinky_01/local_costmap:'));
      expect(result.yaml, contains('\n  local_costmap:'));
    });
  });

  group('가르는 것', () {
    test('로봇의 TF 프레임을 가른다', () {
      final yaml = rewrite().yaml;
      expect(yaml, contains('base_frame_id: "pinky_01/base_footprint"'));
      expect(yaml, contains('odom_frame_id: "pinky_01/odom"'));
      expect(yaml, contains('robot_base_frame: pinky_01/base_link'));
      expect(yaml, contains('robot_base_frame: pinky_01/base_footprint'));
      expect(yaml, contains('local_frame: pinky_01/odom'));
    });

    test('local costmap 의 global_frame 은 odom 이라 가른다', () {
      expect(rewrite().yaml, contains('global_frame: pinky_01/odom'));
    });

    test('라이다·오도메트리 토픽을 가른다', () {
      final yaml = rewrite().yaml;
      expect(yaml, contains('scan_topic: /pinky_01/scan'));
      expect(yaml, contains('topic: /pinky_01/scan'));
      expect(yaml, contains('odom_topic: /pinky_01/odom'));
      expect(yaml, contains('odom_topic: "/pinky_01/odom"'));
      expect(yaml, contains('speed_limit_topic: "/pinky_01/speed_limit"'));
      // 절대 이름 /scan 이 하나도 안 남아야 한다. 남으면 두 대가 같은 라이다를
      // 본다.
      expect(yaml, isNot(contains('topic: /scan')));
    });
  });

  group('함께 쓰는 것', () {
    test('map 프레임은 가르지 않는다 — 같은 건물이다', () {
      final yaml = rewrite().yaml;
      expect(yaml, contains('global_frame_id: "map"'));
      expect(yaml, contains('global_frame: map'));
      expect(yaml, isNot(contains('pinky_01/map')));
    });

    test('costmap 안쪽 토픽은 상대 이름 그대로 둔다', () {
      // behavior_server 가 제 네임스페이스에서 풀므로 이미 맞다.
      expect(
        rewrite().yaml,
        contains('local_costmap_topic: local_costmap/costmap_raw'),
      );
    });
  });

  group('AMCL 이 처음 찍는 자리', () {
    test('벤더의 리스트 모양을 제대로 된 모양으로 고친다', () {
      // AMCL 은 initial_pose.x/.y/.z/.yaw 로 선언한다. 벤더가 적은
      // `initial_pose: [0, 0, 0]` 은 맞는 이름이 없어 조용히 버려진다.
      final result = rewrite();
      expect(result.yaml, isNot(contains('initial_pose: [0, 0, 0]')));
      expect(result.yaml, contains('    initial_pose:'));
      expect(result.yaml, contains('      x: 1.760700'));
      expect(result.yaml, contains('      y: -0.637600'));
      expect(result.yaml, contains('      z: 0.0'));
      expect(result.yaml, contains('      yaw: 0.000000'));
      expect(result.changes.any((change) => change.contains('버려집니다')), isTrue);
    });

    test('자리를 모르면 손대지 않고 경고한다', () {
      final result = rewrite(x: null, y: null);
      expect(result.yaml, contains('initial_pose: [0, 0, 0]'));
      expect(result.warnings.any((w) => w.contains('원점에서 시작')), isTrue);
    });
  });

  group('벤더 파일이 바뀌면', () {
    test('손대지 못한 절대 이름을 경고한다', () {
      const changed = '''
some_server:
  ros__parameters:
    mystery_input: /camera/points
''';
      final result = rewrite(source: changed);
      expect(result.clean, isFalse);
      expect(
        result.warnings.single,
        contains('`mystery_input: /camera/points` 는 손대지 않았습니다'),
      );
    });

    test('월드에 하나뿐인 토픽은 경고하지 않는다', () {
      const shared = '''
some_server:
  ros__parameters:
    map_topic: /map
    clock_input: /clock
''';
      expect(rewrite(source: shared).clean, isTrue);
    });

    test('벤더가 맞춰 둔 값과 주석을 살린다', () {
      final yaml = rewrite().yaml;
      expect(yaml, contains('# 속도 제한 구역'));
      expect(yaml, contains('# 현재 속도를 읽어올 토픽'));
      expect(yaml, contains('set_initial_pose: true'));
      expect(yaml, contains('observation_sources: scan'));
    });
  });

  group('무엇을 바꿨는지 알린다', () {
    test('바꾼 것을 사람이 읽을 수 있게 남긴다', () {
      final changes = rewrite().changes;
      expect(changes, contains('amcl → /pinky_01/amcl'));
      expect(changes, contains('scan_topic: scan → /pinky_01/scan'));
      expect(changes.any((c) => c.contains('map — 함께 씁니다')), isTrue);
    });
  });

  group('두 대가 겹치지 않는다', () {
    test('로봇이 다르면 같은 이름이 하나도 없다', () {
      final one = rewrite(namespace: 'pinky_01').yaml;
      final two = rewrite(namespace: 'pinky_02').yaml;
      // 갈라야 하는 것은 전부 달라야 한다.
      for (final name in [
        'base_frame_id: "pinky_01/base_footprint"',
        'odom_frame_id: "pinky_01/odom"',
        'scan_topic: /pinky_01/scan',
        '/pinky_01/amcl:',
      ]) {
        expect(one, contains(name));
        expect(two, isNot(contains(name)));
      }
      // 함께 쓰는 것은 둘 다 같아야 한다.
      expect(one, contains('global_frame_id: "map"'));
      expect(two, contains('global_frame_id: "map"'));
    });
  });

  group('도착 인정 반경', () {
    test('벤더 값은 이 맵에 안 맞는다', () {
      // 벤더 0.25m 는 사람 다니는 복도를 전제한 값이다. 이 맵은 레인 최소
      // 간격이 0.331m 라, 도착 원이 이웃 Waypoint 까지 거리의 76% 다.
      expect(vendorGoalTolerance, 0.25);
    });

    test('레인 간격의 4분의 1로 잡는다', () {
      // 4분의 1이면 옆 Waypoint 의 도착 원과 겹치지 않는다.
      expect(recommendedGoalTolerance(minLaneSpacing: 2.0), 0.25);
      expect(recommendedGoalTolerance(minLaneSpacing: 0.8), closeTo(0.2, 1e-9));
    });

    test('코스트맵 두 칸보다 작게는 안 잡는다', () {
      // 한 칸이 0.05m 다. 그보다 촘촘히 요구하면 도착을 못 하고 맴돈다.
      expect(minimumGoalTolerance(), closeTo(0.1, 1e-9));
      expect(
        recommendedGoalTolerance(minLaneSpacing: 0.331),
        closeTo(0.1, 1e-9),
      );
    });

    test('간격을 모르면 벤더 값을 그대로 둔다', () {
      // 함부로 조이면 도착을 못 한다. 모르면 손대지 않는다.
      expect(recommendedGoalTolerance(minLaneSpacing: null), 0.25);
      expect(recommendedGoalTolerance(minLaneSpacing: 0), 0.25);
    });

    test('넘겨준 값으로 파일을 다시 쓴다', () {
      const source = '''
/controller_server:
  ros__parameters:
    general_goal_checker:
      xy_goal_tolerance: 0.25
      yaw_goal_tolerance: 0.25
''';
      final result = rewriteNav2Params(
        source: source,
        namespace: 'pinky_01',
        goalTolerance: 0.1,
      );
      expect(result.yaml, contains('xy_goal_tolerance: 0.100'));
      // 각도는 건드리지 않는다. 물어본 것만 고친다.
      expect(result.yaml, contains('yaw_goal_tolerance: 0.25'));
      expect(
        result.changes.any(
          (c) => c.contains('xy_goal_tolerance: 0.25 → 0.100'),
        ),
        isTrue,
      );
    });

    test('안 넘기면 그대로 둔다', () {
      const source = '''
/controller_server:
  ros__parameters:
    general_goal_checker:
      xy_goal_tolerance: 0.25
''';
      final result = rewriteNav2Params(source: source, namespace: 'pinky_01');
      expect(result.yaml, contains('xy_goal_tolerance: 0.25'));
    });
  });

  group('최소보다 작게 넣을 때', () {
    test('입력 중에 무엇이 일어나는지 알린다', () {
      final source = File('lib/main.dart').readAsStringSync();
      expect(source, contains('주변을 맴돌다 포기합니다'));
      // 겪은 일을 그대로 적어 둔다. 숫자가 있어야 남 얘기로 안 읽힌다.
      expect(source, contains('실제로 0.080 을 넣었다가'));
    });

    test('저장할 때 한 번 더 묻는다', () {
      // 입력 중에만 알리면 그냥 지나치기 쉽다. 실제로 0.080 이 저장돼 나갔다.
      final source = File('lib/main.dart').readAsStringSync();
      expect(source, contains('그래도 쓰시려면 한 번 더 누르세요'));
      expect(source, contains('if (toleranceForced != tolerance)'));
      // 값을 고치면 되묻기를 처음부터 다시 한다.
      expect(source, contains('toleranceForced = null;'));
    });
  });
}
