"""WhatsApp Alert Notification Dispatcher for ApplyPilot.

Supports sending instantaneous notifications to Deepak S H via WhatsApp for:
- 🚨 Urgent Online Assessments & Coding Test Deadlines (<48h)
- 🎯 Recruiter Inbound & Interview Screening Invitations
- 🔥 9/10 & 10/10 Tier-1 Job Discoveries (Java/Go/Kafka/Meesho Stack)
- ⚡ Daily 9:00 AM Naukri Profile Refresh Confirmations

Delivery Backends:
1. CallMeBot WhatsApp API (Free, Instant, 1-step activation phone API key)
2. Twilio WhatsApp Business API (Enterprise fallback)
3. Direct Desktop WhatsApp Web hook
"""

from __future__ import annotations

import logging
import os
import urllib.parse
import urllib.request
from typing import Any

from applypilot.config import APP_DIR, load_profile

logger = logging.getLogger("whatsapp_alerts")

# Default target recipient from candidate profile
DEFAULT_PHONE = "8431433659"
COUNTRY_CODE = "+91"


def get_whatsapp_config() -> dict[str, str]:
    """Retrieve WhatsApp API credentials from environment or profile."""
    profile = {}
    try:
        profile = load_profile().get("personal", {})
    except Exception:
        pass

    phone = os.environ.get("WHATSAPP_PHONE") or profile.get("phone") or DEFAULT_PHONE
    # Strip spaces, dashes, +
    phone_clean = phone.replace("+", "").replace("-", "").replace(" ", "").strip()
    if len(phone_clean) == 10:
        phone_clean = "91" + phone_clean

    api_key = os.environ.get("CALLMEBOT_API_KEY", "").strip()

    return {
        "phone": phone_clean,
        "api_key": api_key,
        "twilio_sid": os.environ.get("TWILIO_ACCOUNT_SID", "").strip(),
        "twilio_token": os.environ.get("TWILIO_AUTH_TOKEN", "").strip(),
        "twilio_from": os.environ.get("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886").strip(),
    }


def send_whatsapp_alert(message: str) -> dict[str, Any]:
    """Dispatch a formatted WhatsApp alert to Deepak's phone.

    Uses CallMeBot free API as primary instant gateway, with Twilio as secondary.
    If no API key is configured yet, generates a ready 1-click WhatsApp Web launch link.
    """
    cfg = get_whatsapp_config()
    phone = cfg["phone"]
    api_key = cfg["api_key"]

    # 1. CallMeBot API (Instant, Free, 100% Reliable for Personal Bots)
    if api_key:
        encoded_msg = urllib.parse.quote(message)
        url = f"https://api.callmebot.com/whatsapp.php?phone=+{phone}&text={encoded_msg}&apikey={api_key}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ApplyPilot/2.0"})
            with urllib.request.urlopen(req, timeout=12) as response:
                status_code = response.getcode()
                body = response.read().decode("utf-8")
                if status_code == 200 and "queued" in body.lower() or "success" in body.lower() or status_code == 200:
                    logger.info("Successfully dispatched WhatsApp alert to +%s", phone)
                    return {"status": "sent", "channel": "callmebot", "phone": phone}
        except Exception as e:
            logger.warning("CallMeBot dispatch error: %s", e)

    # 2. Twilio WhatsApp API (If configured)
    if cfg["twilio_sid"] and cfg["twilio_token"]:
        try:
            import base64
            auth_str = f"{cfg['twilio_sid']}:{cfg['twilio_token']}"
            b64_auth = base64.b64encode(auth_str.encode()).decode()
            data = urllib.parse.urlencode({
                "From": cfg["twilio_from"],
                "To": f"whatsapp:+{phone}",
                "Body": message,
            }).encode()

            req = urllib.request.Request(
                f"https://api.twilio.com/2010-04-01/Accounts/{cfg['twilio_sid']}/Messages.json",
                data=data,
                headers={"Authorization": f"Basic {b64_auth}"}
            )
            with urllib.request.urlopen(req, timeout=12) as response:
                return {"status": "sent", "channel": "twilio", "phone": phone}
        except Exception as e:
            logger.warning("Twilio WhatsApp error: %s", e)

    # 3. Direct WhatsApp Web Link generation (No API key needed)
    encoded_msg = urllib.parse.quote(message)
    wa_url = f"https://web.whatsapp.com/send?phone=+{phone}&text={encoded_msg}"
    return {
        "status": "api_key_required",
        "phone": phone,
        "direct_send_url": wa_url,
        "message": (
            "WhatsApp alert prepared! To enable automatic background push directly to your phone, "
            "obtain your 1-step free CallMeBot key."
        )
    }


# ---------------------------------------------------------------------------
# Pre-crafted Notification Helpers
# ---------------------------------------------------------------------------

def alert_urgent_oa(company: str, role: str, deadline: str, test_url: str = "") -> dict[str, Any]:
    """Send high-priority OA deadline alert."""
    msg = (
        f"🚨 *APPLYPILOT: URGENT OA DETECTED*\n\n"
        f"🏢 *Company:* {company}\n"
        f"💼 *Role:* {role}\n"
        f"⏳ *Deadline:* {deadline}\n\n"
        f"🔗 *Test Link:* {test_url or 'Check ApplyPilot Dashboard'}\n\n"
        f"⚡ _Please complete before the window expires._"
    )
    return send_whatsapp_alert(msg)


def alert_recruiter_interview(company: str, sender_name: str, snippet: str) -> dict[str, Any]:
    """Send interview / technical screen inbound alert."""
    msg = (
        f"🎯 *APPLYPILOT: INTERVIEW INVITATION*\n\n"
        f"🏢 *Company:* {company}\n"
        f"👤 *Recruiter:* {sender_name}\n"
        f"💬 *Message:* \"{snippet[:180]}...\"\n\n"
        f"👉 _Check your Gmail or the ApplyPilot Dashboard to schedule your slot!_"
    )
    return send_whatsapp_alert(msg)


def alert_naukri_refreshed(time_str: str = "9:00 AM") -> dict[str, Any]:
    """Send daily Naukri refresh confirmation."""
    msg = (
        f"⚡ *APPLYPILOT: NAUKRI PROFILE REFRESHED*\n\n"
        f"📄 *Action:* Resume re-uploaded successfully at {time_str} IST.\n"
        f"📈 *Rank:* Recruiter search priority is active at top tier for today."
    )
    return send_whatsapp_alert(msg)


def alert_dream_job_discovered(company: str, role: str, score: int, apply_url: str) -> dict[str, Any]:
    """Send 9/10 or 10/10 dream match discovery alert."""
    msg = (
        f"🔥 *APPLYPILOT: DREAM FIT DISCOVERED ({score}/10)*\n\n"
        f"🏢 *Company:* {company}\n"
        f"💼 *Role:* {role}\n"
        f"📄 *Tailored Resume:* Compiled & ready with Meesho BNPL facts.\n\n"
        f"🚀 *Apply in 1-Click:* {apply_url}"
    )
    return send_whatsapp_alert(msg)
