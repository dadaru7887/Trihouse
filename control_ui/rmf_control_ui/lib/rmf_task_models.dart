/// 앱과 RMF 사이를 오가는 값들.
///
/// `dart:io` 를 쓰지 않는다. 웹 빌드와 테스트가 이 파일만 읽으면 되도록.
library;

import 'dart:convert';

/// RMF 가 작업을 받았는지, 못 받았으면 왜인지.
class RmfTaskSubmission {
  const RmfTaskSubmission({
    required this.accepted,
    required this.message,
    this.taskId,
    this.assignedRobot,
  });

  final bool accepted;

  /// 사람이 읽을 한 줄. 거절당했을 때 RMF 가 준 사유가 그대로 들어간다.
  final String message;

  /// RMF 가 붙인 작업 번호. 앱의 작업 번호와 다르다.
  final String? taskId;
  final String? assignedRobot;

  /// `<맵>_task_bridge.py` 가 찍은 JSON 한 줄을 읽는다.
  factory RmfTaskSubmission.parse(String output) {
    final line = output
        .split('\n')
        .map((text) => text.trim())
        .lastWhere((text) => text.startsWith('{'), orElse: () => '');
    if (line.isEmpty) {
      return RmfTaskSubmission(
        accepted: false,
        message: output.trim().isEmpty
            ? 'RMF 가 아무 답도 하지 않았습니다.'
            : output.trim(),
      );
    }
    Map<String, Object?> body;
    try {
      body = jsonDecode(line) as Map<String, Object?>;
    } catch (_) {
      return RmfTaskSubmission(accepted: false, message: line);
    }
    if (body['success'] == true) {
      final state = body['state'] as Map<String, Object?>?;
      final booking = state?['booking'] as Map<String, Object?>?;
      final assigned = state?['assigned_to'] as Map<String, Object?>?;
      return RmfTaskSubmission(
        accepted: true,
        message: 'RMF 가 받았습니다.',
        taskId: booking?['id'] as String?,
        assignedRobot: assigned?['name'] as String?,
      );
    }
    final errors = (body['errors'] as List?) ?? const [];
    final details = [
      for (final error in errors)
        if (error is Map && error['detail'] != null) '${error['detail']}',
    ];
    return RmfTaskSubmission(
      accepted: false,
      message: details.isEmpty ? 'RMF 가 거절했습니다.' : details.join(' · '),
    );
  }
}

/// 어댑터가 낸 진행 소식 하나.
class RmfTaskProgress {
  const RmfTaskProgress({
    required this.robotId,
    required this.event,
    this.x,
    this.y,
    this.category,
    this.seconds,
  });

  final String robotId;

  /// `navigate_start` · `navigate_done` · `action_start` · `action_done`.
  final String event;

  /// 이동 소식이면 RMF 월드 좌표의 목적지.
  final double? x;
  final double? y;

  /// 동작 소식이면 그 이름.
  final String? category;
  final double? seconds;

  bool get isArrival => event == 'navigate_done' || event == 'action_done';
  bool get isStart => event == 'navigate_start' || event == 'action_start';

  static RmfTaskProgress? parse(String line) {
    final text = line.trim();
    if (!text.startsWith('{')) return null;
    try {
      final body = jsonDecode(text) as Map<String, Object?>;
      final robot = body['robot'] as String?;
      final event = body['event'] as String?;
      if (robot == null || event == null) return null;
      return RmfTaskProgress(
        robotId: robot,
        event: event,
        x: (body['x'] as num?)?.toDouble(),
        y: (body['y'] as num?)?.toDouble(),
        category: body['category'] as String?,
        seconds: (body['seconds'] as num?)?.toDouble(),
      );
    } catch (_) {
      return null;
    }
  }
}
