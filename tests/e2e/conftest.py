"""P0 인수 e2e가 쓰는 공용 fixture.

e2e는 `db/migrations/001_physical_v1_baseline.sql` + `db/seeds/seed_dev.sql`을 매번 다시 만들고, UI가 쓰는
것과 **같은** 공개 API로 주문을 넣는다. 실제 MySQL이 없으면 조용히 통과하지
않고 건너뛴다.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
GATEWAY_TESTS = ROOT / "fms_gateway" / "tests"

# 게이트웨이 통합 헬퍼(`install_active_map`, `real_client` 등)를 그대로 쓴다.
for entry in (HERE, GATEWAY_TESTS / "integration", GATEWAY_TESTS, ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))


def _load_gateway_conftest():
    """저장소 루트 conftest와 이름이 겹치므로 경로로 직접 적재한다.

    전체 트리를 한 번에 수집하면 `conftest`라는 이름은 이미 루트
    `conftest.py`가 차지한다. 여기서는 게이트웨이 통합 fixture가 필요하므로
    고유한 이름으로 따로 적재한다.
    """
    name = "fms_gateway_tests_conftest"
    existing = sys.modules.get(name)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(name, GATEWAY_TESTS / "conftest.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    # 게이트웨이 통합 테스트 모듈이 `from conftest import ...` 로 찾을 수 있게
    # 같은 객체를 그 이름으로도 등록한다.
    sys.modules.setdefault("conftest", module)
    return module


_gateway_conftest = _load_gateway_conftest()

fresh_schema = _gateway_conftest.fresh_schema
mysql_db = _gateway_conftest.mysql_db
seeded_schema = _gateway_conftest.seeded_schema
mysql_connection = _gateway_conftest.mysql_connection
