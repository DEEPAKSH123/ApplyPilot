"""Gmail Application Response & Sentiment Tracker.

Reads emails from Deepak's connected Gmail account (deepakshkarkala@gmail.com),
classifies responses from companies (Positive/Next Steps, Acknowledged, Rejected),
and syncs them with the application pipeline and review dashboard.
"""

import base64
import json
import logging
import re
import shutil
import subprocess
from datetime import datetime, timezone
from typing import Any

from applypilot.database import get_connection

log = logging.getLogger(__name__)


def init_email_responses_table() -> None:
    """Ensure application_responses table exists in database."""
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS application_responses (
            message_id     TEXT PRIMARY KEY,
            company        TEXT,
            role_title     TEXT,
            sender         TEXT,
            subject        TEXT,
            received_date  TEXT,
            sentiment      TEXT,
            status         TEXT,
            summary        TEXT,
            body_snippet   TEXT,
            action_url     TEXT,
            synced_at      TEXT
        )
    """)
    conn.commit()


def extract_company_from_email(from_header: str, subject: str, body: str) -> str:
    """Extract clean company name from email headers or content."""
    # Common known patterns
    combined = f"{from_header} {subject}"

    # Check for "at Company", "with Company", "Company Careers", "Company Team"
    patterns = [
        r"(?:at|with)\s+([A-Z][A-Za-z0-9\s]{1,18}?)(?:\s+(?:Careers|Talent|Team|India|Inc|Pvt|Ltd|\.|\!|\?|$))",
        r"([A-Z][A-Za-z0-9]{2,18})\s+(?:Careers|Talent Acquisition|Recruitment|Hiring|Jobs)",
        r"(?:from|to)\s+([A-Z][A-Za-z0-9]{2,18})\s+Recruitment",
    ]
    for p in patterns:
        m = re.search(p, combined)
        if m:
            cand = m.group(1).strip()
            if cand.lower() not in ("team", "the", "your", "our", "software", "backend", "interview", "application"):
                return cand

    # Extract domain from email sender
    domain_match = re.search(r"@(?:[a-zA-Z0-9-]+\.)*([a-zA-Z0-9-]+)\.[a-zA-Z]{2,}", from_header)
    if domain_match:
        dom = domain_match.group(1).capitalize()
        if dom.lower() not in ("gmail", "google", "outlook", "yahoo", "greenhouse", "lever", "myworkday", "smartrecruiters", "ashbyhq"):
            return dom

    # From sender name
    sender_name = from_header.split("<")[0].strip().replace('"', '')
    if sender_name and len(sender_name) < 25 and not any(w in sender_name.lower() for w in ["noreply", "donotreply", "no-reply"]):
        return sender_name

    return "Employer"


def classify_email_sentiment(subject: str, body: str) -> tuple[str, str, str]:
    """Classify email as Positive (Interview/Assessment), Neutral (Received), or Negative (Rejected)."""
    text = f"{subject}\n{body}".lower()

    # 1. Positive Triggers: Interview, Assessment, Next Steps, Offer
    positive_words = [
        "assessment", "take home", "test link", "coding challenge", "interview",
        "schedule a call", "speak with", "shortlisted", "next step", "next round",
        "extend the deadline", "congratulations", "offer", "hackerrank", "codility",
        "invitation to", "technical round"
    ]
    for w in positive_words:
        if w in text:
            # Check if it's an assessment link
            action_match = re.search(r"https?://[^\s<>\"']*(?:form|hackerrank|codility|calendly|hirevue|test|assessment)[^\s<>\"']*", body)
            action_url = action_match.group(0) if action_match else ""
            summary = f"Positive next step: {w.title()}."
            if "assessment" in w or "coding" in w:
                summary = "Coding Assessment / Test invitation received."
            elif "interview" in w or "schedule" in w:
                summary = "Interview scheduling / Discussion invite."
            return "positive", "Interview / Assessment (Action Required)", summary

    # 2. Negative Triggers: Rejection
    negative_words = [
        "unfortunately", "not moving forward", "regret to inform",
        "pursuing other candidates", "decided not to proceed",
        "will not be moving forward", "other applicants who more closely",
        "not selected at this time", "position has been filled", "unable to offer"
    ]
    for w in negative_words:
        if w in text:
            return "negative", "Not Selected / Rejected", f"Application update: {w}."

    # 3. Neutral Triggers: Application Received / Under Review
    return "neutral", "Application Acknowledged", "Application successfully received and under review."


def decode_body_part(part: dict) -> str:
    """Decode base64 encoded email part body."""
    body_data = part.get("body", {}).get("data", "")
    if body_data:
        try:
            return base64.urlsafe_b64decode(body_data + "==").decode("utf-8", errors="ignore")
        except Exception:
            pass
    return ""


def get_full_email_body(payload: dict) -> str:
    """Extract plain text or HTML body from Gmail payload."""
    parts = payload.get("parts", [])
    if not parts:
        return decode_body_part(payload)

    text_content = []
    for p in parts:
        mime = p.get("mimeType", "")
        if mime == "text/plain":
            text_content.append(decode_body_part(p))
        elif mime == "text/html" and not text_content:
            raw_html = decode_body_part(p)
            clean_text = re.sub(r"<[^>]+>", " ", raw_html)
            text_content.append(clean_text)

    return "\n".join(text_content)


def sync_gmail_job_responses(max_results: int = 15) -> list[dict[str, Any]]:
    """Query Gmail for recent job application emails and categorize responses."""
    init_email_responses_table()

    # Search for application updates across inbox
    query = 'subject:(application OR interview OR assessment OR "next step" OR "offer" OR "regret" OR "status" OR "thank you for applying")'
    cmd = ["gmail", "readonly", "read", query, "--max", str(max_results), "--json"]

    log.info("Querying Gmail for job application responses...")
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        if res.returncode != 0:
            log.warning("Gmail CLI returned code %d: %s", res.returncode, res.stderr)
            return []

        out = res.stdout.strip()
        if not out.startswith("["):
            return []

        messages = json.loads(out)
    except Exception as e:
        log.error("Failed to execute Gmail CLI: %s", e)
        return []

    conn = get_connection()
    c = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()
    results = []

    for msg in messages:
        msg_id = msg.get("id")
        if not msg_id:
            continue

        payload = msg.get("payload", {})
        headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}

        subject = headers.get("subject", "No Subject")
        from_hdr = headers.get("from", "Unknown")
        date_hdr = headers.get("date", "")
        snippet = msg.get("snippet", "")
        full_body = get_full_email_body(payload) or snippet

        company = extract_company_from_email(from_hdr, subject, full_body)
        sentiment, status, summary = classify_email_sentiment(subject, full_body)

        # Extract role if present in subject
        role_match = re.search(r"(?:for|position:?|role:?)\s+([A-Za-z0-9\s/+-]{3,35}\b(?:engineer|developer|sde|role|position))", subject, re.IGNORECASE)
        role_title = role_match.group(1).strip() if role_match else "Software Engineer"

        # Action link (e.g. test link or scheduling link)
        action_match = re.search(r"https?://[^\s<>\"']*(?:form|hackerrank|codility|calendly|hirevue|test|assessment)[^\s<>\"']*", full_body)
        action_url = action_match.group(0) if action_match else ""

        entry = {
            "message_id": msg_id,
            "company": company,
            "role_title": role_title,
            "sender": from_hdr,
            "subject": subject,
            "received_date": date_hdr,
            "sentiment": sentiment,
            "status": status,
            "summary": summary,
            "body_snippet": snippet[:200],
            "action_url": action_url,
            "synced_at": now
        }

        # Save to database
        c.execute("""
            INSERT OR REPLACE INTO application_responses 
            (message_id, company, role_title, sender, subject, received_date, sentiment, status, summary, body_snippet, action_url, synced_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            msg_id, company, role_title, from_hdr, subject, date_hdr, sentiment, status, summary, snippet[:200], action_url, now
        ))

        # Also update corresponding job in jobs table if company matches
        if sentiment == "positive":
            c.execute("UPDATE jobs SET apply_status = 'interview' WHERE site LIKE ? OR url LIKE ?", (f"%{company}%", f"%{company.lower()}%"))
        elif sentiment == "negative":
            c.execute("UPDATE jobs SET apply_status = 'rejected' WHERE site LIKE ? OR url LIKE ?", (f"%{company}%", f"%{company.lower()}%"))

        results.append(entry)

    conn.commit()
    log.info("Synced %d job application responses from Gmail.", len(results))
    return results


def get_cached_responses() -> list[dict[str, Any]]:
    """Retrieve already saved responses from database."""
    init_email_responses_table()
    conn = get_connection()
    c = conn.cursor()
    rows = c.execute("""
        SELECT message_id, company, role_title, sender, subject, received_date, sentiment, status, summary, body_snippet, action_url
        FROM application_responses
        ORDER BY rowid DESC
    """).fetchall()
    cols = [d[0] for d in c.description]
    return [dict(zip(cols, r)) for r in rows]
