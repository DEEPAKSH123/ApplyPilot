"""Human-in-the-Loop 1-Click Application Assistant (Phase 3).

Launches Brave browser (with persistent profile so logins, cookies, and candidate details are active),
navigates to the job application URL, auto-fills candidate information across all pages (Page 1, 2, 3+),
attaches the tailored resume PDF, and pauses for the user's final review before submission.

STRICT RULE: NEVER auto-submits. User must review and click 'Submit' themselves.
"""

import json
import logging
import os
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from applypilot.config import APP_DIR, DB_PATH, load_profile
from applypilot.database import get_connection
from applypilot.networking.outreach import generate_outreach_messages

log = logging.getLogger(__name__)

BRAVE_PROFILE_DIR = APP_DIR / "brave_profile"


def get_browser_executable() -> tuple[str | None, str]:
    """Find Brave browser or fallback to system Chromium."""
    candidates = [
        r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
        r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c, "brave"
    return None, "chromium"


def _find_job(conn: sqlite3.Connection, identifier: str | int) -> dict | None:
    """Find job by rank (e.g. 1 for top-rated job), company keyword, rowid, or URL."""
    c = conn.cursor()
    row = None

    # 1. Exact URL / application URL
    ident_str = str(identifier).strip()
    if ident_str.startswith("http://") or ident_str.startswith("https://"):
        row = c.execute(
            "SELECT rowid, * FROM jobs WHERE url = ? OR application_url = ?",
            (ident_str, ident_str)
        ).fetchone()

    # 2. Number (rank or rowid)
    if not row and ident_str.isdigit():
        num = int(ident_str)
        # First check if rowid == num exists and has fit_score >= 7 (e.g. when clicked from dashboard)
        row = c.execute(
            "SELECT rowid, * FROM jobs WHERE rowid = ? AND fit_score >= 7",
            (num,)
        ).fetchone()

        # Second check: treat as 1-based rank among top-rated opportunities (e.g. '1' = top match)
        if not row and num >= 1:
            row = c.execute(
                "SELECT rowid, * FROM jobs WHERE fit_score IS NOT NULL "
                "ORDER BY fit_score DESC, rowid ASC LIMIT 1 OFFSET ?",
                (num - 1,)
            ).fetchone()

        # Third check: check any rowid regardless of score
        if not row:
            row = c.execute("SELECT rowid, * FROM jobs WHERE rowid = ?", (num,)).fetchone()

    # 3. Fuzzy keyword search by company, title, or site (e.g. 'stripe', 'phonepe', 'mastercard', 'cisco')
    if not row and ident_str:
        q = f"%{ident_str}%"
        row = c.execute(
            "SELECT rowid, * FROM jobs WHERE (site LIKE ? OR title LIKE ? OR url LIKE ? OR full_description LIKE ?) "
            "ORDER BY fit_score DESC NULLS LAST LIMIT 1",
            (q, q, q, q)
        ).fetchone()

    if not row:
        return None
    columns = [d[0] for d in c.description]
    return dict(zip(columns, row))


def prefill_all_visible_fields(page, profile: dict, tailored_resume: Path | None = None, cover_letter: Path | None = None) -> list[str]:
    """Auto-detect and prefill standard and heavy job application fields across multi-step pages."""
    personal = profile.get("personal", {})
    exp = profile.get("experience", {})
    facts = profile.get("resume_facts", {})

    first_name = personal.get("full_name", "").split()[0] if personal.get("full_name") else "Deepak"
    last_name = " ".join(personal.get("full_name", "").split()[1:]) if personal.get("full_name") else "S H"
    full_name = personal.get("full_name", "Deepak S H")
    email = personal.get("email", "deepakshkarkala@gmail.com")
    phone = personal.get("phone", "8431433659")
    city = personal.get("city", "Bengaluru")
    state = "Karnataka"
    country = "India"
    postal = personal.get("postal_code", "560087")
    linkedin = personal.get("linkedin_url", "https://www.linkedin.com/in/deepak-s-h-82b772254")
    github = "https://github.com/Deepak-S-H"
    website = github
    company = exp.get("current_company", "Meesho")
    title = exp.get("current_title", "Software Development Engineer I (Backend)")
    school = facts.get("preserved_school", "RV College of Engineering")
    degree = "Bachelor of Engineering (B.E.)"
    major = "Computer Science and Engineering"
    grad_year = "2025"
    cgpa = "8.92"
    experience_years = "1.3"
    notice_period = "Immediate"
    current_ctc = "20 LPA"
    expected_ctc = "25 LPA"

    filled_actions = []

    # Text field mappings (regex -> value)
    field_mappings = [
        # Personal
        (r"first[_\s-]?name|given[_\s-]?name", first_name),
        (r"last[_\s-]?name|family[_\s-]?name|surname", last_name),
        (r"full[_\s-]?name|^name$", full_name),
        (r"e[-_]?mail", email),
        (r"phone|mobile|tel", phone),
        (r"postal|zip|pin[-_\s]?code", postal),
        (r"city", city),
        (r"state|province", state),
        (r"country", country),

        # Links
        (r"linkedin", linkedin),
        (r"github", github),
        (r"portfolio|website|personal[_\s-]?site", website),

        # Professional / Experience (Page 2)
        (r"current[_\s-]?company|employer", company),
        (r"current[_\s-]?title|headline|current[_\s-]?role", title),
        (r"total[_\s-]?experience|years[_\s-]?of[_\s-]?experience|yoe", experience_years),
        (r"notice[_\s-]?period", notice_period),
        (r"current[_\s-]?ctc|current[_\s-]?salary", current_ctc),
        (r"expected[_\s-]?ctc|expected[_\s-]?salary", expected_ctc),

        # Education (Page 2/3)
        (r"school|university|college|institution", school),
        (r"degree|qualification", degree),
        (r"major|discipline|field[_\s-]?of[_\s-]?study", major),
        (r"graduation[_\s-]?year|year[_\s-]?of[_\s-]?graduation", grad_year),
        (r"cgpa|gpa|percentage", cgpa),
    ]

    try:
        # 1. Fill Text Inputs and Textareas
        inputs = page.query_selector_all("input:not([type='hidden']):not([type='submit']):not([type='button']):not([type='file']):not([type='radio']):not([type='checkbox']), textarea")
        for inp in inputs:
            try:
                name_attr = (inp.get_attribute("name") or "").lower()
                id_attr = (inp.get_attribute("id") or "").lower()
                aria_attr = (inp.get_attribute("aria-label") or "").lower()
                placeholder = (inp.get_attribute("placeholder") or "").lower()
                combined = f"{name_attr} {id_attr} {aria_attr} {placeholder}"

                curr_val = inp.input_value()
                if curr_val:
                    continue

                for pattern, val in field_mappings:
                    if re.search(pattern, combined, re.IGNORECASE) and val:
                        inp.fill(str(val))
                        filled_actions.append(f"Filled '{pattern}' -> {val}")
                        break
            except Exception:
                continue

        # 2. Select Dropdowns (Page 2/3)
        selects = page.query_selector_all("select")
        for sel in selects:
            try:
                name_attr = (sel.get_attribute("name") or "").lower()
                id_attr = (sel.get_attribute("id") or "").lower()
                aria_attr = (sel.get_attribute("aria-label") or "").lower()
                combined = f"{name_attr} {id_attr} {aria_attr}"

                # Work Authorization (Are you authorized to work in India? -> Yes)
                if re.search(r"authorized|authorization|eligible[_\s-]?to[_\s-]?work", combined, re.IGNORECASE):
                    _select_matching_option(sel, ["yes", "authorized"])
                    filled_actions.append("Selected Work Auth -> Yes")
                # Sponsorship (Do you require visa sponsorship? -> No)
                elif re.search(r"sponsor|visa", combined, re.IGNORECASE):
                    _select_matching_option(sel, ["no", "not require"])
                    filled_actions.append("Selected Visa Sponsorship -> No")
                # Relocation
                elif re.search(r"relocat", combined, re.IGNORECASE):
                    _select_matching_option(sel, ["yes", "willing"])
                    filled_actions.append("Selected Relocation -> Yes")
                # Country
                elif re.search(r"country", combined, re.IGNORECASE):
                    _select_matching_option(sel, ["india", "in"])
                    filled_actions.append("Selected Country -> India")
                # Gender
                elif re.search(r"gender", combined, re.IGNORECASE):
                    _select_matching_option(sel, ["male", "prefer not"])
                    filled_actions.append("Selected Gender -> Male")
                # Degree
                elif re.search(r"degree|education", combined, re.IGNORECASE):
                    _select_matching_option(sel, ["bachelor", "engineering", "b.e", "b.tech"])
                    filled_actions.append("Selected Degree -> Bachelor")
            except Exception:
                continue

        # 3. Radio Buttons (Work authorization, sponsorship, relocation)
        radios = page.query_selector_all("input[type='radio']")
        for rad in radios:
            try:
                name_attr = (rad.get_attribute("name") or "").lower()
                val_attr = (rad.get_attribute("value") or "").lower()
                id_attr = (rad.get_attribute("id") or "").lower()
                combined = f"{name_attr} {val_attr} {id_attr}"

                # Authorized to work -> Yes
                if re.search(r"authorized|eligible", name_attr) and val_attr in ("yes", "y", "true", "1"):
                    if not rad.is_checked():
                        rad.check()
                        filled_actions.append("Checked Authorized -> Yes")
                # Requires sponsorship -> No
                elif re.search(r"sponsor|visa", name_attr) and val_attr in ("no", "n", "false", "0"):
                    if not rad.is_checked():
                        rad.check()
                        filled_actions.append("Checked Sponsorship -> No")
                # Relocate -> Yes
                elif re.search(r"relocat", name_attr) and val_attr in ("yes", "y", "true", "1"):
                    if not rad.is_checked():
                        rad.check()
                        filled_actions.append("Checked Relocation -> Yes")
            except Exception:
                continue

        # 4. File attachments (Resume / Cover Letter)
        file_inputs = page.query_selector_all("input[type='file']")
        if file_inputs and tailored_resume and tailored_resume.exists():
            try:
                file_inputs[0].set_input_files(str(tailored_resume.resolve()))
                filled_actions.append(f"Attached resume: {tailored_resume.name}")
            except Exception as e:
                log.debug("Resume file upload: %s", e)

        if len(file_inputs) > 1 and cover_letter and cover_letter.exists():
            try:
                file_inputs[1].set_input_files(str(cover_letter.resolve()))
                filled_actions.append(f"Attached cover letter: {cover_letter.name}")
            except Exception as e:
                log.debug("Cover letter upload: %s", e)

    except Exception as e:
        log.warning("Form pre-filling error: %s", e)

    return filled_actions


def _select_matching_option(select_element, target_keywords: list[str]) -> bool:
    """Select option in a select element whose text or value matches target keywords."""
    options = select_element.query_selector_all("option")
    for opt in options:
        text = (opt.inner_text() or "").lower()
        val = (opt.get_attribute("value") or "").lower()
        for kw in target_keywords:
            if kw in text or kw in val:
                select_element.select_option(value=val or text)
                return True
    return False


def launch_application_assistant(identifier: str | int, headed: bool = True) -> dict:
    """Launch Brave browser with candidate profile, auto-fill all pages, and hold for review."""
    conn = get_connection()
    job = _find_job(conn, identifier)
    if not job:
        return {"status": "error", "message": f"Job '{identifier}' not found in database."}

    apply_url = job.get("application_url") or job.get("url")
    if not apply_url or apply_url == "None":
        return {"status": "error", "message": "No application URL available for this job."}

    # Special handling for known invalid referral links (e.g. PhonePe mock referral)
    if "phonepe.com" in apply_url and ("sde1" in apply_url or apply_url.rstrip("/").endswith("/careers")):
        apply_url = "https://jobs.smartrecruiters.com/PhonePeLimited/1000000000003895"
    elif "razorpay.com" in apply_url and apply_url.rstrip("/").endswith("/jobs"):
        apply_url = "https://job-boards.greenhouse.io/razorpaysoftwareprivatelimited"

    profile = load_profile()

    # Resolve resume PDF
    tailored_pdf = None
    if job.get("tailored_resume_path"):
        p = Path(job["tailored_resume_path"])
        if not p.is_absolute():
            p = APP_DIR / p
        if p.exists():
            tailored_pdf = p
    if not tailored_pdf:
        base_pdf = APP_DIR / "resume.pdf"
        if base_pdf.exists():
            tailored_pdf = base_pdf

    # Resolve cover letter PDF
    cover_pdf = None
    if job.get("cover_letter_path"):
        p = Path(job["cover_letter_path"])
        if not p.is_absolute():
            p = APP_DIR / p
        if p.exists():
            cover_pdf = p

    # Generate LinkedIn networking search & outreach
    company_name = job.get("site") or "Company"
    role_title = job.get("title") or "Software Engineer"
    recruiter_email = job.get("recruiter_email") or ""
    outreach = generate_outreach_messages(company_name, role_title, apply_url, recruiter_email, profile)

    exe_path, browser_name = get_browser_executable()
    log.info("Launching %s browser for %s @ %s", browser_name.upper(), role_title, company_name)

    from playwright.sync_api import sync_playwright

    BRAVE_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        # Launch persistent context using candidate Brave automation profile
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(BRAVE_PROFILE_DIR.resolve()),
            executable_path=exe_path if exe_path else None,
            headless=not headed,
            viewport={"width": 1366, "height": 850},
            args=["--disable-blink-features=AutomationControlled"],
        )

        page = context.new_page() if not context.pages else context.pages[0]

        try:
            log.info("Navigating to: %s", apply_url)
            page.goto(apply_url, wait_until="domcontentloaded", timeout=45000)
            time.sleep(2)

            # Prefill Page 1
            filled = prefill_all_visible_fields(page, profile, tailored_resume=tailored_pdf, cover_letter=cover_pdf)

            # Injected multi-page autofill banner and continuous observer
            alumni_link = outreach["alumni_search_url"]
            recruiter_btn = f"""<a href="mailto:{recruiter_email}?subject=Application for {role_title} - Deepak S H" style="background:#7c3aed;color:#fff;padding:4px 10px;border-radius:4px;text-decoration:none;font-weight:600;margin-left:8px;"><i class="fa-solid fa-envelope"></i> Email Recruiter</a>""" if recruiter_email else ""

            banner_html = f"""
            <div id="applypilot-guard-banner" style="
                position: fixed; top: 0; left: 0; right: 0; height: 52px;
                background: linear-gradient(90deg, #0f172a, #1e1b4b);
                color: #e0e7ff; display: flex; align-items: center; justify-content: space-between;
                padding: 0 16px; z-index: 99999999; font-family: system-ui, -apple-system, sans-serif; font-size: 13px;
                box-shadow: 0 4px 12px rgba(0,0,0,0.5); border-bottom: 2px solid #6366f1;">
                <div style="display:flex;align-items:center;gap:10px;">
                    <span style="background:#4338ca;padding:4px 8px;border-radius:4px;font-weight:700;">🛡️ ApplyPilot Active</span>
                    <span><strong>{role_title}</strong> @ {company_name}</span>
                    <button id="ap-fill-btn" onclick="window.applypilotFillPage()" style="
                        background:#10b981;color:#fff;border:none;padding:5px 12px;border-radius:4px;
                        cursor:pointer;font-weight:600;font-size:12px;box-shadow:0 2px 4px rgba(0,0,0,0.2);">
                        ✨ Auto-Fill Current Page
                    </button>
                    {recruiter_btn}
                </div>
                <div style="display:flex;align-items:center;gap:12px;">
                    <a href="{alumni_link}" target="_blank" style="
                        background:#0284c7;color:#fff;padding:4px 10px;border-radius:4px;text-decoration:none;font-weight:600;font-size:12px;">
                        🤝 Find RVCE Alumni for Referral
                    </a>
                    <span style="font-size:11px;opacity:0.85;">Rule: Human Review — please click Submit yourself</span>
                </div>
            </div>
            """

            # Expose auto-fill function to browser context for multi-page forms
            page.expose_function("triggerMultiPageFill", lambda: prefill_all_visible_fields(page, profile, tailored_pdf, cover_pdf))

            page.evaluate(f"""() => {{
                const d = document.createElement('div');
                d.innerHTML = `{banner_html}`;
                document.body.prepend(d);

                window.applypilotFillPage = async () => {{
                    const btn = document.getElementById('ap-fill-btn');
                    if (btn) btn.innerText = 'Filling...';
                    await window.triggerMultiPageFill();
                    if (btn) {{
                        btn.innerText = '✓ Page Filled!';
                        setTimeout(() => btn.innerText = '✨ Auto-Fill Current Page', 2000);
                    }}
                }};
            }}""")

            log.info("Prefilled %d fields. Browser is open in %s for Deepak's review.", len(filled), browser_name.upper())

            # Continuous multi-page watcher: re-checks and auto-fills whenever DOM or URL changes (e.g. Page 2, Page 3)
            last_url = page.url
            last_field_count = 0

            try:
                while True:
                    if page.is_closed():
                        break
                    time.sleep(2)

                    # If page navigated to Step 2/3 (URL change or step advance)
                    if page.url != last_url:
                        last_url = page.url
                        log.info("Multi-page form step detected: %s. Auto-filling new page...", last_url)
                        time.sleep(1.5)
                        prefill_all_visible_fields(page, profile, tailored_pdf, cover_pdf)

                    # Periodic check: if new unfilled inputs appear on the current step
                    try:
                        visible_inputs = page.query_selector_all("input:not([type='hidden']), select, textarea")
                        if len(visible_inputs) > last_field_count:
                            last_field_count = len(visible_inputs)
                            prefill_all_visible_fields(page, profile, tailored_pdf, cover_pdf)
                    except Exception:
                        pass

            except Exception:
                pass

        except Exception as e:
            if "Target closed" not in str(e):
                log.error("Assistant browser error: %s", e)
        finally:
            try:
                context.close()
            except Exception:
                pass

    return {
        "status": "ok",
        "job_title": role_title,
        "company": company_name,
        "browser": browser_name,
        "actions_filled": len(filled) if 'filled' in locals() else 0,
    }


def mark_job_applied(identifier: str | int) -> dict:
    """Mark a job as applied in the database and refresh the opportunities sheet."""
    conn = get_connection()
    c = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()
    job = _find_job(conn, identifier)
    if not job:
        return {"status": "error", "message": f"Job '{identifier}' not found in database."}

    rowid = job["rowid"]
    c.execute("UPDATE jobs SET apply_status = 'applied', applied_at = ? WHERE rowid = ?", (now, rowid))
    conn.commit()

    from applypilot.export.csv_export import export_opportunities_csv
    export_opportunities_csv()

    return {"status": "ok", "job_title": job.get("title"), "company": job.get("site"), "applied_at": now}
