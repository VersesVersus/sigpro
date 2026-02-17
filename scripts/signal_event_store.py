#!/usr/bin/env python3
"""Shared SQLite event store for Signal inbound collector + consumers."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

DEFAULT_DB = Path("/home/james/.openclaw/workspace-sigpro/.openclaw/signal_events.db")


def get_conn(db_path: Path = DEFAULT_DB) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS signal_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT NOT NULL UNIQUE,
            source TEXT NOT NULL DEFAULT 'signal',
            account TEXT,
            received_at INTEGER NOT NULL,
            source_message_id TEXT,
            chat_json TEXT NOT NULL,
            sender_json TEXT NOT NULL,
            message_json TEXT NOT NULL,
            attachments_json TEXT NOT NULL,
            raw_json TEXT NOT NULL,
            created_at INTEGER NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_signal_events_received_at ON signal_events(received_at);
        CREATE INDEX IF NOT EXISTS idx_signal_events_source_msg_id ON signal_events(source_message_id);

        CREATE TABLE IF NOT EXISTS consumer_offsets (
            consumer_name TEXT PRIMARY KEY,
            last_event_rowid INTEGER NOT NULL DEFAULT 0,
            updated_at INTEGER NOT NULL
        );
        """
    )
    conn.commit()


def publish_event(conn: sqlite3.Connection, event: dict[str, Any]) -> bool:
    now = int(time.time())
    payload = {
        "event_id": str(event["event_id"]),
        "source": str(event.get("source", "signal")),
        "account": event.get("account"),
        "received_at": int(event.get("received_at", now)),
        "source_message_id": event.get("source_message_id"),
        "chat_json": json.dumps(event.get("chat", {}), ensure_ascii=False),
        "sender_json": json.dumps(event.get("sender", {}), ensure_ascii=False),
        "message_json": json.dumps(event.get("message", {}), ensure_ascii=False),
        "attachments_json": json.dumps(event.get("attachments", []), ensure_ascii=False),
        "raw_json": json.dumps(event.get("raw", {}), ensure_ascii=False),
        "created_at": now,
    }

    try:
        conn.execute(
            """
            INSERT INTO signal_events (
                event_id, source, account, received_at, source_message_id,
                chat_json, sender_json, message_json, attachments_json, raw_json, created_at
            ) VALUES (
                :event_id, :source, :account, :received_at, :source_message_id,
                :chat_json, :sender_json, :message_json, :attachments_json, :raw_json, :created_at
            )
            """,
            payload,
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        # duplicate event_id
        return False


def get_offset(conn: sqlite3.Connection, consumer_name: str) -> int:
    row = conn.execute(
        "SELECT last_event_rowid FROM consumer_offsets WHERE consumer_name = ?",
        (consumer_name,),
    ).fetchone()
    return int(row[0]) if row else 0


def set_offset(conn: sqlite3.Connection, consumer_name: str, rowid: int) -> None:
    now = int(time.time())
    conn.execute(
        """
        INSERT INTO consumer_offsets (consumer_name, last_event_rowid, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(consumer_name)
        DO UPDATE SET last_event_rowid=excluded.last_event_rowid, updated_at=excluded.updated_at
        """,
        (consumer_name, rowid, now),
    )
    conn.commit()


def fetch_events(conn: sqlite3.Connection, after_rowid: int, limit: int = 100) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM signal_events WHERE id > ? ORDER BY id ASC LIMIT ?",
            (after_rowid, limit),
        ).fetchall()
    )
