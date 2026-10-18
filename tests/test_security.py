from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from job_scraper.api import create_app
from job_scraper.config import Settings
from job_scraper.security import RateLimiter


@pytest.fixture
def config(tmp_path):
    return Settings(
        api_key="r" * 40,
        admin_key="a" * 40,
        database=tmp_path / "jobs.sqlite3",
        api_rate_limit_per_minute=3,
        admin_rate_limit_per_minute=2,
        auth_rate_limit_per_minute=2,
        ip_rate_limit_per_minute=20,
    )


def test_sliding_window_boundary_and_retry():
    timestamp = [0.0]
    limiter = RateLimiter(clock=lambda: timestamp[0])
    assert limiter.consume("key", 2).remaining == 1
    timestamp[0] = 10
    assert limiter.consume("key", 2).remaining == 0
    timestamp[0] = 59.1
    denied = limiter.consume("key", 2)
    assert not denied.allowed and denied.headers()["Retry-After"] == "1"
    timestamp[0] = 60
    assert limiter.consume("key", 2).allowed
    assert not limiter.consume("key", 2).allowed
    timestamp[0] = 70
    assert limiter.consume("key", 2).allowed


def test_bucket_capacity_recovery_and_rejections_do_not_reorder_expiry():
    timestamp = [0.0]
    limiter = RateLimiter(max_clients=2, clock=lambda: timestamp[0])
    limiter.consume("first", 1)
    timestamp[0] = 10
    limiter.consume("second", 1)
    assert not limiter.consume("first", 1).allowed
    assert not limiter.consume("third", 1).allowed
    timestamp[0] = 60
    assert limiter.consume("third", 1).allowed
    assert len(limiter.buckets) == 2


def test_parallel_consumption_does_not_exceed_limit():
    limiter = RateLimiter()
    with ThreadPoolExecutor(max_workers=8) as pool:
        decisions = list(pool.map(lambda _: limiter.consume("key", 10), range(50)))
    assert sum(decision.allowed for decision in decisions) == 10


def test_key_limits_headers_reset_and_health_exemption(config):
    app = create_app(config, schedule=False)
    headers = {"X-API-Key": config.api_key}
    timestamp = [0.0]
    with TestClient(app) as client:
        app.state.limiter.clock = lambda: timestamp[0]
        for remaining in (2, 1, 0):
            response = client.get("/v1/jobs", headers=headers)
            assert response.status_code == 200
            assert response.headers["X-RateLimit-Limit"] == "3"
            assert response.headers["X-RateLimit-Remaining"] == str(remaining)
        response = client.get("/v1/sources", headers=headers)
        assert response.status_code == 429 and response.headers["Retry-After"] == "60"
        assert int(response.headers["X-RateLimit-Reset"]) > 0
        for _ in range(5):
            assert client.get("/healthz").status_code == 200
        timestamp[0] = 60
        assert client.get("/v1/jobs", headers=headers).status_code == 200


def test_read_and_admin_have_separate_key_budgets(config):
    with TestClient(create_app(config, schedule=False)) as client:
        for _ in range(3):
            assert client.get("/v1/jobs", headers={"X-API-Key": config.api_key}).status_code == 200
        assert client.get("/v1/jobs", headers={"X-API-Key": config.api_key}).status_code == 429
        assert client.get("/v1/jobs", headers={"X-API-Key": config.admin_key}).status_code == 200


def test_admin_writes_have_tighter_budget_and_reads_still_work(config):
    config = replace(config, api_rate_limit_per_minute=20)
    with TestClient(create_app(config, schedule=False)) as client:
        for _ in range(2):
            result = client.delete("/v1/runs/nonexistent", headers={"X-API-Key": config.admin_key})
            assert result.status_code == 409
        result = client.delete("/v1/runs/nonexistent", headers={"X-API-Key": config.admin_key})
        assert result.status_code == 429 and result.headers["X-RateLimit-Limit"] == "2"
        assert client.get("/v1/jobs", headers={"X-API-Key": config.admin_key}).status_code == 200


def test_invalid_keys_share_ip_budget_and_forwarded_headers_do_not_bypass(config):
    app = create_app(config, schedule=False)
    with TestClient(app) as client:
        for i in range(2):
            assert (
                client.get(
                    "/v1/jobs",
                    headers={"X-API-Key": f"wrong-{i}", "X-Forwarded-For": f"192.0.2.{i}"},
                ).status_code
                == 401
            )
        assert client.get("/v1/jobs", headers={"X-API-Key": "another"}).status_code == 429
        assert client.get("/v1/jobs", headers={"X-API-Key": config.api_key}).status_code == 200
        assert len(app.state.limiter.buckets) == 3
        assert not any(
            "wrong-" in identity or config.api_key in identity
            for identity in app.state.limiter.buckets
        )


def test_ip_cap_is_shared_by_keys(config):
    config = replace(config, ip_rate_limit_per_minute=2)
    with TestClient(create_app(config, schedule=False)) as client:
        assert client.get("/v1/jobs", headers={"X-API-Key": config.api_key}).status_code == 200
        assert client.get("/v1/jobs", headers={"X-API-Key": config.admin_key}).status_code == 200
        response = client.get("/v1/jobs", headers={"X-API-Key": config.admin_key})
        assert response.status_code == 429 and response.headers["X-RateLimit-Limit"] == "2"


def test_duplicate_key_headers_use_same_first_value_as_authentication(config):
    config = replace(config, api_rate_limit_per_minute=20)
    headers = [("X-API-Key", config.admin_key), ("X-API-Key", config.api_key)]
    with TestClient(create_app(config, schedule=False)) as client:
        assert client.delete("/v1/runs/missing", headers=headers).status_code == 409
        assert client.delete("/v1/runs/missing", headers=headers).status_code == 409
        assert client.delete("/v1/runs/missing", headers=headers).status_code == 429


def test_rate_limit_environment_and_invalid_configuration(monkeypatch, config):
    monkeypatch.setenv("API_KEY", config.api_key)
    monkeypatch.setenv("ADMIN_API_KEY", config.admin_key)
    monkeypatch.setenv("API_RATE_LIMIT_PER_MINUTE", "55")
    monkeypatch.setenv("ADMIN_RATE_LIMIT_PER_MINUTE", "7")
    monkeypatch.setenv("AUTH_RATE_LIMIT_PER_MINUTE", "12")
    monkeypatch.setenv("IP_RATE_LIMIT_PER_MINUTE", "99")
    loaded = Settings.from_env()
    assert (
        loaded.api_rate_limit_per_minute,
        loaded.admin_rate_limit_per_minute,
        loaded.auth_rate_limit_per_minute,
        loaded.ip_rate_limit_per_minute,
    ) == (55, 7, 12, 99)
    for value in (0, -1, 100001):
        with pytest.raises(ValueError, match="rate limits"):
            replace(config, api_rate_limit_per_minute=value)
