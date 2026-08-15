import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../../core/fleet_engine.dart';
import '../../core/layout.dart';
import 'package:robo_core/models/enums.dart';
import 'package:robo_core/models/robot.dart';
import 'package:robo_core/models/warehouse.dart';
import '../theme.dart';

/// 물류센터 실시간 평면도.
///
/// 3온도 구획, 랙, 통로, 도크·충전소, 로봇 위치·경로, 작업자 안전 필드,
/// 안전 상황 반경을 한 화면에 표시한다.
class WarehouseMap extends StatefulWidget {
  const WarehouseMap({
    super.key,
    required this.engine,
    this.showTrace = true,
    this.compact = false,
  });

  final FleetEngine engine;
  final bool showTrace;
  final bool compact;

  @override
  State<WarehouseMap> createState() => _WarehouseMapState();
}

class _WarehouseMapState extends State<WarehouseMap> {
  Offset? _hoverWorld;

  @override
  Widget build(BuildContext context) {
    final engine = widget.engine;
    return LayoutBuilder(
      builder: (context, c) {
        final scale = math.min(
          c.maxWidth / WarehouseLayout.width,
          c.maxHeight / WarehouseLayout.height,
        );
        final origin = Offset(
          (c.maxWidth - WarehouseLayout.width * scale) / 2,
          (c.maxHeight - WarehouseLayout.height * scale) / 2,
        );

        Offset toWorld(Offset local) =>
            Offset((local.dx - origin.dx) / scale, (local.dy - origin.dy) / scale);

        return MouseRegion(
          onHover: (e) => setState(() => _hoverWorld = toWorld(e.localPosition)),
          onExit: (_) => setState(() => _hoverWorld = null),
          child: GestureDetector(
            onTapDown: (d) {
              final w = toWorld(d.localPosition);
              Robot? hit;
              var best = 4.0;
              for (final r in engine.robots) {
                final dist = (r.pos - w).distance;
                if (dist < best) {
                  best = dist;
                  hit = r;
                }
              }
              engine.selectRobot(hit?.id);
            },
            child: CustomPaint(
              size: Size(c.maxWidth, c.maxHeight),
              painter: _MapPainter(
                baseStyle: DefaultTextStyle.of(context).style,
                engine: engine,
                scale: scale,
                origin: origin,
                hoverWorld: _hoverWorld,
                showTrace: widget.showTrace,
                compact: widget.compact,
              ),
            ),
          ),
        );
      },
    );
  }
}

class _MapPainter extends CustomPainter {
  _MapPainter({
    required this.baseStyle,
    required this.engine,
    required this.scale,
    required this.origin,
    required this.hoverWorld,
    required this.showTrace,
    required this.compact,
  });

  final FleetEngine engine;
  final double scale;
  final Offset origin;
  final Offset? hoverWorld;

  /// 지도 라벨의 기준 스타일. 테마의 타이포그래피를 그대로 상속한다.
  final TextStyle baseStyle;
  final bool showTrace;
  final bool compact;

  Offset _p(Offset world) =>
      Offset(origin.dx + world.dx * scale, origin.dy + world.dy * scale);

  double _s(double v) => v * scale;

  @override
  void paint(Canvas canvas, Size size) {
    _paintZones(canvas);
    _paintCorridors(canvas);
    _paintRacks(canvas);
    _paintStations(canvas);
    _paintIncidents(canvas);
    _paintPaths(canvas);
    _paintWorkers(canvas);
    _paintRobots(canvas);
  }

  void _paintZones(Canvas canvas) {
    const bounds = <List<double>>[
      <double>[0, 50],
      <double>[50, 88],
      <double>[88, 120],
    ];
    for (var i = 0; i < TempZone.values.length; i++) {
      final zone = TempZone.values[i];
      final env = engine.environment[zone]!;
      final rect = Rect.fromLTRB(
        _p(Offset(bounds[i][0], 0)).dx,
        _p(const Offset(0, 0)).dy,
        _p(Offset(bounds[i][1], 0)).dx,
        _p(const Offset(0, WarehouseLayout.height)).dy,
      );
      canvas.drawRect(
        rect,
        Paint()..color = AppColors.zoneFill(zone).withValues(alpha: 0.07),
      );
      canvas.drawRect(
        rect,
        Paint()
          ..style = PaintingStyle.stroke
          ..strokeWidth = 1
          ..color = AppColors.zoneFill(zone).withValues(alpha: 0.35),
      );

      if (!env.powerOn) {
        canvas.drawRect(
          rect,
          Paint()..color = AppColors.baseline.withValues(alpha: 0.55),
        );
      }

      _label(
        canvas,
        '${zone.label}  ${env.temperatureC.toStringAsFixed(1)}℃',
        Offset(rect.left + 8, rect.top + 6),
        color: AppColors.zoneColor(zone),
        size: compact ? 9 : 11,
        bold: true,
      );
      if (!compact) {
        _label(
          canvas,
          '조도 ${env.lux.toStringAsFixed(0)}lx · 마찰 ${env.friction.toStringAsFixed(2)} · '
              '경사 ${env.slopeDeg.toStringAsFixed(1)}° · 성능 ${(env.performanceIndex * 100).toStringAsFixed(0)}%',
          Offset(rect.left + 8, rect.top + 20),
          color: AppColors.muted,
          size: 9,
        );
      }
    }
  }

  void _paintCorridors(Canvas canvas) {
    final paint = Paint()
      ..color = AppColors.surface
      ..strokeWidth = math.max(1, _s(1.8))
      ..strokeCap = StrokeCap.round;
    for (final y in WarehouseLayout.corridorY) {
      canvas.drawLine(
        _p(Offset(WarehouseLayout.corridorX.first, y)),
        _p(Offset(WarehouseLayout.corridorX.last, y)),
        paint,
      );
    }
    for (final x in WarehouseLayout.corridorX) {
      canvas.drawLine(
        _p(Offset(x, WarehouseLayout.corridorY.first)),
        _p(Offset(x, WarehouseLayout.corridorY.last)),
        paint,
      );
    }
  }

  void _paintRacks(Canvas canvas) {
    final fill = Paint()..color = const Color(0xFFDCDAD2);
    final stroke = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1
      ..color = AppColors.muted.withValues(alpha: 0.55);
    for (final bar in engine.layout.rackBars) {
      final r = Rect.fromLTRB(
        _p(bar.topLeft).dx,
        _p(bar.topLeft).dy,
        _p(bar.bottomRight).dx,
        _p(bar.bottomRight).dy,
      );
      final rr = RRect.fromRectAndRadius(r, const Radius.circular(2));
      canvas.drawRRect(rr, fill);
      canvas.drawRRect(rr, stroke);
    }

    // 점유 중인 랙 슬롯 강조(자원 잠금 시각화).
    for (final loc in engine.layout.locations) {
      final owner = engine.ledger.resourceOwner(loc.id);
      if (owner == null) continue;
      canvas.drawCircle(
        _p(loc.pos),
        math.max(2.0, _s(1.6)),
        Paint()..color = AppColors.series4,
      );
    }
  }

  void _paintStations(Canvas canvas) {
    for (final s in engine.layout.stations) {
      final color = switch (s.kind) {
        StationKind.inboundDock => AppColors.series3,
        StationKind.outboundDock => AppColors.series2,
        StationKind.charger => AppColors.series7,
        StationKind.workstation => AppColors.series5,
        StationKind.loading => AppColors.series4,
        StationKind.standby => AppColors.muted,
        StationKind.assembly => AppColors.good,
      };
      final c = _p(s.pos);
      final half = math.max(3.0, _s(2.6));
      final rect = Rect.fromCenter(center: c, width: half * 2, height: half * 2);
      canvas.drawRRect(
        RRect.fromRectAndRadius(rect, const Radius.circular(3)),
        Paint()..color = color.withValues(alpha: 0.30),
      );
      canvas.drawRRect(
        RRect.fromRectAndRadius(rect, const Radius.circular(3)),
        Paint()
          ..style = PaintingStyle.stroke
          ..strokeWidth = 1.4
          ..color = color,
      );
      if (!compact) {
        _label(
          canvas,
          s.id,
          Offset(c.dx - 12, c.dy + half + 2),
          color: color,
          size: 8.5,
        );
      }
    }
  }

  void _paintIncidents(Canvas canvas) {
    for (final inc in engine.incidents.where((i) => i.active)) {
      if (inc.pos == null || inc.radius <= 0) continue;
      final color = AppColors.severityColor(inc.type.severity);
      canvas.drawCircle(
        _p(inc.pos!),
        _s(inc.radius),
        Paint()..color = color.withValues(alpha: 0.12),
      );
      canvas.drawCircle(
        _p(inc.pos!),
        _s(inc.radius),
        Paint()
          ..style = PaintingStyle.stroke
          ..strokeWidth = 1.5
          ..color = color.withValues(alpha: 0.7),
      );
      _label(
        canvas,
        inc.type.label,
        _p(inc.pos!) + Offset(_s(inc.radius) * 0.2, -_s(inc.radius) - 12),
        color: color,
        size: 10,
        bold: true,
      );
    }
  }

  void _paintPaths(Canvas canvas) {
    for (final r in engine.robots) {
      if (r.path.isEmpty) continue;
      final selected = engine.selectedRobotId == r.id;
      final color = AppColors.robotStateColor(r.state);
      final paint = Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = selected ? 2.0 : 1.2
        ..color = color.withValues(alpha: selected ? 0.85 : 0.32);
      final path = Path()..moveTo(_p(r.pos).dx, _p(r.pos).dy);
      for (final wp in r.path) {
        path.lineTo(_p(wp).dx, _p(wp).dy);
      }
      canvas.drawPath(path, paint);
      canvas.drawCircle(
        _p(r.path.last),
        selected ? 3.5 : 2.2,
        Paint()..color = color.withValues(alpha: selected ? 0.9 : 0.4),
      );
    }

    // 선택 로봇의 최근 주행 궤적(이력).
    if (showTrace) {
      final sel = engine.selectedRobot;
      if (sel != null && sel.trace.length > 1) {
        final path = Path()
          ..moveTo(_p(sel.trace.first).dx, _p(sel.trace.first).dy);
        for (final t in sel.trace.skip(1)) {
          path.lineTo(_p(t).dx, _p(t).dy);
        }
        canvas.drawPath(
          path,
          Paint()
            ..style = PaintingStyle.stroke
            ..strokeWidth = 1.2
            ..color = AppColors.textSecondary.withValues(alpha: 0.45),
        );
      }
    }
  }

  void _paintWorkers(Canvas canvas) {
    for (final w in engine.workers) {
      final c = _p(w.pos);
      final distress = w.inDistress;
      final color = distress ? AppColors.critical : AppColors.series5;

      // 안전 필드(경고 4m / 보호 1.7m).
      canvas.drawCircle(
        c,
        _s(8),
        Paint()..color = color.withValues(alpha: 0.06),
      );
      canvas.drawCircle(
        c,
        _s(3.5),
        Paint()..color = color.withValues(alpha: 0.14),
      );

      canvas.drawCircle(c, math.max(3.0, _s(1.9)), Paint()..color = color);
      canvas.drawCircle(
        c,
        math.max(3.0, _s(1.9)),
        Paint()
          ..style = PaintingStyle.stroke
          ..strokeWidth = 1.4
          ..color = AppColors.surface,
      );
      if (!compact) {
        _label(
          canvas,
          distress ? '${w.name} ⚠ 위급' : w.name,
          Offset(c.dx + 7, c.dy - 5),
          color: distress ? AppColors.critical : AppColors.textSecondary,
          size: 9,
          bold: distress,
        );
      }
    }
  }

  void _paintRobots(Canvas canvas) {
    for (final r in engine.robots) {
      final c = _p(r.pos);
      final color = AppColors.robotStateColor(r.state);
      final selected = engine.selectedRobotId == r.id;
      final radius = math.max(5.0, _s(2.4));

      if (selected) {
        canvas.drawCircle(
          c,
          radius + 6,
          Paint()
            ..style = PaintingStyle.stroke
            ..strokeWidth = 1.5
            ..color = AppColors.textPrimary.withValues(alpha: 0.75),
        );
      }

      // 본체.
      canvas.drawCircle(c, radius, Paint()..color = color);
      // 겹침 방지용 서피스 링.
      canvas.drawCircle(
        c,
        radius,
        Paint()
          ..style = PaintingStyle.stroke
          ..strokeWidth = 2
          ..color = AppColors.surface,
      );

      // 진행 방향.
      final head = Offset(
        c.dx + math.cos(r.heading) * (radius + 4),
        c.dy + math.sin(r.heading) * (radius + 4),
      );
      canvas.drawLine(
        c,
        head,
        Paint()
          ..strokeWidth = 1.6
          ..strokeCap = StrokeCap.round
          ..color = color,
      );

      // 배터리 링.
      canvas.drawArc(
        Rect.fromCircle(center: c, radius: radius + 3.2),
        -math.pi / 2,
        2 * math.pi * (r.battery / 100),
        false,
        Paint()
          ..style = PaintingStyle.stroke
          ..strokeWidth = 2
          ..strokeCap = StrokeCap.round
          ..color = AppColors.batteryColor(r.battery),
      );

      // 안전 정지/양보 표시.
      if (r.safetyNote != null) {
        canvas.drawCircle(
          c,
          radius + 8,
          Paint()
            ..style = PaintingStyle.stroke
            ..strokeWidth = 1
            ..color = AppColors.warning.withValues(alpha: 0.75),
        );
      }

      if (!compact) {
        _label(
          canvas,
          r.id,
          Offset(c.dx - 11, c.dy + radius + 4),
          color: selected ? AppColors.textPrimary : AppColors.textSecondary,
          size: 9,
          bold: selected,
        );
      }
    }

    // 호버 툴팁.
    if (hoverWorld != null) {
      Robot? hit;
      var best = 4.0;
      for (final r in engine.robots) {
        final d = (r.pos - hoverWorld!).distance;
        if (d < best) {
          best = d;
          hit = r;
        }
      }
      if (hit != null) _paintRobotTooltip(canvas, hit);
    }
  }

  void _paintRobotTooltip(Canvas canvas, Robot r) {
    final lines = <String>[
      '${r.id} ${r.name} · ${r.state.label}',
      '배터리 ${r.battery.toStringAsFixed(0)}%  ·  속도 ${r.speed.toStringAsFixed(1)} u/s',
      r.taskId == null
          ? '태스크 없음'
          : '${r.taskId} · 진행 ${(r.taskProgress * 100).toStringAsFixed(0)}%',
      r.activity ?? r.safetyNote ?? '-',
    ];
    const w = 210.0;
    final h = 14.0 * lines.length + 12;
    var pos = _p(r.pos) + const Offset(12, -10);
    // 캔버스 밖으로 나가지 않도록 보정.
    final maxX = origin.dx + WarehouseLayout.width * scale - w;
    if (pos.dx > maxX) pos = Offset(maxX, pos.dy);
    if (pos.dy < origin.dy) pos = Offset(pos.dx, origin.dy);

    final rect = Rect.fromLTWH(pos.dx, pos.dy, w, h);
    canvas.drawRRect(
      RRect.fromRectAndRadius(rect, const Radius.circular(6)),
      Paint()..color = AppColors.surfaceRaised.withValues(alpha: 0.98),
    );
    canvas.drawRRect(
      RRect.fromRectAndRadius(rect, const Radius.circular(6)),
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1
        ..color = AppColors.border,
    );
    for (var i = 0; i < lines.length; i++) {
      _label(
        canvas,
        lines[i],
        Offset(rect.left + 8, rect.top + 6 + i * 14),
        color: i == 0 ? AppColors.textPrimary : AppColors.textSecondary,
        size: 10.5,
        bold: i == 0,
      );
    }
  }

  void _label(
    Canvas canvas,
    String text,
    Offset at, {
    Color color = AppColors.muted,
    double size = 10,
    bool bold = false,
  }) {
    final tp = TextPainter(
      text: TextSpan(
        text: text,
        style: baseStyle.copyWith(
          color: color,
          fontSize: size,
          fontWeight: bold ? FontWeight.w700 : FontWeight.w400,
        ),
      ),
      textDirection: TextDirection.ltr,
    )..layout();
    tp.paint(canvas, at);
  }

  @override
  bool shouldRepaint(covariant _MapPainter old) => true;
}
