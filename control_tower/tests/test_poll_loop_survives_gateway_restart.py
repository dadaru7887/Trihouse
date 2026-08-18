"""관제 노드는 Gateway 재배포를 견뎌야 한다.

Gateway 는 빌드 이미지이므로 코드가 바뀌면 재시작한다. 그 순간 진행 중인 HTTP 가
`Connection reset by peer` 나 `Broken pipe` 로 끊긴다. 그 예외가 poll 루프 밖으로
전파되면 프로세스가 죽고, 주문은 `queued` 에서 멈춘다.

2026-08-19 에 실제로 `job_runner` 와 `executor_worker` 가 그렇게 죽었고
`rmf_gateway_worker` 만 살아남았다 — 커밋 `4d1f3c4f` 가 그쪽에만 내성을 넣었다.
운영 중 Gateway 재배포는 언제든 일어나므로 셋 다 견뎌야 한다.
"""

from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
NODES = {
    "job_runner": ROOT / "task_manager" / "job_runner_node.py",
    "executor_worker": ROOT / "task_manager" / "executor_worker_node.py",
    "rmf_gateway_worker": ROOT / "rmf_adapter" / "rmf_gateway_worker_node.py",
}


def _poll_loop(path: Path) -> str:
    source = path.read_text(encoding="utf-8")
    return source.split("def run_poll_loop(")[1].split("\ndef ")[0]


@pytest.mark.parametrize("name", sorted(NODES))
def test_poll_loop_does_not_die_on_a_gateway_error(name: str) -> None:
    loop = _poll_loop(NODES[name])

    run_once = loop.index("run_once(")
    guard = loop.find("except Exception")

    assert guard != -1, f"{name}: run_once 를 감싸는 except 가 없다 — 재시작에 죽는다"
    assert loop.index("try:") < run_once, f"{name}: run_once 가 try 밖에 있다"
