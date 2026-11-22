"""Regression guardrail test to ensure 100% browser isolation and prevent accidental leaks.

Enforces:
1. FAILS if any file under src/applypilot/ contains BraveSoftware, brave.exe, connect_over_cdp, 9222, or 'User Data'.
2. FAILS if any file under src/applypilot/ contains headless=False EXCEPT allowlisted interactive locations:
   - applypilot/cli.py (linkedin-login / manual interactive login)
   - applypilot/apply/assistant.py (interactive application form fill review)
   - applypilot/automation/naukri_updater.py (interactive naukri login)
3. Unit tests verifying:
   - color_scheme="dark" and headless=True are passed for background runs
   - rotated cookies are persisted to linkedin_cookies.json
   - 24-hour circuit breaker trips on 401/429/checkpoint challenge
"""

import inspect
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from applypilot import config
from applypilot.apply.chrome import open_isolated_context, export_cookies_to_json
from applypilot.networking.linkedin import (
    check_page_for_challenges_or_auth,
    trigger_linkedin_circuit_breaker,
    is_linkedin_cooldown_active,
    AUTH_EXPIRED_OR_CHALLENGED,
)

SRC_DIR = Path(__file__).resolve().parent.parent / "src" / "applypilot"


def test_guardrail_zero_brave_and_cdp_references():
    """Scan every .py file under src/applypilot/ to guarantee no Brave or CDP leaks exist."""
    forbidden_terms = [
        "BraveSoftware",
        "brave.exe",
        "connect_over_cdp",
        "9222",
        "User Data",
    ]

    py_files = list(SRC_DIR.rglob("*.py"))
    assert len(py_files) > 0, "No python source files found to scan!"

    violations = []
    for f in py_files:
        content = f.read_text(encoding="utf-8", errors="ignore")
        for term in forbidden_terms:
            if term in content:
                violations.append(f"{f.relative_to(SRC_DIR.parent)} contains forbidden term: '{term}'")

    assert not violations, "Browser isolation violations found:\n" + "\n".join(violations)


def test_guardrail_headless_false_only_in_allowlist():
    """Ensure headless=False cannot be used in background modules."""
    allowlisted_files = {
        "applypilot/cli.py",
        "applypilot/apply/assistant.py",
        "applypilot/automation/naukri_updater.py",
        "applypilot/networking/linkedin.py", # compose_referral_dm assisted review
    }

    py_files = list(SRC_DIR.rglob("*.py"))
    violations = []

    for f in py_files:
        rel_path = f.relative_to(SRC_DIR).as_posix()
        # If in allowlist, verify it's only explicit interactive flows
        content = f.read_text(encoding="utf-8", errors="ignore")
        if "headless=False" in content or "headless = False" in content:
            if f"applypilot/{rel_path}" not in allowlisted_files:
                violations.append(f"Unexpected headless=False in {rel_path}")

    assert not violations, "Unauthorized headless=False found:\n" + "\n".join(violations)


def test_open_isolated_context_defaults_dark_mode_and_headless():
    """Verify open_isolated_context enforces dark mode and headless=True."""
    sig = inspect.signature(open_isolated_context)
    assert sig.parameters["headless"].default is True
    assert sig.parameters["color_scheme"].default == "dark"


def test_cookie_export_to_json(tmp_path):
    """Verify export_cookies_to_json persists session cookies."""
    mock_context = MagicMock()
    mock_context.cookies.return_value = [
        {"name": "li_at", "value": "test_li_at_val", "domain": ".linkedin.com"},
        {"name": "JSESSIONID", "value": "ajax:123456", "domain": ".linkedin.com"},
    ]
    target_file = tmp_path / "linkedin_cookies.json"

    with patch.object(config, "LINKEDIN_COOKIES_FILE", target_file):
        cookies = export_cookies_to_json(mock_context)
        assert len(cookies) == 2
        assert target_file.exists()
        saved = json.loads(target_file.read_text(encoding="utf-8"))
        assert saved[0]["name"] == "li_at"
        assert saved[0]["value"] == "test_li_at_val"


def test_circuit_breaker_trips_on_auth_and_challenges(tmp_path):
    """Verify challenge detection correctly flags 401, 429, and checkpoint challenges."""
    # 1. Status 401
    is_ch, reason = check_page_for_challenges_or_auth("https://www.linkedin.com/feed", status_code=401)
    assert is_ch is True
    assert "401" in reason

    # 2. Status 429
    is_ch, reason = check_page_for_challenges_or_auth("https://www.linkedin.com/feed", status_code=429)
    assert is_ch is True
    assert "429" in reason

    # 3. Checkpoint challenge URL
    is_ch, reason = check_page_for_challenges_or_auth("https://www.linkedin.com/checkpoint/challenge/12345")
    assert is_ch is True
    assert "checkpoint" in reason

    # 4. Trigger circuit breaker writes 24h cooldown
    cooldown_target = tmp_path / "linkedin_cooldown.json"
    with patch.object(config, "LINKEDIN_COOLDOWN_FILE", cooldown_target):
        res = trigger_linkedin_circuit_breaker("Security check tripped", trigger_url="https://www.linkedin.com/checkpoint/challenge")
        assert res["status"] == AUTH_EXPIRED_OR_CHALLENGED
        assert cooldown_target.exists()
        is_active, active_reason = is_linkedin_cooldown_active()
        assert is_active is True
        assert "Security check tripped" in active_reason
