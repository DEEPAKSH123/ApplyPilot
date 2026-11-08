"""CSV Exporter for ApplyPilot job opportunities.

Generates two distinct sheets for maximum confidence:
1. ready_to_apply.csv: Curated, high-fit (>= 7/10) actionable applications with ready PDFs.
2. all_opportunities.csv: Comprehensive raw dump of all discovered jobs for audit/history.
Handles Windows file locks gracefully if files are currently open in Excel.
"""

import csv
import logging
from pathlib import Path
from applypilot.config import APP_DIR
from applypilot.database import get_connection

log = logging.getLogger(__name__)


def _safe_write_csv(path: Path, fieldnames: list[str], rows: list) -> Path:
    """Write CSV safely, handling file locks if open in Excel."""
    try:
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(fieldnames)
            for r in rows:
                writer.writerow(list(r))
        return path
    except PermissionError:
        log.warning("File %s is currently open in Excel or another program. Writing to _latest.csv instead.", path.name)
        alt_path = path.with_name(f"{path.stem}_latest.csv")
        try:
            with open(alt_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(fieldnames)
                for r in rows:
                    writer.writerow(list(r))
            return alt_path
        except Exception as e:
            log.error("Could not write CSV to fallback %s: %s", alt_path.name, e)
            return path


def export_opportunities_csv(output_path: Path | str | None = None, min_apply_score: int = 7) -> Path:
    """Export scored and discovered opportunities from SQLite to clean CSV files.

    Outputs:
      - ready_to_apply.csv: Curated list of high-fit jobs (fit_score >= min_apply_score)
      - all_opportunities.csv: Full raw dump of all jobs
      - opportunities.csv: Kept for backward compatibility
    """
    conn = get_connection()

    fieldnames = [
        "Company", "Title", "Location", "Rating (Fit Score 1-10)",
        "Apply Link", "Tailored Resume PDF", "Cover Letter PDF",
        "Discovered At", "Scored At", "Match Reasoning"
    ]

    # 1. Query full dump
    all_query = """
        SELECT 
            COALESCE(site, 'Unknown') AS company,
            COALESCE(title, 'N/A') AS title,
            COALESCE(location, 'N/A') AS location,
            fit_score AS rating,
            COALESCE(application_url, url) AS apply_link,
            COALESCE(tailored_resume_path, '') AS tailored_resume_pdf,
            COALESCE(cover_letter_path, '') AS cover_letter_pdf,
            COALESCE(discovered_at, '') AS discovered_at,
            COALESCE(scored_at, '') AS scored_at,
            COALESCE(score_reasoning, '') AS match_reasoning
        FROM jobs
        ORDER BY fit_score DESC NULLS LAST, discovered_at DESC
    """
    all_rows = conn.execute(all_query).fetchall()

    all_csv_path = _safe_write_csv(APP_DIR / "all_opportunities.csv", fieldnames, all_rows)
    _safe_write_csv(APP_DIR / "opportunities.csv", fieldnames, all_rows)

    # 2. Query curated Ready-to-Apply opportunities (fit_score >= min_apply_score)
    ready_query = """
        SELECT 
            COALESCE(site, 'Unknown') AS company,
            COALESCE(title, 'N/A') AS title,
            COALESCE(location, 'N/A') AS location,
            fit_score AS rating,
            COALESCE(application_url, url) AS apply_link,
            COALESCE(tailored_resume_path, '') AS tailored_resume_pdf,
            COALESCE(cover_letter_path, '') AS cover_letter_pdf,
            COALESCE(discovered_at, '') AS discovered_at,
            COALESCE(scored_at, '') AS scored_at,
            COALESCE(score_reasoning, '') AS match_reasoning
        FROM jobs
        WHERE fit_score >= ?
        ORDER BY fit_score DESC, discovered_at DESC
    """
    ready_rows = conn.execute(ready_query, (min_apply_score,)).fetchall()

    ready_csv_path = _safe_write_csv(APP_DIR / "ready_to_apply.csv", fieldnames, ready_rows)

    log.info(
        "Exported %d total opportunities and %d high-fit curated jobs to %s",
        len(all_rows), len(ready_rows), ready_csv_path.name
    )

    return ready_csv_path
