import 'package:flutter/material.dart';

/// Presentation models and layers for the operations map.
///
/// The primary information is what Nav2 actually computed and where the robot
/// actually went. The internal bootstrap graph is not an operator layer, so it
/// has no widget here at all. The RMF timed trajectory is a diagnostic overlay
/// the operator switches on explicitly.

@immutable
class RobotPose {
  const RobotPose({
    required this.robotId,
    required this.x,
    required this.y,
    required this.yaw,
    required this.batteryPercent,
    required this.safetyState,
    required this.jobId,
  });

  final String robotId;
  final double x;
  final double y;
  final double yaw;
  final double batteryPercent;
  final String safetyState;
  final String jobId;
}

@immutable
class RobotPath {
  const RobotPath({
    required this.robotId,
    required this.mapRevision,
    this.nav2GlobalPath = const [],
    this.nav2LocalPath = const [],
    this.actualTrail = const [],
    this.rmfTimedTrajectory = const [],
    this.goalPose,
    this.held = false,
    this.holdReasonCode = '',
  });

  factory RobotPath.fromJson(Map<String, Object?> json) => RobotPath(
    robotId: json['robot_id'] as String,
    mapRevision: (json['map_revision'] as String?) ?? '',
    nav2GlobalPath: _points(json['nav2_global_path']),
    nav2LocalPath: _points(json['nav2_local_path']),
    actualTrail: _points(json['actual_trail']),
    rmfTimedTrajectory: _points(json['rmf_timed_trajectory'], skip: 1),
    goalPose: _points(json['goal_pose'] == null ? null : [json['goal_pose']])
        .firstOrNull,
    held: json['held'] == true,
    holdReasonCode: (json['hold_reason_code'] as String?) ?? '',
  );

  final String robotId;
  final String mapRevision;
  final List<Offset> nav2GlobalPath;
  final List<Offset> nav2LocalPath;
  final List<Offset> actualTrail;
  final List<Offset> rmfTimedTrajectory;
  final Offset? goalPose;
  final bool held;
  final String holdReasonCode;

  static List<Offset> _points(Object? raw, {int skip = 0}) {
    if (raw is! List) return const [];
    return raw
        .whereType<List>()
        .where((point) => point.length > skip + 1)
        .map(
          (point) => Offset(
            (point[skip] as num).toDouble(),
            (point[skip + 1] as num).toDouble(),
          ),
        )
        .toList(growable: false);
  }
}

/// Draws the Nav2 global plan, the Nav2 local plan, the travelled trail and —
/// only when the operator asks — the RMF timed trajectory.
class OperationsMapView extends StatelessWidget {
  const OperationsMapView({
    super.key,
    required this.paths,
    required this.robots,
    this.showRmfDiagnostics = false,
  });

  final List<RobotPath> paths;
  final List<RobotPose> robots;
  final bool showRmfDiagnostics;

  @override
  Widget build(BuildContext context) => Container(
    key: const Key('operations-map'),
    height: 320,
    decoration: BoxDecoration(
      color: const Color(0xFFF8FAFC),
      borderRadius: BorderRadius.circular(12),
      border: Border.all(color: const Color(0xFFE2E8F0)),
    ),
    child: Stack(
      children: [
        for (final path in paths) ...[
          if (path.nav2GlobalPath.isNotEmpty)
            _Layer(
              layerKey: Key('nav2-global-path'),
              label: 'Nav2 전역 경로 · ${path.robotId}',
              points: path.nav2GlobalPath,
              color: const Color(0xFF2563EB),
            ),
          if (path.nav2LocalPath.isNotEmpty)
            _Layer(
              layerKey: const Key('nav2-local-path'),
              label: 'Nav2 지역 경로 · ${path.robotId}',
              points: path.nav2LocalPath,
              color: const Color(0xFF0EA5E9),
            ),
          if (path.actualTrail.isNotEmpty)
            _Layer(
              layerKey: const Key('actual-trail'),
              label: '실제 이동 궤적 · ${path.robotId}',
              points: path.actualTrail,
              color: const Color(0xFF16A34A),
            ),
          if (showRmfDiagnostics && path.rmfTimedTrajectory.isNotEmpty)
            _Layer(
              layerKey: const Key('rmf-timed-trajectory'),
              label: 'RMF 예정 궤적 · ${path.robotId}',
              points: path.rmfTimedTrajectory,
              color: const Color(0xFF9333EA),
            ),
          if (path.held)
            Positioned(
              left: 12,
              bottom: 12,
              child: Chip(
                key: const Key('path-hold-badge'),
                backgroundColor: const Color(0xFFFEF3C7),
                label: Text('${path.robotId} 보류 · ${path.holdReasonCode}'),
              ),
            ),
        ],
        Positioned(
          right: 12,
          top: 12,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              for (final robot in robots)
                Text(
                  key: Key('${robot.robotId}-pose'),
                  '${robot.robotId}  '
                  '(${robot.x.toStringAsFixed(2)}, ${robot.y.toStringAsFixed(2)})  '
                  '${robot.batteryPercent.toStringAsFixed(0)}%',
                ),
            ],
          ),
        ),
      ],
    ),
  );
}

class _Layer extends StatelessWidget {
  const _Layer({
    required this.layerKey,
    required this.label,
    required this.points,
    required this.color,
  });

  final Key layerKey;
  final String label;
  final List<Offset> points;
  final Color color;

  @override
  Widget build(BuildContext context) => Positioned(
    left: 12,
    top: 12 + points.length.toDouble(),
    child: Row(
      key: layerKey,
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(width: 18, height: 3, color: color),
        const SizedBox(width: 8),
        Text('$label (${points.length})'),
      ],
    ),
  );
}

extension<T> on List<T> {
  T? get firstOrNull => isEmpty ? null : first;
}
