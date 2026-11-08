# ApplyPilot – India Tech Platform Architecture & Customizations

> **Owner:** Deepak S H (deepakshkarkala@gmail.com)  
> **Candidate Profile:** Backend Engineer / SDE-I (1.3+ years experience, started Jan 2025 at Meesho)  
> **Core Stack:** Java, Golang, Kafka, Redis, Spring Boot, MySQL, GCP, BigQuery  
> **Target Scope:** SDE-I / SDE-II Backend Roles in Bengaluru, Pune, Hyderabad, and Remote India  

---

## 1. Permanent Architectural Rules & Guarantees

1. **Human Approval Boundary (STRICT):**
   - The platform **NEVER** auto-submits applications or sends automated messages without explicit human confirmation.
   - Applications, referral requests, and external communications must be presented to Deepak for review first.

2. **Always Save & Version Control Changes:**
   - Every modification to code, search configurations, and scoring logic must be committed to git (`git add -A && git commit`) and backed up to `D:\ApplyPilot_Workspace\backups\`.

3. **LaTeX Native Compilation & Template Integrity:**
   - Resumes adhere strictly to Deepak's Jake LaTeX Resume template (`D:\ApplyPilot_Workspace\data\resume.tex`).
   - Compilation to vector `.pdf` is handled natively by `tectonic.exe` in `D:\ApplyPilot_Workspace\code\.venv\Scripts\tectonic.exe` (or dynamic lookup via `TECTONIC_PATH` / virtualenv `Scripts/`).
   - Never fabricate skills, projects, or metrics not present in Deepak's master profile.

4. **10-Day Recency Filter:**
   - Discovery strictly enforces `max_posted_days <= 10` and drops `"Posted 30+ Days Ago"`.

5. **Pre-Ingestion Seniority Gatekeeper (`_title_ok`):**
   - Filters out `Director`, `VP`, `Manager`, `Lead`, `Principal`, `Staff`, `Architect`, `Scientist`, `PM`, `QA`, and `Intern` **before** detail extraction to prevent flooding the database with out-of-scope roles.

6. **Multi-Source Discovery & Error Isolation:**
   - Pipeline discovers across Workday portals, Direct ATS boards (Greenhouse, Lever, SmartRecruiters, Ashby), and JobSpy aggregators (LinkedIn, Indeed, Glassdoor).
   - Sources are independently toggleable in `searches.yaml` under `sources:`.
   - Cross-source deduplication prevents repeated postings across aggregators and direct employer feeds.
   - A failure in one source (e.g. anti-bot block) is gracefully logged and isolated without halting other sources.

7. **Automated CSV Spreadsheet Reporting:**
   - Every pipeline run automatically exports or updates `D:\ApplyPilot_Workspace\data\opportunities.csv` with Company, Title, Location, Rating (Fit Score 1–10), Apply Link, Tailored Resume PDF, Cover Letter PDF, Discovered At, Scored At, and Match Reasoning.
   - Also directly runnable via `applypilot export`.

8. **Performance & Concurrency:**
   - Employer scraping runs with `workers = 4` parallel threads.
   - Detail extraction runs with `max_workers = 8` parallel threads.
   - Search depth is capped at 3 pages (max 60 postings) per employer query with smart early-stopping on old postings.
   - Daily runs must complete in **under 4 minutes**.

---

## 2. Key Directories & Canonical Paths

| Resource | Path |
| :--- | :--- |
| **Workspace Root** | `D:\ApplyPilot_Workspace\` |
| **Codebase Repo** | `D:\ApplyPilot_Workspace\code\` (Git branch `main`) |
| **User Data & Active DB** | `D:\ApplyPilot_Workspace\data\` (`applypilot.db`, `profile.json`, `searches.yaml`, `.env`) |
| **Environment Variable** | `APPLYPILOT_DIR=D:\ApplyPilot_Workspace\data` |
| **Virtual Environment** | `D:\ApplyPilot_Workspace\code\.venv\` |
| **Tectonic LaTeX Compiler** | `D:\ApplyPilot_Workspace\code\.venv\Scripts\tectonic.exe` |
| **Opportunities Spreadsheet**| `D:\ApplyPilot_Workspace\data\opportunities.csv` |
| **Tailored Resumes (.tex & .pdf)** | `D:\ApplyPilot_Workspace\data\tailored_resumes\` |
| **Cover Letters (.txt & .pdf)** | `D:\ApplyPilot_Workspace\data\cover_letters\` |
| **Backup Snapshots** | `D:\ApplyPilot_Workspace\backups\` |

---

## 3. Verified Employer Registry

Stored dynamically in `src/applypilot/config/employers.yaml`:
- **Workday Enterprise:** Cisco, Mastercard, Visa, Autodesk, Nvidia, Qualcomm, Salesforce, Dell, Adobe, Intuit, Walmart Global Tech, etc.
- **Direct ATS Boards (Greenhouse, Lever, SmartRecruiters):** Groww, Razorpay, InMobi, CRED, Freshworks, Rubrik, Stripe, Coinbase, Databricks, Cloudflare, Elastic, Twilio, MongoDB, Okta, etc.
- Tested and verified: zero guessed slugs; all endpoints return live career opportunities.


---

## 4. Latest Git Commit & Snapshot Backups
- **Git Commit:** `47fdc02` (*feat: complete safe migration to D:\ApplyPilot_Workspace, update config/paths to dynamic env, and add automatic CSV pipeline export*)
- **Snapshot Backup:** `D:\ApplyPilot_Workspace\backups\snapshot_20261108_125849_migrated_D\`
