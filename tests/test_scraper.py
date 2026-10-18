import asyncio
from dataclasses import replace

import httpx
import pytest
from fastapi.testclient import TestClient

from job_scraper.api import create_app
from job_scraper.collectors import SourceError, collect, normalize
from job_scraper.config import Settings
from job_scraper.service import CollectorService
from job_scraper.storage import Store

READ = "read-" + "a" * 40
HEADERS = {"X-API-Key": READ}


@pytest.fixture
def config(tmp_path):
    return Settings(api_key=READ, database=tmp_path / "jobs.sqlite3", request_delay=0)


def remotive(**overrides):
    return {
        "id": 12,
        "title": "React Engineer",
        "company_name": "Example",
        "url": "https://remotive.com/remote-jobs/software-dev/react-12",
        "description": "<p>Build <b>apps</b></p><script>bad()</script>",
        "candidate_required_location": "US only",
        "salary": "USD 40/hour",
        "publication_date": "2026-10-01T12:00:00",
        **overrides,
    }


def response(payload):
    return httpx.Response(200, json=payload)


def test_normalization_preserves_restrictions_and_unknowns():
    job = normalize("remotive", remotive())
    assert job.location == "US only" and job.remote is True
    assert job.salary_text == "USD 40/hour"
    assert job.description == "Build apps"
    assert job.published_at == "2026-10-01T12:00:00+00:00"
    job = normalize("arbeitnow", {"slug": "x", "title": "Nurse", "url": "https://example.com/x"})
    assert job.remote is None and job.location is None
    with pytest.raises(ValueError):
        normalize("remotive", remotive(url="javascript:alert(1)"))


def test_himalayas_keeps_source_link_and_timezone():
    job = normalize(
        "himalayas",
        {
            "guid": "https://himalayas.app/companies/ex/jobs/123",
            "applicationLink": "https://ats.example.com/123",
            "title": "Engineer",
            "locationRestrictions": ["Germany"],
            "timezoneRestrictions": [1, 2],
            "minSalary": 0,
            "maxSalary": 100,
            "currency": "EUR",
            "salaryPeriod": "hourly",
        },
    )
    assert job.source_url.startswith("https://himalayas.app/")
    assert job.timezone_restrictions == [1, 2]
    assert job.salary_text == "0 100 EUR hourly"


def test_pagination_dedup_and_invalid_records(config):
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.params.get("page") == "1":
            return response(
                {
                    "data": [
                        {
                            "slug": "a",
                            "title": "Full Stack Developer",
                            "url": "https://e.com/a",
                            "remote": True,
                        },
                        {"slug": "invalid"},
                    ],
                    "links": {"next": "https://evil.test"},
                }
            )
        return response(
            {
                "data": [
                    {
                        "slug": "a",
                        "title": "Full Stack Developer",
                        "url": "https://e.com/a",
                        "remote": True,
                    },
                    {
                        "slug": "b",
                        "title": "React Engineer",
                        "url": "https://e.com/b",
                        "remote": True,
                    },
                ],
                "links": {"next": None},
            }
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await collect("arbeitnow", client, config)

    batch = asyncio.run(run())
    assert len(batch.jobs) == 2 and batch.invalid == 1 and batch.duplicates == 1
    assert len(requests) == 2
    assert all(r.url.host == "www.arbeitnow.com" for r in requests)


@pytest.mark.parametrize(
    "result",
    [
        httpx.Response(429),
        httpx.Response(403),
        httpx.Response(302, headers={"location": "http://localhost"}),
        httpx.Response(200, text="<html>challenge</html>"),
        response({"unexpected": []}),
        httpx.Response(200, content=b"not json", headers={"content-type": "application/json"}),
    ],
)
def test_source_errors_are_visible(config, result):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: result)) as client:
            with pytest.raises(SourceError):
                await collect("remotive", client, config)

    asyncio.run(run())


def test_bounded_responses_and_results(config):
    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: response({"jobs": [remotive(id=1), remotive(id=2)]})
            )
        ) as client:
            batch = await collect("remotive", client, replace(config, max_jobs=1))
            assert len(batch.jobs) == 1 and batch.truncated
            with pytest.raises(SourceError, match="byte limit"):
                await collect("remotive", client, replace(config, max_response_bytes=10))

    asyncio.run(run())


def test_storage_upsert_filter_and_retention(config):
    store = Store(config.database)
    job = normalize("remotive", remotive())
    assert store.save([job]) == {"inserted": 1, "updated": 0}
    updated = job.model_copy(update={"title": "Senior React Engineer", "first_seen_at": "later"})
    assert store.save([updated]) == {"inserted": 0, "updated": 1}
    assert store.job(job.id)["first_seen_at"] == job.first_seen_at
    assert store.jobs(q="senior", remote=True)["total"] == 1
    assert store.jobs(q="%")["total"] == 0
    assert store.jobs(source="arbeitnow")["total"] == 0
    assert store.jobs(offset=1)["items"] == []
    expired = normalize("remotive", remotive(id=99)).model_copy(
        update={
            "expires_at": "2000-01-01T00:00:00+00:00",
            "fetched_at": "2000-01-01T00:00:00+00:00",
        }
    )
    store.save([expired])
    assert store.jobs()["total"] == 1
    assert store.jobs(include_expired=True)["total"] == 2
    store.prune(90)
    assert store.jobs(include_expired=True)["total"] == 1


def test_api_auth_validation_and_contract(config):
    app = create_app(config, schedule=False)
    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200
        for endpoint in ("/v1/jobs", "/v1/sources", "/v1/runs", "/openapi.json"):
            assert client.get(endpoint).status_code == 401
            assert (
                client.get(endpoint, headers={"X-API-Key": "é".encode().hex()}).status_code == 401
            )
            assert client.get(endpoint, headers=HEADERS).status_code == 200
        assert client.post("/v1/runs", json={}).status_code == 401
        assert client.get("/v1/jobs?limit=201", headers=HEADERS).status_code == 422
        assert client.get("/v1/jobs?since=2026-01-01", headers=HEADERS).status_code == 422
        assert client.get("/v1/jobs/missing", headers=HEADERS).status_code == 404
        assert (
            client.post("/v1/runs", headers=HEADERS, json={"sources": ["unsupported"]}).status_code
            == 422
        )
        assert client.get("/v1/jobs", headers=HEADERS).json()["items"] == []


def test_runs_partial_cooldown_recovery_and_cancellation(config):
    async def run():
        async def handler(request):
            if request.url.host == "remotive.com":
                return response({"jobs": [remotive()]})
            return httpx.Response(429)

        store = Store(config.database)
        service = CollectorService(store, config, httpx.MockTransport(handler))
        run_id = service.start(["remotive", "arbeitnow"])
        with pytest.raises(RuntimeError):
            service.start(["himalayas"])
        await service.active
        result = store.run(run_id)
        assert result["status"] == "partial"
        assert result["results"]["remotive"]["inserted"] == 1
        assert "429" in result["results"]["arbeitnow"]["error"]
        restarted = CollectorService(Store(config.database), config)
        with pytest.raises(ValueError, match="cooling down"):
            restarted.start(["remotive"])
        broken_id = store.start_run(["himalayas"])
        store.recover()
        assert store.run(broken_id)["status"] == "interrupted"

        async def slow(_):
            await asyncio.sleep(10)

        service.transport = httpx.MockTransport(slow)
        cancel_id = service.start(["himalayas"])
        await asyncio.sleep(0.01)
        await service.stop()
        assert store.run(cancel_id)["status"] == "cancelled"

    asyncio.run(run())


def test_api_run_and_persistence(config):
    transport = httpx.MockTransport(lambda _: response({"jobs": [remotive()]}))
    with TestClient(create_app(config, transport=transport, schedule=False)) as client:
        result = client.post("/v1/runs", headers=HEADERS, json={"sources": ["remotive"]})
        assert result.status_code == 202
        run_id = result.json()["id"]
        # TestClient portal waits on the actual worker, without timing-based polling.
        client.portal.call(lambda: client.app.state.service.active)
        assert client.get(f"/v1/runs/{run_id}", headers=HEADERS).json()["status"] == "completed"
        assert (
            client.post("/v1/runs", headers=HEADERS, json={"sources": ["remotive"]}).status_code
            == 429
        )
        jobs = client.get("/v1/jobs?q=React", headers=HEADERS).json()
        assert jobs["total"] == 1
        assert client.get("/v1/jobs/" + jobs["items"][0]["id"], headers=HEADERS).status_code == 200
    with TestClient(create_app(config, schedule=False)) as client:
        assert client.get("/v1/jobs", headers=HEADERS).json()["total"] == 1
        assert client.get("/v1/sources", headers=HEADERS).json()["items"][0]["last_attempt_at"]


def test_single_process_ownership_and_missing_keys(config):
    with pytest.raises(ValueError):
        replace(config, api_key="")
    with pytest.raises(ValueError):
        replace(config, interval_seconds=60)
    with TestClient(create_app(config, schedule=False)):
        with pytest.raises(RuntimeError, match="already in use"):
            with TestClient(create_app(config, schedule=False)):
                pass


def test_scheduler_collects_once_and_respects_persisted_cooldown(config):
    config = replace(config, sources=("remotive",))
    calls = []

    def handler(request):
        calls.append(request)
        return response({"jobs": [remotive()]})

    app = create_app(config, transport=httpx.MockTransport(handler))
    with TestClient(app) as client:

        async def complete_initial_run():
            # Scheduler is a real task; yield until it has launched its worker.
            while app.state.service.active is None:
                await asyncio.sleep(0)
            await app.state.service.active

        client.portal.call(complete_initial_run)
        assert client.get("/v1/jobs", headers=HEADERS).json()["total"] == 1
        assert len(calls) == 1
    with TestClient(create_app(config, transport=httpx.MockTransport(handler))) as client:
        assert client.get("/healthz").status_code == 200
        assert len(calls) == 1


def test_cancel_and_default_enabled_sources(config):
    async def slow(_):
        await asyncio.sleep(10)
        return response({"jobs": []})

    config = replace(config, sources=("remotive",))
    app = create_app(config, transport=httpx.MockTransport(slow), schedule=False)
    with TestClient(app) as client:
        started = client.post("/v1/runs", headers=HEADERS, json={})
        assert started.status_code == 202
        run_id = started.json()["id"]
        assert client.delete(f"/v1/runs/{run_id}").status_code == 401
        result = client.delete(f"/v1/runs/{run_id}", headers=HEADERS)
        assert result.status_code == 200 and result.json()["status"] == "cancelled"
        assert result.json()["sources"] == ["remotive"]
        assert client.delete(f"/v1/runs/{run_id}", headers=HEADERS).status_code == 409
        assert (
            client.post("/v1/runs", headers=HEADERS, json={"sources": ["himalayas"]}).status_code
            == 422
        )


def test_total_source_timeout_is_recorded(config):
    async def slow(_):
        await asyncio.sleep(10)

    async def run():
        service = CollectorService(
            Store(config.database), replace(config, source_timeout=0.01), httpx.MockTransport(slow)
        )
        run_id = service.start(["remotive"])
        await service.active
        result = service.store.run(run_id)
        assert result["status"] == "failed"
        assert result["results"]["remotive"]["error"] == "Source timeout"

    asyncio.run(run())
