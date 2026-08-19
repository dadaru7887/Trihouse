import 'dart:async';

import 'package:flutter/material.dart';

import '../api/fms_api.dart';
import '../api/fms_models.dart';
import 'shared.dart';

class MainDashboard extends StatefulWidget {
  const MainDashboard({super.key, required this.api});

  final FmsApi api;

  @override
  State<MainDashboard> createState() => _MainDashboardState();
}

/// 한 번의 새로고침으로 모은 원장 상태. 카드 넷이 서로 다른 시점을 보여 주지
/// 않도록 네 목록을 함께 받아 한 값으로 묶는다.
class _DashboardSnapshot {
  const _DashboardSnapshot({
    required this.devices,
    required this.jobs,
    required this.anomalies,
    required this.inventory,
  });

  final List<DeviceDto> devices;
  final List<JobSummaryDto> jobs;
  final List<ReservationAnomalyDto> anomalies;
  final List<InventoryLotDto> inventory;

  Iterable<DeviceDto> get mobiles => devices.where((device) => device.isMobile);

  int get operationalMobiles =>
      mobiles.where((device) => device.isOperational).length;

  int get openJobs => jobs.where((job) => job.isOpen).length;
}

class _MainDashboardState extends State<MainDashboard> {
  /// 운영 이벤트는 몰려서 온다. 한 건마다 목록 넷을 다시 받으면 Gateway 를
  /// 두드리게 되므로, 이 창 안에 연달아 온 이벤트를 한 번의 재조회로 합친다.
  static const Duration _coalesceWindow = Duration(milliseconds: 400);

  /// 장비 텔레메트리는 `operation_events` 를 만들지 않는다. WebSocket 만 기다리면
  /// 로봇 상태와 배터리가 job 이 움직일 때까지 낡은 채로 남는다(실측 15분).
  /// 그래서 이벤트 구독과 별도로 주기 조회를 함께 돌린다.
  static const Duration _pollInterval = Duration(seconds: 5);

  static const int _recentLimit = 12;

  _DashboardSnapshot? _data;
  Object? _loadFailure;
  bool _loading = false;
  StreamSubscription<OperationsEventDto>? _events;
  Timer? _coalesce;
  Timer? _poll;
  final List<OperationsEventDto> _recent = <OperationsEventDto>[];
  Object? _streamFailure;

  @override
  void initState() {
    super.initState();
    unawaited(_refresh());
    _poll = Timer.periodic(_pollInterval, (_) => unawaited(_refresh()));
    _events = widget.api.operationsEvents().listen(
      _onEvent,
      onError: (Object error) {
        if (mounted) setState(() => _streamFailure = error);
      },
    );
  }

  @override
  void dispose() {
    _coalesce?.cancel();
    _poll?.cancel();
    final subscription = _events;
    _events = null;
    if (subscription != null) unawaited(subscription.cancel());
    super.dispose();
  }

  Future<_DashboardSnapshot> _load() async {
    // 넷을 동시에 띄운다. `Future.wait` 는 모든 future 에 listener 를 붙이므로,
    // 하나가 실패해도 나머지가 처리되지 않은 오류로 남지 않는다.
    final results = await Future.wait<Object?>(<Future<Object?>>[
      widget.api.listDevices(),
      widget.api.listJobs(),
      widget.api.listAnomalies(),
      widget.api.listInventory(),
    ]);
    return _DashboardSnapshot(
      devices: results[0]! as List<DeviceDto>,
      jobs: results[1]! as List<JobSummaryDto>,
      anomalies: results[2]! as List<ReservationAnomalyDto>,
      inventory: results[3]! as List<InventoryLotDto>,
    );
  }

  /// 받아 온 값을 상태에 넣는다. 조회 중에도 직전 값을 그대로 두어 5초마다
  /// 화면이 빈칸으로 깜빡이지 않게 한다.
  Future<void> _refresh() async {
    if (_loading || !mounted) return;
    _loading = true;
    try {
      final next = await _load();
      if (mounted) {
        setState(() {
          _data = next;
          _loadFailure = null;
        });
      }
    } catch (error) {
      if (mounted) setState(() => _loadFailure = error);
    } finally {
      _loading = false;
    }
  }

  void _onEvent(OperationsEventDto event) {
    if (!mounted) return;
    setState(() {
      _streamFailure = null;
      _recent.insert(0, event);
      if (_recent.length > _recentLimit) _recent.removeLast();
    });
    _coalesce?.cancel();
    _coalesce = Timer(_coalesceWindow, () => unawaited(_refresh()));
  }

  @override
  Widget build(BuildContext context) {
    final data = _data;
    return Padding(
      padding: const EdgeInsets.all(28),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          PageHeading(
            title: '운영 대시보드',
            description: '창고 맵, 로봇, 작업과 재고 상태를 한 화면에서 확인합니다.',
            actions: [
              LiveBadge(connected: _streamFailure == null && _loadFailure == null),
              const SizedBox(width: 12),
              OutlinedButton.icon(
                onPressed: () => unawaited(_refresh()),
                icon: const Icon(Icons.refresh, size: 18),
                label: const Text('새로고침'),
              ),
            ],
          ),
          const SizedBox(height: 20),
          Row(
            children: [
              _MetricCard(
                key: const Key('metric-robots'),
                label: '운영 로봇',
                value: data == null
                    ? '—'
                    : '${data.operationalMobiles}/${data.mobiles.length}',
                icon: Icons.smart_toy,
              ),
              const SizedBox(width: 12),
              _MetricCard(
                key: const Key('metric-open-jobs'),
                label: '진행 작업',
                value: data == null ? '—' : '${data.openJobs}',
                icon: Icons.route,
              ),
              const SizedBox(width: 12),
              _MetricCard(
                key: const Key('metric-anomalies'),
                label: '안전 이벤트',
                value: data == null ? '—' : '${data.anomalies.length}',
                icon: Icons.health_and_safety,
              ),
            ],
          ),
          const SizedBox(height: 18),
          Expanded(
            child: Row(
              children: [
                Expanded(
                  flex: 2,
                  child: DashboardPanel(
                    title: '진행 중인 작업',
                    icon: Icons.route_outlined,
                    child: _JobList(
                      data: data,
                      failure: _loadFailure,
                      onRetry: () => unawaited(_refresh()),
                    ),
                  ),
                ),
                const SizedBox(width: 18),
                Expanded(
                  child: Column(
                    children: [
                      Expanded(
                        child: DashboardPanel(
                          title: '재고',
                          icon: Icons.inventory_2_outlined,
                          child: _InventoryList(
                            data: data,
                            failure: _loadFailure,
                            onRetry: () => unawaited(_refresh()),
                          ),
                        ),
                      ),
                      const SizedBox(height: 18),
                      Expanded(
                        child: DashboardPanel(
                          title: '최근 작업 활동',
                          icon: Icons.history,
                          child: _RecentActivity(
                            events: _recent,
                            failure: _streamFailure,
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 18),
          const _QuickActions(),
        ],
      ),
    );
  }
}

class _JobList extends StatelessWidget {
  const _JobList({
    required this.data,
    required this.failure,
    required this.onRetry,
  });

  final _DashboardSnapshot? data;
  final Object? failure;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final data = this.data;
    if (data == null) {
      if (failure != null) {
        return Padding(
          padding: const EdgeInsets.all(14),
          child: GatewayFailurePanel(error: failure!, onRetry: onRetry),
        );
      }
      return const Center(child: CircularProgressIndicator());
    }
    // 닫힌 작업까지 보이면 시연 중에 무엇이 도는지 알 수 없다. 진행 중을 먼저 둔다.
    final jobs = <JobSummaryDto>[
      ...data.jobs.where((job) => job.isOpen),
      ...data.jobs.where((job) => !job.isOpen),
    ];
    if (jobs.isEmpty) {
      return const Center(child: Text('원장에 작업이 없습니다.'));
    }
    return ListView(
      padding: const EdgeInsets.all(12),
      children: [
        for (final job in jobs)
          ListTile(
            dense: true,
            leading: Icon(
              job.isOpen ? Icons.play_circle_outline : Icons.check_circle_outline,
              color: job.isOpen ? controlBlue : controlSlate,
            ),
            title: Text('${job.jobCode}  ·  ${job.state}'),
            subtitle: Text(
              '${job.operationType} · 품목 ${job.itemCount} · 단계 ${job.stepCount}'
              '${job.assignedMobileId == null ? '' : ' · ${job.assignedMobileId}'}',
            ),
            trailing: Text('#${job.jobId}'),
          ),
      ],
    );
  }
}

class _InventoryList extends StatelessWidget {
  const _InventoryList({
    required this.data,
    required this.failure,
    required this.onRetry,
  });

  final _DashboardSnapshot? data;
  final Object? failure;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final data = this.data;
    if (data == null) {
      if (failure != null) {
        return Padding(
          padding: const EdgeInsets.all(14),
          child: GatewayFailurePanel(error: failure!, onRetry: onRetry),
        );
      }
      return const Center(child: CircularProgressIndicator());
    }
    return ListView(
      padding: const EdgeInsets.all(12),
      children: [
        for (final lot in data.inventory)
          ListTile(
            dense: true,
            leading: const Icon(Icons.inventory_2_outlined),
            title: Text(lot.productCode),
            subtitle: Text(lot.lotCode),
            trailing: Text('가용 ${lot.availableQty} · 예약 ${lot.reservedQty}'),
          ),
      ],
    );
  }
}

class _RecentActivity extends StatelessWidget {
  const _RecentActivity({required this.events, required this.failure});

  final List<OperationsEventDto> events;
  final Object? failure;

  @override
  Widget build(BuildContext context) {
    if (failure != null) {
      return Padding(
        padding: const EdgeInsets.all(14),
        child: GatewayFailurePanel(error: failure!),
      );
    }
    if (events.isEmpty) {
      return const Center(child: Text('운영 이벤트 수신 대기'));
    }
    return ListView(
      padding: const EdgeInsets.all(12),
      children: [
        for (final event in events)
          ListTile(
            dense: true,
            title: Text('${event.category} · ${event.eventType}'),
            subtitle: Text(event.message ?? '—'),
            trailing: Text(
              '${event.occurredAt.hour.toString().padLeft(2, '0')}:'
              '${event.occurredAt.minute.toString().padLeft(2, '0')}:'
              '${event.occurredAt.second.toString().padLeft(2, '0')}',
              style: const TextStyle(color: controlSlate),
            ),
          ),
      ],
    );
  }
}

class _MetricCard extends StatelessWidget {
  const _MetricCard({
    super.key,
    required this.label,
    required this.value,
    required this.icon,
  });

  final String label;
  final String value;
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
          CircleAvatar(
            backgroundColor: const Color(0xFFEFF6FF),
            child: Icon(icon, color: controlBlue),
          ),
          const SizedBox(width: 12),
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(label, style: const TextStyle(color: controlSlate)),
              Text(
                value,
                style: const TextStyle(
                  fontSize: 20,
                  fontWeight: FontWeight.w800,
                ),
              ),
            ],
          ),
        ],
      ),
    ),
  );
}

class _QuickActions extends StatelessWidget {
  const _QuickActions();

  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 13),
    decoration: BoxDecoration(
      color: Colors.white,
      borderRadius: BorderRadius.circular(13),
      border: Border.all(color: const Color(0xFFE2E8F0)),
    ),
    child: const Row(
      children: [
        Text('빠른 실행', style: TextStyle(fontWeight: FontWeight.w800)),
        SizedBox(width: 20),
        Chip(label: Text('맵 프로젝트 열기')),
        SizedBox(width: 8),
        Chip(label: Text('작업 조회')),
        SizedBox(width: 8),
        Chip(label: Text('운영 이벤트 보기')),
      ],
    ),
  );
}
