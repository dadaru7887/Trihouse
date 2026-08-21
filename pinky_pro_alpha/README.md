# Pinky Pro Alpha overlay

Trihouse에서 실측한 지도와 Nav2 설정만 관리하는 오버레이이다. 공식 Pinky Pro
소스 전체를 복사하지 않으므로 upstream 이력과 Trihouse 변경 범위가 섞이지 않는다.

공식 소스는 <https://github.com/pinklab-art/pinky_pro.git>이다. Raspberry Pi에서
Trihouse 저장소 루트를 `/home/<user>/Trihouse`로 정했다면 공식 소스는 다음 위치에
둔다.

```bash
cd /home/<user>/Trihouse
git submodule update --init pinky_pro
```

Trihouse 저장소 없이 공식 소스를 별도로 다시 받는 경우에도 목적지는 동일하다.

```bash
git clone https://github.com/pinklab-art/pinky_pro.git /home/<user>/Trihouse/pinky_pro
```

오버레이를 적용한다. 이 명령은 네트워크를 사용하거나 원격 저장소를 갱신하지 않고,
명시된 checkout의 지도와 parameter 파일만 덮어쓴다.

```bash
cd /home/<user>/Trihouse
./scripts/apply_pinky_pro_alpha ./pinky_pro
```

LiDAR driver는 [vendor/sllidar_ros2.gitref](vendor/sllidar_ros2.gitref)의 URL과
commit을 사용해 `pinky_pro/sllidar_ros2`에 별도로 checkout한다. 그 뒤 의존성을
설치하고 빌드한다.

```bash
cd /home/<user>/Trihouse/pinky_pro
rosdep install --from-paths . --ignore-src -r -y
colcon build --symlink-install
source install/setup.bash
```

실물 ROS 2 통신 전에는 Pinky Pi와 관제/추론 PC 모두 같은 domain을 사용한다.
따옴표 없이 다음 값을 shell 환경 또는 역할별 `.env`에 설정한다.

```bash
export ROS_DOMAIN_ID=12
```

DB command ID는 `PK_01`, `PK_02`이고 ROS namespace는 각각 `pinky_01`,
`pinky_02`다. 두 값은 용도가 다르므로 adapter 설정에서 명시적으로 대응시킨다.

`build/`, `install/`, `log/`, `.bak` 파일은 오버레이에 넣지 않는다. 공식 소스를
갱신할 때는 깨끗한 checkout에서 오버레이 테스트를 먼저 실행하고, 충돌이 없는
것을 확인한 뒤 새 upstream revision을 기록한다. 공식 저장소의 라이선스와 각
third-party package의 라이선스 파일은 원본 checkout에 그대로 유지한다.
