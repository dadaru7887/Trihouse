/// Gazebo 월드에서 벽을 얼마나 높게 세울지.
///
/// 도면은 위에서 내려다본 그림이라 **높이가 없다.** 그래서 길이는
/// Measurement 로 재지만 높이는 잴 데가 없고, 사람이 따로 넣어야 한다.
///
/// 넣지 않으면 traffic_editor 의 기본값인 2.5m 로 선다
/// (`rmf_building_map_tools` 의 `building_map/wall.py`, `wall_height = 2.5`).
/// 실험실 책상 위의 0.3m 세트를 그대로 두면 무릎 높이 칸막이가 건물 벽처럼
/// 서서, 시뮬레이터 그림이 실제와 딴판이 된다.
///
/// **높이는 그림 문제만이 아니다.** 벽이 로봇 라이다보다 낮으면 라이다가 벽을
/// 넘겨다본다. 그러면 Gazebo 에서는 아무것도 안 맞히는데 지도(점유격자)에는
/// 벽이 있으므로, AMCL 이 맞출 것을 못 찾아 위치를 잃는다. 그 증상은 "로봇이
/// 제자리에서 헤맨다" 로 나타나 원인에서 멀다. 그래서 낮은 값에는 경고를 준다.
library;

/// 안 넣으면 이 높이로 선다. traffic_editor 의 `wall_height` 와 같은 값이다.
const double defaultWallHeight = 2.5;

/// 핑키의 라이다가 바닥에서 얼마나 높이 있나(m).
///
/// `robo_pinky_description/urdf/pinky.urdf.xacro` 를 따라간 값이다 —
/// 바퀴 반지름 0.030 + lidar_mount 0.052 + laser_link 0.020 = 0.102m.
/// 로봇이 바뀌면 이 값도 바뀐다. 벽이 이보다 낮으면 라이다가 벽 위를 지나간다.
const double laserHeightPinky = .102;

/// 이보다 낮은 벽은 세울 수 없다. 라이다 아래로 완전히 내려가 아무 뜻이 없다.
const double minWallHeight = .05;

/// 이보다 높은 값은 받지 않는다. 손이 미끄러져 0 을 하나 더 친 것에 가깝다.
const double maxWallHeight = 10;

/// 넣은 값이 벽 높이로 쓸 수 있나. 쓸 수 있으면 null, 아니면 까닭.
String? wallHeightError(double? meters) {
  if (meters == null) return '숫자로 입력하세요.';
  if (meters.isNaN || meters.isInfinite) return '숫자로 입력하세요.';
  if (meters <= 0) return '0보다 큰 높이를 입력하세요.';
  if (meters < minWallHeight) {
    return '${minWallHeight.toStringAsFixed(2)}m 보다 낮은 벽은 세울 수 없습니다.';
  }
  if (meters > maxWallHeight) {
    return '${maxWallHeight.toStringAsFixed(0)}m 보다 높은 벽은 받지 않습니다.';
  }
  return null;
}

/// 받을 수는 있지만 알려 줘야 하는 값인가. 문제없으면 null.
///
/// 막지는 않는다. 라이다 높이는 로봇마다 다르고, 사람이 제 로봇을 안다.
String? wallHeightWarning(
  double meters, {
  double laserHeight = laserHeightPinky,
}) {
  if (meters >= laserHeight) return null;
  return '벽이 ${meters.toStringAsFixed(2)}m 로 로봇 라이다(바닥에서 '
      '${laserHeight.toStringAsFixed(3)}m)보다 낮습니다.\n\n'
      '라이다가 벽을 넘겨다보므로 Gazebo 에서는 아무것도 맞히지 못하는데 '
      '지도에는 벽이 있습니다. AMCL 이 맞출 것을 못 찾아 위치를 잃고, '
      '로봇이 제자리에서 헤맵니다.';
}

/// 도면에서 만든 격자(점유격자)는 이 높이와 상관없다.
///
/// 격자는 2D 라 벽이 있냐 없냐만 담는다. 높이를 낮춰도 격자는 그대로이고,
/// 그래서 위의 경고가 성립한다 — 지도에는 벽이 남고 라이다만 못 본다.
const String wallHeightGridNote =
    '점유격자(Nav2 지도)는 2D 라 이 값과 상관없습니다. 벽 높이는 Gazebo 월드의 '
    '벽 모델에만 들어갑니다.';
