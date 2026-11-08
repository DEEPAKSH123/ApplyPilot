"""Direct ATS Job Discovery: Greenhouse, Lever, SmartRecruiters, Ashby boards.

Directly queries official public job board APIs for verified employers.
Zero browser automation, pure HTTP/JSON.
"""

import logging
import re
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from curl_cffi import requests

from applypilot import config
from applypilot.config import CONFIG_DIR
from applypilot.database import get_connection, init_db, store_jobs_deduped
from applypilot.discovery.workday import _location_ok, _posted_within_days, _title_ok, strip_html

log = logging.getLogger(__name__)

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


# ── Load ATS Employers ───────────────────────────────────────────────────

def load_ats_employers() -> dict:
    """Load employers using direct ATS boards (Greenhouse, Lever, SmartRecruiters, Ashby)."""
    import yaml
    path = CONFIG_DIR / "employers.yaml"
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    employers = data.get("employers", {})
    return {k: v for k, v in employers.items() if v.get("ats") in ("greenhouse", "lever", "smartrecruiters", "ashby")}


# ── Individual ATS Fetchers ───────────────────────────────────────────────

def _scrape_greenhouse(employer_key: str, emp: dict, accept_locs: list[str], reject_locs: list[str],
                        max_days_old: int, exclude_titles: list[str]) -> list[dict]:
    """Fetch and filter jobs from a Greenhouse board."""
    slug = emp.get("slug")
    name = emp.get("name", employer_key)
    api_url = emp.get("api_url") or f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"

    try:
        r = requests.get(api_url, impersonate="chrome120", timeout=10)
        if r.status_code != 200:
            log.warning("Greenhouse [%s] HTTP %d", name, r.status_code)
            return []
        data = r.json()
        raw_jobs = data.get("jobs", [])
    except Exception as e:
        log.error("Greenhouse [%s] error: %s", name, e)
        return []

    matched = []
    for j in raw_jobs:
        title = j.get("title", "")
        if not _title_ok(title, exclude_titles):
            continue

        loc_obj = j.get("location", {})
        loc = loc_obj.get("name", "") if isinstance(loc_obj, dict) else str(loc_obj)
        if not _location_ok(loc, accept_locs, reject_locs):
            continue

        updated = j.get("updated_at") or j.get("first_published")
        if max_days_old > 0 and not _posted_within_days(updated, max_days_old):
            continue

        job_id = j.get("id")
        apply_url = j.get("absolute_url", "")

        # Fetch detail for full description
        full_desc = ""
        if job_id and slug:
            try:
                detail_url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{job_id}"
                dr = requests.get(detail_url, impersonate="chrome120", timeout=8)
                if dr.status_code == 200:
                    full_desc = strip_html(dr.json().get("content", ""))
            except Exception:
                pass

        matched.append({
            "title": title,
            "site": name,
            "location": loc,
            "url": apply_url,
            "application_url": apply_url,
            "full_description": full_desc,
            "description": full_desc[:500] if full_desc else title,
            "strategy": "greenhouse_api",
        })

    return matched


def _scrape_lever(employer_key: str, emp: dict, accept_locs: list[str], reject_locs: list[str],
                  max_days_old: int, exclude_titles: list[str]) -> list[dict]:
    """Fetch and filter jobs from a Lever board."""
    slug = emp.get("slug")
    name = emp.get("name", employer_key)
    api_url = emp.get("api_url") or f"https://api.lever.co/v0/postings/{slug}?mode=json"

    try:
        r = requests.get(api_url, impersonate="chrome120", timeout=10)
        if r.status_code != 200:
            log.warning("Lever [%s] HTTP %d", name, r.status_code)
            return []
        raw_jobs = r.json()
        if not isinstance(raw_jobs, list):
            return []
    except Exception as e:
        log.error("Lever [%s] error: %s", name, e)
        return []

    matched = []
    for j in raw_jobs:
        title = j.get("text", "")
        if not _title_ok(title, exclude_titles):
            continue

        cats = j.get("categories", {})
        loc = cats.get("location", "") or cats.get("allLocations", [""])[0] if isinstance(cats, dict) else ""
        if not _location_ok(loc, accept_locs, reject_locs):
            continue

        created_ms = j.get("createdAt")
        posted_str = None
        if created_ms:
            days = (time.time() - (created_ms / 1000)) / 86400
            posted_str = f"{int(days)} days ago"
            if max_days_old > 0 and days > max_days_old:
                continue

        apply_url = j.get("hostedUrl", "")
        desc = j.get("descriptionPlain", "") or strip_html(j.get("description", ""))

        matched.append({
            "title": title,
            "site": name,
            "location": loc,
            "url": apply_url,
            "application_url": apply_url,
            "full_description": desc,
            "description": desc[:500] if desc else title,
            "strategy": "lever_api",
        })

    return matched


def _scrape_smartrecruiters(employer_key: str, emp: dict, accept_locs: list[str], reject_locs: list[str],
                            max_days_old: int, exclude_titles: list[str]) -> list[dict]:
    """Fetch and filter jobs from a SmartRecruiters board."""
    slug = emp.get("slug")
    name = emp.get("name", employer_key)
    api_url = emp.get("api_url") or f"https://api.smartrecruiters.com/v1/companies/{slug}/postings"

    try:
        r = requests.get(api_url, impersonate="chrome120", timeout=10)
        if r.status_code != 200:
            log.warning("SmartRecruiters [%s] HTTP %d", name, r.status_code)
            return []
        raw_jobs = r.json().get("content", [])
    except Exception as e:
        log.error("SmartRecruiters [%s] error: %s", name, e)
        return []

    matched = []
    for j in raw_jobs:
        title = j.get("name", "")
        if not _title_ok(title, exclude_titles):
            continue

        loc_obj = j.get("location", {})
        city = loc_obj.get("city", "")
        country = loc_obj.get("country", "")
        loc = f"{city}, {country}".strip(", ")
        if not _location_ok(loc, accept_locs, reject_locs):
            continue

        released = j.get("releasedDate")
        if max_days_old > 0 and not _posted_within_days(released, max_days_old):
            continue

        job_id = j.get("id")
        ref = j.get("refNumber", "")
        apply_url = f"https://jobs.smartrecruiters.com/{slug}/{job_id}"

        # Fetch detail
        full_desc = ""
        if job_id:
            try:
                detail_url = f"https://api.smartrecruiters.com/v1/companies/{slug}/postings/{job_id}"
                dr = requests.get(detail_url, impersonate="chrome120", timeout=8)
                if dr.status_code == 200:
                    dj = dr.json()
                    sections = dj.get("jobAd", {}).get("sections", {})
                    parts = []
                    for s in sections.values():
                        parts.append(strip_html(s.get("text", "")))
                    full_desc = "\n\n".join(parts)
            except Exception:
                pass

        matched.append({
            "title": title,
            "site": name,
            "location": loc,
            "url": apply_url,
            "application_url": apply_url,
            "full_description": full_desc,
            "description": full_desc[:500] if full_desc else title,
            "strategy": "smartrecruiters_api",
        })

    return matched


# ── Main ATS Runner ───────────────────────────────────────────────────────

def run_ats_discovery(workers: int = 4) -> dict:
    """Discover jobs across all configured direct ATS employers (Greenhouse, Lever, SmartRecruiters)."""
    employers = load_ats_employers()
    if not employers:
        log.info("No direct ATS employers configured.")
        return {"found": 0, "new": 0, "existing": 0}

    search_cfg = config.load_search_config()
    from applypilot.discovery.workday import _load_location_filter
    accept_locs, reject_locs = _load_location_filter(search_cfg)
    max_days_old = search_cfg.get("max_posted_days", 10)
    exclude_titles = search_cfg.get("exclude_titles", [])

    log.info("Direct ATS discovery: %d employers (workers=%d)", len(employers), workers)

    def _process_emp(item):
        key, emp = item
        ats = emp.get("ats")
        if ats == "greenhouse":
            return _scrape_greenhouse(key, emp, accept_locs, reject_locs, max_days_old, exclude_titles)
        elif ats == "lever":
            return _scrape_lever(key, emp, accept_locs, reject_locs, max_days_old, exclude_titles)
        elif ats == "smartrecruiters":
            return _scrape_smartrecruiters(key, emp, accept_locs, reject_locs, max_days_old, exclude_titles)
        return []

    all_matched = []
    with ThreadPoolExecutor(max_workers=min(workers, len(employers))) as pool:
        futures = [pool.submit(_process_emp, item) for item in employers.items()]
        for f in as_completed(futures):
            try:
                res = f.result()
                all_matched.extend(res)
            except Exception as e:
                log.error("ATS worker error: %s", e)

    log.info("Direct ATS discovery found %d matching jobs across %d employers", len(all_matched), len(employers))

    conn = get_connection()
    new_count = 0
    dupe_count = 0
    cross_dupe_count = 0

    now = datetime.now(timezone.utc).isoformat()
    for job in all_matched:
        # Cross-source deduplication
        n, e, c = store_jobs_deduped(conn, [job], job["site"], job["strategy"])
        new_count += n
        dupe_count += e
        cross_dupe_count += c

    log.info("ATS stored: %d new, %d URL dupes, %d cross-source dupes", new_count, dupe_count, cross_dupe_count)
    return {"found": len(all_matched), "new": new_count, "existing": dupe_count, "cross_dupes": cross_dupe_count}
