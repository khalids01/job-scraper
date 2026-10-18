"""Reviewed, fixed public endpoints. No caller-controlled collection URLs."""

from dataclasses import dataclass
from enum import StrEnum


class Source(StrEnum):
    remotive = "remotive"
    arbeitnow = "arbeitnow"
    himalayas = "himalayas"
    remoteok = "remoteok"
    jobicy = "jobicy"
    workingnomads = "workingnomads"
    reallyremote = "reallyremote"
    remotejobsorg = "remotejobsorg"
    weworkremotely = "weworkremotely"
    realworkfromanywhere = "realworkfromanywhere"
    nodesk = "nodesk"
    jobspresso = "jobspresso"
    authenticjobs = "authenticjobs"
    larajobs = "larajobs"
    vuejobs = "vuejobs"
    wordpress = "wordpress"
    findjobit = "findjobit"
    cryptojobslist = "cryptojobslist"
    cryptocurrencyjobs = "cryptocurrencyjobs"
    fossjobs = "fossjobs"
    landingjobs = "landingjobs"
    hasjob = "hasjob"
    remotefirstjobs = "remotefirstjobs"


@dataclass(frozen=True)
class SourceSpec:
    name: str
    url: str
    docs: str
    format: str = "json"
    remote_only: bool = True


SPECS = {
    "remotive": SourceSpec(
        "Remotive",
        "https://remotive.com/api/remote-jobs",
        "https://github.com/remotive-com/remote-jobs-api",
    ),
    "arbeitnow": SourceSpec(
        "Arbeitnow",
        "https://www.arbeitnow.com/api/job-board-api",
        "https://www.arbeitnow.com/blog/job-board-api",
        remote_only=False,
    ),
    "himalayas": SourceSpec(
        "Himalayas", "https://himalayas.app/jobs/api/search", "https://himalayas.app/api"
    ),
    "remoteok": SourceSpec("Remote OK", "https://remoteok.com/api", "https://remoteok.com/api"),
    "jobicy": SourceSpec(
        "Jobicy", "https://jobicy.com/api/v2/remote-jobs", "https://jobicy.com/jobs-rss-feed"
    ),
    "workingnomads": SourceSpec(
        "Working Nomads",
        "https://www.workingnomads.com/api/exposed_jobs/",
        "https://www.workingnomads.com/jobs",
    ),
    "reallyremote": SourceSpec(
        "Really Remote",
        "https://reallyremote.co/api/public/jobs",
        "https://reallyremote.co/developers",
    ),
    "remotejobsorg": SourceSpec(
        "RemoteJobs.org",
        "https://remotejobs.org/api/v1/jobs",
        "https://remotejobs.org/developers/api",
    ),
    "weworkremotely": SourceSpec(
        "We Work Remotely",
        "https://weworkremotely.com/categories/remote-programming-jobs.rss",
        "https://weworkremotely.com/remote-job-rss-feed",
        "rss",
    ),
    "realworkfromanywhere": SourceSpec(
        "Real Work From Anywhere",
        "https://www.realworkfromanywhere.com/rss.xml",
        "https://www.realworkfromanywhere.com/rss-feeds",
        "rss",
    ),
    "nodesk": SourceSpec(
        "NoDesk", "https://nodesk.co/remote-jobs/index.xml", "https://nodesk.co/remote-jobs/", "rss"
    ),
    "jobspresso": SourceSpec(
        "Jobspresso",
        "https://jobspresso.co/feed/?post_type=job_listing",
        "https://jobspresso.co/",
        "rss",
    ),
    "authenticjobs": SourceSpec(
        "Authentic Jobs",
        "https://authenticjobs.com/?feed=job_feed&search_location=remote",
        "https://authenticjobs.com/",
        "rss",
        False,
    ),
    "larajobs": SourceSpec(
        "LaraJobs", "https://larajobs.com/feed", "https://larajobs.com/", "rss", False
    ),
    "vuejobs": SourceSpec(
        "VueJobs", "https://app.vuejobs.com/feed/posts", "https://vuejobs.com/", "rss", False
    ),
    "wordpress": SourceSpec(
        "WordPress Jobs",
        "https://jobs.wordpress.net/feed/",
        "https://jobs.wordpress.net/",
        "rss",
        False,
    ),
    "findjobit": SourceSpec(
        "Findjobit", "https://findjobit.com/jobs/feed", "https://findjobit.com/jobs", "rss", False
    ),
    "cryptojobslist": SourceSpec(
        "CryptoJobsList",
        "https://api.cryptojobslist.com/jobs.rss?jobLocation=Remote",
        "https://cryptojobslist.com/remote",
        "rss",
        False,
    ),
    "cryptocurrencyjobs": SourceSpec(
        "Cryptocurrency Jobs",
        "https://cryptocurrencyjobs.co/index.xml",
        "https://cryptocurrencyjobs.co/",
        "rss",
        False,
    ),
    "fossjobs": SourceSpec(
        "FOSS Jobs",
        "https://www.fossjobs.net/rss/all/",
        "https://www.fossjobs.net/rss/",
        "rss",
        False,
    ),
    "landingjobs": SourceSpec(
        "Landing.jobs",
        "https://landing.jobs/feed?remote=true",
        "https://landing.jobs/",
        "rss",
        False,
    ),
    "hasjob": SourceSpec("Hasjob", "https://hasjob.co/feed", "https://hasjob.co/", "rss", False),
    "remotefirstjobs": SourceSpec(
        "RemoteFirstJobs",
        "https://remotefirstjobs.com/rss/jobs/software-development.rss",
        "https://remotefirstjobs.com/rss",
        "rss",
    ),
}

assert set(SPECS) == set(Source)
