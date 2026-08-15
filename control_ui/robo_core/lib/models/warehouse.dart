import 'dart:ui' show Offset;

import 'enums.dart';

/// 랙 슬롯 하나.
class StorageLocation {
  StorageLocation({
    required this.id,
    required this.pos,
    required this.zone,
    required this.row,
  });

  final String id;
  final Offset pos;
  final TempZone zone;
  final int row;
}

/// 고정 설비 종류.
enum StationKind {
  inboundDock('입고 도크'),
  outboundDock('출고 도크'),
  charger('충전소'),
  workstation('작업 스테이션'),

  /// 구획별 적재 스테이션. 로봇팔이 로봇에 화물을 실어 주는 자리다.
  loading('적재 스테이션'),
  standby('대기 구역'),
  assembly('비상 집결지');

  const StationKind(this.label);

  final String label;
}

/// 도크·충전소·작업 스테이션 등 고정 설비.
class Station {
  Station({
    required this.id,
    required this.kind,
    required this.pos,
    required this.zone,
  });

  final String id;
  final StationKind kind;
  final Offset pos;
  final TempZone zone;

  /// 점유 중인 로봇 ID. 동시 점유를 막는 자원 잠금 역할.
  String? occupiedBy;
}

/// 현장 작업자. 로봇은 작업자 주변에서 감속·정지한다.
class Worker {
  Worker({
    required this.id,
    required this.name,
    required this.role,
    required this.pos,
    required this.zone,
  }) : target = pos;

  final String id;
  final String name;
  final String role;
  final TempZone zone;

  Offset pos;
  Offset target;

  /// 위급 상황(쓰러짐·부상) 여부.
  bool inDistress = false;

  /// 로봇에게 물건 전달을 요청한 상태.
  bool awaitingHandover = false;
}

/// 구획별 동적 환경 상태(온도·조도·마찰·경사).
class ZoneEnvironment {
  ZoneEnvironment({
    required this.zone,
    required this.temperatureC,
    required this.lux,
    required this.friction,
    required this.slopeDeg,
    required this.humidity,
  });

  final TempZone zone;

  double temperatureC;
  double lux;

  /// 바닥 마찰계수. 0.70 이상이면 정상, 낮을수록 미끄럽다.
  double friction;

  /// 바닥 경사(도). 램프 구간에서 커진다.
  double slopeDeg;

  double humidity;

  /// 전원 공급 여부. 차단 시 조도가 비상등 수준으로 떨어진다.
  bool powerOn = true;

  /// 마찰 기반 구동 성능 계수.
  double get tractionFactor => (friction / 0.70).clamp(0.45, 1.0);

  /// 조도 기반 비전 측위 성능 계수.
  double get visibilityFactor => (lux / 260.0).clamp(0.45, 1.0);

  /// 경사 기반 성능 계수.
  double get slopeFactor => (1.0 - slopeDeg.abs() / 12.0).clamp(0.6, 1.0);

  /// 종합 주행 성능 지수(0~1). 관제 화면에 그대로 노출된다.
  double get performanceIndex =>
      tractionFactor * visibilityFactor * slopeFactor;

  bool get temperatureOk =>
      temperatureC >= zone.minC - 1.5 && temperatureC <= zone.maxC + 1.5;

  bool get slippery => friction < 0.55;

  bool get dim => lux < 140;
}
