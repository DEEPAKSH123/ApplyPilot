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
   - Every modification to code, search configurations, and scoring logic must be committed to git (`git add -A && git commit`) and backed up to `C:\Users\Admin\.applypilot_backups\`.

3. **LaTeX Native Compilation & Template Integrity:**
   - Resumes must adhere to Deepak's Jake LaTeX Resume template (`C:\Users\Admin\.applypilot\resume.tex`).
   - Compilation to vector `.pdf` is handled natively by `tectonic.exe` in `C:\Users\Admin\ApplyPilot\.venv\Scripts\tectonic.exe`.
   - Never fabricate skills, projects, or metrics not present in Deepak's master profile.

4. **10-Day Recency Filter:**
   - Discovery strictly enforces `max_posted_days <= 10` and drops `"Posted 30+ Days Ago"`.

5. **Pre-Ingestion Seniority Gatekeeper (`_title_ok`):**
   - Filters out `Director`, `VP`, `Manager`, `Lead`, `Principal`, `Staff`, `Architect`, `Scientist`, `PM`, `QA`, and `Intern` **before** detail extraction to prevent flooding the database with out-of-scope roles.

6. **Performance & Concurrency:**
   - Employer scraping runs with `workers = 4` parallel threads.
   - Detail extraction runs with `max_workers = 8` parallel threads.
   - Search depth is capped at 3 pages (max 60 postings) per employer query with smart early-stopping on old postings.
   - Daily runs must complete in **under 4 minutes**.

---

## 2. Key Directories & Backups

| Resource | Path |
| :--- | :--- |
| **Codebase Repo** | `C:\Users\Admin\ApplyPilot` (Git branch `main`) |
| **User Config & Active DB** | `C:\Users\Admin\.applypilot\` (`applypilot.db`, `profile.yaml`, `searches.yaml`, `.env`) |
| **Backup Snapshots** | `C:\Users\Admin\.applypilot_backups\` |
| **Tailored Resumes (.tex & .pdf)** | `C:\Users\Admin\.applypilot\tailored_resumes\` |
| **Cover Letters (.txt & .pdf)** | `C:\Users\Admin\.applypilot\cover_letters\` |
| **Tectonic LaTeX Compiler** | `C:\Users\Admin\ApplyPilot\.venv\Scripts\tectonic.exe` |

---

## 3. Latest Git Commit & Backups
- **Git Commit:** `68660dd` (*feat: optimize India backend job discovery, title gatekeeping, LaTeX pdf compiler, and multi-threading*)
- **Snapshot Backup:** `C:\Users\Admin\.applypilot_backups\snapshot_20261108_122032\`
