import numpy as np
import pytest
from pydantic import ValidationError

from job_scraper.matching import MatchRequest, SemanticMatcher


class Embeddings:
    def __init__(self):
        self.documents = []

    def embed(self, texts, **kwargs):
        for text in texts:
            self.documents.append(text)
            yield np.array([1.0, 0.0]) if "developer" in text else np.array([0.0, 1.0])


class Store:
    def jobs(self, **kwargs):
        self.query = kwargs
        return {
            "total": 1002,
            "items": [
                {"id": "1", "title": "sales", "description": "sales", "tags": []},
                {"id": "2", "title": "developer", "description": "web developer", "tags": []},
            ],
        }


def test_ranks_semantically_caches_only_jobs_and_reports_coverage():
    embedder, store = Embeddings(), Store()
    matcher = SemanticMatcher(embedder)
    request = MatchRequest(profile="experienced developer", titles=["web developer"])
    result = matcher.rank(store, request)
    assert result["items"][0]["job"]["id"] == "2"
    assert result["items"][0]["score"] == 100
    assert result["truncated"] and result["scanned"] == 2
    matcher.rank(store, request)
    assert embedder.documents.count("developer. . web developer") == 1
    assert embedder.documents.count("experienced developer") == 2


def test_exclusions_and_query_forwarding():
    store = Store()
    result = SemanticMatcher(Embeddings()).rank(
        store,
        MatchRequest(
            profile="experienced developer", excluded_terms=["sales"], remote_only=True, q="react"
        ),
    )
    assert len(result["items"]) == 1
    assert store.query["remote"] is True and store.query["q"] == "react"


def test_limits_and_unknown_parameters():
    for payload in (
        {"profile": "x"},
        {"profile": "developer profile", "limit": 101},
        {"profile": "developer profile", "api_key": "secret"},
    ):
        with pytest.raises(ValidationError):
            MatchRequest(**payload)


def test_matching_endpoint_requires_key_validates_and_uses_same_quota(monkeypatch):
    from fastapi.testclient import TestClient

    from job_scraper.api import create_app
    from job_scraper.config import Settings

    called = []

    def rank(self, store, request):
        called.append(request)
        return {"items": [], "total": 0, "scanned": 0, "truncated": False, "model": "fixture"}

    monkeypatch.setattr(SemanticMatcher, "rank", rank)
    key = "m" * 40
    with TestClient(create_app(Settings(api_key=key), schedule=False)) as client:
        assert (
            client.post("/v1/matches", json={"profile": "experienced developer"}).status_code == 401
        )
        assert not called
        headers = {"X-API-Key": key}
        assert (
            client.post("/v1/matches", headers=headers, json={"profile": "short"}).status_code
            == 422
        )
        response = client.post(
            "/v1/matches", headers=headers, json={"profile": "experienced developer"}
        )
        assert response.status_code == 200 and response.json()["model"] == "fixture"
        assert "x-ratelimit-remaining" in response.headers
        assert len(called) == 1


def test_busy_matcher_rejects_without_loading_another_corpus():
    from job_scraper.matching import MatchingBusy

    matcher = SemanticMatcher(Embeddings())
    matcher.lock.acquire()
    try:
        with pytest.raises(MatchingBusy):
            matcher.rank(Store(), MatchRequest(profile="experienced developer"))
    finally:
        matcher.lock.release()


def test_cold_index_returns_progress_and_resumes_cached_batches(monkeypatch):
    import job_scraper.matching as module

    clock = [0.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])

    class SlowEmbedding:
        def embed(self, texts, **kwargs):
            for _ in texts:
                clock[0] += 2
                yield np.array([1.0, 0.0])

    class ManyJobs:
        def jobs(self, **kwargs):
            return {
                "total": 10,
                "items": [
                    {"id": str(i), "title": f"developer {i}", "description": "web", "tags": []}
                    for i in range(10)
                ],
            }

    matcher = SemanticMatcher(SlowEmbedding())
    request = MatchRequest(profile="experienced developer")
    first = matcher.rank(ManyJobs(), request)
    assert first["indexing"] and first["indexed"] == 8
    second = matcher.rank(ManyJobs(), request)
    assert not second["indexing"] and second["indexed"] == 10
