import 'package:robo_core/robo_core.dart';

/// 소비자에게 보여줄 상품 한 종류.
///
/// 재고는 로트 단위로 관리되지만 소비자에게는 SKU 단위로 묶어서 보여준다.
/// 판매 가능 수량은 로트들의 가용 수량 합이고, 신선도는 가장 임박한 유통기한을
/// 기준으로 표시한다(FEFO로 그 로트가 먼저 나가기 때문).
class Product {
  Product({
    required this.sku,
    required this.name,
    required this.zone,
    required this.available,
    required this.price,
    this.nearestExpiry,
  });

  final String sku;
  final String name;
  final TempZone zone;
  final int available;
  final int price;
  final DateTime? nearestExpiry;

  bool get inStock => available > 0;

  int? daysToExpiry(DateTime now) => nearestExpiry?.difference(now).inDays;
}

/// 재고 로트를 소비자용 상품 목록으로 집계한다.
class Catalog {
  Catalog(this._inventory);

  final InventoryRepository _inventory;

  /// SKU별 가격표. 실제 운영에서는 상품 마스터에서 온다.
  static const Map<String, int> _price = <String, int>{
    'SKU-A1': 5900,
    'SKU-A2': 18900,
    'SKU-A3': 6900,
    'SKU-A4': 7900,
    'SKU-C1': 8900,
    'SKU-C2': 4500,
    'SKU-C3': 16900,
    'SKU-C4': 7200,
    'SKU-F1': 12900,
    'SKU-F2': 9900,
    'SKU-F3': 19900,
    'SKU-F4': 11500,
  };

  static int priceOf(String sku) => _price[sku] ?? 9900;

  List<Product> load({TempZone? zone, DateTime? now}) {
    final at = now ?? DateTime.now();
    final grouped = <String, List<Lot>>{};
    for (final lot in _inventory.loadAll()) {
      if (lot.isExpired(at) || lot.available <= 0) continue;
      if (zone != null && lot.zone != zone) continue;
      grouped.putIfAbsent(lot.sku, () => <Lot>[]).add(lot);
    }

    final products = grouped.entries.map((e) {
      final lots = e.value..sort((a, b) => a.expiry.compareTo(b.expiry));
      return Product(
        sku: e.key,
        name: lots.first.name,
        zone: lots.first.zone,
        available: lots.fold<int>(0, (a, l) => a + l.available),
        price: priceOf(e.key),
        nearestExpiry: lots.first.expiry,
      );
    }).toList();

    products.sort((a, b) => a.name.compareTo(b.name));
    return products;
  }
}
