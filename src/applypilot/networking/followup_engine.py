"""End-to-End Referral Tracking, Two-Email Guardrail, and Follow-Up Engine.

Deterministic Finite State Machine managing job routing, referral outreach holds,
email selection (Primary vs Secondary), and Day-3/Day-7 follow-ups.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from applypilot.config import (
    DB_PATH,
    get_primary_email,
    get_secondary_email,
    get_referral_hold_hours,
)
from applypilot.database import (
    get_connection,
    init_referral_followup_state,
    compute_canonical_hash,
    job_hash_exists,
)

log = logging.getLogger(__name__)


def _to_iso(dt: datetime | str) -> str:
    """Normalize datetime or ISO string to ISO format string."""
    if isinstance(dt, datetime):
        return dt.isoformat()
    return dt


def _parse_iso(dt_str: str) -> datetime:
    """Parse ISO formatted string to datetime with timezone awareness."""
    try:
        dt = datetime.fromisoformat(dt_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return datetime.now(timezone.utc)


@dataclass
class RouteDecision:
    action: str  # "SKIP_DUPLICATE", "REFERRAL_HOLD", "APPLY_IMMEDIATELY"
    status: str
    email_to_use: str
    next_due_at: Optional[str] = None
    canonical_hash: Optional[str] = None
    job_id: Optional[str] = None


@dataclass
class FollowUpAction:
    job_id: str
    stage: str  # "HOUR_48_FALLBACK_APPLY", "DAY_3_NUDGE", "DAY_7_FINAL"
    company: str
    title: str
    job_url: str
    email_to_use: str
    contact_name: str
    contact_handle: str
    due_at: str
    template_text: str


class ReferralFollowUpEngine:
    """Deterministic Referral Follow-Up and Two-Email Guardrail State Machine."""

    def __init__(
        self,
        db_path: Path | str | None = None,
        primary_email: str | None = None,
        secondary_email: str | None = None,
        referral_hold_hours: int | None = None,
    ):
        self.db_path = db_path or DB_PATH
        self.primary_email = primary_email or get_primary_email()
        self.secondary_email = secondary_email or get_secondary_email()
        self.referral_hold_hours = (
            referral_hold_hours
            if referral_hold_hours is not None
            else get_referral_hold_hours()
        )

    def _get_conn(self) -> sqlite3.Connection:
        if isinstance(self.db_path, sqlite3.Connection):
            conn = self.db_path
        else:
            conn = get_connection(self.db_path)
        init_referral_followup_state(conn)
        return conn

    def register_job(
        self,
        job_id: str,
        company: str,
        title: str,
        job_url: str,
        location: str,
        is_tier_1: bool,
        now: datetime | str | None = None,
    ) -> RouteDecision:
        """Register a discovered job through the deduplication & tiering state machine.

        - Checks canonical_hash; returns SKIP_DUPLICATE if found.
        - If is_tier_1 == True: inserts status='REFERRAL_HOLD', email_used=primary_email, next_due_at=now + 48h.
        - If is_tier_1 == False: inserts status='READY_TO_APPLY', email_used=primary_email, next_due_at=now + 72h.
        """
        conn = self._get_conn()
        now_dt = _parse_iso(_to_iso(now)) if now is not None else datetime.now(timezone.utc)
        now_iso = now_dt.isoformat()

        canon_hash = compute_canonical_hash(company, title, location)
        existing_id = job_hash_exists(conn, canon_hash)
        if existing_id is not None:
            return RouteDecision(
                action="SKIP_DUPLICATE",
                status="SKIP_DUPLICATE",
                email_to_use=self.primary_email,
                canonical_hash=canon_hash,
                job_id=existing_id,
            )

        if is_tier_1:
            status = "REFERRAL_HOLD"
            email_used = self.primary_email
            next_due = (now_dt + timedelta(hours=self.referral_hold_hours)).isoformat()
            action = "REFERRAL_HOLD"
        else:
            status = "READY_TO_APPLY"
            email_used = self.primary_email
            next_due = (now_dt + timedelta(hours=72)).isoformat()
            action = "APPLY_IMMEDIATELY"

        conn.execute(
            """
            INSERT INTO referral_followup_state (
                job_id, canonical_hash, company, title, job_url, is_tier_1,
                status, email_used, contact_name, contact_handle,
                created_at, last_action_at, followup_count, next_due_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '', '', ?, ?, 0, ?)
            """,
            (
                str(job_id),
                canon_hash,
                company,
                title,
                job_url or "",
                1 if is_tier_1 else 0,
                status,
                email_used,
                now_iso,
                now_iso,
                next_due,
            ),
        )
        conn.commit()

        return RouteDecision(
            action=action,
            status=status,
            email_to_use=email_used,
            next_due_at=next_due,
            canonical_hash=canon_hash,
            job_id=str(job_id),
        )

    def mark_referral_requested(
        self,
        job_id: str,
        contact_name: str,
        contact_handle: str,
        now: datetime | str | None = None,
    ) -> None:
        """Mark job as REFERRAL_REQUESTED with primary email and Day-3 due timer (now + 72h)."""
        conn = self._get_conn()
        now_dt = _parse_iso(_to_iso(now)) if now is not None else datetime.now(timezone.utc)
        now_iso = now_dt.isoformat()
        next_due = (now_dt + timedelta(hours=72)).isoformat()

        conn.execute(
            """
            UPDATE referral_followup_state
            SET status = 'REFERRAL_REQUESTED',
                email_used = ?,
                contact_name = ?,
                contact_handle = ?,
                last_action_at = ?,
                next_due_at = ?
            WHERE job_id = ?
            """,
            (
                self.primary_email,
                contact_name or "",
                contact_handle or "",
                now_iso,
                next_due,
                str(job_id),
            ),
        )
        conn.commit()

    def mark_connect_failed(
        self,
        job_id: str,
        contact_name: str,
        contact_handle: str,
        error_message: str = "",
        now: datetime | str | None = None,
    ) -> None:
        """Mark job referral connection attempt as CONNECT_FAILED with error details."""
        conn = self._get_conn()
        now_dt = _parse_iso(_to_iso(now)) if now is not None else datetime.now(timezone.utc)
        now_iso = now_dt.isoformat()

        conn.execute(
            """
            UPDATE referral_followup_state
            SET status = 'CONNECT_FAILED',
                contact_name = CASE WHEN ? != '' THEN ? ELSE contact_name END,
                contact_handle = CASE WHEN ? != '' THEN ? ELSE contact_handle END,
                last_action_at = ?
            WHERE job_id = ?
            """,
            (
                contact_name or "",
                contact_name or "",
                contact_handle or "",
                contact_handle or "",
                now_iso,
                str(job_id),
            ),
        )
        conn.commit()

    def mark_applied(
        self,
        job_id: str,
        used_secondary_email: bool,
        recruiter_name: str = "",
        recruiter_handle: str = "",
        now: datetime | str | None = None,
    ) -> None:
        """Mark job as APPLIED with assigned email and Day-3 due timer (now + 72h)."""
        conn = self._get_conn()
        now_dt = _parse_iso(_to_iso(now)) if now is not None else datetime.now(timezone.utc)
        now_iso = now_dt.isoformat()
        next_due = (now_dt + timedelta(hours=72)).isoformat()
        email_to_set = self.secondary_email if used_secondary_email else self.primary_email

        conn.execute(
            """
            UPDATE referral_followup_state
            SET status = 'APPLIED',
                email_used = ?,
                contact_name = CASE WHEN ? != '' THEN ? ELSE contact_name END,
                contact_handle = CASE WHEN ? != '' THEN ? ELSE contact_handle END,
                last_action_at = ?,
                next_due_at = ?
            WHERE job_id = ?
            """,
            (
                email_to_set,
                recruiter_name,
                recruiter_name,
                recruiter_handle,
                recruiter_handle,
                now_iso,
                next_due,
                str(job_id),
            ),
        )
        conn.commit()

    def collect_due_actions(
        self, now: datetime | str | None = None
    ) -> list[FollowUpAction]:
        """Collect all due actions where now >= next_due_at:

        status == 'REFERRAL_HOLD' -> stage='HOUR_48_FALLBACK_APPLY', email_to_use=secondary_email
        followup_count == 0       -> stage='DAY_3_NUDGE' (renders personalized template)
        followup_count == 1       -> stage='DAY_7_FINAL' (renders final 1-line check-in template)
        """
        conn = self._get_conn()
        now_dt = _parse_iso(_to_iso(now)) if now is not None else datetime.now(timezone.utc)
        now_iso = now_dt.isoformat()

        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT job_id, canonical_hash, company, title, job_url, is_tier_1,
                   status, email_used, contact_name, contact_handle,
                   created_at, last_action_at, followup_count, next_due_at
            FROM referral_followup_state
            WHERE status IN ('REFERRAL_HOLD', 'REFERRAL_REQUESTED', 'APPLIED', 'FOLLOWUP_1_SENT', 'OA_OR_SCREEN_PENDING', 'INTERVIEW_ROUND_COMPLETED')
              AND next_due_at IS NOT NULL
              AND next_due_at <= ?
            ORDER BY next_due_at ASC
            """,
            (now_iso,),
        )
        rows = cursor.fetchall()

        actions: list[FollowUpAction] = []
        for r in rows:
            st = r["status"]
            f_count = r["followup_count"]
            comp = r["company"]
            title = r["title"]
            jid = r["job_id"]
            jurl = r["job_url"]
            cname = r["contact_name"] or "there"
            chandle = r["contact_handle"]
            due_at = r["next_due_at"]

            if st == "OA_OR_SCREEN_PENDING":
                stage = "OA_COMPLETION_REMINDER"
                email_to_use = r["email_used"] or self.primary_email
                template_text = f"OA / AI-screen completion reminder for {comp} ({title}). Target 48-hour completion deadline approaching."
            elif st == "INTERVIEW_ROUND_COMPLETED":
                if f_count == 0:
                    stage = "THANK_YOU_NOTE"
                    email_to_use = r["email_used"] or self.primary_email
                    template_text = f"Hi {cname},\n\nThank you for taking the time to speak with me today about the {title} role at {comp}. I really enjoyed learning more about the team and remain very excited about the opportunity.\n\nBest regards,\nDeepak S H"
                elif f_count == 1:
                    stage = "POST_INTERVIEW_DAY_3"
                    email_to_use = r["email_used"] or self.primary_email
                    template_text = f"Hi {cname},\n\nFollowing up on our interview last week for the {title} role at {comp}. Wanted to check if there are any updates or additional information I can provide.\n\nBest regards,\nDeepak S H"
                elif f_count == 2:
                    stage = "POST_INTERVIEW_FINAL"
                    email_to_use = r["email_used"] or self.primary_email
                    template_text = f"Hi {cname},\n\nFinal check-in regarding the {title} position at {comp}. Thanks again for the opportunity to interview with your team.\n\nBest regards,\nDeepak S H"
                else:
                    continue
            elif st == "REFERRAL_HOLD":
                stage = "HOUR_48_FALLBACK_APPLY"
                email_to_use = self.secondary_email
                template_text = (
                    f"48-Hour Referral Window Expired for {comp} ({title}). "
                    f"Switching to Secondary Email ({self.secondary_email}) for portal auto-apply "
                    f"to preserve primary email ({self.primary_email}) for late referrals."
                )
            elif f_count == 0:
                stage = "DAY_3_NUDGE"
                email_to_use = r["email_used"] or self.primary_email
                template_text = (
                    f"Hi {cname},\n\n"
                    f"Following up on the {title} role (Job ID: {jid}) at {comp}. "
                    f"I previously worked at Meesho where I engineered high-throughput Go and Java distributed backend "
                    f"services processing millions of daily transactions at 95%+ reconciliation accuracy. "
                    f"Would love to connect or see if my profile aligns with the team's needs!\n\n"
                    f"Best regards,\nDeepak S H"
                )
            elif f_count == 1:
                stage = "DAY_7_FINAL"
                email_to_use = r["email_used"] or self.primary_email
                template_text = (
                    f"Hi {cname}, gently checking in one last time on the {title} opportunity at {comp} — "
                    f"I remain very excited about the role and would appreciate any quick updates or referral guidance."
                )
            else:
                continue

            actions.append(
                FollowUpAction(
                    job_id=jid,
                    stage=stage,
                    company=comp,
                    title=title,
                    job_url=jurl,
                    email_to_use=email_to_use,
                    contact_name=r["contact_name"] or "",
                    contact_handle=chandle or "",
                    due_at=due_at,
                    template_text=template_text,
                )
            )

        return actions

    def acknowledge_action(
        self, job_id: str, now: datetime | str | None = None
    ) -> None:
        """Acknowledge a completed follow-up action.

        - If status == 'REFERRAL_HOLD': transitions to READY_TO_APPLY_SECONDARY with email_used=secondary_email.
        - Else increments followup_count:
            if 1, sets next_due_at = now + 96h;
            if >= 2, sets status='ARCHIVED_NO_RESPONSE' and next_due_at=None.
        """
        conn = self._get_conn()
        now_dt = _parse_iso(_to_iso(now)) if now is not None else datetime.now(timezone.utc)
        now_iso = now_dt.isoformat()

        cursor = conn.cursor()
        cursor.execute(
            "SELECT status, followup_count FROM referral_followup_state WHERE job_id = ?",
            (str(job_id),),
        )
        row = cursor.fetchone()
        if not row:
            return

        status = row["status"]
        count = row["followup_count"]

        if status == "OA_OR_SCREEN_PENDING":
            conn.execute(
                """
                UPDATE referral_followup_state
                SET status = 'OA_COMPLETED',
                    last_action_at = ?,
                    next_due_at = NULL
                WHERE job_id = ?
                """,
                (now_iso, str(job_id)),
            )
        elif status == "INTERVIEW_ROUND_COMPLETED":
            new_count = count + 1
            if new_count == 1:
                # T + 3 business days (~72h)
                next_due = (now_dt + timedelta(days=3)).isoformat()
                conn.execute(
                    """
                    UPDATE referral_followup_state
                    SET followup_count = ?,
                        last_action_at = ?,
                        next_due_at = ?
                    WHERE job_id = ?
                    """,
                    (new_count, now_iso, next_due, str(job_id)),
                )
            elif new_count == 2:
                # T + 10 business days (~7 days after day 3)
                next_due = (now_dt + timedelta(days=7)).isoformat()
                conn.execute(
                    """
                    UPDATE referral_followup_state
                    SET followup_count = ?,
                        last_action_at = ?,
                        next_due_at = ?
                    WHERE job_id = ?
                    """,
                    (new_count, now_iso, next_due, str(job_id)),
                )
            else:
                conn.execute(
                    """
                    UPDATE referral_followup_state
                    SET status = 'OFFER_OR_CLOSED',
                        followup_count = ?,
                        last_action_at = ?,
                        next_due_at = NULL
                    WHERE job_id = ?
                    """,
                    (new_count, now_iso, str(job_id)),
                )
        elif status == "REFERRAL_HOLD":
            conn.execute(
                """
                UPDATE referral_followup_state
                SET status = 'READY_TO_APPLY_SECONDARY',
                    email_used = ?,
                    last_action_at = ?,
                    next_due_at = NULL
                WHERE job_id = ?
                """,
                (self.secondary_email, now_iso, str(job_id)),
            )
        else:
            new_count = count + 1
            if new_count == 1:
                next_due = (now_dt + timedelta(hours=96)).isoformat()
                conn.execute(
                    """
                    UPDATE referral_followup_state
                    SET followup_count = ?,
                        status = 'FOLLOWUP_1_SENT',
                        last_action_at = ?,
                        next_due_at = ?
                    WHERE job_id = ?
                    """,
                    (new_count, now_iso, next_due, str(job_id)),
                )
            else:
                conn.execute(
                    """
                    UPDATE referral_followup_state
                    SET followup_count = ?,
                        status = 'ARCHIVED_NO_RESPONSE',
                        last_action_at = ?,
                        next_due_at = NULL
                    WHERE job_id = ?
                    """,
                    (new_count, now_iso, str(job_id)),
                )

        conn.commit()

    def get_job_state(self, job_id: str) -> Optional[dict]:
        """Fetch the current state record for a job."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT job_id, canonical_hash, company, title, job_url, is_tier_1,
                   status, email_used, contact_name, contact_handle,
                   created_at, last_action_at, followup_count, next_due_at
            FROM referral_followup_state
            WHERE job_id = ?
            """,
            (str(job_id),),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return dict(row)




    def trigger_oa_pending(self, job_id: str, now: datetime | str | None = None) -> None:
        """Move job into OA_OR_SCREEN_PENDING state with next_due_at = now + 48h."""
        conn = self._get_conn()
        now_dt = _parse_iso(_to_iso(now)) if now is not None else datetime.now(timezone.utc)
        due_dt = (now_dt + timedelta(hours=48)).isoformat()
        conn.execute("""
            UPDATE referral_followup_state
            SET status = 'OA_OR_SCREEN_PENDING',
                next_due_at = ?,
                last_action_at = ?
            WHERE job_id = ?
        """, (due_dt, now_dt.isoformat(), str(job_id)))
        conn.commit()

    def mark_interview_completed(self, job_id: str, contact_name: str = "", now: datetime | str | None = None) -> None:
        """Move job into INTERVIEW_ROUND_COMPLETED state:
        Sets stage for T+2h thank-you note draft.
        """
        conn = self._get_conn()
        now_dt = _parse_iso(_to_iso(now)) if now is not None else datetime.now(timezone.utc)
        due_dt = (now_dt + timedelta(hours=2)).isoformat()
        conn.execute("""
            UPDATE referral_followup_state
            SET status = 'INTERVIEW_ROUND_COMPLETED',
                contact_name = CASE WHEN ? != '' THEN ? ELSE contact_name END,
                followup_count = 0,
                next_due_at = ?,
                last_action_at = ?
            WHERE job_id = ?
        """, (contact_name, contact_name, due_dt, now_dt.isoformat(), str(job_id)))
        conn.commit()

    def mark_offer_or_closed(self, job_id: str, final_status: str = 'OFFER_OR_CLOSED') -> None:
        """Terminal state: clears next_due_at."""
        conn = self._get_conn()
        conn.execute("""
            UPDATE referral_followup_state
            SET status = ?,
                next_due_at = NULL
            WHERE job_id = ?
        """, (final_status, str(job_id)))
        conn.commit()

def sync_state_from_email_response(
    conn: sqlite3.Connection,
    company: str,
    role_title: str = "",
    category: str = "",
) -> int:
    """Sync email response (reply, interview, OA, rejection) to referral_followup_state.

    - Matches open rows in referral_followup_state where LOWER(company) LIKE ?
      and status IN ('REFERRAL_HOLD', 'REFERRAL_REQUESTED', 'APPLIED', 'FOLLOWUP_1_SENT').
    - If category in ("interview", "oa", "referral_or_recruiter_reply", "offer"):
        updates status = 'REPLIED_ACTIVE', sets next_due_at = NULL,
        and triggers a high-priority Telegram alert.
    - If category == "rejection":
        updates status = 'REJECTED', sets next_due_at = NULL.

    Returns:
        Number of rows updated.
    """
    if not company:
        return 0

    init_referral_followup_state(conn)
    clean_company = company.strip().lower()
    now_iso = datetime.now(timezone.utc).isoformat()

    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT job_id, company, title, status, email_used, contact_name, contact_handle
        FROM referral_followup_state
        WHERE LOWER(company) LIKE ?
          AND status IN ('REFERRAL_HOLD', 'REFERRAL_REQUESTED', 'APPLIED', 'FOLLOWUP_1_SENT')
        """,
        (f"%{clean_company}%",),
    )
    rows = cursor.fetchall()
    if not rows:
        return 0

    updated_count = 0
    cat_lower = category.lower()

    if cat_lower == "oa":
        new_status = "OA_OR_SCREEN_PENDING"
        next_due = (datetime.now(timezone.utc) + timedelta(hours=48)).isoformat()
        for r in rows:
            cursor.execute(
                """
                UPDATE referral_followup_state
                SET status = ?,
                    next_due_at = ?,
                    last_action_at = ?
                WHERE job_id = ?
                """,
                (new_status, next_due, now_iso, r["job_id"]),
            )
            updated_count += 1
        conn.commit()
        return updated_count
    elif cat_lower in ("interview", "referral_or_recruiter_reply", "offer"):
        new_status = "REPLIED_ACTIVE"
        for r in rows:
            cursor.execute(
                """
                UPDATE referral_followup_state
                SET status = ?,
                    next_due_at = NULL,
                    last_action_at = ?
                WHERE job_id = ?
                """,
                (new_status, now_iso, r["job_id"]),
            )
            updated_count += 1

            # Trigger high-priority Telegram alert
            try:
                from applypilot.automation.telegram_notifier import send_telegram_alert
                msg = (
                    f"🎯 *APPLYPILOT: ACTIVE RESPONSE DETECTED*\n\n"
                    f"🏢 *Company:* `{r['company']}`\n"
                    f"💼 *Role:* {r['title']}\n"
                    f"📩 *Category:* `{category}`\n"
                    f"✅ *State Machine:* Moved to `REPLIED_ACTIVE`. Automated Day-3/Day-7 follow-ups paused."
                )
                send_telegram_alert(msg)
            except Exception as te:
                log.debug("Telegram alert error on reply sync: %s", te)

    elif cat_lower in ("rejection", "rejected"):
        new_status = "REJECTED"
        for r in rows:
            cursor.execute(
                """
                UPDATE referral_followup_state
                SET status = ?,
                    next_due_at = NULL,
                    last_action_at = ?
                WHERE job_id = ?
                """,
                (new_status, now_iso, r["job_id"]),
            )
            updated_count += 1

    conn.commit()
    return updated_count

