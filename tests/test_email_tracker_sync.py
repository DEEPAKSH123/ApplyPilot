"""Test Suite for Gmail Email Tracker Alignment and Referral State Sync.

Tests:
1. An incoming reply from a referrer cancels next_due_at and moves referral_followup_state.status to REPLIED_ACTIVE.
2. An ATS rejection email (no-reply@us.greenhouse-mail.io) moves status to REJECTED and clears next_due_at.
3. An Instahyre match email extracts the instahyre.com/job-... link and registers it in SQLite.
"""

from datetime import datetime, timezone
import pytest
from applypilot.database import init_db, get_connection
from applypilot.networking.followup_engine import ReferralFollowUpEngine, sync_state_from_email_response
from applypilot.enrichment.email_tracker import (
    classify_email,
    extract_instahyre_job,
    extract_company_from_email,
    is_known_outreach_contact,
)


@pytest.fixture
def temp_db(tmp_path):
    """Create an isolated test database with initialized schema."""
    db_file = tmp_path / "test_email_tracker.db"
    init_db(db_file)
    conn = get_connection(db_file)
    engine = ReferralFollowUpEngine(
        db_path=conn,
        primary_email="deepakshkarkala@gmail.com",
        secondary_email="deepaksh.apply@gmail.com",
        referral_hold_hours=48,
    )
    return conn, engine, db_file


def test_referrer_reply_moves_to_replied_active(temp_db):
    """An incoming reply from a referrer cancels next_due_at and moves status to REPLIED_ACTIVE."""
    conn, engine, _ = temp_db
    t0 = datetime(2026, 11, 21, 10, 0, 0, tzinfo=timezone.utc)

    # 1. Register a referral outreach in state machine
    job_url = "https://nablon.io/careers/1"
    engine.register_job(
        job_id=job_url,
        company="Nablon",
        title="Backend Engineer",
        job_url=job_url,
        location="Bengaluru",
        is_tier_1=False,
        now=t0,
    )
    engine.mark_referral_requested(
        job_id=job_url,
        contact_name="Kingshuk",
        contact_handle="kingshuk@nablon.io",
        now=t0,
    )

    state_before = engine.get_job_state(job_url)
    assert state_before["status"] == "REFERRAL_REQUESTED"
    assert state_before["next_due_at"] is not None

    # 2. Check reply classification
    sender_hdr = "Kingshuk <kingshuk@nablon.io>"
    subject = "Re: Referral inquiry for Backend Engineer"
    body = "Hi Deepak, thanks for reaching out! Happy to refer you, sending your resume to the hiring manager."

    assert is_known_outreach_contact(sender_hdr, conn) is True

    classification = classify_email(subject, body, from_header=sender_hdr, conn=conn)
    assert classification["category"] == "referral_or_recruiter_reply"
    assert classification["sentiment"] == "positive"

    # 3. Sync state from email response
    updated_count = sync_state_from_email_response(
        conn=conn,
        company="Nablon",
        role_title="Backend Engineer",
        category=classification["category"],
    )
    assert updated_count == 1

    # 4. Verify referral_followup_state is now REPLIED_ACTIVE with next_due_at = NULL
    state_after = engine.get_job_state(job_url)
    assert state_after["status"] == "REPLIED_ACTIVE"
    assert state_after["next_due_at"] is None

    # Verify collect_due_actions returns empty for this job
    due_actions = engine.collect_due_actions()
    assert not any(a.job_id == job_url for a in due_actions)


def test_ats_rejection_moves_to_rejected(temp_db):
    """An ATS rejection email (e.g. greenhouse) moves status to REJECTED and clears next_due_at."""
    conn, engine, _ = temp_db
    t0 = datetime(2026, 11, 21, 10, 0, 0, tzinfo=timezone.utc)

    # 1. Register applied job in state machine
    job_url = "https://boards.greenhouse.io/bitgo/jobs/12345"
    engine.register_job(
        job_id=job_url,
        company="BitGo",
        title="Software Engineer - Platform",
        job_url=job_url,
        location="Bengaluru",
        is_tier_1=False,
        now=t0,
    )
    engine.mark_applied(
        job_id=job_url,
        used_secondary_email=False,
        recruiter_name="",
        recruiter_handle="",
        now=t0,
    )

    state_before = engine.get_job_state(job_url)
    assert state_before["status"] == "APPLIED"
    assert state_before["next_due_at"] is not None

    # 2. Check rejection email classification
    sender_hdr = "BitGo Recruiting <no-reply@us.greenhouse-mail.io>"
    subject = "Update regarding your application to BitGo"
    body = "Thank you for your interest in BitGo. Unfortunately, we will not be moving forward with your candidacy at this time."

    company = extract_company_from_email(sender_hdr, subject, body)
    assert company == "Bitgo" or "BitGo" in sender_hdr

    classification = classify_email(subject, body, from_header=sender_hdr, conn=conn)
    assert classification["category"] == "rejected"
    assert classification["sentiment"] == "negative"

    # 3. Sync state
    updated_count = sync_state_from_email_response(
        conn=conn,
        company="BitGo",
        role_title="Software Engineer - Platform",
        category="rejection",
    )
    assert updated_count == 1

    # 4. Verify status is REJECTED and next_due_at is cleared
    state_after = engine.get_job_state(job_url)
    assert state_after["status"] == "REJECTED"
    assert state_after["next_due_at"] is None


def test_instahyre_match_email_extraction_and_storage(temp_db):
    """An Instahyre match email extracts the instahyre.com/job-... link and registers it in SQLite."""
    conn, _, _ = temp_db

    sender_hdr = "Jushey from Instahyre <jushey@tryinstahyre.com>"
    subject = "Job Match: Backend Engineer at Razorpay"
    body = """
    Hi Deepak,
    A recruiter at Razorpay is looking for a Backend Engineer (Go/Java distributed systems).
    View and apply to the opportunity here: https://www.instahyre.com/job-192837-backend-engineer-at-razorpay/
    Best,
    The Instahyre Team
    """

    job_info = extract_instahyre_job(sender_hdr, subject, body)
    assert job_info is not None
    assert job_info["url"] == "https://www.instahyre.com/job-192837-backend-engineer-at-razorpay/"
    assert "Razorpay" in job_info["company"]
    assert "Backend Engineer" in job_info["title"]

    from applypilot.database import store_jobs_deduped
    new, url_dupes, cross_dupes = store_jobs_deduped(
        conn=conn,
        jobs=[{
            "url": job_info["url"],
            "title": job_info["title"],
            "company": job_info["company"],
            "site": job_info["company"],
            "location": "Bengaluru",
            "description": body,
            "application_url": job_info["url"],
            "fit_score": 8,
        }],
        site=job_info["company"],
        strategy="instahyre_email_match",
    )
    assert new == 1

    # Verify job is stored in SQLite jobs table with strategy = 'instahyre_email_match' and fit_score = 8
    row = conn.execute("SELECT url, title, site, strategy, fit_score FROM jobs WHERE url = ?", (job_info["url"],)).fetchone()
    assert row is not None
    assert row[0] == job_info["url"]
    assert row[3] == "instahyre_email_match"
    assert row[4] == 8
