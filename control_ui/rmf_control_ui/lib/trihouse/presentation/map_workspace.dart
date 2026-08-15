import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';

import 'shared.dart';

class MapWaypointPresentation {
  const MapWaypointPresentation({
    required this.code,
    required this.position,
    required this.yaw,
  });

  final String code;
  final Offset position;
  final double yaw;

  MapWaypointPresentation movedTo(Offset value) =>
      MapWaypointPresentation(code: code, position: value, yaw: yaw);
}

class MapWorkspace extends StatefulWidget {
  const MapWorkspace({
    super.key,
    required this.waypoints,
    required this.onWaypointMoved,
    this.transformationController,
  });

  final List<MapWaypointPresentation> waypoints;
  final ValueChanged<MapWaypointPresentation> onWaypointMoved;
  final TransformationController? transformationController;

  @override
  State<MapWorkspace> createState() => _MapWorkspaceState();
}

class _MapWorkspaceState extends State<MapWorkspace> {
  late final TransformationController _ownedController;
  late List<MapWaypointPresentation> _waypoints;

  TransformationController get _controller =>
      widget.transformationController ?? _ownedController;

  @override
  void initState() {
    super.initState();
    _ownedController = TransformationController();
    _waypoints = List.of(widget.waypoints);
  }

  @override
  void didUpdateWidget(covariant MapWorkspace oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.waypoints != widget.waypoints) {
      _waypoints = List.of(widget.waypoints);
    }
  }

  @override
  void dispose() {
    _ownedController.dispose();
    super.dispose();
  }

  void _zoom(double factor) {
    final current = _controller.value.getMaxScaleOnAxis();
    final next = (current * factor).clamp(.5, 4.0);
    _controller.value = Matrix4.diagonal3Values(next, next, 1);
  }

  void _move(int index, Offset delta, {required bool ended}) {
    final updated = _waypoints[index].movedTo(
      _waypoints[index].position + delta,
    );
    setState(() => _waypoints[index] = updated);
    if (ended) widget.onWaypointMoved(updated);
  }

  @override
  Widget build(BuildContext context) => Container(
    clipBehavior: Clip.antiAlias,
    decoration: BoxDecoration(
      color: Colors.white,
      borderRadius: BorderRadius.circular(14),
      border: Border.all(color: const Color(0xFFE2E8F0)),
    ),
    child: Column(
      children: [
        Container(
          height: 58,
          padding: const EdgeInsets.symmetric(horizontal: 18),
          decoration: const BoxDecoration(
            border: Border(bottom: BorderSide(color: Color(0xFFE5EAF0))),
          ),
          child: Row(
            children: [
              const Text(
                '도면 작업 영역',
                style: TextStyle(fontWeight: FontWeight.w800),
              ),
              const SizedBox(width: 16),
              const Chip(
                avatar: Icon(Icons.location_on_outlined, size: 16),
                label: Text('Waypoint 편집'),
              ),
              const Spacer(),
              IconButton(
                onPressed: () => _zoom(.8),
                icon: const Icon(Icons.zoom_out),
                tooltip: '축소',
              ),
              IconButton(
                onPressed: () => _zoom(1.25),
                icon: const Icon(Icons.zoom_in),
                tooltip: '확대',
              ),
              IconButton(
                onPressed: () => _controller.value = Matrix4.identity(),
                icon: const Icon(Icons.fit_screen),
                tooltip: '화면 맞춤',
              ),
            ],
          ),
        ),
        Expanded(
          child: ClipRect(
            child: InteractiveViewer(
              transformationController: _controller,
              minScale: .5,
              maxScale: 4,
              child: LayoutBuilder(
                builder: (context, constraints) => SizedBox(
                  width: constraints.maxWidth,
                  height: constraints.maxHeight,
                  child: Stack(
                    children: [
                      Positioned.fill(
                        child: CustomPaint(
                          painter: _MapCanvasPainter(waypoints: _waypoints),
                        ),
                      ),
                      for (var index = 0; index < _waypoints.length; index++)
                        Positioned(
                          left: _waypoints[index].position.dx - 18,
                          top: _waypoints[index].position.dy - 18,
                          width: 36,
                          height: 36,
                          child: GestureDetector(
                            key: Key('waypoint-${_waypoints[index].code}'),
                            behavior: HitTestBehavior.opaque,
                            dragStartBehavior: DragStartBehavior.down,
                            onPanUpdate: (details) =>
                                _move(index, details.delta, ended: false),
                            onPanEnd: (_) =>
                                _move(index, Offset.zero, ended: true),
                            child: Tooltip(
                              message: _waypoints[index].code,
                              child: const Icon(
                                Icons.location_on,
                                color: controlBlue,
                                size: 32,
                              ),
                            ),
                          ),
                        ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ),
      ],
    ),
  );
}

class _MapCanvasPainter extends CustomPainter {
  const _MapCanvasPainter({required this.waypoints});

  final List<MapWaypointPresentation> waypoints;

  @override
  void paint(Canvas canvas, Size size) {
    canvas.drawRect(
      Offset.zero & size,
      Paint()..color = const Color(0xFFF8FAFC),
    );
    final grid = Paint()
      ..color = const Color(0xFFE2E8F0)
      ..strokeWidth = 1;
    for (var x = 0.0; x < size.width; x += 32) {
      canvas.drawLine(Offset(x, 0), Offset(x, size.height), grid);
    }
    for (var y = 0.0; y < size.height; y += 32) {
      canvas.drawLine(Offset(0, y), Offset(size.width, y), grid);
    }
  }

  @override
  bool shouldRepaint(covariant _MapCanvasPainter oldDelegate) =>
      oldDelegate.waypoints != waypoints;
}
