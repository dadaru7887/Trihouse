#!/usr/bin/env python3
"""`trihouse_test_01` 지도 프로젝트를 Gateway API 로 발행한다.

관제 UI 의 지도 화면이 하는 일(업로드 → 저장 → 배포)을 그대로 명령줄에서 한다.
DB 를 seed 로 되돌리면 발행된 revision 도 사라지므로 매번 다시 발행해야 한다.

## 어떤 SLAM 지도를 올리는가

`P0_MAP` 환경변수 또는 첫 번째 인자로 고른다. 기본은 `trihouse_map_01` 이다 —
waypoint 실측 기록의 `source_map_name` 이 그것이고 bringup 의 기본값도 그것이다.

    python3 scripts/p0_publish_map.py new_map_2
    python3 scripts/p0_publish_map.py control_ui/rmf_control_ui/data/rmf_maps/new_map_2.yaml
    P0_MAP=/절대/경로/my_map.yaml python3 scripts/p0_publish_map.py

이름을 주면 `control_ui/rmf_control_ui/data/rmf_maps/<이름>.yaml` 을 쓴다. 경로를
주면 그 파일을 쓰고, 이미지는 ROS 지도 규약대로 yaml 과 같은 디렉터리에서 찾는다.

**여기서 고른 지도와 Nav2 가 도는 지도가 같아야 한다.** 좌표는 지도마다 다른
프레임 위의 값이라, 갈라지면 로봇이 "도착했다"고 말하는 자리가 원장이 아는 자리와
어긋난다. `scripts/p0_reset.sh` 가 고른 이름을 `.trihouse/map_name` 에 적어 두고
`scripts/p0_up.sh` 가 그것을 읽는 이유다.

## 확장자와 내용이 다른 파일

`new_map_2.pgm` 은 확장자만 `.pgm` 이고 내용은 PNG 다. 배포 검증기는 **확장자로
파서를 고르므로** 그대로 올리면 `SLAM_IMAGE_INVALID` 가 난다. 저장소 파일은 고치지
않고, 올릴 때의 이름과 yaml 의 `image` 필드만 실제 형식에 맞춘다. 어느 지도든
동작하도록 이름이 아니라 **파일의 magic bytes** 로 판별한다.
"""
import json
import os
import sys
from pathlib import Path

import requests

BASE = "http://127.0.0.1:8080/api/v1/map-projects"
MAP = "trihouse_test_01"
ROOT = Path(__file__).resolve().parents[1]
MAPS = ROOT / "control_ui" / "rmf_control_ui" / "data" / "rmf_maps"

# 지도는 이름으로도, yaml 경로로도 지정할 수 있다.
#   scripts/p0_publish_map.py trihouse_map_01
#   scripts/p0_publish_map.py control_ui/rmf_control_ui/data/rmf_maps/new_map_2.yaml
#   P0_MAP=/절대/경로/my_map.yaml scripts/p0_publish_map.py
SELECTOR = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("P0_MAP", "trihouse_map_01")).strip()

if SELECTOR.endswith(".yaml") or "/" in SELECTOR:
    yaml_path = Path(SELECTOR).expanduser()
    if not yaml_path.is_absolute():
        yaml_path = (Path.cwd() / yaml_path).resolve()
else:
    yaml_path = MAPS / f"{SELECTOR}.yaml"

if not yaml_path.is_file():
    print(f"[실패] SLAM yaml 이 없습니다: {yaml_path}")
    available = sorted(q.stem for q in MAPS.glob("*.yaml"))
    print(f"       저장소에 있는 지도: {', '.join(available)}")
    sys.exit(1)

MAP_NAME = yaml_path.stem
yaml_bytes = yaml_path.read_bytes()

image_name = None
for line in yaml_bytes.decode("utf-8").splitlines():
    if line.startswith("image:"):
        image_name = line.split(":", 1)[1].strip()
        break
if image_name is None:
    print(f"[실패] {yaml_path} 에 image 항목이 없습니다.")
    sys.exit(1)

# ROS 지도 규약대로 이미지는 yaml 과 같은 디렉터리에서 찾는다.
image_path = yaml_path.parent / image_name
if not image_path.is_file():
    print(f"[실패] SLAM 이미지가 없습니다: {image_path}")
    sys.exit(1)
image_bytes = image_path.read_bytes()

# 확장자가 아니라 내용으로 형식을 정한다. 검증기는 확장자로 파서를 고르므로,
# 내용과 어긋나는 이름으로 올리면 SLAM_IMAGE_INVALID 가 난다.
if image_bytes.startswith(b"\x89PNG\r\n"):
    upload_image_name, image_mime = f"{Path(image_name).stem}.png", "image/png"
elif image_bytes[:2] in (b"P5", b"P2"):
    upload_image_name, image_mime = f"{Path(image_name).stem}.pgm", "image/x-portable-graymap"
else:
    print(f"[실패] 알 수 없는 이미지 형식입니다: {image_path}")
    sys.exit(1)

# yaml 의 image 는 올리는 이름과 **같아야** 한다(검증기가 대조한다).
if upload_image_name != image_name:
    yaml_bytes = yaml_bytes.replace(
        f"image: {image_name}".encode(), f"image: {upload_image_name}".encode()
    )

# 웨이포인트 좌표는 **지도 좌표계에 묶여 있다.** 지도를 다시 그리면 같은 물리적
# 자리가 다른 숫자가 된다. 그래서 지도별 실측 파일을 먼저 찾고, 없을 때만 기본
# 파일로 되돌아간다. 기본 파일은 trihouse_map_01 에서 잰 값이다.
IMPORT_DIR = ROOT / "control_ui" / "rmf_control_ui" / "data" / "import"
features_path = IMPORT_DIR / f"{MAP}_physical_features.{MAP_NAME}.jsonl"
if not features_path.is_file():
    features_path = IMPORT_DIR / f"{MAP}_physical_features.jsonl"
    print(f"[주의] 지도 '{MAP_NAME}' 전용 실측 파일이 없어 기본 파일을 씁니다: {features_path.name}")
else:
    print(f"[0/4] 실측: {features_path.name}")
SOURCES = [
    ("slam_yaml", f"{MAP_NAME}.yaml", "application/x-yaml", yaml_bytes),
    ("slam_image", upload_image_name, image_mime, image_bytes),
    ("physical_features_import", features_path.name, "application/x-ndjson", features_path.read_bytes()),
]

print(f"[0/4] 지도 {MAP_NAME}\n      yaml  {yaml_path}\n      image {image_path} -> {upload_image_name} ({image_mime})")


def die(step, response):
    print(f"[실패] {step} -> HTTP {response.status_code}")
    print(response.text[:1500])
    sys.exit(1)


# 1. 프로젝트 열기 (없으면 빈 draft 를 돌려준다)
r = requests.post(BASE, json={"map_name": MAP}, timeout=30)
if r.status_code != 200:
    die("open", r)
opened = r.json()
draft = opened["draft"]
print(f"[1/4] open  draft_revision={draft['draft_revision']} open_existing={opened['open_existing']}")

# 2. 원본 3종 stage
tokens = {}
for source_type, file_name, content_type, payload in SOURCES:
    r = requests.post(
        f"{BASE}/{MAP}/sources/stage",
        data={"source_type": source_type},
        files={"source": (file_name, payload, content_type)},
        timeout=120,
    )
    if r.status_code != 201:
        die(f"stage {source_type}", r)
    staged = r.json()
    tokens[source_type] = staged["upload_token"]
    extra = ""
    if source_type == "physical_features_import":
        extra = f" waypoints={len(staged['waypoints'])} features={len(staged['features'])}"
    print(f"[2/4] stage {source_type:26s} {staged['byte_size']:>9,} B{extra}")

# 3. 저장 (waypoints/features 는 서버가 실측 JSONL 에서 정본으로 채운다)
body = {
    "map_name": MAP,
    "format_version": draft["format_version"],
    "draft_revision": draft["draft_revision"],
    "source_uuids": draft["source_uuids"],
    "staged_source_tokens": tokens,
    "waypoints": [],
    "features": [],
    "runtime_profile_hash": draft["runtime_profile_hash"],
}
r = requests.put(
    f"{BASE}/{MAP}",
    json=body,
    headers={"If-Match": f'"{draft["draft_revision"]}"'},
    timeout=60,
)
if r.status_code != 200:
    die("save", r)
saved = r.json()
print(f"[3/4] save  draft_revision={saved['draft_revision']} waypoints={len(saved['waypoints'])} features={len(saved['features'])}")

# 4. 배포 (서버가 먼저 검증한다)
r = requests.post(
    f"{BASE}/{MAP}/publish",
    json={"expected_draft_revision": saved["draft_revision"], "published_by": "cli-publish"},
    timeout=120,
)
if r.status_code != 200:
    die("publish", r)
published = r.json()
print(f"[4/4] publish 완료")
print()
print("TRIHOUSE_MAP_REVISION 값:")
print(published["map_revision"])
