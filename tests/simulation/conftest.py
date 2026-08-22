"""협로 시뮬레이션은 명시적 옵션 없이는 Gazebo 로봇을 움직이지 않는다."""


def pytest_addoption(parser):
    group = parser.getgroup("trihouse-simulation-motion")
    group.addoption("--enable-sim-motion", action="store_true", default=False)
    group.addoption("--sim-robot-namespace", default="pinky_01")
    group.addoption(
        "--sim-destination",
        default="frozen_storage_loading_dock_01",
    )
    group.addoption(
        "--sim-phase",
        choices=("enter", "exit", "roundtrip"),
        default="roundtrip",
    )
