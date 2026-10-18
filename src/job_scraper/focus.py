"""Deterministic discovery scope, not an assessment of personal eligibility."""

import re

ROLE = re.compile(
    r"\b(developer|dev|engineer|programmer|architect|software|desarrollador|développeur|"
    r"desenvolvedor|technical lead|tech lead)\b",
    re.I,
)
FULLSTACK = re.compile(r"\bfull[\s-]?stack\b", re.I)
FRONTEND = re.compile(r"\b(front[\s-]?end|web developer|web engineer|ui engineer)\b", re.I)
STACK = re.compile(
    r"\b(typescript|javascript|node\.?js|next\.?js|nest\.?js|nuxt(?:\.?js)?|"
    r"react(?:\.?js)?|vue(?:\.?js)?|angular|svelte|deno)\b",
    re.I,
)
NON_DEVELOPER = re.compile(
    r"\b(recruiter|recruitment|sales|account executive|marketing|customer|support|"
    r"designer|advocate|evangelist|developer relations|product manager|project manager|program manager|engineering manager|"
    r"director|vice president|devops|sre|data engineer|data scientist|security engineer|"
    r"quality assurance|qa|sdet|test engineer|automation tester)\b",
    re.I,
)
HYBRID = re.compile(r"\b(hybrid|on[\s-]?site|office[\s-]?based)\b", re.I)
REMOTE = re.compile(r"\b(remote|remoto|remota|remotely|anywhere|worldwide|telecommut\w*)\b", re.I)
REMOTE_DESCRIPTION = re.compile(
    r"\b(100\s*%\s*remote|fully[\s-]+remote|full[\s-]+remote|work(?:ing)? remotely|"
    r"work from (?:anywhere|home)|remote[\s-]+(?:role|position|job|first|work)|"
    r"can be done remotely|fully distributed|trabajo remoto|modalidad remota)\b",
    re.I,
)
NOT_REMOTE = re.compile(
    r"\b(not remote|no remote (?:work|option)|remote (?:work )?not (?:available|allowed))\b", re.I
)


def remote_claim(title, location, description="", *, declared=None, remote_feed=False):
    """Return a remote claim plus its evidence; ambiguous mixed-board entries stay unknown."""
    header = f"{title} {location or ''}"
    if declared is False or NOT_REMOTE.search(header) or NOT_REMOTE.search(description):
        return False, "Explicitly non-remote"
    if HYBRID.search(header):
        return False, "Hybrid or onsite in title/location"
    if declared is True:
        return True, "Source remote flag"
    match = REMOTE.search(header)
    if match:
        return True, f"Title/location: {match.group()}"
    match = REMOTE_DESCRIPTION.search(description)
    if match:
        return True, f"Description: {match.group()}"
    if remote_feed:
        return True, "Remote-only source feed; geographic eligibility remains unknown"
    return None, None


def role_matches(job) -> bool:
    title = job.title
    if NON_DEVELOPER.search(title):
        return False
    if FULLSTACK.search(title) or FRONTEND.search(title):
        return True
    if not ROLE.search(title):
        return False
    if re.search(r"\b(node|bun|next|nest)\b", " ".join([title, *job.tags]), re.I):
        return True
    # Generic software/backend/mobile roles need actual evidence of a JS/TS stack.
    return bool(STACK.search(" ".join([title, *job.tags, job.description])))


def in_scope(job) -> bool:
    return (
        job.remote is True
        and not HYBRID.search(f"{job.title} {job.location or ''}")
        and role_matches(job)
    )
