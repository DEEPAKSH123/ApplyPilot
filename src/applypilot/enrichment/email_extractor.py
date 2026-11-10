"""Email and contact extraction for recruiters, hiring managers, and direct referrals."""

import logging
import re
import sqlite3
from applypilot.database import get_connection

log = logging.getLogger(__name__)

# Strict regex for email extraction
EMAIL_REGEX = re.compile(r'\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b')

# Exclude false positives and system emails
IGNORED_DOMAINS = {
    "example.com", "w3.org", "schema.org", "sentry.io", "github.com",
    "git-scm.com", "google.com"  # e.g. fonts.google.com
}
IGNORED_PREFIXES = {
    "noreply", "no-reply", "donotreply", "support", "help", "info", "admin", "privacy", "legal"
}


def extract_emails_from_text(text: str | None) -> list[str]:
    """Extract valid recruiter or contact email addresses from a text block."""
    if not text:
        return []

    found = EMAIL_REGEX.findall(text)
    valid = []
    for e in found:
        e_clean = e.strip(".,;:()<>[]'\"").lower()
        if "@" not in e_clean:
            continue
        user, domain = e_clean.split("@", 1)
        if domain in IGNORED_DOMAINS or any(d in domain for d in ["sentry", "w3.org", "schema.org"]):
            continue
        if user in IGNORED_PREFIXES:
            continue
        # Dedupe keeping order
        if e_clean not in valid:
            valid.append(e_clean)

    return valid


def run_email_extraction(conn: sqlite3.Connection | None = None) -> int:
    """Scan all jobs in the database and populate recruiter_email."""
    if conn is None:
        conn = get_connection()

    c = conn.cursor()
    rows = c.execute("""
        SELECT url, description, full_description 
        FROM jobs 
        WHERE (recruiter_email IS NULL OR recruiter_email = '')
          AND (description IS NOT NULL OR full_description IS NOT NULL)
    """).fetchall()

    updated = 0
    for r in rows:
        url = r[0]
        desc = r[1] or ""
        full = r[2] or ""
        combined = f"{full}\n{desc}"

        emails = extract_emails_from_text(combined)
        if emails:
            email_str = ", ".join(emails[:3])
            c.execute("UPDATE jobs SET recruiter_email = ? WHERE url = ?", (email_str, url))
            updated += 1

    conn.commit()
    log.info("Extracted recruiter emails for %d jobs.", updated)
    return updated
