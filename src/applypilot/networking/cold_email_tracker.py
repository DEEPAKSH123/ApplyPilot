"""Cold Email Sales Funnel & Tracking Engine for ApplyPilot.

Treats job search like a sales process:
1. Multi-contact targeting per company (Founder, Engineering Manager/Lead, Recruiter/HR)
2. Tracks opens, replies, calls, and follow-ups
3. Dynamic follow-up rules based on open rate signals:
   - 0-2 opens: Not interested/unseen -> wait 7 days -> short nudge in same thread -> max 2 follow-ups
   - 3-5 opens: Showing interest -> wait 7 days -> personalized value-add -> up to 5 follow-ups
   - 6-10 opens: Strong interest / internally forwarded -> follow up within 48h with demo/pitch -> up to 5 follow-ups
4. A/B template tracking and conversion metrics.
"""

import json
import logging
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from applypilot.config import APP_DIR, DB_PATH, load_profile
from applypilot.database import get_connection

log = logging.getLogger(__name__)

# Templates registry for A/B testing
DEFAULT_TEMPLATES = [
    {
        "id": "quick_pitch_v1",
        "name": "Quick Pitch (Top College + Immediate Join)",
        "pitch_style": "quick_pitch",
        "subject_template": "{role} (SDE-1 @ Meesho) - Saw your hiring post",
        "body_template": (
            "Hi {first_name},\n\n"
            "Saw your post about the {role} opening at {company}.\n\n"
            "I'm an SDE-1 Backend Engineer at Meesho (RVCE CSE '25, CGPA 8.92). My day-to-day work is building "
            "high-throughput backend services using Java, Go, Kafka, and Redis, focusing on financial reconciliation and event streaming.\n\n"
            "Can join immediately / 0 days notice. Tailored resume attached.\n\n"
            "Would love to chat if my background looks relevant for your team.\n\n"
            "Best,\n"
            "{full_name} | {phone}\n"
            "{linkedin_url}"
        ),
    },
    {
        "id": "founder_value_v1",
        "name": "Founder Value (Scale Problem Solving & Ownership)",
        "pitch_style": "founder_value",
        "subject_template": "Building backend at {company} - Deepak (SDE-1 @ Meesho)",
        "body_template": (
            "Hi {first_name},\n\n"
            "I've been following what you're building at {company} and wanted to reach out directly.\n\n"
            "I'm an SDE-1 Backend Engineer at Meesho. My core focus is distributed systems and data consistency under high volume—handling "
            "millions of transactions with Kafka, Java, Go, and Redis caching. A recent problem I tackled was redesigning "
            "out-of-order webhook reconciliation pipelines using idempotent consumers and distributed locks to prevent financial data drift.\n\n"
            "I'm looking for an early/growth engineering team where I can ship high-impact backend infrastructure. "
            "I graduated from RVCE (CGPA 8.92) and can join immediately.\n\n"
            "Resume is attached. Happy to jump on a quick 10-minute call this week if this sounds like a fit.\n\n"
            "Best,\n"
            "{full_name} | {phone}\n"
            "{linkedin_url}"
        ),
    },
    {
        "id": "tech_lead_peer_v1",
        "name": "Engineering Lead / Peer (Tech Stack & Architecture Focus)",
        "pitch_style": "lead_peer",
        "subject_template": "Backend engineering @ {company} - Deepak S H (SDE-1 @ Meesho)",
        "body_template": (
            "Hi {first_name},\n\n"
            "Saw that {company} is scaling the engineering team for {role}.\n\n"
            "I'm currently working on distributed backend microservices at Meesho (Java 17, Go, Kafka, Redis, GCP). "
            "I focus heavily on low-latency data access (sub-10ms Redis patterns), partition rebalance mitigation in Kafka consumer groups, "
            "and idempotent financial transaction handling.\n\n"
            "Graduated from RVCE CSE (8.92 CGPA) and looking for teams tackling hard backend scale challenges. Available to join immediately.\n\n"
            "Attached my resume. Would love to connect and see if there's a technical match for your team.\n\n"
            "Best,\n"
            "{full_name} | {phone}\n"
            "{linkedin_url}"
        ),
    },
]


def init_cold_email_tables(conn: sqlite3.Connection | None = None) -> None:
    """Ensure cold_email_outreach and cold_email_templates tables exist."""
    if conn is None:
        conn = get_connection()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS cold_email_outreach (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            job_rowid          INTEGER,
            company            TEXT,
            role_title         TEXT,
            recipient_email    TEXT NOT NULL,
            recipient_name     TEXT,
            recipient_role     TEXT DEFAULT 'recruiter', -- founder, hiring_manager, hr, recruiter, engineer
            subject            TEXT,
            body               TEXT,
            template_id        TEXT,
            pitch_style        TEXT DEFAULT 'quick_pitch',
            gmail_message_id   TEXT,
            thread_id          TEXT,
            sent_at            TEXT,
            open_count         INTEGER DEFAULT 0,
            last_opened_at     TEXT,
            reply_status       TEXT DEFAULT 'none', -- none, positive, negative, polite
            reply_at           TEXT,
            reply_snippet      TEXT,
            led_to_call        INTEGER DEFAULT 0,
            interest_level     TEXT DEFAULT 'unverified', -- unverified, not_interested, polite, genuine, strong
            followup_count     INTEGER DEFAULT 0,
            max_followups      INTEGER DEFAULT 2,
            next_followup_at   TEXT,
            followup_strategy  TEXT DEFAULT 'nudge_7d', -- nudge_7d, personalized_7d, urgent_48h, stop
            status             TEXT DEFAULT 'sent', -- draft, sent, following_up, replied, call_scheduled, closed
            notes              TEXT,
            created_at         TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS cold_email_templates (
            id               TEXT PRIMARY KEY,
            name             TEXT,
            pitch_style      TEXT,
            subject_template TEXT,
            body_template    TEXT,
            total_sent       INTEGER DEFAULT 0,
            total_opens      INTEGER DEFAULT 0,
            total_replies    INTEGER DEFAULT 0,
            total_calls      INTEGER DEFAULT 0,
            created_at       TEXT
        )
    """)

    now = datetime.now(timezone.utc).isoformat()
    for t in DEFAULT_TEMPLATES:
        conn.execute("""
            INSERT OR IGNORE INTO cold_email_templates (id, name, pitch_style, subject_template, body_template, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (t["id"], t["name"], t["pitch_style"], t["subject_template"], t["body_template"], now))

    conn.commit()


def calculate_followup_rules(open_count: int, followup_count: int) -> dict[str, Any]:
    """Apply the Sales Funnel Follow-Up Algorithm based on open signals."""
    if open_count <= 2:
        # Not interested or haven't seen it
        max_followups = 2
        if followup_count >= max_followups:
            return {
                "strategy": "stop",
                "action": "stop",
                "days_to_wait": 0,
                "max_followups": max_followups,
                "label": "Stopped (Low Opens, Max Followups Reached)",
                "template_type": "none"
            }
        return {
            "strategy": "nudge_7d",
            "action": "nudge",
            "days_to_wait": 7,
            "max_followups": max_followups,
            "label": "7-Day Short Thread Nudge",
            "template_type": "short_nudge"
        }
    elif 3 <= open_count <= 5:
        # Showing interest - moderate signal
        max_followups = 5
        if followup_count >= max_followups:
            return {
                "strategy": "stop",
                "action": "stop",
                "days_to_wait": 0,
                "max_followups": max_followups,
                "label": "Stopped (5 Followups Completed)",
                "template_type": "none"
            }
        return {
            "strategy": "personalized_7d",
            "action": "personalized",
            "days_to_wait": 7,
            "max_followups": max_followups,
            "label": "Personalized Value Follow-Up (Within 1 Week)",
            "template_type": "value_add"
        }
    else:  # >= 6 opens
        # Strong signal: Forwarded internally or frequently revisited!
        max_followups = 5
        if followup_count >= max_followups:
            return {
                "strategy": "stop",
                "action": "stop",
                "days_to_wait": 0,
                "max_followups": max_followups,
                "label": "Stopped (5 Followups Completed)",
                "template_type": "none"
            }
        return {
            "strategy": "urgent_48h",
            "action": "urgent_demo_pitch",
            "days_to_wait": 2,
            "max_followups": max_followups,
            "label": "🔥 48h Fast Pitch / Mini-Demo (High Engagement Signal)",
            "template_type": "demo_pitch"
        }


def generate_followup_message(
    company: str,
    role: str,
    recipient_name: str,
    original_subject: str,
    followup_number: int,
    open_count: int
) -> dict[str, str]:
    """Generate intelligent follow-up email copy tailored to intent/open count."""
    first_name = recipient_name.strip().split()[0] if recipient_name else "there"
    rule = calculate_followup_rules(open_count, followup_number - 1)
    
    subject = f"Re: {original_subject}" if not original_subject.lower().startswith("re:") else original_subject

    if rule["template_type"] == "short_nudge":
        body = (
            f"Hi {first_name},\n\n"
            f"Quick follow-up on my note last week regarding the {role} position at {company}.\n\n"
            f"Know your inbox is packed—just wanted to bubble this up in case you're still looking for a backend engineer "
            f"with Java/Go/Kafka distributed systems experience who can join immediately.\n\n"
            f"Happy to share any additional details.\n\n"
            f"Best,\n"
            f"Deepak S H | +91 8431433659\n"
            f"https://www.linkedin.com/in/deepak-s-h-82b772254"
        )
    elif rule["template_type"] == "value_add":
        body = (
            f"Hi {first_name},\n\n"
            f"Following up on the {role} role at {company}.\n\n"
            f"I was reviewing {company}'s tech domain and engineering challenges. At Meesho, I tackled similar high-throughput problems "
            f"by tuning Kafka consumer groups to eliminate partition lag during peak traffic spikes and utilizing Redis distributed caching "
            f"with fallback locks to prevent database connection saturation.\n\n"
            f"I'm confident I can hit the ground running with zero ramp-up time and ship robust backend services for your team.\n\n"
            f"Do you have 10 minutes this week for a brief conversation?\n\n"
            f"Best,\n"
            f"Deepak S H | +91 8431433659\n"
            f"https://www.linkedin.com/in/deepak-s-h-82b772254"
        )
    elif rule["template_type"] == "demo_pitch":
        body = (
            f"Hi {first_name},\n\n"
            f"Wanted to check in on the {role} opening at {company}.\n\n"
            f"To demonstrate how I work, I've outlined how I'd approach resilient distributed event ingestion and idempotency "
            f"for high-volume workflows, drawing directly from my experience building Meesho's financial reconciliation microservices.\n\n"
            f"I've attached an updated overview and would love 10 minutes to walk through how this directly applies to {company}'s goals.\n\n"
            f"Would tomorrow or Thursday afternoon work for a short call?\n\n"
            f"Best,\n"
            f"Deepak S H | +91 8431433659\n"
            f"https://www.linkedin.com/in/deepak-s-h-82b772254"
        )
    else:
        body = (
            f"Hi {first_name},\n\n"
            f"Following up once more to see if the {role} role at {company} has been filled. "
            f"Still very interested and ready to contribute immediately.\n\n"
            f"Best,\n"
            f"Deepak S H"
        )

    return {"subject": subject, "body": body, "strategy": rule["strategy"], "rule": rule}


def record_cold_outreach(
    recipient_email: str,
    company: str,
    role_title: str,
    recipient_name: str = "",
    recipient_role: str = "recruiter",
    subject: str = "",
    body: str = "",
    template_id: str = "quick_pitch_v1",
    pitch_style: str = "quick_pitch",
    gmail_message_id: str = "",
    thread_id: str = "",
    job_rowid: int | None = None,
    open_count: int = 0
) -> dict[str, Any]:
    """Store new cold email entry into the CRM funnel and schedule first follow-up."""
    conn = get_connection()
    init_cold_email_tables(conn)
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    rules = calculate_followup_rules(open_count, 0)
    next_followup = (now + timedelta(days=rules["days_to_wait"])).isoformat() if rules["days_to_wait"] > 0 else None

    cur = conn.cursor()
    cur.execute("""
        INSERT INTO cold_email_outreach (
            job_rowid, company, role_title, recipient_email, recipient_name, recipient_role,
            subject, body, template_id, pitch_style, gmail_message_id, thread_id, sent_at,
            open_count, max_followups, next_followup_at, followup_strategy, status, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'sent', ?)
    """, (
        job_rowid, company, role_title, recipient_email.strip(), recipient_name.strip(), recipient_role,
        subject, body, template_id, pitch_style, gmail_message_id, thread_id, now_iso,
        open_count, rules["max_followups"], next_followup, rules["strategy"], now_iso
    ))
    new_id = cur.lastrowid

    # Update template stats
    if template_id:
        conn.execute("UPDATE cold_email_templates SET total_sent = total_sent + 1 WHERE id = ?", (template_id,))

    conn.commit()
    return {"status": "ok", "outreach_id": new_id, "next_followup_at": next_followup, "strategy": rules["strategy"]}


def log_interaction_update(
    outreach_id: int,
    open_count: int | None = None,
    reply_status: str | None = None,
    reply_snippet: str | None = None,
    led_to_call: bool | None = None,
    interest_level: str | None = None,
    notes: str | None = None,
    increment_followup: bool = False
) -> dict[str, Any]:
    """Update tracking signals (opens, replies, calls) and recalculate next follow-up."""
    conn = get_connection()
    init_cold_email_tables(conn)
    
    row = conn.execute("SELECT * FROM cold_email_outreach WHERE id = ?", (outreach_id,)).fetchone()
    if not row:
        return {"status": "error", "message": f"Outreach record {outreach_id} not found"}

    curr_opens = row["open_count"] if open_count is None else max(0, int(open_count))
    curr_followups = row["followup_count"] + (1 if increment_followup else 0)
    now_iso = datetime.now(timezone.utc).isoformat()

    updates = []
    params = []

    if open_count is not None:
        updates.append("open_count = ?")
        params.append(curr_opens)
        updates.append("last_opened_at = ?")
        params.append(now_iso)

    if reply_status is not None:
        updates.append("reply_status = ?")
        params.append(reply_status)
        updates.append("reply_at = ?")
        params.append(now_iso)
        if reply_status in ("positive", "polite"):
            updates.append("status = 'replied'")
        elif reply_status == "negative":
            updates.append("status = 'closed'")
            updates.append("followup_strategy = 'stop'")

    if reply_snippet is not None:
        updates.append("reply_snippet = ?")
        params.append(reply_snippet)

    if led_to_call is not None:
        updates.append("led_to_call = ?")
        params.append(1 if led_to_call else 0)
        if led_to_call:
            updates.append("status = 'call_scheduled'")

    if interest_level is not None:
        updates.append("interest_level = ?")
        params.append(interest_level)

    if notes is not None:
        existing_notes = row["notes"] or ""
        new_notes = f"{existing_notes}\n[{now_iso[:10]}] {notes}".strip() if existing_notes else f"[{now_iso[:10]}] {notes}"
        updates.append("notes = ?")
        params.append(new_notes)

    if increment_followup:
        updates.append("followup_count = ?")
        params.append(curr_followups)

    # Recalculate follow-up strategy and dates
    if row["reply_status"] not in ("positive", "negative") and (reply_status != "negative"):
        rules = calculate_followup_rules(curr_opens, curr_followups)
        updates.append("max_followups = ?")
        params.append(rules["max_followups"])
        updates.append("followup_strategy = ?")
        params.append(rules["strategy"])
        if rules["action"] == "stop":
            updates.append("next_followup_at = NULL")
            if curr_followups >= rules["max_followups"]:
                updates.append("status = 'closed'")
        else:
            next_date = (datetime.now(timezone.utc) + timedelta(days=rules["days_to_wait"])).isoformat()
            updates.append("next_followup_at = ?")
            params.append(next_date)
            updates.append("status = 'following_up'")

    if updates:
        params.append(outreach_id)
        conn.execute(f"UPDATE cold_email_outreach SET {', '.join(updates)} WHERE id = ?", tuple(params))
        conn.commit()

    return {"status": "ok", "outreach_id": outreach_id, "open_count": curr_opens, "followup_count": curr_followups}


def get_cold_email_funnel_summary() -> dict[str, Any]:
    """Retrieve complete funnel statistics, due follow-ups, and active pipeline."""
    conn = get_connection()
    init_cold_email_tables(conn)

    # Funnel totals
    total_outreach = conn.execute("SELECT COUNT(*) FROM cold_email_outreach").fetchone()[0]
    total_opened = conn.execute("SELECT COUNT(*) FROM cold_email_outreach WHERE open_count > 0").fetchone()[0]
    hot_leads = conn.execute("SELECT COUNT(*) FROM cold_email_outreach WHERE open_count >= 6").fetchone()[0]
    total_replied = conn.execute("SELECT COUNT(*) FROM cold_email_outreach WHERE reply_status IN ('positive', 'polite', 'negative')").fetchone()[0]
    positive_replies = conn.execute("SELECT COUNT(*) FROM cold_email_outreach WHERE reply_status = 'positive'").fetchone()[0]
    total_calls = conn.execute("SELECT COUNT(*) FROM cold_email_outreach WHERE led_to_call = 1").fetchone()[0]

    open_rate = round((total_opened / total_outreach * 100), 1) if total_outreach > 0 else 0.0
    reply_rate = round((total_replied / total_outreach * 100), 1) if total_outreach > 0 else 0.0
    call_rate = round((total_calls / total_outreach * 100), 1) if total_outreach > 0 else 0.0

    # Due follow-ups (next_followup_at <= now, reply not received, strategy != stop)
    now_iso = datetime.now(timezone.utc).isoformat()
    due_rows = conn.execute("""
        SELECT * FROM cold_email_outreach 
        WHERE next_followup_at IS NOT NULL 
          AND next_followup_at <= ? 
          AND reply_status = 'none' 
          AND followup_strategy != 'stop'
        ORDER BY open_count DESC, next_followup_at ASC
    """, (now_iso,)).fetchall()

    due_followups = []
    for r in due_rows:
        rule = calculate_followup_rules(r["open_count"], r["followup_count"])
        due_followups.append({
            "id": r["id"],
            "company": r["company"],
            "role_title": r["role_title"],
            "recipient_email": r["recipient_email"],
            "recipient_name": r["recipient_name"],
            "recipient_role": r["recipient_role"],
            "subject": r["subject"],
            "open_count": r["open_count"],
            "followup_count": r["followup_count"],
            "max_followups": r["max_followups"],
            "next_followup_at": r["next_followup_at"],
            "strategy": r["followup_strategy"],
            "strategy_label": rule["label"],
            "action": rule["action"]
        })

    # All active outreach entries
    all_rows = conn.execute("""
        SELECT * FROM cold_email_outreach ORDER BY created_at DESC LIMIT 100
    """).fetchall()

    leads = [dict(r) for r in all_rows]

    # Template performance
    templates = conn.execute("SELECT * FROM cold_email_templates").fetchall()
    template_stats = []
    for t in templates:
        t_sent = t["total_sent"]
        t_opens = t["total_opens"]
        t_replies = t["total_replies"]
        t_calls = t["total_calls"]
        template_stats.append({
            "id": t["id"],
            "name": t["name"],
            "pitch_style": t["pitch_style"],
            "sent": t_sent,
            "opens": t_opens,
            "replies": t_replies,
            "calls": t_calls,
            "open_rate": round(t_opens / t_sent * 100, 1) if t_sent > 0 else 0.0,
            "reply_rate": round(t_replies / t_sent * 100, 1) if t_sent > 0 else 0.0
        })

    return {
        "metrics": {
            "total_sent": total_outreach,
            "total_opened": total_opened,
            "open_rate": open_rate,
            "hot_leads": hot_leads,
            "total_replies": total_replied,
            "positive_replies": positive_replies,
            "reply_rate": reply_rate,
            "total_calls": total_calls,
            "call_rate": call_rate,
            "due_followups_count": len(due_followups),
        },
        "due_followups": due_followups,
        "leads": leads,
        "templates": template_stats
    }
