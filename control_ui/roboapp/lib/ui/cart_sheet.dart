import 'package:flutter/material.dart';
import 'package:robo_core/robo_core.dart';

import '../shop/cart.dart';
import '../shop/order_service.dart';
import 'live_view.dart';
import 'theme.dart';

/// 장바구니 확인 + 주문 접수 시트.
class CartSheet extends StatefulWidget {
  const CartSheet({super.key, required this.cart, required this.service});

  final Cart cart;
  final OrderService service;

  static Future<void> show(
    BuildContext context,
    Cart cart,
    OrderService service,
  ) => showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    backgroundColor: ShopColors.surface,
    shape: const RoundedRectangleBorder(
      borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
    ),
    builder: (_) => CartSheet(cart: cart, service: service),
  );

  @override
  State<CartSheet> createState() => _CartSheetState();
}

class _CartSheetState extends State<CartSheet> {
  Urgency _urgency = Urgency.normal;

  static const Map<Urgency, String> _leadLabel = <Urgency, String>{
    Urgency.critical: '15분 이내',
    Urgency.high: '30분 이내',
    Urgency.normal: '1시간 이내',
    Urgency.low: '3시간 이내',
  };

  @override
  Widget build(BuildContext context) {
    final cart = widget.cart;
    return SafeArea(
      child: Padding(
        padding: EdgeInsets.only(
          bottom: MediaQuery.viewInsetsOf(context).bottom,
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            const SizedBox(height: 10),
            Container(
              width: 38,
              height: 4,
              decoration: BoxDecoration(
                color: ShopColors.line,
                borderRadius: BorderRadius.circular(2),
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(18, 14, 18, 6),
              child: Row(
                children: <Widget>[
                  const Text(
                    '장바구니',
                    style: TextStyle(
                      color: ShopColors.ink,
                      fontSize: 16,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  const Spacer(),
                  TextButton(
                    onPressed: () {
                      cart.clear();
                      Navigator.of(context).pop();
                    },
                    child: const Text('비우기', style: TextStyle(fontSize: 12.5)),
                  ),
                ],
              ),
            ),
            Flexible(
              child: ListView(
                shrinkWrap: true,
                padding: const EdgeInsets.symmetric(horizontal: 18),
                children: <Widget>[
                  for (final item in cart.items) _line(item),
                  const SizedBox(height: 14),
                  const Text(
                    '수령 희망 시간',
                    style: TextStyle(color: ShopColors.inkSoft, fontSize: 12),
                  ),
                  const SizedBox(height: 8),
                  Wrap(
                    spacing: 7,
                    runSpacing: 7,
                    children: <Widget>[
                      for (final u in Urgency.values)
                        InkWell(
                          onTap: () => setState(() => _urgency = u),
                          child: Container(
                            padding: const EdgeInsets.symmetric(
                              horizontal: 12,
                              vertical: 9,
                            ),
                            decoration: BoxDecoration(
                              color: _urgency == u
                                  ? ShopColors.brand.withValues(alpha: 0.10)
                                  : Colors.transparent,
                              borderRadius: BorderRadius.circular(8),
                              border: Border.all(
                                color: _urgency == u
                                    ? ShopColors.brand
                                    : ShopColors.line,
                              ),
                            ),
                            child: Text(
                              _leadLabel[u]!,
                              style: TextStyle(
                                color: _urgency == u
                                    ? ShopColors.brand
                                    : ShopColors.inkSoft,
                                fontSize: 12.5,
                                fontWeight: _urgency == u
                                    ? FontWeight.w700
                                    : FontWeight.w400,
                              ),
                            ),
                          ),
                        ),
                    ],
                  ),
                  const SizedBox(height: 16),
                ],
              ),
            ),
            Container(
              padding: const EdgeInsets.fromLTRB(18, 14, 18, 18),
              decoration: const BoxDecoration(
                border: Border(top: BorderSide(color: ShopColors.line)),
              ),
              child: Column(
                children: <Widget>[
                  Row(
                    children: <Widget>[
                      const Text(
                        '결제 예정 금액',
                        style: TextStyle(color: ShopColors.inkSoft, fontSize: 13),
                      ),
                      const Spacer(),
                      Text(
                        won(cart.totalPrice),
                        style: const TextStyle(
                          color: ShopColors.ink,
                          fontSize: 19,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 12),
                  SizedBox(
                    width: double.infinity,
                    child: FilledButton(
                      onPressed: cart.isEmpty ? null : _placeOrder,
                      style: FilledButton.styleFrom(
                        backgroundColor: ShopColors.brand,
                        padding: const EdgeInsets.symmetric(vertical: 15),
                      ),
                      child: Text(
                        '${cart.totalQty}개 주문하기',
                        style: const TextStyle(
                          fontSize: 15,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _line(CartItem item) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 8),
    child: Row(
      children: <Widget>[
        Container(
          width: 34,
          height: 34,
          decoration: BoxDecoration(
            color: ShopColors.zone(item.product.zone).withValues(alpha: 0.10),
            borderRadius: BorderRadius.circular(8),
          ),
          child: Icon(
            ShopColors.zoneIcon(item.product.zone),
            size: 16,
            color: ShopColors.zone(item.product.zone),
          ),
        ),
        const SizedBox(width: 11),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              Text(
                item.product.name,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                  color: ShopColors.ink,
                  fontSize: 13.5,
                  fontWeight: FontWeight.w600,
                ),
              ),
              Text(
                won(item.product.price),
                style: const TextStyle(color: ShopColors.muted, fontSize: 11.5),
              ),
            ],
          ),
        ),
        _stepper(item),
        SizedBox(
          width: 74,
          child: Text(
            won(item.subtotal),
            textAlign: TextAlign.right,
            style: const TextStyle(
              color: ShopColors.ink,
              fontSize: 13,
              fontWeight: FontWeight.w600,
            ),
          ),
        ),
      ],
    ),
  );

  Widget _stepper(CartItem item) => Row(
    children: <Widget>[
      _stepButton(Icons.remove, () {
        widget.cart.setQty(item.product.sku, item.qty - 1);
        setState(() {});
      }),
      SizedBox(
        width: 28,
        child: Text(
          '${item.qty}',
          textAlign: TextAlign.center,
          style: const TextStyle(
            color: ShopColors.ink,
            fontSize: 13,
            fontWeight: FontWeight.w600,
          ),
        ),
      ),
      _stepButton(
        Icons.add,
        item.qty >= item.product.available
            ? null
            : () {
                widget.cart.setQty(item.product.sku, item.qty + 1);
                setState(() {});
              },
      ),
    ],
  );

  Widget _stepButton(IconData icon, VoidCallback? onTap) => InkWell(
    onTap: onTap,
    borderRadius: BorderRadius.circular(6),
    child: Container(
      width: 26,
      height: 26,
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: ShopColors.line),
      ),
      child: Icon(
        icon,
        size: 14,
        color: onTap == null ? ShopColors.line : ShopColors.inkSoft,
      ),
    ),
  );

  void _placeOrder() {
    final order = widget.service.placeOrder(widget.cart, urgency: _urgency);
    widget.cart.clear();
    Navigator.of(context).pop();
    showDialog<void>(
      context: context,
      builder: (context) => AlertDialog(
        backgroundColor: ShopColors.surface,
        icon: const Icon(
          Icons.check_circle_outline,
          color: ShopColors.good,
          size: 34,
        ),
        title: const Text(
          '주문이 접수되었습니다',
          style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
        ),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            Text(
              '주문번호 ${order.id}',
              style: const TextStyle(
                color: ShopColors.ink,
                fontSize: 13.5,
                fontWeight: FontWeight.w600,
              ),
            ),
            const SizedBox(height: 8),
            const Text(
              '센터에서 로봇이 상품을 집품합니다.\n실시간 화면에서 진행 상황을 볼 수 있습니다.',
              textAlign: TextAlign.center,
              style: TextStyle(
                color: ShopColors.inkSoft,
                fontSize: 12.5,
                height: 1.6,
              ),
            ),
          ],
        ),
        actions: <Widget>[
          TextButton(
            onPressed: () => Navigator.of(context).pop(),
            child: const Text('확인', style: TextStyle(fontSize: 13)),
          ),
          FilledButton.icon(
            onPressed: () {
              Navigator.of(context).pop();
              Navigator.of(context).push(
                MaterialPageRoute<void>(
                  builder: (_) => LiveViewPage(orderId: order.id),
                ),
              );
            },
            style: FilledButton.styleFrom(backgroundColor: ShopColors.brand),
            icon: const Icon(Icons.videocam_outlined, size: 16),
            label: const Text('실시간 보기', style: TextStyle(fontSize: 13)),
          ),
        ],
      ),
    );
  }
}
