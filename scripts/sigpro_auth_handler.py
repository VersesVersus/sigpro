#!/usr/bin/env python3
import sys
import json
import subprocess
from pathlib import Path

AUTH_SCRIPT = Path("/home/james/.openclaw/workspace-sigpro/scripts/auth_manager.py")
PENDING_FILE = Path("/home/james/.openclaw/workspace-sigpro/.openclaw/pending_transcript.json")
TARGET_USER = "+19412907826"

def handle_auth(code):
    # 1. Validate Code
    result_json = subprocess.run(["python3", str(AUTH_SCRIPT), "validate", code], capture_output=True, text=True).stdout
    try:
        result = json.loads(result_json)
    except:
        result = {"ok": False, "message": "Internal error validating code."}

    if not result.get("ok"):
        msg = f"Auth Failed: {result.get('message')}"
        subprocess.run(["openclaw", "message", "send", "--channel", "signal", "--target", TARGET_USER, "--text", msg])
        print(msg)
        return

    # 2. Retrieve Pending Transcript
    if not PENDING_FILE.exists():
        msg = "Error: No pending transcript found."
        subprocess.run(["openclaw", "message", "send", "--channel", "signal", "--target", TARGET_USER, "--text", msg])
        print(msg)
        return

    try:
        with open(PENDING_FILE, "r") as f:
            data = json.load(f)
        transcript = data.get("transcript")
    except Exception as e:
        msg = f"Error reading pending transcript: {str(e)}"
        subprocess.run(["openclaw", "message", "send", "--channel", "signal", "--target", TARGET_USER, "--text", msg])
        return

    # 3. Execute against Main Interpreter
    # We use sessions_send (via openclaw cli) to target the main session
    # Note: 'main' is the default label for the human's main chat session.
    exec_msg = f"SigPro Authorized Request: {transcript}"
    subprocess.run(["openclaw", "sessions", "send", "--label", "main", "--message", exec_msg])

    # 4. Cleanup
    PENDING_FILE.unlink()

    # 5. Summary to Signal
    summary = f"Code accepted. Request sent to main interpreter:\n\"{transcript}\""
    subprocess.run(["openclaw", "message", "send", "--channel", "signal", "--target", TARGET_USER, "--text", summary])
    print("Execution authorized and sent.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: sigpro_auth_handler.py <code>")
        sys.exit(1)
    
    handle_auth(sys.argv[1])
