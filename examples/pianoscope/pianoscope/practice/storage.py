"""SQLite persistence for completed MIDI practice sessions."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any


class PracticeStore:
    """Small transactional store kept outside the repository."""

    def __init__(self, path: Path) -> None:
        """Open or initialize a local practice database."""
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                PRAGMA user_version = 1;
                CREATE TABLE IF NOT EXISTS practice_sessions (
                    id TEXT PRIMARY KEY,
                    source_fingerprint TEXT NOT NULL,
                    source_revision TEXT NOT NULL,
                    playback_revision TEXT NOT NULL,
                    started_at REAL NOT NULL,
                    ended_at REAL,
                    rate REAL NOT NULL,
                    hand_mode TEXT NOT NULL,
                    staff_ids_json TEXT NOT NULL,
                    voice_ids_json TEXT NOT NULL,
                    loop_a_s REAL NOT NULL,
                    loop_b_s REAL NOT NULL,
                    expected_count INTEGER NOT NULL,
                    hit_count INTEGER NOT NULL DEFAULT 0,
                    miss_count INTEGER NOT NULL DEFAULT 0,
                    extra_count INTEGER NOT NULL DEFAULT 0,
                    mean_abs_delta_ms REAL,
                    status TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS practice_note_results (
                    session_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL,
                    expected_instance_id TEXT,
                    occurrence_id TEXT,
                    expected_pitch INTEGER,
                    actual_pitch INTEGER,
                    expected_s REAL,
                    actual_s REAL,
                    delta_ms REAL,
                    result TEXT NOT NULL,
                    velocity INTEGER,
                    actual_duration_ms REAL,
                    PRIMARY KEY (session_id, ordinal),
                    FOREIGN KEY (session_id) REFERENCES practice_sessions(id)
                );
                CREATE INDEX IF NOT EXISTS practice_sessions_source_idx
                    ON practice_sessions(source_fingerprint, started_at DESC);
                CREATE INDEX IF NOT EXISTS practice_results_session_idx
                    ON practice_note_results(session_id, ordinal);
                """
            )

    def create(self, metadata: dict[str, Any]) -> str:
        """Create a playing session and return its stable identifier."""
        session_id = uuid.uuid4().hex
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO practice_sessions(
                    id,source_fingerprint,source_revision,playback_revision,
                    started_at,rate,hand_mode,staff_ids_json,voice_ids_json,
                    loop_a_s,loop_b_s,expected_count,status
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    session_id,
                    metadata["source_fingerprint"],
                    metadata["source_revision"],
                    metadata["playback_revision"],
                    time.time(),
                    metadata["rate"],
                    metadata["hand_mode"],
                    json.dumps(metadata.get("staff_ids", []), ensure_ascii=False),
                    json.dumps(metadata.get("voice_ids", []), ensure_ascii=False),
                    metadata["loop_a_s"],
                    metadata["loop_b_s"],
                    metadata["expected_count"],
                    "playing",
                ),
            )
        return session_id

    def finish(
        self, session_id: str, summary: dict[str, Any], results: list[dict[str, Any]]
    ) -> None:
        """Commit session summary and all per-note results atomically."""
        with self._connect() as db:
            db.execute(
                """
                UPDATE practice_sessions SET ended_at=?,hit_count=?,miss_count=?,
                extra_count=?,mean_abs_delta_ms=?,status=? WHERE id=?
                """,
                (
                    time.time(),
                    summary["hit_count"],
                    summary["miss_count"],
                    summary["extra_count"],
                    summary["mean_abs_delta_ms"],
                    summary["status"],
                    session_id,
                ),
            )
            db.executemany(
                """
                INSERT INTO practice_note_results(
                    session_id,ordinal,expected_instance_id,occurrence_id,
                    expected_pitch,actual_pitch,expected_s,actual_s,delta_ms,
                    result,velocity,actual_duration_ms
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                [
                    (
                        session_id,
                        index,
                        item.get("expected_instance_id"),
                        item.get("occurrence_id"),
                        item.get("expected_pitch"),
                        item.get("actual_pitch"),
                        item.get("expected_s"),
                        item.get("actual_s"),
                        item.get("delta_ms"),
                        item["result"],
                        item.get("velocity"),
                        item.get("actual_duration_ms"),
                    )
                    for index, item in enumerate(results)
                ],
            )

    def results(
        self, session_id: str, offset: int = 0, limit: int = 200
    ) -> dict[str, Any]:
        """Return a bounded page of results for one session."""
        offset, limit = max(0, int(offset)), max(1, min(1000, int(limit)))
        with self._connect() as db:
            total = db.execute(
                "SELECT COUNT(*) FROM practice_note_results WHERE session_id=?",
                (session_id,),
            ).fetchone()[0]
            rows = db.execute(
                "SELECT * FROM practice_note_results WHERE session_id=? ORDER BY ordinal LIMIT ? OFFSET ?",
                (session_id, limit, offset),
            ).fetchall()
        return dict(
            total=total,
            items=[dict(row) for row in rows],
            next_offset=offset + len(rows) if offset + len(rows) < total else None,
        )
