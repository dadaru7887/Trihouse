import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'controller.dart';
import 'backend_bootstrap.dart';
import 'map_view.dart';
import 'models.dart';
import 'operations_view.dart';

const _bg = Color(0xff101417);
const _surface = Color(0xff181d21);
const _surfaceHigh = Color(0xff20262b);
const _border = Color(0xff30383e);
const _text = Color(0xffedf2f3);
const _muted = Color(0xff94a1a8);
const _cyan = Color(0xff3bc8c2);
const _amber = Color(0xffffb454);
const _red = Color(0xffff6b6b);

class OpenRmfApp extends StatefulWidget {
  const OpenRmfApp({
    super.key,
    required this.apiUrl,
    required this.apiToken,
    required this.trajectoryUrl,
    this.backend,
  });
  final String apiUrl;
  final String apiToken;
  final String trajectoryUrl;
  final BackendSupervisor? backend;

  @override
  State<OpenRmfApp> createState() => _OpenRmfAppState();
}

class _OpenRmfAppState extends State<OpenRmfApp> {
  late final RmfController controller = RmfController(
    apiUrl: widget.apiUrl,
    apiToken: widget.apiToken,
    trajectoryUrl: widget.trajectoryUrl,
    backend: widget.backend,
  );

  @override
  void initState() {
    super.initState();
    controller.start();
  }

  @override
  void dispose() {
    controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Open-RMF Office Control',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        brightness: Brightness.dark,
        scaffoldBackgroundColor: _bg,
        colorScheme: const ColorScheme.dark(
          primary: _cyan,
          secondary: _amber,
          surface: _surface,
          error: _red,
        ),
        fontFamily: 'sans-serif',
        dividerColor: _border,
        textTheme: const TextTheme(
          bodyMedium: TextStyle(color: _text, fontSize: 13),
          bodySmall: TextStyle(color: _muted, fontSize: 11),
        ),
      ),
      home: ListenableBuilder(
        listenable: controller,
        builder: (context, _) => _Console(controller: controller),
      ),
    );
  }
}

class _Console extends StatelessWidget {
  const _Console({required this.controller});
  final RmfController controller;

  @override
  Widget build(BuildContext context) {
    return DefaultTabController(
      length: 5,
      child: Scaffold(
        body: SafeArea(
          child: Column(
            children: [
              _TopBar(controller: controller),
              Container(
                color: _surface,
                child: const TabBar(
                  isScrollable: true,
                  tabAlignment: TabAlignment.start,
                  tabs: [
                    Tab(icon: Icon(Icons.map_outlined), text: '지도'),
                    Tab(icon: Icon(Icons.route_outlined), text: '태스크'),
                    Tab(icon: Icon(Icons.smart_toy_outlined), text: '로봇'),
                    Tab(icon: Icon(Icons.apartment_outlined), text: '설비'),
                    Tab(icon: Icon(Icons.notifications_outlined), text: '알림'),
                  ],
                ),
              ),
              Expanded(
                child: TabBarView(
                  children: [
                    _Overview(controller: controller),
                    TasksView(controller: controller),
                    RobotsView(controller: controller),
                    InfrastructureView(controller: controller),
                    AlertsView(controller: controller),
                  ],
                ),
              ),
              if (controller.notice != null)
                MaterialBanner(
                  content: Text(controller.notice!),
                  actions: [
                    TextButton(
                      onPressed: controller.clearNotice,
                      child: const Text('닫기'),
                    ),
                  ],
                ),
              AppLogPanel(controller: controller),
            ],
          ),
        ),
      ),
    );
  }
}

class _Overview extends StatelessWidget {
  const _Overview({required this.controller});
  final RmfController controller;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        if (constraints.maxWidth < 900) {
          return Column(
            children: [
              Expanded(flex: 3, child: _MapPanel(controller: controller)),
              SizedBox(
                height: 280,
                child: _OperationsPanel(controller: controller),
              ),
            ],
          );
        }
        return Row(
          children: [
            SizedBox(width: 250, child: _RobotPanel(controller: controller)),
            Expanded(child: _MapPanel(controller: controller)),
            SizedBox(
              width: 340,
              child: _OperationsPanel(controller: controller),
            ),
          ],
        );
      },
    );
  }
}

class _TopBar extends StatelessWidget {
  const _TopBar({required this.controller});
  final RmfController controller;

  @override
  Widget build(BuildContext context) {
    final working = controller.robots.where((r) => r.isWorking).length;
    return Container(
      height: 64,
      padding: const EdgeInsets.symmetric(horizontal: 18),
      decoration: const BoxDecoration(
        color: _surface,
        border: Border(bottom: BorderSide(color: _border)),
      ),
      child: Row(
        children: [
          Container(
            width: 34,
            height: 34,
            decoration: BoxDecoration(
              color: _cyan.withValues(alpha: 0.12),
              border: Border.all(color: _cyan.withValues(alpha: 0.45)),
              borderRadius: BorderRadius.circular(6),
            ),
            child: const Icon(Icons.hub_outlined, color: _cyan, size: 19),
          ),
          const SizedBox(width: 11),
          const Column(
            mainAxisAlignment: MainAxisAlignment.center,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'OPEN-RMF OFFICE',
                style: TextStyle(
                  color: _text,
                  fontWeight: FontWeight.w700,
                  fontSize: 14,
                  letterSpacing: 0,
                ),
              ),
              Text(
                'Fleet operations console',
                style: TextStyle(color: _muted, fontSize: 10),
              ),
            ],
          ),
          const Spacer(),
          if (MediaQuery.sizeOf(context).width >= 720) ...[
            _Metric(label: 'ROBOTS', value: '${controller.robots.length}'),
            _Metric(label: 'WORKING', value: '$working', color: _cyan),
            _Metric(
              label: 'TASKS',
              value:
                  '${controller.tasks.where((t) => t.status == 'underway').length}',
              color: _amber,
            ),
            const SizedBox(width: 18),
          ],
          Tooltip(
            message: controller.error ?? controller.apiUrl,
            child: Row(
              children: [
                Container(
                  width: 8,
                  height: 8,
                  decoration: BoxDecoration(
                    color: controller.connected ? _cyan : _red,
                    shape: BoxShape.circle,
                  ),
                ),
                const SizedBox(width: 7),
                Text(
                  controller.connected ? 'API ONLINE' : 'API OFFLINE',
                  style: TextStyle(
                    color: controller.connected ? _cyan : _red,
                    fontSize: 10,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(width: 8),
          IconButton(
            onPressed: controller.refresh,
            tooltip: '새로고침',
            icon: const Icon(Icons.refresh, size: 18),
          ),
        ],
      ),
    );
  }
}

class _Metric extends StatelessWidget {
  const _Metric({required this.label, required this.value, this.color = _text});
  final String label;
  final String value;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 72,
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label, style: const TextStyle(color: _muted, fontSize: 9)),
          Text(
            value,
            style: TextStyle(
              color: color,
              fontSize: 17,
              fontWeight: FontWeight.w700,
            ),
          ),
        ],
      ),
    );
  }
}

class _RobotPanel extends StatelessWidget {
  const _RobotPanel({required this.controller});
  final RmfController controller;

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: const BoxDecoration(
        color: _surface,
        border: Border(right: BorderSide(color: _border)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const _PanelTitle(icon: Icons.smart_toy_outlined, title: 'ROBOTS'),
          Expanded(
            child: controller.robots.isEmpty
                ? const _EmptyState(icon: Icons.sensors_off, text: '로봇 상태 대기 중')
                : ListView.separated(
                    padding: const EdgeInsets.fromLTRB(10, 0, 10, 12),
                    itemCount: controller.robots.length,
                    separatorBuilder: (_, _) => const SizedBox(height: 6),
                    itemBuilder: (context, index) {
                      final robot = controller.robots[index];
                      final selected = controller.selectedRobot == robot.name;
                      return _RobotTile(
                        robot: robot,
                        selected: selected,
                        onTap: () => controller.selectRobot(
                          selected ? null : robot.name,
                        ),
                      );
                    },
                  ),
          ),
        ],
      ),
    );
  }
}

class _RobotTile extends StatelessWidget {
  const _RobotTile({
    required this.robot,
    required this.selected,
    required this.onTap,
  });
  final RmfRobot robot;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final color = _statusColor(robot.status);
    return Material(
      color: selected ? _cyan.withValues(alpha: 0.09) : _surfaceHigh,
      borderRadius: BorderRadius.circular(6),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(6),
        child: Container(
          padding: const EdgeInsets.all(11),
          decoration: BoxDecoration(
            border: Border.all(color: selected ? _cyan : _border),
            borderRadius: BorderRadius.circular(6),
          ),
          child: Column(
            children: [
              Row(
                children: [
                  Container(
                    width: 7,
                    height: 7,
                    decoration: BoxDecoration(
                      color: color,
                      shape: BoxShape.circle,
                    ),
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      robot.name,
                      style: const TextStyle(
                        fontSize: 12,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ),
                  Text(
                    robot.fleet,
                    style: const TextStyle(color: _muted, fontSize: 9),
                  ),
                ],
              ),
              const SizedBox(height: 9),
              Row(
                children: [
                  Text(
                    _statusLabel(robot.status),
                    style: TextStyle(
                      color: color,
                      fontSize: 10,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  const Spacer(),
                  Text(
                    '${(robot.battery * 100).round()}%',
                    style: const TextStyle(color: _text, fontSize: 10),
                  ),
                ],
              ),
              const SizedBox(height: 5),
              ClipRRect(
                borderRadius: BorderRadius.circular(2),
                child: LinearProgressIndicator(
                  minHeight: 3,
                  value: robot.battery,
                  color: robot.battery < 0.25 ? _red : _cyan,
                  backgroundColor: _border,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _MapPanel extends StatelessWidget {
  const _MapPanel({required this.controller});
  final RmfController controller;

  @override
  Widget build(BuildContext context) {
    final levels = controller.building?.levels ?? const <RmfLevel>[];
    return ColoredBox(
      color: _bg,
      child: Column(
        children: [
          SizedBox(
            height: 52,
            child: Row(
              children: [
                const SizedBox(width: 16),
                const Icon(Icons.map_outlined, size: 17, color: _cyan),
                const SizedBox(width: 8),
                Text(
                  controller.building?.name.toUpperCase() ?? 'OFFICE MAP',
                  style: const TextStyle(
                    fontSize: 11,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                const SizedBox(width: 10),
                Text(
                  '${controller.visibleRobots.length} ROBOTS',
                  style: TextStyle(
                    color: controller.visibleRobots.isEmpty ? _red : _cyan,
                    fontSize: 10,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                const Spacer(),
                if (levels.length > 1)
                  SegmentedButton<int>(
                    segments: [
                      for (var i = 0; i < levels.length; i++)
                        ButtonSegment(value: i, label: Text(levels[i].name)),
                    ],
                    selected: {controller.selectedLevel},
                    onSelectionChanged: (value) =>
                        controller.selectLevel(value.first),
                    showSelectedIcon: false,
                    style: const ButtonStyle(
                      visualDensity: VisualDensity.compact,
                      textStyle: WidgetStatePropertyAll(
                        TextStyle(fontSize: 10),
                      ),
                    ),
                  ),
                const SizedBox(width: 14),
              ],
            ),
          ),
          Expanded(
            child: Padding(
              padding: const EdgeInsets.fromLTRB(14, 0, 14, 14),
              child: ClipRRect(
                borderRadius: BorderRadius.circular(6),
                child: DecoratedBox(
                  decoration: BoxDecoration(
                    color: const Color(0xff0c1012),
                    border: Border.all(color: _border),
                  ),
                  child: controller.level == null
                      ? _EmptyState(
                          icon: controller.error == null
                              ? Icons.map_outlined
                              : Icons.link_off,
                          text: controller.error ?? 'building map 대기 중',
                          copyable: controller.error != null,
                        )
                      : RmfMapView(controller: controller),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _OperationsPanel extends StatelessWidget {
  const _OperationsPanel({required this.controller});
  final RmfController controller;

  @override
  Widget build(BuildContext context) {
    final selected = controller.selectedRobot == null
        ? null
        : controller.robots.cast<RmfRobot?>().firstWhere(
            (r) => r?.name == controller.selectedRobot,
            orElse: () => null,
          );
    return Container(
      decoration: const BoxDecoration(
        color: _surface,
        border: Border(left: BorderSide(color: _border)),
      ),
      child: Column(
        children: [
          if (selected != null) _RobotDetail(robot: selected),
          const _PanelTitle(icon: Icons.route_outlined, title: 'TASK ACTIVITY'),
          Expanded(
            child: controller.tasks.isEmpty
                ? const _EmptyState(
                    icon: Icons.route_outlined,
                    text: '태스크가 없습니다',
                  )
                : ListView.separated(
                    padding: const EdgeInsets.fromLTRB(12, 0, 12, 12),
                    itemCount: controller.tasks.length.clamp(0, 40),
                    separatorBuilder: (_, _) => const Divider(height: 1),
                    itemBuilder: (context, index) =>
                        _TaskRow(task: controller.tasks[index]),
                  ),
          ),
          Container(
            padding: const EdgeInsets.all(12),
            decoration: const BoxDecoration(
              border: Border(top: BorderSide(color: _border)),
            ),
            child: Row(
              children: [
                const Icon(Icons.api_outlined, size: 15, color: _muted),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    controller.apiUrl,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(color: _muted, fontSize: 10),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _RobotDetail extends StatelessWidget {
  const _RobotDetail({required this.robot});
  final RmfRobot robot;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: const BoxDecoration(
        color: _surfaceHigh,
        border: Border(bottom: BorderSide(color: _border)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.my_location, color: _cyan, size: 16),
              const SizedBox(width: 8),
              Text(
                robot.name,
                style: const TextStyle(fontWeight: FontWeight.w700),
              ),
              const Spacer(),
              Text(
                _statusLabel(robot.status),
                style: TextStyle(color: _statusColor(robot.status)),
              ),
            ],
          ),
          const SizedBox(height: 10),
          Text(
            '${robot.level}  ·  x ${robot.x.toStringAsFixed(2)}  y ${robot.y.toStringAsFixed(2)}',
            style: const TextStyle(color: _muted, fontSize: 10),
          ),
          if (robot.taskId != null) ...[
            const SizedBox(height: 5),
            Text(
              'TASK ${robot.taskId}',
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(color: _amber, fontSize: 10),
            ),
          ],
        ],
      ),
    );
  }
}

class _TaskRow extends StatelessWidget {
  const _TaskRow({required this.task});
  final RmfTask task;

  @override
  Widget build(BuildContext context) {
    final color = _taskColor(task.status);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 11),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 3,
            height: 34,
            decoration: BoxDecoration(
              color: color,
              borderRadius: BorderRadius.circular(2),
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: Text(
                        task.category.toUpperCase(),
                        style: const TextStyle(
                          fontSize: 11,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ),
                    Text(
                      task.status.toUpperCase(),
                      style: TextStyle(
                        color: color,
                        fontSize: 9,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 4),
                Text(
                  task.robot == null
                      ? task.id
                      : '${task.fleet}/${task.robot}  ·  ${task.id}',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(color: _muted, fontSize: 9),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _PanelTitle extends StatelessWidget {
  const _PanelTitle({required this.icon, required this.title});
  final IconData icon;
  final String title;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 52,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 14),
        child: Row(
          children: [
            Icon(icon, color: _cyan, size: 16),
            const SizedBox(width: 8),
            Text(
              title,
              style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w700),
            ),
          ],
        ),
      ),
    );
  }
}

class _EmptyState extends StatelessWidget {
  const _EmptyState({
    required this.icon,
    required this.text,
    this.copyable = false,
  });
  final IconData icon;
  final String text;
  final bool copyable;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, color: _muted, size: 24),
            const SizedBox(height: 9),
            SelectableText(
              text,
              textAlign: TextAlign.center,
              style: const TextStyle(color: _muted),
            ),
            if (copyable) ...[
              const SizedBox(height: 10),
              IconButton(
                onPressed: () async {
                  await Clipboard.setData(ClipboardData(text: text));
                  if (!context.mounted) return;
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(
                      content: Text('오류 메시지를 복사했습니다.'),
                      duration: Duration(seconds: 2),
                    ),
                  );
                },
                tooltip: '오류 메시지 복사',
                icon: const Icon(Icons.copy_outlined, size: 17),
                color: _muted,
              ),
            ],
          ],
        ),
      ),
    );
  }
}

Color _statusColor(String status) => switch (status) {
  'idle' || 'charging' => _cyan,
  'working' => _amber,
  'error' || 'offline' || 'shutdown' => _red,
  _ => _muted,
};

Color _taskColor(String status) => switch (status) {
  'completed' => _cyan,
  'underway' || 'queued' || 'standby' => _amber,
  'error' || 'failed' || 'canceled' || 'killed' => _red,
  _ => _muted,
};

String _statusLabel(String status) => switch (status) {
  'idle' => '대기',
  'charging' => '충전',
  'working' => '작업 중',
  'error' => '오류',
  'offline' => '오프라인',
  'shutdown' => '종료',
  _ => status,
};
