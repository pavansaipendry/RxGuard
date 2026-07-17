"""SQLite audit log.

Every decision is recorded with which guards fired and why — in healthcare,
"the system blocked it" must always be answerable with "because X, at Y".
"""

import json
import sqlite3
import time
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    verdict TEXT NOT NULL,
    request_preview TEXT,
    response_preview TEXT,
    fired_json TEXT,
    overridden_json TEXT,
    latency_ms REAL
);
CREATE INDEX IF NOT EXISTS idx_decisions_verdict ON decisions(verdict);
CREATE INDEX IF NOT EXISTS idx_decisions_ts ON decisions(ts);
"""


class AuditLog:
    def __init__(self, db_path: str):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        with self._conn() as conn:
            conn.executescript(_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def log(self, decision, request_preview: str, response_preview: str, latency_ms: float) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO decisions (verdict, request_preview, response_preview, "
                "fired_json, overridden_json, latency_ms) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    decision.verdict.value,
                    request_preview[:500],
                    response_preview[:500],
                    json.dumps([r.to_dict() for r in decision.fired]),
                    json.dumps([r.to_dict() for r in decision.overridden]),
                    latency_ms,
                ),
            )

    def recent(self, limit: int = 50) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM decisions ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        out = []
        for row in rows:
            d = dict(row)
            d["fired"] = json.loads(d.pop("fired_json") or "[]")
            d["overridden"] = json.loads(d.pop("overridden_json") or "[]")
            out.append(d)
        return out


class NullAuditLog:
    """No-op stand-in for tests and benchmark runs."""

    def log(self, *args, **kwargs) -> None:
        pass

    def recent(self, limit: int = 50) -> list[dict]:
        return []


def now_ms() -> float:
    return time.perf_counter() * 1000.0
