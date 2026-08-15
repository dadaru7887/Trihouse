import 'package:flutter/material.dart';

import '../core/fleet_engine.dart';
import 'pages/dashboard_page.dart';
import 'pages/events_page.dart';
import 'pages/inventory_page.dart';
import 'pages/map_page.dart';
import 'pages/robots_page.dart';
import 'pages/safety_page.dart';
import 'pages/tasks_page.dart';
import 'theme.dart';
import 'widgets/common.dart';

/// 엔진을 위젯 트리에 공급한다. 엔진이 notify할 때마다 화면이 갱신된다.
class EngineScope extends InheritedNotifier<FleetEngine> {
  const EngineScope({super.key, required FleetEngine engine, required super.child})
    : super(notifier: engine);

  static FleetEngine of(BuildContext context) {
    final scope = context.dependOnInheritedWidgetOfExactType<EngineScope>();
    assert(scope != null, 'EngineScope를 찾을 수 없습니다.');
    return scope!.notifier!;
  }
}

class _NavItem {
  const _NavItem(this.label, this.icon, this.builder, {this.minHeight = 0});

  final String label;
  final IconData icon;
  final WidgetBuilder builder;

  /// 이 화면이 잘림 없이 표시되기 위한 최소 높이. 창이 더 낮으면 스크롤된다.
  /// (종합 현황은 지표 타일 수가 폭에 따라 달라져 화면 자체가 계산한다.)
  final double minHeight;
}

class ControlCenterShell extends StatefulWidget {
  const ControlCenterShell({super.key});

  @override
  State<ControlCenterShell> createState() => _ControlCenterShellState();
}

class _ControlCenterShellState extends State<ControlCenterShell> {
  int _index = 0;

  static final List<_NavItem> _items = <_NavItem>[
    _NavItem('종합 현황', Icons.dashboard_outlined, (c) => const DashboardPage()),
    _NavItem('실시간 맵', Icons.map_outlined, (c) => const MapPage(), minHeight: 540),
    _NavItem('로봇 관제', Icons.smart_toy_outlined, (c) => const RobotsPage(),
        minHeight: 580),
    _NavItem('태스크·주문', Icons.assignment_outlined, (c) => const TasksPage(),
        minHeight: 540),
    _NavItem('재고 · FEFO', Icons.inventory_2_outlined, (c) => const InventoryPage(),
        minHeight: 500),
    _NavItem('안전 관리', Icons.health_and_safety_outlined, (c) => const SafetyPage(),
        minHeight: 780),
    _NavItem('운행 이력', Icons.receipt_long_outlined, (c) => const EventsPage(),
        minHeight: 460),
  ];

  @override
  Widget build(BuildContext context) {
    final engine = EngineScope.of(context);
    final narrow = MediaQuery.sizeOf(context).width < 1100;

    return Scaffold(
      backgroundColor: AppColors.page,
      body: SafeArea(
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: <Widget>[
            _Sidebar(
              items: _items,
              index: _index,
              collapsed: narrow,
              onSelect: (i) => setState(() => _index = i),
              engine: engine,
            ),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: <Widget>[
                  _TopBar(engine: engine, title: _items[_index].label),
                  if (engine.activeIncidents.isNotEmpty)
                    _IncidentBanner(engine: engine),
                  Expanded(
                    child: Padding(
                      padding: const EdgeInsets.fromLTRB(14, 12, 14, 14),
                      child: MinHeightScroll(
                        minHeight: _items[_index].minHeight,
                        child: _items[_index].builder(context),
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _Sidebar extends StatelessWidget {
  const _Sidebar({
    required this.items,
    required this.index,
    required this.onSelect,
    required this.collapsed,
    required this.engine,
  });

  final List<_NavItem> items;
  final int index;
  final ValueChanged<int> onSelect;
  final bool collapsed;
  final FleetEngine engine;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: collapsed ? 62 : 208,
      decoration: BoxDecoration(
        color: AppColors.surface,
        border: Border(right: BorderSide(color: AppColors.border)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          Padding(
            padding: EdgeInsets.fromLTRB(collapsed ? 12 : 16, 16, 12, 16),
            child: Row(
              children: <Widget>[
                Container(
                  width: 26,
                  height: 26,
                  decoration: BoxDecoration(
                    color: AppColors.series1.withValues(alpha: 0.18),
                    borderRadius: BorderRadius.circular(6),
                    border: Border.all(
                      color: AppColors.series1.withValues(alpha: 0.6),
                    ),
                  ),
                  child: const Icon(
                    Icons.hub_outlined,
                    size: 15,
                    color: AppColors.series1,
                  ),
                ),
                if (!collapsed) ...<Widget>[
                  const SizedBox(width: 9),
                  const Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: <Widget>[
                        Text(
                          'RoboSapiens',
                          style: TextStyle(
                            color: AppColors.textPrimary,
                            fontSize: 13,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                        Text(
                          '물류 관제센터',
                          style: TextStyle(
                            color: AppColors.muted,
                            fontSize: 10.5,
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ],
            ),
          ),
          Divider(height: 1, color: AppColors.border),
          Expanded(
            child: ListView.builder(
              padding: const EdgeInsets.symmetric(vertical: 8),
              itemCount: items.length,
              itemBuilder: (context, i) {
                final item = items[i];
                final selected = i == index;
                return InkWell(
                  onTap: () => onSelect(i),
                  child: Container(
                    margin: const EdgeInsets.symmetric(
                      horizontal: 8,
                      vertical: 2,
                    ),
                    padding: EdgeInsets.symmetric(
                      horizontal: collapsed ? 0 : 10,
                      vertical: 9,
                    ),
                    decoration: BoxDecoration(
                      color: selected
                          ? AppColors.series1.withValues(alpha: 0.16)
                          : Colors.transparent,
                      borderRadius: BorderRadius.circular(7),
                      border: Border.all(
                        color: selected
                            ? AppColors.series1.withValues(alpha: 0.5)
                            : Colors.transparent,
                      ),
                    ),
                    child: Row(
                      mainAxisAlignment: collapsed
                          ? MainAxisAlignment.center
                          : MainAxisAlignment.start,
                      children: <Widget>[
                        Icon(
                          item.icon,
                          size: 16,
                          color: selected
                              ? AppColors.series1
                              : AppColors.textSecondary,
                        ),
                        if (!collapsed) ...<Widget>[
                          const SizedBox(width: 9),
                          Expanded(
                            child: Text(
                              item.label,
                              style: TextStyle(
                                color: selected
                                    ? AppColors.textPrimary
                                    : AppColors.textSecondary,
                                fontSize: 12.5,
                                fontWeight: selected
                                    ? FontWeight.w600
                                    : FontWeight.w400,
                              ),
                            ),
                          ),
                        ],
                      ],
                    ),
                  ),
                );
              },
            ),
          ),
          if (!collapsed)
            Padding(
              padding: const EdgeInsets.fromLTRB(14, 8, 14, 14),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: <Widget>[
                  const Text(
                    '동시성 제어',
                    style: TextStyle(color: AppColors.muted, fontSize: 10),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    '리스 ${engine.ledger.activeLeases} · 자원 ${engine.ledger.heldResources}',
                    style: const TextStyle(
                      color: AppColors.textSecondary,
                      fontSize: 11,
                    ),
                  ),
                  Text(
                    '중복 차단 ${engine.ledger.conflictsPrevented}건',
                    style: const TextStyle(
                      color: AppColors.textSecondary,
                      fontSize: 11,
                    ),
                  ),
                  const SizedBox(height: 10),
                  const Text(
                    '현장 링크',
                    style: TextStyle(color: AppColors.muted, fontSize: 10),
                  ),
                  const SizedBox(height: 4),
                  Row(
                    children: <Widget>[
                      Icon(
                        engine.link.linkedCount > 0
                            ? Icons.cell_tower
                            : Icons.wifi_tethering_off,
                        size: 12,
                        color: engine.link.linkedCount > 0
                            ? AppColors.good
                            : AppColors.muted,
                      ),
                      const SizedBox(width: 5),
                      Expanded(
                        child: Text(
                          engine.link.linkedCount > 0
                              ? '실장비 ${engine.link.linkedCount}대 접속'
                              : engine.link.listening
                              ? '게이트웨이 대기 :${engine.link.port}'
                              : '게이트웨이 닫힘',
                          style: TextStyle(
                            color: engine.link.linkedCount > 0
                                ? AppColors.textSecondary
                                : AppColors.muted,
                            fontSize: 11,
                          ),
                        ),
                      ),
                    ],
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }
}

class _TopBar extends StatelessWidget {
  const _TopBar({required this.engine, required this.title});

  final FleetEngine engine;
  final String title;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.fromLTRB(16, 10, 14, 10),
      decoration: BoxDecoration(
        color: AppColors.surface,
        border: Border(bottom: BorderSide(color: AppColors.border)),
      ),
      child: Row(
        children: <Widget>[
          Text(title, style: Theme.of(context).textTheme.titleLarge),
          const SizedBox(width: 14),
          StatusChip(
            label: engine.globalEStop ? '비상정지' : '정상 운영',
            color: engine.globalEStop ? AppColors.critical : AppColors.good,
            icon: engine.globalEStop
                ? Icons.pan_tool_outlined
                : Icons.check_circle_outline,
          ),
          const Spacer(),
          Row(
            children: <Widget>[
              const Icon(Icons.schedule, size: 14, color: AppColors.muted),
              const SizedBox(width: 5),
              Text(
                engine.timeLabel(engine.simNow),
                style: const TextStyle(
                  color: AppColors.textPrimary,
                  fontSize: 13,
                  fontFeatures: <FontFeature>[FontFeature.tabularFigures()],
                ),
              ),
            ],
          ),
          const SizedBox(width: 14),
          _SpeedControl(engine: engine),
          const SizedBox(width: 8),
          IconButton(
            tooltip: engine.paused ? '시뮬레이션 재개' : '시뮬레이션 일시정지',
            onPressed: () => engine.setPaused(!engine.paused),
            icon: Icon(
              engine.paused ? Icons.play_arrow : Icons.pause,
              size: 18,
              color: AppColors.textSecondary,
            ),
          ),
          const SizedBox(width: 4),
          FilledButton.icon(
            onPressed: engine.toggleGlobalEStop,
            style: FilledButton.styleFrom(
              backgroundColor: engine.globalEStop
                  ? AppColors.good
                  : AppColors.critical,
              foregroundColor: Colors.white,
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(7),
              ),
            ),
            icon: Icon(
              engine.globalEStop ? Icons.restart_alt : Icons.pan_tool,
              size: 15,
            ),
            label: Text(
              engine.globalEStop ? '비상정지 해제' : '전체 비상정지',
              style: const TextStyle(
                fontSize: 12.5,
                fontWeight: FontWeight.w700,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _SpeedControl extends StatelessWidget {
  const _SpeedControl({required this.engine});

  final FleetEngine engine;

  @override
  Widget build(BuildContext context) {
    const speeds = <double>[1, 2, 4, 8];
    final locked = engine.realTimeLocked;
    final current = engine.effectiveSpeedMultiplier;

    return Tooltip(
      message: locked
          ? '현장 로봇 ${engine.link.linkedCount}대 연동 중 — 실장비는 실시간으로 '
                '움직이므로 배속을 1×로 고정합니다.'
          : '시뮬레이션 배속',
      child: Container(
        decoration: BoxDecoration(
          color: AppColors.page,
          borderRadius: BorderRadius.circular(7),
          border: Border.all(
            color: locked ? AppColors.warning.withValues(alpha: 0.6) : AppColors.border,
          ),
        ),
        padding: const EdgeInsets.all(2),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            if (locked)
              const Padding(
                padding: EdgeInsets.only(left: 5, right: 2),
                child: Icon(Icons.lock_clock, size: 13, color: AppColors.warning),
              ),
            for (final s in speeds)
              InkWell(
                onTap: locked ? null : () => engine.setSpeed(s),
                child: Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 9,
                    vertical: 5,
                  ),
                  decoration: BoxDecoration(
                    color: current == s
                        ? AppColors.series1.withValues(alpha: 0.2)
                        : Colors.transparent,
                    borderRadius: BorderRadius.circular(5),
                  ),
                  child: Text(
                    '${s.toStringAsFixed(0)}×',
                    style: TextStyle(
                      color: current == s
                          ? AppColors.textPrimary
                          : AppColors.muted,
                      fontSize: 11.5,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

class _IncidentBanner extends StatelessWidget {
  const _IncidentBanner({required this.engine});

  final FleetEngine engine;

  @override
  Widget build(BuildContext context) {
    final incident = engine.activeIncidents.first;
    final color = AppColors.severityColor(incident.type.severity);
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 9),
      color: color.withValues(alpha: 0.16),
      child: Row(
        children: <Widget>[
          Icon(AppColors.severityIcon(incident.type.severity), size: 16, color: color),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              '[${incident.type.label}] ${incident.description} · 자동 대응 ${incident.actions.length}건 실행 중'
              '${engine.activeIncidents.length > 1 ? " (외 ${engine.activeIncidents.length - 1}건 진행)" : ""}',
              style: TextStyle(
                color: color,
                fontSize: 12.5,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
          TextButton(
            onPressed: () => engine.clearIncident(incident.id),
            child: const Text('상황 해제', style: TextStyle(fontSize: 12)),
          ),
        ],
      ),
    );
  }
}
