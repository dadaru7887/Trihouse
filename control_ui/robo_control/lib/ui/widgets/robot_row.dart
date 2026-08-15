import 'package:flutter/material.dart';

import '../../core/fleet_engine.dart';
import 'package:robo_core/models/enums.dart';
import 'package:robo_core/models/robot.dart';
import '../theme.dart';
import 'common.dart';

/// 로봇 한 대의 요약 행. 상태·배터리·현재 태스크 진행률을 함께 보여준다.
class RobotRow extends StatelessWidget {
  const RobotRow({
    super.key,
    required this.robot,
    required this.engine,
    this.onTap,
    this.showActivity = true,
    this.compact = false,
  });

  final Robot robot;
  final FleetEngine engine;
  final VoidCallback? onTap;
  final bool showActivity;

  /// 폭이 좁은 목록(사이드 패널)에서는 상태 칩만 표시한다.
  /// 절전 여부는 배터리 수치의 색으로도 드러나므로 라벨이 잘리는 편보다 낫다.
  final bool compact;

  @override
  Widget build(BuildContext context) {
    final selected = engine.selectedRobotId == robot.id;
    final stateColor = AppColors.robotStateColor(robot.state);
    final task = robot.taskId == null ? null : engine.tasks[robot.taskId];

    return InkWell(
      onTap: onTap ?? () => engine.selectRobot(selected ? null : robot.id),
      child: Container(
        margin: const EdgeInsets.only(bottom: 6),
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
        decoration: BoxDecoration(
          color: selected
              ? AppColors.series1.withValues(alpha: 0.08)
              : AppColors.page.withValues(alpha: 0.55),
          borderRadius: BorderRadius.circular(7),
          border: Border.all(
            color: selected ? AppColors.series1.withValues(alpha: 0.5) : AppColors.border,
          ),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            Row(
              children: <Widget>[
                Icon(AppColors.robotStateIcon(robot.state), size: 14, color: stateColor),
                const SizedBox(width: 7),
                SizedBox(
                  width: compact ? 88 : 96,
                  child: Text(
                    '${robot.id} ${robot.name}',
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      color: AppColors.textPrimary,
                      fontSize: 12.5,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
                // 좁은 패널에서도 잘리지 않도록 칩 영역이 남은 폭을 흡수한다.
                Expanded(
                  child: Row(
                    children: <Widget>[
                      Flexible(
                        child: StatusChip(
                          label: robot.state.label,
                          color: stateColor,
                          compact: true,
                        ),
                      ),
                      // 상태 칩이 이미 '절전'이면 같은 배지를 겹쳐 달지 않는다.
                      if (robot.powerSaving &&
                          !compact &&
                          robot.state != RobotState.powerSaving) ...<Widget>[
                        const SizedBox(width: 4),
                        const Flexible(
                          child: StatusChip(
                            label: '절전',
                            color: AppColors.warning,
                            icon: Icons.energy_savings_leaf_outlined,
                            compact: true,
                          ),
                        ),
                      ],
                    ],
                  ),
                ),
                const SizedBox(width: 6),
                SizedBox(
                  width: 52,
                  child: Text(
                    '${robot.battery.toStringAsFixed(0)}%',
                    textAlign: TextAlign.right,
                    style: TextStyle(
                      color: AppColors.batteryColor(robot.battery),
                      fontSize: 12,
                      fontWeight: FontWeight.w600,
                      fontFeatures: const <FontFeature>[FontFeature.tabularFigures()],
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 6),
            Row(
              children: <Widget>[
                SizedBox(
                  width: 62,
                  child: MeterBar(
                    value: robot.battery / 100,
                    color: AppColors.batteryColor(robot.battery),
                    height: 5,
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: MeterBar(
                    value: robot.taskProgress,
                    color: task == null ? AppColors.baseline : AppColors.series1,
                    height: 5,
                  ),
                ),
                const SizedBox(width: 8),
                SizedBox(
                  width: 34,
                  child: Text(
                    task == null ? '—' : '${(robot.taskProgress * 100).toStringAsFixed(0)}%',
                    textAlign: TextAlign.right,
                    style: const TextStyle(
                      color: AppColors.textSecondary,
                      fontSize: 11,
                      fontFeatures: <FontFeature>[FontFeature.tabularFigures()],
                    ),
                  ),
                ),
              ],
            ),
            if (showActivity) ...<Widget>[
              const SizedBox(height: 5),
              Text(
                robot.safetyNote ??
                    robot.activity ??
                    (task != null ? task.title : '할당된 태스크 없음'),
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(
                  color: robot.safetyNote != null
                      ? AppColors.warning
                      : AppColors.muted,
                  fontSize: 11,
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}
