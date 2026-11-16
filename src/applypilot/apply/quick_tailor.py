"""Job Tailor & Referral Generator: Process any job link on-demand.

Extracts Job Description (JD), company, title, location from link (Playwright / BeautifulSoup),
tailors Deepak's resume + cover letter instantly, and generates high-converting referral & recruiter
outreach messages + 1-click LinkedIn network search links.
"""

import json
import logging
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

from applypilot.config import APP_DIR, DB_PATH, RESUME_PATH, TAILORED_DIR, COVER_LETTER_DIR, load_env, load_profile
from applypilot.database import get_connection
from applypilot.llm import get_client
from applypilot.networking.outreach import generate_outreach_messages, generate_linkedin_searches
from applypilot.scoring.cover_letter import generate_cover_letter
from applypilot.scoring.pdf import convert_to_pdf
from applypilot.scoring.tailor import tailor_resume

log = logging.getLogger(__name__)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"


def fetch_job_page(url: str) -> tuple[str, str]:
    """Fetch job posting webpage content and extract clean text and title.
    
    Tries standard fast HTTP request first. If content seems dynamic or empty,
    falls back to headless Playwright.
    """
    raw_html = ""
    title_tag = ""

    # Strategy 1: Fast HTTP GET
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": UA,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            raw_html = resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        log.warning("Fast HTTP fetch failed for %s: %s. Trying Playwright fallback...", url, e)

    # Strategy 2: Playwright fallback if fast fetch got blocked or short content
    if not raw_html or len(raw_html) < 800:
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(user_agent=UA)
                page.goto(url, timeout=25000, wait_until="domcontentloaded")
                try:
                    page.wait_for_timeout(2000)
                except Exception:
                    pass
                raw_html = page.content()
                browser.close()
        except Exception as e:
            log.warning("Playwright fallback also failed for %s: %s", url, e)

    if not raw_html:
        return "", ""

    soup = BeautifulSoup(raw_html, "html.parser")
    if soup.title and soup.title.string:
        title_tag = soup.title.string.strip()

    for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "svg", "button", "input"]):
        tag.decompose()

    text = soup.get_text(separator="\n", strip=True)
    # Remove excessive blank lines
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    return text[:15000], title_tag


def extract_job_details_with_llm(page_text: str, title_tag: str, url: str) -> dict[str, str]:
    """Use LLM to accurately extract Company, Role Title, Location, and Core JD."""
    load_env()
    client = get_client()

    prompt = f"""You are an expert technical talent analyst.
Analyze the following webpage content for a job posting.
URL: {url}
HTML Page Title: {title_tag}

Webpage text excerpt:
\"\"\"
{page_text[:7000]}
\"\"\"

Extract the exact job details and return ONLY a valid JSON object matching this schema:
{{
  "company": "Company Name (clean, without Inc/Pvt Ltd/Hiring)",
  "title": "Exact Role Title (e.g. SDE-I Backend Engineer, Software Engineer, etc.)",
  "location": "Location (e.g. Bengaluru, India / Remote)",
  "job_description_summary": "Clean 3-5 paragraph summary of key responsibilities and tech stack required",
  "required_skills": ["Skill1", "Skill2", "Skill3"]
}}
Return raw JSON with no Markdown wrapping or conversational explanation.
"""
    try:
        raw_resp = client.ask(prompt)
        cleaned = raw_resp.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        data = json.loads(cleaned)
        return {
            "company": str(data.get("company") or "").strip() or "Company",
            "title": str(data.get("title") or "").strip() or "Software Engineer",
            "location": str(data.get("location") or "").strip() or "Bengaluru, India",
            "jd": str(data.get("job_description_summary") or "").strip() or page_text[:2000],
            "skills": ", ".join(data.get("required_skills", [])) if isinstance(data.get("required_skills"), list) else ""
        }
    except Exception as e:
        log.error("LLM job extraction failed: %s", e)
        # Fallback to heuristics
        guessed_comp = "Target Company"
        guessed_title = "Software Engineer"
        if title_tag:
            parts = [p.strip() for p in re.split(r"[-|–—:]", title_tag) if p.strip()]
            if len(parts) >= 2:
                guessed_title = parts[0]
                guessed_comp = parts[1]
            elif len(parts) == 1:
                guessed_title = parts[0]
        return {
            "company": guessed_comp,
            "title": guessed_title,
            "location": "Bengaluru, India",
            "jd": page_text[:2000],
            "skills": "",
        }


def process_job_link(url: str, manual_jd: str = "") -> dict[str, Any]:
    """Complete workflow: Link -> JD Extraction -> Tailored Resume & PDF -> Referral Messages.
    
    Returns a rich dictionary containing:
    - Extracted details (company, title, location, jd, skills)
    - Customized referral messages (1st-degree, 2nd-degree, alumni, recruiter, KaDegree)
    - LinkedIn search URLs
    - Tailored resume text & download paths (PDF & TXT)
    - Cover letter text & download path
    - rowid in database if persisted
    """
    load_env()
    profile = load_profile()
    resume_text = RESUME_PATH.read_text(encoding="utf-8")

    jd_text = ""
    title_tag = ""
    company = ""
    title = ""
    location = ""
    skills = ""

    if manual_jd and len(manual_jd.strip()) > 30:
        jd_text = manual_jd.strip()
        extracted = extract_job_details_with_llm(jd_text, "", url)
        company = extracted["company"]
        title = extracted["title"]
        location = extracted["location"]
        skills = extracted["skills"]
    elif url:
        page_text, title_tag = fetch_job_page(url)
        if not page_text:
            return {"status": "error", "message": f"Could not fetch or parse job page from {url}. Please ensure URL is accessible or paste JD text directly."}
        extracted = extract_job_details_with_llm(page_text, title_tag, url)
        company = extracted["company"]
        title = extracted["title"]
        location = extracted["location"]
        skills = extracted["skills"]
        jd_text = extracted["jd"]
    else:
        return {"status": "error", "message": "Please provide a valid Job URL or Job Description text."}

    # Generate Referral & Outreach Messages & Links
    outreach = generate_outreach_messages(
        company=company,
        role_title=title,
        apply_url=url,
        candidate_profile=profile
    )
    # Ensure aliases for UI and CLI display
    if "first_deg_message" in outreach and "first_degree_message" not in outreach:
        outreach["first_degree_message"] = outreach["first_deg_message"]
    if "second_deg_message" in outreach and "second_degree_message" not in outreach:
        outreach["second_degree_message"] = outreach["second_deg_message"]

    searches = generate_linkedin_searches(company, title)
    outreach.update(searches)

    # Tailor Resume & Cover Letter
    TAILORED_DIR.mkdir(parents=True, exist_ok=True)
    COVER_LETTER_DIR.mkdir(parents=True, exist_ok=True)
    prefix = re.sub(r"[^\w\-]", "_", f"Quick_{company}_{title}")[:45]

    job_dict = {
        "title": title,
        "site": company,
        "location": location,
        "full_description": jd_text,
        "url": url,
    }

    tailored_txt = ""
    pdf_resume_path = ""
    txt_resume_path = ""
    cover_txt = ""
    pdf_cover_path = ""

    try:
        log.info("Tailoring resume for quick job: %s @ %s", title, company)
        tailored_txt, _ = tailor_resume(resume_text, job_dict, profile, validation_mode="normal")

        txt_file = TAILORED_DIR / f"{prefix}.txt"
        txt_file.write_text(tailored_txt, encoding="utf-8")
        txt_resume_path = str(txt_file.relative_to(APP_DIR))

        pdf_file = TAILORED_DIR / f"{prefix}.pdf"
        compiled = convert_to_pdf(txt_file, output_path=pdf_file)
        if compiled and compiled.exists():
            pdf_resume_path = str(compiled.relative_to(APP_DIR))
        else:
            pdf_resume_path = txt_resume_path
    except Exception as e:
        log.warning("Quick resume tailoring error: %s. Using base resume.", e)
        tailored_txt = resume_text

    try:
        log.info("Generating cover letter for quick job: %s @ %s", title, company)
        cover_txt = generate_cover_letter(tailored_txt or resume_text, job_dict, profile)
        c_txt_file = COVER_LETTER_DIR / f"{prefix}_CL.txt"
        c_txt_file.write_text(cover_txt, encoding="utf-8")

        c_pdf_file = COVER_LETTER_DIR / f"{prefix}_CL.pdf"
        c_compiled = convert_to_pdf(c_txt_file, output_path=c_pdf_file)
        if c_compiled and c_compiled.exists():
            pdf_cover_path = str(c_compiled.relative_to(APP_DIR))
    except Exception as e:
        log.warning("Quick cover letter generation error: %s", e)

    # Persist or update into SQLite jobs database
    rowid = None
    try:
        conn = get_connection()
        c = conn.cursor()
        now = datetime.now(timezone.utc).isoformat()
        
        # Check if URL exists
        existing = c.execute("SELECT rowid FROM jobs WHERE url = ?", (url,)).fetchone()
        if existing:
            rowid = existing[0]
            c.execute("""
                UPDATE jobs SET 
                    title = COALESCE(?, title),
                    site = COALESCE(?, site),
                    location = COALESCE(?, location),
                    full_description = COALESCE(?, full_description),
                    tailored_resume_path = COALESCE(?, tailored_resume_path),
                    cover_letter_path = COALESCE(?, cover_letter_path),
                    tailored_at = ?
                WHERE rowid = ?
            """, (title, company, location, jd_text, pdf_resume_path, pdf_cover_path, now, rowid))
        else:
            c.execute("""
                INSERT INTO jobs (
                    url, title, site, location, full_description, application_url,
                    strategy, discovered_at, tailored_resume_path, cover_letter_path, tailored_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'quick_link_intake', ?, ?, ?, ?)
            """, (url, title, company, location, jd_text, url, now, pdf_resume_path, pdf_cover_path, now))
            rowid = c.lastrowid
        conn.commit()
    except Exception as e:
        log.error("Failed to persist quick job to DB: %s", e)

    return {
        "status": "ok",
        "rowid": rowid,
        "company": company,
        "title": title,
        "location": location,
        "skills": skills,
        "jd": jd_text,
        "outreach": outreach,
        "tailored_resume_text": tailored_txt,
        "pdf_resume_path": pdf_resume_path,
        "cover_letter_text": cover_txt,
        "pdf_cover_path": pdf_cover_path,
        "url": url,
    }
