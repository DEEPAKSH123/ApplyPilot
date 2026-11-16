"""Telegram Tech Channels & Community Hiring Discovery.

Scrapes public Indian tech channels, SDE communities, and off-campus referral broadcasts:
- Placement Lelo (@placementlelo)
- OffCampusJobs4u (@offcampusjobs4u)
- Tech Jobs India (@techjobs_india)
- Freshershunt (@freshershunt)
- Campus Ambassador Referral Info (@campus_ambassador)
- IEMDaily / Off Campus Updates (@Jobs_Internships_Updates)

Filters strictly for Software Engineer / Backend Developer roles (0-3 YOE),
extracts recruiter emails, direct requisition URLs, and stores them deduped in SQLite.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from applypilot.apply.assistant import get_browser_executable
from applypilot.config import APP_DIR, load_search_config
from applypilot.database import get_connection, store_jobs_deduped
from applypilot.discovery.whatsapp import is_job_relevant_to_deepak
from applypilot.enrichment.email_extractor import extract_emails_from_text

log = logging.getLogger(__name__)

URL_REGEX = re.compile(r'https?://[^\s<>"]+')

DEFAULT_TELEGRAM_CHANNELS = [
    "placementlelo",
    "offcampusjobs4u",
    "techjobs_india",
    "freshershunt",
    "campus_ambassador",
    "Jobs_Internships_Updates",
]


def parse_telegram_message(msg_elem, channel_name: str) -> dict | None:
    """Parse an individual Telegram message element into a structured job posting."""
    text_elem = msg_elem.find("div", class_="tgme_widget_message_text")
    if not text_elem:
        return None

    raw_text = text_elem.get_text("\n", strip=True)
    if not raw_text or len(raw_text) < 25:
        return None

    # Check date
    date_elem = msg_elem.find("time", class_="time")
    msg_date = date_elem.get("datetime") if date_elem else datetime.now(timezone.utc).isoformat()

    # Check post url
    link_elem = msg_elem.find("a", class_="tgme_widget_message_date")
    post_url = link_elem.get("href") if link_elem else f"https://t.me/s/{channel_name}"

    # Extract company and role
    company = "Tech Firm"
    title = "Software Engineer"

    # 1. Company extraction
    comp_m = re.search(r"(?:Company\s*Name|Company|Organization)\s*:\s*([^\n\r,]+)", raw_text, re.IGNORECASE)
    if comp_m:
        company = comp_m.group(1).strip()
    else:
        hiring_m = re.search(r"^([A-Z][A-Za-z0-9&.\s]{1,25})\s+(?:is\s+)?hiring\s+([^\n\r,]+)", raw_text, re.IGNORECASE | re.MULTILINE)
        if hiring_m:
            company = hiring_m.group(1).strip()
            title = hiring_m.group(2).strip()
        else:
            recruit_m = re.search(r"^([A-Z][A-Za-z0-9&.\s]{1,25})\s+(?:Recruitment|Off\s*Campus|Careers|Hiring)", raw_text, re.MULTILINE)
            if recruit_m:
                company = recruit_m.group(1).strip()

    # 2. Role extraction
    role_m = re.search(r"(?:Role|Position|Job\s*Title|Designation)\s*:\s*([^\n\r,]+)", raw_text, re.IGNORECASE)
    if role_m:
        title = role_m.group(1).strip()
    elif title == "Software Engineer":
        title_match = re.search(r"\b(sde[- ]?[123iI]+|software engineer|backend engineer|golang developer|java developer|associate software engineer)\b", raw_text, re.IGNORECASE)
        if title_match:
            title = title_match.group(1).title()

    # Clean titles
    title = re.sub(r"^(?:Recruitment\s*20\d\d|Off\s*Campus)\s*[-:]\s*", "", title, flags=re.IGNORECASE).strip()
    title = title.rstrip(" :-\t")

    # 3. Relevance gating for Deepak (SDE-1 Backend @ Meesho, Java/Go, RVCE '25)
    if not is_job_relevant_to_deepak(title, raw_text):
        return None

    # 4. Extract URLs (exclude internal t.me links)
    urls = [u for u in URL_REGEX.findall(raw_text) if "t.me" not in u.lower()]
    apply_url = urls[0] if urls else post_url

    # Clean known company portal URLs
    u_lower = apply_url.lower()
    c_lower = company.lower()
    if "razorpay" in u_lower or "razorpay" in c_lower:
        if "greenhouse.io" not in u_lower:
            apply_url = "https://job-boards.greenhouse.io/razorpaysoftwareprivatelimited"
    elif "phonepe" in u_lower or "phonepe" in c_lower:
        if "sde1" in u_lower or u_lower.rstrip("/").endswith("/careers"):
            apply_url = "https://jobs.smartrecruiters.com/PhonePeLimited/1000000000003895"

    # 5. Extract Emails
    emails = extract_emails_from_text(raw_text)
    email_str = ", ".join(emails) if emails else ""

    # Generate unique hash for deduplication
    msg_hash = hashlib.md5(f"{company}_{title}_{msg_date}_{raw_text[:50]}".encode()).hexdigest()[:12]
    unique_url = apply_url if apply_url != post_url else f"https://telegram.me/{channel_name}/{msg_hash}"

    return {
        "url": unique_url,
        "title": title,
        "site": company if company != "Tech Firm" else f"Telegram ({channel_name})",
        "location": "Bengaluru / India (Telegram Tech Channel)",
        "description": raw_text[:500],
        "full_description": f"Channel: @{channel_name} | Post Link: {post_url}\n\n{raw_text}",
        "strategy": "telegram_channel",
        "recruiter_email": email_str,
        "application_url": apply_url,
        "discovered_at": msg_date,
    }


def scrape_telegram_channels(channels: list[str] | None = None) -> list[dict]:
    """Scrape public Telegram channel web previews using Playwright to bypass ISP DNS/socket blocks."""
    if not channels:
        cfg = load_search_config()
        channels = cfg.get("telegram_channels", DEFAULT_TELEGRAM_CHANNELS)

    exe_path, _ = get_browser_executable()
    all_jobs: list[dict] = []

    log.info("Starting Telegram channel discovery for %d channels: %s", len(channels), channels)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                executable_path=exe_path if exe_path else None,
                headless=True,
                args=["--disable-blink-features=AutomationControlled"]
            )
            page = browser.new_page()

            for ch in channels:
                channel_clean = ch.lstrip("@").strip()
                url = f"https://t.me/s/{channel_clean}"
                try:
                    log.info("Scanning Telegram channel: @%s...", channel_clean)
                    page.goto(url, timeout=25000, wait_until="domcontentloaded")
                    html = page.content()

                    soup = BeautifulSoup(html, "html.parser")
                    msgs = soup.find_all("div", class_="tgme_widget_message_wrap")

                    found_in_channel = 0
                    for m in msgs:
                        job = parse_telegram_message(m, channel_clean)
                        if job:
                            all_jobs.append(job)
                            found_in_channel += 1

                    log.info("Parsed %d relevant SDE opportunities from @%s (out of %d messages)", found_in_channel, channel_clean, len(msgs))
                except Exception as ce:
                    log.warning("Failed to scrape Telegram channel @%s: %s", channel_clean, ce)

            browser.close()
    except Exception as e:
        log.warning("Telegram channel scraper encountered: %s", e)

    return all_jobs


def run_discovery(channels: list[str] | None = None) -> int:
    """Main discovery runner for Telegram tech channel opportunities."""
    log.info("Running Telegram Tech Channels discovery...")
    jobs = scrape_telegram_channels(channels=channels)
    if not jobs:
        log.info("No new Telegram opportunities found.")
        return 0

    conn = get_connection()
    count, _, _ = store_jobs_deduped(conn, jobs, site="Telegram Lead", strategy="telegram_channel")
    log.info("Ingested %d opportunities from Telegram tech channels.", count)
    return count
