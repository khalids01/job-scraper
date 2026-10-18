import asyncio
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from redis import Redis
from redis.exceptions import ConnectionError

from job_scraper.api import create_app
from job_scraper.config import Settings
from job_scraper.security import RedisRateLimiter


@pytest.fixture
def config(tmp_path):
    return Settings(api_key="r" * 40, database=tmp_path / "jobs.sqlite3", max_req_per_min=3)


def test_atomic_quota_and_concurrent_clients(config):
    async def run():
        first, second = RedisRateLimiter(config), RedisRateLimiter(config)
        try:
            await first.ping()
            decisions = await asyncio.gather(
                *(limiter.consume() for limiter in [first, second] * 20)
            )
            assert sum(d.allowed for d in decisions) == 3
            assert all(1 <= d.retry_after <= 60 for d in decisions)
            assert await first.redis.zcard(first.key) == 3
            assert 0 < await first.redis.pttl(first.key) <= 60000
            assert config.api_key not in first.key
        finally:
            await first.close()
            await second.close()

    asyncio.run(run())


def test_sliding_window_prunes_expired_entries_and_restores_capacity(config):
    async def run():
        limiter = RedisRateLimiter(replace(config, max_req_per_min=2))
        try:
            seconds, microseconds = await limiter.redis.time()
            now = seconds * 1000 + microseconds // 1000
            await limiter.redis.zadd(limiter.key, {"expired": now - 60001, "recent": now - 10000})
            decision = await limiter.consume()
            assert decision.allowed and decision.remaining == 0
            assert await limiter.redis.zscore(limiter.key, "expired") is None
            assert not (await limiter.consume()).allowed
            # Age both existing events instead of sleeping for an entire minute.
            entries = await limiter.redis.zrange(limiter.key, 0, -1)
            await limiter.redis.zadd(limiter.key, {entry: now - 60001 for entry in entries})
            assert (await limiter.consume()).allowed
        finally:
            await limiter.close()

    asyncio.run(run())


def test_single_key_headers_health_exemption_and_restart_persistence(config):
    headers = {"X-API-Key": config.api_key}
    with TestClient(create_app(config, schedule=False)) as client:
        for remaining in (2, 1, 0):
            result = client.get("/v1/jobs", headers=headers)
            assert result.status_code == 200
            assert result.headers["X-RateLimit-Limit"] == "3"
            assert result.headers["X-RateLimit-Remaining"] == str(remaining)
        result = client.get("/v1/sources", headers=headers)
        assert result.status_code == 429
        assert 1 <= int(result.headers["Retry-After"]) <= 60
        assert int(result.headers["X-RateLimit-Reset"]) > 0
        assert client.get("/healthz").status_code == 200
    with TestClient(create_app(config, schedule=False)) as client:
        assert client.get("/v1/jobs", headers=headers).status_code == 429


def test_same_key_shares_quota_across_app_instances(config, tmp_path):
    first = create_app(config, schedule=False)
    second = create_app(replace(config, database=tmp_path / "second.sqlite3"), schedule=False)
    headers = {"X-API-Key": config.api_key}
    with TestClient(first) as a, TestClient(second) as b:
        assert a.get("/v1/jobs", headers=headers).status_code == 200
        assert b.get("/v1/jobs", headers=headers).status_code == 200
        assert a.get("/v1/jobs", headers=headers).status_code == 200
        assert b.get("/v1/jobs", headers=headers).status_code == 429


def test_reads_and_collection_controls_share_one_quota(config):
    headers = {"X-API-Key": config.api_key}
    with TestClient(create_app(config, schedule=False)) as client:
        assert client.get("/v1/jobs", headers=headers).status_code == 200
        assert client.delete("/v1/runs/missing", headers=headers).status_code == 409
        assert (
            client.post("/v1/runs", headers=headers, json={"sources": ["unsupported"]}).status_code
            == 422
        )
        assert client.get("/v1/jobs", headers=headers).status_code == 429


def test_missing_wrong_and_duplicate_keys(config):
    with TestClient(create_app(config, schedule=False)) as client:
        for headers in (
            {},
            {"X-API-Key": "wrong"},
            [("X-API-Key", "wrong"), ("X-API-Key", config.api_key)],
        ):
            assert client.get("/v1/jobs", headers=headers).status_code == 401
        result = client.get(
            "/v1/jobs", headers=[("X-API-Key", config.api_key), ("X-API-Key", "wrong")]
        )
        assert result.status_code == 200 and result.headers["X-RateLimit-Remaining"] == "2"
        with Redis.from_url(config.redis_url) as redis:
            assert len(redis.keys("job-scraper:rate:*")) == 1


def test_redis_failure_returns_503_without_bypassing_or_exposing_details(config, monkeypatch):
    app = create_app(config, schedule=False)

    async def unavailable():
        raise ConnectionError("redis://user:secret@example.invalid:6379")

    with TestClient(app) as client:
        monkeypatch.setattr(app.state.limiter, "consume", unavailable)
        result = client.get("/v1/jobs", headers={"X-API-Key": config.api_key})
        assert result.status_code == 503 and result.headers["Retry-After"] == "2"
        assert "secret" not in result.text
        assert client.get("/v1/jobs").status_code == 401
        monkeypatch.setattr(app.state.limiter, "ping", unavailable)
        assert client.get("/healthz").status_code == 503


def test_unavailable_redis_prevents_startup(config):
    broken = replace(config, redis_url="redis://private:secret@127.0.0.1:1/0")
    with pytest.raises(RuntimeError, match="Redis is unavailable") as error:
        with TestClient(create_app(broken, schedule=False)):
            pass
    assert "secret" not in str(error.value)


def test_only_one_key_and_limit_are_required(monkeypatch, config):
    monkeypatch.setenv("API_KEY", config.api_key)
    monkeypatch.setenv("MAX_REQ_PER_MIN", "55")
    monkeypatch.delenv("ADMIN_API_KEY", raising=False)
    loaded = Settings.from_env()
    assert loaded.max_req_per_min == 55
    assert not hasattr(loaded, "admin_key")
    for value in (0, -1, 100001):
        with pytest.raises(ValueError, match="MAX_REQ_PER_MIN"):
            replace(config, max_req_per_min=value)
    with pytest.raises(ValueError, match="API_KEY"):
        replace(config, api_key="")


def test_reduced_limit_waits_for_enough_previous_requests_to_expire(config):
    async def run():
        limiter = RedisRateLimiter(replace(config, max_req_per_min=2))
        try:
            seconds, micros = await limiter.redis.time()
            now = seconds * 1000 + micros // 1000
            await limiter.redis.zadd(
                limiter.key,
                {
                    "a": now - 50000,
                    "b": now - 40000,
                    "c": now - 30000,
                    "d": now - 20000,
                },
            )
            result = await limiter.consume()
            assert not result.allowed and 29 <= result.retry_after <= 30
        finally:
            await limiter.close()

    asyncio.run(run())
