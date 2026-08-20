# `.glb` 창고 모델을 Gazebo 에 올리고 SLAM 지도와 정합시키기

지도는 두 가지 일을 한다. **보여 주는 것**과 **위치를 정하는 것**이다. 지금은 둘이
갈라져 있다 — Gazebo 세계에는 `ground_plane` 하나뿐이라 벽이 없고, 벽은 오직
`new_map_2.pgm` 안에만 있다. 그래서:

- 라이다가 아무것도 못 봐서 **AMCL 이 위치를 고칠 수 없다.** 자세는 순수 오도메트리다.
- 로봇이 물리적으로 아무 데나 갈 수 있다. 2026-08-19 에 지도 밖 (−0.80, −2.10) 까지
  나가서 계획기가 421번 연속 실패했다.
- 협로 규칙 주행을 시뮬레이션에서 **검증할 수 없다.** 부딪힐 벽이 없다.

`.glb` 를 올리면 이 셋이 한꺼번에 풀린다. 단, **정합이 맞아야만** 그렇다.

---

## 1. 무엇과 무엇을 맞추는가

두 좌표계를 겹치는 일이다.

| | 원점이 뜻하는 곳 | 어디에 적혀 있나 |
|---|---|---|
| **지도 프레임** | 이미지 좌하단 픽셀의 세계 좌표 | `new_map_2.yaml` 의 `origin: [-0.22, -1.473, 0]`, `resolution: 0.03` |
| **Gazebo 세계 프레임** | 모델 `<pose>` 가 재는 기준 | world SDF |

픽셀 → 세계 좌표 변환은 이렇다.

```
x = origin_x + (col + 0.5) * resolution
y = origin_y + (height - 1 - row + 0.5) * resolution
```

`new_map_2` 는 73×89 @ 0.03 m 이므로 x는 −0.220~1.970, y는 −1.473~1.197. 실제 방은
**2.19 m × 2.67 m** 다. `.glb` 가 이보다 훨씬 크면 단위가 다른 것이다(대개 mm).

> **기존 웨이포인트 좌표는 이 지도 프레임 위의 값이다.** 그러니 맞춰야 하는 것은
> `.glb` 쪽이지 좌표 쪽이 아니다. 모델을 움직여 지도에 맞춘다.

---

## 2. Gazebo 가 실제로 요구하는 것

**`<visual>` 만 넣으면 예쁘기만 하고 아무 일도 안 한다.** 라이다는 `<collision>` 에
광선을 쏜다. 충돌 형상이 없으면 로봇은 벽을 그냥 통과하고 라이다는 빈 공간을 본다.

```xml
<model name="warehouse">
  <static>true</static>                       <!-- 물리 계산에서 빠져 가볍다 -->
  <pose>TX TY 0 0 0 TYAW</pose>               <!-- 3절에서 구한 값 -->
  <link name="body">
    <visual name="visual">
      <geometry><mesh><uri>model://warehouse/meshes/warehouse.glb</uri></mesh></geometry>
    </visual>
    <collision name="collision">
      <geometry><mesh><uri>model://warehouse/meshes/warehouse_collision.glb</uri></mesh></geometry>
    </collision>
  </link>
</model>
```

- gz-sim(Jazzy)은 `.glb`/`.gltf`/`.dae`/`.obj`/`.stl` 을 읽는다.
- **충돌용은 따로 단순화한 메시를 쓴다.** 시각용 고해상도 메시를 충돌에 그대로 쓰면
  광선 검사가 느려져 실시간 배율이 떨어진다. 벽만 남긴 저폴리 버전이나 `<box>` 몇 개면
  충분하다 — 라이다는 벽의 **위치**만 알면 된다.
- `model://` 을 쓰려면 모델 폴더의 부모를 자원 경로에 넣는다.
  `export GZ_SIM_RESOURCE_PATH=$HOME/Trihouse/models:$GZ_SIM_RESOURCE_PATH`
  귀찮으면 `<uri>file:///절대/경로/warehouse.glb</uri>` 로 절대 경로를 써도 된다.

---

## 3. 변환값 (TX, TY, TYAW) 구하기

지도와 `.glb` 양쪽에서 **같은 물리적 지점 두 곳**을 찾는다. 서로 먼 벽 모서리 두 개가 좋다.

**지도 쪽** — 픽셀을 눈으로 찾고 위 공식으로 세계 좌표를 낸다.

```bash
python3 - <<'PY'
import yaml
from pathlib import Path
from PIL import Image
m = Path("control_ui/rmf_control_ui/data/rmf_maps")
d = yaml.safe_load((m / "new_map_2.yaml").read_text())
im = Image.open(m / d["image"]).convert("L"); W, H = im.size
px = list(im.getdata()); r = float(d["resolution"]); ox, oy = map(float, d["origin"][:2])
print("   " + "".join(str(c % 10) for c in range(W)))
for row in range(H):
    print(f"{row:3d}" + "".join("." if px[row*W+c] > 200 else "#" for c in range(W)))
print(f"\n픽셀(row, col) -> x = {ox} + (col+0.5)*{r},  y = {oy} + ({H-1}-row+0.5)*{r}")
PY
```

**`.glb` 쪽** — 같은 모서리의 정점 좌표를 읽는다.

```bash
pip install trimesh
python3 -c "
import trimesh
s = trimesh.load('warehouse.glb')
print('경계상자:', s.bounds)          # 방 크기가 2.19 x 2.67 m 인지 여기서 확인
print('크기:', s.extents)
"
```

**두 대응점에서 변환을 푼다.** 회전과 평행이동만 있고 축척은 1 이어야 한다.

```bash
python3 - <<'PY'
import math
# 같은 물리적 모서리 두 곳. (지도 좌표), (glb 좌표)
A_map, A_glb = (0.10, 1.05), (0.00, 0.00)     # <- 실제 값으로 바꾼다
B_map, B_glb = (1.90, -1.35), (1.80, -2.40)   # <- 실제 값으로 바꾼다

dm = (B_map[0]-A_map[0], B_map[1]-A_map[1])
dg = (B_glb[0]-A_glb[0], B_glb[1]-A_glb[1])
scale = math.hypot(*dm) / math.hypot(*dg)
yaw = math.atan2(dm[1], dm[0]) - math.atan2(dg[1], dg[0])
c, s = math.cos(yaw), math.sin(yaw)
tx = A_map[0] - (A_glb[0]*c - A_glb[1]*s)
ty = A_map[1] - (A_glb[0]*s + A_glb[1]*c)
print(f"축척 {scale:.4f}   <- 1.000 에서 멀면 .glb 단위가 다르다 (mm 이면 0.001)")
print(f"<pose>{tx:.4f} {ty:.4f} 0 0 0 {yaw:.4f}</pose>")
PY
```

축척이 1 이 아니면 SDF 의 `<mesh><scale>` 로 맞추거나 Blender 에서 미리 고친다.
**축척을 먼저 맞추고 나서** 회전·평행이동을 다시 푼다.

---

## 4. 올려서 돌리기

`PINKY_WORLD` 가 환경변수라 저장소 파일을 고칠 필요가 없다.

```bash
cp control_tower/bringup/p0_world.sdf /tmp/p0_world_warehouse.sdf
# /tmp/p0_world_warehouse.sdf 의 </world> 바로 위에 2절의 <model> 을 넣는다

export GZ_SIM_RESOURCE_PATH=$HOME/Trihouse/models:$GZ_SIM_RESOURCE_PATH
PINKY_WORLD=/tmp/p0_world_warehouse.sdf scripts/p0_up.sh
```

## 5. 정합 검증 — 이게 판정이다

눈으로 겹쳐 보는 것으로는 부족하다. 라이다가 보는 벽과 지도의 벽을 빔마다 견준다.

```bash
source install/setup.bash
python3 scripts/p0_check_world_alignment.py --robot pinky_01
```

```
  중앙값 오차 0.021 m
  0.05 m 안에 든 빔 96.3 %
정합됨. 지도의 벽과 세계의 벽이 같은 자리에 있습니다.
```

- **90 % 이상** — 정합. 그대로 쓴다.
- **60~90 %** — 회전은 맞고 평행이동이 남았다. `<pose>` 의 x y 를 조금씩 옮긴다.
- **60 % 미만** — 회전이나 축척이 틀렸다. 3절로 돌아간다.

**로봇을 서로 다른 세 자리로 옮겨 가며 돌린다.** 한 자리에서 맞는 건 우연일 수 있지만,
떨어진 세 자리에서 맞으면 회전과 평행이동이 모두 맞았다는 뜻이다.

---

## 6. 순서가 중요하다

```
  .glb 정합  ──▶  협로 실측  ──▶  존 표 작성  ──▶  사이클 주행
     (이 문서)      (노트북)      (config/)
```

**정합이 먼저다.** 벽이 없는 세계에서 협로를 재는 것은 허공을 재는 것이다. 지금
`config/narrow_zones.new_map_2.yaml` 이 없는 이유도 이것이다 — 잴 대상이 아직 없다.
