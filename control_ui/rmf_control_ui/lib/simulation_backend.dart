/// 프로젝트를 실행할 때 사용할 물리 시뮬레이션 백엔드.
///
/// RViz는 시뮬레이터가 아니라 ROS 시각화 도구이므로 이 값과 별도로 켜고 끈다.
enum SimulationBackend {
  gazebo,
  isaacSim,
  none;

  String get storageValue => switch (this) {
    SimulationBackend.gazebo => 'gazebo',
    SimulationBackend.isaacSim => 'isaac_sim',
    SimulationBackend.none => 'none',
  };

  String get label => switch (this) {
    SimulationBackend.gazebo => 'Gazebo',
    SimulationBackend.isaacSim => 'Isaac Sim',
    SimulationBackend.none => '시뮬레이터 없음',
  };

  static SimulationBackend parse(String? value) => switch (value) {
    'isaac_sim' => SimulationBackend.isaacSim,
    'none' => SimulationBackend.none,
    _ => SimulationBackend.gazebo,
  };
}

class ProjectSimulationSettings {
  const ProjectSimulationSettings({
    this.backend = SimulationBackend.gazebo,
    this.simulatorGui = false,
    this.rviz = false,
    this.gazeboSettings = const {},
    this.isaacSettings = const {},
    this.coordinateTransform = const {
      'metersPerUnit': 1.0,
      'rmfOriginX': 0.0,
      'rmfOriginY': 0.0,
      'stageOriginX': 0.0,
      'stageOriginY': 0.0,
      'yawOffsetRad': 0.0,
      'invertY': false,
    },
  });

  final SimulationBackend backend;
  final bool simulatorGui;
  final bool rviz;
  final Map<String, Object?> gazeboSettings;
  final Map<String, Object?> isaacSettings;
  final Map<String, Object?> coordinateTransform;
}
