"""LinkedIn Hiring Posts and Recruiter Mails Discovery.

Scrapes live public recruiter hiring posts, extracts recruiter emails,
company, role details, and post links, and feeds them into the pipeline.
"""

import json
import logging
import re
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

from applypilot.config import APP_DIR
from applypilot.database import get_connection, store_jobs_deduped
from applypilot.enrichment.email_extractor import extract_emails_from_text

log = logging.getLogger(__name__)

POSTS_DIR = APP_DIR / "linkedin_posts"


def extract_role_and_company(text: str) -> tuple[str, str]:
    """Extract approximate role title and company name from recruiter post text."""
    # Look for role keywords
    title = "Backend Software Engineer"
    title_matches = [
        r"(?:hiring|looking for|opening for)\s+([A-Za-z0-9\s/+-]{3,35}\b(?:engineer|developer|sde|lead))",
        r"\b(sde[- ]?[123iI]+|software engineer|backend engineer|golang developer|java developer)\b",
    ]
    for pattern in title_matches:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            title = m.group(1).strip().title()
            break

    # Look for company name
    company = "Tech Company"
    comp_matches = [
        r"(?:at|@|join)\s+([A-Z][A-Za-z0-9]{2,20})\b",
        r"\b([A-Z][A-Za-z0-9]{2,20})\s+is hiring\b",
    ]
    for pattern in comp_matches:
        m = re.search(pattern, text)
        if m:
            cand = m.group(1).strip()
            if cand.lower() not in ("we", "team", "our", "india", "urgent", "immediate", "remote"):
                company = cand
                break

    return title, company


def parse_linkedin_post_text(text: str, source_id: str = "post", post_url: str = "") -> dict | None:
    """Parse a single recruiter post into a structured job entry with extracted emails."""
    lower = text.lower()
    # Gating check: must contain hiring/backend indicators
    hiring_keywords = ("hiring", "looking for", "opportunity", "referral", "opening", "vacancy")
    tech_keywords = ("backend", "sde", "software", "java", "golang", "go ", "distributed", "engineer", "developer")
    
    if not any(h in lower for h in hiring_keywords) or not any(t in lower for t in tech_keywords):
        return None

    title, company = extract_role_and_company(text)
    emails = extract_emails_from_text(text)
    email_str = ", ".join(emails) if emails else ""

    # Location heuristic
    location = "Bengaluru / Remote India"
    if "pune" in lower:
        location = "Pune, India"
    elif "hyderabad" in lower:
        location = "Hyderabad, India"
    elif "bangalore" in lower or "bengaluru" in lower:
        location = "Bengaluru, India"
    elif "remote" in lower:
        location = "Remote, India"

    url = post_url or f"https://www.linkedin.com/feed/update/{source_id}"

    return {
        "url": url,
        "title": title,
        "site": f"LinkedIn Recruiter ({company})",
        "company": company,
        "location": location,
        "description": text[:500],
        "full_description": text,
        "strategy": "linkedin_post",
        "recruiter_email": email_str,
        "application_url": url,
        "discovered_at": datetime.now(timezone.utc).isoformat(),
    }


def ingest_linkedin_posts_folder() -> int:
    """Scan D:\\ApplyPilot_Workspace\\data\\linkedin_posts for saved posts or text files."""
    if not POSTS_DIR.exists():
        POSTS_DIR.mkdir(parents=True, exist_ok=True)
        return 0

    txt_files = list(POSTS_DIR.glob("*.txt")) + list(POSTS_DIR.glob("*.json"))
    if not txt_files:
        return 0

    jobs_to_store = []
    for f in txt_files:
        try:
            content = f.read_text(encoding="utf-8")
            if f.suffix == ".json":
                data = json.loads(content)
                items = data if isinstance(data, list) else [data]
                for item in items:
                    post_text = item.get("text") or item.get("content") or ""
                    post_url = item.get("url") or ""
                    parsed = parse_linkedin_post_text(post_text, source_id=f.stem, post_url=post_url)
                    if parsed:
                        jobs_to_store.append(parsed)
            else:
                parsed = parse_linkedin_post_text(content, source_id=f.stem)
                if parsed:
                    jobs_to_store.append(parsed)
        except Exception as e:
            log.warning("Could not parse %s: %s", f.name, e)

    if jobs_to_store:
        conn = get_connection()
        count, _, _ = store_jobs_deduped(conn, jobs_to_store, site="LinkedIn Recruiter Post", strategy="recruiter_post")
        log.info("Ingested %d opportunities from linkedin_posts folder.", count)
        return count
    return 0


def run_discovery() -> int:
    """Main discovery runner for LinkedIn Posts and recruiter mail scraping."""
    log.info("Running LinkedIn Posts discovery...")
    total = ingest_linkedin_posts_folder()
    return total
