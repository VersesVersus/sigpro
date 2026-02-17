# Universal Signal Inbound Collector Architecture

## Purpose

Provide a **single, reusable, lock-safe architecture** for any project that needs to ingest Signal messages (text + attachments) without risking `signal-cli` DB/session lock conflicts.

This design separates:
1. **Inbound collection** (single owner of `signal-cli receive`)
2. **Event distribution** (normalized queue/log)
3. **Project-specific processing** (N independent consumers)

---

## Why This Exists

`signal-cli` inbound access can conflict when multiple processes poll/receive simultaneously for the same account.

Common failure modes:
- SQLite/DB lock contention
- Session/store lock errors
- Missed/duplicated messages
- Fragile race conditions between bots

**Rule:** One Signal account/store → one inbound collector process.

---

## High-Level Design

```text
                ┌──────────────────────────────┐
                │      signal-cli account      │
                │  (single source of inbound)  │
                └──────────────┬───────────────┘
                               │
                               ▼
                  ┌──────────────────────────┐
                  │ Signal Inbound Collector │
                  │  (single-reader only)    │
                  └──────────────┬───────────┘
                                 │ normalized events
                                 ▼
              ┌────────────────────────────────────┐
              │ Durable Event Stream / Queue       │
              │ (JSONL, SQLite, Redis Streams, NATS│
              │  or Kafka depending on scale)      │
              └──────────────┬───────────────┬─────┘
                             │               │
                             ▼               ▼
              ┌─────────────────────┐   ┌─────────────────────┐
              │ Consumer: SigPro    │   │ Consumer: Other Bot │
              │ voice auth workflow │   │ analytics/ops/etc   │
              └─────────────────────┘   └─────────────────────┘
```

---

## Core Principles

1. **Single Reader**
   - Exactly one process interacts with Signal inbound receive path.

2. **At-Least-Once Delivery**
   - Collector persists events before acknowledging processing state.

3. **Idempotent Consumers**
   - Consumers track `event_id`/`source_message_id` to avoid duplicate effects.

4. **Separation of Concerns**
   - Collector does transport ingestion + normalization only.
   - Business logic (auth, execution, summaries) lives in consumers.

5. **Observability First**
   - Structured logs, metrics, dead-letter strategy, replay capability.

---

## Event Contract (Canonical)

Use a shared normalized schema for all projects.

```json
{
  "event_id": "uuid-v7-or-stable-hash",
  "source": "signal",
  "account": "+1XXXXXXXXXX",
  "received_at": "2026-02-17T16:10:00Z",
  "source_message_id": "provider-native-id-or-timestamp",
  "chat": {
    "type": "direct|group",
    "id": "stable-chat-identifier",
    "name": "optional"
  },
  "sender": {
    "id": "+1XXXXXXXXXX",
    "name": "optional profile name"
  },
  "message": {
    "text": "raw text body",
    "is_edit": false,
    "is_delete": false
  },
  "attachments": [
    {
      "id": "attachment-id",
      "mime_type": "audio/mp4",
      "filename": "abc.m4a",
      "path": "/absolute/local/path",
      "size_bytes": 80781,
      "sha256": "optional"
    }
  ],
  "raw": {
    "provider_payload": {}
  }
}
```

Notes:
- Keep `raw.provider_payload` for debugging/replay.
- `event_id` should be deterministic when possible to support dedupe.

---

## Lock-Safe Runtime Model

### Process model
- Run collector as a daemon/service (`systemd` recommended).
- Enforce singleton with one of:
  - `flock` lock file
  - systemd `RefuseManualStart=no` + single unit
  - PID file + advisory lock

### Example singleton guard

```bash
flock -n /var/lock/signal-inbound.lock \
  /usr/local/bin/signal-inbound-collector
```

If lock acquisition fails, process exits and logs "collector already running".

---

## Storage/Queue Options

### Small/Local (recommended default)
1. **SQLite queue table** (durable, simple, queryable)
2. **JSONL append log + cursor files** (very simple)

### Medium/Large
1. Redis Streams
2. NATS JetStream
3. Kafka

Pick based on throughput, retention, and ops maturity.

---

## Consumer Pattern (Universal)

Each consumer should:
1. Read new events from queue
2. Filter by project criteria (chat, sender, attachment type)
3. Perform business logic
4. Record processed `event_id` in consumer state
5. Commit cursor

This allows many independent projects to share one Signal inbound feed safely.

---

## SigPro Mapping (Current Project)

For SigPro, consumer logic becomes:

1. On event with new voice attachment:
   - transcribe
   - generate auth code
   - send WhatsApp code
   - store pending transcript
   - send Signal prompt to enter code

2. On event with 4-digit text from authorized sender:
   - validate code
   - execute pending transcript in main interpreter
   - send Signal summary
   - clear pending transcript

No direct `signal-cli receive` calls in SigPro worker.

---

## Failure Handling

### Collector failures
- Retry with backoff on transient errors.
- On repeated parse failures, write raw payload to dead-letter store.

### Consumer failures
- Do not block collector.
- Move failing event to consumer DLQ after N retries.
- Keep replay tooling to reprocess from checkpoint.

---

## Security & Privacy

- Restrict file permissions on inbound store and attachment paths.
- Encrypt at rest if storing sensitive message content.
- Keep retention bounded (TTL + archival policy).
- Never expose raw Signal payloads externally without sanitization.

---

## Observability Checklist

Minimum metrics:
- collector_events_total
- collector_errors_total
- queue_depth
- consumer_lag_seconds
- consumer_failures_total
- duplicate_events_dropped_total

Minimum logs:
- startup/shutdown + lock status
- receive parse summary
- event publish success/fail
- consumer ack/retry/DLQ

---

## Implementation Blueprint (Phased)

### Phase 1 (now)
- Build singleton Signal inbound collector
- Write normalized events to local SQLite/JSONL
- Add cursor-based SigPro consumer

### Phase 2
- Add shared event schema library/util
- Add replay command and DLQ tooling
- Add dashboards/alerts

### Phase 3
- Migrate queue backend (Redis/Kafka) if needed
- Add multi-project routing and ACLs

---

## Non-Negotiable Rule

> Any project needing Signal inbound must consume from the shared inbound stream.
> Do not add a second direct inbound `signal-cli receive` loop.

This is the key control that prevents lock contention and race conditions.
