#!/usr/bin/env python3
"""Transcribe local audio files with ElevenLabs Speech-to-Text.

Usage:
  python3 scripts/transcribe_elevenlabs.py /path/to/file.m4a
  python3 scripts/transcribe_elevenlabs.py /path/to/file.m4a --json --out /tmp/out.json
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        os.environ.setdefault(k, v)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Transcribe audio with ElevenLabs STT")
    p.add_argument("audio_file", help="Path to local audio file")
    p.add_argument("--out", help="Output file path")
    p.add_argument("--json", action="store_true", help="Write raw JSON response")
    p.add_argument(
        "--model-id",
        default=os.getenv("ELEVENLABS_SPEECH_MODEL_ID", "scribe_v1"),
        help="ElevenLabs speech model id (default: scribe_v1)",
    )
    p.add_argument("--language", help="Optional language code (e.g., en)")
    return p.parse_args()


def main() -> int:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    args = parse_args()

    audio_path = Path(args.audio_file).expanduser().resolve()
    if not audio_path.exists():
        print(f"Audio file not found: {audio_path}", file=sys.stderr)
        return 2

    api_key = os.getenv("ELEVENLABS_API_KEY", "").strip()
    if not api_key:
        print("ELEVENLABS_API_KEY is required", file=sys.stderr)
        return 2

    output_path = Path(args.out) if args.out else audio_path.with_suffix(".txt")

    cmd = [
        "curl",
        "-sS",
        "-X",
        "POST",
        "https://api.elevenlabs.io/v1/speech-to-text",
        "-H",
        f"xi-api-key: {api_key}",
        "-F",
        f"model_id={args.model_id}",
        "-F",
        f"file=@{audio_path}",
    ]

    if args.language:
        cmd.extend(["-F", f"language_code={args.language}"])

    try:
        proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    except FileNotFoundError:
        print("curl is required but not found", file=sys.stderr)
        return 2

    if proc.returncode != 0:
        print(proc.stderr.strip() or "curl call failed", file=sys.stderr)
        return 1

    raw = proc.stdout.strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        print(raw, file=sys.stderr)
        return 1

    # ElevenLabs commonly returns {"text": "..."}; keep robust fallbacks.
    text = payload.get("text") or payload.get("transcript") or ""
    if not text and isinstance(payload.get("words"), list):
        text = " ".join([w.get("text", "") for w in payload["words"]]).strip()

    if "error" in payload:
        output_path.write_text(json.dumps(payload, indent=2) + "\n")
        print(json.dumps(payload, indent=2), file=sys.stderr)
        return 1

    if args.json:
        output_path.write_text(json.dumps(payload, indent=2) + "\n")
    else:
        output_path.write_text((text or "") + "\n")

    print(str(output_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
