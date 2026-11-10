# Instructions & Guidelines for Agents Working on ApplyPilot

Refer to `../MEMORY.md` for the complete operational history and candidate persona.

## Critical Invariants for Developers & AI Agents:

1. **Browser Navigation:**
   * NEVER use programmatic `window.open(...)` from JavaScript functions—Brave Shields intercepts and blocks it silently as an unwanted popup.
   * ALWAYS render links as native HTML `<a href="..." target="_blank" rel="noopener noreferrer">` anchor elements (used for Job cards, Open LinkedIn, Assessment links, and Referral filters).
   * In backend Python, NEVER pass `stdout=DEVNULL, stderr=DEVNULL` to `subprocess.Popen([BRAVE_EXE, ...])` on Windows; pipe redirection causes Chromium's process initialization to drop IPC messages.
   * Prefer `os.startfile(url)` on Windows to launch links via the registered default browser (`BraveHTML`).
   * Use native JavaScript `navigator.clipboard.writeText(...)` for copying files or notes to clipboard with zero latency.

2. **User Profiles:**
   * Do not configure automated scripts to use isolated, empty browser profiles (`data/brave_profile`) for human workflows.
   * Deepak's personal credentials and session cookies are located in his standard Brave profile (`%LOCALAPPDATA%\BraveSoftware\Brave-Browser\User Data`).

3. **URL Sanitization:**
   * Verify all URLs start with `http://` or `https://`.
   * Never permit `"None"`, `"http://none/"`, or dead links to enter `applypilot.db` or `opportunities.csv`.

4. **Autonomy Constraint:**
   * NEVER instruct the user to open a terminal or run commands.
   * Perform all setup, migrations, database queries, and background daemon monitoring autonomously.

5. **Seniority & Experience Filter (0–3 YOE):**
   * Deepak S H has ~1.3 years of experience.
   * Strictly reject titles with Senior, Lead, Staff, Principal, Manager, Architect, or jobs requiring 4+ YOE.
   * Maintain only eligible 0–3 YOE roles in `opportunities.csv` and the UI.

6. **Recruiter Outreach & Gmail Drafting:**
   * Never send emails automatically.
   * Create drafts in Gmail using `gmail mutate create-draft` with `--body-file <temp_md> --md` and `--file <resume_pdf>` via `applypilot.networking.gmail_drafter`.
   * On Windows, resolve `gmail` via `shutil.which("gmail")` and pass `shell=True`.
