import 'enums.dart';

/// 재고 로트. FEFO 스케줄링의 기준 단위다.
class Lot {
  Lot({
    required this.id,
    required this.sku,
    required this.name,
    required this.zone,
    required this.locationId,
    required this.qty,
    required this.expiry,
    required this.receivedAt,
  });

  final String id;
  final String sku;
  final String name;
  final TempZone zone;

  String locationId;
  int qty;
  final DateTime expiry;
  final DateTime receivedAt;

  /// 예약 수량(중복 출고 방지).
  int reserved = 0;

  int get available => qty - reserved;

  int daysToExpiry(DateTime now) => expiry.difference(now).inDays;

  /// 유통기한 임박도 0~1. 스케줄러 가중치로 그대로 쓰인다.
  double expiryPressure(DateTime now) {
    final d = expiry.difference(now).inHours / 24.0;
    if (d <= 0) return 1.0;
    if (d >= 45) return 0.0;
    return (1.0 - d / 45.0).clamp(0.0, 1.0);
  }

  bool isExpired(DateTime now) => !expiry.isAfter(now);
}
