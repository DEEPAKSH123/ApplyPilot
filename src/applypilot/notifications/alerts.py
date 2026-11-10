"""ApplyPilot Real-Time Instant Notification & Alert Engine.

Dispatches instant alerts directly to Deepak's phone and desktop for:
1. Online Assessments (OAs) received with pending deadlines.
2. Technical Interview selections & scheduling requests.
3. High-fit (>8/10) Community referrals (WhatsApp, KaDegree, RVCE).
4. Recruiter phone screens logged.

Supported Notification Channels:
- Telegram Bot API (Instant push notifications, zero subscription cost, high reliability).
- WhatsApp via CallMeBot API (Direct WhatsApp push message to phone).
- Windows Native Desktop Notification (PowerShell Windows Notification banner).
"""

import json
import logging
import os
import subprocess
import urllib.parse
import urllib.request
from typing import Any

from applypilot.config import load_env

log = logging.getLogger(__name__)


def get_alert_config() -> dict[str, str]:
    """Load notification channel tokens and phone numbers from environment."""
    load_env()
    return {
        "telegram_token": os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(),
        "telegram_chat_id": os.environ.get("TELEGRAM_CHAT_ID", "").strip(),
        "whatsapp_phone": os.environ.get("CALLMEBOT_PHONE", "").strip() or os.environ.get("WHATSAPP_ALERT_PHONE", "").strip(),
        "whatsapp_apikey": os.environ.get("CALLMEBOT_APIKEY", "").strip(),
    }


def send_windows_desktop_toast(title: str, message: str) -> bool:
    """Trigger a native Windows notification toast banner on Deepak's screen."""
    try:
        # PowerShell script using Windows 10/11 Notification API
        ps_script = f"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] > $null

$template = @"
<toast>
    <visual>
        <binding template="ToastGeneric">
            <text>{title}</text>
            <text>{message}</text>
        </binding>
    </visual>
</toast>
"@

$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml($template)
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
$notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("ApplyPilot")
$notifier.Show($toast)
"""
        res = subprocess.run(["powershell", "-NoProfile", "-Command", ps_script], capture_output=True, text=True, timeout=5)
        return res.returncode == 0
    except Exception as e:
        log.debug("Windows toast notification error: %s", e)
        return False


def send_telegram_alert(text: str, parse_mode: str = "HTML") -> dict[str, Any]:
    """Send an instant message via Telegram Bot API."""
    cfg = get_alert_config()
    token = cfg["telegram_token"]
    chat_id = cfg["telegram_chat_id"]

    if not token or not chat_id:
        return {"status": "skipped", "message": "Telegram bot token or chat ID not configured."}

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": False
    }

    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp_body = json.loads(resp.read().decode("utf-8"))
            if resp_body.get("ok"):
                return {"status": "ok", "message": "Telegram alert dispatched successfully."}
            return {"status": "error", "message": resp_body.get("description", "Unknown Telegram error")}
    except Exception as e:
        log.error("Failed to send Telegram alert: %s", e)
        return {"status": "error", "message": str(e)}


def send_whatsapp_callmebot_alert(text: str) -> dict[str, Any]:
    """Send direct WhatsApp message using free CallMeBot API."""
    cfg = get_alert_config()
    phone = cfg["whatsapp_phone"]
    apikey = cfg["whatsapp_apikey"]

    if not phone or not apikey:
        return {"status": "skipped", "message": "CallMeBot phone or API key not configured."}

    # Format URL: https://api.callmebot.com/whatsapp.php?phone=[phone]&text=[text]&apikey=[apikey]
    encoded_text = urllib.parse.quote_plus(text)
    url = f"https://api.callmebot.com/whatsapp.php?phone={phone}&text={encoded_text}&apikey={apikey}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ApplyPilot/1.0"})
        with urllib.request.urlopen(req, timeout=12) as resp:
            content = resp.read().decode("utf-8", errors="ignore")
            if "Message queued" in content or "success" in content.lower():
                return {"status": "ok", "message": "WhatsApp alert queued successfully."}
            return {"status": "ok", "message": f"Response: {content[:100]}"}
    except Exception as e:
        log.error("Failed to send WhatsApp alert: %s", e)
        return {"status": "error", "message": str(e)}


def dispatch_alert(title: str, body: str, url: str = "", priority: str = "normal") -> dict[str, Any]:
    """Broadcast alert across all configured channels (Telegram, WhatsApp, Desktop)."""
    # 1. Format clean text for mobile bots
    clean_body = body
    if url:
        clean_body += f"\n\n🔗 <b>Action Link:</b> {url}"

    formatted_msg = f"<b>⚡ ApplyPilot Alert: {title}</b>\n\n{clean_body}"

    results = {
        "title": title,
        "priority": priority,
        "telegram": send_telegram_alert(formatted_msg),
        "whatsapp": send_whatsapp_callmebot_alert(f"⚡ ApplyPilot Alert: {title}\n\n{body}" + (f"\nLink: {url}" if url else "")),
        "windows_toast": send_windows_desktop_toast(f"ApplyPilot: {title}", body[:120]),
    }
    log.info("Dispatched alert '%s' -> TG: %s | WA: %s | Toast: %s", title, results["telegram"]["status"], results["whatsapp"]["status"], results["windows_toast"])
    return results


def alert_new_online_assessment(company: str, role: str, due_date: str, action_url: str = "") -> dict[str, Any]:
    """Trigger high-priority alert for incoming Online Assessment / Coding Test."""
    title = f"New Online Assessment Received — {company}"
    body = (
        f"🎯 <b>Role:</b> {role}\n"
        f"🏢 <b>Company:</b> {company}\n"
        f"⏰ <b>Deadline:</b> {due_date if due_date else 'Action required promptly'}\n"
        f"💡 <i>Focus time can be automatically scheduled via ApplyPilot Google Calendar.</i>"
    )
    return dispatch_alert(title, body, url=action_url, priority="high")


def alert_interview_shortlisted(company: str, role: str, notes: str = "", meeting_url: str = "") -> dict[str, Any]:
    """Trigger high-priority alert when shortlisted for interview round."""
    title = f"🎉 Interview Shortlist — {company}!"
    body = (
        f"🎯 <b>Role:</b> {role}\n"
        f"🏢 <b>Company:</b> {company}\n"
        f"📝 <b>Details:</b> {notes if notes else 'Next technical round / discussion scheduling link ready.'}\n"
        f"🛡️ <i>Interview tech cheat-sheet generated and ready in ApplyPilot dashboard.</i>"
    )
    return dispatch_alert(title, body, url=meeting_url, priority="urgent")


def alert_high_fit_referral(company: str, role: str, score: int, channel: str = "RVCE Community", apply_url: str = "") -> dict[str, Any]:
    """Trigger notification when a high-fit (>8/10) community referral is spotted."""
    title = f"🔥 High-Fit Referral Match ({score}/10) — {company}"
    body = (
        f"🎯 <b>Role:</b> {role}\n"
        f"🏢 <b>Company:</b> {company}\n"
        f"🤝 <b>Source:</b> {channel}\n"
        f"🚀 <i>Tailored resume PDF compiled and ready to submit in 1 click.</i>"
    )
    return dispatch_alert(title, body, url=apply_url, priority="normal")
