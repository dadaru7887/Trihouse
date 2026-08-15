import 'package:flutter/material.dart';

import '../../operations_log_models.dart';
import '../api/fms_api.dart';
import '../api/fms_models.dart';
import 'shared.dart';

class OperationsAnalyticsPage extends StatefulWidget {
  const OperationsAnalyticsPage({super.key, required this.api});

  final FmsApi api;

  @override
  State<OperationsAnalyticsPage> createState() =>
      _OperationsAnalyticsPageState();
}

class _OperationsAnalyticsPageState extends State<OperationsAnalyticsPage> {
  late final Stream<OperationsEventDto> _events;

  @override
  void initState() {
    super.initState();
    _events = widget.api.operationsEvents();
  }

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.all(28),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const PageHeading(
          title: '운영 분석',
          description: 'Gateway가 제공하는 작업, 로봇, 재고와 안전 이벤트를 같은 시간축에서 봅니다.',
        ),
        const SizedBox(height: 18),
        const Row(
          children: [
            _AnalyticsMetric(label: '작업', icon: Icons.assignment_outlined),
            SizedBox(width: 12),
            _AnalyticsMetric(label: '로봇', icon: Icons.smart_toy_outlined),
            SizedBox(width: 12),
            _AnalyticsMetric(
              label: '안전',
              icon: Icons.health_and_safety_outlined,
            ),
          ],
        ),
        const SizedBox(height: 18),
        Expanded(
          child: DashboardPanel(
            title: '운영 이벤트 타임라인',
            icon: Icons.timeline,
            child: StreamBuilder<OperationsEventDto>(
              stream: _events,
              builder: (context, snapshot) {
                if (snapshot.hasError) {
                  return Padding(
                    padding: const EdgeInsets.all(14),
                    child: GatewayFailurePanel(error: snapshot.error!),
                  );
                }
                final event = snapshot.data;
                if (event == null) {
                  return const Center(child: Text('운영 이벤트 수신 대기'));
                }
                final kind = OperationLogKind.parse(event.category);
                return ListView(
                  padding: const EdgeInsets.all(16),
                  children: [
                    ListTile(
                      leading: CircleAvatar(
                        backgroundColor: _severityColor(
                          event.severity,
                        ).withValues(alpha: .12),
                        child: Icon(
                          Icons.bolt,
                          color: _severityColor(event.severity),
                        ),
                      ),
                      title: Text(
                        event.message ?? event.eventType,
                        style: const TextStyle(fontWeight: FontWeight.w800),
                      ),
                      subtitle: Text(
                        '${kind.label} · ${event.eventType} · ${event.occurredAt.toLocal()}',
                      ),
                      trailing: Text(event.deviceId ?? 'system'),
                    ),
                  ],
                );
              },
            ),
          ),
        ),
      ],
    ),
  );

  Color _severityColor(String severity) => switch (severity) {
    'critical' || 'error' => const Color(0xFFDC2626),
    'warning' => const Color(0xFFD97706),
    _ => controlBlue,
  };
}

class _AnalyticsMetric extends StatelessWidget {
  const _AnalyticsMetric({required this.label, required this.icon});

  final String label;
  final IconData icon;

  @override
  Widget build(BuildContext context) => Expanded(
    child: Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(13),
        border: Border.all(color: const Color(0xFFE2E8F0)),
      ),
      child: Row(
        children: [
          Icon(icon, color: controlBlue),
          const SizedBox(width: 10),
          Text(label, style: const TextStyle(fontWeight: FontWeight.w800)),
          const Spacer(),
          const Text(
            '—',
            style: TextStyle(fontSize: 20, fontWeight: FontWeight.w800),
          ),
        ],
      ),
    ),
  );
}
