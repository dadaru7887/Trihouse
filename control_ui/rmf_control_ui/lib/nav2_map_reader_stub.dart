/// 웹 빌드용 대체 구현. 브라우저에서는 배포 파일을 읽을 수 없다.
library;

import 'nav2_map_alignment.dart';

MapExtentMeters? readNav2MapExtent(String yamlPath) => null;

Map<String, ({double x, double y})> readNavGraphWaypoints(String path) =>
    const {};
