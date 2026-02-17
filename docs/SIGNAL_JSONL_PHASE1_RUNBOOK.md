# Signal JSONL Phase-1 Runbook

## Components

1. `scripts/signal_jsonl_ingest.py`
   - append raw Signal inbound events into `.openclaw/signal_inbound_raw.jsonl`
2. `scripts/signal_inbound_collector.py`
   - singleton collector; reads incremental JSONL and publishes normalized events to SQLite
3. `scripts/signal_event_consumer_sigpro.py`
   - consumes normalized events and runs SigPro auth/transcribe/execute flow

---

## File Paths

- Raw ingress JSONL: `.openclaw/signal_inbound_raw.jsonl`
- Raw ingress offset: `.openclaw/signal_inbound_raw.offset`
- Collector singleton lock: `.openclaw/signal_inbound.lock`
- Event DB: `.openclaw/signal_events.db`

---

## 1) Feed ingress JSONL

Upstream bridge should append one JSON object per message/event.

Example test write:

```bash
cat <<'JSON' | python3 scripts/signal_jsonl_ingest.py
{"id":"msg-1","timestamp":1771345200,"sender":{"id":"+19412907826"},"message":{"text":"5829"},"attachments":[]}
JSON
```

For voice event:

```json
{
  "id": "msg-voice-1",
  "timestamp": 1771345300,
  "sender": {"id": "+19412907826"},
  "message": {"text": ""},
  "attachments": [
    {
      "filename": "sample.m4a",
      "path": "/home/james/.local/share/signal-cli/attachments/sample.m4a",
      "mime_type": "audio/mp4"
    }
  ]
}
```

---

## 2) Run collector

Single-pass:

```bash
python3 scripts/signal_inbound_collector.py
```

Daemon-ish follow mode:

```bash
python3 scripts/signal_inbound_collector.py --follow --poll-ms 1500
```

---

## 3) Run SigPro consumer

```bash
python3 scripts/signal_event_consumer_sigpro.py --consumer sigpro-main --limit 200
```

Run periodically (cron/systemd timer), e.g. every 10–20 seconds.

---

## Suggested systemd split

- `signal-inbound-collector.service` (long-running `--follow`)
- `sigpro-consumer.service` + `sigpro-consumer.timer` (frequent short runs)

This keeps collector singleton + consumer stateless.

---

## Notes

- Collector dedupes by `event_id`.
- Consumer is cursor-based via `consumer_offsets` table.
- This is Phase-1; later we can add DLQ/replay CLI and stricter schema validation.
