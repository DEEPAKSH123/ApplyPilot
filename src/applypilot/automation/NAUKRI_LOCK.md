# ⚠️ CRITICAL RULE: DO NOT MODIFY NAUKRI AUTOMATION CODE ⚠️

## Protected Files
1. `D:\ApplyPilot_Workspace\code\src\applypilot\automation\naukri_updater.py`
2. `D:\ApplyPilot_Workspace\data\Deepak_S_H_Resume.pdf`
3. Windows Scheduled Task: `ApplyPilot_Naukri_Daily_Refresh`

## Production State (100% Verified & Working)
- **Daily Execution Time:** `08:55:00 AM IST`
- **Resume Target File:** `Deepak_S_H_Resume.pdf`
- **File Name Standard:** Must ALWAYS stay as `Deepak_S_H_Resume.pdf` (never rename to generic `resume.pdf` or include dynamic timestamps).
- **Execution Engine:** Uses Brave browser via remote CDP port 9222 with fallback to persistent profile.
- **Task Scheduler Configuration:** `-StartWhenAvailable` is active so if laptop is closed/asleep at 8:55 AM, it triggers immediately upon wake.

## Instruction for Any AI Agent or Contributor
**DO NOT TOUCH OR REFACTOR** `naukri_updater.py` or the scheduled task configuration.
It is running in production and verified 100% working as requested by Deepak.
