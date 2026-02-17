#!/usr/bin/env python3
"""Phase-1 SigPro consumer for normalized Signal events from SQLite queue.

Consumes events published by signal_inbound_collector.py and applies:
- New voice attachment -> transcribe + OOB auth flow
- 4-digit text code -> validate + execute pending transcript
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from signal_event_store import DEFAULT_DB, fetch_events, get_conn, get_offset, init_db, set_offset

VOICE_EXTENSIONS = {".m4a", ".opus", ".ogg", ".oga", ".aac", ".mp3", ".wav", ".webm"}
TARGET_USER = "+19412907826"
CODE_RE = re.compile(r"^\s*(\d{4})\s*$")

STATE_DIR = Path("/home/james/.openclaw/workspace-sigpro/.openclaw")
PENDING_FILE = STATE_DIR / "pending_transcript.json"
AUTH_FAILURE_LOG = STATE_DIR / "auth_failures.log"

TRANSCRIBE_SCRIPT = Path("/home/james/.openclaw/workspace-sigpro/scripts/transcribe_elevenlabs.py")
AUTH_SCRIPT = Path("/home/james/.openclaw/workspace-sigpro/scripts/auth_manager.py")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="SigPro consumer for normalized Signal event stream")
    p.add_argument("--db", default=str(DEFAULT_DB), help="SQLite DB path")
    p.add_argument("--consumer", default="sigpro-main", help="Consumer offset name")
    p.add_argument("--limit", type=int, default=100, help="Max events to process this run")
    return p.parse_args()


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True)


def _send_message(channel: str, target: str, text: str) -> bool:
    proc = _run([
        "openclaw",
        "message",
        "send",
        "--channel",
        channel,
        "--target",
        target,
        "--message",
        text,
    ])
    return proc.returncode == 0


def _log_auth_failure(reason: str, code: str | None = None, message_id: str | None = None) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    entry = {"ts": int(time.time()), "reason": reason, "code": code, "message_id": message_id}
    with AUTH_FAILURE_LOG.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def _transcribe(path: Path) -> str | None:
    proc = _run(["python3", str(TRANSCRIBE_SCRIPT), str(path)])
    if proc.returncode != 0:
        return None
    out_path = Path(proc.stdout.strip())
    if not out_path.exists():
        return None
    text = out_path.read_text().strip()
    return text or None


def _generate_auth_code() -> str | None:
    proc = _run(["python3", str(AUTH_SCRIPT), "generate"])
    code = proc.stdout.strip()
    if proc.returncode != 0 or not re.fullmatch(r"\d{4}", code):
        return None
    return code


def _validate_code(code: str) -> tuple[bool, str]:
    proc = _run(["python3", str(AUTH_SCRIPT), "validate", code])
    if proc.returncode != 0:
        return False, "Internal validation error."
    try:
        payload = json.loads(proc.stdout.strip())
    except json.JSONDecodeError:
        return False, "Internal validation parse error."
    return bool(payload.get("ok")), str(payload.get("message") or "Invalid code.")


def _extract_text_candidates(obj: Any) -> list[str]:
    out: list[str] = []

    def walk(v: Any) -> None:
        if isinstance(v, dict):
            for k in ("final", "reply", "text", "message", "content", "output"):
                val = v.get(k)
                if isinstance(val, str) and val.strip():
                    out.append(val.strip())
            for _, child in v.items():
                walk(child)
        elif isinstance(v, list):
            for item in v:
                walk(item)

    walk(obj)
    # preserve order, remove duplicates
    dedup: list[str] = []
    seen: set[str] = set()
    for s in out:
        if s not in seen:
            seen.add(s)
            dedup.append(s)
    return dedup


def _best_assistant_text(payload: dict[str, Any]) -> str:
    # Prefer top-level canonical fields first.
    for k in ("final", "reply", "text", "message"):
        v = payload.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()

    # Then scan nested payload for any textual content.
    candidates = _extract_text_candidates(payload)
    for c in candidates:
        if c.lower() not in {"execution completed.", "execution completed"}:
            return c

    return candidates[0] if candidates else ""


def _execute_in_main(transcript: str) -> str:
    text = f"SigPro Authorized Signal Voice Request:\n{transcript}"
    proc = _run([
        "openclaw", "agent",
        "--agent", "main",
        "--message", text,
        "--json",
        "--timeout", "120",
    ])
    if proc.returncode != 0:
        return "Execution was triggered, but no assistant output was returned."

    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return "Execution completed, but assistant output could not be parsed."

    assistant_text = _best_assistant_text(payload)
    if not assistant_text:
        return "Execution completed, but no assistant text was returned."

    return assistant_text[:3000]


def _store_pending_transcript(transcript: str, source_file: str, source_message_id: str | None) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "transcript": transcript,
        "source_file": source_file,
        "source_message_id": source_message_id,
        "created_at": int(time.time()),
        "expires_in_sec": 300,
    }
    PENDING_FILE.write_text(json.dumps(payload, indent=2))


def handle_voice_event(row) -> None:
    attachments = json.loads(row["attachments_json"])
    if not attachments:
        return

    # only one pending request at a time in phase-1
    if PENDING_FILE.exists():
        return

    for a in attachments:
        path = a.get("path")
        filename = a.get("filename") or ""
        suffix = Path(filename).suffix.lower() if filename else Path(path or "").suffix.lower()
        if suffix not in VOICE_EXTENSIONS:
            continue
        if not path or not Path(path).exists():
            continue

        transcript = _transcribe(Path(path))
        if not transcript:
            return

        code = _generate_auth_code()
        if not code:
            _log_auth_failure("code_generation_failed", message_id=row["source_message_id"])
            return

        _store_pending_transcript(transcript, filename or Path(path).name, row["source_message_id"])
        _send_message("whatsapp", TARGET_USER, f"SigPro Auth Code: {code} (Valid for 5 mins for your Signal voice request)")
        _send_message("signal", TARGET_USER, "Voice request transcribed. Please enter the 4-digit code sent to your WhatsApp to authorize execution.")
        return


def handle_code_event(row) -> None:
    if not PENDING_FILE.exists():
        return

    msg = json.loads(row["message_json"])
    text = str(msg.get("text") or "")
    m = CODE_RE.match(text)
    if not m:
        return

    code = m.group(1)
    ok, reason = _validate_code(code)
    if not ok:
        _log_auth_failure(reason, code=code, message_id=row["source_message_id"])
        _send_message("signal", TARGET_USER, f"Auth failed: {reason}")
        return

    try:
        pending = json.loads(PENDING_FILE.read_text())
        transcript = str(pending.get("transcript") or "").strip()
    except Exception:
        transcript = ""

    if not transcript:
        _log_auth_failure("pending_transcript_missing_or_invalid", code=code, message_id=row["source_message_id"])
        _send_message("signal", TARGET_USER, "Auth accepted, but no pending transcript was found.")
        return

    summary = _execute_in_main(transcript)
    formatted = (
        "✅ SigPro request authorized and executed\n\n"
        f"🗣️ Request:\n{transcript[:500]}\n\n"
        f"🤖 Assistant Output:\n{summary}"
    )
    _send_message("signal", TARGET_USER, formatted[:3500])
    PENDING_FILE.unlink(missing_ok=True)


def is_from_target_sender(row) -> bool:
    sender = json.loads(row["sender_json"])
    sid = str(sender.get("id") or "").strip()
    # Strict scope: only process messages where sender is the configured self user.
    return sid == TARGET_USER


def main() -> int:
    args = parse_args()
    conn = get_conn(Path(args.db))
    init_db(conn)

    offset = get_offset(conn, args.consumer)
    rows = fetch_events(conn, offset, limit=args.limit)

    for row in rows:
        if not is_from_target_sender(row):
            set_offset(conn, args.consumer, row["id"])
            continue

        handle_voice_event(row)
        handle_code_event(row)
        set_offset(conn, args.consumer, row["id"])

    print(json.dumps({"processed": len(rows), "last_offset": get_offset(conn, args.consumer)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
