// ignore_for_file: avoid_web_libraries_in_flutter, deprecated_member_use

import 'dart:async';
import 'dart:html' as html;
import 'dart:typed_data';

import '../../api/fms_models.dart';

Future<MapSourceUploadDto?> pickMapSource(String sourceType) async {
  final input = html.FileUploadInputElement()
    ..accept = switch (sourceType) {
      'slam_yaml' => '.yaml,.yml,application/x-yaml,text/yaml',
      'slam_image' => '.pgm,.png,image/x-portable-graymap,image/png',
      'physical_features_import' =>
        '.jsonl,application/x-ndjson,application/json',
      _ => '*/*',
    };
  input.click();
  await input.onChange.first;
  final files = input.files;
  if (files == null || files.isEmpty) return null;
  final file = files.single;
  final reader = html.FileReader();
  reader.readAsArrayBuffer(file);
  await reader.onLoad.first;
  final bytes = Uint8List.view(reader.result as ByteBuffer);
  final fallbackMime = switch (sourceType) {
    'slam_yaml' => 'application/x-yaml',
    'slam_image' => 'application/octet-stream',
    'physical_features_import' => 'application/x-ndjson',
    _ => 'application/octet-stream',
  };
  return MapSourceUploadDto(
    sourceType: sourceType,
    fileName: file.name,
    mimeType: file.type.isEmpty ? fallbackMime : file.type,
    bytes: bytes,
  );
}
