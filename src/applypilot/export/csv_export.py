"""CSV Exporter for ApplyPilot job opportunities.

Maintains ONE single master sheet: opportunities.csv.
Updated in place every day with all jobs, sorted by fit score (top matches first).
Includes Recruiter Email for direct cold-email reach-out.
Paths are kept short and clean (e.g. tailored_resumes\\file.pdf).
"""

import csv
import logging
from pathlib import Path
from applypilot.config import APP_DIR
from applypilot.database import get_connection

log = logging.getLogger(__name__)


def _clean_path(p: str | None) -> str:
    """Format path concisely as folder\\filename.pdf instead of full D:\\... path."""
    if not p:
        return ""
    p_str = str(p)
    for folder in ["tailored_resumes", "cover_letters"]:
        idx = p_str.find(folder)
        if idx != -1:
            return p_str[idx:].replace("/", "\\")
    return Path(p_str).name


def export_opportunities_csv(output_path: Path | str | None = None) -> Path:
    """Export all opportunities to the single master opportunities.csv file.

    Sorted with top-fit (>= 7/10) jobs with ready resumes/cover letters at the top.
    """
    if output_path is None:
        target_path = APP_DIR / "opportunities.csv"
    else:
        target_path = Path(output_path)

    conn = get_connection()

    fieldnames = [
        "Company", "Title", "Location", "Rating (Fit Score 1-10)",
        "Recruiter Email", "Apply Link", "Tailored Resume PDF", "Cover Letter PDF",
        "LinkedIn Referral Search", "Discovered At", "Scored At", "Match Reasoning"
    ]

    from applypilot.networking.outreach import generate_linkedin_searches

    query = """
        SELECT 
            COALESCE(site, 'Unknown') AS company,
            COALESCE(title, 'N/A') AS title,
            COALESCE(location, 'N/A') AS location,
            fit_score AS rating,
            COALESCE(recruiter_email, '') AS recruiter_email,
            COALESCE(application_url, url) AS apply_link,
            COALESCE(tailored_resume_path, '') AS tailored_resume_pdf,
            COALESCE(cover_letter_path, '') AS cover_letter_pdf,
            COALESCE(discovered_at, '') AS discovered_at,
            COALESCE(scored_at, '') AS scored_at,
            COALESCE(score_reasoning, '') AS match_reasoning,
            COALESCE(full_description, '') AS full_desc,
            COALESCE(description, '') AS desc
        FROM jobs
        ORDER BY fit_score DESC NULLS LAST, discovered_at DESC
    """
    rows = conn.execute(query).fetchall()

    import re
    from applypilot.config import load_search_config
    cfg = load_search_config()
    reject_patterns = cfg.get("location", {}).get("reject_patterns", [])
    seniority_cfg = cfg.get("seniority", {})
    reject_titles = [t.lower() for t in seniority_cfg.get("reject_titles", [
        "senior", "sr.", "sr ", "lead", "tech lead", "staff", "principal", "manager", "mgr", "director", "architect", "head"
    ])]
    exp_pattern = re.compile(r'(\d+)\+?\s*(?:to\s*(\d+))?\s*(?:years?|yrs?)(?:\s*of)?\s*experience', re.IGNORECASE)

    formatted_rows = []
    for r in rows:
        row = list(r)
        comp = row[0]
        tit = row[1]
        loc = (row[2] or "").lower()
        full_desc = row[11]
        desc = row[12]

        # 1. Filter out jobs that match location reject patterns (e.g. US-only remote, Canada, UK)
        if any(rp.lower() in loc for rp in reject_patterns):
            continue

        # 2. Filter out senior / high-experience titles (Deepak has ~1.3 yrs exp)
        tit_lower = tit.lower()
        if any(st in tit_lower for st in reject_titles):
            continue

        # 3. Filter out roles explicitly requiring 4+ years of experience
        text = f"{tit} {full_desc} {desc}"
        matches = exp_pattern.findall(text)
        if matches:
            years = [int(m[0]) for m in matches if m[0].isdigit()]
            if years and min(years) >= 4:
                continue

        # Slice off full_desc and desc from CSV row
        row = row[:11]

        # item 6: tailored_resume_pdf
        row[6] = _clean_path(row[6])
        # item 7: cover_letter_pdf
        row[7] = _clean_path(row[7])

        # LinkedIn Referral Search Link for RVCE alumni
        ref_searches = generate_linkedin_searches(comp, tit)
        alumni_link = ref_searches.get("alumni_search_url", "")
        # Insert alumni_link before item 8 (discovered_at)
        row.insert(8, alumni_link)

        formatted_rows.append(row)

    try:
        with open(target_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(fieldnames)
            for r in formatted_rows:
                writer.writerow(r)
    except PermissionError:
        log.warning("File %s is currently open in Excel. Please close it so it can be updated directly.", target_path.name)
        # Fall back to writing safely if open
        alt_path = target_path.with_name(f"{target_path.stem}_latest.csv")
        with open(alt_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(fieldnames)
            for r in formatted_rows:
                writer.writerow(r)
        return alt_path

    log.info("Updated master sheet %s with %d opportunities (including recruiter emails)", target_path.name, len(formatted_rows))
    return target_path
