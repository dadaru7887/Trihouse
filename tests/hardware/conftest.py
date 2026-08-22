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
