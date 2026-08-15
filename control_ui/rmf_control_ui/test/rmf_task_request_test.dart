/// 앱 작업을 RMF 요청으로 옮기는 규칙.
///
/// 여기서 틀리면 RMF 가 요청을 거절하는데, 그 거절이 화면에 안 보이면 "배차는
/// 됐는데 로봇이 안 움직인다" 로만 보인다. 그래서 모양을 못으로 박아 둔다.
library;

import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/rmf_task_request.dart';

void main() {
  group('요청 모양', () {
    test('로봇을 정하면 그 로봇에게 바로 간다', () {
      // 앱의 연속 작업은 로봇을 이미 정해 두었다. 입찰에 부치면 다른 로봇이
      // 가져갈 수 있다.
      final request = buildRmfTaskRequest(
        fleetName: 'gwanghee_pinky',
        robotId: 'PK-01',
        activities: [const RmfTaskActivity.goToPlace('픽업1')],
      );
      final json = request.decoded;
      expect(json['type'], 'robot_task_request');
      expect(json['robot'], 'PK-01');
      expect(json['fleet'], 'gwanghee_pinky');
    });

    test('로봇을 안 정하면 플릿이 고른다', () {
      final request = buildRmfTaskRequest(
        fleetName: 'gwanghee_pinky',
        activities: [const RmfTaskActivity.goToPlace('픽업1')],
      );
      final json = request.decoded;
      expect(json['type'], 'dispatch_task_request');
      expect((json['request'] as Map)['fleet_name'], 'gwanghee_pinky');
      expect(request.robotId, isNull);
    });

    test('compose 의 sequence 안에 순서대로 들어간다', () {
      final request = buildRmfTaskRequest(
        fleetName: 'f',
        robotId: 'PK-01',
        activities: [
          const RmfTaskActivity.goToPlace('충전1'),
          const RmfTaskActivity.goToPlace('픽업1'),
          RmfTaskActivity.performAction('armLoad', durationSeconds: 9.6),
          const RmfTaskActivity.goToPlace('드랍오프1'),
        ],
      );
      final description =
          ((request.decoded['request'] as Map)['description'] as Map);
      final phases = description['phases'] as List;
      expect(phases, hasLength(1));
      final sequence = (phases.first as Map)['activity'] as Map;
      expect(sequence['category'], 'sequence');
      final activities = (sequence['description'] as Map)['activities'] as List;
      expect(activities.map((a) => (a as Map)['category']).toList(), [
        'go_to_place',
        'go_to_place',
        'perform_action',
        'go_to_place',
      ]);
      // 이동 목적지는 Waypoint 이름 그대로다. 좌표를 주면 RMF 가 그래프에서
      // 그 자리를 못 찾는다.
      expect((activities.first as Map)['description'], '충전1');
    });

    test('별도 동작은 걸리는 시간을 밀리초로 알린다', () {
      // RMF 는 이 동작이 무엇인지 모른다. 얼마나 걸릴지만 배차 계산에 쓴다.
      final activity = RmfTaskActivity.performAction(
        'armLoad',
        durationSeconds: 9.6,
      );
      final description = activity.description! as Map<String, Object?>;
      expect(description['unix_millis_action_duration_estimate'], 9600);
      expect(description['category'], 'armLoad');
      // 어댑터에게는 안쪽 description 만 간다. 바깥 밀리초 값은 안 닿는다.
      expect((description['description']! as Map)['seconds'], 9.6);
    });

    test('빈 작업은 만들지 않는다', () {
      // 동작이 하나도 없는 요청을 보내면 RMF 가 거절하는데, 그 거절이 화면에
      // 안 보이면 원인을 찾을 데가 없다.
      expect(
        () => buildRmfTaskRequest(fleetName: 'f', activities: const []),
        throwsArgumentError,
      );
    });

    test('보내는 문자열이 그대로 JSON 이다', () {
      final request = buildRmfTaskRequest(
        fleetName: 'f',
        activities: [const RmfTaskActivity.goToPlace('대기1')],
      );
      expect(() => jsonDecode(request.json), returnsNormally);
    });
  });

  group('앱 단계 옮기기', () {
    test('연속 작업 1 을 그대로 옮긴다', () {
      // 실제로 저장돼 있던 작업이다. 이동 9 · 적재 1.
      const steps = [
        RmfTaskStepInput(kind: 'navigate', placeName: '충전1'),
        RmfTaskStepInput(kind: 'navigate', placeName: '홈1'),
        RmfTaskStepInput(kind: 'navigate', placeName: '대기5'),
        RmfTaskStepInput(kind: 'navigate', placeName: '대기2'),
        RmfTaskStepInput(kind: 'navigate', placeName: '픽업1'),
        RmfTaskStepInput(kind: 'armLoad', durationSeconds: 9.6),
        RmfTaskStepInput(kind: 'navigate', placeName: '대기3'),
        RmfTaskStepInput(kind: 'navigate', placeName: '대기4'),
        RmfTaskStepInput(kind: 'navigate', placeName: '드랍오프1'),
        RmfTaskStepInput(kind: 'navigate', placeName: '홈1'),
      ];
      final converted = convertTaskSteps(steps);
      expect(converted.activities, hasLength(10));
      expect(converted.skipped, isEmpty);
      expect(converted.activities[5].category, 'perform_action');
      final armLoad = converted.activities[5].description! as Map;
      expect((armLoad['description'] as Map)['target_guid'], '픽업1');
    });

    test('이동 위치 없이 로봇팔 적재만 요청하지 않는다', () {
      const steps = [RmfTaskStepInput(kind: 'armLoad', durationSeconds: 4)];
      final converted = convertTaskSteps(steps);
      expect(converted.activities, isEmpty);
      expect(converted.skipped.single, contains('먼저 픽업 위치로 이동'));
    });

    test('선택한 물품 policy를 워크셀 요청 설명에 넣는다', () {
      const steps = [
        RmfTaskStepInput(kind: 'navigate', placeName: '픽업3'),
        RmfTaskStepInput(kind: 'armLoad', policyId: 'policy_4'),
      ];
      final converted = convertTaskSteps(steps);
      final action = converted.activities.last.description! as Map;
      final description = action['description'] as Map;
      expect(description['target_guid'], '픽업3');
      expect(description['item_type'], 'policy_4');
      expect(description['quantity'], 1);
    });

    test('홈 복귀는 로봇의 자리로 간다', () {
      // 홈 복귀 단계는 배정 전에는 목적지가 비어 있다.
      const steps = [RmfTaskStepInput(kind: 'returnHome')];
      final converted = convertTaskSteps(steps, homePlaceName: '충전1');
      expect(converted.activities.single.description, '충전1');
    });

    test('갈 곳이 없는 단계는 버리고 무엇을 버렸는지 남긴다', () {
      // 조용히 버리면 화면의 10단계와 실제로 도는 9단계가 어긋난다.
      const steps = [
        RmfTaskStepInput(kind: 'navigate', placeName: '픽업1'),
        RmfTaskStepInput(kind: 'navigate'),
        RmfTaskStepInput(kind: 'returnHome'),
      ];
      final converted = convertTaskSteps(steps);
      expect(converted.activities, hasLength(1));
      expect(converted.skipped, hasLength(2));
      expect(converted.skipped.first, contains('2번째'));
      expect(converted.skipped.last, contains('돌아갈 자리'));
    });

    test('모르는 단계도 버렸다고 밝힌다', () {
      const steps = [RmfTaskStepInput(kind: '청소')];
      final converted = convertTaskSteps(steps);
      expect(converted.isEmpty, isTrue);
      expect(converted.skipped.single, contains('RMF 가 모르는 단계'));
    });

    test('대기는 그 자리에서 기다리는 동작이 된다', () {
      const steps = [RmfTaskStepInput(kind: 'wait', durationSeconds: 5)];
      final converted = convertTaskSteps(steps);
      expect(converted.activities.single.category, 'wait_for');
      expect(
        (converted.activities.single.description! as Map)['duration'],
        5.0,
      );
    });
  });

  group('작업 취소 요청', () {
    test('RMF 가 아는 취소 요청을 만든다', () {
      // 넣던 그 토픽으로 취소도 간다. 작업 다리를 그대로 쓰고 JSON 만 다르다.
      final json = jsonDecode(buildCancelTaskRequest('abc-123')) as Map;
      expect(json['type'], 'cancel_task');
      expect(json['task_id'], 'abc-123');
    });

    test('앱 작업 번호가 아니라 RMF 가 준 ID 를 그대로 싣는다', () {
      // 둘을 헷갈리면 RMF 는 모르는 작업이라고 답한다.
      final json =
          jsonDecode(buildCancelTaskRequest('project1_pinky/PK_02/4')) as Map;
      expect(json['task_id'], 'project1_pinky/PK_02/4');
    });
  });
}
