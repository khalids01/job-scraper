"""CPU semantic ranking. No paid API calls and no persisted candidate profiles."""

import hashlib
import os
import threading
from collections import OrderedDict
from typing import Annotated

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from .sources import Source

Text = Annotated[str, Field(min_length=1, max_length=200)]
MODEL = "BAAI/bge-small-en-v1.5"


class MatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile: str = Field(min_length=10, max_length=12000)
    titles: list[Text] = Field(default_factory=list, max_length=12)
    q: str = Field(default="", max_length=200)
    source: Source | None = None
    remote_only: bool = False
    excluded_terms: list[Text] = Field(default_factory=list, max_length=50)
    limit: int = Field(default=50, ge=1, le=100)


class MatchingBusy(RuntimeError):
    pass


class SemanticMatcher:
    def __init__(self, embedder=None):
        self.model = embedder
        self.lock = threading.Lock()
        self.cache = OrderedDict()

    def _vectors(self, texts):
        keys = [hashlib.sha256(text.encode()).hexdigest() for text in texts]
        missing = dict((key, text) for key, text in zip(keys, texts) if key not in self.cache)
        if missing:
            vectors = self.model.embed(list(missing.values()), batch_size=32)
            for key, vector in zip(missing, vectors):
                self.cache[key] = np.asarray(vector)
        result = [self.cache[key] for key in keys]
        for key in keys:
            self.cache.move_to_end(key)
        while len(self.cache) > 4096:
            self.cache.popitem(last=False)
        return result

    def rank(self, store, request: MatchRequest):
        if not self.lock.acquire(blocking=False):
            raise MatchingBusy("Matching is busy; retry shortly")
        try:
            return self._rank(store, request)
        finally:
            self.lock.release()

    def _rank(self, store, request: MatchRequest):
        # Bound CPU work. Return coverage explicitly rather than claiming exhaustive search.
        page = store.jobs(
            q=request.q or None,
            source=request.source,
            remote=True if request.remote_only else None,
            limit=1000,
        )
        jobs = [
            job
            for job in page["items"]
            if not any(
                term.casefold() in (job["title"] + " " + job["description"]).casefold()
                for term in request.excluded_terms
            )
        ]
        if not jobs:
            return {
                "items": [],
                "total": page["total"],
                "truncated": page["total"] > 1000,
                "model": MODEL,
                "scanned": len(page["items"]),
            }
        # Serialize inference and lazy initialization to bound memory/CPU under concurrent calls.
        if self.model is None:
            from fastembed import TextEmbedding

            self.model = TextEmbedding(
                model_name=MODEL,
                threads=2,
                cache_dir=os.getenv("FASTEMBED_CACHE_PATH", "/models"),
                local_files_only=True,
            )
        queries = [request.profile[:6000], *request.titles]
        query_vectors = list(self.model.embed(queries, batch_size=16))
        documents = [
            f"{job['title']}. {', '.join(job['tags'])}. {job['description'][:2200]}" for job in jobs
        ]
        vectors = self._vectors(documents)

        def cosine(a, b):
            return float(np.dot(a, b) / max(float(np.linalg.norm(a) * np.linalg.norm(b)), 1e-9))

        ranked = []
        for job, vector in zip(jobs, vectors):
            profile_score = cosine(query_vectors[0], vector)
            title_score = max((cosine(q, vector) for q in query_vectors[1:]), default=profile_score)
            score = round(100 * max(0, min(1, 0.8 * profile_score + 0.2 * title_score)), 1)
            ranked.append({"job": job, "score": score})
        ranked.sort(key=lambda row: (-row["score"], row["job"]["id"]))
        return {
            "items": [
                {**row, "job": {**row["job"], "description": row["job"]["description"][:6000]}}
                for row in ranked[: request.limit]
            ],
            "total": page["total"],
            "truncated": page["total"] > len(page["items"]),
            "model": MODEL,
            "scanned": len(page["items"]),
        }
