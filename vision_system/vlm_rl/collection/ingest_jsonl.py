"""Bridge-neutral JSONL ingestion for Nav2/rule driving and recovery results."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from .collector import DriveDatasetCollector


def ingest(source: Path, dataset_dir: Path) -> int:
    collector = DriveDatasetCollector(dataset_dir)
    count = 0
    with source.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                envelope: dict[str, Any] = json.loads(line)
                kind = envelope["kind"]
                if kind == "navigation":
                    collector.record_navigation_event(envelope["event"])
                elif kind == "recovery_completion":
                    collector.record_recovery_completion(envelope["completion"])
                else:
                    raise ValueError("kind must be navigation or recovery_completion")
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
                raise ValueError(f"invalid input on line {line_number}: {error}") from error
            count += 1
    return count


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="JSONL event envelope file")
    parser.add_argument("--dataset-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    print(f"ingested {ingest(args.source, args.dataset_dir)} records", file=sys.stderr)


if __name__ == "__main__":
    main()

