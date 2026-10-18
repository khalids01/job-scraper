import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from .models import Job, now


class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, source TEXT NOT NULL, source_id TEXT NOT NULL,
                    title TEXT NOT NULL, company TEXT, location TEXT, remote INTEGER,
                    published_at TEXT, expires_at TEXT, first_seen_at TEXT NOT NULL,
                    fetched_at TEXT NOT NULL, document TEXT NOT NULL,
                    UNIQUE(source, source_id)
                );
                CREATE INDEX IF NOT EXISTS jobs_fetched ON jobs(fetched_at DESC, id);
                CREATE INDEX IF NOT EXISTS jobs_source ON jobs(source);
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, status TEXT NOT NULL, started_at TEXT NOT NULL,
                    finished_at TEXT, sources TEXT NOT NULL, results TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS source_attempts (
                    source TEXT PRIMARY KEY, attempted_at TEXT NOT NULL
                );
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def recover(self):
        with self.connect() as db:
            db.execute(
                "UPDATE runs SET status='interrupted', finished_at=? WHERE status='running'",
                (now(),),
            )

    def start_run(self, sources: list[str]) -> str:
        run_id = uuid4().hex
        with self.connect() as db:
            db.execute(
                "INSERT INTO runs VALUES (?, 'running', ?, NULL, ?, '{}')",
                (run_id, now(), json.dumps(sources)),
            )
        return run_id

    def update_run(self, run_id: str, results: dict, status: str = "running"):
        with self.connect() as db:
            db.execute(
                "UPDATE runs SET results=?, status=?, finished_at=? WHERE id=?",
                (json.dumps(results), status, None if status == "running" else now(), run_id),
            )

    def runs(self, limit=20):
        with self.connect() as db:
            rows = db.execute("SELECT * FROM runs ORDER BY started_at DESC LIMIT ?", (limit,))
            return [self.decode_run(row) for row in rows]

    @staticmethod
    def decode_run(row):
        return {
            **dict(row),
            "sources": json.loads(row["sources"]),
            "results": json.loads(row["results"]),
        }

    def run(self, run_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            return self.decode_run(row) if row else None

    def attempts(self) -> dict[str, str]:
        with self.connect() as db:
            return dict(db.execute("SELECT source, attempted_at FROM source_attempts"))

    def mark_attempt(self, source: str):
        with self.connect() as db:
            db.execute(
                "INSERT INTO source_attempts VALUES (?, ?) ON CONFLICT(source) "
                "DO UPDATE SET attempted_at=excluded.attempted_at",
                (source, now()),
            )

    def save(self, jobs: list[Job]) -> dict:
        inserted = 0
        with self.connect() as db:
            for job in jobs:
                existing = db.execute(
                    "SELECT first_seen_at FROM jobs WHERE id=?", (job.id,)
                ).fetchone()
                if existing:
                    job = job.model_copy(update={"first_seen_at": existing[0]})
                else:
                    inserted += 1
                db.execute(
                    """INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET title=excluded.title, company=excluded.company,
                    location=excluded.location, remote=excluded.remote,
                    published_at=excluded.published_at, expires_at=excluded.expires_at,
                    fetched_at=excluded.fetched_at, document=excluded.document""",
                    (
                        job.id,
                        job.source,
                        job.source_id,
                        job.title,
                        job.company,
                        job.location,
                        job.remote,
                        job.published_at,
                        job.expires_at,
                        job.first_seen_at,
                        job.fetched_at,
                        job.model_dump_json(),
                    ),
                )
        return {"inserted": inserted, "updated": len(jobs) - inserted}

    def job(self, job_id):
        with self.connect() as db:
            row = db.execute("SELECT document FROM jobs WHERE id=?", (job_id,)).fetchone()
            return json.loads(row[0]) if row else None

    def jobs(
        self,
        *,
        q=None,
        source=None,
        remote=None,
        since=None,
        limit=50,
        offset=0,
        include_expired=False,
    ):
        clauses, values = [], []
        for key, value in (("source", source), ("remote", remote)):
            if value is not None:
                clauses.append(f"{key}=?")
                values.append(value)
        if q:
            clauses.append(
                "(instr(lower(title), lower(?)) > 0 OR "
                "instr(lower(coalesce(company, '')), lower(?)) > 0)"
            )
            values.extend([q, q])
        if since:
            clauses.append("fetched_at>=?")
            values.append(since)
        if not include_expired:
            clauses.append("(expires_at IS NULL OR expires_at>?)")
            values.append(now())
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self.connect() as db:
            total = db.execute("SELECT count(*) FROM jobs" + where, values).fetchone()[0]
            rows = db.execute(
                "SELECT document FROM jobs"
                + where
                + " ORDER BY fetched_at DESC, id LIMIT ? OFFSET ?",
                [*values, limit, offset],
            )
            return {
                "items": [json.loads(row[0]) for row in rows],
                "total": total,
                "limit": limit,
                "offset": offset,
            }

    def prune(self, retention_days):
        cutoff = (datetime.now(UTC) - timedelta(days=retention_days)).isoformat()
        with self.connect() as db:
            db.execute("DELETE FROM jobs WHERE fetched_at<?", (cutoff,))
            db.execute("DELETE FROM runs WHERE finished_at<?", (cutoff,))
