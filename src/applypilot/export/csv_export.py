"""CSV Exporter for ApplyPilot job opportunities.

Exports scored jobs with company, rating, apply link, tailored resume, and cover letter.
"""

import csv
import logging
from pathlib import Path
from applypilot.config import APP_DIR
from applypilot.database import get_connection

log = logging.getLogger(__name__)


def export_opportunities_csv(output_path: Path | str | None = None) -> Path:
    """Export scored and discovered opportunities from SQLite to a clean CSV.

    Columns:
      Company, Title, Location, Rating (Fit Score), Apply Link,
      Tailored Resume PDF, Cover Letter PDF, Discovered At, Scored At, Match Reasoning
    """
    if output_path is None:
        output_path = APP_DIR / "opportunities.csv"
    else:
        output_path = Path(output_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    conn = get_connection()
    query = """
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
    rows = conn.execute(query).fetchall()

    fieldnames = [
        "Company", "Title", "Location", "Rating (Fit Score 1-10)",
        "Apply Link", "Tailored Resume PDF", "Cover Letter PDF",
        "Discovered At", "Scored At", "Match Reasoning"
    ]

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(fieldnames)
        for r in rows:
            writer.writerow(list(r))

    log.info("Exported %d opportunities to %s", len(rows), output_path)
    return output_path
