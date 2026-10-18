"""Bounded collection, per-source pagination and shared discovery filtering."""

import asyncio
import json
from collections import deque
from dataclasses import dataclass, field

import httpx
from pydantic import ValidationError

from .config import Settings
from .feeds import normalize_feed, parse_feed
from .focus import role_matches
from .json_adapters import normalize
from .models import Job, now
from .sources import SPECS

ENDPOINTS = {source: spec.url for source, spec in SPECS.items()}


class SourceError(Exception):
    """Safe, credential-free diagnostic for a source failure."""


@dataclass
class Batch:
    jobs: list[Job] = field(default_factory=list)
    fetched: int = 0
    invalid: int = 0
    duplicates: int = 0
    filtered_role: int = 0
    filtered_remote: int = 0
    expired: int = 0
    parser_warnings: int = 0
    truncated: bool = False
    requests: int = 0


async def fetch_bytes(
    client: httpx.AsyncClient, url: str, params: dict, maximum: int, *, xml=False
):
    try:
        # Passing params={} to httpx discards a URL's existing query. Preserve the
        # reviewed feed selectors (post_type, remote=true, jobLocation=Remote).
        target = httpx.URL(url).copy_merge_params(params)
        async with client.stream("GET", target) as response:
            if response.status_code != 200:
                raise SourceError(f"Upstream HTTP {response.status_code}; no automatic retry")
            content_type = response.headers.get("content-type", "").lower()
            if not (
                any(t in content_type for t in ("xml", "rss", "atom"))
                if xml
                else "json" in content_type
            ):
                raise SourceError(
                    "Upstream returned non-feed content"
                    if xml
                    else "Upstream returned non-JSON content"
                )
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > maximum:
                    raise SourceError("Upstream response exceeded byte limit")
            return bytes(body)
    except httpx.RequestError:
        raise SourceError("Upstream network error or request timeout") from None


async def fetch_json(client: httpx.AsyncClient, url: str, params: dict, maximum: int):
    body = await fetch_bytes(client, url, params, maximum)
    try:
        return json.loads(body)
    except (ValueError, UnicodeDecodeError):
        raise SourceError("Upstream returned invalid JSON") from None


def accept(batch: Batch, seen: set[str], job: Job, settings: Settings):
    if job.id in seen:
        batch.duplicates += 1
        return True
    seen.add(job.id)
    if job.remote is not True:
        batch.filtered_remote += 1
    elif not role_matches(job):
        batch.filtered_role += 1
    elif job.expires_at and job.expires_at <= now():
        batch.expired += 1
    elif len(batch.jobs) >= settings.max_jobs:
        batch.truncated = True
        return False
    else:
        batch.jobs.append(job)
    return True


async def collect(source: str, client: httpx.AsyncClient, settings: Settings) -> Batch:
    if source not in SPECS:
        raise SourceError("Unknown collection source")
    spec, batch, seen = SPECS[source], Batch(), set()
    if spec.format == "rss":
        body = await fetch_bytes(client, spec.url, {}, settings.max_response_bytes, xml=True)
        batch.requests = 1
        try:
            items, batch.parser_warnings = parse_feed(body)
        except ValueError as exc:
            raise SourceError(str(exc)) from None
        batch.fetched = len(items)
        for item in items:
            try:
                job = normalize_feed(source, item)
            except (ValidationError, ValueError, TypeError, AttributeError, KeyError):
                batch.invalid += 1
                continue
            if not accept(batch, seen, job, settings):
                break
        return batch

    # MAX_PAGES is a total per-source request budget, including every search term.
    pending = (
        deque((term, 1, None) for term in settings.search_terms)
        if source == "himalayas"
        else deque([(None, 1, None)])
    )
    cursors = set()
    while pending and batch.requests < settings.max_pages:
        term, page, cursor = pending.popleft()
        params = {}
        if source == "remotive":
            params = {"category": "software-dev"}
        elif source == "arbeitnow":
            params = {"page": page}
        elif source == "himalayas":
            params = {"q": term, "sort": "recent", "page": page}
        elif source == "jobicy":
            params = {"count": 100, "industry": "engineering"}
            if cursor:
                params["cursor"] = cursor
        elif source == "remotejobsorg":
            params = {"category": "programming", "limit": 50, "offset": (page - 1) * 50}
        elif source == "reallyremote":
            params = {"category": "Engineering", "limit": 100, "offset": (page - 1) * 100}
        if batch.requests:
            await asyncio.sleep(settings.request_delay)
        payload = await fetch_json(client, spec.url, params, settings.max_response_bytes)
        batch.requests += 1
        if source in {"remoteok", "workingnomads"}:
            items = payload
        else:
            key = "data" if source in {"arbeitnow", "remotejobsorg"} else "jobs"
            items = payload.get(key) if isinstance(payload, dict) else None
        if not isinstance(items, list):
            raise SourceError("Upstream schema changed: expected a job array")
        if source == "jobicy" and payload.get("success") is False:
            raise SourceError("Upstream reported an API failure")
        if source == "remoteok":
            items = [
                item
                for item in items
                if not (isinstance(item, dict) and "legal" in item and "id" not in item)
            ]
        batch.fetched += len(items)
        for item in items:
            try:
                if not isinstance(item, dict):
                    raise ValueError("Invalid item")
                job = normalize(source, item)
            except (ValidationError, ValueError, TypeError, AttributeError, KeyError):
                batch.invalid += 1
                continue
            if not accept(batch, seen, job, settings):
                return batch
        if not items:
            continue
        if source == "himalayas":
            # Search pages can be short before the end. Only an empty page ends a query.
            pending.append((term, page + 1, None))
        elif source == "arbeitnow":
            links = payload.get("links")
            if isinstance(links, dict) and links.get("next"):
                pending.append((None, page + 1, None))
        elif source == "jobicy":
            next_cursor = payload.get("nextCursor")
            if next_cursor:
                if not isinstance(next_cursor, str) or next_cursor in cursors:
                    raise SourceError("Upstream returned an invalid/repeated pagination cursor")
                cursors.add(next_cursor)
                pending.append((None, page + 1, next_cursor))
        elif source == "remotejobsorg":
            pagination = payload.get("pagination")
            if not isinstance(pagination, dict) or not isinstance(pagination.get("has_more"), bool):
                raise SourceError("Upstream schema changed: missing pagination.has_more")
            if pagination["has_more"]:
                pending.append((None, page + 1, None))
        elif source == "reallyremote":
            total = payload.get("total")
            if not isinstance(total, int) or total < 0:
                raise SourceError("Upstream schema changed: missing total")
            if page * 100 < total:
                pending.append((None, page + 1, None))
    batch.truncated = bool(pending)
    return batch
