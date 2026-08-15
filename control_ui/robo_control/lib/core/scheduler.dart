import 'dart:math' as math;

import 'package:robo_core/models/enums.dart';
import 'package:robo_core/models/inventory.dart';
import 'package:robo_core/models/robot.dart';
import 'package:robo_core/models/task.dart';
import 'layout.dart';

/// 스케줄링 가중치. 관제 화면에서 조정 가능하다.
class ScheduleWeights {
  ScheduleWeights({
    this.urgency = 26,
    this.fefo = 30,
    this.travel = 22,
    this.aging = 12,
    this.dueDate = 18,
    this.dockPressure = 22,
  });

  /// 주문 긴급도 가중치.
  double urgency;

  /// FEFO(유통기한 임박) 가중치.
  double fefo;

  /// 로봇 이동 동선 가중치.
  double travel;

  /// 대기 시간 가중치(기아 방지).
  double aging;

  /// 납기 임박 가중치.
  double dueDate;

  /// 입고 도크 점유 압박 가중치.
  ///
  /// 입고는 긴급도·FEFO 가점이 없어 출고에 계속 밀리기 쉽다. 그러나 도크에
  /// 대기 중인 차량은 계속 자원을 점유하므로, 대기 시간이 길어질수록 빠르게
  /// 우선순위를 올려 기아를 막는다.
  double dockPressure;
}

/// 하나의 태스크에 대한 로봇 입찰.
class Bid {
  Bid(this.robot, this.score, this.travelDistance);

  final Robot robot;
  final double score;
  final double travelDistance;
}

/// 태스크 우선순위 계산 결과(관제 화면 설명용).
class PriorityBreakdown {
  PriorityBreakdown({
    required this.urgency,
    required this.fefo,
    required this.aging,
    required this.dueDate,
    required this.total,
    this.dock = 0,
  });

  final double urgency;
  final double fefo;
  final double aging;
  final double dueDate;
  final double dock;
  final double total;
}

/// FEFO · 긴급도 · 동선 기반 작업 스케줄러.
class Scheduler {
  Scheduler(this.layout, {ScheduleWeights? weights})
    : weights = weights ?? ScheduleWeights();

  final WarehouseLayout layout;
  final ScheduleWeights weights;

  /// 태스크 자체의 우선순위 점수.
  PriorityBreakdown priority(
    WorkTask task,
    DateTime now, {
    Lot? lot,
    SalesOrder? order,
  }) {
    final u = (task.urgency.weight / 3.0) * weights.urgency;

    var fefo = 0.0;
    if (task.expiry != null) {
      final hours = task.expiry!.difference(now).inMinutes / 60.0;
      final pressure = hours <= 0
          ? 1.0
          : (1.0 - (hours / (45 * 24))).clamp(0.0, 1.0);
      fefo = pressure * weights.fefo;
    } else if (lot != null) {
      fefo = lot.expiryPressure(now) * weights.fefo;
    }

    final waitedMin = now.difference(task.createdAt).inSeconds / 60.0;
    final aging = math.min(waitedMin / 8.0, 1.0) * weights.aging;

    var due = 0.0;
    if (order != null) {
      final left = order.dueAt.difference(now).inSeconds / 60.0;
      due = left <= 0 ? weights.dueDate : (1.0 - (left / 45.0)).clamp(0.0, 1.0) * weights.dueDate;
    }

    // 작업자 요청은 사람이 대기 중이므로 별도 가산점을 준다.
    final human =
        (task.type == TaskType.handover || task.type == TaskType.relay)
        ? 14.0
        : 0.0;

    // 입고 도크 점유 압박: 5분이면 최대치에 도달한다.
    final dock = task.type == TaskType.inbound
        ? math.min(waitedMin / 5.0, 1.0) * weights.dockPressure
        : 0.0;

    return PriorityBreakdown(
      urgency: u,
      fefo: fefo,
      aging: aging,
      dueDate: due,
      dock: dock,
      total: u + fefo + aging + due + human + dock,
    );
  }

  /// 특정 태스크에 대한 로봇 적합도. 동선이 짧고 배터리 여유가 있으며
  /// 해당 온도 구획에 대응 가능한 로봇이 높은 점수를 받는다.
  Bid? bid(Robot robot, WorkTask task, DateTime now) {
    if (!robot.zoneRating.contains(task.zone)) return null;
    if (robot.battery <= 22) return null;

    final start = task.steps.isEmpty ? robot.pos : task.steps.first.target;
    final travel = layout.routeLength(robot.pos, start);

    // 태스크 전체 동선(픽업→하역)까지 고려해 배터리 소요를 추정한다.
    var full = travel;
    var cur = start;
    for (final s in task.steps) {
      full += layout.routeLength(cur, s.target);
      cur = s.target;
    }
    final estimatedDrain = full * 0.09 + task.steps.length * 1.2;
    if (robot.battery - estimatedDrain < 12) return null;

    final travelScore = (1.0 - (travel / 180.0).clamp(0.0, 1.0)) * weights.travel;
    final batteryScore = (robot.battery / 100.0) * 10.0;
    final zoneBonus = layout.zoneAt(robot.pos) == task.zone ? 6.0 : 0.0;
    final idlePenalty = robot.state == RobotState.charging ? 12.0 : 0.0;

    return Bid(
      robot,
      travelScore + batteryScore + zoneBonus - idlePenalty,
      travel,
    );
  }

  /// 태스크에 대한 입찰을 점수순으로 반환한다.
  /// 상위 후보들이 동시에 점유를 시도하고, 리스 레지스트리가 한 대만
  /// 승인함으로써 중복 수행이 방지된다.
  List<Bid> collectBids(
    WorkTask task,
    Iterable<Robot> robots,
    DateTime now,
  ) {
    final bids = <Bid>[];
    for (final r in robots) {
      final b = bid(r, task, now);
      if (b != null) bids.add(b);
    }
    bids.sort((a, b) => b.score.compareTo(a.score));
    return bids;
  }

  /// FEFO 정렬: 유통기한이 가장 임박한 로트를 먼저 반환한다.
  List<Lot> fefoOrder(Iterable<Lot> lots, DateTime now) {
    final list = lots.where((l) => l.available > 0).toList()
      ..sort((a, b) => a.expiry.compareTo(b.expiry));
    return list;
  }
}
