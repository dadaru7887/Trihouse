import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/main.dart';
import 'package:rmf_control_ui/trihouse/api/fms_api.dart';
import 'package:rmf_control_ui/trihouse/api/fms_models.dart';

class _InventoryApi implements FmsApi {
  @override
  Future<List<InventoryLotDto>> listInventory() async => [
    InventoryLotDto(
      lotId: 7,
      lotCode: 'LOT-0007',
      productCode: 'MILK-1L',
      itemName: 'Milk',
      temperatureZone: 'chilled',
      locationCode: 'CHILL-A-01',
      expiryDate: DateTime(2026, 8, 20),
      availableQty: 12,
      reservedQty: 3,
      state: 'available',
    ),
  ];

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

void main() {
  testWidgets('app shell renders inventory supplied by the FMS Gateway', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1280, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(RmfControlApp(api: _InventoryApi()));
    await tester.pumpAndSettle();

    expect(find.text('Trihouse Control'), findsOneWidget);
    expect(find.text('재고'), findsOneWidget);
    expect(find.text('MILK-1L'), findsOneWidget);
    expect(find.text('가용 12 · 예약 3'), findsOneWidget);
    expect(find.byIcon(Icons.refresh), findsOneWidget);
  });
}
