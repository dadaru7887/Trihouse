import 'package:flutter/material.dart';

import '../../core/fleet_engine.dart';
import 'package:robo_core/models/enums.dart';
import 'package:robo_core/models/robot.dart';
import '../theme.dart';
import 'common.dart';
import 'registration_dialogs.dart';

/// 선택된 로봇의 상세 상태 · 이력 · 수동 제어.
class RobotDetail extends StatelessWidget {
  const RobotDetail({super.key, required this.engine, required this.robot});

  final FleetEngine engine;
  final Robot robot;

  @override
  Widget build(BuildContext context) {
    final task = robot.taskId == null ? null : engine.tasks[robot.taskId];
    final stateColor = AppColors.robotStateColor(robot.state);

    return ListView(
      padding: EdgeInsets.zero,
      children: <Widget>[
        Row(
          children: <Widget>[
            Icon(AppColors.robotStateIcon(robot.state), size: 16, color: stateColor),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                '${robot.id} · ${robot.name}',
                style: const TextStyle(
                  color: AppColors.textPrimary,
                  fontSize: 14,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ),
          ],
        ),
        const SizedBox(height: 8),
        Wrap(
          spacing: 5,
          runSpacing: 5,
          children: <Widget>[
            StatusChip(label: robot.state.label, color: stateColor, compact: true),
            if (robot.powerSaving)
              const StatusChip(
                label: '절전 모드',
                color: AppColors.warning,
                icon: Icons.energy_savings_leaf_outlined,
                compact: true,
              ),
            if (robot.reserve)
              const StatusChip(
                label: '예비 대기',
                color: AppColors.muted,
                icon: Icons.nightlight_outlined,
                compact: true,
              ),
            StatusChip(
              label: robot.zoneRating.contains(TempZone.frozen) ? '냉동 대응' : '상온·냉장',
              color: AppColors.ink(AppColors.series7),
              icon: Icons.ac_unit,
              compact: true,
            ),
          ],
        ),
        const SizedBox(height: 12),
        Row(
          children: <Widget>[
            const SizedBox(
              width: 46,
              child: Text('배터리', style: TextStyle(color: AppColors.muted, fontSize: 11)),
            ),
            Expanded(
              child: MeterBar(
                value: robot.battery / 100,
                color: AppColors.batteryColor(robot.battery),
                height: 7,
              ),
            ),
            const SizedBox(width: 8),
            Text(
              '${robot.battery.toStringAsFixed(1)}%',
              style: TextStyle(
                color: AppColors.batteryColor(robot.battery),
                fontSize: 12,
                fontWeight: FontWeight.w600,
                fontFeatures: const <FontFeature>[FontFeature.tabularFigures()],
              ),
            ),
          ],
        ),
        const SizedBox(height: 7),
        Row(
          children: <Widget>[
            const SizedBox(
              width: 46,
              child: Text('진행률', style: TextStyle(color: AppColors.muted, fontSize: 11)),
            ),
            Expanded(
              child: MeterBar(
                value: robot.taskProgress,
                color: task == null ? AppColors.baseline : AppColors.series1,
                height: 7,
              ),
            ),
            const SizedBox(width: 8),
            Text(
              '${(robot.taskProgress * 100).toStringAsFixed(0)}%',
              style: const TextStyle(
                color: AppColors.textSecondary,
                fontSize: 12,
                fontFeatures: <FontFeature>[FontFeature.tabularFigures()],
              ),
            ),
          ],
        ),
        const SizedBox(height: 12),
        if (robot.safetyNote != null) ...<Widget>[
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 7),
            decoration: BoxDecoration(
              color: AppColors.warning.withValues(alpha: 0.16),
              borderRadius: BorderRadius.circular(6),
              border: Border.all(color: AppColors.warning.withValues(alpha: 0.4)),
            ),
            child: Row(
              children: <Widget>[
                Icon(
                  Icons.shield_outlined,
                  size: 13,
                  color: AppColors.ink(AppColors.warning),
                ),
                const SizedBox(width: 6),
                Expanded(
                  child: Text(
                    robot.safetyNote!,
                    style: TextStyle(
                      color: AppColors.ink(AppColors.warning),
                      fontSize: 11.5,
                    ),
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 10),
        ],
        KeyValueRow('모델', robot.model),
        KeyValueRow('현재 위치', '(${robot.pos.dx.toStringAsFixed(1)}, ${robot.pos.dy.toStringAsFixed(1)}) · ${engine.layout.zoneAt(robot.pos).label}'),
        KeyValueRow('속도', '${robot.speed.toStringAsFixed(2)} u/s'),
        KeyValueRow('측위 신뢰도', '${(robot.localizationConfidence * 100).toStringAsFixed(0)}%',
            valueColor: robot.localizationConfidence < 0.7
                ? AppColors.ink(AppColors.warning)
                : AppColors.textPrimary),
        KeyValueRow('누적 주행', '${robot.odometer.toStringAsFixed(0)} unit'),
        KeyValueRow('가동 시간', '${robot.workingSeconds.toStringAsFixed(0)}초 (대기 ${robot.idleSeconds.toStringAsFixed(0)}초)'),
        const Divider(height: 18, color: AppColors.grid),
        KeyValueRow('현재 태스크', task == null ? '없음' : '${task.id} · ${task.type.label}'),
        if (task != null) ...<Widget>[
          KeyValueRow('작업 내용', task.title),
          KeyValueRow('현재 스텝',
              '${task.stepIndex + 1}/${task.steps.length} · ${task.currentStep?.label ?? "-"}'),
          KeyValueRow('경로', '${task.originLabel} → ${task.destLabel}'),
          KeyValueRow('긴급도', task.urgency.label,
              valueColor: AppColors.urgencyColor(task.urgency)),
          if (task.expiry != null)
            KeyValueRow('유통기한', engine.dateLabel(task.expiry!)),
        ],
        KeyValueRow('목적지', robot.destinationLabel ?? '-'),
        KeyValueRow('적재물', robot.payload ?? '없음'),
        KeyValueRow('점유 자원', robot.reservedResourceId ?? '없음'),
        const Divider(height: 18, color: AppColors.grid),
        KeyValueRow('완료 / 실패', '${robot.completedTasks} / ${robot.failedTasks}'),
        KeyValueRow('작업자 인계', '${robot.handovers}회'),
        KeyValueRow('안전 정지', '${robot.safetyStops}회'),
        KeyValueRow('최근 오류', robot.lastFault ?? '없음',
            valueColor: robot.lastFault == null
                ? AppColors.textPrimary
                : AppColors.ink(AppColors.serious)),
        const SizedBox(height: 14),
        Row(
          children: <Widget>[
            Expanded(
              child: OutlinedButton.icon(
                onPressed: () => engine.recallRobot(robot),
                style: OutlinedButton.styleFrom(
                  foregroundColor: AppColors.textSecondary,
                  side: BorderSide(color: AppColors.border),
                  padding: const EdgeInsets.symmetric(vertical: 10),
                ),
                icon: const Icon(Icons.u_turn_left_outlined, size: 14),
                label: const Text('충전소 회수', style: TextStyle(fontSize: 11.5)),
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: OutlinedButton.icon(
                onPressed: () => engine.resumeRobot(robot),
                style: OutlinedButton.styleFrom(
                  foregroundColor: AppColors.series1,
                  side: BorderSide(color: AppColors.series1.withValues(alpha: 0.5)),
                  padding: const EdgeInsets.symmetric(vertical: 10),
                ),
                icon: const Icon(Icons.play_arrow, size: 14),
                label: const Text('투입 재개', style: TextStyle(fontSize: 11.5)),
              ),
            ),
          ],
        ),
        const SizedBox(height: 8),
        OutlinedButton.icon(
          onPressed: () => RemoveRobotDialog.show(context, engine, robot),
          style: OutlinedButton.styleFrom(
            foregroundColor: AppColors.critical,
            side: BorderSide(color: AppColors.critical.withValues(alpha: 0.45)),
            padding: const EdgeInsets.symmetric(vertical: 10),
          ),
          icon: const Icon(Icons.remove_circle_outline, size: 14),
          label: const Text('플릿에서 등록 해제', style: TextStyle(fontSize: 11.5)),
        ),
      ],
    );
  }
}
