# ⚡ ApplyPilot — Naukri Daily 9:00 AM Resume Refresher
## Complete 1-Pager Operation & Troubleshooting Guide

> **Why 9:00 AM IST Matters:** Naukri’s candidate search ranking heavily favors candidates whose profiles were updated within the last 24 hours. Re-uploading your resume every morning right before talent acquisition teams start searching ensures Deepak S H ranks at the top of candidate queues every single business day.

---

## 1. System Requirements & Prerequisites Checklist

| Component | Requirement | Status / Location |
| :--- | :--- | :--- |
| **Operating System** | Windows 10 or Windows 11 | Supported (Native Windows Task Scheduler) |
| **Browser** | Brave Browser (or Chromium) | `C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe` |
| **Python Environment** | Python 3.11 with Playwright | `D:\ApplyPilot_Workspace\code\.venv\Scripts\python.exe` |
| **Master Resume PDF** | Standard ATS Resume PDF | `D:\ApplyPilot_Workspace\data\resume.pdf` |
| **Naukri Credentials** | Active Naukri candidate account | One-time browser login (Saved in `data/brave_profile`) |
| **Internet Access** | Active connection at 9:00 AM | Required for uploading resume to Naukri |

---

## 2. How to Use (3 Convenient Modes)

### Mode A: 100% Hands-Free (Default)
You don’t have to do anything. Every morning at **9:00 AM IST**, Windows Task Scheduler silently runs the update in the background. If your laptop is asleep or closed at 9:00 AM, Windows automatically executes the update **the moment you open the lid**.

### Mode B: 1-Click from the Web Dashboard (`http://localhost:8765`)
* Look at the top navigation bar for the **`[⚡ Naukri: 9 AM Active]`** pill.
* Click it anytime to trigger an instantaneous on-demand refresh.
* It changes to **`[✓ Naukri: Refreshed Today]`** with a confirmation toast.

### Mode C: Command-Line Shortcuts (CLI)
From the workspace, you can manage the automation with clean commands:
* **Check Status:** `applypilot naukri-schedule --status`
* **Trigger Immediate Refresh:** `applypilot naukri-update`
* **One-Time Login / Cookie Renewal:** `applypilot naukri-update --login`
* **Change Scheduled Time:** `applypilot naukri-schedule --time 08:30`
* **Disable/Uninstall Scheduler:** `applypilot naukri-schedule --uninstall`

---

## 3. One-Time Setup: Connecting Your Naukri Account

If you haven't logged into Naukri inside ApplyPilot's Brave automation profile yet:

1. Run this single command:
   ```powershell
   applypilot naukri-update --login
   ```
2. A Brave window will open directly to `https://www.naukri.com/mnjuser/profile`.
3. Log in normally using your Google account, OTP, or email and password.
4. As soon as your profile loads, ApplyPilot automatically captures and locks your session cookies to `D:\ApplyPilot_Workspace\data\naukri_session.json`.
5. The browser closes and the automation is fully activated. You will never need to log in again unless cookies expire.

---

## 4. Step-by-Step Troubleshooting Playbook

### Scenario 1: "Auth Required / Session Expired" Notification
* **Symptom:** You receive a desktop notification stating *"Naukri session expired or not logged in"* or log displays `auth_required`.
* **Cause:** Naukri periodically expires session tokens (typically every 30 to 60 days).
* **Fix:**
  1. Click **`[⚡ Naukri: 9 AM Active]`** on the dashboard or run `applypilot naukri-update --login`.
  2. Sign in once in the Brave window that appears.
  3. Cookies will immediately refresh and daily automations will resume smoothly.

---

### Scenario 2: "My laptop was asleep at 9:00 AM. Did the update run?"
* **Symptom:** You opened your laptop at 9:30 AM and want to know if it ran.
* **Explanation:** The task is registered with the `-StartWhenAvailable` Windows flag. This explicitly tells Windows: *"If the scheduled start time was missed because the PC was sleeping or turned off, run the task as soon as possible after wake-up."*
* **Verification:**
  1. Open the dashboard at `http://localhost:8765` — the pill will show `[✓ Naukri: Refreshed Today]`.
  2. Or run:
     ```powershell
     applypilot naukri-schedule --status
     ```
  3. Inspect `D:\ApplyPilot_Workspace\data\naukri_update_log.json` to see the exact timestamp.

---

### Scenario 3: "I have a new resume version. Where do I update it?"
* **How it works:** ApplyPilot always pulls your master ATS resume from:
  ```
  D:\ApplyPilot_Workspace\data\resume.pdf
  ```
* **Step:**
  1. Simply overwrite or save your newly compiled resume to `D:\ApplyPilot_Workspace\data\resume.pdf`.
  2. Run `applypilot naukri-update` to push it to Naukri immediately without waiting for tomorrow morning.

---

### Scenario 4: "Naukri redesigned their UI and the upload button moved"
* **How it works:** `naukri_updater.py` utilizes a resilient multi-tier selector cascade:
  1. `#attachCV` (Standard desktop file input)
  2. `#lazyAttachCV` (Lazy-loaded dynamic file input)
  3. `input[id*='attachCV']`
  4. `input[type='file'][accept*='pdf']`
  5. Fallback trigger click on `.update-link` or `Update resume` span before attaching.
* **If Naukri updates DOM completely:** Check the log file at `D:\ApplyPilot_Workspace\data\logs\naukri_updater.log` to see the exact step where it paused, and update the selector list in `naukri_updater.py`.

---

### Scenario 5: How to Inspect or Manage via Windows Task Scheduler GUI
If you ever want to see or modify the task directly inside Windows:
1. Press `Win + R`, type `taskschd.msc`, and press **Enter**.
2. Click **Task Scheduler Library** on the left panel.
3. Look for **`ApplyPilot_Naukri_Daily_Refresh`** in the middle list.
4. Right-click -> **Run** to test it manually, or check the **History** tab to see past execution times.

---

## 5. Diagnostic & Health-Check Commands Reference

| Action | Command |
| :--- | :--- |
| **Check Task Scheduler Status** | `applypilot naukri-schedule --status` |
| **Run Update Right Now (Headless)** | `applypilot naukri-update` |
| **Run Update in Visible Browser** | `applypilot naukri-update --headed` |
| **Renew / Refresh Login Cookies** | `applypilot naukri-update --login` |
| **Change Daily Run Time** | `applypilot naukri-schedule --time 08:45` |
| **Inspect Detailed Logs** | `Get-Content "D:\ApplyPilot_Workspace\data\logs\naukri_updater.log" -Tail 20` |
| **View Last Update JSON Payload** | `Get-Content "D:\ApplyPilot_Workspace\data\naukri_update_log.json"` |
