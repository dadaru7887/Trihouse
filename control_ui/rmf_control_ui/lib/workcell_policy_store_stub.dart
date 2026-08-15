import 'dart:typed_data';
import 'workcell_policy.dart';

Future<List<WorkcellPolicy>> loadWorkcellPolicies(String projectName) async =>
    [];
Future<List<WorkcellPolicy>> loadGlobalWorkcellPolicies() async => [];
Future<void> saveWorkcellPolicy(
  String projectName,
  WorkcellPolicy policy,
  Uint8List archive,
) async {}
Future<void> deleteWorkcellPolicy(
  String projectName,
  WorkcellPolicy policy,
) async {}
Future<void> bindWorkcellPolicy(
  String projectName,
  WorkcellPolicy policy,
) async {}
Future<List<String>> globalPolicyReferences(String policyId) async => [];
Future<void> deleteGlobalWorkcellPolicy(WorkcellPolicy policy) async {}
Future<HuggingFacePolicyDownload> downloadHuggingFacePolicy({
  required String repositoryUrl,
}) => throw UnsupportedError('이 플랫폼에서는 Hugging Face 다운로드를 지원하지 않습니다.');
