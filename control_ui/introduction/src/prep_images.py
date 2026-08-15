#!/usr/bin/env python3
"""슬라이드에 얹을 이미지를 자르고 줄여 data URI 로 만든다.

Artifact 는 외부 호스트를 막으므로 전부 판 안에 심어야 한다. 16MB 안에
들어가도록 필요한 크기까지만 줄이고 JPEG 로 굽는다.
"""
import base64, io, json, pathlib
from PIL import Image

HERE = pathlib.Path(__file__).parent
IMG = HERE / "photos"
PROJ = HERE.parent.parent  # 저장소 뿌리

# (키, 원본, 자를 상자 or None, 목표 폭, 품질)
JOBS = [
    # 붉은 휴머노이드 — 검은 배경이라 다크 판에 그대로 얹힌다
    ("humanoid",  IMG / "TOCABI_black_3200px.jpg", None, 900, 84),
    # 흰 협동 휴머노이드 — 오른쪽 사람은 잘라 낸다 (남의 초상은 쓰지 않는다)
    ("cobot",     IMG / "Halodi_Robotics__Perception_Engineer_With_a_Humanoid_Collaborative_Robot.jpg",
                  (0, 0, 1180, 1500), 620, 84),
    # 산업용 로봇팔 라인 — 스마트 팩토리
    ("factory",   IMG / "MIREA_Laboratory_Industry_4.0._Digital_robotic_manufacturing_5.jpg",
                  None, 1120, 82),
    ("factory2",  IMG / "MIREA_Laboratory_Industry_4.0._Digital_robotic_manufacturing_8.jpg",
                  None, 820, 82),
    # 내가 만든 실제 화면
    ("dashboard", PROJ / "robo_control/docs/images/01-dashboard.png", None, 1440, 86),
    ("map",       PROJ / "robo_control/docs/images/02-map.png",       None, 1200, 86),
    ("safety",    PROJ / "robo_control/docs/images/06-safety.png",    None, 1200, 86),
    ("robots",    PROJ / "robo_control/docs/images/03-robots.png",    None, 1100, 86),
]

out, total = {}, 0
for key, src, box, width, q in JOBS:
    im = Image.open(src).convert("RGB")
    if box:
        im = im.crop(box)
    if im.width > width:
        im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=q, optimize=True, progressive=True)
    b = buf.getvalue()
    total += len(b)
    out[key] = "data:image/jpeg;base64," + base64.b64encode(b).decode()
    print(f"{key:10} {im.width}x{im.height:5}  {len(b)/1024:7.1f} KB")

print(f"합계 {total/1024/1024:.2f} MB")
(HERE / "images.json").write_text(json.dumps(out), encoding="utf-8")
