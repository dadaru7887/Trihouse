import 'deployed_map_models.dart';

Future<List<DeployedMapSummary>> listDeployedMaps() async => const [];

Future<DeployedMapData> loadDeployedMap(DeployedMapSummary summary) =>
    Future.error('배포 맵 불러오기는 Linux 데스크톱 앱에서 지원됩니다.');
