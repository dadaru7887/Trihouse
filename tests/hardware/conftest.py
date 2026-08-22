"""실물 motion 테스트는 명시적인 pytest 옵션 없이는 수집돼도 실행되지 않는다."""


def pytest_addoption(parser):
    group = parser.getgroup("trihouse-hardware-motion")
    group.addoption("--enable-motion", action="store_true", default=False)
    group.addoption("--enable-full-stack", action="store_true", default=False)
    group.addoption("--robot-namespace", default="")
    group.addoption("--destination", default="")
    group.addoption("--fms-url", default="http://127.0.0.1:8080")
    group.addoption("--full-stack-timeout", type=float, default=300.0)
    group.addoption(
        "--phase",
        choices=("enter", "exit", "roundtrip"),
        default="enter",
    )
    # 세 온도 구역 순회 주행 전용 옵션.
    group.addoption("--device-id", default="PK_01")
    group.addoption(
        "--narrow-zones-file",
        default="config/narrow_zones.new_map_2.yaml",
        help="주행 gate가 읽을 협로 표. 도킹 실측 전에는 zone_tour 표를 쓴다",
    )
    group.addoption("--narrow-map-name", default="new_map_2")
    group.addoption(
        "--zone-items",
        default="",
        help="ambient=SKU-...,chilled=SKU-...,frozen=SKU-... (비우면 기본 품목)",
    )
    group.addoption("--packing-worker", default="W-FIELD-01")
    group.addoption("--tour-artifacts", default="artifacts/zone_tour")
