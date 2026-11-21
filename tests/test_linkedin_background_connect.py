import json
import pytest
from unittest.mock import MagicMock, patch

from applypilot.networking.linkedin import (
    send_connect_via_api,
    send_connect_via_headless_browser,
    connect_in_background,
)
from applypilot.networking.outreach import send_referral_connection_outreach
from applypilot.networking.followup_engine import ReferralFollowUpEngine
from applypilot.database import init_db


@pytest.fixture
def mock_cookies(monkeypatch):
    """Provide li_at and JSESSIONID cookies for Voyager API."""
    cookies = [
        {"name": "li_at", "value": "mock_li_at_token_1234567890"},
        {"name": "JSESSIONID", "value": "ajax:mock_csrf_token_987654"},
    ]
    monkeypatch.setattr(
        "applypilot.networking.linkedin.get_stored_cookies",
        lambda: cookies
    )
    return cookies


def test_voyager_api_success_201(mock_cookies):
    """Voyager API successfully resolves URN and returns 201 on invite."""
    profile_url = "https://www.linkedin.com/in/satyanadella/"

    with patch("requests.Session") as mock_session_cls:
        session_instance = MagicMock()
        mock_session_cls.return_value = session_instance

        # Mock GET profile lookup
        get_resp = MagicMock()
        get_resp.status_code = 200
        get_resp.json.return_value = {
            "elements": [{"entityUrn": "urn:li:fsd_profile:ACoAAAB_MOCK123"}]
        }
        get_resp.text = json.dumps(get_resp.json.return_value)

        # Mock POST invite
        post_resp = MagicMock()
        post_resp.status_code = 201
        post_resp.text = ""

        session_instance.get.return_value = get_resp
        session_instance.post.return_value = post_resp

        res = send_connect_via_api(profile_url, note="Hi, would love to connect!")

        assert res["ok"] is True
        assert res["method"] == "voyager_api"
        assert res["target_urn"] == "urn:li:fsd_profile:ACoAAAB_MOCK123"

        # Verify POST payload
        post_call = session_instance.post.call_args
        assert post_call is not None
        payload = post_call[1]["json"]
        assert payload["invitee"]["inviteeUnion"]["memberProfile"] == "urn:li:fsd_profile:ACoAAAB_MOCK123"
        assert payload["message"] == "Hi, would love to connect!"


def test_voyager_api_cant_resend_yet(mock_cookies):
    """Voyager API 422 CANT_RESEND_YET treated as ok=True."""
    profile_url = "https://www.linkedin.com/in/already-invited/"

    with patch("requests.Session") as mock_session_cls:
        session_instance = MagicMock()
        mock_session_cls.return_value = session_instance

        get_resp = MagicMock()
        get_resp.status_code = 200
        get_resp.json.return_value = {
            "elements": [{"entityUrn": "urn:li:fsd_profile:ACoAAAB_ALREADY"}]
        }
        get_resp.text = json.dumps(get_resp.json.return_value)

        post_resp = MagicMock()
        post_resp.status_code = 422
        post_resp.text = "CANT_RESEND_YET"

        session_instance.get.return_value = get_resp
        session_instance.post.return_value = post_resp

        res = send_connect_via_api(profile_url)
        assert res["ok"] is True
        assert res["method"] == "voyager_api"


def test_api_failure_fallback_to_headless_playwright(mock_cookies, monkeypatch):
    """When Voyager API fails (e.g. 403/500/network), connect_in_background falls back to headless Playwright."""
    profile_url = "https://www.linkedin.com/in/johndoe/"

    # Mock API failure
    monkeypatch.setattr(
        "applypilot.networking.linkedin.send_connect_via_api",
        lambda url, note: {"ok": False, "error": "HTTP 403 Forbidden", "method": "voyager_api"}
    )

    # Mock headless playwright success
    monkeypatch.setattr(
        "applypilot.networking.linkedin.send_connect_via_headless_browser",
        lambda url, note: {"ok": True, "method": "headless_playwright"}
    )

    res = connect_in_background(profile_url, note="Hi John!")
    assert res["ok"] is True
    assert res["method"] == "headless_playwright"


def test_both_fail_returns_ok_false(monkeypatch):
    """When both Voyager API and headless browser fail, returns ok=False with error details."""
    profile_url = "https://www.linkedin.com/in/unknown/"

    monkeypatch.setattr(
        "applypilot.networking.linkedin.send_connect_via_api",
        lambda url, note: {"ok": False, "error": "Profile not found", "method": "voyager_api"}
    )
    monkeypatch.setattr(
        "applypilot.networking.linkedin.send_connect_via_headless_browser",
        lambda url, note: {"ok": False, "error": "Button not found", "method": "headless_playwright"}
    )

    res = connect_in_background(profile_url)
    assert res["ok"] is False
    assert "Profile not found" in res["error"]
    assert "Button not found" in res["error"]


def test_sqlite_gated_tracking_on_success(tmp_path, monkeypatch):
    """SQLite records REFERRAL_REQUESTED only when connect_in_background returns ok=True."""
    db_file = tmp_path / "test_connect_gate.db"
    init_db(db_file)
    engine = ReferralFollowUpEngine(db_path=db_file)

    # Create dummy job in referral_followup_state
    engine.register_job("job_1", "Stripe", "Backend Engineer", "Bengaluru", "https://stripe.com/job/1", is_tier_1=True)

    monkeypatch.setattr("applypilot.config.DB_PATH", db_file)
    monkeypatch.setattr(
        "applypilot.networking.linkedin.connect_in_background",
        lambda url, note: {"ok": True, "method": "voyager_api"}
    )

    res = send_referral_connection_outreach(
        profile_url="https://www.linkedin.com/in/stripe-engineer",
        company="Stripe",
        person_name="Stripe Engineer",
        role_title="Backend Engineer",
        custom_note="Hi!",
        job_id="job_1"
    )

    assert res["status"] == "ok"

    # Verify status in referral_followup_state is REFERRAL_REQUESTED
    conn = engine._get_conn()
    row = conn.execute("SELECT status, contact_name FROM referral_followup_state WHERE job_id = 'job_1'").fetchone()
    assert row["status"] == "REFERRAL_REQUESTED"
    assert row["contact_name"] == "Stripe Engineer"


def test_sqlite_gated_tracking_on_failure(tmp_path, monkeypatch):
    """SQLite records CONNECT_FAILED when connect_in_background returns ok=False."""
    db_file = tmp_path / "test_connect_gate_fail.db"
    init_db(db_file)
    engine = ReferralFollowUpEngine(db_path=db_file)

    engine.register_job("job_2", "Google", "SWE", "Bengaluru", "https://google.com/job/2", is_tier_1=True)

    monkeypatch.setattr("applypilot.config.DB_PATH", db_file)
    monkeypatch.setattr(
        "applypilot.networking.linkedin.connect_in_background",
        lambda url, note: {"ok": False, "error": "Auth expired", "method": "voyager_api"}
    )

    res = send_referral_connection_outreach(
        profile_url="https://www.linkedin.com/in/googler",
        company="Google",
        person_name="Googler",
        role_title="SWE",
        custom_note="Hi!",
        job_id="job_2"
    )

    assert res["status"] == "error"

    # Verify status in referral_followup_state is CONNECT_FAILED
    conn = engine._get_conn()
    row = conn.execute("SELECT status, contact_name FROM referral_followup_state WHERE job_id = 'job_2'").fetchone()
    assert row["status"] == "CONNECT_FAILED"
    assert row["contact_name"] == "Googler"
