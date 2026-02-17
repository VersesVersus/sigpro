# SigPro

Secure Signal voice/text-to-action pipeline with two-channel auth.

## Architecture Summary

This repository follows the staged flow in `ARCHITECTURE.md`:

1. **Signal Ingress**
   - Signal daemon receives messages.
   - `signal-journal-bridge` reads daemon journald output and appends normalized JSON events to raw ingress JSONL.
   - `signal-inbound-collector` is the single collector process (singleton lock) that ingests JSONL and publishes events into SQLite.

2. **Audio Transcription**
   - Voice-note attachments are transcribed with ElevenLabs (`scripts/transcribe_elevenlabs.py`).

3. **Prompt Normalization**
   - Transcript is converted into an execution-ready request payload for the main interpreter.

4. **Guardrails / Auth**
   - Out-of-band 4-digit code is generated (`scripts/auth_manager.py generate`) and sent via WhatsApp.
   - Pending transcript is stored in `.openclaw/pending_transcript.json`.
   - Signal code reply is validated (`scripts/auth_manager.py validate <code>`).
   - No execution occurs without valid code + pending transcript.
   - Auth failures are logged in `.openclaw/auth_failures.log`.

5. **Execution**
   - On valid auth, request is sent to `agent:main:main` via OpenClaw sessions.

6. **Response**
   - Concise execution summary is returned to Signal.

## Runtime Components (Phase 1 JSONL Model)

### Ingress + Stream
- Raw ingress JSONL: `.openclaw/signal_inbound_raw.jsonl`
- Raw ingress cursor: `.openclaw/signal_inbound_raw.offset`
- Event DB: `.openclaw/signal_events.db`
- Collector lock: `.openclaw/signal_inbound.lock`

### Services / Timers
- `signal-journal-bridge.timer` -> `signal-journal-bridge.service` (every 5s)
- `signal-inbound-collector.service` (continuous)
- `sigpro-consumer.timer` -> `sigpro-consumer.service` (every 15s)

These are user-level systemd units installed under:
- `~/.config/systemd/user/`

## Key Design Rules

- **Single collector** for inbound Signal event stream (prevents multi-process Signal receive lock conflicts).
- **Cursor-based consumers** for idempotent processing.
- **At-least-once ingestion** with duplicate-safe event IDs.
- **Guardrails-first execution**: ambiguous or unauthorized input must not execute.

## Reference Docs

- `ARCHITECTURE.md`
- `docs/SIGNAL_INBOUND_ARCHITECTURE.md`
- `docs/SIGNAL_JSONL_PHASE1_RUNBOOK.md`
- `deploy/systemd/README.md`
