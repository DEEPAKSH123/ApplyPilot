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
        "Discovered At", "Scored At", "Match Reasoning"
    ]

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
            COALESCE(score_reasoning, '') AS match_reasoning
        FROM jobs
        ORDER BY fit_score DESC NULLS LAST, discovered_at DESC
    """
    rows = conn.execute(query).fetchall()

    formatted_rows = []
    for r in rows:
        row = list(r)
        # item 6: tailored_resume_pdf
        row[6] = _clean_path(row[6])
        # item 7: cover_letter_pdf
        row[7] = _clean_path(row[7])
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
