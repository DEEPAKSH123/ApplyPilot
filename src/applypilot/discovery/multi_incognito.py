"""Multi-Source Incognito & Fresh Discovery Engine.

Orchestrates headless, guest-mode incognito discovery across multiple platforms
with zero login requirements:
1. LinkedIn Incognito (multi-query fresh postings <= 4h, < 200 applicants)
2. Indeed India Incognito (past 24h, negative seniority filters)
3. Direct ATS Fast Sweep (Greenhouse, Lever, SmartRecruiters for 35+ top tech employers)
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from applypilot.discovery.ats import run_ats_discovery
from applypilot.discovery.indeed_incognito import scan_indeed_incognito_recent_jobs
from applypilot.networking.linkedin import scan_linkedin_incognito_recent_jobs

log = logging.getLogger(__name__)


def run_fresh_incognito_multisource_scan(
    linkedin_hours: int = 4,
    indeed_days: int = 1,
    run_ats: bool = True,
    workers: int = 4,
) -> dict[str, Any]:
    """Execute simultaneous fresh discovery across LinkedIn, Indeed, and Direct ATS.

    All sources operate in zero-login / guest incognito mode with strict 0-3 YOE
    backend role and location filtering.
    """
    summary: dict[str, Any] = {
        "status": "ok",
        "sources": {},
        "total_new_jobs": 0,
        "total_found": 0,
    }

    def _sweep_linkedin():
        try:
            log.info("Running LinkedIn Fresh Incognito sweep...")
            return ("linkedin", scan_linkedin_incognito_recent_jobs(hours_old=linkedin_hours, max_pages=2, max_applicants=200))
        except Exception as e:
            log.error("LinkedIn sweep error: %s", e)
            return ("linkedin", {"status": "error", "error": str(e), "new_jobs_added": 0, "total_found": 0})

    def _sweep_indeed():
        try:
            log.info("Running Indeed India Fresh Incognito sweep...")
            return ("indeed", scan_indeed_incognito_recent_jobs(fromage_days=indeed_days, max_pages_per_query=2))
        except Exception as e:
            log.error("Indeed sweep error: %s", e)
            return ("indeed", {"status": "error", "error": str(e), "new_jobs_added": 0, "total_found": 0})

    def _sweep_ats():
        if not run_ats:
            return ("ats", {"found": 0, "new": 0})
        try:
            log.info("Running Direct ATS Fast Sweep across configured product companies...")
            res = run_ats_discovery(workers=workers)
            return ("ats", {"status": "ok", "total_found": res.get("found", 0), "new_jobs_added": res.get("new", 0)})
        except Exception as e:
            log.error("Direct ATS sweep error: %s", e)
            return ("ats", {"status": "error", "error": str(e), "new_jobs_added": 0, "total_found": 0})

    tasks = [_sweep_linkedin, _sweep_indeed, _sweep_ats]

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(t) for t in tasks]
        for f in as_completed(futures):
            src_name, src_res = f.result()
            summary["sources"][src_name] = src_res
            summary["total_new_jobs"] += src_res.get("new_jobs_added", src_res.get("new", 0))
            summary["total_found"] += src_res.get("total_found", src_res.get("found", 0))

    log.info(
        "Multi-source incognito sweep finished: %d new jobs discovered (total found: %d)",
        summary["total_new_jobs"],
        summary["total_found"],
    )
    return summary
