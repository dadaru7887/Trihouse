/// ROS2 확인 — 노드·토픽·서비스·액션을 화면에서 들여다본다.
///
/// 탭마다 **목록만** 보여 준다. 하나를 누르면 자세한 내용을 움직일 수 있는 팝업에
/// 띄운다. 목록에 상세를 함께 늘어놓으면 서른 개가 넘는 노드에서 정작 찾는 것이
/// 안 보인다.
///
/// 토픽 팝업에는 **값 한 건 읽기**가 붙는다. 목록에는 있어도 발행자가 없는 토픽이
/// 흔해서, 값이 오는지가 원인을 짚는 첫 갈림길이다.
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'movable_dialog.dart';
import 'ros2_inspect.dart';

class Ros2InspectPage extends StatefulWidget {
  const Ros2InspectPage({super.key});

  @override
  State<Ros2InspectPage> createState() => _Ros2InspectPageState();
}

class _Ros2InspectPageState extends State<Ros2InspectPage>
    with SingleTickerProviderStateMixin {
  static const _kinds = Ros2Kind.values;

  late final TabController _tabs = TabController(
    length: _kinds.length,
    vsync: this,
  );
  final _filter = TextEditingController();

  /// 탭마다 따로 담는다. 탭을 옮길 때마다 다시 읽으면 느리다.
  final Map<Ros2Kind, Ros2ListResult> _results = {};
  final Set<Ros2Kind> _loading = {};

  Ros2Probe _probe = Ros2Probe.daemon;
  int _spinSeconds = 3;
  bool _includeHidden = false;

  Ros2Kind get _kind => _kinds[_tabs.index];
  Ros2InspectRequest get _request => Ros2InspectRequest(
    probe: _probe,
    spinSeconds: _spinSeconds,
    includeHidden: _includeHidden,
  );

  @override
  void initState() {
    super.initState();
    _tabs.addListener(() {
      if (_tabs.indexIsChanging) return;
      setState(() {});
      // 처음 열는 탭만 읽는다.
      if (!_results.containsKey(_kind)) _load(_kind);
    });
    _load(_kind);
  }

  @override
  void dispose() {
    _tabs.dispose();
    _filter.dispose();
    super.dispose();
  }

  Future<void> _load(Ros2Kind kind) async {
    setState(() => _loading.add(kind));
    final result = await ros2List(kind, _request);
    if (!mounted) return;
    setState(() {
      _loading.remove(kind);
      _results[kind] = result;
    });
  }

  /// 조회 방식을 바꾸면 지금 탭만 다시 읽는다. 네 탭을 다 읽으면 오래 걸린다.
  void _changeProbe(void Function() change) {
    setState(change);
    _load(_kind);
  }

  Future<void> _openDetail(Ros2Kind kind, Ros2Item item) =>
      showMovableDialog<void>(
        context: context,
        builder: (_) =>
            _Ros2DetailDialog(kind: kind, item: item, request: _request),
      );

  @override
  Widget build(BuildContext context) {
    final result = _results[_kind];
    final loading = _loading.contains(_kind);
    final needle = _filter.text.trim().toLowerCase();
    final items = [
      for (final item in result?.items ?? const <Ros2Item>[])
        if (needle.isEmpty ||
            item.name.toLowerCase().contains(needle) ||
            (item.type ?? '').toLowerCase().contains(needle))
          item,
    ];

    return Column(
      children: [
        Material(
          color: Colors.white,
          child: Column(
            children: [
              TabBar(
                controller: _tabs,
                isScrollable: true,
                tabAlignment: TabAlignment.start,
                tabs: [
                  for (final kind in _kinds)
                    Tab(text: '${kind.label} (${kind.command})'),
                ],
              ),
              _toolbar(result, loading, items.length),
            ],
          ),
        ),
        Expanded(
          child: loading
              ? const Center(child: CircularProgressIndicator())
              : _list(result, items),
        ),
      ],
    );
  }

  Widget _toolbar(Ros2ListResult? result, bool loading, int shown) => Padding(
    padding: const EdgeInsets.fromLTRB(24, 14, 24, 12),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Wrap(
          spacing: 10,
          runSpacing: 10,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: [
            FilledButton.icon(
              onPressed: loading ? null : () => _load(_kind),
              icon: const Icon(Icons.refresh, size: 18),
              label: const Text('다시 읽기'),
            ),
            SizedBox(
              width: 230,
              child: TextField(
                controller: _filter,
                onChanged: (_) => setState(() {}),
                decoration: const InputDecoration(
                  labelText: '이름·형식으로 걸러내기',
                  isDense: true,
                  prefixIcon: Icon(Icons.search, size: 18),
                  border: OutlineInputBorder(),
                ),
              ),
            ),
            // 데몬과 직접 탐색의 결과가 서로 다르게 나오는 일을 겪었다. 화면에서
            // 바로 견줄 수 있어야 한다.
            SegmentedButton<Ros2Probe>(
              segments: [
                for (final probe in Ros2Probe.values)
                  ButtonSegment(value: probe, label: Text(probe.label)),
              ],
              selected: {_probe},
              onSelectionChanged: (value) =>
                  _changeProbe(() => _probe = value.first),
            ),
            if (_probe == Ros2Probe.direct && _kind.takesProbeOptions)
              SizedBox(
                width: 150,
                child: DropdownButtonFormField<int>(
                  initialValue: _spinSeconds,
                  decoration: const InputDecoration(
                    labelText: '탐색 시간',
                    isDense: true,
                    border: OutlineInputBorder(),
                  ),
                  items: const [
                    DropdownMenuItem(value: 1, child: Text('1초')),
                    DropdownMenuItem(value: 3, child: Text('3초')),
                    DropdownMenuItem(value: 5, child: Text('5초')),
                    DropdownMenuItem(value: 10, child: Text('10초')),
                  ],
                  onChanged: (value) =>
                      _changeProbe(() => _spinSeconds = value ?? _spinSeconds),
                ),
              ),
            if (_kind.includeHiddenFlag != null)
              FilterChip(
                label: const Text('숨은 것까지'),
                selected: _includeHidden,
                onSelected: (value) =>
                    _changeProbe(() => _includeHidden = value),
              ),
          ],
        ),
        const SizedBox(height: 10),
        Row(
          children: [
            Expanded(
              child: Text(
                result == null
                    ? '읽는 중…'
                    : '${result.message}'
                          '${shown != result.items.length ? '  ·  걸러낸 $shown개' : ''}',
                style: TextStyle(
                  fontSize: 12.5,
                  fontWeight: FontWeight.w700,
                  color: result != null && !result.success
                      ? const Color(0xFF991B1B)
                      : const Color(0xFF475569),
                ),
              ),
            ),
            if (result != null && result.command.isNotEmpty)
              _CommandChip(command: result.command),
          ],
        ),
        if (result != null && !result.success) ...[
          const SizedBox(height: 8),
          Container(
            width: double.infinity,
            padding: const EdgeInsets.fromLTRB(13, 10, 13, 11),
            decoration: BoxDecoration(
              color: const Color(0xFFFEF2F2),
              borderRadius: BorderRadius.circular(9),
              border: Border.all(color: const Color(0xFFFCA5A5)),
            ),
            child: SelectableText(
              result.message,
              style: const TextStyle(
                fontSize: 12,
                height: 1.55,
                color: Color(0xFF991B1B),
              ),
            ),
          ),
        ],
      ],
    ),
  );

  Widget _list(Ros2ListResult? result, List<Ros2Item> items) {
    if (result == null) return const SizedBox.shrink();
    if (items.isEmpty) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Text(
            result.items.isEmpty ? result.message : '걸러낸 결과가 없습니다.',
            textAlign: TextAlign.center,
            style: const TextStyle(fontSize: 13, color: Color(0xFF64748B)),
          ),
        ),
      );
    }
    return ListView.separated(
      padding: const EdgeInsets.fromLTRB(24, 4, 24, 28),
      itemCount: items.length,
      separatorBuilder: (_, _) =>
          const Divider(height: 1, color: Color(0xFFE2E8F0)),
      itemBuilder: (context, index) {
        final item = items[index];
        return ListTile(
          dense: true,
          title: SelectableText(
            item.name,
            style: const TextStyle(
              fontSize: 13.5,
              fontWeight: FontWeight.w700,
              fontFamily: 'monospace',
            ),
          ),
          subtitle: item.type == null
              ? null
              : Text(
                  item.type!,
                  style: const TextStyle(
                    fontSize: 12,
                    color: Color(0xFF64748B),
                  ),
                ),
          trailing: const Icon(Icons.open_in_new, size: 17),
          onTap: () => _openDetail(_kind, item),
        );
      },
    );
  }
}

/// 돌린 명령을 보여 주고 복사한다. 터미널에서 그대로 재현할 수 있어야 한다.
class _CommandChip extends StatelessWidget {
  const _CommandChip({required this.command});
  final String command;

  @override
  Widget build(BuildContext context) => Tooltip(
    message: command,
    child: TextButton.icon(
      onPressed: () async {
        await Clipboard.setData(ClipboardData(text: command));
        if (!context.mounted) return;
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(const SnackBar(content: Text('명령을 복사했습니다.')));
      },
      icon: const Icon(Icons.terminal, size: 16),
      label: const Text('명령 복사'),
      style: TextButton.styleFrom(
        padding: const EdgeInsets.symmetric(horizontal: 10),
        minimumSize: const Size(0, 32),
        tapTargetSize: MaterialTapTargetSize.shrinkWrap,
      ),
    ),
  );
}

/// 하나를 자세히 보는 팝업. 움직일 수 있다.
///
/// 팝업이 화면 가운데 고정되면 그 아래 목록을 보면서 견줄 수 없다 —
/// `movable_dialog.dart` 를 쓰는 이유와 같다.
class _Ros2DetailDialog extends StatefulWidget {
  const _Ros2DetailDialog({
    required this.kind,
    required this.item,
    required this.request,
  });

  final Ros2Kind kind;
  final Ros2Item item;
  final Ros2InspectRequest request;

  @override
  State<_Ros2DetailDialog> createState() => _Ros2DetailDialogState();
}

class _Ros2DetailDialogState extends State<_Ros2DetailDialog> {
  Ros2DetailResult? _detail;
  Ros2ValueResult? _value;
  bool _loadingDetail = true;
  bool _loadingValue = false;

  @override
  void initState() {
    super.initState();
    unawaited(_loadDetail());
  }

  Future<void> _loadDetail() async {
    setState(() => _loadingDetail = true);
    final detail = await ros2Detail(
      widget.kind,
      widget.item.name,
      widget.request,
    );
    if (!mounted) return;
    setState(() {
      _detail = detail;
      _loadingDetail = false;
    });
  }

  Future<void> _readValue() async {
    setState(() => _loadingValue = true);
    final value = await ros2TopicValue(widget.item.name, widget.request);
    if (!mounted) return;
    setState(() {
      _value = value;
      _loadingValue = false;
    });
  }

  @override
  Widget build(BuildContext context) {
    final detail = _detail;
    return AlertDialog(
      icon: const Icon(Icons.account_tree_outlined, size: 30),
      title: Text(
        widget.item.name,
        style: const TextStyle(fontSize: 17, fontFamily: 'monospace'),
      ),
      content: SizedBox(
        width: 620,
        child: SingleChildScrollView(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (widget.item.type != null) ...[
                SelectableText(
                  widget.item.type!,
                  style: const TextStyle(
                    fontSize: 12.5,
                    color: Color(0xFF64748B),
                  ),
                ),
                const SizedBox(height: 12),
              ],
              _section(
                '자세히',
                loading: _loadingDetail,
                failed: detail != null && !detail.success,
                text: detail?.text ?? '',
                command: detail?.command ?? '',
                onRetry: _loadDetail,
              ),
              if (widget.kind == Ros2Kind.topic) ...[
                const SizedBox(height: 16),
                _valueSection(),
              ],
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
    );
  }

  Widget _valueSection() {
    final value = _value;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            const Text(
              '수신값',
              style: TextStyle(fontSize: 13.5, fontWeight: FontWeight.w800),
            ),
            const SizedBox(width: 12),
            FilledButton.tonalIcon(
              onPressed: _loadingValue ? null : _readValue,
              icon: _loadingValue
                  ? const SizedBox(
                      width: 15,
                      height: 15,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.download_outlined, size: 16),
              label: Text(_loadingValue ? '기다리는 중…' : '값 한 건 읽기'),
            ),
          ],
        ),
        const SizedBox(height: 4),
        const Text(
          '한 건만 받고 끊습니다. 발행자가 없으면 아무것도 오지 않습니다.',
          style: TextStyle(fontSize: 11.5, color: Color(0xFF94A3B8)),
        ),
        if (value != null) ...[
          const SizedBox(height: 10),
          _resultBox(
            text: value.text,
            command: value.command,
            tone: switch (value.state) {
              Ros2ValueState.received => _Tone.good,
              Ros2ValueState.empty => _Tone.warn,
              Ros2ValueState.failed => _Tone.bad,
            },
          ),
        ],
      ],
    );
  }

  Widget _section(
    String title, {
    required bool loading,
    required bool failed,
    required String text,
    required String command,
    required Future<void> Function() onRetry,
  }) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Row(
        children: [
          Text(
            title,
            style: const TextStyle(fontSize: 13.5, fontWeight: FontWeight.w800),
          ),
          const SizedBox(width: 10),
          if (!loading)
            TextButton.icon(
              onPressed: () => unawaited(onRetry()),
              icon: const Icon(Icons.refresh, size: 15),
              label: const Text('다시'),
              style: TextButton.styleFrom(
                padding: const EdgeInsets.symmetric(horizontal: 8),
                minimumSize: const Size(0, 30),
                tapTargetSize: MaterialTapTargetSize.shrinkWrap,
              ),
            ),
        ],
      ),
      const SizedBox(height: 8),
      if (loading)
        const Padding(
          padding: EdgeInsets.symmetric(vertical: 14),
          child: Center(child: CircularProgressIndicator()),
        )
      else
        _resultBox(
          text: text,
          command: command,
          tone: failed ? _Tone.bad : _Tone.plain,
        ),
    ],
  );

  Widget _resultBox({
    required String text,
    required String command,
    required _Tone tone,
  }) {
    final (background, border, ink) = switch (tone) {
      _Tone.good => (
        const Color(0xFFF0FDF4),
        const Color(0xFF86EFAC),
        const Color(0xFF14532D),
      ),
      _Tone.warn => (
        const Color(0xFFFFFBEB),
        const Color(0xFFFCD34D),
        const Color(0xFF78350F),
      ),
      _Tone.bad => (
        const Color(0xFFFEF2F2),
        const Color(0xFFFCA5A5),
        const Color(0xFF991B1B),
      ),
      _Tone.plain => (
        const Color(0xFFF8FAFC),
        const Color(0xFFE2E8F0),
        const Color(0xFF1E293B),
      ),
    };
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Container(
          width: double.infinity,
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: background,
            borderRadius: BorderRadius.circular(9),
            border: Border.all(color: border),
          ),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxHeight: 260),
            child: SingleChildScrollView(
              child: SelectableText(
                text.isEmpty ? '내용이 없습니다.' : text,
                style: TextStyle(
                  fontSize: 12,
                  height: 1.5,
                  fontFamily: 'monospace',
                  color: ink,
                ),
              ),
            ),
          ),
        ),
        if (command.isNotEmpty) ...[
          const SizedBox(height: 6),
          _CommandChip(command: command),
        ],
      ],
    );
  }
}

enum _Tone { good, warn, bad, plain }
