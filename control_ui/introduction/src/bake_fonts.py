#!/usr/bin/env python3
"""portfolio.html 에 쓰인 글자만 서브셋해 @font-face data URI 로 심는다.

Artifact 는 폰트 CDN 을 막으므로 심지 않으면 조용히 대체 서체로 떨어진다.
"""
import base64, io, re, subprocess, sys, tempfile, pathlib

SRC = pathlib.Path(sys.argv[1])
OUT = pathlib.Path(sys.argv[2])
NANUM = pathlib.Path("/usr/share/fonts/truetype/nanum")

FACES = [
    ("NanumSquare",       700, NANUM / "NanumSquareB.ttf"),
    ("NanumBarunGothic",  400, NANUM / "NanumBarunGothic.ttf"),
    ("NanumGothicCoding", 400, NANUM / "NanumGothicCoding.ttf"),
    ("NanumGothicCoding", 700, NANUM / "NanumGothicCodingBold.ttf"),
]

html = SRC.read_text(encoding="utf-8")

# <style>/<svg> 를 뺀 뒤 태그를 걷어 내 실제로 그려지는 글자만 모은다.
visible = re.sub(r"<(style|svg)\b.*?</\1>", " ", html, flags=re.S | re.I)
visible = re.sub(r"<[^>]+>", " ", visible)
chars = set(visible) | set(
    "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    " .,:;·—–-/·()[]{}<>+×%&'\"…"
)
chars = {c for c in chars if c.isprintable() and not c.isspace()}
text = "".join(sorted(chars))
print(f"글자 {len(text)}자")

blocks, total = [], 0
with tempfile.TemporaryDirectory() as tmp:
    for family, weight, path in FACES:
        if not path.exists():
            sys.exit(f"없는 서체: {path}")
        dst = pathlib.Path(tmp) / f"{path.stem}.woff2"
        subprocess.run(
            [sys.executable, "-m", "fontTools.subset", str(path), f"--text={text}",
             "--flavor=woff2", "--layout-features=", "--no-hinting",
             f"--output-file={dst}"],
            check=True,
        )
        b = dst.read_bytes()
        total += len(b)
        print(f"  {path.name:28} {len(b)/1024:7.1f} KB")
        blocks.append(
            "@font-face{"
            f"font-family:\"{family}\";font-style:normal;font-weight:{weight};"
            "font-display:block;src:url(data:font/woff2;base64,"
            f"{base64.b64encode(b).decode()}) format(\"woff2\")}}"
        )

print(f"합계 {total/1024:.1f} KB")
OUT.write_text(html.replace("/*FONTS*/", "\n".join(blocks)), encoding="utf-8")
print(f"→ {OUT} ({OUT.stat().st_size/1024:.0f} KB)")
