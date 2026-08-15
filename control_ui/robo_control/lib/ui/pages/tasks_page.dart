import 'package:flutter/material.dart';

import '../../core/fleet_engine.dart';
import 'package:robo_core/models/enums.dart';
import 'package:robo_core/models/task.dart';
import '../app_shell.dart';
import '../theme.dart';
import '../widgets/common.dart';
import '../widgets/operations_dialogs.dart';

/// 태스크·주문 관제: 스케줄링 결과, 진행 상태, 성공·실패 기록.
class TasksPage extends StatefulWidget {
  const TasksPage({super.key});

  @override
  State<TasksPage> createState() => _TasksPageState();
}

class _TasksPageState extends State<TasksPage> {
  String _filter = '진행';

  static const List<String> _filters = <String>[
    '진행',
    '대기',
    '완료',
    '실패',
    '전체',
  ];

  bool _match(WorkTask t) => switch (_filter) {
    '대기' => t.state == TaskState.pending || t.state == TaskState.blocked,
    '진행' =>
      t.state == TaskState.inProgress ||
          t.state == TaskState.claimed ||
          t.state == TaskState.pending,
    '완료' => t.state == TaskState.done,
    '실패' => t.state == TaskState.failed || t.state == TaskState.cancelled,
    _ => true,
  };

  @override
  Widget build(BuildContext context) {
    final engine = EngineScope.of(context);
    final list = <WorkTask>[];
    for (final id in engine.taskOrder) {
      final t = engine.tasks[id];
      if (t != null && _match(t)) list.add(t);
      if (list.length >= 120) break;
    }
    if (_filter == '진행' || _filter == '대기') {
      list.sort((a, b) => b.score.compareTo(a.score));
    }

    return Row(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: <Widget>[
        Expanded(
          child: Panel(
            title: '태스크 대기열',
            subtitle:
                'FEFO · 긴급도 · 이동 동선 · 대기시간 가중 합산 우선순위 (${list.length}건 표시)',
            trailing: Row(
              mainAxisSize: MainAxisSize.min,
              children: <Widget>[
                for (final f in _filters)
                  Padding(
                    padding: const EdgeInsets.only(left: 5),
                    child: InkWell(
                      onTap: () => setState(() => _filter = f),
                      child: Container(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 9,
                          vertical: 5,
                        ),
                        decoration: BoxDecoration(
                          color: _filter == f
                              ? AppColors.series1.withValues(alpha: 0.18)
                              : Colors.transparent,
                          borderRadius: BorderRadius.circular(5),
                          border: Border.all(
                            color: _filter == f
                                ? AppColors.series1.withValues(alpha: 0.5)
                                : AppColors.border,
                          ),
                        ),
                        child: Text(
                          f,
                          style: TextStyle(
                            color: _filter == f
                                ? AppColors.textPrimary
                                : AppColors.muted,
                            fontSize: 11,
                          ),
                        ),
                      ),
                    ),
                  ),
              ],
            ),
            child: _TaskTable(engine: engine, tasks: list),
          ),
        ),
        const SizedBox(width: 12),
        SizedBox(
          width: 330,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: <Widget>[
              Panel(
                title: '주문 접수',
                subtitle: '관제에서 출고 주문을 직접 등록합니다',
                child: SizedBox(
                  width: double.infinity,
                  child: FilledButton.icon(
                    onPressed: () => CreateOrderDialog.show(context, engine),
                    style: FilledButton.styleFrom(
                      backgroundColor: AppColors.series1,
                      foregroundColor: Colors.white,
                      padding: const EdgeInsets.symmetric(vertical: 12),
                    ),
                    icon: const Icon(Icons.add_shopping_cart_outlined, size: 15),
                    label: const Text(
                      '새 주문 접수',
                      style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w600),
                    ),
                  ),
                ),
              ),
              const SizedBox(height: 12),
              Panel(
                title: '스케줄링 가중치',
                subtitle: '우선순위 점수 = 각 항목 가중 합산',
                child: Column(
                  children: <Widget>[
                    _WeightRow('긴급도', engine.scheduler.weights.urgency, AppColors.series8),
                    _WeightRow('FEFO(유통기한)', engine.scheduler.weights.fefo, AppColors.series4),
                    _WeightRow('이동 동선', engine.scheduler.weights.travel, AppColors.series1),
                    _WeightRow('납기 임박', engine.scheduler.weights.dueDate, AppColors.series5),
                    _WeightRow('대기 시간', engine.scheduler.weights.aging, AppColors.series3),
                    _WeightRow('입고 도크 점유', engine.scheduler.weights.dockPressure, AppColors.series2),
                  ],
                ),
              ),
              const SizedBox(height: 12),
              Expanded(
                child: Panel(
                  title: '주문 현황',
                  subtitle: '주문별 성공·실패 및 납기 준수 기록',
                  child: ListView.builder(
                    padding: EdgeInsets.zero,
                    itemCount: engine.orders.length > 40 ? 40 : engine.orders.length,
                    itemBuilder: (context, i) =>
                        _OrderRow(engine: engine, order: engine.orders[i]),
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

class _TaskTable extends StatelessWidget {
  const _TaskTable({required this.engine, required this.tasks});

  final FleetEngine engine;
  final List<WorkTask> tasks;

  @override
  Widget build(BuildContext context) {
    if (tasks.isEmpty) return const EmptyHint('해당 조건의 태스크가 없습니다.');

    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: SizedBox(
        width: 1030,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: <Widget>[
            Row(
              children: const <Widget>[
                _H('태스크 ID', 84),
                _H('유형', 86),
                _H('긴급도', 56),
                _H('작업 내용', 220),
                _H('구획', 46),
                _H('경로', 120),
                _H('유통기한', 84),
                _H('상태', 84),
                _H('로봇', 58),
                _H('진행률', 86),
                SizedBox(width: 8),
                _H('우선순위', 56),
              ],
            ),
            Divider(height: 10, color: AppColors.border),
            Expanded(
              child: ListView.builder(
                padding: EdgeInsets.zero,
                itemCount: tasks.length,
                itemBuilder: (context, i) {
                  final t = tasks[i];
                  final stateColor = AppColors.taskStateColor(t.state);
                  return InkWell(
                    onTap: () => _showDetail(context, engine, t),
                    child: Padding(
                      padding: const EdgeInsets.symmetric(vertical: 5),
                      child: Row(
                        children: <Widget>[
                          _C(t.id, 84, color: AppColors.textPrimary),
                          SizedBox(
                            width: 86,
                            child: StatusChip(
                              label: t.type.label,
                              color: AppColors.series1,
                              compact: true,
                            ),
                          ),
                          SizedBox(
                            width: 56,
                            child: Text(
                              t.urgency.label,
                              style: TextStyle(
                                color: AppColors.urgencyColor(t.urgency),
                                fontSize: 11,
                                fontWeight: FontWeight.w600,
                              ),
                            ),
                          ),
                          _C(t.title, 220),
                          SizedBox(
                            width: 46,
                            child: Text(
                              t.zone.label,
                              style: TextStyle(
                                color: AppColors.zoneColor(t.zone),
                                fontSize: 11,
                              ),
                            ),
                          ),
                          _C('${t.originLabel}→${t.destLabel}', 120),
                          _C(
                            t.expiry == null ? '—' : engine.dateLabel(t.expiry!),
                            84,
                            color: t.expiry != null &&
                                    t.expiry!.difference(engine.simNow).inDays <= 3
                                ? AppColors.serious
                                : AppColors.textSecondary,
                          ),
                          SizedBox(
                            width: 84,
                            child: StatusChip(
                              label: t.state.label,
                              color: stateColor,
                              compact: true,
                            ),
                          ),
                          _C(t.robotId ?? '—', 58),
                          SizedBox(
                            width: 86,
                            child: Row(
                              children: <Widget>[
                                Expanded(
                                  child: MeterBar(
                                    value: t.progress,
                                    color: t.state == TaskState.failed
                                        ? AppColors.critical
                                        : (t.state == TaskState.done
                                              ? AppColors.good
                                              : AppColors.series1),
                                    height: 5,
                                  ),
                                ),
                                const SizedBox(width: 5),
                                Text(
                                  '${(t.progress * 100).toStringAsFixed(0)}%',
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
                          const SizedBox(width: 8),
                          _C(
                            t.score.toStringAsFixed(0),
                            56,
                            color: AppColors.textPrimary,
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

  void _showDetail(BuildContext context, FleetEngine engine, WorkTask t) {
    showDialog<void>(
      context: context,
      builder: (context) => Dialog(
        backgroundColor: AppColors.surface,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(10),
          side: BorderSide(color: AppColors.border),
        ),
        child: Container(
          width: 480,
          padding: const EdgeInsets.all(18),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              Row(
                children: <Widget>[
                  Text(
                    '${t.id} · ${t.type.label}',
                    style: const TextStyle(
                      color: AppColors.textPrimary,
                      fontSize: 15,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  const Spacer(),
                  StatusChip(
                    label: t.state.label,
                    color: AppColors.taskStateColor(t.state),
                  ),
                ],
              ),
              const SizedBox(height: 12),
              KeyValueRow('작업 내용', t.title),
              KeyValueRow('주문', t.orderId ?? '—'),
              KeyValueRow('요청자', t.requestedBy ?? '—'),
              KeyValueRow('SKU / 로트', '${t.sku ?? "—"} / ${t.lotId ?? "—"}'),
              KeyValueRow(
                '유통기한',
                t.expiry == null ? '—' : engine.dateLabel(t.expiry!),
              ),
              KeyValueRow('경로', '${t.originLabel} → ${t.destLabel}'),
              KeyValueRow('담당 로봇', t.robotId ?? '미할당'),
              KeyValueRow('우선순위 점수', t.score.toStringAsFixed(1)),
              KeyValueRow('재시도', '${t.retries}회'),
              KeyValueRow(
                '실패 사유',
                t.failReason ?? '—',
                valueColor: t.failReason == null
                    ? AppColors.textPrimary
                    : AppColors.serious,
              ),
              KeyValueRow(
                '소요 시간',
                t.cycleTime == null ? '—' : '${t.cycleTime!.inSeconds}초',
              ),
              const Divider(height: 20, color: AppColors.grid),
              const Text(
                '스텝 진행',
                style: TextStyle(
                  color: AppColors.muted,
                  fontSize: 11,
                  fontWeight: FontWeight.w600,
                ),
              ),
              const SizedBox(height: 6),
              for (var i = 0; i < t.steps.length; i++)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 3),
                  child: Row(
                    children: <Widget>[
                      Icon(
                        i < t.stepIndex
                            ? Icons.check_circle
                            : (i == t.stepIndex
                                  ? Icons.radio_button_checked
                                  : Icons.radio_button_unchecked),
                        size: 13,
                        color: i < t.stepIndex
                            ? AppColors.good
                            : (i == t.stepIndex
                                  ? AppColors.series1
                                  : AppColors.muted),
                      ),
                      const SizedBox(width: 7),
                      Expanded(
                        child: Text(
                          '${t.steps[i].kind.label} · ${t.steps[i].label}',
                          style: const TextStyle(
                            color: AppColors.textSecondary,
                            fontSize: 11.5,
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              const SizedBox(height: 14),
              Row(
                children: <Widget>[
                  OutlinedButton(
                    onPressed: t.isTerminal
                        ? null
                        : () {
                            engine.reassignTask(t);
                            Navigator.of(context).pop();
                          },
                    child: const Text('재할당', style: TextStyle(fontSize: 12)),
                  ),
                  const SizedBox(width: 8),
                  OutlinedButton(
                    onPressed: t.isTerminal
                        ? null
                        : () {
                            engine.cancelTask(t);
                            Navigator.of(context).pop();
                          },
                    style: OutlinedButton.styleFrom(
                      foregroundColor: AppColors.critical,
                    ),
                    child: const Text('취소', style: TextStyle(fontSize: 12)),
                  ),
                  const Spacer(),
                  TextButton(
                    onPressed: () => Navigator.of(context).pop(),
                    child: const Text('닫기', style: TextStyle(fontSize: 12)),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _H extends StatelessWidget {
  const _H(this.text, this.width);

  final String text;
  final double width;

  @override
  Widget build(BuildContext context) => SizedBox(
    width: width,
    child: Text(
      text,
      style: const TextStyle(
        color: AppColors.muted,
        fontSize: 10.5,
        fontWeight: FontWeight.w600,
        letterSpacing: 0.3,
      ),
    ),
  );
}

class _C extends StatelessWidget {
  const _C(this.text, this.width, {this.color});

  final String text;
  final double width;
  final Color? color;

  @override
  Widget build(BuildContext context) => SizedBox(
    width: width,
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

class _WeightRow extends StatelessWidget {
  const _WeightRow(this.label, this.value, this.color);

  final String label;
  final double value;
  final Color color;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 4),
    child: Row(
      children: <Widget>[
        SizedBox(
          width: 96,
          child: Text(
            label,
            style: const TextStyle(color: AppColors.textSecondary, fontSize: 11.5),
          ),
        ),
        Expanded(child: MeterBar(value: value / 32, color: color, height: 5)),
        const SizedBox(width: 8),
        SizedBox(
          width: 26,
          child: Text(
            value.toStringAsFixed(0),
            textAlign: TextAlign.right,
            style: const TextStyle(
              color: AppColors.textPrimary,
              fontSize: 11.5,
              fontFeatures: <FontFeature>[FontFeature.tabularFigures()],
            ),
          ),
        ),
      ],
    ),
  );
}

class _OrderRow extends StatelessWidget {
  const _OrderRow({required this.engine, required this.order});

  final FleetEngine engine;
  final SalesOrder order;

  @override
  Widget build(BuildContext context) {
    final color = switch (order.state) {
      OrderState.fulfilled => AppColors.good,
      OrderState.partial => AppColors.warning,
      OrderState.failed => AppColors.critical,
      OrderState.working => AppColors.series1,
      OrderState.open => AppColors.muted,
    };
    final overdue = order.closedAt == null && order.dueAt.isBefore(engine.simNow);

    return Padding(
      padding: const EdgeInsets.only(bottom: 9),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            children: <Widget>[
              Text(
                order.id,
                style: const TextStyle(
                  color: AppColors.textPrimary,
                  fontSize: 11.5,
                  fontWeight: FontWeight.w600,
                ),
              ),
              const SizedBox(width: 6),
              StatusChip(label: order.state.label, color: color, compact: true),
              const Spacer(),
              Text(
                order.urgency.label,
                style: TextStyle(
                  color: AppColors.urgencyColor(order.urgency),
                  fontSize: 10.5,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ],
          ),
          const SizedBox(height: 3),
          Text(
            '${order.customer} · 라인 ${order.doneLines}/${order.taskIds.length} 완료'
            '${order.failedLines > 0 ? " · 실패 ${order.failedLines}" : ""}',
            style: const TextStyle(color: AppColors.textSecondary, fontSize: 11),
          ),
          Text(
            order.closedAt == null
                ? '납기 ${engine.timeLabel(order.dueAt)}${overdue ? " · 초과" : ""}'
                : '마감 ${engine.timeLabel(order.closedAt!)} · ${order.onTime ? "정시" : "지연"}',
            style: TextStyle(
              color: overdue || (order.closedAt != null && !order.onTime)
                  ? AppColors.serious
                  : AppColors.muted,
              fontSize: 10.5,
            ),
          ),
        ],
      ),
    );
  }
}
