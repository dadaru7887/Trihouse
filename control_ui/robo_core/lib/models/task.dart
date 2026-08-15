import 'dart:math' as math;
import 'dart:ui' show Offset;

import 'enums.dart';

/// 태스크 세부 단계 종류.
enum StepKind {
  move('이동'),
  pick('집품'),
  place('하역'),
  scan('검수'),
  handover('인계'),

  /// 구획 적재 스테이션의 로봇팔이 로봇에 화물을 실어 주는 스텝.
  load('적재'),
  wait('대기');

  const StepKind(this.label);

  final String label;
}

/// 태스크를 구성하는 단일 스텝.
class TaskStep {
  TaskStep({
    required this.kind,
    required this.label,
    required this.target,
    required this.duration,
    this.resourceId,
  });

  final StepKind kind;
  final String label;
  final Offset target;

  /// 스텝 수행 소요 시간(초, 시뮬레이션 시간 기준).
  final double duration;

  /// 이 스텝이 점유해야 하는 자원(랙 슬롯·도크) ID.
  final String? resourceId;

  double elapsed = 0;

  double get progress =>
      duration <= 0 ? 1 : (elapsed / duration).clamp(0.0, 1.0);
}

/// 작업 단위. 주문·작업자 요청·안전 조치 모두 태스크로 표현된다.
class WorkTask {
  WorkTask({
    required this.id,
    required this.type,
    required this.title,
    required this.urgency,
    required this.zone,
    required this.steps,
    required this.createdAt,
    required this.originLabel,
    required this.destLabel,
    this.orderId,
    this.sku,
    this.lotId,
    this.expiry,
    this.qty = 1,
    this.requestedBy,
  });

  final String id;
  final TaskType type;
  final String title;
  final Urgency urgency;
  final TempZone zone;
  final List<TaskStep> steps;
  final DateTime createdAt;
  final String originLabel;
  final String destLabel;

  final String? orderId;
  final String? sku;
  final String? lotId;

  /// FEFO 판단 기준이 되는 유통기한.
  final DateTime? expiry;
  final int qty;

  /// 작업자 요청 태스크의 요청자.
  final String? requestedBy;

  TaskState state = TaskState.pending;
  String? robotId;
  int stepIndex = 0;
  int retries = 0;
  String? failReason;
  DateTime? assignedAt;
  DateTime? startedAt;
  DateTime? endedAt;

  /// 스케줄러가 마지막으로 계산한 우선순위 점수(관제 화면 노출용).
  double score = 0;

  bool get isTerminal =>
      state == TaskState.done ||
      state == TaskState.failed ||
      state == TaskState.cancelled;

  TaskStep? get currentStep =>
      stepIndex < steps.length ? steps[stepIndex] : null;

  double get progress {
    if (steps.isEmpty) return 0;
    if (state == TaskState.done) return 1;
    final i = math.min(stepIndex, steps.length - 1);
    return ((i + steps[i].progress) / steps.length).clamp(0.0, 1.0);
  }

  Duration? get cycleTime => (startedAt != null && endedAt != null)
      ? endedAt!.difference(startedAt!)
      : null;
}

/// 출고 주문.
class SalesOrder {
  SalesOrder({
    required this.id,
    required this.customer,
    required this.urgency,
    required this.createdAt,
    required this.dueAt,
    required this.lineCount,
  });

  final String id;
  final String customer;
  final Urgency urgency;
  final DateTime createdAt;
  final DateTime dueAt;
  final int lineCount;

  final List<String> taskIds = <String>[];
  OrderState state = OrderState.open;
  int doneLines = 0;
  int failedLines = 0;
  DateTime? closedAt;

  bool get onTime => closedAt != null && !closedAt!.isAfter(dueAt);
}
