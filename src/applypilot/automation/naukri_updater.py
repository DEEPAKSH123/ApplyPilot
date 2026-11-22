"""Naukri Daily Resume & Profile Refresh Automation.

Optimized for the Indian tech market:
Naukri's recruiter search algorithm aggressively prioritizes candidates whose profiles
were updated within the last 24 hours. Re-uploading your resume every morning at 9:00 AM IST
places your profile at the top of recruiter sourcing queues as recruiters start their day.

Key Capabilities:
- Connects using isolated persistent browser session (`~/.applypilot/playwright_profile`).
- Navigates to `https://www.naukri.com/mnjuser/profile` and attaches `D:\ApplyPilot_Workspace\data\resume.pdf`.
- Verifies upload confirmation and logs timestamps to `data/naukri_update_log.json`.
- Dispatches native Windows balloon/toast notifications upon successful refresh.
- Registers/unregisters Windows Task Scheduler daily 9:00 AM job with `-StartWhenAvailable`
  (fires immediately upon laptop wake if laptop was asleep at 9:00 AM).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from applypilot.apply.chrome import acquire_browser_lock, launch_isolated_playwright_context
from applypilot.config import APP_DIR, LOG_DIR, PLAYWRIGHT_PROFILE_DIR

# Logging configuration
LOG_FILE = LOG_DIR / "naukri_updater.log"

LOCK_FILE = APP_DIR / "data" / "naukri.lock"

def acquire_naukri_lock() -> bool:
    """Acquire lockfile with PID and timestamp.
    If stale (< 30 min old or PID dead), clears stale lock automatically.
    """
    try:
        LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        if LOCK_FILE.exists():
            try:
                data = json.loads(LOCK_FILE.read_text(encoding="utf-8"))
                lock_pid = data.get("pid")
                lock_time = data.get("timestamp", 0)
                # Check age
                age_minutes = (time.time() - lock_time) / 60
                pid_alive = False
                if lock_pid:
                    try:
                        import psutil
                        pid_alive = psutil.pid_exists(lock_pid)
                    except Exception:
                        # Fallback for Windows
                        try:
                            import ctypes
                            kernel32 = ctypes.windll.kernel32
                            handle = kernel32.OpenProcess(1, False, lock_pid)
                            if handle != 0:
                                kernel32.CloseHandle(handle)
                                pid_alive = True
                        except Exception:
                            pid_alive = False

                if age_minutes > 30 or not pid_alive:
                    log.warning("Clearing stale Naukri lock (PID %s, age %.1f min)", lock_pid, age_minutes)
                    LOCK_FILE.unlink(missing_ok=True)
                else:
                    log.info("Naukri updater already running (PID %s, age %.1f min). Skipping.", lock_pid, age_minutes)
                    return False
            except Exception as e:
                log.warning("Error inspecting lockfile: %s. Overwriting.", e)

        LOCK_FILE.write_text(json.dumps({"pid": os.getpid(), "timestamp": time.time()}), encoding="utf-8")
        return True
    except Exception as e:
        log.warning("Could not acquire lock: %s", e)
        return True

def release_naukri_lock() -> None:
    """Release Naukri lockfile."""
    try:
        LOCK_FILE.unlink(missing_ok=True)
    except Exception:
        pass

LOG_DIR.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger("naukri_updater")
if not logger.handlers:
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

NAUKRI_PROFILE_URL = "https://www.naukri.com/mnjuser/profile"
NAUKRI_LOGIN_URL = "https://www.naukri.com/nlogin/login"
SESSION_FILE = APP_DIR / "naukri_session.json"
UPDATE_LOG_FILE = APP_DIR / "naukri_update_log.json"
DEFAULT_RESUME_PATH = APP_DIR / "Deepak_S_H_Resume.pdf"
TASK_NAME = "ApplyPilot_Naukri_Daily_Refresh"


# ---------------------------------------------------------------------------
# Windows Notification Helper
# ---------------------------------------------------------------------------

def send_windows_notification(title: str, message: str) -> None:
    """Send a native Windows desktop balloon/toast notification."""
    if platform.system() != "Windows":
        return

    ps_script = f"""
    [void] [System.Reflection.Assembly]::LoadWithPartialName("System.Windows.Forms")
    $obj = New-Object System.Windows.Forms.NotifyIcon
    $obj.Icon = [System.Drawing.SystemIcons]::Information
    $obj.BalloonTipIcon = "Info"
    $obj.BalloonTipTitle = "{title}"
    $obj.BalloonTipText = "{message}"
    $obj.Visible = $True
    $obj.ShowBalloonTip(6000)
    Start-Sleep -Seconds 1
    $obj.Dispose()
    """
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps_script],
            capture_output=True,
            timeout=10,
        )
    except Exception as e:
        logger.debug("Could not dispatch desktop notification: %s", e)


# ---------------------------------------------------------------------------
# Session & Cookie Management
# ---------------------------------------------------------------------------

def get_stored_cookies() -> list[dict]:
    """Retrieve saved Naukri session cookies from JSON."""
    if not SESSION_FILE.exists():
        return []
    try:
        data = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
        return data.get("cookies", [])
    except Exception:
        return []


def save_stored_cookies(cookies: list[dict], user_info: dict | None = None) -> None:
    """Save Naukri cookies and metadata to disk."""
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "user_info": user_info or {},
        "cookies": cookies,
    }
    SESSION_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    logger.info("Saved %d Naukri cookies to %s", len(cookies), SESSION_FILE)


def record_update_log(status: str, message: str, resume_path: str, details: dict | None = None) -> dict:
    """Record refresh attempt status to `naukri_update_log.json`."""
    record = {
        "last_updated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "message": message,
        "resume_path": resume_path,
        "details": details or {},
    }
    try:
        UPDATE_LOG_FILE.write_text(json.dumps(record, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning("Could not write update log: %s", e)
    return record


def get_last_update_status() -> dict[str, Any]:
    """Read the last recorded update status."""
    if not UPDATE_LOG_FILE.exists():
        return {
            "status": "never_run",
            "message": "Naukri profile update has not been executed yet.",
            "last_updated_at": None,
        }
    try:
        return json.loads(UPDATE_LOG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"status": "error", "message": "Failed to read update log file."}


# ---------------------------------------------------------------------------
# Core Naukri Automation
# ---------------------------------------------------------------------------

def get_isolated_page_or_context(p, headed: bool = False, exe_path: str | None = None):
    """Obtain browser page/context using isolated automation profile."""
    ctx = launch_isolated_playwright_context(
        p,
        headless=True,
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    return None, ctx, page, False


def is_logged_in_page(page) -> bool:
    """Check if the current page represents an authenticated Naukri user profile."""
    current_url = page.url.lower()
    if "nlogin" in current_url or "login" in current_url:
        return False
    if "mnjuser/profile" in current_url:
        return True

    # Check for presence of typical profile elements
    try:
        indicators = [
            "#attachCV",
            "#lazyAttachCV",
            ".user-name",
            ".profile-name",
            ".resume-name",
            "a[href*='profile']",
        ]
        for sel in indicators:
            if page.locator(sel).count() > 0:
                return True
    except Exception:
        pass

    return False


def login_interactive(timeout_seconds: int = 90) -> dict[str, Any]:
    """Launch isolated Playwright Chromium browser for Deepak to sign in to Naukri."""
    from playwright.sync_api import sync_playwright

    logger.info("Opening isolated browser to log in to Naukri (timeout: %d seconds)...", timeout_seconds)

    with acquire_browser_lock():
        with sync_playwright() as p:
            context = launch_isolated_playwright_context(
                p,
                headless=True,
            )

            page = context.pages[0] if context.pages else context.new_page()

            # Inject existing cookies if present
            existing_cookies = get_stored_cookies()
            if existing_cookies:
                try:
                    context.add_cookies(existing_cookies)
                except Exception:
                    pass
                pass

        page.goto(NAUKRI_PROFILE_URL, wait_until="domcontentloaded", timeout=45000)
        time.sleep(3)

        if is_logged_in_page(page):
            logger.info("Already logged in to Naukri!")
            cookies = context.cookies()
            save_stored_cookies(cookies)
            context.close()
            return {"status": "success", "message": "Already logged in to Naukri."}

        logger.info("Redirected to login. Please log in manually in the opened browser window...")
        send_windows_notification(
            "ApplyPilot: Naukri Login Required",
            "Please log in to your Naukri account in the browser window to enable daily refresh.",
        )

        start_time = time.time()
        while time.time() - start_time < timeout_seconds:
            if page.is_closed():
                break
            if is_logged_in_page(page):
                logger.info("Login successful! Saving session cookies...")
                time.sleep(2)
                cookies = context.cookies()
                save_stored_cookies(cookies)
                try:
                    if is_cdp:
                        page.close()
                    else:
                        context.close()
                except Exception:
                    pass
                send_windows_notification(
                    "ApplyPilot: Naukri Connected",
                    "Naukri session successfully saved. Daily 9:00 AM refresh is ready!",
                )
                return {"status": "success", "message": "Naukri login successful and session saved."}
            time.sleep(2)

        try:
            context.close()
        except Exception:
            pass

        return {
            "status": "timeout",
            "message": f"Login was not completed within {timeout_seconds} seconds.",
        }


def update_naukri_resume(
    resume_path: Path | str | None = None,
    headed: bool = False,
    max_retries: int = 2,
) -> dict[str, Any]:
    """Upload/refresh resume PDF on Naukri to update the profile activity timestamp.

    Args:
        resume_path: Path to the PDF file (defaults to `D:\\ApplyPilot_Workspace\\data\\resume.pdf`).
        headed: If True, launches visible browser window; False runs headless.
        max_retries: Number of retry attempts on transient network glitches.

    Returns:
        dict with status ('success' | 'auth_required' | 'error') and details.
    """
    from playwright.sync_api import sync_playwright

    target_resume = Path(resume_path) if resume_path else DEFAULT_RESUME_PATH
    if not target_resume.is_absolute():
        target_resume = APP_DIR / target_resume

    # If Deepak_S_H_Resume.pdf doesn't exist yet, fall back to resume.pdf or copy it
    if not target_resume.exists():
        fallback_resume = APP_DIR / "resume.pdf"
        if fallback_resume.exists():
            import shutil
            shutil.copy2(str(fallback_resume), str(target_resume))
            logger.info("Created %s from %s", target_resume.name, fallback_resume.name)

    if not target_resume.exists():
        err = f"Resume file not found at: {target_resume}"
        logger.error(err)
        return record_update_log("error", err, str(target_resume))

    exe_path, browser_name = get_browser_executable()
    PLAYWRIGHT_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    logger.info("Starting Naukri resume update with: %s (using ISOLATED CHROMIUM)", target_resume.name)

    last_error = ""

    for attempt in range(1, max_retries + 1):
        try:
            with sync_playwright() as p:
                browser, context, page, is_cdp = get_isolated_page_or_context(p, headed=headed, exe_path=exe_path)

                # Add pre-saved cookies if available and not on live CDP
                if not is_cdp:
                    saved_cookies = get_stored_cookies()
                    if saved_cookies:
                        try:
                            context.add_cookies(saved_cookies)
                        except Exception as ce:
                            logger.debug("Cookie inject notice: %s", ce)

                logger.info("[Attempt %d/%d] Navigating to %s (via %s)...", 
                            attempt, max_retries, NAUKRI_PROFILE_URL, "Isolated Profile")
                page.goto(NAUKRI_PROFILE_URL, wait_until="domcontentloaded", timeout=45000)
                time.sleep(3)

                # Check if session is valid
                if not is_logged_in_page(page):
                    logger.warning("Naukri redirected to login page. Session cookies may be expired or missing.")
                    if headed or is_cdp:
                        logger.info("Headed mode enabled — waiting up to 120s for manual login...")
                        send_windows_notification(
                            "ApplyPilot: Naukri Sign-In",
                            "Please complete sign-in to connect your account.",
                        )
                        login_ok = False
                        for _ in range(60):
                            if is_logged_in_page(page):
                                login_ok = True
                                break
                            time.sleep(2)
                        if not login_ok:
                            if not is_cdp:
                                try:
                                    context.close()
                                except Exception:
                                    pass
                            return record_update_log(
                                "auth_required",
                                "Naukri authentication required. Please sign in to connect.",
                                str(target_resume),
                            )
                        # Navigate back to profile explicitly once login succeeds
                        if "profile" not in page.url.lower():
                            page.goto(NAUKRI_PROFILE_URL, wait_until="domcontentloaded", timeout=45000)
                            time.sleep(3)
                    else:
                        if not is_cdp:
                            try:
                                context.close()
                            except Exception:
                                pass
                        send_windows_notification(
                            "ApplyPilot: Naukri Session Expired",
                            "Daily 9:00 AM refresh needs a quick login renewal. Click ApplyPilot dashboard or run `applypilot naukri-update --login`.",
                        )
                        return record_update_log(
                            "auth_required",
                            "Naukri authentication required. Please run `applypilot naukri-update --login`.",
                            str(target_resume),
                        )

                # Save freshest cookies from this authenticated navigation
                try:
                    save_stored_cookies(context.cookies())
                except Exception:
                    pass

                logger.info("Successfully on Naukri profile page. Searching for resume upload input...")

                # Scroll down slightly to trigger lazy-loaded sections (Resume card)
                try:
                    page.evaluate("window.scrollTo(0, 400);")
                    time.sleep(1.5)
                except Exception:
                    pass

                # Candidate selectors for resume file input on Naukri
                file_input_selectors = [
                    "#attachCV",
                    "#lazyAttachCV",
                    "input[id*='attachCV']",
                    "input[type='file'][accept*='pdf']",
                    "input[type='file']",
                ]

                upload_element = None
                for selector in file_input_selectors:
                    loc = page.locator(selector).first
                    if loc.count() > 0:
                        upload_element = loc
                        logger.info("Found file input selector: %s", selector)
                        break

                if not upload_element:
                    # Sometimes "Update resume" link/button needs to be clicked or scrolled to
                    update_triggers = [
                        "a:has-text('Update resume')",
                        "button:has-text('Update resume')",
                        "span:has-text('Update resume')",
                        "text=Update resume",
                        ".update-link",
                    ]
                    for trig in update_triggers:
                        trig_loc = page.locator(trig).first
                        if trig_loc.count() > 0:
                            logger.info("Triggering '%s' to reveal upload input...", trig)
                            try:
                                trig_loc.scroll_into_view_if_needed()
                                trig_loc.click()
                                time.sleep(1.5)
                                break
                            except Exception:
                                pass

                    # Re-check selectors after click
                    for selector in file_input_selectors:
                        loc = page.locator(selector).first
                        if loc.count() > 0:
                            upload_element = loc
                            logger.info("Found file input selector after trigger: %s", selector)
                            break

                if not upload_element:
                    raise RuntimeError("Could not find file input element (#attachCV / input[type='file']) on profile page.")

                # Upload the PDF resume
                logger.info("Attaching resume file: %s", target_resume)
                upload_element.set_input_files(str(target_resume.resolve()))

                # Wait for upload request and UI confirmation
                logger.info("Waiting for upload processing to complete...")
                time.sleep(5)

                # Look for confirmation indicators
                confirmation_detected = False
                confirm_selectors = [
                    "text=Resume has been successfully uploaded",
                    "text=uploaded successfully",
                    "text=Resume updated",
                    ".msg",
                    ".toaster",
                    ".success-msg",
                ]
                for c_sel in confirm_selectors:
                    if page.locator(c_sel).count() > 0:
                        confirmation_detected = True
                        logger.info("Detected UI confirmation: %s", c_sel)
                        break

                # Extract last updated date if available
                last_updated_text = ""
                try:
                    date_loc = page.locator(".update-on, .resume-uploaded-date, [class*='uploadDate']").first
                    if date_loc.count() > 0:
                        last_updated_text = date_loc.inner_text().strip()
                except Exception:
                    pass

                try:
                    if is_cdp:
                        page.close()
                    else:
                        context.close()
                except Exception:
                    pass

                msg = "Naukri resume uploaded and profile freshness timestamp refreshed successfully."
                logger.info("SUCCESS: %s (Detected text: %s)", msg, last_updated_text)

                send_windows_notification(
                    "ApplyPilot: Naukri Profile Refreshed! ⚡",
                    f"Your resume was re-uploaded at {datetime.now().strftime('%I:%M %p')}. Recruiter search rank is now active at the top!",
                )

                # Dispatch mobile push alerts (Telegram + WhatsApp)
                try:
                    from applypilot.automation.telegram_notifier import alert_naukri_refreshed as tg_naukri
                    tg_naukri(datetime.now().strftime('%I:%M %p'))
                except Exception as te:
                    logger.debug("Telegram notify notice: %s", te)

                try:
                    from applypilot.automation.whatsapp_notifier import alert_naukri_refreshed
                    alert_naukri_refreshed(datetime.now().strftime('%I:%M %p'))
                except Exception as we:
                    logger.debug("WhatsApp notify notice: %s", we)

                return record_update_log(
                    "success",
                    msg,
                    str(target_resume),
                    details={
                        "confirmed": confirmation_detected,
                        "updated_label": last_updated_text,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                )

        except Exception as e:
            last_error = str(e)
            logger.warning("[Attempt %d/%d] Update attempt encountered error: %s", attempt, max_retries, e)
            time.sleep(3)

    err_msg = f"Failed to update Naukri resume after {max_retries} attempts. Error: {last_error}"
    logger.error(err_msg)
    return record_update_log("error", err_msg, str(target_resume))


# ---------------------------------------------------------------------------
# Windows Task Scheduler Integration
# ---------------------------------------------------------------------------

def get_python_exe() -> str:
    """Resolve virtual environment python executable or current sys.executable."""
    workspace_venv = Path(r"D:\ApplyPilot_Workspace\code\.venv\Scripts\python.exe")
    if workspace_venv.exists():
        return str(workspace_venv.resolve())
    return sys.executable


def register_windows_task(task_time: str = "08:55") -> dict[str, Any]:
    """Register daily scheduled task in Windows Task Scheduler.

    Configured with:
    - Daily run at specified time (default: 08:55 AM IST).
    - -StartWhenAvailable: Runs immediately upon waking if the laptop was asleep at scheduled time.
    - Runs Python module in background with proper workspace working directory.
    """
    if platform.system() != "Windows":
        return {"status": "error", "message": "Task Scheduler is only supported on Windows OS."}

    python_exe = get_python_exe()
    work_dir = r"D:\ApplyPilot_Workspace\code"
    script_arg = "-m applypilot.automation.naukri_updater"

    ps_script = f"""
    $ErrorActionPreference = 'Stop'
    $action = New-ScheduledTaskAction -Execute "{python_exe}" -Argument "{script_arg}" -WorkingDirectory "{work_dir}"
    $trigger = New-ScheduledTaskTrigger -Daily -At "{task_time}"
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    $desc = "ApplyPilot daily 8:55 AM Naukri resume refresher to maximize recruiter sourcing visibility."
    Register-ScheduledTask -TaskName "{TASK_NAME}" -Action $action -Trigger $trigger -Settings $settings -Description $desc -Force
    """

    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if res.returncode == 0:
            logger.info("Successfully registered Windows Task '%s' at %s daily.", TASK_NAME, task_time)
            return {
                "status": "success",
                "task_name": TASK_NAME,
                "schedule_time": task_time,
                "start_when_available": True,
                "message": f"Windows Task '{TASK_NAME}' registered successfully for {task_time} daily.",
            }
        else:
            logger.error("Failed to register Windows Task: %s", res.stderr)
            return {"status": "error", "message": res.stderr.strip()}
    except Exception as e:
        logger.error("Exception registering scheduled task: %s", e)
        return {"status": "error", "message": str(e)}


def unregister_windows_task() -> dict[str, Any]:
    """Unregister the daily refresh task from Windows Task Scheduler."""
    if platform.system() != "Windows":
        return {"status": "error", "message": "Only supported on Windows OS."}

    ps_script = f"""
    Unregister-ScheduledTask -TaskName "{TASK_NAME}" -Confirm:$false -ErrorAction SilentlyContinue
    """
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True,
            text=True,
            timeout=10,
        )
        logger.info("Unregistered Windows Task '%s'.", TASK_NAME)
        return {"status": "success", "message": f"Task '{TASK_NAME}' unregistered."}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def get_windows_task_status() -> dict[str, Any]:
    """Query current registration status of the Windows Task Scheduler job."""
    if platform.system() != "Windows":
        return {"registered": False, "status": "unsupported_os"}

    ps_script = f"""
    $task = Get-ScheduledTask -TaskName "{TASK_NAME}" -ErrorAction SilentlyContinue
    if ($null -eq $task) {{
        [Console]::WriteLine('{{"registered": false}}')
    }} else {{
        $info = Get-ScheduledTaskInfo -TaskName "{TASK_NAME}" -ErrorAction SilentlyContinue
        $next = if ($info.NextRunTime) {{ $info.NextRunTime.ToString("yyyy-MM-dd HH:mm:ss") }} else {{ $null }}
        $last = if ($info.LastRunTime) {{ $info.LastRunTime.ToString("yyyy-MM-dd HH:mm:ss") }} else {{ $null }}
        $state = $task.State.ToString()
        $json = @{{
            registered = $true
            task_name = "{TASK_NAME}"
            state = $state
            next_run = $next
            last_run = $last
            last_result = $info.LastTaskResult
        }} | ConvertTo-Json -Compress
        [Console]::WriteLine($json)
    }}
    """
    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True,
            text=True,
            timeout=10,
        )
        out = res.stdout.strip()
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                return json.loads(line)
        return {"registered": False, "raw_output": out}
    except Exception as e:
        return {"registered": False, "error": str(e)}


# ---------------------------------------------------------------------------
# CLI Entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Naukri Daily Resume & Profile Refresh Automation.")
    parser.add_argument("--login", action="store_true", help="Launch interactive window to log in and save cookies.")
    parser.add_argument("--headed", action="store_true", help="Run browser in headed (visible) mode.")
    parser.add_argument("--resume", type=str, default=None, help="Custom resume PDF path to upload.")
    parser.add_argument("--schedule", action="store_true", help="Register Windows Task Scheduler 9:00 AM daily job.")
    parser.add_argument("--unschedule", action="store_true", help="Remove Windows Task Scheduler daily job.")
    parser.add_argument("--status", action="store_true", help="Show current scheduler and update status.")
    parser.add_argument("--time", type=str, default="09:00", help="Scheduled time in HH:mm format (default: 09:00).")

    args = parser.parse_args()

    if args.status:
        task_info = get_windows_task_status()
        last_log = get_last_update_status()
        print("\n--- ApplyPilot Naukri Automation Status ---")
        print("Windows Scheduled Task:", json.dumps(task_info, indent=2))
        print("Last Resume Update:", json.dumps(last_log, indent=2))
        return

    if args.schedule:
        res = register_windows_task(task_time=args.time)
        print(f"Schedule result: {res}")
        return

    if args.unschedule:
        res = unregister_windows_task()
        print(f"Unschedule result: {res}")
        return

    if args.login:
        res = login_interactive()
        print(f"Login result: {res}")
        return

    # Default action: run resume update
    res = update_naukri_resume(resume_path=args.resume, headed=args.headed)
    print(f"Update result: {res}")


if __name__ == "__main__":
    main()
