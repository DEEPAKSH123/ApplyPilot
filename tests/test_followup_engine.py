"""Test Suite for Referral Tracking, Two-Email Guardrail, and Follow-Up Engine.

Asserts 5 deterministic state machine test cases:
1. test_canonical_deduplication
2. test_tier1_referral_hold_blocks_portal
3. test_48h_fallback_switches_to_secondary_email
4. test_day3_and_day7_nudge_progression
5. test_tier2_immediate_apply_uses_primary_email
"""

from datetime import datetime, timedelta, timezone
import pytest
from applypilot.networking.followup_engine import ReferralFollowUpEngine
from applypilot.database import init_db, get_connection


@pytest.fixture
def temp_engine(tmp_path):
    """Create an isolated test engine and database."""
    test_db = tmp_path / "test_applypilot.db"
    init_db(test_db)
    engine = ReferralFollowUpEngine(
        db_path=test_db,
        primary_email="deepakshkarkala@gmail.com",
        secondary_email="deepaksh.apply@gmail.com",
        referral_hold_hours=48,
    )
    return engine, test_db


def test_canonical_deduplication(temp_engine):
    """'Razorpay' + 'Backend Software Engineer II' + 'Bengaluru' vs

    'Razorpay India' + 'Backend Software Engineer 2' + 'Bangalore' ->
    second call returns SKIP_DUPLICATE.
    """
    engine, _ = temp_engine
    t0 = datetime(2026, 11, 21, 10, 0, 0, tzinfo=timezone.utc)

    # First registration
    route1 = engine.register_job(
        job_id="job_1",
        company="Razorpay",
        title="Backend Software Engineer II",
        job_url="https://razorpay.com/jobs/1",
        location="Bengaluru",
        is_tier_1=True,
        now=t0,
    )
    assert route1.action != "SKIP_DUPLICATE"
    assert route1.status == "REFERRAL_HOLD"

    # Second registration with near-synonym normalized variants
    # Note: canonical hash normalizes remote vs city prefix ([:10]) and strips non-alphanumerics
    # 'Bengaluru' -> 'bengaluru'[:10] == 'bengaluru'
    # 'Bangalore' -> both represent the city, let's test canonical hash normalization
    # If using Bangalore vs Bengaluru, both start with 'b' but the spec states:
    # "Razorpay" + "Backend Software Engineer II" + "Bengaluru" vs
    # "Razorpay India" + "Backend Software Engineer 2" + "Bangalore" -> second call returns SKIP_DUPLICATE
    # Let's verify how canonical hash handles this:
    # We normalized "Razorpay India" -> "razorpay" (or substring match) or city normalization.
    route2 = engine.register_job(
        job_id="job_2",
        company="Razorpay India",
        title="Backend Software Engineer 2",
        job_url="https://razorpay.com/jobs/2",
        location="Bangalore",
        is_tier_1=True,
        now=t0,
    )
    assert route2.action == "SKIP_DUPLICATE"


def test_tier1_referral_hold_blocks_portal(temp_engine, monkeypatch):
    """Registering a Tier-1 job sets REFERRAL_HOLD with PRIMARY_EMAIL;

    calling assistant pre-check at T + 12h raises/returns BLOCKED.
    """
    engine, db_path = temp_engine
    t0 = datetime(2026, 11, 21, 10, 0, 0, tzinfo=timezone.utc)

    # Register Tier-1 job
    job_url = "https://www.linkedin.com/jobs/view/99901/"
    route = engine.register_job(
        job_id=job_url,
        company="Google",
        title="Software Engineer",
        job_url=job_url,
        location="Bengaluru",
        is_tier_1=True,
        now=t0,
    )
    assert route.status == "REFERRAL_HOLD"
    assert route.email_to_use == "deepakshkarkala@gmail.com"

    # Insert into jobs table for assistant pre-check
    conn = get_connection(db_path)
    conn.execute(
        """
        INSERT INTO jobs (url, application_url, title, site, discovered_at, fit_score)
        VALUES (?, ?, ?, ?, ?, 10)
        """,
        (job_url, job_url, "Software Engineer", "Google", t0.isoformat()),
    )
    conn.commit()

    # Pre-check at T + 12h
    t_12h = t0 + timedelta(hours=12)

    from applypilot.apply import assistant
    monkeypatch.setattr(assistant, "DB_PATH", db_path)
    monkeypatch.setattr(assistant, "get_connection", lambda path=None: conn)

    # Mock datetime.now in assistant to return t_12h
    class MockDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return t_12h

    monkeypatch.setattr(assistant, "datetime", MockDatetime)

    res = assistant.launch_application_assistant(job_url, auto_submit=True)
    assert res.get("status") == "BLOCKED"
    assert "Tier-1 Referral Hold active" in res.get("message", "")


def test_48h_fallback_switches_to_secondary_email(temp_engine):
    """Advancing clock to T + 48h + 1m returns HOUR_48_FALLBACK_APPLY with email_to_use == SECONDARY_EMAIL."""
    engine, _ = temp_engine
    t0 = datetime(2026, 11, 21, 10, 0, 0, tzinfo=timezone.utc)

    job_url = "https://careers.uber.com/jobs/888"
    engine.register_job(
        job_id=job_url,
        company="Uber",
        title="Backend Engineer",
        job_url=job_url,
        location="Bengaluru",
        is_tier_1=True,
        now=t0,
    )

    # Check at T + 24h -> No action due yet
    t_24h = t0 + timedelta(hours=24)
    actions_24h = engine.collect_due_actions(now=t_24h)
    assert len(actions_24h) == 0

    # Advance clock to T + 48h + 1m
    t_48h_1m = t0 + timedelta(hours=48, minutes=1)
    actions_48h = engine.collect_due_actions(now=t_48h_1m)

    assert len(actions_48h) == 1
    act = actions_48h[0]
    assert act.stage == "HOUR_48_FALLBACK_APPLY"
    assert act.email_to_use == "deepaksh.apply@gmail.com"
    assert act.company == "Uber"


def test_day3_and_day7_nudge_progression(temp_engine):
    """Calling mark_referral_requested at T0 -> collect_due_actions(T0 + 72h) returns DAY_3_NUDGE ->

    acknowledge_action -> collect_due_actions(T0 + 168h) returns DAY_7_FINAL ->
    acknowledge_action -> status becomes ARCHIVED_NO_RESPONSE and collect_due_actions(T0 + 240h) returns [].
    """
    engine, _ = temp_engine
    t0 = datetime(2026, 11, 21, 10, 0, 0, tzinfo=timezone.utc)
    job_id = "job_progress_1"

    engine.register_job(
        job_id=job_id,
        company="Atlassian",
        title="Backend Developer",
        job_url="https://atlassian.com/jobs/1",
        location="Bengaluru",
        is_tier_1=True,
        now=t0,
    )

    # Log referral requested at T0
    engine.mark_referral_requested(
        job_id=job_id,
        contact_name="Ramesh Kumar",
        contact_handle="https://linkedin.com/in/ramesh",
        now=t0,
    )

    # At T0 + 72h -> DAY_3_NUDGE
    t_day3 = t0 + timedelta(hours=72)
    actions_day3 = engine.collect_due_actions(now=t_day3)
    assert len(actions_day3) == 1
    assert actions_day3[0].stage == "DAY_3_NUDGE"
    assert "Meesho" in actions_day3[0].template_text
    assert "95%" in actions_day3[0].template_text

    # Acknowledge Day 3 action
    engine.acknowledge_action(job_id=job_id, now=t_day3)

    # At T0 + 168h (Day 3 + 96h = Day 7) -> DAY_7_FINAL
    t_day7 = t0 + timedelta(hours=168)
    actions_day7 = engine.collect_due_actions(now=t_day7)
    assert len(actions_day7) == 1
    assert actions_day7[0].stage == "DAY_7_FINAL"
    assert "gently checking in one last time" in actions_day7[0].template_text

    # Acknowledge Day 7 action
    engine.acknowledge_action(job_id=job_id, now=t_day7)

    # Status should be ARCHIVED_NO_RESPONSE
    state = engine.get_job_state(job_id)
    assert state["status"] == "ARCHIVED_NO_RESPONSE"
    assert state["followup_count"] == 2
    assert state["next_due_at"] is None

    # At T0 + 240h -> No more due actions
    t_day10 = t0 + timedelta(hours=240)
    actions_day10 = engine.collect_due_actions(now=t_day10)
    assert len(actions_day10) == 0


def test_tier2_immediate_apply_uses_primary_email(temp_engine):
    """Non-Tier-1 job returns APPLY_IMMEDIATELY with PRIMARY_EMAIL and schedules Day-3 recruiter follow-up upon mark_applied."""
    engine, _ = temp_engine
    t0 = datetime(2026, 11, 21, 10, 0, 0, tzinfo=timezone.utc)
    job_id = "tier2_job_101"

    route = engine.register_job(
        job_id=job_id,
        company="Startup Co",
        title="Junior Go Developer",
        job_url="https://startup.io/careers/1",
        location="Remote",
        is_tier_1=False,
        now=t0,
    )
    assert route.action == "APPLY_IMMEDIATELY"
    assert route.status == "READY_TO_APPLY"
    assert route.email_to_use == "deepakshkarkala@gmail.com"

    # Mark applied with primary email
    engine.mark_applied(
        job_id=job_id,
        used_secondary_email=False,
        recruiter_name="Anita Sharma",
        recruiter_handle="anita@startup.io",
        now=t0,
    )

    state = engine.get_job_state(job_id)
    assert state["status"] == "APPLIED"
    assert state["email_used"] == "deepakshkarkala@gmail.com"

    # Day 3 due check
    t_day3 = t0 + timedelta(hours=72)
    actions = engine.collect_due_actions(now=t_day3)
    assert len(actions) == 1
    assert actions[0].stage == "DAY_3_NUDGE"
    assert actions[0].email_to_use == "deepakshkarkala@gmail.com"


def test_store_jobs_auto_registers_tier1_hold(temp_engine, monkeypatch):
    """Calling store_jobs_deduped() with a Tier-1 company automatically creates a

    REFERRAL_HOLD row in referral_followup_state and blocks launch_application_assistant()
    until 48 hours elapse.
    """
    engine, db_path = temp_engine
    conn = get_connection(db_path)
    from applypilot.database import store_jobs_deduped
    from applypilot.apply import assistant

    monkeypatch.setattr(assistant, "DB_PATH", db_path)
    monkeypatch.setattr(assistant, "get_connection", lambda path=None: conn)

    t0 = datetime(2026, 11, 21, 10, 0, 0, tzinfo=timezone.utc)

    # Class to mock datetime.now
    current_mock_time = t0

    class MockDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return current_mock_time

    monkeypatch.setattr(assistant, "datetime", MockDatetime)

    tier1_job_url = "https://razorpay.com/jobs/backend-lead-1"
    jobs = [
        {
            "url": tier1_job_url,
            "title": "Staff Backend Engineer",
            "company": "Razorpay",
            "site": "Razorpay",
            "location": "Bengaluru",
            "description": "Lead distributed core payment systems",
        }
    ]

    new, url_dupes, cross_dupes = store_jobs_deduped(conn, jobs, site="Razorpay", strategy="test_scrape")
    assert new == 1

    # Verify referral_followup_state has REFERRAL_HOLD created
    state = engine.get_job_state(tier1_job_url)
    assert state is not None
    assert state["status"] == "REFERRAL_HOLD"
    assert state["company"] == "Razorpay"
    assert state["email_used"] == "deepakshkarkala@gmail.com"

    # Pre-check at T + 12h -> BLOCKED
    current_mock_time = t0 + timedelta(hours=12)
    res_blocked = assistant.launch_application_assistant(tier1_job_url, auto_submit=True)
    assert res_blocked.get("status") == "BLOCKED"
    assert "Tier-1 Referral Hold active" in res_blocked.get("message", "")

    # Advance beyond 48 hours (T + 49h) -> Hold expires, auto-acknowledges and switches to SECONDARY_EMAIL
    current_mock_time = t0 + timedelta(hours=49)
    # Mock playwright or connection to verify that assistant transitions state to READY_TO_APPLY_SECONDARY
    # launch_application_assistant will auto-acknowledge and proceed past the REFERRAL_HOLD block.
    # We can mock prefill or check the state after launching assistant.
    # To prevent launching full browser in tests, we can test that calling launch_application_assistant
    # does NOT return BLOCKED.
    # Let's mock sync_playwright in assistant:
    class DummyPage:
        def __init__(self):
            self.url = tier1_job_url
        def is_closed(self):
            return True
        def evaluate(self, script):
            return None
        def wait_for_timeout(self, ms):
            pass

    class DummyContext:
        def __init__(self):
            self.pages = [DummyPage()]
        def new_page(self):
            return DummyPage()
        def close(self):
            pass

    class DummyChromium:
        def launch_persistent_context(self, *args, **kwargs):
            return DummyContext()
        def launch(self, *args, **kwargs):
            return DummyContext()

    class DummyPlaywright:
        def __init__(self):
            self.chromium = DummyChromium()
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    import playwright.sync_api
    monkeypatch.setattr(playwright.sync_api, "sync_playwright", lambda: DummyPlaywright())

    res_allowed = assistant.launch_application_assistant(tier1_job_url, auto_submit=False, headed=False)
    assert res_allowed.get("status") != "BLOCKED"

    # Check updated state after hold expired
    updated_state = engine.get_job_state(tier1_job_url)
    assert updated_state["status"] == "READY_TO_APPLY_SECONDARY"
    assert updated_state["email_used"] == "deepaksh.apply@gmail.com"

