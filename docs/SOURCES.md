# Remote developer source research — 2026-10-18

This is a broad, evidence-based expansion, not a claim to enumerate every remote job site on the
internet. I used Exa to review 70 requested search results across four workstreams (public APIs,
RSS/Atom, developer niches, and employer ATS APIs), then inspected primary documentation and live
endpoints. A [101-entry legacy directory](https://github.com/georgemandis/remote-working-list) supplied additional discovery candidates; it is not
proof that those sites or feeds still work. Its entries and disposition are preserved in
[research-inventory.csv](research-inventory.csv).

23 provider adapters are implemented, enabled by default, and have each returned a usable public
feed/API in live checks. Some are general developer/job boards; remote evidence and the shared
full-stack/frontend/JavaScript/TypeScript rule decide what is retained. A matching role is not a
promise of worldwide eligibility. No logins, browser fingerprint impersonation, proxies, CAPTCHA
bypasses, paid endpoints, or application actions are used.

## Verified adapters

The numbers below are one-page snapshots, not total site inventories. The initial full sweep is
recorded in [live-validation.json](live-validation.json). The targeted follow-up
[live-followup.json](live-followup.json) verifies fixed query preservation on feeds whose selector
is in the URL, and records RemoteJobs.org recovering from a temporary 503. Each source's latest
snapshot below is independent: these counts are not a single globally deduplicated collection.

| Source | Public endpoint | Matched | Rejected role | Rejected remote | XML warnings | Notes |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| [Remotive](https://github.com/remotive-com/remote-jobs-api) | [Feed/API](https://remotive.com/api/remote-jobs) | 6 | 6 | 0 | 0 |  |
| [Arbeitnow](https://www.arbeitnow.com/blog/job-board-api) | [Feed/API](https://www.arbeitnow.com/api/job-board-api) | 0 | 26 | 274 | 0 | Request budget reached; more results may exist; Valid feed; no matching roles in this sample |
| [Himalayas](https://himalayas.app/api) | [Feed/API](https://himalayas.app/jobs/api/search) | 13 | 6 | 0 | 0 | Request budget reached; more results may exist |
| [Remote OK](https://remoteok.com/api) | [Feed/API](https://remoteok.com/api) | 8 | 91 | 0 | 0 |  |
| [Jobicy](https://jobicy.com/jobs-rss-feed) | [Feed/API](https://jobicy.com/api/v2/remote-jobs) | 46 | 54 | 0 | 0 | Request budget reached; more results may exist |
| [Working Nomads](https://www.workingnomads.com/jobs) | [Feed/API](https://www.workingnomads.com/api/exposed_jobs/) | 13 | 36 | 0 | 0 |  |
| [Really Remote](https://reallyremote.co/developers) | [Feed/API](https://reallyremote.co/api/public/jobs) | 31 | 69 | 0 | 0 | Request budget reached; more results may exist |
| [RemoteJobs.org](https://remotejobs.org/developers/api) | [Feed/API](https://remotejobs.org/api/v1/jobs) | 20 | 30 | 0 | 0 | Request budget reached; more results may exist |
| [We Work Remotely](https://weworkremotely.com/remote-job-rss-feed) | [Feed/API](https://weworkremotely.com/categories/remote-programming-jobs.rss) | 4 | 20 | 0 | 0 |  |
| [Real Work From Anywhere](https://www.realworkfromanywhere.com/rss-feeds) | [Feed/API](https://www.realworkfromanywhere.com/rss.xml) | 21 | 107 | 0 | 1 | Recoverable upstream XML; run reports partial |
| [NoDesk](https://nodesk.co/remote-jobs/) | [Feed/API](https://nodesk.co/remote-jobs/index.xml) | 1 | 9 | 0 | 1 | Recoverable upstream XML; run reports partial |
| [Jobspresso](https://jobspresso.co/) | [Feed/API](https://jobspresso.co/feed/?post_type=job_listing) | 4 | 16 | 0 | 0 |  |
| [Authentic Jobs](https://authenticjobs.com/) | [Feed/API](https://authenticjobs.com/?feed=job_feed&search_location=remote) | 2 | 4 | 0 | 0 | Mixed board: remote evidence required |
| [LaraJobs](https://larajobs.com/) | [Feed/API](https://larajobs.com/feed) | 3 | 1 | 0 | 0 | Mixed board: remote evidence required |
| [VueJobs](https://vuejobs.com/) | [Feed/API](https://app.vuejobs.com/feed/posts) | 87 | 83 | 986 | 0 | Mixed board: remote evidence required |
| [WordPress Jobs](https://jobs.wordpress.net/) | [Feed/API](https://jobs.wordpress.net/feed/) | 0 | 2 | 2 | 0 | Valid feed; no matching roles in this sample; Mixed board: remote evidence required |
| [Findjobit](https://findjobit.com/jobs) | [Feed/API](https://findjobit.com/jobs/feed) | 3 | 7 | 48 | 0 | Mixed board: remote evidence required |
| [CryptoJobsList](https://cryptojobslist.com/remote) | [Feed/API](https://api.cryptojobslist.com/jobs.rss?jobLocation=Remote) | 9 | 31 | 60 | 0 | Mixed board: remote evidence required |
| [Cryptocurrency Jobs](https://cryptocurrencyjobs.co/) | [Feed/API](https://cryptocurrencyjobs.co/index.xml) | 2 | 32 | 18 | 0 | Mixed board: remote evidence required |
| [FOSS Jobs](https://www.fossjobs.net/rss/) | [Feed/API](https://www.fossjobs.net/rss/all/) | 0 | 4 | 6 | 0 | Valid feed; no matching roles in this sample; Mixed board: remote evidence required |
| [Landing.jobs](https://landing.jobs/) | [Feed/API](https://landing.jobs/feed?remote=true) | 0 | 8 | 0 | 1 | Valid feed; no matching roles in this sample; Mixed board: remote evidence required; Recoverable upstream XML; run reports partial |
| [Hasjob](https://hasjob.co/) | [Feed/API](https://hasjob.co/feed) | 1 | 4 | 11 | 0 | Mixed board: remote evidence required |
| [RemoteFirstJobs](https://remotefirstjobs.com/rss) | [Feed/API](https://remotefirstjobs.com/rss/jobs/software-development.rss) | 20 | 78 | 2 | 0 |  |

The latest per-source snapshots accepted **294 postings** across the 23 providers, before
cross-source deduplication. Zero malformed job records were skipped in those snapshots. Parser
warnings are separate and visible. RemoteJobs.org was 503 in the first sweep; it returned a
usable 200 response in the follow-up. Earlier bounded probes also confirmed valid data from every
registered endpoint; no empty-success substitute is used for a blocked or failed source.

## Access and attribution

- [Remotive API rules](https://github.com/remotive-com/remote-jobs-api): software-dev category,
  delayed listings, original posting links and attribution; six-hour service cooldown implements
  its advice of at most four requests/day.
- [Remote OK's official API/feed help](https://remoteok.featurebase.app/en/help/articles/3140840-is-there-an-api-or-rssjson-feed-of-remote-jobs)
  and [feed terms](https://remoteok.com/api): keep a followed posting link and name attribution;
  ignore the metadata entry, not a job.
- [Jobicy API/feed documentation](https://jobicy.com/jobs-rss-feed): free public listing links,
  optional paid direct ATS links are not used; cursor pagination is bounded and attribution kept.
- [Himalayas API documentation](https://himalayas.app/api): search accepts keyword and page, short
  pages do not imply end-of-results. Keep original Himalayas URLs and country/timezone restrictions.
- [WWR feed documentation](https://weworkremotely.com/remote-job-rss-feed),
  [Real Work From Anywhere feeds](https://www.realworkfromanywhere.com/rss-feeds),
  [Really Remote developer docs](https://reallyremote.co/developers),
  [RemoteJobs.org API docs](https://remotejobs.org/developers/api), and
  [RemoteFirstJobs RSS docs](https://remotefirstjobs.com/rss) explicitly publish machine feeds.
  Preserve each posting URL and provider credit. Public redistribution has separate provider terms.
- Other integrated boards expose syndication on their own domains. The configured endpoint is
  the canonical feed URL; redirects are not automatically followed. WordPress/Hasjob/Vue/Lara and
  other mixed boards can include onsite jobs, so the scraper never assumes the whole board is remote.

## Candidates checked but not integrated

These outcomes describe this audit, not permanent judgments about a provider. HTML pages were
not promoted to working feeds, and a guessed RSS route is not evidence of an official API.

| Candidate | Observed result / reason excluded |
| --- | --- |
| FreshRemote.work | Connection failure; no working feed established |
| Remote1stJobs | Published jobs.json endpoint redirected to an HTML jobs page |
| EU Remote Jobs | Published/legacy feed request returned HTTP 403 |
| Remote.co | Feed request timed out; no access bypass attempted |
| Remote Rocketship | Canonical candidate RSS path returned 404 |
| Remote Leaf | Candidate feed path returned 404 |
| Dynamite Jobs | Candidate RSS path served HTML; no usable feed established |
| JustRemote | Candidate RSS path served HTML; no usable feed established |
| Remote.io | Legacy RSS host redirected; usable canonical feed not established |
| JS Remotely / JavaScript.jobs | Old feed redirects to a board page; candidate new RSS path returned 404 |
| Working Nomads legacy .co / Remote OK legacy .io / VueJobs legacy feed | Canonical working API/feed hosts were resolved and used instead |
| Crunchboard | Legacy jobs.rss redirects to generic Jobboard.io site |
| Find Bacon | Legacy RSS endpoint returned 404 |
| WP Hired | Feed request returned 522 |
| Freelancermap | Legacy international XML feed returned 404 |
| Jobhunt.ai / Privacy-First Jobs / Remotists | Connection or timeout failures |
| Smashing Jobs / ProBlogger | Empty feeds; ProBlogger also outside the requested developer focus |
| 4 Day Week | Candidate RSS route returned 404 |
| Remote in Tech | Company directory, not a job-posting feed |
| LinkedIn / Indeed / Glassdoor / Wellfound / FlexJobs | No verified permitted keyless job feed implemented; login/restriction/partner API workflows are separate work |
| Findwork / Adzuna / JSearch / Jooble / Reed / USAJOBS | Require credentials, partner access, or a broader non-remote API setup; none are silently enabled with missing keys |
| Reddit / Hacker News hiring threads | Mixed discussions rather than reliably structured job postings; no thread parsing shipped |
| Language-specific Python/Go/Rust/Clojure boards and design-only boards | Not prioritized over the requested full-stack/JS/TS developer sources |

Public employer ATS endpoints were researched too: [Greenhouse](https://developers.greenhouse.io/job-board.html),
[Lever](https://github.com/lever/postings-api), and
[Ashby](https://developers.ashbyhq.com/docs/public-job-posting-api). They require a curated employer
board list and per-employer remote evidence; they are not global remote job feeds. No speculative
board enumeration or unlisted-posting collection was added. Supporting those is a distinct
coverage expansion, not evidence that every employer on an ATS was scanned.

## Coverage limits

Feeds often expose only their most recent posts; repeated runs can rediscover the same posts.
Sources can return stale listings, incomplete descriptions, incidental technology mentions, or
incorrect remote claims. Classification is deterministic and tested on positive/negative examples;
it is not a semantic guarantee. One failed source does not prevent others from collecting.
The six-hour cooldown persists across restarts and failures, and max request/byte/job limits remain
in force. Run histories and /v1/sources show filtering, source errors, truncation and parser warnings.
