class StoredProjectFile {
  const StoredProjectFile({
    required this.fileName,
    required this.modifiedAt,
    required this.size,
  });

  final String fileName;
  final DateTime modifiedAt;
  final int size;

  String get projectName =>
      fileName.replaceFirst(RegExp(r'\.rmfproject$', caseSensitive: false), '');
}
