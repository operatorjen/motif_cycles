from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

JSON_FIELDS = {
    "motif_ids",
    "checkpoint_ids",
    "motif_packet",
    "folding_import",
    "fold_artifact",
    "failure_trace",
    "contract",
    "feedback_trace",
    "closeout",
    "outcome",
}


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


class Storage:
    def __init__(self, database: Path):
        self.database = database

    @contextmanager
    def connection(self):
        connection = sqlite3.connect(self.database, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute("PRAGMA journal_mode = WAL")
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS rounds (
                    id TEXT PRIMARY KEY,
                    parent_round_id TEXT REFERENCES rounds(id) ON DELETE SET NULL,
                    title TEXT NOT NULL,
                    inquiry TEXT NOT NULL,
                    status TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    feedback_project_id TEXT NOT NULL,
                    folding_project_id TEXT NOT NULL,
                    motif_ids TEXT NOT NULL DEFAULT '[]',
                    checkpoint_ids TEXT NOT NULL DEFAULT '[]',
                    human_note TEXT NOT NULL DEFAULT '',
                    motif_packet TEXT,
                    folding_import TEXT,
                    folding_run_id TEXT,
                    fold_artifact TEXT,
                    selected_fold_id TEXT,
                    contract TEXT,
                    feedback_turn_id TEXT,
                    feedback_trace TEXT,
                    closeout TEXT,
                    outcome TEXT,
                    failed_stage TEXT,
                    failure_trace TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS round_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    round_id TEXT NOT NULL REFERENCES rounds(id) ON DELETE CASCADE,
                    stage TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_rounds_updated
                    ON rounds(updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_round_events_round
                    ON round_events(round_id, id);
                """
            )
            columns = {row["name"] for row in db.execute("PRAGMA table_info(rounds)")}
            if "failed_stage" not in columns:
                db.execute("ALTER TABLE rounds ADD COLUMN failed_stage TEXT")
            if "failure_trace" not in columns:
                db.execute("ALTER TABLE rounds ADD COLUMN failure_trace TEXT")

    def create_round(self, payload: dict[str, Any], parent_round_id: str | None = None) -> dict:
        timestamp = now_iso()
        value = {
            "id": f"round-{uuid.uuid4().hex[:16]}",
            "parent_round_id": parent_round_id,
            "title": payload["title"].strip(),
            "inquiry": payload["inquiry"].strip(),
            "status": "queued",
            "stage": "intake",
            "feedback_project_id": payload["feedback_project_id"],
            "folding_project_id": payload["folding_project_id"],
            "motif_ids": json.dumps(payload.get("motif_ids", [])),
            "checkpoint_ids": json.dumps(payload.get("checkpoint_ids", [])),
            "human_note": payload.get("human_note", "").strip(),
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        with self.connection() as db:
            db.execute(
                """
                INSERT INTO rounds(
                    id, parent_round_id, title, inquiry, status, stage,
                    feedback_project_id, folding_project_id, motif_ids,
                    checkpoint_ids, human_note, created_at, updated_at
                ) VALUES (
                    :id, :parent_round_id, :title, :inquiry, :status, :stage,
                    :feedback_project_id, :folding_project_id, :motif_ids,
                    :checkpoint_ids, :human_note, :created_at, :updated_at
                )
                """,
                value,
            )
        self.add_event(value["id"], "intake", "Round created by the human operator")
        return self.get_round(value["id"])

    def update_round(self, round_id: str, **values: Any) -> dict:
        allowed = {
            "status",
            "stage",
            "motif_packet",
            "folding_import",
            "folding_run_id",
            "fold_artifact",
            "selected_fold_id",
            "contract",
            "feedback_turn_id",
            "feedback_trace",
            "closeout",
            "outcome",
            "failed_stage",
            "failure_trace",
            "error",
        }
        changes = {key: value for key, value in values.items() if key in allowed}
        if not changes:
            return self.get_round(round_id)
        for key in set(changes) & JSON_FIELDS:
            changes[key] = json.dumps(changes[key], ensure_ascii=False)
        changes["updated_at"] = now_iso()
        assignments = ", ".join(f"{key} = ?" for key in changes)
        with self.connection() as db:
            updated = db.execute(
                f"UPDATE rounds SET {assignments} WHERE id = ?",  # noqa: S608
                (*changes.values(), round_id),
            )
        if updated.rowcount != 1:
            raise KeyError("Round not found")
        return self.get_round(round_id)

    def add_event(self, round_id: str, stage: str, message: str) -> None:
        with self.connection() as db:
            db.execute(
                "INSERT INTO round_events(round_id, stage, message, created_at) "
                "VALUES (?, ?, ?, ?)",
                (round_id, stage, message, now_iso()),
            )

    def get_round(self, round_id: str) -> dict[str, Any]:
        with self.connection() as db:
            row = db.execute("SELECT * FROM rounds WHERE id = ?", (round_id,)).fetchone()
            events = db.execute(
                "SELECT stage, message, created_at FROM round_events "
                "WHERE round_id = ? ORDER BY id",
                (round_id,),
            ).fetchall()
        if row is None:
            raise KeyError("Round not found")
        result = dict(row)
        for key in JSON_FIELDS:
            raw = result.get(key)
            result[key] = json.loads(raw) if raw else ([] if key.endswith("_ids") else None)
        result["events"] = [dict(event) for event in events]
        return result

    def list_rounds(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute(
                "SELECT id FROM rounds ORDER BY updated_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self.get_round(row["id"]) for row in rows]
