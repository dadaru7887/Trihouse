import 'package:flutter/material.dart';
import 'package:flutter_webrtc/flutter_webrtc.dart';

import 'theme.dart';

/// 매장 실시간 영상 뷰.
///
/// 지금은 **로컬 카메라(웹캠)** 를 띄운다. 실제 연동 시에는 [_open]을
/// 시그널링 접속 + `RTCPeerConnection` 원격 트랙 구독으로 바꾸면 되고,
/// 렌더러와 화면 구성은 그대로 쓴다.
///
/// [active]가 false가 되면 카메라를 끈다. 탭으로 쓸 때 다른 화면을 보는 동안
/// 카메라를 계속 점유하지 않기 위한 것이다.
class LiveStoreView extends StatefulWidget {
  const LiveStoreView({
    super.key,
    this.active = true,
    this.orderId,
    this.robotId,
    this.caption,
  });

  final bool active;
  final String? orderId;
  final String? robotId;

  /// 영상 아래 설명. 비우면 기본 안내가 나온다.
  final String? caption;

  @override
  State<LiveStoreView> createState() => _LiveStoreViewState();
}

enum _Stage { idle, connecting, live, denied, unavailable }

class _LiveStoreViewState extends State<LiveStoreView> {
  final RTCVideoRenderer _renderer = RTCVideoRenderer();
  MediaStream? _stream;
  _Stage _stage = _Stage.idle;
  String? _detail;
  List<MediaDeviceInfo> _cameras = <MediaDeviceInfo>[];
  String? _deviceId;
  bool _ready = false;

  @override
  void initState() {
    super.initState();
    _init();
  }

  Future<void> _init() async {
    try {
      await _renderer.initialize();
    } catch (e) {
      // 카메라 플랫폼 채널이 없는 환경(테스트 등).
      if (mounted) {
        setState(() {
          _stage = _Stage.unavailable;
          _detail = '이 환경에서는 영상 렌더러를 초기화할 수 없습니다.';
        });
      }
      return;
    }
    if (!mounted) return;
    _ready = true;
    if (widget.active) await _open();
  }

  @override
  void didUpdateWidget(LiveStoreView old) {
    super.didUpdateWidget(old);
    if (!_ready || widget.active == old.active) return;
    if (widget.active) {
      _open(deviceId: _deviceId);
    } else {
      _stop();
    }
  }

  Future<void> _open({String? deviceId}) async {
    if (!_ready) return;
    setState(() {
      _stage = _Stage.connecting;
      _detail = null;
    });
    try {
      _releaseStream();
      final stream = await navigator.mediaDevices.getUserMedia(<String, dynamic>{
        'audio': false,
        'video': deviceId == null
            ? <String, dynamic>{
                'width': <String, dynamic>{'ideal': 1280},
                'height': <String, dynamic>{'ideal': 720},
              }
            : <String, dynamic>{
                'deviceId': deviceId,
                'width': <String, dynamic>{'ideal': 1280},
                'height': <String, dynamic>{'ideal': 720},
              },
      });
      if (!mounted || !widget.active) {
        stream.getTracks().forEach((t) => t.stop());
        await stream.dispose();
        return;
      }
      _stream = stream;
      _renderer.srcObject = stream;

      final devices = await navigator.mediaDevices.enumerateDevices();
      if (!mounted) return;
      setState(() {
        _cameras = devices.where((d) => d.kind == 'videoinput').toList();
        _deviceId = deviceId;
        _stage = _Stage.live;
      });
    } catch (e) {
      if (!mounted) return;
      final msg = e.toString();
      setState(() {
        _stage = msg.contains('NotAllowed') || msg.contains('Permission')
            ? _Stage.denied
            : _Stage.unavailable;
        _detail = msg;
      });
    }
  }

  void _releaseStream() {
    if (_ready) _renderer.srcObject = null;
    _stream?.getTracks().forEach((t) => t.stop());
    _stream?.dispose();
    _stream = null;
  }

  void _stop() {
    _releaseStream();
    if (mounted) setState(() => _stage = _Stage.idle);
  }

  @override
  void dispose() {
    _releaseStream();
    if (_ready) _renderer.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      children: <Widget>[
        Expanded(
          child: Stack(
            fit: StackFit.expand,
            children: <Widget>[
              if (_stage == _Stage.live)
                RTCVideoView(
                  _renderer,
                  objectFit: RTCVideoViewObjectFit.RTCVideoViewObjectFitCover,
                )
              else
                _placeholder(),
              if (_stage == _Stage.live) ...<Widget>[
                _badge(),
                if (_cameras.length > 1) _cameraSwitch(),
              ],
            ],
          ),
        ),
        _footer(),
      ],
    );
  }

  Widget _placeholder() {
    final (IconData icon, String title, String body) = switch (_stage) {
      _Stage.idle => (
        Icons.videocam_outlined,
        '카메라 꺼짐',
        '이 탭을 보고 있을 때만 카메라를 사용합니다.',
      ),
      _Stage.connecting => (
        Icons.videocam_outlined,
        '카메라 연결 중',
        '브라우저가 권한을 물으면 허용해 주세요.',
      ),
      _Stage.denied => (
        Icons.videocam_off_outlined,
        '카메라 권한이 거부되었습니다',
        '주소창의 카메라 아이콘에서 권한을 허용한 뒤 다시 시도해 주세요.',
      ),
      _Stage.unavailable => (
        Icons.error_outline,
        '카메라를 열 수 없습니다',
        _detail ?? '사용 가능한 카메라를 찾지 못했습니다.',
      ),
      _Stage.live => (Icons.videocam, '', ''),
    };

    return Container(
      color: const Color(0xFF141414),
      alignment: Alignment.center,
      padding: const EdgeInsets.all(28),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: <Widget>[
          if (_stage == _Stage.connecting)
            const SizedBox(
              width: 26,
              height: 26,
              child: CircularProgressIndicator(strokeWidth: 2.5),
            )
          else
            Icon(icon, size: 38, color: Colors.white38),
          const SizedBox(height: 15),
          Text(
            title,
            style: const TextStyle(
              color: Colors.white,
              fontSize: 14.5,
              fontWeight: FontWeight.w600,
            ),
          ),
          const SizedBox(height: 7),
          Text(
            body,
            textAlign: TextAlign.center,
            style: const TextStyle(
              color: Colors.white54,
              fontSize: 12.5,
              height: 1.5,
            ),
          ),
          if (_stage != _Stage.connecting) ...<Widget>[
            const SizedBox(height: 16),
            OutlinedButton.icon(
              onPressed: () => _open(deviceId: _deviceId),
              style: OutlinedButton.styleFrom(
                foregroundColor: Colors.white,
                side: const BorderSide(color: Colors.white24),
              ),
              icon: const Icon(Icons.play_arrow, size: 15),
              label: Text(
                _stage == _Stage.idle ? '보기' : '다시 시도',
                style: const TextStyle(fontSize: 12.5),
              ),
            ),
          ],
        ],
      ),
    );
  }

  Widget _badge() => Positioned(
    left: 14,
    top: 14,
    child: Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(
        color: Colors.black.withValues(alpha: 0.55),
        borderRadius: BorderRadius.circular(20),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: <Widget>[
          Container(
            width: 7,
            height: 7,
            decoration: const BoxDecoration(
              color: Color(0xFFE34948),
              shape: BoxShape.circle,
            ),
          ),
          const SizedBox(width: 7),
          Text(
            widget.robotId == null ? 'LIVE' : 'LIVE · ${widget.robotId}',
            style: const TextStyle(
              color: Colors.white,
              fontSize: 11.5,
              fontWeight: FontWeight.w700,
              letterSpacing: 0.6,
            ),
          ),
        ],
      ),
    ),
  );

  Widget _cameraSwitch() => Positioned(
    right: 10,
    top: 8,
    child: PopupMenuButton<String>(
      tooltip: '카메라 선택',
      icon: const Icon(Icons.cameraswitch_outlined, color: Colors.white),
      onSelected: (id) => _open(deviceId: id),
      itemBuilder: (context) => <PopupMenuEntry<String>>[
        for (final c in _cameras)
          PopupMenuItem<String>(
            value: c.deviceId,
            child: Row(
              children: <Widget>[
                if (c.deviceId == _deviceId)
                  const Icon(Icons.check, size: 15)
                else
                  const SizedBox(width: 15),
                const SizedBox(width: 8),
                Text(c.label.isEmpty ? '카메라 ${c.deviceId}' : c.label),
              ],
            ),
          ),
      ],
    ),
  );

  Widget _footer() => Container(
    width: double.infinity,
    color: const Color(0xFF1A1A1A),
    padding: const EdgeInsets.fromLTRB(18, 13, 18, 16),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        Text(
          widget.orderId == null ? '매장 실시간 화면' : '${widget.orderId} 집품 현황',
          style: const TextStyle(
            color: Colors.white,
            fontSize: 13.5,
            fontWeight: FontWeight.w600,
          ),
        ),
        const SizedBox(height: 5),
        Text(
          widget.caption ??
              '현재는 이 기기의 카메라를 표시하고 있습니다. 센터 연동이 완료되면 '
                  '매장에서 작업 중인 로봇의 카메라 영상이 같은 자리에 나옵니다.',
          style: TextStyle(
            color: Colors.white.withValues(alpha: 0.55),
            fontSize: 11.5,
            height: 1.5,
          ),
        ),
      ],
    ),
  );
}

/// 주문 카드에서 여는 전체 화면 실시간 뷰.
class LiveViewPage extends StatelessWidget {
  const LiveViewPage({super.key, this.orderId, this.robotId});

  final String? orderId;
  final String? robotId;

  @override
  Widget build(BuildContext context) => Scaffold(
    backgroundColor: Colors.black,
    appBar: AppBar(
      backgroundColor: Colors.black,
      foregroundColor: Colors.white,
      title: Text(
        orderId == null ? '실시간 화면' : '$orderId 실시간 화면',
        style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
      ),
    ),
    body: LiveStoreView(orderId: orderId, robotId: robotId),
  );
}

/// 주문 카드에 붙는 작은 실시간 보기 버튼.
class LiveViewButton extends StatelessWidget {
  const LiveViewButton({
    super.key,
    this.orderId,
    this.robotId,
    this.dense = false,
  });

  final String? orderId;
  final String? robotId;
  final bool dense;

  @override
  Widget build(BuildContext context) => TextButton.icon(
    onPressed: () => Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => LiveViewPage(orderId: orderId, robotId: robotId),
      ),
    ),
    style: TextButton.styleFrom(
      foregroundColor: ShopColors.brand,
      minimumSize: Size.zero,
      padding: EdgeInsets.symmetric(horizontal: dense ? 6 : 10, vertical: 4),
      tapTargetSize: MaterialTapTargetSize.shrinkWrap,
    ),
    icon: const Icon(Icons.videocam_outlined, size: 15),
    label: Text(
      '실시간 보기',
      style: TextStyle(
        fontSize: dense ? 11.5 : 12.5,
        fontWeight: FontWeight.w600,
      ),
    ),
  );
}
