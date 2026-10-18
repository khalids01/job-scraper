# Verification — 2026-10-18

Executed in the sibling `job-scraper` directory. Existing Job Agent and Joblake source files
were not modified. Temporary verification databases were isolated from user data and removed.

- Python 3.14 virtual environment: `ruff check src tests` passed; `pytest -q` passed **18 tests**.
  Tests cover normalization, uncertain locations, source attribution, pagination, malformed records,
  unsafe URL schemes, blocked/non-JSON/schema failures, byte/job limits, upserts, filtering,
  expiry/retention, API authentication/permissions, single-process ownership, source timeouts,
  concurrent runs, cancellation, restart recovery, persistent cooldown, and startup scheduling.
  The installed Starlette version emits a TestClient deprecation warning about httpx; tests pass.
- A real Uvicorn subprocess passed localhost HTTP checks: health 200, unauthenticated jobs 401,
  authenticated jobs 200. SIGTERM completed application shutdown. No server remains running.
- `docker compose config --quiet` passed with temporary nonsecret validation values.
- A live, single-page collection returned **132 normalized jobs**, all stored in temporary SQLite:
  Remotive 12, Arbeitnow 100, Himalayas 20; zero invalid records. Arbeitnow and Himalayas were
  truncated by the explicit pilot limits (100 jobs/source, one page/source), so the overall run
  correctly reported `partial`. Exact result counters and timestamps are in `LIVE_CHECK.json`.
  This verifies one bounded live run, not exhaustive coverage or ongoing source availability.
- Docker image execution could **not** be verified: the build failed downloading Python base-image
  metadata/blobs from `production.cloudfront.docker.com` with a TCP timeout. A pull through the
  public ECR mirror also timed out. No Docker daemon configuration was changed. Run
  `docker build --target test -t job-agent-scraper:test .` and `docker compose up -d --build`
  on a host with working registry access to finish container verification.

No VPS deployment, Tauri integration, public port exposure, real API-key file, or commits were made.
