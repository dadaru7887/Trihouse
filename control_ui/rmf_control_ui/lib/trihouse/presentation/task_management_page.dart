import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../api/fms_api.dart';
import '../api/fms_models.dart';
import '../features/orders/job_detail_page.dart';
import 'shared.dart';

class TaskManagementPage extends StatefulWidget {
  const TaskManagementPage({super.key, required this.api});

  final FmsApi api;

  @override
  State<TaskManagementPage> createState() => _TaskManagementPageState();
}

class _TaskManagementPageState extends State<TaskManagementPage> {
  /// 운영 이벤트가 몰려 올 때 목록을 한 번만 다시 받도록 합친다.
  static const Duration _coalesceWindow = Duration(milliseconds: 400);

  final _jobId = TextEditingController();
  JobDetailDto? _job;
  Object? _failure;
  bool _busy = false;
  /// 이벤트가 끊겨도 목록이 멈추지 않도록 주기 조회를 함께 돈다.
  static const Duration _pollInterval = Duration(seconds: 5);

  List<JobSummaryDto>? _jobs;
  Object? _jobsFailure;
  bool _loadingJobs = false;
  StreamSubscription<OperationsEventDto>? _events;
  Timer? _coalesce;
  Timer? _poll;
  bool _live = true;

  @override
  void initState() {
    super.initState();
    unawaited(_reloadJobs());
    _poll = Timer.periodic(_pollInterval, (_) => unawaited(_reloadJobs()));
    _events = widget.api.operationsEvents().listen(
      (_) {
        if (!mounted) return;
        if (!_live) setState(() => _live = true);
        _coalesce?.cancel();
        _coalesce = Timer(_coalesceWindow, () => unawaited(_reloadJobs()));
      },
      onError: (Object _) {
        if (mounted) setState(() => _live = false);
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
    _jobId.dispose();
    super.dispose();
  }

  /// 조회 중에도 직전 목록을 그대로 둔다.
  Future<void> _reloadJobs() async {
    if (_loadingJobs || !mounted) return;
    _loadingJobs = true;
    try {
      final next = await widget.api.listJobs();
      if (mounted) {
        setState(() {
          _jobs = next;
          _jobsFailure = null;
        });
      }
    } catch (error) {
      if (mounted) setState(() => _jobsFailure = error);
    } finally {
      _loadingJobs = false;
    }
  }

  Future<void> _loadJob() async {
    final id = int.tryParse(_jobId.text);
    if (id == null || id <= 0) return;
    await _openJob(id);
  }

  /// 목록에서 고른 작업과 ID 로 조회한 작업이 같은 경로를 타게 한다.
  Future<void> _openJob(int id) async {
    setState(() {
      _busy = true;
      _failure = null;
    });
    try {
      final job = await widget.api.getJob(id);
      if (mounted) setState(() => _job = job);
    } catch (error) {
      if (mounted) setState(() => _failure = error);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.all(28),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        PageHeading(
          title: '작업 관리',
          description: 'Control Tower가 계획한 Job과 Step을 조회하고 작업자 완료 상태를 확인합니다.',
          actions: [
            if (_job != null) ...[
              OutlinedButton.icon(
                key: const Key('back-to-job-list'),
                onPressed: () {
                  setState(() {
                    _job = null;
                    _failure = null;
                  });
                  unawaited(_reloadJobs());
                },
                icon: const Icon(Icons.arrow_back, size: 18),
                label: const Text('목록으로'),
              ),
              const SizedBox(width: 12),
            ],
            LiveBadge(connected: _live),
          ],
        ),
        const SizedBox(height: 18),
        Container(
          padding: const EdgeInsets.all(18),
          decoration: BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.circular(14),
            border: Border.all(color: const Color(0xFFE2E8F0)),
          ),
          child: Column(
            children: [
              Row(
                children: [
                  const Icon(Icons.search, color: controlBlue),
                  const SizedBox(width: 12),
                  const Expanded(
                    child: Text(
                      'Gateway 작업 조회',
                      style: TextStyle(fontWeight: FontWeight.w800),
                    ),
                  ),
                  SizedBox(
                    width: 180,
                    child: TextField(
                      key: const Key('job-id-field'),
                      controller: _jobId,
                      keyboardType: TextInputType.number,
                      inputFormatters: [FilteringTextInputFormatter.digitsOnly],
                      decoration: const InputDecoration(
                        labelText: 'Job ID',
                        isDense: true,
                        border: OutlineInputBorder(),
                      ),
                      onSubmitted: (_) => _loadJob(),
                    ),
                  ),
                  const SizedBox(width: 10),
                  FilledButton.icon(
                    onPressed: _busy ? null : _loadJob,
                    icon: const Icon(Icons.manage_search),
                    label: const Text('작업 조회'),
                  ),
                ],
              ),
              const SizedBox(height: 9),
              const Align(
                alignment: Alignment.centerRight,
                child: Chip(
                  avatar: Icon(Icons.policy_outlined, size: 16),
                  label: Text('배차 · 순서 결정은 Control Tower'),
                ),
              ),
            ],
          ),
        ),
        if (_failure != null) ...[
          const SizedBox(height: 14),
          GatewayFailurePanel(error: _failure!),
        ],
        const SizedBox(height: 18),
        Expanded(
          child: _job == null
              ? _JobPicker(
                  jobs: _jobs,
                  failure: _jobsFailure,
                  onOpen: _openJob,
                  onRetry: () => unawaited(_reloadJobs()),
                )
              : JobDetailPage(
                  api: widget.api,
                  jobId: _job!.jobId,
                  workerId: _job!.requestedBy ?? 'W-OP-01',
                  initialJob: _job,
                ),
        ),
      ],
    ),
  );
}

/// 원장에 있는 작업을 그대로 보여 주고, 누르면 상세로 넘긴다. 이전에는 Job ID 를
/// 외워서 타이핑해야만 아무것도 볼 수 없었다.
class _JobPicker extends StatelessWidget {
  const _JobPicker({
    required this.jobs,
    required this.failure,
    required this.onOpen,
    required this.onRetry,
  });

  final List<JobSummaryDto>? jobs;
  final Object? failure;
  final void Function(int jobId) onOpen;
  final VoidCallback onRetry;

  @override
  // 배경색은 Material 이 칠한다. Container 로 칠하면 그 위의 ListTile 이 잉크를
  // 그릴 Material 조상을 찾지 못해 탭 반응이 보이지 않는다.
  Widget build(BuildContext context) => Material(
    color: Colors.white,
    borderRadius: BorderRadius.circular(14),
    child: Container(
      width: double.infinity,
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: const Color(0xFFE2E8F0)),
      ),
      child: Builder(
      builder: (context) {
        final data = jobs;
        if (data == null) {
          if (failure != null) {
            return Padding(
              padding: const EdgeInsets.all(14),
              child: GatewayFailurePanel(error: failure!, onRetry: onRetry),
            );
          }
          return const Center(child: CircularProgressIndicator());
        }
        if (data.isEmpty) {
          return const Center(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(
                  Icons.assignment_outlined,
                  size: 54,
                  color: Color(0xFF94A3B8),
                ),
                SizedBox(height: 12),
                Text('원장에 작업이 없습니다.'),
              ],
            ),
          );
        }
        // 진행 중인 것을 위로 올린다. 시연에서 지금 도는 작업이 먼저 보여야 한다.
        final ordered = <JobSummaryDto>[
          ...data.where((job) => job.isOpen),
          ...data.where((job) => !job.isOpen),
        ];
        return ListView.separated(
          padding: const EdgeInsets.symmetric(vertical: 8),
          itemCount: ordered.length,
          separatorBuilder: (_, _) => const Divider(height: 1),
          itemBuilder: (context, index) {
            final job = ordered[index];
            return ListTile(
              key: Key('job-row-${job.jobId}'),
              leading: Icon(
                job.isOpen
                    ? Icons.play_circle_outline
                    : Icons.check_circle_outline,
                color: job.isOpen ? controlBlue : controlSlate,
              ),
              title: Text('${job.jobCode}  ·  ${job.state}'),
              subtitle: Text(
                '${job.operationType} · 품목 ${job.itemCount} · 단계 ${job.stepCount}'
                '${job.assignedMobileId == null ? '' : ' · ${job.assignedMobileId}'}',
              ),
              trailing: Text('#${job.jobId}'),
              onTap: () => onOpen(job.jobId),
            );
          },
        );
        },
      ),
    ),
  );
}
