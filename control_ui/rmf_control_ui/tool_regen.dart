import 'dart:io';
import 'package:rmf_control_ui/rmf_project_config.dart';
void main() {
  const d = '/home/gyi/robosapiens/rmf_maps/gwanghee';
  const robots = [
    RmfProjectRobot(robotId:'PK-01', displayName:'핑키 1호', model:'PINKY-GZ',
      dataSource: RobotDataSource.gazebo, gzName:'pinky_01',
      zones:['ambient','chilled','frozen'], chargerWaypoint:'충전1',
      spawnX:1.6418717082129357, spawnY:1.5951569811762285),
    RmfProjectRobot(robotId:'OMX-01', displayName:'매니퓰레이터 1호',
      model:'open_manipulator_x', kind: RmfRobotKind.workcell,
      dataSource: RobotDataSource.gazebo, gzName:'omx_01', zones:[],
      chargerWaypoint:'OMX1', spawnX:0.36845049765743737, spawnY:1.530985280792512),
    RmfProjectRobot(robotId:'OMX-02', displayName:'매니퓰레이터 2호',
      model:'open_manipulator_x', kind: RmfRobotKind.workcell,
      dataSource: RobotDataSource.gazebo, gzName:'omx_02', zones:[],
      chargerWaypoint:'OMX2', spawnX:0.37248417942236944, spawnY:0.5664639262891022),
  ];
  File('$d/gwanghee_bringup.launch.xml').writeAsStringSync(
    buildProjectBringupXml(mapName:'gwanghee', robots: robots, mapDirectory: d));
  File('$d/run_gwanghee.sh').writeAsStringSync(
    buildProjectRunScript(mapName:'gwanghee', mapDirectory: d, robots: robots));
}
