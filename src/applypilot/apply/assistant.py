"""Human-in-the-Loop 1-Click Application Assistant (Phase 3).

Launches a visible browser window, navigates to the job application URL,
pre-fills candidate information from profile.json, attaches the tailored
resume PDF, and pauses for the user's final review before submission.

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

from applypilot.config import APP_DIR, DB_PATH, load_profile
from applypilot.database import get_connection

log = logging.getLogger(__name__)


def _find_job(conn: sqlite3.Connection, identifier: str | int) -> dict | None:
    """Find job by rowid or URL."""
    c = conn.cursor()
    if isinstance(identifier, int) or (isinstance(identifier, str) and identifier.isdigit()):
        row = c.execute("SELECT rowid, * FROM jobs WHERE rowid = ?", (int(identifier),)).fetchone()
    else:
        row = c.execute("SELECT rowid, * FROM jobs WHERE url = ? OR application_url = ?", (str(identifier), str(identifier))).fetchone()
    
    if not row:
        return None
    columns = [d[0] for d in c.description]
    return dict(zip(columns, row))


def prefill_form_fields(page, profile: dict, tailored_resume: Path | None = None, cover_letter: Path | None = None) -> list[str]:
    """Auto-detect and prefill standard job application fields."""
    personal = profile.get("personal", {})
    exp = profile.get("experience", {})
    facts = profile.get("resume_facts", {})

    first_name = personal.get("full_name", "").split()[0] if personal.get("full_name") else "Deepak"
    last_name = " ".join(personal.get("full_name", "").split()[1:]) if personal.get("full_name") else "S H"
    full_name = personal.get("full_name", "Deepak S H")
    email = personal.get("email", "")
    phone = personal.get("phone", "")
    city = personal.get("city", "Bengaluru")
    linkedin = personal.get("linkedin_url", "")
    company = exp.get("current_company", "Meesho")
    title = exp.get("current_title", "Software Development Engineer I (Backend)")
    school = facts.get("preserved_school", "RV College of Engineering")

    filled_actions = []

    # Map of regex patterns to values
    field_mappings = [
        (r"first[_\s-]?name|given[_\s-]?name", first_name),
        (r"last[_\s-]?name|family[_\s-]?name|surname", last_name),
        (r"full[_\s-]?name|^name$", full_name),
        (r"e[-_]?mail", email),
        (r"phone|mobile|tel", phone),
        (r"linkedin", linkedin),
        (r"city", city),
        (r"current[_\s-]?company|employer", company),
        (r"current[_\s-]?title|headline", title),
        (r"school|university|college", school),
    ]

    try:
        inputs = page.query_selector_all("input:not([type='hidden']):not([type='submit']):not([type='button']), textarea")
        for inp in inputs:
            try:
                name_attr = (inp.get_attribute("name") or "").lower()
                id_attr = (inp.get_attribute("id") or "").lower()
                aria_attr = (inp.get_attribute("aria-label") or "").lower()
                placeholder = (inp.get_attribute("placeholder") or "").lower()
                combined = f"{name_attr} {id_attr} {aria_attr} {placeholder}"

                # Check if already filled
                curr_val = inp.input_value() if inp.get_attribute("type") != "file" else ""
                if curr_val:
                    continue

                for pattern, val in field_mappings:
                    if re.search(pattern, combined) and val:
                        inp.fill(str(val))
                        filled_actions.append(f"Filled '{pattern}' -> {val}")
                        break
            except Exception:
                continue

        # File attachments (Resume / Cover Letter)
        file_inputs = page.query_selector_all("input[type='file']")
        if file_inputs and tailored_resume and tailored_resume.exists():
            try:
                # Attach resume to the first file input or resume-specific input
                file_inputs[0].set_input_files(str(tailored_resume.resolve()))
                filled_actions.append(f"Attached resume: {tailored_resume.name}")
            except Exception as e:
                log.debug("Resume file upload error: %s", e)

        if len(file_inputs) > 1 and cover_letter and cover_letter.exists():
            try:
                file_inputs[1].set_input_files(str(cover_letter.resolve()))
                filled_actions.append(f"Attached cover letter: {cover_letter.name}")
            except Exception as e:
                log.debug("Cover letter upload error: %s", e)

    except Exception as e:
        log.warning("Form pre-filling encountered: %s", e)

    return filled_actions


def launch_application_assistant(identifier: str | int, headed: bool = True) -> dict:
    """Launch the visible browser application assistant for a job.

    Opens the apply link, fills candidate profile fields, attaches the tailored resume PDF,
    and pauses for human review.
    """
    conn = get_connection()
    job = _find_job(conn, identifier)
    if not job:
        return {"status": "error", "message": f"Job '{identifier}' not found in database."}

    apply_url = job.get("application_url") or job.get("url")
    if not apply_url:
        return {"status": "error", "message": "No application URL available for this job."}

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
        # Fall back to base resume
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

    from playwright.sync_api import sync_playwright

    log.info("Launching Application Assistant for: %s @ %s", job.get("title"), job.get("site"))

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        context = browser.new_context(viewport={"width": 1366, "height": 850})
        page = context.new_page()

        try:
            page.goto(apply_url, wait_until="domcontentloaded", timeout=45000)
            time.sleep(2)  # Give JS SPAs a moment to render forms

            filled = prefill_form_fields(page, profile, tailored_resume=tailored_pdf, cover_letter=cover_pdf)

            # Inject human-in-the-loop notification banner
            banner_html = """
            <div id="applypilot-guard-banner" style="
                position: fixed; top: 0; left: 0; right: 0; height: 50px;
                background: linear-gradient(90deg, #1e1b4b, #312e81);
                color: #e0e7ff; display: flex; align-items: center; justify-content: space-between;
                padding: 0 20px; z-index: 9999999; font-family: system-ui, sans-serif; font-size: 14px;
                box-shadow: 0 4px 12px rgba(0,0,0,0.4); border-bottom: 2px solid #6366f1;">
                <div>
                    <strong>🛡️ ApplyPilot Human Review:</strong> 
                    Candidate fields filled & Tailored Resume attached. Please review and click <strong>Submit</strong> yourself.
                </div>
                <div>
                    <span style="font-size: 12px; opacity: 0.8; margin-right: 12px;">Rule: Zero automated submission without human approval</span>
                </div>
            </div>
            """
            page.evaluate(f"""() => {{
                const d = document.createElement('div');
                d.innerHTML = `{banner_html}`;
                document.body.prepend(d);
            }}""")

            log.info("Prefilled %d fields. Browser is open for Deepak's review.", len(filled))

            # Keep browser alive until user closes the window or 10 minutes pass
            while not page.is_closed():
                time.sleep(1)

        except Exception as e:
            if "Target closed" not in str(e):
                log.error("Assistant browser error: %s", e)
        finally:
            try:
                browser.close()
            except Exception:
                pass

    return {
        "status": "ok",
        "job_title": job.get("title"),
        "company": job.get("site"),
        "actions_filled": len(filled) if 'filled' in locals() else 0,
    }


def mark_job_applied(identifier: str | int) -> dict:
    """Mark a job as applied in the database and refresh the opportunities sheet."""
    conn = get_connection()
    c = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()
    if isinstance(identifier, int) or (isinstance(identifier, str) and identifier.isdigit()):
        c.execute("UPDATE jobs SET apply_status = 'applied', applied_at = ? WHERE rowid = ?", (now, int(identifier)))
    else:
        c.execute("UPDATE jobs SET apply_status = 'applied', applied_at = ? WHERE url = ? OR application_url = ?", (now, str(identifier), str(identifier)))
    
    conn.commit()

    from applypilot.export.csv_export import export_opportunities_csv
    export_opportunities_csv()

    return {"status": "ok", "applied_at": now}
