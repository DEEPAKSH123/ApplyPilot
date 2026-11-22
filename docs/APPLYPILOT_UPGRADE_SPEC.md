# ApplyPilot v2 Upgrade Specification (Antigravity Execution Blueprint)

**Target Repository:** `DEEPAKSH123/ApplyPilot` (base branch: `main`, commit `b05254c`)  
**Feature Branch:** `feat/anti-job-board-v2-and-ui-fix`  
**Candidate Profile Constraints:** Target roles are Backend Software Engineer (Java, Golang, Distributed Systems) in Bengaluru or Remote. Never fabricate metrics or experience. Preserve the Two-Email Guardrail (`PRIMARY_EMAIL=deepakshkarkala@gmail.com` for referrals/outreach; `SECONDARY_EMAIL=deepaksh.apply@gmail.com` for expired 48h Tier-1 portal fallbacks).

---

## Phase 0: Pre-Flight Inspection, Repo Hygiene & SQLite Concurrency

Before modifying business logic, Antigravity must read the target modules and fix repository hygiene and database locking risks.

1. **Inspect Existing Implementations:**  
   Read the current code in:
   - `src/applypilot/database.py`
   - `src/applypilot/pipeline.py`
   - `src/applypilot/dashboard/server.py`
   - `src/applypilot/discovery/ats.py`
   - `src/applypilot/discovery/workday.py`
   - `src/applypilot/discovery/seed_startups.py`
   - `src/applypilot/networking/followup_engine.py`
   - `src/applypilot/networking/gmail_drafter.py`
   - `src/applypilot/enrichment/email_tracker.py`
   - `src/applypilot/scoring/validator.py`
   - `src/applypilot/scoring/pdf.py`
   - `src/applypilot/automation/poller.py`

2. **Clean Root Directory Clutter:**  
   - Delete `scratch_check.py` (435 bytes) from the repository root and append `scratch_*.py` to `.gitignore`.  
   - Move `draft_headhunters.py` (3,589 bytes) and `log_headhunters_crm.py` (2,994 bytes) from the root into `scripts/` (creating `scripts/` if absent) and update any imports if needed.

3. **Enforce SQLite WAL Mode (`src/applypilot/database.py`):**  
   - Locate `get_connection()` (and any direct `sqlite3.connect(...)` calls across `followup_engine.py`, `dashboard/server.py`, and `email_tracker.py`).  
   - Set `timeout=30.0` on all connections and execute immediately upon connection creation:
     ```sql
     PRAGMA journal_mode = WAL;
     PRAGMA synchronous = NORMAL;
     PRAGMA busy_timeout = 30000;
     ```
   - **Why:** Prevents `sqlite3.OperationalError: database is locked` when `poller.py` (`workers=4`) runs concurrently with the dashboard UI and `email_tracker.py`.

---

## Phase 1: Dashboard UI Recovery & Decoupling (`src/applypilot/dashboard/`)

Currently `dashboard/server.py` is 456,602 bytes (~29.1% of the entire repository) because HTML, CSS, and JavaScript are embedded inside Python strings, making syntax errors and failed renders likely.

1. **Extract Static Assets:**  
   - Create `src/applypilot/dashboard/static/` containing `index.html`, `styles.css`, and `app.js`.  
   - Move all inline `<style>`, `<script>`, and HTML markup out of `dashboard/server.py` into those static files.  
   - Update `server.py` HTTP GET handler to serve `/`, `/static/styles.css`, and `/static/app.js` with proper `Content-Type` headers (`text/html`, `text/css`, `application/javascript; charset=utf-8`) and `Cache-Control: no-store` for local dev.

2. **Harden API Endpoints & Frontend Error Handling:**  
   - Wrap all JSON API routes (`/api/jobs`, `/api/followups/due`, `/api/followups/<job_id>/ack`, `/api/stats`) in try/except blocks that always return valid JSON (`{"status": "error", "message": "..."}`) rather than broken HTML tracebacks.  
   - Verify `init_db()` runs automatically on server startup so missing tables/columns (like `referral_followup_state` or new v2 tables) never trigger HTTP 500s.  
   - In `app.js`, ensure every `fetch()` call checks `if (!res.ok)` and renders a visible non-blocking error banner in the UI instead of crashing the rest of the page render.

3. **Add `GET /api/skills/demand` Endpoint:**  
   - Expose top recurring required backend technologies from Score 8+ jobs over the last 7 days (see Phase 6) so the UI renders a "Top 3 Market Skills This Week" card.

---

## Phase 2: Harden Direct ATS Discovery (`discovery/ats.py` & `discovery/workday.py`)

Directly polling company career pages catches roles at Hour 0 rather than waiting 6–18 hours for LinkedIn batch alerts. Update `ats.py` and `workday.py` to enforce the verified public API contracts and edge cases across ATS vendors:

| ATS Module / Vendor | Endpoint & Query Rules | Required Parsing & Bug Fixes |
| :--- | :--- | :--- |
| **Greenhouse (`ats.py`)** | `GET https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true` | Decode double-encoded HTML entities (`html.unescape()`) in `content` before stripping HTML tags. Parse `first_published` and `updated_at` ISO timestamps. |
| **Lever (`ats.py`)** | `GET https://api.lever.co/v0/postings/{slug}?mode=json` (fallback to `https://api.eu.lever.co/v0/postings/{slug}?mode=json` if 404) | Paginate via `skip`/`limit`. Map `text` -> `title`, `hostedUrl` / `applyUrl` -> URLs, and divide `createdAt` (epoch ms) by 1000 for UTC timestamp. Extract `salaryRange` if present. |
| **Ashby (`ats.py`)** | `GET https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true` | Filter out `isListed == False` (unlisted/private roles). Store `compensation.summaryComponents[]` (`minValue`, `maxValue`, `currencyCode`, `interval`). Keep geographic eligibility distinct from `isRemote`. |
| **SmartRecruiters (`ats.py`)** | `GET https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100&offset={N}` | Do not assume HTTP 200 means valid slug (invalid slugs return 200 with empty list). Fetch detail endpoint `/postings/{id}` for job descriptions (`jobAd.sections.*.text`) only for title-matched engineering roles. |
| **Workday (`workday.py`)** | `POST https://{tenant}.wd{N}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs` | Enforce max `limit=20` (higher returns HTTP 400). Cache total from page 1 only (pages 2+ return `total: 0`). Strip locale segments like `/en-US/`. Fetch detail endpoint when `locationsText` is vague (e.g., `"2 Locations"`). |
| **Personio & Recruitee (`ats.py`)** | Personio: `GET https://{slug}.jobs.personio.de/xml`<br>Recruitee: `GET https://{slug}.recruitee.com/api/offers/` | Add lightweight fetchers using stdlib `xml.etree.ElementTree` (Personio) and JSON (Recruitee). |

- **ATS Auto-Slug Discovery Helper:**  
  Add `detect_ats_board(company_slug: str)` in `ats.py` that probes Greenhouse, Lever, and Ashby in order (checking HTTP 200 and non-empty valid payload) when a new company is discovered via `seed_startups.py`. Keep HTTP requests polite with a descriptive User-Agent header and response caching.

---

## Phase 3: Pre-Post Startup Funding & YC Radar (`src/applypilot/discovery/seed_startups.py`)

Startups that recently raised capital hire roughly 30%+ of their engineering payroll early and fill ~30% of roles at small teams via direct sourcing before a public JD exists. Upgrade `seed_startups.py` to ingest free funding and launch signals:

1. **New SQLite Table (`funding_leads` in `database.py`):**
   ```sql
   CREATE TABLE IF NOT EXISTS funding_leads (
       id INTEGER PRIMARY KEY AUTOINCREMENT,
       lead_hash TEXT UNIQUE NOT NULL,
       company TEXT NOT NULL,
       source TEXT NOT NULL,           -- 'yc_oss' | 'hn_launch' | 'inc42' | 'yourstory' | 'isn' | 'ettech' | 'techcrunch'
       headline TEXT NOT NULL,
       article_url TEXT NOT NULL,
       round_amount TEXT DEFAULT '',
       product_focus TEXT DEFAULT '',
       target_team_pitch TEXT DEFAULT '',
       ats_provider TEXT DEFAULT '',   -- 'greenhouse' | 'lever' | 'ashby' | ''
       ats_slug TEXT DEFAULT '',
       status TEXT NOT NULL DEFAULT 'NEW', -- 'NEW' | 'OUTREACH_DRAFTED' | 'PITCHED' | 'SKIPPED'
       discovered_at TEXT NOT NULL
   );
   ```

2. **Feed Sources to Poll:**
   - **Y Combinator (`yc-oss/api`):** Fetch `https://yc-oss.github.io/api/companies/hiring.json` (actively hiring YC companies) and recent batch endpoints (`batches/{season}-{year}.json`). Filter for active companies with backend/infra/AI/fintech tags.
   - **Hacker News (`hnrss.org`):** Poll `https://hnrss.org/launches` ("Launch HN") and `https://hnrss.org/whoishiring/jobs`.
   - **Startup Funding RSS Feeds (Verified HTTP 200):** Poll `https://inc42.com/feed/`, `https://yourstory.com/feed`, `https://indianstartupnews.com/rss` (note `/rss`, not `/feed`), `https://economictimes.indiatimes.com/tech/funding/rssfeeds/78570540.cms`, and `https://techcrunch.com/category/startups/feed/`. Do not hardcode `entrackr.com/feed` (404); if adding Entrackr, probe `https://entrackr.com/rss` and skip gracefully on non-200.

3. **Deterministic Headline Filtering & Extraction:**
   - Because RSS feeds are rolling 20–50 item windows, persist every run into `funding_leads` using `INSERT OR IGNORE` on `lead_hash`.
   - **Positive match regex:** `\b(raise|raised|bags|secures|nets|funding)\b` (case-insensitive).
   - **Negative exclusion regex:** `\b(fund|ipo|q[1-4]|loss|profit|revenue|in talks|looks to|plans to|weekly|digest|startups raised)\b` (case-insensitive).
   - For passing leads (and `yc_oss` / `hn_launch` items), call `llm.py` to extract `company`, `round_amount`, and a 1-sentence `product_focus` (what they are building next), and automatically probe `detect_ats_board(slug)`.
   - Expose `GET /api/funding-leads` and `POST /api/funding-leads/{id}/status` in `dashboard/server.py` so noisy false positives (~15% in RSS headline filtering) can be dismissed in one click.

---

## Phase 4: Sub-80-Word Founder/EM Pitch & Optional SMTP Verification

Direct emails to a named Founder, CTO, or Engineering Manager skip ATS knockout filters and the 7.4-second recruiter skim. Outreach benchmarks show messages under 80 words with one clear ask yield stronger replies.

1. **Add `generate_founder_pitch()` in `src/applypilot/networking/gmail_drafter.py`:**
   - Strictly enforce `word_count <= 80` (truncate or re-prompt if LLM exceeds 80 words).
   - **Required 3-part structure:**
     - **Specific Hook:** Reference their funding lead's `product_focus` or specific engineering problem (never generic praise).
     - **Concrete Backend Proof:** Pick 1 verifiable Meesho highlight matching their stack (e.g., Go concurrency & adaptive RPS reducing reconciliation from 50–60h to 2–3h, or 150K+ orders/day & ~1,000 RPS payment workflows with 40% fewer DB lookups at 300ms SLA).
     - **Clickable Link + Single Ask:** Include a live clickable URL (`https://github.com/DEEPAKSH123` or specific repo/write-up) and ask for a 15-minute technical chat.
   - **Guardrail:** Reject drafting to generic prefixes (`jobs@`, `careers@`, `hr@`, `info@`, `talent@`) inside `generate_founder_pitch()`.

2. **Optional Pre-Send Email Verification (`src/applypilot/enrichment/email_verifier.py`):**
   - Add a lightweight adapter wrapping `reacherhq/check-if-email-exists` (configurable via `REACHER_API_URL`, e.g., `http://localhost:8080/v0/check_email` when running `reacherhq/backend:latest` via Docker with port 25/SOCKS5).
   - If `REACHER_API_URL` is configured, verify guessed founder emails before `gmail_drafter.py` creates a Gmail draft: skip if `is_reachable == "invalid"`, flag warning if `smtp.is_catch_all == True`. If `REACHER_API_URL` is unset, degrade gracefully without blocking drafts.

---

## Phase 5: Post-Interview Anti-Ghosting & Dual-Email Sync

61% of candidates report being ghosted after interviews, and 57% expect updates within 3 days. Currently, `followup_engine.py` clears `next_due_at` when `REPLIED_ACTIVE` is reached.

1. **Extend ReferralFollowUpEngine States (`src/applypilot/networking/followup_engine.py`):**  
   Add three post-reply lifecycle states (preserving all existing states and tests in `test_followup_engine.py`):
   - **`OA_OR_SCREEN_PENDING`:** Triggered when `email_tracker.py` classifies an incoming email as `oa` or `AI-screen invite`. Sets `next_due_at = now + 48 hours` as an actionable completion reminder.
   - **`INTERVIEW_ROUND_COMPLETED`:** Triggered manually via CLI (`applypilot interview-done <job_id> --contact "<name>"`), Dashboard button, or automatically by `calendar/scheduler.py` once a linked interview calendar event passes its end time.
     - *Action 1 (T + 2 hours):* Queue short thank-you note draft.
     - *Action 2 (T + 3 business days):* Queue polite post-interview status check-in (`POST_INTERVIEW_DAY_3`).
     - *Action 3 (T + 10 business days):* Queue final check-in (`POST_INTERVIEW_FINAL`) before transitioning to `OFFER_OR_CLOSED` (`ARCHIVED_GHOSTED`).
   - **`OFFER_OR_CLOSED`:** Terminal state when offer, rejection, or final archive occurs (`next_due_at = NULL`).

2. **Dual-Email Sync Safety (`src/applypilot/enrichment/email_tracker.py`):**
   - Because expired 48h Tier-1 holds submit via `SECONDARY_EMAIL` (`deepaksh.apply@gmail.com`), ensure `email_tracker.py` either supports polling a comma-separated `GMAIL_SYNC_ACCOUNTS` list (with separate OAuth tokens if configured) OR logs a startup warning reminding the user to verify Gmail auto-forwarding from `deepaksh.apply@gmail.com` to `deepakshkarkala@gmail.com`.

---

## Phase 6: Resume Scannability Guardrails & JD Demand Feedback Loop

1. **7.4-Second Single-Column & Zero-Fabrication Validator (`src/applypilot/scoring/validator.py` & `pdf.py`):**
   - Eye-tracking research shows recruiters spend ~7.4 seconds on initial resume scans and lose focus on multi-column layouts or long sentences.
   - **Enforce in `pdf.py`:** Strictly single-column HTML/LaTeX template, bolded metrics (`95%`, `150K+`, `1,000 RPS`, `40%`, `300 ms`, `35%`), and GitHub URL (`https://github.com/DEEPAKSH123`) in the header.
   - **Enforce in `validator.py`:**
     - Zero-fabrication check against `profile.json` ground-truth companies, dates (Meesho Intern Jan 2025 – Jun 2025, SDE I Jul 2025 – Present), and numeric metrics.
     - Conciseness check: warn or auto-condense any tailored bullet exceeding 220 characters (~2 lines) so PDFs remain scannable within 1 page.

2. **Local Screening Memory (`src/applypilot/apply/screening_copilot.py`):**
   - Add a persistent `data/qa_memory.json` (keyed by normalized regex/question intent such as notice period, current/expected CTC, Bengaluru location, YOE) so recurring Workday/Greenhouse screening questions resolve locally in 0ms without redundant LLM calls.

3. **JD-to-Prep Skill Demand Aggregator (`src/applypilot/pipeline.py` & `dashboard/analytics.py`):**
   - Add a lightweight `extract_required_skills(description)` helper matching canonical backend tags (`Java`, `Golang`, `Kafka`, `Redis`, `PostgreSQL`, `MySQL`, `Kubernetes`, `Docker`, `System Design`, `Microservices`) and store as JSON in a `required_skills` column on `jobs` (auto-migrated safely via `ALTER TABLE` if missing).
   - Query trailing 7-day counts across `fit_score >= 8` jobs and return the top 3 skills via `/api/skills/demand`.

---

## Phase 7: Cron Entrypoints & Stale-Lock Safety (`automation/poller.py` & `naukri_updater.py`)

1. **Standardize Entrypoints:**
   - Ensure `python -m applypilot.automation.poller` runs cleanly as a standalone CLI/cron entrypoint (`if __name__ == "__main__":`) executing:
     1. Direct ATS polling (`ats.py`, `workday.py`)
     2. `jobspy.py` with `hours_old=4`
     3. `remote_boards.py`
     4. `seed_startups.py` funding radar
     5. `run_pipeline(stages=["enrich", "score", "tailor", "pdf"], min_score=8, workers=4)`
     6. `email_tracker.py` sync
     7. `followup_engine.collect_due_actions()` Telegram digest
   - Do not reference `cron_runner.py` (which does not exist in `b05254c`).

2. **Naukri Stale-Lock Protection (`src/applypilot/automation/naukri_updater.py`):**
   - Per `NAUKRI_LOCK.md`, implement PID + timestamp lockfile checking (`data/naukri.lock`): if a lockfile exists, check if the PID is still alive and if age < 30 minutes; if stale/dead, clear the lock automatically so a crashed browser never blocks future 10:30 AM / 8:30 PM runs.

---

## Phase 8: Mandatory Verification Suite & Acceptance Criteria

Antigravity must add automated tests and verify all checks pass before committing on `feat/anti-job-board-v2-and-ui-fix`:

1. **New Unit & Integration Tests:**
   - `tests/test_ats_parsers.py`: Mock HTTP responses covering Greenhouse double-encoded HTML, Lever millisecond timestamps + EU fallback, Ashby `isListed: false` filtering, Workday `limit=20` & page-2 `total: 0` pagination loop, and SmartRecruiters empty-200 handling.
   - `tests/test_funding_radar.py`: Verify positive/negative regex filtering on RSS headlines, deduplication across repeated polling runs, and `funding_leads` persistence.
   - `tests/test_anti_ghosting.py`: Verify `OA_OR_SCREEN_PENDING`, `INTERVIEW_ROUND_COMPLETED` -> `POST_INTERVIEW_DAY_3` -> `POST_INTERVIEW_FINAL` -> `OFFER_OR_CLOSED`, plus `generate_founder_pitch()` rejecting `jobs@` emails and enforcing `<= 80` words.
   - `tests/test_dashboard_api.py`: Start the HTTP handler in a test thread or invoke handlers against a temp WAL SQLite DB; assert HTTP 200 and valid JSON for `/`, `/static/app.js`, `/api/jobs`, `/api/followups/due`, `/api/funding-leads`, and `/api/skills/demand`.

2. **Acceptance Commands (Must All Exit 0):**
   ```bash
   pytest -v
   python -m compileall src/
   python -m applypilot.automation.poller --dry-run
   ```
