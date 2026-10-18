"""Explicit, bounded maintainer probe; no API credentials or production database.

Run sparingly: provider usage rules still apply. Does not bypass access controls or retry failures.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

import httpx

from job_scraper.collectors import SourceError, collect
from job_scraper.config import SOURCES, Settings
from job_scraper.models import now
from job_scraper.sources import SPECS


async def verify(args):
    results = []
    config = Settings(
        api_key="verification-read-" + "r" * 32,
        mongodb_url="mongodb://unused.invalid/probe",
        max_pages=1,
        max_jobs=500,
    )
    seen = set()
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(25, connect=10),
        follow_redirects=False,
        headers={
            "User-Agent": "JobAgentScraper/0.2 (personal remote developer discovery)",
            "Accept": "application/json, application/rss+xml, application/atom+xml, application/xml, text/xml",
        },
    ) as client:
        for source in args.sources:
            result = {"source": source, "endpoint": SPECS[source].url, "checked_at": now()}
            try:
                async with asyncio.timeout(config.source_timeout):
                    batch = await collect(source, client, config)
                inserted = sum(job.id not in seen for job in batch.jobs)
                seen.update(job.id for job in batch.jobs)
                stored = {"inserted": inserted, "updated": len(batch.jobs) - inserted}
                result.update(
                    status="ok",
                    accepted=len(batch.jobs),
                    **{k: v for k, v in vars(batch).items() if k != "jobs"},
                    **stored,
                )
            except (SourceError, TimeoutError) as exc:
                result.update(status="failed", error=str(exc) or "Source timeout")
            results.append(result)
            print(json.dumps(result), flush=True)
    report = {
        "checked_at": now(),
        "method": "Live public endpoints; one request/source, in-memory deduplication",
        "limits": {"max_pages": 1, "max_jobs": 500},
        "results": results,
        "stored_jobs": len(seen),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    return int(any(result["status"] != "ok" for result in results))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", nargs="+", choices=SOURCES, default=list(SOURCES))
    parser.add_argument("--output", type=Path, default=Path("docs/live-validation.json"))
    sys.exit(asyncio.run(verify(parser.parse_args())))
