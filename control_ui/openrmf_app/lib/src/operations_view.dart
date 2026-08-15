import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'controller.dart';
import 'models.dart';

const _surface = Color(0xff181d21);
const _surfaceHigh = Color(0xff20262b);
const _border = Color(0xff30383e);
const _muted = Color(0xff94a1a8);
const _cyan = Color(0xff3bc8c2);
const _amber = Color(0xffffb454);
const _red = Color(0xffff6b6b);

class AppLogPanel extends StatefulWidget {
  const AppLogPanel({super.key, required this.controller});
  final RmfController controller;

  @override
  State<AppLogPanel> createState() => _AppLogPanelState();
}

class _AppLogPanelState extends State<AppLogPanel> {
  bool _expanded = false;
  final ScrollController _scrollController = ScrollController();

  @override
  void dispose() {
    _scrollController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final logs = widget.controller.appLogs;
    return Container(
      decoration: const BoxDecoration(
        color: Color(0xff0b0e10),
        border: Border(top: BorderSide(color: _border)),
      ),
      child: Column(
        children: [
          SizedBox(
            height: 38,
            child: Row(
              children: [
                IconButton(
                  visualDensity: VisualDensity.compact,
                  tooltip: _expanded ? '로그 접기' : '로그 펼치기',
                  onPressed: () => setState(() => _expanded = !_expanded),
                  icon: Icon(
                    _expanded ? Icons.expand_more : Icons.expand_less,
                    size: 19,
                  ),
                ),
                const Icon(Icons.terminal, size: 15, color: _cyan),
                const SizedBox(width: 7),
                Text(
                  'LOG  ${logs.length}',
                  style: const TextStyle(
                    color: _muted,
                    fontSize: 10,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                const Spacer(),
                IconButton(
                  visualDensity: VisualDensity.compact,
                  tooltip: '전체 로그 복사',
                  onPressed: logs.isEmpty ? null : () => _copyLogs(context),
                  icon: const Icon(Icons.copy_all_outlined, size: 17),
                ),
                IconButton(
                  visualDensity: VisualDensity.compact,
                  tooltip: '로그 지우기',
                  onPressed: logs.isEmpty ? null : widget.controller.clearLogs,
                  icon: const Icon(Icons.delete_sweep_outlined, size: 17),
                ),
                const SizedBox(width: 6),
              ],
            ),
          ),
          if (_expanded)
            SizedBox(
              height: 190,
              child: logs.isEmpty
                  ? const Center(
                      child: Text('로그가 없습니다.', style: TextStyle(color: _muted)),
                    )
                  : ListView.builder(
                      controller: _scrollController,
                      padding: const EdgeInsets.fromLTRB(12, 6, 12, 10),
                      itemCount: logs.length,
                      itemBuilder: (context, index) => SelectableText(
                        logs[index],
                        style: TextStyle(
                          fontFamily: 'monospace',
                          fontSize: 11,
                          height: 1.35,
                          color: logs[index].contains('[error]')
                              ? _red
                              : const Color(0xffc8d1d4),
                        ),
                      ),
                    ),
            ),
        ],
      ),
    );
  }

  Future<void> _copyLogs(BuildContext context) async {
    await Clipboard.setData(
      ClipboardData(text: widget.controller.appLogs.join('\n')),
    );
    if (!context.mounted) return;
    ScaffoldMessenger.of(
      context,
    ).showSnackBar(const SnackBar(content: Text('전체 로그를 클립보드에 복사했습니다.')));
  }
}

class TasksView extends StatefulWidget {
  const TasksView({super.key, required this.controller});
  final RmfController controller;

  @override
  State<TasksView> createState() => _TasksViewState();
}

class _TasksViewState extends State<TasksView> {
  String _query = '';
  String _status = 'all';

  @override
  Widget build(BuildContext context) {
    final tasks = widget.controller.tasks.where((task) {
      final matchesStatus = _status == 'all' || task.status == _status;
      final haystack =
          '${task.id} ${task.category} ${task.fleet} ${task.robot} ${task.requester}'
              .toLowerCase();
      return matchesStatus && haystack.contains(_query.toLowerCase());
    }).toList();
    final statuses = {
      'all',
      ...widget.controller.tasks.map((task) => task.status),
    }.toList();
    return _Page(
      title: '태스크 관제',
      subtitle: '태스크 요청, 검색, 진행 확인 및 취소',
      actions: [
        FilledButton.icon(
          onPressed: widget.controller.commandInProgress
              ? null
              : () => showDialog<void>(
                  context: context,
                  builder: (_) =>
                      _TaskRequestDialog(controller: widget.controller),
                ),
          icon: const Icon(Icons.add),
          label: const Text('새 태스크'),
        ),
      ],
      child: Column(
        children: [
          Padding(
            padding: const EdgeInsets.all(12),
            child: Row(
              children: [
                Expanded(
                  child: TextField(
                    decoration: const InputDecoration(
                      prefixIcon: Icon(Icons.search),
                      labelText: 'ID, 유형, 로봇 또는 요청자 검색',
                      border: OutlineInputBorder(),
                    ),
                    onChanged: (value) => setState(() => _query = value),
                  ),
                ),
                const SizedBox(width: 12),
                DropdownButton<String>(
                  value: statuses.contains(_status) ? _status : 'all',
                  items: statuses
                      .map(
                        (value) => DropdownMenuItem(
                          value: value,
                          child: Text(value == 'all' ? '전체 상태' : value),
                        ),
                      )
                      .toList(),
                  onChanged: (value) => setState(() => _status = value!),
                ),
              ],
            ),
          ),
          Expanded(
            child: Column(
              children: [
                if (widget.controller.scheduledTasks.isNotEmpty)
                  SizedBox(
                    height: 72,
                    child: ListView.separated(
                      padding: const EdgeInsets.symmetric(horizontal: 12),
                      scrollDirection: Axis.horizontal,
                      itemCount: widget.controller.scheduledTasks.length,
                      separatorBuilder: (_, _) => const SizedBox(width: 8),
                      itemBuilder: (context, index) {
                        final scheduled =
                            widget.controller.scheduledTasks[index];
                        final id = (scheduled['id'] as num?)?.toInt();
                        return InputChip(
                          avatar: const Icon(Icons.schedule, size: 17),
                          label: Text(
                            '예약 #${id ?? '-'} · ${scheduled['created_by'] ?? ''}',
                          ),
                          onDeleted: id == null
                              ? null
                              : () => widget.controller.deleteScheduledTask(id),
                        );
                      },
                    ),
                  ),
                Expanded(
                  child: tasks.isEmpty
                      ? const _Empty(
                          icon: Icons.route_outlined,
                          text: '표시할 태스크가 없습니다.',
                        )
                      : ListView.separated(
                          padding: const EdgeInsets.fromLTRB(12, 0, 12, 16),
                          itemCount: tasks.length,
                          separatorBuilder: (_, _) => const SizedBox(height: 7),
                          itemBuilder: (context, index) {
                            final task = tasks[index];
                            return Card(
                              child: ListTile(
                                leading: _StatusDot(active: task.isActive),
                                title: Text('${task.category} · ${task.id}'),
                                subtitle: Text(
                                  '${task.status}  ${task.fleet ?? '-'} / ${task.robot ?? '-'}'
                                  '${task.requester == null ? '' : '  요청: ${task.requester}'}',
                                ),
                                trailing: Row(
                                  mainAxisSize: MainAxisSize.min,
                                  children: [
                                    if (task.isActive)
                                      IconButton(
                                        tooltip: '태스크 취소',
                                        onPressed:
                                            widget.controller.commandInProgress
                                            ? null
                                            : () =>
                                                  _confirmCancel(context, task),
                                        icon: const Icon(
                                          Icons.cancel_outlined,
                                          color: _red,
                                        ),
                                      ),
                                    if (task.isCanceled)
                                      IconButton(
                                        tooltip: '취소된 태스크 목록에서 삭제',
                                        onPressed:
                                            widget.controller.commandInProgress
                                            ? null
                                            : () => _confirmDeleteCanceled(
                                                context,
                                                task,
                                              ),
                                        icon: const Icon(
                                          Icons.delete_outline,
                                          color: _red,
                                        ),
                                      ),
                                    IconButton(
                                      tooltip: '상세 및 로그',
                                      onPressed: () => _showTask(context, task),
                                      icon: const Icon(Icons.chevron_right),
                                    ),
                                  ],
                                ),
                                onTap: () => _showTask(context, task),
                              ),
                            );
                          },
                        ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Future<void> _confirmCancel(BuildContext context, RmfTask task) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('태스크 취소'),
        content: Text('${task.id} 태스크를 취소하시겠습니까?'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('닫기'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('취소 요청'),
          ),
        ],
      ),
    );
    if (confirmed == true) await widget.controller.cancelTask(task.id);
  }

  Future<void> _confirmDeleteCanceled(
    BuildContext context,
    RmfTask task,
  ) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('취소 태스크 삭제'),
        content: Text(
          '${task.id} 태스크를 이 목록에서 삭제하시겠습니까?\n'
          'RMF 서버의 감사 이력은 유지됩니다.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('닫기'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('목록에서 삭제'),
          ),
        ],
      ),
    );
    if (confirmed == true) {
      widget.controller.dismissCanceledTask(task);
    }
  }

  void _showTask(BuildContext context, RmfTask task) {
    showDialog<void>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text('${task.category} · ${task.id}'),
        content: SizedBox(
          width: 680,
          height: 480,
          child: FutureBuilder<Map<String, dynamic>?>(
            future: widget.controller.getTaskLog(task.id),
            builder: (context, snapshot) => ListView(
              children: [
                _DetailTable({
                  '상태': task.status,
                  'Fleet': task.fleet ?? '-',
                  '로봇': task.robot ?? '-',
                  '요청자': task.requester ?? '-',
                  '요청 시각': _date(task.requestedAt),
                  '시작 시각': _date(task.startedAt),
                  '완료 시각': _date(task.finishedAt),
                }),
                const SizedBox(height: 16),
                const Text('상태 원문', style: TextStyle(color: _cyan)),
                _JsonBox(task.detail),
                const SizedBox(height: 16),
                const Text('이벤트 로그', style: TextStyle(color: _cyan)),
                if (snapshot.connectionState == ConnectionState.waiting)
                  const LinearProgressIndicator()
                else
                  _JsonBox(snapshot.data ?? {'message': '로그가 없습니다.'}),
              ],
            ),
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('닫기'),
          ),
        ],
      ),
    );
  }
}

class RobotsView extends StatefulWidget {
  const RobotsView({super.key, required this.controller});
  final RmfController controller;

  @override
  State<RobotsView> createState() => _RobotsViewState();
}

class _RobotsViewState extends State<RobotsView> {
  String? _fleet;

  @override
  Widget build(BuildContext context) {
    final fleets = widget.controller.robots.map((e) => e.fleet).toSet().toList()
      ..sort();
    final robots = widget.controller.robots
        .where((robot) => _fleet == null || robot.fleet == _fleet)
        .toList();
    return _Page(
      title: '로봇 및 Fleet',
      subtitle: '상태, 배터리, 이슈와 운행 투입 상태 관리',
      actions: [
        DropdownButton<String?>(
          value: fleets.contains(_fleet) ? _fleet : null,
          hint: const Text('모든 Fleet'),
          items: [
            const DropdownMenuItem(value: null, child: Text('모든 Fleet')),
            ...fleets.map(
              (fleet) => DropdownMenuItem(value: fleet, child: Text(fleet)),
            ),
          ],
          onChanged: (value) => setState(() => _fleet = value),
        ),
      ],
      child: robots.isEmpty
          ? const _Empty(icon: Icons.smart_toy_outlined, text: '로봇이 없습니다.')
          : GridView.builder(
              padding: const EdgeInsets.all(12),
              gridDelegate: const SliverGridDelegateWithMaxCrossAxisExtent(
                maxCrossAxisExtent: 430,
                mainAxisExtent: 285,
                crossAxisSpacing: 10,
                mainAxisSpacing: 10,
              ),
              itemCount: robots.length,
              itemBuilder: (context, index) {
                final robot = robots[index];
                return Card(
                  child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            _StatusDot(active: robot.status != 'offline'),
                            const SizedBox(width: 10),
                            Expanded(
                              child: Text(
                                robot.name,
                                style: Theme.of(context).textTheme.titleMedium,
                              ),
                            ),
                            Text(
                              robot.fleet,
                              style: const TextStyle(color: _muted),
                            ),
                          ],
                        ),
                        const SizedBox(height: 14),
                        _DetailTable({
                          '상태': robot.status,
                          '위치':
                              '${robot.level}  (${robot.x.toStringAsFixed(2)}, ${robot.y.toStringAsFixed(2)})',
                          '태스크': robot.taskId ?? '-',
                          '이슈': '${robot.issueCount}',
                          'Mutex 보유': robot.lockedMutexGroups.isEmpty
                              ? '-'
                              : robot.lockedMutexGroups.join(', '),
                          'Mutex 대기': robot.requestingMutexGroups.isEmpty
                              ? '-'
                              : robot.requestingMutexGroups.join(', '),
                        }),
                        const Spacer(),
                        Row(
                          children: [
                            const Icon(Icons.battery_5_bar, size: 18),
                            const SizedBox(width: 6),
                            Expanded(
                              child: LinearProgressIndicator(
                                value: robot.battery,
                              ),
                            ),
                            const SizedBox(width: 8),
                            Text('${(robot.battery * 100).round()}%'),
                            const SizedBox(width: 16),
                            PopupMenuButton<String>(
                              enabled: !widget.controller.commandInProgress,
                              tooltip: '운행 관리',
                              onSelected: (value) {
                                if (value == 'off') {
                                  widget.controller.decommissionRobot(robot);
                                } else {
                                  widget.controller.recommissionRobot(robot);
                                }
                              },
                              itemBuilder: (_) => const [
                                PopupMenuItem(
                                  value: 'on',
                                  child: Text('운행 복귀'),
                                ),
                                PopupMenuItem(
                                  value: 'off',
                                  child: Text('운행 제외'),
                                ),
                              ],
                            ),
                            if (robot.lockedMutexGroups.isNotEmpty)
                              PopupMenuButton<String>(
                                enabled: !widget.controller.commandInProgress,
                                tooltip: 'Mutex 수동 해제',
                                icon: const Icon(Icons.lock_open_outlined),
                                onSelected: (group) =>
                                    widget.controller.unlockMutex(robot, group),
                                itemBuilder: (_) => robot.lockedMutexGroups
                                    .map(
                                      (group) => PopupMenuItem(
                                        value: group,
                                        child: Text('$group 해제'),
                                      ),
                                    )
                                    .toList(),
                              ),
                          ],
                        ),
                      ],
                    ),
                  ),
                );
              },
            ),
    );
  }
}

class InfrastructureView extends StatelessWidget {
  const InfrastructureView({super.key, required this.controller});
  final RmfController controller;

  @override
  Widget build(BuildContext context) {
    return _Page(
      title: '건물 설비',
      subtitle: '도어, 리프트, 디스펜서 및 인제스터 상태와 제어',
      child: ListView(
        padding: const EdgeInsets.all(12),
        children: [
          _SectionTitle('도어', controller.doors.length),
          if (controller.doors.isEmpty)
            const _InlineEmpty('등록된 도어가 없습니다.')
          else
            Wrap(
              spacing: 10,
              runSpacing: 10,
              children: controller.doors
                  .map(
                    (door) => _FacilityCard(
                      width: 310,
                      icon: Icons.meeting_room_outlined,
                      title: door.name,
                      subtitle: door.stateLabel,
                      child: SegmentedButton<int>(
                        segments: const [
                          ButtonSegment(value: 0, label: Text('닫기')),
                          ButtonSegment(value: 2, label: Text('열기')),
                        ],
                        selected: {door.mode == 2 ? 2 : 0},
                        onSelectionChanged: controller.commandInProgress
                            ? null
                            : (value) => controller.setDoor(door, value.first),
                      ),
                    ),
                  )
                  .toList(),
            ),
          const SizedBox(height: 24),
          _SectionTitle('리프트', controller.lifts.length),
          if (controller.lifts.isEmpty)
            const _InlineEmpty('등록된 리프트가 없습니다.')
          else
            Wrap(
              spacing: 10,
              runSpacing: 10,
              children: controller.lifts
                  .map(
                    (lift) => _FacilityCard(
                      width: 380,
                      icon: Icons.elevator_outlined,
                      title: lift.name,
                      subtitle:
                          '현재 ${lift.currentFloor} · 목적지 ${lift.destinationFloor.isEmpty ? '-' : lift.destinationFloor}',
                      child: Wrap(
                        spacing: 7,
                        runSpacing: 7,
                        children: lift.availableFloors
                            .map(
                              (floor) => OutlinedButton(
                                onPressed: controller.commandInProgress
                                    ? null
                                    : () => controller.callLift(lift, floor),
                                child: Text(floor),
                              ),
                            )
                            .toList(),
                      ),
                    ),
                  )
                  .toList(),
            ),
          const SizedBox(height: 24),
          _SectionTitle('Workcells', controller.workcells.length),
          if (controller.workcells.isEmpty)
            const _InlineEmpty('등록된 디스펜서 또는 인제스터가 없습니다.')
          else
            Wrap(
              spacing: 10,
              runSpacing: 10,
              children: controller.workcells
                  .map(
                    (cell) => _FacilityCard(
                      width: 310,
                      icon: cell.kind == 'dispenser'
                          ? Icons.outbox_outlined
                          : Icons.move_to_inbox_outlined,
                      title: cell.id,
                      subtitle: '${cell.kind} · mode ${cell.mode}',
                      child: Text('대기 요청 ${cell.queue}개'),
                    ),
                  )
                  .toList(),
            ),
        ],
      ),
    );
  }
}

class AlertsView extends StatelessWidget {
  const AlertsView({super.key, required this.controller});
  final RmfController controller;

  @override
  Widget build(BuildContext context) {
    return _Page(
      title: '운영 알림',
      subtitle: '응답이 필요한 RMF 경고와 작업 요청',
      child: controller.alerts.isEmpty
          ? const _Empty(
              icon: Icons.notifications_none,
              text: '응답 대기 중인 알림이 없습니다.',
            )
          : ListView.separated(
              padding: const EdgeInsets.all(12),
              itemCount: controller.alerts.length,
              separatorBuilder: (_, _) => const SizedBox(height: 8),
              itemBuilder: (context, index) {
                final alert = controller.alerts[index];
                final color = switch (alert.tier) {
                  'error' => _red,
                  'warning' => _amber,
                  _ => _cyan,
                };
                return Card(
                  child: ListTile(
                    leading: Icon(Icons.warning_amber, color: color),
                    title: Text(alert.title),
                    subtitle: Text(
                      '${alert.subtitle}${alert.subtitle.isEmpty ? '' : '\n'}${alert.message}'
                      '${alert.taskId == null ? '' : '\nTask: ${alert.taskId}'}',
                    ),
                    isThreeLine: true,
                    trailing: Wrap(
                      spacing: 6,
                      children: alert.responses
                          .map(
                            (response) => FilledButton.tonal(
                              onPressed: controller.commandInProgress
                                  ? null
                                  : () => controller.respondToAlert(
                                      alert,
                                      response,
                                    ),
                              child: Text(response),
                            ),
                          )
                          .toList(),
                    ),
                  ),
                );
              },
            ),
    );
  }
}

class _TaskRequestDialog extends StatefulWidget {
  const _TaskRequestDialog({required this.controller});
  final RmfController controller;

  @override
  State<_TaskRequestDialog> createState() => _TaskRequestDialogState();
}

class _TaskRequestDialogState extends State<_TaskRequestDialog> {
  String _type = 'patrol';
  String? _fleet;
  bool _highPriority = false;
  bool _scheduled = false;
  String _period = 'day';
  final _first = TextEditingController();
  final _second = TextEditingController();
  final _third = TextEditingController();
  final _rounds = TextEditingController(text: '1');
  final _at = TextEditingController(text: '09:00');
  final _custom = TextEditingController(
    text: const JsonEncoder.withIndent('  ').convert({
      'category': 'compose',
      'description': {'category': 'clean', 'phases': <Object>[]},
    }),
  );
  String? _error;

  @override
  void dispose() {
    _first.dispose();
    _second.dispose();
    _third.dispose();
    _rounds.dispose();
    _at.dispose();
    _custom.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final fleets = widget.controller.robots.map((e) => e.fleet).toSet().toList()
      ..sort();
    final waypoints =
        widget.controller.building?.levels
            .expand((level) => level.waypointNames)
            .toSet()
            .toList() ??
        <String>[];
    waypoints.sort();
    return AlertDialog(
      title: const Text('새 태스크 요청'),
      content: SizedBox(
        width: 620,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              DropdownButtonFormField<String>(
                initialValue: _type,
                decoration: const InputDecoration(
                  labelText: '태스크 유형',
                  border: OutlineInputBorder(),
                ),
                items: const [
                  DropdownMenuItem(value: 'patrol', child: Text('Patrol')),
                  DropdownMenuItem(value: 'delivery', child: Text('Delivery')),
                  DropdownMenuItem(value: 'clean', child: Text('Clean')),
                  DropdownMenuItem(
                    value: 'custom',
                    child: Text('Custom Compose'),
                  ),
                ],
                onChanged: (value) => setState(() => _type = value!),
              ),
              const SizedBox(height: 12),
              DropdownButtonFormField<String?>(
                initialValue: _fleet,
                decoration: const InputDecoration(
                  labelText: 'Fleet 지정 (선택)',
                  border: OutlineInputBorder(),
                ),
                items: [
                  const DropdownMenuItem(value: null, child: Text('자동 입찰')),
                  ...fleets.map(
                    (fleet) =>
                        DropdownMenuItem(value: fleet, child: Text(fleet)),
                  ),
                ],
                onChanged: (value) => setState(() => _fleet = value),
              ),
              const SizedBox(height: 12),
              if (_type == 'custom')
                TextField(
                  controller: _custom,
                  minLines: 12,
                  maxLines: 18,
                  style: const TextStyle(fontFamily: 'monospace', fontSize: 12),
                  decoration: const InputDecoration(
                    labelText: 'TaskRequest JSON',
                    border: OutlineInputBorder(),
                  ),
                )
              else ...[
                _WaypointField(
                  controller: _first,
                  options: waypoints,
                  label: switch (_type) {
                    'patrol' => '경유지 (쉼표로 구분)',
                    'delivery' => 'Pickup 위치',
                    _ => '청소 구역',
                  },
                ),
                if (_type == 'patrol') ...[
                  const SizedBox(height: 12),
                  TextField(
                    controller: _rounds,
                    keyboardType: TextInputType.number,
                    decoration: const InputDecoration(
                      labelText: '반복 횟수',
                      border: OutlineInputBorder(),
                    ),
                  ),
                ],
                if (_type == 'delivery') ...[
                  const SizedBox(height: 12),
                  _WaypointField(
                    controller: _second,
                    options: waypoints,
                    label: 'Dropoff 위치',
                  ),
                  const SizedBox(height: 12),
                  TextField(
                    controller: _third,
                    decoration: const InputDecoration(
                      labelText: 'Payload SKU',
                      border: OutlineInputBorder(),
                    ),
                  ),
                ],
              ],
              CheckboxListTile(
                value: _highPriority,
                contentPadding: EdgeInsets.zero,
                title: const Text('높은 우선순위'),
                onChanged: (value) =>
                    setState(() => _highPriority = value ?? false),
              ),
              CheckboxListTile(
                value: _scheduled,
                contentPadding: EdgeInsets.zero,
                title: const Text('반복 실행 예약'),
                onChanged: (value) =>
                    setState(() => _scheduled = value ?? false),
              ),
              if (_scheduled)
                Row(
                  children: [
                    Expanded(
                      child: DropdownButtonFormField<String>(
                        initialValue: _period,
                        decoration: const InputDecoration(
                          labelText: '주기',
                          border: OutlineInputBorder(),
                        ),
                        items: const [
                          DropdownMenuItem(value: 'day', child: Text('매일')),
                          DropdownMenuItem(
                            value: 'monday',
                            child: Text('매주 월요일'),
                          ),
                          DropdownMenuItem(
                            value: 'tuesday',
                            child: Text('매주 화요일'),
                          ),
                          DropdownMenuItem(
                            value: 'wednesday',
                            child: Text('매주 수요일'),
                          ),
                          DropdownMenuItem(
                            value: 'thursday',
                            child: Text('매주 목요일'),
                          ),
                          DropdownMenuItem(
                            value: 'friday',
                            child: Text('매주 금요일'),
                          ),
                          DropdownMenuItem(
                            value: 'saturday',
                            child: Text('매주 토요일'),
                          ),
                          DropdownMenuItem(
                            value: 'sunday',
                            child: Text('매주 일요일'),
                          ),
                        ],
                        onChanged: (value) => _period = value!,
                      ),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: TextField(
                        controller: _at,
                        decoration: const InputDecoration(
                          labelText: '시각 (HH:mm)',
                          border: OutlineInputBorder(),
                        ),
                      ),
                    ),
                  ],
                ),
              if (_error != null)
                Align(
                  alignment: Alignment.centerLeft,
                  child: Text(_error!, style: const TextStyle(color: _red)),
                ),
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('닫기'),
        ),
        FilledButton.icon(
          onPressed: _submit,
          icon: const Icon(Icons.send),
          label: const Text('요청'),
        ),
      ],
    );
  }

  Future<void> _submit() async {
    try {
      Map<String, dynamic> request;
      if (_type == 'custom') {
        final decoded = jsonDecode(_custom.text);
        if (decoded is! Map) throw const FormatException('JSON 객체가 필요합니다.');
        request = Map<String, dynamic>.from(decoded);
      } else {
        final description = switch (_type) {
          'patrol' => {
            'places': _first.text
                .split(',')
                .map((e) => e.trim())
                .where((e) => e.isNotEmpty)
                .toList(),
            'rounds': int.tryParse(_rounds.text) ?? 1,
          },
          'delivery' => {
            'pickup': {
              'place': _first.text.trim(),
              'handler': 'coke_dispenser',
              'payload': {'sku': _third.text.trim(), 'quantity': 1},
            },
            'dropoff': {
              'place': _second.text.trim(),
              'handler': 'coke_ingestor',
              'payload': {'sku': _third.text.trim(), 'quantity': 1},
            },
          },
          _ => {
            'category': 'clean',
            'phases': [
              {
                'activity': {
                  'category': 'sequence',
                  'description': {
                    'activities': [
                      {
                        'category': 'go_to_place',
                        'description': _first.text.trim(),
                      },
                      {
                        'category': 'perform_action',
                        'description': {
                          'unix_millis_action_duration_estimate': 60000,
                          'category': 'clean',
                          'expected_finish_location': _first.text.trim(),
                          'description': {'zone': _first.text.trim()},
                          'use_tool_sink': true,
                        },
                      },
                    ],
                  },
                },
              },
            ],
          },
        };
        if (_first.text.trim().isEmpty ||
            (_type == 'delivery' &&
                (_second.text.trim().isEmpty || _third.text.trim().isEmpty))) {
          throw const FormatException('필수 값을 입력하세요.');
        }
        request = {
          'category': _type == 'clean' ? 'compose' : _type,
          'description': description,
          // The office demo runs all RMF nodes on Gazebo simulation time,
          // which begins at zero. A wall-clock epoch timestamp would leave
          // the awarded task queued for years of simulated time. Zero means
          // the task can begin immediately in both simulated and real-time
          // RMF deployments.
          'unix_millis_earliest_start_time': 0,
          'requester': 'openrmf_app',
          'priority': {'type': 'binary', 'value': _highPriority ? 1 : 0},
          'labels': ['app=openrmf_app', 'task_definition_id=$_type'],
          if (_fleet != null) 'fleet_name': _fleet,
        };
      }
      if (_scheduled) {
        if (!RegExp(r'^\d{2}:\d{2}$').hasMatch(_at.text)) {
          throw const FormatException('예약 시각은 HH:mm 형식이어야 합니다.');
        }
        await widget.controller.scheduleTask(request, _period, _at.text);
      } else {
        await widget.controller.dispatchTask(request);
      }
      if (mounted) Navigator.pop(context);
    } catch (exception) {
      setState(() => _error = '$exception');
    }
  }
}

class _WaypointField extends StatelessWidget {
  const _WaypointField({
    required this.controller,
    required this.options,
    required this.label,
  });
  final TextEditingController controller;
  final List<String> options;
  final String label;

  @override
  Widget build(BuildContext context) {
    return Autocomplete<String>(
      optionsBuilder: (value) => options.where(
        (option) =>
            value.text.isEmpty ||
            option.toLowerCase().contains(value.text.toLowerCase()),
      ),
      onSelected: (value) => controller.text = value,
      fieldViewBuilder: (context, fieldController, focus, submit) {
        if (fieldController.text.isEmpty && controller.text.isNotEmpty) {
          fieldController.text = controller.text;
        }
        fieldController.addListener(
          () => controller.text = fieldController.text,
        );
        return TextField(
          controller: fieldController,
          focusNode: focus,
          decoration: InputDecoration(
            labelText: label,
            border: const OutlineInputBorder(),
          ),
        );
      },
    );
  }
}

class _Page extends StatelessWidget {
  const _Page({
    required this.title,
    required this.subtitle,
    required this.child,
    this.actions = const [],
  });
  final String title;
  final String subtitle;
  final Widget child;
  final List<Widget> actions;

  @override
  Widget build(BuildContext context) {
    return ColoredBox(
      color: const Color(0xff101417),
      child: Column(
        children: [
          Container(
            padding: const EdgeInsets.fromLTRB(18, 14, 18, 14),
            decoration: const BoxDecoration(
              color: _surface,
              border: Border(bottom: BorderSide(color: _border)),
            ),
            child: Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        title,
                        style: Theme.of(context).textTheme.titleLarge,
                      ),
                      Text(subtitle, style: const TextStyle(color: _muted)),
                    ],
                  ),
                ),
                ...actions,
              ],
            ),
          ),
          Expanded(child: child),
        ],
      ),
    );
  }
}

class _FacilityCard extends StatelessWidget {
  const _FacilityCard({
    required this.width,
    required this.icon,
    required this.title,
    required this.subtitle,
    required this.child,
  });
  final double width;
  final IconData icon;
  final String title;
  final String subtitle;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: width,
      child: Card(
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Icon(icon, color: _cyan),
                  const SizedBox(width: 9),
                  Expanded(child: Text(title)),
                ],
              ),
              const SizedBox(height: 4),
              Text(subtitle, style: const TextStyle(color: _muted)),
              const SizedBox(height: 12),
              child,
            ],
          ),
        ),
      ),
    );
  }
}

class _SectionTitle extends StatelessWidget {
  const _SectionTitle(this.title, this.count);
  final String title;
  final int count;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(bottom: 9),
    child: Text(
      '$title  $count',
      style: Theme.of(context).textTheme.titleMedium?.copyWith(color: _cyan),
    ),
  );
}

class _DetailTable extends StatelessWidget {
  const _DetailTable(this.values);
  final Map<String, String> values;

  @override
  Widget build(BuildContext context) => Column(
    children: values.entries
        .map(
          (entry) => Padding(
            padding: const EdgeInsets.symmetric(vertical: 3),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                SizedBox(
                  width: 85,
                  child: Text(entry.key, style: const TextStyle(color: _muted)),
                ),
                Expanded(child: Text(entry.value)),
              ],
            ),
          ),
        )
        .toList(),
  );
}

class _JsonBox extends StatelessWidget {
  const _JsonBox(this.value);
  final Object value;

  @override
  Widget build(BuildContext context) => Container(
    width: double.infinity,
    margin: const EdgeInsets.only(top: 7),
    padding: const EdgeInsets.all(10),
    decoration: BoxDecoration(
      color: _surfaceHigh,
      border: Border.all(color: _border),
      borderRadius: BorderRadius.circular(5),
    ),
    child: SelectableText(
      const JsonEncoder.withIndent('  ').convert(value),
      style: const TextStyle(fontFamily: 'monospace', fontSize: 11),
    ),
  );
}

class _StatusDot extends StatelessWidget {
  const _StatusDot({required this.active});
  final bool active;

  @override
  Widget build(BuildContext context) => Container(
    width: 10,
    height: 10,
    decoration: BoxDecoration(
      color: active ? _cyan : _muted,
      shape: BoxShape.circle,
    ),
  );
}

class _Empty extends StatelessWidget {
  const _Empty({required this.icon, required this.text});
  final IconData icon;
  final String text;

  @override
  Widget build(BuildContext context) => Center(
    child: Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(icon, size: 38, color: _muted),
        const SizedBox(height: 10),
        Text(text, style: const TextStyle(color: _muted)),
      ],
    ),
  );
}

class _InlineEmpty extends StatelessWidget {
  const _InlineEmpty(this.text);
  final String text;

  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.all(18),
    decoration: BoxDecoration(
      color: _surface,
      border: Border.all(color: _border),
      borderRadius: BorderRadius.circular(6),
    ),
    child: Text(text, style: const TextStyle(color: _muted)),
  );
}

String _date(DateTime? value) =>
    value == null ? '-' : value.toLocal().toString().split('.').first;
