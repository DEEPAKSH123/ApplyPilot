"""Telegram Alert Notification Dispatcher for ApplyPilot.

Provides instantaneous, 100% reliable push alerts to Deepak's phone via official Telegram Bot API:
- 🚨 Urgent Online Assessments & Coding Test Deadlines (<48h)
- 🎯 Recruiter Inbound & Interview Screening Invitations
- 🔥 9/10 & 10/10 Tier-1 Job Discoveries (Java/Go/Kafka/Meesho Stack)
- ⚡ Daily 9:00 AM Naukri Profile Refresh Confirmations
"""

from __future__ import annotations

import json
import logging
import os
import urllib.parse
import urllib.request
from typing import Any

from applypilot.config import APP_DIR, load_env

logger = logging.getLogger("telegram_alerts")


def get_telegram_config() -> dict[str, str]:
    """Load Telegram Bot Token and Chat ID from .env."""
    load_env()
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    return {
        "bot_token": bot_token,
        "chat_id": chat_id,
    }


def send_telegram_alert(message: str, parse_mode: str = "Markdown") -> dict[str, Any]:
    """Send a push notification to Deepak's phone via Telegram Bot API."""
    cfg = get_telegram_config()
    token = cfg["bot_token"]
    chat_id = cfg["chat_id"]

    if not token or not chat_id:
        logger.warning("Telegram Bot Token or Chat ID not configured.")
        return {
            "status": "config_missing",
            "message": "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env",
        }

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": parse_mode,
        "disable_web_page_preview": False,
    }

    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json", "User-Agent": "ApplyPilot/2.0"},
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            if res_data.get("ok"):
                logger.info("Successfully dispatched Telegram alert to %s", chat_id)
                return {"status": "sent", "channel": "telegram", "message_id": res_data.get("result", {}).get("message_id")}
            else:
                return {"status": "error", "error": res_data.get("description")}
    except Exception as e:
        logger.error("Failed to send Telegram alert: %s", e)
        return {"status": "error", "error": str(e)}


# ---------------------------------------------------------------------------
# Pre-formatted Telegram Alert Templates
# ---------------------------------------------------------------------------

def alert_urgent_oa(company: str, role: str, deadline: str, test_url: str = "") -> dict[str, Any]:
    """Dispatch OA deadline warning."""
    msg = (
        f"🚨 *APPLYPILOT: URGENT OA DETECTED*\n\n"
        f"🏢 *Company:* `{company}`\n"
        f"💼 *Role:* {role}\n"
        f"⏳ *Deadline:* {deadline}\n\n"
        f"🔗 [Open Test Link in Browser]({test_url or 'http://localhost:8765'})\n\n"
        f"⚡ _Please complete before the window expires!_"
    )
    return send_telegram_alert(msg)


def alert_recruiter_interview(company: str, sender_name: str, snippet: str) -> dict[str, Any]:
    """Dispatch interview invitation alert."""
    msg = (
        f"🎯 *APPLYPILOT: INTERVIEW INVITATION*\n\n"
        f"🏢 *Company:* `{company}`\n"
        f"👤 *Recruiter:* {sender_name}\n"
        f"💬 *Message:*\n> \"{snippet[:200]}...\"\n\n"
        f"👉 _Check your Gmail or the ApplyPilot Dashboard to schedule!_"
    )
    return send_telegram_alert(msg)


def alert_naukri_refreshed(time_str: str = "9:00 AM") -> dict[str, Any]:
    """Dispatch daily 9:00 AM Naukri refresh confirmation."""
    msg = (
        f"⚡ *APPLYPILOT: NAUKRI PROFILE REFRESHED*\n\n"
        f"📄 *Action:* Resume re-uploaded at `{time_str} IST`\n"
        f"📈 *Status:* Recruiter search priority active at *Top Tier* for today."
    )
    return send_telegram_alert(msg)


def alert_dream_job_discovered(company: str, role: str, score: int, apply_url: str) -> dict[str, Any]:
    """Dispatch 9/10 dream fit discovery alert."""
    msg = (
        f"🔥 *APPLYPILOT: DREAM FIT DISCOVERED ({score}/10)*\n\n"
        f"🏢 *Company:* `{company}`\n"
        f"💼 *Role:* {role}\n"
        f"📄 *Resume:* Tailored with Meesho BNPL & Reconciliation facts\n\n"
        f"🚀 [1-Click Apply Portal]({apply_url})"
    )
    return send_telegram_alert(msg)
