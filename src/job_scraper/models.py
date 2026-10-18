from datetime import UTC, datetime
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from bs4 import BeautifulSoup
from pydantic import BaseModel, Field, field_validator

Source = Literal["remotive", "arbeitnow", "himalayas"]


def now() -> str:
    return datetime.now(UTC).isoformat()


def date_text(value) -> str | None:
    if value is None or value == "":
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, UTC).isoformat()
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result.replace(tzinfo=result.tzinfo or UTC).astimezone(UTC).isoformat()
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def plain(value) -> str:
    soup = BeautifulSoup(str(value or "")[:200_000], "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    return soup.get_text(" ", strip=True)[:100_000]


class Job(BaseModel):
    id: str
    source: Source
    source_id: str = Field(min_length=1, max_length=1000)
    source_url: str
    title: str = Field(min_length=1, max_length=1000)
    company: str | None = Field(default=None, max_length=1000)
    location: str | None = Field(default=None, max_length=2000)
    remote: bool | None = None
    description: str = Field(default="", max_length=100_000)
    salary_text: str | None = Field(default=None, max_length=2000)
    employment_type: str | None = None
    tags: list[str] = Field(default_factory=list, max_length=200)
    location_restrictions: list[str] = Field(default_factory=list, max_length=200)
    timezone_restrictions: list[float] = Field(default_factory=list, max_length=100)
    published_at: str | None = None
    expires_at: str | None = None
    first_seen_at: str = Field(default_factory=now)
    fetched_at: str = Field(default_factory=now)

    @field_validator("source_url")
    @classmethod
    def valid_url(cls, value):
        parts = urlsplit(value)
        if (
            parts.scheme not in {"https", "http"}
            or not parts.hostname
            or parts.username
            or parts.password
        ):
            raise ValueError("A public HTTP(S) posting URL is required")
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, parts.query, ""))


class RunRequest(BaseModel):
    sources: list[Source] | None = Field(default=None, min_length=1, max_length=3)
