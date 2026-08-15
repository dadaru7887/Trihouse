/// 그리드맵 화면에서 고치는 값들. 저장할 것이 남았는지 여기서 가린다.
///
/// 이 값들은 프로젝트에 저장되지만(`gridResolution`·`useSlamMap`), 그리드맵
/// 화면에는 **저장하는 자리가 없었다.** 고쳐 놓고 다른 화면으로 옮겨 가
/// `프로젝트 저장` 을 눌러야 남았다. 그것을 모르면 격자 크기를 맞춰 놓고
/// 프로젝트를 다시 열었을 때 옛 값으로 돌아가 있다 — 그러고도 아무 말이 없다.
///
/// 화면 코드에서 떼어 둔다. 무엇이 바뀌었는지 가리는 일은 위젯 없이 시험할 수
/// 있어야 한다.
library;

/// 그리드맵 화면이 건드리는 값 한 벌.
class GridMapSettings {
  const GridMapSettings({
    required this.mode,
    required this.targetWidth,
    required this.targetHeight,
    required this.padToTarget,
    required this.manualResolution,
    required this.useSlamMap,
  });

  /// 격자 크기를 정하는 방법. `target` 이면 픽셀 수, `manual` 이면 한 칸 크기.
  final String mode;

  final int targetWidth;
  final int targetHeight;

  /// 도면이 목표 크기보다 작을 때 여백을 채울지.
  final bool padToTarget;

  /// 격자 한 칸 [m]. `manual` 일 때만 쓴다.
  final double manualResolution;

  /// Nav2 가 도면 대신 SLAM 지도를 띄울지.
  final bool useSlamMap;

  @override
  bool operator ==(Object other) =>
      other is GridMapSettings &&
      other.mode == mode &&
      other.targetWidth == targetWidth &&
      other.targetHeight == targetHeight &&
      other.padToTarget == padToTarget &&
      // 실수는 그대로 견주지 않는다. 0.02 를 다시 읽어 0.019999… 가 되면
      // 아무도 안 고쳤는데 고쳤다고 나온다.
      (other.manualResolution - manualResolution).abs() < 1e-9 &&
      other.useSlamMap == useSlamMap;

  @override
  int get hashCode => Object.hash(
    mode,
    targetWidth,
    targetHeight,
    padToTarget,
    // 견줄 때와 같은 자리에서 끊는다.
    (manualResolution * 1e9).round(),
    useSlamMap,
  );
}

/// 사람이 읽을 이름.
String _modeLabel(String mode) => switch (mode) {
  'target' => '목표 크기',
  'manual' => '직접 지정',
  _ => mode,
};

/// [saved] 에서 [current] 로 무엇이 바뀌었는지.
///
/// 바뀐 것이 없으면 빈 목록이다. "저장할 것이 있다" 를 이 목록이 비었는지로
/// 가린다 — 따로 깃발을 두면 둘이 어긋난다.
///
/// 무엇이 바뀌었는지까지 적는 이유는, 저장 단추만 켜 두면 무엇을 저장하는지
/// 모르는 채로 누르게 되기 때문이다.
List<String> gridSettingChanges({
  required GridMapSettings saved,
  required GridMapSettings current,
}) {
  final changes = <String>[];
  if (saved.mode != current.mode) {
    changes.add(
      '격자 크기 방식 ${_modeLabel(saved.mode)} → ${_modeLabel(current.mode)}',
    );
  }
  // 크기는 둘을 한 줄로 묶는다. 가로만 고쳐도 사람은 크기를 고쳤다고 여긴다.
  if (saved.targetWidth != current.targetWidth ||
      saved.targetHeight != current.targetHeight) {
    changes.add(
      '목표 크기 ${saved.targetWidth}×${saved.targetHeight} → '
      '${current.targetWidth}×${current.targetHeight}',
    );
  }
  if (saved.padToTarget != current.padToTarget) {
    changes.add(current.padToTarget ? '여백 채우기 켬' : '여백 채우기 끔');
  }
  if ((saved.manualResolution - current.manualResolution).abs() >= 1e-9) {
    changes.add(
      '한 칸 크기 ${saved.manualResolution.toStringAsFixed(3)}m → '
      '${current.manualResolution.toStringAsFixed(3)}m',
    );
  }
  if (saved.useSlamMap != current.useSlamMap) {
    changes.add(current.useSlamMap ? 'Nav2 가 SLAM 지도 사용' : 'Nav2 가 도면 사용');
  }
  return changes;
}
