"""ApplyPilot Autonomous Auto-Apply & Application Assistant.

Provides end-to-end autonomous job application capabilities:
- Filters jobs matching Deepak's target criteria (0-3 YOE, Go/Java Backend, RVCE, Meesho)
- Injects active LinkedIn session cookies into Brave browser context
- Automatically fills personal, contact, education, and professional experience
- Intelligently answers ATS & Easy Apply screening questions (skills YOE, CTC, notice period, auth)
- Attaches vector tailored resume PDF
- Multi-step progression (Page 1 -> Page 2 -> Review -> Submit) for LinkedIn Easy Apply & ATS portals
- Automatically marks jobs as applied in database and audit ledger
- Supports both:
    1. 100% Autonomous Mode ("Doing everything itself" - Kanistus workflow)
    2. Review Mode ("Fill & Pause before submit" - Human-in-the-loop)
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

# Global progress state for dashboard monitoring
AUTO_APPLY_STATE = {
    "is_running": False,
    "current_job": None,
    "current_step": "idle",
    "total": 0,
    "completed": 0,
    "submitted": [],
    "half_applied": [],
    "requires_login": [],
    "captcha_blocked": [],
    "last_error": None,
}

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


def inject_session_cookies(context) -> int:
    """Inject saved LinkedIn session cookies into the browser context."""
    session_file = APP_DIR / "linkedin_session.json"
    if not session_file.exists():
        return 0
    try:
        with open(session_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            raw_cookies = data.get("cookies", [])
            pw_cookies = []
            for c in raw_cookies:
                s = c.get("sameSite", "Lax")
                if s not in ("Strict", "Lax", "None"):
                    s = "Lax"
                pw_cookies.append({
                    "name": c["name"],
                    "value": c["value"],
                    "domain": c.get("domain", ".linkedin.com"),
                    "path": c.get("path", "/"),
                    "httpOnly": c.get("httpOnly", False),
                    "secure": c.get("secure", True),
                    "sameSite": s,
                })
            if pw_cookies:
                context.add_cookies(pw_cookies)
                log.info("Injected %d session cookies into browser context", len(pw_cookies))
                return len(pw_cookies)
    except Exception as e:
        log.warning("Could not inject session cookies: %s", e)
    return 0


def _find_job(conn: sqlite3.Connection, identifier: str | int) -> dict | None:
    """Find job by rank, company keyword, rowid, or URL."""
    c = conn.cursor()
    row = None
    ident_str = str(identifier).strip()

    if ident_str.startswith("http://") or ident_str.startswith("https://"):
        row = c.execute(
            "SELECT rowid, * FROM jobs WHERE url = ? OR application_url = ?",
            (ident_str, ident_str)
        ).fetchone()

    if not row and ident_str.isdigit():
        num = int(ident_str)
        row = c.execute(
            "SELECT rowid, * FROM jobs WHERE rowid = ? AND fit_score >= 7",
            (num,)
        ).fetchone()
        if not row and num >= 1:
            row = c.execute(
                "SELECT rowid, * FROM jobs WHERE fit_score IS NOT NULL "
                "ORDER BY fit_score DESC, rowid ASC LIMIT 1 OFFSET ?",
                (num - 1,)
            ).fetchone()
        if not row:
            row = c.execute("SELECT rowid, * FROM jobs WHERE rowid = ?", (num,)).fetchone()

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


def _extract_prompt_text(element, page) -> str:
    """Extract descriptive question/prompt text from label, aria, or parent container."""
    try:
        aria = element.get_attribute("aria-label") or ""
        placeholder = element.get_attribute("placeholder") or ""
        name = element.get_attribute("name") or ""
        el_id = element.get_attribute("id") or ""

        label_text = ""
        if el_id:
            lbl = page.query_selector(f"label[for='{el_id}']")
            if lbl:
                label_text = lbl.inner_text() or ""
        if not label_text:
            parent_text = element.evaluate("""el => {
                const p = el.closest('.jobs-easy-apply-form-section__grouping, .fb-form-element, .form-group, fieldset, label, tr, .field');
                return p ? p.innerText : '';
            }""")
            label_text = parent_text or ""

        return f"{name} {el_id} {aria} {placeholder} {label_text}".strip()
    except Exception:
        return ""


def smart_answer_screening_question(prompt_text: str, field_type: str = "text") -> str | None:
    """Intelligently determine answers for common screening questions."""
    q = prompt_text.lower()

    # Technical experience questions
    tech_skills = [
        "go", "golang", "java", "kafka", "redis", "spring", "spring boot", "mysql", "sql",
        "docker", "kubernetes", "gcp", "google cloud", "aws", "distributed", "microservices",
        "python", "backend", "rest", "api", "git", "linux", "nosql", "postgres", "concurrency",
        "system design"
    ]

    is_yoe = any(k in q for k in ["how many years", "years of experience", "experience with", "yoe", "years working"])
    if is_yoe:
        for skill in tech_skills:
            if re.search(r'\b' + re.escape(skill) + r'\b', q):
                return "1" if field_type == "int" else "1.3"
        # General engineering YOE
        return "1" if field_type == "int" else "1.3"

    # Notice period
    if "notice" in q:
        if field_type == "int" or "days" in q:
            return "0"
        return "Immediate"

    # Compensation / CTC
    if "current" in q and any(k in q for k in ["ctc", "salary", "compensation", "inr", "lpa"]):
        return "2000000" if field_type == "int" else "20 LPA"
    if any(k in q for k in ["expected", "desired", "requirement"]) and any(k in q for k in ["ctc", "salary", "compensation", "inr", "lpa"]):
        return "2500000" if field_type == "int" else "25 LPA"

    # Work Authorization
    if any(k in q for k in ["authorized", "authorization", "eligible to work", "legally", "right to work"]):
        return "Yes"

    # Visa sponsorship
    if any(k in q for k in ["sponsor", "visa"]):
        return "No"

    # Commute / Relocation / Onsite / Hybrid
    if any(k in q for k in ["relocat", "commute", "hybrid", "on-site", "onsite", "office", "bangalore", "bengaluru", "pune", "hyderabad"]):
        return "Yes"

    # Background checks & Drug screens
    if any(k in q for k in ["background", "verification", "check", "screening"]):
        return "Yes"

    # Age 18+
    if any(k in q for k in ["18 years", "at least 18", "age"]):
        return "Yes"

    # Education / Degree
    if any(k in q for k in ["bachelor", "degree", "completed your education", "undergraduate"]):
        return "Yes"

    # Negative defaults
    if any(k in q for k in [
        "felony", "criminal", "convict", "non-compete", "previously worked",
        "former employee", "employed by our company", "worked for us", "relative", "worked for"
    ]):
        return "No"

    return None


def prefill_all_visible_fields(page, profile: dict, tailored_resume: Path | None = None, cover_letter: Path | None = None) -> list[str]:
    """Auto-detect and prefill standard and screening application fields."""
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
        (r"first[_\s-]?name|given[_\s-]?name", first_name),
        (r"last[_\s-]?name|family[_\s-]?name|surname", last_name),
        (r"full[_\s-]?name|^name$", full_name),
        (r"e[-_]?mail", email),
        (r"phone|mobile|tel", phone),
        (r"postal|zip|pin[-_\s]?code", postal),
        (r"city", city),
        (r"state|province", state),
        (r"country", country),
        (r"linkedin", linkedin),
        (r"github", github),
        (r"portfolio|website|personal[_\s-]?site", website),
        (r"current[_\s-]?company|employer", company),
        (r"current[_\s-]?title|headline|current[_\s-]?role", title),
        (r"total[_\s-]?experience|years[_\s-]?of[_\s-]?experience|yoe", experience_years),
        (r"notice[_\s-]?period", notice_period),
        (r"current[_\s-]?ctc|current[_\s-]?salary", current_ctc),
        (r"expected[_\s-]?ctc|expected[_\s-]?salary", expected_ctc),
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
                curr_val = inp.input_value()
                if curr_val:
                    continue

                prompt = _extract_prompt_text(inp, page)
                matched = False

                for pattern, val in field_mappings:
                    if re.search(pattern, prompt, re.IGNORECASE) and val:
                        inp.fill(str(val))
                        filled_actions.append(f"Filled '{pattern}' -> {val}")
                        matched = True
                        break

                if not matched and prompt:
                    inp_type = inp.get_attribute("type") or "text"
                    field_t = "int" if inp_type == "number" else "text"
                    ans = smart_answer_screening_question(prompt, field_t)
                    if ans:
                        inp.fill(str(ans))
                        filled_actions.append(f"Answered screening: '{prompt[:30]}...' -> {ans}")
            except Exception:
                continue

        # 2. Select Dropdowns
        selects = page.query_selector_all("select")
        for sel in selects:
            try:
                prompt = _extract_prompt_text(sel, page).lower()

                if re.search(r"authorized|authorization|eligible[_\s-]?to[_\s-]?work", prompt):
                    _select_matching_option(sel, ["yes", "authorized"])
                    filled_actions.append("Selected Work Auth -> Yes")
                elif re.search(r"sponsor|visa", prompt):
                    _select_matching_option(sel, ["no", "not require"])
                    filled_actions.append("Selected Visa Sponsorship -> No")
                elif re.search(r"relocat|commute", prompt):
                    _select_matching_option(sel, ["yes", "willing"])
                    filled_actions.append("Selected Relocation -> Yes")
                elif re.search(r"country", prompt):
                    _select_matching_option(sel, ["india", "in"])
                    filled_actions.append("Selected Country -> India")
                elif re.search(r"gender", prompt):
                    _select_matching_option(sel, ["male", "prefer not"])
                    filled_actions.append("Selected Gender -> Male")
                elif re.search(r"degree|education", prompt):
                    _select_matching_option(sel, ["bachelor", "engineering", "b.e", "b.tech"])
                    filled_actions.append("Selected Degree -> Bachelor")
                elif re.search(r"experience|yoe|years", prompt):
                    _select_matching_option(sel, ["1", "1-3", "1 - 3", "2", "yes"])
                    filled_actions.append("Selected Experience -> 1-3 yrs")
                else:
                    ans = smart_answer_screening_question(prompt, "text")
                    if ans:
                        _select_matching_option(sel, [ans.lower()])
            except Exception:
                continue

        # 3. Radio Buttons
        radios = page.query_selector_all("input[type='radio']")
        for rad in radios:
            try:
                val_attr = (rad.get_attribute("value") or "").lower()
                prompt = _extract_prompt_text(rad, page).lower()

                target_ans = smart_answer_screening_question(prompt, "text")
                if target_ans:
                    is_yes_radio = val_attr in ("yes", "y", "true", "1") or "yes" in (rad.inner_text() or "").lower()
                    is_no_radio = val_attr in ("no", "n", "false", "0") or "no" in (rad.inner_text() or "").lower()
                    if target_ans == "Yes" and is_yes_radio and not rad.is_checked():
                        rad.check()
                        filled_actions.append(f"Checked Radio Yes: {prompt[:30]}...")
                    elif target_ans == "No" and is_no_radio and not rad.is_checked():
                        rad.check()
                        filled_actions.append(f"Checked Radio No: {prompt[:30]}...")
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


def handle_linkedin_easy_apply(page, profile: dict, tailored_resume: Path | None, auto_submit: bool = True) -> tuple[bool, str]:
    """Execute end-to-end LinkedIn Easy Apply workflow."""
    easy_apply_selectors = [
        "button.jobs-apply-button",
        "button:has-text('Easy Apply')",
        "button[data-job-id] .jobs-apply-button",
        ".jobs-s-apply button"
    ]
    easy_btn = None
    for sel in easy_apply_selectors:
        try:
            btn = page.query_selector(sel)
            if btn and btn.is_visible():
                easy_btn = btn
                break
        except Exception:
            continue

    if not easy_btn:
        return False, "No Easy Apply button found"

    log.info("Found LinkedIn Easy Apply! Clicking to initiate modal...")
    easy_btn.click()
    page.wait_for_timeout(2000)

    # Multi-step wizard
    for step in range(1, 12):
        prefill_all_visible_fields(page, profile, tailored_resume=tailored_resume)
        page.wait_for_timeout(1000)

        # Check for Submit application
        for sel in ["button[aria-label='Submit application']", "button:has-text('Submit application')"]:
            sub_btn = page.query_selector(sel)
            if sub_btn and sub_btn.is_visible():
                if auto_submit:
                    log.info("Autonomous mode: Submitting LinkedIn Easy Apply on step %d...", step)
                    sub_btn.click()
                    page.wait_for_timeout(3000)
                    for d_sel in ["button[aria-label='Dismiss']", "button:has-text('Done')", "button:has-text('Not now')"]:
                        try:
                            d_btn = page.query_selector(d_sel)
                            if d_btn and d_btn.is_visible():
                                d_btn.click()
                                break
                        except Exception:
                            pass
                    return True, "Submitted successfully via LinkedIn Easy Apply!"
                else:
                    return False, "Paused on Review step for Deepak's review."

        # Check for Review button
        review_btn = None
        for sel in ["button[aria-label='Review your application']", "button:has-text('Review')"]:
            r = page.query_selector(sel)
            if r and r.is_visible():
                review_btn = r
                break
        if review_btn:
            log.info("Clicking Review button on step %d...", step)
            review_btn.click()
            page.wait_for_timeout(1500)
            continue

        # Check for Next button
        next_btn = None
        for sel in ["button[aria-label='Continue to next step']", "button:has-text('Next')"]:
            n = page.query_selector(sel)
            if n and n.is_visible():
                next_btn = n
                break
        if next_btn:
            log.info("Clicking Next button on step %d...", step)
            next_btn.click()
            page.wait_for_timeout(1500)
            continue

        break

    return False, "Completed form steps"


def handle_portal_apply(page, profile: dict, tailored_resume: Path | None, cover_letter: Path | None = None, auto_submit: bool = True) -> tuple[bool, str]:
    """Execute application form on external ATS (Greenhouse, SmartRecruiters, Lever, etc.)."""
    # 1. Check if there is an initial entry button before the form (e.g. SmartRecruiters 'I'm interested', Lever 'Apply')
    entry_selectors = [
        'button:has-text("interested")', 'a:has-text("interested")',
        'button:has-text("Apply for this job")', 'a:has-text("Apply for this job")',
        'button:has-text("Apply Now")', 'a:has-text("Apply Now")',
        'button:has-text("Apply manually")', 'a:has-text("Apply manually")',
        'button:has-text("Apply")', 'a:has-text("Apply")',
        'a[data-qa="apply-button"]', 'button[data-qa="apply-button"]',
        '[data-automation-id="adventureButton"]'
    ]
    inputs_before = page.query_selector_all("input:not([type='hidden']), textarea")
    curr_url_before = page.url
    if len(inputs_before) < 2:
        for sel in entry_selectors:
            try:
                btn = page.query_selector(sel)
                if btn and btn.is_visible():
                    log.info("Clicking initial portal application button: %s", sel)
                    target_href = btn.get_attribute("href")
                    btn.click()
                    page.wait_for_timeout(2500)
                    if target_href and page.url == curr_url_before:
                        log.info("Navigating to entry href directly: %s", target_href)
                        try:
                            page.goto(target_href, wait_until="domcontentloaded", timeout=25000)
                            page.wait_for_timeout(2000)
                        except Exception:
                            pass
                    break
            except Exception as e:
                log.debug("Entry button error: %s", e)

    # Check for authentication redirect (e.g. kadegree/login)
    curr_url = (page.url or "").lower()
    if any(p in curr_url for p in ["/login", "/signin", "/auth/login", "/auth/signin", "login."]):
        return False, "Login required (portal gated by authentication)"

    # Check for CAPTCHA / bot challenge
    try:
        page_html = (page.content() or "").lower()
        if any(term in page_html for term in ["captcha-delivery", "datadome", "cf-turnstile", "g-recaptcha", "verify you are human"]):
            return False, "Verification/CAPTCHA challenge detected (requires human confirmation)"
    except Exception:
        pass

    # 2. Prefill visible fields
    prefill_all_visible_fields(page, profile, tailored_resume=tailored_resume, cover_letter=cover_letter)
    page.wait_for_timeout(1500)

    # 3. Check for multi-step 'Next' / 'Continue' buttons
    for step in range(1, 6):
        next_selectors = [
            "button:has-text('Next')", "button:has-text('Continue')",
            "button:has-text('Save and continue')", "button:has-text('Review')"
        ]
        next_clicked = False
        for n_sel in next_selectors:
            try:
                n_btn = page.query_selector(n_sel)
                if n_btn and n_btn.is_visible():
                    txt = (n_btn.inner_text() or "").strip().lower()
                    if txt in ("next", "continue", "save and continue", "review", "review application"):
                        log.info("Advancing form step %d via button: %s", step, txt)
                        n_btn.click()
                        page.wait_for_timeout(2000)
                        prefill_all_visible_fields(page, profile, tailored_resume=tailored_resume, cover_letter=cover_letter)
                        next_clicked = True
                        break
            except Exception:
                pass
        if not next_clicked:
            break

    if not auto_submit:
        return False, "Form pre-filled. Paused for human review."

    submit_selectors = [
        "button[type='submit']",
        "input[type='submit']",
        "button:has-text('Submit Application')",
        "button:has-text('Submit application')",
        "button:has-text('Apply Now')",
        "button:has-text('Submit')",
        "#submit_app",
        "[data-qa='btn-submit']"
    ]
    for sel in submit_selectors:
        try:
            btn = page.query_selector(sel)
            if btn and btn.is_visible():
                btn_text = (btn.inner_text() or btn.get_attribute("value") or "").lower()
                if any(w in btn_text for w in ["submit", "apply", "send"]):
                    log.info("Autonomous mode: Clicking submit button: %s", btn_text)
                    btn.click()
                    page.wait_for_timeout(4000)
                    return True, f"Submitted successfully via portal ({btn_text})!"
        except Exception as e:
            log.debug("Submit attempt: %s", e)

    return False, "Form prefilled (ready for confirmation)"


def launch_application_assistant(identifier: str | int, headed: bool = True, auto_submit: bool = True, is_batch: bool = False, batch_timeout_sec: int = 15) -> dict:
    """Launch Brave browser, auto-fill all fields, and handle submission."""
    conn = get_connection()
    job = _find_job(conn, identifier)
    if not job:
        return {"status": "error", "message": f"Job '{identifier}' not found in database."}

    apply_url = job.get("application_url") or job.get("url")
    if not apply_url or apply_url == "None":
        conn.execute("UPDATE jobs SET apply_status = 'no_url', apply_error = 'Missing valid application URL' WHERE rowid = ?", (job["rowid"],))
        conn.commit()
        return {"status": "error", "message": "No application URL available for this job."}

    if "kadegree.in/openings" in str(apply_url):
        return {
            "status": "referral_lead",
            "submitted": False,
            "job_title": job.get("title", "Role"),
            "company": job.get("site", "Company"),
            "message": "Internal referral lead. Use '+ Draft Cold Email' to email the referrer.",
        }

    if "phonepe.com" in apply_url and ("sde1" in apply_url or apply_url.rstrip("/").endswith("/careers")):
        apply_url = "https://jobs.smartrecruiters.com/PhonePeLimited/1000000000003895"
    elif "razorpay.com" in apply_url or "lever.co/razorpay" in apply_url:
        if "greenhouse.io" not in apply_url:
            apply_url = "https://job-boards.greenhouse.io/razorpaysoftwareprivatelimited"

    profile = load_profile()

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

    cover_pdf = None
    if job.get("cover_letter_path"):
        p = Path(job["cover_letter_path"])
        if not p.is_absolute():
            p = APP_DIR / p
        if p.exists():
            cover_pdf = p

    company_name = job.get("site") or "Company"
    role_title = job.get("title") or "Software Engineer"
    rowid = job["rowid"]

    exe_path, browser_name = get_browser_executable()
    log.info("Launching %s browser for %s @ %s (auto_submit=%s)", browser_name.upper(), role_title, company_name, auto_submit)

    from playwright.sync_api import sync_playwright

    is_submitted = False
    submission_msg = ""

    with sync_playwright() as p:
        # Check if Deepak's primary Brave is running with CDP remote debugging
        is_cdp = False
        try:
            import urllib.request
            with urllib.request.urlopen("http://127.0.0.1:9222/json/version", timeout=1.0) as resp:
                is_cdp = (resp.status == 200)
        except Exception:
            is_cdp = False

        if is_cdp:
            log.info("Connecting directly to Deepak's live Brave browser on CDP port 9222...")
            browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
            contexts = browser.contexts
            context = contexts[0] if contexts else browser.new_context()
            page = context.new_page()
        else:
            log.info("Launching visible Brave browser instance...")
            browser = p.chromium.launch(
                executable_path=exe_path if exe_path else None,
                headless=not headed,
                args=["--disable-blink-features=AutomationControlled"],
            )
            context = browser.new_context(viewport={"width": 1366, "height": 850})
            inject_session_cookies(context)
            page = context.new_page()

        try:
            log.info("Navigating to: %s", apply_url)
            page.goto(apply_url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(2500)

            # Check if LinkedIn Easy Apply
            if "linkedin.com" in apply_url:
                is_submitted, submission_msg = handle_linkedin_easy_apply(page, profile, tailored_pdf, auto_submit=auto_submit)

            # If not submitted or not LinkedIn, try portal apply
            if not is_submitted:
                is_submitted, submission_msg = handle_portal_apply(page, profile, tailored_pdf, cover_pdf, auto_submit=auto_submit)

            if is_submitted:
                mark_job_applied(rowid)
                log.info("Application successfully submitted for %s @ %s! %s", role_title, company_name, submission_msg)

                # Show celebration banner
                celebration_html = f"""
                <div style="position:fixed;top:0;left:0;right:0;padding:16px;background:linear-gradient(90deg,#059669,#10b981);color:#fff;text-align:center;font-weight:700;font-size:16px;z-index:99999999;box-shadow:0 4px 12px rgba(0,0,0,0.4);">
                    🎉 Application Submitted Autonomously! [{role_title} @ {company_name}] — Recorded in ApplyPilot Database & Ledger
                </div>
                """
                page.evaluate(f"() => {{ const d = document.createElement('div'); d.innerHTML = `{celebration_html}`; document.body.prepend(d); }}")
                page.wait_for_timeout(4000)
                if not is_cdp:
                    try:
                        context.close()
                        browser.close()
                    except Exception:
                        pass
                else:
                    try:
                        page.wait_for_timeout(3000)
                        page.close()
                    except Exception:
                        pass
                return {
                    "status": "applied",
                    "submitted": True,
                    "job_title": role_title,
                    "company": company_name,
                    "message": submission_msg,
                }

            # If not submitted (review mode or awaiting user action)
            banner_html = f"""
            <div id="applypilot-guard-banner" style="
                position: fixed; top: 0; left: 0; right: 0; height: 52px;
                background: linear-gradient(90deg, #0f172a, #1e1b4b);
                color: #e0e7ff; display: flex; align-items: center; justify-content: space-between;
                padding: 0 16px; z-index: 99999999; font-family: system-ui, sans-serif; font-size: 13px;
                box-shadow: 0 4px 12px rgba(0,0,0,0.5); border-bottom: 2px solid #6366f1;">
                <div style="display:flex;align-items:center;gap:10px;">
                    <span style="background:#4338ca;padding:4px 8px;border-radius:4px;font-weight:700;">🛡️ ApplyPilot Active</span>
                    <span><strong>{role_title}</strong> @ {company_name}</span>
                    <button id="ap-fill-btn" onclick="window.applypilotFillPage()" style="
                        background:#10b981;color:#fff;border:none;padding:5px 12px;border-radius:4px;
                        cursor:pointer;font-weight:600;font-size:12px;box-shadow:0 2px 4px rgba(0,0,0,0.2);">
                        ✨ Auto-Fill Current Page
                    </button>
                </div>
                <div style="display:flex;align-items:center;gap:12px;">
                    <span style="font-size:12px;color:#a5b4fc;">Review fields & click Submit when ready</span>
                </div>
            </div>
            """
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

            if "login" in submission_msg.lower():
                from applypilot.analytics.activity import mark_job_half_applied
                mark_job_half_applied(rowid, action="requires_login")
                conn.execute("UPDATE jobs SET apply_status = 'requires_login', apply_error = ? WHERE rowid = ?", (submission_msg, rowid))
                conn.commit()
                return {
                    "status": "requires_login",
                    "submitted": False,
                    "job_title": role_title,
                    "company": company_name,
                    "message": submission_msg,
                }

            if "captcha" in submission_msg.lower() or "challenge" in submission_msg.lower():
                from applypilot.analytics.activity import mark_job_half_applied
                mark_job_half_applied(rowid, action="captcha_blocked")
                conn.execute("UPDATE jobs SET apply_status = 'captcha_blocked', apply_error = ? WHERE rowid = ?", (submission_msg, rowid))
                conn.commit()
                return {
                    "status": "captcha_blocked",
                    "submitted": False,
                    "job_title": role_title,
                    "company": company_name,
                    "message": submission_msg,
                }

            if is_batch:
                log.info("Batch mode: Waiting %ds for portal processing before closing...", batch_timeout_sec)
                page.wait_for_timeout(min(batch_timeout_sec * 1000, 8000))
                from applypilot.analytics.activity import mark_job_half_applied
                mark_job_half_applied(rowid, action="prefilled")
                conn.execute("UPDATE jobs SET apply_status = 'half_applied', apply_error = ? WHERE rowid = ? AND (apply_status IS NULL OR apply_status NOT IN ('applied', 'interview'))", ("Prefilled in batch mode", rowid))
                conn.commit()
                try:
                    context.close()
                except Exception:
                    pass
                return {
                    "status": "half_applied",
                    "submitted": False,
                    "job_title": role_title,
                    "company": company_name,
                    "message": "Prefilled and saved in batch mode",
                }

            # Interactive review watch loop
            if headed and not auto_submit:
                last_url = page.url
                while True:
                    if page.is_closed():
                        break
                    page.wait_for_timeout(2000)
                    if page.url != last_url:
                        last_url = page.url
                        page.wait_for_timeout(1500)
                        prefill_all_visible_fields(page, profile, tailored_pdf, cover_pdf)
            elif auto_submit and not is_submitted:
                log.info("Autonomous mode completed all fill actions. Waiting 10s for portal sync before closing...")
                page.wait_for_timeout(10000)

        except Exception as e:
            if "Target closed" not in str(e):
                log.error("Assistant browser error: %s", e)
                try:
                    (APP_DIR / "logs").mkdir(parents=True, exist_ok=True)
                    with open(APP_DIR / "logs" / "auto_apply.log", "a", encoding="utf-8") as lf:
                        lf.write(f"[{datetime.now().isoformat()}] Assistant error for {identifier} ({apply_url}): {e}\n")
                except Exception:
                    pass
        finally:
            if not is_cdp:
                try:
                    context.close()
                except Exception:
                    pass
                try:
                    browser.close()
                except Exception:
                    pass

    return {
        "status": "ok",
        "submitted": is_submitted,
        "job_title": role_title,
        "company": company_name,
        "message": submission_msg or "Review completed",
    }


def auto_apply_batch(limit: int = 5, min_score: int = 7, headed: bool = True, auto_submit: bool = True) -> dict:
    """Run autonomous applications sequentially across top qualified unapplied jobs."""
    global AUTO_APPLY_STATE
    conn = get_connection()
    c = conn.cursor()

    query = """
        SELECT rowid, site, title, fit_score, application_url, url
        FROM jobs
        WHERE (apply_status IS NULL OR apply_status NOT IN ('applied', 'half_applied', 'requires_login', 'captcha_blocked', 'failed', 'no_url'))
          AND (application_url IS NOT NULL OR url IS NOT NULL)
          AND (application_url NOT LIKE '%kadegree.in/openings%' AND (url NOT LIKE '%kadegree.in/openings%' OR url IS NULL))
          AND strategy NOT IN ('kadegree_community', 'telegram_channel', 'whatsapp_community')
          AND fit_score >= ?
        ORDER BY fit_score DESC, rowid ASC
        LIMIT ?
    """
    rows = c.execute(query, (min_score, limit)).fetchall()
    if not rows:
        return {"status": "ok", "message": "No eligible unapplied jobs found matching threshold.", "applied_count": 0}

    AUTO_APPLY_STATE["is_running"] = True
    AUTO_APPLY_STATE["total"] = len(rows)
    AUTO_APPLY_STATE["completed"] = 0
    AUTO_APPLY_STATE["submitted"] = []
    AUTO_APPLY_STATE["half_applied"] = []
    AUTO_APPLY_STATE["requires_login"] = []
    AUTO_APPLY_STATE["captcha_blocked"] = []
    AUTO_APPLY_STATE["last_error"] = None

    submitted_list = []
    try:
        for idx, r in enumerate(rows, 1):
            rowid, site, title, score, app_url, url = r
            AUTO_APPLY_STATE["current_job"] = f"{title} @ {site}"
            AUTO_APPLY_STATE["current_step"] = f"Applying [{idx}/{len(rows)}]"
            log.info("Batch Applying [%d/%d]: %s @ %s (Score: %s)", idx, len(rows), title, site, score)

            res = launch_application_assistant(rowid, headed=headed, auto_submit=auto_submit, is_batch=True)
            res_status = res.get("status")
            if res.get("submitted") or res_status == "applied":
                submitted_list.append({"rowid": rowid, "company": site, "title": title})
                AUTO_APPLY_STATE["submitted"].append(f"{title} @ {site}")
            elif res_status == "half_applied":
                AUTO_APPLY_STATE["half_applied"].append(f"{title} @ {site}")
            elif res_status == "requires_login":
                AUTO_APPLY_STATE["requires_login"].append(f"{title} @ {site}")
            elif res_status == "captcha_blocked":
                AUTO_APPLY_STATE["captcha_blocked"].append(f"{title} @ {site}")

            AUTO_APPLY_STATE["completed"] += 1
            time.sleep(2)

    except Exception as e:
        AUTO_APPLY_STATE["last_error"] = str(e)
        log.error("Batch auto-apply error: %s", e)
    finally:
        AUTO_APPLY_STATE["is_running"] = False
        AUTO_APPLY_STATE["current_step"] = "finished"

    return {
        "status": "ok",
        "total_attempted": len(rows),
        "submitted_count": len(submitted_list),
        "submitted_jobs": submitted_list,
        "half_applied_count": len(AUTO_APPLY_STATE.get("half_applied", [])),
        "requires_login_count": len(AUTO_APPLY_STATE.get("requires_login", [])),
        "captcha_blocked_count": len(AUTO_APPLY_STATE.get("captcha_blocked", [])),
    }


def mark_job_applied(identifier: str | int) -> dict:
    """Mark a job as applied in the database and audit ledger, and refresh exports."""
    conn = get_connection()
    c = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()
    job = _find_job(conn, identifier)
    if not job:
        return {"status": "error", "message": f"Job '{identifier}' not found in database."}

    rowid = job["rowid"]
    site = job.get("site") or "Company"
    title = job.get("title") or "Software Engineer"
    apply_url = job.get("application_url") or job.get("url") or ""

    # Update jobs table
    c.execute("UPDATE jobs SET apply_status = 'applied', applied_at = ? WHERE rowid = ?", (now, rowid))

    # Record in application_responses audit ledger if table exists
    try:
        msg_id = f"auto_{rowid}_{int(time.time())}"
        c.execute("""
            INSERT INTO application_responses (message_id, company, role_title, sender, subject, received_date, status, summary, body_snippet, action_url, synced_at, action_type)
            VALUES (?, ?, ?, 'ApplyPilot Assistant', 'Application Submitted Autonomously', ?, 'applied', 'Application submitted via portal', ?, ?, ?, 'applied')
        """, (msg_id, site, title, now, f"Submitted to {apply_url}", apply_url, now))
    except Exception as e:
        log.debug("Response ledger logging: %s", e)

    conn.commit()

    from applypilot.export.csv_export import export_opportunities_csv
    export_opportunities_csv()

    return {"status": "ok", "job_title": title, "company": site, "applied_at": now}
