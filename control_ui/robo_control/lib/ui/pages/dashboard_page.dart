import 'package:flutter/material.dart';

import '../../core/fleet_engine.dart';
import 'package:robo_core/models/enums.dart';
import '../app_shell.dart';
import '../theme.dart';
import '../widgets/common.dart';
import '../widgets/robot_row.dart';
import '../widgets/throughput_chart.dart';

/// 종합 현황: 핵심 지표 · 처리량 · 3온도 환경 · 로봇 · 최근 이벤트.
class DashboardPage extends StatefulWidget {
  const DashboardPage({super.key});

  @override
  State<DashboardPage> createState() => _DashboardPageState();
}

class _DashboardPageState extends State<DashboardPage> {
  bool _chartAsTable = false;

  @override
  Widget build(BuildContext context) {
    final engine = EngineScope.of(context);

    return LayoutBuilder(
      builder: (context, c) {
        final perRow = c.maxWidth > 1500 ? 6 : (c.maxWidth > 1100 ? 4 : 3);
        final rows = (_MetricsRow.tileCount / perRow).ceil();
        final metricsHeight =
            rows * _MetricsRow.tileHeight + (rows - 1) * _MetricsRow.spacing;
        return MinHeightScroll(
          minHeight: metricsHeight + 12 + 520,
          child: _body(engine, perRow, metricsHeight),
        );
      },
    );
  }

  Widget _body(FleetEngine engine, int perRow, double metricsHeight) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: <Widget>[
        SizedBox(
          height: metricsHeight,
          child: _MetricsRow(engine: engine, perRow: perRow),
        ),
        const SizedBox(height: 12),
        Expanded(
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: <Widget>[
              Expanded(
                flex: 3,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: <Widget>[
                    Panel(
                      title: '완료 태스크 처리량',
                      subtitle: '5분 구간별 완료 건수 · 마지막 구간은 집계 중',
                      trailing: IconButton(
                        tooltip: _chartAsTable ? '차트로 보기' : '표로 보기',
                        onPressed: () =>
                            setState(() => _chartAsTable = !_chartAsTable),
                        icon: Icon(
                          _chartAsTable
                              ? Icons.bar_chart_outlined
                              : Icons.table_rows_outlined,
                          size: 16,
                          color: AppColors.textSecondary,
                        ),
                      ),
                      child: ThroughputChart(
                        buckets: engine.throughput,
                        asTable: _chartAsTable,
                        height: 168,
                      ),
                    ),
                    const SizedBox(height: 12),
                    Expanded(
                      child: Panel(
                        title: '로봇 상태 공유 현황',
                        subtitle:
                            '각 로봇이 브로드캐스트한 상태 · 현재 태스크 · 진행률 (${engine.beacons.length}대 수신)',
                        child: ListView(
                          padding: EdgeInsets.zero,
                          children: <Widget>[
                            for (final r in engine.robots)
                              RobotRow(robot: r, engine: engine),
                          ],
                        ),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                flex: 2,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: <Widget>[
                    Panel(
                      title: '3온도 구획 환경',
                      subtitle: '온도 · 조도 · 바닥 마찰 · 경사에 따른 주행 성능 보정',
                      child: Column(
                        children: <Widget>[
                          for (final zone in TempZone.values)
                            _ZoneEnvRow(engine: engine, zone: zone),
                        ],
                      ),
                    ),
                    const SizedBox(height: 12),
                    Expanded(
                      child: Panel(
                        title: '최근 이벤트',
                        subtitle: '주행 · 작업 · 배터리 · 안전 이력 실시간 적재',
                        child: ListView.builder(
                          padding: EdgeInsets.zero,
                          itemCount: engine.events.length > 40
                              ? 40
                              : engine.events.length,
                          itemBuilder: (context, i) {
                            final e = engine.events[i];
                            final color = AppColors.severityColor(e.severity);
                            return Padding(
                              padding: const EdgeInsets.only(bottom: 8),
                              child: Row(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: <Widget>[
                                  Icon(
                                    AppColors.severityIcon(e.severity),
                                    size: 13,
                                    color: color,
                                  ),
                                  const SizedBox(width: 7),
                                  Text(
                                    engine.timeLabel(e.at),
                                    style: const TextStyle(
                                      color: AppColors.muted,
                                      fontSize: 10.5,
                                      fontFeatures: <FontFeature>[
                                        FontFeature.tabularFigures(),
                                      ],
                                    ),
                                  ),
                                  const SizedBox(width: 8),
                                  Expanded(
                                    child: Text(
                                      e.message,
                                      style: const TextStyle(
                                        color: AppColors.textSecondary,
                                        fontSize: 11.5,
                                        height: 1.35,
                                      ),
                                    ),
                                  ),
                                ],
                              ),
                            );
                          },
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _MetricsRow extends StatelessWidget {
  const _MetricsRow({required this.engine, required this.perRow});

  static const int tileCount = 12;
  static const double tileHeight = 98;
  static const double spacing = 10;

  final FleetEngine engine;
  final int perRow;

  @override
  Widget build(BuildContext context) {
    final hourly = engine.throughput.fold<int>(0, (a, b) => a + b.completed);
    final safetyColor = engine.activeIncidents.isEmpty
        ? AppColors.good
        : AppColors.critical;

    final tiles = <Widget>[
      MetricTile(
        label: '가동 로봇',
        value: '${engine.activeRobots}',
        unit: '/ ${engine.robots.length}',
        sub: '작업 중 ${engine.workingRobots}대 · 예비 ${engine.robots.where((r) => r.reserve).length}대',
        icon: Icons.smart_toy_outlined,
        accent: AppColors.series1,
      ),
      MetricTile(
        label: '진행 중 태스크',
        value: '${engine.inProgressTasks}',
        sub: '할당 대기 ${engine.pendingTasks}건',
        icon: Icons.play_circle_outline,
        accent: AppColors.series1,
      ),
      MetricTile(
        label: '시간당 처리량',
        value: '$hourly',
        unit: '건/h',
        sub: '최근 60분 완료 기준',
        icon: Icons.speed_outlined,
      ),
      MetricTile(
        label: '태스크 성공률',
        value: (engine.successRate * 100).toStringAsFixed(1),
        unit: '%',
        sub: '완료 ${engine.completedTotal} · 실패 ${engine.failedTotal}',
        icon: Icons.task_alt,
        accent: engine.successRate >= 0.95 ? AppColors.good : AppColors.serious,
      ),
      MetricTile(
        label: '주문 정시 납기율',
        value: (engine.onTimeRate * 100).toStringAsFixed(0),
        unit: '%',
        sub: '마감 주문 ${engine.orders.where((o) => o.closedAt != null).length}건',
        icon: Icons.schedule_outlined,
        accent: engine.onTimeRate >= 0.9 ? AppColors.good : AppColors.serious,
      ),
      MetricTile(
        label: '평균 사이클 타임',
        value: engine.avgCycleSeconds.toStringAsFixed(0),
        unit: '초',
        sub: '집품→하역 완료 평균',
        icon: Icons.timer_outlined,
      ),
      MetricTile(
        label: '평균 배터리',
        value: engine.avgBattery.toStringAsFixed(0),
        unit: '%',
        sub: '20% 절전 · 10% 복귀 정책 적용',
        icon: Icons.battery_charging_full,
        accent: AppColors.batteryColor(engine.avgBattery),
      ),
      MetricTile(
        label: 'FEFO 준수율',
        value: (engine.fefoCompliance * 100).toStringAsFixed(0),
        unit: '%',
        sub: '이탈 ${engine.fefoDeviations}건 · 임박 재고 ${engine.expiringLots}개',
        icon: Icons.event_busy_outlined,
        accent: engine.fefoCompliance >= 0.95
            ? AppColors.good
            : AppColors.warning,
      ),
      MetricTile(
        label: '주행 성능 지수',
        value: (engine.fleetPerformanceIndex * 100).toStringAsFixed(0),
        unit: '%',
        sub: '온도·조도·마찰·경사 반영',
        icon: Icons.terrain_outlined,
        accent: engine.fleetPerformanceIndex >= 0.75
            ? AppColors.good
            : AppColors.warning,
      ),
      MetricTile(
        label: '안전 정지',
        value: '${engine.safetyStopTotal}',
        unit: '회',
        sub: engine.activeIncidents.isEmpty
            ? '진행 중 상황 없음'
            : '진행 중 상황 ${engine.activeIncidents.length}건',
        icon: Icons.health_and_safety_outlined,
        accent: safetyColor,
      ),
      MetricTile(
        label: '중복 수행 차단',
        value: '${engine.ledger.conflictsPrevented}',
        unit: '건',
        sub: '자원 대기 ${engine.ledger.resourceWaits}회',
        icon: Icons.lock_outline,
      ),
      MetricTile(
        label: '태스크 재할당',
        value: '${engine.reassignedTotal}',
        unit: '건',
        sub: '배터리·안전·오류 사유 포함',
        icon: Icons.swap_horiz,
      ),
    ];

    assert(tiles.length == tileCount);
    return LayoutBuilder(
      builder: (context, c) {
        final width = (c.maxWidth - spacing * (perRow - 1)) / perRow;
        return Wrap(
          spacing: spacing,
          runSpacing: spacing,
          children: <Widget>[
            for (final t in tiles)
              SizedBox(width: width, height: tileHeight, child: t),
          ],
        );
      },
    );
  }
}

class _ZoneEnvRow extends StatelessWidget {
  const _ZoneEnvRow({required this.engine, required this.zone});

  final FleetEngine engine;
  final TempZone zone;

  @override
  Widget build(BuildContext context) {
    final e = engine.environment[zone]!;
    final color = AppColors.zoneColor(zone);
    final perf = e.performanceIndex;
    final perfColor = perf >= 0.75
        ? AppColors.good
        : (perf >= 0.6 ? AppColors.warning : AppColors.critical);

    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            children: <Widget>[
              Container(width: 8, height: 8, decoration: BoxDecoration(
                color: color,
                borderRadius: BorderRadius.circular(2),
              )),
              const SizedBox(width: 7),
              Text(
                zone.label,
                style: const TextStyle(
                  color: AppColors.textPrimary,
                  fontSize: 12.5,
                  fontWeight: FontWeight.w600,
                ),
              ),
              const SizedBox(width: 8),
              Text(
                '${e.temperatureC.toStringAsFixed(1)}℃',
                style: TextStyle(
                  color: e.temperatureOk
                      ? AppColors.textSecondary
                      : AppColors.serious,
                  fontSize: 12,
                  fontFeatures: const <FontFeature>[FontFeature.tabularFigures()],
                ),
              ),
              const Spacer(),
              if (!e.powerOn)
                const StatusChip(
                  label: '전원 차단',
                  color: AppColors.serious,
                  icon: Icons.power_off_outlined,
                  compact: true,
                )
              else if (e.slippery)
                const StatusChip(
                  label: '미끄럼 주의',
                  color: AppColors.warning,
                  icon: Icons.ac_unit,
                  compact: true,
                )
              else if (!e.temperatureOk)
                const StatusChip(
                  label: '온도 이탈',
                  color: AppColors.serious,
                  icon: Icons.thermostat,
                  compact: true,
                ),
            ],
          ),
          const SizedBox(height: 5),
          Text(
            '조도 ${e.lux.toStringAsFixed(0)}lx · 마찰 ${e.friction.toStringAsFixed(2)} · '
            '경사 ${e.slopeDeg.toStringAsFixed(1)}° · 습도 ${e.humidity.toStringAsFixed(0)}%',
            style: const TextStyle(color: AppColors.muted, fontSize: 11),
          ),
          const SizedBox(height: 6),
          Row(
            children: <Widget>[
              Expanded(child: MeterBar(value: perf, color: perfColor, height: 6)),
              const SizedBox(width: 8),
              Text(
                '성능 ${(perf * 100).toStringAsFixed(0)}%',
                style: TextStyle(
                  color: perfColor,
                  fontSize: 11,
                  fontWeight: FontWeight.w600,
                  fontFeatures: const <FontFeature>[FontFeature.tabularFigures()],
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
