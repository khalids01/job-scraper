# Verification — 2026-10-18, version 0.2.0

All checks used the standalone `job-scraper` repository. Job Agent, the original Joblake project,
DiskVacuum, production databases, and real desktop credentials were not modified by this change.

- **98 tests passed** on host Python 3.14 and in the Python 3.12 Docker test target. Ruff lint and
  format checks passed. Fixtures cover all 23 source adapters, full-stack/JS/TS focus, unrelated
  roles, remote claims and unknowns, mixed-board onsite/hybrid exclusion, JSON pagination budgets,
  repeated cursors, deduplication, unsafe/non-feed XML, recoverable RSS, Atom metadata, source query
  preservation, legacy database scope backfill, authentication and admin permissions, cancellation,
  startup collection, persistent cooldown, upserts, expiration, retention and process ownership.
  Starlette emits one TestClient deprecation warning about httpx; no test failures.
- `docker compose config --quiet` passed with temporary nonsecret placeholder credentials.
- `docker build --network=host --target test -t job-agent-scraper:test .` passed, including lint and
  all 98 tests inside the image. The default local Docker bridge could not reach package indexes;
  host networking was used only for the build, without changing Docker daemon configuration.
- The runtime image built successfully. A temporary container ran as the configured unprivileged
  user with read-only root, dropped capabilities, 512 MB memory limit and **no external network**.
  With a synthetic SQLite seed and pre-marked source cooldowns, HTTP health/authentication, all 23
  source entries, hiding unrelated stored jobs, and persisted jobs/cooldowns passed before and
  after a container restart. The test container and its named volume were removed afterward.
- The bounded live source sweep and targeted follow-up are saved in
  [docs/live-validation.json](docs/live-validation.json) and
  [docs/live-followup.json](docs/live-followup.json). Each provider has a successful live response.
  The latest per-source samples total **294 matching postings**, before cross-source deduplication.
  These are separate source snapshots, not a complete inventory or one transactional global run.
- The first sweep recorded a RemoteJobs.org 503 and caught lost URL query selectors on certain
  RSS feeds. Query preservation was fixed with regression tests; the targeted follow-up succeeded
  for RemoteJobs.org, Jobspresso, Authentic Jobs, Landing.jobs and CryptoJobsList. Both reports are
  retained so failures remain visible.
- Real Work From Anywhere, NoDesk and Landing.jobs exposed recoverable XML errors. Their parser
  warnings are recorded; the app marks runs with those warnings as partial. Zero malformed job
  records were skipped in the latest successful samples. Some valid feeds produced zero matches.
- [docs/SOURCES.md](docs/SOURCES.md) documents provider access/attribution, excluded candidates,
  bounds, and scope limitations. [docs/research-inventory.csv](docs/research-inventory.csv)
  preserves the 101-entry legacy discovery list and its disposition. Discovery entries are not
  claims of live access. No exhaustive-internet coverage claim is made.

No VPS deployment or Tauri integration is part of this change. Existing `.env` source overrides
must be updated or removed to enable all 23 providers in an existing installation.

The initial 0.1.0 pilot (18 tests and 132 unfiltered postings from three sources) remains recorded
in `LIVE_CHECK.json`; it is historical evidence, not the current scope or verification count.


## API-key and request-limit follow-up — version 0.2.1

- Host Python 3.14 and Python 3.12 Docker tests: **108 passed**, including concurrent quota consumption, sliding-window boundary
  recovery, rate-limit headers, independent key quotas, tighter admin-write quotas, invalid-key
  attempts, client-IP caps, duplicate API-key headers, forwarded-header spoofing, bounded client
  buckets, health-check exemption, and environment validation.
- API keys are required and role-separated. A private, Git-ignored local `.env` was created with
  independently generated read/admin keys, file permissions `0600`; values were not printed or
  committed. Docker Hub credentials are separate.
- Request limits are in-memory for the enforced single-process deployment; restarts reset API
  windows. Existing source-fetch cooldowns still persist in SQLite across restarts.


## Redis and simplified environment configuration — 2026-10-19, version 0.3.0

- Removed the separate admin key, role model and per-IP/admin/authentication quotas. Runtime
  authentication/rate settings are now just `API_KEY` and `MAX_REQ_PER_MIN`. `.env.example`
  contains those two settings. Existing local API_KEY was preserved; obsolete fields were removed.
- All protected routes use the same API key, including collection commands. No panel or dashboard
  was added. Source collection cooldowns and all 23 provider adapters remain intact.
- The limiter now runs an atomic sliding-window Lua script against real Redis, using Redis time,
  expiring sorted-set events and a hashed key identifier. Quota survives scraper restarts and is
  shared across app instances using the same key. Redis failure gives 503; no in-memory fallback.
- **108 host tests passed against a private real Redis 8 instance**, covering concurrent consumers,
  shared windows across app instances, scraper restarts, TTL/expired-event pruning, quota reduction,
  authentication, common read/write quotas, response headers, Redis outage and startup failure.
  Synthetic source fixtures remain offline; no job-provider requests were made for this change.
- The Python 3.12 Docker test target passed its initial 107-test Redis suite before the final
  quota-reduction regression was added. The publishing workflow runs the complete updated suite.
- Compose includes Redis with private networking, health checks, persistent AOF volume and no host
  port or UI. Optional REDIS_URL supports connecting to an existing Redis; Compose supplies it.

- Runtime containers also passed a private-network integration check: the API exhausted its
  configured two-request quota, kept returning 429 after a scraper restart and a Redis AOF restart,
  returned 503 while Redis was stopped, and recovered with the same quota after Redis restarted.
  Temporary containers, volumes and network were removed; no production data was used.
