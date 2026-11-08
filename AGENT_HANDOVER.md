# AI Agent Continuation Prompt & Handover Protocol

Copy and paste the prompt below into any new AI agent session (Antigravity, Claude, ChatGPT, Cursor, etc.) to immediately resume work without losing context.

---

```markdown
You are assisting Deepak S H on his Job Search Automation Platform (ApplyPilot).

## Core Identity & Constraints:
- Candidate: Deepak S H (SDE-I Backend @ Meesho, 1.3y exp, RVCE CSE 8.92 CGPA).
- Stack: Java, Golang, Kafka, Redis, Spring Boot, MySQL, GCP, Distributed Systems.
- Target Roles: SDE-I / SDE-II Backend in Bengaluru, Pune, Hyderabad, and Remote India.
- CRITICAL BOUNDARY: NEVER auto-apply or message recruiters without explicit human approval.
- ALWAYS commit changes to git and create a snapshot backup before completing work.

## Canonical Locations (Migrated to D: Drive):
- Workspace Root: D:\ApplyPilot_Workspace\
- Codebase: D:\ApplyPilot_Workspace\code (Git branch: main, virtualenv: .venv)
- User Data & Database: D:\ApplyPilot_Workspace\data (applypilot.db, profile.json, searches.yaml, .env)
- Environment Variable: APPLYPILOT_DIR=D:\ApplyPilot_Workspace\data
- Master Resume: D:\ApplyPilot_Workspace\data\resume.tex (Jake LaTeX template) & resume.pdf
- Opportunities CSV: D:\ApplyPilot_Workspace\data\opportunities.csv
- Backup Snapshots: D:\ApplyPilot_Workspace\backups\
- Architecture Guide: D:\ApplyPilot_Workspace\code\ARCHITECTURE.md

## Engine Details:
- LLM: gemini-3.5-flash-lite (configured in D:\ApplyPilot_Workspace\data\.env)
- LaTeX Compiler: D:\ApplyPilot_Workspace\code\.venv\Scripts\tectonic.exe
- Headless Browser: C:\Program Files\Google\Chrome\Application\chrome.exe
- Filters: <= 10 days old postings, title seniority gatekeeper (_title_ok in workday.py & ats.py)
- Sources: Workday registry, Direct ATS (Greenhouse, Lever, SmartRecruiters, Ashby), JobSpy aggregators

## Standard Execution Commands:
- Run full daily pipeline (with auto-CSV export):
  & "D:\ApplyPilot_Workspace\code\.venv\Scripts\applypilot.exe" run --workers 4 --min-score 7
- Export opportunities CSV standalone:
  & "D:\ApplyPilot_Workspace\code\.venv\Scripts\applypilot.exe" export
- Inspect top-ranked jobs:
  & "D:\ApplyPilot_Workspace\code\.venv\Scripts\python.exe" -c "import sqlite3; c=sqlite3.connect(r'D:\ApplyPilot_Workspace\data\applypilot.db').cursor(); print([(r[0], r[1], r[2]) for r in c.execute('SELECT site, title, fit_score FROM jobs WHERE fit_score>=7 ORDER BY fit_score DESC').fetchall()])"
- Check git & working tree:
  cd "D:\ApplyPilot_Workspace\code"; git status

Please read D:\ApplyPilot_Workspace\code\ARCHITECTURE.md, check the current database and git status, and proceed with the next task requested by the user.
```
