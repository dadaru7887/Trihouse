import 'dart:ui' show Offset;

import 'enums.dart';

/// 운행 이력 한 줄. 주행·작업·오류·안전 이벤트를 모두 담는다.
class OpsEvent {
  OpsEvent({
    required this.id,
    required this.at,
    required this.severity,
    required this.category,
    required this.source,
    required this.message,
    this.taskId,
    this.orderId,
  });

  final String id;
  final DateTime at;
  final Severity severity;

  /// 분류: 주행 / 작업 / 배터리 / 안전 / 스케줄 / 시스템.
  final String category;

  /// 발생 주체(로봇 ID, SAFETY, SCHED 등).
  final String source;
  final String message;
  final String? taskId;
  final String? orderId;
}

/// 안전 상황 레코드.
class Incident {
  Incident({
    required this.id,
    required this.type,
    required this.at,
    required this.description,
    this.zone,
    this.pos,
    this.radius = 0,
  });

  final String id;
  final IncidentType type;
  final DateTime at;
  final String description;

  /// 구획 단위 상황(정전 등).
  final TempZone? zone;

  /// 지점 단위 상황(작업자 위급 등).
  final Offset? pos;
  final double radius;

  bool active = true;
  DateTime? clearedAt;

  /// 자동 실행된 대응 조치 목록.
  final List<String> actions = <String>[];
}
