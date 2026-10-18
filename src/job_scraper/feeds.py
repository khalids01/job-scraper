"""Bounded RSS/Atom parsing with explicit source fields and remote evidence."""

import calendar
import hashlib
import re
from html import unescape

import feedparser
from bs4 import BeautifulSoup

from .focus import remote_claim
from .models import Job, date_text, plain
from .sources import SPECS


def label(html: str, names: tuple[str, ...]):
    """Read labelled metadata, rather than guessing a location from arbitrary prose."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(["strong", "b"]):
        key = tag.get_text(" ", strip=True).rstrip(":").lower()
        if key in names:
            parts = []
            for sibling in tag.next_siblings:
                if getattr(sibling, "name", None) in {"br", "p", "strong", "b"}:
                    break
                parts.append(
                    sibling.get_text(" ", strip=True)
                    if hasattr(sibling, "get_text")
                    else str(sibling)
                )
            value = " ".join(parts).strip(" :\n\t")
            if value:
                return plain(value)[:2000]
    return None


def normalize_feed(source: str, entry: dict) -> Job:
    spec = SPECS[source]
    title = plain(entry.get("title"))
    html = next(
        (c.get("value", "") for c in entry.get("content", []) if c.get("value")),
        entry.get("summary", ""),
    )
    # Some publishers double-escape descriptions.
    html = unescape(html)
    description = plain(html)
    company = entry.get("job_company") or entry.get("job_listing_company")
    location = (
        entry.get("job_location")
        or entry.get("job_listing_location")
        or entry.get("region")
        or entry.get("location")
        or entry.get("media_location")
    )
    if source == "weworkremotely" and ": " in title:
        company, title = title.split(": ", 1)
    elif source in {
        "nodesk",
        "realworkfromanywhere",
        "remotefirstjobs",
        "cryptocurrencyjobs",
        "fossjobs",
    }:
        if " at " in title:
            title, company = title.rsplit(" at ", 1)
    if source == "fossjobs":
        title = re.sub(r"^\[[^]]+\]\s*", "", title)
    if source in {"realworkfromanywhere", "landingjobs"}:
        company = company or entry.get("author")
    if source == "jobspresso" and entry.get("author"):
        # Author is the company followed by an HTML location marker, not a username.
        creator = plain(entry["author"])
        company, separator, author_location = creator.partition("⚲")
        company = company.strip() or None
        if separator:
            location = location or author_location.strip()
    location = plain(location) if location else label(html, ("location", "ubicación", "region"))
    company = plain(company) if company else label(html, ("employer", "company"))
    if source == "landingjobs":
        location = location or entry.get("lj_country") or entry.get("lj_city") or None
    declared = None
    policy = entry.get("lj_remote_policy") or entry.get("lj_location_type")
    if policy:
        declared = policy.casefold() in {"full remote", "fully remote", "remote"}
    remote, evidence = remote_claim(
        title, location, description, declared=declared, remote_feed=spec.remote_only
    )
    url = entry.get("link")
    source_id = str(entry.get("id") or url or "")
    published = entry.get("published_parsed") or entry.get("updated_parsed")
    published = date_text(calendar.timegm(published)) if published else None
    return Job(
        id=hashlib.sha256(f"{source}:{source_id}".encode()).hexdigest(),
        source=source,
        source_id=source_id,
        source_url=url,
        title=title,
        company=company,
        location=location,
        remote=remote,
        remote_evidence=evidence,
        description=description,
        tags=[plain(t["term"]) for t in entry.get("tags", []) if t.get("term")],
        salary_text=entry.get("job_salary") or entry.get("lj_salary") or None,
        employment_type=entry.get("job_job_type")
        or entry.get("job_listing_job_type")
        or entry.get("lj_job_type")
        or entry.get("type"),
        published_at=published,
        expires_at=date_text(entry.get("lj_expires_at")),
    )


def parse_feed(body: bytes):
    # Parsing bytes never fetches a URL. Reject DTD/entity declarations before SAX parsing;
    # NULL bytes are rejected too, preventing UTF-16/32 from hiding those declarations.
    if b"\x00" in body or re.search(rb"<!\s*(?:DOCTYPE|ENTITY)\b", body, re.I):
        raise ValueError("Feed contains a forbidden XML declaration")
    feed = feedparser.parse(body)
    if not feed.version or (feed.get("bozo") and not feed.entries):
        raise ValueError("Upstream is not a usable RSS/Atom feed")
    return feed.entries, int(bool(feed.get("bozo")))
