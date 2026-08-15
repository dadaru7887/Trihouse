/// 끌어서 옮길 수 있는 팝업.
///
/// 팝업이 화면 한가운데 고정되면 그 아래의 지도나 목록을 볼 수 없다. 오류
/// 내용을 보면서 해당 Waypoint를 찾거나, 설정값을 바꾸면서 결과를 확인해야
/// 하는 일이 잦아서 팝업은 언제나 옆으로 치울 수 있어야 한다.
///
/// 이 파일의 [showMovableDialog] 는 `showDialog` 와 인자가 같으므로 그대로
/// 바꿔 쓰면 된다. 새 팝업도 이쪽을 쓴다.
library;

import 'dart:math' as math;

import 'package:flutter/material.dart';

/// [showDialog] 와 같은 자리에 쓴다. 만들어진 팝업을 [MovableDialog] 로 감싸
/// 끌어 옮길 수 있게 한다.
Future<T?> showMovableDialog<T>({
  required BuildContext context,
  required WidgetBuilder builder,
  bool barrierDismissible = true,
  Color? barrierColor,
  bool useRootNavigator = true,
}) => showDialog<T>(
  context: context,
  barrierDismissible: barrierDismissible,
  barrierColor: barrierColor,
  useRootNavigator: useRootNavigator,
  builder: (dialogContext) => MovableDialog(child: builder(dialogContext)),
);

/// 팝업을 끌어서 옮길 수 있게 감싼다.
///
/// 팝업 맨 위에 얇은 이동 손잡이를 얹는다. 표면 전체를 끌게 하면 안에서 끌어
/// 쓰는 것들과 부딪힌다 — 본문 글자 선택, 목록 스크롤, 크기 조절 손잡이가
/// 모두 같은 드래그를 두고 다툰다. 실제로 표면 전체를 끌게 해 보니 바깥 pan 이
/// 안쪽 pan 과 경합해 **둘 다 아무것도 못 받았다.** 감싸지 않았을 때 `(120,90)`
/// 을 받던 크기 조절 손잡이가 `(0,0)` 이 되었다. 손잡이를 따로 두면 그런 다툼이
/// 없고, 옮길 수 있다는 것도 눈에 보인다.
///
/// 손잡이는 **팝업 상자 위에** 놓아야 한다. 예전에는 `Positioned(top: 0)` 으로
/// 얹었는데, `AlertDialog` 는 제 상자만 그리는 것이 아니라 화면을 가득 채우고
/// 그 안에서 상자를 가운데 놓는다. 그래서 `Stack` 도 화면 크기가 되어 손잡이가
/// 팝업이 아니라 **화면 맨 위**에 그려졌다 — 800×600 화면에서 팝업 상자가
/// `(176,102)~(624,498)` 일 때 손잡이는 `(0,0)~(800,20)` 이었다. 82px 떨어진
/// 자리라 아무도 잡을 수 없었고, 테스트가 키로 직접 끌었던 탓에 드러나지도
/// 않았다.
///
/// 상자의 자리는 [Material] 을 찾아 잰다. `AlertDialog` 도 `Dialog` 도 표면을
/// [Material] 로 그리므로 이것이 곧 눈에 보이는 상자다.
class MovableDialog extends StatefulWidget {
  const MovableDialog({super.key, required this.child});

  /// 손잡이가 차지하는 높이. AlertDialog 의 위쪽 여백 안에 들어가므로 제목이나
  /// 아이콘을 가리지 않는다.
  static const double handleHeight = 20;

  /// 이동 손잡이를 가리키는 키. 테스트에서 이 부분만 끌어 확인한다.
  static const Key handleKey = Key('movable-dialog-handle');

  final Widget child;

  @override
  State<MovableDialog> createState() => _MovableDialogState();
}

class _MovableDialogState extends State<MovableDialog> {
  final GlobalKey _childKey = GlobalKey();
  Offset _offset = Offset.zero;

  /// 팝업 상자의 자리. [_childKey] 를 기준으로 잰 것이라 팝업을 옮겨도 그대로다.
  Rect? _surface;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _measure());
  }

  /// 팝업 상자를 찾아 [_surface] 에 담는다.
  ///
  /// 레이아웃이 끝나야 잴 수 있으므로 프레임 뒤에 부른다. 팝업 안에서 내용이
  /// 바뀌면 상자 크기도 바뀌므로 그릴 때마다 다시 잰다. 값이 같으면 다시
  /// 그리지 않는다 — 안 그러면 프레임마다 setState 가 돌아 멈추지 않는다.
  void _measure() {
    if (!mounted) return;
    final anchor = _childKey.currentContext?.findRenderObject();
    if (anchor is! RenderBox || !anchor.hasSize) return;
    final surface = _findSurface(_childKey.currentContext!);
    if (surface == null || !surface.hasSize) return;
    final origin = surface.localToGlobal(Offset.zero, ancestor: anchor);
    final found = origin & surface.size;
    if (_surface == found) return;
    setState(() => _surface = found);
  }

  /// 팝업 표면([Material])의 RenderBox. 못 찾으면 null.
  RenderBox? _findSurface(BuildContext context) {
    RenderBox? found;
    void visit(Element element) {
      if (found != null) return;
      if (element.widget is Material) {
        final render = element.findRenderObject();
        if (render is RenderBox) {
          found = render;
          return;
        }
      }
      element.visitChildren(visit);
    }

    (context as Element).visitChildren(visit);
    return found;
  }

  @override
  Widget build(BuildContext context) {
    // 내용이 바뀌면 상자도 달라진다. 그린 뒤에 다시 재 둔다.
    WidgetsBinding.instance.addPostFrameCallback((_) => _measure());
    final screen = MediaQuery.of(context).size;
    // 화면 밖으로 완전히 빠져나가면 다시 잡을 수 없다. 어느 방향으로 끌든
    // 절반은 남도록 묶는다.
    final limitX = math.max(0.0, screen.width / 2);
    final limitY = math.max(0.0, screen.height / 2);
    // 아직 못 쟀으면 첫 프레임뿐이다. 그동안은 손잡이를 감춘다 — 엉뚱한 자리에
    // 잠깐 보였다 사라지는 것보다 낫다.
    final surface = _surface;
    return Transform.translate(
      offset: _offset,
      child: Stack(
        children: [
          KeyedSubtree(key: _childKey, child: widget.child),
          if (surface != null)
            Positioned(
              left: surface.left,
              top: surface.top,
              width: surface.width,
              height: MovableDialog.handleHeight,
              child: MouseRegion(
                cursor: SystemMouseCursors.move,
                child: GestureDetector(
                  key: MovableDialog.handleKey,
                  behavior: HitTestBehavior.opaque,
                  onPanUpdate: (details) => setState(() {
                    _offset = Offset(
                      (_offset.dx + details.delta.dx).clamp(-limitX, limitX),
                      (_offset.dy + details.delta.dy).clamp(-limitY, limitY),
                    );
                  }),
                  child: Center(
                    child: Container(
                      width: 42,
                      height: 4,
                      decoration: BoxDecoration(
                        color: const Color(0xFFCBD5E1),
                        borderRadius: BorderRadius.circular(2),
                      ),
                    ),
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }
}
