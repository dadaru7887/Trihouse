import 'package:flutter/material.dart';

import 'package:robo_core/models/enums.dart';
import 'package:robo_core/models/inventory.dart';
import '../app_shell.dart';
import '../theme.dart';
import '../../core/fleet_engine.dart';
import '../widgets/common.dart';
import '../widgets/operations_dialogs.dart';

/// 재고 · FEFO: 유통기한 임박 순 정렬과 출고 우선순위 근거를 제공한다.
class InventoryPage extends StatefulWidget {
  const InventoryPage({super.key});

  @override
  State<InventoryPage> createState() => _InventoryPageState();
}

class _InventoryPageState extends State<InventoryPage> {
  TempZone? _zone;

  @override
  Widget build(BuildContext context) {
    final engine = EngineScope.of(context);
    final list = engine.lots
        .where((l) => (_zone == null || l.zone == _zone) && l.qty > 0)
        .toList()
      ..sort((a, b) => a.expiry.compareTo(b.expiry));

    final urgent = list
        .where((l) => l.daysToExpiry(engine.simNow) <= 3)
        .toList();

    return Row(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: <Widget>[
        Expanded(
          child: Panel(
            title: 'FEFO 재고 목록',
            subtitle:
                '유통기한 임박 순 정렬 · 행을 클릭하면 재고를 조정합니다 (${list.length}개 로트)',
            trailing: Row(
              mainAxisSize: MainAxisSize.min,
              children: <Widget>[
                _ZoneFilter(
                  label: '전체',
                  selected: _zone == null,
                  color: AppColors.textSecondary,
                  onTap: () => setState(() => _zone = null),
                ),
                for (final z in TempZone.values)
                  _ZoneFilter(
                    label: z.label,
                    selected: _zone == z,
                    color: AppColors.zoneColor(z),
                    onTap: () => setState(() => _zone = z),
                  ),
              ],
            ),
            child: _LotTable(engine: engine, lots: list),
          ),
        ),
        const SizedBox(width: 12),
        SizedBox(
          width: 330,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: <Widget>[
              Panel(
                title: 'FEFO 운영 지표',
                child: Column(
                  children: <Widget>[
                    KeyValueRow(
                      'FEFO 준수율',
                      '${(engine.fefoCompliance * 100).toStringAsFixed(1)}%',
                      valueColor: engine.fefoCompliance >= 0.95
                          ? AppColors.good
                          : AppColors.warning,
                    ),
                    KeyValueRow('1순위 로트 출고', '${engine.fefoPicks}건'),
                    KeyValueRow(
                      '차순위 대체(이탈)',
                      '${engine.fefoDeviations}건',
                      valueColor: AppColors.warning,
                    ),
                    KeyValueRow('D-3 이내 로트', '${urgent.length}개'),
                    const SizedBox(height: 8),
                    const Text(
                      'FEFO 1순위 로트가 다른 로봇에 점유되어 있으면 차순위 로트를 사용하고, '
                      '그 사유를 이력에 남겨 이탈로 집계합니다.',
                      style: TextStyle(
                        color: AppColors.muted,
                        fontSize: 11,
                        height: 1.45,
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 12),
              Expanded(
                child: Panel(
                  title: '유통기한 임박 로트',
                  subtitle: 'D-3 이내 · 최우선 출고/회수 대상',
                  child: urgent.isEmpty
                      ? const EmptyHint('임박 로트가 없습니다.')
                      : ListView.builder(
                          padding: EdgeInsets.zero,
                          itemCount: urgent.length,
                          itemBuilder: (context, i) {
                            final l = urgent[i];
                            final d = l.daysToExpiry(engine.simNow);
                            return Padding(
                              padding: const EdgeInsets.only(bottom: 9),
                              child: Row(
                                children: <Widget>[
                                  Icon(
                                    d <= 0
                                        ? Icons.dangerous_outlined
                                        : Icons.schedule_outlined,
                                    size: 13,
                                    color: d <= 0
                                        ? AppColors.critical
                                        : AppColors.serious,
                                  ),
                                  const SizedBox(width: 7),
                                  Expanded(
                                    child: Column(
                                      crossAxisAlignment: CrossAxisAlignment.start,
                                      children: <Widget>[
                                        Text(
                                          l.name,
                                          style: const TextStyle(
                                            color: AppColors.textPrimary,
                                            fontSize: 11.5,
                                          ),
                                        ),
                                        Text(
                                          '${l.id} · ${l.locationId} · 잔량 ${l.available}',
                                          style: const TextStyle(
                                            color: AppColors.muted,
                                            fontSize: 10.5,
                                          ),
                                        ),
                                      ],
                                    ),
                                  ),
                                  Text(
                                    d <= 0 ? '경과' : 'D-$d',
                                    style: TextStyle(
                                      color: d <= 0
                                          ? AppColors.critical
                                          : AppColors.serious,
                                      fontSize: 11.5,
                                      fontWeight: FontWeight.w600,
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
    );
  }
}

class _ZoneFilter extends StatelessWidget {
  const _ZoneFilter({
    required this.label,
    required this.selected,
    required this.color,
    required this.onTap,
  });

  final String label;
  final bool selected;
  final Color color;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(left: 5),
    child: InkWell(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 5),
        decoration: BoxDecoration(
          color: selected ? color.withValues(alpha: 0.18) : Colors.transparent,
          borderRadius: BorderRadius.circular(5),
          border: Border.all(
            color: selected ? color.withValues(alpha: 0.55) : AppColors.border,
          ),
        ),
        child: Text(
          label,
          style: TextStyle(
            color: selected ? AppColors.textPrimary : AppColors.muted,
            fontSize: 11,
          ),
        ),
      ),
    ),
  );
}

class _LotTable extends StatelessWidget {
  const _LotTable({required this.engine, required this.lots});

  final FleetEngine engine;
  final List<Lot> lots;

  DateTime get now => engine.simNow;

  @override
  Widget build(BuildContext context) {
    if (lots.isEmpty) return const EmptyHint('표시할 재고가 없습니다.');

    Widget head(String t, double w) => SizedBox(
      width: w,
      child: Text(
        t,
        style: const TextStyle(
          color: AppColors.muted,
          fontSize: 10.5,
          fontWeight: FontWeight.w600,
        ),
      ),
    );

    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: SizedBox(
        width: 860,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: <Widget>[
            Row(
              children: <Widget>[
                head('FEFO 순위', 62),
                head('로트', 84),
                head('SKU', 66),
                head('상품', 160),
                head('구획', 50),
                head('로케이션', 86),
                head('가용/총', 74),
                head('유통기한', 92),
                head('잔여', 52),
                head('임박도', 110),
              ],
            ),
            Divider(height: 10, color: AppColors.border),
            Expanded(
              child: ListView.builder(
                padding: EdgeInsets.zero,
                itemCount: lots.length,
                itemBuilder: (context, i) {
                  final l = lots[i];
                  final d = l.daysToExpiry(now);
                  final pressure = l.expiryPressure(now);
                  final pColor = d <= 0
                      ? AppColors.critical
                      : (d <= 3
                            ? AppColors.serious
                            : (d <= 10 ? AppColors.warning : AppColors.good));
                  return InkWell(
                    onTap: () =>
                        AdjustStockDialog.show(context, engine, l),
                    child: Padding(
                    padding: const EdgeInsets.symmetric(vertical: 4.5),
                    child: Row(
                      children: <Widget>[
                        SizedBox(
                          width: 62,
                          child: Text(
                            '${i + 1}',
                            style: TextStyle(
                              color: i < 3
                                  ? AppColors.textPrimary
                                  : AppColors.muted,
                              fontSize: 11.5,
                              fontWeight: i < 3 ? FontWeight.w700 : FontWeight.w400,
                              fontFeatures: const <FontFeature>[
                                FontFeature.tabularFigures(),
                              ],
                            ),
                          ),
                        ),
                        _cell(l.id, 84, color: AppColors.textPrimary),
                        _cell(l.sku, 66),
                        _cell(l.name, 160),
                        SizedBox(
                          width: 50,
                          child: Text(
                            l.zone.label,
                            style: TextStyle(
                              color: AppColors.zoneColor(l.zone),
                              fontSize: 11,
                            ),
                          ),
                        ),
                        _cell(l.locationId, 86),
                        _cell('${l.available}/${l.qty}', 74),
                        _cell(
                          '${l.expiry.year}-${l.expiry.month.toString().padLeft(2, "0")}-${l.expiry.day.toString().padLeft(2, "0")}',
                          92,
                        ),
                        SizedBox(
                          width: 52,
                          child: Text(
                            d <= 0 ? '경과' : 'D-$d',
                            style: TextStyle(
                              color: pColor,
                              fontSize: 11,
                              fontWeight: FontWeight.w600,
                            ),
                          ),
                        ),
                        SizedBox(
                          width: 110,
                          child: Row(
                            children: <Widget>[
                              Expanded(
                                child: MeterBar(
                                  value: pressure,
                                  color: pColor,
                                  height: 5,
                                ),
                              ),
                              const SizedBox(width: 6),
                              Text(
                                (pressure * 100).toStringAsFixed(0),
                                style: const TextStyle(
                                  color: AppColors.muted,
                                  fontSize: 10,
                                  fontFeatures: <FontFeature>[
                                    FontFeature.tabularFigures(),
                                  ],
                                ),
                              ),
                            ],
                          ),
                        ),
                      ],
                    ),
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

  Widget _cell(String text, double w, {Color? color}) => SizedBox(
    width: w,
    child: Text(
      text,
      maxLines: 1,
      overflow: TextOverflow.ellipsis,
      style: TextStyle(
        color: color ?? AppColors.textSecondary,
        fontSize: 11.5,
        fontFeatures: const <FontFeature>[FontFeature.tabularFigures()],
      ),
    ),
  );
}
