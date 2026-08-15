import 'package:flutter/material.dart';

import '../../core/fleet_engine.dart';
import 'package:robo_core/data/repositories.dart';
import 'package:robo_core/models/enums.dart';
import 'package:robo_core/models/inventory.dart';
import '../theme.dart';
import 'common.dart';

InputDecoration _dec(String hint) => InputDecoration(
  hintText: hint,
  hintStyle: const TextStyle(color: AppColors.muted, fontSize: 12),
  isDense: true,
  contentPadding: const EdgeInsets.symmetric(horizontal: 10, vertical: 9),
  filled: true,
  fillColor: AppColors.page,
  enabledBorder: OutlineInputBorder(
    borderRadius: BorderRadius.circular(6),
    borderSide: BorderSide(color: AppColors.border),
  ),
  focusedBorder: OutlineInputBorder(
    borderRadius: BorderRadius.circular(6),
    borderSide: BorderSide(color: AppColors.series1.withValues(alpha: 0.7)),
  ),
);

Widget _shell({
  required BuildContext context,
  required String title,
  required IconData icon,
  required Color accent,
  required Widget body,
  required List<Widget> actions,
  double width = 560,
}) {
  return Dialog(
    backgroundColor: AppColors.surface,
    shape: RoundedRectangleBorder(
      borderRadius: BorderRadius.circular(10),
      side: BorderSide(color: AppColors.border),
    ),
    child: Container(
      width: width,
      constraints: const BoxConstraints(maxHeight: 620),
      padding: const EdgeInsets.all(18),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          Row(
            children: <Widget>[
              Icon(icon, size: 16, color: accent),
              const SizedBox(width: 8),
              Text(
                title,
                style: const TextStyle(
                  color: AppColors.textPrimary,
                  fontSize: 15,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ],
          ),
          const SizedBox(height: 14),
          Flexible(child: SingleChildScrollView(child: body)),
          const SizedBox(height: 16),
          Row(mainAxisAlignment: MainAxisAlignment.end, children: actions),
        ],
      ),
    ),
  );
}

class _OrderLineDraft {
  String sku = 'SKU-A1';
  int qty = 1;
  String? lotId;
}

/// 관제에서 출고 주문을 직접 접수하는 대화상자.
class CreateOrderDialog extends StatefulWidget {
  const CreateOrderDialog({super.key, required this.engine});

  final FleetEngine engine;

  static Future<void> show(BuildContext context, FleetEngine engine) =>
      showDialog<void>(
        context: context,
        builder: (_) => CreateOrderDialog(engine: engine),
      );

  @override
  State<CreateOrderDialog> createState() => _CreateOrderDialogState();
}

class _CreateOrderDialogState extends State<CreateOrderDialog> {
  final TextEditingController _customer = TextEditingController();
  Urgency _urgency = Urgency.normal;
  int _dueMinutes = 45;
  final List<_OrderLineDraft> _lines = <_OrderLineDraft>[_OrderLineDraft()];

  @override
  void dispose() {
    _customer.dispose();
    super.dispose();
  }

  int get _totalQty => _lines.fold(0, (a, l) => a + l.qty);

  bool get _valid =>
      _lines.isNotEmpty &&
      _lines.every((l) => l.qty > 0 && widget.engine.availableOf(l.sku) >= 0);

  @override
  Widget build(BuildContext context) {
    final engine = widget.engine;
    return _shell(
      context: context,
      title: '주문 접수',
      icon: Icons.add_shopping_cart_outlined,
      accent: AppColors.series1,
      body: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        mainAxisSize: MainAxisSize.min,
        children: <Widget>[
          Row(
            children: <Widget>[
              SizedBox(
                width: 74,
                child: Text('고객', style: _labelStyle),
              ),
              Expanded(
                child: TextField(
                  controller: _customer,
                  autofocus: true,
                  style: const TextStyle(
                    color: AppColors.textPrimary,
                    fontSize: 12.5,
                  ),
                  decoration: _dec('예: 강남 스토어'),
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          Row(
            children: <Widget>[
              SizedBox(width: 74, child: Text('긴급도', style: _labelStyle)),
              Expanded(
                child: Wrap(
                  spacing: 6,
                  children: <Widget>[
                    for (final u in Urgency.values)
                      _chip(
                        u.label,
                        _urgency == u,
                        AppColors.urgencyColor(u),
                        () => setState(() {
                          _urgency = u;
                          _dueMinutes = switch (u) {
                            Urgency.critical => 12,
                            Urgency.high => 25,
                            Urgency.normal => 45,
                            Urgency.low => 90,
                          };
                        }),
                      ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          Row(
            children: <Widget>[
              SizedBox(width: 74, child: Text('납기', style: _labelStyle)),
              Expanded(
                child: Wrap(
                  spacing: 6,
                  children: <Widget>[
                    for (final m in <int>[12, 25, 45, 90, 180])
                      _chip(
                        '$m분',
                        _dueMinutes == m,
                        AppColors.series1,
                        () => setState(() => _dueMinutes = m),
                      ),
                  ],
                ),
              ),
            ],
          ),
          const Divider(height: 22, color: AppColors.grid),
          Row(
            children: <Widget>[
              Text('주문 라인', style: _labelStyle),
              const Spacer(),
              TextButton.icon(
                onPressed: () =>
                    setState(() => _lines.add(_OrderLineDraft())),
                style: TextButton.styleFrom(
                  foregroundColor: AppColors.series1,
                  minimumSize: Size.zero,
                  padding: const EdgeInsets.symmetric(horizontal: 8),
                  tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                ),
                icon: const Icon(Icons.add, size: 14),
                label: const Text('라인 추가', style: TextStyle(fontSize: 11.5)),
              ),
            ],
          ),
          const SizedBox(height: 8),
          for (var i = 0; i < _lines.length; i++) _lineRow(engine, i),
          const SizedBox(height: 8),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 9),
            decoration: BoxDecoration(
              color: AppColors.page,
              borderRadius: BorderRadius.circular(6),
              border: Border.all(color: AppColors.border),
            ),
            child: Row(
              children: <Widget>[
                const Icon(
                  Icons.inventory_2_outlined,
                  size: 13,
                  color: AppColors.muted,
                ),
                const SizedBox(width: 7),
                Expanded(
                  child: Text(
                    '로트를 지정하지 않으면 FEFO 1순위 로트가 자동 선택됩니다. '
                    '지정한 경우 그 사유가 FEFO 이탈로 이력에 남습니다. '
                    '총 $_totalQty개 · 라인 ${_lines.length}건.',
                    style: const TextStyle(
                      color: AppColors.muted,
                      fontSize: 11,
                      height: 1.4,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
      actions: <Widget>[
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('취소', style: TextStyle(fontSize: 12)),
        ),
        const SizedBox(width: 6),
        FilledButton(
          onPressed: _valid
              ? () {
                  engine.createOrder(
                    customer: _customer.text,
                    urgency: _urgency,
                    dueIn: Duration(minutes: _dueMinutes),
                    lines: _lines
                        .map(
                          (l) => (sku: l.sku, qty: l.qty, lotId: l.lotId),
                        )
                        .toList(),
                  );
                  Navigator.of(context).pop();
                }
              : null,
          style: FilledButton.styleFrom(
            backgroundColor: AppColors.series1,
            foregroundColor: Colors.white,
          ),
          child: const Text('접수', style: TextStyle(fontSize: 12)),
        ),
      ],
    );
  }

  Widget _lineRow(FleetEngine engine, int i) {
    final line = _lines[i];
    final available = engine.availableOf(line.sku);
    final lots = engine.availableLots(line.sku);
    final shortage = line.qty > available;

    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.fromLTRB(10, 9, 6, 9),
      decoration: BoxDecoration(
        color: AppColors.page.withValues(alpha: 0.6),
        borderRadius: BorderRadius.circular(7),
        border: Border.all(
          color: shortage
              ? AppColors.serious.withValues(alpha: 0.5)
              : AppColors.border,
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            children: <Widget>[
              Expanded(
                child: DropdownButtonHideUnderline(
                  child: DropdownButton<String>(
                    value: line.sku,
                    isDense: true,
                    dropdownColor: AppColors.surfaceRaised,
                    style: DefaultTextStyle.of(context).style.copyWith(
                      color: AppColors.textPrimary,
                      fontSize: 12,
                    ),
                    items: <DropdownMenuItem<String>>[
                      for (final c in FleetEngine.catalogSkus)
                        DropdownMenuItem<String>(
                          value: c[0],
                          child: Text('${c[0]} · ${c[1]}'),
                        ),
                    ],
                    onChanged: (v) => setState(() {
                      line.sku = v!;
                      line.lotId = null;
                    }),
                  ),
                ),
              ),
              const SizedBox(width: 8),
              SizedBox(
                width: 66,
                child: TextField(
                  controller: TextEditingController(text: '${line.qty}'),
                  textAlign: TextAlign.right,
                  keyboardType: TextInputType.number,
                  style: const TextStyle(
                    color: AppColors.textPrimary,
                    fontSize: 12.5,
                  ),
                  decoration: _dec('수량'),
                  onChanged: (v) =>
                      setState(() => line.qty = int.tryParse(v) ?? 0),
                ),
              ),
              IconButton(
                tooltip: '라인 삭제',
                onPressed: _lines.length == 1
                    ? null
                    : () => setState(() => _lines.removeAt(i)),
                padding: EdgeInsets.zero,
                constraints: const BoxConstraints.tightFor(
                  width: 30,
                  height: 30,
                ),
                icon: const Icon(Icons.close, size: 14, color: AppColors.muted),
              ),
            ],
          ),
          const SizedBox(height: 6),
          Row(
            children: <Widget>[
              Text(
                '가용 $available개',
                style: TextStyle(
                  color: shortage ? AppColors.serious : AppColors.muted,
                  fontSize: 11,
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: DropdownButtonHideUnderline(
                  child: DropdownButton<String?>(
                    value: line.lotId,
                    isDense: true,
                    isExpanded: true,
                    dropdownColor: AppColors.surfaceRaised,
                    style: DefaultTextStyle.of(context).style.copyWith(
                      color: AppColors.textSecondary,
                      fontSize: 11.5,
                    ),
                    hint: const Text(
                      'FEFO 자동 선택',
                      style: TextStyle(color: AppColors.muted, fontSize: 11.5),
                    ),
                    items: <DropdownMenuItem<String?>>[
                      const DropdownMenuItem<String?>(
                        child: Text('FEFO 자동 선택'),
                      ),
                      for (var k = 0; k < lots.length; k++)
                        DropdownMenuItem<String?>(
                          value: lots[k].id,
                          child: Text(
                            '${k == 0 ? "① " : ""}${lots[k].id} · '
                            'D-${lots[k].daysToExpiry(widget.engine.simNow)} · '
                            '가용 ${lots[k].available}',
                          ),
                        ),
                    ],
                    onChanged: (v) => setState(() => line.lotId = v),
                  ),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  static const TextStyle _labelStyle = TextStyle(
    color: AppColors.muted,
    fontSize: 11.5,
  );

  Widget _chip(String label, bool selected, Color color, VoidCallback onTap) =>
      InkWell(
        onTap: onTap,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 6),
          decoration: BoxDecoration(
            color: selected ? color.withValues(alpha: 0.14) : Colors.transparent,
            borderRadius: BorderRadius.circular(5),
            border: Border.all(
              color: selected ? color.withValues(alpha: 0.55) : AppColors.border,
            ),
          ),
          child: Text(
            label,
            style: TextStyle(
              color: selected ? AppColors.textPrimary : AppColors.muted,
              fontSize: 11.5,
              fontWeight: selected ? FontWeight.w600 : FontWeight.w400,
            ),
          ),
        ),
      );
}

/// 로트 재고 조정 대화상자.
class AdjustStockDialog extends StatefulWidget {
  const AdjustStockDialog({super.key, required this.engine, required this.lot});

  final FleetEngine engine;
  final Lot lot;

  static Future<void> show(BuildContext context, FleetEngine engine, Lot lot) =>
      showDialog<void>(
        context: context,
        builder: (_) => AdjustStockDialog(engine: engine, lot: lot),
      );

  @override
  State<AdjustStockDialog> createState() => _AdjustStockDialogState();
}

class _AdjustStockDialogState extends State<AdjustStockDialog> {
  final TextEditingController _note = TextEditingController();
  final TextEditingController _counted = TextEditingController();
  StockMoveReason _reason = StockMoveReason.cycleCount;
  int _delta = 0;

  @override
  void dispose() {
    _note.dispose();
    _counted.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final lot = widget.lot;
    final after = lot.qty + _delta;
    final invalid = after < 0 || after < lot.reserved;
    final moves = widget.engine.stockMoves(limit: 8, lotId: lot.id);

    return _shell(
      context: context,
      title: '재고 조정 · ${lot.id}',
      icon: Icons.tune,
      accent: AppColors.series4,
      width: 520,
      body: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        mainAxisSize: MainAxisSize.min,
        children: <Widget>[
          KeyValueRow('품목', '${lot.sku} · ${lot.name}'),
          KeyValueRow('로케이션', lot.locationId),
          KeyValueRow('현재 수량', '${lot.qty}개 (예약 ${lot.reserved} · 가용 ${lot.available})'),
          KeyValueRow('유통기한', widget.engine.dateLabel(lot.expiry)),
          const Divider(height: 20, color: AppColors.grid),
          Text('조정 사유', style: _label),
          const SizedBox(height: 6),
          Wrap(
            spacing: 6,
            runSpacing: 6,
            children: <Widget>[
              for (final r in <StockMoveReason>[
                StockMoveReason.cycleCount,
                StockMoveReason.adjustment,
                StockMoveReason.disposal,
                StockMoveReason.inbound,
              ])
                InkWell(
                  onTap: () => setState(() => _reason = r),
                  child: Container(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 9,
                      vertical: 6,
                    ),
                    decoration: BoxDecoration(
                      color: _reason == r
                          ? AppColors.series4.withValues(alpha: 0.14)
                          : Colors.transparent,
                      borderRadius: BorderRadius.circular(5),
                      border: Border.all(
                        color: _reason == r
                            ? AppColors.series4.withValues(alpha: 0.55)
                            : AppColors.border,
                      ),
                    ),
                    child: Text(
                      r.label,
                      style: TextStyle(
                        color: _reason == r
                            ? AppColors.textPrimary
                            : AppColors.muted,
                        fontSize: 11.5,
                      ),
                    ),
                  ),
                ),
            ],
          ),
          const SizedBox(height: 14),
          Row(
            children: <Widget>[
              SizedBox(width: 74, child: Text('실사 수량', style: _label)),
              SizedBox(
                width: 84,
                child: TextField(
                  controller: _counted,
                  textAlign: TextAlign.right,
                  keyboardType: TextInputType.number,
                  style: const TextStyle(
                    color: AppColors.textPrimary,
                    fontSize: 12.5,
                  ),
                  decoration: _dec('${lot.qty}'),
                  onChanged: (v) {
                    final counted = int.tryParse(v);
                    setState(() => _delta = counted == null ? 0 : counted - lot.qty);
                  },
                ),
              ),
              const SizedBox(width: 12),
              Text('또는 증감', style: _label),
              const SizedBox(width: 8),
              _step(-10),
              _step(-1),
              Container(
                width: 56,
                alignment: Alignment.center,
                child: Text(
                  _delta > 0 ? '+$_delta' : '$_delta',
                  style: TextStyle(
                    color: _delta == 0
                        ? AppColors.muted
                        : (_delta > 0
                              ? AppColors.ink(AppColors.good)
                              : AppColors.ink(AppColors.serious)),
                    fontSize: 14,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
              _step(1),
              _step(10),
            ],
          ),
          const SizedBox(height: 10),
          Row(
            children: <Widget>[
              SizedBox(width: 74, child: Text('메모', style: _label)),
              Expanded(
                child: TextField(
                  controller: _note,
                  style: const TextStyle(
                    color: AppColors.textPrimary,
                    fontSize: 12.5,
                  ),
                  decoration: _dec('예: 월말 실사 차이, 파손 폐기'),
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 9),
            decoration: BoxDecoration(
              color: invalid
                  ? AppColors.critical.withValues(alpha: 0.10)
                  : AppColors.page,
              borderRadius: BorderRadius.circular(6),
              border: Border.all(
                color: invalid
                    ? AppColors.critical.withValues(alpha: 0.45)
                    : AppColors.border,
              ),
            ),
            child: Text(
              invalid
                  ? '조정 후 수량 $after개는 예약 수량 ${lot.reserved}개보다 적어 반영할 수 없습니다.'
                  : '조정 후 수량 $after개 (가용 ${after - lot.reserved}개). '
                        '변경 내역은 재고 원장에 기록됩니다.',
              style: TextStyle(
                color: invalid ? AppColors.ink(AppColors.critical) : AppColors.muted,
                fontSize: 11.5,
                height: 1.4,
              ),
            ),
          ),
          if (moves.isNotEmpty) ...<Widget>[
            const Divider(height: 22, color: AppColors.grid),
            Text('최근 재고 이동', style: _label),
            const SizedBox(height: 6),
            for (final m in moves)
              Padding(
                padding: const EdgeInsets.only(bottom: 4),
                child: Row(
                  children: <Widget>[
                    SizedBox(
                      width: 62,
                      child: Text(
                        widget.engine.timeLabel(m.at),
                        style: const TextStyle(
                          color: AppColors.muted,
                          fontSize: 10.5,
                        ),
                      ),
                    ),
                    SizedBox(
                      width: 62,
                      child: Text(
                        m.reason.label,
                        style: const TextStyle(
                          color: AppColors.textSecondary,
                          fontSize: 10.5,
                        ),
                      ),
                    ),
                    SizedBox(
                      width: 46,
                      child: Text(
                        m.delta > 0 ? '+${m.delta}' : '${m.delta}',
                        textAlign: TextAlign.right,
                        style: TextStyle(
                          color: m.delta > 0
                              ? AppColors.ink(AppColors.good)
                              : AppColors.ink(AppColors.serious),
                          fontSize: 10.5,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Text(
                        '→ ${m.qtyAfter}개'
                        '${m.note == null ? "" : " · ${m.note}"}'
                        '${m.taskId == null ? "" : " · ${m.taskId}"}',
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                          color: AppColors.muted,
                          fontSize: 10.5,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
          ],
        ],
      ),
      actions: <Widget>[
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('취소', style: TextStyle(fontSize: 12)),
        ),
        const SizedBox(width: 6),
        FilledButton(
          onPressed: (_delta == 0 || invalid)
              ? null
              : () {
                  widget.engine.adjustStock(
                    lotId: lot.id,
                    delta: _delta,
                    reason: _reason,
                    note: _note.text.trim().isEmpty ? null : _note.text.trim(),
                  );
                  Navigator.of(context).pop();
                },
          style: FilledButton.styleFrom(
            backgroundColor: AppColors.ink(AppColors.series4),
            foregroundColor: Colors.white,
          ),
          child: const Text('조정 반영', style: TextStyle(fontSize: 12)),
        ),
      ],
    );
  }

  static const TextStyle _label = TextStyle(
    color: AppColors.muted,
    fontSize: 11.5,
  );

  Widget _step(int by) => InkWell(
    onTap: () => setState(() {
      _delta += by;
      _counted.text = '${widget.lot.qty + _delta}';
    }),
    child: Container(
      margin: const EdgeInsets.symmetric(horizontal: 2),
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 5),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(5),
        border: Border.all(color: AppColors.border),
      ),
      child: Text(
        by > 0 ? '+$by' : '$by',
        style: const TextStyle(color: AppColors.textSecondary, fontSize: 11),
      ),
    ),
  );
}
