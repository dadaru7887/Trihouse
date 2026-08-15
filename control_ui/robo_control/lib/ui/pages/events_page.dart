import 'package:flutter/material.dart';

import 'package:robo_core/models/enums.dart';
import 'package:robo_core/models/event.dart';
import '../app_shell.dart';
import '../theme.dart';
import '../widgets/common.dart';

/// 운행 이력: 주행 · 작업 · 배터리 · 안전 · 스케줄 이벤트 통합 조회.
class EventsPage extends StatefulWidget {
  const EventsPage({super.key});

  @override
  State<EventsPage> createState() => _EventsPageState();
}

class _EventsPageState extends State<EventsPage> {
  String _category = '전체';
  Severity? _severity;

  static const List<String> _categories = <String>[
    '전체',
    '작업',
    '스케줄',
    '배터리',
    '안전',
    '환경',
    '주문',
    '작업자 요청',
    '가용성',
    '운영',
    '시스템',
  ];

  @override
  Widget build(BuildContext context) {
    final engine = EngineScope.of(context);
    final list = engine.events
        .where(
          (e) =>
              (_category == '전체' || e.category == _category) &&
              (_severity == null || e.severity == _severity),
        )
        .toList();

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: <Widget>[
        Row(
          children: <Widget>[
            Expanded(
              child: Wrap(
                spacing: 5,
                runSpacing: 5,
                children: <Widget>[
                  for (final c in _categories)
                    _Chip(
                      label: c,
                      selected: _category == c,
                      color: AppColors.series1,
                      onTap: () => setState(() => _category = c),
                    ),
                ],
              ),
            ),
            const SizedBox(width: 12),
            Wrap(
              spacing: 5,
              children: <Widget>[
                _Chip(
                  label: '전체 등급',
                  selected: _severity == null,
                  color: AppColors.textSecondary,
                  onTap: () => setState(() => _severity = null),
                ),
                for (final s in Severity.values)
                  _Chip(
                    label: s.label,
                    selected: _severity == s,
                    color: AppColors.severityColor(s),
                    onTap: () => setState(() => _severity = s),
                  ),
              ],
            ),
          ],
        ),
        const SizedBox(height: 12),
        Expanded(
          child: Panel(
            title: '운행 이력',
            subtitle: '${list.length}건 표시 · 최신순 (최근 400건 보관)',
            child: list.isEmpty
                ? const EmptyHint('조건에 맞는 이력이 없습니다.')
                : ListView.builder(
                    padding: EdgeInsets.zero,
                    itemCount: list.length,
                    itemBuilder: (context, i) =>
                        _EventRow(event: list[i], time: engine.timeLabel(list[i].at)),
                  ),
          ),
        ),
      ],
    );
  }
}

class _EventRow extends StatelessWidget {
  const _EventRow({required this.event, required this.time});

  final OpsEvent event;
  final String time;

  @override
  Widget build(BuildContext context) {
    final color = AppColors.severityColor(event.severity);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 5),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Icon(AppColors.severityIcon(event.severity), size: 13, color: color),
          const SizedBox(width: 8),
          SizedBox(
            width: 66,
            child: Text(
              time,
              style: const TextStyle(
                color: AppColors.muted,
                fontSize: 11,
                fontFeatures: <FontFeature>[FontFeature.tabularFigures()],
              ),
            ),
          ),
          SizedBox(
            width: 82,
            child: Text(
              event.category,
              style: const TextStyle(color: AppColors.textSecondary, fontSize: 11),
            ),
          ),
          SizedBox(
            width: 66,
            child: Text(
              event.source,
              style: const TextStyle(
                color: AppColors.textPrimary,
                fontSize: 11,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
          Expanded(
            child: Text(
              event.message,
              style: const TextStyle(
                color: AppColors.textSecondary,
                fontSize: 11.5,
                height: 1.4,
              ),
            ),
          ),
          SizedBox(
            width: 92,
            child: Text(
              event.taskId ?? event.orderId ?? '',
              style: const TextStyle(color: AppColors.muted, fontSize: 10.5),
            ),
          ),
        ],
      ),
    );
  }
}

class _Chip extends StatelessWidget {
  const _Chip({
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
  Widget build(BuildContext context) => InkWell(
    onTap: onTap,
    child: Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(
        color: selected ? color.withValues(alpha: 0.18) : AppColors.surface,
        borderRadius: BorderRadius.circular(6),
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
  );
}
