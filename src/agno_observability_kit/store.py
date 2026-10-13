"""Small persistent event store with bounded retention and idempotent ingestion."""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from agno_observability_kit.events import EventBatch, HostSnapshot, TERMINAL


class EventStore:
    def __init__(self, path: str, retention_days: int = 7, max_events: int = 100_000):
        self.path, self.retention_days, self.max_events = path, retention_days, max_events
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL UNIQUE,
                    timestamp REAL NOT NULL, received REAL NOT NULL,
                    job_id TEXT NOT NULL, trace_id TEXT NOT NULL, service TEXT NOT NULL,
                    kind TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS job_events ON events(job_id, timestamp, seq);
                CREATE INDEX IF NOT EXISTS trace_events ON events(trace_id, timestamp, seq);
                CREATE INDEX IF NOT EXISTS event_time ON events(timestamp);
                CREATE TABLE IF NOT EXISTS hosts (
                    host_id TEXT PRIMARY KEY, timestamp REAL NOT NULL,
                    received REAL NOT NULL, payload TEXT NOT NULL);
            """)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def ingest(self, batch: EventBatch) -> int:
        with self.connection() as db:
            before = db.total_changes
            for event in batch.events:
                db.execute("INSERT OR IGNORE INTO events(event_id,timestamp,received,job_id,trace_id,service,kind,status,payload) VALUES(?,?,?,?,?,?,?,?,?)",
                           (event.event_id, event.timestamp.timestamp(), time.time(), event.job_id, event.trace_id,
                            event.service, event.kind, event.status, event.model_dump_json()))
            accepted = db.total_changes - before
            self._prune(db)
        return accepted

    def _prune(self, db):
        db.execute("DELETE FROM events WHERE timestamp < ?", (time.time() - self.retention_days * 86400,))
        cutoff = db.execute("SELECT seq FROM events ORDER BY seq DESC LIMIT 1 OFFSET ?", (self.max_events - 1,)).fetchone()
        if cutoff:
            db.execute("DELETE FROM events WHERE seq < ?", (cutoff[0],))
        db.execute("DELETE FROM hosts WHERE received < ?", (time.time() - self.retention_days * 86400,))

    def prune(self):
        with self.connection() as db:
            self._prune(db)

    def events(self, job_id=None, trace_id=None, after=0, limit=100):
        clauses, params = ["seq > ?"], [after]
        for column, value in (("job_id", job_id), ("trace_id", trace_id)):
            if value:
                clauses.append(f"{column} = ?")
                params.append(value)
        with self.connection() as db:
            # Cursor follows ingestion order; UI sorts timestamp/seq within the returned set.
            rows = db.execute(f"SELECT seq,payload FROM events WHERE {' AND '.join(clauses)} ORDER BY seq LIMIT ?", (*params, limit + 1)).fetchall()
        return {"events": [{**json.loads(r['payload']), "seq": r['seq']} for r in rows[:limit]],
                "next_cursor": rows[min(len(rows), limit) - 1]['seq'] if rows else after,
                "has_more": len(rows) > limit}

    def jobs(self, status="", service="", q="", limit=50, offset=0):
        # A completed tool/span never changes a root job's lifecycle status.
        with self.connection() as db:
            rows = db.execute("""
                WITH roots AS (
                    SELECT *, ROW_NUMBER() OVER (PARTITION BY job_id ORDER BY timestamp DESC, seq DESC) AS rn
                    FROM events WHERE kind='job'
                )
                SELECT * FROM roots WHERE rn=1 AND (?='' OR status=?)
                    AND (?='' OR service=?) AND (?='' OR instr(job_id, ?) > 0)
                ORDER BY timestamp DESC,seq DESC LIMIT ? OFFSET ?
            """, (status,status,service,service,q,q,limit + 1,offset)).fetchall()
            jobs = []
            for row in rows[:limit]:
                data = json.loads(row['payload'])
                stats = db.execute("SELECT MIN(timestamp),COUNT(*),MAX(received) FROM events WHERE job_id=?", (row['job_id'],)).fetchone()
                data.update(event_count=stats[1], elapsed_seconds=max(0, (row['timestamp'] if data['status'] in TERMINAL else time.time()) - stats[0]),
                            last_received_at=stats[2], stale=data['status'] not in TERMINAL and time.time() - stats[2] > 300)
                jobs.append(data)
        return {"jobs": jobs, "has_more": len(rows) > limit, "next_offset": offset + len(jobs)}

    def host(self, snapshot: HostSnapshot):
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute("SELECT 1 FROM hosts WHERE host_id=?", (snapshot.host_id,)).fetchone() and db.execute("SELECT COUNT(*) FROM hosts").fetchone()[0] >= 100:
                raise ValueError("Maximum of 100 configured hosts reached")
            db.execute("""INSERT INTO hosts VALUES(?,?,?,?) ON CONFLICT(host_id) DO UPDATE SET
                timestamp=excluded.timestamp,received=excluded.received,payload=excluded.payload
                WHERE excluded.timestamp >= hosts.timestamp""", (snapshot.host_id, snapshot.timestamp.timestamp(), time.time(), snapshot.model_dump_json()))

    def hosts(self, stale_seconds=90):
        with self.connection() as db:
            rows = db.execute("SELECT * FROM hosts ORDER BY host_id").fetchall()
        return [{**json.loads(r['payload']), "received_at": r['received'], "stale": time.time() - r['timestamp'] > stale_seconds} for r in rows]

    def summary(self):
        with self.connection() as db:
            sources = db.execute("SELECT service,MAX(received) AS last_seen,COUNT(*) AS events FROM events GROUP BY service").fetchall()
            count = db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            states = db.execute("""WITH latest AS (SELECT status,ROW_NUMBER() OVER
                (PARTITION BY job_id ORDER BY timestamp DESC,seq DESC) AS rn FROM events WHERE kind='job')
                SELECT status,COUNT(*) AS count FROM latest WHERE rn=1 GROUP BY status""").fetchall()
            duration = db.execute("""WITH latest AS (SELECT status,payload,ROW_NUMBER() OVER
                (PARTITION BY job_id ORDER BY timestamp DESC,seq DESC) AS rn FROM events WHERE kind='job')
                SELECT AVG(json_extract(payload,'$.attributes.duration_ms')) FROM latest
                WHERE rn=1 AND status IN ('succeeded','failed','cancelled')""").fetchone()[0]
            model = db.execute("""WITH latest AS (SELECT status,payload,ROW_NUMBER() OVER
                (PARTITION BY service,trace_id,json_extract(payload,'$.span_id') ORDER BY timestamp DESC,seq DESC) AS rn
                FROM events WHERE kind='span' AND json_extract(payload,'$.phase')='model')
                SELECT SUM(json_extract(payload,'$.attributes.tokens_input')) AS tokens_input,
                    SUM(json_extract(payload,'$.attributes.tokens_output')) AS tokens_output,
                    SUM(json_extract(payload,'$.attributes.cost_usd')) AS cost_usd
                FROM latest WHERE rn=1 AND status='succeeded'""").fetchone()
        return {"event_count": count, "services": [dict(r) for r in sources], "jobs_by_status": {r['status']:r['count'] for r in states},
                "retention_days": self.retention_days, "max_events": self.max_events,
                "mean_job_duration_ms":duration, **dict(model)}
