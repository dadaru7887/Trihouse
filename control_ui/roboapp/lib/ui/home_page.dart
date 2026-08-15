import 'package:flutter/material.dart';

import '../shop/cart.dart';
import '../shop/catalog.dart';
import '../shop/order_service.dart';
import 'live_view.dart';
import 'orders_page.dart';
import 'shop_page.dart';
import 'theme.dart';

/// 앱의 메인 메뉴.
///
/// 상품 · **실시간 매장** · 주문 내역 3개 항목을 하단 바로 오간다.
/// 실시간 매장은 주문이 없어도 언제든 볼 수 있다.
class HomePage extends StatefulWidget {
  const HomePage({
    super.key,
    required this.catalog,
    required this.cart,
    required this.orders,
  });

  final Catalog catalog;
  final Cart cart;
  final OrderService orders;

  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> {
  int _index = 0;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: ShopColors.page,
      body: IndexedStack(
        index: _index,
        children: <Widget>[
          ShopPage(
            catalog: widget.catalog,
            cart: widget.cart,
            orders: widget.orders,
            onSeeOrders: () => setState(() => _index = 2),
          ),
          _LiveStorePage(active: _index == 1),
          OrdersPage(service: widget.orders, embedded: true),
        ],
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _index,
        onDestinationSelected: (i) => setState(() => _index = i),
        height: 62,
        backgroundColor: ShopColors.surface,
        surfaceTintColor: Colors.transparent,
        indicatorColor: ShopColors.brand.withValues(alpha: 0.12),
        labelBehavior: NavigationDestinationLabelBehavior.alwaysShow,
        destinations: const <NavigationDestination>[
          NavigationDestination(
            icon: Icon(Icons.storefront_outlined),
            selectedIcon: Icon(Icons.storefront, color: ShopColors.brand),
            label: '상품',
          ),
          NavigationDestination(
            icon: Icon(Icons.videocam_outlined),
            selectedIcon: Icon(Icons.videocam, color: ShopColors.brand),
            label: '실시간 매장',
          ),
          NavigationDestination(
            icon: Icon(Icons.receipt_long_outlined),
            selectedIcon: Icon(Icons.receipt_long, color: ShopColors.brand),
            label: '주문 내역',
          ),
        ],
      ),
    );
  }
}

/// 실시간 매장 탭. 주문과 무관하게 매장 상황을 보여준다.
class _LiveStorePage extends StatelessWidget {
  const _LiveStorePage({required this.active});

  final bool active;

  @override
  Widget build(BuildContext context) => Scaffold(
    backgroundColor: Colors.black,
    appBar: AppBar(
      backgroundColor: Colors.black,
      foregroundColor: Colors.white,
      title: const Text(
        '실시간 매장',
        style: TextStyle(fontSize: 17, fontWeight: FontWeight.w700),
      ),
    ),
    body: LiveStoreView(
      active: active,
      caption: '주문하지 않아도 매장 상황을 볼 수 있습니다. 주문하시면 상품을 집품하는 '
          '로봇의 화면으로 전환됩니다.',
    ),
  );
}
