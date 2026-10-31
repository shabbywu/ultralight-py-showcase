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

            db.execute(
                "CREATE TABLE IF NOT EXISTS library(path TEXT PRIMARY KEY,name TEXT NOT NULL,fingerprint TEXT NOT NULL DEFAULT '')"
            )
            columns = {r[1] for r in db.execute("PRAGMA table_info(practice_sessions)")}
            for name in ("title", "device", "config_json"):
                if name not in columns:
                    db.execute(
                        f"ALTER TABLE practice_sessions ADD COLUMN {name} TEXT NOT NULL DEFAULT ''"
                    )
            columns = {
                r[1] for r in db.execute("PRAGMA table_info(practice_note_results)")
            }
            for name, declaration in (
                ("round_index", "INTEGER NOT NULL DEFAULT 1"),
                ("locator", "TEXT NOT NULL DEFAULT ''"),
            ):
                if name not in columns:
                    db.execute(
                        f"ALTER TABLE practice_note_results ADD COLUMN {name} {declaration}"
                    )
            columns = {r[1] for r in db.execute("PRAGMA table_info(practice_sessions)")}
            for name in (
                "early_count",
                "late_count",
                "evaluated_count",
                "completed_rounds",
            ):
                if name not in columns:
                    db.execute(
                        f"ALTER TABLE practice_sessions ADD COLUMN {name} INTEGER NOT NULL DEFAULT 0"
                    )
            db.execute(
                "UPDATE practice_sessions SET status='interrupted' WHERE status='playing'"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS preferences(key TEXT PRIMARY KEY,value TEXT NOT NULL)"
            )
            columns = {r[1] for r in db.execute("PRAGMA table_info(library)")}
            if "id" not in columns:
                db.execute("ALTER TABLE library ADD COLUMN id TEXT NOT NULL DEFAULT ''")
                for row in db.execute("SELECT path FROM library").fetchall():
                    db.execute(
                        "UPDATE library SET id=? WHERE path=?",
                        (uuid.uuid4().hex, row[0]),
                    )
            db.execute(
                "CREATE TABLE IF NOT EXISTS library_sources(path TEXT PRIMARY KEY)"
            )
            db.execute("PRAGMA user_version=4")

    def preference(self, key: str, value: Any = None) -> Any:
        """读取或保存曲目手别、文件夹来源等后端偏好。"""
        with self._connect() as db:
            if value is not None:
                db.execute(
                    "INSERT INTO preferences VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, json.dumps(value, ensure_ascii=False)),
                )
                return value
            row = db.execute(
                "SELECT value FROM preferences WHERE key=?", (key,)
            ).fetchone()
            return json.loads(row[0]) if row else None

    def forget(self, path: str) -> None:
        """仅移除索引，保留原文件和练习历史。"""
        with self._connect() as db:
            db.execute("DELETE FROM library WHERE path=?", (path,))

    def sources(self, path: str | None = None) -> list[str]:
        """登记并读取持久化文件夹来源。"""
        with self._connect() as db:
            if path:
                db.execute("INSERT OR IGNORE INTO library_sources VALUES(?)", (path,))
            return [
                r[0]
                for r in db.execute("SELECT path FROM library_sources ORDER BY path")
            ]

    def relocate(self, old: str, new: str) -> None:
        """保持曲目稳定 ID 重新定位引用。"""
        with self._connect() as db:
            db.execute(
                "UPDATE library SET path=?,name=? WHERE path=?",
                (new, Path(new).name, old),
            )

    def library(self) -> list[dict[str, Any]]:
        """读取持久化曲目索引。"""
        with self._connect() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT library.*, (SELECT MAX(started_at) FROM practice_sessions WHERE source_fingerprint=library.fingerprint) AS last_practiced FROM library ORDER BY name COLLATE NOCASE"
                )
            ]

    def remember(self, path: str, name: str, fingerprint: str = "") -> None:
        """按规范化路径登记或更新曲目。"""
        with self._connect() as db:
            db.execute(
                "INSERT INTO library(path,name,fingerprint,id) VALUES(?,?,?,?) ON CONFLICT(path) DO UPDATE SET name=excluded.name,fingerprint=CASE WHEN excluded.fingerprint='' THEN library.fingerprint ELSE excluded.fingerprint END",
                (path, name, fingerprint, uuid.uuid4().hex),
            )

    def history(self, fingerprint: str = "", offset: int = 0) -> dict[str, Any]:
        """分页查询曲目历史，空指纹可查看未关联记录。"""
        with self._connect() as db:
            where = " WHERE source_fingerprint=?" if fingerprint else ""
            args = (fingerprint,) if fingerprint else ()
            rows = db.execute(
                "SELECT * FROM practice_sessions"
                + where
                + " ORDER BY started_at DESC LIMIT 50 OFFSET ?",
                (*args, max(0, offset)),
            ).fetchall()
            total = db.execute(
                "SELECT COUNT(*) FROM practice_sessions" + where, args
            ).fetchone()[0]
        return dict(
            items=[dict(r) for r in rows],
            total=total,
            next_offset=offset + len(rows) if offset + len(rows) < total else None,
        )

    def comparison(self, session_id: str) -> dict[str, Any] | None:
        """比较相同条件的完整轮次，排除提前停止的末轮。"""
        with self._connect() as db:
            current = db.execute(
                "SELECT * FROM practice_sessions WHERE id=?", (session_id,)
            ).fetchone()
            if current is None or not current["config_json"]:
                return None

            def key(row: sqlite3.Row) -> str:
                """构建版本、目标、伴奏和判定条件的稳定比较键。"""
                config = json.loads(row["config_json"] or "{}")
                return json.dumps(
                    [
                        row["source_fingerprint"],
                        row["source_revision"],
                        row["playback_revision"],
                        row["rate"],
                        row["loop_a_s"],
                        row["loop_b_s"],
                        config.get("options"),
                        config.get("rules_version"),
                    ],
                    sort_keys=True,
                )

            expected = key(current)
            rates = []
            for row in db.execute(
                "SELECT * FROM practice_sessions WHERE source_fingerprint=? AND completed_rounds>0 ORDER BY started_at DESC",
                (current["source_fingerprint"],),
            ):
                if key(row) != expected:
                    continue
                counts = db.execute(
                    "SELECT SUM(CASE WHEN result='hit' THEN 1 ELSE 0 END), SUM(CASE WHEN result IN ('hit','early','late','miss') THEN 1 ELSE 0 END) FROM practice_note_results WHERE session_id=? AND round_index<=?",
                    (row["id"], row["completed_rounds"]),
                ).fetchone()
                if counts[1]:
                    rates.append(dict(id=row["id"], rate=100 * counts[0] / counts[1]))
            if not rates:
                return None
            current_rate = next(
                (r["rate"] for r in rates if r["id"] == session_id), None
            )
            previous = next((r["rate"] for r in rates if r["id"] != session_id), None)
            return dict(
                best=max(r["rate"] for r in rates),
                current=current_rate,
                previous=previous,
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
            db.execute(
                "UPDATE practice_sessions SET title=?,device=?,config_json=? WHERE id=?",
                (
                    metadata.get("title", ""),
                    metadata.get("device", ""),
                    json.dumps(metadata, ensure_ascii=False),
                    session_id,
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
                    None if summary["status"] == "playing" else time.time(),
                    summary["hit_count"],
                    summary["miss_count"],
                    summary["extra_count"],
                    summary["mean_abs_delta_ms"],
                    summary["status"],
                    session_id,
                ),
            )
            db.execute(
                "UPDATE practice_sessions SET early_count=?,late_count=?,evaluated_count=?,completed_rounds=? WHERE id=?",
                (
                    summary.get("early_count", 0),
                    summary.get("late_count", 0),
                    summary.get("evaluated_count", 0),
                    summary.get("completed_rounds", 0),
                    session_id,
                ),
            )
            db.executemany(
                """
                INSERT OR REPLACE INTO practice_note_results(
                    session_id,ordinal,expected_instance_id,occurrence_id,
                    expected_pitch,actual_pitch,expected_s,actual_s,delta_ms,
                    result,velocity,actual_duration_ms,round_index,locator
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                [
                    (
                        session_id,
                        item.get("ordinal", index),
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
                        item.get("round_index", 1),
                        item.get("locator", ""),
                    )
                    for index, item in enumerate(results)
                ],
            )

    def results(
        self,
        session_id: str,
        offset: int = 0,
        limit: int = 200,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return a bounded page of results for one session."""
        offset, limit = max(0, int(offset)), max(1, min(1000, int(limit)))
        filters = filters or {}
        clauses = ["session_id=?"]
        args: list[Any] = [session_id]
        if filters.get("round_index"):
            clauses.append("round_index=?")
            args.append(max(1, int(filters["round_index"])))
        if filters.get("result"):
            if filters["result"] not in ("hit", "early", "late", "miss", "extra"):
                raise ValueError("判定筛选无效")
            clauses.append("result=?")
            args.append(filters["result"])
        where = " AND ".join(clauses)
        with self._connect() as db:
            total = db.execute(
                "SELECT COUNT(*) FROM practice_note_results WHERE " + where, args
            ).fetchone()[0]
            rows = db.execute(
                "SELECT * FROM practice_note_results WHERE "
                + where
                + " ORDER BY ordinal LIMIT ? OFFSET ?",
                (*args, limit, offset),
            ).fetchall()
        return dict(
            total=total,
            items=[dict(row) for row in rows],
            next_offset=offset + len(rows) if offset + len(rows) < total else None,
        )
