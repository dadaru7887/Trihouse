import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:robo_core/robo_core.dart';
import 'package:roboapp/data/demo_seed.dart';
import 'package:roboapp/shop/cart.dart';
import 'package:roboapp/shop/catalog.dart';
import 'package:roboapp/shop/order_service.dart';
import 'package:roboapp/ui/home_page.dart';
import 'package:roboapp/ui/shop_page.dart';
import 'package:roboapp/ui/theme.dart';

(DataStore, Catalog, OrderService) _shop() {
  final store = MemoryDataStore();
  seedDemoCatalog(store);
  return (store, Catalog(store.inventory), OrderService(store));
}

void main() {
  test('카탈로그는 3온도 상품을 로트 합계로 집계한다', () {
    final (_, catalog, _) = _shop();
    final all = catalog.load();

    expect(all, isNotEmpty);
    for (final z in TempZone.values) {
      expect(
        catalog.load(zone: z).every((p) => p.zone == z),
        isTrue,
        reason: '${z.label} 필터가 다른 구획을 포함하면 안 됩니다.',
      );
      expect(catalog.load(zone: z), isNotEmpty, reason: '${z.label} 상품 필요');
    }
    expect(all.every((p) => p.available > 0 && p.price > 0), isTrue);
  });

  test('장바구니는 가용 재고를 넘겨 담을 수 없다', () {
    final (_, catalog, _) = _shop();
    final product = catalog.load().first;
    final cart = Cart();

    cart.add(product, qty: product.available);
    expect(cart.totalQty, product.available);

    cart.add(product); // 초과 → 무시
    expect(cart.totalQty, product.available);

    cart.setQty(product.sku, 2);
    expect(cart.totalQty, 2);
    expect(cart.totalPrice, product.price * 2);

    cart.remove(product.sku);
    expect(cart.isEmpty, isTrue);
  });

  test('주문은 라인과 함께 저장되고 관제 전개 대상으로 남는다', () {
    final (store, catalog, service) = _shop();
    final products = catalog.load();
    final cart = Cart()
      ..add(products[0], qty: 2)
      ..add(products[1]);

    final order = service.placeOrder(cart, urgency: Urgency.high);

    expect(order.lineCount, 2);
    expect(order.dueAt.isAfter(order.createdAt), isTrue);

    final lines = store.orders.loadLines(order.id);
    expect(lines.length, 2);
    expect(lines.first.qty, 2);

    // 관제가 아직 태스크로 전개하지 않은 상태여야 한다.
    expect(
      store.orders.loadUnexpanded().map((o) => o.id),
      contains(order.id),
    );
    expect(service.myOrders().first.id, order.id);
  });

  testWidgets('메인 메뉴에 상품·실시간 매장·주문 내역이 있다', (WidgetTester tester) async {
    tester.view.physicalSize = const Size(430, 950);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);

    final (_, catalog, service) = _shop();
    await tester.pumpWidget(
      MaterialApp(
        theme: buildShopTheme(),
        home: HomePage(catalog: catalog, cart: Cart(), orders: service),
      ),
    );
    await tester.pump();

    // 주문이 없어도 실시간 매장 항목이 노출된다.
    expect(find.text('실시간 매장'), findsOneWidget);
    expect(find.text('상품'), findsOneWidget);
    expect(find.text('주문 내역'), findsOneWidget);

    await tester.tap(find.text('실시간 매장'));
    await tester.pump();
    expect(tester.takeException(), isNull);

    await tester.tap(find.text('주문 내역'));
    await tester.pump();
    expect(find.text('아직 주문이 없습니다.'), findsOneWidget);
  });

  testWidgets('상품 화면이 3개 카테고리 탭으로 렌더링된다', (WidgetTester tester) async {
    tester.view.physicalSize = const Size(900, 1400);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);

    final (_, catalog, service) = _shop();
    await tester.pumpWidget(
      MaterialApp(
        theme: buildShopTheme(),
        home: ShopPage(catalog: catalog, cart: Cart(), orders: service),
      ),
    );
    await tester.pump();

    // 탭 라벨과 상품 카드의 구획 배지에 같은 문구가 쓰인다.
    expect(find.descendant(of: find.byType(TabBar), matching: find.text('상온')),
        findsOneWidget);
    expect(find.descendant(of: find.byType(TabBar), matching: find.text('냉장')),
        findsOneWidget);
    expect(find.descendant(of: find.byType(TabBar), matching: find.text('냉동')),
        findsOneWidget);
    expect(find.byIcon(Icons.add_shopping_cart), findsWidgets);
    expect(tester.takeException(), isNull);
  });
}
