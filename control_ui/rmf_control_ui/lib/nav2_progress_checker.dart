/// Nav2 의 "끼었나" 판정을 로봇 속도에 맞춘다.
///
/// `SimpleProgressChecker` 는 [movement_time_allowance] 초 동안
/// [required_movement_radius] 미터를 못 벗어나면 로봇이 끼었다고 보고 복구
/// 동작(제자리 회전·후진)을 돌린다. 벤더 기본값은 10초에 0.5m 다 — **0.05m/s
/// 이상으로 달리는 로봇**을 전제한 값이다.
///
/// 속도만 낮추고 이 값을 그대로 두면 **정상 주행이 실패로 판정된다.** 실제로
/// 직진 속도를 0.02m/s 로 내렸더니 10초에 0.2m 밖에 못 가는데 0.5m 를 요구받아,
/// 로그가 `Failed to make progress` 로 도배되고 로봇은 목적지로 가다 말고
/// 되돌아오기를 되풀이했다. 픽업 지점에 영영 닿지 못했다.
///
/// 그 위에 복구 회전은 바퀴만 돌리고 몸은 안 움직이므로 odom 에 헛회전이 쌓인다.
/// AMCL 이 그만큼 되돌리느라 `map→odom` 이 46도까지 틀어졌고, 화면마다 로봇
/// 위치가 달라 보였다.
library;

/// 여유 시간 동안 낼 수 있는 거리의 몇 할을 요구할지.
///
/// 1.0 을 요구하면 안 된다. 로봇은 늘 최고 속도로 달리지 않는다 — 방향을 틀 때
/// 멈추고, 장애물 옆에서 늦추고, 목적지 가까이서 줄인다. 그 모두가 정상인데
/// 끼었다고 판정되면 안 된다.
const double progressCheckerDutyRatio = .3;

/// 요구 거리의 바닥 [m].
///
/// 더 작게 잡으면 진짜로 끼었을 때도 안 걸린다. AMCL 이 떠는 폭이 몇 cm 라
/// 그 안에서는 움직임과 흔들림을 못 가른다. 코스트맵 한 칸이 0.05m 다.
const double minProgressRadius = .05;

/// 이 속도에 맞는 요구 거리 [m].
///
/// [vendorRadius] 보다 크게 잡지 않는다. 벤더가 그 값을 고른 이유가 있고,
/// 속도를 올렸다고 판정을 더 깐깐하게 만들 까닭은 없다.
double progressCheckerRadius({
  required double linearVelocity,
  required double allowanceSeconds,
  required double vendorRadius,
}) {
  if (linearVelocity <= 0 || allowanceSeconds <= 0) return vendorRadius;
  final reachable =
      linearVelocity * allowanceSeconds * progressCheckerDutyRatio;
  if (reachable >= vendorRadius) return vendorRadius;
  return reachable < minProgressRadius ? minProgressRadius : reachable;
}

/// 이 속도로는 판정을 못 벗어난다면 그 사실. 문제없으면 null.
///
/// 요구 거리에는 바닥이 있어서 속도를 한없이 낮추면 결국 걸린다. 그때는 값을
/// 맞춰 주는 것으로 해결되지 않으므로 사람에게 알린다 — 조용히 두면 로봇이
/// 제자리를 맴도는 것을 보고 원인을 딴 데서 찾는다.
String? progressCheckerWarning({
  required double linearVelocity,
  required double allowanceSeconds,
  required double vendorRadius,
}) {
  if (linearVelocity <= 0 || allowanceSeconds <= 0) return null;
  final radius = progressCheckerRadius(
    linearVelocity: linearVelocity,
    allowanceSeconds: allowanceSeconds,
    vendorRadius: vendorRadius,
  );
  final reachable = linearVelocity * allowanceSeconds;
  // 바닥에 걸린 요구 거리조차 못 가면, 정상 주행이 늘 실패로 판정된다.
  if (reachable > radius) return null;
  return '직진 속도 ${linearVelocity.toStringAsFixed(3)}m/s 로는 '
      '${allowanceSeconds.toStringAsFixed(0)}초에 '
      '${reachable.toStringAsFixed(2)}m 밖에 못 갑니다.\n'
      'Nav2 는 그 시간에 ${radius.toStringAsFixed(2)}m 를 못 벗어나면 끼었다고 '
      '보고 제자리 회전·후진을 시킵니다. 정상 주행이 계속 실패로 판정되어 '
      '목적지에 닿지 못합니다.\n'
      '${(radius / (allowanceSeconds * progressCheckerDutyRatio)).toStringAsFixed(3)}m/s '
      '이상을 넣으세요.';
}
