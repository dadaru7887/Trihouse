import 'dart:ui' show Offset;

import 'enums.dart';

/// 로봇 한 대의 실시간 상태.
///
/// 이 객체가 그대로 "로봇 간 상태 공유" 메시지의 페이로드에 해당한다.
/// 작업 여부뿐 아니라 현재 태스크 ID와 진행률, 경로, 점유 자원까지 포함한다.
class Robot {
  Robot({
    required this.id,
    required this.name,
    required this.model,
    required this.pos,
    required this.homeChargerId,
    required this.zoneRating,
    this.battery = 100,
    this.state = RobotState.idle,
    this.reserve = false,
  });

  final String id;
  final String name;
  final String model;

  /// 이 로봇이 진입 가능한 온도 구획(냉동 대응 여부 등).
  final Set<TempZone> zoneRating;

  final String homeChargerId;

  Offset pos;
  double heading = 0;
  double battery;
  RobotState state;

  /// 예비기(단계적 투입 대기) 여부.
  bool reserve;

  /// 절전 모드 진입 여부(배터리 20% 이하).
  bool powerSaving = false;

  /// 현재 수행 중인 태스크 ID.
  String? taskId;

  /// 현재 태스크 진행률 0~1. 다른 로봇/관제에 공유된다.
  double taskProgress = 0;

  /// 현재 스텝 설명(예: "A-02-07로 이동").
  String? activity;

  /// 남은 주행 경로(웨이포인트).
  List<Offset> path = <Offset>[];
  String? destinationLabel;

  /// 최근 주행 궤적(이력 관리용, 최대 200점).
  final List<Offset> trace = <Offset>[];

  double speed = 0;
  double odometer = 0;
  double workingSeconds = 0;
  double idleSeconds = 0;

  int completedTasks = 0;
  int failedTasks = 0;
  int handovers = 0;
  int safetyStops = 0;

  /// 적재 중인 화물 표기.
  String? payload;

  /// 점유 중인 랙/도크 자원 ID(중복 점유 방지).
  String? reservedResourceId;

  /// 비전 측위 신뢰도. 조도·결빙에 따라 변동한다.
  double localizationConfidence = 0.98;

  /// 안전 필드 상태 메모(예: "작업자 근접 감속").
  String? safetyNote;

  DateTime? lastFaultAt;
  String? lastFault;

  bool get isAvailable =>
      !reserve &&
      taskId == null &&
      !powerSaving &&
      (state == RobotState.idle || state == RobotState.standby) &&
      battery > 22;

  bool get isOperational =>
      state != RobotState.estop &&
      state != RobotState.error &&
      state != RobotState.standby;

  void pushTrace(Offset p) {
    if (trace.isNotEmpty && (trace.last - p).distance < 1.2) return;
    trace.add(p);
    if (trace.length > 200) trace.removeAt(0);
  }
}
