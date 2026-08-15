import 'package:flutter/foundation.dart';

import 'catalog.dart';

/// 장바구니 한 줄.
class CartItem {
  CartItem({required this.product, required this.qty});

  final Product product;
  int qty;

  int get subtotal => product.price * qty;
}

/// 장바구니. 재고 가용 수량을 넘겨 담을 수 없다.
class Cart extends ChangeNotifier {
  final List<CartItem> items = <CartItem>[];

  int get totalQty => items.fold(0, (a, i) => a + i.qty);

  int get totalPrice => items.fold(0, (a, i) => a + i.subtotal);

  bool get isEmpty => items.isEmpty;

  int qtyOf(String sku) => items
      .where((i) => i.product.sku == sku)
      .fold(0, (a, i) => a + i.qty);

  void add(Product product, {int qty = 1}) {
    final existing = items.cast<CartItem?>().firstWhere(
      (i) => i?.product.sku == product.sku,
      orElse: () => null,
    );
    final next = (existing?.qty ?? 0) + qty;
    if (next > product.available) return;
    if (existing == null) {
      items.add(CartItem(product: product, qty: qty));
    } else {
      existing.qty = next;
    }
    notifyListeners();
  }

  void setQty(String sku, int qty) {
    final item = items.cast<CartItem?>().firstWhere(
      (i) => i?.product.sku == sku,
      orElse: () => null,
    );
    if (item == null) return;
    if (qty <= 0) {
      items.remove(item);
    } else {
      item.qty = qty.clamp(1, item.product.available);
    }
    notifyListeners();
  }

  void remove(String sku) {
    items.removeWhere((i) => i.product.sku == sku);
    notifyListeners();
  }

  void clear() {
    items.clear();
    notifyListeners();
  }
}
