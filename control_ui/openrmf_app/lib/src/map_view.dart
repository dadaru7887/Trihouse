import 'dart:math' as math;

import 'package:flutter/material.dart';

import 'controller.dart';
import 'models.dart';

const _cyan = Color(0xff3bc8c2);
const _amber = Color(0xffffb454);

class RmfMapView extends StatelessWidget {
  const RmfMapView({super.key, required this.controller});
  final RmfController controller;

  @override
  Widget build(BuildContext context) {
    final level = controller.level!;
    final bytes = controller.mapBytes;
    final decoded = controller.decodedMap;
    return InteractiveViewer(
      minScale: 0.7,
      maxScale: 5,
      boundaryMargin: const EdgeInsets.all(100),
      child: LayoutBuilder(
        builder: (context, constraints) {
          final size = Size(constraints.maxWidth, constraints.maxHeight);
          if (bytes == null || decoded == null || level.image == null) {
            return SizedBox.fromSize(
              size: size,
              child: CustomPaint(
                painter: _GraphOnlyPainter(
                  level: level,
                  robots: controller.visibleRobots.toList(),
                  trajectories: controller.trajectories,
                  selectedRobot: controller.selectedRobot,
                ),
              ),
            );
          }
          final imageSize = Size(
            decoded.width.toDouble(),
            decoded.height.toDouble(),
          );
          final fitted = applyBoxFit(BoxFit.contain, imageSize, size);
          final destination = Alignment.center.inscribe(
            fitted.destination,
            Offset.zero & size,
          );
          return SizedBox.fromSize(
            size: size,
            child: Stack(
              fit: StackFit.expand,
              children: [
                Positioned.fromRect(
                  rect: destination,
                  child: Image.memory(
                    bytes,
                    fit: BoxFit.fill,
                    gaplessPlayback: true,
                  ),
                ),
                CustomPaint(
                  painter: _MapOverlayPainter(
                    level: level,
                    robots: controller.visibleRobots.toList(),
                    trajectories: controller.trajectories,
                    selectedRobot: controller.selectedRobot,
                    imagePixels: imageSize,
                    destination: destination,
                  ),
                ),
              ],
            ),
          );
        },
      ),
    );
  }
}

class _MapOverlayPainter extends CustomPainter {
  const _MapOverlayPainter({
    required this.level,
    required this.robots,
    required this.trajectories,
    required this.selectedRobot,
    required this.imagePixels,
    required this.destination,
  });

  final RmfLevel level;
  final List<RmfRobot> robots;
  final List<RmfTrajectory> trajectories;
  final String? selectedRobot;
  final Size imagePixels;
  final Rect destination;

  Offset _point(double x, double y) {
    final image = level.image!;
    final px = (x - image.xOffset) / image.scale;
    final py = (image.yOffset - y) / image.scale;
    return Offset(
      destination.left + px / imagePixels.width * destination.width,
      destination.top + py / imagePixels.height * destination.height,
    );
  }

  @override
  void paint(Canvas canvas, Size size) {
    final lane = Paint()
      ..color = _cyan.withValues(alpha: 0.28)
      ..strokeWidth = 1.2
      ..style = PaintingStyle.stroke;
    for (final edge in level.edges) {
      if (edge.from >= level.vertices.length ||
          edge.to >= level.vertices.length) {
        continue;
      }
      final from = level.vertices[edge.from];
      final to = level.vertices[edge.to];
      canvas.drawLine(_point(from.x, from.y), _point(to.x, to.y), lane);
    }
    for (final trajectory in trajectories.where(
      (trajectory) => trajectory.level == level.name,
    )) {
      if (trajectory.points.length < 2) continue;
      final path = Path();
      final first = trajectory.points.first;
      path.moveTo(_point(first.$1, first.$2).dx, _point(first.$1, first.$2).dy);
      for (final point in trajectory.points.skip(1)) {
        final mapped = _point(point.$1, point.$2);
        path.lineTo(mapped.dx, mapped.dy);
      }
      canvas.drawPath(
        path,
        Paint()
          ..color = trajectory.conflict ? Colors.redAccent : _amber
          ..strokeWidth = trajectory.conflict ? 3 : 2
          ..style = PaintingStyle.stroke,
      );
    }
    for (final robot in robots) {
      final center = _point(robot.x, robot.y);
      final selected = robot.name == selectedRobot;
      if (selected) {
        canvas.drawCircle(
          center,
          19,
          Paint()..color = _cyan.withValues(alpha: 0.22),
        );
      }
      canvas.save();
      canvas.translate(center.dx, center.dy);
      canvas.rotate(-robot.yaw);
      final marker = Path()
        ..moveTo(13, 0)
        ..lineTo(-8, -8)
        ..lineTo(-3, 0)
        ..lineTo(-8, 8)
        ..close();
      canvas.drawPath(
        marker,
        Paint()..color = robot.isWorking ? _amber : _cyan,
      );
      canvas.drawPath(
        marker,
        Paint()
          ..color = Colors.black.withValues(alpha: 0.7)
          ..style = PaintingStyle.stroke
          ..strokeWidth = 1,
      );
      canvas.restore();
      final label = TextPainter(
        text: TextSpan(
          text: robot.name,
          style: const TextStyle(
            color: Colors.white,
            fontSize: 9,
            fontWeight: FontWeight.w700,
            backgroundColor: Color(0xcc111619),
          ),
        ),
        textDirection: TextDirection.ltr,
      )..layout();
      label.paint(canvas, center + const Offset(11, -6));
    }
  }

  @override
  bool shouldRepaint(covariant _MapOverlayPainter oldDelegate) =>
      oldDelegate.robots != robots ||
      oldDelegate.selectedRobot != selectedRobot ||
      oldDelegate.destination != destination;
}

class _GraphOnlyPainter extends CustomPainter {
  const _GraphOnlyPainter({
    required this.level,
    required this.robots,
    required this.trajectories,
    required this.selectedRobot,
  });

  final RmfLevel level;
  final List<RmfRobot> robots;
  final List<RmfTrajectory> trajectories;
  final String? selectedRobot;

  @override
  void paint(Canvas canvas, Size size) {
    final points = [
      ...level.vertices.map((v) => Offset(v.x, v.y)),
      ...robots.map((r) => Offset(r.x, r.y)),
    ];
    if (points.isEmpty) return;
    final minX = points.map((p) => p.dx).reduce(math.min);
    final maxX = points.map((p) => p.dx).reduce(math.max);
    final minY = points.map((p) => p.dy).reduce(math.min);
    final maxY = points.map((p) => p.dy).reduce(math.max);
    const pad = 32.0;
    Offset point(double x, double y) => Offset(
      pad + (x - minX) / math.max(0.01, maxX - minX) * (size.width - pad * 2),
      size.height -
          pad -
          (y - minY) / math.max(0.01, maxY - minY) * (size.height - pad * 2),
    );
    final lane = Paint()
      ..color = _cyan.withValues(alpha: 0.45)
      ..strokeWidth = 1.2;
    for (final edge in level.edges) {
      if (edge.from >= level.vertices.length ||
          edge.to >= level.vertices.length) {
        continue;
      }
      final a = level.vertices[edge.from];
      final b = level.vertices[edge.to];
      canvas.drawLine(point(a.x, a.y), point(b.x, b.y), lane);
    }
    for (final trajectory in trajectories.where(
      (trajectory) => trajectory.level == level.name,
    )) {
      if (trajectory.points.length < 2) continue;
      final path = Path();
      final first = trajectory.points.first;
      path.moveTo(point(first.$1, first.$2).dx, point(first.$1, first.$2).dy);
      for (final knot in trajectory.points.skip(1)) {
        final mapped = point(knot.$1, knot.$2);
        path.lineTo(mapped.dx, mapped.dy);
      }
      canvas.drawPath(
        path,
        Paint()
          ..color = trajectory.conflict ? Colors.redAccent : _amber
          ..strokeWidth = 2
          ..style = PaintingStyle.stroke,
      );
    }
    for (final robot in robots) {
      canvas.drawCircle(
        point(robot.x, robot.y),
        robot.name == selectedRobot ? 9 : 6,
        Paint()..color = robot.isWorking ? _amber : _cyan,
      );
    }
  }

  @override
  bool shouldRepaint(covariant _GraphOnlyPainter oldDelegate) => true;
}
