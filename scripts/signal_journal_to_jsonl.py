#!/usr/bin/env python3
"""Bridge Signal daemon journald logs -> normalized-ish JSONL ingress.

Reads new logs from signal-cli-daemon.service using journal cursor state and emits
JSON objects to .openclaw/signal_inbound_raw.jsonl via signal_jsonl_ingest.py.

Designed for Phase-1 reliability without opening another signal-cli receive process.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

STATE_DIR = Path("/home/james/.openclaw/workspace-sigpro/.openclaw")
CURSOR_FILE = STATE_DIR / "signal_journal.cursor"
TMP_JSON_FILE = STATE_DIR / "signal_journal_batch.json"
INGEST_SCRIPT = Path("/home/james/.openclaw/workspace-sigpro/scripts/signal_jsonl_ingest.py")

ENVELOPE_RE = re.compile(r"Envelope from: .*?\s(\+\d+)\s\(device:\s*(\d+)\)")
TS_RE = re.compile(r"Timestamp:\s*(\d+)")
BODY_RE = re.compile(r"\s*Body:\s*(.*)")
ATTACH_ID_RE = re.compile(r"\s*Id:\s*(\S+)")
ATTACH_FILE_RE = re.compile(r"\s*Filename:\s*(.*)")
ATTACH_MIME_RE = re.compile(r"\s*Content-Type:\s*(.*)")
ATTACH_PATH_RE = re.compile(r"\s*Stored plaintext in:\s*(.*)")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Ingest signal-cli journald messages into JSONL")
    p.add_argument("--unit", default="signal-cli-daemon.service")
    p.add_argument("--cursor-file", default=str(CURSOR_FILE))
    p.add_argument("--limit", type=int, default=400)
    return p.parse_args()


def read_cursor(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text().strip()


def write_cursor(path: Path, cursor: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(cursor)


def run_journal(unit: str, cursor: str, limit: int) -> list[dict]:
    cmd = ["journalctl", "--user", "-u", unit, "-o", "json", "-n", str(limit), "--no-pager"]
    if cursor:
        cmd = ["journalctl", "--user", "-u", unit, "-o", "json", "--after-cursor", cursor, "-n", str(limit), "--no-pager"]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return []

    out = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        out.append(obj)
    return out


def parse_events(entries: list[dict]) -> tuple[list[dict], str]:
    events: list[dict] = []
    current: dict | None = None
    last_cursor = ""

    def flush():
        nonlocal current
        if not current:
            return
        if current.get("source_message_id"):
            events.append(current)
        current = None

    for e in entries:
        last_cursor = e.get("__CURSOR") or last_cursor
        msg = str(e.get("MESSAGE") or "")

        m_env = ENVELOPE_RE.search(msg)
        if m_env:
            # envelope starts context but we wait for timestamp to finalize event id
            if current and current.get("source_message_id"):
                flush()
            current = {
                "sender": {"id": m_env.group(1)},
                "message": {"text": ""},
                "attachments": [],
            }
            continue

        m_ts = TS_RE.search(msg)
        if m_ts:
            if current and current.get("source_message_id"):
                flush()
            if not current:
                current = {"sender": {"id": ""}, "message": {"text": ""}, "attachments": []}
            ts = int(m_ts.group(1))
            current["timestamp"] = ts
            current["id"] = str(ts)
            current["source_message_id"] = str(ts)
            continue

        if not current:
            continue

        m_body = BODY_RE.search(msg)
        if m_body:
            current["message"]["text"] = m_body.group(1).strip()
            continue

        if "Attachments:" in msg:
            continue

        m_id = ATTACH_ID_RE.search(msg)
        if m_id:
            current["attachments"].append({"id": m_id.group(1)})
            continue

        m_fn = ATTACH_FILE_RE.search(msg)
        if m_fn and current["attachments"]:
            current["attachments"][-1]["filename"] = m_fn.group(1).strip()
            continue

        m_mt = ATTACH_MIME_RE.search(msg)
        if m_mt and current["attachments"]:
            current["attachments"][-1]["mime_type"] = m_mt.group(1).strip()
            continue

        m_path = ATTACH_PATH_RE.search(msg)
        if m_path and current["attachments"]:
            current["attachments"][-1]["path"] = m_path.group(1).strip()
            continue

    flush()
    return events, last_cursor


def main() -> int:
    args = parse_args()
    cursor_path = Path(args.cursor_file)
    cursor = read_cursor(cursor_path)

    entries = run_journal(args.unit, cursor, args.limit)
    if not entries:
        return 0

    events, last_cursor = parse_events(entries)
    if last_cursor:
        write_cursor(cursor_path, last_cursor)

    if not events:
        return 0

    TMP_JSON_FILE.parent.mkdir(parents=True, exist_ok=True)
    TMP_JSON_FILE.write_text(json.dumps(events, ensure_ascii=False))
    proc = subprocess.run(["python3", str(INGEST_SCRIPT), "--in-file", str(TMP_JSON_FILE)])
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
