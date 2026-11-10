"""Gmail Application Response, Online Assessment (OA) & Sentiment Tracker.

Reads emails from Deepak's connected Gmail account (deepakshkarkala@gmail.com),
classifies responses into:
  - Online Assessment (OA) & Coding Tests (with strict deadlines / due dates)
  - Selected / Next Steps / Interview Invitations
  - Not Selected / Rejections
  - Direct Application Links / Referral Portal Links
  - Application Acknowledged / Under Review
and syncs them seamlessly into the ApplyPilot review dashboard.
"""

import base64
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from applypilot.database import get_connection

log = logging.getLogger(__name__)


def find_gmail_cli() -> str | None:
    """Find the registered Gmail CLI binary on Windows/Unix."""
    # 1. Standard PATH lookup
    cli = shutil.which("gmail") or shutil.which("gmail.cmd") or shutil.which("gmail.exe")
    if cli and os.path.exists(cli):
        return cli

    # 2. Check Antigravity plugin temp directories on Windows
    temp_dir = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "Temp"
    for candidate in temp_dir.glob("agy-plugin-cli-*/gmail.cmd"):
        if candidate.exists():
            return str(candidate)

    # 3. Check ~/.gemini/antigravity/bin
    default_bin = Path(os.environ.get("USERPROFILE", "")) / ".gemini" / "antigravity" / "bin" / "gmail.cmd"
    if default_bin.exists():
        return str(default_bin)

    return None


def init_email_responses_table() -> None:
    """Ensure application_responses table exists in database with all required columns."""
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
            synced_at      TEXT,
            category       TEXT DEFAULT 'acknowledged',
            due_date       TEXT DEFAULT '',
            is_completed   INTEGER DEFAULT 0,
            action_type    TEXT DEFAULT ''
        )
    """)

    # Safe migration of new columns
    new_cols = [
        ("category", "TEXT DEFAULT 'acknowledged'"),
        ("due_date", "TEXT DEFAULT ''"),
        ("is_completed", "INTEGER DEFAULT 0"),
        ("action_type", "TEXT DEFAULT ''"),
    ]
    for col_name, col_def in new_cols:
        try:
            conn.execute(f"ALTER TABLE application_responses ADD COLUMN {col_name} {col_def}")
        except Exception:
            pass  # Already exists

    conn.commit()


def extract_company_from_email(from_header: str, subject: str, body: str) -> str:
    """Extract clean company name from email headers or content."""
    combined = f"{from_header} {subject}"

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

    domain_match = re.search(r"@(?:[a-zA-Z0-9-]+\.)*([a-zA-Z0-9-]+)\.[a-zA-Z]{2,}", from_header)
    if domain_match:
        dom = domain_match.group(1).capitalize()
        if dom.lower() not in ("gmail", "google", "outlook", "yahoo", "greenhouse", "lever", "myworkday", "smartrecruiters", "ashbyhq"):
            return dom

    sender_name = from_header.split("<")[0].strip().replace('"', '')
    if sender_name and len(sender_name) < 25 and not any(w in sender_name.lower() for w in ["noreply", "donotreply", "no-reply"]):
        return sender_name

    return "Employer"


def extract_due_date(text: str) -> str:
    """Extract deadline or due date for Online Assessments or time-sensitive application actions."""
    patterns = [
        # Explicit deadline patterns: "deadline to Monday, 9 November, 11:59 pm IST", "deadline is Nov 15"
        r"(?:deadline(?:\s+is|\s+extended\s+to|\s+to|\s+until|:)?|complete(?:d)?\s+by|valid\s+until|due(?:\s+date)?(?:\s+is|\s+by|:)?|expires?\s+on|finish\s+by)\s+([A-Za-z]+,?\s+\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+(?:\s+\d{4})?(?:,?\s+\d{1,2}(?::\d{2})?\s*(?:am|pm|ist|gmt|utc)?)?)",
        # Relative time window: "complete within 48 hours", "within 3 days"
        r"(?:complete|submit|take)\s+(?:within|in)\s+(\d+\s+(?:hours?|hrs?|days?|business\s+days?))",
        r"within\s+(\d+\s+(?:hours?|hrs?|days?|business\s+days?))",
        # Date slash format: "before 25/11/2026", "by 15/11/2026"
        r"(?:by|before)\s+([0-9]{1,2}/[0-9]{1,2}/[0-9]{2,4})",
        # "before Nov 18, 2026", "by Friday, Nov 13"
        r"(?:by|before)\s+([A-Za-z]+,?\s+\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+(?:\s+\d{4})?(?:,?\s+\d{1,2}(?::\d{2})?\s*(?:am|pm|ist|gmt|utc)?)?)",
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            val = m.group(1).strip()
            if len(val) > 3 and val.lower() not in ("this", "that", "our", "your", "the", "next", "some"):
                return val
    return ""


def classify_email(subject: str, body: str) -> dict[str, Any]:
    """Classify email into detailed categories: OA, Selected/Interview, Rejected, Apply Link, or Acknowledged."""
    combined = f"{subject}\n{body}"
    text_lower = combined.lower()

    # 1. Online Assessment (OA) / Coding Challenge / Technical Test
    oa_triggers = [
        "assessment", "take home", "test link", "coding challenge", "hackerrank", "codility",
        "online assessment", "online test", "technical test", "oa", "byteboard", "mettl",
        "hirevue", "codesignal", "karat", "talentsprint", "exam", "coding test"
    ]
    is_oa = any(w in text_lower for w in oa_triggers)
    if is_oa and not any(neg in text_lower for neg in ["unfortunately", "not moving forward", "regret to inform"]):
        action_match = re.search(
            r"https?://[^\s<>\"']*(?:form|hackerrank|codility|mettl|hirevue|codesignal|karat|byteboard|test|assessment|interviewing\.io)[^\s<>\"']*",
            body
        )
        action_url = action_match.group(0) if action_match else ""
        due_date = extract_due_date(combined)
        summary = "Coding Assessment / Online Test invitation received."
        if due_date:
            summary += f" Action required before {due_date}."

        return {
            "category": "oa",
            "sentiment": "positive",
            "status": "Online Assessment (Action Required)",
            "summary": summary,
            "due_date": due_date,
            "action_url": action_url,
            "action_type": "open_oa" if action_url else "none",
        }

    # 2. Selected / Interview Invitation / Offer / Next Steps
    interview_triggers = [
        "congratulations", "pleased to invite", "selected for", "shortlisted for",
        "invitation to interview", "interview invitation", "schedule an interview",
        "schedule a discussion", "speak with our team", "round 1", "round 2",
        "technical interview", "hiring manager interview", "offer letter", "formal offer",
        "delighted to offer", "schedule a call", "next step in the process"
    ]
    is_interview = any(w in text_lower for w in interview_triggers)
    if is_interview and not any(neg in text_lower for neg in ["unfortunately", "not moving forward"]):
        action_match = re.search(
            r"https?://[^\s<>\"']*(?:calendly|calendar|chili-piper|savvycal|goodtime|meet\.google|zoom\.us|teams\.microsoft|interview)[^\s<>\"']*",
            body
        )
        action_url = action_match.group(0) if action_match else ""
        due_date = extract_due_date(combined)
        return {
            "category": "interview_selected",
            "sentiment": "positive",
            "status": "Interview / Discussion (Action Required)",
            "summary": "Shortlisted for interview / Next technical discussion round.",
            "due_date": due_date,
            "action_url": action_url,
            "action_type": "schedule_interview" if action_url else "none",
        }

    # 3. Not Selected / Application Rejection
    negative_triggers = [
        "unfortunately", "not moving forward", "regret to inform",
        "pursuing other candidates", "decided not to proceed",
        "will not be moving forward", "other applicants who more closely",
        "not selected at this time", "position has been filled", "unable to offer",
        "decided to close", "application was not successful", "not a match at this time"
    ]
    for w in negative_triggers:
        if w in text_lower:
            portal_match = re.search(r"https?://[^\s<>\"']*(?:careers|jobs|workday)[^\s<>\"']*", body)
            portal_url = portal_match.group(0) if portal_match else ""
            return {
                "category": "rejected",
                "sentiment": "negative",
                "status": "Not Selected / Rejected",
                "summary": f"Application update: {w}.",
                "due_date": "",
                "action_url": portal_url,
                "action_type": "portal" if portal_url else "none",
            }

    # 4. Direct Application Link / Invitation to Apply / Referral Link
    apply_link_triggers = [
        "apply here", "application link", "apply online", "complete your application",
        "link to apply", "submit your application", "apply at:", "referral application link",
        "open application", "job link", "complete your submission"
    ]
    is_apply_link = any(w in text_lower for w in apply_link_triggers)
    if is_apply_link:
        portal_match = re.search(
            r"https?://[^\s<>\"']*(?:greenhouse|lever|myworkdayjobs|smartrecruiters|ashbyhq|careers|jobs|apply|forms\.gle)[^\s<>\"']*",
            body
        )
        if portal_match:
            due_date = extract_due_date(combined)
            return {
                "category": "apply_link",
                "sentiment": "positive",
                "status": "Direct Apply Link Available",
                "summary": "Application or referral link provided to complete submission.",
                "due_date": due_date,
                "action_url": portal_match.group(0),
                "action_type": "apply_link",
            }

    # 5. Default: Application Acknowledged / Under Review
    return {
        "category": "acknowledged",
        "sentiment": "neutral",
        "status": "Application Acknowledged",
        "summary": "Application successfully received and under review.",
        "due_date": "",
        "action_url": "",
        "action_type": "none",
    }


def classify_email_sentiment(subject: str, body: str) -> tuple[str, str, str]:
    """Backward compatibility wrapper returning (sentiment, status, summary)."""
    res = classify_email(subject, body)
    return res["sentiment"], res["status"], res["summary"]


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


def sync_gmail_job_responses(max_results: int = 20) -> list[dict[str, Any]]:
    """Query Gmail for recent job application emails, classify them, and update SQLite."""
    init_email_responses_table()

    gmail_bin = find_gmail_cli()
    if not gmail_bin:
        log.warning("Gmail CLI binary not found on system. Returning cached responses.")
        return get_cached_responses()

    query = 'subject:(application OR interview OR assessment OR "next step" OR "offer" OR "regret" OR "status" OR "thank you for applying" OR "coding challenge" OR "hackerrank" OR "codility")'
    cmd = [gmail_bin, "readonly", "read", query, "--max", str(max_results), "--json"]

    log.info("Querying Gmail CLI for application responses: %s", " ".join(cmd))
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", shell=True)
        if res.returncode != 0:
            log.warning("Gmail CLI returned code %d: %s (serving cached database responses)", res.returncode, res.stderr.strip())
            return get_cached_responses()

        out = res.stdout.strip()
        if not out.startswith("["):
            log.info("No JSON response list returned by Gmail CLI.")
            return get_cached_responses()

        messages = json.loads(out)
    except Exception as e:
        log.error("Failed to execute Gmail CLI: %s", e)
        return get_cached_responses()

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
        classification = classify_email(subject, full_body)

        category = classification["category"]
        sentiment = classification["sentiment"]
        status = classification["status"]
        summary = classification["summary"]
        due_date = classification["due_date"]
        action_url = classification["action_url"]
        action_type = classification["action_type"]

        # Extract role if present in subject
        role_match = re.search(r"(?:for|position:?|role:?)\s+([A-Za-z0-9\s/+-]{3,35}\b(?:engineer|developer|sde|role|position))", subject, re.IGNORECASE)
        role_title = role_match.group(1).strip() if role_match else "Software Engineer"

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
            "body_snippet": snippet[:220],
            "action_url": action_url,
            "synced_at": now,
            "category": category,
            "due_date": due_date,
            "is_completed": 0,
            "action_type": action_type
        }

        # Insert or update in database (preserving existing is_completed status if present)
        c.execute("""
            INSERT INTO application_responses 
            (message_id, company, role_title, sender, subject, received_date, sentiment, status, summary, body_snippet, action_url, synced_at, category, due_date, is_completed, action_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
            ON CONFLICT(message_id) DO UPDATE SET
                company = excluded.company,
                role_title = excluded.role_title,
                sender = excluded.sender,
                subject = excluded.subject,
                received_date = excluded.received_date,
                sentiment = excluded.sentiment,
                status = excluded.status,
                summary = excluded.summary,
                body_snippet = excluded.body_snippet,
                action_url = CASE WHEN excluded.action_url != '' THEN excluded.action_url ELSE application_responses.action_url END,
                synced_at = excluded.synced_at,
                category = excluded.category,
                due_date = CASE WHEN excluded.due_date != '' THEN excluded.due_date ELSE application_responses.due_date END,
                action_type = excluded.action_type
        """, (
            msg_id, company, role_title, from_hdr, subject, date_hdr, sentiment, status, summary, snippet[:220], action_url, now, category, due_date, action_type
        ))

        # Update matching jobs status
        if category in ("oa", "interview_selected"):
            c.execute("UPDATE jobs SET apply_status = 'interview' WHERE site LIKE ? OR url LIKE ?", (f"%{company}%", f"%{company.lower()}%"))
        elif category == "rejected":
            c.execute("UPDATE jobs SET apply_status = 'rejected' WHERE site LIKE ? OR url LIKE ?", (f"%{company}%", f"%{company.lower()}%"))

        results.append(entry)

    conn.commit()
    log.info("Synced %d job application responses from Gmail.", len(results))
    return get_cached_responses()


def get_cached_responses(category_filter: str | None = None) -> list[dict[str, Any]]:
    """Retrieve already saved responses from database with all metadata."""
    init_email_responses_table()
    conn = get_connection()
    c = conn.cursor()

    if category_filter:
        rows = c.execute("""
            SELECT message_id, company, role_title, sender, subject, received_date, sentiment, status, summary, body_snippet, action_url, synced_at, category, due_date, is_completed, action_type
            FROM application_responses
            WHERE category = ?
            ORDER BY rowid DESC
        """, (category_filter,)).fetchall()
    else:
        rows = c.execute("""
            SELECT message_id, company, role_title, sender, subject, received_date, sentiment, status, summary, body_snippet, action_url, synced_at, category, due_date, is_completed, action_type
            FROM application_responses
            ORDER BY rowid DESC
        """).fetchall()

    cols = [d[0] for d in c.description]
    return [dict(zip(cols, r)) for r in rows]


def toggle_response_completed(message_id: str) -> bool:
    """Toggle completed flag on an OA or application task."""
    init_email_responses_table()
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        UPDATE application_responses
        SET is_completed = CASE WHEN is_completed = 1 THEN 0 ELSE 1 END
        WHERE message_id = ?
    """, (message_id,))
    conn.commit()
    return c.rowcount > 0
