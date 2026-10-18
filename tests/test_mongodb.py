from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure

from job_scraper.api import create_app
from job_scraper.collectors import normalize
from job_scraper.config import Settings
from job_scraper.storage import Store


def test_database_selection_and_secret_validation(mongodb_url, monkeypatch):
    settings = Settings(api_key="a" * 40)
    assert settings.mongodb_url == mongodb_url
    assert mongodb_url not in repr(settings)
    monkeypatch.setenv("MONGODB_URL", "https://secret@example.invalid")
    with pytest.raises(ValueError, match="MONGODB_URL") as error:
        Settings.from_env()
    assert "secret" not in str(error.value)
    monkeypatch.delenv("MONGODB_URL")
    with pytest.raises(ValueError, match="MONGODB_URL"):
        Settings(api_key="a" * 40)


def test_lease_exclusivity_renewal_crash_recovery_and_safe_release(mongodb_url):
    first, second = Store(mongodb_url), Store(mongodb_url)
    try:
        first.acquire()
        first.renew()
        with pytest.raises(RuntimeError, match="already in use"):
            second.acquire()
        # Simulate crash expiry, using a real BSON date rather than string comparison.
        first.db.leases.update_one(
            {"_id": "collector"}, {"$set": {"expires_at": datetime.now(UTC) - timedelta(seconds=1)}}
        )
        second.acquire()
        with pytest.raises(RuntimeError, match="ownership lost"):
            first.renew()
        with pytest.raises(RuntimeError, match="ownership lost"):
            first.mark_attempt("remotive")
        first.close()
        second.renew()  # Stale owner's cleanup cannot release the new owner's lease.
    finally:
        first.client.close()
        second.close()
    third = Store(mongodb_url)
    try:
        third.acquire()
    finally:
        third.close()


def test_mongodb_failure_is_sanitized_in_health_reads_and_startup(mongodb_url, monkeypatch):
    config = Settings(api_key="a" * 40)
    app = create_app(config, schedule=False)

    def unavailable(*args, **kwargs):
        raise ConnectionFailure("mongodb://user:private-secret@host/db")

    with TestClient(app) as client:
        monkeypatch.setattr(app.state.store, "ping", unavailable)
        response = client.get("/healthz")
        assert response.status_code == 503 and "private-secret" not in response.text
        monkeypatch.setattr(app.state.store, "jobs", unavailable)
        response = client.get("/v1/jobs", headers={"X-API-Key": config.api_key})
        assert response.status_code == 503 and "private-secret" not in response.text
        app.state.database_ready = False
        assert client.get("/v1/sources", headers={"X-API-Key": config.api_key}).status_code == 503
    broken = replace(config, mongodb_url="mongodb://user:private-secret@127.0.0.1:1/db")
    with pytest.raises(RuntimeError, match="MongoDB is unavailable") as error:
        with TestClient(create_app(broken, schedule=False)):
            pass
    assert "private-secret" not in str(error.value)


def test_literal_search_ordering_retention_and_run_persistence(mongodb_url):
    store = Store(mongodb_url)
    try:
        jobs = [
            normalize(
                "remotive",
                {
                    "id": i,
                    "title": "TypeScript Developer",
                    "company_name": "A.* Company",
                    "url": f"https://example.com/{i}",
                    "description": "TypeScript",
                },
            ).model_copy(update={"fetched_at": "2026-10-19T00:00:00+00:00"})
            for i in range(1, 4)
        ]
        store.save(jobs)
        assert store.jobs(q=".*")["total"] == 3
        assert store.jobs(q=".*absent")["total"] == 0
        expected = sorted(job.id for job in jobs)
        assert [job["id"] for job in store.jobs()["items"]] == expected
        assert store.jobs(offset=1, limit=1)["items"][0]["id"] == expected[1]
        assert store.jobs(since="2099-01-01T00:00:00+00:00")["total"] == 0
        assert store.jobs(remote=False)["total"] == 0
        run_id = store.start_run(["remotive"])
        store.update_run(run_id, {"remotive": {"accepted": 3}}, "completed")
        result = store.run(run_id)
        assert "_id" not in result and result["results"]["remotive"]["accepted"] == 3
        store.db.runs.update_one(
            {"_id": run_id}, {"$set": {"finished_at": "2000-01-01T00:00:00+00:00"}}
        )
        store.prune(90)
        assert store.run(run_id) is None
        assert store.db.jobs.index_information()["source_1_source_id_1"]["unique"]
    finally:
        store.close()


def test_uri_database_is_used_without_touching_other_databases(mongodb_url):
    store = Store(mongodb_url)
    try:
        assert store.db.name == mongodb_url.rsplit("/", 1)[1]
        with MongoClient(mongodb_url) as client:
            assert client.get_default_database().name == store.db.name
    finally:
        store.close()
