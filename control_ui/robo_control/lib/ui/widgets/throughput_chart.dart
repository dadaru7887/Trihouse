import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../../core/fleet_engine.dart';
import '../theme.dart';

/// 5분 단위 완료 태스크 수 막대 차트(단일 계열).
///
/// 계열이 하나이므로 범례 없이 제목이 계열을 지시한다. 축은 하나만 쓰고,
/// 실패 건수는 별도 계열이 아니라 툴팁의 보조 정보로만 제공한다.
class ThroughputChart extends StatefulWidget {
  const ThroughputChart({
    super.key,
    required this.buckets,
    this.asTable = false,
    this.height = 160,
  });

  final List<ThroughputBucket> buckets;
  final bool asTable;
  final double height;

  @override
  State<ThroughputChart> createState() => _ThroughputChartState();
}

class _ThroughputChartState extends State<ThroughputChart> {
  int? _hover;

  static const double _padLeft = 30;
  static const double _padBottom = 20;
  static const double _padTop = 8;

  @override
  Widget build(BuildContext context) {
    if (widget.asTable) return _table();

    return SizedBox(
      height: widget.height,
      child: LayoutBuilder(
        builder: (context, c) {
          final plotWidth = c.maxWidth - _padLeft;
          return MouseRegion(
            onHover: (e) {
              final i = _indexAt(e.localPosition.dx, plotWidth);
              if (i != _hover) setState(() => _hover = i);
            },
            onExit: (_) => setState(() => _hover = null),
            child: Stack(
              children: <Widget>[
                Positioned.fill(
                  child: CustomPaint(
                    painter: _ThroughputPainter(
                      buckets: widget.buckets,
                      hover: _hover,
                      baseStyle: DefaultTextStyle.of(context).style,
                    ),
                  ),
                ),
                if (_hover != null && _hover! < widget.buckets.length)
                  _tooltip(c.maxWidth, plotWidth),
              ],
            ),
          );
        },
      ),
    );
  }

  int? _indexAt(double dx, double plotWidth) {
    if (widget.buckets.isEmpty) return null;
    final x = dx - _padLeft;
    if (x < 0 || x > plotWidth) return null;
    final slot = plotWidth / widget.buckets.length;
    final i = (x / slot).floor();
    return (i >= 0 && i < widget.buckets.length) ? i : null;
  }

  Widget _tooltip(double totalWidth, double plotWidth) {
    final i = _hover!;
    final b = widget.buckets[i];
    final slot = plotWidth / widget.buckets.length;
    final center = _padLeft + slot * (i + 0.5);
    const tipWidth = 150.0;
    final left = (center - tipWidth / 2).clamp(0.0, totalWidth - tipWidth);

    return Positioned(
      left: left,
      top: 0,
      width: tipWidth,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 7),
        decoration: BoxDecoration(
          color: AppColors.surfaceRaised,
          borderRadius: BorderRadius.circular(6),
          border: Border.all(color: AppColors.border),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            Text(
              b.label,
              style: const TextStyle(
                color: AppColors.textPrimary,
                fontSize: 12,
                fontWeight: FontWeight.w600,
              ),
            ),
            const SizedBox(height: 3),
            Row(
              children: <Widget>[
                Container(
                  width: 8,
                  height: 8,
                  decoration: const BoxDecoration(
                    color: AppColors.series1,
                    shape: BoxShape.circle,
                  ),
                ),
                const SizedBox(width: 5),
                Text(
                  '완료 ${b.completed}건',
                  style: const TextStyle(
                    color: AppColors.textSecondary,
                    fontSize: 11.5,
                  ),
                ),
              ],
            ),
            Text(
              '실패 ${b.failed}건',
              style: const TextStyle(color: AppColors.muted, fontSize: 11),
            ),
          ],
        ),
      ),
    );
  }

  Widget _table() {
    return SizedBox(
      height: widget.height,
      child: SingleChildScrollView(
        child: Table(
          columnWidths: const <int, TableColumnWidth>{
            0: FlexColumnWidth(1.2),
            1: FlexColumnWidth(1),
            2: FlexColumnWidth(1),
          },
          children: <TableRow>[
            const TableRow(
              children: <Widget>[
                _Cell('구간', header: true),
                _Cell('완료', header: true),
                _Cell('실패', header: true),
              ],
            ),
            for (final b in widget.buckets.reversed)
              TableRow(
                children: <Widget>[
                  _Cell(b.label),
                  _Cell('${b.completed}'),
                  _Cell('${b.failed}'),
                ],
              ),
          ],
        ),
      ),
    );
  }
}

class _Cell extends StatelessWidget {
  const _Cell(this.text, {this.header = false});

  final String text;
  final bool header;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 3),
    child: Text(
      text,
      style: TextStyle(
        color: header ? AppColors.muted : AppColors.textSecondary,
        fontSize: 11.5,
        fontWeight: header ? FontWeight.w600 : FontWeight.w400,
        fontFeatures: const <FontFeature>[FontFeature.tabularFigures()],
      ),
    ),
  );
}

class _ThroughputPainter extends CustomPainter {
  _ThroughputPainter({
    required this.buckets,
    required this.hover,
    required this.baseStyle,
  });

  final List<ThroughputBucket> buckets;
  final int? hover;

  /// 축·라벨 텍스트의 기준 스타일. 테마의 타이포그래피를 그대로 상속한다.
  final TextStyle baseStyle;

  @override
  void paint(Canvas canvas, Size size) {
    if (buckets.isEmpty) return;

    const padLeft = _ThroughputChartState._padLeft;
    const padBottom = _ThroughputChartState._padBottom;
    const padTop = _ThroughputChartState._padTop;

    final plotW = size.width - padLeft;
    final plotH = size.height - padBottom - padTop;
    final maxV = math.max(
      4,
      buckets.map((b) => b.completed).reduce(math.max),
    );
    final niceMax = ((maxV / 4).ceil() * 4).toDouble();

    final gridPaint = Paint()
      ..color = AppColors.grid
      ..strokeWidth = 1;
    final basePaint = Paint()
      ..color = AppColors.baseline
      ..strokeWidth = 1;

    // 가로 격자 + y축 라벨.
    for (var i = 0; i <= 4; i++) {
      final v = niceMax * i / 4;
      final y = padTop + plotH - (v / niceMax) * plotH;
      canvas.drawLine(Offset(padLeft, y), Offset(size.width, y), gridPaint);
      _text(
        canvas,
        v.toStringAsFixed(0),
        Offset(padLeft - 6, y),
        align: TextAlign.right,
        color: AppColors.muted,
        size: 10,
        anchorRight: true,
        anchorMiddle: true,
      );
    }
    canvas.drawLine(
      Offset(padLeft, padTop + plotH),
      Offset(size.width, padTop + plotH),
      basePaint,
    );

    final slot = plotW / buckets.length;
    final barW = math.max(3.0, math.min(26.0, slot - 6));

    for (var i = 0; i < buckets.length; i++) {
      final b = buckets[i];
      final h = (b.completed / niceMax) * plotH;
      final cx = padLeft + slot * (i + 0.5);
      final rect = Rect.fromLTWH(cx - barW / 2, padTop + plotH - h, barW, h);
      final isHover = hover == i;
      final isCurrent = i == buckets.length - 1;

      final paint = Paint()
        ..color = isHover
            ? AppColors.series1
            : AppColors.series1.withValues(alpha: isCurrent ? 0.62 : 0.92);

      if (h > 0.5) {
        canvas.drawRRect(
          RRect.fromRectAndCorners(
            rect,
            topLeft: const Radius.circular(4),
            topRight: const Radius.circular(4),
          ),
          paint,
        );
      }

      // 마지막 버킷은 집계 중임을 파선 윤곽으로 표시한다.
      if (isCurrent && h > 0.5) {
        canvas.drawRRect(
          RRect.fromRectAndCorners(
            rect,
            topLeft: const Radius.circular(4),
            topRight: const Radius.circular(4),
          ),
          Paint()
            ..style = PaintingStyle.stroke
            ..strokeWidth = 1
            ..color = AppColors.series1,
        );
      }

      // 첫 구간·마지막 구간·호버 구간만 선별 직접 라벨.
      if (isHover || isCurrent) {
        _text(
          canvas,
          '${b.completed}',
          Offset(cx, padTop + plotH - h - 11),
          color: AppColors.textPrimary,
          size: 10.5,
          anchorCenter: true,
        );
      }

      if (i % 2 == 0 || isHover) {
        _text(
          canvas,
          b.label,
          Offset(cx, size.height - padBottom + 5),
          color: isHover ? AppColors.textSecondary : AppColors.muted,
          size: 10,
          anchorCenter: true,
        );
      }
    }
  }

  void _text(
    Canvas canvas,
    String text,
    Offset at, {
    Color color = AppColors.muted,
    double size = 10,
    TextAlign align = TextAlign.left,
    bool anchorCenter = false,
    bool anchorRight = false,
    bool anchorMiddle = false,
  }) {
    final tp = TextPainter(
      text: TextSpan(
        text: text,
        style: baseStyle.copyWith(color: color, fontSize: size),
      ),
      textDirection: TextDirection.ltr,
      textAlign: align,
    )..layout();
    var dx = at.dx;
    var dy = at.dy;
    if (anchorCenter) dx -= tp.width / 2;
    if (anchorRight) dx -= tp.width;
    if (anchorMiddle) dy -= tp.height / 2;
    tp.paint(canvas, Offset(dx, dy));
  }

  @override
  bool shouldRepaint(covariant _ThroughputPainter old) => true;
}
