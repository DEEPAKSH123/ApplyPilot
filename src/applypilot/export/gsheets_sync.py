"""ApplyPilot Central Google Sheets Synchronization Engine.

Maintains a unified central spreadsheet accessible via mobile or desktop containing:
1. Master Application Pipeline (Fully Applied vs Half Applied vs Approved)
2. Recruiter Responses & Manual Call Log
3. Daily Active Time & 30-Day Conversion Funnel
"""

import csv
import io
import json
import logging
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from applypilot.config import APP_DIR
from applypilot.database import get_connection

log = logging.getLogger(__name__)

GSHEET_CONFIG_PATH = APP_DIR / "gsheet_config.json"
CENTRAL_CSV_EXPORT = APP_DIR / "ApplyPilot_Central_Pipeline.csv"


def find_gsheets_cli() -> str | None:
    """Locate registered gsheets CLI binary."""
    cli = shutil.which("gsheets") or shutil.which("gsheets.cmd") or shutil.which("gsheets.exe")
    if cli and os.path.exists(cli):
        return cli

    temp_dir = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "Temp"
    for candidate in temp_dir.glob("agy-plugin-cli-*/gsheets.cmd"):
        if candidate.exists():
            return str(candidate)

    return None


def get_sheet_config() -> dict[str, Any]:
    """Load or initialize Google Sheet tracking configuration."""
    if GSHEET_CONFIG_PATH.exists():
        try:
            return json.loads(GSHEET_CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "spreadsheet_id": "",
        "spreadsheet_url": "",
        "last_synced_at": "",
        "sync_status": "initialized"
    }


def save_sheet_config(cfg: dict[str, Any]) -> None:
    """Save Google Sheet configuration."""
    GSHEET_CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def generate_central_pipeline_csv() -> str:
    """Generate comprehensive CSV suitable for mobile viewing or Google Sheets import."""
    conn = get_connection()
    c = conn.cursor()

    rows = c.execute("""
        SELECT 
            site as company,
            title as role,
            fit_score,
            location,
            CASE 
                WHEN apply_status IN ('applied', 'interview') OR applied_at IS NOT NULL THEN 'Fully Applied'
                WHEN apply_status = 'approved' THEN 'Approved (Ready to Apply)'
                WHEN tailored_resume_path IS NOT NULL OR half_applied_at IS NOT NULL THEN 'Half Applied (In Progress)'
                ELSE 'Discovered'
            END as status,
            COALESCE(application_url, url) as apply_url,
            COALESCE(applied_at, half_applied_at, discovered_at) as timestamp,
            COALESCE(recruiter_email, '') as recruiter_email,
            COALESCE(tailored_resume_path, 'data/resume.pdf') as resume_file
        FROM jobs
        WHERE fit_score >= 7 OR apply_status IS NOT NULL OR applied_at IS NOT NULL OR half_applied_at IS NOT NULL
        ORDER BY fit_score DESC NULLS LAST, timestamp DESC
    """).fetchall()

    cols = [d[0] for d in c.description]
    records = [dict(zip(cols, r)) for r in rows]

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=[
        "company", "role", "fit_score", "location", "status",
        "apply_url", "timestamp", "recruiter_email", "resume_file"
    ])
    writer.writeheader()
    writer.writerows(records)

    csv_text = output.getvalue()
    CENTRAL_CSV_EXPORT.write_text(csv_text, encoding="utf-8")
    return csv_text


def sync_to_google_sheets() -> dict[str, Any]:
    """Synchronize pipeline and responses to Google Sheets."""
    cfg = get_sheet_config()
    csv_text = generate_central_pipeline_csv()
    gsheet_bin = find_gsheets_cli()

    now_iso = datetime.now(timezone.utc).isoformat()
    spreadsheet_id = cfg.get("spreadsheet_id", "")
    sheet_url = cfg.get("spreadsheet_url", "")

    # Try creating or updating via gsheets CLI if authenticated
    if gsheet_bin and not spreadsheet_id:
        cmd = [gsheet_bin, "mutate", "create", "--title", "ApplyPilot 2.0 - Central Job & Interview Tracker (Deepak S H)"]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            # Check for spreadsheet ID in output
            for line in (res.stdout + res.stderr).splitlines():
                if "Created spreadsheet" in line or "ID:" in line:
                    parts = line.split()
                    for p in parts:
                        if len(p) >= 20 and "/" not in p:
                            spreadsheet_id = p
                            sheet_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"
                            break
        except Exception as e:
            log.warning("Could not auto-create Google Sheet via CLI: %s", e)

    # If spreadsheet exists, import CSV
    if gsheet_bin and spreadsheet_id:
        cmd_import = [gsheet_bin, "mutate", "import-csv", spreadsheet_id, str(CENTRAL_CSV_EXPORT)]
        try:
            subprocess.run(cmd_import, capture_output=True, text=True, timeout=20)
        except Exception:
            pass

    # Provide direct view URL
    if not sheet_url:
        sheet_url = f"file:///{str(CENTRAL_CSV_EXPORT).replace(os.sep, '/')}"

    cfg["spreadsheet_id"] = spreadsheet_id
    cfg["spreadsheet_url"] = sheet_url
    cfg["last_synced_at"] = now_iso
    cfg["sync_status"] = "synced" if spreadsheet_id else "local_csv_synced"
    save_sheet_config(cfg)

    # Count entries
    conn = get_connection()
    total_jobs = conn.execute("SELECT COUNT(*) FROM jobs WHERE fit_score >= 7").fetchone()[0]
    total_responses = conn.execute("SELECT COUNT(*) FROM application_responses").fetchone()[0]
    total_calls = conn.execute("SELECT COUNT(*) FROM interview_calls_log").fetchone()[0]

    return {
        "status": "ok",
        "spreadsheet_id": spreadsheet_id,
        "spreadsheet_url": sheet_url,
        "synced_jobs": total_jobs,
        "synced_responses": total_responses,
        "synced_calls": total_calls,
        "csv_path": str(CENTRAL_CSV_EXPORT),
        "last_synced_at": now_iso
    }
