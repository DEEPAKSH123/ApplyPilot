"""WhatsApp Community & Group Job Ingestion.

Parses WhatsApp group chat exports and live WhatsApp Web messages from Indian tech
communities, alumni channels (e.g. RVCE / Bangalore SDE groups), and referral networks.
Extracts recruiter emails, referral links, role details, and stores them in the pipeline.
"""

import hashlib
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from applypilot.config import APP_DIR
from applypilot.database import get_connection, store_jobs_deduped
from applypilot.enrichment.email_extractor import extract_emails_from_text

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


def parse_whatsapp_chat_export(content: str, group_name: str = "WhatsApp Tech Community") -> list[dict]:
    """Parse raw text from a WhatsApp chat export into structured job postings."""
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

    # Filter messages for hiring/job content
    hiring_triggers = ("hiring", "referral", "opening", "openings", "vacancy", "vacancies", "job", "sde", "backend")
    tech_triggers = ("java", "golang", "go ", "python", "backend", "sde", "engineer", "developer", "microservices")

    jobs = []
    for msg in messages:
        text = msg["text"]
        text_lower = text.lower()

        if not any(h in text_lower for h in hiring_triggers) or not any(t in text_lower for t in tech_triggers):
            continue

        # Extract URLs (Google forms, Lever, Greenhouse, wa.me, etc.)
        urls = URL_REGEX.findall(text)
        apply_url = urls[0] if urls else ""

        # Extract Emails
        emails = extract_emails_from_text(text)
        email_str = ", ".join(emails) if emails else ""

        # Identify company
        company = "Tech Firm"
        comp_match = re.search(r"(?:at|@|join|company:?)\s+([A-Z][A-Za-z0-9]{2,20})\b", text)
        if comp_match:
            cand = comp_match.group(1)
            if cand.lower() not in ("we", "our", "urgent", "immediate", "remote", "bangalore", "india"):
                company = cand

        # Identify title
        title = "SDE Backend Engineer"
        title_match = re.search(r"\b(sde[- ]?[123iI]+|software engineer|backend engineer|golang developer|java developer)\b", text, re.IGNORECASE)
        if title_match:
            title = title_match.group(1).title()

        # Generate unique hash for deduplication
        msg_hash = hashlib.md5(f"{company}_{title}_{msg['date']}_{text[:50]}".encode()).hexdigest()[:12]
        unique_url = apply_url or f"https://whatsapp.community/referral/{msg_hash}"

        jobs.append({
            "url": unique_url,
            "title": title,
            "site": f"WhatsApp ({group_name})",
            "company": company,
            "location": "Bengaluru / India (Community Referral)",
            "description": text[:500],
            "full_description": f"Posted by {msg['sender']} in {group_name}:\n\n{text}",
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


def run_discovery() -> int:
    """Main discovery runner for WhatsApp community referrals."""
    log.info("Running WhatsApp Communities discovery...")
    return ingest_whatsapp_folder()
