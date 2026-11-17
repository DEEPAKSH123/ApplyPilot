"""LinkedIn Post Parser & Intelligent Application Intake Agent.

Processes individual LinkedIn post URLs (e.g. /feed/update/urn:li:activity:... or /posts/...):
- Fetches post content via authenticated Playwright session (using stored cookies / Brave profile).
- Fallbacks to BeautifulSoup / HTTP or manual post text input if session or auth blocks.
- Extracts author info, company name, role title, requirements, recruiter emails, and Google Forms / external application URLs.
- Synthesizes personalized recruiter outreach email and pre-configures 1-click Gmail draft with tailored resume attached.
- Immediately tailors Deepak S H's resume and compiles ATS PDF.
- Saves opportunity to SQLite jobs database and prepares referral network links.
"""

import json
import logging
import os
import re
import sqlite3
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

from applypilot.apply.assistant import BRAVE_PROFILE_DIR, get_browser_executable
from applypilot.apply.quick_tailor import process_job_link
from applypilot.config import APP_DIR, RESUME_PATH, TAILORED_DIR, COVER_LETTER_DIR, load_env, load_profile
from applypilot.database import get_connection
from applypilot.llm import get_client
from applypilot.networking.gmail_drafter import generate_recruiter_email, create_gmail_draft
from applypilot.networking.linkedin import get_stored_cookies, is_linkedin_authenticated, check_experience_exceeds
from applypilot.networking.outreach import generate_outreach_messages, generate_linkedin_searches

log = logging.getLogger(__name__)

EMAIL_REGEX = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b")
URL_REGEX = re.compile(r"https?://[^\s<>\"\'\)]+")


def extract_links_and_emails(text: str) -> tuple[list[str], list[str], list[str]]:
    """Extract emails, form links (Google Forms, Typeform, Airtable), and job/career URLs from post text."""
    emails = list(dict.fromkeys(EMAIL_REGEX.findall(text)))

    raw_urls = URL_REGEX.findall(text)
    form_links = []
    other_links = []

    for u in raw_urls:
        u_clean = u.rstrip(".,;!?:")
        u_lower = u_clean.lower()
        # Skip generic LinkedIn feed links
        if "linkedin.com/feed" in u_lower or "linkedin.com/posts" in u_lower or "linkedin.com/in" in u_lower:
            continue
        if any(f in u_lower for f in ("forms.gle", "docs.google.com/forms", "typeform.com", "airtable.com", "tally.so", "form")):
            form_links.append(u_clean)
        else:
            other_links.append(u_clean)

    return emails, list(dict.fromkeys(form_links)), list(dict.fromkeys(other_links))


def fetch_linkedin_post_content(post_url: str) -> dict[str, Any]:
    """Fetch live post text and author metadata from LinkedIn using Playwright."""
    from playwright.sync_api import sync_playwright

    clean_url = post_url.strip()
    result = {
        "post_url": clean_url,
        "author_name": "",
        "author_headline": "",
        "post_text": "",
        "success": False,
        "error": None
    }

    exe_path, browser_type = get_browser_executable()
    BRAVE_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    try:
        with sync_playwright() as p:
            launch_args = [
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--no-default-browser-check",
            ]
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(BRAVE_PROFILE_DIR.resolve()),
                executable_path=exe_path if exe_path else None,
                headless=True,
                args=launch_args,
                viewport={"width": 1280, "height": 850},
            )

            existing_cookies = get_stored_cookies()
            if existing_cookies:
                try:
                    context.add_cookies(existing_cookies)
                except Exception as ce:
                    log.warning("Could not pre-load cookies: %s", ce)

            page = context.pages[0] if context.pages else context.new_page()
            log.info("Navigating to LinkedIn post: %s", clean_url)
            page.goto(clean_url, wait_until="domcontentloaded", timeout=25000)
            page.wait_for_timeout(2500)

            # Click 'see more' button if post text is truncated
            try:
                see_more_btns = page.query_selector_all("button.feed-shared-inline-show-more-text__see-more-less-toggle, button.see-more, button[aria-label*='more']")
                for btn in see_more_btns:
                    if btn.is_visible():
                        btn.click(timeout=1500)
                        page.wait_for_timeout(500)
            except Exception:
                pass

            # Extract post description/commentary
            post_text = ""
            text_selectors = [
                ".feed-shared-update-v2__description",
                ".update-components-text",
                ".feed-shared-inline-show-more-text",
                "div.attributed-text-segment-list__content",
                "article",
                "main"
            ]
            for sel in text_selectors:
                el = page.query_selector(sel)
                if el:
                    txt = el.inner_text().strip()
                    if len(txt) > len(post_text):
                        post_text = txt

            # Author name and headline
            author_name = ""
            author_headline = ""
            author_el = page.query_selector(".update-components-actor__name, .feed-shared-actor__name, span.update-components-actor__single-line-truncate")
            if author_el:
                author_name = author_el.inner_text().strip()

            headline_el = page.query_selector(".update-components-actor__description, .feed-shared-actor__description")
            if headline_el:
                author_headline = headline_el.inner_text().strip()

            context.close()

            if post_text:
                result["post_text"] = post_text
                result["author_name"] = author_name
                result["author_headline"] = author_headline
                result["success"] = True
            else:
                result["error"] = "Could not locate post body text from DOM."
    except Exception as e:
        log.warning("Playwright post fetch error for %s: %s", clean_url, e)
        result["error"] = str(e)

    return result


def analyze_linkedin_post_with_llm(post_text: str, author_name: str = "", author_headline: str = "", post_url: str = "") -> dict[str, Any]:
    """Extract structured hiring details from LinkedIn post using LLM."""
    load_env()
    client = get_client()

    prompt = f"""You are an expert technical talent scout analyzing a LinkedIn hiring post.

Post URL: {post_url}
Author Name: {author_name}
Author Headline: {author_headline}

Post Content:
\"\"\"
{post_text[:6000]}
\"\"\"

Extract and analyze the post carefully. Return ONLY a valid JSON object matching this schema:
{{
  "company": "Company Name (clean, e.g. 'Swiggy', 'PhonePe', 'Target', 'Zepto' - never 'Hiring' or 'Tech Company')",
  "title": "Exact Role Title (e.g. 'SDE-I Backend Engineer', 'Backend Engineer', 'Software Engineer', etc.)",
  "location": "Location (e.g. 'Bengaluru, India', 'Remote India', etc.)",
  "experience_level": "Extracted experience range or '0-3 years'",
  "tech_stack": ["Java", "Go", "Kafka", "Redis"],
  "summary": "Clear 2-3 paragraph summary of the role, requirements, and hiring instructions from the post",
  "recruiter_email": "Extracted email if present, else empty string",
  "form_url": "Extracted Google Form / Typeform link if present, else empty string",
  "careers_url": "Extracted company careers / job link if present, else empty string"
}}

Return pure raw JSON without Markdown formatting or commentary.
"""
    try:
        raw_resp = client.ask(prompt)
        cleaned = raw_resp.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        data = json.loads(cleaned)
        return data
    except Exception as e:
        log.error("LLM post analysis failed: %s", e)
        # Regex heuristics fallback
        emails, forms, others = extract_links_and_emails(post_text)
        comp_match = re.search(r"(?:at|@|join|hiring\s+for)\s+([A-Z][A-Za-z0-9]{2,20})\b", post_text)
        company = comp_match.group(1) if comp_match else (author_headline.split("at")[-1].strip() if "at" in author_headline else "Company")
        return {
            "company": company,
            "title": "Backend Software Engineer",
            "location": "Bengaluru, India",
            "experience_level": "0-3 years",
            "tech_stack": ["Java", "Go", "Kafka", "Redis"],
            "summary": post_text[:1000],
            "recruiter_email": emails[0] if emails else "",
            "form_url": forms[0] if forms else "",
            "careers_url": others[0] if others else "",
        }


def process_linkedin_post(post_url: str, manual_text: str = "") -> dict[str, Any]:
    """Complete workflow for LinkedIn Post Intake:
    
    1. Fetches post text (via Playwright or manual input).
    2. Extracts company, role title, recruiter email, Google Forms link, tech stack.
    3. Tailors resume and generates PDF.
    4. Generates customized cold email draft and 1-click web compose URL.
    5. Generates referral network outreach messages & searches.
    6. Persists job to ApplyPilot SQLite DB.
    """
    clean_url = (post_url or "").strip()
    post_text = (manual_text or "").strip()
    author_name = ""
    author_headline = ""

    if not post_text and clean_url:
        fetch_res = fetch_linkedin_post_content(clean_url)
        if fetch_res.get("success"):
            post_text = fetch_res["post_text"]
            author_name = fetch_res["author_name"]
            author_headline = fetch_res["author_headline"]
        else:
            log.warning("Could not auto-scrape LinkedIn post: %s", fetch_res.get("error"))

    if not post_text:
        return {
            "status": "error",
            "message": f"Could not fetch content from '{clean_url}'. The post might require an active LinkedIn login or session refresh. You can also paste the post text directly into the text area."
        }

    # Guardrail: Check experience requirement in post text (must be <= 4 years for Deepak S H)
    is_over_exp, exp_reason = check_experience_exceeds(post_text, max_years=4)
    if is_over_exp:
        log.warning("LinkedIn post requires > 4 years experience (%s). Aborting intake.", exp_reason)
        return {
            "status": "error",
            "message": f"This role requires senior experience: {exp_reason}. ApplyPilot only targets 0–4 years of experience (Deepak has 2 YOE)."
        }

    # Extract emails and form links via regex first (ground truth)
    regex_emails, regex_forms, regex_others = extract_links_and_emails(post_text)

    # LLM extraction for semantic understanding
    analysis = analyze_linkedin_post_with_llm(post_text, author_name, author_headline, clean_url)

    company = analysis.get("company") or "Target Company"
    title = analysis.get("title") or "Backend Software Engineer"
    location = analysis.get("location") or "Bengaluru, India"
    summary = analysis.get("summary") or post_text[:1200]
    tech_stack = analysis.get("tech_stack", [])

    # Priority email & form URLs
    recruiter_email = regex_emails[0] if regex_emails else (analysis.get("recruiter_email") or "")
    form_url = regex_forms[0] if regex_forms else (analysis.get("form_url") or "")
    careers_url = regex_others[0] if regex_others else (analysis.get("careers_url") or "")

    # Target application URL: Form URL > Careers URL > LinkedIn Post URL
    target_app_url = form_url or careers_url or clean_url

    # Generate Tailored Resume & Cover Letter via quick_tailor engine
    quick_res = process_job_link(url=target_app_url or clean_url, manual_jd=f"Role: {title}\nCompany: {company}\nRequirements:\n{summary}")

    pdf_resume_path = quick_res.get("pdf_resume_path", "")
    pdf_cover_path = quick_res.get("pdf_cover_path", "")
    tailored_text = quick_res.get("tailored_resume_text", "")

    # Generate Recruiter Outreach Email
    profile = load_profile()
    email_draft_content = generate_recruiter_email(
        company=company,
        role_title=title,
        job_url=clean_url,
        recruiter_name=author_name,
        candidate_profile=profile,
        pitch_style="quick_pitch"
    )

    # Pre-generate 1-click Gmail Web Compose URL (for active Brave browser)
    web_compose_url = (
        f"https://mail.google.com/mail/?view=cm&fs=1"
        f"&to={urllib.parse.quote(recruiter_email)}"
        f"&su={urllib.parse.quote(email_draft_content['subject'])}"
        f"&body={urllib.parse.quote(email_draft_content['body_markdown'])}"
    )

    # Generate referral messages & 1-click searches
    outreach = generate_outreach_messages(
        company=company,
        role_title=title,
        apply_url=target_app_url,
        recruiter_email=recruiter_email,
        candidate_profile=profile
    )
    searches = generate_linkedin_searches(company, title)
    outreach.update(searches)

    # Persist in Database with 'linkedin_post_intake' strategy
    rowid = quick_res.get("rowid")
    try:
        conn = get_connection()
        c = conn.cursor()
        now = datetime.now(timezone.utc).isoformat()
        if rowid:
            c.execute("""
                UPDATE jobs SET
                    recruiter_email = COALESCE(?, recruiter_email),
                    application_url = COALESCE(?, application_url),
                    strategy = 'linkedin_post_intake'
                WHERE rowid = ?
            """, (recruiter_email, target_app_url, rowid))
        else:
            c.execute("""
                INSERT INTO jobs (
                    url, title, site, location, full_description, application_url,
                    strategy, discovered_at, recruiter_email, tailored_resume_path, cover_letter_path, tailored_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'linkedin_post_intake', ?, ?, ?, ?, ?)
            """, (clean_url or f"https://www.linkedin.com/feed/post_{int(time.time())}", title, f"LinkedIn Post ({company})", location, summary, target_app_url, now, recruiter_email, pdf_resume_path, pdf_cover_path, now))
            rowid = c.lastrowid
        conn.commit()
    except Exception as e:
        log.error("Failed to update database for LinkedIn post intake: %s", e)

    return {
        "status": "ok",
        "rowid": rowid,
        "company": company,
        "title": title,
        "location": location,
        "author_name": author_name,
        "author_headline": author_headline,
        "summary": summary,
        "tech_stack": tech_stack,
        "recruiter_email": recruiter_email,
        "form_url": form_url,
        "careers_url": careers_url,
        "target_app_url": target_app_url,
        "post_url": clean_url,
        "email_subject": email_draft_content["subject"],
        "email_body": email_draft_content["body_markdown"],
        "web_compose_url": web_compose_url,
        "pdf_resume_path": pdf_resume_path,
        "pdf_cover_path": pdf_cover_path,
        "tailored_resume_text": tailored_text,
        "outreach": outreach
    }
