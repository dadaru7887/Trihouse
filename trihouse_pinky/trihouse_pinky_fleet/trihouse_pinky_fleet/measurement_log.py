"""POC 측정값을 실행별 JSONL 파일로 안전하게 기록한다."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping


_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _validate_token(value: str, field: str) -> str:
    if not _SAFE_TOKEN.fullmatch(value):
        raise ValueError(f"unsafe {field}: {value!r}")
    return value


class MeasurementLogWriter:
    """로봇 제어 흐름과 분리된 best-effort JSONL 기록기."""

    def __init__(
        self,
        *,
        root: str | Path | None = None,
        run_id: str | None = None,
        component: str,
        enabled: bool = True,
    ) -> None:
        self.root = Path(root) if root is not None else (
            Path.home() / ".ros" / "trihouse" / "measurements"
        )
        default_run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.run_id = _validate_token(run_id or default_run_id, "run_id")
        self.component = _validate_token(component, "component")
        self.enabled = enabled

    @classmethod
    def from_environment(
        cls, *, component: str, enabled: bool = True
    ) -> "MeasurementLogWriter":
        return cls(
            root=os.environ.get("TRIHOUSE_MEASUREMENT_LOG_ROOT"),
            run_id=os.environ.get("TRIHOUSE_MEASUREMENT_RUN_ID"),
            component=component,
            enabled=enabled,
        )

    def write(self, stream: str, record: Mapping[str, object]) -> bool:
        """한 레코드를 추가한다. 저장 실패는 ``False``로만 알린다."""
        _validate_token(stream, "stream")
        if not self.enabled:
            return True

        run_directory = self.root / self.run_id
        try:
            run_directory.mkdir(parents=True, exist_ok=True)
            self._write_metadata_once(run_directory)
            payload = dict(record)
            payload.update(
                {
                    "schema_version": 1,
                    "recorded_at": _utc_now(),
                    "run_id": self.run_id,
                    "record_type": stream,
                }
            )
            with (run_directory / f"{stream}.jsonl").open(
                "a", encoding="utf-8"
            ) as output:
                output.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
                output.write("\n")
                output.flush()
        except (OSError, TypeError, ValueError):
            return False
        return True

    def _write_metadata_once(self, run_directory: Path) -> None:
        metadata_path = run_directory / "run_metadata.json"
        if metadata_path.exists():
            return
        metadata = {
            "schema_version": 1,
            "created_at": _utc_now(),
            "run_id": self.run_id,
            "component": self.component,
        }
        try:
            with metadata_path.open("x", encoding="utf-8") as output:
                json.dump(metadata, output, ensure_ascii=False, indent=2, sort_keys=True)
                output.write("\n")
        except FileExistsError:
            # Pinky와 Control Tower가 같은 run을 동시에 시작할 수 있다.
            return
