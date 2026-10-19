# Job Agent Scraper

A standalone Python service that collects public job feeds, persists normalized postings in MongoDB,
and serves only remote full-stack/frontend and JavaScript/TypeScript development matches through an authenticated API. Run the same Docker image locally or on
a VPS. There are 23 reviewed JSON/RSS/Atom source adapters. No Python installation is needed on the desktop; desktop integration is a separate change.

## Deploy from GitHub in Dokploy

1. Create a **Docker Compose** service in your Dokploy project.
2. Select the GitHub provider, repository `khalids01/job-scraper`, branch `main`,
   and Compose Path `./compose.yaml`. Use Compose, not Docker Stack. Keep **Isolated
   Deployments disabled**: this configuration explicitly joins the shared `dokploy-network`
   so it can resolve and connect to Dokploy database services on this server.
3. In **Environment**, set the following and save:

   ```dotenv
   API_KEY=your-secret-key-at-least-32-characters
   MAX_REQ_PER_MIN=120
   MONGODB_URL=mongodb://USER:PASSWORD@HOST:27017/job_scraper?authSource=admin
   REDIS_URL=redis://:PASSWORD@HOST:6379/0
   ```

   Generate an API key with `openssl rand -hex 32`. Use your own external MongoDB
   and Redis connection URLs. `mongodb+srv://` and `rediss://` are supported.
   Percent-encode special characters in URL credentials. The URI database is used;
   if omitted, MongoDB defaults to `job_scraper`. The MongoDB account needs read/write
   and index-creation permissions in that database. Both hosts must be reachable from
   the scraper container; `localhost` refers to the scraper container itself.
   For MongoDB/Redis managed by this same Dokploy VPS, copy the database service's
   **Internal Connection URL**. Keep its service hostname and internal port; do not
   substitute the public API domain. Preserve its authentication options. A root MongoDB
   user normally authenticates against `admin` even when jobs use `/job_scraper`.
   Confirm each database is running and attached to `dokploy-network`.
4. In **Domains**, select service `scraper`, container port `8000`, path `/`, and
   your API hostname. Point its DNS A record to the VPS, enable HTTPS/Let's Encrypt.
5. Click **Deploy**, check the logs, and request `https://YOUR_HOST/healthz`.
   The first collection starts automatically; jobs may take a few minutes to appear.

Compose builds the checked-out revision using the Dockerfile's `runtime` target.
It does not wait for or depend on Docker Hub publication. GitHub Actions separately
continues testing and publishing the same runtime image. The file contains no database
containers, host port bindings, secrets, or local data volumes. Dokploy handles domain
routing. Data persists in the external MongoDB/Redis services across deployments.
Use **one worker and one replica** per MongoDB database, with stop-before-start
replacement. A MongoDB lease rejects concurrent collectors; after an unclean exit,
allow up to 60 seconds for the old lease to expire. If lease renewal fails, collection
stops and health returns 503; restart the service after restoring connectivity.

Official Dokploy instructions: [GitHub Compose setup](https://docs.dokploy.com/docs/core/docker-compose/example),
[environment variables](https://docs.dokploy.com/docs/core/docker-compose),
and [domain routing](https://docs.dokploy.com/docs/core/docker-compose/domains).

### Local Docker

Copy `.env.example` to `.env` and fill in the same four values. Outside Dokploy, create
the external network once with `docker network create dokploy-network` (if it does not
already exist). To publish a local
port, create a `compose.local.yaml` override:

```yaml
services:
  scraper:
    ports:
      - "127.0.0.1:8787:8000"
```

```bash
docker compose -f compose.yaml -f compose.local.yaml up -d --build
curl http://127.0.0.1:8787/healthz
```

The container runs as an unprivileged user with a read-only root filesystem. Collection
repeats every six hours. Source attempts are persisted before fetching, so failures,
manual requests, and restarts respect the cooldown. There are no automatic retries of
blocked, rate-limited, or failed source requests.

Rotate `API_KEY` through your environment and redeploy. Keep `.env` out of version control.
Back up MongoDB and enable Redis persistence in your external services. SQLite files from
older versions are not automatically imported; the new MongoDB starts collecting fresh
postings. Preserve any old SQLite volume if you still need its historical data.

## API

All endpoints except `/healthz` require `X-API-Key` matching the single `API_KEY` environment
variable. The same key authorizes job reads and collection start/cancel commands. No admin key,
login screen, dashboard, or admin panel is involved. Keep the key in the desktop's OS credential
store and send requests through Rust. This scraper key is separate from the Docker Hub token.

### Redis request limit

`MAX_REQ_PER_MIN` is the only API rate setting (default 120). All authenticated requests share
one **sliding 60-second window** stored in Redis, including read requests, collection controls,
and requests that later return errors. Missing or invalid keys receive 401 and do not consume the
configured key's quota. `/healthz` is public and exempt from the request quota.

Exceeding the quota returns **429** with `Retry-After` in seconds. Responses include
`X-RateLimit-Limit`, `X-RateLimit-Remaining`, and `X-RateLimit-Reset` (Unix timestamp of the next
slot). Redis checks and increments the sorted-set window atomically using its own clock, so
concurrent clients cannot exceed the configured allowance. Scraper process restarts keep the
quota. Redis keys expire automatically after inactivity; the API key itself is never stored in
Redis, only its SHA-256-derived identifier and event timestamps.

`REDIS_URL` is required in Compose and points to your external Redis service. Redis must
be reachable at startup. Outages return **503**, never an unmetered fallback; quota requests
recover when Redis becomes available. `/healthz` checks both MongoDB and Redis.
`rediss://` and Unix socket URLs are supported. Multiple apps using the same API key/Redis
share the quota; use separate MongoDB databases if running independent collectors.
Enable Redis persistence to retain request windows across Redis restarts.

When upgrading, retain your existing `API_KEY`, set `MAX_REQ_PER_MIN`, and remove the obsolete
`ADMIN_API_KEY`, `API_RATE_LIMIT_PER_MINUTE`, `ADMIN_RATE_LIMIT_PER_MINUTE`,
`AUTH_RATE_LIMIT_PER_MINUTE`, and `IP_RATE_LIMIT_PER_MINUTE` settings. They are no longer used.

The per-source six-hour collection cooldown, response/request/job bounds, and upstream rate-limit
handling remain separate from the API quota.

| Method | Path | Behavior |
| --- | --- | --- |
| GET | `/healthz` | Container/database/scheduler liveness; does not assert fresh source data |
| GET | `/v1/jobs` | Stored jobs, with pagination and optional filters |
| GET | `/v1/jobs/{id}` | Full normalized posting |
| GET | `/v1/sources` | Enabled sources, last attempt, next allowed attempt, limits |
| GET | `/v1/runs` | Recent collection runs and per-source results |
| GET | `/v1/runs/{id}` | Run status, counts, truncation, invalid records, errors |
| POST | `/v1/runs` | Start a bounded collection run (HTTP 202) |
| DELETE | `/v1/runs/{id}` | Cancel the current run |
| GET | `/openapi.json` | Authenticated machine-readable API schema |

Examples below assume you exported `API_KEY` in your shell. Compose reads `.env`
itself; it does not export those variables into your shell.

```bash
curl -H "X-API-Key: $API_KEY" \
  'http://127.0.0.1:8787/v1/jobs?q=react&remote=true&limit=50&offset=0'

curl -H "X-API-Key: $API_KEY" http://127.0.0.1:8787/v1/runs

curl -X POST -H "X-API-Key: $API_KEY" -H 'Content-Type: application/json' \
  -d '{"sources":["himalayas"]}' http://127.0.0.1:8787/v1/runs
```

`GET /v1/jobs` accepts `q` (literal substring in title/company), `source`, `remote`, `since`
(ISO datetime **with timezone**, compared against fetched time), `limit` (1–200), `offset`, and
`include_expired` (default false). The response is `{items, total, limit, offset}`. Order is newest
fetch first, then stable ID. Offset pagination can shift during a collection; refresh from offset
zero after a run completes. `since` is an inclusive refresh filter, not an exactly-once change log.

Only postings with a remote claim and a matching developer role appear in either job endpoint.
Out-of-scope postings are excluded from both job endpoints.

Jobs contain stable `id`, `source`, `source_id`, `source_url`, title, company, location, remote
claim with `remote_evidence`, plain-text description, original salary text where supplied, employment type, tags,
location/timezone restrictions, publication/expiry dates, first-seen time, and last-fetched time.
Missing facts stay null or empty. Descriptions are normalized to plain text; treat every field as
untrusted content and render it as text in clients. `remote=true` does not mean worldwide eligibility.
Use `source_url` to open the original listing and display source attribution alongside it.

A run ends as `completed`, `partial`, `failed`, `cancelled`, or `interrupted`. `partial` also
includes bounded/truncated runs, skipped malformed records, and recoverable RSS parser warnings. Source-level results expose fetched,
accepted, invalid, duplicate, role-filtered, remote-filtered, expired, inserted, updated, parser-warning, and request counts on successful collection.
Network/HTTP/schema failures are explicit errors, not empty successful results. Concurrent starts
return 409; cooldown returns 429. Stopping the server cancels active fetching; uncleanly stopped
runs become `interrupted` at the next startup.

## Discovery scope

This service is configured for your remote web development search:

- Full-stack, frontend, UI/web developer and web engineer roles.
- Other developer, backend, mobile and software roles when the title, tags, or description
  supplies a JavaScript/TypeScript stack: React, Node.js, Next.js, NestJS, Vue, Angular, Svelte,
  Nuxt or Deno. Full-stack roles may use other backend languages.
- Excludes unrelated sales, support, recruiting, design, management, QA, DevOps, data and security
  roles even when the description mentions TypeScript. These rules are a discovery heuristic,
  not a guarantee of fit; they can miss atypical job titles or match incidental stack mentions.
- Requires explicit remote evidence on mixed boards. Hybrid, onsite, and unknown remote status
  are excluded. Remote-only boards supply a source-level claim, not verified worldwide eligibility.
- Keeps country and timezone restrictions. US-only/EU-only roles are not relabelled worldwide;
  geographic eligibility still belongs to the desktop review workflow.

`GET /v1/sources` reports this scope, enabled source names/endpoints/documentation, limits, and
last per-source results. Each run separates `filtered_role` and `filtered_remote` from malformed
records and genuinely empty feeds. A zero accepted count does not imply a broken source.

## Sources and collection limits

All 23 adapters are enabled by default. The [source research and coverage report](docs/SOURCES.md)
links primary documentation, live results, and excluded candidates. No finite list covers every
remote job site; this is the set with a verified public feed/API during the research.

| Source ID | Provider | Format | Provider scope |
| --- | --- | --- | --- |
| `remotive` | [Remotive](https://github.com/remotive-com/remote-jobs-api) | JSON | Remote source |
| `arbeitnow` | [Arbeitnow](https://www.arbeitnow.com/blog/job-board-api) | JSON | Mixed; remote evidence required |
| `himalayas` | [Himalayas](https://himalayas.app/api) | JSON | Remote source |
| `remoteok` | [Remote OK](https://remoteok.com/api) | JSON | Remote source |
| `jobicy` | [Jobicy](https://jobicy.com/jobs-rss-feed) | JSON | Remote source |
| `workingnomads` | [Working Nomads](https://www.workingnomads.com/jobs) | JSON | Remote source |
| `reallyremote` | [Really Remote](https://reallyremote.co/developers) | JSON | Remote source |
| `remotejobsorg` | [RemoteJobs.org](https://remotejobs.org/developers/api) | JSON | Remote source |
| `weworkremotely` | [We Work Remotely](https://weworkremotely.com/remote-job-rss-feed) | RSS/Atom | Remote source |
| `realworkfromanywhere` | [Real Work From Anywhere](https://www.realworkfromanywhere.com/rss-feeds) | RSS/Atom | Remote source |
| `nodesk` | [NoDesk](https://nodesk.co/remote-jobs/) | RSS/Atom | Remote source |
| `jobspresso` | [Jobspresso](https://jobspresso.co/) | RSS/Atom | Remote source |
| `authenticjobs` | [Authentic Jobs](https://authenticjobs.com/) | RSS/Atom | Mixed; remote evidence required |
| `larajobs` | [LaraJobs](https://larajobs.com/) | RSS/Atom | Mixed; remote evidence required |
| `vuejobs` | [VueJobs](https://vuejobs.com/) | RSS/Atom | Mixed; remote evidence required |
| `wordpress` | [WordPress Jobs](https://jobs.wordpress.net/) | RSS/Atom | Mixed; remote evidence required |
| `findjobit` | [Findjobit](https://findjobit.com/jobs) | RSS/Atom | Mixed; remote evidence required |
| `cryptojobslist` | [CryptoJobsList](https://cryptojobslist.com/remote) | RSS/Atom | Mixed; remote evidence required |
| `cryptocurrencyjobs` | [Cryptocurrency Jobs](https://cryptocurrencyjobs.co/) | RSS/Atom | Mixed; remote evidence required |
| `fossjobs` | [FOSS Jobs](https://www.fossjobs.net/rss/) | RSS/Atom | Mixed; remote evidence required |
| `landingjobs` | [Landing.jobs](https://landing.jobs/) | RSS/Atom | Mixed; remote evidence required |
| `hasjob` | [Hasjob](https://hasjob.co/) | RSS/Atom | Mixed; remote evidence required |
| `remotefirstjobs` | [RemoteFirstJobs](https://remotefirstjobs.com/rss) | RSS/Atom | Remote source |

Himalayas uses its search endpoint, rotating through `SEARCH_TERMS` (default `typescript,full
stack,react,node.js,frontend`). Short search pages do not end a query; only empty pages do.
`MAX_PAGES` is the **total request budget per source**, shared across all terms. With the default
five requests, each of the five queries gets one recent page; a larger budget walks further pages
round-robin. Remotive requests its software development category; RemoteJobs.org requests
programming; Jobicy and Really Remote request engineering. The shared local filter still runs
because provider categories and search results can be broad.

Default limits: 500 accepted matching jobs/source, five requests/source, 16 MB decoded
bytes/response, 25-second request timeout (10-second connect timeout), and 90-second total async
timeout/source. RSS feeds and unpaginated JSON feeds use one request. Paginated JSON sources use
page numbers, offsets or opaque cursors on fixed endpoints; an upstream next URL is never followed.
Requests within a source are spaced by 0.5 seconds. Sources run sequentially, every six hours,
with no automatic retry of failed, blocked or rate-limited responses. Redirects are rejected;
reviewed canonical feed hosts are configured directly. XML DTD/entity declarations are rejected.
Recoverable malformed RSS is parsed with a visible warning, producing a `partial` run. HTML
challenge pages and unusable feeds fail explicitly.

Descriptions are plain text capped at 100,000 characters. A source batch is upserted into MongoDB
**after its pages complete**. Fetch failures/cancellation discard the in-progress fetch batch.
Each job upsert is atomic; a database failure during a batch can leave partial job updates,
which the next collection reconciles. Completed sources stay available. Deduplication uses source plus source job ID, preserving the
first-seen time on upsert. Cross-source copies remain separate with their provenance.

Configure `SOURCES`, `SEARCH_TERMS`, `SCRAPE_INTERVAL_SECONDS`, `MAX_JOBS`, `MAX_PAGES`, and
`RETENTION_DAYS` in `.env`. **If you already have an `.env` listing only the original three sources,
remove that line to use the expanded default; source IDs are listed above.**
Redeploy after configuration changes. Existing MongoDB jobs are updated by stable source/job ID;
first-seen timestamps are preserved.

Retention removes jobs not fetched again within 90 days and old finished runs after collection.
Only explicit source expiry dates are treated as closed. Bounded feeds are recent discovery
samples, not complete job inventories. A valid feed can be empty or yield zero relevant jobs.
Missing dates and remote/geographic claims remain uncertain; do not treat first-seen time as the
publication date. Older jobs in a feed may still be returned until they expire or disappear.

Preserve the original listing URL and visible provider attribution in clients. In particular,
Remotive, Remote OK, Himalayas, Jobicy, RemoteJobs.org, Really Remote and RemoteFirstJobs publish
specific attribution requirements; some restrict further redistribution to other aggregators.
This is a personal discovery service. No resumes, AI matching, or applications are involved, and collection does not bypass authentication, CAPTCHA or provider access limits.

## Development and verification

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/ruff check src tests
.venv/bin/pytest -q
```

Tests start private real MongoDB and Redis servers (using `mongod`/`redis-server` if installed,
otherwise Docker with `mongo:7.0` and `redis:8-alpine`). Each test has its own MongoDB database.
They ignore production connection variables and never hit job providers.

Or run all checks in Docker without installing Python, MongoDB, or Redis locally:

```bash
docker build --target test -t job-agent-scraper:test .
```

Runtime and test dependencies are pinned in `requirements.lock` and `requirements-dev.lock` for
Docker builds. For a matching local environment, install `-r requirements-dev.lock` first, then
`pip install --no-deps -e .`. Re-resolve and test both lock files when changing dependencies.
See [VALIDATION.md](VALIDATION.md) for completed checks and the verification results.

To start outside Docker, export `API_KEY`, `MONGODB_URL`, and `REDIS_URL` (optionally
`MAX_REQ_PER_MIN`), then run `.venv/bin/uvicorn job_scraper.api:app --host 127.0.0.1 --port 8787`.
Environment variables are read directly; Uvicorn does not automatically load `.env`.
`DATABASE_PATH` is no longer used. No public deployment or desktop connection is created by
this repository.

Adapters were written afresh using the user's existing Joblake project as a field-mapping reference:
`/home/khalid/Desktop/projects/saas/swiftcv/joblake`, revision
`4808036a7f2c72148646974b09743f0e81f57637`, collectors `remotive.py`, `arbeitnow.py`, and
`himalayas.py`. The service does not import or modify that project.

For an **explicit, sparingly used maintainer live check**, run:

```bash
.venv/bin/python scripts/verify_live.py --sources vuejobs larajobs --output /tmp/source-check.json
```

It makes at most one request/source and writes no production data. Do not run it repeatedly:
provider limits still apply. Automated tests use synthetic fixtures and never hit job providers.
The saved live reports in `docs/` record failures, filtering and warnings as well as successes.
