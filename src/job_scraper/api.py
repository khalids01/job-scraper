import asyncio
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.security import APIKeyHeader
from pymongo.errors import PyMongoError
from redis.exceptions import RedisError

from .config import Settings
from .models import RunRequest, Source
from .security import RateLimitMiddleware, RedisRateLimiter, valid_key
from .service import CollectorService
from .sources import SPECS
from .storage import Store

header = APIKeyHeader(name="X-API-Key", auto_error=False)


def create_app(settings: Settings | None = None, *, transport=None, schedule=True):
    @asynccontextmanager
    async def lifespan(app):
        config = settings or Settings.from_env()
        try:
            store = await asyncio.to_thread(Store, config.mongodb_url)
        except PyMongoError:
            raise RuntimeError("MongoDB is unavailable; check MONGODB_URL") from None
        limiter = RedisRateLimiter(config)
        lease_task = None
        service = None
        try:
            try:
                await asyncio.to_thread(store.acquire)
                await asyncio.to_thread(store.recover)
            except PyMongoError:
                raise RuntimeError("MongoDB is unavailable; check MONGODB_URL") from None
            service = CollectorService(store, config, transport)
            app.state.store, app.state.service, app.state.settings = store, service, config
            app.state.limiter = limiter
            app.state.database_ready = True
            try:
                await limiter.ping()
            except RedisError:
                raise RuntimeError("Redis is unavailable; check REDIS_URL") from None

            async def maintain_lease():
                while True:
                    await asyncio.sleep(10)
                    try:
                        await asyncio.to_thread(store.renew)
                    except (PyMongoError, RuntimeError):
                        app.state.database_ready = False
                        # Stop source requests immediately if ownership cannot be verified.
                        await service.stop()
                        return

            lease_task = asyncio.create_task(maintain_lease())
            if schedule:
                service.timer = asyncio.create_task(service.schedule())
            yield
        finally:
            if lease_task:
                lease_task.cancel()
                with suppress(asyncio.CancelledError):
                    await lease_task
            try:
                if service:
                    await service.stop()
            finally:
                await limiter.close()
                with suppress(PyMongoError):
                    await asyncio.to_thread(store.close)

    app = FastAPI(
        title="Job Agent Scraper",
        version="0.4.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.add_middleware(RateLimitMiddleware, state=app.state)

    @app.exception_handler(PyMongoError)
    async def database_error(request, exc):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=503, content={"detail": "MongoDB unavailable"})

    def authorize(key: Annotated[str | None, Depends(header)]):
        if not valid_key(key, app.state.settings):
            raise HTTPException(401, "Invalid API key")
        if not app.state.database_ready:
            raise HTTPException(503, "Database ownership unavailable; restart the service")

    @app.get("/healthz")
    async def health():
        try:
            await app.state.limiter.ping()
        except RedisError:
            raise HTTPException(503, "Redis unavailable") from None
        if not app.state.database_ready:
            raise HTTPException(503, "Database ownership unavailable; restart the service")
        try:
            await asyncio.to_thread(app.state.store.ping)
        except PyMongoError:
            raise HTTPException(503, "MongoDB unavailable") from None
        timer = app.state.service.timer
        if schedule and timer and timer.done():
            raise HTTPException(503, "Scheduler stopped")
        return {"status": "ok", "version": "0.4.0"}

    @app.get("/v1/sources", dependencies=[Depends(authorize)])
    def sources():
        config = app.state.settings
        attempts = app.state.store.attempts()
        latest = {}
        for run in app.state.store.runs(limit=100):
            for source, result in run["results"].items():
                latest.setdefault(source, result)
        return {
            "items": [
                {
                    "source": source,
                    "name": SPECS[source].name,
                    "format": SPECS[source].format,
                    "feed_url": SPECS[source].url,
                    "documentation_url": SPECS[source].docs,
                    "last_result": latest.get(source),
                    "last_attempt_at": attempts.get(source),
                    "next_allowed_at": (
                        datetime.fromisoformat(attempts[source])
                        + timedelta(seconds=config.interval_seconds)
                    ).isoformat()
                    if source in attempts
                    else None,
                    "attribution_required": True,
                }
                for source in config.sources
            ],
            "limits": {
                "jobs_per_source": config.max_jobs,
                "pages_per_source": config.max_pages,
                "interval_seconds": config.interval_seconds,
            },
            "scope": {
                "remote_only": True,
                "roles": "Full-stack/frontend development or developer roles with a JavaScript/TypeScript stack",
                "search_terms": config.search_terms,
                "geographic_eligibility": "Not inferred; inspect each posting's restrictions",
            },
        }

    @app.get("/v1/jobs", dependencies=[Depends(authorize)])
    def jobs(
        q: str | None = Query(None, max_length=200),
        source: Source | None = None,
        remote: bool | None = None,
        since: datetime | None = None,
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0, le=1_000_000),
        include_expired: bool = False,
    ):
        if since and (since.tzinfo is None or since.utcoffset() is None):
            raise HTTPException(422, "since must include a timezone")
        return app.state.store.jobs(
            q=q,
            source=source,
            remote=remote,
            since=since.astimezone(UTC).isoformat() if since else None,
            limit=limit,
            offset=offset,
            include_expired=include_expired,
        )

    @app.get("/v1/jobs/{job_id}", dependencies=[Depends(authorize)])
    def job(job_id: str):
        result = app.state.store.job(job_id)
        if result is None:
            raise HTTPException(404, "Job not found")
        return result

    @app.get("/v1/runs", dependencies=[Depends(authorize)])
    def runs(limit: int = Query(20, ge=1, le=100)):
        return {"items": app.state.store.runs(limit)}

    @app.get("/v1/runs/{run_id}", dependencies=[Depends(authorize)])
    def run(run_id: str):
        result = app.state.store.run(run_id)
        if result is None:
            raise HTTPException(404, "Run not found")
        return result

    @app.post("/v1/runs", status_code=202, dependencies=[Depends(authorize)])
    async def start_run(request: RunRequest):
        selected = (
            request.sources if request.sources is not None else list(app.state.settings.sources)
        )
        if not set(selected) <= set(app.state.settings.sources):
            raise HTTPException(422, "Requested source is disabled")
        try:
            run_id = app.state.service.start(selected)
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from None
        except ValueError as exc:
            raise HTTPException(429, str(exc)) from None
        return {"id": run_id, "status": "running"}

    @app.delete("/v1/runs/{run_id}", dependencies=[Depends(authorize)])
    async def cancel(run_id: str):
        service = app.state.service
        if service.run_id != run_id or not service.active or service.active.done():
            raise HTTPException(409, "Run is not active in this process")
        service.active.cancel()

        with suppress(asyncio.CancelledError):
            await service.active
        # A task cancelled before its first instruction never enters execute().
        current = app.state.store.run(run_id)
        if current["status"] == "running":
            app.state.store.update_run(run_id, current["results"], "cancelled")
        return app.state.store.run(run_id)

    @app.get("/openapi.json", dependencies=[Depends(authorize)])
    def schema():
        return app.openapi()

    return app


app = create_app()
