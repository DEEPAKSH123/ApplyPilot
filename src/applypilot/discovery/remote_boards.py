"""Remote Boards Discovery Module (Remotive & Working Nomads APIs).

Crawls remote tech boards that provide official, free JSON feeds:
- Remotive (https://remotive.com/api/remote-jobs)
- Working Nomads (https://www.workingnomads.com/api/exposed_jobs/)

Filters specifically for Backend, Distributed Systems, Golang, and Java roles.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
import httpx

from applypilot import config
from applypilot.database import get_connection, store_jobs_deduped
from applypilot.discovery.workday import _location_ok, _posted_within_days, _title_ok, strip_html

log = logging.getLogger(__name__)

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def scrape_remotive(accept_locs: list[str], reject_locs: list[str], max_days_old: int = 14) -> list[dict]:
    """Fetch backend & software developer roles from Remotive official API."""
    url = "https://remotive.com/api/remote-jobs?category=software-dev&limit=40"
    matched = []
    try:
        with httpx.Client(headers=HEADERS, timeout=10) as client:
            resp = client.get(url)
        if resp.status_code != 200:
            log.warning("Remotive API HTTP %d", resp.status_code)
            return []
        data = resp.json()
        raw_jobs = data.get("jobs", [])
    except Exception as e:
        log.error("Remotive API error: %s", e)
        return []

    target_keywords = ["backend", "software engineer", "developer", "golang", "java", "distributed", "api", "platform"]

    for j in raw_jobs:
        title = j.get("title", "")
        desc = j.get("description", "")
        comb_text = f"{title} {desc}".lower()

        # Must match developer / backend criteria
        if not any(k in comb_text for k in target_keywords):
            continue

        loc = j.get("candidate_required_location", "Remote")
        # Accept if worldwide or any location acceptable for India / remote
        loc_lower = loc.lower()
        if "only" in loc_lower and not any(k in loc_lower for k in ("worldwide", "anywhere", "india", "apac")):
            continue

        pub = j.get("publication_date")
        apply_url = j.get("url") or ""
        company = j.get("company_name", "Remote Company")

        clean_desc = strip_html(desc) if desc else title

        matched.append({
            "title": title,
            "site": company,
            "location": f"Remote ({loc})",
            "url": apply_url,
            "application_url": apply_url,
            "full_description": clean_desc,
            "description": clean_desc[:500] if clean_desc else title,
            "salary": j.get("salary") or None,
            "strategy": "remotive_api",
            "date_posted": pub[:10] if pub else None,
        })

    return matched


def scrape_working_nomads(accept_locs: list[str], reject_locs: list[str], max_days_old: int = 14) -> list[dict]:
    """Fetch developer roles from Working Nomads exposed API."""
    url = "https://www.workingnomads.com/api/exposed_jobs/"
    matched = []
    try:
        with httpx.Client(headers=HEADERS, timeout=10) as client:
            resp = client.get(url)
        if resp.status_code != 200:
            log.warning("Working Nomads HTTP %d", resp.status_code)
            return []
        raw_jobs = resp.json()
        if not isinstance(raw_jobs, list):
            return []
    except Exception as e:
        log.error("Working Nomads error: %s", e)
        return []

    target_keywords = ["backend", "software engineer", "developer", "golang", "java", "distributed", "api", "sde"]

    for j in raw_jobs:
        title = j.get("title", "")
        cat = j.get("category_name", "")
        comb_text = f"{title} {cat}".lower()

        if not any(k in comb_text for k in target_keywords):
            continue

        loc = j.get("location", "Remote")
        loc_lower = loc.lower()
        # Filter out US-only / UK-only / EU-only if strict timezone
        if any(r in loc_lower for r in ("us only", "usa only", "uk only", "canada only")):
            continue

        company = j.get("company_name", "Remote Company")
        apply_url = j.get("url") or ""
        desc = j.get("description", "")
        clean_desc = strip_html(desc) if desc else title

        pub = j.get("pub_date")

        matched.append({
            "title": title,
            "site": company,
            "location": f"Remote ({loc})",
            "url": apply_url,
            "application_url": apply_url,
            "full_description": clean_desc,
            "description": clean_desc[:500] if clean_desc else title,
            "strategy": "workingnomads_api",
            "date_posted": pub[:10] if pub else None,
        })

    return matched


def run_remote_boards_discovery() -> dict:
    """Run discovery across Remotive & Working Nomads and persist to DB."""
    search_cfg = config.load_search_config()
    from applypilot.discovery.workday import _load_location_filter
    accept_locs, reject_locs = _load_location_filter(search_cfg)
    max_days = search_cfg.get("max_posted_days", 14)

    all_jobs = []
    try:
        rem_jobs = scrape_remotive(accept_locs, reject_locs, max_days)
        all_jobs.extend(rem_jobs)
        log.info("Remotive discovered %d matching remote roles", len(rem_jobs))
    except Exception as e:
        log.error("Remotive runner error: %s", e)

    try:
        wn_jobs = scrape_working_nomads(accept_locs, reject_locs, max_days)
        all_jobs.extend(wn_jobs)
        log.info("Working Nomads discovered %d matching remote roles", len(wn_jobs))
    except Exception as e:
        log.error("Working Nomads runner error: %s", e)

    conn = get_connection()
    new_count = 0
    dupe_count = 0
    cross_dupe_count = 0

    for job in all_jobs:
        n, e, c = store_jobs_deduped(conn, [job], job["site"], job["strategy"])
        new_count += n
        dupe_count += e
        cross_dupe_count += c

    return {
        "status": "ok",
        "total_found": len(all_jobs),
        "new_stored": new_count,
        "duplicates": dupe_count + cross_dupe_count,
    }
