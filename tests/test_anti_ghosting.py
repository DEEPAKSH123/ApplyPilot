"""Unit tests for Post-Interview Anti-Ghosting State Machine and Founder Pitch Generator."""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from applypilot.database import init_db
from applypilot.networking.followup_engine import ReferralFollowUpEngine
from applypilot.networking.gmail_drafter import generate_founder_pitch


def test_anti_ghosting_lifecycle_progression(tmp_path):
    """Verify OA_OR_SCREEN_PENDING and INTERVIEW_ROUND_COMPLETED state progression."""
    db_file = tmp_path / "test_anti_ghosting.db"
    init_db(db_file)

    engine = ReferralFollowUpEngine(db_path=db_file)
    now = datetime(2026, 11, 20, 10, 0, tzinfo=timezone.utc)

    # 1. Register a Tier-1 job
    engine.register_job("job-101", "Acme Corp", "Backend Engineer", "https://acme.com/jobs/101", "Bengaluru", True, now=now)

    # 2. Trigger OA Pending
    engine.trigger_oa_pending("job-101", now=now)
    state = engine.get_job_state("job-101")
    assert state["status"] == "OA_OR_SCREEN_PENDING"
    assert state["next_due_at"] == (now + timedelta(hours=48)).isoformat()

    # 3. Mark Interview Completed -> T+2h thank-you note
    engine.mark_interview_completed("job-101", contact_name="Alice Smith", now=now)
    state = engine.get_job_state("job-101")
    assert state["status"] == "INTERVIEW_ROUND_COMPLETED"
    assert state["followup_count"] == 0
    assert state["next_due_at"] == (now + timedelta(hours=2)).isoformat()

    # 4. Acknowledge T+2h note -> transitions to Day 3 check-in
    engine.acknowledge_action("job-101", now=now + timedelta(hours=2))
    state = engine.get_job_state("job-101")
    assert state["followup_count"] == 1
    assert state["next_due_at"] == (now + timedelta(hours=2) + timedelta(days=3)).isoformat()

    # 5. Acknowledge Day 3 check-in -> transitions to Day 10 final check-in
    engine.acknowledge_action("job-101", now=now + timedelta(days=3))
    state = engine.get_job_state("job-101")
    assert state["followup_count"] == 2

    # 6. Acknowledge Day 10 final check-in -> transitions to terminal OFFER_OR_CLOSED
    engine.acknowledge_action("job-101", now=now + timedelta(days=10))
    state = engine.get_job_state("job-101")
    assert state["status"] == "OFFER_OR_CLOSED"
    assert state["next_due_at"] is None


def test_generate_founder_pitch_guardrails():
    """Verify founder pitch generator rejects generic prefixes and enforces <= 80 words."""
    # Reject generic prefixes
    for bad_email in ["jobs@company.com", "careers@company.com", "hr@company.com", "info@company.com", "talent@company.com"]:
        with pytest.raises(ValueError) as exc:
            generate_founder_pitch(bad_email, "Founder", "Company")
        assert "Rejected generic email prefix" in str(exc.value)

    # Valid named pitch
    pitch = generate_founder_pitch(
        "alice@startup.ai",
        "Alice Johnson",
        "StartupAI",
        product_focus="real-time fraud prevention engine",
    )
    assert pitch["word_count"] <= 80
    assert "https://github.com/DEEPAKSH123" in pitch["body"]
    assert "Meesho" in pitch["body"]
    assert "Alice" in pitch["body"]
