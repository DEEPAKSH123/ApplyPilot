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

from applypilot.config import APP_DIR, DB_PATH, load_profile, load_env
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
                const p = el.closest('.jobs-easy-apply-form-section__grouping, .fb-form-element, .form-group, fieldset, label, tr, .field, div');
                return p ? p.innerText : '';
            }""")
            label_text = parent_text or ""

        return f"{name} {el_id} {aria} {placeholder} {label_text}".strip()
    except Exception:
        return ""


def smart_answer_screening_question(prompt_text: str, field_type: str = "text") -> str | None:
    """Intelligently determine answers for common screening questions with LLM fallback."""
    q = prompt_text.lower().strip()
    if not q:
        return None

    # GPA / Marks / Grades
    if any(k in q for k in ["gpa", "cgpa", "/10", "10 scale", "grade point", "percentage", "marks"]):
        return "8.92"

    # Technical experience questions
    is_yoe = any(k in q for k in ["how many years", "years of experience", "experience with", "yoe", "years working", "years have you"])
    if is_yoe:
        # LinkedIn Easy Apply numeric YOE inputs require a whole integer (decimals like 1.3 cause "Invalid input")
        return "1"

    # Tier 1 institution questions (IIT, IIIT, NIT, BITS)
    if any(k in q for k in ["tier 1", "tier-1", "iit", "iiit", "nit", "bits"]):
        return "No"

    # Promoted in company
    if any(k in q for k in ["promoted", "promotion"]):
        return "No"

    # Notice period
    if "notice" in q:
        if field_type == "int" or "days" in q:
            return "0"
        return "Immediate"

    # Compensation / CTC
    if "current" in q and any(k in q for k in ["ctc", "salary", "compensation", "inr", "lpa", "pay"]):
        if any(k in q for k in ["lakh", "lakhs"]):
            return "20"
        # If question asks in INR, numbers, annual, or is a numeric input, return pure integer
        if field_type == "int" or any(k in q for k in ["inr", "example", "annual", "digits", "number"]):
            return "2000000"
        return "2000000"

    if any(k in q for k in ["expected", "desired", "requirement"]) and any(k in q for k in ["ctc", "salary", "compensation", "inr", "lpa", "pay"]):
        if any(k in q for k in ["lakh", "lakhs"]):
            return "25"
        if field_type == "int" or any(k in q for k in ["inr", "example", "annual", "digits", "number"]):
            return "2500000"
        return "2500000"

    # Work Authorization / Legally authorized
    if any(k in q for k in ["authorized", "authorization", "eligible to work", "legally", "right to work"]):
        return "Yes"

    # Visa sponsorship
    if any(k in q for k in ["sponsor", "visa"]):
        return "No"

    # Commute / Relocation / Onsite / Hybrid / Travel
    if any(k in q for k in [
        "relocat", "commute", "commuting", "hybrid", "on-site", "onsite", "in-office", "office",
        "bangalore", "bengaluru", "pune", "hyderabad", "travel", "willing to work", "comfortable commuting"
    ]):
        return "Yes"

    # Background checks, Drug screens, Reference checks
    if any(k in q for k in ["background", "verification", "check", "screening", "drug", "reference"]):
        return "Yes"

    # Age 18+
    if any(re.search(p, q) for p in [r"\b18\s*years\b", r"\bat\s*least\s*18\b", r"\bage\s*of\s*majority\b", r"\blegally\s*of\s*age\b"]):
        return "Yes"

    # Education / Degree / Graduation (CS, IT, ECE, EEE)
    if any(k in q for k in [
        "bachelor's", "bachelors", "undergraduate degree", "graduate degree",
        "completed your degree", "completed your education", "level of education",
        "b.e", "b.tech", "cs or eee"
    ]):
        return "Yes"

    # Shift / Full-time / Availability
    if any(k in q for k in ["full-time", "full time", "start date", "available to start", "comfort", "ready to join"]):
        return "Yes"

    # Negative defaults
    if any(k in q for k in [
        "felony", "criminal", "convict", "non-compete", "previously worked",
        "former employee", "employed by our company", "worked for us", "relative", "worked for"
    ]):
        return "No"

    # Why are you a good fit / Summary / Additional information
    if any(k in q for k in [
        "why are you a good fit", "why should we hire you", "why are you interested",
        "why this role", "why do you want to join", "tell us about yourself",
        "brief summary", "relevant experience", "what makes you a good fit"
    ]):
        return (
            "I'm an SDE-I Backend Engineer at Meesho with production experience building high-throughput services "
            "using Java, Go, Kafka, Redis, and Spring Boot. At Meesho, I work on distributed reconciliation "
            "and event-driven pipelines handling large transaction volumes with sub-10ms cache latency. "
            "I graduated from RVCE in CSE (8.92 CGPA) and enjoy working on scalable, reliable backend systems."
        )

    # Fallback to LLM for unknown screening questions
    try:
        load_env()
        from applypilot.llm import get_client
        llm = get_client()
        prompt = (
            f"You are answering an employment application screening question for Deepak S H.\n"
            f"Profile: 1.3 years of experience as SDE-I Backend Engineer at Meesho. RVCE CSE 2025 graduate (CGPA 8.92/10). "
            f"Skills: Java, Go, Kafka, Redis, Spring Boot, MySQL, GCP, Distributed Systems. "
            f"Location: Bengaluru, India. Notice Period: Immediate / 0 days. Current CTC: 20 LPA, Expected: 25 LPA. "
            f"Authorized to work in India (Yes), Does not require visa sponsorship (No).\n\n"
            f"Question: \"{prompt_text}\"\n"
            f"Requested Field Type: {field_type}\n"
            f"Provide ONLY the direct, concise answer (e.g. 'Yes', 'No', a single number, or short sentence). No commentary, no quotes."
        )
        ans = llm.ask(prompt).strip().strip('"').strip("'")
        if ans:
            log.info("LLM answered screening question '%s' -> '%s'", prompt_text[:40], ans)
            return ans
    except Exception as ex:
        log.debug("LLM fallback screening error: %s", ex)

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
    company = exp.get("current_company", "Meesho")
    title = exp.get("current_title", "Software Development Engineer I (Backend)")
    school = facts.get("preserved_school", "RV College of Engineering")
    degree = "Bachelor of Engineering (B.E.)"
    major = "Computer Science and Engineering"
    grad_year = "2025"
    cgpa = "8.92"
    experience_years = "1"
    notice_period = "0"
    current_ctc = "2000000"
    expected_ctc = "2500000"

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
        (r"^country$|country[_\s-]?region|country[_\s-]?name", country),
        (r"linkedin", linkedin),
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
        (r"cgpa|gpa|percentage|scale", cgpa),
    ]

    try:
        # 1. Fill Text Inputs and Textareas
        inputs = page.query_selector_all("input:not([type='hidden']):not([type='submit']):not([type='button']):not([type='file']):not([type='radio']):not([type='checkbox']), textarea")
        for inp in inputs:
            try:
                if not inp.is_visible():
                    continue

                curr_val = inp.input_value()
                # Skip search / top navigation bars
                ph = (inp.get_attribute("placeholder") or "").lower()
                if "search" in ph or "describe the job" in ph:
                    continue

                # Overwrite invalid decimal YOE values (e.g. 1.3 -> 1)
                if curr_val and curr_val != "1.3":
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
                if not sel.is_visible():
                    continue

                prompt = _extract_prompt_text(sel, page).lower()

                # Phone country code dropdown
                if re.search(r"phone.*country|country.*code|dialing|phone", prompt):
                    _select_matching_option(sel, ["india (+91)", "india", "+91"])
                    filled_actions.append("Selected Phone Country Code -> India (+91)")
                elif re.search(r"authorized|authorization|eligible[_\s-]?to[_\s-]?work", prompt):
                    _select_matching_option(sel, ["yes", "authorized"])
                    filled_actions.append("Selected Work Auth -> Yes")
                elif re.search(r"sponsor|visa", prompt):
                    _select_matching_option(sel, ["no", "not require"])
                    filled_actions.append("Selected Visa Sponsorship -> No")
                elif re.search(r"relocat|commute", prompt):
                    _select_matching_option(sel, ["yes", "willing"])
                    filled_actions.append("Selected Relocation -> Yes")
                elif re.search(r"country", prompt):
                    _select_matching_option(sel, ["india"])
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

        # 3. Radio Buttons (handles both native and custom LinkedIn styled radio buttons)
        radios = page.query_selector_all("input[type='radio']")
        for rad in radios:
            try:
                # Skip resume selection radios (e.g. choose between previously uploaded resumes)
                name_attr = (rad.get_attribute("name") or "").lower()
                id_attr = (rad.get_attribute("id") or "").lower()
                val_attr = (rad.get_attribute("value") or "").lower()
                if any("resume" in s or "document" in s for s in [name_attr, id_attr, val_attr]):
                    # If this is the first resume radio and none are checked, select it
                    if not any(r.is_checked() for r in radios if "resume" in (r.get_attribute("name") or "").lower()):
                        rad.evaluate("r => { let l = document.querySelector('label[for=\"' + r.id + '\"]'); if (l) l.click(); else r.click(); }")
                    continue

                prompt = _extract_prompt_text(rad, page).lower()
                if "resume" in prompt or ".pdf" in prompt or "cv" in prompt:
                    continue

                target_ans = smart_answer_screening_question(prompt, "text")
                if target_ans:
                    # Examine associated label text or parent container text
                    label_text = rad.evaluate("""r => {
                        let text = '';
                        let label = document.querySelector('label[for=\"' + r.id + '\"]');
                        if (label && label.innerText.trim()) text = label.innerText.trim();
                        if (!text && r.parentElement && r.parentElement.parentElement) {
                            text = r.parentElement.parentElement.innerText.trim();
                        }
                        return text;
                    }""").strip().lower()

                    is_yes_radio = (
                        val_attr in ("yes", "y", "true", "1") or
                        label_text.startswith("yes") or
                        label_text == "yes" or
                        "yes" in label_text
                    )
                    is_no_radio = (
                        val_attr in ("no", "n", "false", "0") or
                        label_text.startswith("no") or
                        label_text == "no" or
                        "no" in label_text
                    )

                    should_check = False
                    if target_ans.lower() == "yes" and is_yes_radio and not is_no_radio:
                        should_check = True
                    elif target_ans.lower() == "no" and is_no_radio and not is_yes_radio:
                        should_check = True

                    if should_check and not rad.is_checked():
                        # Use label click or JavaScript event dispatch to safely click opacity:0 elements
                        rad.evaluate("""r => {
                            let label = document.querySelector('label[for=\"' + r.id + '\"]');
                            if (label) {
                                label.click();
                            } else {
                                r.checked = true;
                                r.dispatchEvent(new Event('input', {bubbles: true}));
                                r.dispatchEvent(new Event('change', {bubbles: true}));
                            }
                        }""")
                        filled_actions.append(f"Checked Radio {target_ans}: {prompt[:30]}...")
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
    
    # 1. First attempt exact word or strict substring match
    for opt in options:
        text = (opt.inner_text() or "").strip().lower()
        val = (opt.get_attribute("value") or "").strip().lower()
        for kw in target_keywords:
            kw_clean = kw.strip().lower()
            if len(kw_clean) > 2 and (kw_clean in text or kw_clean in val):
                select_element.select_option(value=opt.get_attribute("value") or opt.inner_text())
                return True
            elif len(kw_clean) <= 2:
                if re.search(r"\b" + re.escape(kw_clean) + r"\b", text) or val.endswith(":" + kw_clean) or val == kw_clean:
                    select_element.select_option(value=opt.get_attribute("value") or opt.inner_text())
                    return True
    return False


def _find_active_apply_button(page, keywords: list[str]):
    """Find a visible, enabled button matching any target keywords."""
    btns = page.query_selector_all("button")
    for btn in btns:
        try:
            if not btn.is_visible() or not btn.is_enabled():
                continue
            txt = (btn.inner_text() or "").strip().lower()
            aria = (btn.get_attribute("aria-label") or "").strip().lower()
            for kw in keywords:
                kw_lower = kw.lower()
                if kw_lower in txt or kw_lower in aria:
                    return btn
        except Exception:
            continue
    return None


def get_linkedin_applicant_count(page) -> int | None:
    """Extract applicant count from LinkedIn job details page."""
    try:
        raw_text = page.evaluate("""() => {
            const textNodes = [];
            const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null, false);
            let n;
            while(n = walk.nextNode()) {
                if (n.textContent && n.textContent.toLowerCase().includes('applicant')) {
                    const t = n.textContent.trim();
                    if (t.length < 80) textNodes.push(t);
                }
            }
            return textNodes.join(' | ');
        }""")
        if not raw_text:
            return None

        # Look for explicit counts like '6 applicants', '42 applicants', 'Over 100 applicants'
        over_match = re.search(r'over\s+(\d+)\s+applicants?', raw_text, re.IGNORECASE)
        if over_match:
            return int(over_match.group(1)) + 1  # e.g. Over 100 -> 101

        num_match = re.search(r'(\d+)\s+applicants?', raw_text, re.IGNORECASE)
        if num_match:
            return int(num_match.group(1))
    except Exception as e:
        log.debug("Applicant count extraction error: %s", e)
    return None


def handle_linkedin_easy_apply(page, profile: dict, tailored_resume: Path | None, auto_submit: bool = True, max_applicants: int = 100) -> tuple[bool, str]:
    """Execute end-to-end LinkedIn Easy Apply workflow across legacy modals & new 2026 container layouts."""
    # Check applicant threshold if specified
    if max_applicants is not None and max_applicants > 0:
        count = get_linkedin_applicant_count(page)
        if count is not None and count > max_applicants:
            log.info("Skipping job: Applicant count %d exceeds threshold of %d", count, max_applicants)
            return False, f"Skipped: Applicant count {count} exceeds threshold of {max_applicants}"

    # Step 0: Ensure Easy Apply button was clicked if wizard is not already open
    wizard_open = page.evaluate("""() => {
        const btns = Array.from(document.querySelectorAll('button'));
        return btns.some(b => {
            const txt = b.innerText.trim().toLowerCase();
            return (txt === 'next' || txt === 'review' || txt === 'submit application' || txt === 'submit') && b.offsetParent !== null;
        });
    }""")

    if not wizard_open:
        easy_btn = None
        easy_selectors = [
            "button[aria-label='Easy Apply to this job']",
            "button:has-text('Easy Apply')",
            "button.jobs-apply-button",
            ".jobs-s-apply button"
        ]
        for sel in easy_selectors:
            try:
                b = page.query_selector(sel)
                if b and b.is_visible():
                    easy_btn = b
                    break
            except Exception:
                continue

        if not easy_btn:
            # Fallback by keyword inspection
            easy_btn = _find_active_apply_button(page, ["easy apply"])

        if not easy_btn:
            return False, "No Easy Apply button found on page"

        log.info("Found LinkedIn Easy Apply button! Clicking to initiate application...")
        try:
            easy_btn.scroll_into_view_if_needed()
            easy_btn.click()
        except Exception:
            page.evaluate("b => b.click()", easy_btn)
        page.wait_for_timeout(3000)

    # Multi-step wizard loop (Handles Page 1 -> Page 2 -> Additional Questions -> Review -> Submit)
    stalled_count = 0
    for step in range(1, 15):
        # 1. Scroll dialog or form body to reveal off-screen fields
        try:
            page.evaluate("""() => {
                const scrollables = document.querySelectorAll('.jobs-easy-apply-modal__content, div[role=\"dialog\"], form, main');
                scrollables.forEach(s => s.scrollTop = s.scrollHeight);
            }""")
            page.wait_for_timeout(500)
        except Exception:
            pass

        # 2. Prefill all visible form inputs, selects, and radios on current step
        actions = prefill_all_visible_fields(page, profile, tailored_resume=tailored_resume)
        page.wait_for_timeout(1000)

        import random
        # Human jitter before clicking next/review/submit (1.5s - 3.0s)
        page.wait_for_timeout(random.randint(1500, 3000))

        # 3. Check for Submit button
        sub_btn = _find_active_apply_button(page, ["submit application", "submit"])
        if sub_btn:
            if auto_submit:
                log.info("Autonomous mode: Submitting LinkedIn Easy Apply on step %d...", step)
                try:
                    sub_btn.click()
                except Exception:
                    page.evaluate("btn => btn.click()", sub_btn)
                page.wait_for_timeout(4000)

                # Dismiss completion dialog if any
                for d_sel in ["button[aria-label='Dismiss']", "button:has-text('Done')", "button:has-text('Not now')", ".artdeco-modal__dismiss"]:
                    try:
                        d_btn = page.query_selector(d_sel)
                        if d_btn and d_btn.is_visible():
                            d_btn.click()
                            break
                    except Exception:
                        pass
                return True, "Submitted successfully via LinkedIn Easy Apply!"
            else:
                return False, "Paused on Review step for human inspection."

        # 4. Check for Review button
        rev_btn = _find_active_apply_button(page, ["review your application", "review"])
        if rev_btn:
            log.info("Clicking Review button on step %d...", step)
            try:
                rev_btn.click()
            except Exception:
                page.evaluate("btn => btn.click()", rev_btn)
            page.wait_for_timeout(2000)
            stalled_count = 0
            continue

        # 5. Check for Next button
        next_btn = _find_active_apply_button(page, ["continue to next step", "next"])
        if next_btn:
            log.info("Clicking Next button on step %d...", step)
            try:
                next_btn.click()
            except Exception:
                page.evaluate("btn => btn.click()", next_btn)
            page.wait_for_timeout(2000)
            stalled_count = 0
            continue

        # Check if form is stalled by an unfulfilled validation requirement
        stalled_count += 1
        if stalled_count <= 2:
            log.info("Step %d stalled, re-evaluating unanswered fields...", step)
            page.wait_for_timeout(1500)
            continue
        break

    return False, "Completed available form steps"


def handle_portal_apply(page, profile: dict, tailored_resume: Path | None, cover_letter: Path | None = None, auto_submit: bool = True) -> tuple[bool, str]:
    """Execute application form on external ATS (Greenhouse, SmartRecruiters, Lever, etc.)."""
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

    curr_url = (page.url or "").lower()
    if any(p in curr_url for p in ["/login", "/signin", "/auth/login", "/auth/signin", "login."]):
        return False, "Login required (portal gated by authentication)"

    try:
        page_html = (page.content() or "").lower()
        if any(term in page_html for term in ["captcha-delivery", "datadome", "cf-turnstile", "g-recaptcha", "verify you are human"]):
            return False, "Verification/CAPTCHA challenge detected (requires human confirmation)"
    except Exception:
        pass

    prefill_all_visible_fields(page, profile, tailored_resume=tailored_resume, cover_letter=cover_letter)
    page.wait_for_timeout(1500)

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


# Anti-Ban Safety Limits
MAX_DAILY_EASY_APPLIES = 35  # LinkedIn safe daily ceiling for Easy Apply

def get_today_applied_count() -> int:
    """Return count of applications submitted today (UTC)."""
    try:
        conn = get_connection()
        c = conn.cursor()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        c.execute("SELECT COUNT(*) FROM jobs WHERE apply_status = 'applied' AND applied_at LIKE ?", (f"{today}%",))
        return c.fetchone()[0]
    except Exception:
        return 0


def launch_application_assistant(identifier: str | int, headed: bool = True, auto_submit: bool = True, is_batch: bool = False, batch_timeout_sec: int = 15, max_applicants: int = 100, easy_apply_only: bool = True) -> dict:
    """Launch Brave browser, auto-fill all fields, and handle submission."""
    # Safety Check: Enforce daily application ceiling to protect LinkedIn account
    daily_count = get_today_applied_count()
    if auto_submit and daily_count >= MAX_DAILY_EASY_APPLIES:
        log.warning("Daily safety limit reached (%d/%d applications submitted today). Halting auto-apply to keep your LinkedIn account 100%% safe.", daily_count, MAX_DAILY_EASY_APPLIES)
        return {
            "status": "safety_halt",
            "submitted": False,
            "message": f"Daily safety limit reached ({daily_count}/{MAX_DAILY_EASY_APPLIES}). Paused to protect your LinkedIn account from flagging.",
        }

    conn = get_connection()
    job = _find_job(conn, identifier)
    if not job:
        # If identifier is a full URL not yet in DB, dynamically register it
        ident_str = str(identifier).strip()
        if ident_str.startswith("http://") or ident_str.startswith("https://"):
            now_iso = datetime.now(timezone.utc).isoformat()
            site_name = "LinkedIn" if "linkedin.com" in ident_str else "External"
            c = conn.cursor()
            c.execute(
                "INSERT INTO jobs (url, application_url, title, site, discovered_at, fit_score, is_easy_apply) VALUES (?, ?, ?, ?, ?, 10, 1)",
                (ident_str, ident_str, "Shared Target Job", site_name, now_iso)
            )
            conn.commit()
            job = _find_job(conn, ident_str)
        if not job:
            return {"status": "error", "message": f"Job '{identifier}' not found in database."}

    apply_url = job.get("application_url")
    if not apply_url or str(apply_url).strip() in ("", "None", "null"):
        apply_url = job.get("url")
    if not apply_url or str(apply_url).strip() in ("", "None", "null"):
        conn.execute("UPDATE jobs SET apply_status = 'no_url', apply_error = 'Missing valid application URL' WHERE rowid = ?", (job["rowid"],))
        conn.commit()
        return {"status": "error", "message": "No application URL available for this job."}

    # Strict constraint: If easy_apply_only is True, skip external jobs or non-LinkedIn postings immediately
    if easy_apply_only and "linkedin.com" not in str(apply_url).lower():
        conn.execute("UPDATE jobs SET apply_status = 'skipped_non_easy_apply', apply_error = 'Not a LinkedIn Easy Apply job' WHERE rowid = ?", (job["rowid"],))
        conn.commit()
        return {
            "status": "skipped",
            "submitted": False,
            "job_title": job.get("title", "Role"),
            "company": job.get("site", "Company"),
            "message": "Skipped: Not a LinkedIn Easy Apply job (easy_apply_only=True)",
        }

    # Two-Email Guardrail & Referral Hold Pre-Check
    try:
        from applypilot.networking.followup_engine import ReferralFollowUpEngine
        from applypilot.config import get_secondary_email
        fe = ReferralFollowUpEngine(db_path=conn)
        job_state = fe.get_job_state(str(job["url"]))
        if job_state:
            st = job_state.get("status")
            due_at = job_state.get("next_due_at")
            now_iso = datetime.now(timezone.utc).isoformat()
            if st == "REFERRAL_HOLD" and due_at and now_iso < due_at:
                block_msg = f"BLOCKED: Tier-1 Referral Hold active until {due_at}. Send referral via Primary Email first."
                print(block_msg)
                log.warning(block_msg)
                return {
                    "status": "BLOCKED",
                    "submitted": False,
                    "job_title": job.get("title", "Role"),
                    "company": job.get("site", "Company"),
                    "message": block_msg,
                }
    except Exception as fe_err:
        log.warning("Followup engine pre-check warning: %s", fe_err)

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

    # Determine assigned email to prevent submitting the wrong email
    assigned_email = None
    used_secondary = False
    try:
        from applypilot.networking.followup_engine import ReferralFollowUpEngine
        from applypilot.config import get_secondary_email
        fe = ReferralFollowUpEngine(db_path=conn)
        jstate = fe.get_job_state(str(job["url"]))
        if jstate and jstate.get("email_used"):
            assigned_email = jstate["email_used"]
            if assigned_email == get_secondary_email():
                used_secondary = True
    except Exception:
        pass

    if assigned_email:
        if "personal" not in profile:
            profile["personal"] = {}
        profile["personal"]["email"] = assigned_email

    tailored_pdf = None
    if job.get("tailored_resume_path"):
        p = Path(job["tailored_resume_path"])
        if not p.is_absolute():
            p = APP_DIR / p
        if p.exists():
            tailored_pdf = p
    if not tailored_pdf:
        for candidate_name in ["Deepak_S_H_Resume.pdf", "resume.pdf"]:
            cand = APP_DIR / candidate_name
            if cand.exists():
                tailored_pdf = cand
                break

    # Ensure tailored resume is uploaded under standard name Deepak_S_H_Resume.pdf
    if tailored_pdf and tailored_pdf.exists():
        import shutil
        upload_staging_dir = APP_DIR / "apply-workers" / "current"
        upload_staging_dir.mkdir(parents=True, exist_ok=True)
        named_pdf = upload_staging_dir / "Deepak_S_H_Resume.pdf"
        try:
            shutil.copy2(str(tailored_pdf), str(named_pdf))
            tailored_pdf = named_pdf
        except Exception as e:
            log.debug("Failed staging named resume PDF: %s", e)

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
                is_submitted, submission_msg = handle_linkedin_easy_apply(page, profile, tailored_pdf, auto_submit=auto_submit, max_applicants=max_applicants)
                if not is_submitted and "exceeds threshold" in submission_msg:
                    conn.execute("UPDATE jobs SET apply_status = 'skipped_high_applicants', apply_error = ? WHERE rowid = ?", (submission_msg, rowid))
                    conn.commit()
                    return {
                        "status": "skipped",
                        "submitted": False,
                        "job_title": role_title,
                        "company": company_name,
                        "message": submission_msg,
                    }
                if not is_submitted and "No Easy Apply button" in submission_msg and easy_apply_only:
                    conn.execute("UPDATE jobs SET apply_status = 'skipped_no_easy_apply', apply_error = ? WHERE rowid = ?", (submission_msg, rowid))
                    conn.commit()
                    return {
                        "status": "skipped",
                        "submitted": False,
                        "job_title": role_title,
                        "company": company_name,
                        "message": "Skipped: Posting does not offer LinkedIn Easy Apply",
                    }

            # If not submitted or not LinkedIn, try portal apply
            if not is_submitted and not easy_apply_only:
                is_submitted, submission_msg = handle_portal_apply(page, profile, tailored_pdf, cover_pdf, auto_submit=auto_submit)

            if is_submitted:
                mark_job_applied(rowid)
                try:
                    from applypilot.networking.followup_engine import ReferralFollowUpEngine
                    fe = ReferralFollowUpEngine(db_path=conn)
                    rec_name = job.get("recruiter_name") or ""
                    fe.mark_applied(
                        job_id=str(job["url"]),
                        used_secondary_email=used_secondary,
                        recruiter_name=rec_name,
                    )
                except Exception as me:
                    log.warning("Followup engine mark_applied warning: %s", me)
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
                    if is_cdp:
                        page.close()
                    else:
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
    candidates = c.execute(query, (min_score, limit)).fetchall()
    if not candidates:
        return {"status": "no_candidates", "message": "No eligible unapplied jobs found matching criteria."}

    total = len(candidates)
    AUTO_APPLY_STATE["is_running"] = True
    AUTO_APPLY_STATE["total"] = total
    AUTO_APPLY_STATE["completed"] = 0
    AUTO_APPLY_STATE["submitted"] = []
    AUTO_APPLY_STATE["half_applied"] = []
    AUTO_APPLY_STATE["requires_login"] = []
    AUTO_APPLY_STATE["captcha_blocked"] = []
    AUTO_APPLY_STATE["last_error"] = None

    log.info("Starting Auto-Apply Batch for %d qualified candidates (auto_submit=%s)...", total, auto_submit)

    for i, cand in enumerate(candidates, 1):
        rowid, site, title, score, app_url, url = cand
        role_label = f"{title} @ {site}"
        AUTO_APPLY_STATE["current_job"] = role_label
        AUTO_APPLY_STATE["current_step"] = f"Applying ({i}/{total})"

        try:
            res = launch_application_assistant(rowid, headed=headed, auto_submit=auto_submit, is_batch=True)
            status = res.get("status")
            if res.get("submitted"):
                AUTO_APPLY_STATE["submitted"].append(role_label)
            elif status == "requires_login":
                AUTO_APPLY_STATE["requires_login"].append(role_label)
            elif status == "captcha_blocked":
                AUTO_APPLY_STATE["captcha_blocked"].append(role_label)
            else:
                AUTO_APPLY_STATE["half_applied"].append(role_label)
        except Exception as e:
            log.error("Batch apply failed on %s: %s", role_label, e)
            AUTO_APPLY_STATE["last_error"] = str(e)
            c.execute("UPDATE jobs SET apply_status = 'failed', apply_error = ? WHERE rowid = ?", (str(e), rowid))
            conn.commit()

        AUTO_APPLY_STATE["completed"] = i
        import random
        # Human delay between different jobs (6 to 14 seconds) to ensure normal behavioral traffic
        delay_sec = random.uniform(6.0, 14.0)
        log.info("Anti-ban safe delay: Waiting %.1fs before next application...", delay_sec)
        time.sleep(delay_sec)

    AUTO_APPLY_STATE["is_running"] = False
    AUTO_APPLY_STATE["current_step"] = "Finished"

    return {
        "status": "complete",
        "total": total,
        "submitted": len(AUTO_APPLY_STATE["submitted"]),
        "half_applied": len(AUTO_APPLY_STATE["half_applied"]),
        "requires_login": len(AUTO_APPLY_STATE["requires_login"]),
        "captcha_blocked": len(AUTO_APPLY_STATE["captcha_blocked"]),
    }


def mark_job_applied(identifier: str | int) -> dict:
    """Mark a job as applied in SQLite, update application_responses and refresh opportunities.csv."""
    conn = get_connection()
    c = conn.cursor()
    job = _find_job(conn, identifier)
    if not job:
        return {"status": "error", "message": f"Job '{identifier}' not found."}

    rowid = job["rowid"]
    now_iso = datetime.now(timezone.utc).isoformat()
    c.execute(
        "UPDATE jobs SET apply_status = 'applied', applied_at = ?, apply_error = NULL WHERE rowid = ?",
        (now_iso, rowid)
    )
    try:
        c.execute(
            "INSERT OR IGNORE INTO application_responses (message_id, company, role_title, sentiment, status, summary, body_snippet, synced_at) "
            "VALUES (?, ?, ?, 'Positive', 'applied', ?, ?, ?)",
            (
                f"app_{rowid}_{int(time.time())}",
                job.get("site", "Company"),
                job.get("title", "Role"),
                f"Autonomous application submitted successfully on {datetime.now().strftime('%b %d, %Y %I:%M %p')}.",
                f"Submitted application for {job.get('title', 'Role')} at {job.get('site', 'Company')}",
                now_iso,
            )
        )
    except Exception as e:
        log.warning("Could not insert application audit log: %s", e)
    conn.commit()

    try:
        from applypilot.export.csv_export import export_opportunities_csv
        export_opportunities_csv()
    except Exception as e:
        log.warning("Could not refresh opportunities.csv: %s", e)

    return {
        "status": "applied",
        "rowid": rowid,
        "title": job.get("title"),
        "company": job.get("site"),
    }


def mark_job_referral_asked(identifier: str | int, contact_name: str = "", platform: str = "LinkedIn") -> dict:
    """Record that candidate reached out to an internal referrer."""
    conn = get_connection()
    c = conn.cursor()
    job = _find_job(conn, identifier)
    if not job:
        return {"status": "error", "message": f"Job '{identifier}' not found."}

    rowid = job["rowid"]
    now_iso = datetime.now(timezone.utc).isoformat()
    snippet = f"Referral request sent to {contact_name or 'employee'} via {platform} on {datetime.now().strftime('%b %d, %Y')}."
    c.execute(
        "UPDATE jobs SET referral_status = 'asked', referral_contact_name = ?, referral_contact_platform = ? WHERE rowid = ?",
        (contact_name, platform, rowid)
    )
    try:
        c.execute(
            "INSERT OR IGNORE INTO application_responses (message_id, company, role_title, sentiment, status, summary, body_snippet, synced_at) "
            "VALUES (?, ?, ?, 'Neutral', 'referral_request', ?, ?, ?)",
            (
                f"ref_{rowid}_{int(time.time())}",
                job.get("site", "Company"),
                job.get("title", "Role"),
                f"Referral outreach to {contact_name or 'contact'} on {platform}",
                snippet,
                now_iso,
            )
        )
    except Exception as e:
        log.warning("Could not insert referral audit log: %s", e)
    conn.commit()
    return {"status": "ok", "rowid": rowid}
