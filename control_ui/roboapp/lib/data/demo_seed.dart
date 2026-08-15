import 'package:robo_core/robo_core.dart';

/// 웹 데모용 기초 재고.
///
/// 네이티브 빌드는 관제센터 원장을 그대로 읽으므로 이 함수를 쓰지 않는다.
void seedDemoCatalog(DataStore store) {
  final now = DateTime.now();
  var n = 0;

  void lot(String sku, String name, TempZone zone, int qty, int days) {
    store.inventory.insertLot(
      Lot(
        id: 'LOT-D${(++n).toString().padLeft(3, '0')}',
        sku: sku,
        name: name,
        zone: zone,
        locationId: '${zone.code}-01-${n.toString().padLeft(2, '0')}',
        qty: qty,
        expiry: now.add(Duration(days: days)),
        receivedAt: now.subtract(const Duration(days: 1)),
      ),
      reason: StockMoveReason.initial,
    );
  }

  lot('SKU-A1', '생수 2L 6입', TempZone.ambient, 48, 240);
  lot('SKU-A2', '즉석밥 24입', TempZone.ambient, 30, 180);
  lot('SKU-A3', '라면 멀티팩', TempZone.ambient, 42, 150);
  lot('SKU-A4', '식용유 1.8L', TempZone.ambient, 25, 300);

  lot('SKU-C1', '우유 1L 6입', TempZone.chilled, 36, 9);
  lot('SKU-C2', '샐러드 팩', TempZone.chilled, 22, 3);
  lot('SKU-C3', '숙성 삼겹살', TempZone.chilled, 18, 5);
  lot('SKU-C4', '요구르트 12입', TempZone.chilled, 40, 14);

  lot('SKU-F1', '냉동만두 1.4kg', TempZone.frozen, 33, 210);
  lot('SKU-F2', '아이스크림 벌크', TempZone.frozen, 27, 300);
  lot('SKU-F3', '냉동새우 1kg', TempZone.frozen, 15, 260);
  lot('SKU-F4', '냉동피자 3입', TempZone.frozen, 21, 190);
}
