"""Map facts from public JSON feeds into the common posting model."""

import hashlib

from .focus import remote_claim
from .models import Job, date_text, plain
from .sources import SPECS


def strings(value):
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return []


def salary(item, keys):
    return " ".join(str(item[k]) for k in keys if item.get(k) is not None) or None


def normalize(source: str, item: dict) -> Job:
    if source == "remotive":
        values = dict(
            source_id=str(item.get("id") or ""),
            title=plain(item.get("title")),
            company=item.get("company_name"),
            source_url=item.get("url"),
            location=item.get("candidate_required_location"),
            description=plain(item.get("description")),
            salary_text=item.get("salary"),
            employment_type=item.get("job_type"),
            tags=strings(item.get("tags")),
            published_at=date_text(item.get("publication_date")),
        )
    elif source == "arbeitnow":
        values = dict(
            source_id=item.get("slug") or "",
            title=plain(item.get("title")),
            company=item.get("company_name"),
            source_url=item.get("url"),
            location=item.get("location"),
            remote=item.get("remote"),
            description=plain(item.get("description")),
            tags=strings(item.get("tags")),
            published_at=date_text(item.get("created_at")),
        )
    elif source == "himalayas":
        restrictions = strings(item.get("locationRestrictions"))
        values = dict(
            source_id=item.get("guid") or "",
            title=plain(item.get("title")),
            company=item.get("companyName"),
            source_url=item.get("guid"),
            location=", ".join(restrictions) or None,
            location_restrictions=restrictions,
            timezone_restrictions=item.get("timezoneRestrictions") or [],
            description=plain(item.get("description") or item.get("excerpt")),
            salary_text=salary(item, ("minSalary", "maxSalary", "currency", "salaryPeriod")),
            employment_type=item.get("employmentType"),
            tags=strings(item.get("categories")),
            published_at=date_text(item.get("pubDate")),
            expires_at=date_text(item.get("expiryDate")),
        )
    elif source == "remoteok":
        values = dict(
            source_id=str(item.get("id") or ""),
            title=plain(item.get("position")),
            source_url=item.get("url"),
            company=item.get("company"),
            location=item.get("location"),
            description=plain(item.get("description")),
            tags=strings(item.get("tags")),
            salary_text=item.get("salary"),
            published_at=date_text(item.get("date")),
        )
        # Remote OK's zero/zero salary bounds represent missing pay, not an unpaid role.
        if not values["salary_text"] and (item.get("salary_min") or item.get("salary_max")):
            values["salary_text"] = salary(item, ("salary_min", "salary_max", "salary_currency"))
    elif source == "jobicy":
        values = dict(
            source_id=str(item.get("id") or ""),
            title=plain(item.get("jobTitle")),
            source_url=item.get("url"),
            company=item.get("companyName"),
            location=item.get("jobGeo"),
            description=plain(item.get("jobDescription") or item.get("jobExcerpt")),
            tags=strings(item.get("jobIndustry")),
            employment_type=", ".join(strings(item.get("jobType"))) or None,
            salary_text=salary(item, ("salaryMin", "salaryMax", "salaryCurrency", "salaryPeriod")),
            published_at=date_text(item.get("pubDate")),
        )
    elif source == "workingnomads":
        values = dict(
            source_id=str(item.get("id") or item.get("url") or ""),
            title=plain(item.get("title")),
            source_url=item.get("url"),
            company=item.get("company_name"),
            location=item.get("location"),
            description=plain(item.get("description")),
            tags=strings(item.get("tags")),
            published_at=date_text(item.get("pub_date")),
        )
    elif source == "reallyremote":
        values = dict(
            source_id=item.get("slug") or "",
            title=plain(item.get("title")),
            source_url=item.get("url"),
            company=item.get("company"),
            # Do not turn the site's worldwide verdict into verified geographic eligibility.
            location=item.get("location"),
            description=plain(item.get("description") or item.get("summary")),
            tags=strings(item.get("tags")),
            published_at=date_text(item.get("posted_at")),
            salary_text=salary(
                item, ("salary_min", "salary_max", "salary_currency", "salary_period")
            ),
        )
    elif source == "remotejobsorg":
        company = item.get("company") or {}
        facts = item.get("search_facts") or {}
        geography = item.get("location_normalization") or {}
        values = dict(
            source_id=str(item.get("id") or ""),
            title=plain(item.get("title")),
            source_url=item.get("url"),
            company=company.get("name"),
            location=item.get("location"),
            description=plain(item.get("description")),
            tags=strings(facts.get("required_skills")) + strings(facts.get("mentioned_skills")),
            salary_text=item.get("salary_source_text") or item.get("salary_text"),
            employment_type=item.get("type"),
            published_at=date_text(item.get("posted_at")),
            location_restrictions=strings(geography.get("allowed_countries")),
        )
    else:
        raise ValueError("Unknown JSON source")
    remote, evidence = remote_claim(
        values["title"],
        values.get("location"),
        values.get("description", ""),
        declared=values.pop("remote", None),
        remote_feed=SPECS[source].remote_only,
    )
    identity = f"{source}:{values['source_id']}"
    return Job(
        id=hashlib.sha256(identity.encode()).hexdigest(),
        source=source,
        remote=remote,
        remote_evidence=evidence,
        **values,
    )
