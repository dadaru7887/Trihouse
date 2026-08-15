import 'package:robo_core/robo_core.dart';

import 'cart.dart';

/// 소비자 주문을 접수한다.
///
/// 관제(robo_control)와 같은 원장을 쓰되, **태스크는 만들지 않는다.**
/// 스케줄러·평면도를 아는 쪽은 관제이므로, 여기서는 주문과 라인만 기록하고
/// `expanded = 0` 표시를 남긴다. 관제가 3초 주기로 이를 읽어 출고 태스크로
/// 전개한다.
class OrderService {
  OrderService(this.store, {this.customerName = '모바일 고객'});

  final DataStore store;
  final String customerName;

  static const Map<Urgency, Duration> _leadTime = <Urgency, Duration>{
    Urgency.critical: Duration(minutes: 15),
    Urgency.high: Duration(minutes: 30),
    Urgency.normal: Duration(minutes: 60),
    Urgency.low: Duration(hours: 3),
  };

  SalesOrder placeOrder(Cart cart, {Urgency urgency = Urgency.normal}) {
    final now = DateTime.now();
    final id = 'ORD-${store.counters.next('order').toString().padLeft(4, '0')}';

    final order = SalesOrder(
      id: id,
      customer: customerName,
      urgency: urgency,
      createdAt: now,
      dueAt: now.add(_leadTime[urgency]!),
      lineCount: cart.items.length,
    );

    store.orders.insert(
      order,
      source: 'customer',
      expanded: false,
      lines: cart.items
          .map(
            (i) => OrderLine(
              sku: i.product.sku,
              name: i.product.name,
              qty: i.qty,
            ),
          )
          .toList(),
    );

    return order;
  }

  /// 이 고객의 주문 목록(최신순).
  List<SalesOrder> myOrders({int limit = 30}) => store.orders
      .loadRecent(limit: 200)
      .where((o) => o.customer == customerName)
      .take(limit)
      .toList();

  List<OrderLine> linesOf(String orderId) => store.orders.loadLines(orderId);

  /// 주문에 딸린 태스크의 진행 상황. 관제가 전개하기 전이면 비어 있다.
  List<WorkTask> tasksOf(SalesOrder order) => store.tasks
      .loadRecent(limit: 300)
      .where((t) => t.orderId == order.id)
      .toList();
}
