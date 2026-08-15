import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../api/fms_api.dart';
import '../api/fms_models.dart';
import 'shared.dart';

class TaskManagementPage extends StatefulWidget {
  const TaskManagementPage({super.key, required this.api});

  final FmsApi api;

  @override
  State<TaskManagementPage> createState() => _TaskManagementPageState();
}

class _TaskManagementPageState extends State<TaskManagementPage> {
  final _jobId = TextEditingController();
  JobDetailDto? _job;
  Object? _failure;
  bool _busy = false;

  @override
  void dispose() {
    _jobId.dispose();
    super.dispose();
  }

  Future<void> _loadJob() async {
    final id = int.tryParse(_jobId.text);
    if (id == null || id <= 0) return;
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
        const PageHeading(
          title: '작업 관리',
          description: 'Control Tower가 계획한 Job과 Step을 조회하고 작업자 완료 상태를 확인합니다.',
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
              ? const _EmptyTaskState()
              : _JobDetail(job: _job!),
        ),
      ],
    ),
  );
}

class _EmptyTaskState extends StatelessWidget {
  const _EmptyTaskState();

  @override
  Widget build(BuildContext context) => Container(
    width: double.infinity,
    decoration: BoxDecoration(
      color: Colors.white,
      borderRadius: BorderRadius.circular(14),
      border: Border.all(color: const Color(0xFFE2E8F0)),
    ),
    child: const Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.assignment_outlined, size: 54, color: Color(0xFF94A3B8)),
          SizedBox(height: 12),
          Text('조회한 작업이 없습니다.'),
        ],
      ),
    ),
  );
}

class _JobDetail extends StatelessWidget {
  const _JobDetail({required this.job});

  final JobDetailDto job;

  @override
  Widget build(BuildContext context) => Row(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      Expanded(
        child: DashboardPanel(
          title: '작업 상세',
          icon: Icons.assignment_outlined,
          child: ListView(
            padding: const EdgeInsets.all(18),
            children: [
              Text(
                job.jobCode,
                style: const TextStyle(
                  fontSize: 22,
                  fontWeight: FontWeight.w800,
                ),
              ),
              const SizedBox(height: 12),
              _Fact(label: '상태', value: job.state),
              _Fact(label: '종류', value: job.operationType),
              _Fact(label: '우선순위', value: job.priority),
              _Fact(label: '요청자', value: job.requestedBy ?? '—'),
              _Fact(label: '외부 참조', value: job.externalReference ?? '—'),
            ],
          ),
        ),
      ),
      const SizedBox(width: 18),
      Expanded(
        flex: 2,
        child: DashboardPanel(
          title: '작업 단계',
          icon: Icons.account_tree_outlined,
          child: ListView.separated(
            padding: const EdgeInsets.all(14),
            itemCount: job.steps.length,
            separatorBuilder: (_, _) => const Divider(),
            itemBuilder: (context, index) {
              final step = job.steps[index];
              return ListTile(
                leading: CircleAvatar(child: Text('${index + 1}')),
                title: Text('Step ${step['step_no'] ?? index + 1}'),
                subtitle: Text('${step['state'] ?? 'unknown'}'),
              );
            },
          ),
        ),
      ),
    ],
  );
}

class _Fact extends StatelessWidget {
  const _Fact({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 7),
    child: Row(
      children: [
        SizedBox(
          width: 90,
          child: Text(label, style: const TextStyle(color: controlSlate)),
        ),
        Expanded(
          child: Text(
            value,
            style: const TextStyle(fontWeight: FontWeight.w700),
          ),
        ),
      ],
    ),
  );
}
