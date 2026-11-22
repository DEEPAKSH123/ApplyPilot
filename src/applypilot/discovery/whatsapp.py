"""WhatsApp Community & Group Job Ingestion.

Parses WhatsApp group chat exports and live WhatsApp Web messages from Indian tech
communities, alumni channels (e.g. RVCE / Bangalore SDE groups), and broadcast channels:
- "Let's Code"
- "TechFresher/Experienced Job"
- "Factz and Code"

Includes smart relevance gating to reject support, hardware/silicon, and non-backend roles,
while extracting legitimate software/backend engineering opportunities for Deepak.
"""

import hashlib
import logging
import os
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

from applypilot.apply.chrome import open_isolated_context, acquire_browser_lock, launch_isolated_playwright_context
from applypilot.config import APP_DIR, load_search_config, PLAYWRIGHT_PROFILE_DIR

log = logging.getLogger(__name__)

WHATSAPP_DIR = APP_DIR / "whatsapp_imports"

# Regex for WhatsApp message headers
# Android: "05/11/24, 14:32 - Sender Name: Message"
# iOS: "[05/11/24, 2:32:15 PM] Sender Name: Message"
WA_MSG_REGEX = re.compile(
    r'^(?:\[?(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}),?\s+(\d{1,2}:\d{2}(?::\d{2})?(?:\s*[AaPp][Mm])?)\]?(?:\s*-\s*)?)([^:]+):\s+(.*)$'
)

# URL extractor
URL_REGEX = re.compile(r'https?://[^\s<>"]+')

# Strict rejection patterns (NOT applicable to Deepak S H)
REJECT_PATTERNS = [
    re.compile(r"\b(?:associate\s+)?support\b", re.IGNORECASE),
    re.compile(r"\btech(?:nical)?\s+support\b", re.IGNORECASE),
    re.compile(r"\bcustomer\s+(?:support|care|service)\b", re.IGNORECASE),
    re.compile(r"\bsilicon\b", re.IGNORECASE),
    re.compile(r"\bhardware\b", re.IGNORECASE),
    re.compile(r"\bvlsi\b", re.IGNORECASE),
    re.compile(r"\bembedded\b", re.IGNORECASE),
    re.compile(r"\bfirmware\b", re.IGNORECASE),
    re.compile(r"\b(?:manual\s+)?qa\b|\btester\b|\btest\s+engineer\b", re.IGNORECASE),
    re.compile(r"\bdata\s+entry\b|\bbpo\b|\btelecaller\b|\bsales\b|\bmarketing\b", re.IGNORECASE),
    re.compile(r"\b(?:2026|2027)\s*(?:batch|graduate|grad|passout)\b", re.IGNORECASE),
]

# Strict acceptance patterns (Applicable Software / Backend Engineering)
ACCEPT_PATTERNS = [
    re.compile(r"\bbackend\b", re.IGNORECASE),
    re.compile(r"\bsde[- ]?[123iI]*\b", re.IGNORECASE),
    re.compile(r"\bsoftware\s+engineer\b", re.IGNORECASE),
    re.compile(r"\bsoftware\s+developer\b", re.IGNORECASE),
    re.compile(r"\bjava\b", re.IGNORECASE),
    re.compile(r"\bgolang\b|\bgo\s+developer\b", re.IGNORECASE),
    re.compile(r"\bdistributed\s+systems\b", re.IGNORECASE),
    re.compile(r"\bmicroservices\b", re.IGNORECASE),
    re.compile(r"\bspring\s+boot\b", re.IGNORECASE),
    re.compile(r"\bapi\s+developer\b", re.IGNORECASE),
    re.compile(r"\bfull[- ]?stack\b", re.IGNORECASE),
    re.compile(r"\bcloud\s+engineer\b", re.IGNORECASE),
]


def is_job_relevant_to_deepak(title: str, text: str) -> bool:
    """Strict relevance check for Deepak (SDE-1 Backend @ Meesho, Java/Go, RVCE '25)."""
    combined = f"{title}\n{text}"

    # 1. If matches any reject pattern -> NOT RELEVANT
    for rp in REJECT_PATTERNS:
        if rp.search(title) or (rp.search(text) and "software" not in text.lower() and "backend" not in text.lower()):
            log.debug("Skipping message matching reject pattern %s: title=%s", rp.pattern, title)
            return False

    # 2. Must match at least one software/backend trigger
    for ap in ACCEPT_PATTERNS:
        if ap.search(title) or ap.search(text):
            return True

    return False


def parse_whatsapp_chat_export(content: str, group_name: str = "WhatsApp Tech Community") -> list[dict]:
    """Parse raw text from a WhatsApp chat export or live channel into structured job postings."""
    lines = content.split("\n")
    messages = []
    current_msg = None

    for line in lines:
        line_clean = line.strip()
        m = WA_MSG_REGEX.match(line_clean)
        if m:
            if current_msg:
                messages.append(current_msg)
            date_str, time_str, sender, text = m.groups()
            current_msg = {
                "date": f"{date_str} {time_str}",
                "sender": sender.strip(),
                "text": text.strip()
            }
        else:
            if current_msg and line_clean:
                current_msg["text"] += "\n" + line_clean

    if current_msg:
        messages.append(current_msg)

    jobs = []
    for msg in messages:
        text = msg["text"]

        # Parse structured Indian channel format:
        # "Company Name: Clinisys \n Role: Associate Support"
        # "Google University Graduate, 2026 Position: Silicon..."
        company = "Tech Firm"
        title = "SDE Backend Engineer"

        # 1. Check structured "Company Name:" / "Company:"
        comp_m = re.search(r"(?:Company\s*Name|Company|Organization)\s*:\s*([^\n\r,]+)", text, re.IGNORECASE)
        if comp_m:
            company = comp_m.group(1).strip()
        else:
            comp_match = re.search(r"(?:at|@|join)\s+([A-Z][A-Za-z0-9]{2,20})\b", text)
            if comp_match:
                cand = comp_match.group(1)
                if cand.lower() not in ("we", "our", "urgent", "immediate", "remote", "bangalore", "india", "team"):
                    company = cand

        # 2. Check structured "Role:" / "Position:" / "Job Title:"
        role_m = re.search(r"(?:Role|Position|Job\s*Title|Designation)\s*:\s*([^\n\r,]+)", text, re.IGNORECASE)
        if role_m:
            title = role_m.group(1).strip()
        else:
            title_match = re.search(r"\b(sde[- ]?[123iI]+|software engineer|backend engineer|golang developer|java developer|systems engineer)\b", text, re.IGNORECASE)
            if title_match:
                title = title_match.group(1).title()

        # 3. Deepak Relevance Gating
        if not is_job_relevant_to_deepak(title, text):
            continue

        # Extract URLs
        urls = URL_REGEX.findall(text)
        apply_url = urls[0] if urls else ""
        if apply_url:
            u_lower = apply_url.lower()
            c_lower = company.lower()
            if "razorpay" in u_lower or "razorpay" in c_lower:
                if "greenhouse.io" not in u_lower:
                    apply_url = "https://job-boards.greenhouse.io/razorpaysoftwareprivatelimited"
            elif "phonepe" in u_lower or "phonepe" in c_lower:
                if "sde1" in u_lower or u_lower.rstrip("/").endswith("/careers"):
                    apply_url = "https://jobs.smartrecruiters.com/PhonePeLimited/1000000000003895"

        # Extract Emails
        emails = extract_emails_from_text(text)
        email_str = ", ".join(emails) if emails else ""

        # Generate unique hash for deduplication
        msg_hash = hashlib.md5(f"{company}_{title}_{msg['date']}_{text[:50]}".encode()).hexdigest()[:12]
        unique_url = apply_url or f"https://whatsapp.community/referral/{msg_hash}"

        jobs.append({
            "url": unique_url,
            "title": title,
            "site": f"WhatsApp ({group_name})",
            "company": company,
            "location": "Bengaluru / India (Tech Community)",
            "description": text[:500],
            "full_description": f"Channel: {group_name} | Posted by {msg['sender']}:\n\n{text}",
            "strategy": "whatsapp_community",
            "recruiter_email": email_str,
            "application_url": apply_url or unique_url,
            "discovered_at": datetime.now(timezone.utc).isoformat(),
        })

    return jobs


def ingest_whatsapp_folder() -> int:
    """Scan D:\\ApplyPilot_Workspace\\data\\whatsapp_imports for exported chat files."""
    if not WHATSAPP_DIR.exists():
        WHATSAPP_DIR.mkdir(parents=True, exist_ok=True)
        return 0

    txt_files = list(WHATSAPP_DIR.glob("*.txt"))
    if not txt_files:
        return 0

    all_jobs = []
    for f in txt_files:
        try:
            content = f.read_text(encoding="utf-8")
            parsed = parse_whatsapp_chat_export(content, group_name=f.stem)
            all_jobs.extend(parsed)
        except Exception as e:
            log.warning("Error reading WhatsApp export %s: %s", f.name, e)

    if all_jobs:
        conn = get_connection()
        count, _, _ = store_jobs_deduped(conn, all_jobs, site="WhatsApp Referral", strategy="whatsapp_community")
        log.info("Ingested %d opportunities from WhatsApp community exports.", count)
        return count
    return 0


def scrape_live_whatsapp_web(target_groups: list[str] | None = None, wait_timeout_sec: int = 40, headless: bool = True) -> int:
    """Connect to WhatsApp Web using isolated browser factory."""
    from playwright.sync_api import sync_playwright

    log.info("Connecting to WhatsApp Web to discover tech referral opportunities...")
    new_jobs_total = 0

    search_queries = [
        "referral",
        "sde",
        "backend",
        "engineer",
        "hiring",
        "java",
        "golang",
        "kadegree"
    ]

    try:
        with acquire_browser_lock():
            with sync_playwright() as p:
                context = launch_isolated_playwright_context(
                    p,
                    headless=True,
                )
                wa_page = context.pages[0] if context.pages else context.new_page()
                wa_page.goto("https://web.whatsapp.com/", wait_until="domcontentloaded", timeout=45000)

            # Wait for search box or chat pane
            try:
                wa_page.wait_for_selector("input[role='textbox'], div[contenteditable='true']", timeout=15000)
            except Exception:
                log.warning("WhatsApp Web search box not ready or requires QR code.")
                if context:
                    context.close()
                return 0

            all_found = []
            seen_snippets = set()

            # Iterate through tech keywords
            for q in search_queries:
                try:
                    search_box = wa_page.query_selector("input[role='textbox'], div[contenteditable='true']")
                    if not search_box:
                        continue

                    search_box.click()
                    search_box.fill(q)
                    time.sleep(2.5)

                    # Get matched message and chat rows
                    rows = wa_page.query_selector_all("div[role='listitem'], div[role='row']")
                    for r in rows[:6]:
                        try:
                            # Avoid clicking unrelated contacts
                            row_txt = r.inner_text().strip()
                            if not row_txt or len(row_txt) < 10:
                                continue

                            # Skip obvious banking / family / personal chats
                            lower_txt = row_txt.lower()
                            if any(k in lower_txt for k in ["axis bank", "reserve bank", "cibil", "family", "neighbours"]):
                                continue

                            r.click()
                            time.sleep(1.5)

                            # Extract visible chat bubbles
                            bubbles = wa_page.query_selector_all("div.message-in, div.copyable-text")
                            raw_texts = []
                            for b in bubbles[-15:]:
                                t = b.inner_text().strip()
                                if t and t not in seen_snippets:
                                    seen_snippets.add(t)
                                    raw_texts.append(t)

                            if raw_texts:
                                fake_chat = "\n".join([f"10/11/26, 12:00 - WhatsApp Lead: {m}" for m in raw_texts])
                                parsed = parse_whatsapp_chat_export(fake_chat, group_name="WhatsApp Live Referral")
                                all_found.extend(parsed)
                        except Exception:
                            continue

                    # Clear search box for next query
                    search_box.fill("")
                    wa_page.keyboard.press("Escape")
                    time.sleep(0.5)

                except Exception as q_err:
                    log.debug("Error querying %s on WhatsApp Web: %s", q, q_err)

            if all_found:
                conn = get_connection()
                new_jobs_total, _, _ = store_jobs_deduped(conn, all_found, site="WhatsApp Referral", strategy="whatsapp_community")
                log.info("Saved %d new opportunities from live WhatsApp Web.", new_jobs_total)

            if context:
                context.close()
    except Exception as e:
        log.warning("WhatsApp Web live scraping encountered: %s", e)

    return new_jobs_total


def run_discovery() -> int:
    """Main discovery runner for WhatsApp community referrals."""
    log.info("Running WhatsApp Communities discovery...")
    folder_count = ingest_whatsapp_folder()
    return folder_count
