#!/usr/bin/env python3
"""Phase-1 Signal inbound collector (singleton) -> normalized SQLite event stream.

Default mode reads incremental JSONL from:
  .openclaw/signal_inbound_raw.jsonl
and tracks byte offset in:
  .openclaw/signal_inbound_raw.offset

Input modes:
1) --stdin-jsonl              : read JSON lines from stdin (single pass)
2) --in-file-jsonl <path>     : read JSONL file (incremental with offset)
3) --follow                   : keep running and poll for new lines
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Iterator

from signal_event_store import DEFAULT_DB, get_conn, init_db, publish_event

STATE_DIR = Path("/home/james/.openclaw/workspace-sigpro/.openclaw")
LOCK_PATH = STATE_DIR / "signal_inbound.lock"
DEFAULT_RAW_JSONL = STATE_DIR / "signal_inbound_raw.jsonl"
DEFAULT_OFFSET_FILE = STATE_DIR / "signal_inbound_raw.offset"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Signal inbound collector skeleton")
    p.add_argument("--db", default=str(DEFAULT_DB), help="SQLite DB path")
    p.add_argument("--stdin-jsonl", action="store_true", help="Read inbound events from stdin JSONL")
    p.add_argument("--in-file-jsonl", default=str(DEFAULT_RAW_JSONL), help="Read inbound events from JSONL file")
    p.add_argument("--offset-file", default=str(DEFAULT_OFFSET_FILE), help="Cursor file (byte offset for --in-file-jsonl)")
    p.add_argument("--follow", action="store_true", help="Follow file for new events")
    p.add_argument("--poll-ms", type=int, default=1500, help="Follow poll interval in ms")
    p.add_argument("--account", default="", help="Signal account identifier (optional)")
    return p.parse_args()


def acquire_lock_or_exit(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("collector already running (lock held)", file=sys.stderr)
        sys.exit(1)
    return fd


def read_offset(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        return int(path.read_text().strip() or "0")
    except Exception:
        return 0


def write_offset(path: Path, value: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(int(value)))


def stable_event_id(raw_obj: dict[str, Any]) -> str:
    src_id = str(raw_obj.get("source_message_id") or raw_obj.get("id") or "")
    ts = str(raw_obj.get("received_at") or raw_obj.get("timestamp") or int(time.time()))
    sender = str((raw_obj.get("sender") or {}).get("id") or raw_obj.get("sender_id") or "")
    text = str((raw_obj.get("message") or {}).get("text") or raw_obj.get("text") or "")
    seed = "|".join([src_id, ts, sender, text])
    if seed == "|||":
        seed = json.dumps(raw_obj, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def normalize(raw_obj: dict[str, Any], account: str = "") -> dict[str, Any]:
    now = int(time.time())
    message_obj = raw_obj.get("message") if isinstance(raw_obj.get("message"), dict) else {}
    sender_obj = raw_obj.get("sender") if isinstance(raw_obj.get("sender"), dict) else {}
    chat_obj = raw_obj.get("chat") if isinstance(raw_obj.get("chat"), dict) else {}
    attachments = raw_obj.get("attachments") if isinstance(raw_obj.get("attachments"), list) else []

    return {
        "event_id": stable_event_id(raw_obj),
        "source": "signal",
        "account": account or raw_obj.get("account"),
        "received_at": int(raw_obj.get("received_at") or raw_obj.get("timestamp") or now),
        "source_message_id": raw_obj.get("source_message_id") or raw_obj.get("id"),
        "chat": {
            "type": chat_obj.get("type") or raw_obj.get("chat_type") or "direct",
            "id": chat_obj.get("id") or raw_obj.get("chat_id") or "",
            "name": chat_obj.get("name") or raw_obj.get("chat_name"),
        },
        "sender": {
            "id": sender_obj.get("id") or raw_obj.get("sender_id") or raw_obj.get("source"),
            "name": sender_obj.get("name") or raw_obj.get("sender_name"),
        },
        "message": {
            "text": message_obj.get("text") or raw_obj.get("text") or "",
            "is_edit": bool(message_obj.get("is_edit") or raw_obj.get("is_edit")),
            "is_delete": bool(message_obj.get("is_delete") or raw_obj.get("is_delete")),
        },
        "attachments": attachments,
        "raw": {"provider_payload": raw_obj},
    }


def iter_jsonl_from_stdin() -> Iterator[dict[str, Any]]:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                yield obj
        except json.JSONDecodeError:
            print(f"invalid JSONL line skipped: {line[:120]}", file=sys.stderr)


def ingest_file_once(path: Path, offset_path: Path) -> tuple[list[dict[str, Any]], int]:
    if not path.exists():
        return [], read_offset(offset_path)

    offset = read_offset(offset_path)
    size = path.stat().st_size
    if offset > size:
        offset = 0  # file rotated/truncated

    out: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        f.seek(offset)
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    out.append(obj)
            except json.JSONDecodeError:
                print(f"invalid JSONL line skipped: {line[:120]}", file=sys.stderr)
        new_offset = f.tell()

    write_offset(offset_path, new_offset)
    return out, new_offset


def main() -> int:
    args = parse_args()
    _lock_fd = acquire_lock_or_exit(LOCK_PATH)

    conn = get_conn(Path(args.db))
    init_db(conn)

    published = 0
    duplicates = 0

    if args.stdin_jsonl:
        for raw_obj in iter_jsonl_from_stdin():
            event = normalize(raw_obj, account=args.account)
            if publish_event(conn, event):
                published += 1
            else:
                duplicates += 1
        print(json.dumps({"published": published, "duplicates": duplicates}))
        return 0

    in_path = Path(args.in_file_jsonl)
    offset_path = Path(args.offset_file)

    while True:
        batch, _ = ingest_file_once(in_path, offset_path)
        for raw_obj in batch:
            event = normalize(raw_obj, account=args.account)
            if publish_event(conn, event):
                published += 1
            else:
                duplicates += 1

        if not args.follow:
            break
        time.sleep(max(0.2, args.poll_ms / 1000.0))

    print(json.dumps({"published": published, "duplicates": duplicates}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
