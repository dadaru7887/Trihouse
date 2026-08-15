import 'package:robo_core/models/robot.dart';

/// 태스크 점유 리스(lease). 다중 로봇이 동시에 같은 태스크를 집어가는
/// 중복 수행을 막는 단일 소유권 레지스트리다.
///
/// 실제 시스템에서는 Redis/etcd의 CAS 연산에 해당하며, 여기서는 동일한
/// 계약(단일 소유자 + TTL + 갱신 + 해제)을 인메모리로 구현한다.
class TaskLedger {
  TaskLedger();

  final Map<String, _Lease> _leases = <String, _Lease>{};

  /// 자원(랙 슬롯·도크) 점유표.
  final Map<String, String> _resourceOwner = <String, String>{};

  int conflictsPrevented = 0;
  int resourceWaits = 0;

  /// 태스크 점유 시도. 이미 유효한 다른 소유자가 있으면 실패한다.
  bool claim(String taskId, String robotId, DateTime now, Duration ttl) {
    final cur = _leases[taskId];
    if (cur != null && cur.robotId != robotId && cur.expiresAt.isAfter(now)) {
      conflictsPrevented++;
      return false;
    }
    _leases[taskId] = _Lease(robotId, now.add(ttl));
    return true;
  }

  /// 하트비트. 로봇이 살아있는 동안 리스를 연장한다.
  void renew(String taskId, String robotId, DateTime now, Duration ttl) {
    final cur = _leases[taskId];
    if (cur == null || cur.robotId != robotId) return;
    _leases[taskId] = _Lease(robotId, now.add(ttl));
  }

  void release(String taskId) => _leases.remove(taskId);

  String? ownerOf(String taskId, DateTime now) {
    final cur = _leases[taskId];
    if (cur == null || !cur.expiresAt.isAfter(now)) return null;
    return cur.robotId;
  }

  /// TTL이 만료된 리스를 회수한다. 로봇이 응답 불능일 때 태스크가
  /// 영구 점유 상태로 남지 않도록 하는 장치.
  List<String> reapExpired(DateTime now) {
    final expired = <String>[];
    _leases.removeWhere((taskId, lease) {
      if (lease.expiresAt.isAfter(now)) return false;
      expired.add(taskId);
      return true;
    });
    return expired;
  }

  /// 자원 점유. 같은 랙 슬롯에 두 로봇이 동시에 진입하는 것을 막는다.
  bool acquireResource(String resourceId, String robotId) {
    final owner = _resourceOwner[resourceId];
    if (owner != null && owner != robotId) {
      resourceWaits++;
      return false;
    }
    _resourceOwner[resourceId] = robotId;
    return true;
  }

  void releaseResource(String resourceId, String robotId) {
    if (_resourceOwner[resourceId] == robotId) {
      _resourceOwner.remove(resourceId);
    }
  }

  void releaseAllOf(String robotId) {
    _resourceOwner.removeWhere((_, owner) => owner == robotId);
    _leases.removeWhere((_, lease) => lease.robotId == robotId);
  }

  String? resourceOwner(String resourceId) => _resourceOwner[resourceId];

  int get activeLeases => _leases.length;

  int get heldResources => _resourceOwner.length;
}

class _Lease {
  _Lease(this.robotId, this.expiresAt);

  final String robotId;
  final DateTime expiresAt;
}

/// 로봇이 주기적으로 브로드캐스트하는 상태 요약.
/// 관제 시스템과 다른 로봇이 동일한 뷰를 공유하기 위한 스냅샷이다.
class RobotStatusBeacon {
  RobotStatusBeacon({
    required this.robotId,
    required this.at,
    required this.state,
    required this.battery,
    required this.taskId,
    required this.progress,
    required this.activity,
    required this.holding,
  });

  factory RobotStatusBeacon.of(Robot r, DateTime now) => RobotStatusBeacon(
    robotId: r.id,
    at: now,
    state: r.state.label,
    battery: r.battery,
    taskId: r.taskId,
    progress: r.taskProgress,
    activity: r.activity ?? '-',
    holding: r.reservedResourceId,
  );

  final String robotId;
  final DateTime at;
  final String state;
  final double battery;
  final String? taskId;
  final double progress;
  final String activity;
  final String? holding;
}
