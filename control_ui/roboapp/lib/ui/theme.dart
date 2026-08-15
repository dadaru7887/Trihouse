import 'package:flutter/material.dart';
import 'package:robo_core/robo_core.dart';

/// 소비자 앱 팔레트. 관제센터와 같은 계열이되, 상품 카테고리를 색으로 구분한다.
class ShopColors {
  const ShopColors._();

  static const Color page = Color(0xFFF7F6F3);
  static const Color surface = Color(0xFFFFFFFF);
  static const Color ink = Color(0xFF14140F);
  static const Color inkSoft = Color(0xFF5C5B55);
  static const Color muted = Color(0xFF908E86);
  static const Color line = Color(0xFFE4E2DA);
  static const Color brand = Color(0xFF2A78D6);

  static const Color good = Color(0xFF0CA30C);
  static const Color warning = Color(0xFFB8860B);
  static const Color critical = Color(0xFFC0392B);

  /// 3온도 카테고리 색.
  static Color zone(TempZone z) => switch (z) {
    TempZone.ambient => const Color(0xFF9A6B00),
    TempZone.chilled => const Color(0xFF1B6FC4),
    TempZone.frozen => const Color(0xFF4A3AA7),
  };

  static IconData zoneIcon(TempZone z) => switch (z) {
    TempZone.ambient => Icons.inventory_2_outlined,
    TempZone.chilled => Icons.kitchen_outlined,
    TempZone.frozen => Icons.ac_unit,
  };
}

ThemeData buildShopTheme() => ThemeData(
  useMaterial3: true,
  colorScheme: const ColorScheme.light(
    primary: ShopColors.brand,
    surface: ShopColors.surface,
    onSurface: ShopColors.ink,
  ),
  scaffoldBackgroundColor: ShopColors.page,
  appBarTheme: const AppBarTheme(
    backgroundColor: ShopColors.surface,
    surfaceTintColor: Colors.transparent,
    foregroundColor: ShopColors.ink,
    elevation: 0,
    centerTitle: false,
  ),
  dividerColor: ShopColors.line,
);

String won(int v) {
  final s = v.toString();
  final buf = StringBuffer();
  for (var i = 0; i < s.length; i++) {
    if (i > 0 && (s.length - i) % 3 == 0) buf.write(',');
    buf.write(s[i]);
  }
  return '$buf원';
}
