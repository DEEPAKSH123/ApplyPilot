"""Email verification adapter wrapping Reacher (check-if-email-exists).

Configurable via REACHER_API_URL environment variable.
Degrades gracefully if unset or unreachable.
"""

import logging
import os
import httpx

log = logging.getLogger(__name__)


def verify_email_smtp(email: str) -> dict:
    """Verify email reachability via Reacher API if configured.
    
    Returns dict:
      {
        "verified": bool,
        "is_reachable": "safe" | "risky" | "invalid" | "unknown",
        "is_catch_all": bool,
        "reason": str
      }
    """
    reacher_url = os.environ.get("REACHER_API_URL", "").strip()
    if not reacher_url:
        return {
            "verified": False,
            "is_reachable": "unknown",
            "is_catch_all": False,
            "reason": "REACHER_API_URL not configured (graceful degradation)",
        }

    try:
        endpoint = reacher_url.rstrip("/")
        if not endpoint.endswith("/check_email") and not endpoint.endswith("/v0/check_email"):
            endpoint = f"{endpoint}/v0/check_email"

        with httpx.Client(timeout=10.0) as client:
            resp = client.post(endpoint, json={"to_email": email})

        if resp.status_code == 200:
            data = resp.json()
            reachability = data.get("is_reachable", "unknown")
            is_catch_all = data.get("smtp", {}).get("is_catch_all", False)
            return {
                "verified": True,
                "is_reachable": reachability,
                "is_catch_all": is_catch_all,
                "reason": f"Reacher status: {reachability}",
            }
        else:
            log.warning("Reacher API returned HTTP %d", resp.status_code)
            return {
                "verified": False,
                "is_reachable": "unknown",
                "is_catch_all": False,
                "reason": f"HTTP {resp.status_code}",
            }
    except Exception as e:
        log.warning("Reacher verification failed: %s", e)
        return {
            "verified": False,
            "is_reachable": "unknown",
            "is_catch_all": False,
            "reason": str(e),
        }
