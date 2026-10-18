import asyncio
import logging
from contextlib import suppress
from datetime import UTC, datetime

import httpx

from .collectors import SourceError, collect
from .config import Settings
from .storage import Store

log = logging.getLogger(__name__)


class CollectorService:
    def __init__(self, store: Store, settings: Settings, transport=None):
        self.store, self.settings, self.transport = store, settings, transport
        self.active: asyncio.Task | None = None
        self.run_id: str | None = None
        self.timer: asyncio.Task | None = None

    def due(self, sources):
        attempts = self.store.attempts()
        return [
            source
            for source in sources
            if source not in attempts
            or (datetime.now(UTC) - datetime.fromisoformat(attempts[source])).total_seconds()
            >= self.settings.interval_seconds
        ]

    def start(self, sources):
        if self.active and not self.active.done():
            raise RuntimeError("A collection run is already active")
        sources = list(dict.fromkeys(sources))
        due = self.due(sources)
        if len(due) != len(sources):
            raise ValueError("One or more sources are cooling down; inspect GET /v1/sources")
        self.run_id = self.store.start_run(sources)
        self.active = asyncio.create_task(self.execute(self.run_id, sources))
        return self.run_id

    async def execute(self, run_id, sources):
        results = {}
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(25, connect=10),
                follow_redirects=False,
                headers={
                    "User-Agent": "JobAgentScraper/0.1 (personal job discovery)",
                    "Accept": "application/json",
                },
                transport=self.transport,
            ) as client:
                for source in sources:
                    # Persist before the request so restarting cannot evade cooldown.
                    self.store.mark_attempt(source)
                    results[source] = {"status": "running"}
                    self.store.update_run(run_id, results)
                    try:
                        async with asyncio.timeout(self.settings.source_timeout):
                            batch = await collect(source, client, self.settings)
                        counts = self.store.save(batch.jobs)
                        stats = {key: value for key, value in vars(batch).items() if key != "jobs"}
                        results[source] = {
                            "status": "completed",
                            "accepted": len(batch.jobs),
                            **stats,
                            **counts,
                        }
                    except (SourceError, TimeoutError) as exc:
                        results[source] = {
                            "status": "failed",
                            "error": str(exc) or "Source timeout",
                        }
                    self.store.update_run(run_id, results)
            failed = sum(result["status"] == "failed" for result in results.values())
            degraded = any(r.get("truncated") or r.get("invalid") for r in results.values())
            status = (
                "failed"
                if failed == len(sources)
                else "partial"
                if failed or degraded
                else "completed"
            )
            self.store.update_run(run_id, results, status)
            self.store.prune(self.settings.retention_days)
        except asyncio.CancelledError:
            for result in results.values():
                if result["status"] == "running":
                    result["status"] = "cancelled"
            self.store.update_run(run_id, results, "cancelled")
            raise
        except Exception:
            # Never serialize exception text: URLs or configuration may contain secrets.
            log.error("Collection failed unexpectedly; run=%s", run_id)
            results["service"] = {"status": "failed", "error": "Internal collection failure"}
            self.store.update_run(run_id, results, "failed")

    async def schedule(self):
        while True:
            if not self.active or self.active.done():
                due = self.due(self.settings.sources)
                if due:
                    self.start(due)
            await asyncio.sleep(30)

    async def stop(self):
        for task in (self.timer, self.active):
            if task and not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
        if self.run_id:
            run = self.store.run(self.run_id)
            if run and run["status"] == "running":
                self.store.update_run(self.run_id, run["results"], "cancelled")
