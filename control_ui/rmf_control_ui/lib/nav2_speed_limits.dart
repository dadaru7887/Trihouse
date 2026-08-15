/// 벤더 Nav2 파라미터에서 속도·가속도를 뽑는다.
///
/// RMF 의 `rmf_fleet.limits` 는 이 값으로 배차 시간을 계산하는데, 실제로 로봇을
/// 움직이는 것은 Nav2 다. 둘이 어긋나면 조용히 틀어진다 — 벤더 파일이
/// `desired_linear_vel: 0.2` 인데 RMF 가 0.5 로 알고 있으면, RMF 는 예상의 2.5배가
/// 걸리는 것을 보고 멀쩡히 가는 로봇을 지연으로 판단해 경로를 다시 짠다.
///
/// 그래서 벤더 파일을 **읽기만** 한다. 로봇 등록에서 이 값을 보여 주고, 사람이
/// 그대로 쓰거나 고쳐서 RMF 쪽 한계로 넣는다. 벤더 파일은 건드리지 않는다.
///
/// YAML 파서를 들이지 않고 줄 단위로 훑는다. [rewriteNav2Params] 가 같은 이유로
/// 같은 방식을 쓴다 — 벤더 파일의 주석은 왜 그 값인지를 적어 둔 것이라 살려야
/// 하고, 필요한 것은 네 줄뿐이다.
library;

/// 벤더 파일에서 읽은 속도 한계. 못 찾은 값은 null 이다.
///
/// 없는 값을 0 으로 채우지 않는다. 0 을 넣으면 "벤더가 정지를 원한다"는 뜻이
/// 되어 버리는데, 실제로는 그저 못 찾았다는 뜻이다.
class VendorSpeedLimits {
  const VendorSpeedLimits({
    this.linearVelocity,
    this.linearAcceleration,
    this.angularVelocity,
    this.angularAcceleration,
    this.progressAllowanceSeconds,
    this.progressRadiusMeters,
  });

  /// `desired_linear_vel` — 컨트롤러가 노리는 직진 속도 [m/s].
  ///
  /// `velocity_smoother` 의 `max_velocity` 첫 항이 아니라 이것을 쓴다. 후자는
  /// 넘지 못하는 상한이고, 로봇이 실제로 내는 속도는 이쪽이다.
  final double? linearVelocity;

  /// `velocity_smoother` 의 `max_accel` 첫 항 [m/s²].
  final double? linearAcceleration;

  /// `rotate_to_heading_angular_vel` — 제자리 회전 속도 [rad/s].
  final double? angularVelocity;

  /// `max_angular_accel` [rad/s²].
  final double? angularAcceleration;

  /// `movement_time_allowance` — 끼었나 판정에 쓰는 여유 시간 [s].
  ///
  /// 속도와 함께 봐야 뜻이 생긴다. 이 시간 동안 [progressRadiusMeters] 를 못
  /// 벗어나면 Nav2 가 로봇을 끼었다고 보고 제자리 회전·후진을 시킨다.
  final double? progressAllowanceSeconds;

  /// `required_movement_radius` — 그동안 벗어나야 하는 거리 [m].
  final double? progressRadiusMeters;

  /// 하나도 못 찾았는가. 벤더 파일이 크게 바뀌면 이렇게 된다.
  bool get isEmpty =>
      linearVelocity == null &&
      linearAcceleration == null &&
      angularVelocity == null &&
      angularAcceleration == null;

  /// 네 개를 다 찾았는가.
  bool get isComplete =>
      linearVelocity != null &&
      linearAcceleration != null &&
      angularVelocity != null &&
      angularAcceleration != null;
}

/// `키: 값` 한 줄. 들여쓰기 깊이는 보지 않는다 — 찾는 이름이 벤더 파일 안에서
/// 유일해서 어느 블록에 있는지 따질 필요가 없다.
final RegExp _entry = RegExp(r'^\s*([A-Za-z_][A-Za-z_0-9]*):\s*(.*)$');

/// 주석을 걷어낸 값.
///
/// 벤더 파일은 값마다 `# [m/s] 목표 기본 직진 속도` 처럼 단위와 설명을 달아 둔다.
/// 이것을 안 떼면 `double.tryParse` 가 통째로 null 을 돌려준다.
String _bare(String raw) {
  final hash = raw.indexOf('#');
  return (hash >= 0 ? raw.substring(0, hash) : raw).trim();
}

/// `[2.5, 0.0, 3.2]` 의 첫 항. 목록이 아니면 null.
///
/// Nav2 의 속도 벡터는 `[x, y, theta]` 순서다. 차동 구동이라 y 는 늘 0 이고,
/// 직진 가속도는 첫 항이다.
double? _firstOfList(String value) {
  if (!value.startsWith('[')) return null;
  final end = value.indexOf(']');
  if (end < 0) return null;
  final items = value.substring(1, end).split(',');
  return items.isEmpty ? null : double.tryParse(items.first.trim());
}

/// 벤더 Nav2 파라미터 [yaml] 에서 속도·가속도를 뽑는다.
///
/// 같은 이름이 여러 번 나오면 **처음 것**만 쓴다. 벤더 파일에서 컨트롤러 블록이
/// 앞에 오고, 뒤에 오는 것은 복구 동작처럼 평소 주행과 상관없는 값이다.
VendorSpeedLimits parseVendorSpeedLimits(String yaml) {
  double? linearVelocity;
  double? linearAcceleration;
  double? angularVelocity;
  double? angularAcceleration;
  double? progressAllowanceSeconds;
  double? progressRadiusMeters;

  for (final line in yaml.split('\n')) {
    final match = _entry.firstMatch(line);
    if (match == null) continue;
    final value = _bare(match.group(2) ?? '');
    if (value.isEmpty) continue;
    switch (match.group(1)) {
      case 'desired_linear_vel':
        linearVelocity ??= double.tryParse(value);
      case 'max_accel':
        linearAcceleration ??= _firstOfList(value);
      case 'rotate_to_heading_angular_vel':
        angularVelocity ??= double.tryParse(value);
      case 'max_angular_accel':
        angularAcceleration ??= double.tryParse(value);
      case 'movement_time_allowance':
        progressAllowanceSeconds ??= double.tryParse(value);
      case 'required_movement_radius':
        progressRadiusMeters ??= double.tryParse(value);
    }
  }

  return VendorSpeedLimits(
    linearVelocity: linearVelocity,
    linearAcceleration: linearAcceleration,
    angularVelocity: angularVelocity,
    angularAcceleration: angularAcceleration,
    progressAllowanceSeconds: progressAllowanceSeconds,
    progressRadiusMeters: progressRadiusMeters,
  );
}
