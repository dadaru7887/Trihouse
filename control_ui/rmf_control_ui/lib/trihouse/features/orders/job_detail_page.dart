import 'dart:async';

import 'package:flutter/material.dart';

import '../../api/fms_api.dart';
import '../../api/fms_api_client.dart';
import '../../api/fms_models.dart';

class JobDetailPage extends StatefulWidget {
  const JobDetailPage({
    super.key,
    required this.api,
    required this.jobId,
    required this.workerId,
    this.initialJob,
  });

  final FmsApi api;
  final int jobId;
  final String workerId;
  final JobDetailDto? initialJob;

  @override
  State<JobDetailPage> createState() => _JobDetailPageState();
}

class _JobDetailPageState extends State<JobDetailPage> {
  /// 운영 이벤트가 몰려 올 때 상세를 한 번만 다시 받도록 합친다.
  static const Duration _coalesceWindow = Duration(milliseconds: 400);

  /// 단계가 게이트에서 멈추면 이벤트가 하나도 나지 않는다. 그래서 이벤트만
  /// 기다리면 화면이 멈춘 것처럼 보인다. 짧은 주기로 원장을 다시 읽는다.
  static const Duration _pollInterval = Duration(seconds: 3);

  final _completionNote = TextEditingController();
  final _acknowledgedManualItems = <int>{};
  JobDetailDto? _job;
  String? _error;
  String? _completionKey;
  bool _loading = true;
  bool _submitting = false;
  bool _completed = false;
  bool _reloading = false;
  StreamSubscription<OperationsEventDto>? _events;
  Timer? _coalesce;
  Timer? _poll;

  @override
  void initState() {
    super.initState();
    _job = widget.initialJob;
    _loading = widget.initialJob == null;
    unawaited(_load());
    _poll = Timer.periodic(_pollInterval, (_) => unawaited(_load()));
    _events = widget.api.operationsEvents().listen(
      (event) {
        // 이 작업과 무관한 이벤트로 원장을 다시 읽지 않는다.
        if (!mounted || (event.jobId != null && event.jobId != widget.jobId)) {
          return;
        }
        _coalesce?.cancel();
        _coalesce = Timer(_coalesceWindow, () => unawaited(_load()));
      },
      onError: (Object _) {},
    );
  }

  @override
  void dispose() {
    _coalesce?.cancel();
    _poll?.cancel();
    final subscription = _events;
    _events = null;
    if (subscription != null) unawaited(subscription.cancel());
    _completionNote.dispose();
    super.dispose();
  }

  /// 다시 읽는 동안에도 직전 내용을 그대로 둔다. 3초마다 화면이 비면 못 읽는다.
  Future<void> _load() async {
    if (_reloading) return;
    _reloading = true;
    try {
      final job = await widget.api.getJob(widget.jobId);
      if (mounted) {
        setState(() {
          _job = job;
          _error = null;
        });
      }
    } catch (error) {
      if (mounted) setState(() => _error = fmsApiUserMessage(error));
    } finally {
      _reloading = false;
      if (mounted && _loading) setState(() => _loading = false);
    }
  }

  List<JsonObject> get _manualItems => [
    for (final item in _job?.items ?? const <JsonObject>[])
      if (item['verification_state'] == 'manual_review' ||
          (item['metadata'] as Map<Object?, Object?>?)?['fulfillment_state'] ==
              'MANUAL_FULFILLMENT_REQUIRED')
        item,
  ];

  bool get _allManualAcknowledged => _manualItems.every(
    (item) => _acknowledgedManualItems.contains(item['job_item_id'] as int),
  );

  Future<void> _complete() async {
    if (!_allManualAcknowledged || _submitting || _completed) return;
    final key = _completionKey ??=
        'control-ui-worker-completion-${widget.jobId}-${DateTime.now().microsecondsSinceEpoch}';
    setState(() {
      _submitting = true;
      _error = null;
    });
    try {
      final completed = await widget.api.completeJob(
        widget.jobId,
        WorkerCompletionDto(
          workerId: widget.workerId,
          completionNote: _completionNote.text.trim().isEmpty
              ? null
              : _completionNote.text.trim(),
          acknowledgedManualItemIds: _acknowledgedManualItems.toList()..sort(),
        ),
        idempotencyKey: key,
      );
      if (!mounted) return;
      setState(() {
        _job = completed;
        _completed = true;
      });
    } catch (error) {
      if (mounted) setState(() => _error = fmsApiUserMessage(error));
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) return const Center(child: CircularProgressIndicator());
    if (_job == null) {
      return Center(child: Text(_error ?? '작업을 불러오지 못했습니다.'));
    }
    final job = _job!;
    final assignment =
        (job.context['assignment'] as Map<Object?, Object?>?) ?? const {};
    return Material(
      color: Theme.of(context).colorScheme.surface,
      child: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          Text(job.jobCode, style: Theme.of(context).textTheme.headlineSmall),
          const SizedBox(height: 6),
          Text(job.state),
          Text('포장대 ${assignment['packing_dock_code'] ?? '미배정'}'),
          Text('담당 Pinky ${assignment['mobile_id'] ?? '미배정'}'),
          const Divider(height: 28),
          Row(
            children: [
              Expanded(
                child: Text(
                  '실행 단계',
                  style: Theme.of(context).textTheme.titleMedium,
                ),
              ),
              Text(
                '${_finishedSteps(job.steps)}/${job.steps.length} 완료',
                style: const TextStyle(color: Color(0xFF64748B)),
              ),
            ],
          ),
          const SizedBox(height: 8),
          _StepTimeline(steps: job.steps),
          const Divider(height: 28),
          Text('품목', style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 8),
          for (final item in job.items)
            _ItemTile(
              item: item,
              acknowledged: _acknowledgedManualItems.contains(
                item['job_item_id'] as int,
              ),
              onAcknowledged: (value) {
                final itemId = item['job_item_id'] as int;
                setState(() {
                  if (value) {
                    _acknowledgedManualItems.add(itemId);
                  } else {
                    _acknowledgedManualItems.remove(itemId);
                  }
                });
              },
            ),
          const SizedBox(height: 12),
          TextField(
            controller: _completionNote,
            maxLength: 512,
            decoration: const InputDecoration(
              labelText: '완료 메모 (선택)',
              border: OutlineInputBorder(),
            ),
          ),
          if (_error != null)
            Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: Text(_error!, style: const TextStyle(color: Colors.red)),
            ),
          Align(
            alignment: Alignment.centerRight,
            child: FilledButton.icon(
              key: const Key('worker-complete-button'),
              onPressed: _allManualAcknowledged && !_submitting && !_completed
                  ? _complete
                  : null,
              icon: _submitting
                  ? const SizedBox.square(
                      dimension: 16,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.task_alt),
              label: Text(_completed ? '완료 처리됨' : '완료'),
            ),
          ),
        ],
      ),
    );
  }
}

/// 원장이 끝났다고 적은 단계 수. 파이프라인이 어디까지 왔는지 한 줄로 말한다.
int _finishedSteps(List<JsonObject> steps) =>
    steps.where((step) => step['state'] == 'succeeded').length;

const Map<String, Color> _stepStateColors = {
  'succeeded': Color(0xFF16A34A),
  'running': Color(0xFF2563EB),
  'failed': Color(0xFFDC2626),
  'cancelled': Color(0xFF94A3B8),
  'pending': Color(0xFF94A3B8),
};

const Map<String, IconData> _stepStateIcons = {
  'succeeded': Icons.check_circle,
  'running': Icons.play_circle_fill,
  'failed': Icons.error,
  'cancelled': Icons.cancel,
  'pending': Icons.radio_button_unchecked,
};

/// Control Tower 가 계획한 실행 단계를 원장 값 그대로 보여 준다.
///
/// 가공하지 않는 것이 요점이다. `executor_type`·`action_type`·`gate`·`dependencies`
/// 는 백엔드가 실제로 판정에 쓰는 값이고, 화면이 그것을 그대로 보여 줘야 어디서
/// 멈췄는지 원장과 화면이 다른 말을 하지 않는다.
class _StepTimeline extends StatelessWidget {
  const _StepTimeline({required this.steps});

  final List<JsonObject> steps;

  /// 선행 단계가 모두 끝났는데 아직 시작하지 못한 첫 단계. 지금 막고 있는 곳이다.
  int? get _blockedStepNo {
    final byNo = <int, JsonObject>{
      for (final step in steps) step['step_no'] as int: step,
    };
    for (final step in steps) {
      final state = step['state'];
      if (state != 'pending') continue;
      final input = step['input'];
      final dependencies = input is JsonObject
          ? (input['dependencies'] as List<Object?>? ?? const <Object?>[])
          : const <Object?>[];
      final ready = dependencies.every(
        (dependency) => byNo[dependency as int]?['state'] == 'succeeded',
      );
      if (ready) return step['step_no'] as int;
    }
    return null;
  }

  @override
  Widget build(BuildContext context) {
    if (steps.isEmpty) {
      return const Text('계획된 단계가 없습니다.');
    }
    final blocked = _blockedStepNo;
    final ordered = [...steps]
      ..sort((a, b) => (a['step_no'] as int).compareTo(b['step_no'] as int));
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        for (final step in ordered)
          _StepTile(
            step: step,
            blocked: step['step_no'] == blocked,
            byNo: {for (final s in ordered) s['step_no'] as int: s},
          ),
      ],
    );
  }
}

class _StepTile extends StatelessWidget {
  const _StepTile({
    required this.step,
    required this.blocked,
    required this.byNo,
  });

  final JsonObject step;
  final bool blocked;
  final Map<int, JsonObject> byNo;

  JsonObject? get _input =>
      step['input'] is JsonObject ? step['input'] as JsonObject : null;

  JsonObject? get _result =>
      step['result'] is JsonObject ? step['result'] as JsonObject : null;

  /// 단계가 왜 이 상태인지 원장이 말해 주는 것을 그대로 옮긴다.
  String? get _reason {
    final failure = step['failure_reason'] ?? step['final_outcome_reason_code'];
    if (failure is String && failure.isNotEmpty) return failure;
    final code = _result?['reason_code'];
    if (code is String && code.isNotEmpty) return code;
    return null;
  }

  @override
  Widget build(BuildContext context) {
    final stepNo = step['step_no'] as int;
    final state = step['state'] as String? ?? 'pending';
    final color = _stepStateColors[state] ?? const Color(0xFF94A3B8);
    final executor = step['executor_type'] ?? '?';
    final action = step['action_type'] ?? '?';
    final device = step['assigned_device_id'] as String?;
    final gate = _input?['gate'];
    final dependencies =
        _input?['dependencies'] as List<Object?>? ?? const <Object?>[];
    final reason = _reason;
    final rmfTaskId = step['rmf_task_id'] as String?;

    return Container(
      key: Key('job-step-$stepNo'),
      margin: const EdgeInsets.only(bottom: 6),
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        // 막힌 단계만 눈에 띄게 한다. 나머지는 조용히 둔다.
        color: blocked ? const Color(0xFFFFFBEB) : Colors.transparent,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(
          color: blocked ? const Color(0xFFFCD34D) : const Color(0xFFE2E8F0),
        ),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(_stepStateIcons[state] ?? Icons.circle_outlined,
              size: 18, color: color),
          const SizedBox(width: 10),
          SizedBox(
            width: 34,
            child: Text('$stepNo',
                style: const TextStyle(fontWeight: FontWeight.w700)),
          ),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '$executor/$action'
                  '${device == null ? '' : '  ·  $device'}',
                  style: const TextStyle(fontWeight: FontWeight.w600),
                ),
                if (reason != null)
                  Text(reason,
                      style: const TextStyle(color: Color(0xFF64748B))),
                if (rmfTaskId != null)
                  Text('RMF $rmfTaskId',
                      style: const TextStyle(color: Color(0xFF94A3B8))),
                if (blocked && gate is String)
                  Text(
                    '게이트 $gate 대기 중'
                    '${dependencies.isEmpty ? '' : ' · 선행 ${dependencies.join(', ')} 완료'}',
                    key: Key('job-step-$stepNo-gate'),
                    style: const TextStyle(
                      color: Color(0xFFB45309),
                      fontWeight: FontWeight.w600,
                    ),
                  ),
              ],
            ),
          ),
          const SizedBox(width: 10),
          Text(state, style: TextStyle(color: color, fontWeight: FontWeight.w700)),
        ],
      ),
    );
  }
}

class _ItemTile extends StatelessWidget {
  const _ItemTile({
    required this.item,
    required this.acknowledged,
    required this.onAcknowledged,
  });

  final JsonObject item;
  final bool acknowledged;
  final ValueChanged<bool> onAcknowledged;

  bool get _manualRequired =>
      item['verification_state'] == 'manual_review' ||
      (item['metadata'] as Map<Object?, Object?>?)?['fulfillment_state'] ==
          'MANUAL_FULFILLMENT_REQUIRED';

  @override
  Widget build(BuildContext context) {
    final itemId = item['job_item_id'] as int;
    if (_manualRequired) {
      return CheckboxListTile(
        key: Key('manual-item-$itemId'),
        value: acknowledged,
        onChanged: (value) => onAcknowledged(value ?? false),
        title: Text(item['product_code'] as String),
        subtitle: const Text('포장대에서 처리 확인 필요'),
        controlAffinity: ListTileControlAffinity.leading,
      );
    }
    return ListTile(
      leading: const Icon(Icons.inventory_2_outlined),
      title: Text(item['product_code'] as String),
      subtitle: Text(
        '완료 ${item['completed_qty']} / 요청 ${item['requested_qty']}',
      ),
    );
  }
}
