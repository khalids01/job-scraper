import asyncio
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient

from job_scraper.api import create_app
from job_scraper.collectors import SourceError, collect, normalize
from job_scraper.config import SOURCES, Settings
from job_scraper.feeds import normalize_feed, parse_feed
from job_scraper.focus import in_scope, remote_claim, role_matches
from job_scraper.models import RunRequest
from job_scraper.sources import SPECS, Source
from job_scraper.storage import Store


@pytest.fixture
def config(tmp_path):
    return Settings(
        api_key="r" * 40, admin_key="a" * 40, database=tmp_path / "jobs.sqlite3", request_delay=0
    )


def sample(**changes):
    return {
        "id": 1,
        "title": "Full Stack Developer",
        "company_name": "Example",
        "url": "https://example.com/job",
        "description": "Build in TypeScript.",
        **changes,
    }


@pytest.mark.parametrize(
    "title,description,expected",
    [
        ("Senior Full-stack Developer", "Python/Django", True),
        ("Fullstack Engineer", "", True),
        ("Frontend Engineer", "", True),
        ("Web Developer", "HTML and CSS", True),
        ("Senior Backend Developer", "Node.js and NestJS", True),
        ("Software Engineer", "TypeScript applications", True),
        ("React Native Developer", "Mobile apps", True),
        ("Vue.js Developer", "", True),
        ("Software Engineer", "Next.js", True),
        ("Software Engineer", "Deno and JavaScript", True),
        ("Software Engineer", "Python only", False),
        ("Backend Developer", "Java and Spring", False),
        ("Data Engineer", "TypeScript integration", False),
        ("Data Scientist", "React dashboards", False),
        ("Sales Engineer", "TypeScript demos", False),
        ("Customer Support Engineer", "React", False),
        ("Product Designer", "full-stack TypeScript", False),
        ("Full-stack Designer", "TypeScript", False),
        ("Technical Recruiter", "Hiring TypeScript developers", False),
        ("QA Engineer", "Playwright TypeScript", False),
        ("DevOps Engineer", "Node.js", False),
        ("Developer Advocate", "TypeScript", False),
        ("Engineering Manager", "Full-stack team", False),
        ("Nurse", "We use React for internal software", False),
        ("Software Engineer", "Typing, reaction time, and neuroscience", False),
    ],
)
def test_developer_focus(title, description, expected):
    job = normalize("remotive", sample(title=title, description=description))
    assert role_matches(job) is expected


@pytest.mark.parametrize(
    "title,location,description,declared,remote_feed,expected",
    [
        ("Engineer", "Remote, US only", "", None, False, True),
        ("Engineer", "Anywhere", "", None, False, True),
        ("Engineer", None, "This is a fully remote position.", None, False, True),
        ("Engineer", None, "Work from home", None, False, True),
        ("Engineer", None, "Distributed data structures", None, False, None),
        ("Engineer", None, "We sell remote-control equipment", None, False, None),
        ("Engineer", None, "Office role, no remote work available", None, True, False),
        ("Engineer", "Hybrid in London", "", True, True, False),
        ("On-site React Engineer", "London", "", True, True, False),
        ("Engineer", "Paris", "", False, True, False),
        ("Engineer", "Paris", "", None, False, None),
        ("Engineer", None, "", None, True, True),
        ("Engineer", "Germany", "", True, False, True),
    ],
)
def test_remote_evidence(title, location, description, declared, remote_feed, expected):
    result, evidence = remote_claim(
        title, location, description, declared=declared, remote_feed=remote_feed
    )
    assert result is expected
    assert bool(evidence) is (expected is not None)


def json_payload(source):
    if source == "remotive":
        return {"jobs": [sample()]}
    if source == "arbeitnow":
        return {
            "data": [
                {
                    "slug": "1",
                    "title": "Full Stack Developer",
                    "remote": True,
                    "url": "https://example.com/job",
                }
            ],
            "links": {"next": None},
        }
    if source == "himalayas":
        return {"jobs": [{"guid": "https://himalayas.app/job/1", "title": "Full Stack Engineer"}]}
    if source == "remoteok":
        return [
            {"legal": "Attribute Remote OK"},
            {
                "id": "1",
                "position": "TypeScript Developer",
                "url": "https://remoteok.com/job/1",
                "salary_min": 0,
                "salary_max": 0,
            },
        ]
    if source == "jobicy":
        return {
            "jobs": [
                {
                    "id": 1,
                    "jobTitle": "React Engineer",
                    "jobType": ["Full-time"],
                    "jobIndustry": ["Engineering"],
                    "url": "https://jobicy.com/jobs/1",
                }
            ],
            "nextCursor": None,
            "success": True,
        }
    if source == "workingnomads":
        return [
            {
                "title": "Backend Engineer",
                "description": "Node.js",
                "tags": "node.js,react",
                "url": "https://www.workingnomads.com/job/1/",
            }
        ]
    if source == "reallyremote":
        return {
            "jobs": [
                {
                    "slug": "1",
                    "title": "TypeScript Engineer",
                    "summary": "Build apps",
                    "company": "Example",
                    "url": "https://reallyremote.co/jobs/1",
                }
            ],
            "total": 1,
        }
    return {
        "data": [
            {
                "id": "1",
                "title": "TypeScript Engineer",
                "company": {"name": "Example"},
                "location": "Remote US",
                "url": "https://remotejobs.org/job/1",
                "salary_source_text": "EUR 50/hour",
                "search_facts": {"required_skills": ["typescript"]},
            }
        ],
        "pagination": {"has_more": False},
    }


RSS = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>Jobs</title><link>https://example.com/</link>
<description>Jobs</description><item><title>Full Stack Developer - Remote</title>
<link>https://example.com/job</link><guid>stable-1</guid>
<description>Build TypeScript apps. Fully remote.</description>
<pubDate>Sun, 18 Oct 2026 09:00:00 +0000</pubDate></item></channel></rss>"""


@pytest.mark.parametrize("source", SOURCES)
def test_every_registered_adapter_returns_scoped_stable_jobs(config, source):
    spec = SPECS[source]
    requests = []

    def handler(request):
        requests.append(request)
        if spec.format == "rss":
            return httpx.Response(200, content=RSS, headers={"content-type": "application/rss+xml"})
        return httpx.Response(200, json=json_payload(source))

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            batch = await collect(source, client, replace(config, max_pages=1))
            again = await collect(source, client, replace(config, max_pages=1))
        assert len(batch.jobs) == 1 and batch.invalid == 0
        assert batch.jobs[0].source == source
        assert in_scope(batch.jobs[0])
        assert batch.jobs[0].id == again.jobs[0].id
        assert len(requests) == 2
        assert requests[0].url.host == urlsplit(spec.url).hostname
        if source == "remoteok":
            assert batch.fetched == 1 and batch.jobs[0].salary_text is None
        if source == "remotejobsorg":
            assert batch.jobs[0].salary_text == "EUR 50/hour"

    asyncio.run(run())


def test_himalayas_query_rotation_short_pages_and_total_budget(config):
    params = []

    def handler(request):
        params.append(dict(request.url.params))
        if request.url.params["page"] == "2":
            return httpx.Response(200, json={"jobs": []})
        return httpx.Response(200, json=json_payload("himalayas"))

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            batch = await collect(
                "himalayas",
                client,
                replace(config, search_terms=("typescript", "full stack"), max_pages=3),
            )
        assert params == [
            dict(q="typescript", sort="recent", page="1"),
            dict(q="full stack", sort="recent", page="1"),
            dict(q="typescript", sort="recent", page="2"),
        ]
        assert len(batch.jobs) == 1 and batch.duplicates == 1 and batch.truncated
        assert batch.requests == 3

    asyncio.run(run())


@pytest.mark.parametrize("source", ["jobicy", "remotejobsorg", "reallyremote"])
def test_new_pagination_respects_total_budget(config, source):
    requests = []

    def handler(request):
        requests.append(request)
        payload = json_payload(source)
        if source == "jobicy":
            payload["nextCursor"] = str(len(requests))
        elif source == "remotejobsorg":
            payload["pagination"]["has_more"] = True
        else:
            payload["total"] = 300
        return httpx.Response(200, json=payload)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            batch = await collect(source, client, replace(config, max_pages=2))
        assert len(requests) == 2 and len(batch.jobs) == 1 and batch.duplicates == 1
        assert batch.truncated
        key = "cursor" if source == "jobicy" else "offset"
        assert requests[1].url.params[key] == (
            "1" if source == "jobicy" else "50" if source == "remotejobsorg" else "100"
        )

    asyncio.run(run())


def test_repeated_cursor_fails_instead_of_looping(config):
    payload = {**json_payload("jobicy"), "nextCursor": "same"}

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
        ) as client:
            with pytest.raises(SourceError, match="repeated"):
                await collect("jobicy", client, config)

    asyncio.run(run())


@pytest.mark.parametrize(
    "body",
    [
        b"<html><body>Challenge</body></html>",
        b'<!DOCTYPE rss [<!ENTITY x SYSTEM "file:///etc/passwd">]><rss>&x;</rss>',
        b'<!ENTITY x "expand">',
        "<!DOCTYPE rss><rss/>".encode("utf-16"),
        b'<rss version="2.0"><channel><broken>',
    ],
)
def test_invalid_or_unsafe_feeds_fail(body):
    with pytest.raises(ValueError):
        parse_feed(body)


def test_empty_feed_is_distinct_from_html_and_recoverable_xml_is_visible():
    empty = RSS[: RSS.index(b"<item>")] + b"</channel></rss>"
    entries, warnings = parse_feed(empty)
    assert entries == [] and warnings == 0
    malformed = RSS.replace(b"Build TypeScript apps.", b"Build TypeScript & React apps.")
    entries, warnings = parse_feed(malformed)
    assert len(entries) == 1 and warnings == 1


def test_atom_metadata_and_remote_evidence():
    body = b"""<feed xmlns="http://www.w3.org/2005/Atom" xmlns:lj="https://landing.jobs/">
    <title>Jobs</title><entry><id>stable-1</id><title>Backend TypeScript Developer</title>
    <link href="https://landing.jobs/job/1"/><published>2026-10-17T08:00:00Z</published>
    <author><name>Example</name></author><lj:remote_policy>Full remote</lj:remote_policy>
    <content type="html">Build Node.js apps</content></entry></feed>"""
    entries, warnings = parse_feed(body)
    job = normalize_feed("landingjobs", entries[0])
    assert not warnings and job.remote and job.company == "Example"
    assert job.published_at == "2026-10-17T08:00:00+00:00"


def test_scoping_counts_and_unknown_remote_are_explicit(config):
    payload = {
        "data": [
            {"slug": "1", "title": "React Engineer", "url": "https://e.com/1", "remote": True},
            {"slug": "2", "title": "Nurse", "url": "https://e.com/2", "remote": True},
            {"slug": "3", "title": "React Engineer", "url": "https://e.com/3", "remote": False},
            {"slug": "4", "title": "React Engineer", "url": "https://e.com/4"},
        ],
        "links": {"next": None},
    }

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
        ) as client:
            batch = await collect("arbeitnow", client, config)
        assert len(batch.jobs) == 1 and batch.filtered_role == 1 and batch.filtered_remote == 2
        assert batch.invalid == 0 and batch.fetched == 4

    asyncio.run(run())


def test_legacy_database_backfill_hides_unrelated_without_deleting(config):
    store = Store(config.database)
    relevant = normalize("remotive", sample())
    unrelated = normalize("remotive", sample(id=2, title="Nurse"))
    store.save([relevant, unrelated])
    with store.connect() as db:
        db.execute("ALTER TABLE jobs DROP COLUMN eligible")
        db.execute("DELETE FROM schema_meta WHERE key='focus_version'")
    migrated = Store(config.database)
    assert migrated.jobs()["total"] == 1
    assert migrated.job(unrelated.id) is None
    with migrated.connect() as db:
        assert db.execute("SELECT count(*) FROM jobs").fetchone()[0] == 2
    app = create_app(config, schedule=False)
    with TestClient(app) as client:
        assert (
            client.get(
                "/v1/jobs/" + unrelated.id, headers={"X-API-Key": config.api_key}
            ).status_code
            == 404
        )
        result = client.get("/v1/sources", headers={"X-API-Key": config.api_key}).json()
        assert len(result["items"]) == len(SPECS)
        assert result["scope"]["remote_only"]


def test_source_registry_api_and_container_defaults_stay_aligned():
    assert set(SOURCES) == set(Source) == set(SPECS)
    assert len(RunRequest(sources=list(SOURCES)).sources) == len(SOURCES)
    for filename in [".env.example", "compose.yaml"]:
        assert ",".join(SOURCES) in Path(filename).read_text()


@pytest.mark.parametrize(
    "source", [name for name, spec in SPECS.items() if spec.format == "rss" and "?" in spec.url]
)
def test_fixed_feed_query_parameters_survive_http_client(config, source):
    async def run():
        def handler(request):
            from urllib.parse import parse_qsl

            for key, value in parse_qsl(urlsplit(SPECS[source].url).query):
                assert request.url.params[key] == value
            return httpx.Response(200, content=RSS, headers={"content-type": "application/rss+xml"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await collect(source, client, config)

    asyncio.run(run())
