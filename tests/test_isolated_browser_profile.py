"""Unit tests for isolated browser profile, dark mode, stealth flags, and LinkedIn circuit breaker."""

import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from applypilot import config
from applypilot.apply.chrome import acquire_browser_lock, launch_isolated_playwright_context
from applypilot.networking.linkedin import (
    AUTH_EXPIRED_OR_CHALLENGED,
    check_page_for_challenges_or_auth,
    is_linkedin_cooldown_active,
    trigger_linkedin_circuit_breaker,
)


def test_chrome_never_references_brave_user_data():
    """Verify apply/chrome.py and related launchers never reference BraveSoftware User Data."""
    chrome_file = Path(__file__).parent.parent / "src" / "applypilot" / "apply" / "chrome.py"
    content = chrome_file.read_text(encoding="utf-8")
    assert "BraveSoftware" not in content
    assert "brave.exe" not in content
    assert "connect_over_cdp" not in content


def test_isolated_profile_path_and_lock(tmp_path, monkeypatch):
    """Verify isolated Playwright profile directory and file lock behavior."""
    mock_lock_file = tmp_path / "browser.lock"
    mock_profile_dir = tmp_path / "playwright_profile"

    monkeypatch.setattr(config, "BROWSER_LOCK_FILE", mock_lock_file)
    monkeypatch.setattr(config, "PLAYWRIGHT_PROFILE_DIR", mock_profile_dir)

    # Test lock acquisition
    with acquire_browser_lock(timeout=2.0) as lock_path:
        assert lock_path.exists()
        data = json.loads(lock_path.read_text(encoding="utf-8"))
        assert "pid" in data
        assert "timestamp" in data

    # Lock must be released
    assert not mock_lock_file.exists()


def test_stale_lock_auto_reclaimed(tmp_path, monkeypatch):
    """Verify stale lock (>15m old or dead PID) is reclaimed automatically."""
    mock_lock_file = tmp_path / "browser.lock"
    monkeypatch.setattr(config, "BROWSER_LOCK_FILE", mock_lock_file)

    # Create stale lock file with timestamp 20 minutes ago
    stale_payload = {
        "pid": 999999,
        "timestamp": time.time() - 1200,
    }
    mock_lock_file.write_text(json.dumps(stale_payload), encoding="utf-8")

    # Should reclaim without timeout
    with acquire_browser_lock(timeout=2.0, stale_age=900) as lock_path:
        assert lock_path.exists()
        data = json.loads(lock_path.read_text(encoding="utf-8"))
        assert data["pid"] != 999999

    assert not mock_lock_file.exists()


def test_launch_isolated_playwright_context_dark_mode_and_stealth(tmp_path, monkeypatch):
    """Verify launch_isolated_playwright_context enforces dark mode, stealth flags, and desktop UA."""
    mock_profile_dir = tmp_path / "playwright_profile"
    monkeypatch.setattr(config, "PLAYWRIGHT_PROFILE_DIR", mock_profile_dir)

    mock_playwright = MagicMock()
    mock_chromium = MagicMock()
    mock_playwright.chromium = mock_chromium

    launch_isolated_playwright_context(
        mock_playwright,
        headless=True,
        color_scheme="dark",
    )

    assert mock_chromium.launch_persistent_context.called
    _, kwargs = mock_chromium.launch_persistent_context.call_args

    assert kwargs.get("color_scheme") == "dark"
    assert kwargs.get("headless") is True
    assert "user-data-dir" not in kwargs or kwargs.get("user_data_dir") == str(mock_profile_dir.resolve())
    assert kwargs.get("user_data_dir") == str(mock_profile_dir.resolve())

    args = kwargs.get("args", [])
    assert "--disable-blink-features=AutomationControlled" in args
    assert "--force-dark-mode" in args
    assert "--no-first-run" in args
    assert "--no-default-browser-check" in args

    ua = kwargs.get("user_agent", "")
    assert "Windows NT 10.0" in ua
    assert "Chrome" in ua


def test_circuit_breaker_triggers_and_writes_cooldown(tmp_path, monkeypatch):
    """Verify circuit breaker writes 24h cooldown timestamp on challenge or 429."""
    mock_cooldown_file = tmp_path / "linkedin_cooldown.json"
    monkeypatch.setattr(config, "LINKEDIN_COOLDOWN_FILE", mock_cooldown_file)

    try:
        # Trigger circuit breaker for rate limit
        payload = trigger_linkedin_circuit_breaker("HTTP 429 Rate limited", trigger_url="https://www.linkedin.com")
        assert payload["status"] == AUTH_EXPIRED_OR_CHALLENGED
        assert mock_cooldown_file.exists()

        data = json.loads(mock_cooldown_file.read_text(encoding="utf-8"))
        assert data["status"] == AUTH_EXPIRED_OR_CHALLENGED
        cooldown_until = datetime.fromisoformat(data["cooldown_until"])
        assert cooldown_until > datetime.now(timezone.utc) + timedelta(hours=23)

        # is_linkedin_cooldown_active should return True
        active, reason = is_linkedin_cooldown_active()
        assert active is True
        assert "HTTP 429" in reason
    finally:
        # Cleanup mock file and any created files
        if mock_cooldown_file.exists():
            mock_cooldown_file.unlink()
        actual_file = Path.home() / ".applypilot" / "linkedin_cooldown.json"
        if actual_file.exists():
            actual_file.unlink()


def test_challenge_detection_logic():
    """Verify check_page_for_challenges_or_auth detects challenges, logins, and error statuses."""
    # Status codes
    hit, reason = check_page_for_challenges_or_auth("https://www.linkedin.com/feed/", status_code=429)
    assert hit is True
    assert "429" in reason

    hit, reason = check_page_for_challenges_or_auth("https://www.linkedin.com/feed/", status_code=401)
    assert hit is True

    # Challenge URLs
    hit, reason = check_page_for_challenges_or_auth("https://www.linkedin.com/checkpoint/challenge/AZT123")
    assert hit is True
    assert "checkpoint challenge" in reason

    # Login URLs
    hit, reason = check_page_for_challenges_or_auth("https://www.linkedin.com/login")
    assert hit is True
    assert "login" in reason

    # Normal feed URL
    hit, reason = check_page_for_challenges_or_auth("https://www.linkedin.com/feed/")
    assert hit is False


def test_background_poller_enforces_headless():
    """Verify poller referral sync runs headless."""
    import inspect
    from applypilot.automation.poller import execute_polling_cycle
    source = inspect.getsource(execute_polling_cycle)
    assert "sync_accepted_connections_from_linkedin(max_check=30, headless=True)" in source
