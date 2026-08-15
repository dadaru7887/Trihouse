import 'dart:async';

import 'package:flutter/material.dart';
import 'package:robo_core/robo_core.dart';

import '../shop/order_service.dart';
import 'live_view.dart';
import 'theme.dart';

/// 내 주문 내역과 진행 상황.
///
/// 관제센터가 주문을 태스크로 전개하면 그 진행률이 여기 실시간으로 반영된다.
class OrdersPage extends StatefulWidget {
  const OrdersPage({super.key, required this.service, this.embedded = false});

  final OrderService service;

  /// 하단 메뉴 안에서 쓰일 때는 뒤로가기 화살표를 숨긴다.
  final bool embedded;

  @override
  State<OrdersPage> createState() => _OrdersPageState();
}

class _OrdersPageState extends State<OrdersPage> {
  Timer? _timer;
  List<SalesOrder> _orders = <SalesOrder>[];

  @override
  void initState() {
    super.initState();
    _reload();
    _timer = Timer.periodic(const Duration(seconds: 2), (_) => _reload());
  }

  void _reload() {
    if (!mounted) return;
    setState(() => _orders = widget.service.myOrders());
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        automaticallyImplyLeading: !widget.embedded,
        title: const Text(
          '주문 내역',
          style: TextStyle(fontSize: 17, fontWeight: FontWeight.w700),
        ),
      ),
      body: _orders.isEmpty
          ? const Center(
              child: Text(
                '아직 주문이 없습니다.',
                style: TextStyle(color: ShopColors.muted, fontSize: 13),
              ),
            )
          : ListView.builder(
              padding: const EdgeInsets.fromLTRB(14, 14, 14, 24),
              itemCount: _orders.length,
              itemBuilder: (context, i) => _OrderCard(
                order: _orders[i],
                service: widget.service,
              ),
            ),
    );
  }
}

class _OrderCard extends StatelessWidget {
  const _OrderCard({required this.order, required this.service});

  final SalesOrder order;
  final OrderService service;

  @override
  Widget build(BuildContext context) {
    final lines = service.linesOf(order.id);
    final tasks = service.tasksOf(order);
    final done = tasks.where((t) => t.state == TaskState.done).length;
    final active = tasks.cast<WorkTask?>().firstWhere(
      (t) => t?.state == TaskState.inProgress || t?.state == TaskState.claimed,
      orElse: () => null,
    );

    final (String label, Color color, IconData icon) = switch (order.state) {
      OrderState.fulfilled => ('수령 준비 완료', ShopColors.good, Icons.check_circle),
      OrderState.partial => ('일부만 준비됨', ShopColors.warning, Icons.error_outline),
      OrderState.failed => ('처리 실패', ShopColors.critical, Icons.cancel_outlined),
      OrderState.working => ('집품 중', ShopColors.brand, Icons.autorenew),
      OrderState.open => (
        tasks.isEmpty ? '접수 확인 중' : '작업 대기 중',
        ShopColors.muted,
        Icons.schedule,
      ),
    };

    final progress = tasks.isEmpty
        ? 0.0
        : tasks.fold<double>(0, (a, t) => a + t.progress) / tasks.length;

    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.fromLTRB(15, 13, 15, 12),
      decoration: BoxDecoration(
        color: ShopColors.surface,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: ShopColors.line),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            children: <Widget>[
              Icon(icon, size: 15, color: color),
              const SizedBox(width: 7),
              Text(
                label,
                style: TextStyle(
                  color: color,
                  fontSize: 13,
                  fontWeight: FontWeight.w700,
                ),
              ),
              const Spacer(),
              Text(
                order.id,
                style: const TextStyle(color: ShopColors.muted, fontSize: 11.5),
              ),
            ],
          ),
          const SizedBox(height: 10),
          for (final l in lines)
            Padding(
              padding: const EdgeInsets.only(bottom: 3),
              child: Text(
                '${l.name} × ${l.qty}',
                style: const TextStyle(color: ShopColors.ink, fontSize: 13),
              ),
            ),
          const SizedBox(height: 10),
          if (tasks.isNotEmpty) ...<Widget>[
            ClipRRect(
              borderRadius: BorderRadius.circular(3),
              child: LinearProgressIndicator(
                value: progress,
                minHeight: 5,
                backgroundColor: ShopColors.line,
                valueColor: AlwaysStoppedAnimation<Color>(color),
              ),
            ),
            const SizedBox(height: 7),
            Text(
              '$done / ${tasks.length} 품목 완료'
              '${active?.robotId == null ? "" : " · ${active!.robotId} 작업 중"}',
              style: const TextStyle(color: ShopColors.inkSoft, fontSize: 11.5),
            ),
          ] else
            const Text(
              '센터에서 주문을 확인하고 있습니다.',
              style: TextStyle(color: ShopColors.muted, fontSize: 11.5),
            ),
          const SizedBox(height: 4),
          Row(
            children: <Widget>[
              Text(
                '수령 예정 ${_hhmm(order.dueAt)}',
                style: const TextStyle(color: ShopColors.muted, fontSize: 11.5),
              ),
              const Spacer(),
              LiveViewButton(orderId: order.id, robotId: active?.robotId),
            ],
          ),
        ],
      ),
    );
  }

  static String _hhmm(DateTime t) =>
      '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';
}
