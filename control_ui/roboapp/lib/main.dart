import 'package:flutter/material.dart';
import 'package:robo_core/robo_core.dart';

import 'data/store_factory.dart';
import 'shop/cart.dart';
import 'shop/catalog.dart';
import 'shop/order_service.dart';
import 'ui/home_page.dart';
import 'ui/theme.dart';

void main() {
  runApp(const RoboShopApp());
}

/// RoboSapiens 소비자 주문 앱.
///
/// 관제센터(robo_control)와 **같은 원장**을 사용한다. 여기서 접수한 주문은
/// `orders` 테이블에 남고, 관제가 이를 읽어 로봇 출고 태스크로 전개한다.
class RoboShopApp extends StatefulWidget {
  const RoboShopApp({super.key});

  @override
  State<RoboShopApp> createState() => _RoboShopAppState();
}

class _RoboShopAppState extends State<RoboShopApp> {
  late final DataStore _store = createStore();
  late final Catalog _catalog = Catalog(_store.inventory);
  late final OrderService _orders = OrderService(_store);
  final Cart _cart = Cart();

  @override
  void dispose() {
    _cart.dispose();
    _store.close();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'RoboSapiens 마트',
      debugShowCheckedModeBanner: false,
      theme: buildShopTheme(),
      home: HomePage(catalog: _catalog, cart: _cart, orders: _orders),
    );
  }
}
