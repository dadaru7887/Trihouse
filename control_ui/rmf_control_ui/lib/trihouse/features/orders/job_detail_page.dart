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
  final _completionNote = TextEditingController();
  final _acknowledgedManualItems = <int>{};
  JobDetailDto? _job;
  String? _error;
  String? _completionKey;
  bool _loading = true;
  bool _submitting = false;
  bool _completed = false;

  @override
  void initState() {
    super.initState();
    _job = widget.initialJob;
    _loading = widget.initialJob == null;
    if (_loading) _load();
  }

  @override
  void dispose() {
    _completionNote.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final job = await widget.api.getJob(widget.jobId);
      if (mounted) setState(() => _job = job);
    } catch (error) {
      if (mounted) setState(() => _error = fmsApiUserMessage(error));
    } finally {
      if (mounted) setState(() => _loading = false);
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
