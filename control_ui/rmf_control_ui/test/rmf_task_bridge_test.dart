/// 앱과 RMF 사이를 오가는 값 읽기.
///
/// RMF 가 작업을 거절해도 그 사유가 화면에 안 닿으면 "배차는 됐는데 로봇이
/// 안 움직인다" 로만 보인다. 실제로 그렇게 하루를 썼다.
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/rmf_task_models.dart';

void main() {
  group('RMF 의 답 읽기', () {
    test('받았으면 작업 번호와 맡은 로봇을 꺼낸다', () {
      // 실제로 돌아온 답이다.
      const answer =
          '{"state": {"assigned_to": {"group": "gwanghee_pinky", '
          '"name": "PK-01"}, "booking": {"id": "rmf_control_ui-373396bb"}, '
          '"status": "queued"}, "success": true}';
      final result = RmfTaskSubmission.parse(answer);
      expect(result.accepted, isTrue);
      expect(result.taskId, 'rmf_control_ui-373396bb');
      expect(result.assignedRobot, 'PK-01');
    });

    test('거절 사유를 그대로 전한다', () {
      // 플릿 설정 actions 에 armLoad 를 안 넣어 실제로 받은 답이다. 사유가
      // 없으면 무엇을 고쳐야 하는지 알 수 없다.
      const answer =
          '{"errors": [{"category": "unknown", "code": 42, "detail": '
          '"Fleet not configured to perform this action"}], "success": false}';
      final result = RmfTaskSubmission.parse(answer);
      expect(result.accepted, isFalse);
      expect(result.message, contains('Fleet not configured'));
    });

    test('JSON 이 아닌 것이 와도 그 말을 그대로 보여 준다', () {
      final result = RmfTaskSubmission.parse(
        'ModuleNotFoundError: No module named \'rmf_task_msgs\'',
      );
      expect(result.accepted, isFalse);
      expect(result.message, contains('rmf_task_msgs'));
    });

    test('아무 말도 없으면 그렇다고 밝힌다', () {
      final result = RmfTaskSubmission.parse('   ');
      expect(result.accepted, isFalse);
      expect(result.message, contains('아무 답도'));
    });

    test('앞에 다른 줄이 있어도 마지막 JSON 을 읽는다', () {
      // ROS 환경을 읽을 때 경고가 먼저 나오는 일이 있다.
      const answer = '[WARN] something\n{"success": true, "state": {}}';
      expect(RmfTaskSubmission.parse(answer).accepted, isTrue);
    });
  });

  group('진행 소식 읽기', () {
    test('어디로 가라고 했는지 읽는다', () {
      final event = RmfTaskProgress.parse(
        '{"robot": "PK-01", "event": "navigate_start", '
        '"x": 1.7607, "y": -0.6376, "yaw": -1.0087}',
      );
      expect(event, isNotNull);
      expect(event!.robotId, 'PK-01');
      expect(event.isStart, isTrue);
      expect(event.x, closeTo(1.7607, 1e-6));
      expect(event.y, closeTo(-0.6376, 1e-6));
    });

    test('도착과 동작 끝을 같은 것으로 본다', () {
      final arrived = RmfTaskProgress.parse(
        '{"robot": "PK-01", "event": "navigate_done"}',
      );
      final acted = RmfTaskProgress.parse(
        '{"robot": "PK-01", "event": "action_done", "category": "armLoad"}',
      );
      expect(arrived!.isArrival, isTrue);
      expect(acted!.isArrival, isTrue);
      expect(acted.category, 'armLoad');
    });

    test('토픽 사이에 섞여 오는 구분선은 버린다', () {
      // `ros2 topic echo` 는 소식 사이에 `---` 를 낸다.
      expect(RmfTaskProgress.parse('---'), isNull);
      expect(RmfTaskProgress.parse(''), isNull);
    });

    test('로봇이나 사건이 빠진 것은 안 읽는다', () {
      expect(RmfTaskProgress.parse('{"event": "navigate_done"}'), isNull);
      expect(RmfTaskProgress.parse('{"robot": "PK-01"}'), isNull);
    });
  });
}
