import 'package:flutter/material.dart';
import 'package:robo_core/robo_core.dart';

import '../shop/cart.dart';
import '../shop/catalog.dart';
import '../shop/order_service.dart';
import 'cart_sheet.dart';
import 'theme.dart';

/// 상품 목록 — 상온·냉장·냉동 3개 카테고리.
class ShopPage extends StatefulWidget {
  const ShopPage({
    super.key,
    required this.catalog,
    required this.cart,
    required this.orders,
    this.onSeeOrders,
  });

  final Catalog catalog;
  final Cart cart;
  final OrderService orders;

  /// 주문 내역 메뉴로 이동. 하단 메뉴가 처리한다.
  final VoidCallback? onSeeOrders;

  @override
  State<ShopPage> createState() => _ShopPageState();
}

class _ShopPageState extends State<ShopPage> with SingleTickerProviderStateMixin {
  late final TabController _tab = TabController(length: 3, vsync: this);
  List<Product> _products = <Product>[];

  @override
  void initState() {
    super.initState();
    _reload();
    widget.cart.addListener(_onCart);
  }

  void _onCart() => setState(() {});

  void _reload() => setState(() => _products = widget.catalog.load());

  @override
  void dispose() {
    widget.cart.removeListener(_onCart);
    _tab.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text(
          'RoboSapiens 마트',
          style: TextStyle(fontSize: 17, fontWeight: FontWeight.w700),
        ),
        actions: <Widget>[
          IconButton(
            tooltip: '새로고침',
            onPressed: _reload,
            icon: const Icon(Icons.refresh, size: 20),
          ),
          const SizedBox(width: 4),
        ],
        bottom: TabBar(
          controller: _tab,
          labelColor: ShopColors.ink,
          unselectedLabelColor: ShopColors.muted,
          indicatorColor: ShopColors.brand,
          labelStyle: const TextStyle(fontSize: 13.5, fontWeight: FontWeight.w600),
          tabs: <Widget>[
            for (final z in TempZone.values)
              Tab(
                height: 46,
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: <Widget>[
                    Icon(ShopColors.zoneIcon(z), size: 15),
                    const SizedBox(width: 6),
                    Text(z.label),
                  ],
                ),
              ),
          ],
        ),
      ),
      body: TabBarView(
        controller: _tab,
        children: <Widget>[
          for (final z in TempZone.values) _grid(z),
        ],
      ),
      bottomNavigationBar: widget.cart.isEmpty ? null : _cartBar(),
    );
  }

  Widget _grid(TempZone zone) {
    final items = _products.where((p) => p.zone == zone).toList();
    if (items.isEmpty) {
      return const Center(
        child: Padding(
          padding: EdgeInsets.all(28),
          child: Text(
            '판매 가능한 상품이 없습니다.\n센터에 재고가 입고되면 표시됩니다.',
            textAlign: TextAlign.center,
            style: TextStyle(color: ShopColors.muted, fontSize: 13, height: 1.6),
          ),
        ),
      );
    }
    return LayoutBuilder(
      builder: (context, c) {
        final columns = (c.maxWidth / 260).floor().clamp(1, 4);
        return GridView.builder(
          padding: const EdgeInsets.fromLTRB(14, 14, 14, 20),
          gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
            crossAxisCount: columns,
            mainAxisSpacing: 12,
            crossAxisSpacing: 12,
            mainAxisExtent: 196,
          ),
          itemCount: items.length,
          itemBuilder: (context, i) => _ProductCard(
            product: items[i],
            inCart: widget.cart.qtyOf(items[i].sku),
            onAdd: () => widget.cart.add(items[i]),
          ),
        );
      },
    );
  }

  Widget _cartBar() => SafeArea(
    child: Container(
      padding: const EdgeInsets.fromLTRB(16, 10, 12, 10),
      decoration: const BoxDecoration(
        color: ShopColors.surface,
        border: Border(top: BorderSide(color: ShopColors.line)),
      ),
      child: Row(
        children: <Widget>[
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: <Widget>[
                Text(
                  '장바구니 ${widget.cart.totalQty}개',
                  style: const TextStyle(
                    color: ShopColors.inkSoft,
                    fontSize: 11.5,
                  ),
                ),
                Text(
                  won(widget.cart.totalPrice),
                  style: const TextStyle(
                    color: ShopColors.ink,
                    fontSize: 17,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ],
            ),
          ),
          FilledButton(
            onPressed: () async {
              await CartSheet.show(context, widget.cart, widget.orders);
              _reload();
            },
            style: FilledButton.styleFrom(
              backgroundColor: ShopColors.brand,
              padding: const EdgeInsets.symmetric(horizontal: 22, vertical: 14),
            ),
            child: const Text(
              '주문하기',
              style: TextStyle(fontSize: 14, fontWeight: FontWeight.w700),
            ),
          ),
        ],
      ),
    ),
  );
}

class _ProductCard extends StatelessWidget {
  const _ProductCard({
    required this.product,
    required this.inCart,
    required this.onAdd,
  });

  final Product product;
  final int inCart;
  final VoidCallback onAdd;

  @override
  Widget build(BuildContext context) {
    final zoneColor = ShopColors.zone(product.zone);
    final days = product.daysToExpiry(DateTime.now());
    final soon = days != null && days <= 3;

    return Container(
      decoration: BoxDecoration(
        color: ShopColors.surface,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: ShopColors.line),
      ),
      padding: const EdgeInsets.fromLTRB(14, 12, 14, 10),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            children: <Widget>[
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
                decoration: BoxDecoration(
                  color: zoneColor.withValues(alpha: 0.10),
                  borderRadius: BorderRadius.circular(4),
                ),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: <Widget>[
                    Icon(ShopColors.zoneIcon(product.zone), size: 11, color: zoneColor),
                    const SizedBox(width: 4),
                    Text(
                      product.zone.label,
                      style: TextStyle(
                        color: zoneColor,
                        fontSize: 10.5,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ],
                ),
              ),
              const Spacer(),
              if (soon)
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 3),
                  decoration: BoxDecoration(
                    color: ShopColors.warning.withValues(alpha: 0.12),
                    borderRadius: BorderRadius.circular(4),
                  ),
                  child: Text(
                    days <= 0 ? '당일 소진' : '임박 D-$days',
                    style: const TextStyle(
                      color: ShopColors.warning,
                      fontSize: 10,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
            ],
          ),
          const SizedBox(height: 10),
          Text(
            product.name,
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(
              color: ShopColors.ink,
              fontSize: 14,
              fontWeight: FontWeight.w600,
              height: 1.3,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            product.sku,
            style: const TextStyle(color: ShopColors.muted, fontSize: 10.5),
          ),
          const Spacer(),
          Text(
            won(product.price),
            style: const TextStyle(
              color: ShopColors.ink,
              fontSize: 16,
              fontWeight: FontWeight.w700,
            ),
          ),
          const SizedBox(height: 2),
          Row(
            children: <Widget>[
              Text(
                '재고 ${product.available}개',
                style: TextStyle(
                  color: product.available <= 5
                      ? ShopColors.critical
                      : ShopColors.muted,
                  fontSize: 11,
                ),
              ),
              const Spacer(),
              if (inCart > 0)
                Padding(
                  padding: const EdgeInsets.only(right: 6),
                  child: Text(
                    '담김 $inCart',
                    style: const TextStyle(
                      color: ShopColors.brand,
                      fontSize: 11,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
              IconButton(
                tooltip: '장바구니 담기',
                onPressed: inCart >= product.available ? null : onAdd,
                visualDensity: VisualDensity.compact,
                padding: EdgeInsets.zero,
                constraints: const BoxConstraints.tightFor(width: 34, height: 34),
                icon: const Icon(Icons.add_shopping_cart, size: 18),
                color: ShopColors.brand,
              ),
            ],
          ),
        ],
      ),
    );
  }
}
