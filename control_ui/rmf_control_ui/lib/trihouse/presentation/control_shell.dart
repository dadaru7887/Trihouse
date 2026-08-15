import 'package:flutter/material.dart';

import '../api/fms_api.dart';
import 'control_navigation.dart';
import 'main_dashboard.dart';
import 'map_project_page.dart';
import 'operations_analytics_page.dart';
import 'robot_operations_page.dart';
import 'task_management_page.dart';

class ControlAppShell extends StatefulWidget {
  const ControlAppShell({super.key, required this.api});

  final FmsApi api;

  @override
  State<ControlAppShell> createState() => _ControlAppShellState();
}

class _ControlAppShellState extends State<ControlAppShell> {
  ControlDestination _selected = ControlDestination.dashboard;

  Widget _page() => switch (_selected) {
    ControlDestination.dashboard => MainDashboard(api: widget.api),
    ControlDestination.maps => MapProjectPage(api: widget.api),
    ControlDestination.robots => RobotOperationsPage(api: widget.api),
    ControlDestination.tasks => TaskManagementPage(api: widget.api),
    ControlDestination.operations => OperationsAnalyticsPage(api: widget.api),
  };

  @override
  Widget build(BuildContext context) => Scaffold(
    body: Row(
      children: [
        ControlNavigationRail(
          selected: _selected,
          onSelected: (value) => setState(() => _selected = value),
        ),
        Expanded(
          child: Column(
            children: [
              ControlTopBar(destination: _selected),
              Expanded(child: _page()),
            ],
          ),
        ),
      ],
    ),
  );
}
