import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/trihouse/api/fms_api.dart';
import 'package:rmf_control_ui/trihouse/api/fms_models.dart';
import 'package:rmf_control_ui/trihouse/features/orders/order_page.dart';

class _OrderApi implements FmsApi {
  OutboundOrderRequestDto? submitted;
  String? idempotencyKey;

  @override
  Future<List<InventoryLotDto>> listInventory() async => [
    InventoryLotDto(
      lotId: 1,
      lotCode: 'LOT-CHL-MILK-001',
      productCode: 'SKU-MILK',
      itemName: 'Milk',
      temperatureZone: 'chilled',
      locationCode: 'CHL-L1-S02',
      expiryDate: DateTime(2026, 9, 20),
      availableQty: 2,
      reservedQty: 0,
      state: 'stored',
    ),
    InventoryLotDto(
      lotId: 2,
      lotCode: 'LOT-CHL-MILK-002',
      productCode: 'SKU-MILK',
      itemName: 'Milk',
      temperatureZone: 'chilled',
      locationCode: 'CHL-L2-S02',
      expiryDate: DateTime(2026, 9, 25),
      availableQty: 1,
      reservedQty: 1,
      state: 'stored',
    ),
  ];

  @override
  Future<OutboundOrderDto> createOutboundOrder(
    OutboundOrderRequestDto request, {
    required String idempotencyKey,
  }) async {
    submitted = request;
    this.idempotencyKey = idempotencyKey;
    return const OutboundOrderDto(
      jobId: 17,
      jobCode: 'OUT-17',
      externalReference: 'ORDER-17',
      state: 'queued',
      requestedQuantity: 3,
      fulfillableQuantity: 2,
      outstandingQuantity: 1,
    );
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

Widget _testOrderPage(_OrderApi api) => MaterialApp(
  home: Scaffold(
    body: OrderPage(api: api, requestedBy: 'W-OP-01'),
  ),
);

void main() {
  testWidgets('order page asks for products but not destinations or robots', (
    tester,
  ) async {
    await tester.pumpWidget(_testOrderPage(_OrderApi()));
    await tester.pumpAndSettle();

    expect(find.text('상품 추가'), findsOneWidget);
    expect(find.text('긴급'), findsOneWidget);
    expect(find.text('부분 출고 허용'), findsOneWidget);
    expect(find.byKey(const Key('product-search')), findsOneWidget);
    expect(find.textContaining('Waypoint 선택'), findsNothing);
    expect(find.textContaining('목적지'), findsNothing);
    expect(find.textContaining('로봇 선택'), findsNothing);
    expect(find.textContaining('OMX 선택'), findsNothing);
  });

  testWidgets(
    'search submit and result preserve product quantity and partial intent',
    (tester) async {
      final api = _OrderApi();
      await tester.pumpWidget(_testOrderPage(api));
      await tester.pumpAndSettle();

      await tester.enterText(find.byKey(const Key('product-search')), 'milk');
      await tester.pump();
      expect(find.text('Milk · SKU-MILK'), findsOneWidget);
      await tester.tap(find.text('상품 추가'));
      await tester.pump();
      await tester.enterText(find.byKey(const Key('quantity-1')), '3');
      await tester.tap(find.text('긴급'));
      await tester.tap(find.text('부분 출고 허용'));
      await tester.tap(find.text('주문 제출'));
      await tester.pumpAndSettle();

      expect(api.submitted, isNotNull);
      expect(api.submitted!.requester, 'W-OP-01');
      expect(api.submitted!.priority, 'critical');
      expect(api.submitted!.allowPartialFulfillment, isTrue);
      expect(api.submitted!.lines.single.productCode, 'SKU-MILK');
      expect(api.submitted!.lines.single.quantity, 3);
      expect(api.idempotencyKey, isNotEmpty);
      expect(find.text('OUT-17'), findsOneWidget);
      expect(find.text('출고 가능 2/요청 3'), findsOneWidget);
      expect(find.text('미출고 1'), findsOneWidget);
    },
  );

  testWidgets('editing quantity hides a result from the previous intent', (
    tester,
  ) async {
    final api = _OrderApi();
    await tester.pumpWidget(_testOrderPage(api));
    await tester.pumpAndSettle();

    await tester.enterText(find.byKey(const Key('product-search')), 'milk');
    await tester.pump();
    await tester.tap(find.text('상품 추가'));
    await tester.pump();
    await tester.tap(find.text('주문 제출'));
    await tester.pumpAndSettle();
    expect(find.text('OUT-17'), findsOneWidget);

    await tester.enterText(find.byKey(const Key('quantity-1')), '2');
    await tester.pump();

    expect(find.text('OUT-17'), findsNothing);
    expect(find.text('출고 가능 2/요청 3'), findsNothing);
  });

  testWidgets('editing quantity clears a validation error from the previous intent', (
    tester,
  ) async {
    final api = _OrderApi();
    await tester.pumpWidget(_testOrderPage(api));
    await tester.pumpAndSettle();

    await tester.enterText(find.byKey(const Key('product-search')), 'milk');
    await tester.pump();
    await tester.tap(find.text('상품 추가'));
    await tester.pump();
    await tester.enterText(find.byKey(const Key('quantity-1')), '');
    await tester.tap(find.text('주문 제출'));
    await tester.pump();
    expect(find.text('상품과 1 이상의 수량을 확인하세요.'), findsOneWidget);

    await tester.enterText(find.byKey(const Key('quantity-1')), '2');
    await tester.pump();

    expect(find.text('상품과 1 이상의 수량을 확인하세요.'), findsNothing);
  });
}
