#!/usr/bin/env python3
"""deck.html 에 폰트·사진·배경 SVG 를 심어 자립형 한 장으로 만든다.

Artifact 는 외부 호스트를 전부 막으므로 폰트도 사진도 판 안에 있어야 한다.
폰트는 실제로 쓰이는 글자만 서브셋한다 — 나눔 한 벌을 통째로 넣으면 4MB 다.
"""
import base64, json, re, subprocess, sys, tempfile, pathlib

HERE = pathlib.Path(__file__).parent
SRC = HERE / "deck.html"
OUT = HERE.parent / "발표페이지.html"
NANUM = pathlib.Path("/usr/share/fonts/truetype/nanum")

FACES = [
    ("NanumSquare",       700, NANUM / "NanumSquareB.ttf"),
    ("NanumBarunGothic",  400, NANUM / "NanumBarunGothic.ttf"),
    ("NanumBarunGothic",  700, NANUM / "NanumBarunGothicBold.ttf"),
    ("NanumGothicCoding", 400, NANUM / "NanumGothicCoding.ttf"),
    ("NanumGothicCoding", 700, NANUM / "NanumGothicCodingBold.ttf"),
]

# 배경 lane graph — 창고 도면의 waypoint·lane. 앱이 실제로 그리는 것이다.
LANES = """<svg viewBox="0 0 1920 1080" preserveAspectRatio="none" aria-hidden="true">
<defs><pattern id="g" width="48" height="48" patternUnits="userSpaceOnUse">
<path d="M48 0H0V48" fill="none" stroke="#4C8DFF" stroke-width=".7" opacity=".07"/></pattern></defs>
<rect width="1920" height="1080" fill="url(#g)"/>
<g fill="none" stroke="#4C8DFF" stroke-width="1.2" opacity=".1">
<path d="M120 250H640V430H1180V210H1690"/><path d="M640 250V96"/>
<path d="M120 250V700H430V890H980"/><path d="M1180 430V760H700"/>
<path d="M1690 210V620H1330V960"/><path d="M430 700H700V960"/>
<path d="M980 890H1330"/><path d="M120 700V960H430"/>
</g>
<g fill="#070C18" stroke="#4C8DFF" stroke-width="1.5" opacity=".2">
<circle cx="120" cy="250" r="6"/><circle cx="640" cy="250" r="6"/><circle cx="640" cy="430" r="6"/>
<circle cx="1180" cy="430" r="6"/><circle cx="1180" cy="210" r="6"/><circle cx="1690" cy="210" r="6"/>
<circle cx="120" cy="700" r="6"/><circle cx="430" cy="700" r="6"/><circle cx="430" cy="890" r="6"/>
<circle cx="980" cy="890" r="6"/><circle cx="700" cy="760" r="6"/><circle cx="1330" cy="620" r="6"/>
<circle cx="1330" cy="960" r="6"/><circle cx="640" cy="96" r="6"/><circle cx="700" cy="960" r="6"/>
</g></svg>"""

ARROW = ('<svg width="14" height="9" viewBox="0 0 14 9">'
         ''
         '<path d="M2.4 1.5 7 7l4.6-5.5" fill="none" stroke="currentColor" '
         'stroke-width="1.6" stroke-linejoin="round"/></svg>')

html = SRC.read_text(encoding="utf-8")

# ── 동영상 ────────────────────────────────────────────────────
# 슬라이드 PNG 에서 굽는 파일이라 첫 빌드에는 없다. 없으면 단추를 빼고,
# 있으면 판 안에 심는다 — Artifact 는 외부 링크를 막으므로 data URI 뿐이다.
VIDEO = HERE.parent / "포트폴리오-15초.mp4"
if VIDEO.exists():
    mp4 = VIDEO.read_bytes()
    b64 = base64.b64encode(mp4).decode()
    button = ('<button type="button" class="dl" id="dl">'
              "↓ 동영상 내려받기 <small>15초 · MP4</small></button>")
    # base64 는 href 가 아니라 script 안에 둔다. 자바스크립트가 Blob 으로 풀어
    # 넘겨야 샌드박스 iframe 과 URL 길이 제한을 둘 다 피한다.
    block = (
        '<div class="vidwrap">'
        '<video id="vid" controls preload="metadata" playsinline></video>'
        "<p>카톡 프로필에 올릴 15초 동영상입니다. 위 단추가 막히면 영상에서 "
        "오른쪽 클릭 → <b>다른 이름으로 저장</b>, 또는 "
        '<a href="#" id="dlopen">새 창에서 열기</a>.</p>'
        "</div>\n"
        f'<script id="mp4data" type="text/plain">{b64}</script>'
    )
    print(f"동영상 {len(mp4)/1024/1024:.2f} MB → base64 {len(b64)/1024/1024:.2f} MB")
else:
    button = block = ""
    print("동영상 없음 — 단추를 뺀다 (슬라이드를 굽고 다시 실행하세요)")
html = html.replace("{{DL_BUTTON}}", button).replace("{{VIDEO_BLOCK}}", block)

# ── 사진 ──────────────────────────────────────────────────────
images = json.loads((HERE / "images.json").read_text(encoding="utf-8"))
for key, uri in images.items():
    html = html.replace("{{" + key + "}}", uri)
html = html.replace("{{LANES}}", LANES).replace("{{ARROW}}", ARROW)

left = set(re.findall(r"\{\{(\w+)\}\}", html))
if left:
    sys.exit(f"안 채운 자리: {sorted(left)}")

# ── 폰트 ──────────────────────────────────────────────────────
# 사진 data URI 를 먼저 심었으니 글자 수집에서는 style/svg/script 를 뺀다.
visible = re.sub(r"<(style|svg|script)\b.*?</\1>", " ", html, flags=re.S | re.I)
visible = re.sub(r"<[^>]+>", " ", visible)
chars = {c for c in visible if c.isprintable() and not c.isspace()}
chars |= set("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
             " .,:;·—–-/()[]<>+×%&'\"…©№")
text = "".join(sorted(chars))
print(f"글자 {len(text)}자")

blocks, ftotal = [], 0
with tempfile.TemporaryDirectory() as tmp:
    for family, weight, path in FACES:
        dst = pathlib.Path(tmp) / f"{path.stem}.woff2"
        subprocess.run(
            [sys.executable, "-m", "fontTools.subset", str(path), f"--text={text}",
             "--flavor=woff2", "--layout-features=", "--no-hinting",
             f"--output-file={dst}"],
            check=True, stderr=subprocess.DEVNULL)
        b = dst.read_bytes()
        ftotal += len(b)
        blocks.append(
            f'@font-face{{font-family:"{family}";font-style:normal;font-weight:{weight};'
            "font-display:block;src:url(data:font/woff2;base64,"
            f'{base64.b64encode(b).decode()}) format("woff2")}}')
print(f"폰트 {ftotal/1024:.0f} KB")

OUT.write_text(html.replace("/*FONTS*/", "\n".join(blocks)), encoding="utf-8")
print(f"→ {OUT.name}  {OUT.stat().st_size/1024/1024:.2f} MB")
