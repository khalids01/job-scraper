import os
from dataclasses import dataclass, field
from pathlib import Path

SOURCES = ("remotive", "arbeitnow", "himalayas")


@dataclass(frozen=True)
class Settings:
    api_key: str = field(repr=False)
    admin_key: str = field(repr=False)
    database: Path = Path("data/jobs.sqlite3")
    sources: tuple[str, ...] = SOURCES
    interval_seconds: int = 21600
    max_jobs: int = 500
    max_pages: int = 5
    max_response_bytes: int = 16_000_000
    source_timeout: float = 90
    retention_days: int = 90

    def __post_init__(self):
        if min(len(self.api_key), len(self.admin_key)) < 32:
            raise ValueError("API_KEY and ADMIN_API_KEY must each contain at least 32 characters")
        if self.api_key == self.admin_key:
            raise ValueError("Use different read and admin API keys")
        if not self.sources or not set(self.sources) <= set(SOURCES):
            raise ValueError(f"SOURCES must be a nonempty subset of {SOURCES}")
        if self.interval_seconds < 21600:
            raise ValueError("SCRAPE_INTERVAL_SECONDS must be at least 21600 (six hours)")
        if not 1 <= self.max_jobs <= 5000 or not 1 <= self.max_pages <= 25:
            raise ValueError("MAX_JOBS must be 1..5000; MAX_PAGES must be 1..25")
        if self.retention_days < 1 or self.source_timeout <= 0 or self.max_response_bytes < 1:
            raise ValueError("Retention, timeout and response limit must be positive")

    @classmethod
    def from_env(cls):
        return cls(
            api_key=os.environ.get("API_KEY", ""),
            admin_key=os.environ.get("ADMIN_API_KEY", ""),
            database=Path(os.environ.get("DATABASE_PATH", "data/jobs.sqlite3")),
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
        )
