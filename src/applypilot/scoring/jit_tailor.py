"""Just-In-Time (JIT) On-Demand Tailoring.

Tailors resume and generates cover letter for a specific single job on-demand,
compiling vector PDFs instantly and updating database + master CSV.
"""

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from applypilot.config import APP_DIR, COVER_LETTER_DIR, RESUME_PATH, TAILORED_DIR, load_env, load_profile
from applypilot.database import get_connection
from applypilot.export.csv_export import export_opportunities_csv
from applypilot.scoring.cover_letter import generate_cover_letter
from applypilot.scoring.pdf import convert_to_pdf
from applypilot.scoring.tailor import tailor_resume

log = logging.getLogger(__name__)


def tailor_single_job(rowid: int, validation_mode: str = "normal") -> dict[str, Any]:
    """Tailor resume and cover letter for a single job by rowid in real-time."""
    load_env()
    conn = get_connection()
    c = conn.cursor()
    row = c.execute(
        "SELECT rowid, url, title, site, location, full_description, tailored_resume_path, cover_letter_path FROM jobs WHERE rowid = ?",
        (rowid,)
    ).fetchone()
    if not row:
        return {"status": "error", "message": f"Job rowid {rowid} not found."}

    job = {
        "rowid": row[0],
        "url": row[1],
        "title": row[2] or "Software Engineer",
        "site": row[3] or "Company",
        "location": row[4] or "Bengaluru, India",
        "full_description": row[5] or "",
        "tailored_resume_path": row[6],
        "cover_letter_path": row[7],
    }

    profile = load_profile()
    resume_text = RESUME_PATH.read_text(encoding="utf-8")
    now = datetime.now(timezone.utc).isoformat()

    prefix = re.sub(r"[^\w\-]", "_", f"{job['site']}_{job['title']}")[:50]
    TAILORED_DIR.mkdir(parents=True, exist_ok=True)
    COVER_LETTER_DIR.mkdir(parents=True, exist_ok=True)

    pdf_resume_path = None
    pdf_cover_path = None

    # 1. Tailor Resume
    try:
        log.info("JIT Tailoring resume for: %s @ %s", job['title'], job['site'])
        tailored_txt, report = tailor_resume(resume_text, job, profile, validation_mode=validation_mode)

        txt_path = TAILORED_DIR / f"{prefix}.txt"
        txt_path.write_text(tailored_txt, encoding="utf-8")

        pdf_dest = TAILORED_DIR / f"{prefix}.pdf"
        compiled = convert_to_pdf(txt_path, output_path=pdf_dest)
        if compiled and compiled.exists():
            pdf_resume_path = str(compiled.relative_to(APP_DIR))
        else:
            pdf_resume_path = str(txt_path.relative_to(APP_DIR))

        c.execute(
            "UPDATE jobs SET tailored_resume_path=?, tailored_at=?, tailor_attempts=COALESCE(tailor_attempts,0)+1 WHERE rowid=?",
            (pdf_resume_path, now, rowid)
        )
        conn.commit()
    except Exception as e:
        log.error("JIT Resume tailoring failed: %s", e)
        return {"status": "error", "message": f"Resume tailoring failed: {e}"}

    # 2. Generate Cover Letter
    try:
        log.info("JIT Generating cover letter for: %s @ %s", job['title'], job['site'])
        cover_txt = generate_cover_letter(tailored_txt or resume_text, job, profile)

        c_txt_path = COVER_LETTER_DIR / f"{prefix}_CL.txt"
        c_txt_path.write_text(cover_txt, encoding="utf-8")

        c_pdf_dest = COVER_LETTER_DIR / f"{prefix}_CL.pdf"
        c_compiled = convert_to_pdf(c_txt_path, output_path=c_pdf_dest)
        if c_compiled and c_compiled.exists():
            pdf_cover_path = str(c_compiled.relative_to(APP_DIR))
        else:
            pdf_cover_path = str(c_txt_path.relative_to(APP_DIR))

        c.execute(
            "UPDATE jobs SET cover_letter_path=?, cover_letter_at=?, cover_attempts=COALESCE(cover_attempts,0)+1 WHERE rowid=?",
            (pdf_cover_path, now, rowid)
        )
        conn.commit()
    except Exception as ce:
        log.warning("JIT Cover letter warning: %s", ce)

    # 3. Refresh Master CSV
    try:
        export_opportunities_csv()
    except Exception:
        pass

    return {
        "status": "ok",
        "job_title": job["title"],
        "company": job["site"],
        "tailored_resume_path": pdf_resume_path,
        "cover_letter_path": pdf_cover_path,
    }
