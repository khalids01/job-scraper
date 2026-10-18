import os
from dataclasses import dataclass, field

from .sources import SPECS

SOURCES = tuple(SPECS)


@dataclass(frozen=True)
class Settings:
    api_key: str = field(repr=False)
    mongodb_url: str = field(
        default_factory=lambda: os.environ.get("MONGODB_URL", ""), repr=False
    )
    sources: tuple[str, ...] = SOURCES
    interval_seconds: int = 21600
    max_jobs: int = 500
    max_pages: int = 5
    max_response_bytes: int = 16_000_000
    source_timeout: float = 90
    retention_days: int = 90
    search_terms: tuple[str, ...] = ("typescript", "full stack", "react", "node.js", "frontend")
    request_delay: float = 0.5
    max_req_per_min: int = 120
    redis_url: str = field(
        default_factory=lambda: os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"), repr=False
    )

    def __post_init__(self):
        if not self.mongodb_url.startswith(("mongodb://", "mongodb+srv://")):
            raise ValueError("MONGODB_URL must use mongodb:// or mongodb+srv://")
        if len(self.api_key) < 32:
            raise ValueError("API_KEY must contain at least 32 characters")
        if not 1 <= self.max_req_per_min <= 100_000:
            raise ValueError("MAX_REQ_PER_MIN must be 1..100000")
        if not self.redis_url.startswith(("redis://", "rediss://", "unix://")):
            raise ValueError("REDIS_URL must use redis://, rediss://, or unix://")
        if not self.sources or not set(self.sources) <= set(SOURCES):
            raise ValueError(f"SOURCES must be a nonempty subset of {SOURCES}")
        if self.interval_seconds < 21600:
            raise ValueError("SCRAPE_INTERVAL_SECONDS must be at least 21600 (six hours)")
        if not 1 <= self.max_jobs <= 5000 or not 1 <= self.max_pages <= 25:
            raise ValueError("MAX_JOBS must be 1..5000; MAX_PAGES must be 1..25")
        if self.retention_days < 1 or self.source_timeout <= 0 or self.max_response_bytes < 1:
            raise ValueError("Retention, timeout and response limit must be positive")
        if (
            not self.search_terms
            or len(self.search_terms) > 12
            or any(not term.strip() or len(term) > 80 for term in self.search_terms)
        ):
            raise ValueError(
                "SEARCH_TERMS must contain 1..12 nonempty terms of at most 80 characters"
            )
        if self.request_delay < 0:
            raise ValueError("Request delay must not be negative")

    @classmethod
    def from_env(cls):
        return cls(
            api_key=os.environ.get("API_KEY", ""),
            sources=tuple(
                dict.fromkeys(
                    s.strip()
                    for s in os.environ.get("SOURCES", ",".join(SOURCES)).split(",")
                    if s.strip()
                )
            ),
            interval_seconds=int(os.environ.get("SCRAPE_INTERVAL_SECONDS", "21600")),
            max_jobs=int(os.environ.get("MAX_JOBS", "500")),
            max_pages=int(os.environ.get("MAX_PAGES", "5")),
            retention_days=int(os.environ.get("RETENTION_DAYS", "90")),
            max_req_per_min=int(os.environ.get("MAX_REQ_PER_MIN", "120")),
            search_terms=tuple(
                dict.fromkeys(
                    s.strip()
                    for s in os.environ.get(
                        "SEARCH_TERMS", "typescript,full stack,react,node.js,frontend"
                    ).split(",")
                    if s.strip()
                )
            ),
        )
