import 'package:flutter/material.dart';

import 'package:robo_core/models/enums.dart';
import 'package:robo_core/models/warehouse.dart';
import '../app_shell.dart';
import '../theme.dart';
import '../widgets/common.dart';
import '../widgets/robot_detail.dart';
import '../widgets/robot_row.dart';
import '../widgets/warehouse_map.dart';

/// 실시간 평면도: 로봇 위치·경로·작업자 안전 필드·안전 상황 반경.
class MapPage extends StatelessWidget {
  const MapPage({super.key});

  @override
  Widget build(BuildContext context) {
    final engine = EngineScope.of(context);
    final selected = engine.selectedRobot;

    return Row(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: <Widget>[
        Expanded(
          child: Panel(
            title: '물류센터 실시간 평면도',
            subtitle: '로봇을 클릭하면 상세 상태와 주행 궤적을 확인할 수 있습니다',
            trailing: const _MapLegend(),
            padding: const EdgeInsets.fromLTRB(12, 12, 12, 12),
            child: WarehouseMap(engine: engine),
          ),
        ),
        const SizedBox(width: 12),
        SizedBox(
          width: 330,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: <Widget>[
              Expanded(
                flex: 3,
                child: Panel(
                  title: selected == null ? '로봇 상세' : '로봇 상세 · ${selected.id}',
                  subtitle: selected == null ? '지도에서 로봇을 선택하세요' : null,
                  child: selected == null
                      ? const EmptyHint('선택된 로봇이 없습니다.')
                      : RobotDetail(engine: engine, robot: selected),
                ),
              ),
              const SizedBox(height: 12),
              Expanded(
                flex: 2,
                child: Panel(
                  title: '로봇 목록',
                  subtitle: '${engine.robots.length}대 등록',
                  child: ListView(
                    padding: EdgeInsets.zero,
                    children: <Widget>[
                      for (final r in engine.robots)
                        RobotRow(
                          robot: r,
                          engine: engine,
                          showActivity: false,
                          compact: true,
                        ),
                    ],
                  ),
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _MapLegend extends StatelessWidget {
  const _MapLegend();

  @override
  Widget build(BuildContext context) {
    Widget dot(Color c, String label) => Row(
      mainAxisSize: MainAxisSize.min,
      children: <Widget>[
        Container(
          width: 8,
          height: 8,
          decoration: BoxDecoration(color: c, borderRadius: BorderRadius.circular(2)),
        ),
        const SizedBox(width: 4),
        Text(label, style: const TextStyle(color: AppColors.muted, fontSize: 10.5)),
      ],
    );

    return Wrap(
      spacing: 10,
      runSpacing: 4,
      alignment: WrapAlignment.end,
      children: <Widget>[
        for (final z in TempZone.values) dot(AppColors.zoneColor(z), z.label),
        dot(AppColors.ink(AppColors.series3), StationKind.inboundDock.label),
        dot(AppColors.ink(AppColors.series2), StationKind.outboundDock.label),
        dot(AppColors.ink(AppColors.series7), StationKind.charger.label),
        dot(AppColors.ink(AppColors.series5), '작업자'),
        dot(AppColors.ink(AppColors.good), StationKind.assembly.label),
      ],
    );
  }
}
