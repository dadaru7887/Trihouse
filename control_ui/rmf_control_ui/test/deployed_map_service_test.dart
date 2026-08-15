import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/deployed_map_service.dart';

void main() {
  test('프로젝트의 배포 맵 목록과 robosapiens 도면을 불러온다', () async {
    final maps = await listDeployedMaps();
    expect(maps, isNotEmpty);

    final summary = maps.firstWhere((map) => map.name == 'robosapiens');
    final loaded = await loadDeployedMap(summary);

    expect(loaded.imageName, 'robosapiens.png');
    expect(loaded.imageBytes, isNotEmpty);
    expect(loaded.imageSize.width, greaterThan(0));
    expect(loaded.imageSize.height, greaterThan(0));
    expect(loaded.lanes, isNotEmpty);
    expect(loaded.waypoints, isNotEmpty);
  });
}
