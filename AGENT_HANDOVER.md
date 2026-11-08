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

## Environment & Codebase Locations:
- Codebase: C:\Users\Admin\ApplyPilot (Git branch: main, virtualenv: .venv)
- User Config & Database: C:\Users\Admin\.applypilot\ (applypilot.db, profile.yaml, searches.yaml, .env)
- Master Resume: C:\Users\Admin\.applypilot\resume.tex (Jake LaTeX template) & resume.pdf
- Backup Snapshots: C:\Users\Admin\.applypilot_backups\
- Architecture Guide: C:\Users\Admin\ApplyPilot\ARCHITECTURE.md

## Engine Details:
- LLM: gemini-3.5-flash-lite (via C:\Users\Admin\.applypilot\.env)
- LaTeX Compiler: C:\Users\Admin\ApplyPilot\.venv\Scripts\tectonic.exe
- Headless Browser: C:\Program Files\Google\Chrome\Application\chrome.exe
- Filters: <= 10 days old postings, title seniority gatekeeper (_title_ok in workday.py)

## Standard Execution Commands:
- Run full daily pipeline:
  & "C:\Users\Admin\ApplyPilot\.venv\Scripts\applypilot.exe" run --workers 4 --min-score 7
- Inspect top-ranked jobs:
  & "C:\Users\Admin\ApplyPilot\.venv\Scripts\python.exe" -c "import sqlite3; c=sqlite3.connect(r'C:\Users\Admin\.applypilot\applypilot.db').cursor(); print([(r[0], r[1], r[2]) for r in c.execute('SELECT site, title, fit_score FROM jobs WHERE fit_score>=7 ORDER BY fit_score DESC').fetchall()])"
- Check git & working tree:
  cd "C:\Users\Admin\ApplyPilot"; git status

Please read C:\Users\Admin\ApplyPilot\ARCHITECTURE.md, check the current database and git status, and proceed with the next task requested by the user.
```
