# Job Agent Scraper

A standalone Python service that collects public job feeds, persists normalized postings in SQLite,
and serves them to Job Agent through an authenticated API. Run the same Docker image locally or on
a VPS. No Python installation is needed on the desktop; desktop integration is a separate change.

## Start with Docker

```bash
cp .env.example .env
```

Generate **two different** keys with `openssl rand -hex 32`, and put them into `.env` as `API_KEY`
(desktop read access) and `ADMIN_API_KEY` (collection controls). Neither has a default.

```bash
docker compose up -d --build
curl http://127.0.0.1:8787/healthz
```

Compose binds to **127.0.0.1:8787**. For a VPS, put an HTTPS reverse proxy in front of that local
port, or access it through a private tunnel. Set the desktop's eventual base URL to that HTTPS
address. Do not expose an unencrypted API key over the internet. HTTP on localhost is suitable
for a local container. The container runs as an unprivileged user, with a read-only root filesystem.

Collection starts automatically for sources that have never been attempted, then repeats every
six hours. Each source's last attempt is persisted **before** fetching; failed requests, admin
requests, and container restarts all respect the same cooldown. Lower intervals are rejected.
There are no automatic retries of blocked, rate-limited, or failed requests.

```bash
docker compose logs --tail=100 scraper
docker compose down
```

The `scraper-data` named volume survives `down` and image rebuilds. `down -v` deletes the stored
jobs and collection history. To back up a running database, use SQLite's backup API rather than
copying only the database file while its WAL is active. Rotate keys by updating `.env` and running
`docker compose up -d` again. Keep `.env` out of version control.

## API

All endpoints except `/healthz` require `X-API-Key`. Read routes accept either key;
collection start/cancel require the admin key. Keep the read key in the desktop's OS credential
store and make requests through Rust. Do not embed either key in frontend assets.

| Method | Path | Behavior |
| --- | --- | --- |
| GET | `/healthz` | Container/database/scheduler liveness; does not assert fresh source data |
| GET | `/v1/jobs` | Stored jobs, with pagination and optional filters |
| GET | `/v1/jobs/{id}` | Full normalized posting |
| GET | `/v1/sources` | Enabled sources, last attempt, next allowed attempt, limits |
| GET | `/v1/runs` | Recent collection runs and per-source results |
| GET | `/v1/runs/{id}` | Run status, counts, truncation, invalid records, errors |
| POST | `/v1/runs` | Start a bounded collection run (admin, HTTP 202) |
| DELETE | `/v1/runs/{id}` | Cancel the current run (admin) |
| GET | `/openapi.json` | Authenticated machine-readable API schema |

Examples below assume you exported `API_KEY` and `ADMIN_API_KEY` in your shell. Compose reads `.env`
itself; it does not export those variables into your shell.

```bash
curl -H "X-API-Key: $API_KEY" \
  'http://127.0.0.1:8787/v1/jobs?q=react&remote=true&limit=50&offset=0'

curl -H "X-API-Key: $API_KEY" http://127.0.0.1:8787/v1/runs

curl -X POST -H "X-API-Key: $ADMIN_API_KEY" -H 'Content-Type: application/json' \
  -d '{"sources":["himalayas"]}' http://127.0.0.1:8787/v1/runs
```

`GET /v1/jobs` accepts `q` (literal substring in title/company), `source`, `remote`, `since`
(ISO datetime **with timezone**, compared against fetched time), `limit` (1–200), `offset`, and
`include_expired` (default false). The response is `{items, total, limit, offset}`. Order is newest
fetch first, then stable ID. Offset pagination can shift during a collection; refresh from offset
zero after a run completes. `since` is an inclusive refresh filter, not an exactly-once change log.

Jobs contain stable `id`, `source`, `source_id`, `source_url`, title, company, location, remote
claim, plain-text description, original salary text where supplied, employment type, tags,
location/timezone restrictions, publication/expiry dates, first-seen time, and last-fetched time.
Missing facts stay null or empty. Descriptions are normalized to plain text; treat every field as
untrusted content and render it as text in clients. `remote=true` does not mean worldwide eligibility.
Use `source_url` to open the original listing and display source attribution alongside it.

A run ends as `completed`, `partial`, `failed`, `cancelled`, or `interrupted`. `partial` also
includes bounded/truncated runs and skipped malformed records. Source-level results expose fetched,
accepted, invalid, duplicate, inserted, updated, and request counts on successful collection.
Network/HTTP/schema failures are explicit errors, not empty successful results. Concurrent starts
return 409; cooldown returns 429. Stopping the server cancels active fetching; uncleanly stopped
runs become `interrupted` at the next startup.

## Sources and collection limits

| Source | Collection | Notes |
| --- | --- | --- |
| Remotive | One public API request | Includes all returned categories; max jobs still applies |
| Arbeitnow | Page numbers on the fixed public API host | Includes onsite postings and remote claims |
| Himalayas | Browse feed using `nextCursor`, 20 jobs/page | Preserves country/timezone restrictions and original posting URL |

Default limits: 500 accepted jobs/source, five pages/source, 16 MB decoded bytes/response,
25-second request timeout (10-second connect timeout), and 90-second total timeout/source.
Requests run sequentially. Redirects are rejected. Pagination never follows an upstream-provided
host or URL; only page numbers/cursors are passed back to fixed source endpoints. Descriptions
are limited to 100,000 characters. A source batch is saved transactionally **after its pages
complete**; source failure/cancellation discards that source's in-progress batch. Completed sources
remain available. One source failing does not prevent the next source from running.

`SOURCES`, `SCRAPE_INTERVAL_SECONDS`, `MAX_JOBS`, `MAX_PAGES`, and `RETENTION_DAYS` can be changed
in `.env`; see `.env.example`. Retention removes jobs not fetched again within 90 days and old
finished runs after collection. It is not a guarantee a job is still open: only explicit upstream
expiry dates are hidden automatically. The feeds and bounded pages are a recent discovery sample,
not an exhaustive crawl. In particular Himalayas' default five pages cover at most 100 jobs/run.
Increasing limits requires checking source usage rules and container memory needs.

Deduplication/upserts use source plus source job ID. Re-fetching updates the same row while
preserving first-seen time. Cross-source postings remain separate so source evidence is retained.
No personal relevance terms, inferred eligibility, AI inference, resume data, application actions,
MongoDB, or Redis are involved.

Source documentation checked on 2026-10-18:

- [Remotive API and usage rules](https://github.com/remotive-com/remote-jobs-api): preserve the
  Remotive posting link and attribution. Its published guidance advises at most four fetches/day;
  listings are delayed by 24 hours. Respect its restrictions on redistribution.
- [Arbeitnow job board API](https://www.arbeitnow.com/blog/job-board-api): public feed focused on
  European jobs. Keep its posting link and attribution.
- [Himalayas API](https://himalayas.app/api) and its linked API terms: preserve original Himalayas
  URLs and attribution. Country restrictions and timezone restrictions are distinct.

This is for personal job discovery. Recheck provider terms before operating a public redistribution
service. No CAPTCHA, authentication barriers, or rate limits are bypassed.

## Development and verification

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/ruff check src tests
.venv/bin/pytest -q
```

Or run all checks in Docker without installing Python:

```bash
docker build --target test -t job-agent-scraper:test .
```

Runtime and test dependencies are pinned in `requirements.lock` and `requirements-dev.lock` for
Docker builds. For a matching local environment, install `-r requirements-dev.lock` first, then
`pip install --no-deps -e .`. Re-resolve and test both lock files when changing dependencies.
See [VALIDATION.md](VALIDATION.md) for completed checks and the container-download limitation.

To start outside Docker, export the two keys and run
`.venv/bin/uvicorn job_scraper.api:app --host 127.0.0.1 --port 8787`.
Environment variables are read directly; local Uvicorn does not automatically load `.env`.
`DATABASE_PATH` defaults to `data/jobs.sqlite3` outside Docker. Use **one worker and one replica**
per database. A filesystem lock enforces this on Linux (VPS/local Docker); horizontal scaling
requires a separate queue/database design. No public deployment or desktop connection is created
by this repository.

Adapters were written afresh using the user's existing Joblake project as a field-mapping reference:
`/home/khalid/Desktop/projects/saas/swiftcv/joblake`, revision
`4808036a7f2c72148646974b09743f0e81f57637`, collectors `remotive.py`, `arbeitnow.py`, and
`himalayas.py`. The service does not import or modify that project.
