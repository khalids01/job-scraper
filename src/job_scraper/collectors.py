"""Public-feed adapters. No profile matching or inferred geographic eligibility."""

import hashlib
import json
from dataclasses import dataclass, field

import httpx
from pydantic import ValidationError

from .config import Settings
from .models import Job, date_text, plain

ENDPOINTS = {
    "remotive": "https://remotive.com/api/remote-jobs",
    "arbeitnow": "https://www.arbeitnow.com/api/job-board-api",
    "himalayas": "https://himalayas.app/jobs/api",
}


class SourceError(Exception):
    """Safe, credential-free diagnostic for a source failure."""


@dataclass
class Batch:
    jobs: list[Job] = field(default_factory=list)
    fetched: int = 0
    invalid: int = 0
    duplicates: int = 0
    truncated: bool = False
    requests: int = 0


def normalize(source: str, item: dict) -> Job:
    if source == "remotive":
        values = dict(
            source_id=str(item.get("id") or ""),
            title=plain(item.get("title")),
            company=item.get("company_name"),
            source_url=item.get("url"),
            location=item.get("candidate_required_location"),
            remote=True,
            description=plain(item.get("description")),
            salary_text=item.get("salary"),
            employment_type=item.get("job_type"),
            tags=item.get("tags") or [],
            published_at=date_text(item.get("publication_date")),
        )
    elif source == "arbeitnow":
        values = dict(
            source_id=item.get("slug") or "",
            title=plain(item.get("title")),
            company=item.get("company_name"),
            source_url=item.get("url"),
            location=item.get("location"),
            remote=item.get("remote"),
            description=plain(item.get("description")),
            tags=item.get("tags") or [],
            published_at=date_text(item.get("created_at")),
        )
    else:
        # guid is also the original Himalayas posting URL, required for attribution.
        restrictions = item.get("locationRestrictions") or []
        salary = (
            " ".join(
                str(item[k])
                for k in ("minSalary", "maxSalary", "currency", "salaryPeriod")
                if item.get(k) is not None
            )
            or None
        )
        values = dict(
            source_id=item.get("guid") or "",
            title=plain(item.get("title")),
            company=item.get("companyName"),
            source_url=item.get("guid"),
            location=", ".join(restrictions) or None,
            remote=True,
            location_restrictions=restrictions,
            timezone_restrictions=item.get("timezoneRestrictions") or [],
            description=plain(item.get("description") or item.get("excerpt")),
            salary_text=salary,
            employment_type=item.get("employmentType"),
            tags=item.get("categories") or [],
            published_at=date_text(item.get("pubDate")),
            expires_at=date_text(item.get("expiryDate")),
        )
    identity = f"{source}:{values['source_id']}"
    return Job(id=hashlib.sha256(identity.encode()).hexdigest(), source=source, **values)


async def fetch_json(client: httpx.AsyncClient, url: str, params: dict, maximum: int):
    try:
        async with client.stream("GET", url, params=params) as response:
            if response.status_code != 200:
                raise SourceError(f"Upstream HTTP {response.status_code}; no automatic retry")
            if "json" not in response.headers.get("content-type", "").lower():
                raise SourceError("Upstream returned non-JSON content")
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > maximum:
                    raise SourceError("Upstream response exceeded byte limit")
            try:
                return json.loads(body)
            except (ValueError, UnicodeDecodeError):
                raise SourceError("Upstream returned invalid JSON") from None
    except httpx.RequestError:
        raise SourceError("Upstream network error or request timeout") from None


async def collect(source: str, client: httpx.AsyncClient, settings: Settings) -> Batch:
    batch = Batch()
    seen: set[str] = set()
    cursor = None
    for page in range(1, settings.max_pages + 1):
        params = {"page": page} if source == "arbeitnow" else {}
        if source == "himalayas":
            params = {"limit": 20}
            if cursor:
                params["cursor"] = cursor
        payload = await fetch_json(client, ENDPOINTS[source], params, settings.max_response_bytes)
        batch.requests += 1
        key = "data" if source == "arbeitnow" else "jobs"
        if not isinstance(payload, dict) or not isinstance(payload.get(key), list):
            raise SourceError("Upstream schema changed: expected a job array")
        items = payload[key]
        batch.fetched += len(items)
        for item in items:
            try:
                if not isinstance(item, dict):
                    raise ValueError("Invalid item")
                job = normalize(source, item)
            except (ValidationError, ValueError, TypeError, AttributeError):
                batch.invalid += 1
                continue
            if job.id in seen:
                batch.duplicates += 1
                continue
            seen.add(job.id)
            if len(batch.jobs) >= settings.max_jobs:
                batch.truncated = True
                break
            batch.jobs.append(job)
        if batch.truncated:
            break
        if source == "remotive":
            break
        if source == "himalayas":
            next_cursor = payload.get("nextCursor")
            more = isinstance(next_cursor, str) and bool(next_cursor) and next_cursor != cursor
            cursor = next_cursor
        else:
            links = payload.get("links")
            more = isinstance(links, dict) and bool(links.get("next"))
        if not items or not more:
            break
        if page == settings.max_pages:
            batch.truncated = True
    return batch
