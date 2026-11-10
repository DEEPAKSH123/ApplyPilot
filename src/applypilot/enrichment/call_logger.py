"""ApplyPilot Recruiter Phone Call & Offline Response Intake Engine.

Enables seamless logging of recruiter phone screens, WhatsApp messages, offline interview calls,
and assessment links through the web dashboard or API.
Automatically integrates with:
1. Application Responses Registry (shows up across the dashboard)
2. Google Calendar Time-Blocking (schedules focus blocks for interviews & OAs)
3. Central Google Sheet Synchronization
"""

import logging
from datetime import datetime, timezone
from typing import Any

from applypilot.database import get_connection

log = logging.getLogger(__name__)


def log_recruiter_call(data: dict[str, Any]) -> dict[str, Any]:
    """Record an incoming recruiter call, phone screen, or assessment update."""
    conn = get_connection()
    company = data.get("company", "").strip()
    role_title = data.get("role_title", "Backend Software Engineer").strip()
    call_type = data.get("call_type", "phone_screen").strip()
    date_received = data.get("date_received") or datetime.now().strftime("%a, %d %b %Y, %I:%M %p")
    scheduled_at = data.get("scheduled_at", "").strip()
    recruiter_name = data.get("recruiter_name", "").strip()
    recruiter_contact = data.get("recruiter_contact", "").strip()
    notes = data.get("notes", "").strip()
    action_url = data.get("action_url", "").strip()
    auto_calendar = data.get("auto_calendar", True)

    now_iso = datetime.now(timezone.utc).isoformat()

    # 1. Insert into interview_calls_log
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO interview_calls_log (
            company, role_title, call_type, date_received, scheduled_at,
            recruiter_name, recruiter_contact, notes, gsheet_synced, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
    """, (company, role_title, call_type, date_received, scheduled_at, recruiter_name, recruiter_contact, notes, now_iso))
    call_id = cursor.lastrowid

    # 2. Map into application_responses table so it is instantly unified with Gmail responses
    # Category mapping:
    # oa -> 'oa'
    # technical_interview / phone_screen -> 'interview_selected'
    # rejection -> 'rejected'
    # hr_followup / other -> 'acknowledged'
    if call_type == "oa":
        category = "oa"
        status_label = "Online Assessment (Action Required)"
        sentiment = "Positive"
    elif call_type in ("technical_interview", "phone_screen", "offer"):
        category = "interview_selected"
        status_label = "Interview / Discussion (Action Required)"
        sentiment = "Positive"
    elif call_type == "rejection":
        category = "rejected"
        status_label = "Not Selected / Rejected"
        sentiment = "Negative"
    else:
        category = "acknowledged"
        status_label = "Application Acknowledged"
        sentiment = "Neutral"

    summary_text = notes if notes else f"{call_type.replace('_', ' ').title()} logged for {company}."
    message_id = f"manual_call_{call_id}"

    cursor.execute("""
        INSERT OR REPLACE INTO application_responses (
            message_id, company, role_title, sender, subject, received_date,
            sentiment, status, summary, body_snippet, action_url, synced_at,
            category, due_date, is_completed, action_type
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
    """, (
        message_id,
        company,
        role_title,
        f"{recruiter_name} ({recruiter_contact})" if recruiter_name or recruiter_contact else "Recruiter Direct Outreach",
        f"Direct Recruiter Outreach: {role_title} at {company}",
        date_received,
        sentiment,
        status_label,
        summary_text,
        f"Direct outreach logged via ApplyPilot: {notes}",
        action_url,
        now_iso,
        category,
        scheduled_at,
        "interview_scheduled" if "interview" in call_type else "oa_due" if call_type == "oa" else ""
    ))

    # Also update matching job if exists
    cursor.execute("""
        UPDATE jobs
        SET apply_status = CASE 
                WHEN ? = 'interview_selected' THEN 'interview'
                WHEN ? = 'rejected' THEN 'rejected'
                ELSE COALESCE(apply_status, 'applied')
            END
        WHERE site LIKE ?
    """, (category, category, f"%{company}%"))

    conn.commit()

    # 3. Smart Calendar Time-Blocking
    calendar_res = None
    if auto_calendar and scheduled_at:
        try:
            from applypilot.calendar.scheduler import schedule_calendar_event
            calendar_res = schedule_calendar_event(
                company=company,
                role_title=role_title,
                event_type=call_type,
                time_str=scheduled_at,
                notes=notes,
                action_url=action_url,
                response_id=message_id
            )
        except Exception as e:
            log.warning("Could not auto-schedule calendar event: %s", e)

    # 4. Instant Phone & Desktop Alert
    try:
        from applypilot.notifications.alerts import alert_interview_shortlisted, alert_new_online_assessment
        if call_type == "oa":
            alert_new_online_assessment(company, role_title, scheduled_at, action_url)
        elif call_type in ("technical_interview", "phone_screen", "offer"):
            alert_interview_shortlisted(company, role_title, f"{recruiter_name} ({recruiter_contact}): {notes}", action_url)
    except Exception as e:
        log.debug("Could not dispatch call alert: %s", e)

    return {
        "status": "ok",
        "call_id": call_id,
        "message_id": message_id,
        "company": company,
        "category": category,
        "calendar": calendar_res
    }


def get_logged_calls() -> list[dict[str, Any]]:
    """Retrieve all logged recruiter phone calls and responses."""
    conn = get_connection()
    c = conn.cursor()
    rows = c.execute("""
        SELECT id, company, role_title, call_type, date_received, scheduled_at,
               recruiter_name, recruiter_contact, notes, calendar_event_id,
               calendar_event_link, created_at
        FROM interview_calls_log
        ORDER BY id DESC
    """).fetchall()
    cols = [d[0] for d in c.description]
    return [dict(zip(cols, r)) for r in rows]
