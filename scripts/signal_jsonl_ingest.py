#!/usr/bin/env python3
"""Append normalized/raw Signal inbound JSON events to shared JSONL ingress file.

Use this as the single append point from any upstream bridge.
It enforces atomic append with a file lock to avoid line corruption.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

STATE_DIR = Path("/home/james/.openclaw/workspace-sigpro/.openclaw")
RAW_JSONL = STATE_DIR / "signal_inbound_raw.jsonl"
LOCK_FILE = STATE_DIR / "signal_inbound_raw.write.lock"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Append Signal inbound JSON objects to JSONL")
    p.add_argument("--in-file", help="Read JSON/JSONL from file instead of stdin")
    p.add_argument("--out", default=str(RAW_JSONL), help="Output JSONL file")
    return p.parse_args()


def lock_fd(path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    import fcntl

    fcntl.flock(fd, fcntl.LOCK_EX)
    return fd


def parse_input_text(text: str):
    text = text.strip()
    if not text:
        return []

    # Try whole-document JSON first.
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return [obj]
        if isinstance(obj, list):
            return [x for x in obj if isinstance(x, dict)]
    except json.JSONDecodeError:
        pass

    # Fallback: JSONL
    out = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        try:
            obj = json.loads(s)
            if isinstance(obj, dict):
                out.append(obj)
        except json.JSONDecodeError:
            continue
    return out


def main() -> int:
    args = parse_args()
    if args.in_file:
        text = Path(args.in_file).read_text(encoding="utf-8")
    else:
        text = sys.stdin.read()

    objs = parse_input_text(text)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    fd = lock_fd(LOCK_FILE)
    _ = fd
    with out_path.open("a", encoding="utf-8") as f:
        for obj in objs:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")

    print(json.dumps({"appended": len(objs), "out": str(out_path)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
