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


def is_known_outreach_contact(from_header: str, conn: Any = None) -> bool:
    """Check if the sender's email or domain matches any contact_handle or recruiter_email in DB."""
    if not from_header or not conn:
        return False

    # Extract email and domain from from_header
    email_match = re.search(r"[\w\.-]+@[\w\.-]+\.\w+", from_header)
    if not email_match:
        return False
    sender_email = email_match.group(0).lower()
    sender_domain = sender_email.split("@")[-1]

    # Ignore generic public mail domains
    generic_domains = {"gmail.com", "google.com", "outlook.com", "yahoo.com", "hotmail.com", "icloud.com"}

    try:
        # 1. Check referral_followup_state (contact_handle)
        cursor = conn.cursor()
        rows = cursor.execute("SELECT contact_handle FROM referral_followup_state WHERE contact_handle IS NOT NULL AND contact_handle != ''").fetchall()
        for r in rows:
            handle = (r[0] or "").lower()
            if sender_email in handle:
                return True
            if sender_domain not in generic_domains and f"@{sender_domain}" in handle:
                return True

        # 2. Check cold_email_outreach (recipient_email)
        try:
            ce_rows = cursor.execute("SELECT recipient_email FROM cold_email_outreach WHERE recipient_email IS NOT NULL AND recipient_email != ''").fetchall()
            for r in ce_rows:
                rec_em = (r[0] or "").lower()
                if sender_email == rec_em:
                    return True
                if sender_domain not in generic_domains and rec_em.endswith(f"@{sender_domain}"):
                    return True
        except Exception:
            pass

        # 3. Check jobs table (recruiter_email)
        try:
            job_rows = cursor.execute("SELECT recruiter_email FROM jobs WHERE recruiter_email IS NOT NULL AND recruiter_email != ''").fetchall()
            for r in job_rows:
                rec_em = (r[0] or "").lower()
                if sender_email == rec_em:
                    return True
                if sender_domain not in generic_domains and rec_em.endswith(f"@{sender_domain}"):
                    return True
        except Exception:
            pass
    except Exception as e:
        log.debug("Contact lookup error: %s", e)

    return False


def extract_instahyre_job(from_header: str, subject: str, body: str) -> dict[str, str] | None:
    """Extract job opening from Instahyre email (e.g. from jushey@tryinstahyre.com)."""
    if "tryinstahyre.com" not in from_header.lower() and "instahyre" not in from_header.lower():
        return None

    # Find instahyre.com/job- URL
    url_match = re.search(r"https?://(?:www\.)?instahyre\.com/job-[^\s<>\"']+", body)
    if not url_match:
        return None
    job_url = url_match.group(0).rstrip(".,)>\"'")

    # Extract company and title heuristics
    company = ""
    title = ""

    # Subject pattern: e.g. "Opportunity at Razorpay: Backend Engineer" or "Razorpay is hiring Backend Engineer"
    sub_patterns = [
        r"Job Match:\s*(.+?)\s+at\s+(.+)",
        r"(?:at|with)\s+([^:]+?):\s*(.+)",
        r"([^:\-]+?)\s+(?:is hiring|is looking for)\s+(.+)",
    ]
    for p in sub_patterns:
        m = re.search(p, subject, re.IGNORECASE)
        if m:
            if "Job Match:" in p:
                title = m.group(1).strip()
                company = m.group(2).strip()
            elif "at" in p:
                company = m.group(1).strip()
                title = m.group(2).strip()
            else:
                company = m.group(1).strip()
                title = m.group(2).strip()
            break

    if not company or not title:
        comp_m = re.search(r"(?:Company|Employer):\s*([^\n\r]+)", body, re.IGNORECASE)
        if comp_m:
            company = comp_m.group(1).strip()
        role_m = re.search(r"(?:Role|Position|Job Title):\s*([^\n\r]+)", body, re.IGNORECASE)
        if role_m:
            title = role_m.group(1).strip()

    if not company:
        company = "Instahyre Match"
    if not title:
        title = "Software Engineer"

    return {
        "url": job_url,
        "company": company,
        "title": title,
    }


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


def classify_email(subject: str, body: str, from_header: str = "", conn: Any = None) -> dict[str, Any]:
    """Classify email into detailed categories: OA, Selected/Interview, Rejected, Reply, Apply Link, or Acknowledged."""
    combined = f"{subject}\n{body}"
    text_lower = combined.lower()

    # 0. Direct Human Reply (In-Reply-To / Re:) on an outreach thread or known contact
    is_re_thread = subject.strip().lower().startswith("re:") or "re:" in subject.lower()
    is_known_contact = is_known_outreach_contact(from_header, conn) if from_header else False
    if is_re_thread or is_known_contact:
        # Check if it's not an explicit automated rejection
        is_rejection = any(neg in text_lower for neg in [
            "unfortunately", "not moving forward", "regret to inform",
            "pursuing other candidates", "decided not to proceed",
            "not selected at this time", "position has been filled"
        ])
        if not is_rejection and (is_known_contact or ("referral" in text_lower or "interview" in text_lower or "resume" in text_lower or "profile" in text_lower or is_re_thread)):
            return {
                "category": "referral_or_recruiter_reply",
                "sentiment": "positive",
                "status": "Direct Reply / Active Thread",
                "summary": "Direct human reply received on outreach or application thread.",
                "due_date": "",
                "action_url": "",
                "action_type": "reply",
            }

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

    query = 'newer_than:7d -label:"Career/Job Board Digests" -label:"Personal & Social/LinkedIn"'
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

    # Prioritize messages carrying Career/Interviews & Action or Career/ATS & Applications
    def _priority_score(m: dict) -> int:
        lbls = [l.lower() for l in m.get("labelIds", [])]
        for l in lbls:
            if "interview" in l or "action" in l:
                return 0
            if "ats" in l or "application" in l:
                return 1
        return 2

    messages.sort(key=_priority_score)

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

        # Check for Instahyre direct match email ingestion
        instahyre_job = extract_instahyre_job(from_hdr, subject, full_body)
        if instahyre_job:
            try:
                from applypilot.database import store_jobs_deduped
                store_jobs_deduped(
                    conn=conn,
                    jobs=[{
                        "url": instahyre_job["url"],
                        "title": instahyre_job["title"],
                        "company": instahyre_job["company"],
                        "site": instahyre_job["company"],
                        "location": "Bengaluru",
                        "description": full_body[:1000],
                        "application_url": instahyre_job["url"],
                        "fit_score": 8,
                    }],
                    site=instahyre_job["company"],
                    strategy="instahyre_email_match",
                )
            except Exception as ih_err:
                log.warning("Instahyre direct match ingestion warning: %s", ih_err)

        company = extract_company_from_email(from_hdr, subject, full_body)
        classification = classify_email(subject, full_body, from_header=from_hdr, conn=conn)

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

        # Check if message is newly discovered to trigger instant alert
        is_new_msg = c.execute("SELECT 1 FROM application_responses WHERE message_id = ?", (msg_id,)).fetchone() is None
        if is_new_msg:
            try:
                from applypilot.notifications.alerts import alert_new_online_assessment, alert_interview_shortlisted
                if category == "oa":
                    alert_new_online_assessment(company, role_title, due_date, action_url)
                elif category in ("interview_selected", "referral_or_recruiter_reply"):
                    alert_interview_shortlisted(company, role_title, summary, action_url)
            except Exception as alert_err:
                log.debug("Notification alert dispatch error: %s", alert_err)

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
        if category in ("oa", "interview_selected", "referral_or_recruiter_reply"):
            c.execute("""
                UPDATE jobs 
                SET apply_status = 'interview',
                    application_stage = 'interview'
                WHERE (site LIKE ? OR url LIKE ?)
            """, (f"%{company}%", f"%{company.lower()}%"))
        elif category in ("rejected", "rejection"):
            c.execute("""
                UPDATE jobs 
                SET apply_status = 'rejected',
                    application_stage = 'rejected'
                WHERE (site LIKE ? OR url LIKE ?)
            """, (f"%{company}%", f"%{company.lower()}%"))
        elif category == "acknowledged":
            c.execute("""
                UPDATE jobs 
                SET apply_status = 'applied',
                    applied_at = COALESCE(applied_at, ?),
                    application_stage = 'applied'
                WHERE (site LIKE ? OR url LIKE ?) AND (apply_status IS NULL OR apply_status NOT IN ('interview', 'rejected'))
            """, (now, f"%{company}%", f"%{company.lower()}%"))

        # Bridge email response to ReferralFollowUpEngine to automatically pause/stop follow-ups
        try:
            from applypilot.networking.followup_engine import sync_state_from_email_response
            sync_state_from_email_response(
                conn=conn,
                company=company,
                role_title=role_title,
                category=category,
            )
        except Exception as fe_sync_err:
            log.warning("Failed syncing followup state from email response: %s", fe_sync_err)

        results.append(entry)

    conn.commit()
    log.info("Synced %d job application responses from Gmail.", len(results))
    return get_cached_responses()


def sanitize_response_url(url: str, company: str = "") -> str:
    """Sanitize action URLs to ensure no dead mock or broken paths are served."""
    if not url:
        return ""
    u_lower = str(url).lower()
    c_lower = str(company).lower()
    if "razorpay" in u_lower or "razorpay" in c_lower:
        if "lever.co" in u_lower or "backend-sde2" in u_lower or u_lower.rstrip("/").endswith("/jobs"):
            return "https://job-boards.greenhouse.io/razorpaysoftwareprivatelimited"
    if "phonepe" in u_lower or "phonepe" in c_lower:
        if "sde1" in u_lower or u_lower.rstrip("/").endswith("/careers"):
            return "https://jobs.smartrecruiters.com/PhonePeLimited/1000000000003895"
    return url


def get_cached_responses(category_filter: str | None = None) -> list[dict[str, Any]]:
    """Retrieve already saved responses from database enriched with application attribution, turnaround time, and channel diagnostics."""
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
    results = [dict(zip(cols, r)) for r in rows]

    # Pre-fetch all applied jobs to match and correlate channel, application date, and turnaround time
    try:
        job_rows = c.execute("""
            SELECT rowid, site, title, applied_at, discovered_at, strategy, url, is_easy_apply, num_applicants, referral_status, referral_contact_name, apply_status
            FROM jobs
            WHERE apply_status IN ('applied', 'interview', 'rejected') OR applied_at IS NOT NULL
        """).fetchall()
    except Exception:
        job_rows = []

    def parse_dt(dt_val: Any) -> datetime | None:
        if not dt_val:
            return None
        dt_str = str(dt_val).replace("Z", "+00:00").strip()
        try:
            if "T" in dt_str:
                return datetime.fromisoformat(dt_str)
            return datetime.strptime(dt_str[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except Exception:
            return None

    now_utc = datetime.now(timezone.utc)

    for res in results:
        res["action_url"] = sanitize_response_url(res.get("action_url", ""), res.get("company", ""))
        comp = str(res.get("company", "")).strip().lower()
        role = str(res.get("role_title", "")).strip().lower()

        matched_job = None
        for j in job_rows:
            j_site = str(j[1] or "").lower()
            j_url = str(j[6] or "").lower()
            if (comp and (comp in j_site or j_site in comp or (len(comp) > 4 and comp in j_url))):
                matched_job = j
                break

        # Compute channel attribution
        channel = "Direct Application"
        channel_icon = "fa-solid fa-paper-plane"
        channel_color = "#38bdf8"
        applied_at_str = ""
        turnaround_label = ""
        turnaround_days = None

        if matched_job:
            j_rowid, j_site, j_title, j_applied_at, j_disc_at, j_strat, j_url, j_easy, j_num_apps, j_ref_stat, j_ref_name, j_stat = matched_job
            strat_l = str(j_strat or "").lower()
            site_l = str(j_site or "").lower()
            url_l = str(j_url or "").lower()

            applied_dt = parse_dt(j_applied_at) or parse_dt(j_disc_at)
            if applied_dt:
                applied_at_str = applied_dt.strftime("%b %d, %Y")

            if j_ref_stat == "asked" or j_ref_name or "referral" in strat_l or "whatsapp" in site_l or "kadegree" in strat_l:
                channel = "Referral Network / Community"
                channel_icon = "fa-solid fa-people-arrows"
                channel_color = "#a855f7"
            elif "1h_incognito" in strat_l or "incognito" in strat_l or (j_num_apps is not None and j_num_apps <= 100):
                channel = "Fast Incognito Apply (< 4h Discovery)"
                channel_icon = "fa-solid fa-bolt"
                channel_color = "#f59e0b"
            elif any(ats in url_l for ats in ["myworkday", "greenhouse", "lever", "smartrecruiters", "ashbyhq", "icims", "taleo", "oracle"]):
                channel = "Enterprise ATS / Career Page"
                channel_icon = "fa-solid fa-building"
                channel_color = "#60a5fa"
            else:
                channel = "Direct Job Portal"
                channel_icon = "fa-solid fa-globe"
                channel_color = "#34d399"

            # Compute response turnaround time
            rec_dt = parse_dt(res.get("received_date") or res.get("synced_at"))
            if applied_dt and rec_dt:
                diff = (rec_dt - applied_dt).total_seconds()
                diff_days = round(diff / 86400.0, 1)
                turnaround_days = diff_days
                if diff_days <= 0.1:
                    turnaround_label = "< 4 hours (Immediate Auto-Acknowledgement)"
                elif diff_days < 1.0:
                    turnaround_label = f"{round(diff / 3600.0, 1)} hours"
                else:
                    turnaround_label = f"{diff_days} days"
            elif applied_dt:
                diff_days = round((now_utc - applied_dt).total_seconds() / 86400.0, 1)
                turnaround_days = diff_days
                turnaround_label = f"{diff_days} days pending"

        # Formulate intelligence diagnosis (Why status / explanation)
        cat = res.get("category", "acknowledged")
        why_explanation = ""
        if cat in ("oa", "interview_selected"):
            why_explanation = f"Passed ATS screening via {channel}. Candidate profile & backend keywords matched recruiter criteria."
        elif cat == "rejected":
            if channel == "Enterprise ATS / Career Page":
                why_explanation = "Automated ATS parse filter: Enterprise ATS filters candidates strictly on years of experience, keyword density, or location before recruiter review."
            elif turnaround_days and turnaround_days <= 1.0:
                why_explanation = "Automated knock-out question or screening rule triggered."
            else:
                why_explanation = "Role closed or recruiter proceeded with internal/more experienced candidates."
        elif cat == "apply_link":
            why_explanation = "Direct application / referral link sent to complete submission in ATS portal."
        else:
            if turnaround_days and turnaround_days >= 7.0:
                why_explanation = f"Under review for {turnaround_days} days. In standard recruiting cycles, response after 7+ days suggests slow ATS batch review or role on hold."
            else:
                why_explanation = f"Application confirmed in system via {channel}. Awaiting recruiter batch review."

        res["channel"] = channel
        res["channel_icon"] = channel_icon
        res["channel_color"] = channel_color
        res["applied_at_str"] = applied_at_str
        res["turnaround_label"] = turnaround_label or "1–3 days (Estimated)"
        res["why_status"] = why_explanation

    return results


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
