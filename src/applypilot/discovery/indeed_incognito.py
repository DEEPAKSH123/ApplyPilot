"""Indeed India incognito / guest-mode scraper.

Scrapes recent jobs from in.indeed.com with 24-hour freshness, location filters,
and negative seniority keywords (-senior, -lead, -staff, -manager) without requiring login.
"""

import logging
import re
import urllib.parse
from datetime import datetime, timezone
from typing import Any

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from applypilot import config
from applypilot.database import get_connection, store_jobs_deduped
from applypilot.discovery.workday import _location_ok
from applypilot.networking.linkedin import check_experience_exceeds, is_company_excluded, is_role_relevant_for_backend

log = logging.getLogger(__name__)


def scan_indeed_incognito_recent_jobs(
    queries: list[str] | None = None,
    location: str = "Bengaluru, Karnataka",
    fromage_days: int = 1,
    max_pages_per_query: int = 2,
) -> dict[str, Any]:
    """Scrape fresh jobs from Indeed India in headless incognito mode without logging in.

    Args:
        queries: List of job search strings (e.g. ['Backend Engineer', 'Java Developer', 'Golang Developer']).
        location: Target location (default: Bengaluru, Karnataka).
        fromage_days: Age in days (1 = last 24 hours).
        max_pages_per_query: Pages to fetch per query.

    Returns:
        Summary dict with discovered, filtered, and newly inserted job counts.
    """
    if not queries:
        queries = [
            "Backend Engineer",
            "Java Developer",
            "Golang Developer",
            "Software Engineer Backend",
        ]

    search_cfg = config.load_search_config()
    from applypilot.discovery.workday import _load_location_filter
    accept_locs, reject_locs = _load_location_filter(search_cfg)

    seen_links = set()
    all_jobs: list[dict[str, Any]] = []

    log.info("Starting Indeed India Incognito scan: %d queries, location=%s, fromage=%d", len(queries), location, fromage_days)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled", "--incognito"]
            )
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 850}
            )
            page = context.new_page()

            for q_idx, raw_q in enumerate(queries):
                q = raw_q.strip()
                # Apply negative seniority filters
                query_str = f"({q}) -senior -lead -staff -manager -director -principal"
                encoded_q = urllib.parse.quote(query_str)
                encoded_loc = urllib.parse.quote(location)

                for page_idx in range(max_pages_per_query):
                    start = page_idx * 10
                    url = f"https://in.indeed.com/jobs?q={encoded_q}&l={encoded_loc}&fromage={fromage_days}&sort=date"
                    if start > 0:
                        url += f"&start={start}"

                    log.info("[%d/%d] Fetching Indeed: %s (page %d)", q_idx + 1, len(queries), q, page_idx + 1)

                    try:
                        page.goto(url, wait_until="domcontentloaded", timeout=20000)
                        page.wait_for_timeout(2000)
                        # Scroll to trigger lazy renders
                        page.evaluate("window.scrollBy(0, 1000);")
                        page.wait_for_timeout(800)
                    except Exception as err:
                        log.warning("Indeed navigation failed for %s: %s", q, err)
                        break

                    soup = BeautifulSoup(page.content(), "html.parser")
                    cards = soup.find_all("div", class_="job_seen_beacon")
                    if not cards:
                        # Fallback cards selector
                        cards = soup.find_all("div", {"data-jk": True})
                    if not cards:
                        log.debug("No more Indeed cards found for query %s at page %d", q, page_idx + 1)
                        break

                    for card in cards:
                        try:
                            # 1. Job title & Link
                            title_el = card.find("a", class_="jcs-JobTitle") or card.find("h2")
                            if not title_el:
                                continue
                            title = title_el.text.strip()
                            jk = card.get("data-jk")
                            if not jk and hasattr(title_el, "get"):
                                jk = title_el.get("data-jk")

                            if jk:
                                job_url = f"https://in.indeed.com/viewjob?jk={jk}"
                            elif title_el.name == "a" and title_el.get("href"):
                                href = title_el.get("href")
                                job_url = urllib.parse.urljoin("https://in.indeed.com", href)
                            else:
                                continue

                            if job_url in seen_links:
                                continue
                            seen_links.add(job_url)

                            # 2. Company & Location
                            cmp_el = card.find("span", {"data-testid": "company-name"}) or card.find(class_="companyName")
                            company = cmp_el.text.strip() if cmp_el else "Employer"

                            # Skip blacklisted companies (Accenture, Infosys, Capgemini, Flexiple)
                            is_excluded, exc_reason = is_company_excluded(company)
                            if not is_excluded:
                                is_excluded, exc_reason = is_company_excluded(title)
                            if is_excluded:
                                log.debug("Skipping excluded company role '%s' at '%s': %s", title, company, exc_reason)
                                continue

                            loc_el = card.find("div", {"data-testid": "text-location"}) or card.find(class_="companyLocation")
                            loc_str = loc_el.text.strip() if loc_el else location

                            # 3. Role relevance filter (Backend, Java, Golang, Spring Boot, 0-3 YOE)
                            role_ok, role_reason = is_role_relevant_for_backend(title)
                            if not role_ok:
                                log.debug("Skipping non-matching Indeed role '%s': %s", title, role_reason)
                                continue

                            # 4. Location check
                            if not _location_ok(loc_str, accept_locs, reject_locs):
                                log.debug("Skipping out-of-bounds location '%s' for '%s'", loc_str, title)
                                continue

                            # 5. Experience guardrail check (must strictly be <= 3 YOE)
                            card_text = card.get_text(separator=" ", strip=True)
                            over_exp, exp_reason = check_experience_exceeds(card_text, max_years=3)
                            if over_exp:
                                log.debug("Skipping Indeed role with >3 YOE (%s): '%s'", exp_reason, title)
                                continue

                            # 6. Snippet / Salary
                            snippet_el = card.find("div", class_="job-snippet") or card.find("ul")
                            snippet = snippet_el.text.strip() if snippet_el else ""

                            salary_el = card.find("div", {"data-testid": "attribute_snippet_testid"}) or card.find(class_="salary-snippet-container")
                            salary = salary_el.text.strip() if salary_el else None

                            now_iso = datetime.now(timezone.utc).isoformat()
                            all_jobs.append({
                                "url": job_url,
                                "title": title,
                                "company": company,
                                "location": loc_str,
                                "salary": salary,
                                "description": snippet,
                                "site": company,
                                "strategy": "indeed_incognito",
                                "discovered_at": now_iso,
                                "date_posted": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                                "is_easy_apply": 0,
                                "num_applicants": 25,
                            })
                        except Exception as card_err:
                            log.debug("Error parsing Indeed card: %s", card_err)

            browser.close()
    except Exception as e:
        log.error("Fatal error during Indeed incognito scrape: %s", e)
        return {"status": "error", "message": str(e), "total_found": len(all_jobs), "new_jobs_added": 0}

    # Store discovered jobs in DB
    conn = get_connection()
    new_count = 0
    dupe_count = 0
    cross_dupe_count = 0

    for job in all_jobs:
        n, e, c = store_jobs_deduped(conn, [job], job["site"], job["strategy"])
        new_count += n
        dupe_count += e
        cross_dupe_count += c

    log.info("Indeed Incognito complete: %d found, %d new, %d dupes, %d cross-dupes", len(all_jobs), new_count, dupe_count, cross_dupe_count)
    return {
        "status": "ok",
        "total_scanned": len(seen_links),
        "total_found": len(all_jobs),
        "new_jobs_added": new_count,
        "existing": dupe_count,
        "cross_dupes": cross_dupe_count,
    }
