#!/usr/bin/env python3
"""SigPro live loop: Signal voice ingestion + WhatsApp OOB auth + execution.

Run this script periodically (e.g., cron). Each run does:
1) If a new Signal attachment exists: transcribe, generate code, notify WhatsApp/Signal, store pending transcript.
2) Else, check for a new 4-digit Signal text code and validate.
3) On valid code: execute pending transcript against the main interpreter and send a concise Signal summary.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any

VOICE_EXTENSIONS = {".m4a", ".opus", ".ogg", ".oga", ".aac", ".mp3", ".wav", ".webm"}

ATTACHMENT_DIR = Path("/home/james/.local/share/signal-cli/attachments")
STATE_DIR = Path("/home/james/.openclaw/workspace-sigpro/.openclaw")
LAST_ATTACHMENT_FILE = STATE_DIR / "last_processed_attachment.txt"
LAST_SIGNAL_MSG_FILE = STATE_DIR / "last_processed_signal_message.txt"
PENDING_FILE = STATE_DIR / "pending_transcript.json"
AUTH_FAILURE_LOG = STATE_DIR / "auth_failures.log"

TRANSCRIBE_SCRIPT = Path("/home/james/.openclaw/workspace-sigpro/scripts/transcribe_elevenlabs.py")
AUTH_SCRIPT = Path("/home/james/.openclaw/workspace-sigpro/scripts/auth_manager.py")
DISPATCHER_SCRIPT = Path("/home/james/.openclaw/workspace/shared/signal_dispatcher.py")

TARGET_USER = "+19412907826"
# Strict reply-code format: exactly 4 digits, nothing else.
CODE_RE = re.compile(r"^([0-9]{4})$")


def _ensure_state_dir() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True)


def _read_text(path: Path) -> str:
    return path.read_text().strip() if path.exists() else ""


def _write_text(path: Path, value: str) -> None:
    _ensure_state_dir()
    path.write_text(value)


def _log_auth_failure(reason: str, code: str | None = None, message_id: str | None = None) -> None:
    _ensure_state_dir()
    entry = {
        "ts": int(time.time()),
        "reason": reason,
        "code": code,
        "message_id": message_id,
    }
    with AUTH_FAILURE_LOG.open("a") as f:
        f.write(json.dumps(entry) + "\n")


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


def _find_newest_unprocessed_attachment() -> Path | None:
    if not ATTACHMENT_DIR.exists():
        return None

    files = [
        p
        for p in ATTACHMENT_DIR.glob("*")
        if p.is_file() and p.suffix.lower() in VOICE_EXTENSIONS
    ]
    if not files:
        return None

    files.sort(key=lambda p: p.stat().st_mtime)
    last_name = _read_text(LAST_ATTACHMENT_FILE)

    if not last_name:
        # First run initialization: mark latest and do not process historical backlog.
        _write_text(LAST_ATTACHMENT_FILE, files[-1].name)
        return None

    # Return the first file after last processed (oldest-first progression).
    seen_last = False
    for p in files:
        if seen_last:
            return p
        if p.name == last_name:
            seen_last = True

    # If we found the last processed file and nothing newer exists, nothing to do.
    if seen_last:
        return None

    # If state points to deleted/unknown file, process only newest to avoid replay storms.
    return files[-1]


def _transcribe(attachment: Path) -> str | None:
    proc = _run(["python3", str(TRANSCRIBE_SCRIPT), str(attachment)])
    if proc.returncode != 0:
        return None

    txt_path = Path(proc.stdout.strip())
    if not txt_path.exists():
        return None

    text = txt_path.read_text().strip()
    return text or None


def _generate_auth_code() -> str | None:
    proc = _run(["python3", str(AUTH_SCRIPT), "generate"])
    code = proc.stdout.strip()
    if proc.returncode != 0 or not re.fullmatch(r"\d{4}", code):
        return None
    return code


def _store_pending_transcript(transcript: str, source_file: str) -> None:
    _ensure_state_dir()
    payload = {
        "transcript": transcript,
        "source_file": source_file,
        "created_at": int(time.time()),
        "expires_in_sec": 300,
    }
    PENDING_FILE.write_text(json.dumps(payload, indent=2))


def _process_new_voice_note() -> bool:
    voice_file = _find_newest_unprocessed_attachment()
    if not voice_file:
        return False

    transcript = _transcribe(voice_file)
    _write_text(LAST_ATTACHMENT_FILE, voice_file.name)
    if not transcript:
        return True

    code = _generate_auth_code()
    if not code:
        _log_auth_failure("code_generation_failed")
        return True

    _store_pending_transcript(transcript, voice_file.name)

    wa_text = f"SigPro Auth Code: {code} (Valid for 5 mins for your Signal voice request)"
    _send_message("whatsapp", TARGET_USER, wa_text)

    signal_text = (
        "Voice request transcribed. Please enter the 4-digit code sent to your "
        "WhatsApp to authorize execution."
    )
    _send_message("signal", TARGET_USER, signal_text)
    return True


def _extract_messages(payload: Any) -> list[dict[str, Any]]:
    # CLI payload shape varies by provider/runtime. Normalize to list[dict].
    if isinstance(payload, list):
        return [m for m in payload if isinstance(m, dict)]
    if isinstance(payload, dict):
        for key in ("messages", "items", "data", "results"):
            v = payload.get(key)
            if isinstance(v, list):
                return [m for m in v if isinstance(m, dict)]
    return []


def _read_latest_signal_code_message() -> tuple[str, str] | None:
    proc = _run([
        "python3",
        str(DISPATCHER_SCRIPT),
        "consume",
        "--consumer",
        "sigpro-auth-codes",
        "--channel",
        "signal",
        "--from",
        TARGET_USER,
        "--limit",
        "50",
    ])
    if proc.returncode != 0:
        return None

    try:
        payload = json.loads(proc.stdout.strip())
        events = payload.get("events", []) if isinstance(payload, dict) else []
    except json.JSONDecodeError:
        return None

    newest_code_msg: tuple[str, str] | None = None
    for ev in events:
        # Strict inbox scope: only self note-to-self style messages.
        sender = str(ev.get("from") or "").strip()
        target = str(ev.get("target") or "").strip()
        if sender != TARGET_USER:
            continue
        if target and target != TARGET_USER:
            continue

        msg_id = str(ev.get("id") or "").strip()
        text = str(ev.get("text") or "").strip()

        # Ignore anything that is not exactly ####.
        match = CODE_RE.match(text)
        if match and msg_id:
            newest_code_msg = (msg_id, match.group(1))

    return newest_code_msg


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
    dedup: list[str] = []
    seen: set[str] = set()
    for s in out:
        if s not in seen:
            seen.add(s)
            dedup.append(s)
    return dedup


def _best_assistant_text(payload: dict[str, Any]) -> str:
    for k in ("final", "reply", "text", "message"):
        v = payload.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()

    candidates = _extract_text_candidates(payload)
    for c in candidates:
        if c.lower() not in {"execution completed.", "execution completed"}:
            return c
    return candidates[0] if candidates else ""


def _execute_in_main(transcript: str) -> str:
    # Target the main interpreter session key directly via sessions send.
    text = f"SigPro Authorized Signal Voice Request:\n{transcript}"

    proc = _run([
        "openclaw",
        "agent",
        "--agent",
        "main",
        "--message",
        text,
        "--json",
        "--timeout",
        "120",
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


def _process_signal_auth_code() -> bool:
    # Only handle code entry if there is something pending.
    if not PENDING_FILE.exists():
        return False

    code_msg = _read_latest_signal_code_message()
    if not code_msg:
        return False

    message_id, code = code_msg
    ok, reason = _validate_code(code)
    if not ok:
        _log_auth_failure(reason=reason, code=code, message_id=message_id)
        _send_message("signal", TARGET_USER, f"Auth failed: {reason}")
        return True

    try:
        pending = json.loads(PENDING_FILE.read_text())
        transcript = str(pending.get("transcript") or "").strip()
    except Exception:
        transcript = ""

    if not transcript:
        _log_auth_failure(reason="pending_transcript_missing_or_invalid", code=code, message_id=message_id)
        _send_message("signal", TARGET_USER, "Auth accepted, but no pending transcript was found.")
        return True

    summary = _execute_in_main(transcript)
    formatted = (
        "✅ SigPro request authorized and executed\n\n"
        f"🗣️ Request:\n{transcript[:500]}\n\n"
        f"🤖 Assistant Output:\n{summary}"
    )
    _send_message("signal", TARGET_USER, formatted[:3500])

    try:
        PENDING_FILE.unlink(missing_ok=True)
    except Exception:
        pass

    return True


def main() -> int:
    _ensure_state_dir()

    # Priority: if a new voice note appears, process it first and stop.
    if _process_new_voice_note():
        return 0

    # No new voice ingestion, so we can accept a Signal code for pending transcript.
    _process_signal_auth_code()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
