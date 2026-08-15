import 'package:flutter/material.dart';

import 'package:robo_core/models/enums.dart';

/// 관제 화면의 단일 라이트 팔레트.
///
/// 계열색(series)은 개체 식별용, 상태색(status)은 상태 전용으로 분리해
/// 사용한다. 상태색은 항상 라벨/아이콘과 함께 표기하며 색만으로 의미를
/// 전달하지 않는다.
///
/// 라이트 서피스(#fcfcfb)에서 계열색 중 aqua·yellow·magenta와 상태색
/// warning·serious는 3:1 대비에 미치지 못한다. 이 팔레트는 그 경우를
/// 라벨/아이콘 동반 표기(구제 규칙)로 보완하는 것을 전제로 한다 —
/// 어떤 색도 단독으로 의미를 전달하지 않는다.
class AppColors {
  const AppColors._();

  /// 페이지 평면 — 패널보다 한 단계 어두워 카드 경계가 드러난다.
  static const Color page = Color(0xFFF1F0EC);

  /// 패널(차트) 서피스.
  static const Color surface = Color(0xFFFCFCFB);

  /// 툴팁·대화상자처럼 한 단계 떠 있는 면.
  static const Color surfaceRaised = Color(0xFFFFFFFF);

  static const Color textPrimary = Color(0xFF0B0B0B);
  static const Color textSecondary = Color(0xFF52514E);
  static const Color muted = Color(0xFF898781);
  static const Color grid = Color(0xFFE1E0D9);
  static const Color baseline = Color(0xFFC3C2B7);

  // 계열색(라이트 서피스 기준 스텝).
  static const Color series1 = Color(0xFF2A78D6); // blue
  static const Color series2 = Color(0xFFEB6834); // orange
  static const Color series3 = Color(0xFF1BAF7A); // aqua
  static const Color series4 = Color(0xFFEDA100); // yellow
  static const Color series5 = Color(0xFFE87BA4); // magenta
  static const Color series6 = Color(0xFF008300); // green
  static const Color series7 = Color(0xFF4A3AA7); // violet
  static const Color series8 = Color(0xFFE34948); // red

  // 상태색(모드 불변).
  static const Color good = Color(0xFF0CA30C);
  static const Color warning = Color(0xFFFAB219);
  static const Color serious = Color(0xFFEC835A);
  static const Color critical = Color(0xFFD03B3B);

  /// 계열색·상태색을 라이트 배경 위 '글자'로 쓸 때의 대비 보정.
  ///
  /// 채도가 높은 원색은 흰 배경에서 3:1을 밑돌아 잘 읽히지 않는다.
  /// 칩·라벨의 텍스트에는 이 어두운 변형을 쓰고, 마커·막대 등 면적이 있는
  /// 요소에는 원색을 그대로 쓴다.
  static Color ink(Color c) =>
      Color.alphaBlend(c.withValues(alpha: 0.68), const Color(0xFF1A1A19));

  static Color get border => Colors.black.withValues(alpha: 0.12);

  static Color severityColor(Severity s) => ink(switch (s) {
    Severity.info => series1,
    Severity.warning => warning,
    Severity.serious => serious,
    Severity.critical => critical,
  });

  static IconData severityIcon(Severity s) => switch (s) {
    Severity.info => Icons.info_outline,
    Severity.warning => Icons.warning_amber_outlined,
    Severity.serious => Icons.report_problem_outlined,
    Severity.critical => Icons.dangerous_outlined,
  };

  static Color robotStateColor(RobotState s) => ink(switch (s) {
    RobotState.moving ||
    RobotState.picking ||
    RobotState.placing ||
    RobotState.handover ||
    RobotState.loading => series1,
    RobotState.charging || RobotState.returning => series7,
    RobotState.powerSaving => warning,
    RobotState.blocked || RobotState.yielding => serious,
    RobotState.error || RobotState.estop => critical,
    RobotState.idle => muted,
    RobotState.standby => Color(0xFF9A9891),
  });

  static IconData robotStateIcon(RobotState s) => switch (s) {
    RobotState.moving => Icons.navigation_outlined,
    RobotState.picking => Icons.download_outlined,
    RobotState.placing => Icons.upload_outlined,
    RobotState.handover => Icons.volunteer_activism_outlined,
    RobotState.loading => Icons.precision_manufacturing_outlined,
    RobotState.charging => Icons.bolt_outlined,
    RobotState.returning => Icons.u_turn_left_outlined,
    RobotState.powerSaving => Icons.energy_savings_leaf_outlined,
    RobotState.blocked => Icons.block_outlined,
    RobotState.yielding => Icons.slow_motion_video_outlined,
    RobotState.error => Icons.error_outline,
    RobotState.estop => Icons.pan_tool_outlined,
    RobotState.idle => Icons.pause_circle_outline,
    RobotState.standby => Icons.nightlight_outlined,
  };

  static Color batteryColor(double pct) {
    if (pct <= 10) return ink(critical);
    if (pct <= 20) return ink(warning);
    if (pct <= 45) return ink(serious);
    return ink(good);
  }

  static Color urgencyColor(Urgency u) => ink(switch (u) {
    Urgency.critical => critical,
    Urgency.high => serious,
    Urgency.normal => series1,
    Urgency.low => muted,
  });

  static Color taskStateColor(TaskState s) => ink(switch (s) {
    TaskState.pending => muted,
    TaskState.claimed => series7,
    TaskState.inProgress => series1,
    TaskState.blocked => serious,
    TaskState.done => good,
    TaskState.failed => critical,
    TaskState.cancelled => baseline,
  });

  static Color zoneColor(TempZone z) => ink(switch (z) {
    TempZone.ambient => series4,
    TempZone.chilled => series1,
    TempZone.frozen => series7,
  });

  /// 지도의 면적 채색용 원색(텍스트 대비 보정을 하지 않은 값).
  static Color zoneFill(TempZone z) => switch (z) {
    TempZone.ambient => series4,
    TempZone.chilled => series1,
    TempZone.frozen => series7,
  };
}

ThemeData buildControlRoomTheme() {
  const scheme = ColorScheme.light(
    primary: AppColors.series1,
    surface: AppColors.surface,
    onSurface: AppColors.textPrimary,
    error: AppColors.critical,
  );

  return ThemeData(
    useMaterial3: true,
    colorScheme: scheme,
    scaffoldBackgroundColor: AppColors.page,
    fontFamily: null,
    textTheme: const TextTheme(
      titleLarge: TextStyle(
        color: AppColors.textPrimary,
        fontSize: 18,
        fontWeight: FontWeight.w600,
      ),
      titleMedium: TextStyle(
        color: AppColors.textPrimary,
        fontSize: 14,
        fontWeight: FontWeight.w600,
      ),
      bodyMedium: TextStyle(color: AppColors.textSecondary, fontSize: 13),
      bodySmall: TextStyle(color: AppColors.muted, fontSize: 12),
      labelSmall: TextStyle(
        color: AppColors.muted,
        fontSize: 11,
        letterSpacing: 0.4,
      ),
    ),
    dividerColor: AppColors.grid,
    tooltipTheme: TooltipThemeData(
      decoration: BoxDecoration(
        color: AppColors.surfaceRaised,
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: AppColors.border),
      ),
      textStyle: const TextStyle(color: AppColors.textPrimary, fontSize: 12),
    ),
  );
}
