import 'package:flutter/material.dart';

import '../../core/fleet_engine.dart';
import 'package:robo_core/models/enums.dart';
import '../app_shell.dart';
import '../theme.dart';
import '../widgets/common.dart';
import '../widgets/registration_dialogs.dart';
import '../widgets/robot_detail.dart';
import '../widgets/robot_row.dart';

/// 로봇 관제: 상태 공유(브로드캐스트) · 배터리 정책 · 개별 제어.
class RobotsPage extends StatelessWidget {
  const RobotsPage({super.key});

  @override
  Widget build(BuildContext context) {
    final engine = EngineScope.of(context);
    final selected = engine.selectedRobot;

    return Row(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: <Widget>[
        SizedBox(
          width: 320,
          child: Panel(
            title: '로봇 목록',
            subtitle: '가동 ${engine.activeRobots}대 · 예비 ${engine.robots.where((r) => r.reserve).length}대',
            trailing: TextButton.icon(
              onPressed: () => AddRobotDialog.show(context, engine),
              style: TextButton.styleFrom(
                foregroundColor: AppColors.series1,
                padding: const EdgeInsets.symmetric(horizontal: 8),
                minimumSize: Size.zero,
                tapTargetSize: MaterialTapTargetSize.shrinkWrap,
              ),
              icon: const Icon(Icons.add, size: 14),
              label: const Text('로봇 등록', style: TextStyle(fontSize: 11.5)),
            ),
            child: ListView(
              padding: EdgeInsets.zero,
              children: <Widget>[
                for (final r in engine.robots)
                  RobotRow(robot: r, engine: engine, compact: true),
              ],
            ),
          ),
        ),
        const SizedBox(width: 12),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: <Widget>[
              Expanded(
                flex: 3,
                child: Panel(
                  title: '로봇 상태 브로드캐스트',
                  subtitle:
                      '각 로봇이 2초 주기로 관제·타 로봇에 공유하는 상태 스냅샷 (수신 ${engine.beacons.length}건)',
                  child: _BeaconTable(engine: engine),
                ),
              ),
              const SizedBox(height: 12),
              Expanded(
                flex: 2,
                child: Panel(
                  title: '배터리 · 가용성 정책',
                  subtitle: '20% 절전 진입 · 10% 충전소 복귀 · 예비기 단계적 투입',
                  child: _BatteryPolicyPanel(engine: engine),
                ),
              ),
            ],
          ),
        ),
        const SizedBox(width: 12),
        SizedBox(
          width: 330,
          child: Panel(
            title: selected == null ? '로봇 상세' : '로봇 상세 · ${selected.id}',
            subtitle: selected == null ? '목록에서 로봇을 선택하세요' : selected.model,
            child: selected == null
                ? const EmptyHint('선택된 로봇이 없습니다.')
                : RobotDetail(engine: engine, robot: selected),
          ),
        ),
      ],
    );
  }
}

class _BeaconTable extends StatelessWidget {
  const _BeaconTable({required this.engine});

  final FleetEngine engine;

  @override
  Widget build(BuildContext context) {
    if (engine.beacons.isEmpty) {
      return const EmptyHint('상태 수신 대기 중입니다.');
    }
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: SizedBox(
        width: 760,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: <Widget>[
            const _BeaconHeader(),
            Divider(height: 10, color: AppColors.border),
            Expanded(
              child: ListView.builder(
                padding: EdgeInsets.zero,
                itemCount: engine.beacons.length,
                itemBuilder: (context, i) {
                  final b = engine.beacons[i];
                  final robot = engine.robots.firstWhere((r) => r.id == b.robotId);
                  final color = AppColors.robotStateColor(robot.state);
                  return Padding(
                    padding: const EdgeInsets.symmetric(vertical: 5),
                    child: Row(
                      children: <Widget>[
                        SizedBox(
                          width: 84,
                          child: Row(
                            children: <Widget>[
                              if (engine.isLinked(robot) ||
                                  engine.isLinkOffline(robot)) ...<Widget>[
                                Tooltip(
                                  message: engine.isLinked(robot)
                                      ? '현장 장비 링크 연결됨 — 위치·배터리는 실장비 보고값'
                                      : '현장 장비 링크 대기 중 — 배차 제외',
                                  child: Icon(
                                    engine.isLinked(robot)
                                        ? Icons.cell_tower
                                        : Icons.wifi_tethering_off,
                                    size: 11,
                                    color: engine.isLinked(robot)
                                        ? AppColors.good
                                        : AppColors.muted,
                                  ),
                                ),
                                const SizedBox(width: 3),
                              ],
                              Expanded(
                                child: Text(
                                  '${b.robotId} ${robot.name}',
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis,
                                  style: const TextStyle(
                                    color: AppColors.textPrimary,
                                    fontSize: 11.5,
                                    fontWeight: FontWeight.w600,
                                  ),
                                ),
                              ),
                            ],
                          ),
                        ),
                        SizedBox(
                          width: 62,
                          child: Text(
                            engine.timeLabel(b.at),
                            style: const TextStyle(
                              color: AppColors.muted,
                              fontSize: 11,
                              fontFeatures: <FontFeature>[FontFeature.tabularFigures()],
                            ),
                          ),
                        ),
                        SizedBox(
                          width: 92,
                          child: StatusChip(label: b.state, color: color, compact: true),
                        ),
                        SizedBox(
                          width: 54,
                          child: Text(
                            '${b.battery.toStringAsFixed(0)}%',
                            style: TextStyle(
                              color: AppColors.batteryColor(b.battery),
                              fontSize: 11.5,
                              fontFeatures: const <FontFeature>[FontFeature.tabularFigures()],
                            ),
                          ),
                        ),
                        SizedBox(
                          width: 92,
                          child: Text(
                            b.taskId ?? '—',
                            style: const TextStyle(
                              color: AppColors.textSecondary,
                              fontSize: 11.5,
                            ),
                          ),
                        ),
                        SizedBox(
                          width: 88,
                          child: Row(
                            children: <Widget>[
                              Expanded(
                                child: MeterBar(
                                  value: b.progress,
                                  color: b.taskId == null
                                      ? AppColors.baseline
                                      : AppColors.series1,
                                  height: 5,
                                ),
                              ),
                              const SizedBox(width: 6),
                              Text(
                                '${(b.progress * 100).toStringAsFixed(0)}%',
                                style: const TextStyle(
                                  color: AppColors.muted,
                                  fontSize: 10.5,
                                  fontFeatures: <FontFeature>[FontFeature.tabularFigures()],
                                ),
                              ),
                            ],
                          ),
                        ),
                        const SizedBox(width: 8),
                        Expanded(
                          child: Text(
                            b.activity,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: const TextStyle(
                              color: AppColors.textSecondary,
                              fontSize: 11.5,
                            ),
                          ),
                        ),
                        SizedBox(
                          width: 78,
                          child: Text(
                            b.holding ?? '—',
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: TextStyle(
                              color: AppColors.ink(AppColors.series4),
                              fontSize: 11,
                            ),
                          ),
                        ),
                      ],
                    ),
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _BeaconHeader extends StatelessWidget {
  const _BeaconHeader();

  @override
  Widget build(BuildContext context) {
    Widget h(String t, double w) => SizedBox(
      width: w,
      child: Text(
        t,
        style: const TextStyle(
          color: AppColors.muted,
          fontSize: 10.5,
          fontWeight: FontWeight.w600,
          letterSpacing: 0.3,
        ),
      ),
    );

    return Row(
      children: <Widget>[
        h('로봇', 84),
        h('수신 시각', 62),
        h('상태', 92),
        h('배터리', 54),
        h('태스크', 92),
        h('진행률', 88),
        const SizedBox(width: 8),
        const Expanded(
          child: Text(
            '현재 작업',
            style: TextStyle(
              color: AppColors.muted,
              fontSize: 10.5,
              fontWeight: FontWeight.w600,
            ),
          ),
        ),
        h('점유 자원', 78),
      ],
    );
  }
}

class _BatteryPolicyPanel extends StatelessWidget {
  const _BatteryPolicyPanel({required this.engine});

  final FleetEngine engine;

  @override
  Widget build(BuildContext context) {
    final saving = engine.robots.where((r) => r.powerSaving).toList();
    final returning =
        engine.robots.where((r) => r.state == RobotState.returning).length;
    final charging =
        engine.robots.where((r) => r.state == RobotState.charging).length;
    final reserve = engine.robots.where((r) => r.reserve).length;

    return ListView(
      padding: EdgeInsets.zero,
      children: <Widget>[
        Row(
          children: <Widget>[
            Expanded(
              child: _MiniStat(
                label: '절전 모드',
                value: '${saving.length}대',
                color: AppColors.ink(AppColors.warning),
              ),
            ),
            Expanded(
              child: _MiniStat(
                label: '충전소 복귀',
                value: '$returning대',
                color: AppColors.ink(AppColors.series7),
              ),
            ),
            Expanded(
              child: _MiniStat(
                label: '충전 중',
                value: '$charging대',
                color: AppColors.ink(AppColors.series7),
              ),
            ),
            Expanded(
              child: _MiniStat(
                label: '예비 대기',
                value: '$reserve대',
                color: AppColors.muted,
              ),
            ),
          ],
        ),
        const SizedBox(height: 12),
        const _PolicyLine(
          icon: Icons.energy_savings_leaf_outlined,
          color: AppColors.warning,
          text: '배터리 20% 이하 — 절전 모드 진입. 진행률 65% 미만 태스크는 안전 종료 후 대기열에 반환하고, '
              '가장 가까운 대기 구역·충전소까지 최소 동선으로만 이동합니다.',
        ),
        const _PolicyLine(
          icon: Icons.u_turn_left_outlined,
          color: AppColors.critical,
          text: '배터리 10% 이하 — 현재 작업을 안전 종료하고 충전소로 복귀합니다. '
              '반환된 태스크는 우선순위를 유지한 채 다른 로봇에 재할당됩니다.',
        ),
        const _PolicyLine(
          icon: Icons.groups_outlined,
          color: AppColors.series1,
          text: '가용 대수가 줄거나 대기 태스크가 5건 이상 적체되면 예비기를 단계적으로 투입해 '
              '전체 작업이 중단되지 않도록 유지합니다.',
        ),
        if (saving.isNotEmpty) ...<Widget>[
          const SizedBox(height: 6),
          Text(
            '절전 대상: ${saving.map((r) => "${r.id}(${r.battery.toStringAsFixed(0)}%)").join(", ")}',
            style: TextStyle(
              color: AppColors.ink(AppColors.warning),
              fontSize: 11.5,
            ),
          ),
        ],
      ],
    );
  }
}

class _MiniStat extends StatelessWidget {
  const _MiniStat({required this.label, required this.value, required this.color});

  final String label;
  final String value;
  final Color color;

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: <Widget>[
      Text(label, style: const TextStyle(color: AppColors.muted, fontSize: 10.5)),
      const SizedBox(height: 3),
      Text(
        value,
        style: TextStyle(color: color, fontSize: 16, fontWeight: FontWeight.w600),
      ),
    ],
  );
}

class _PolicyLine extends StatelessWidget {
  const _PolicyLine({required this.icon, required this.color, required this.text});

  final IconData icon;
  final Color color;
  final String text;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(bottom: 8),
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        Icon(icon, size: 13, color: color),
        const SizedBox(width: 8),
        Expanded(
          child: Text(
            text,
            style: const TextStyle(
              color: AppColors.textSecondary,
              fontSize: 11.5,
              height: 1.45,
            ),
          ),
        ),
      ],
    ),
  );
}
