"""Automated Community & Inbound Poller for ApplyPilot.

Runs scheduled or on-demand cycles across:
1. Live WhatsApp Web monitoring (using synced Brave profile session)
2. Telegram Tech & Referral Channels (@placementlelo, @offcampusjobs4u, etc.)
3. Inbound Recruiter Gmail sync (Interviews, OAs, Rejections, Offers)
4. Export and synchronization to data/opportunities.csv and SQLite
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from applypilot.config import APP_DIR
from applypilot.discovery.whatsapp import scrape_live_whatsapp_web, ingest_whatsapp_folder
from applypilot.discovery.telegram import run_discovery as run_telegram_discovery
from applypilot.enrichment.email_tracker import sync_gmail_job_responses
from applypilot.export.csv_export import export_opportunities_csv

log = logging.getLogger(__name__)


def execute_polling_cycle(headless: bool = True) -> dict[str, Any]:
    """Execute a single complete polling cycle."""
    started_at = datetime.now(timezone.utc).isoformat()
    log.info("Starting automated ApplyPilot polling cycle at %s...", started_at)

    results: dict[str, Any] = {
        "started_at": started_at,
        "whatsapp_jobs_new": 0,
        "telegram_jobs_new": 0,
        "gmail_responses_new": 0,
        "csv_path": None,
        "status": "success",
        "errors": []
    }

    # 1. Telegram tech channels (Fast & zero UI friction)
    try:
        log.info("[1/3] Polling Telegram tech channels...")
        tg_count = run_telegram_discovery()
        results["telegram_jobs_new"] = tg_count
    except Exception as e:
        log.warning("Telegram polling error: %s", e)
        results["errors"].append(f"Telegram: {e}")

    # 2. WhatsApp community channels
    try:
        log.info("[2/3] Ingesting WhatsApp chat export files...")
        wa_folder_count = ingest_whatsapp_folder()
        log.info("[2/3] Polling live WhatsApp Web via Brave profile...")
        wa_live_count = scrape_live_whatsapp_web(headless=headless, wait_timeout_sec=40)
        results["whatsapp_jobs_new"] = wa_folder_count + wa_live_count
    except Exception as e:
        log.warning("WhatsApp polling error: %s", e)
        results["errors"].append(f"WhatsApp: {e}")

    # 3. Gmail recruiter tracking
    try:
        log.info("[3/4] Syncing inbound recruiter updates from Gmail...")
        new_responses = sync_gmail_job_responses(max_results=25)
        results["gmail_responses_new"] = len(new_responses)

        # Dispatch immediate Telegram push for high-priority recruiter events
        if new_responses:
            try:
                from applypilot.automation.telegram_notifier import alert_urgent_oa, alert_recruiter_interview
                for resp in new_responses:
                    cat = resp.get("category", "")
                    comp = resp.get("company", "Employer")
                    if cat in ("oa", "assessment", "oa_missed"):
                        alert_urgent_oa(
                            company=comp,
                            role=resp.get("subject", "Online Assessment"),
                            deadline=resp.get("deadline", "Check Dashboard"),
                            test_url=resp.get("portal_link", "")
                        )
                    elif cat in ("interview", "selection", "shortlist"):
                        alert_recruiter_interview(
                            company=comp,
                            sender_name=resp.get("sender", "Recruiter"),
                            snippet=resp.get("snippet", "")
                        )
            except Exception as pe:
                log.debug("Push alert notification error: %s", pe)
    except Exception as e:
        log.warning("Gmail sync error: %s", e)
        results["errors"].append(f"Gmail: {e}")

    # 4. KaDegree Kannada Referral Community
    try:
        log.info("[4/5] Syncing KaDegree Kannada Referral Community...")
        from applypilot.discovery.kadegree import sync_kadegree_jobs
        kd_res = sync_kadegree_jobs()
        results["kadegree_jobs_new"] = kd_res.get("new_stored", 0)
    except Exception as e:
        log.warning("KaDegree sync error: %s", e)
        results["errors"].append(f"KaDegree: {e}")

    # 5. Live LinkedIn Tech Crawl (JobSpy Backend Roles)
    try:
        log.info("[5/6] Crawling fresh LinkedIn postings for Bangalore backend roles...")
        from applypilot.discovery.jobspy import search_jobs
        li_res = search_jobs(
            query="Software Engineer Backend",
            location="Bengaluru, India",
            sites=["linkedin"],
            remote_only=False,
            results_per_site=15,
            hours_old=24,
            country_indeed="india"
        )
        results["linkedin_jobs_new"] = li_res.get("new", 0)
    except Exception as e:
        log.warning("LinkedIn JobSpy crawl error: %s", e)
        results["errors"].append(f"LinkedIn: {e}")

    # 6. Referral Connections Acceptance Check & Follow-Up Sync
    try:
        log.info("[6/6] Syncing accepted LinkedIn referral requests...")
        from applypilot.networking.referral_tracker import sync_accepted_connections_from_linkedin
        ref_sync = sync_accepted_connections_from_linkedin(max_check=30, headless=headless)
        results["referral_accepted_new"] = ref_sync.get("matched_count", 0)
    except Exception as e:
        log.warning("Referral acceptance sync error: %s", e)
        results["errors"].append(f"ReferralSync: {e}")

    # 7. Prune stale jobs older than 15 days (safe — never deletes applied/interview rows)
    try:
        log.info("[7/7] Pruning stale job listings older than 15 days...")
        from applypilot.database import prune_old_jobs
        prune_result = prune_old_jobs(days=15)
        results["pruned_jobs"] = prune_result.get("deleted", 0)
        log.info("Pruned %d stale jobs.", prune_result.get("deleted", 0))
    except Exception as e:
        log.warning("Job prune error: %s", e)
        results["errors"].append(f"Prune: {e}")

    # 5. Refresh opportunities.csv
    try:
        csv_file = export_opportunities_csv()
        results["csv_path"] = str(csv_file)
        log.info("Updated master CSV ledger: %s", csv_file)
    except Exception as e:
        log.warning("CSV export error: %s", e)

    results["completed_at"] = datetime.now(timezone.utc).isoformat()
    log.info("Completed polling cycle: WA=%d, TG=%d, Gmail=%d",
             results["whatsapp_jobs_new"], results["telegram_jobs_new"], results["gmail_responses_new"])
    return results


def run_poller_loop(interval_hours: float = 12.0, headless: bool = True) -> None:
    """Run polling in a continuous daemon loop (default: twice a day = 12 hours)."""
    log.info("Starting ApplyPilot daemon poller loop (interval: %.1f hours)...", interval_hours)
    sleep_seconds = int(interval_hours * 3600)

    while True:
        try:
            execute_polling_cycle(headless=headless)
        except Exception as e:
            log.error("Unhandled error in polling cycle: %s", e)

        log.info("Sleeping for %d seconds (%.1f hours) until next polling cycle...", sleep_seconds, interval_hours)
        time.sleep(sleep_seconds)
