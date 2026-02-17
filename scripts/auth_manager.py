#!/usr/bin/env python3
"""SigPro Auth Manager - Generate and validate 4-digit OOB codes."""

import json
import random
import sys
import time
from pathlib import Path

AUTH_FILE = Path("/home/james/.openclaw/workspace-sigpro/.openclaw/auth_state.json")
EXPIRY_SEC = 300 # 5 minutes

def load_state():
    if not AUTH_FILE.exists():
        return {}
    try:
        return json.loads(AUTH_FILE.read_text())
    except:
        return {}

def save_state(state):
    AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    AUTH_FILE.write_text(json.dumps(state))

def generate():
    code = f"{random.randint(0, 9999):04d}"
    state = {
        "code": code,
        "expires_at": int(time.time()) + EXPIRY_SEC
    }
    save_state(state)
    return code

def validate(submitted_code):
    state = load_state()
    if not state:
        return False, "No active code."
    
    if time.time() > state.get("expires_at", 0):
        return False, "Code expired."
    
    if submitted_code.strip() == state.get("code"):
        # One-time use: clear after successful validation
        save_state({})
        return True, "Code valid."
    
    return False, "Code mismatch."

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: auth.py generate | validate <code>")
        sys.exit(1)
    
    cmd = sys.argv[1]
    if cmd == "generate":
        print(generate())
    elif cmd == "validate":
        ok, msg = validate(sys.argv[2])
        print(json.dumps({"ok": ok, "message": msg}))
