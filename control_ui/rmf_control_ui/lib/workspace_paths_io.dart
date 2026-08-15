import 'dart:io';

/// 단독 배포된 robosapiens의 루트. RMF 작업공간도 이 루트 안에 둔다.
Directory robosapiensRoot() {
  var directory = Directory.current.absolute;
  for (var i = 0; i < 8; i++) {
    if (Directory('${directory.path}/rmf_maps').existsSync() &&
        Directory('${directory.path}/rmf_control_ui').existsSync()) {
      return directory;
    }
    final parent = directory.parent;
    if (parent.path == directory.path) break;
    directory = parent;
  }
  return Directory.current.absolute;
}

String bundledRmfWorkspace() => '${robosapiensRoot().path}/rmf_ws';
