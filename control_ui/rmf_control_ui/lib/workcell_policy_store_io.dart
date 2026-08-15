import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:archive/archive.dart';

import 'workcell_policy.dart';

String _safe(String value) => value.replaceAll(RegExp(r'[^A-Za-z0-9_-]'), '_');
Directory _workspaceRoot() {
  final configured = Platform.environment['RMF_ROOT'];
  if (configured != null && configured.isNotEmpty) {
    final directory = Directory(configured).absolute;
    if (Directory('${directory.path}/rmf_maps').existsSync()) return directory;
  }
  var directory = Directory.current.absolute;
  for (var i = 0; i < 8; i++) {
    if (Directory('${directory.path}/rmf_maps').existsSync()) return directory;
    if (directory.parent.path == directory.path) break;
    directory = directory.parent;
  }
  throw StateError('rmf_maps 디렉터리를 찾을 수 없습니다.');
}

Directory _libraryRoot() =>
    Directory('${_workspaceRoot().path}/workcell_policies');

File _bindingsFile(String project) => File(
  '${_workspaceRoot().path}/rmf_maps/${_safe(project)}/policy_bindings.json',
);

Directory _legacyRoot(String project) =>
    Directory('${_workspaceRoot().path}/rmf_maps/${_safe(project)}/policies');

Future<List<WorkcellPolicy>> loadGlobalWorkcellPolicies() async {
  final index = File('${_libraryRoot().path}/index.json');
  if (!await index.exists()) return [];
  final decoded = jsonDecode(await index.readAsString()) as List<dynamic>;
  return [
    for (final item in decoded)
      WorkcellPolicy.fromJson(Map<String, dynamic>.from(item as Map)),
  ];
}

Future<void> _writeGlobalIndex(List<WorkcellPolicy> policies) async {
  final root = _libraryRoot();
  await root.create(recursive: true);
  await File('${root.path}/index.json').writeAsString(
    const JsonEncoder.withIndent(
      '  ',
    ).convert([for (final policy in policies) policy.toJson()]),
    flush: true,
  );
}

Future<void> _migrateLegacyPolicies(String projectName) async {
  final bindings = _bindingsFile(projectName);
  if (await bindings.exists()) return;
  final legacyIndex = File('${_legacyRoot(projectName).path}/index.json');
  if (!await legacyIndex.exists()) return;
  final decoded = jsonDecode(await legacyIndex.readAsString()) as List<dynamic>;
  final policies = [
    for (final item in decoded)
      WorkcellPolicy.fromJson(Map<String, dynamic>.from(item as Map)),
  ];
  final globals = await loadGlobalWorkcellPolicies();
  for (final policy in policies) {
    final source = File(
      '${_legacyRoot(projectName).path}/${_safe(policy.name)}/${_safe(policy.version)}/policy.zip',
    );
    if (!globals.any((item) => item.id == policy.id) && await source.exists()) {
      final global = policy.copyWith(
        deployedWorkcells: const [],
        objectType: '',
      );
      final target = Directory(
        '${_libraryRoot().path}/${_safe(policy.name)}/${_safe(policy.version)}',
      );
      await target.create(recursive: true);
      await source.copy('${target.path}/policy.zip');
      await File(
        '${target.path}/manifest.json',
      ).writeAsString(global.globalManifest(), flush: true);
      globals.add(global);
    }
  }
  await _writeGlobalIndex(globals);
  await _writeBindings(projectName, policies);
}

Future<List<WorkcellPolicy>> loadWorkcellPolicies(String projectName) async {
  await _migrateLegacyPolicies(projectName);
  final file = _bindingsFile(projectName);
  if (!await file.exists()) return [];
  final globals = await loadGlobalWorkcellPolicies();
  final byId = {for (final policy in globals) policy.id: policy};
  final decoded = jsonDecode(await file.readAsString()) as List<dynamic>;
  return [
    for (final raw in decoded)
      if (byId[(raw as Map)['policyId']] case final global?)
        global.copyWith(
          objectType: raw['objectType']?.toString() ?? '',
          deployedWorkcells: [
            for (final value
                in raw['deployedWorkcells'] as List<dynamic>? ?? const [])
              value.toString(),
          ],
        ),
  ];
}

Future<void> _writeBindings(
  String projectName,
  List<WorkcellPolicy> policies,
) async {
  final file = _bindingsFile(projectName);
  await file.parent.create(recursive: true);
  await file.writeAsString(
    const JsonEncoder.withIndent('  ').convert([
      for (final policy in policies)
        {
          'policyId': policy.id,
          'objectType': policy.objectType,
          'deployedWorkcells': policy.deployedWorkcells,
        },
    ]),
    flush: true,
  );
}

Future<void> saveWorkcellPolicy(
  String projectName,
  WorkcellPolicy policy,
  Uint8List archive,
) async {
  final globals = await loadGlobalWorkcellPolicies();
  final existing = globals.where((item) => item.id == policy.id).firstOrNull;
  final versionDir = Directory(
    '${_libraryRoot().path}/${_safe(policy.name)}/${_safe(policy.version)}',
  );
  if (existing == null) {
    final global = policy.copyWith(deployedWorkcells: const [], objectType: '');
    await versionDir.create(recursive: true);
    await File(
      '${versionDir.path}/policy.zip',
    ).writeAsBytes(archive, flush: true);
    await File(
      '${versionDir.path}/manifest.json',
    ).writeAsString(global.globalManifest(), flush: true);
    globals.add(global);
    await _writeGlobalIndex(globals);
  } else if (existing.sourceRevision != policy.sourceRevision ||
      existing.archiveBytes != policy.archiveBytes) {
    throw StateError('같은 이름과 버전의 Policy가 전역 보관함에 이미 있습니다.');
  }
  await bindWorkcellPolicy(projectName, policy);
}

Future<void> bindWorkcellPolicy(
  String projectName,
  WorkcellPolicy policy,
) async {
  final globals = await loadGlobalWorkcellPolicies();
  if (!globals.any((item) => item.id == policy.id)) {
    throw StateError('전역 보관함에서 ${policy.id}을 찾을 수 없습니다.');
  }
  final policies = await loadWorkcellPolicies(projectName)
    ..removeWhere((item) => item.id == policy.id)
    ..add(policy);
  await _writeBindings(projectName, policies);
}

Future<void> deleteWorkcellPolicy(
  String projectName,
  WorkcellPolicy policy,
) async {
  final policies = await loadWorkcellPolicies(projectName)
    ..removeWhere((item) => item.id == policy.id);
  await _writeBindings(projectName, policies);
}

Future<List<String>> globalPolicyReferences(String policyId) async {
  final maps = Directory('${_workspaceRoot().path}/rmf_maps');
  if (!await maps.exists()) return [];
  final result = <String>[];
  await for (final entity in maps.list()) {
    if (entity is! Directory || entity.path.split('/').last.startsWith('.')) {
      continue;
    }
    final file = File('${entity.path}/policy_bindings.json');
    if (!await file.exists()) continue;
    final bindings = jsonDecode(await file.readAsString()) as List<dynamic>;
    if (bindings.any((item) => (item as Map)['policyId'] == policyId)) {
      result.add(entity.path.split('/').last);
    }
  }
  return result..sort();
}

Future<void> deleteGlobalWorkcellPolicy(WorkcellPolicy policy) async {
  final references = await globalPolicyReferences(policy.id);
  if (references.isNotEmpty) {
    throw StateError('사용 중인 프로젝트: ${references.join(', ')}');
  }
  final globals = await loadGlobalWorkcellPolicies()
    ..removeWhere((item) => item.id == policy.id);
  final directory = Directory(
    '${_libraryRoot().path}/${_safe(policy.name)}/${_safe(policy.version)}',
  );
  if (await directory.exists()) await directory.delete(recursive: true);
  await _writeGlobalIndex(globals);
}

Future<HuggingFacePolicyDownload> downloadHuggingFacePolicy({
  required String repositoryUrl,
}) async {
  final repo = parseHuggingFaceRepository(repositoryUrl);
  if (repo == null) {
    throw const FormatException('올바른 Hugging Face 모델 주소를 입력하세요.');
  }
  final client = HttpClient()..connectionTimeout = const Duration(seconds: 20);
  try {
    final metadataUri = Uri.parse('https://huggingface.co/api/models/$repo');
    final metadata =
        jsonDecode(utf8.decode(await _get(client, metadataUri)))
            as Map<String, dynamic>;
    final revision = metadata['sha'] as String? ?? 'main';
    final siblings = metadata['siblings'] as List<dynamic>? ?? const [];
    final files = <String>[
      for (final item in siblings)
        if (item is Map && item['rfilename'] is String)
          item['rfilename'] as String,
    ].where(_includeHubFile).toList();
    if (!files.contains('config.json') ||
        !files.contains('model.safetensors')) {
      throw const FormatException(
        'LeRobot policy 필수 파일(config.json, model.safetensors)이 없습니다.',
      );
    }
    const limit = 1024 * 1024 * 1024;
    var total = 0;
    final archive = Archive();
    for (final file in files) {
      final encoded = file.split('/').map(Uri.encodeComponent).join('/');
      final uri = Uri.parse(
        'https://huggingface.co/$repo/resolve/$revision/$encoded',
      );
      final bytes = await _get(client, uri, limit: limit - total);
      total += bytes.length;
      if (total > limit) {
        throw const FileSystemException('Policy ZIP은 1GB 이하여야 합니다.');
      }
      archive.addFile(ArchiveFile(file, bytes.length, bytes));
    }
    final zipped = ZipEncoder().encode(archive);
    if (zipped == null) {
      throw const FileSystemException('Policy ZIP 생성에 실패했습니다.');
    }
    return HuggingFacePolicyDownload(
      repositoryId: repo,
      revision: revision,
      fileName: '${repo.split('/').last}.zip',
      bytes: Uint8List.fromList(zipped),
    );
  } finally {
    client.close(force: true);
  }
}

bool _includeHubFile(String file) =>
    file.isNotEmpty &&
    !file.startsWith('.') &&
    !file.split('/').contains('..') &&
    !file.toLowerCase().endsWith('.zip');

Future<Uint8List> _get(HttpClient client, Uri uri, {int? limit}) async {
  final request = await client.getUrl(uri);
  final token =
      Platform.environment['HF_TOKEN'] ??
      Platform.environment['HUGGING_FACE_HUB_TOKEN'];
  if (token != null && token.isNotEmpty) {
    request.headers.set(HttpHeaders.authorizationHeader, 'Bearer $token');
  }
  request.headers.set(
    HttpHeaders.userAgentHeader,
    'robosapiens-workcell-policy/1.0',
  );
  final response = await request.close();
  if (response.statusCode != HttpStatus.ok) {
    await response.drain<void>();
    throw HttpException(
      response.statusCode == HttpStatus.unauthorized ||
              response.statusCode == HttpStatus.forbidden
          ? '접근 권한이 없습니다. 비공개 저장소라면 HF_TOKEN을 설정하세요.'
          : 'Hugging Face 다운로드 실패 (HTTP ${response.statusCode})',
      uri: uri,
    );
  }
  final builder = BytesBuilder(copy: false);
  await for (final chunk in response) {
    if (limit != null && builder.length + chunk.length > limit) {
      throw const FileSystemException('Policy ZIP은 1GB 이하여야 합니다.');
    }
    builder.add(chunk);
  }
  return builder.takeBytes();
}
