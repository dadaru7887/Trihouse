#!/usr/bin/env python3
"""Collect a project runner's combined output without stdio buffering."""

from __future__ import annotations

import argparse
import os
import re
import sys


ERROR = re.compile(r"ERROR|error:|Error|Traceback|Warning|WARN|없는 파일|실패")
TIMESTAMP = re.compile(r"\[[0-9]+\.[0-9]+\]")
EMPTY_PREFIX = re.compile(r"^\[[^]]+\] *$")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--err", required=True)
    parser.add_argument("--max-mb", type=int, default=200)
    args = parser.parse_args()

    limit = max(1, args.max_mb) * 1024 * 1024
    size = os.path.getsize(args.out) if os.path.exists(args.out) else 0
    previous = None
    duplicates = 0

    # Open both files before reading. A running collector is therefore visible even
    # when its producers are temporarily quiet.
    output = open(args.out, "a", encoding="utf-8", buffering=1)
    errors = open(args.err, "a", encoding="utf-8", buffering=1)

    def write(text: str) -> None:
        nonlocal output, size
        encoded_size = len(text.encode("utf-8")) + 1
        if size + encoded_size > limit:
            output.close()
            rotated = args.out + ".1"
            try:
                os.replace(args.out, rotated)
            except FileNotFoundError:
                pass
            output = open(args.out, "a", encoding="utf-8", buffering=1)
            banner = f"=== 로그가 {args.max_mb}MB 를 넘어 {rotated} 로 밀었다 ==="
            output.write(banner + "\n")
            size = len(banner.encode("utf-8")) + 1
        output.write(text + "\n")
        size += encoded_size

    def flush_duplicates() -> None:
        nonlocal duplicates
        if duplicates:
            write(f"  ↑ 같은 줄 {duplicates}번 더")
            duplicates = 0

    try:
        for raw in sys.stdin:
            line = raw.rstrip("\r\n")
            if EMPTY_PREFIX.fullmatch(line):
                continue
            signature = TIMESTAMP.sub("[time]", line)
            if signature == previous:
                duplicates += 1
                if duplicates % 100000 == 0:
                    write(f"  ↑ 같은 줄 {duplicates}번째, 계속 접는 중")
                continue
            flush_duplicates()
            write(line)
            previous = signature
            if ERROR.search(line):
                errors.write(line + "\n")
    finally:
        flush_duplicates()
        output.close()
        errors.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
