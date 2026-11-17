# ApplyPilot - Working & Operational Status

This document tracks the live operational status, active agents, running services, and protocols for any agent working on the ApplyPilot workspace.

---

## 1. Active Service & Process Status

* **Dashboard Web Service:**
  * **Status:** `ACTIVE / RUNNING`
  * **Port:** `8765`
  * **URL:** [http://localhost:8765](http://localhost:8765)
  * **Root Directory:** `D:\ApplyPilot_Workspace\code`
  * **Virtual Environment:** `D:\ApplyPilot_Workspace\code\.venv`
  * **Start Command:**
    ```powershell
    cd /d "D:\ApplyPilot_Workspace\code"
    .venv\Scripts\python.exe -m applypilot dashboard --port 8765 --no-browser
    ```
    *(Or execute `D:\ApplyPilot_Workspace\start_applypilot.bat`)*

* **Database & Data Root:**
  * `APPLYPILOT_DIR=D:\ApplyPilot_Workspace\data`
  * Active SQLite DB: `D:\ApplyPilot_Workspace\data\applypilot.db`
  * Pipeline Opportunities: `D:\ApplyPilot_Workspace\data\opportunities.csv`

---

## 2. Invariants & Rules for Any Active Agent

1. **Service Uptime Invariant:**
   * Whenever an agent is actively working in this workspace, the ApplyPilot dashboard service **must be running** on port `8765`.
   * Check service status before completing tasks:
     ```powershell
     Get-NetTCPConnection -LocalPort 8765 -ErrorAction SilentlyContinue
     ```
   * If the service is stopped or port 8765 is not listening, the agent must start it immediately.

2. **Autonomous Execution Rule:**
   * **Never** ask the user to open a terminal or run background server commands manually.
   * All process management, database inspection, and pipeline runs must be handled autonomously by the agent.

3. **Candidate Persona Guardrails (Deepak S H):**
   * Experience: ~1.3 YOE (SDE-I Backend @ Meesho, RVCE CGPA 8.92).
   * **Strict Seniority Filter:** Only target 0–3 YOE roles (Freshers, SDE-1, early SDE-2). Reject Senior/Lead/Staff/Manager roles.
   * **Location Policy:** Bengaluru, Pune, Hyderabad, Remote India, Worldwide/Anywhere Remote. Reject US/UK/Canada-restricted roles.

4. **Browser & UI Safety Rules:**
   * Never use programmatic `window.open(...)` from JavaScript—Brave Shields silently blocks it.
   * Render links as standard HTML `<a href="..." target="_blank" rel="noopener noreferrer">`.
   * On Windows, prefer `os.startfile(url)` for OS browser launches.
   * Never auto-apply or email recruiters without explicit human confirmation.

---

## 3. Standard Operational Commands

* **Start Dashboard:**
  ```powershell
  cd /d "D:\ApplyPilot_Workspace\code"
  & .venv\Scripts\python.exe -m applypilot dashboard --port 8765 --no-browser
  ```
* **Run Daily Pipeline:**
  ```powershell
  & "D:\ApplyPilot_Workspace\code\.venv\Scripts\applypilot.exe" run --workers 4 --min-score 7
  ```
* **Export Opportunities CSV:**
  ```powershell
  & "D:\ApplyPilot_Workspace\code\.venv\Scripts\applypilot.exe" export
  ```

---

## 4. Current Work Log

| Timestamp | Agent / Context | Action / Status |
|---|---|---|
| 2026-11-11 08:06 IST | Antigravity Agent | Created `WORKING.md` tracking protocol & started ApplyPilot dashboard on port 8765 (HTTP 200 OK). |
| 2026-11-11 08:47 IST | Antigravity Agent | Restarted ApplyPilot Dashboard on port 8765 (PID 27528, HTTP 200 OK) following server update. |

